"""Helpers for compact recognition, decision-delta, and generation payloads."""

from __future__ import annotations

import threading
import warnings

from deepagents_template.checklist import FINAL_REVIEW_ISSUE_LISTS, fusion_review_issue_id
from deepagents_template.schemas import DecisionDelta, FinalReviewResult, ObjectCandidate, ObjectReviewResult, RegionRecognitionResult, RegionReviewResult


CONTEXT_PAYLOAD_WORD_BUDGET = 32
CONTEXT_PAYLOAD_ISSUE_LABEL_BUDGET = 24

_WARNING_CALLBACK_LOCK = threading.Lock()
_WARNING_CALLBACK = None


def set_context_payload_warning_callback(callback):
    """Register a structured warning callback for oversized context payload text."""

    global _WARNING_CALLBACK
    with _WARNING_CALLBACK_LOCK:
        previous = _WARNING_CALLBACK
        _WARNING_CALLBACK = callback
    return previous


def clear_context_payload_warning_callback(callback=None):
    """Clear the current structured warning callback if it matches the expected callback."""

    global _WARNING_CALLBACK
    with _WARNING_CALLBACK_LOCK:
        if callback is None or _WARNING_CALLBACK is callback:
            _WARNING_CALLBACK = None


def _emit_warning(payload: dict, message: str) -> None:
    callback = None
    with _WARNING_CALLBACK_LOCK:
        callback = _WARNING_CALLBACK
    if callback is not None:
        callback(payload)
        return
    warnings.warn(message, UserWarning, stacklevel=3)


def check_word_budget(
    value: str | None,
    *,
    max_words: int,
    builder: str,
    field: str,
    scope: str,
    target_id: str,
    max_chars: int | None = None,
) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    word_count = len(text.split())
    over_words = max_words > 0 and word_count > max_words
    over_chars = max_chars is not None and max_chars > 0 and len(text) > max_chars
    if over_words or over_chars:
        payload = {
            "warning": "text exceeded suggested budget and was preserved without trimming",
            "budget_kind": "word_count",
            "builder": builder,
            "field": field,
            "scope": scope,
            "target_id": target_id,
            "suggested_word_limit": max_words,
            "actual_word_count": word_count,
            "preview": text[:160],
        }
        if max_chars is not None:
            payload["suggested_char_limit"] = max_chars
            payload["actual_char_count"] = len(text)
        _emit_warning(
            payload,
            f"{builder} preserved over-budget text in {field} ({word_count}/{max_words} words)",
        )
    return text


def check_item_budget(
    items: list,
    *,
    max_items: int,
    builder: str,
    field: str,
    scope: str,
    target_id: str,
) -> list:
    count = len(items)
    if max_items > 0 and count > max_items:
        payload = {
            "warning": "item count exceeded suggested budget and was preserved without trimming",
            "budget_kind": "item_count",
            "builder": builder,
            "field": field,
            "scope": scope,
            "target_id": target_id,
            "suggested_item_limit": max_items,
            "actual_item_count": count,
        }
        _emit_warning(
            payload,
            f"{builder} preserved {count} items in {field} (limit {max_items})",
        )
    return items


def _trim_text(
    value: str | None,
    *,
    max_words: int = CONTEXT_PAYLOAD_WORD_BUDGET,
    builder: str,
    field: str,
    scope: str,
    target_id: str,
) -> str:
    return check_word_budget(
        value,
        max_words=max_words,
        builder=builder,
        field=field,
        scope=scope,
        target_id=target_id,
    )


def _issue_label(*parts: str | None, max_words: int = CONTEXT_PAYLOAD_ISSUE_LABEL_BUDGET, builder: str, field: str, scope: str, target_id: str) -> str:
    return _trim_text(
        " ".join(part or "" for part in parts),
        max_words=max_words,
        builder=builder,
        field=field,
        scope=scope,
        target_id=target_id,
    )


def _generation_focus_from_object(obj: ObjectCandidate) -> list[str]:
    focus = [item.strip() for item in (obj.generation_focus or []) if isinstance(item, str) and item.strip()]
    return focus[:3]


def _included_elements_from_object(obj: ObjectCandidate | dict) -> list[str]:
    if isinstance(obj, dict):
        items = obj.get("included_elements") or []
    else:
        items = obj.included_elements or []
    if isinstance(items, str):
        items = [items]
    return [item.strip() for item in items if isinstance(item, str) and item.strip()]


_OWNED_SYMBOLIC_FIDELITY_TERMS = (
    "icon",
    "mark",
    "badge",
    "emblem",
    "logo",
)


def _object_type_from_object(obj: ObjectCandidate | dict) -> str:
    if isinstance(obj, dict):
        return str(obj.get("object_type") or "").strip()
    return str(obj.object_type or "").strip()


def _description_from_object(obj: ObjectCandidate | dict) -> str:
    if isinstance(obj, dict):
        return str(obj.get("description") or "").strip()
    return str(obj.description or "").strip()


def _raw_fidelity_hints_from_object(obj: ObjectCandidate | dict) -> dict | None:
    raw = obj.get("fidelity_hints") if isinstance(obj, dict) else getattr(obj, "fidelity_hints", None)
    if raw is None:
        return None
    if hasattr(raw, "model_dump"):
        return raw.model_dump(mode="json")
    return raw if isinstance(raw, dict) else None


def _contains_symbolic_term(text: str) -> bool:
    normalized = " ".join(str(text or "").lower().replace("_", " ").replace("-", " ").split())
    words = set(normalized.split())
    return any((" " in term and term in normalized) or (term in words) for term in _OWNED_SYMBOLIC_FIDELITY_TERMS)


def _goal_from_hint_text(text: str) -> str:
    cleaned = " ".join(str(text or "").strip().split())
    if not cleaned:
        return ""
    return f"Preserve visible fidelity of: {cleaned}."


def _fidelity_hints_from_object(obj: ObjectCandidate | dict) -> dict | None:
    raw = _raw_fidelity_hints_from_object(obj)
    raw_goals: list[str] = []
    verify_required = False
    if raw is not None:
        verify_required = bool(raw.get("verify_required"))
        goals = raw.get("fidelity_goals")
        if goals is None:
            goals = raw.get("must_preserve")
        if isinstance(goals, str):
            goals = [goals]
        if isinstance(goals, list):
            raw_goals = [str(item).strip() for item in goals if str(item).strip()]
        if raw_goals:
            return {
                "verify_required": bool(verify_required),
                "fidelity_goals": list(dict.fromkeys(raw_goals))[:5],
            }

    included = _included_elements_from_object(obj)
    focus = _generation_focus_from_object(obj) if not isinstance(obj, dict) else [
        item.strip()
        for item in (obj.get("generation_focus") or [])
        if isinstance(item, str) and item.strip()
    ][:3]
    object_type = _object_type_from_object(obj)
    if object_type == "icon":
        verify_required = True

    if not verify_required:
        symbolic_candidates = [item for item in included if _contains_symbolic_term(item)]
        if symbolic_candidates:
            verify_required = True
            raw_goals.extend(symbolic_candidates[:4])

    if verify_required and not raw_goals:
        raw_goals = (included or focus)[:5]
    if verify_required and not raw_goals:
        description = _description_from_object(obj)
        if description:
            raw_goals = [description]

    fidelity_goals = list(
        dict.fromkeys(goal for goal in (_goal_from_hint_text(item) for item in raw_goals) if goal)
    )[:5]
    if not verify_required and not fidelity_goals:
        return None
    return {
        "verify_required": bool(verify_required),
        "fidelity_goals": fidelity_goals,
    }


def build_recognition_generation_payload(recognition: RegionRecognitionResult) -> dict:
    return {
        "region_id": recognition.region_id,
        "observation": _trim_text(
            recognition.observation,
            max_words=CONTEXT_PAYLOAD_WORD_BUDGET,
            builder="build_recognition_generation_payload",
            field="observation",
            scope="region",
            target_id=recognition.region_id,
        ),
        "objects": [
            {
                "object_id": obj.object_id,
                "object_type": obj.object_type,
                "description": _trim_text(
                    obj.description,
                    max_words=CONTEXT_PAYLOAD_WORD_BUDGET,
                    builder="build_recognition_generation_payload",
                    field=f"objects[{obj.object_id}].description",
                    scope="object",
                    target_id=obj.object_id,
                ),
                "included_elements": _included_elements_from_object(obj),
                "generation_focus": _generation_focus_from_object(obj),
                "fidelity_hints": _fidelity_hints_from_object(obj),
                "bbox": obj.bbox.model_dump(mode="json") if obj.bbox else None,
                "bbox_space": getattr(obj, "bbox_space", None) if obj.bbox else None,
            }
            for obj in recognition.recognized_objects
        ],
    }


def build_bbox_feedback_payload(feedback_items: list) -> list[dict]:
    payload: list[dict] = []
    for item in feedback_items or []:
        if hasattr(item, "to_prompt_payload"):
            payload.append(item.to_prompt_payload())
        elif isinstance(item, dict):
            payload.append(item)
    return payload


def build_object_index_payload(recognition: RegionRecognitionResult) -> dict:
    return {
        "objects": [
            {
                "object_id": obj.object_id,
                "object_type": obj.object_type,
                "bbox": obj.bbox.model_dump(mode="json") if obj.bbox else None,
                "bbox_space": getattr(obj, "bbox_space", None) if obj.bbox else None,
                "description": _trim_text(
                    obj.description,
                    max_words=CONTEXT_PAYLOAD_WORD_BUDGET,
                    builder="build_object_index_payload",
                    field=f"objects[{obj.object_id}].description",
                    scope="object",
                    target_id=obj.object_id,
                ),
                "included_elements": _included_elements_from_object(obj),
                "fidelity_hints": _fidelity_hints_from_object(obj),
            }
            for obj in recognition.recognized_objects
        ]
    }


def build_region_review_object_summary(recognition: RegionRecognitionResult) -> list[dict]:
    return [
        {
            "object_id": obj.object_id,
            "object_type": obj.object_type,
            "bbox": obj.bbox.model_dump(mode="json") if obj.bbox else None,
            "bbox_space": getattr(obj, "bbox_space", None) if obj.bbox else None,
            "description": _trim_text(
                obj.description,
                max_words=CONTEXT_PAYLOAD_WORD_BUDGET,
                builder="build_region_review_object_summary",
                field=f"objects[{obj.object_id}].description",
                scope="object",
                target_id=obj.object_id,
            ),
            "included_elements": _included_elements_from_object(obj),
            "fidelity_hints": _fidelity_hints_from_object(obj),
        }
        for obj in recognition.recognized_objects
    ]


def build_object_generation_payload(obj: ObjectCandidate) -> dict:
    payload = {
        "object_id": obj.object_id,
        "object_type": obj.object_type,
        "description": _trim_text(
            obj.description,
            max_words=CONTEXT_PAYLOAD_WORD_BUDGET,
            builder="build_object_generation_payload",
            field="description",
            scope="object",
            target_id=obj.object_id,
        ),
        "included_elements": _included_elements_from_object(obj),
        "generation_focus": _generation_focus_from_object(obj),
        "fidelity_hints": _fidelity_hints_from_object(obj),
        "bbox": obj.bbox.model_dump(mode="json") if obj.bbox else None,
        "bbox_space": getattr(obj, "bbox_space", None) if obj.bbox else None,
    }
    return payload


def build_object_policy_payload(obj: ObjectCandidate | dict) -> dict:
    if isinstance(obj, dict):
        return {
            "object_id": obj.get("object_id", ""),
            "object_type": obj.get("object_type", ""),
            "bbox": obj.get("bbox"),
            "bbox_space": obj.get("bbox_space") or ("global" if obj.get("bbox") else None),
            "description": _trim_text(
                obj.get("description"),
                max_words=CONTEXT_PAYLOAD_WORD_BUDGET,
                builder="build_object_policy_payload",
                field="description",
                scope="object",
                target_id=str(obj.get("object_id", "")),
            ),
            "included_elements": _included_elements_from_object(obj),
            "fidelity_hints": _fidelity_hints_from_object(obj),
        }
    return {
        "object_id": obj.object_id,
        "object_type": obj.object_type,
        "bbox": obj.bbox.model_dump(mode="json") if obj.bbox else None,
        "bbox_space": getattr(obj, "bbox_space", None) if obj.bbox else None,
        "description": _trim_text(
            obj.description,
            max_words=CONTEXT_PAYLOAD_WORD_BUDGET,
            builder="build_object_policy_payload",
            field="description",
            scope="object",
            target_id=obj.object_id,
        ),
        "included_elements": _included_elements_from_object(obj),
        "fidelity_hints": _fidelity_hints_from_object(obj),
    }


def build_region_previous_decision_delta(review: RegionReviewResult, *, route: str | None = None, strategy: str | None = None) -> dict:
    prior_issues = [
        {
            "issue_id": f"region:{review.region_id}:{item.criterion}",
            "scope": "region",
            "target_id": review.region_id,
            "criterion": item.criterion,
            "previous_reason": _issue_label(
                item.reason,
                builder="build_region_previous_decision_delta",
                field="prior_issues_to_verify.previous_reason",
                scope="region",
                target_id=review.region_id,
            ),
        }
        for item in review.global_repairs[:3]
    ] + [
        {
            "issue_id": f"object:{review.region_id}:{item.object_id}:{item.criterion}",
            "scope": "object",
            "target_id": item.object_id,
            "object_id": item.object_id,
            "criterion": item.criterion,
            "previous_reason": _issue_label(
                item.reason,
                builder="build_region_previous_decision_delta",
                field="prior_issues_to_verify.previous_reason",
                scope="object",
                target_id=item.object_id,
            ),
        }
        for item in review.object_issues[:3]
    ]
    return DecisionDelta(
        last_route=route,
        last_strategy=strategy,
        recent_repair_attempt=strategy,
        prior_issues_to_verify=prior_issues,
    ).model_dump(mode="json")


def build_object_previous_decision_delta(review: ObjectReviewResult, *, strategy: str | None = None) -> dict:
    return DecisionDelta(
        last_strategy=strategy,
        recent_repair_attempt=strategy,
        prior_issues_to_verify=[
            {
                "issue_id": f"object:{review.object_id}:{item.criterion}",
                "scope": "object",
                "target_id": review.object_id,
                "object_id": review.object_id,
                "criterion": item.criterion,
                "previous_reason": _issue_label(
                    item.reason,
                    builder="build_object_previous_decision_delta",
                    field="prior_issues_to_verify.previous_reason",
                    scope="object",
                    target_id=review.object_id,
                ),
            }
            for item in review.failed_items[:3]
        ],
    ).model_dump(mode="json")


def build_fusion_previous_decision_delta(review: FinalReviewResult, *, strategy: str | None = None) -> dict:
    issues = []
    section_items = (
        review.spatial_relation_issues.layout_fidelity_issues,
        review.spatial_relation_issues.dimension_fidelity_issues,
        review.logical_relation_issues.redundancy_issues,
        review.logical_relation_issues.boundary_issues,
        review.visual_quality_issues.consistency_issues,
        review.visual_quality_issues.visual_reasonableness_issues,
    )
    issue_kinds = [entry[2] for entry in FINAL_REVIEW_ISSUE_LISTS]
    for items, issue_kind in zip(section_items, issue_kinds, strict=True):
        for item in items[:4]:
            item_payload = item.model_dump(mode="json")
            issues.append(
                {
                    "issue_id": f"fusion:{fusion_review_issue_id(item_payload, issue_kind=issue_kind)}",
                    "scope": "fusion",
                    "target_id": ",".join(item.related_regions) or "global",
                    "criterion": item.criterion,
                    "previous_reason": _issue_label(
                        item.description,
                        builder="build_fusion_previous_decision_delta",
                        field="prior_issues_to_verify.previous_reason",
                        scope="fusion",
                        target_id=",".join(item.related_regions) or "global",
                    ),
                }
            )
    return DecisionDelta(
        last_strategy=strategy,
        recent_repair_attempt=strategy,
        prior_issues_to_verify=issues,
    ).model_dump(mode="json")
