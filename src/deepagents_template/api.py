"""Overview: FastAPI service exposing thread, invocation, and artifact endpoints."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import ipaddress
import logging
import mimetypes
import os
import secrets
import signal
from concurrent.futures import Future
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from deepagents_template.config import get_settings
from deepagents_template.config import load_runtime_overrides
from deepagents_template.config import RUNTIME_OVERRIDE_PATH
from deepagents_template.config import save_runtime_overrides
from deepagents_template.artifact_leases import ArtifactLease, artifact_leases
from deepagents_template.bounded_executor import BoundedExecutor, QueueFullError
from deepagents_template.conversion import BudgetExceededError, RasterToSvgPipeline, RunCancelledError
from deepagents_template.error_reporting import (
    build_failure_diagnostic_from_exception,
    load_failure_diagnostic_from_run_dir,
    merge_failure_diagnostics,
)
from deepagents_template.manual_adjustment import ManualAdjustmentService
from deepagents_template.artifacts import (
    PREVIEWABLE_KINDS,
    ArtifactStore,
    slugify_project_name,
)
from deepagents_template.resume import build_artifact_resume_info, build_resume_plan, load_request_from_run_dir
from deepagents_template.retry_policy import resolve_retry_limits
from deepagents_template.runtime import (
    get_thread_store,
)
from deepagents_template.schemas import (
    AgentRequest,
    AgentResponse,
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
    FrontendDefaultsResponse,
    FrontendHostInfoResponse,
    HistoryPreviewResponse,
    ManualAdjustmentRequest,
    ManualAdjustmentResponse,
    RuntimeOverridesPayload,
    ResumePlan,
    ResumeRunRequest,
    ResumeResponse,
    RunListResponse,
    RunOpenResponse,
    RunRenameRequest,
    RunStartResponse,
    ThreadCreateResponse,
    ThreadState,
    UploadImageRequest,
    UploadImageResponse,
    ExecutionRun,
)
from deepagents_template.version import __version__
from deepagents_template.workflow_trace import build_workflow_trace


logger = logging.getLogger(__name__)


def _positive_env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        logger.warning("Invalid %s; using %s.", name, default)
        return default


executor = BoundedExecutor(
    max_workers=4,
    max_queued=_positive_env_int("SHAPE_STUDIO_MAX_QUEUED_RUNS", 12),
    thread_name_prefix="deepagents-template",
)
manual_adjustment_executor = BoundedExecutor(
    max_workers=_positive_env_int("SHAPE_STUDIO_MANUAL_ADJUSTMENT_WORKERS", 2),
    max_queued=_positive_env_int("SHAPE_STUDIO_MAX_QUEUED_MANUAL_ADJUSTMENTS", 6),
    thread_name_prefix="manual-adjustment",
)
artifact_store = ArtifactStore()
DEV_SHUTDOWN_TOKEN = os.getenv("RASTER_SVG_DEV_SHUTDOWN_TOKEN", "").strip()
_active_run_ids: set[str] = set()
_active_run_lock = Lock()
_run_cancel_events: dict[str, Event] = {}
_run_cancel_lock = Lock()
_run_futures: dict[str, Future] = {}
_run_future_lock = Lock()
_manual_adjustment_thread_ids: set[str] = set()
_thread_operation_lock = Lock()


def _try_mark_manual_adjustment(thread_id: str) -> bool:
    with _thread_operation_lock:
        if thread_id in _manual_adjustment_thread_ids:
            return False
        current_run = get_thread_store().get(thread_id).current_run
        if current_run is not None and current_run.status in {"queued", "running"}:
            return False
        _manual_adjustment_thread_ids.add(thread_id)
        return True


def _unmark_manual_adjustment(thread_id: str) -> None:
    with _thread_operation_lock:
        _manual_adjustment_thread_ids.discard(thread_id)


def _register_cancel_event(run_id: str) -> Event:
    event = Event()
    with _run_cancel_lock:
        _run_cancel_events[run_id] = event
    return event


def _remove_cancel_event(run_id: str) -> None:
    with _run_cancel_lock:
        _run_cancel_events.pop(run_id, None)


def _request_run_cancel(run_id: str) -> bool:
    with _run_cancel_lock:
        event = _run_cancel_events.get(run_id)
        if event is None:
            return False
        event.set()
        return True


def _register_run_future(
    run_id: str,
    future: Future | None,
    *,
    thread_id: str,
    lease: ArtifactLease,
) -> None:
    if future is None:
        return
    with _run_future_lock:
        _run_futures[run_id] = future

    def handle_done(completed: Future) -> None:
        with _run_future_lock:
            if _run_futures.get(run_id) is completed:
                _run_futures.pop(run_id, None)
        if not completed.cancelled():
            return
        try:
            thread_store = get_thread_store()
            thread = thread_store.get(thread_id)
            if thread.current_run is not None and thread.current_run.run_id == run_id:
                thread_store.append_message(
                    thread_id,
                    ChatMessage(role="system", content="Run cancelled before execution started."),
                )
                thread = thread_store.finish_run(
                    thread_id,
                    status="cancelled",
                    stage="cancelled",
                    title="Queued run cancelled",
                    detail="The run was removed from the queue before execution started.",
                    level="warning",
                )
                artifact_store.write_metadata(thread)
        finally:
            _unmark_active_run(run_id)
            artifact_leases.release(lease)
            _remove_cancel_event(run_id)

    future.add_done_callback(handle_done)


def _cancel_queued_future(run_id: str) -> bool:
    with _run_future_lock:
        future = _run_futures.get(run_id)
    return bool(future is not None and future.cancel())


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
        manual_adjustment_executor.shutdown(wait=True)


app = FastAPI(title="Shape Studio API", version=__version__, lifespan=lifespan)


def _is_loopback_client(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.strip().strip("[]").split("%", 1)[0].lower()
    if normalized in {"localhost", "testclient"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


@app.middleware("http")
async def local_access_only(request: Request, call_next):
    client_host = getattr(request.client, "host", None)
    if not _is_loopback_client(client_host):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "Shape Studio only accepts requests from this computer."},
        )
    return await call_next(request)


static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


async def _request_process_shutdown() -> None:
    await asyncio.sleep(0.1)
    signal.raise_signal(signal.SIGINT)


def build_frontend_defaults_response() -> FrontendDefaultsResponse:
    settings = get_settings()
    retry_limits = resolve_retry_limits(settings, AgentRequest())
    return FrontendDefaultsResponse(
        default_user_input=settings.resolved_user_input(),
        api_key_configured=bool(settings.resolved_api_key()),
        base_url=settings.resolved_base_url(),
        api_provider=settings.resolved_api_provider(),
        api_format=settings.resolved_api_format(),
        max_retries=settings.resolved_max_retries(),
        transport_max_attempts=retry_limits.transport_max_attempts,
        response_validation_max_attempts=retry_limits.response_validation_max_attempts,
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
        bbox_initial_localization_max_attempts=retry_limits.bbox_initial_localization_max_attempts,
        bbox_refinement_max_rounds=retry_limits.bbox_refinement_max_rounds,
        bbox_global_stagnation_max_rounds=retry_limits.bbox_global_stagnation_max_rounds,
        region_repair_max_attempts=retry_limits.region_repair_max_attempts,
        object_repair_max_attempts=retry_limits.object_repair_max_attempts,
        fidelity_verification_max_attempts=retry_limits.fidelity_verification_max_attempts,
        fidelity_verification_independent_budget=retry_limits.fidelity_verification_uses_independent_budget,
        fusion_repair_max_attempts=retry_limits.fusion_repair_max_attempts,
        run_model_call_budget=retry_limits.run_model_call_budget,
    )


def _freeze_run_request_settings(request: AgentRequest) -> tuple[AgentRequest, str]:
    """Resolve mutable runtime defaults once so queued runs cannot affect each other."""
    settings = get_settings()
    region_processing_mode = settings.resolved_region_processing_mode(request.region_processing_mode)
    retry_limits = resolve_retry_limits(settings, request)
    frozen = request.model_copy(
        update={
            "api_provider": settings.resolved_api_provider(request.api_provider),
            "base_url": settings.resolved_base_url(request.base_url),
            "api_format": settings.resolved_api_format(request.api_format),
            "max_retries": settings.resolved_max_retries(request.max_retries),
            "transport_max_attempts": retry_limits.transport_max_attempts,
            "response_validation_max_attempts": retry_limits.response_validation_max_attempts,
            "region_processing_mode": region_processing_mode,
            "region_concurrency": settings.resolved_region_concurrency(
                region_processing_mode,
                request.region_concurrency,
            ),
            "bbox_issue_concurrency": settings.resolved_bbox_issue_concurrency(
                request.bbox_issue_concurrency
            ),
            "bbox_issue_stagnation_rounds": settings.resolved_bbox_issue_stagnation_rounds(
                request.bbox_issue_stagnation_rounds
            ),
            "bbox_global_stagnation_rounds": settings.resolved_bbox_global_stagnation_rounds(
                request.bbox_global_stagnation_rounds
            ),
            "bbox_initial_localization_max_attempts": retry_limits.bbox_initial_localization_max_attempts,
            "bbox_refinement_max_rounds": retry_limits.bbox_refinement_max_rounds,
            "bbox_global_stagnation_max_rounds": retry_limits.bbox_global_stagnation_max_rounds,
            "workflow_mode": settings.resolved_workflow_mode(request.workflow_mode),
            "agent_model": settings.resolved_agent_model(request.agent_model),
            "subagent_model": settings.resolved_subagent_model(request.subagent_model),
            "agent_name": settings.resolved_agent_name(request.agent_name),
            "use_previous_response_id": settings.resolved_use_previous_response_id(
                request.use_previous_response_id
            ),
            "max_retry": settings.resolved_max_retry(request.max_retry),
            "region_repair_max_attempts": retry_limits.region_repair_max_attempts,
            "object_repair_max_attempts": retry_limits.object_repair_max_attempts,
            "fidelity_verification_max_attempts": retry_limits.fidelity_verification_max_attempts,
            "fidelity_verification_independent_budget": retry_limits.fidelity_verification_uses_independent_budget,
            "fusion_max_retry": settings.resolved_fusion_max_retry(request.fusion_max_retry),
            "fusion_repair_max_attempts": retry_limits.fusion_repair_max_attempts,
            "max_budget": settings.resolved_max_budget(request.max_budget),
            "run_model_call_budget": retry_limits.run_model_call_budget,
            "supervisor_memory_enabled": settings.resolved_supervisor_memory_enabled(
                request.supervisor_memory_enabled
            ),
            "supervisor_memory_persist_enabled": settings.resolved_supervisor_memory_persist_enabled(
                request.supervisor_memory_persist_enabled
            ),
            "strategy_enabled": settings.resolved_strategy_enabled(request.strategy_enabled),
            "recognition_bbox_refine_mode": settings.resolved_recognition_bbox_refine_mode(
                request.recognition_bbox_refine_mode
            ),
            "sam_provider_mode": settings.resolved_sam_provider_mode(request.sam_provider_mode),
            "sam_remote_url": settings.resolved_sam_remote_url(request.sam_remote_url),
            "sam_enabled": settings.resolved_sam_enabled(request.sam_enabled),
            "sam_fallback_to_llm": settings.resolved_sam_fallback_to_llm(
                request.sam_fallback_to_llm
            ),
        }
    )
    return frozen, settings.resolved_api_key(request.api_key)


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

    recent_runs = [run.model_copy(deep=True) for run in thread.recent_runs]
    for run in recent_runs:
        run.artifact_revision = _artifact_revision_for_run(run)
    project_runs = []
    seen_run_ids: set[str] = set()
    if current_run is not None:
        seen_run_ids.add(current_run.run_id)
    for run in artifact_store.list_recent_runs():
        if run.run_id in seen_run_ids:
            continue
        run.artifact_revision = _artifact_revision_for_run(run)
        project_runs.append(run)
        seen_run_ids.add(run.run_id)

    if current_run is not None:
        current_run = current_run.model_copy(deep=True)
        current_run.artifact_revision = _artifact_revision_for_run(current_run)

    return AgentResponse(
        thread_id=thread.thread_id,
        bound_run_id=thread.bound_run_id,
        status=status_value,
        content=latest_assistant,
        approval_request=thread.pending_approval,
        messages=thread.messages,
        current_run=current_run,
        recent_runs=recent_runs,
        project_runs=project_runs,
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


def _find_owned_run_for_thread(thread: ThreadState, run_id: str | None = None):
    """Find a mutable run only when its persisted owner matches the URL thread."""
    candidates = []
    if thread.current_run is not None:
        candidates.append(thread.current_run)
    candidates.extend(thread.recent_runs)
    if run_id is None:
        for run in candidates:
            if run.owner_thread_id == thread.thread_id:
                return run
        return None
    for run in candidates:
        if run.run_id == run_id and run.owner_thread_id == thread.thread_id:
            return run

    run = artifact_store.find_run_by_id(run_id)
    if run is not None and run.owner_thread_id == thread.thread_id:
        return run
    return None


def _find_attached_run_for_thread(thread: ThreadState, run_id: str | None = None):
    """Find a mutable run already attached to this in-memory thread state."""
    candidates = []
    if thread.current_run is not None:
        candidates.append(thread.current_run)
    candidates.extend(thread.recent_runs)
    for run in candidates:
        if (run_id is None or run.run_id == run_id) and run.owner_thread_id == thread.thread_id:
            return run
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

    try:
        content = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 upload payload.") from exc

    safe_stem = slugify_project_name(stem)
    while True:
        candidate = upload_root / f"{timestamp}-{safe_stem}-{secrets.token_hex(8)}{suffix}"
        try:
            with candidate.open("xb") as handle:
                handle.write(content)
            break
        except FileExistsError:
            continue
    return UploadImageResponse(image_path=str(candidate), filename=filename, size_bytes=len(content))


def _execute_agent_in_background(
    thread_id: str,
    run_id: str,
    request: AgentRequest,
    artifact_dir: str,
    api_key: str,
    cancellation_event: Event,
) -> None:
    thread_store = get_thread_store()
    active_run_id = run_id
    _mark_active_run(active_run_id)
    settings = get_settings()
    retry_limits = resolve_retry_limits(settings, request)
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
                "retry_limits": retry_limits.model_dump(mode="json"),
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
            run_id=run_id,
            project_name=thread.current_run.project_name if thread.current_run else None,
            api_key_override=api_key,
            use_frozen_runtime=True,
            cancellation_event=cancellation_event,
        )
        final_content = pipeline.run()
        if cancellation_event.is_set():
            raise RunCancelledError("Run cancelled by the user.")
    except RunCancelledError as exc:
        thread_store.append_message(thread_id, ChatMessage(role="system", content=str(exc)))
        thread = thread_store.finish_run(
            thread_id,
            status="cancelled",
            stage="cancelled",
            title="Run cancelled",
            detail=str(exc),
            level="warning",
        )
        artifact_store.write_metadata(thread)
        return
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
        thread_store.append_message(
            thread_id,
            ChatMessage(role="system", content=f"Conversion pipeline paused: {exc}"),
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
        thread_store.append_message(
            thread_id,
            ChatMessage(role="system", content=f"Conversion pipeline failed: {exc}"),
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


def _execute_resume_conversion_in_background(
    thread_id: str,
    run_id: str,
    request: AgentRequest,
    artifact_dir: str,
    api_key: str,
    cancellation_event: Event,
) -> None:
    thread_store = get_thread_store()
    active_run_id = run_id
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
            run_id=run_id,
            project_name=thread.current_run.project_name if thread.current_run else None,
            api_key_override=api_key,
            use_frozen_runtime=True,
            cancellation_event=cancellation_event,
        )
        final_content = pipeline.run()
        if cancellation_event.is_set():
            raise RunCancelledError("Run cancelled by the user.")
    except RunCancelledError as exc:
        thread_store.append_message(thread_id, ChatMessage(role="system", content=str(exc)))
        thread = thread_store.finish_run(
            thread_id,
            status="cancelled",
            stage="cancelled",
            title="Run cancelled",
            detail=str(exc),
            level="warning",
        )
        artifact_store.write_metadata(thread)
        return
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
        thread_store.append_message(
            thread_id,
            ChatMessage(role="system", content=f"Conversion pipeline paused: {exc}"),
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
        thread_store.append_message(
            thread_id,
            ChatMessage(role="system", content=f"Conversion resume failed: {exc}"),
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


def _run_agent_in_background(
    thread_id: str,
    run_id: str,
    request: AgentRequest,
    artifact_dir: str,
    api_key: str,
    lease: ArtifactLease,
    cancellation_event: Event,
) -> None:
    try:
        _execute_agent_in_background(thread_id, run_id, request, artifact_dir, api_key, cancellation_event)
    finally:
        _unmark_active_run(run_id)
        artifact_leases.release(lease)
        _remove_cancel_event(run_id)


def _resume_conversion_in_background(
    thread_id: str,
    run_id: str,
    request: AgentRequest,
    artifact_dir: str,
    api_key: str,
    lease: ArtifactLease,
    cancellation_event: Event,
) -> None:
    try:
        _execute_resume_conversion_in_background(
            thread_id, run_id, request, artifact_dir, api_key, cancellation_event
        )
    finally:
        _unmark_active_run(run_id)
        artifact_leases.release(lease)
        _remove_cancel_event(run_id)


def _artifact_conflict(artifact_dir: str | Path) -> HTTPException:
    lease = artifact_leases.get(artifact_dir)
    operation = lease.operation if lease is not None else "another operation"
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"This project is already in use by {operation}.",
    )


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


@app.get("/runs", response_model=RunListResponse)
def list_saved_runs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=6, ge=1, le=100),
    status_filter: str = Query(default="all", alias="status"),
    search: str = Query(default="", max_length=200),
    sort: str = Query(default="updated_desc"),
) -> RunListResponse:
    if status_filter not in {"all", "completed", "failed", "paused"}:
        raise HTTPException(status_code=400, detail="Unsupported History status filter.")
    if sort not in {"updated_desc", "name_asc", "status_asc"}:
        raise HTTPException(status_code=400, detail="Unsupported History sort order.")
    runs, total, total_pages, has_more = artifact_store.list_runs_page(
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        search=search,
        sort=sort,
    )
    for run in runs:
        run.artifact_revision = _artifact_revision_for_run(run)
    return RunListResponse(
        runs=runs,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_more=has_more,
    )


@app.post("/runs/{run_id}/open", response_model=RunOpenResponse)
def open_saved_run(run_id: str) -> RunOpenResponse:
    run = artifact_store.find_run_by_id(run_id)
    if run is None or not run.owner_thread_id:
        raise HTTPException(status_code=404, detail="Saved project was not found.")
    try:
        thread = get_thread_store().attach_persisted_run(run)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RunOpenResponse(
        thread_id=thread.thread_id,
        run=run,
        snapshot=build_agent_response(thread),
    )


@app.get("/runs/{run_id}/history-preview", response_model=HistoryPreviewResponse)
def get_history_preview_metadata(run_id: str) -> HistoryPreviewResponse:
    run = artifact_store.find_run_by_id(run_id)
    if run is None or not run.artifact_dir:
        raise HTTPException(status_code=404, detail="Saved project was not found.")
    previews = artifact_store.find_existing_history_previews(run.artifact_dir)
    return HistoryPreviewResponse(
        run_id=run_id,
        input_preview_url=f"/runs/{run_id}/preview/input" if previews["input"] else None,
        output_preview_url=f"/runs/{run_id}/preview/output" if previews["output"] else None,
    )


@app.get("/runs/{run_id}/preview/{kind}")
def get_history_preview_file(run_id: str, kind: str) -> FileResponse:
    if kind not in {"input", "output"}:
        raise HTTPException(status_code=404, detail="Preview kind was not found.")
    run = artifact_store.find_run_by_id(run_id)
    if run is None or not run.artifact_dir:
        raise HTTPException(status_code=404, detail="Saved project was not found.")
    preview_path = artifact_store.find_existing_history_previews(run.artifact_dir)[kind]
    if preview_path is None:
        raise HTTPException(status_code=404, detail="Preview is not available.")
    media_type = mimetypes.guess_type(preview_path.name)[0]
    if preview_path.suffix.lower() == ".svg":
        media_type = "image/svg+xml"
    return FileResponse(preview_path, media_type=media_type)


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
    run = _find_owned_run_for_thread(thread, run_id)
    if run is None or not run.artifact_dir:
        raise HTTPException(status_code=404, detail="Saved project was not found.")
    lease = artifact_leases.try_acquire(
        run.artifact_dir,
        owner_id=f"rename:{run_id}",
        operation="rename",
    )
    if lease is None:
        raise _artifact_conflict(run.artifact_dir)
    try:
        updated_run = artifact_store.update_run_project_name(run, payload.project_name)
        thread_store.update_run_project_name(thread_id, run_id, payload.project_name)
        return updated_run
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        artifact_leases.release(lease)


@app.delete("/threads/{thread_id}/runs/{run_id}")
def delete_thread_run(
    thread_id: str,
    run_id: str,
    artifact_dir: str | None = None,
) -> dict[str, bool | str | None]:
    thread_store = get_thread_store()
    thread = thread_store.get(thread_id)
    run = _find_owned_run_for_thread(thread, run_id)
    target_artifact_dir = run.artifact_dir if run is not None else None
    if not target_artifact_dir:
        raise HTTPException(status_code=404, detail="Saved project was not found.")
    if artifact_dir and artifact_store.resolve_run_dir(artifact_dir) != artifact_store.resolve_run_dir(target_artifact_dir):
        raise HTTPException(status_code=400, detail="Artifact directory does not match the requested run.")
    lease = artifact_leases.try_acquire(
        target_artifact_dir,
        owner_id=f"delete:{run_id}",
        operation="delete",
    )
    if lease is None:
        raise _artifact_conflict(target_artifact_dir)
    try:
        deleted_dir = artifact_store.delete_run_dir(target_artifact_dir)
        thread_store.remove_run(thread_id, run_id)
        return {
            "ok": True,
            "run_id": run.run_id if run is not None else run_id,
            "project_name": run.project_name if run is not None else deleted_dir.name,
            "artifact_dir": str(deleted_dir),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        artifact_leases.release(lease)


@app.post("/threads/{thread_id}/runs/{run_id}/cancel")
def cancel_thread_run(thread_id: str, run_id: str) -> dict[str, bool | str]:
    thread = get_thread_store().get(thread_id)
    run = thread.current_run
    if run is None or run.run_id != run_id:
        raise HTTPException(status_code=404, detail="Active run was not found.")
    if run.status not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="This run can no longer be cancelled.")
    if not _request_run_cancel(run_id):
        raise HTTPException(status_code=409, detail="Cancellation is not available for this run.")
    cancelled_while_queued = _cancel_queued_future(run_id)
    return {
        "ok": True,
        "run_id": run_id,
        "status": "cancelled" if cancelled_while_queued else "cancelling",
    }


def _resolve_owned_resume_target(thread_id: str, run_id: str) -> tuple[ThreadState, ExecutionRun, Path]:
    thread = get_thread_store().get(thread_id)
    run = _find_owned_run_for_thread(thread, run_id)
    if run is None or not run.artifact_dir:
        raise HTTPException(status_code=404, detail="Owned resumable run was not found.")
    run_dir = artifact_store.resolve_run_dir(run.artifact_dir)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="Owned resumable run was not found.")
    return thread, run, run_dir


@app.get("/runs/resume-plan", response_model=ResumePlan)
def get_resume_plan(thread_id: str, run_id: str) -> ResumePlan:
    _, _, run_dir = _resolve_owned_resume_target(thread_id, run_id)
    return build_resume_plan(run_dir)


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


def _execute_manual_adjustment(
    thread_id: str,
    payload: ManualAdjustmentRequest,
    thread: ThreadState,
    run: ExecutionRun,
    lease: ArtifactLease,
) -> ManualAdjustmentResponse:
    thread_store = get_thread_store()
    try:
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
    finally:
        artifact_leases.release(lease)
        _unmark_manual_adjustment(thread_id)


@app.post("/threads/{thread_id}/manual-adjust", response_model=ManualAdjustmentResponse)
async def manual_adjust_artifacts(thread_id: str, payload: ManualAdjustmentRequest) -> ManualAdjustmentResponse:
    thread = get_thread_store().get(thread_id)
    run = _find_attached_run_for_thread(thread, payload.run_id)
    if run is None or not run.artifact_dir:
        raise HTTPException(status_code=404, detail="No artifact-backed run found for this thread.")
    lease = artifact_leases.try_acquire(
        run.artifact_dir,
        owner_id=f"manual-adjust:{thread_id}:{secrets.token_hex(8)}",
        operation="manual adjustment",
    )
    if lease is None:
        raise _artifact_conflict(run.artifact_dir)
    if not _try_mark_manual_adjustment(thread_id):
        artifact_leases.release(lease)
        raise HTTPException(
            status_code=409,
            detail="This thread already has a conversion or manual adjustment in progress.",
        )
    try:
        future = manual_adjustment_executor.submit(
            _execute_manual_adjustment,
            thread_id,
            payload,
            thread,
            run,
            lease,
        )
    except Exception as exc:
        artifact_leases.release(lease)
        _unmark_manual_adjustment(thread_id)
        response_status = 429 if isinstance(exc, QueueFullError) else 503
        raise HTTPException(
            status_code=response_status,
            detail=str(exc) or "Manual adjustment could not be queued.",
        ) from exc
    return await asyncio.shield(asyncio.wrap_future(future))


@app.post("/invoke", response_model=RunStartResponse)
def invoke_agent(payload: AgentRequest) -> RunStartResponse:
    thread_store = get_thread_store()
    settings = get_settings()
    resolved_message = settings.resolved_user_input(payload.message)
    payload = payload.model_copy(update={"message": resolved_message})
    payload, resolved_api_key = _freeze_run_request_settings(payload)
    if not payload.image_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`image_path` is required for conversion runs.",
        )
    thread = thread_store.get_or_create(payload.thread_id)
    run_dir = artifact_store.create_run_dir()
    run_id = run_dir.name
    project_name = payload.project_name.strip() if payload.project_name and payload.project_name.strip() else run_id
    with _thread_operation_lock:
        started_thread = None if thread.thread_id in _manual_adjustment_thread_ids else thread_store.try_begin_run(
            thread.thread_id,
            mode="invoke",
            stage="queued",
            title="Run accepted",
            detail="The request has been queued and will start shortly.",
            project_name=project_name,
            artifact_dir=str(run_dir),
            run_id=run_id,
        )
    if started_thread is None:
        try:
            artifact_store.delete_run_dir(str(run_dir))
        except (FileNotFoundError, OSError):
            pass
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This thread already has a conversion or manual adjustment in progress.",
        )
    thread = started_thread
    thread = thread_store.append_message(
        thread.thread_id,
        ChatMessage(
            role="user",
            content=payload.message,
        ),
    )
    artifact_store.write_metadata(thread)
    _mark_active_run(thread.current_run.run_id if thread.current_run else None)
    run_id = thread.current_run.run_id if thread.current_run else ""
    cancellation_event = _register_cancel_event(run_id)
    lease = artifact_leases.try_acquire(
        run_dir,
        owner_id=run_id,
        operation="conversion",
    )
    if lease is None:
        _unmark_active_run(run_id)
        _remove_cancel_event(run_id)
        thread_store.finish_run(
            thread.thread_id,
            status="failed",
            stage="lease-conflict",
            title="Run could not acquire its project",
            detail="The project directory is already in use by another operation.",
            level="error",
            error="The project directory is already in use by another operation.",
        )
        raise _artifact_conflict(run_dir)
    try:
        future = executor.submit(
            _run_agent_in_background,
            thread.thread_id,
            run_id,
            payload,
            str(run_dir),
            resolved_api_key,
            lease,
            cancellation_event,
        )
        _register_run_future(
            run_id,
            future,
            thread_id=thread.thread_id,
            lease=lease,
        )
    except Exception as exc:
        artifact_leases.release(lease)
        _unmark_active_run(run_id)
        _remove_cancel_event(run_id)
        thread_store.finish_run(
            thread.thread_id,
            status="failed",
            stage="queue-failed",
            title="Run could not be queued",
            detail=str(exc),
            level="error",
            error=str(exc),
        )
        response_status = 429 if isinstance(exc, QueueFullError) else 503
        raise HTTPException(status_code=response_status, detail=str(exc) or "Run could not be queued.") from exc
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
    thread, source_run, run_dir = _resolve_owned_resume_target(payload.thread_id, payload.run_id)
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

    request, resolved_api_key = _freeze_run_request_settings(request)
    lease = artifact_leases.try_acquire(
        run_dir,
        owner_id=f"resume:{payload.thread_id}:{payload.run_id}:{secrets.token_hex(8)}",
        operation="resume",
    )
    if lease is None:
        raise _artifact_conflict(run_dir)
    with _thread_operation_lock:
        started_thread = None if thread.thread_id in _manual_adjustment_thread_ids else thread_store.resume_bound_run(
            thread.thread_id,
            payload.run_id,
            stage="queued",
            title="Resume accepted",
            detail=f"Continuing the prior run from {plan.resume_stage or 'the latest checkpoint'}.",
        )
    if started_thread is None:
        artifact_leases.release(lease)
        raise HTTPException(
            status_code=409,
            detail="This thread already has a conversion or manual adjustment in progress.",
        )
    thread = started_thread
    artifact_store.write_metadata(thread)
    _mark_active_run(thread.current_run.run_id if thread.current_run else None)
    run_id = thread.current_run.run_id if thread.current_run else ""
    cancellation_event = _register_cancel_event(run_id)
    try:
        future = executor.submit(
            _resume_conversion_in_background,
            thread.thread_id,
            run_id,
            request,
            str(run_dir),
            resolved_api_key,
            lease,
            cancellation_event,
        )
        _register_run_future(
            run_id,
            future,
            thread_id=thread.thread_id,
            lease=lease,
        )
    except Exception as exc:
        artifact_leases.release(lease)
        _unmark_active_run(run_id)
        _remove_cancel_event(run_id)
        thread_store.finish_run(
            thread.thread_id,
            status="failed",
            stage="queue-failed",
            title="Resume could not be queued",
            detail=str(exc),
            level="error",
            error=str(exc),
        )
        response_status = 429 if isinstance(exc, QueueFullError) else 503
        raise HTTPException(status_code=response_status, detail=str(exc) or "Resume could not be queued.") from exc
    return RunStartResponse(thread_id=thread.thread_id, run=thread.current_run, messages=thread.messages)
