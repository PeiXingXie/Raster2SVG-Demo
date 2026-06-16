"""Helpers for persisting policy decision traces."""

from __future__ import annotations

from typing import Any


def build_policy_trace(
    *,
    policy_name: str,
    request_context: dict[str, Any],
    llm_request: dict[str, str],
    raw_response: str | None,
    proposed_decision: dict[str, Any] | None,
    final_decision: dict[str, Any] | None,
    applied_rules: list[dict[str, Any]],
    fallback_used: bool,
    error: str | None = None,
    error_type: str | None = None,
    supervisor_memory_used: bool | None = None,
    supervisor_memory_persisted: bool | None = None,
    history_delta_used: bool | None = None,
) -> dict[str, Any]:
    """Build a single JSON payload that explains one policy decision."""

    return {
        "policy_name": policy_name,
        "request_context": request_context,
        "llm_request": llm_request,
        "raw_response": raw_response,
        "proposed_decision": proposed_decision,
        "final_decision": final_decision,
        "applied_rules": applied_rules,
        "fallback_used": fallback_used,
        "error": error,
        "error_type": error_type,
        "supervisor_memory_used": supervisor_memory_used,
        "supervisor_memory_persisted": supervisor_memory_persisted,
        "history_delta_used": history_delta_used,
    }
