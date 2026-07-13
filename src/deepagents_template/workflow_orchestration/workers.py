"""Worker implementations used by the raster-to-SVG workflow supervisors."""

from __future__ import annotations

from pathlib import Path

from deepagents_template.checklist import (
    checklist_budget_issues,
    checklist_budget_summary,
    flatten_checklists,
    select_checklist_payload_for_region,
)
from deepagents_template.geometry import build_region_context, build_region_recognition_context
from deepagents_template.modeling.executor import summarize_exception
from deepagents_template.prompt import (
    build_object_bbox_candidate_generation_prompts,
    build_object_bbox_candidate_selection_prompts,
    build_object_initial_bbox_prompts,
    build_checklist_plan_prompts,
    build_fusion_combined_policy_prompts,
    build_integrated_svg_repair_prompts,
    build_layout_bbox_adjustment_prompts,
    build_layout_bbox_combined_policy_prompts,
    build_layout_detection_prompts,
    build_object_combined_policy_prompts,
    build_object_svg_generation_prompts,
    build_recognition_bbox_adjustment_prompts,
    build_recognition_bbox_combined_policy_prompts,
    build_region_combined_policy_prompts,
    build_region_recognition_prompts,
    build_region_svg_generation_prompts,
)
from deepagents_template.schemas import (
    BboxAdjustmentResult,
    BboxCombinedPolicyModelResult,
    ChecklistPlanResult,
    FinalReviewResult,
    FusionCombinedPolicyModelResult,
    IntegratedSvgRepairResult,
    LayoutDetectionResult,
    ObjectBboxCandidateGenerationResult,
    ObjectBboxCandidateSelectionResult,
    ObjectInitialBboxResult,
    ObjectCandidate,
    ObjectCombinedPolicyModelResult,
    ObjectSvgGenerationResult,
    RegionCombinedPolicyModelResult,
    RegionRecognitionResult,
    RegionSvgGenerationResult,
)

from .base import BaseWorkflowAgent


class LayoutDetectionWorkerAgent(BaseWorkflowAgent):
    """Worker that performs whole-image layout detection."""

    def run(
        self,
        *,
        copied_input_path: Path,
        width: int,
        height: int,
    ) -> tuple[LayoutDetectionResult, str]:
        system_prompt, user_prompt = build_layout_detection_prompts(
            width=width,
            height=height,
        )
        return self.pipeline.final_caller.call_json(
            LayoutDetectionResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[copied_input_path],
        )


class BboxAdjustmentWorkerAgent(BaseWorkflowAgent):
    """Worker that reviews and corrects bbox layouts using overlay images."""

    def run_layout(
        self,
        *,
        copied_input_path: Path,
        overlay_path: Path,
        width: int,
        height: int,
        regions: list[dict],
        memory_summary: dict | None,
        retry_state: dict | None = None,
    ) -> tuple[BboxAdjustmentResult, str]:
        system_prompt, user_prompt = build_layout_bbox_adjustment_prompts(
            width=width,
            height=height,
            regions=regions,
            memory_summary=memory_summary,
            retry_state=retry_state,
        )
        return self.pipeline.final_caller.call_json(
            BboxAdjustmentResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[copied_input_path, overlay_path],
        )

    def run_recognition(
        self,
        *,
        crop_path: Path,
        overlay_path: Path,
        region: dict,
        recognized_objects: list[dict],
        validation_feedback: list[dict] | None,
        memory_summary: dict | None,
        retry_state: dict | None = None,
        exempted_issue_ids: list[str] | None = None,
        recently_resolved_issue_ids: list[str] | None = None,
    ) -> tuple[BboxAdjustmentResult, str]:
        system_prompt, user_prompt = build_recognition_bbox_adjustment_prompts(
            region=region,
            recognized_objects=recognized_objects,
            validation_feedback=validation_feedback,
            memory_summary=memory_summary,
            retry_state=retry_state,
            exempted_issue_ids=exempted_issue_ids,
            recently_resolved_issue_ids=recently_resolved_issue_ids,
        )
        return self.pipeline.region_caller.call_json(
            BboxAdjustmentResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[crop_path, overlay_path],
        )

    def run_initial_object_bboxes(
        self,
        *,
        crop_path: Path,
        grid_path: Path,
        region: dict,
        recognized_objects: list[dict],
        checklist_criteria: list[dict] | None = None,
    ) -> tuple[ObjectInitialBboxResult, str]:
        system_prompt, user_prompt = build_object_initial_bbox_prompts(
            region=region,
            recognized_objects=recognized_objects,
            checklist_criteria=checklist_criteria or [],
        )
        return self.pipeline.region_caller.call_json(
            ObjectInitialBboxResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[crop_path, grid_path],
        )

    def run_object_bbox_candidates(
        self,
        *,
        crop_path: Path,
        grid_path: Path,
        overlay_path: Path,
        region: dict,
        recognized_objects: list[dict],
        current_issues: list[dict],
    ) -> tuple[ObjectBboxCandidateGenerationResult, str]:
        system_prompt, user_prompt = build_object_bbox_candidate_generation_prompts(
            region=region,
            recognized_objects=recognized_objects,
            current_issues=current_issues,
        )
        return self.pipeline.region_caller.call_json(
            ObjectBboxCandidateGenerationResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[crop_path, grid_path, overlay_path],
        )

    def run_object_bbox_candidate_selection(
        self,
        *,
        crop_path: Path,
        current_overlay_path: Path,
        candidate_overlay_path: Path,
        region: dict,
        target_object: dict,
        issue: dict,
        candidates: list[dict],
        current_objects: list[dict],
    ) -> tuple[ObjectBboxCandidateSelectionResult, str]:
        system_prompt, user_prompt = build_object_bbox_candidate_selection_prompts(
            region=region,
            target_object=target_object,
            issue=issue,
            candidates=candidates,
            current_objects=current_objects,
        )
        return self.pipeline.region_caller.call_json(
            ObjectBboxCandidateSelectionResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[crop_path, current_overlay_path, candidate_overlay_path],
        )


class BboxCombinedPolicyModelWorker(BaseWorkflowAgent):
    """Worker that reviews bbox candidates and emits termination tendencies in one call."""

    def run_layout(
        self,
        *,
        copied_input_path: Path,
        current_overlay_path: Path,
        candidate_overlay_path: Path,
        width: int,
        height: int,
        current_regions: list[dict],
        candidate_regions: list[dict],
        proposal_result: dict,
        memory_summary: dict | None,
        candidate_changed: bool,
        retry_state: dict | None = None,
    ) -> tuple[BboxCombinedPolicyModelResult, str]:
        system_prompt, user_prompt = build_layout_bbox_combined_policy_prompts(
            width=width,
            height=height,
            current_regions=current_regions,
            candidate_regions=candidate_regions,
            proposal_result=proposal_result,
            memory_summary=memory_summary,
            candidate_changed=candidate_changed,
            retry_state=retry_state,
        )
        return self.pipeline.final_caller.call_json(
            BboxCombinedPolicyModelResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[copied_input_path, current_overlay_path, candidate_overlay_path],
        )

    def run_recognition(
        self,
        *,
        crop_path: Path,
        current_overlay_path: Path,
        candidate_overlay_path: Path,
        region: dict,
        current_objects: list[dict],
        candidate_objects: list[dict],
        proposal_result: dict,
        validation_feedback: list[dict] | None,
        memory_summary: dict | None,
        candidate_changed: bool,
        retry_state: dict | None = None,
    ) -> tuple[BboxCombinedPolicyModelResult, str]:
        system_prompt, user_prompt = build_recognition_bbox_combined_policy_prompts(
            region=region,
            current_objects=current_objects,
            candidate_objects=candidate_objects,
            proposal_result=proposal_result,
            validation_feedback=validation_feedback,
            memory_summary=memory_summary,
            candidate_changed=candidate_changed,
            retry_state=retry_state,
        )
        return self.pipeline.region_caller.call_json(
            BboxCombinedPolicyModelResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[crop_path, current_overlay_path, candidate_overlay_path],
        )


class ChecklistPlanningWorkerAgent(BaseWorkflowAgent):
    """Worker that converts layout understanding into an image-aware acceptance checklist."""

    def _normalize_plan(self, result: ChecklistPlanResult) -> tuple[dict, list[dict]]:
        checklist = result.checklists.model_dump(mode="json")
        element_presence = [item.model_dump(mode="json") for item in result.element_presence]
        return checklist, element_presence

    def _emit_budget_warning(
        self,
        issues: list[str],
        summary: dict,
        *,
        detail: str,
        artifact_name: str = "checklist_budget_warning.json",
    ) -> None:
        payload = {"issues": issues, "summary": summary}
        self.pipeline._write_json(self.pipeline.root_intermediate_dir / artifact_name, payload)
        if hasattr(self.pipeline, "_push_event"):
            self.pipeline._push_event(
                "planning",
                "Checklist budget warning",
                detail,
                payload=payload,
                status="running",
                level="warning",
            )

    def run(
        self,
        *,
        copied_input_path: Path,
        layout_overview: str,
        regions: list[dict],
    ) -> dict:
        system_prompt, user_prompt = build_checklist_plan_prompts(
            user_request=self.pipeline.user_message,
            layout_overview=layout_overview,
            regions=regions,
        )
        try:
            result, raw_text = self.pipeline.final_caller.call_json(
                ChecklistPlanResult,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_paths=[copied_input_path],
            )
            self.pipeline._write_text(
                self.pipeline.root_intermediate_dir / "checklist_generation_raw.txt",
                raw_text,
            )
            self.pipeline._write_json(
                self.pipeline.root_intermediate_dir / "element_presence.json",
                [item.model_dump(mode="json") for item in result.element_presence],
            )
            self.pipeline._write_json(
                self.pipeline.root_intermediate_dir / "checklist_plan.json",
                result.model_dump(mode="json"),
            )
            checklist, _element_presence = self._normalize_plan(result)
            if not flatten_checklists(checklist):
                raise ValueError("Checklist planner returned an empty checklist.")
            budget_issues = checklist_budget_issues(checklist)
            if budget_issues:
                summary = checklist_budget_summary(checklist)
                self._emit_budget_warning(
                    budget_issues,
                    summary,
                    detail="Checklist planner exceeded the configured budget; continuing with warning and preserving the concise high-signal checklist as returned.",
                )
            return checklist
        except Exception as exc:
            self.pipeline._write_json(
                self.pipeline.root_intermediate_dir / "checklist_generation_error.json",
                {"error": summarize_exception(exc), "fallback_used": False},
            )
            raise


class RegionRecognitionWorkerAgent(BaseWorkflowAgent):
    """Worker that recognizes object structure inside one region crop."""

    def run(
        self,
        *,
        crop_path: Path,
        region: dict,
        checklist: dict,
    ) -> tuple[RegionRecognitionResult, str]:
        region_context = build_region_recognition_context(region)
        region_checklist = select_checklist_payload_for_region(
            checklist,
            region["region_id"],
            stage="recognition",
        )
        system_prompt, user_prompt = build_region_recognition_prompts(
            region=region,
            region_context=region_context,
            checklist_criteria=region_checklist,
        )
        return self.pipeline.region_caller.call_json(
            RegionRecognitionResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[crop_path],
        )


class RegionSvgWorkerAgent(BaseWorkflowAgent):
    """Worker that generates or updates editable SVG for one region."""

    def run(
        self,
        *,
        crop_path: Path,
        region: dict,
        checklist: dict,
        recognition: RegionRecognitionResult,
        bbox_validation_feedback: list[dict] | None = None,
        current_svg_elements: str | None = None,
        current_svg_file_path: Path | None = None,
        failed_items: list[dict] | None = None,
        strategy_hint: dict | None = None,
    ) -> tuple[RegionSvgGenerationResult, str]:
        region_context = build_region_context(region)
        region_checklist = select_checklist_payload_for_region(
            checklist,
            region["region_id"],
            stage="generation_refine",
        )
        system_prompt, user_prompt = build_region_svg_generation_prompts(
            region=region,
            region_context=region_context,
            checklist_criteria=region_checklist,
            recognition=recognition,
            bbox_validation_feedback=bbox_validation_feedback,
            current_svg_elements=current_svg_elements,
            failed_items=failed_items,
            strategy_hint=strategy_hint,
        )
        return self.pipeline.region_caller.call_json(
            RegionSvgGenerationResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[crop_path],
        )


class RegionCombinedPolicyModelWorker(BaseWorkflowAgent):
    """Worker that emits region review plus repair/termination tendencies in one call."""

    def run(
        self,
        *,
        crop_path: Path,
        region: dict,
        review_context: dict,
        memory_summary: dict | None,
        retry_context_summary: dict,
        strategy_enabled: bool,
        rendered_svg_path: Path | None = None,
        svg_file_path: Path | None = None,
    ) -> tuple[RegionCombinedPolicyModelResult, str]:
        svg_source_text = svg_file_path.read_text(encoding="utf-8") if svg_file_path is not None and svg_file_path.is_file() else None
        system_prompt, user_prompt = build_region_combined_policy_prompts(
            region=region,
            review_context=review_context,
            memory_summary=memory_summary,
            retry_context_summary=retry_context_summary,
            strategy_enabled=strategy_enabled,
            svg_source_text=svg_source_text,
            svg_file_name=svg_file_path.name if svg_file_path is not None else None,
        )
        return self.pipeline.region_caller.call_json(
            RegionCombinedPolicyModelResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[path for path in [crop_path, rendered_svg_path] if path is not None],
        )


class ObjectSvgWorkerAgent(BaseWorkflowAgent):
    """Worker that generates or updates editable SVG for one object."""

    def run(
        self,
        *,
        object_crop_path: Path,
        obj: ObjectCandidate,
        current_svg: str,
        failed_items: list[dict] | None = None,
        current_svg_file_path: Path | None = None,
        strategy_hint: dict | None = None,
    ) -> tuple[ObjectSvgGenerationResult, str]:
        system_prompt, user_prompt = build_object_svg_generation_prompts(
            obj=obj,
            current_svg=current_svg,
            failed_items=failed_items,
            strategy_hint=strategy_hint,
        )
        return self.pipeline.region_caller.call_json(
            ObjectSvgGenerationResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[object_crop_path],
        )

class ObjectCombinedPolicyModelWorker(BaseWorkflowAgent):
    """Worker that emits object review plus repair/termination tendencies in one call."""

    def run(
        self,
        *,
        object_crop_path: Path,
        obj: dict,
        review_context: dict,
        memory_summary: dict | None,
        strategy_enabled: bool,
        rendered_svg_path: Path | None = None,
        svg_file_path: Path | None = None,
    ) -> tuple[ObjectCombinedPolicyModelResult, str]:
        svg_source_text = svg_file_path.read_text(encoding="utf-8") if svg_file_path is not None and svg_file_path.is_file() else None
        system_prompt, user_prompt = build_object_combined_policy_prompts(
            obj=obj,
            review_context=review_context,
            memory_summary=memory_summary,
            strategy_enabled=strategy_enabled,
            svg_source_text=svg_source_text,
            svg_file_name=svg_file_path.name if svg_file_path is not None else None,
        )
        return self.pipeline.region_caller.call_json(
            ObjectCombinedPolicyModelResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[path for path in [object_crop_path, rendered_svg_path] if path is not None],
        )


class FusionCombinedPolicyModelWorker(BaseWorkflowAgent):
    """Worker that emits fusion review plus repair/termination tendencies in one call."""

    def run(
        self,
        *,
        copied_input_path: Path,
        final_review_context: dict,
        memory_summary: dict | None,
        strategy_enabled: bool,
        rendered_svg_path: Path | None = None,
        svg_file_path: Path | None = None,
    ) -> tuple[FusionCombinedPolicyModelResult, str]:
        svg_source_text = svg_file_path.read_text(encoding="utf-8") if svg_file_path is not None and svg_file_path.is_file() else None
        system_prompt, user_prompt = build_fusion_combined_policy_prompts(
            user_request=self.pipeline.user_message,
            final_review_context=final_review_context,
            memory_summary=memory_summary,
            strategy_enabled=strategy_enabled,
            svg_source_text=svg_source_text,
            svg_file_name=svg_file_path.name if svg_file_path is not None else None,
        )
        return self.pipeline.final_caller.call_json(
            FusionCombinedPolicyModelResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[path for path in [copied_input_path, rendered_svg_path] if path is not None],
        )


class IntegratedSvgRepairWorkerAgent(BaseWorkflowAgent):
    """Worker that performs one conservative merge-time repair pass."""

    def run(
        self,
        *,
        copied_input_path: Path,
        merged_svg: str,
        final_review: FinalReviewResult,
        svg_file_path: Path | None = None,
    ) -> tuple[IntegratedSvgRepairResult, str]:
        system_prompt, user_prompt = build_integrated_svg_repair_prompts(
            user_request=self.pipeline.user_message,
            merged_svg=merged_svg,
            final_review=final_review.model_dump(mode="json"),
            svg_file_name="merged_final.svg",
        )
        return self.pipeline.final_caller.call_json(
            IntegratedSvgRepairResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[copied_input_path],
        )
