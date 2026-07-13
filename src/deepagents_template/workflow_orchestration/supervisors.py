"""Supervisor implementations for the raster-to-SVG workflow."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from threading import current_thread

from PIL import Image, ImageDraw

from deepagents_template.checklist import (
    final_review_spatial_logical_issues,
    fusion_review_issue_id,
    flatten_checklists,
    select_checklist_payload_for_fusion,
    select_checklist_payload_for_region,
    select_checklist_for_region,
)
from deepagents_template.bbox_sanitization import sanitize_bbox_issues, truncate_text
from deepagents_template.geometry import (
    compact_regions_for_prompt,
    crop_object_image,
    normalize_recognition_bboxes,
    normalize_regions,
    recognition_bboxes_to_global,
)
from deepagents_template.policy import BboxPolicyEngine, FusionPolicyEngine, ObjectPolicyEngine, RegionPolicyEngine
from deepagents_template.recognition_grouping import group_oversegmented_recognition
from deepagents_template.schemas import (
    BboxAdjustmentResult,
    BboxGlobalRoundSummary,
    BboxIssueThreadSummary,
    BboxSupervisorMemory,
    FinalReviewResult,
    FusionSupervisorMemory,
    LayoutDetectionResult,
    ObjectBboxCandidateSelectionResult,
    ObjectInitialBboxResult,
    LayoutSupervisorMemory,
    ObjectRepairSupervisorMemory,
    ObjectCandidate,
    RegionRecognitionResult,
    RegionBoundingBox,
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


_CANDIDATE_BBOX_COLORS = {
    "compact": "#e63946",
    "balanced": "#1d3557",
    "roomy": "#2a9d8f",
}

_REGION_REPAIR_ISSUE_LIMIT = 3
_OBJECT_REPAIR_ISSUE_LIMIT = 3
_OBJECT_FIDELITY_ISSUE_FAMILIES = {
    "content_accuracy",
    "shape_fidelity",
    "internal_structure",
}


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

    def _sanitize_result_without_issue_budget(self, result: BboxAdjustmentResult) -> BboxAdjustmentResult:
        return result.model_copy(
            update={
                "overview": self._truncate_text(result.overview, max_words=28, max_chars=180),
                "issues": [
                    issue.model_copy(
                        update={
                            "criterion": self._truncate_text(issue.criterion, max_words=12, max_chars=72),
                            "reason": self._truncate_text(issue.reason, max_words=24, max_chars=140),
                        }
                    )
                    for issue in result.issues
                    if issue.criterion and issue.reason
                ],
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
            cleaned = self._truncate_text(item, max_words=20, max_chars=120)
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

    def _render_grid_reference(self, *, crop_path: Path, output_path: Path, scale: int = 2) -> Path:
        """Render a readable coordinate grid while preserving original crop coordinates."""

        with Image.open(crop_path) as source:
            crop_image = source.convert("RGBA")
        scale = max(1, int(scale))
        if scale > 1:
            crop_image = crop_image.resize((crop_image.width * scale, crop_image.height * scale))
        crop_width, crop_height = crop_image.size
        original_width = max(1, crop_width // scale)
        original_height = max(1, crop_height // scale)

        top_pad = 28
        left_pad = 46
        right_pad = 12
        bottom_pad = 12
        image = Image.new(
            "RGBA",
            (left_pad + crop_width + right_pad, top_pad + crop_height + bottom_pad),
            (246, 247, 249, 255),
        )
        image.paste(crop_image, (left_pad, top_pad))
        draw = ImageDraw.Draw(image)
        minor = 10
        major = 20
        emphasis = 100
        crop_left = left_pad
        crop_top = top_pad
        crop_right = left_pad + crop_width
        crop_bottom = top_pad + crop_height
        draw.rectangle((0, 0, crop_right, top_pad - 1), fill=(246, 247, 249, 255))
        draw.rectangle((0, 0, left_pad - 1, crop_bottom), fill=(246, 247, 249, 255))
        draw.line((crop_left, 0, crop_left, crop_bottom), fill=(80, 80, 80, 180), width=1)
        draw.line((0, crop_top, crop_right, crop_top), fill=(80, 80, 80, 180), width=1)
        x_marks = list(range(0, original_width + 1, minor))
        if x_marks[-1] != original_width:
            x_marks.append(original_width)
        for x in x_marks:
            sx = crop_left + x * scale
            is_boundary = x == 0 or x == original_width
            is_emphasis = is_boundary or x % emphasis == 0
            is_major = x % major == 0
            color = (55, 55, 55, 130) if is_emphasis else (80, 80, 80, 90) if is_major else (120, 120, 120, 45)
            line_width = 2 if is_emphasis else 1
            draw.line((sx, crop_top, sx, crop_bottom), fill=color, width=line_width)
            if x % major == 0 or x == original_width:
                label_fill = (0, 0, 0, 255) if is_emphasis else (30, 30, 30, 230)
                label = str(x)
                label_width = draw.textlength(label)
                label_x = min(max(sx + 2, crop_left + 2), crop_right - int(label_width) - 2)
                draw.text((label_x, 6), label, fill=label_fill)
        y_marks = list(range(0, original_height + 1, minor))
        if y_marks[-1] != original_height:
            y_marks.append(original_height)
        for y in y_marks:
            sy = crop_top + y * scale
            is_boundary = y == 0 or y == original_height
            is_emphasis = is_boundary or y % emphasis == 0
            is_major = y % major == 0
            color = (55, 55, 55, 130) if is_emphasis else (80, 80, 80, 90) if is_major else (120, 120, 120, 45)
            line_width = 2 if is_emphasis else 1
            draw.line((crop_left, sy, crop_right, sy), fill=color, width=line_width)
            if y % major == 0 or y == original_height:
                label_fill = (0, 0, 0, 255) if is_emphasis else (30, 30, 30, 230)
                label = str(y)
                label_height = draw.textbbox((0, 0), label)[3]
                label_y = min(max(sy + 2, crop_top + 2), crop_bottom - label_height - 2)
                draw.text((4, label_y), label, fill=label_fill)
        boundary_color = (55, 55, 55, 150)
        draw.line((crop_left, crop_top, crop_left, crop_bottom), fill=boundary_color, width=2)
        draw.line((crop_right, crop_top, crop_right, crop_bottom), fill=boundary_color, width=2)
        draw.line((crop_left, crop_top, crop_right, crop_top), fill=boundary_color, width=2)
        draw.line((crop_left, crop_bottom, crop_right, crop_bottom), fill=boundary_color, width=2)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)
        return output_path

    @staticmethod
    def _coerce_crop_bbox(bbox, *, crop_path: Path) -> RegionBoundingBox | None:
        if bbox is None:
            return None
        payload = bbox.model_dump(mode="json") if hasattr(bbox, "model_dump") else dict(bbox)
        with Image.open(crop_path) as image:
            crop_width, crop_height = image.size
        x = max(0, min(int(payload.get("x", 0)), max(crop_width - 1, 0)))
        y = max(0, min(int(payload.get("y", 0)), max(crop_height - 1, 0)))
        width = max(1, min(int(payload.get("width", 1)), max(crop_width - x, 1)))
        height = max(1, min(int(payload.get("height", 1)), max(crop_height - y, 1)))
        return RegionBoundingBox(x=x, y=y, width=width, height=height)

    def _render_candidate_overlay(
        self,
        *,
        crop_path: Path,
        output_path: Path,
        object_id: str,
        candidates: list[dict],
    ) -> Path:
        boxes = []
        for item in candidates:
            candidate_id = str(item.get("candidate_id") or "candidate")
            boxes.append(
                {
                    "id": candidate_id,
                    "label": f"{object_id}:{candidate_id}",
                    "bbox": item.get("bbox") or {},
                    "color": _CANDIDATE_BBOX_COLORS.get(candidate_id),
                }
            )
        with Image.open(crop_path) as image:
            min_dimension = min(image.size)
        line_width = max(1, min(2, round(min_dimension * 0.004)))
        return render_bbox_overlay(
            image_path=crop_path,
            boxes=boxes,
            output_path=output_path,
            line_width=line_width,
            draw_labels=False,
        )

    def _collect_recognition_validation_feedback(
        self,
        *,
        crop_path: Path,
        recognition: RegionRecognitionResult,
        target_ids: set[str] | None = None,
    ) -> list[dict]:
        return []

    def _apply_recognition_updates(
        self,
        *,
        recognition: RegionRecognitionResult,
        updates: list,
    ) -> RegionRecognitionResult:
        if not updates:
            return recognition
        update_by_id = {}
        for item in updates:
            if isinstance(item, dict):
                target_id = item.get("target_id")
                bbox = item.get("bbox")
            else:
                target_id = getattr(item, "target_id", None)
                bbox = getattr(item, "bbox", None)
            if target_id:
                update_by_id[target_id] = bbox
        adjusted_objects = []
        for obj in recognition.recognized_objects:
            replacement_bbox = update_by_id.get(obj.object_id)
            adjusted_objects.append(
                obj.model_copy(update={"bbox": replacement_bbox}) if replacement_bbox is not None else obj
            )
        return recognition.model_copy(update={"recognized_objects": adjusted_objects})

    @staticmethod
    def _recognition_objects_payload(recognition: RegionRecognitionResult) -> list[dict]:
        return [
            {
                "object_id": obj.object_id,
                "description": obj.description,
                "included_elements": obj.included_elements,
                "generation_focus": obj.generation_focus,
                "bbox": obj.bbox.model_dump(mode="json") if obj.bbox else None,
            }
            for obj in recognition.recognized_objects
        ]

    @staticmethod
    def _bbox_issue_key(issue) -> tuple[str, str]:
        return (issue.target_id, issue.issue_code or issue.canonical_issue_id or issue.criterion)

    @staticmethod
    def _bbox_issue_score(issue) -> int:
        severity_score = {"high": 30, "medium": 12, "low": 4}.get(issue.severity, 8)
        criterion = (issue.criterion or "").lower()
        reason = (issue.reason or "").lower()
        bonus = 0
        if "clip" in criterion or "clip" in reason:
            bonus += 6
        if "text" in criterion or "text" in reason:
            bonus += 2
        if "border" in criterion or "border" in reason:
            bonus += 1
        return severity_score + bonus

    @staticmethod
    def _issue_ids(issues: list) -> list[str]:
        return [item.canonical_issue_id or f"{item.target_id}:{item.criterion}" for item in issues]

    def _select_ranked_bbox_issues(
        self,
        issues: list,
        *,
        exempted_issue_ids: set[str],
        limit: int = 3,
    ) -> list:
        selected = []
        seen_target_ids: set[str] = set()
        seen_issue_ids: set[str] = set()
        for issue in sorted(issues, key=self._bbox_issue_score, reverse=True):
            canonical_id = issue.canonical_issue_id or f"{issue.target_id}:{issue.issue_code or issue.criterion}"
            if not canonical_id or canonical_id in exempted_issue_ids or canonical_id in seen_issue_ids:
                continue
            # One issue thread per target per global round avoids same-object thread conflicts.
            if issue.target_id in seen_target_ids:
                continue
            selected.append(issue)
            seen_target_ids.add(issue.target_id)
            seen_issue_ids.add(canonical_id)
            if len(selected) >= limit:
                break
        return selected

    def _bbox_artifact_dir(self, *, region_dir: Path) -> Path:
        path = region_dir / "bbox"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _bbox_round_name(round_index: int) -> str:
        return f"g{round_index:02d}"

    @staticmethod
    def _bbox_iteration_name(iteration: int) -> str:
        return f"i{iteration:02d}"

    @staticmethod
    def _bbox_issue_dir_name(issue) -> str:
        safe_target = (getattr(issue, "target_id", "") or "target").replace(":", "_").replace("/", "_").replace("\\", "_")
        safe_target = "_".join(part for part in safe_target.split("_") if part)
        if len(safe_target) > 16:
            safe_target = safe_target[:16].rstrip("_")
        digest_source = getattr(issue, "canonical_issue_id", None) or f"{getattr(issue, 'target_id', '')}:{getattr(issue, 'issue_code', '')}"
        digest = hashlib.sha1(str(digest_source).encode("utf-8")).hexdigest()[:8]
        return f"i_{safe_target or 'target'}_{digest}"

    def _bbox_round_dir(self, *, region_dir: Path, round_index: int) -> Path:
        path = self._bbox_artifact_dir(region_dir=region_dir) / self._bbox_round_name(round_index)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _bbox_issue_dir(self, *, region_dir: Path, round_index: int, issue) -> Path:
        path = self._bbox_round_dir(region_dir=region_dir, round_index=round_index) / "issues" / self._bbox_issue_dir_name(issue)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _memory_summary_payload(memory: BboxSupervisorMemory, enabled: bool) -> dict | None:
        if not enabled:
            return None
        return {
            "iteration": memory.iteration,
            "attempted_adjustment_types": memory.attempted_adjustment_types[-4:],
            "accepted_changes": memory.accepted_changes[-4:],
            "rejected_changes": memory.rejected_changes[-4:],
        }

    @staticmethod
    def _hard_bbox_issues(issues: list) -> list:
        return [
            item
            for item in issues
            if getattr(item, "issue_code", "") in {"target_not_contained", "target_clipped", "invalid_bbox"}
        ]

    def _apply_initial_bbox_result(
        self,
        *,
        recognition: RegionRecognitionResult,
        initial_result: ObjectInitialBboxResult,
        crop_path: Path,
    ) -> RegionRecognitionResult:
        updates = []
        known_ids = {obj.object_id for obj in recognition.recognized_objects}
        for item in initial_result.object_bboxes:
            if item.object_id not in known_ids:
                continue
            bbox = self._coerce_crop_bbox(item.bbox, crop_path=crop_path)
            if bbox is not None:
                updates.append({"target_id": item.object_id, "bbox": bbox})
        return self._apply_recognition_updates(recognition=recognition, updates=updates)

    @staticmethod
    def _objects_missing_bboxes(recognition: RegionRecognitionResult) -> list[str]:
        return [obj.object_id for obj in recognition.recognized_objects if obj.bbox is None]

    @staticmethod
    def _clear_recognition_bboxes(recognition: RegionRecognitionResult) -> RegionRecognitionResult:
        return recognition.model_copy(
            update={
                "recognized_objects": [
                    obj.model_copy(update={"bbox": None})
                    for obj in recognition.recognized_objects
                ]
            }
        )

    def _push_bbox_warning(self, *, region_id: str, title: str, detail: str, payload: dict) -> None:
        push_event = getattr(self.pipeline, "_push_event", None)
        if callable(push_event):
            push_event(
                "bbox-review",
                title,
                detail,
                payload={"region_id": region_id, **payload},
                status="running",
                level="warning",
            )

    def _warn_missing_issue_edges(self, *, region_id: str, issues: list) -> None:
        missing = [
            {
                "canonical_issue_id": issue.canonical_issue_id,
                "object_id": issue.target_id,
                "issue_family": issue.issue_code,
                "severity": issue.severity,
            }
            for issue in issues
            if issue.issue_code in {"target_not_contained", "target_clipped"} and not issue.edges
        ]
        if not missing:
            return
        self._push_bbox_warning(
            region_id=region_id,
            title="Bbox issue missing concrete edge",
            detail="BBox issue omitted concrete edge values; no hard edge inference was applied.",
            payload={"issues": missing},
        )

    @staticmethod
    def _issue_payload(issue) -> dict:
        payload = issue.model_dump(mode="json") if hasattr(issue, "model_dump") else dict(issue)
        payload["object_id"] = payload.get("target_id") or payload.get("object_id")
        payload["issue_family"] = payload.get("issue_code") or payload.get("issue_family")
        payload.pop("canonical_issue_id", None)
        return payload

    def _candidate_set_for_issue(self, candidate_result, issue) -> object | None:
        issue_code = getattr(issue, "issue_code", "")
        issue_edges = list(getattr(issue, "edges", []) or [])
        for item in candidate_result.candidate_sets:
            if item.object_id != issue.target_id:
                continue
            if item.issue_code and item.issue_code != issue_code:
                continue
            if list(item.edges or []) and list(item.edges or []) != issue_edges:
                continue
            return item
        for item in candidate_result.candidate_sets:
            if item.object_id == issue.target_id:
                return item
        return None

    @staticmethod
    def _selection_to_issue_summary(*, issue, selection: ObjectBboxCandidateSelectionResult) -> BboxIssueThreadSummary:
        return BboxIssueThreadSummary(
            canonical_issue_id=issue.canonical_issue_id,
            target_id=issue.target_id,
            issue_code=issue.issue_code,
            severity=issue.severity,
            status="resolved" if selection.issue_resolved else "progressive",
            stop_reason=selection.selection_rationale or "selected best bbox candidate",
            iterations=1,
            committed=True,
            stagnation_count=0,
        )

    def _review_recognition_v2(
        self,
        *,
        crop_path: Path,
        region: dict,
        recognition: RegionRecognitionResult,
        region_dir: Path,
    ) -> tuple[RegionRecognitionResult, BboxAdjustmentResult]:
        scope_key = f"recognition:{region['region_id']}"
        memory = self._memory_for(scope_key, "recognition")
        bbox_dir = self._bbox_artifact_dir(region_dir=region_dir)
        grid_path = bbox_dir / "grid_reference.png"
        self._render_grid_reference(crop_path=crop_path, output_path=grid_path)

        current_recognition = self._clear_recognition_bboxes(recognition)
        if current_recognition.recognized_objects:
            initial_result, initial_raw = self.worker.run_initial_object_bboxes(
                crop_path=crop_path,
                grid_path=grid_path,
                region=region,
                recognized_objects=self._recognition_objects_payload(current_recognition),
                checklist_criteria=[],
            )
            current_recognition = self._apply_initial_bbox_result(
                recognition=current_recognition,
                initial_result=initial_result,
                crop_path=crop_path,
            )
            self.pipeline._write_text(bbox_dir / "initial_bbox_raw.txt", initial_raw)
            self.pipeline._write_json(bbox_dir / "initial_bbox.json", initial_result.model_dump(mode="json"))
            missing_object_ids = self._objects_missing_bboxes(current_recognition)
            if missing_object_ids:
                missing_objects = [
                    obj
                    for obj in self._recognition_objects_payload(current_recognition)
                    if obj.get("object_id") in set(missing_object_ids)
                ]
                retry_result, retry_raw = self.worker.run_initial_object_bboxes(
                    crop_path=crop_path,
                    grid_path=grid_path,
                    region=region,
                    recognized_objects=missing_objects,
                    checklist_criteria=[],
                )
                current_recognition = self._apply_initial_bbox_result(
                    recognition=current_recognition,
                    initial_result=retry_result,
                    crop_path=crop_path,
                )
                self.pipeline._write_text(bbox_dir / "initial_bbox_missing_retry_raw.txt", retry_raw)
                self.pipeline._write_json(
                    bbox_dir / "initial_bbox_missing_retry.json",
                    {
                        "missing_object_ids": missing_object_ids,
                        "result": retry_result.model_dump(mode="json"),
                    },
                )
                remaining_missing = self._objects_missing_bboxes(current_recognition)
                if remaining_missing:
                    self._push_bbox_warning(
                        region_id=region["region_id"],
                        title="Initial object bbox missing after retry",
                        detail="Initial bbox generation still omitted recognized objects after targeted retry.",
                        payload={"missing_object_ids": remaining_missing},
                    )

        latest_result = BboxAdjustmentResult(scope="recognition", region_id=region["region_id"], overview="", issues=[], needs_adjustment=False)
        resolved_issue_ids: set[str] = set()
        exempted_issue_ids: set[str] = set()
        global_rounds: list[BboxGlobalRoundSummary] = []
        previous_issue_signature: tuple[str, ...] = ()
        repeated_rounds = 0
        soft_only_rounds = 0
        round_index = 0

        while True:
            round_dir = self._bbox_round_dir(region_dir=region_dir, round_index=round_index)
            scan_dir = round_dir / "scan"
            scan_dir.mkdir(parents=True, exist_ok=True)
            overlay_path = scan_dir / "cur.png"
            self._render_recognition_overlay(crop_path, current_recognition, overlay_path)
            current_objects = self._recognition_objects_payload(current_recognition)
            scan_result, scan_raw = self.worker.run_recognition(
                crop_path=crop_path,
                overlay_path=overlay_path,
                region=region,
                recognized_objects=current_objects,
                validation_feedback=[],
                memory_summary=self._memory_summary_payload(memory, self.use_supervisor_memory),
                exempted_issue_ids=sorted(exempted_issue_ids),
                recently_resolved_issue_ids=sorted(resolved_issue_ids),
            )
            scan_result = self._sanitize_result_without_issue_budget(scan_result)
            self.pipeline._write_text(scan_dir / "scan.txt", scan_raw)
            self.pipeline._write_json(scan_dir / "scan.json", scan_result.model_dump(mode="json"))

            ranked_issues = self._select_ranked_bbox_issues(scan_result.issues, exempted_issue_ids=exempted_issue_ids, limit=3)
            self._warn_missing_issue_edges(region_id=region["region_id"], issues=ranked_issues)
            hard_issues = self._hard_bbox_issues(ranked_issues)
            soft_only_rounds = soft_only_rounds + 1 if ranked_issues and not hard_issues else 0
            issue_signature = tuple(self._issue_ids(ranked_issues))
            repeated_rounds = repeated_rounds + 1 if issue_signature and issue_signature == previous_issue_signature else 0
            previous_issue_signature = issue_signature

            if not ranked_issues or (not hard_issues and soft_only_rounds >= 1):
                latest_result = scan_result.model_copy(update={"issues": ranked_issues, "needs_adjustment": bool(hard_issues)})
                stop_reason = "no bbox issues selected" if not ranked_issues else "only soft bbox issues remain"
                round_summary = BboxGlobalRoundSummary(
                    round_index=round_index,
                    proposed_issue_ids=list(issue_signature),
                    resolved_issue_ids=sorted(resolved_issue_ids),
                    exempted_issue_ids=sorted(exempted_issue_ids),
                    committed_issue_ids=[],
                    stop_reason=stop_reason,
                    stagnated=False,
                )
                global_rounds.append(round_summary)
                self.pipeline._write_json(round_dir / "summary.json", round_summary.model_dump(mode="json"))
                memory.stop_reason = stop_reason
                break

            if repeated_rounds >= self.pipeline.bbox_global_stagnation_rounds:
                latest_result = scan_result.model_copy(update={"issues": ranked_issues, "needs_adjustment": True})
                round_summary = BboxGlobalRoundSummary(
                    round_index=round_index,
                    proposed_issue_ids=list(issue_signature),
                    resolved_issue_ids=sorted(resolved_issue_ids),
                    exempted_issue_ids=sorted(exempted_issue_ids),
                    committed_issue_ids=[],
                    stop_reason="global bbox issue set stagnated across rounds",
                    stagnated=True,
                )
                global_rounds.append(round_summary)
                self.pipeline._write_json(round_dir / "summary.json", round_summary.model_dump(mode="json"))
                memory.stop_reason = round_summary.stop_reason
                break

            retry_task = f"bbox:recognition:{region['region_id']}:round"
            if not self.pipeline._begin_retry(retry_task):
                latest_result = scan_result.model_copy(update={"issues": ranked_issues, "needs_adjustment": True})
                memory.stop_reason = "region bbox retry budget exhausted"
                break

            candidates_dir = round_dir / "candidates"
            candidates_dir.mkdir(parents=True, exist_ok=True)
            candidate_result, candidate_raw = self.worker.run_object_bbox_candidates(
                crop_path=crop_path,
                grid_path=grid_path,
                overlay_path=overlay_path,
                region=region,
                recognized_objects=current_objects,
                current_issues=[self._issue_payload(issue) for issue in ranked_issues],
            )
            self.pipeline._write_text(candidates_dir / "candidates_raw.txt", candidate_raw)
            self.pipeline._write_json(candidates_dir / "candidates.json", candidate_result.model_dump(mode="json"))

            updates = []
            committed_in_round: list[str] = []
            selections = []
            objects_by_id = {obj["object_id"]: obj for obj in current_objects}
            for issue in ranked_issues:
                candidate_set = self._candidate_set_for_issue(candidate_result, issue)
                if candidate_set is None or not candidate_set.candidates:
                    exempted_issue_ids.add(issue.canonical_issue_id)
                    continue
                candidates_payload = [item.model_dump(mode="json") for item in candidate_set.candidates]
                candidate_overlay = candidates_dir / f"{self._bbox_issue_dir_name(issue)}_overlay.png"
                self._render_candidate_overlay(
                    crop_path=crop_path,
                    output_path=candidate_overlay,
                    object_id=issue.target_id,
                    candidates=candidates_payload,
                )
                selection, selection_raw = self.worker.run_object_bbox_candidate_selection(
                    crop_path=crop_path,
                    current_overlay_path=overlay_path,
                    candidate_overlay_path=candidate_overlay,
                    region=region,
                    target_object=objects_by_id.get(issue.target_id, {"object_id": issue.target_id}),
                    issue=self._issue_payload(issue),
                    candidates=candidates_payload,
                    current_objects=current_objects,
                )
                selected_bbox = self._coerce_crop_bbox(selection.selected_bbox, crop_path=crop_path)
                if selected_bbox is None:
                    exempted_issue_ids.add(issue.canonical_issue_id)
                    continue
                updates.append({"target_id": issue.target_id, "bbox": selected_bbox})
                committed_in_round.append(issue.canonical_issue_id)
                if selection.issue_resolved:
                    resolved_issue_ids.add(issue.canonical_issue_id)
                selection_payload = selection.model_dump(mode="json")
                selection_payload["canonical_issue_id"] = issue.canonical_issue_id
                selections.append(selection_payload)
                issue_dir = round_dir / "issues" / self._bbox_issue_dir_name(issue)
                issue_dir.mkdir(parents=True, exist_ok=True)
                self.pipeline._write_text(issue_dir / "selection_raw.txt", selection_raw)
                self.pipeline._write_json(issue_dir / "selection.json", selection_payload)
                summary = self._selection_to_issue_summary(issue=issue, selection=selection)
                self.pipeline._write_json(issue_dir / "summary.json", summary.model_dump(mode="json"))
                memory.iteration += 1
                memory.issue_history.append(
                    SupervisorIssueMemory(
                        issue_id=issue.canonical_issue_id,
                        scope="object",
                        target_id=issue.target_id,
                        criterion=issue.criterion,
                        reason=issue.reason,
                        status="resolved" if selection.issue_resolved else "attempted",
                        attempts=1,
                        source_iteration=str(round_index),
                    )
                )
                memory.accepted_changes.append(f"selected {selection.selected_candidate_id} for {issue.target_id}")

            if updates:
                current_recognition = self._apply_recognition_updates(recognition=current_recognition, updates=updates)
                latest_result = BboxAdjustmentResult(
                    scope="recognition",
                    region_id=region["region_id"],
                    overview="selected best bbox candidates for current region issues",
                    issues=ranked_issues,
                    adjustment_type="mixed",
                    target_ids=[item["target_id"] for item in updates],
                    adjusted_object_bboxes=updates,
                    changes_applied=[f"updated {item['target_id']}" for item in updates][:4],
                    needs_adjustment=True,
                )
            else:
                latest_result = scan_result.model_copy(update={"issues": ranked_issues, "needs_adjustment": True})

            round_summary = BboxGlobalRoundSummary(
                round_index=round_index,
                proposed_issue_ids=list(issue_signature),
                resolved_issue_ids=sorted(resolved_issue_ids),
                exempted_issue_ids=sorted(exempted_issue_ids),
                committed_issue_ids=committed_in_round,
                stop_reason="completed bbox candidate selection batch",
                stagnated=False,
            )
            global_rounds.append(round_summary)
            self.pipeline._write_json(round_dir / "summary.json", round_summary.model_dump(mode="json"))
            self.pipeline._write_json(
                round_dir / "index.json",
                {
                    "schema_version": 3,
                    "region_id": region["region_id"],
                    "round_index": round_index,
                    "scan_dir_name": "scan",
                    "candidate_dir_name": "candidates",
                    "proposed_issue_ids": list(issue_signature),
                    "committed_issue_ids": committed_in_round,
                    "selections": selections,
                },
            )
            if not updates:
                memory.stop_reason = "no bbox candidate selection could be applied"
                break
            round_index += 1

        self.pipeline._write_json(region_dir / "recognition_bbox_adjustment.json", latest_result.model_dump(mode="json"))
        self.pipeline._write_json(
            region_dir / "recognition_bbox_summary.json",
            {
                "schema_version": 3,
                "issues": [item.model_dump(mode="json") for item in latest_result.issues],
                "changes_applied": latest_result.changes_applied,
                "needs_adjustment": latest_result.needs_adjustment,
                "stop_reason": memory.stop_reason,
                "global_rounds": [item.model_dump(mode="json") for item in global_rounds],
                "resolved_issue_ids": sorted(resolved_issue_ids),
                "exempted_issue_ids": sorted(exempted_issue_ids),
            },
        )
        self.pipeline._write_json(
            bbox_dir / "index.json",
            {
                "schema_version": 3,
                "region_id": region["region_id"],
                "grid_reference": "grid_reference.png",
                "global_rounds": [item.model_dump(mode="json") for item in global_rounds],
            },
        )
        self.pipeline._push_event(
            "region-process",
            f"Completed bbox supervisor loop for {region['region_id']}",
            f"bbox loop finished after {len(global_rounds)} region round(s) with {len(latest_result.issues)} residual issue(s).",
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

    def _persist_bbox_trace(self, path: Path, payload: dict) -> None:
        self.pipeline._write_json(path, payload)

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
        return self._review_recognition_v2(
            crop_path=crop_path,
            region=region,
            recognition=recognition,
            region_dir=region_dir,
        )



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
            object_crop_path = crop_object_image(
                region_crop_path=crop_path,
                obj=obj,
                object_dir=object_dir,
                region=region,
                bbox_space="global",
            )
            if not self.pipeline._begin_retry(retry_task):
                memory.object_attempts[obj.object_id] = memory.object_attempts.get(obj.object_id, 0)
                memory.object_last_failure[obj.object_id] = "retry exhausted before new attempt"
                memory.unresolved_objects = sorted(set(memory.unresolved_objects + [obj.object_id]))
                history.append({"object_id": issue.object_id, "retry_task": retry_task, "skipped": True, "retry": self.pipeline._retry_state(retry_task), "final_svg_elements": current_object_svg})
                continue

            failed_items = [
                {
                    "issue_family": getattr(issue, "issue_family", None),
                    "criterion": issue.criterion,
                    "reason": issue.reason,
                }
            ]
            object_task = create_object_task(
                object_id=obj.object_id,
                object_type=obj.object_type,
                description=obj.description,
                included_elements=obj.included_elements,
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

    @staticmethod
    def _select_object_issues_for_region_round(
        object_issues: list,
        *,
        target_objects: list[str],
        valid_object_ids: set[str],
        limit: int = _OBJECT_REPAIR_ISSUE_LIMIT,
    ) -> list:
        candidates = [
            issue
            for issue in object_issues
            if issue.object_id in valid_object_ids
            and (not target_objects or issue.object_id in target_objects)
        ]
        fidelity_candidates = [
            issue
            for issue in candidates
            if issue.severity in {"medium", "high"}
            and getattr(issue, "issue_family", "") in _OBJECT_FIDELITY_ISSUE_FAMILIES
        ]
        selected = fidelity_candidates or candidates
        return selected[:limit]

    def _region_bbox_feedback(
        self,
        *,
        crop_path: Path,
        recognition: RegionRecognitionResult,
    ) -> list[dict]:
        return []

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
            recognition = recognition_bboxes_to_global(recognition, region=region)
        else:
            bbox_result = BboxAdjustmentResult(scope="recognition", region_id=region_id, overview="", issues=[], needs_adjustment=False)
            recognition = recognition_bboxes_to_global(recognition, region=region)
        self.pipeline._write_text(region_dir / "recognition_raw.txt", recognition_raw)
        self.pipeline._write_json(region_dir / "recognition.json", recognition.model_dump(mode="json"))
        if grouping_summary.merged_count:
            self.pipeline._write_json(
                region_dir / "recognition_grouping.json",
                grouping_summary.to_payload(),
            )
        existing_bbox_summary = {}
        bbox_summary_path = region_dir / "recognition_bbox_summary.json"
        if bbox_summary_path.is_file():
            try:
                loaded_summary = json.loads(bbox_summary_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                loaded_summary = {}
            if isinstance(loaded_summary, dict):
                existing_bbox_summary = loaded_summary
        self.pipeline._write_json(
            bbox_summary_path,
            {
                **existing_bbox_summary,
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
                region_retry_task=region_retry_task,
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

            current_can_object = (
                self.pipeline.workflow_mode == "region_object"
                and self.pipeline._has_object_retry_capacity(region_id, recognition, review.object_issues)
            )
            selected_region_issues = list(review.global_repairs[:_REGION_REPAIR_ISSUE_LIMIT])
            selected_object_issues = (
                self._select_object_issues_for_region_round(
                    review.object_issues,
                    target_objects=decision.final_target_objects,
                    valid_object_ids=valid_object_ids,
                )
                if current_can_object
                else []
            )
            did_repair = False

            if selected_region_issues:
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
                        issue_ids=[f"region:{region_id}:{item.criterion}" for item in selected_region_issues],
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
                    failed_items=[item.model_dump(mode="json") for item in selected_region_issues],
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
                did_repair = True

            if selected_object_issues:
                self._emit_region_semantic_stage(region=region, semantic_stage="Object Repair", phase="refine")
                self._record_object_strategy(memory=memory, iteration=f"object-{policy_iteration}", object_ids=[issue.object_id for issue in selected_object_issues])
                object_svg_index, round_history = self.object_supervisor.repair(
                    crop_path=crop_path,
                    region=region,
                    checklist=checklist,
                    region_dir=region_dir,
                    recognition=recognition,
                    object_svg_index=object_svg_index,
                    object_issues=selected_object_issues,
                )
                object_history.extend(round_history)
                final_svg_elements = aggregate_region_object_svg(final_svg_elements, object_svg_index, region)
                self.pipeline._write_text(region_dir / f"region_object_aggregate_{policy_iteration}.svgfrag", final_svg_elements)
                did_repair = True
            if not did_repair:
                break
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
        fusion_retry_limit = max(0, int(getattr(self.pipeline, "fusion_max_retry", 3)))
        final_decision = None
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
                retry_exhausted=iteration >= fusion_retry_limit,
                iteration=str(iteration),
                rendered_svg_path=rendered_merged_svg_path,
                svg_file_path=fusion_policy_dir / merged_svg_file_name,
            )
            final_decision = decision
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
            if iteration > fusion_retry_limit:
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
        final_outcome = getattr(final_decision, "final_outcome", None) if final_decision is not None else None
        final_reason = getattr(final_decision, "final_reason", None) if final_decision is not None else None
        self.memory.stop_reason = (
            f"{final_outcome}: {final_reason}"
            if final_outcome and final_reason
            else final_reason or "fusion policy completed"
        )
        self._persist_fusion_memory()
        self.pipeline._set_overview(
            {
                "fusion_agent_mode": "supervisor_worker",
                "final_issue_count": len(final_review_spatial_logical_issues(final_review.model_dump(mode="json"))),
                "fusion_stop_outcome": final_outcome,
                "fusion_stop_reason": self.memory.stop_reason,
                "fusion_repair_attempts_used": min(iteration, fusion_retry_limit),
                "fusion_max_retry": fusion_retry_limit,
            }
        )
        return merged_svg, final_review, final_review_raw

