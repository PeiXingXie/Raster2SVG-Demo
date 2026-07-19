"""Overview: Integrate-process node for SVG merging and merged-image review."""

from __future__ import annotations

from pathlib import Path

from deepagents_template.schemas import FinalReviewResult


class IntegrateProcessNodeMixin:
    """Implements merge-and-review behavior for integrated SVG outputs."""

    def _run_integrate_process_node(
        self,
        *,
        copied_input_path: Path,
        checklist: dict,
        svg_template: str,
        merged_regions: dict[str, str],
        output_path: Path,
        review_raw_path: Path,
        review_json_path: Path,
        detail: str,
        trace_phase: str,
    ) -> tuple[str, FinalReviewResult, str]:
        self._push_event(
            "integrate-process",
            "Running integrate-process node",
            detail,
            payload={"phase": trace_phase},
        )
        return self.workflow_agents.fusion.execute(
            copied_input_path=copied_input_path,
            checklist=checklist,
            svg_template=svg_template,
            merged_regions=merged_regions,
            output_path=output_path,
            review_raw_path=review_raw_path,
            review_json_path=review_json_path,
        )
