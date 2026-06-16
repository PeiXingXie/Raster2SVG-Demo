"""Post-recognition semantic grouping helpers for overly fine object splits."""

from __future__ import annotations

from dataclasses import dataclass

from deepagents_template.schemas import RegionRecognitionResult


_EMBED_HOST_TYPES = {"container", "diagram", "icon", "fig"}
_ATTACHABLE_TEXT_TYPES = {"text"}


@dataclass(slots=True)
class RecognitionGroupingSummary:
    merged_count: int
    dropped_object_ids: list[str]
    kept_object_ids: list[str]

    def to_payload(self) -> dict:
        return {
            "merged_count": self.merged_count,
            "dropped_object_ids": self.dropped_object_ids,
            "kept_object_ids": self.kept_object_ids,
        }


def _bbox_payload(obj) -> dict | None:
    bbox = getattr(obj, "bbox", None)
    return bbox.model_dump(mode="json") if bbox is not None else None


def _bbox_contains(inner: dict, outer: dict, *, tolerance: int = 10) -> bool:
    return (
        int(inner["x"]) >= int(outer["x"]) - tolerance
        and int(inner["y"]) >= int(outer["y"]) - tolerance
        and int(inner["x"]) + int(inner["width"]) <= int(outer["x"]) + int(outer["width"]) + tolerance
        and int(inner["y"]) + int(inner["height"]) <= int(outer["y"]) + int(outer["height"]) + tolerance
    )


def _bbox_gap(a: dict, b: dict) -> int:
    ax1, ay1 = int(a["x"]), int(a["y"])
    ax2, ay2 = ax1 + int(a["width"]), ay1 + int(a["height"])
    bx1, by1 = int(b["x"]), int(b["y"])
    bx2, by2 = bx1 + int(b["width"]), by1 + int(b["height"])
    dx = max(bx1 - ax2, ax1 - bx2, 0)
    dy = max(by1 - ay2, ay1 - by2, 0)
    return dx + dy


def _looks_like_local_annotation(description: str) -> bool:
    text = " ".join(str(description or "").lower().split())
    tokens = (
        "annotation",
        "caption",
        "label",
        "legend",
        "loss",
        "pose",
        "aug",
        "inference",
        "finetuning",
    )
    return any(token in text for token in tokens)


def group_oversegmented_recognition(
    recognition: RegionRecognitionResult,
    *,
    max_objects_before_grouping: int = 6,
) -> tuple[RegionRecognitionResult, RecognitionGroupingSummary]:
    objects = list(recognition.recognized_objects or [])
    if len(objects) <= max_objects_before_grouping:
        return recognition, RecognitionGroupingSummary(merged_count=0, dropped_object_ids=[], kept_object_ids=[obj.object_id for obj in objects])

    dropped_ids: list[str] = []
    kept_objects = []
    consumed: set[str] = set()
    object_by_id = {obj.object_id: obj for obj in objects}

    for obj in objects:
        if obj.object_id in consumed:
            continue
        bbox = _bbox_payload(obj)
        if bbox is None or obj.object_type not in _EMBED_HOST_TYPES:
            kept_objects.append(obj)
            consumed.add(obj.object_id)
            continue

        merged_descriptions = [str(obj.description or "").strip()]
        merged_focus = [item for item in (obj.generation_focus or []) if isinstance(item, str) and item.strip()]
        merged_any = False
        for other in objects:
            if other.object_id == obj.object_id or other.object_id in consumed:
                continue
            other_bbox = _bbox_payload(other)
            if other_bbox is None or other.object_type not in _ATTACHABLE_TEXT_TYPES:
                continue
            attach = _bbox_contains(other_bbox, bbox, tolerance=12) or (
                _bbox_gap(other_bbox, bbox) <= 18 and _looks_like_local_annotation(other.description)
            )
            if not attach:
                continue
            consumed.add(other.object_id)
            dropped_ids.append(other.object_id)
            merged_any = True
            text_desc = str(other.description or "").strip()
            if text_desc:
                merged_descriptions.append(f"includes local text/annotation: {text_desc}")
            for item in (other.generation_focus or []):
                if isinstance(item, str) and item.strip():
                    merged_focus.append(item.strip())

        consumed.add(obj.object_id)
        if merged_any:
            kept_objects.append(
                obj.model_copy(
                    update={
                        "description": "; ".join(part for part in merged_descriptions if part),
                        "generation_focus": list(dict.fromkeys(merged_focus))[:3],
                    }
                )
            )
        else:
            kept_objects.append(obj)

    for obj in objects:
        if obj.object_id not in consumed:
            kept_objects.append(obj)
            consumed.add(obj.object_id)

    updated = recognition.model_copy(update={"recognized_objects": kept_objects})
    return updated, RecognitionGroupingSummary(
        merged_count=len(dropped_ids),
        dropped_object_ids=dropped_ids,
        kept_object_ids=[obj.object_id for obj in kept_objects],
    )
