"""Overview: Object-process node for object-level generation, review, and local repair."""

from __future__ import annotations

import time
from pathlib import Path

from deepagents_template.schemas import RegionRecognitionResult


class ObjectProcessNodeMixin:
    """Implements object-level refinement and object-to-region reintegration."""

    def _run_object_process_node(
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
        self._push_event(
            "object-process",
            f"Running object-process for {region['region_id']}",
            "Generating/refining object SVG fragments and reviewing object-scoped failures.",
            payload={"region_id": region["region_id"], "object_issues": len(object_issues), "phase": "refine"},
            status="running",
        )
        started_at = time.perf_counter()
        previous_trace_stage = self._set_current_trace_stage("refine")
        try:
            return self.workflow_agents.object.repair(
                crop_path=crop_path,
                region=region,
                checklist=checklist,
                region_dir=region_dir,
                recognition=recognition,
                object_svg_index=object_svg_index,
                object_issues=object_issues,
            )
        finally:
            self._set_current_trace_stage(previous_trace_stage)
            self._record_node_timing(
                "object-process",
                phase="repair",
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            )
