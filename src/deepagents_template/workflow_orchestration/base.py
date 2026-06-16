"""Shared base helpers for workflow-local supervisors and workers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from deepagents_template.schemas import SupervisorDecisionMemory, SupervisorIssueMemory
from deepagents_template.utils.svg_rendering import wrap_svg_fragment, write_svg_review_artifacts

if TYPE_CHECKING:
    from deepagents_template.conversion import RasterToSvgPipeline


class BaseWorkflowAgent:
    """Base helper that gives workflow agents access to the shared pipeline context."""

    def __init__(self, pipeline: RasterToSvgPipeline) -> None:
        self.pipeline = pipeline

    @property
    def supervisor_memory_enabled(self) -> bool:
        return bool(getattr(self.pipeline, "supervisor_memory_enabled", False))

    @property
    def use_supervisor_memory(self) -> bool:
        """Return whether supervisor working memory should affect runtime behavior."""

        pipeline_method = getattr(self.pipeline, "use_supervisor_memory", None)
        if callable(pipeline_method):
            return bool(pipeline_method())
        return self.supervisor_memory_enabled

    @property
    def supervisor_memory_persist_enabled(self) -> bool:
        return bool(getattr(self.pipeline, "supervisor_memory_persist_enabled", True))

    @property
    def persist_supervisor_memory(self) -> bool:
        """Return whether supervisor memory artifacts should be persisted."""

        pipeline_method = getattr(self.pipeline, "persist_supervisor_memory", None)
        if callable(pipeline_method):
            return bool(pipeline_method())
        return self.supervisor_memory_persist_enabled

    def _persist_memory(self, path: Path, payload) -> None:
        if not self.persist_supervisor_memory:
            return
        self.pipeline._write_json(path, payload.model_dump(mode="json"))

    def _record_review_asset(self, path: Path, *, kind: str) -> None:
        if path.is_file():
            self.pipeline._record_written_file(path, kind=kind)

    def _write_svg_prompt_attachment(
        self,
        *,
        svg_text: str,
        svg_path: Path,
    ) -> Path | None:
        if not svg_text.strip():
            return None
        svg_path.parent.mkdir(parents=True, exist_ok=True)
        svg_path.write_text(svg_text, encoding="utf-8")
        self._record_review_asset(svg_path, kind="svg")
        return svg_path

    def _write_region_review_assets(
        self,
        *,
        region: dict,
        svg_fragment: str,
        svg_path: Path,
        png_path: Path,
    ) -> tuple[Path, Path | None]:
        bbox = region.get("bbox") or {}
        wrapped_svg = wrap_svg_fragment(
            svg_fragment,
            view_box=(
                int(bbox.get("x", 0)),
                int(bbox.get("y", 0)),
                max(int(bbox.get("width", 1)), 1),
                max(int(bbox.get("height", 1)), 1),
            ),
        )
        written_svg, written_png = write_svg_review_artifacts(
            svg_text=wrapped_svg,
            svg_path=svg_path,
            png_path=png_path,
        )
        self._record_review_asset(written_svg, kind="svg")
        if written_png is not None:
            self._record_review_asset(written_png, kind="png")
        return written_svg, written_png

    def _write_object_review_assets(
        self,
        *,
        region: dict,
        obj: dict,
        svg_fragment: str,
        svg_path: Path,
        png_path: Path,
    ) -> tuple[Path, Path | None]:
        region_bbox = region.get("bbox") or {}
        object_bbox = obj.get("bbox") or {}
        view_box = (
            int(region_bbox.get("x", 0)) + int(object_bbox.get("x", 0)),
            int(region_bbox.get("y", 0)) + int(object_bbox.get("y", 0)),
            max(int(object_bbox.get("width", 1)), 1),
            max(int(object_bbox.get("height", 1)), 1),
        )
        wrapped_svg = wrap_svg_fragment(svg_fragment, view_box=view_box)
        written_svg, written_png = write_svg_review_artifacts(
            svg_text=wrapped_svg,
            svg_path=svg_path,
            png_path=png_path,
        )
        self._record_review_asset(written_svg, kind="svg")
        if written_png is not None:
            self._record_review_asset(written_png, kind="png")
        return written_svg, written_png

    def _write_full_svg_review_assets(
        self,
        *,
        svg_text: str,
        svg_path: Path,
        png_path: Path,
    ) -> tuple[Path, Path | None]:
        written_svg, written_png = write_svg_review_artifacts(
            svg_text=svg_text,
            svg_path=svg_path,
            png_path=png_path,
        )
        self._record_review_asset(written_svg, kind="svg")
        if written_png is not None:
            self._record_review_asset(written_png, kind="png")
        return written_svg, written_png

    @staticmethod
    def _decision(*, iteration: str, actor: str, action: str, rationale: str, related_issues: list[str] | None = None) -> SupervisorDecisionMemory:
        return SupervisorDecisionMemory(
            iteration=iteration,
            actor=actor,
            action=action,
            rationale=rationale,
            related_issues=related_issues or [],
        )

    @staticmethod
    def _dedupe_issue_list(items: list[SupervisorIssueMemory]) -> list[SupervisorIssueMemory]:
        seen: dict[str, SupervisorIssueMemory] = {}
        for item in items:
            seen[item.issue_id] = item
        return list(seen.values())
