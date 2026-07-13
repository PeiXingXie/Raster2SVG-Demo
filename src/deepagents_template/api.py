"""Overview: FastAPI service exposing thread, invocation, and artifact endpoints."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import logging
import mimetypes
import os
import secrets
import signal
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from deepagents_template.config import get_settings
from deepagents_template.config import load_runtime_overrides
from deepagents_template.config import RUNTIME_OVERRIDE_PATH
from deepagents_template.config import save_runtime_overrides
from deepagents_template.conversion import BudgetExceededError, RasterToSvgPipeline
from deepagents_template.debug_review import DebugReviewService
from deepagents_template.error_reporting import (
    build_failure_diagnostic_from_exception,
    load_failure_diagnostic_from_run_dir,
    merge_failure_diagnostics,
)
from deepagents_template.manual_adjustment import ManualAdjustmentService
from deepagents_template.artifacts import (
    PREVIEWABLE_KINDS,
    ArtifactStore,
    derive_project_name_from_image,
    slugify_project_name,
)
from deepagents_template.resume import build_artifact_resume_info, build_resume_plan, load_request_from_run_dir
from deepagents_template.runtime import (
    get_thread_store,
)
from deepagents_template.schemas import (
    AgentRequest,
    AgentResponse,
    ArtifactBox,
    ArtifactFileEntry,
    ArtifactManualAdjustmentVersion,
    ArtifactOutputFrame,
    ArtifactPreviewSet,
    ArtifactResumeInfo,
    ArtifactRegionOverlay,
    ArtifactRequestSummary,
    ArtifactSnapshot,
    ApprovalDecision,
    ChatMessage,
    DebugReviewRequest,
    DebugReviewResponse,
    FrontendDefaultsResponse,
    FrontendHostInfoResponse,
    ManualAdjustmentRequest,
    ManualAdjustmentResponse,
    RuntimeOverridesPayload,
    ResumePlan,
    ResumeRunRequest,
    ResumeResponse,
    RunRenameRequest,
    RunStartResponse,
    ThreadCreateResponse,
    ThreadState,
    UploadImageRequest,
    UploadImageResponse,
    ExecutionRun,
)
from deepagents_template.workflow_trace import build_workflow_trace


logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="deepagents-template")
artifact_store = ArtifactStore()
DEV_SHUTDOWN_TOKEN = os.getenv("RASTER_SVG_DEV_SHUTDOWN_TOKEN", "").strip()
_active_run_ids: set[str] = set()
_active_run_lock = Lock()


def _mark_active_run(run_id: str | None) -> None:
    if not run_id:
        return
    with _active_run_lock:
        _active_run_ids.add(run_id)


def _unmark_active_run(run_id: str | None) -> None:
    if not run_id:
        return
    with _active_run_lock:
        _active_run_ids.discard(run_id)


def _is_active_run(run_id: str | None) -> bool:
    if not run_id:
        return False
    with _active_run_lock:
        return run_id in _active_run_ids


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        yield
    finally:
        executor.shutdown(wait=True)


app = FastAPI(title="Shape Studio API", version="0.1.0", lifespan=lifespan)
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


async def _request_process_shutdown() -> None:
    await asyncio.sleep(0.1)
    signal.raise_signal(signal.SIGINT)


def build_frontend_defaults_response() -> FrontendDefaultsResponse:
    settings = get_settings()
    return FrontendDefaultsResponse(
        default_user_input=settings.resolved_user_input(),
        api_key_configured=bool(settings.resolved_api_key()),
        base_url=settings.resolved_base_url(),
        api_provider=settings.resolved_api_provider(),
        api_format=settings.resolved_api_format(),
        max_retries=settings.resolved_max_retries(),
        region_processing_mode=settings.resolved_region_processing_mode(),
        region_concurrency=settings.resolved_region_concurrency(),
        workflow_mode=settings.resolved_workflow_mode(),
        agent_model=settings.resolved_agent_model(),
        subagent_model=settings.resolved_subagent_model(),
        agent_name=settings.resolved_agent_name(),
        use_previous_response_id=settings.resolved_use_previous_response_id(),
        max_retry=settings.resolved_max_retry(),
        fusion_max_retry=settings.resolved_fusion_max_retry(),
        max_budget=settings.resolved_max_budget(),
        supervisor_memory_enabled=settings.resolved_supervisor_memory_enabled(),
        supervisor_memory_persist_enabled=settings.resolved_supervisor_memory_persist_enabled(),
        strategy_enabled=settings.resolved_strategy_enabled(),
        recognition_bbox_refine_mode=settings.resolved_recognition_bbox_refine_mode(),
        sam_provider_mode=settings.resolved_sam_provider_mode(),
        sam_remote_url=settings.resolved_sam_remote_url(),
        sam_enabled=settings.resolved_sam_enabled(),
        sam_fallback_to_llm=settings.resolved_sam_fallback_to_llm(),
        bbox_issue_concurrency=settings.resolved_bbox_issue_concurrency(),
        bbox_issue_stagnation_rounds=settings.resolved_bbox_issue_stagnation_rounds(),
        bbox_global_stagnation_rounds=settings.resolved_bbox_global_stagnation_rounds(),
    )


def _artifact_revision_for_run(run: ExecutionRun | None) -> str | None:
    if run is None or not run.artifact_dir:
        return None
    run_dir = artifact_store.resolve_run_dir(run.artifact_dir)
    if run_dir is None:
        return None
    metadata_path = run_dir / "metadata.json"
    output_path = run_dir / "output.json"
    latest_ts = 0.0
    for candidate in (metadata_path, output_path):
        if candidate.is_file():
            latest_ts = max(latest_ts, candidate.stat().st_mtime)
    if latest_ts <= 0:
        return None
    revision_source = {
        "run_id": run.run_id,
        "status": run.status,
        "current_stage": run.current_stage,
        "updated_at": run.updated_at.isoformat() if getattr(run, "updated_at", None) else None,
        "latest_ts": latest_ts,
        "events_count": len(run.events or []),
    }
    return hashlib.sha1(str(revision_source).encode("utf-8")).hexdigest()[:16]


def build_runtime_overrides_response() -> RuntimeOverridesPayload:
    overrides = load_runtime_overrides()
    response_payload = {key: value for key, value in overrides.items() if key != "api_key"}
    response_payload["api_key_configured"] = bool(str(overrides.get("api_key") or "").strip())
    response_payload["runtime_config_path"] = str(RUNTIME_OVERRIDE_PATH)
    return RuntimeOverridesPayload.model_validate(response_payload)


def build_frontend_host_info_response() -> FrontendHostInfoResponse:
    settings = get_settings()
    return FrontendHostInfoResponse(
        host_mode="web",
        desktop_shell_supported=True,
        desktop_client_hint="Electron desktop client can load this same frontend through the FastAPI service.",
        web_monitor_hint="The web frontend remains available for development, debugging, and remote monitoring.",
        frontend_url=f"http://{settings.app_host}:{settings.app_port}/",
        platform=None,
        can_open_local_file_picker=False,
    )


def _validate_dev_shutdown_token(request_token: str | None) -> None:
    if not DEV_SHUTDOWN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Development shutdown endpoint is disabled.",
        )
    if not request_token or not secrets.compare_digest(request_token.strip(), DEV_SHUTDOWN_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid development shutdown token.",
        )


def _validate_local_shutdown_request(request: Request) -> None:
    client_host = getattr(request.client, "host", None)
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Development shutdown endpoint only accepts local requests.",
        )


def build_agent_response(thread: ThreadState) -> AgentResponse:
    latest_assistant = next(
        (message.content for message in reversed(thread.messages) if message.role == "assistant"),
        None,
    )
    current_run = thread.current_run
    if current_run is not None and current_run.artifact_dir and artifact_store.resolve_run_dir(current_run.artifact_dir) is None:
        current_run = None
    status_value = "completed"
    if current_run is not None:
        status_value = current_run.status
    elif thread.pending_approval is not None:
        status_value = "needs_approval"

    recent_runs = []
    seen_run_ids: set[str] = set()
    if current_run is not None:
        seen_run_ids.add(current_run.run_id)
    for run in artifact_store.list_recent_runs():
        if run.run_id in seen_run_ids:
            continue
        run.artifact_revision = _artifact_revision_for_run(run)
        recent_runs.append(run)
        seen_run_ids.add(run.run_id)

    if current_run is not None:
        current_run = current_run.model_copy(deep=True)
        current_run.artifact_revision = _artifact_revision_for_run(current_run)

    return AgentResponse(
        thread_id=thread.thread_id,
        status=status_value,
        content=latest_assistant,
        approval_request=thread.pending_approval,
        messages=thread.messages,
        current_run=current_run,
        recent_runs=recent_runs,
    )


@app.post("/dev/shutdown", status_code=status.HTTP_202_ACCEPTED)
async def dev_shutdown(
    request: Request,
    background_tasks: BackgroundTasks,
    x_dev_shutdown_token: str | None = Header(default=None),
):
    _validate_local_shutdown_request(request)
    _validate_dev_shutdown_token(x_dev_shutdown_token)
    background_tasks.add_task(_request_process_shutdown)
    return {"status": "shutting_down"}


def _find_run_for_thread(thread: ThreadState, run_id: str | None = None):
    candidates = []
    if thread.current_run is not None:
        candidates.append(thread.current_run)
    candidates.extend(thread.recent_runs)
    if run_id:
        for run in candidates:
            if run.run_id == run_id:
                return run
        return artifact_store.find_run_by_id(run_id)
    if candidates:
        return candidates[0]
    return None


def _artifact_file_urls(
    thread_id: str,
    relative_path: str,
    kind: str,
    run_id: str | None = None,
) -> tuple[str | None, str]:
    preview_url = None
    encoded_path = relative_path.replace("\\", "/")
    run_suffix = f"&run_id={run_id}" if run_id else ""
    if kind in PREVIEWABLE_KINDS:
        preview_url = f"/threads/{thread_id}/artifacts/file?path={encoded_path}{run_suffix}"
    download_url = f"/threads/{thread_id}/artifacts/file?path={encoded_path}&download=true{run_suffix}"
    return preview_url, download_url


def build_artifact_response(thread: ThreadState, run_id: str | None = None) -> ArtifactSnapshot:
    run = _find_run_for_thread(thread, run_id)
    if run is None or not run.artifact_dir:
        return ArtifactSnapshot(available=False)

    run_dir = artifact_store.resolve_run_dir(run.artifact_dir)
    failure_diagnostic = load_failure_diagnostic_from_run_dir(run_dir, run) if run_dir is not None else None
    failure_diagnostic = merge_failure_diagnostics(failure_diagnostic, run.failure_diagnostic)
    trace_run = run
    if failure_diagnostic is not None:
        trace_run = run.model_copy(
            deep=True,
            update={
                "failure_diagnostic": failure_diagnostic,
                "failure_stage": failure_diagnostic.failure_stage or run.failure_stage,
            },
        )
    if run_dir is None:
        return ArtifactSnapshot(
            available=False,
            run_id=run.run_id,
            project_name=run.project_name,
            status=run.status,
            current_stage=run.current_stage,
            failure_stage=trace_run.failure_stage,
            artifact_dir=run.artifact_dir,
            failure_diagnostic=failure_diagnostic or run.failure_diagnostic,
            resume=ArtifactResumeInfo(),
        )

    request_payload = artifact_store.load_json(run.artifact_dir, "input/request.json") or {}
    overview = artifact_store.load_json(run.artifact_dir, "logs/overview.json") or {}
    preview_targets = artifact_store.find_preview_targets(run.artifact_dir)
    canvas_width, canvas_height, regions = artifact_store.build_region_overlays(run.artifact_dir)
    output_frames_payload = artifact_store.build_output_frames(run.artifact_dir)
    manual_adjustments_payload = artifact_store.build_manual_adjustments(run.artifact_dir, output_frames_payload)
    region_results_payload = artifact_store.load_payload(run.artifact_dir, "intermediate/region_results.json") or []
    selected_adjustment_id = manual_adjustments_payload[-1]["adjustment_id"] if manual_adjustments_payload else None
    manual_workflow_trace, manual_adjustment_error = artifact_store.build_manual_workflow_trace(
        run.artifact_dir,
        adjustment_id=selected_adjustment_id,
    )

    files: list[ArtifactFileEntry] = []
    for item in artifact_store.list_files(run.artifact_dir):
        relative_path = str(item["relative_path"]).replace("/", "\\")
        file_path = artifact_store.resolve_relative_path(run.artifact_dir, relative_path)
        if file_path is None:
            continue
        stat = file_path.stat()
        kind = str(item.get("kind") or file_path.suffix.lower().lstrip(".") or "file")
        preview_url, download_url = _artifact_file_urls(thread.thread_id, relative_path, kind, run.run_id)
        files.append(
            ArtifactFileEntry(
                relative_path=relative_path,
                name=file_path.name,
                kind=kind,
                size_bytes=int(item.get("size_bytes") or stat.st_size),
                modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
                preview_url=preview_url,
                download_url=download_url,
            )
        )

    def preview_url_for(relative_path: str | None) -> str | None:
        if not relative_path:
            return None
        normalized_path = relative_path.replace("\\", "/")
        return f"/threads/{thread.thread_id}/artifacts/file?path={normalized_path}&run_id={run.run_id}"

    output_frames = []
    for item in output_frames_payload:
        normalized_path = str(item["relative_path"]).replace("\\", "/")
        output_frames.append(
            ArtifactOutputFrame(
                frame_id=item["frame_id"],
                title=item["title"],
                scope=item["scope"],
                target_id=item["target_id"],
                iteration=item["iteration"],
                relative_path=str(item["relative_path"]).replace("/", "\\"),
                preview_url=f"/threads/{thread.thread_id}/artifacts/file?path={normalized_path}&run_id={run.run_id}",
                download_url=f"/threads/{thread.thread_id}/artifacts/file?path={normalized_path}&download=true&run_id={run.run_id}",
                modified_at=item["modified_at"],
                update_summary=item.get("update_summary") or [],
                remaining_issues=item.get("remaining_issues") or [],
            )
        )

    manual_adjustments = []
    for item in manual_adjustments_payload:
        normalized_path = str(item["relative_path"]).replace("\\", "/")
        base_relative_path = item.get("base_relative_path")
        base_preview_url = preview_url_for(str(base_relative_path)) if base_relative_path else None
        manual_adjustments.append(
            ArtifactManualAdjustmentVersion(
                adjustment_id=item["adjustment_id"],
                title=item["title"],
                relative_path=str(item["relative_path"]).replace("/", "\\"),
                preview_url=f"/threads/{thread.thread_id}/artifacts/file?path={normalized_path}&run_id={run.run_id}",
                download_url=(
                    f"/threads/{thread.thread_id}/artifacts/file?path={normalized_path}&download=true&run_id={run.run_id}"
                ),
                modified_at=item["modified_at"],
                base_frame_id=item.get("base_frame_id"),
                base_title=item.get("base_title"),
                base_preview_url=base_preview_url,
                base_download_url=f"{base_preview_url}&download=true" if base_preview_url else None,
                workflow_trace=item.get("workflow_trace") or {},
                adjustment_error=item.get("adjustment_error"),
            )
        )

    bbox_overlays_ready = bool(region_results_payload)
    final_output_ready = bool(
        preview_targets.get("output_svg")
        or preview_targets.get("output_png")
    )
    artifact_revision_source = {
        "run_id": run.run_id,
        "status": run.status,
        "current_stage": run.current_stage,
        "updated_at": run.updated_at.isoformat() if getattr(run, "updated_at", None) else None,
        "events_count": len(run.events or []),
        "files_count": len(files),
        "output_frames_count": len(output_frames),
        "manual_adjustments_count": len(manual_adjustments),
        "workflow_trace_status": (build_workflow_trace(
            trace_run,
            regions=regions,
            region_results=region_results_payload if isinstance(region_results_payload, list) else [],
        ).summary.status),
        "workflow_trace_active_node_id": (build_workflow_trace(
            trace_run,
            regions=regions,
            region_results=region_results_payload if isinstance(region_results_payload, list) else [],
        ).summary.active_node_id),
        "manual_trace_status": manual_workflow_trace.get("summary", {}).get("status") if isinstance(manual_workflow_trace, dict) else None,
        "manual_trace_active_node_id": manual_workflow_trace.get("summary", {}).get("active_node_id") if isinstance(manual_workflow_trace, dict) else None,
    }
    artifact_revision = hashlib.sha1(str(artifact_revision_source).encode("utf-8")).hexdigest()[:16]
    workflow_trace = build_workflow_trace(
        trace_run,
        regions=regions,
        region_results=region_results_payload if isinstance(region_results_payload, list) else [],
    )

    return ArtifactSnapshot(
        available=final_output_ready,
        bbox_overlays_ready=bbox_overlays_ready,
        run_id=run.run_id,
        project_name=run.project_name,
        status=run.status,
        current_stage=run.current_stage,
        failure_stage=trace_run.failure_stage,
        artifact_dir=str(run_dir),
        artifact_revision=artifact_revision,
        request=ArtifactRequestSummary.model_validate(request_payload),
        messages=thread.messages,
        overview=overview,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        regions=[ArtifactRegionOverlay.model_validate(region) for region in regions],
        output_frames=output_frames,
        manual_adjustments=manual_adjustments,
        workflow_trace=workflow_trace,
        manual_workflow_trace=manual_workflow_trace,
        manual_adjustment_error=manual_adjustment_error,
        failure_diagnostic=failure_diagnostic,
        previews=ArtifactPreviewSet(
            input_image_url=preview_url_for(preview_targets["input_image"]),
            output_svg_url=preview_url_for(preview_targets["output_svg"]),
            output_png_url=preview_url_for(preview_targets["output_png"]),
            initial_svg_url=preview_url_for(preview_targets["initial_svg"]),
        ),
        resume=build_artifact_resume_info(run_dir),
        files=files,
    )


def _save_uploaded_image(payload: UploadImageRequest) -> UploadImageResponse:
    upload_root = artifact_store.root / "_uploads"
    upload_root.mkdir(parents=True, exist_ok=True)

    filename = Path(payload.filename or "upload.png").name
    suffix = Path(filename).suffix or ".png"
    stem = Path(filename).stem or "upload"
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    candidate = upload_root / f"{timestamp}-{slugify_project_name(stem)}{suffix}"
    counter = 1
    while candidate.exists():
        counter += 1
        candidate = upload_root / f"{timestamp}-{slugify_project_name(stem)}-{counter}{suffix}"

    try:
        content = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 upload payload.") from exc

    candidate.write_bytes(content)
    return UploadImageResponse(image_path=str(candidate), filename=filename, size_bytes=len(content))


def _run_agent_in_background(thread_id: str, request: AgentRequest, artifact_dir: str) -> None:
    thread_store = get_thread_store()
    active_run_id = thread_store.get(thread_id).current_run.run_id if thread_store.get(thread_id).current_run else None
    _mark_active_run(active_run_id)
    settings = get_settings()
    try:
        resolved_agent_model = settings.resolved_agent_model(request.agent_model)
        resolved_subagent_model = settings.resolved_subagent_model(request.subagent_model)
        thread = thread_store.push_event(
            thread_id,
            stage="preparing-context",
            title="Preparing conversion context",
            detail="Collected the current thread messages and assembled the Shape Studio conversion request payload.",
            status="running",
        )
        artifact_store.write_metadata(thread)
        thread = thread_store.get(thread_id)

        thread = thread_store.push_event(
            thread_id,
            stage="running-conversion",
            title="Running conversion pipeline",
            detail="The backend is cutting regions, calling the multimodal model, and assembling the SVG.",
            status="running",
            payload={
                "image_path": request.image_path,
                "max_retry": settings.resolved_max_retry(request.max_retry),
                "fusion_max_retry": settings.resolved_fusion_max_retry(request.fusion_max_retry),
                "max_budget": settings.resolved_max_budget(request.max_budget),
                "region_processing_mode": settings.resolved_region_processing_mode(
                    request.region_processing_mode
                ),
                "region_concurrency": settings.resolved_region_concurrency(
                    request.region_processing_mode,
                    request.region_concurrency,
                ),
                "workflow_mode": settings.resolved_workflow_mode(request.workflow_mode),
                "supervisor_memory_enabled": settings.resolved_supervisor_memory_enabled(
                    request.supervisor_memory_enabled
                ),
                "supervisor_memory_persist_enabled": settings.resolved_supervisor_memory_persist_enabled(
                    request.supervisor_memory_persist_enabled
                ),
                "api_provider": settings.resolved_api_provider(request.api_provider),
                "api_format": settings.resolved_api_format(request.api_format),
                "base_url": settings.resolved_base_url(request.base_url),
                "agent_model": resolved_agent_model,
                "subagent_model": resolved_subagent_model,
                "max_retries": settings.resolved_max_retries(request.max_retries),
                "use_previous_response_id": settings.resolved_use_previous_response_id(
                    request.use_previous_response_id
                ),
            },
        )
        artifact_store.write_metadata(thread)
        pipeline = RasterToSvgPipeline(
            thread_store=thread_store,
            thread_id=thread_id,
            artifact_dir=Path(artifact_dir),
            request=request,
            agent_model=resolved_agent_model,
            subagent_model=resolved_subagent_model,
        )
        final_content = pipeline.run()
    except BudgetExceededError as exc:
        logger.warning("Conversion pipeline paused on budget for thread %s", thread_id)
        latest_run = thread_store.get(thread_id).current_run
        failure_stage = (
            (latest_run.failure_stage or latest_run.current_stage)
            if latest_run is not None
            else "paused-budget"
        )
        diagnostic = build_failure_diagnostic_from_exception(
            exc,
            run=latest_run,
            terminal_stage="paused-budget",
            artifact_dir=artifact_dir,
            failure_stage=failure_stage,
            status="paused",
        )
        thread = thread_store.finish_run(
            thread_id,
            status="paused",
            stage="paused-budget",
            failure_stage=failure_stage,
            title="Run paused",
            detail=f"Conversion pipeline paused: {exc}",
            level="warning",
            error=diagnostic.error_message or str(exc),
            failure_diagnostic=diagnostic,
        )
        thread = thread_store.append_message(
            thread_id,
            ChatMessage(role="system", content=f"Conversion pipeline paused: {exc}"),
        )
        artifact_store.write_metadata(thread)
        _unmark_active_run(active_run_id)
        return
    except Exception as exc:
        logger.exception("Conversion pipeline failed for thread %s", thread_id)
        latest_run = thread_store.get(thread_id).current_run
        failure_stage = (
            (latest_run.failure_stage or latest_run.current_stage)
            if latest_run is not None
            else "failed"
        )
        diagnostic = build_failure_diagnostic_from_exception(
            exc,
            run=latest_run,
            terminal_stage="failed",
            artifact_dir=artifact_dir,
            failure_stage=failure_stage,
            status="failed",
        )
        thread = thread_store.finish_run(
            thread_id,
            status="failed",
            stage="failed",
            failure_stage=failure_stage,
            title="Run failed",
            detail=f"Conversion pipeline failed: {exc}",
            level="error",
            error=diagnostic.error_message or str(exc),
            failure_diagnostic=diagnostic,
        )
        thread = thread_store.append_message(
            thread_id,
            ChatMessage(role="system", content=f"Conversion pipeline failed: {exc}"),
        )
        artifact_store.write_metadata(thread)
        _unmark_active_run(active_run_id)
        return

    thread = thread_store.push_event(
        thread_id,
        stage="summarizing-result",
        title="Collecting conversion result",
        detail=f"Received {len(final_content)} characters of assistant output.",
        status="running",
        payload={"character_count": len(final_content)},
    )
    artifact_store.write_metadata(thread)
    thread = thread_store.append_message(thread_id, ChatMessage(role="assistant", content=final_content))
    thread_store.set_pending_approval(thread_id, None)
    thread = thread_store.finish_run(
        thread_id,
        status="completed",
        stage="completed",
        title="Run completed",
        detail="The Shape Studio conversion result is ready.",
        level="success",
        payload={"character_count": len(final_content)},
    )
    artifact_store.write_output(thread.current_run, final_content)
    artifact_store.write_metadata(thread)
    _unmark_active_run(active_run_id)


def _resume_conversion_in_background(thread_id: str, request: AgentRequest, artifact_dir: str) -> None:
    thread_store = get_thread_store()
    active_run_id = thread_store.get(thread_id).current_run.run_id if thread_store.get(thread_id).current_run else None
    _mark_active_run(active_run_id)
    settings = get_settings()
    resolved_agent_model = settings.resolved_agent_model(request.agent_model)
    resolved_subagent_model = settings.resolved_subagent_model(request.subagent_model)
    thread = thread_store.push_event(
        thread_id,
        stage="resuming-conversion",
        title="Resuming conversion pipeline",
        detail="Loading persisted checkpoints and continuing the Shape Studio run.",
        status="running",
    )
    artifact_store.write_metadata(thread)
    try:
        pipeline = RasterToSvgPipeline(
            thread_store=thread_store,
            thread_id=thread_id,
            artifact_dir=Path(artifact_dir),
            request=request,
            agent_model=resolved_agent_model,
            subagent_model=resolved_subagent_model,
        )
        final_content = pipeline.run()
    except BudgetExceededError as exc:
        latest_run = thread_store.get(thread_id).current_run
        failure_stage = (
            (latest_run.failure_stage or latest_run.current_stage)
            if latest_run is not None
            else "paused-budget"
        )
        diagnostic = build_failure_diagnostic_from_exception(
            exc,
            run=latest_run,
            terminal_stage="paused-budget",
            artifact_dir=artifact_dir,
            failure_stage=failure_stage,
            status="paused",
        )
        thread = thread_store.finish_run(
            thread_id,
            status="paused",
            stage="paused-budget",
            failure_stage=failure_stage,
            title="Run paused again",
            detail=f"Conversion pipeline paused: {exc}",
            level="warning",
            error=diagnostic.error_message or str(exc),
            failure_diagnostic=diagnostic,
        )
        thread = thread_store.append_message(
            thread_id,
            ChatMessage(role="system", content=f"Conversion pipeline paused: {exc}"),
        )
        artifact_store.write_metadata(thread)
        _unmark_active_run(active_run_id)
        return
    except Exception as exc:
        logger.exception("Conversion resume failed for thread %s", thread_id)
        latest_run = thread_store.get(thread_id).current_run
        failure_stage = (
            (latest_run.failure_stage or latest_run.current_stage)
            if latest_run is not None
            else "failed"
        )
        diagnostic = build_failure_diagnostic_from_exception(
            exc,
            run=latest_run,
            terminal_stage="failed",
            artifact_dir=artifact_dir,
            failure_stage=failure_stage,
            status="failed",
        )
        thread = thread_store.finish_run(
            thread_id,
            status="failed",
            stage="failed",
            failure_stage=failure_stage,
            title="Resume failed",
            detail=f"Conversion resume failed: {exc}",
            level="error",
            error=diagnostic.error_message or str(exc),
            failure_diagnostic=diagnostic,
        )
        thread = thread_store.append_message(
            thread_id,
            ChatMessage(role="system", content=f"Conversion resume failed: {exc}"),
        )
        artifact_store.write_metadata(thread)
        _unmark_active_run(active_run_id)
        return

    thread = thread_store.push_event(
        thread_id,
        stage="summarizing-result",
        title="Collecting resumed conversion result",
        detail=f"Received {len(final_content)} characters of assistant output.",
        status="running",
        payload={"character_count": len(final_content)},
    )
    artifact_store.write_metadata(thread)
    thread = thread_store.append_message(thread_id, ChatMessage(role="assistant", content=final_content))
    thread = thread_store.finish_run(
        thread_id,
        status="completed",
        stage="completed",
        title="Resumed run completed",
        detail="The resumed Shape Studio conversion finished successfully.",
        level="success",
        payload={"character_count": len(final_content)},
    )
    artifact_store.write_output(thread.current_run, final_content)
    artifact_store.write_metadata(thread)
    _unmark_active_run(active_run_id)


@app.get("/")
def frontend() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config/defaults", response_model=FrontendDefaultsResponse)
def get_frontend_defaults() -> FrontendDefaultsResponse:
    return build_frontend_defaults_response()


@app.get("/frontend/host-info", response_model=FrontendHostInfoResponse)
def get_frontend_host_info() -> FrontendHostInfoResponse:
    return build_frontend_host_info_response()


@app.get("/config/runtime-overrides", response_model=RuntimeOverridesPayload)
def get_runtime_overrides() -> RuntimeOverridesPayload:
    return build_runtime_overrides_response()


@app.post("/config/runtime-overrides", response_model=RuntimeOverridesPayload)
def update_runtime_overrides(payload: RuntimeOverridesPayload) -> RuntimeOverridesPayload:
    existing = load_runtime_overrides()
    normalized: dict = dict(existing)
    submitted_values = payload.model_dump(
        exclude={"api_key_configured", "runtime_config_path"},
        exclude_unset=True,
    )
    for key, value in submitted_values.items():
        if isinstance(value, str):
            value = value.strip() or None
        if value is None:
            normalized.pop(key, None)
        else:
            normalized[key] = value
    stored = save_runtime_overrides(normalized)
    response_payload = {key: value for key, value in stored.items() if key != "api_key"}
    response_payload["api_key_configured"] = bool(str(stored.get("api_key") or "").strip())
    response_payload["runtime_config_path"] = str(RUNTIME_OVERRIDE_PATH)
    return RuntimeOverridesPayload.model_validate(response_payload)


@app.delete("/config/runtime-overrides", response_model=RuntimeOverridesPayload)
def reset_runtime_overrides() -> RuntimeOverridesPayload:
    stored = save_runtime_overrides({})
    response_payload = {key: value for key, value in stored.items() if key != "api_key"}
    response_payload["api_key_configured"] = False
    response_payload["runtime_config_path"] = str(RUNTIME_OVERRIDE_PATH)
    return RuntimeOverridesPayload.model_validate(response_payload)


@app.post("/uploads", response_model=UploadImageResponse)
def upload_image(payload: UploadImageRequest) -> UploadImageResponse:
    return _save_uploaded_image(payload)


@app.post("/threads", response_model=ThreadCreateResponse)
def create_thread() -> ThreadCreateResponse:
    thread = get_thread_store().create_thread()
    return ThreadCreateResponse(thread_id=thread.thread_id)


@app.get("/threads/{thread_id}", response_model=ThreadState)
def get_thread(thread_id: str) -> ThreadState:
    return get_thread_store().get(thread_id)


@app.get("/threads/{thread_id}/snapshot", response_model=AgentResponse)
def get_thread_snapshot(thread_id: str) -> AgentResponse:
    return build_agent_response(get_thread_store().get(thread_id))


@app.get("/threads/{thread_id}/artifacts", response_model=ArtifactSnapshot)
def get_thread_artifacts(thread_id: str, run_id: str | None = None) -> ArtifactSnapshot:
    return build_artifact_response(get_thread_store().get(thread_id), run_id=run_id)


@app.patch("/threads/{thread_id}/runs/{run_id}", response_model=ExecutionRun)
def rename_thread_run(thread_id: str, run_id: str, payload: RunRenameRequest) -> ExecutionRun:
    thread_store = get_thread_store()
    thread = thread_store.get(thread_id)
    run = _find_run_for_thread(thread, run_id)
    if run is None or not run.artifact_dir:
        raise HTTPException(status_code=404, detail="Saved project was not found.")
    try:
        updated_run = artifact_store.update_run_project_name(run, payload.project_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    thread_store.update_run_project_name(thread_id, run_id, payload.project_name)
    return updated_run


@app.delete("/threads/{thread_id}/runs/{run_id}")
def delete_thread_run(
    thread_id: str,
    run_id: str,
    artifact_dir: str | None = None,
) -> dict[str, bool | str | None]:
    thread_store = get_thread_store()
    thread = thread_store.get(thread_id)
    run = _find_run_for_thread(thread, run_id)
    target_artifact_dir = artifact_dir or (run.artifact_dir if run is not None else None)
    if not target_artifact_dir:
        raise HTTPException(status_code=404, detail="Saved project was not found.")
    if _is_active_run(run_id):
        raise HTTPException(status_code=409, detail="Active runs cannot be deleted.")
    try:
        deleted_dir = artifact_store.delete_run_dir(target_artifact_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    thread_store.remove_run(thread_id, run_id)
    return {
        "ok": True,
        "run_id": run.run_id if run is not None else run_id,
        "project_name": run.project_name if run is not None else deleted_dir.name,
        "artifact_dir": str(deleted_dir),
    }


@app.get("/runs/resume-plan", response_model=ResumePlan)
def get_resume_plan(run_dir: str) -> ResumePlan:
    return build_resume_plan(Path(run_dir))


@app.get("/threads/{thread_id}/artifacts/file")
def get_thread_artifact_file(
    thread_id: str,
    path: str,
    download: bool = False,
    run_id: str | None = None,
) -> FileResponse:
    thread = get_thread_store().get(thread_id)
    run = _find_run_for_thread(thread, run_id)
    if run is None or not run.artifact_dir:
        raise HTTPException(status_code=404, detail="No artifact directory is available for this thread.")

    file_path = artifact_store.resolve_relative_path(run.artifact_dir, path)
    if file_path is None:
        raise HTTPException(status_code=404, detail="Artifact file was not found.")

    media_type = mimetypes.guess_type(file_path.name)[0]
    if file_path.suffix.lower() == ".svg":
        media_type = "image/svg+xml"

    filename = file_path.name if download else None
    return FileResponse(file_path, media_type=media_type, filename=filename)


@app.post("/threads/{thread_id}/manual-adjust", response_model=ManualAdjustmentResponse)
def manual_adjust_artifacts(thread_id: str, payload: ManualAdjustmentRequest) -> ManualAdjustmentResponse:
    thread_store = get_thread_store()
    thread = thread_store.get(thread_id)
    run = _find_run_for_thread(thread, payload.run_id)
    if run is None or not run.artifact_dir:
        raise HTTPException(status_code=404, detail="No artifact-backed run found for this thread.")
    snapshot = build_artifact_response(thread, run_id=run.run_id)
    if not snapshot.available:
        raise HTTPException(status_code=400, detail="Artifacts are not ready for manual adjustment.")

    service = ManualAdjustmentService(
        artifact_store=artifact_store,
        thread=thread,
        run=run,
    )
    try:
        result = service.execute(payload, artifact_snapshot=snapshot)
    except Exception as exc:
        updated_snapshot = build_artifact_response(thread_store.get(thread_id), run_id=run.run_id)
        artifact_store.write_metadata(thread_store.get(thread_id))
        raise HTTPException(
            status_code=500,
            detail={
                "message": str(exc) or "Manual adjustment failed.",
                "error_type": type(exc).__name__,
                "artifact_snapshot": updated_snapshot.model_dump(mode="json"),
            },
        ) from exc
    updated_snapshot = build_artifact_response(thread_store.get(thread_id), run_id=run.run_id)
    thread_store.append_message(
        thread_id,
        ChatMessage(
            role="system",
            content=(
                f"Manual adjustment applied on {result['scope']} target(s): "
                f"{', '.join(result['target_ids']) or 'manual-layer'}."
            ),
        ),
    )
    artifact_store.write_metadata(thread_store.get(thread_id))
    return ManualAdjustmentResponse(
        ok=True,
        run_id=result["run_id"],
        scope=result["scope"],
        target_ids=result["target_ids"],
        applied_files=result["applied_files"],
        notes=result["notes"],
        edit_strategy=result.get("edit_strategy"),
        artifact_snapshot=updated_snapshot,
    )


@app.post("/threads/{thread_id}/debug-review", response_model=DebugReviewResponse)
def debug_review_artifacts(thread_id: str, payload: DebugReviewRequest) -> DebugReviewResponse:
    thread_store = get_thread_store()
    thread = thread_store.get(thread_id)
    run = _find_run_for_thread(thread, payload.run_id)
    if run is None or not run.artifact_dir:
        raise HTTPException(status_code=404, detail="No artifact-backed run found for this thread.")

    service = DebugReviewService(
        artifact_store=artifact_store,
        thread=thread,
        run=run,
    )
    try:
        return service.execute(payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/invoke", response_model=RunStartResponse)
def invoke_agent(payload: AgentRequest) -> RunStartResponse:
    thread_store = get_thread_store()
    settings = get_settings()
    resolved_message = settings.resolved_user_input(payload.message)
    payload = payload.model_copy(update={"message": resolved_message})
    if not payload.image_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`image_path` is required for conversion runs.",
        )
    thread = thread_store.get_or_create(payload.thread_id)
    if thread.current_run is not None and thread.current_run.status in {"queued", "running"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This thread already has an active run in progress.",
        )

    project_name = derive_project_name_from_image(payload.project_name, payload.image_path, payload.message)
    run_dir = artifact_store.create_run_dir(project_name)
    thread = thread_store.append_message(
        thread.thread_id,
        ChatMessage(
            role="user",
            content=payload.message,
        ),
    )
    thread = thread_store.begin_run(
        thread.thread_id,
        mode="invoke",
        stage="queued",
        title="Run accepted",
        detail="The request has been queued and will start shortly.",
        project_name=project_name,
        artifact_dir=str(run_dir),
    )
    artifact_store.write_metadata(thread)
    _mark_active_run(thread.current_run.run_id if thread.current_run else None)
    executor.submit(_run_agent_in_background, thread.thread_id, payload, str(run_dir))
    return RunStartResponse(thread_id=thread.thread_id, run=thread.current_run, messages=thread.messages)


@app.post("/resume", response_model=ResumeResponse)
def resume_agent(payload: ApprovalDecision) -> ResumeResponse:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Approval-based agent resume is no longer supported. Use `/runs/resume` for pipeline checkpoints.",
    )


@app.post("/runs/resume", response_model=RunStartResponse)
def resume_conversion_run(payload: ResumeRunRequest) -> RunStartResponse:
    thread_store = get_thread_store()
    run_dir = Path(payload.run_dir)
    plan = build_resume_plan(run_dir)
    if not plan.available:
        raise HTTPException(status_code=400, detail=plan.reason or "This run cannot be resumed.")

    request = load_request_from_run_dir(run_dir)
    if payload.extra_budget is not None:
        current_limit = plan.budget.limit
        if payload.budget_mode == "top_up":
            request = request.model_copy(update={"max_budget": current_limit + payload.extra_budget})
        else:
            request = request.model_copy(update={"max_budget": max(current_limit, plan.budget.used + payload.extra_budget)})

    thread = thread_store.get_or_create(payload.thread_id or request.thread_id or plan.run_dir)
    if thread.current_run is not None and thread.current_run.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="A run is already in progress for this thread.")

    thread = thread_store.begin_run(
        thread.thread_id,
        mode="resume",
        stage="queued",
        title="Resume accepted",
        detail=f"Continuing the prior run from {plan.resume_stage or 'the latest checkpoint'}.",
        project_name=thread.current_run.project_name if thread.current_run else run_dir.name,
        artifact_dir=str(run_dir),
    )
    artifact_store.write_metadata(thread)
    _mark_active_run(thread.current_run.run_id if thread.current_run else None)
    executor.submit(_resume_conversion_in_background, thread.thread_id, request, str(run_dir))
    return RunStartResponse(thread_id=thread.thread_id, run=thread.current_run, messages=thread.messages)
