"""Helpers for building compact prompt sections."""

from __future__ import annotations

import json
from typing import Iterable


def is_nonempty_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def compact_dict(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if is_nonempty_value(value)
    }


def json_block(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _normalize_rule_lines(items: Iterable[str] | None) -> list[str]:
    if not items:
        return []
    return [item.strip() for item in items if isinstance(item, str) and item.strip()]


def json_output_contract(
    *,
    required_fields: Iterable[str] | None = None,
    array_fields: Iterable[str] | None = None,
    closed_value_fields: dict[str, Iterable[str]] | None = None,
    extra_rules: Iterable[str] | None = None,
) -> str:
    """Build a lightweight JSON contract block for prompt reuse."""

    lines = [
        "JSON output contract:",
        "- Return a valid JSON object matching the requested shape.",
        "- Include every required field shown in the requested shape unless it is explicitly optional.",
        "- Keep field names and nesting aligned with the requested shape.",
        "- Do not add new top-level sections that are not part of the requested shape.",
    ]
    required = _normalize_rule_lines(required_fields)
    if required:
        lines.append(f"- Required fields: {', '.join(required)}.")
    array_rules = _normalize_rule_lines(array_fields)
    if array_rules:
        lines.append(f"- Array fields must remain arrays: {', '.join(array_rules)}.")
        lines.append("- When an array field has no items, return [].")
    for field_name, values in (closed_value_fields or {}).items():
        normalized_values = _normalize_rule_lines(values)
        if normalized_values:
            joined = ", ".join(f'"{value}"' for value in normalized_values)
            lines.append(f"- {field_name} must use one of these values: {joined}.")
    lines.extend(f"- {rule}" for rule in _normalize_rule_lines(extra_rules))
    return "\n".join(lines)


def svg_output_contract(
    *,
    field_name: str,
    mode: str,
) -> str:
    """Build a shared contract block for SVG-carrying JSON string fields."""

    lines = [
        f'SVG field contract for "{field_name}":',
        f'- {field_name} must be a JSON string field whose value is SVG/XML text.',
        "- SVG comments are allowed when they help preserve structure or editability.",
        "- Preserve the SVG/XML text so the saved field value can be written directly to a file.",
    ]
    if mode == "fragment":
        lines.append(f'- {field_name} must contain only the requested SVG fragment, not a complete outer <svg> document.')
    elif mode == "document":
        lines.append(f'- {field_name} must contain a complete <svg> document string.')
    else:
        raise ValueError(f"Unsupported SVG output contract mode: {mode}")
    return "\n".join(lines)


def section(title: str, body: str | None) -> str:
    if not body or not body.strip():
        return ""
    return f"{title}:\n{body.strip()}"


def json_section(title: str, payload: object) -> str:
    if not is_nonempty_value(payload):
        return ""
    return section(title, json_block(payload))


def list_section(title: str, items: list[str]) -> str:
    clean_items = [item.strip() for item in items if isinstance(item, str) and item.strip()]
    if not clean_items:
        return ""
    return section(title, json_block(clean_items))


def svg_file_section(title: str, *, file_name: str, svg_content: str) -> str:
    if not svg_content.strip():
        return ""
    return section(
        title,
        "\n".join(
            [
                f"filename: {file_name}",
                "content:",
                svg_content.strip(),
            ]
        ),
    )


def inline_text_file_section(
    title: str,
    *,
    file_name: str,
    content: str,
    role: str | None = None,
    language: str = "xml",
) -> str:
    if not content.strip():
        return ""
    lines = [f"filename: {file_name}"]
    if role and role.strip():
        lines.append(f"role: {role.strip()}")
    lines.extend(
        [
            "The following file content is provided inline and is the authoritative source text to inspect:",
            f"```{language}",
            content.strip(),
            "```",
        ]
    )
    return section(title, "\n".join(lines))


def attachment_reference_section(
    title: str,
    *,
    file_name: str,
    role: str | None = None,
) -> str:
    lines = [f"filename: {file_name}"]
    if role and role.strip():
        lines.append(f"role: {role.strip()}")
    return section(title, "\n".join(lines))


def optional_section(enabled: bool, builder) -> str:
    if not enabled:
        return ""
    return builder()


def join_sections(*sections: str) -> str:
    return "\n\n".join(section for section in sections if section.strip())
