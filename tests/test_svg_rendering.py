from pathlib import Path

import pytest

from deepagents_template.error_reporting import build_failure_diagnostic_from_exception
from deepagents_template.schemas import ExecutionEvent, ExecutionRun
from deepagents_template.utils import svg_rendering
from deepagents_template.utils.svg_rendering import SvgPreviewRenderError, SvgRenderResult, write_svg_review_artifacts
from deepagents_template.workflow_orchestration.base import BaseWorkflowAgent


def test_svg_review_artifacts_render_png(tmp_path: Path) -> None:
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'
    svg_path = tmp_path / "preview.svg"
    png_path = tmp_path / "preview.png"

    written_svg, written_png, result = write_svg_review_artifacts(
        svg_text=svg,
        svg_path=svg_path,
        png_path=png_path,
    )

    assert written_svg == svg_path
    assert result.ok
    assert written_png == png_path
    assert png_path.is_file()


def test_svg_review_artifacts_reports_renderer_failure(monkeypatch, tmp_path: Path) -> None:
    failure = SvgRenderResult(ok=False, png_path=None, renderer="test-renderer", error="boom", stderr="details")
    monkeypatch.setattr(svg_rendering, "render_svg_file_to_png_detailed", lambda *_args: failure)
    svg_path = tmp_path / "preview.svg"
    png_path = tmp_path / "preview.png"

    written_svg, written_png, result = write_svg_review_artifacts(
        svg_text="<svg/>",
        svg_path=svg_path,
        png_path=png_path,
    )

    assert written_svg == svg_path
    assert written_png is None
    assert result == failure


def test_base_agent_stops_on_svg_render_failure(monkeypatch, tmp_path: Path) -> None:
    failure = SvgRenderResult(ok=False, png_path=None, renderer="test-renderer", error="boom", stderr="details")
    monkeypatch.setattr(svg_rendering, "render_svg_file_to_png_detailed", lambda *_args: failure)

    class PipelineStub:
        def __init__(self) -> None:
            self.files = []
            self.events = []

        def _record_written_file(self, path, *, kind):
            self.files.append((Path(path), kind))

        def _push_event(self, stage, title, detail, payload=None, status=None, level="info", trace_stage=None):
            self.events.append(
                {
                    "stage": stage,
                    "title": title,
                    "detail": detail,
                    "payload": payload,
                    "status": status,
                    "level": level,
                    "trace_stage": trace_stage,
                }
            )

    pipeline = PipelineStub()
    agent = BaseWorkflowAgent(pipeline)
    svg_path = tmp_path / "region-preview.svg"
    png_path = tmp_path / "region-preview.png"

    with pytest.raises(SvgPreviewRenderError) as exc_info:
        agent._write_region_review_assets(
            region={"region_id": "r1", "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}},
            svg_fragment='<rect x="0" y="0" width="10" height="10"/>',
            svg_path=svg_path,
            png_path=png_path,
        )

    assert png_path.with_suffix(".render_error.txt").is_file()
    assert exc_info.value.error_path == png_path.with_suffix(".render_error.txt")
    assert any(event["stage"] == "svg-render" and event["level"] == "error" for event in pipeline.events)


def test_failure_diagnostic_includes_svg_render_error_log(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "run"
    error_path = artifact_dir / "intermediate" / "regions" / "r1" / "preview.render_error.txt"
    error_path.parent.mkdir(parents=True)
    error_path.write_text("boom", encoding="utf-8")
    render_result = SvgRenderResult(ok=False, png_path=None, renderer="test-renderer", error="boom", stderr="details")
    exc = SvgPreviewRenderError(
        scope="region:r1",
        svg_path=artifact_dir / "preview.svg",
        png_path=artifact_dir / "preview.png",
        error_path=error_path,
        render_result=render_result,
    )
    run = ExecutionRun(
        run_id="run-1",
        mode="invoke",
        project_name="test run",
        status="running",
        current_stage="refine",
        artifact_dir=str(artifact_dir),
        events=[
            ExecutionEvent(
                stage="svg-render",
                title="SVG preview render failed",
                detail="failed",
                level="error",
                payload={"error_path": str(error_path)},
            )
        ],
    )

    diagnostic = build_failure_diagnostic_from_exception(
        exc,
        run=run,
        terminal_stage="failed",
        artifact_dir=str(artifact_dir),
        failure_stage="refine",
    )

    assert diagnostic.error_type == "SvgPreviewRenderError"
    assert any(item.kind == "render-error" and item.relative_path.endswith("preview.render_error.txt") for item in diagnostic.artifact_hints)
