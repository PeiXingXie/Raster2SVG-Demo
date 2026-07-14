"""Helpers for turning raw exceptions and run metadata into structured diagnostics."""

from __future__ import annotations

from pathlib import Path

from deepagents_template.policy.failures import PolicyModelResponseError
from deepagents_template.schemas import ExecutionRun, FailureArtifactHint, FailureDiagnostic, RunState


def _safe_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _find_last_failed_event(run: ExecutionRun | None):
    if run is None:
        return None
    for event in reversed(run.events or []):
        payload = event.payload or {}
        if event.level == "error" or payload.get("status") == "error":
            return event
    return (run.events or [None])[-1] if run.events else None


def _find_last_success_stage(run: ExecutionRun | None, *, fallback_stage: str | None = None) -> str | None:
    if run is None:
        return None
    success_like = {"success", "completed", "ok"}
    failed_stage = fallback_stage or run.failure_stage or run.current_stage
    seen_failed = False
    for event in reversed(run.events or []):
        if getattr(event, "stage", None) == failed_stage:
            seen_failed = True
            continue
        payload = event.payload or {}
        if event.level == "error" or payload.get("status") == "error":
            seen_failed = True
            continue
        if seen_failed:
            return getattr(event, "stage", None)
        if event.level in success_like or payload.get("status") in success_like:
            return getattr(event, "stage", None)
    return None


def _extract_root_cause(exc: Exception) -> tuple[str | None, str | None]:
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        return type(cause).__name__, _safe_text(cause)
    text = _safe_text(exc)
    if not text:
        return None, None
    if ": " in text:
        prefix, suffix = text.rsplit(": ", 1)
        if prefix and suffix:
            root_type = prefix.split()[-1]
            if root_type.endswith("Error") or root_type.endswith("Exception"):
                return root_type, suffix
    return type(exc).__name__, text


def _policy_name_from_exception(exc: Exception) -> str | None:
    if isinstance(exc, PolicyModelResponseError):
        return exc.policy_name
    return None


def _collect_artifact_hints(run: ExecutionRun | None, artifact_dir: str | None) -> list[FailureArtifactHint]:
    hints: list[FailureArtifactHint] = []
    if artifact_dir:
        hints.append(FailureArtifactHint(label="Run state", relative_path="run_state.json", kind="state"))
        hints.append(FailureArtifactHint(label="Timeline", relative_path="logs\\timeline.json", kind="timeline"))
        hints.append(FailureArtifactHint(label="Overview", relative_path="logs\\overview.json", kind="overview"))
    event = _find_last_failed_event(run)
    payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
    request_path = _safe_text(payload.get("request_path"))
    raw_response_path = _safe_text(payload.get("raw_response_path"))
    error_path = _safe_text(payload.get("error_path"))
    if request_path:
        hints.append(FailureArtifactHint(label="Failed request payload", relative_path=request_path.replace("/", "\\"), kind="request"))
    if raw_response_path:
        hints.append(FailureArtifactHint(label="Failed raw response", relative_path=raw_response_path.replace("/", "\\"), kind="response"))
    if error_path:
        relative_error_path = error_path
        if artifact_dir:
            try:
                relative_error_path = str(Path(error_path).resolve().relative_to(Path(artifact_dir).resolve()))
            except (OSError, ValueError):
                relative_error_path = error_path
        hints.append(FailureArtifactHint(label="Render error log", relative_path=relative_error_path.replace("/", "\\"), kind="render-error"))
    return hints


def build_failure_diagnostic(
    *,
    status: str,
    terminal_stage: str | None,
    failure_stage: str | None,
    error_type: str | None,
    error_message: str | None,
    root_cause_type: str | None,
    root_cause_message: str | None,
    policy_name: str | None = None,
    model_name: str | None = None,
    response_model: str | None = None,
    attempt: int | None = None,
    attempts_total: int | None = None,
    last_event_title: str | None = None,
    last_event_detail: str | None = None,
    last_success_stage: str | None = None,
    request_path: str | None = None,
    raw_response_path: str | None = None,
    artifact_hints: list[FailureArtifactHint] | None = None,
) -> FailureDiagnostic:
    summary = error_message
    if failure_stage and root_cause_type:
        summary = f"{failure_stage} failed because {root_cause_type} occurred."
    elif failure_stage and error_message:
        summary = f"{failure_stage} failed: {error_message}"
    return FailureDiagnostic(
        status=status,
        terminal_stage=terminal_stage,
        failure_stage=failure_stage,
        summary=summary,
        error_type=error_type,
        error_message=error_message,
        root_cause_type=root_cause_type,
        root_cause_message=root_cause_message,
        policy_name=policy_name,
        model_name=model_name,
        response_model=response_model,
        attempt=attempt,
        attempts_total=attempts_total,
        last_event_title=last_event_title,
        last_event_detail=last_event_detail,
        last_success_stage=last_success_stage,
        request_path=request_path,
        raw_response_path=raw_response_path,
        artifact_hints=list(artifact_hints or []),
    )


def build_failure_diagnostic_from_exception(
    exc: Exception,
    *,
    run: ExecutionRun | None,
    terminal_stage: str,
    artifact_dir: str | None,
    failure_stage: str | None = None,
    status: str = "failed",
) -> FailureDiagnostic:
    event = _find_last_failed_event(run)
    payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
    resolved_failure_stage = failure_stage or getattr(run, "failure_stage", None) or getattr(run, "current_stage", None)
    root_cause_type, root_cause_message = _extract_root_cause(exc)
    request_path = _safe_text(payload.get("request_path"))
    raw_response_path = _safe_text(payload.get("raw_response_path"))
    return build_failure_diagnostic(
        status=status,
        terminal_stage=terminal_stage,
        failure_stage=resolved_failure_stage,
        error_type=type(exc).__name__,
        error_message=_safe_text(exc),
        root_cause_type=root_cause_type,
        root_cause_message=root_cause_message,
        policy_name=_policy_name_from_exception(exc),
        model_name=_safe_text(payload.get("model")),
        response_model=_safe_text(payload.get("response_model")),
        attempt=payload.get("attempt"),
        attempts_total=payload.get("attempts_total"),
        last_event_title=_safe_text(getattr(event, "title", None)),
        last_event_detail=_safe_text(getattr(event, "detail", None)),
        last_success_stage=_find_last_success_stage(run, fallback_stage=resolved_failure_stage),
        request_path=request_path,
        raw_response_path=raw_response_path,
        artifact_hints=_collect_artifact_hints(run, artifact_dir),
    )


def build_failure_diagnostic_from_run_state(
    *,
    run_state: RunState,
    run: ExecutionRun | None,
    artifact_dir: str | None,
) -> FailureDiagnostic | None:
    if run_state.failure.diagnostic is not None:
        return run_state.failure.diagnostic
    if not (run_state.failure.type or run_state.failure.message or run_state.pause_reason):
        return None
    event = _find_last_failed_event(run)
    payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
    return build_failure_diagnostic(
        status=run_state.status,
        terminal_stage=getattr(run, "current_stage", None) or run_state.status,
        failure_stage=run_state.failure.failure_stage or run_state.current_stage,
        error_type=run_state.failure.type or ("PausedRun" if run_state.status == "paused" else None),
        error_message=run_state.failure.message or run_state.pause_reason,
        root_cause_type=run_state.failure.root_cause_type or run_state.failure.type,
        root_cause_message=run_state.failure.root_cause_message or run_state.failure.message or run_state.pause_reason,
        model_name=_safe_text(payload.get("model")),
        response_model=_safe_text(payload.get("response_model")),
        attempt=payload.get("attempt"),
        attempts_total=payload.get("attempts_total"),
        last_event_title=_safe_text(getattr(event, "title", None)),
        last_event_detail=_safe_text(getattr(event, "detail", None)),
        last_success_stage=_find_last_success_stage(run, fallback_stage=run_state.failure.failure_stage or run_state.current_stage),
        request_path=_safe_text(payload.get("request_path")),
        raw_response_path=_safe_text(payload.get("raw_response_path")),
        artifact_hints=_collect_artifact_hints(run, artifact_dir),
    )


def load_failure_diagnostic_from_run_dir(run_dir: Path, run: ExecutionRun | None) -> FailureDiagnostic | None:
    from deepagents_template.resume import load_run_state

    run_state = load_run_state(run_dir)
    if run_state is None:
        return None
    return build_failure_diagnostic_from_run_state(
        run_state=run_state,
        run=run,
        artifact_dir=str(run_dir),
    )


def merge_failure_diagnostics(
    primary: FailureDiagnostic | None,
    fallback: FailureDiagnostic | None,
) -> FailureDiagnostic | None:
    if primary is None:
        return fallback
    if fallback is None:
        return primary
    merged = primary.model_dump(mode="python")
    fallback_payload = fallback.model_dump(mode="python")

    def is_empty(value: object) -> bool:
        return value is None or value == "" or value == []

    for key, fallback_value in fallback_payload.items():
        current_value = merged.get(key)
        if is_empty(current_value) and not is_empty(fallback_value):
            merged[key] = fallback_value
    return FailureDiagnostic.model_validate(merged)
