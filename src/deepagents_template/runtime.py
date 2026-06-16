"""Overview: Shared runtime singletons and helpers for thread and approval handling."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from deepagents_template.agent import build_agent
from deepagents_template.memory import ThreadStore
from deepagents_template.schemas import ApprovalRequest


@lru_cache(maxsize=1)
def get_checkpointer() -> MemorySaver:
    """Shared in-memory checkpointer for short-term agent memory."""

    return MemorySaver()


@lru_cache(maxsize=1)
def get_thread_store() -> ThreadStore:
    """Shared thread store for chat history and approval state."""

    return ThreadStore()


@lru_cache(maxsize=1)
def get_agent():
    """Build a singleton agent bound to the shared checkpointer."""

    return build_agent(checkpointer=get_checkpointer())


def build_thread_config(thread_id: str) -> dict[str, dict[str, str]]:
    """Return LangGraph config for a given chat thread."""

    return {"configurable": {"thread_id": thread_id}}


def approval_decision_to_command(decision: str, comment: str | None) -> Command:
    """Convert an approval decision into a LangGraph resume command."""

    payload = {"decision": decision}
    if comment:
        payload["comment"] = comment
    return Command(resume=payload)


def extract_approval_request(result: Any) -> ApprovalRequest | None:
    """Extract approval payload from an interrupted graph result."""

    interrupt_payloads = []

    if isinstance(result, dict):
        interrupt_payloads.extend(result.get("__interrupt__", []))
        interrupt_payloads.extend(result.get("interrupts", []))
    else:
        interrupt_payloads.extend(getattr(result, "__interrupt__", []))
        interrupt_payloads.extend(getattr(result, "interrupts", []))

    for item in interrupt_payloads:
        value = getattr(item, "value", item)

        if isinstance(value, dict) and value.get("type") == "approval_request":
            return ApprovalRequest(
                action_name=value["action_name"],
                action_summary=value["action_summary"],
                tool_name=value["tool_name"],
                payload=value.get("payload", {}),
            )

    return None


def extract_final_content(result: Any) -> str | None:
    """Extract the final assistant message from an agent result."""

    messages = None
    if isinstance(result, dict):
        messages = result.get("messages")
    else:
        messages = getattr(result, "messages", None)

    if not messages:
        return None

    last_message = messages[-1]
    content = getattr(last_message, "content", None)
    if isinstance(content, list):
        return "\n".join(str(item) for item in content)
    if content is not None:
        return str(content)
    return str(last_message)
