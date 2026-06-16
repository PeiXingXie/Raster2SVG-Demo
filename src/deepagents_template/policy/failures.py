"""Policy-model failure types and helpers for explicit hard failures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .tracing import build_policy_trace

POLICY_ERROR_INVALID_MODEL_RESPONSE = "InvalidModelResponseError"
POLICY_ERROR_VALIDATION = "ValidationError"
POLICY_ERROR_JSON_DECODE = "JSONDecodeError"
POLICY_ERROR_UNKNOWN = "UnknownPolicyModelError"


def _summarize_exception(exc: Exception) -> str:
    if exc.__class__.__name__ == "InvalidModelResponseError":
        return f"InvalidModelResponseError: {str(exc)}"
    error_count = getattr(exc, "error_count", None)
    if callable(error_count):
        return f"{type(exc).__name__}: {error_count()} validation errors"
    return f"{type(exc).__name__}: {str(exc).splitlines()[0]}"


def classify_policy_model_error(exc: Exception) -> str:
    if exc.__class__.__name__ == "InvalidModelResponseError":
        return POLICY_ERROR_INVALID_MODEL_RESPONSE
    if isinstance(exc, ValidationError):
        return POLICY_ERROR_VALIDATION
    if isinstance(exc, json.JSONDecodeError):
        return POLICY_ERROR_JSON_DECODE
    return POLICY_ERROR_UNKNOWN


class PolicyModelResponseError(RuntimeError):
    """Raised when a combined policy-model call returns an unusable payload."""

    def __init__(self, policy_name: str, exc: Exception) -> None:
        self.policy_name = policy_name
        self.error_type = classify_policy_model_error(exc)
        self.cause_exc = exc
        super().__init__(
            f"{self.error_type}: {policy_name} policy model call failed. {_summarize_exception(exc)}"
        )


def fail_policy_evaluation(
    pipeline: Any,
    *,
    trace_path: Path,
    policy_name: str,
    request_context: dict[str, Any],
    llm_request: dict[str, str],
    exc: Exception,
    raw_response: str | None = None,
    supervisor_memory_used: bool | None = None,
    history_delta_used: bool | None = None,
) -> None:
    """Persist a failure trace, then raise a typed policy-model error."""

    trace = build_policy_trace(
        policy_name=policy_name,
        request_context=request_context,
        llm_request=llm_request,
        raw_response=raw_response,
        proposed_decision=None,
        final_decision=None,
        applied_rules=[],
        fallback_used=False,
        error=_summarize_exception(exc),
        error_type=classify_policy_model_error(exc),
        supervisor_memory_used=supervisor_memory_used,
        supervisor_memory_persisted=bool(getattr(pipeline, "persist_supervisor_memory", lambda: False)())
        if callable(getattr(pipeline, "persist_supervisor_memory", None))
        else bool(getattr(pipeline, "supervisor_memory_persist_enabled", False)),
        history_delta_used=history_delta_used,
    )
    pipeline._write_json(trace_path, trace)
    raise PolicyModelResponseError(policy_name, exc) from exc
