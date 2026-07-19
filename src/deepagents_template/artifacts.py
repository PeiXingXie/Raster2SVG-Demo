"""Overview: Artifact directory management, file discovery, and preview assembly."""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from deepagents_template.atomic_files import atomic_write_text, read_text_with_retry
from deepagents_template.config import get_settings
from deepagents_template.resume import load_run_state, write_run_state
from deepagents_template.schemas import ExecutionRun, ThreadState
from deepagents_template.schemas import FailureDiagnostic
from deepagents_template.svg_utils import merge_svg, normalize_svg


ARTIFACT_KIND_BY_SUFFIX = {
    ".svg": "svg",
    ".svgfrag": "svgfrag",
    ".png": "png",
    ".jpg": "jpg",
    ".jpeg": "jpeg",
    ".webp": "webp",
    ".gif": "gif",
    ".bmp": "bmp",
    ".json": "json",
    ".md": "md",
    ".txt": "txt",
}

PREVIEWABLE_KINDS = {"svg", "png", "jpg", "jpeg", "webp", "gif", "bmp"}
RUN_DIR_SLUG_MAX_LENGTH = 24


def _infer_overlay_object_bbox_space(
    region_bbox: dict,
    object_bbox: dict,
    explicit_space: str | None,
) -> str:
    if explicit_space in {"global", "region_local"}:
        return explicit_space

    try:
        x = int(object_bbox.get("x", 0))
        y = int(object_bbox.get("y", 0))
        width = int(object_bbox.get("width", 0))
        height = int(object_bbox.get("height", 0))
        region_x = int(region_bbox.get("x", 0))
        region_y = int(region_bbox.get("y", 0))
        region_width = int(region_bbox.get("width", 0))
        region_height = int(region_bbox.get("height", 0))
    except (TypeError, ValueError):
        return "global"

    valid_extent = width > 0 and height > 0 and region_width > 0 and region_height > 0
    if not valid_extent:
        return "global"

    fits_global_region = (
        x >= region_x
        and y >= region_y
        and x + width <= region_x + region_width
        and y + height <= region_y + region_height
    )
    if fits_global_region:
        return "global"

    fits_region_local = x >= 0 and y >= 0 and x + width <= region_width and y + height <= region_height
    if fits_region_local:
        return "region_local"
    return "global"


def slugify_project_name(name: str, *, max_length: int | None = None) -> str:
    normalized = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "-", name.strip())
    normalized = normalized.strip("-")
    if max_length is not None and max_length > 0:
        normalized = normalized[:max_length].strip("-")
    return normalized or "run"


def derive_project_name(explicit_name: str | None, fallback_message: str | None) -> str:
    if explicit_name and explicit_name.strip():
        return explicit_name.strip()
    if fallback_message and fallback_message.strip():
        compact = " ".join(fallback_message.strip().split())
        return compact[:48]
    return "agent-run"


def derive_project_name_from_image(explicit_name: str | None, image_path: str | None, fallback_message: str | None) -> str:
    if explicit_name and explicit_name.strip():
        return explicit_name.strip()
    if image_path and image_path.strip():
        return Path(image_path).stem
    return derive_project_name(None, fallback_message)


class ArtifactStore:
    """Persist run metadata and outputs under a unified artifacts directory."""

    def __init__(self) -> None:
        self.root = get_settings().resolved_run_artifacts_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def create_run_dir(self) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        suffix = 1
        while True:
            run_id = timestamp if suffix == 1 else f"{timestamp}-{suffix}"
            candidate = self.root / run_id
            try:
                candidate.mkdir(parents=True, exist_ok=False)
                return candidate
            except FileExistsError:
                suffix += 1

    def write_metadata(self, thread: ThreadState) -> None:
        run = thread.current_run
        if run is None or not run.artifact_dir:
            return
        artifact_dir = Path(run.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        metadata = {
            "thread_id": thread.thread_id,
            "pending_approval": (
                thread.pending_approval.model_dump(mode="json") if thread.pending_approval else None
            ),
            "current_run": run.model_dump(mode="json"),
            "messages": [message.model_dump(mode="json") for message in thread.messages],
            "recent_runs": [recent_run.model_dump(mode="json") for recent_run in thread.recent_runs],
        }
        atomic_write_text(
            artifact_dir / "metadata.json",
            json.dumps(metadata, ensure_ascii=False, indent=2),
        )

    def write_output(self, run: ExecutionRun, content: str) -> None:
        if not run.artifact_dir:
            return
        artifact_dir = Path(run.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        primary_markdown = artifact_dir / "output" / "report.md"
        primary_json = artifact_dir / "output" / "report.json"
        compatibility_markdown = artifact_dir / "output.md"
        atomic_write_text(
            compatibility_markdown,
            "\n".join(
                [
                    "# Compatibility Output",
                    "",
                    "Primary report files for this run:",
                    f"- Markdown report: `{primary_markdown.relative_to(artifact_dir)}`",
                    f"- Structured report: `{primary_json.relative_to(artifact_dir)}`",
                    "",
                    f"- Run ID: `{run.run_id}`",
                    f"- Project: `{run.project_name}`",
                    f"- Status: `{run.status}`",
                    f"- Stage: `{run.current_stage}`",
                    "",
                    "This file is kept as a lightweight compatibility entrypoint.",
                    "Open the primary report files above for the full report body.",
                    "",
                ]
            ),
        )
        payload = {
            "run_id": run.run_id,
            "owner_thread_id": run.owner_thread_id,
            "project_name": run.project_name,
            "status": run.status,
            "current_stage": run.current_stage,
            "duration_ms": run.duration_ms,
            "primary_report_markdown_path": str(primary_markdown.relative_to(artifact_dir)).replace("/", "\\"),
            "primary_report_json_path": str(primary_json.relative_to(artifact_dir)).replace("/", "\\"),
            "compatibility_markdown_path": str(compatibility_markdown.relative_to(artifact_dir)).replace("/", "\\"),
            "content_preview": content[:400] if content else "",
        }
        atomic_write_text(
            artifact_dir / "output.json",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )

    def _run_directory_candidates(self) -> list[tuple[float, Path]]:
        candidates: list[tuple[float, Path]] = []
        with os.scandir(self.root) as entries:
            for entry in entries:
                if not entry.is_dir() or entry.name.startswith((".", "_")):
                    continue
                run_dir = Path(entry.path)
                metadata_path = run_dir / "metadata.json"
                output_path = run_dir / "output.json"
                timestamp_path = metadata_path if metadata_path.is_file() else output_path
                if not timestamp_path.is_file():
                    continue
                try:
                    modified_at = timestamp_path.stat().st_mtime
                except OSError:
                    continue
                candidates.append((modified_at, run_dir))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates

    @staticmethod
    def _run_matches_history_query(run: ExecutionRun, status_filter: str, search: str) -> bool:
        normalized_status = status_filter.strip().lower()
        if normalized_status != "all":
            run_status = str(run.status or "").lower()
            if normalized_status == "paused":
                if not run_status.startswith("paused"):
                    return False
            elif run_status != normalized_status:
                return False
        normalized_search = search.strip().lower()
        if not normalized_search:
            return True
        searchable = " ".join(
            str(value)
            for value in (
                run.project_name,
                run.status,
                run.current_stage,
                run.run_id,
            )
            if value
        ).lower()
        return normalized_search in searchable

    def list_runs_page(
        self,
        *,
        page: int = 1,
        page_size: int = 6,
        status_filter: str = "all",
        search: str = "",
        sort: str = "updated_desc",
    ) -> tuple[list[ExecutionRun], int | None, int | None, bool]:
        """Load only the requested History page unless global sorting requires all runs."""
        resolved_page = max(1, page)
        resolved_page_size = max(1, page_size)
        offset = (resolved_page - 1) * resolved_page_size
        candidates = self._run_directory_candidates()

        if sort in {"name_asc", "status_asc"}:
            matching_runs = []
            for _, run_dir in candidates:
                run = self.load_execution_run(run_dir)
                if run is not None and self._run_matches_history_query(run, status_filter, search):
                    matching_runs.append(run)
            if sort == "name_asc":
                matching_runs.sort(key=lambda run: (run.project_name or "").casefold())
            else:
                matching_runs.sort(
                    key=lambda run: (
                        str(run.status or "").casefold(),
                        -(run.updated_at or run.finished_at or run.started_at).timestamp(),
                    )
                )
            total = len(matching_runs)
            total_pages = max(1, (total + resolved_page_size - 1) // resolved_page_size)
            page_runs = matching_runs[offset : offset + resolved_page_size]
            return page_runs, total, total_pages, offset + len(page_runs) < total

        page_runs: list[ExecutionRun] = []
        matched_count = 0
        has_more = False
        exhausted = True
        for _, run_dir in candidates:
            run = self.load_execution_run(run_dir)
            if run is None or not self._run_matches_history_query(run, status_filter, search):
                continue
            matched_count += 1
            if matched_count <= offset:
                continue
            if len(page_runs) < resolved_page_size:
                page_runs.append(run)
                continue
            has_more = True
            exhausted = False
            break

        default_listing = status_filter == "all" and not search.strip()
        if default_listing:
            total = len(candidates)
            total_pages = max(1, (total + resolved_page_size - 1) // resolved_page_size)
            has_more = offset + len(page_runs) < total
        elif exhausted:
            total = matched_count
            total_pages = max(1, (total + resolved_page_size - 1) // resolved_page_size)
        else:
            total = None
            total_pages = None
        return page_runs, total, total_pages, has_more

    def list_recent_runs(self, limit: int = 20) -> list[ExecutionRun]:
        runs, _, _, _ = self.list_runs_page(page=1, page_size=limit)
        return runs

    def find_run_by_id(self, run_id: str) -> ExecutionRun | None:
        for _, run_dir in self._run_directory_candidates():
            run = self.load_execution_run(run_dir)
            if run is None:
                continue
            if run.run_id == run_id:
                return run
        return None

    def update_run_project_name(self, run: ExecutionRun, project_name: str) -> ExecutionRun:
        run_dir = self.resolve_run_dir(run.artifact_dir)
        if run_dir is None:
            raise FileNotFoundError("Run artifact directory was not found.")
        now = datetime.now(UTC)
        updated_run = run.model_copy(update={"project_name": project_name, "updated_at": now})
        metadata_path = run_dir / "metadata.json"
        if metadata_path.exists():
            try:
                metadata = json.loads(read_text_with_retry(metadata_path, encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                metadata = {}
        else:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["current_run"] = updated_run.model_dump(mode="json")
        recent_runs = []
        for item in metadata.get("recent_runs") or []:
            if not isinstance(item, dict):
                continue
            if item.get("run_id") == updated_run.run_id:
                item = dict(item)
                item["project_name"] = project_name
                item["updated_at"] = now.isoformat()
            recent_runs.append(item)
        metadata["recent_runs"] = recent_runs
        atomic_write_text(metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2))

        output_path = run_dir / "output.json"
        if output_path.exists():
            try:
                output_payload = json.loads(read_text_with_retry(output_path, encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                output_payload = None
            if isinstance(output_payload, dict):
                output_payload["project_name"] = project_name
                atomic_write_text(output_path, json.dumps(output_payload, ensure_ascii=False, indent=2))

        run_state = load_run_state(run_dir)
        if run_state is not None:
            run_state.project_name = project_name
            write_run_state(run_dir, run_state)
        return updated_run

    def delete_run_dir(self, artifact_dir: str | None) -> Path:
        run_dir = self.resolve_run_dir(artifact_dir)
        if run_dir is None:
            raise FileNotFoundError("Run artifact directory was not found.")
        if run_dir == self.root.resolve():
            raise FileNotFoundError("Run artifact directory was not found.")
        shutil.rmtree(run_dir)
        return run_dir

    def delete_run(self, run: ExecutionRun) -> Path:
        return self.delete_run_dir(run.artifact_dir)

    def load_execution_run(self, run_dir: Path) -> ExecutionRun | None:
        metadata_path = run_dir / "metadata.json"
        if metadata_path.exists():
            try:
                payload = json.loads(read_text_with_retry(metadata_path, encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("current_run"), dict):
                run_payload = dict(payload["current_run"])
                run_payload["artifact_dir"] = str(run_dir)
                run_payload.setdefault("owner_thread_id", payload.get("thread_id"))
                try:
                    if isinstance(run_payload.get("failure_diagnostic"), dict):
                        run_payload["failure_diagnostic"] = FailureDiagnostic.model_validate(run_payload["failure_diagnostic"])
                    return ExecutionRun.model_validate(run_payload)
                except Exception:
                    pass

        output_path = run_dir / "output.json"
        if output_path.exists():
            try:
                payload = json.loads(read_text_with_retry(output_path, encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict):
                stat = output_path.stat()
                timestamp = datetime.fromtimestamp(stat.st_mtime, UTC)
                run_id = str(payload.get("run_id") or run_dir.name)
                failure_diagnostic = payload.get("failure_diagnostic")
                return ExecutionRun(
                    run_id=run_id,
                    owner_thread_id=payload.get("owner_thread_id"),
                    mode="invoke",
                    status=str(payload.get("status") or "completed"),
                    current_stage=str(payload.get("current_stage") or "completed"),
                    failure_stage=payload.get("failure_stage"),
                    started_at=timestamp,
                    current_stage_started_at=timestamp,
                    updated_at=timestamp,
                    finished_at=timestamp,
                    duration_ms=payload.get("duration_ms"),
                    current_stage_duration_ms=payload.get("duration_ms"),
                    error=None,
                    failure_diagnostic=FailureDiagnostic.model_validate(failure_diagnostic) if isinstance(failure_diagnostic, dict) else None,
                    project_name=str(payload.get("project_name") or run_dir.name),
                    artifact_dir=str(run_dir),
                    worker_statuses=[],
                    events=[],
                )
        return None

    def resolve_run_dir(self, artifact_dir: str | None) -> Path | None:
        if not artifact_dir:
            return None
        candidate = Path(artifact_dir)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError:
            return None
        try:
            resolved.relative_to(self.root.resolve())
        except ValueError:
            return None
        return resolved

    def resolve_relative_path(self, artifact_dir: str | None, relative_path: str) -> Path | None:
        run_dir = self.resolve_run_dir(artifact_dir)
        if run_dir is None:
            return None
        normalized = relative_path.replace("/", "\\").strip("\\/")
        if not normalized:
            return None
        candidate = (run_dir / normalized).resolve()
        try:
            candidate.relative_to(run_dir)
        except ValueError:
            return None
        if not candidate.is_file():
            return None
        return candidate

    def list_files(self, artifact_dir: str | None) -> list[dict]:
        run_dir = self.resolve_run_dir(artifact_dir)
        if run_dir is None:
            return []
        log_file = run_dir / "logs" / "files.json"
        if log_file.exists():
            try:
                records = json.loads(read_text_with_retry(log_file, encoding="utf-8-sig"))
                if isinstance(records, list):
                    return sorted(
                        [
                            item
                            for item in records
                            if isinstance(item, dict) and item.get("relative_path")
                        ],
                        key=lambda item: item["relative_path"],
                    )
            except json.JSONDecodeError:
                pass

        records: list[dict] = []
        for path in sorted(run_dir.rglob("*")):
            if not path.is_file() or path.name == ".shape-studio.lock":
                continue
            stat = path.stat()
            relative_path = str(path.relative_to(run_dir))
            records.append(
                {
                    "timestamp": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                    "kind": self._kind_for_path(path),
                    "path": str(path),
                    "relative_path": relative_path,
                    "size_bytes": stat.st_size,
                }
            )
        return records

    def load_json(self, artifact_dir: str | None, relative_path: str) -> dict | None:
        file_path = self.resolve_relative_path(artifact_dir, relative_path)
        if file_path is None:
            return None
        try:
            payload = json.loads(read_text_with_retry(file_path, encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def load_payload(self, artifact_dir: str | None, relative_path: str) -> dict | list | None:
        file_path = self.resolve_relative_path(artifact_dir, relative_path)
        if file_path is None:
            return None
        try:
            return json.loads(read_text_with_retry(file_path, encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return None

    def find_preview_targets(self, artifact_dir: str | None) -> dict[str, str | None]:
        run_dir = self.resolve_run_dir(artifact_dir)
        if run_dir is None:
            return {
                "input_image": None,
                "output_svg": None,
                "output_png": None,
                "initial_svg": None,
            }

        input_image = self._find_first_existing(
            run_dir,
            "input/*.png",
            "input/*.jpg",
            "input/*.jpeg",
            "input/*.webp",
            "input/*.gif",
            "input/*.bmp",
        )
        output_svg = self._find_first_existing(run_dir, "output/final.svg", "output/*.svg")
        output_png = self._find_first_existing(run_dir, "output/final.png", "output/*.png")
        initial_svg = self._find_first_existing(run_dir, "intermediate/initial.svg", "intermediate/*.svg")

        return {
            "input_image": self._to_relative(run_dir, input_image),
            "output_svg": self._to_relative(run_dir, output_svg),
            "output_png": self._to_relative(run_dir, output_png),
            "initial_svg": self._to_relative(run_dir, initial_svg),
        }

    def find_existing_history_previews(self, artifact_dir: str | None) -> dict[str, Path | None]:
        """Locate existing History previews without generating or modifying artifacts."""
        run_dir = self.resolve_run_dir(artifact_dir)
        if run_dir is None:
            return {"input": None, "output": None}

        input_preview = self._find_first_existing(
            run_dir,
            "input/*.png",
            "input/*.jpg",
            "input/*.jpeg",
            "input/*.webp",
            "input/*.gif",
            "input/*.bmp",
        )
        output_preview = self._find_first_existing(
            run_dir,
            "output/final.png",
            "output/final.svg",
            "output/*.png",
            "output/*.svg",
            "intermediate/initial.svg",
        )
        return {"input": input_preview, "output": output_preview}

    def build_region_overlays(self, artifact_dir: str | None) -> tuple[int | None, int | None, list[dict]]:
        regions_payload = self.load_payload(artifact_dir, "intermediate/regions.json")
        region_results_payload = self.load_payload(artifact_dir, "intermediate/region_results.json")
        input_metadata = self.load_json(artifact_dir, "input/input_metadata.json") or {}
        layout_payload = self.load_json(artifact_dir, "intermediate/layout_detection.json") or {}
        canvas_width = (
            input_metadata.get("width")
            or layout_payload.get("canvas_width")
        )
        canvas_height = (
            input_metadata.get("height")
            or layout_payload.get("canvas_height")
        )
        if not isinstance(regions_payload, list):
            return canvas_width, canvas_height, []

        region_results_by_id = {}
        if isinstance(region_results_payload, list):
            region_results_by_id = {
                item.get("region_id"): item
                for item in region_results_payload
                if isinstance(item, dict) and item.get("region_id")
            }
        run_dir = self.resolve_run_dir(artifact_dir)
        region_root = (run_dir / "intermediate" / "regions") if run_dir is not None else None

        overlays: list[dict] = []
        for region in regions_payload:
            if not isinstance(region, dict):
                continue
            bbox = region.get("bbox") or {}
            region_id = region.get("region_id")
            result = region_results_by_id.get(region_id, {})
            if not result and region_root is not None and region_id:
                region_dir = region_root / str(region_id)
                fallback_result = (
                    self._load_json_file(region_dir / "final_result.json")
                    or self._load_json_file(region_dir / "initial_result.json")
                )
                if isinstance(fallback_result, dict):
                    result = fallback_result
            retry_summary = result.get("retry_summary") or {}
            region_retry = retry_summary.get(f"region:{region_id}:repair") or {}
            recognition = result.get("recognition") or result.get("generation") or {}
            objects: list[dict] = []
            for obj in recognition.get("recognized_objects", []) or []:
                if not isinstance(obj, dict):
                    continue
                object_bbox = obj.get("bbox") or {}
                object_retry = retry_summary.get(f"object:{region_id}:{obj.get('object_id')}:repair") or {}
                objects.append(
                    {
                        "object_id": obj.get("object_id") or "",
                        "object_type": obj.get("object_type") or "",
                        "description": obj.get("description") or "",
                        "bbox": (
                            {
                                "x": int(object_bbox.get("x", 0)),
                                "y": int(object_bbox.get("y", 0)),
                                "width": int(object_bbox.get("width", 0)),
                                "height": int(object_bbox.get("height", 0)),
                            }
                            if object_bbox
                            else None
                        ),
                        "bbox_space": _infer_overlay_object_bbox_space(
                            bbox,
                            object_bbox,
                            obj.get("bbox_space"),
                        ),
                        "retry_limit": object_retry.get("limit"),
                        "retry_used": object_retry.get("used"),
                        "retry_exhausted": object_retry.get("exhausted"),
                    }
                )
            overlays.append(
                {
                    "region_id": region_id or "",
                    "description": region.get("description") or "",
                    "bbox": {
                        "x": int(bbox.get("x", 0)),
                        "y": int(bbox.get("y", 0)),
                        "width": int(bbox.get("width", 0)),
                        "height": int(bbox.get("height", 0)),
                    },
                    "bbox_space": "global",
                    "status": region.get("status"),
                    "objects": objects,
                    "retry_limit": region_retry.get("limit"),
                    "retry_used": region_retry.get("used"),
                    "retry_exhausted": result.get("retry_exhausted", region_retry.get("exhausted")),
                }
            )

        return canvas_width, canvas_height, overlays

    def build_output_frames(self, artifact_dir: str | None) -> list[dict]:
        run_dir = self.resolve_run_dir(artifact_dir)
        if run_dir is None:
            return []

        template_path = run_dir / "intermediate" / "template.svg"
        if not template_path.is_file():
            return []
        template_svg = read_text_with_retry(template_path)
        frame_dir = run_dir / "logs" / "view_frames"
        frame_dir.mkdir(parents=True, exist_ok=True)

        steps: list[dict] = []
        region_root = run_dir / "intermediate" / "regions"
        if region_root.is_dir():
            for region_dir in sorted(path for path in region_root.iterdir() if path.is_dir()):
                region_id = region_dir.name
                for path in sorted(region_dir.glob("region_svg_gen.svgfrag")):
                    steps.append(
                        {
                            "scope": "region-initial",
                            "region_id": region_id,
                            "title": f"Initial region build {region_id}",
                            "iteration": 0,
                            "fragment_path": path,
                            "target_id": region_id,
                            "update_summary": self._region_initial_summary(region_dir),
                            "remaining_issues": self._region_review_issues(region_dir / "review_iter_0.json"),
                        }
                    )
                for path in sorted(region_dir.glob("region_object_aggregate_*.svgfrag")):
                    iteration = _extract_iteration(path.stem)
                    steps.append(
                        {
                            "scope": "object-aggregate",
                            "region_id": region_id,
                            "title": f"Object aggregation {region_id} · iter {iteration}",
                            "iteration": iteration,
                            "fragment_path": path,
                            "target_id": region_id,
                            "update_summary": self._region_object_aggregate_summary(region_dir, iteration),
                            "remaining_issues": self._region_review_issues(
                                region_dir / f"review_object_aggregate_{iteration}.json"
                            ),
                        }
                    )
                for path in sorted(region_dir.glob("region_svg_update_iter_*.svgfrag")):
                    iteration = _extract_iteration(path.stem)
                    steps.append(
                        {
                            "scope": "region-repair",
                            "region_id": region_id,
                            "title": f"Region repair {region_id} · iter {iteration}",
                            "iteration": iteration,
                            "fragment_path": path,
                            "target_id": region_id,
                            "update_summary": self._region_repair_summary(region_dir, iteration),
                            "remaining_issues": self._region_review_issues(region_dir / f"review_iter_{iteration}.json"),
                        }
                    )
                final_region_path = region_dir / "final_region_elements.svgfrag"
                if final_region_path.is_file():
                    steps.append(
                        {
                            "scope": "region-final",
                            "region_id": region_id,
                            "title": f"Final region state {region_id}",
                            "iteration": None,
                            "fragment_path": final_region_path,
                            "target_id": region_id,
                            "update_summary": [
                                "Captured the final persisted region SVG state after region/object loops."
                            ],
                            "remaining_issues": self._region_review_issues(region_dir / "review.json"),
                        }
                    )

        output_svg_path = run_dir / "output" / "final.svg"
        if output_svg_path.is_file():
            steps.append(
                {
                    "scope": "final-output",
                    "region_id": None,
                    "title": "Final merged SVG",
                    "iteration": None,
                    "fragment_path": output_svg_path,
                    "target_id": None,
                    "update_summary": self._integrated_output_summary(run_dir, "final"),
                    "remaining_issues": self._final_review_issues(run_dir / "output" / "final_review.json"),
                }
            )

        steps.sort(key=lambda item: (item["fragment_path"].stat().st_mtime, str(item["fragment_path"])))
        frames: list[dict] = []
        merged_regions: dict[str, str] = {}
        last_region_fragments: dict[str, str] = {}

        for index, step in enumerate(steps, start=1):
            fragment_path = step["fragment_path"]
            scope = step["scope"]
            frame_svg: str
            if scope == "final-output":
                frame_svg = normalize_svg(read_text_with_retry(fragment_path))
            else:
                region_id = step["region_id"]
                fragment_text = read_text_with_retry(fragment_path)
                last_region_fragments[region_id] = fragment_text
                merged_regions = dict(last_region_fragments)
                frame_svg = normalize_svg(merge_svg(template_svg, merged_regions))

            frame_name = f"{index:03d}_{slugify_project_name(step['title'])}.svg"
            frame_path = frame_dir / frame_name
            existing_text = read_text_with_retry(frame_path) if frame_path.is_file() else None
            if existing_text != frame_svg:
                atomic_write_text(frame_path, frame_svg)
            stat = frame_path.stat()
            frames.append(
                {
                    "frame_id": f"frame-{index}",
                    "title": step["title"],
                    "scope": scope,
                    "target_id": step["target_id"],
                    "iteration": step["iteration"],
                    "relative_path": str(frame_path.relative_to(run_dir)),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC),
                    "update_summary": step.get("update_summary") or [],
                    "remaining_issues": step.get("remaining_issues") or [],
                }
            )

        return frames

    def build_manual_adjustments(self, artifact_dir: str | None, output_frames: list[dict]) -> list[dict]:
        run_dir = self.resolve_run_dir(artifact_dir)
        if run_dir is None:
            return []
        manual_root = run_dir / "output" / "manual_adjustments"
        if not manual_root.is_dir():
            return []

        frames_by_id = {str(frame.get("frame_id")): frame for frame in output_frames if frame.get("frame_id")}
        versions: list[dict] = []
        for adjustment_dir in sorted(path for path in manual_root.iterdir() if path.is_dir()):
            manual_svg_path = adjustment_dir / "final_after_adjustment.svg"
            if not manual_svg_path.is_file():
                continue
            request_payload = self._load_json_file(adjustment_dir / "request.json")
            base_frame_id = request_payload.get("base_frame_id") if isinstance(request_payload, dict) else None
            base_adjustment_id = request_payload.get("base_adjustment_id") if isinstance(request_payload, dict) else None
            base_frame = frames_by_id.get(str(base_frame_id)) if base_frame_id else None
            base_adjustment_title = (
                f"Adjustment {str(base_adjustment_id).removeprefix('adjustment-')}" if base_adjustment_id else None
            )
            base_snapshot_path = adjustment_dir / "base_before_adjustment.svg"
            stat = manual_svg_path.stat()
            workflow_trace, adjustment_error = self.build_manual_workflow_trace(
                artifact_dir,
                adjustment_id=adjustment_dir.name,
            )
            versions.append(
                {
                    "adjustment_id": adjustment_dir.name,
                    "title": f"Adjustment {adjustment_dir.name.removeprefix('adjustment-')}",
                    "relative_path": str(manual_svg_path.relative_to(run_dir)),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC),
                    "base_frame_id": base_frame_id,
                    "base_adjustment_id": base_adjustment_id,
                    "base_title": base_adjustment_title or (base_frame.get("title") if base_frame else None),
                    "base_relative_path": (
                        str(base_snapshot_path.relative_to(run_dir))
                        if base_snapshot_path.is_file()
                        else base_frame.get("relative_path") if base_frame else None
                    ),
                    "workflow_trace": workflow_trace,
                    "adjustment_error": adjustment_error,
                }
            )

        versions.sort(key=lambda item: (item["modified_at"], item["adjustment_id"]))
        return versions

    def build_manual_workflow_trace(
        self,
        artifact_dir: str | None,
        adjustment_id: str | None = None,
    ) -> tuple[dict, dict | None]:
        run_dir = self.resolve_run_dir(artifact_dir)
        empty_trace = {
            "summary": {
                "status": "idle",
                "active_node_id": None,
                "regions_total": 0,
                "retrying_regions": 0,
                "blocked_regions": 0,
                "direct_accept_regions": 0,
                "total_duration_ms": None,
                "loop_iterations_total": 0,
            },
            "nodes": [],
        }
        if run_dir is None:
            return empty_trace, None
        manual_root = run_dir / "output" / "manual_adjustments"
        if not manual_root.is_dir():
            return empty_trace, None

        def adjustment_activity_mtime(path: Path) -> float:
            candidates = [
                path / "session_state.json",
                path / "error.json",
                path / "final_after_adjustment.svg",
                path / "request.json",
            ]
            mtimes = [item.stat().st_mtime for item in candidates if item.is_file()]
            return max(mtimes) if mtimes else path.stat().st_mtime

        adjustment_dirs = sorted(
            (path for path in manual_root.iterdir() if path.is_dir()),
            key=lambda item: (adjustment_activity_mtime(item), item.name),
        )
        if not adjustment_dirs:
            return empty_trace, None
        latest_dir = next((item for item in adjustment_dirs if item.name == adjustment_id), None) if adjustment_id else None
        if latest_dir is None:
            latest_dir = adjustment_dirs[-1]
        session_state = self._load_json_file(latest_dir / "session_state.json") or {}
        request_payload = self._load_json_file(latest_dir / "request.json") or {}
        error_payload = self._load_json_file(latest_dir / "error.json")
        if not isinstance(session_state, dict):
            session_state = {}

        mode = str(session_state.get("mode") or request_payload.get("mode") or "worker")
        status = str(session_state.get("status") or ("failed" if error_payload else "completed" if (latest_dir / "final_after_adjustment.svg").is_file() else "running"))
        current_step = str(session_state.get("current_step") or "prepare")
        current_iteration = int(session_state.get("current_iteration") or 0)
        steps = session_state.get("steps") or {}
        target_ids = session_state.get("target_ids") or []

        def step_entry(name: str) -> dict:
            entry = steps.get(name) if isinstance(steps, dict) else {}
            return entry if isinstance(entry, dict) else {}

        step_order = [
            ("prepare", "Prepare Target"),
            ("analyze", "Analyze Request"),
            ("edit", "Edit Pass"),
            ("review", "Review Result"),
            ("apply", "Apply Output"),
            ("complete", "Complete"),
        ]
        nodes: list[dict] = []
        active_node_id = None
        for step_name, label in step_order:
            if mode != "agent" and step_name in {"analyze", "review"}:
                continue
            entry = step_entry(step_name)
            node_status = str(entry.get("status") or "pending")
            if step_name == current_step and status == "running" and node_status in {"pending", "success"}:
                node_status = "running"
            if step_name == "complete" and status == "completed":
                node_status = "success"
            if step_name == current_step and status == "failed":
                node_status = "failed"
            summary = entry.get("summary")
            nodes.append(
                {
                    "node_id": f"manual:{latest_dir.name}:{step_name}",
                    "parent_node_id": None,
                    "label": label,
                    "kind": "terminal" if step_name == "complete" else "stage",
                    "status": node_status,
                    "summary": summary,
                    "target_type": "object" if target_ids else "run",
                    "target_id": ",".join(target_ids[:3]) if target_ids else None,
                    "started_at": entry.get("started_at"),
                    "ended_at": entry.get("ended_at"),
                    "meta": {"adjustment_id": latest_dir.name},
                }
            )
            if active_node_id is None and node_status in {"running", "retrying"}:
                active_node_id = f"manual:{latest_dir.name}:{step_name}"

        if mode == "agent":
            baseline_review = self._load_json_file(latest_dir / "review_iter_0.json")
            if isinstance(baseline_review, dict):
                baseline_status = "issue_detected" if baseline_review.get("remaining_issues") else "success"
                nodes.append(
                    {
                        "node_id": f"manual:{latest_dir.name}:review:0",
                        "parent_node_id": f"manual:{latest_dir.name}:review",
                        "label": "Baseline Review",
                        "kind": "loop",
                        "status": baseline_status,
                        "summary": baseline_review.get("summary") or "Captured baseline issues.",
                        "target_type": "run",
                        "target_id": None,
                        "iteration": 0,
                    }
                )
            iteration = 1
            while True:
                worker_path = latest_dir / f"worker_iter_{iteration}.json"
                review_path = latest_dir / f"review_iter_{iteration}.json"
                if not worker_path.is_file() and not review_path.is_file():
                    break
                review_payload = self._load_json_file(review_path) or {}
                iteration_status = "running" if iteration == current_iteration and status == "running" else "success"
                if isinstance(review_payload, dict):
                    if review_payload.get("remaining_issues"):
                        iteration_status = "retrying" if status == "running" else "issue_detected"
                    if review_payload.get("passed"):
                        iteration_status = "success"
                if status == "failed" and iteration == current_iteration:
                    iteration_status = "failed"
                nodes.append(
                    {
                        "node_id": f"manual:{latest_dir.name}:iter:{iteration}",
                        "parent_node_id": f"manual:{latest_dir.name}:edit",
                        "label": f"Iteration {iteration}",
                        "kind": "loop",
                        "status": iteration_status,
                        "summary": (review_payload.get("summary") if isinstance(review_payload, dict) else None) or f"Agent edit iteration {iteration}.",
                        "target_type": "run",
                        "target_id": None,
                        "iteration": iteration,
                        "meta": {"adjustment_id": latest_dir.name},
                    }
                )
                iteration += 1
        elif (latest_dir / "worker_pass.json").is_file():
            worker_pass = self._load_json_file(latest_dir / "worker_pass.json") or {}
            nodes.append(
                {
                    "node_id": f"manual:{latest_dir.name}:worker-pass",
                    "parent_node_id": f"manual:{latest_dir.name}:edit",
                    "label": "Worker Pass",
                    "kind": "loop",
                    "status": "failed" if status == "failed" and current_step == "edit" else ("success" if (latest_dir / "worker_pass.json").is_file() else "running"),
                    "summary": worker_pass.get("goal_summary") if isinstance(worker_pass, dict) else "Worker-mode adjustment pass.",
                    "target_type": "run",
                    "target_id": None,
                    "iteration": 1,
                    "meta": {"adjustment_id": latest_dir.name},
                }
            )

        if error_payload and isinstance(error_payload, dict):
            nodes.append(
                {
                    "node_id": f"manual:{latest_dir.name}:error",
                    "parent_node_id": f"manual:{latest_dir.name}:{current_step}",
                    "label": "Error",
                    "kind": "terminal",
                    "status": "failed",
                    "summary": error_payload.get("message") or "Manual adjustment failed.",
                    "target_type": "run",
                    "target_id": None,
                    "meta": {"adjustment_id": latest_dir.name, "error_type": error_payload.get("error_type")},
                }
            )

        trace = {
            "summary": {
                "status": status,
                "active_node_id": active_node_id,
                "regions_total": 0,
                "retrying_regions": max(current_iteration, 0) if status == "running" and mode == "agent" else 0,
                "blocked_regions": 0,
                "direct_accept_regions": 0,
                "total_duration_ms": None,
                "loop_iterations_total": max(current_iteration, 1 if mode != "agent" and (latest_dir / "worker_pass.json").is_file() else 0),
            },
            "nodes": nodes,
        }
        started_candidates = [node.get("started_at") for node in nodes if isinstance(node, dict) and node.get("started_at")]
        ended_candidates = [node.get("ended_at") for node in nodes if isinstance(node, dict) and node.get("ended_at")]
        if started_candidates:
            started_at = min(started_candidates)
            ended_at = max(ended_candidates) if ended_candidates else None
            if ended_at:
                trace["summary"]["total_duration_ms"] = max(
                    0,
                    int((datetime.fromisoformat(str(ended_at)) - datetime.fromisoformat(str(started_at))).total_seconds() * 1000),
                )
        return trace, error_payload if isinstance(error_payload, dict) else None

    def _region_initial_summary(self, region_dir: Path) -> list[str]:
        payload = self._load_json_file(region_dir / "region_svg_gen.json")
        if isinstance(payload, dict):
            notes = payload.get("generation_notes") or []
            if notes:
                return [str(item) for item in notes if item]
        return ["Generated the initial SVG fragment for this region."]

    def _region_repair_summary(self, region_dir: Path, iteration: int) -> list[str]:
        history = self._load_json_file(region_dir / "repair_history.json")
        if isinstance(history, list):
            for item in history:
                if not isinstance(item, dict) or item.get("iteration") != iteration:
                    continue
                repair = item.get("repair") or {}
                repairs_applied = repair.get("repairs_applied") or []
                if repairs_applied:
                    return [str(entry) for entry in repairs_applied if entry]
        return [f"Updated the region SVG during repair iteration {iteration}."]

    def _region_object_aggregate_summary(self, region_dir: Path, iteration: int) -> list[str]:
        history = self._load_json_file(region_dir / "object_history.json")
        if isinstance(history, list):
            object_ids = [
                item.get("object_id")
                for item in history
                if isinstance(item, dict) and item.get("object_id")
            ]
            if object_ids:
                return [
                    f"Reintegrated object-process outputs back into the region SVG (objects: {', '.join(object_ids[:6])})."
                ]
        return [f"Merged object-process outputs back into the region during aggregation pass {iteration}."]

    def _integrated_output_summary(self, run_dir: Path, stem: str) -> list[str]:
        repair_payload = self._load_json_file(run_dir / "output" / f"{stem}_integrate_repair.json")
        if isinstance(repair_payload, dict):
            repairs_applied = repair_payload.get("repairs_applied") or []
            if repairs_applied:
                return [str(item) for item in repairs_applied if item]
        return ["Merged the latest region SVG fragments into a whole-canvas SVG."]

    def _region_review_issues(self, review_path: Path) -> list[str]:
        payload = self._load_json_file(review_path)
        if not isinstance(payload, dict):
            return []
        issues: list[str] = []
        for item in payload.get("global_repairs") or []:
            if isinstance(item, dict):
                issues.append(f"[region] {item.get('criterion', 'issue')}: {item.get('reason', '')}".strip())
        for item in payload.get("object_issues") or []:
            if isinstance(item, dict):
                object_id = item.get("object_id") or "unknown"
                issues.append(
                    f"[object:{object_id}] {item.get('criterion', 'issue')}: {item.get('reason', '')}".strip()
                )
        return issues

    def _final_review_issues(self, review_path: Path) -> list[str]:
        payload = self._load_json_file(review_path)
        if not isinstance(payload, dict):
            return []
        groups = [
            ("spatial_relation_issues", "layout_fidelity_issues"),
            ("spatial_relation_issues", "dimension_fidelity_issues"),
            ("logical_relation_issues", "redundancy_issues"),
            ("logical_relation_issues", "boundary_issues"),
            ("visual_quality_issues", "consistency_issues"),
            ("visual_quality_issues", "visual_reasonableness_issues"),
        ]
        issues: list[str] = []
        for group_name, issue_name in groups:
            issue_group = (payload.get(group_name) or {}).get(issue_name) or []
            for item in issue_group:
                if not isinstance(item, dict):
                    continue
                criterion = str(item.get("criterion") or issue_name.replace("_issues", ""))
                issues.append(f"[{criterion}] {item.get('description', '')}".strip())
        return issues

    @staticmethod
    def _load_json_file(path: Path) -> dict | list | None:
        if not path.is_file():
            return None
        try:
            return json.loads(read_text_with_retry(path, encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _kind_for_path(path: Path) -> str:
        return ARTIFACT_KIND_BY_SUFFIX.get(path.suffix.lower(), path.suffix.lower().lstrip(".") or "file")

    @staticmethod
    def _to_relative(run_dir: Path, path: Path | None) -> str | None:
        if path is None:
            return None
        return str(path.relative_to(run_dir))

    @staticmethod
    def _find_first_existing(run_dir: Path, *patterns: str) -> Path | None:
        for pattern in patterns:
            matches = sorted(run_dir.glob(pattern))
            for path in matches:
                if path.is_file():
                    return path
        return None


def _extract_iteration(stem: str) -> int:
    match = re.search(r"(\d+)$", stem)
    return int(match.group(1)) if match else 0
