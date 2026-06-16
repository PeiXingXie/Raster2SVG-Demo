"""Overview: Layout detection node and checklist-building implementation."""

from __future__ import annotations

from pathlib import Path

from deepagents_template.prompt import build_layout_detection_prompts
from deepagents_template.schemas import LayoutDetectionResult


class LayoutDetectionNodeMixin:
    """Implements the layout detection workflow node."""

    def _build_image_aware_checklist(
        self,
        *,
        copied_input_path: Path,
        layout_overview: str,
        regions: list[dict],
    ) -> list[dict]:
        return self.workflow_agents.layout.checklist_worker.run(
            copied_input_path=copied_input_path,
            layout_overview=layout_overview,
            regions=regions,
        )

    def _run_layout_detection_node(
        self,
        *,
        copied_input_path: Path,
        width: int,
        height: int,
    ) -> tuple[LayoutDetectionResult, str, list[dict], list[dict], str]:
        self._push_event(
            "layout detection",
            "Running layout detection node",
            "Calling layout detection, building the checklist, and preparing the SVG template.",
        )
        return self.workflow_agents.layout.execute(
            copied_input_path=copied_input_path,
            width=width,
            height=height,
        )

    def _detect_layout(
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
        return self.final_caller.call_json(
            LayoutDetectionResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[copied_input_path],
        )
