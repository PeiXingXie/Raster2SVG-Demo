"""Overview: Factory for the low-level OpenAI-compatible client."""

from __future__ import annotations

import httpx
from openai import OpenAI

from deepagents_template.config import Settings, get_settings

OPENAI_CLIENT_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=600.0, pool=600.0)


def build_openai_client(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    max_retries: int | None = None,
    settings: Settings | None = None,
) -> OpenAI:
    """Build a low-level OpenAI-compatible client for multimodal model calls."""

    settings = settings or get_settings()
    return OpenAI(
        api_key=settings.resolved_api_key(api_key),
        base_url=settings.resolved_base_url(base_url),
        max_retries=settings.resolved_max_retries(max_retries),
        timeout=OPENAI_CLIENT_TIMEOUT,
    )
