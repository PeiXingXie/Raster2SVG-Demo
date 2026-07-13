"""Explicit debug-review service kept outside the default runtime object graph."""

from __future__ import annotations

import json
from pathlib import Path

from deepagents_template.config import get_settings
from deepagents_template.debug_review.workers import (
    DebugFinalReviewWorkerAgent,
    DebugObjectReviewWorkerAgent,
    DebugRegionReviewWorkerAgent,
)
from deepagents_template.modeling.executor import MultimodalJsonCaller
from deepagents_template.resume import load_request_from_run_dir
from deepagents_template.schemas import (
    DebugReviewArtifacts,
    DebugReviewRequest,
    DebugReviewResponse,
    ObjectCandidate,
    RegionRecognitionResult,
)
from deepagents_template.utils.svg_rendering import write_svg_review_artifacts, wrap_svg_fragment


class _DebugPipelineContext:
    """Minimal pipeline-like context for explicit debug review workers."""

    def __init__(self, *, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.root_intermediate_dir = run_dir / "intermediate"
        self.root_output_dir = run_dir / "output"
        self.supervisor_memory_enabled = False
        request = load_request_from_run_dir(run_dir)
        settings = get_settings()
        self.user_message = settings.resolved_user_input(request.message)
        api_provider = settings.resolved_api_provider(request.api_provider)
        api_key = settings.resolved_api_key(request.api_key)
        base_url = settings.resolved_base_url(request.base_url)
        api_format = settings.resolved_api_format(request.api_format)
        max_retries = settings.resolved_max_retries(request.max_retries)
        self.region_caller = MultimodalJsonCaller(
            settings.resolved_subagent_model(request.subagent_model),
            api_key=api_key,
            base_url=base_url,
            max_retries=max_retries,
            api_provider=api_provider,
            api_format=api_format,
        )
        self.final_caller = MultimodalJsonCaller(
            settings.resolved_agent_model(request.agent_model),
            api_key=api_key,
            base_url=base_url,
            max_retries=max_retries,
            api_provider=api_provider,
            api_format=api_format,
        )

    def _write_json(self, path: Path, payload) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _record_written_file(self, path: Path, *, kind: str) -> None:  # noqa: ARG002
        return


class DebugReviewService:
    """Runs standalone review workers only when explicitly requested."""

    def __init__(self, *, artifact_store, thread, run) -> None:
        self.artifact_store = artifact_store
        self.thread = thread
        self.run = run

    def execute(self, payload: DebugReviewRequest) -> DebugReviewResponse:
        run_dir = self.artifact_store.resolve_run_dir(self.run.artifact_dir)
        if run_dir is None:
            raise FileNotFoundError("Run artifact directory was not found.")
        pipeline = _DebugPipelineContext(run_dir=run_dir)
        if payload.scope == "region":
            return self._execute_region(pipeline=pipeline, run_dir=run_dir, payload=payload)
        if payload.scope == "object":
            return self._execute_object(pipeline=pipeline, run_dir=run_dir, payload=payload)
        return self._execute_fusion(pipeline=pipeline, run_dir=run_dir, payload=payload)

    @staticmethod
    def _load_json(path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _load_text(path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def _execute_region(self, *, pipeline: _DebugPipelineContext, run_dir: Path, payload: DebugReviewRequest) -> DebugReviewResponse:
        if not payload.region_id:
            raise ValueError("region_id is required for region debug review.")
        region_dir = run_dir / "intermediate" / "regions" / payload.region_id
        result_path = region_dir / "final_result.json"
        if not result_path.is_file():
            result_path = region_dir / "initial_result.json"
        result_payload = self._load_json(result_path)
        review_assets_dir = run_dir / "output" / "debug_review" / "region" / payload.region_id
        review_assets_dir.mkdir(parents=True, exist_ok=True)

        region = result_payload["region"]
        checklist = self._load_json(run_dir / "intermediate" / "checklist.json") if (run_dir / "intermediate" / "checklist.json").is_file() else []
        recognition = RegionRecognitionResult.model_validate(result_payload["recognition"])
        crop_path = region_dir / "crop.png"
        svg_text = self._load_text(region_dir / "final_region_elements.svgfrag") if (region_dir / "final_region_elements.svgfrag").is_file() else result_payload["initial_svg_elements"]
        svg_path = review_assets_dir / f"region-{payload.region_id}-debug-review.svg"
        png_path = review_assets_dir / f"region-{payload.region_id}-debug-review.png"
        wrapped_svg = wrap_svg_fragment(
            svg_text,
            view_box=(
                int(region["bbox"]["x"]),
                int(region["bbox"]["y"]),
                max(int(region["bbox"]["width"]), 1),
                max(int(region["bbox"]["height"]), 1),
            ),
        )
        _, rendered_svg_path = write_svg_review_artifacts(svg_text=wrapped_svg, svg_path=svg_path, png_path=png_path)
        review, raw_text = DebugRegionReviewWorkerAgent(pipeline).run(
            crop_path=crop_path,
            region=region,
            checklist=checklist,
            recognition=recognition,
            proposed_svg_elements=svg_text,
            rendered_svg_path=rendered_svg_path,
            svg_file_path=svg_path,
            svg_file_name=svg_path.name,
        )
        review_json_path = review_assets_dir / "review.json"
        review_raw_path = review_assets_dir / "review_raw.txt"
        pipeline._write_json(review_json_path, review.model_dump(mode="json"))
        pipeline._write_text(review_raw_path, raw_text)
        return DebugReviewResponse(
            run_id=self.run.run_id,
            scope="region",
            region_id=payload.region_id,
            artifacts=DebugReviewArtifacts(
                crop_path=str(crop_path),
                rendered_preview_path=str(rendered_svg_path) if rendered_svg_path is not None else None,
                svg_file_path=str(svg_path),
                review_json_path=str(review_json_path),
                review_raw_path=str(review_raw_path),
            ),
            review=review.model_dump(mode="json"),
            raw_text=raw_text,
        )

    def _execute_object(self, *, pipeline: _DebugPipelineContext, run_dir: Path, payload: DebugReviewRequest) -> DebugReviewResponse:
        if not payload.region_id or not payload.object_id:
            raise ValueError("region_id and object_id are required for object debug review.")
        region_dir = run_dir / "intermediate" / "regions" / payload.region_id
        result_path = region_dir / "final_result.json"
        if not result_path.is_file():
            result_path = region_dir / "initial_result.json"
        result_payload = self._load_json(result_path)
        recognition = RegionRecognitionResult.model_validate(result_payload["recognition"])
        object_lookup = {obj.object_id: obj for obj in recognition.recognized_objects}
        obj = object_lookup.get(payload.object_id)
        if obj is None:
            raise FileNotFoundError(f"Object {payload.object_id} was not found in region {payload.region_id}.")
        object_dir = region_dir / "objects" / payload.object_id
        crop_path = object_dir / "crop.png"
        svg_fragment_path = object_dir / "final_object_elements.svgfrag"
        if not svg_fragment_path.is_file():
            raise FileNotFoundError(f"Object SVG artifact was not found for {payload.object_id}.")
        svg_text = self._load_text(svg_fragment_path)
        review_assets_dir = run_dir / "output" / "debug_review" / "object" / payload.region_id / payload.object_id
        review_assets_dir.mkdir(parents=True, exist_ok=True)
        region = result_payload["region"]
        svg_path = review_assets_dir / f"object-{payload.object_id}-debug-review.svg"
        png_path = review_assets_dir / f"object-{payload.object_id}-debug-review.png"
        wrapped_svg = wrap_svg_fragment(
            svg_text,
            view_box=(
                int(obj.bbox.x if obj.bbox else 0),
                int(obj.bbox.y if obj.bbox else 0),
                max(int(obj.bbox.width if obj.bbox else 1), 1),
                max(int(obj.bbox.height if obj.bbox else 1), 1),
            ),
        )
        _, rendered_svg_path = write_svg_review_artifacts(svg_text=wrapped_svg, svg_path=svg_path, png_path=png_path)
        failed_items = None
        object_history_path = object_dir / "object_history.json"
        if object_history_path.is_file():
            object_history = self._load_json(object_history_path)
            issue = object_history.get("issue")
            if issue:
                failed_items = [
                    {
                        "issue_family": issue.get("issue_family"),
                        "criterion": issue.get("criterion", ""),
                        "reason": issue.get("reason", ""),
                    }
                ]
        review, raw_text = DebugObjectReviewWorkerAgent(pipeline).run(
            object_crop_path=crop_path,
            obj=obj,
            object_svg=svg_text,
            failed_items=failed_items,
            rendered_svg_path=rendered_svg_path,
            svg_file_path=svg_path,
            svg_file_name=svg_path.name,
        )
        review_json_path = review_assets_dir / "review.json"
        review_raw_path = review_assets_dir / "review_raw.txt"
        pipeline._write_json(review_json_path, review.model_dump(mode="json"))
        pipeline._write_text(review_raw_path, raw_text)
        return DebugReviewResponse(
            run_id=self.run.run_id,
            scope="object",
            region_id=payload.region_id,
            object_id=payload.object_id,
            artifacts=DebugReviewArtifacts(
                crop_path=str(crop_path),
                rendered_preview_path=str(rendered_svg_path) if rendered_svg_path is not None else None,
                svg_file_path=str(svg_path),
                review_json_path=str(review_json_path),
                review_raw_path=str(review_raw_path),
            ),
            review=review.model_dump(mode="json"),
            raw_text=raw_text,
        )

    def _execute_fusion(self, *, pipeline: _DebugPipelineContext, run_dir: Path, payload: DebugReviewRequest) -> DebugReviewResponse:
        checklist = self._load_json(run_dir / "intermediate" / "checklist.json") if (run_dir / "intermediate" / "checklist.json").is_file() else []
        source_candidates = [path for path in (run_dir / "input").iterdir() if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
        if not source_candidates:
            raise FileNotFoundError("No copied input image was found for fusion debug review.")
        source_image_path = source_candidates[0]
        merged_svg_path = run_dir / "output" / "final.svg"
        merged_svg = self._load_text(merged_svg_path)
        review_assets_dir = run_dir / "output" / "debug_review" / "fusion"
        review_assets_dir.mkdir(parents=True, exist_ok=True)
        svg_path = review_assets_dir / "merged-final-debug-review.svg"
        png_path = review_assets_dir / "merged-final-debug-review.png"
        _, rendered_svg_path = write_svg_review_artifacts(svg_text=merged_svg, svg_path=svg_path, png_path=png_path)
        review, raw_text = DebugFinalReviewWorkerAgent(pipeline).run(
            copied_input_path=source_image_path,
            checklist=checklist,
            merged_svg=merged_svg,
            rendered_svg_path=rendered_svg_path,
            svg_file_path=svg_path,
            svg_file_name=svg_path.name,
        )
        review_json_path = review_assets_dir / "review.json"
        review_raw_path = review_assets_dir / "review_raw.txt"
        pipeline._write_json(review_json_path, review.model_dump(mode="json"))
        pipeline._write_text(review_raw_path, raw_text)
        return DebugReviewResponse(
            run_id=self.run.run_id,
            scope="fusion",
            artifacts=DebugReviewArtifacts(
                source_image_path=str(source_image_path),
                rendered_preview_path=str(rendered_svg_path) if rendered_svg_path is not None else None,
                svg_file_path=str(svg_path),
                review_json_path=str(review_json_path),
                review_raw_path=str(review_raw_path),
            ),
            review=review.model_dump(mode="json"),
            raw_text=raw_text,
        )
