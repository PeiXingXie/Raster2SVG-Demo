"""Standalone multimodal review workers kept for debugging and offline inspection."""

from __future__ import annotations

from pathlib import Path

from deepagents_template.checklist import select_checklist_payload_for_fusion, select_checklist_payload_for_region
from deepagents_template.geometry import build_region_context
from deepagents_template.prompt import build_final_review_prompts, build_object_review_prompts, build_region_review_prompts
from deepagents_template.schemas import FinalReviewResult, ObjectCandidate, ObjectReviewResult, RegionRecognitionResult, RegionReviewResult
from deepagents_template.utils.context_payloads import build_region_review_object_summary
from deepagents_template.workflow_orchestration.base import BaseWorkflowAgent


class DebugRegionReviewWorkerAgent(BaseWorkflowAgent):
    """Standalone region reviewer. Not used by the default supervisor flow."""

    def run(
        self,
        *,
        crop_path: Path,
        region: dict,
        checklist: dict,
        recognition: RegionRecognitionResult,
        proposed_svg_elements: str,
        rendered_svg_path: Path | None = None,
        svg_file_path: Path | None = None,
        svg_file_name: str = "proposed_region.svg",
    ) -> tuple[RegionReviewResult, str]:
        region_context = build_region_context(region)
        region_checklist = select_checklist_payload_for_region(
            checklist,
            region["region_id"],
            stage="generation_refine",
        )
        object_summary = build_region_review_object_summary(recognition)
        system_prompt, user_prompt = build_region_review_prompts(
            region=region,
            region_context=region_context,
            checklist_criteria=region_checklist,
            proposed_svg_elements=proposed_svg_elements,
            object_summary=object_summary,
            svg_file_name=svg_file_name,
        )
        return self.pipeline.region_caller.call_json(
            RegionReviewResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[path for path in [crop_path, rendered_svg_path] if path is not None],
        )


class DebugObjectReviewWorkerAgent(BaseWorkflowAgent):
    """Standalone object reviewer. Not used by the default supervisor flow."""

    def run(
        self,
        *,
        object_crop_path: Path,
        obj: ObjectCandidate,
        object_svg: str,
        failed_items: list[dict] | None,
        rendered_svg_path: Path | None = None,
        svg_file_path: Path | None = None,
        svg_file_name: str = "proposed_object.svg",
    ) -> tuple[ObjectReviewResult, str]:
        system_prompt, user_prompt = build_object_review_prompts(
            obj=obj,
            object_svg=object_svg,
            failed_items=failed_items,
            svg_file_name=svg_file_name,
        )
        return self.pipeline.region_caller.call_json(
            ObjectReviewResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[path for path in [object_crop_path, rendered_svg_path] if path is not None],
        )


class DebugFinalReviewWorkerAgent(BaseWorkflowAgent):
    """Standalone fusion reviewer. Not used by the default supervisor flow."""

    def run(
        self,
        *,
        copied_input_path: Path,
        checklist: dict,
        merged_svg: str,
        rendered_svg_path: Path | None = None,
        svg_file_path: Path | None = None,
        svg_file_name: str = "merged_final.svg",
    ) -> tuple[FinalReviewResult, str]:
        system_prompt, user_prompt = build_final_review_prompts(
            checklist_criteria=select_checklist_payload_for_fusion(checklist),
            merged_svg=merged_svg,
            svg_file_name=svg_file_name,
        )
        return self.pipeline.final_caller.call_json(
            FinalReviewResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[path for path in [copied_input_path, rendered_svg_path] if path is not None],
        )
