"""Overview: Structured multimodal call execution, JSON parsing, and call-level logging."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Callable, TypeVar

from pydantic import BaseModel
from pydantic import ValidationError

from deepagents_template.config import get_settings
from deepagents_template.modeling.adapters import build_multimodal_adapter, extract_text_from_payload
from deepagents_template.modeling.factory import build_openai_client


ModelT = TypeVar("ModelT", bound=BaseModel)
RETRYABLE_RESPONSE_ERROR_SNIPPETS = (
    "did not contain a json object",
    "did not contain a complete json object",
    "did not contain a json payload",
)
try:
    _MODEL_CALL_CONCURRENCY = max(1, int(os.getenv("SHAPE_STUDIO_MODEL_CALL_CONCURRENCY", "8")))
except ValueError:
    _MODEL_CALL_CONCURRENCY = 8
_MODEL_CALL_SEMAPHORE = threading.BoundedSemaphore(_MODEL_CALL_CONCURRENCY)


def _extract_provider_error_message(payload: dict) -> str | None:
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    if isinstance(error, str) and error.strip():
        return error.strip()
    return None


def _payload_preview(payload: object, *, max_chars: int = 1200) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    except TypeError:
        text = str(payload)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}…"


def _looks_like_empty_provider_envelope(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    object_type = str(payload.get("object") or "")
    choices = payload.get("choices")
    has_choices = isinstance(choices, list) and len(choices) > 0
    has_content = bool(extract_text_from_payload(payload))
    if has_content:
        return False
    if object_type.startswith("chat.completion.chunk") and not has_choices:
        return True
    if object_type.startswith("chat.completion") and not has_choices:
        return True
    return False


class InvalidModelResponseError(ValueError):
    """Raised when a model response exists but is not a valid business payload."""

    def __init__(
        self,
        message: str,
        *,
        payload: object | None = None,
        cause: Exception | None = None,
        failure_kind: str | None = None,
    ) -> None:
        super().__init__(message)
        self.payload = payload
        self.cause = cause
        self.payload_preview = _payload_preview(payload) if payload is not None else ""
        self.failure_kind = failure_kind or "invalid_model_response"


def classify_model_format_error(exc: Exception | None) -> str:
    if exc is None:
        return "unknown_model_error"
    if isinstance(exc, InvalidModelResponseError):
        if getattr(exc, "failure_kind", None):
            return str(exc.failure_kind)
        if isinstance(exc.cause, ValidationError):
            return classify_model_format_error(exc.cause)
        return "invalid_model_response"
    if isinstance(exc, ValidationError):
        errors = exc.errors()
        if any(error.get("type") == "missing" for error in errors):
            return "schema_missing_required_field"
        if any(str(error.get("type", "")).startswith("literal_error") for error in errors):
            return "schema_invalid_enum"
        if any("list_type" in str(error.get("type", "")) for error in errors):
            return "schema_wrong_collection_shape"
        return "schema_validation_error"
    if isinstance(exc, json.JSONDecodeError):
        message = str(exc).lower()
        if "unterminated" in message or "expecting value" in message:
            return "json_decode_error"
        return "json_decode_error"
    if isinstance(exc, ValueError):
        message = str(exc).strip().lower()
        if "did not contain a json object" in message:
            return "json_not_found"
        if "did not contain a complete json object" in message:
            return "json_incomplete"
        if "did not contain a json payload" in message:
            return "json_payload_missing"
        if "empty provider envelope" in message:
            return "provider_empty_payload"
    return exc.__class__.__name__


def _iter_json_documents(text: str) -> list[object]:
    stripped = _strip_code_fences(text).strip()
    if not stripped:
        return []
    decoder = json.JSONDecoder()
    documents: list[object] = []
    index = 0
    length = len(stripped)
    while index < length:
        while index < length and stripped[index].isspace():
            index += 1
        if index >= length:
            break
        if stripped.startswith("data:", index):
            index += 5
            while index < length and stripped[index].isspace():
                index += 1
            if stripped.startswith("[DONE]", index):
                index += len("[DONE]")
                continue
        try:
            payload, end_index = decoder.raw_decode(stripped, index)
        except json.JSONDecodeError:
            break
        documents.append(payload)
        index = end_index
    return documents


def _extract_first_json_value(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
    start = next((idx for idx, char in enumerate(stripped) if char in "{["), -1)
    if start == -1:
        raise ValueError("Model response did not contain a JSON object.")

    opening = stripped[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(stripped)):
        char = stripped[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == opening:
            depth += 1
            continue
        if char == closing:
            depth -= 1
            if depth == 0:
                return stripped[start : index + 1]
    raise ValueError("Model response did not contain a complete JSON object.")


def extract_json_object(text: str) -> str:
    return _extract_first_json_value(text)


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def normalize_model_payload(payload: object) -> object:
    if payload is None:
        return payload
    if isinstance(payload, str):
        stripped = _strip_code_fences(payload)
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return stripped
            return normalize_model_payload(parsed)
        return stripped
    if isinstance(payload, (dict, list)):
        extracted = extract_text_from_payload(payload)
        if isinstance(extracted, str) and extracted and extracted != payload:
            normalized = normalize_model_payload(extracted)
            if normalized != extracted or isinstance(normalized, (dict, list)):
                return normalized
        return payload
    model_dump = getattr(payload, "model_dump", None)
    if callable(model_dump):
        try:
            return normalize_model_payload(model_dump())
        except TypeError:
            return payload
    return payload


def parse_model_response_payload(raw_text: str) -> dict | list:
    normalized = normalize_model_payload(raw_text)
    if isinstance(normalized, (dict, list)):
        return normalized
    if isinstance(normalized, str):
        documents = _iter_json_documents(normalized)
        provider_error_messages = [
            message
            for payload in documents
            if isinstance(payload, dict)
            for message in [_extract_provider_error_message(payload)]
            if message
        ]
        for payload in documents:
            normalized_payload = normalize_model_payload(payload)
            if isinstance(normalized_payload, (dict, list)):
                if isinstance(normalized_payload, dict) and _extract_provider_error_message(normalized_payload):
                    continue
                extracted_text = extract_text_from_payload(normalized_payload)
                if extracted_text:
                    return parse_model_response_payload(extracted_text)
                if _looks_like_empty_provider_envelope(normalized_payload):
                    raise InvalidModelResponseError(
                        "Model response returned an empty provider envelope without assistant content.",
                        payload=normalized_payload,
                        failure_kind="provider_empty_payload",
                    )
                if normalized_payload is payload and isinstance(payload, dict):
                    continue
                return normalized_payload
        if provider_error_messages:
            raise ValueError(provider_error_messages[-1])
        return json.loads(extract_json_object(normalized))
    raise ValueError("Model response did not contain a JSON payload.")


def summarize_exception(exc: Exception) -> str:
    if isinstance(exc, InvalidModelResponseError):
        return f"{type(exc).__name__}: {str(exc)}"
    error_count = getattr(exc, "error_count", None)
    if callable(error_count):
        return f"{type(exc).__name__}: {error_count()} validation errors"
    return f"{type(exc).__name__}: {str(exc).splitlines()[0]}"


def is_retryable_response_error(exc: Exception) -> bool:
    if isinstance(exc, InvalidModelResponseError):
        return True
    if isinstance(exc, (json.JSONDecodeError, ValidationError)):
        return True
    if isinstance(exc, ValueError):
        message = str(exc).strip().lower()
        return any(snippet in message for snippet in RETRYABLE_RESPONSE_ERROR_SNIPPETS)
    return False


def build_logged_prompt_payload(
    *,
    model_name: str,
    api_format: str,
    response_model: str,
    system_prompt: str,
    user_prompt: str,
    image_paths: list[Path] | None = None,
    file_paths: list[Path] | None = None,
) -> dict:
    return {
        "model": model_name,
        "api_format": api_format,
        "response_model": response_model,
        "prompt": {
            "system": system_prompt,
            "user": user_prompt,
        },
        "attachments": [
            {"kind": "image", "path": str(path)}
            for path in (image_paths or [])
        ]
        + [
            {"kind": "file", "path": str(path), "filename": path.name}
            for path in (file_paths or [])
        ],
    }


class MultimodalJsonCaller:
    """Low-level multimodal caller that asks the model for strict JSON output."""

    def __init__(
        self,
        model_name: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        max_retries: int | None = None,
        api_provider: str,
        api_format: str,
        response_callback: Callable[[dict], None] | None = None,
        request_callback: Callable[[dict], None] | None = None,
        warning_callback: Callable[[dict], None] | None = None,
        cancellation_check: Callable[[], None] | None = None,
        response_validation_max_attempts: int | None = None,
    ) -> None:
        self.client = build_openai_client(
            api_key=api_key,
            base_url=base_url,
            max_retries=max_retries,
        )
        self.model_name = model_name
        self.api_provider = api_provider
        self.api_format = api_format
        self.response_callback = response_callback
        self.request_callback = request_callback
        self.warning_callback = warning_callback
        self.cancellation_check = cancellation_check
        self.response_validation_max_attempts = get_settings().resolved_response_validation_max_attempts(
            response_validation_max_attempts
        )
        self.adapter = build_multimodal_adapter(
            client=self.client,
            model_name=model_name,
            api_provider=api_provider,
            api_format=api_format,
        )

    def call(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        image_paths: list[Path] | None = None,
        file_paths: list[Path] | None = None,
    ) -> str:
        if self.cancellation_check is not None:
            self.cancellation_check()
        while not _MODEL_CALL_SEMAPHORE.acquire(timeout=0.25):
            if self.cancellation_check is not None:
                self.cancellation_check()
        try:
            if self.cancellation_check is not None:
                self.cancellation_check()
            return self.adapter.call(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_paths=image_paths,
                file_paths=file_paths,
            )
        finally:
            _MODEL_CALL_SEMAPHORE.release()

    def call_json(
        self,
        response_model: type[ModelT],
        *,
        system_prompt: str,
        user_prompt: str,
        image_paths: list[Path] | None = None,
        file_paths: list[Path] | None = None,
        validation_context: dict[str, object] | None = None,
    ) -> tuple[ModelT, str]:
        started_at = time.perf_counter()
        raw_text = ""
        last_error: Exception | None = None
        call_index: int | None = None
        request_payload = build_logged_prompt_payload(
            model_name=self.model_name,
            api_format=self.api_format,
            response_model=response_model.__name__,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=image_paths,
            file_paths=file_paths,
        )
        if validation_context:
            request_payload["validation_context"] = validation_context
        attempts_total = max(
            1,
            int(
                getattr(
                    self,
                    "response_validation_max_attempts",
                    getattr(self, "unexpected_response_retries", 0) + 1,
                )
            ),
        )
        for attempt in range(1, attempts_total + 1):
            try:
                if self.request_callback is not None:
                    request_result = self.request_callback({**request_payload, "attempt": attempt, "attempts_total": attempts_total})
                    if isinstance(request_result, int):
                        call_index = request_result
                raw_text = self.call(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    image_paths=image_paths,
                    file_paths=file_paths,
                )
                payload = parse_model_response_payload(raw_text)
                if not isinstance(payload, dict):
                    raise InvalidModelResponseError(
                        f"Expected a JSON object for {response_model.__name__}, but received {type(payload).__name__}.",
                        payload=payload,
                        failure_kind="json_top_level_not_object",
                    )
                if _looks_like_empty_provider_envelope(payload):
                    raise InvalidModelResponseError(
                        f"{response_model.__name__} received an empty provider envelope instead of a business payload.",
                        payload=payload,
                        failure_kind="provider_empty_payload",
                    )
                try:
                    parsed = response_model.model_validate(payload, context=validation_context)
                except ValidationError as exc:
                    raise InvalidModelResponseError(
                        f"{response_model.__name__} failed schema validation.",
                        payload=payload,
                        cause=exc,
                        failure_kind=classify_model_format_error(exc),
                    ) from exc
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                if self.response_callback is not None:
                    target_type = None
                    target_id = None
                    if isinstance(payload, dict):
                        if payload.get("object_id"):
                            target_type = "object"
                            target_id = payload.get("object_id")
                        elif payload.get("region_id"):
                            target_type = "region"
                            target_id = payload.get("region_id")
                    self.response_callback(
                        {
                            "call_index": call_index,
                            "status": "ok",
                            "model": self.model_name,
                            "api_format": self.api_format,
                            "response_model": response_model.__name__,
                            "duration_ms": duration_ms,
                            "raw_chars": len(raw_text),
                            "raw_text": raw_text,
                            "target_type": target_type,
                            "target_id": target_id,
                            "json_keys": list(payload.keys()) if isinstance(payload, dict) else [],
                            "attempt": attempt,
                            "attempts_total": attempts_total,
                        }
                    )
                return parsed, raw_text
            except Exception as exc:
                last_error = exc
                if attempt < attempts_total and is_retryable_response_error(exc):
                    if self.warning_callback is not None:
                        invalid_preview = getattr(exc, "payload_preview", "")
                        self.warning_callback(
                            {
                                "call_index": call_index,
                                "model": self.model_name,
                                "api_format": self.api_format,
                                "response_model": response_model.__name__,
                                "attempt": attempt,
                                "attempts_total": attempts_total,
                                "raw_chars": len(raw_text),
                                "raw_text": raw_text,
                                "warning": summarize_exception(exc),
                                "failure_kind": classify_model_format_error(exc),
                                "invalid_response_preview": invalid_preview,
                            }
                        )
                    continue
                break

        duration_ms = int((time.perf_counter() - started_at) * 1000)
        if self.response_callback is not None:
            invalid_preview = getattr(last_error, "payload_preview", "")
            self.response_callback(
                {
                    "call_index": call_index,
                    "status": "error",
                    "model": self.model_name,
                    "api_format": self.api_format,
                    "response_model": response_model.__name__,
                    "duration_ms": duration_ms,
                    "raw_chars": len(raw_text),
                    "raw_text": raw_text,
                    "error": summarize_exception(last_error or RuntimeError("Unknown model response failure")),
                    "failure_kind": classify_model_format_error(last_error),
                    "invalid_response_preview": invalid_preview,
                    "attempt": attempts_total,
                    "attempts_total": attempts_total,
                }
            )
        if last_error is not None:
            raise last_error
        raise RuntimeError("Model JSON call failed without a captured exception.")
