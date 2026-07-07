"""Shared contracts for issue-level object bbox refinement providers."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from deepagents_template.schemas import BboxQualityIssue, ObjectBboxRefinementResult, RegionRecognitionResult


class ObjectBboxRefinementProvider(Protocol):
    """Refine one issue-targeted object bbox inside a region crop."""

    def refine_issue_object(
        self,
        *,
        crop_path: Path,
        overlay_path: Path,
        region: dict,
        recognition: RegionRecognitionResult,
        issue: BboxQualityIssue,
        validation_feedback: list[dict] | None,
        output_dir: Path,
        memory_summary: dict | None = None,
        exempted_issue_ids: list[str] | None = None,
        recently_resolved_issue_ids: list[str] | None = None,
    ) -> ObjectBboxRefinementResult:
        ...
