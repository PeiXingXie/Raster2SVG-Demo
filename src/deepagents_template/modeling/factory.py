"""Overview: Factories for low-level OpenAI-compatible clients and optional chat models."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from deepagents_template.config import Settings, get_settings


def build_chat_model(
    model_name: str,
    *,
    api_format: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    max_retries: int | None = None,
    use_previous_response_id: bool | None = None,
    settings: Settings | None = None,
) -> Any:
    """Build a ChatOpenAI instance for OpenAI-compatible APIs."""

    from langchain_openai import ChatOpenAI

    settings = settings or get_settings()
    model_kwargs: dict = {}
    resolved_api_format = settings.resolved_api_format(api_format)

    if resolved_api_format == "openai_responses":
        model_kwargs["use_responses_api"] = True
        model_kwargs["output_version"] = "responses/v1"
        if settings.resolved_use_previous_response_id(use_previous_response_id):
            model_kwargs["use_previous_response_id"] = True

    return ChatOpenAI(
        model=model_name,
        api_key=settings.resolved_api_key(api_key),
        base_url=settings.resolved_base_url(base_url),
        max_retries=settings.resolved_max_retries(max_retries),
        **model_kwargs,
    )


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
    )
