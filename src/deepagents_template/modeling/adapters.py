"""Overview: Provider/format adapters that translate multimodal prompts to API calls."""

from __future__ import annotations

import base64
import json
import mimetypes
from abc import ABC, abstractmethod
from pathlib import Path

from openai import OpenAI


def _image_to_data_url(image_path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(image_path.name)
    mime_type = mime_type or "image/png"
    data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{data}"


def _guess_file_mime_type(file_path: Path) -> str:
    # SVG assets are provided as source text for the model to inspect/edit,
    # so we upload them as plain text instead of image attachments.
    suffix = file_path.suffix.lower()
    if suffix in {".txt", ".svgfrag", ".svg"}:
        return "text/plain"
    mime_type, _ = mimetypes.guess_type(file_path.name)
    if mime_type:
        return mime_type
    return "application/octet-stream"


def _file_to_data_url(file_path: Path) -> str:
    mime_type = _guess_file_mime_type(file_path)
    data = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{data}"


def extract_text_from_content_parts(content: object) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for item in content or []:
        text_value = extract_text_from_payload(item)
        if text_value:
            parts.append(text_value)
    return "\n".join(parts)


def extract_text_from_mapping(payload: dict) -> str:
    choices = payload.get("choices") or []
    if choices:
        first_choice = choices[0] or {}
        message = first_choice.get("message", {})
        extracted = extract_text_from_payload(message)
        if extracted:
            return extracted
        delta = first_choice.get("delta")
        extracted = extract_text_from_payload(delta)
        if extracted:
            return extracted
        nested_text = first_choice.get("text")
        extracted = extract_text_from_payload(nested_text)
        if extracted:
            return extracted

    output_text = payload.get("output_text")
    extracted = extract_text_from_payload(output_text)
    if extracted:
        return extracted

    for field_name in ("message", "delta", "content", "text", "value"):
        extracted = extract_text_from_payload(payload.get(field_name))
        if extracted:
            return extracted

    return ""


def extract_text_from_payload(payload: object) -> str:
    if payload is None:
        return ""
    model_dump = getattr(payload, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
        except TypeError:
            dumped = None
        if dumped is not None:
            return extract_text_from_payload(dumped)
    if isinstance(payload, str):
        stripped = payload.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return payload
            extracted = extract_text_from_payload(parsed)
            return extracted or payload
        return payload
    if isinstance(payload, dict):
        return extract_text_from_mapping(payload)
    if isinstance(payload, list):
        return extract_text_from_content_parts(payload)

    for field_name in ("text", "output_text", "value", "content"):
        extracted = extract_text_from_payload(getattr(payload, field_name, None))
        if extracted:
            return extracted
    return ""


class MultimodalApiAdapter(ABC):
    """Abstract multimodal API adapter used by the conversion pipeline."""

    def __init__(self, client: OpenAI, model_name: str) -> None:
        self.client = client
        self.model_name = model_name

    @abstractmethod
    def call(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        image_paths: list[Path] | None = None,
        file_paths: list[Path] | None = None,
    ) -> str:
        """Call the underlying multimodal API and return plain text."""


class OpenAIChatCompletionsAdapter(MultimodalApiAdapter):
    """OpenAI-compatible adapter using the Chat Completions API shape."""

    def _extract_text_from_content_parts(self, content: object) -> str:
        return extract_text_from_content_parts(content)

    def _extract_text_from_mapping(self, payload: dict) -> str:
        return extract_text_from_mapping(payload)

    def _extract_text_from_payload(self, payload: object) -> str:
        return extract_text_from_payload(payload)

    def _extract_text(self, response: object) -> str:
        extracted = self._extract_text_from_payload(response)
        if extracted:
            return extracted

        choices = getattr(response, "choices", None)
        if choices:
            message = choices[0].message
            extracted = self._extract_text_from_payload(message)
            if extracted:
                return extracted

        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text:
            return output_text

        text_value = getattr(response, "text", None)
        if isinstance(text_value, str) and text_value:
            return text_value

        raise TypeError(
            "Chat completions adapter expected a string, mapping, or SDK response object with choices."
        )

    def call(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        image_paths: list[Path] | None = None,
        file_paths: list[Path] | None = None,
    ) -> str:
        content: list[dict] = [{"type": "text", "text": user_prompt}]
        for image_path in image_paths or []:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _image_to_data_url(image_path)},
                }
            )
        for file_path in file_paths or []:
            content.append(
                {
                    "type": "file",
                    "file": {
                        "file_data": _file_to_data_url(file_path),
                        "filename": file_path.name,
                    },
                }
            )

        response = self.client.chat.completions.create(
            model=self.model_name,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
        )
        return self._extract_text(response)


class OpenAIResponsesAdapter(MultimodalApiAdapter):
    """OpenAI-compatible adapter using the Responses API shape."""

    def call(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        image_paths: list[Path] | None = None,
        file_paths: list[Path] | None = None,
    ) -> str:
        user_content: list[dict] = [{"type": "input_text", "text": user_prompt}]
        for image_path in image_paths or []:
            user_content.append(
                {
                    "type": "input_image",
                    "image_url": _image_to_data_url(image_path),
                }
            )
        for file_path in file_paths or []:
            user_content.append(
                {
                    "type": "input_file",
                    "file_data": _file_to_data_url(file_path),
                    "filename": file_path.name,
                }
            )

        response = self.client.responses.create(
            model=self.model_name,
            temperature=0,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
        )

        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text:
            return output_text

        parts: list[str] = []
        for output in getattr(response, "output", []) or []:
            for content in getattr(output, "content", []) or []:
                text_value = getattr(content, "text", None)
                if text_value:
                    parts.append(text_value)
        return "\n".join(parts)


def build_multimodal_adapter(
    *,
    client: OpenAI,
    model_name: str,
    api_provider: str,
    api_format: str,
) -> MultimodalApiAdapter:
    """Build a multimodal adapter from provider/format selection."""

    if api_provider != "openai_compatible":
        raise ValueError(
            f"Unsupported api_provider '{api_provider}'. "
            "Add a new MultimodalApiAdapter implementation to support it."
        )

    if api_format == "openai_chat_completions":
        return OpenAIChatCompletionsAdapter(client=client, model_name=model_name)
    if api_format == "openai_responses":
        return OpenAIResponsesAdapter(client=client, model_name=model_name)

    raise ValueError(
        f"Unsupported api_format '{api_format}'. "
        "Supported values are 'openai_chat_completions' and 'openai_responses'."
    )
