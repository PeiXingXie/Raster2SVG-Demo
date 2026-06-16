"""Helpers for recording bbox worker outputs that exceed the intended batch budget."""

from __future__ import annotations


def summarize_bbox_batch_overflow(
    *,
    raw_payload: dict | None,
    target_id_limit: int,
    object_update_limit: int,
    changes_limit: int,
) -> dict:
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    raw_target_ids = payload.get("target_ids") if isinstance(payload.get("target_ids"), list) else []
    raw_object_updates = (
        payload.get("adjusted_object_bboxes") if isinstance(payload.get("adjusted_object_bboxes"), list) else []
    )
    raw_changes = payload.get("changes_applied") if isinstance(payload.get("changes_applied"), list) else []

    overflow = {
        "target_ids_over_limit": len(raw_target_ids) > target_id_limit,
        "adjusted_object_bboxes_over_limit": len(raw_object_updates) > object_update_limit,
        "changes_applied_over_limit": len(raw_changes) > changes_limit,
        "original_counts": {
            "target_ids": len(raw_target_ids),
            "adjusted_object_bboxes": len(raw_object_updates),
            "changes_applied": len(raw_changes),
        },
        "dropped_target_ids": raw_target_ids[target_id_limit:],
        "dropped_object_update_target_ids": [
            str((item or {}).get("target_id", "")).strip()
            for item in raw_object_updates[object_update_limit:]
            if isinstance(item, dict) and str((item or {}).get("target_id", "")).strip()
        ],
        "dropped_changes_applied": [
            str(item).strip()
            for item in raw_changes[changes_limit:]
            if str(item).strip()
        ],
    }
    overflow["has_overflow"] = any(
        (
            overflow["target_ids_over_limit"],
            overflow["adjusted_object_bboxes_over_limit"],
            overflow["changes_applied_over_limit"],
        )
    )
    return overflow
