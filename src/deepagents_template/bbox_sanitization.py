"""BBox issue sanitization helpers with soft budget warnings."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

BBOX_ISSUES_SOFT_LIMIT = 8


def truncate_text(text: str, *, max_words: int, max_chars: int) -> str:
    compact = " ".join(str(text or "").strip().split())
    parts = [item for item in compact.split() if item]
    truncated = " ".join(parts[:max_words]) if parts else compact
    return truncated[:max_chars].strip()


def warn_bbox_issues_truncated(
    *,
    original_count: int,
    scope: str,
    region_id: str | None = None,
    push_event: Callable[..., Any] | None = None,
) -> None:
    if original_count <= BBOX_ISSUES_SOFT_LIMIT:
        return
    payload = {
        "scope": scope,
        "region_id": region_id,
        "original_count": original_count,
        "kept_count": BBOX_ISSUES_SOFT_LIMIT,
        "limit": BBOX_ISSUES_SOFT_LIMIT,
    }
    if push_event is not None:
        target = region_id or scope
        push_event(
            "bbox-review",
            "Bbox issues budget warning",
            (
                f"BboxAdjustmentResult returned {original_count} issues for {target}; "
                f"keeping the first {BBOX_ISSUES_SOFT_LIMIT}."
            ),
            payload=payload,
            status="running",
            level="warning",
        )


def sanitize_bbox_issues(
    issues: list,
    *,
    scope: str,
    region_id: str | None = None,
    push_event: Callable[..., Any] | None = None,
) -> list:
    warn_bbox_issues_truncated(
        original_count=len(issues),
        scope=scope,
        region_id=region_id,
        push_event=push_event,
    )
    deduped_issues: list = []
    seen_issue_keys: set[tuple[str, str, str]] = set()
    for issue in issues[:BBOX_ISSUES_SOFT_LIMIT]:
        cleaned = issue.model_copy(
            update={
                "criterion": truncate_text(issue.criterion, max_words=12, max_chars=72),
                "reason": truncate_text(issue.reason, max_words=20, max_chars=120),
            }
        )
        if not cleaned.criterion or not cleaned.reason:
            continue
        key = (cleaned.target_id, cleaned.criterion, cleaned.reason)
        if key in seen_issue_keys:
            continue
        seen_issue_keys.add(key)
        deduped_issues.append(cleaned)
    return deduped_issues
