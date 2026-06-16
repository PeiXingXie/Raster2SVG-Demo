"""Supervisor implementations for the raster-to-SVG workflow."""

from __future__ import annotations

import json
from pathlib import Path
from threading import current_thread

from deepagents_template.bbox_overflow import summarize_bbox_batch_overflow
from deepagents_template.bbox_validation import validate_crop_local_bbox
from deepagents_template.checklist import (
    final_review_spatial_logical_issues,
    fusion_review_issue_id,
    flatten_checklists,
    select_checklist_payload_for_fusion,
    select_checklist_payload_for_region,
    select_checklist_for_region,
)
from deepagents_template.bbox_sanitization import sanitize_bbox_issues, truncate_text
from deepagents_template.geometry import compact_regions_for_prompt, crop_object_image, normalize_recognition_bboxes, normalize_regions
from deepagents_template.policy import BboxPolicyEngine, FusionPolicyEngine, ObjectPolicyEngine, RegionPolicyEngine
from deepagents_template.recognition_grouping import group_oversegmented_recognition
from deepagents_template.schemas import (
    BboxAdjustmentResult,
    BboxSupervisorMemory,
    FinalReviewResult,
    FusionSupervisorMemory,
    LayoutDetectionResult,
    LayoutSupervisorMemory,
    ObjectRepairSupervisorMemory,
    ObjectCandidate,
    RegionRecognitionResult,
    RegionRepairResult,
    RegionReviewResult,
    RegionSupervisorMemory,
    SupervisorIssueMemory,
)
from deepagents_template.svg_utils import extract_group_template
from deepagents_template.svg_bbox_validation import build_region_bbox_review_feedback
from deepagents_template.utils.planning import summarize_conversion_requirements
from deepagents_template.utils.bbox_visualization import render_bbox_overlay
from deepagents_template.utils.context_payloads import (
    build_bbox_feedback_payload,
    build_fusion_previous_decision_delta,
    build_object_index_payload,
    build_object_policy_payload,
    build_object_previous_decision_delta,
    build_region_previous_decision_delta,
)
from deepagents_template.utils.svg_runtime import (
    aggregate_region_object_svg,
    finalize_region_svg,
    persist_merged_svg,
)
from deepagents_template.utils.svg_templates import build_svg_template
from deepagents_template.utils.tasks import create_object_task, create_region_task

from .base import BaseWorkflowAgent
from .workers import (
    BboxAdjustmentWorkerAgent,
    BboxCombinedPolicyModelWorker,
    ChecklistPlanningWorkerAgent,
    FusionCombinedPolicyModelWorker,
    IntegratedSvgRepairWorkerAgent,
    LayoutDetectionWorkerAgent,
    ObjectCombinedPolicyModelWorker,
    ObjectSvgWorkerAgent,
    RegionCombinedPolicyModelWorker,
    RegionRecognitionWorkerAgent,
    RegionSvgWorkerAgent,
)


class BboxAdjustmentSupervisorAgent(BaseWorkflowAgent):
    """Supervisor loop for bbox proposal, candidate execution, and policy judgement."""

    def __init__(self, pipeline) -> None:
        super().__init__(pipeline)
        self.worker = BboxAdjustmentWorkerAgent(pipeline)
        self.combined_policy_worker = BboxCombinedPolicyModelWorker(pipeline)
        self.policy = BboxPolicyEngine(pipeline, combined_worker=self.combined_policy_worker)
        self._memories: dict[str, BboxSupervisorMemory] = {}

    @staticmethod
    def _truncate_text(text: str, *, max_words: int, max_chars: int) -> str:
        return truncate_text(text, max_words=max_words, max_chars=max_chars)

    def _sanitize_result(self, result: BboxAdjustmentResult) -> BboxAdjustmentResult:
        return result.model_copy(
            update={
                "overview": self._truncate_text(result.overview, max_words=28, max_chars=180),
                "issues": self._sanitize_bbox_issues(
                    result.issues,
                    scope=result.scope,
                    region_id=result.region_id or None,
                ),
                "strategy_label": self._truncate_text(result.strategy_label or "", max_words=8, max_chars=64) or None,
                "strategy_rationale": self._truncate_text(result.strategy_rationale or "", max_words=24, max_chars=160) or None,
                "changes_applied": self._sanitize_changes(result.changes_applied),
                "target_ids": result.target_ids[:6],
            }
        )

    def _sanitize_bbox_issues(
        self,
        issues: list,
        *,
        scope: str,
        region_id: str | None = None,
    ) -> list:
        push_event = getattr(self.pipeline, "_push_event", None)
        return sanitize_bbox_issues(
            issues,
            scope=scope,
            region_id=region_id,
            push_event=push_event,
        )

    def _sanitize_changes(self, changes: list[str]) -> list[str]:
        deduped_changes: list[str] = []
        seen_changes: set[str] = set()
        for item in changes[:6]:
            cleaned = self._truncate_text(item, max_words=16, max_chars=96)
            if not cleaned or cleaned in seen_changes:
                continue
            seen_changes.add(cleaned)
            deduped_changes.append(cleaned)
        return deduped_changes

    def _memory_for(self, scope_key: str, scope: str) -> BboxSupervisorMemory:
        memory = self._memories.get(scope_key)
        if memory is None:
            memory = BboxSupervisorMemory(scope_key=scope_key, scope=scope)
            self._memories[scope_key] = memory
        return memory

    def _render_layout_overlay(self, copied_input_path: Path, regions: list[dict], output_path: Path) -> None:
        render_bbox_overlay(
            image_path=copied_input_path,
            boxes=[{"id": region["region_id"], "label": region["region_id"], "bbox": region["bbox"]} for region in regions],
            output_path=output_path,
        )

    def _render_recognition_overlay(self, crop_path: Path, recognition: RegionRecognitionResult, output_path: Path) -> None:
        render_bbox_overlay(
            image_path=crop_path,
            boxes=[
                {
                    "id": obj.object_id,
                    "label": obj.object_id,
                    "bbox": obj.bbox.model_dump(mode="json") if obj.bbox else {"x": 0, "y": 0, "width": 1, "height": 1},
                }
                for obj in recognition.recognized_objects
                if obj.bbox is not None
            ],
            output_path=output_path,
        )

    def _collect_recognition_validation_feedback(
        self,
        *,
        crop_path: Path,
        recognition: RegionRecognitionResult,
        target_ids: set[str] | None = None,
    ) -> list[dict]:
        feedback_items = []
        for obj in recognition.recognized_objects:
            if obj.bbox is None:
                continue
            if target_ids and obj.object_id not in target_ids:
                continue
            feedback_items.append(
                validate_crop_local_bbox(
                    crop_path=crop_path,
                    target_id=obj.object_id,
                    bbox=obj.bbox.model_dump(mode="json"),
                )
            )
        return build_bbox_feedback_payload(feedback_items)

    def _apply_recognition_updates(
        self,
        *,
        recognition: RegionRecognitionResult,
        updates: list,
    ) -> RegionRecognitionResult:
        if not updates:
            return recognition
        update_by_id = {item.target_id: item.bbox for item in updates}
        adjusted_objects = []
        for obj in recognition.recognized_objects:
            replacement_bbox = update_by_id.get(obj.object_id)
            adjusted_objects.append(
                obj.model_copy(update={"bbox": replacement_bbox}) if replacement_bbox is not None else obj
            )
        return recognition.model_copy(update={"recognized_objects": adjusted_objects})

    def _persist_bbox_trace(self, path: Path, payload: dict) -> None:
        self.pipeline._write_json(path, payload)

    def _warn_bbox_batch_overflow(self, *, region_id: str, iteration: int, overflow_summary: dict) -> None:
        push_event = getattr(self.pipeline, "_push_event", None)
        if not callable(push_event):
            return
        push_event(
            "region-process",
            f"Bbox refine batch overflow for {region_id}",
            (
                "Recognition bbox refine returned more objects than the current batch budget allows; "
                "kept the highest-priority prefix and recorded dropped targets in trace."
            ),
            payload={
                "region_id": region_id,
                "iteration": iteration,
                "budget_limits": {
                    "target_ids": 6,
                    "adjusted_object_bboxes": 12,
                    "changes_applied": 4,
                },
                "batch_overflow": overflow_summary,
            },
            status="running",
            level="warning",
        )

    @staticmethod
    def _candidate_changed(current_payload: list[dict], candidate_payload: list[dict]) -> bool:
        return current_payload != candidate_payload

    def _decision_review_as_result(
        self,
        *,
        base_result: BboxAdjustmentResult,
        policy_review,
    ) -> BboxAdjustmentResult:
        return base_result.model_copy(
            update={
                "overview": policy_review.overview,
                "issues": policy_review.issues,
                "needs_adjustment": policy_review.needs_adjustment,
            }
        )

    def review_layout(
        self,
        *,
        copied_input_path: Path,
        width: int,
        height: int,
        regions: list[dict],
    ) -> tuple[list[dict], BboxAdjustmentResult]:
        scope_key = "layout"
        memory = self._memory_for(scope_key, "layout")
        retry_task = "bbox:layout:repair"
        current_regions = regions
        latest_result = BboxAdjustmentResult(scope="layout", overview="", issues=[], needs_adjustment=False)
        iteration = 0
        while True:
            overlay_path = self.pipeline.root_intermediate_dir / f"layout_bbox_overlay_iter_{iteration}.png"
            self._render_layout_overlay(copied_input_path, current_regions, overlay_path)
            retry_state = self.pipeline._retry_state(retry_task)
            result, raw = self.worker.run_layout(
                copied_input_path=copied_input_path,
                overlay_path=overlay_path,
                width=width,
                height=height,
                regions=current_regions,
                memory_summary=(
                    {
                        "iteration": memory.iteration,
                        "attempted_adjustment_types": memory.attempted_adjustment_types[-4:],
                        "accepted_changes": memory.accepted_changes[-4:],
                        "rejected_changes": memory.rejected_changes[-4:],
                    }
                    if self.use_supervisor_memory
                    else None
                ),
                retry_state=retry_state,
            )
            result = self._sanitize_result(result)
            latest_result = result
            self.pipeline._write_text(
                self.pipeline.root_intermediate_dir / f"layout_bbox_adjustment_iter_{iteration}_raw.txt",
                raw,
            )
            self._persist_bbox_trace(
                self.pipeline.root_intermediate_dir / f"layout_bbox_adjustment_iter_{iteration}.json",
                result.model_dump(mode="json"),
            )
            memory.iteration += 1
            memory.attempted_adjustment_types.append(result.adjustment_type)
            memory.issue_history.extend(
                [
                    SupervisorIssueMemory(
                        issue_id=f"layout:{issue.target_id}:{issue.criterion}",
                        scope="layout",
                        target_id=issue.target_id,
                        criterion=issue.criterion,
                        reason=issue.reason,
                        status="unresolved",
                        source_iteration=str(iteration),
                    )
                    for issue in result.issues
                ]
            )
            candidate_regions = (
                normalize_regions(result.adjusted_regions, width=width, height=height)
                if result.adjusted_regions and result.needs_adjustment
                else current_regions
            )
            candidate_changed = self._candidate_changed(current_regions, candidate_regions)
            candidate_overlay_path = self.pipeline.root_intermediate_dir / f"layout_bbox_candidate_overlay_iter_{iteration}.png"
            self._render_layout_overlay(copied_input_path, candidate_regions, candidate_overlay_path)
            decision = self.policy.evaluate(
                scope="layout",
                proposal=result,
                memory=memory,
                retry_exhausted=self.pipeline._retry_exhausted(retry_task),
                iteration=str(iteration),
                copied_input_path=copied_input_path,
                current_overlay_path=overlay_path,
                candidate_overlay_path=candidate_overlay_path,
                width=width,
                height=height,
                current_regions=current_regions,
                candidate_regions=candidate_regions,
                retry_state=self.pipeline._retry_state(retry_task),
                candidate_changed=candidate_changed,
            )
            memory.decision_notes.append(
                self._decision(
                    iteration=str(iteration),
                    actor="bbox-policy",
                    action=(
                        "layout-continue"
                        if decision.continue_refinement
                        else ("layout-accept" if decision.accept_current_result else "layout-stop")
                    ),
                    rationale=decision.final_reason,
                    related_issues=[item.issue_id for item in memory.issue_history[-4:]],
                )
            )
            candidate_review_result = self._decision_review_as_result(base_result=result, policy_review=decision.review)
            if decision.accept_current_result and candidate_changed:
                current_regions = candidate_regions
                latest_result = candidate_review_result
                memory.accepted_changes.extend(result.changes_applied[:2])
            elif decision.accept_current_result:
                latest_result = candidate_review_result
            elif result.changes_applied:
                memory.rejected_changes.extend(result.changes_applied[:2])
            if decision.continue_refinement:
                if self.pipeline._begin_retry(retry_task):
                    iteration += 1
                    continue
                memory.stop_reason = "bbox retry budget exhausted after policy requested continuation"
                break
            memory.stop_reason = decision.final_reason or (
                "bbox policy accepted current state" if decision.accept_current_result else "bbox policy stopped further retries"
            )
            break
        self.pipeline._write_json(self.pipeline.root_intermediate_dir / "layout_bbox_adjustment.json", latest_result.model_dump(mode="json"))
        self.pipeline._push_event(
            "layout detection",
            "Completed bbox supervisor loop for layout",
            f"bbox loop finished after {memory.iteration} iteration(s) with {len(latest_result.issues)} residual issue(s).",
            payload={
                "issues": [item.model_dump(mode="json") for item in latest_result.issues],
                "changes_applied": latest_result.changes_applied,
                "stop_reason": memory.stop_reason,
            },
            status="running",
        )
        self._persist_memory(self.pipeline.root_intermediate_dir / "layout_bbox_supervisor_memory.json", memory)
        return current_regions, latest_result

    def review_recognition(
        self,
        *,
        crop_path: Path,
        region: dict,
        recognition: RegionRecognitionResult,
        region_dir: Path,
    ) -> tuple[RegionRecognitionResult, BboxAdjustmentResult]:
        scope_key = f"recognition:{region['region_id']}"
        memory = self._memory_for(scope_key, "recognition")
        retry_task = f"bbox:region:{region['region_id']}:repair"
        current_recognition = recognition
        latest_result = BboxAdjustmentResult(scope="recognition", region_id=region["region_id"], overview="", issues=[], needs_adjustment=False)
        iteration = 0
        while True:
            overlay_path = region_dir / f"recognition_bbox_overlay_iter_{iteration}.png"
            self._render_recognition_overlay(crop_path, current_recognition, overlay_path)
            retry_state = self.pipeline._retry_state(retry_task)
            current_objects = [
                {
                    "object_id": obj.object_id,
                    "description": obj.description,
                    "generation_focus": obj.generation_focus,
                    "bbox": obj.bbox.model_dump(mode="json") if obj.bbox else None,
                }
                for obj in current_recognition.recognized_objects
            ]
            current_validation_feedback = self._collect_recognition_validation_feedback(
                crop_path=crop_path,
                recognition=current_recognition,
            )
            result, raw = self.worker.run_recognition(
                crop_path=crop_path,
                overlay_path=overlay_path,
                region=region,
                recognized_objects=current_objects,
                validation_feedback=current_validation_feedback,
                memory_summary=(
                    {
                        "iteration": memory.iteration,
                        "attempted_adjustment_types": memory.attempted_adjustment_types[-4:],
                        "accepted_changes": memory.accepted_changes[-4:],
                        "rejected_changes": memory.rejected_changes[-4:],
                    }
                    if self.use_supervisor_memory
                    else None
                ),
                retry_state=retry_state,
            )
            result = self._sanitize_result(result)
            raw_payload = None
            try:
                raw_payload = json.loads(raw)
            except Exception:
                raw_payload = None
            overflow_summary = summarize_bbox_batch_overflow(
                raw_payload=raw_payload,
                target_id_limit=6,
                object_update_limit=12,
                changes_limit=4,
            )
            latest_result = result
            self.pipeline._write_text(region_dir / f"recognition_bbox_adjustment_iter_{iteration}_raw.txt", raw)
            self._persist_bbox_trace(
                region_dir / f"recognition_bbox_adjustment_iter_{iteration}.json",
                {
                    **result.model_dump(mode="json"),
                    "batch_overflow": overflow_summary,
                },
            )
            if overflow_summary.get("has_overflow"):
                self._warn_bbox_batch_overflow(
                    region_id=region["region_id"],
                    iteration=iteration,
                    overflow_summary=overflow_summary,
                )
            memory.iteration += 1
            memory.attempted_adjustment_types.append(result.adjustment_type)
            memory.issue_history.extend(
                [
                    SupervisorIssueMemory(
                        issue_id=f"bbox:{region['region_id']}:{issue.target_id}:{issue.criterion}",
                        scope="object",
                        target_id=issue.target_id,
                        criterion=issue.criterion,
                        reason=issue.reason,
                        status="unresolved",
                        source_iteration=str(iteration),
                    )
                    for issue in result.issues
                ]
            )
            candidate_recognition = self._apply_recognition_updates(
                recognition=current_recognition,
                updates=result.adjusted_object_bboxes if result.needs_adjustment else [],
            )
            candidate_objects = [
                {
                    "object_id": obj.object_id,
                    "description": obj.description,
                    "generation_focus": obj.generation_focus,
                    "bbox": obj.bbox.model_dump(mode="json") if obj.bbox else None,
                }
                for obj in candidate_recognition.recognized_objects
            ]
            candidate_changed = self._candidate_changed(current_objects, candidate_objects)
            candidate_overlay_path = region_dir / f"recognition_bbox_candidate_overlay_iter_{iteration}.png"
            self._render_recognition_overlay(crop_path, candidate_recognition, candidate_overlay_path)
            candidate_validation_feedback = self._collect_recognition_validation_feedback(
                crop_path=crop_path,
                recognition=candidate_recognition,
                target_ids={item for item in result.target_ids if item} or None,
            )
            decision = self.policy.evaluate(
                scope="recognition",
                proposal=result,
                memory=memory,
                retry_exhausted=self.pipeline._retry_exhausted(retry_task),
                iteration=str(iteration),
                crop_path=crop_path,
                current_overlay_path=overlay_path,
                candidate_overlay_path=candidate_overlay_path,
                region=region,
                current_objects=current_objects,
                candidate_objects=candidate_objects,
                validation_feedback=candidate_validation_feedback,
                retry_state=self.pipeline._retry_state(retry_task),
                candidate_changed=candidate_changed,
                region_dir=region_dir,
            )
            memory.decision_notes.append(
                self._decision(
                    iteration=str(iteration),
                    actor="bbox-policy",
                    action=(
                        "recognition-continue"
                        if decision.continue_refinement
                        else ("recognition-accept" if decision.accept_current_result else "recognition-stop")
                    ),
                    rationale=decision.final_reason,
                    related_issues=[item.issue_id for item in memory.issue_history[-4:]],
                )
            )
            candidate_review_result = self._decision_review_as_result(base_result=result, policy_review=decision.review)
            if decision.accept_current_result and candidate_changed:
                current_recognition = candidate_recognition
                latest_result = candidate_review_result
                memory.accepted_changes.extend(result.changes_applied[:2])
            elif decision.accept_current_result:
                latest_result = candidate_review_result
            elif result.changes_applied:
                memory.rejected_changes.extend(result.changes_applied[:2])
            if decision.continue_refinement:
                if self.pipeline._begin_retry(retry_task):
                    iteration += 1
                    continue
                memory.stop_reason = "bbox retry budget exhausted after policy requested continuation"
                break
            memory.stop_reason = decision.final_reason or (
                "bbox policy accepted current state" if decision.accept_current_result else "bbox policy stopped further retries"
            )
            break
        self.pipeline._write_json(region_dir / "recognition_bbox_adjustment.json", latest_result.model_dump(mode="json"))
        self.pipeline._write_json(
            region_dir / "recognition_bbox_summary.json",
            {
                "issues": [item.model_dump(mode="json") for item in latest_result.issues],
                "changes_applied": latest_result.changes_applied,
                "needs_adjustment": latest_result.needs_adjustment,
                "stop_reason": memory.stop_reason,
                "policy_action": memory.decision_notes[-1].action if memory.decision_notes else "",
                "validation_feedback": candidate_validation_feedback if 'candidate_validation_feedback' in locals() else [],
                "batch_overflow": overflow_summary if 'overflow_summary' in locals() else {"has_overflow": False},
            },
        )
        self.pipeline._push_event(
            "region-process",
            f"Completed bbox supervisor loop for {region['region_id']}",
            f"bbox loop finished after {memory.iteration} iteration(s) with {len(latest_result.issues)} residual issue(s).",
            payload={
                "region_id": region["region_id"],
                "issues": [item.model_dump(mode="json") for item in latest_result.issues],
                "changes_applied": latest_result.changes_applied,
                "stop_reason": memory.stop_reason,
            },
            status="running",
        )
        self._persist_memory(region_dir / "recognition_bbox_supervisor_memory.json", memory)
        return current_recognition, latest_result


class LayoutPlanningSupervisorAgent(BaseWorkflowAgent):
    """Supervisor agent that owns the layout-planning workflow node goal."""

    def __init__(self, pipeline) -> None:
        super().__init__(pipeline)
        self.layout_worker = LayoutDetectionWorkerAgent(pipeline)
        self.checklist_worker = ChecklistPlanningWorkerAgent(pipeline)

    def execute(
        self,
        *,
        copied_input_path: Path,
        width: int,
        height: int,
    ) -> tuple[LayoutDetectionResult, str, dict, list[dict], str]:
        memory = LayoutSupervisorMemory(
            canvas_width=width,
            canvas_height=height,
            goals=[
                "Produce a weak-but-complete region split.",
                "Generate an image-aware acceptance checklist.",
                "Prepare a mergeable SVG template for downstream region workers.",
            ],
        )
        layout_result, layout_raw = self.layout_worker.run(
            copied_input_path=copied_input_path,
            width=width,
            height=height,
        )
        self.pipeline._write_text(self.pipeline.root_intermediate_dir / "layout_detection_raw.txt", layout_raw)
        self.pipeline._write_json(
            self.pipeline.root_intermediate_dir / "layout_detection.json",
            {
                "canvas_width": layout_result.canvas_width,
                "canvas_height": layout_result.canvas_height,
                "overview": layout_result.overview,
                "regions": compact_regions_for_prompt(
                    [region.model_dump(mode="json") for region in layout_result.regions]
                ),
            },
        )
        self.pipeline._set_overview(
            {
                "layout_overview": layout_result.overview,
                "complexity_assessment": layout_result.complexity_assessment,
                "regions_total": len(layout_result.regions),
                "layout_agent_mode": "supervisor_worker",
            }
        )
        regions = normalize_regions(layout_result.regions, width=width, height=height)
        if hasattr(self.pipeline, "workflow_agents"):
            regions, bbox_result = self.pipeline.workflow_agents.bbox.review_layout(
                copied_input_path=copied_input_path,
                width=width,
                height=height,
                regions=regions,
            )
        else:
            bbox_result = BboxAdjustmentResult(scope="layout", overview="", issues=[], needs_adjustment=False)
        requirement_summary = summarize_conversion_requirements(self.pipeline.user_message)
        checklist = self.checklist_worker.run(
            copied_input_path=copied_input_path,
            layout_overview=layout_result.overview,
            regions=regions,
        )
        svg_template = build_svg_template(width, height, json.dumps(regions, ensure_ascii=False))
        self.pipeline._write_json(
            self.pipeline.root_intermediate_dir / "requirement_summary.json",
            requirement_summary,
        )
        self.pipeline._write_json(self.pipeline.root_intermediate_dir / "checklist.json", checklist)
        self.pipeline._write_json(self.pipeline.root_intermediate_dir / "regions.json", regions)
        self.pipeline._write_text(self.pipeline.root_intermediate_dir / "template.svg", svg_template)
        memory.layout_overview = layout_result.overview
        memory.complexity_assessment = dict(layout_result.complexity_assessment)
        memory.region_ids = [region["region_id"] for region in regions]
        memory.assumptions = requirement_summary.get("priorities", [])[:3]
        memory.checklist_summary = [item.get("criterion", "") for item in flatten_checklists(checklist)[:8]]
        memory.decisions.append(
            self._decision(
                iteration="0",
                actor="layout-supervisor",
                action="finalize-layout-plan",
                rationale=(
                    f"Planned {len(regions)} regions and {len(flatten_checklists(checklist))} checklist items "
                    f"after bbox review with {len(bbox_result.issues)} issue(s)."
                ),
            )
        )
        memory.stop_reason = "layout, checklist, and template prepared"
        self._persist_memory(self.pipeline.root_intermediate_dir / "layout_supervisor_memory.json", memory)
        return layout_result, layout_raw, checklist, regions, svg_template


class ObjectRepairSupervisorAgent(BaseWorkflowAgent):
    """Supervisor that coordinates object-scoped repair workers for one region."""

    def __init__(self, pipeline) -> None:
        super().__init__(pipeline)
        self.svg_worker = ObjectSvgWorkerAgent(pipeline)
        self.combined_policy_worker = ObjectCombinedPolicyModelWorker(pipeline)
        self.policy = ObjectPolicyEngine(pipeline, combined_worker=self.combined_policy_worker)
        self._memories: dict[str, ObjectRepairSupervisorMemory] = {}

    def _memory_for_region(self, region_id: str) -> ObjectRepairSupervisorMemory:
        memory = self._memories.get(region_id)
        if memory is None:
            memory = ObjectRepairSupervisorMemory(region_id=region_id)
            self._memories[region_id] = memory
        return memory

    def _persist_region_memory(self, region_dir: Path, memory: ObjectRepairSupervisorMemory) -> None:
        self._persist_memory(region_dir / "objects" / "supervisor_memory.json", memory)

    def repair(
        self,
        *,
        crop_path: Path,
        region: dict,
        checklist: dict,
        region_dir: Path,
        recognition: RegionRecognitionResult,
        object_svg_index: dict[str, str],
        object_issues: list,
    ) -> tuple[dict[str, str], list[dict]]:
        memory = self._memory_for_region(region["region_id"])
        objects_by_id = {obj.object_id: obj for obj in recognition.recognized_objects}
        objects_dir = region_dir / "objects"
        objects_dir.mkdir(parents=True, exist_ok=True)
        history: list[dict] = []
        memory.object_ids = sorted({*memory.object_ids, *objects_by_id.keys()})

        for issue in object_issues:
            obj = objects_by_id.get(issue.object_id)
            if obj is None:
                continue
            retry_task = self.pipeline._object_retry_task_name(region["region_id"], issue.object_id)
            current_object_svg = object_svg_index.get(obj.object_id, "")
            object_dir = objects_dir / obj.object_id
            object_dir.mkdir(parents=True, exist_ok=True)
            object_crop_path = crop_object_image(region_crop_path=crop_path, obj=obj, object_dir=object_dir)
            if not self.pipeline._begin_retry(retry_task):
                memory.object_attempts[obj.object_id] = memory.object_attempts.get(obj.object_id, 0)
                memory.object_last_failure[obj.object_id] = "retry exhausted before new attempt"
                memory.unresolved_objects = sorted(set(memory.unresolved_objects + [obj.object_id]))
                history.append({"object_id": issue.object_id, "retry_task": retry_task, "skipped": True, "retry": self.pipeline._retry_state(retry_task), "final_svg_elements": current_object_svg})
                continue

            failed_items = [{"criterion": issue.criterion, "reason": issue.reason}]
            object_task = create_object_task(
                object_id=obj.object_id,
                object_type=obj.object_type,
                description=obj.description,
                generation_focus=obj.generation_focus,
                region_id=region["region_id"],
                bbox=obj.bbox.model_dump(mode="json") if obj.bbox else None,
                current_svg=current_object_svg,
                failed_items=failed_items,
            )
            self.pipeline._write_json(object_dir / "object_task.json", object_task)
            memory.object_attempts[obj.object_id] = memory.object_attempts.get(obj.object_id, 0) + 1
            iterations: list[dict] = []
            previous_review = None
            previous_strategy_label: str | None = None
            object_iteration = 0
            obj_payload = build_object_policy_payload(obj)
            while True:
                policy_dir = object_dir / "policy"
                svg_file_name = f"object-{obj.object_id}-policy-{object_iteration}.svg"
                _, rendered_svg_path = self._write_object_review_assets(
                    region=region,
                    obj=obj_payload,
                    svg_fragment=current_object_svg,
                    svg_path=policy_dir / svg_file_name,
                    png_path=policy_dir / f"object-{obj.object_id}-policy-{object_iteration}.png",
                )
                decision = self.policy.evaluate(
                    object_crop_path=object_crop_path,
                    object_dir=object_dir,
                    obj=obj_payload,
                    review_context={
                        "failed_items": failed_items,
                        "previous_decision_delta": (
                            build_object_previous_decision_delta(
                                previous_review,
                                strategy=previous_strategy_label,
                            )
                            if self.use_supervisor_memory and previous_review is not None
                            else None
                        ),
                        "svg_file_name": svg_file_name,
                    },
                    memory=memory,
                    retry_exhausted=getattr(self.pipeline, "_retry_exhausted", lambda *_args, **_kwargs: False)(retry_task),
                    iteration=str(object_iteration),
                    rendered_svg_path=rendered_svg_path,
                    svg_file_path=policy_dir / svg_file_name,
                )
                review = decision.review
                self.pipeline._write_json(object_dir / f"object_review_iter_{object_iteration}.json", review.model_dump(mode="json"))
                failed_items = [entry.model_dump(mode="json") for entry in review.failed_items]
                if decision.accept_current_result or not decision.continue_refinement:
                    break
                if object_iteration > 0 and not self.pipeline._begin_retry(retry_task):
                    break
                strategy_hint = None
                if decision.strategy_enabled and decision.final_strategy_label:
                    strategy_hint = {
                        "label": decision.final_strategy_label,
                        "desired_outcome": decision.final_strategy_rationale or "",
                    }
                generation, generation_raw = self.svg_worker.run(
                    object_crop_path=object_crop_path,
                    obj=obj,
                    current_svg=current_object_svg,
                    current_svg_file_path=self._write_svg_prompt_attachment(
                        svg_text=current_object_svg,
                        svg_path=object_dir / "inputs" / f"object-{obj.object_id}-current.svg",
                    ),
                    failed_items=failed_items,
                    strategy_hint=strategy_hint,
                )
                current_object_svg = generation.svg_elements
                iterations.append(
                    {
                        "iteration": object_iteration,
                        "retry": self.pipeline._retry_state(retry_task),
                        "generation": generation.model_dump(mode="json"),
                        "decision": decision.model_dump(mode="json"),
                    }
                )
                previous_review = review
                previous_strategy_label = decision.final_strategy_label
                if decision.strategy_enabled and decision.final_strategy_label:
                    memory.routing_notes.append(
                        self._decision(
                            iteration=str(object_iteration),
                            actor="object-supervisor",
                            action="apply-object-strategy",
                            rationale=f"{decision.final_strategy_label}: {decision.final_strategy_rationale or ''}",
                            related_issues=[obj.object_id],
                        )
                    )
                object_iteration += 1

            final_svg_file_name = f"object-{obj.object_id}-policy-final.svg"
            _, final_rendered_svg_path = self._write_object_review_assets(
                region=region,
                obj=obj_payload,
                svg_fragment=current_object_svg,
                svg_path=(object_dir / "policy" / final_svg_file_name),
                png_path=(object_dir / "policy" / f"object-{obj.object_id}-policy-final.png"),
            )
            final_decision = self.policy.evaluate(
                object_crop_path=object_crop_path,
                object_dir=object_dir,
                obj=obj_payload,
                review_context={
                    "failed_items": [entry.model_dump(mode="json") for entry in review.failed_items],
                    "previous_decision_delta": (
                        build_object_previous_decision_delta(
                            previous_review,
                            strategy=previous_strategy_label,
                        )
                        if self.use_supervisor_memory and previous_review is not None
                        else None
                    ),
                    "svg_file_name": final_svg_file_name,
                },
                memory=memory,
                retry_exhausted=getattr(self.pipeline, "_retry_exhausted", lambda *_args, **_kwargs: False)(retry_task),
                iteration="final",
                rendered_svg_path=final_rendered_svg_path,
                svg_file_path=object_dir / "policy" / final_svg_file_name,
            )
            review = final_decision.review
            memory.issue_history.extend(
                [
                    SupervisorIssueMemory(
                        issue_id=f"object:{review.object_id}:{item.criterion}",
                        scope="object",
                        target_id=review.object_id,
                        criterion=item.criterion,
                        reason=item.reason,
                        status="unresolved",
                        source_iteration="final",
                    )
                    for item in review.failed_items
                ]
            )

            record = {
                "object_id": obj.object_id,
                "retry_task": retry_task,
                "issue": issue.model_dump(mode="json"),
                "iterations": iterations,
                "retry": self.pipeline._retry_state(retry_task),
                "final_svg_elements": current_object_svg,
                "final_decision": final_decision.model_dump(mode="json"),
            }
            self.pipeline._write_json(object_dir / "object_history.json", record)
            self.pipeline._write_text(object_dir / "final_object_elements.svgfrag", current_object_svg)
            object_svg_index[obj.object_id] = current_object_svg
            if review.failed_items:
                memory.object_last_failure[obj.object_id] = review.failed_items[0].reason
                memory.unresolved_objects = sorted(set(memory.unresolved_objects + [obj.object_id]))
            else:
                memory.resolved_objects = sorted(set(memory.resolved_objects + [obj.object_id]))
                memory.unresolved_objects = [item for item in memory.unresolved_objects if item != obj.object_id]
            history.append(record)
            self._persist_region_memory(region_dir, memory)
        memory.issue_history = self._dedupe_issue_list(memory.issue_history)
        memory.stop_reason = "object repair round completed"
        self._persist_region_memory(region_dir, memory)
        return object_svg_index, history


class RegionSupervisorAgent(BaseWorkflowAgent):
    """Supervisor that owns the region node task goal and delegates to region/object workers."""

    def __init__(self, pipeline) -> None:
        super().__init__(pipeline)
        self.recognition_worker = RegionRecognitionWorkerAgent(pipeline)
        self.svg_worker = RegionSvgWorkerAgent(pipeline)
        self.combined_policy_worker = RegionCombinedPolicyModelWorker(pipeline)
        self.object_supervisor = ObjectRepairSupervisorAgent(pipeline)
        self.policy = RegionPolicyEngine(
            pipeline,
            combined_worker=self.combined_policy_worker,
        )
        self._memories: dict[str, RegionSupervisorMemory] = {}

    def _memory_for_region(self, region: dict, checklist: dict) -> RegionSupervisorMemory:
        region_id = region["region_id"]
        memory = self._memories.get(region_id)
        if memory is None:
            memory = RegionSupervisorMemory(
                region_id=region_id,
                goals=select_checklist_for_region(checklist, region_id, stage="generation_refine")[:8],
                accepted_constraints=[
                    "Preserve mergeability into the global SVG template.",
                    "Avoid re-breaking issues already resolved in earlier review rounds.",
                ],
            )
            self._memories[region_id] = memory
        return memory

    def _persist_region_memory(self, region_dir: Path, memory: RegionSupervisorMemory) -> None:
        self._persist_memory(region_dir / "supervisor_memory.json", memory)

    def _warn_unscoped_visuals(
        self,
        *,
        region: dict,
        phase: str,
        unscoped_visuals: list[dict[str, str]],
    ) -> None:
        if not unscoped_visuals:
            return
        sample = ", ".join(
            item["tag"] + (f"#{item['id']}" if item.get("id") else "")
            for item in unscoped_visuals[:5]
        )
        self.pipeline._push_event(
            "region-process",
            f"Unscoped visual elements detected in {region['region_id']}",
            (
                f"{len(unscoped_visuals)} visible SVG element(s) are outside object groups during {phase}. "
                f"Sample: {sample or 'n/a'}."
            ),
            payload={
                "region_id": region["region_id"],
                "phase": phase,
                "unscoped_visual_count": len(unscoped_visuals),
                "unscoped_visuals": unscoped_visuals[:10],
            },
            status="running",
            level="warning",
        )

    def _review_to_issue_memory(
        self,
        *,
        region_id: str,
        review: RegionReviewResult,
        iteration: str,
    ) -> list[SupervisorIssueMemory]:
        items: list[SupervisorIssueMemory] = []
        for issue in review.global_repairs:
            items.append(
                SupervisorIssueMemory(
                    issue_id=f"region:{region_id}:{issue.criterion}",
                    scope="region",
                    target_id=region_id,
                    criterion=issue.criterion,
                    reason=issue.reason,
                    status="unresolved",
                    source_iteration=iteration,
                )
            )
        for issue in review.object_issues:
            items.append(
                SupervisorIssueMemory(
                    issue_id=f"object:{region_id}:{issue.object_id}:{issue.criterion}",
                    scope="object",
                    target_id=issue.object_id,
                    criterion=issue.criterion,
                    reason=issue.reason,
                    status="unresolved",
                    source_iteration=iteration,
                )
            )
        return items

    def _update_region_memory_from_review(
        self,
        *,
        memory: RegionSupervisorMemory,
        review: RegionReviewResult,
        iteration: str,
        prior_issue_assessment: list | None = None,
    ) -> None:
        memory.iteration += 1
        latest = self._review_to_issue_memory(region_id=memory.region_id, review=review, iteration=iteration)
        previous_unresolved = {item.issue_id: item for item in memory.unresolved_issues}
        assessments = {
            str(getattr(item, "issue_id", "") or "").strip(): item
            for item in (prior_issue_assessment or [])
            if str(getattr(item, "issue_id", "") or "").strip()
        }
        for issue_id, previous_issue in previous_unresolved.items():
            assessment = assessments.get(issue_id)
            if assessment is None:
                continue
            if getattr(assessment, "status", None) in {"resolved", "transformed"}:
                memory.resolved_issues.append(previous_issue.model_copy(update={"status": "resolved"}))
        memory.unresolved_issues = latest
        if review.global_repairs:
            action = "route-to-region-repair"
            rationale = f"{len(review.global_repairs)} region-wide issues require another region SVG update."
        elif review.object_issues:
            action = "route-to-object-repair"
            rationale = f"{len(review.object_issues)} localized object issues remain."
        else:
            action = "accept-region"
            rationale = "No remaining region or object issues."
        memory.review_route_history.append(
            self._decision(
                iteration=iteration,
                actor="region-supervisor",
                action=action,
                rationale=rationale,
                related_issues=[item.issue_id for item in latest],
            )
        )

    def _record_region_strategy(
        self,
        *,
        memory: RegionSupervisorMemory,
        iteration: str,
        description: str,
        issue_ids: list[str],
    ) -> None:
        memory.attempted_region_strategies.append(description)
        memory.decision_notes.append(
            self._decision(
                iteration=iteration,
                actor="region-supervisor",
                action="apply-region-strategy",
                rationale=description,
                related_issues=issue_ids,
            )
        )

    def _record_object_strategy(
        self,
        *,
        memory: RegionSupervisorMemory,
        iteration: str,
        object_ids: list[str],
    ) -> None:
        memory.attempted_object_strategies.extend(
            [f"Dispatch object repair for {object_id}" for object_id in object_ids]
        )
        for object_id in object_ids:
            status = memory.object_issue_status.setdefault(object_id, {"attempts": 0, "resolved": False})
            status["attempts"] = int(status.get("attempts", 0)) + 1
        memory.decision_notes.append(
            self._decision(
                iteration=iteration,
                actor="region-supervisor",
                action="dispatch-object-repair",
                rationale=f"Escalate localized issues to {len(object_ids)} object workers.",
                related_issues=object_ids,
            )
        )

    def _region_bbox_feedback(
        self,
        *,
        crop_path: Path,
        recognition: RegionRecognitionResult,
    ) -> list[dict]:
        feedback_items = []
        for obj in recognition.recognized_objects:
            if obj.bbox is None:
                continue
            feedback_items.append(
                validate_crop_local_bbox(
                    crop_path=crop_path,
                    target_id=obj.object_id,
                    bbox=obj.bbox.model_dump(mode="json"),
                )
            )
        return build_bbox_feedback_payload(feedback_items)

    def _emit_region_semantic_stage(
        self,
        *,
        region: dict,
        semantic_stage: str,
        phase: str,
        status: str = "running",
    ) -> None:
        worker_id = current_thread().name
        detail = region.get("description") or f"Processing {region['region_id']}"
        worker_statuses = self.pipeline._set_worker_status(
            worker_id=worker_id,
            status=status,
            stage="region-process",
            task_id=region["region_id"],
            detail=detail,
            semantic_stage=semantic_stage,
        )
        self.pipeline._push_event(
            "region-process",
            f"{region['region_id']} stage: {semantic_stage}",
            detail,
            payload={
                "region_id": region["region_id"],
                "bbox": region.get("bbox"),
                "phase": phase,
                "semantic_stage": semantic_stage,
            },
            worker_statuses=worker_statuses,
            status="running",
        )

    def process_initial(
        self,
        *,
        crop_path: Path,
        region: dict,
        checklist: dict,
        region_dir: Path,
    ) -> dict:
        region_id = region["region_id"]
        memory = self._memory_for_region(region, checklist)
        region_task = create_region_task(
            region_id=region_id,
            region_description=region["description"],
            svg_group_template=extract_group_template(region),
            checklist_focus=[
                "Region content stays inside the bounding box.",
                "Main objects are represented with editable SVG primitives.",
                "Region output remains mergeable into the global SVG.",
                f"Stop after at most {self.pipeline.max_retry} retry iterations per named repair task.",
            ],
        )
        self.pipeline._write_json(region_dir / "region_task.json", region_task)

        self._emit_region_semantic_stage(region=region, semantic_stage="Region Scan", phase="initial")
        recognition, recognition_raw = self.recognition_worker.run(
            crop_path=crop_path,
            region=region,
            checklist=checklist,
        )
        recognition = normalize_recognition_bboxes(recognition, region=region)
        grouped_recognition, grouping_summary = group_oversegmented_recognition(recognition)
        recognition = grouped_recognition
        if grouping_summary.merged_count:
            self.pipeline._push_event(
                "region-process",
                f"Recognition granularity normalized for {region_id}",
                (
                    f"Merged {grouping_summary.merged_count} overly fine local text/annotation object(s) "
                    f"back into nearby semantic hosts."
                ),
                payload={
                    "region_id": region_id,
                    "recognition_grouping": grouping_summary.to_payload(),
                },
                status="running",
                level="warning",
            )
        self._emit_region_semantic_stage(region=region, semantic_stage="BBox Review", phase="initial")
        if hasattr(self.pipeline, "workflow_agents"):
            recognition, bbox_result = self.pipeline.workflow_agents.bbox.review_recognition(
                crop_path=crop_path,
                region=region,
                recognition=recognition,
                region_dir=region_dir,
            )
        else:
            bbox_result = BboxAdjustmentResult(scope="recognition", region_id=region_id, overview="", issues=[], needs_adjustment=False)
        self.pipeline._write_text(region_dir / "recognition_raw.txt", recognition_raw)
        self.pipeline._write_json(region_dir / "recognition.json", recognition.model_dump(mode="json"))
        if grouping_summary.merged_count:
            self.pipeline._write_json(
                region_dir / "recognition_grouping.json",
                grouping_summary.to_payload(),
            )
        self.pipeline._write_json(
            region_dir / "recognition_bbox_summary.json",
            {
                "issues": [item.model_dump(mode="json") for item in bbox_result.issues],
                "changes_applied": bbox_result.changes_applied,
                "needs_adjustment": bbox_result.needs_adjustment,
            },
        )

        self._emit_region_semantic_stage(region=region, semantic_stage="SVG Draft", phase="initial")
        region_svg, region_svg_raw = self.svg_worker.run(
            crop_path=crop_path,
            region=region,
            checklist=checklist,
            recognition=recognition,
            bbox_validation_feedback=self._region_bbox_feedback(crop_path=crop_path, recognition=recognition),
        )
        self.pipeline._write_text(region_dir / "region_svg_gen_raw.txt", region_svg_raw)
        self.pipeline._write_json(region_dir / "region_svg_gen.json", region_svg.model_dump(mode="json"))

        current_svg_elements, object_svg_index, unscoped_visuals = finalize_region_svg(region_svg.svg_elements, region)
        self._warn_unscoped_visuals(region=region, phase="initial", unscoped_visuals=unscoped_visuals)
        self.pipeline._write_text(region_dir / "region_svg_gen.svgfrag", current_svg_elements)
        generation = {
            "region_id": region_id,
            "observation": recognition.observation,
            "recognized_objects": [item.model_dump(mode="json") for item in recognition.recognized_objects],
            "svg_elements": current_svg_elements,
        }
        self.pipeline._write_json(region_dir / "generation.json", generation)
        self._emit_region_semantic_stage(region=region, semantic_stage="Prepared", phase="initial")
        memory.decision_notes.append(
            self._decision(
                iteration="initial",
                actor="region-supervisor",
                action="complete-initial-region-build",
                rationale=f"Recognized {len(recognition.recognized_objects)} objects and generated first-pass SVG.",
            )
        )
        self._persist_region_memory(region_dir, memory)
        return {
            "region_id": region_id,
            "region": region,
            "crop_path": crop_path,
            "region_dir": region_dir,
            "task": region_task,
            "recognition_model": recognition,
            "region_svg_generation_model": region_svg,
            "recognition": recognition.model_dump(mode="json"),
            "region_svg_generation": region_svg.model_dump(mode="json"),
            "generation": generation,
            "initial_svg_elements": current_svg_elements,
            "initial_object_svg_index": dict(object_svg_index),
            "agent_execution": {"mode": "supervisor_worker", "scope": "region_initial"},
        }

    def refine(
        self,
        *,
        initial_result: dict,
        checklist: dict,
    ) -> dict:
        region_id = initial_result["region_id"]
        region = initial_result["region"]
        crop_path = initial_result["crop_path"]
        region_dir = initial_result["region_dir"]
        region_task = initial_result["task"]
        recognition = initial_result["recognition_model"]
        object_svg_index = dict(initial_result["initial_object_svg_index"])
        final_svg_elements = initial_result["initial_svg_elements"]
        memory = self._memory_for_region(region, checklist)

        review_history: list[dict] = []
        repair_history: list[dict] = []
        object_history: list[dict] = []
        region_retry_task = self.pipeline._region_retry_task_name(region_id)
        valid_object_ids = {obj.object_id for obj in recognition.recognized_objects}
        repair_payload = None
        policy_iteration = 0
        review: RegionReviewResult | None = None
        last_region_repair_snapshot: tuple[str, dict[str, str]] | None = None

        while True:
            self._emit_region_semantic_stage(region=region, semantic_stage="Review", phase="refine")
            can_object = (
                self.pipeline.workflow_mode == "region_object"
                and self.pipeline._has_object_retry_capacity(region_id, recognition, review.object_issues if review else [])
            )
            region_policy_dir = region_dir / "policy"
            region_svg_file_name = f"region-{region_id}-policy-{policy_iteration}.svg"
            _, rendered_region_svg_path = self._write_region_review_assets(
                region=region,
                svg_fragment=final_svg_elements,
                svg_path=region_policy_dir / region_svg_file_name,
                png_path=region_policy_dir / f"region-{region_id}-policy-{policy_iteration}.png",
            )
            decision = self.policy.evaluate(
                crop_path=crop_path,
                region=region,
                region_dir=region_dir,
                review_context={
                    "checklist": select_checklist_payload_for_region(
                        checklist,
                        region_id,
                        stage="generation_refine",
                    ),
                    "object_index": build_object_index_payload(recognition),
                    "bbox_constraint_feedback": build_region_bbox_review_feedback(
                        svg_fragment=final_svg_elements,
                        recognition=recognition,
                        region_bbox=region.get("bbox"),
                    ),
                    "previous_decision_delta": (
                        build_region_previous_decision_delta(
                            review,
                            route=review_history[-1]["decision"].get("final_route") if review_history else None,
                            strategy=review_history[-1]["decision"].get("final_strategy_label") if review_history else None,
                        )
                        if self.use_supervisor_memory and review is not None
                        else None
                    ),
                    "svg_file_name": region_svg_file_name,
                },
                memory=memory,
                retry_context_summary={
                    "region_retry_available": not self.pipeline._retry_exhausted(region_retry_task),
                    "object_repair_available": can_object,
                },
                valid_object_ids=valid_object_ids,
                can_object_repair=can_object,
                region_retry_exhausted=self.pipeline._retry_exhausted(region_retry_task),
                iteration=str(policy_iteration),
                rendered_svg_path=rendered_region_svg_path,
                svg_file_path=region_policy_dir / region_svg_file_name,
            )
            review = decision.review
            review_history.append({"iteration": policy_iteration, "review": review.model_dump(mode="json"), "decision": decision.model_dump(mode="json")})
            self.pipeline._write_json(region_dir / f"review_iter_{policy_iteration}.json", review.model_dump(mode="json"))
            self._update_region_memory_from_review(
                memory=memory,
                review=review,
                iteration=str(policy_iteration),
                prior_issue_assessment=decision.prior_issue_assessment,
            )
            self._persist_region_memory(region_dir, memory)

            if decision.accept_current_result or not decision.continue_refinement:
                if (
                    not decision.accept_current_result
                    and last_region_repair_snapshot is not None
                    and repair_history
                    and repair_history[-1]["iteration"] == policy_iteration - 1
                ):
                    final_svg_elements, object_svg_index = last_region_repair_snapshot
                break

            if decision.final_route == "object_repair":
                self._emit_region_semantic_stage(region=region, semantic_stage="Object Repair", phase="refine")
                selected_ids = decision.final_target_objects or [issue.object_id for issue in review.object_issues]
                selected_issues = [issue for issue in review.object_issues if issue.object_id in selected_ids] or review.object_issues
                self._record_object_strategy(memory=memory, iteration=f"object-{policy_iteration}", object_ids=[issue.object_id for issue in selected_issues])
                object_svg_index, round_history = self.object_supervisor.repair(
                    crop_path=crop_path,
                    region=region,
                    checklist=checklist,
                    region_dir=region_dir,
                    recognition=recognition,
                    object_svg_index=object_svg_index,
                    object_issues=selected_issues,
                )
                object_history.extend(round_history)
                final_svg_elements = aggregate_region_object_svg(final_svg_elements, object_svg_index, region)
                self.pipeline._write_text(region_dir / f"region_object_aggregate_{policy_iteration}.svgfrag", final_svg_elements)
            else:
                if not self.pipeline._begin_retry(region_retry_task):
                    break
                self._emit_region_semantic_stage(region=region, semantic_stage="Region Repair", phase="refine")
                last_region_repair_snapshot = (final_svg_elements, dict(object_svg_index))
                strategy_hint = None
                if decision.strategy_enabled and decision.final_strategy_label:
                    strategy_hint = {
                        "label": decision.final_strategy_label,
                        "desired_outcome": decision.final_strategy_rationale or "",
                    }
                    self._record_region_strategy(
                        memory=memory,
                        iteration=str(policy_iteration),
                        description=f"{decision.final_strategy_label}: {decision.final_strategy_rationale or ''}",
                        issue_ids=[f"region:{region_id}:{item.criterion}" for item in review.global_repairs],
                    )
                region_svg_update, repair_raw = self.svg_worker.run(
                    crop_path=crop_path,
                    region=region,
                    checklist=checklist,
                    recognition=recognition,
                    bbox_validation_feedback=self._region_bbox_feedback(crop_path=crop_path, recognition=recognition),
                    current_svg_elements=final_svg_elements,
                    current_svg_file_path=self._write_svg_prompt_attachment(
                        svg_text=final_svg_elements,
                        svg_path=region_dir / "inputs" / f"region-{region_id}-current.svg",
                    ),
                    failed_items=[item.model_dump(mode="json") for item in review.global_repairs],
                    strategy_hint=strategy_hint,
                )
                final_svg_elements, object_svg_index, unscoped_visuals = finalize_region_svg(region_svg_update.svg_elements, region)
                self._warn_unscoped_visuals(region=region, phase=f"region_repair_{policy_iteration}", unscoped_visuals=unscoped_visuals)
                repair_payload = RegionRepairResult(
                    region_id=region_id,
                    repaired_svg_elements=final_svg_elements,
                    repairs_applied=region_svg_update.generation_notes,
                )
                repair_history.append(
                    {
                        "iteration": policy_iteration,
                        "retry": self.pipeline._retry_state(region_retry_task),
                        "repair": repair_payload.model_dump(mode="json"),
                        "raw": repair_raw,
                        "decision": decision.model_dump(mode="json"),
                    }
                )
                self.pipeline._write_json(region_dir / f"region_svg_update_iter_{policy_iteration}.json", region_svg_update.model_dump(mode="json"))
                self.pipeline._write_text(region_dir / f"region_svg_update_iter_{policy_iteration}.svgfrag", final_svg_elements)
            self._emit_region_semantic_stage(region=region, semantic_stage="Next Review", phase="refine")
            policy_iteration += 1

        retry_summary = self.pipeline._retry_summary_for_region(region_id)
        self.pipeline._write_json(region_dir / "review_history.json", review_history)
        self.pipeline._write_json(region_dir / "repair_history.json", repair_history)
        self.pipeline._write_json(region_dir / "object_history.json", object_history)
        self.pipeline._write_json(region_dir / "retry_summary.json", retry_summary)
        self.pipeline._write_json(region_dir / "review.json", review.model_dump(mode="json"))
        if repair_payload:
            self.pipeline._write_json(region_dir / "repair.json", repair_payload.model_dump(mode="json"))
        self.pipeline._write_text(region_dir / "final_region_elements.svgfrag", final_svg_elements)
        if review.object_issues:
            unresolved_objects = {issue.object_id for issue in review.object_issues}
            for object_id, status in memory.object_issue_status.items():
                status["resolved"] = object_id not in unresolved_objects
        memory.stop_reason = review_history[-1]["decision"]["final_reason"] if review_history else None
        memory.resolved_issues = self._dedupe_issue_list(memory.resolved_issues)
        memory.unresolved_issues = self._dedupe_issue_list(memory.unresolved_issues)
        self._persist_region_memory(region_dir, memory)
        return {
            "region_id": region_id,
            "task": region_task,
            "recognition": initial_result["recognition"],
            "region_svg_generation": initial_result["region_svg_generation"],
            "generation": {**initial_result["generation"], "svg_elements": final_svg_elements},
            "review": review.model_dump(mode="json"),
            "repair": repair_payload.model_dump(mode="json") if repair_payload else None,
            "review_history": review_history,
            "repair_history": repair_history,
            "object_history": object_history,
            "retry_summary": retry_summary,
            "retry_exhausted": any(item["exhausted"] for item in retry_summary.values()),
            "final_svg_elements": final_svg_elements,
            "agent_execution": {
                "mode": "supervisor_worker",
                "scope": "region_refine",
                "object_rounds": sum(1 for item in review_history if "object_repair" == item["decision"]["final_route"]),
            },
        }


class FusionSupervisorAgent(BaseWorkflowAgent):
    """Supervisor that owns merged SVG integration and final fusion-quality review."""

    def __init__(self, pipeline) -> None:
        super().__init__(pipeline)
        self.combined_policy_worker = FusionCombinedPolicyModelWorker(pipeline)
        self.repair_worker = IntegratedSvgRepairWorkerAgent(pipeline)
        self.policy = FusionPolicyEngine(pipeline, combined_worker=self.combined_policy_worker)
        self.memory = FusionSupervisorMemory()

    def _final_review_to_issue_memory(self, review: FinalReviewResult, *, iteration: str) -> list[SupervisorIssueMemory]:
        issues: list[SupervisorIssueMemory] = []
        for issue in final_review_spatial_logical_issues(review.model_dump(mode="json")):
            issue_kind = issue.get("issue_kind", "fusion")
            related_regions = issue.get("related_regions") or []
            target_id = ",".join(related_regions) if related_regions else None
            issues.append(
                SupervisorIssueMemory(
                    issue_id=f"fusion:{fusion_review_issue_id(issue, issue_kind=issue_kind)}",
                    scope="fusion",
                    target_id=target_id,
                    criterion=str(issue.get("criterion") or issue_kind),
                    reason=str(issue.get("description", "")),
                    status="unresolved",
                    source_iteration=iteration,
                )
            )
        return issues

    def _persist_fusion_memory(self) -> None:
        self._persist_memory(self.pipeline.root_output_dir / "fusion_supervisor_memory.json", self.memory)

    def _update_fusion_memory_from_decision(
        self,
        *,
        decision: FusionPolicyDecision,
        review: FinalReviewResult,
        iteration: str,
    ) -> None:
        current_issues = self._final_review_to_issue_memory(review, iteration=iteration)
        previous_unresolved = {item.issue_id: item for item in self.memory.remaining_cross_region_issues}
        assessments = {
            str(getattr(item, "issue_id", "") or "").strip(): item
            for item in decision.prior_issue_assessment
            if str(getattr(item, "issue_id", "") or "").strip()
        }
        for issue_id, previous_issue in previous_unresolved.items():
            assessment = assessments.get(issue_id)
            if assessment is None:
                continue
            if getattr(assessment, "status", None) in {"resolved", "transformed"}:
                self.memory.resolved_cross_region_issues.append(previous_issue.model_copy(update={"status": "resolved"}))
        self.memory.resolved_cross_region_issues = self._dedupe_issue_list(self.memory.resolved_cross_region_issues)
        self.memory.issue_groups_seen = self._dedupe_issue_list(self.memory.issue_groups_seen + current_issues)
        self.memory.remaining_cross_region_issues = current_issues

    def execute(
        self,
        *,
        copied_input_path: Path,
        checklist: dict,
        svg_template: str,
        merged_regions: dict[str, str],
        output_path: Path,
        review_raw_path: Path,
        review_json_path: Path,
    ) -> tuple[str, FinalReviewResult, str]:
        self.memory.iteration += 1
        merged_svg = persist_merged_svg(
            svg_template=svg_template,
            merged_regions=merged_regions,
            output_path=output_path,
        )
        self.pipeline._record_written_file(output_path, kind=output_path.suffix.lstrip(".") or "text")
        final_review_raw = ""
        final_review = FinalReviewResult()
        iteration = 0
        while True:
            fusion_policy_dir = self.pipeline.root_output_dir / "policy"
            merged_svg_file_name = f"merged-final-policy-{iteration}.svg"
            _, rendered_merged_svg_path = self._write_full_svg_review_assets(
                svg_text=merged_svg,
                svg_path=fusion_policy_dir / merged_svg_file_name,
                png_path=fusion_policy_dir / f"merged-final-policy-{iteration}.png",
            )
            decision = self.policy.evaluate(
                copied_input_path=copied_input_path,
                final_review_context={
                    "checklist": select_checklist_payload_for_fusion(checklist),
                    "previous_decision_delta": (
                        build_fusion_previous_decision_delta(
                            final_review,
                            strategy=self.memory.attempted_merge_strategies[-1] if self.memory.attempted_merge_strategies else None,
                        )
                        if self.use_supervisor_memory and iteration
                        else None
                    ),
                    "svg_file_name": merged_svg_file_name,
                },
                memory=self.memory,
                retry_exhausted=iteration > 0,
                iteration=str(iteration),
                rendered_svg_path=rendered_merged_svg_path,
                svg_file_path=fusion_policy_dir / merged_svg_file_name,
            )
            final_review = decision.review
            final_review_raw = json.dumps(decision.model_dump(mode="json"), ensure_ascii=False, indent=2)
            self._update_fusion_memory_from_decision(
                decision=decision,
                review=final_review,
                iteration=str(iteration),
            )
            if decision.accept_current_result or not decision.continue_refinement:
                break
            strategy_label = decision.final_strategy_label or "conservative_merge_repair"
            self.memory.attempted_merge_strategies.append(strategy_label)
            repair_result, repair_raw = self.repair_worker.run(
                copied_input_path=copied_input_path,
                merged_svg=merged_svg,
                final_review=final_review,
                svg_file_path=output_path,
            )
            merged_svg = repair_result.repaired_svg
            output_path.write_text(merged_svg, encoding="utf-8")
            self.pipeline._record_written_file(output_path, kind=output_path.suffix.lstrip(".") or "text")
            stem = output_path.stem
            self.pipeline._write_text(output_path.with_name(f"{stem}_integrate_repair_raw.txt"), repair_raw)
            self.pipeline._write_json(output_path.with_name(f"{stem}_integrate_repair.json"), repair_result.model_dump(mode="json"))
            iteration += 1
            if iteration > 1:
                break
        self.pipeline._write_text(review_raw_path, final_review_raw)
        self.pipeline._write_json(review_json_path, final_review.model_dump(mode="json"))
        remaining_regions = set()
        unstable_boundaries: list[dict] = []
        for item in self.memory.remaining_cross_region_issues:
            if item.target_id:
                parts = [part for part in item.target_id.split(",") if part]
                remaining_regions.update(parts)
                if len(parts) >= 2:
                    unstable_boundaries.append({"regions": parts, "issue_id": item.issue_id})
        self.memory.unstable_boundaries = unstable_boundaries
        self.memory.stable_regions = sorted(set(merged_regions) - remaining_regions)
        self.memory.stop_reason = "fusion policy completed"
        self._persist_fusion_memory()
        self.pipeline._set_overview(
            {
                "fusion_agent_mode": "supervisor_worker",
                "final_issue_count": len(final_review_spatial_logical_issues(final_review.model_dump(mode="json"))),
            }
        )
        return merged_svg, final_review, final_review_raw
