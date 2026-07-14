"""Overview: Integrate-process node for SVG merging and merged-image review."""

from __future__ import annotations

from pathlib import Path

from deepagents_template.debug_review import DebugFinalReviewWorkerAgent
from deepagents_template.schemas import FinalReviewResult, IntegratedSvgRepairResult
from deepagents_template.utils.svg_rendering import SvgPreviewRenderError, write_svg_review_artifacts


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

    def _repair_integrated_svg_once(
        self,
        *,
        copied_input_path: Path,
        merged_svg: str,
        final_review: FinalReviewResult,
        output_path: Path,
    ) -> tuple[str, IntegratedSvgRepairResult, str]:
        repair_result, repair_raw = self.workflow_agents.fusion.repair_worker.run(
            copied_input_path=copied_input_path,
            merged_svg=merged_svg,
            final_review=final_review,
            svg_file_path=output_path,
        )
        return repair_result.repaired_svg, repair_result, repair_raw

    def _review_final_svg(
        self,
        *,
        copied_input_path: Path,
        merged_svg: str,
        checklist: dict,
    ) -> tuple[FinalReviewResult, str]:
        review_dir = self.root_output_dir / "review_assets"
        review_dir.mkdir(parents=True, exist_ok=True)
        svg_file_name = "merged-final-review.svg"
        svg_path = review_dir / svg_file_name
        png_path = review_dir / "merged-final-review.png"
        _, rendered_svg_path, render_result = write_svg_review_artifacts(
            svg_text=merged_svg,
            svg_path=svg_path,
            png_path=png_path,
        )
        self._record_written_file(svg_path, kind="svg")
        if rendered_svg_path is not None:
            self._record_written_file(rendered_svg_path, kind="png")
        else:
            error_path = png_path.with_suffix(".render_error.txt")
            error_path.write_text(
                "\n".join(
                    [
                        "scope: legacy-full-svg",
                        f"svg_path: {svg_path}",
                        f"png_path: {png_path}",
                        f"renderer: {render_result.renderer or '-'}",
                        f"error: {render_result.error or '-'}",
                        "stderr:",
                        render_result.stderr or "-",
                    ]
                ),
                encoding="utf-8",
            )
            self._record_written_file(error_path, kind="txt")
            raise SvgPreviewRenderError(
                scope="legacy-full-svg",
                svg_path=svg_path,
                png_path=png_path,
                error_path=error_path,
                render_result=render_result,
            )
        return DebugFinalReviewWorkerAgent(self).run(
            copied_input_path=copied_input_path,
            checklist=checklist,
            merged_svg=merged_svg,
            rendered_svg_path=rendered_svg_path,
            svg_file_path=svg_path,
            svg_file_name=svg_file_name,
        )
