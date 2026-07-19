"""Overview: Shared runtime singleton for thread state."""

from __future__ import annotations

from functools import lru_cache
from deepagents_template.memory import ThreadStore


@lru_cache(maxsize=1)
def get_thread_store() -> ThreadStore:
    """Shared thread store for chat history and approval state."""

    return ThreadStore()
