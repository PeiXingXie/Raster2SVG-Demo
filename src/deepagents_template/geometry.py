"""Overview: Geometry helpers for regions, bounding boxes, and coordinate-frame conversion."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image
from pydantic import BaseModel

from deepagents_template.schemas import ObjectCandidate


def normalize_regions(regions: list, *, width: int, height: int) -> list[dict]:
    normalized: list[dict] = []

    for index, region in enumerate(regions, start=1):
        if isinstance(region, BaseModel):
            region_payload = region.model_dump(mode="json")
        else:
            region_payload = dict(region)

        bbox = dict(region_payload.get("bbox", {}))
        x = max(0, min(int(bbox.get("x", 0)), width - 1 if width > 0 else 0))
        y = max(0, min(int(bbox.get("y", 0)), height - 1 if height > 0 else 0))
        max_width = max(1, width - x)
        max_height = max(1, height - y)
        box = {
            "x": x,
            "y": y,
            "width": max(1, min(int(bbox.get("width", max_width)), max_width)),
            "height": max(1, min(int(bbox.get("height", max_height)), max_height)),
        }
        if box["width"] <= 1 or box["height"] <= 1:
            continue

        description = region_payload.get("description") or f"Region {index}"

        normalized_region = {
            "region_id": region_payload.get("region_id") or f"r{index}",
            "bbox": box,
            "description": description,
            "priority": max(1, min(int(region_payload.get("priority", index)), 5)),
            "status": region_payload.get("status", "planned"),
        }
        normalized.append(normalized_region)

    if not normalized:
        raise ValueError("Layout detector did not produce any valid regions.")
    return normalized


def compact_regions_for_prompt(regions: list[dict]) -> list[dict]:
    return [
        {
            "region_id": region["region_id"],
            "bbox": region["bbox"],
            "description": region["description"],
        }
        for region in regions
    ]


def build_region_context(region: dict) -> dict:
    return {
        "region_bounds_global": region["bbox"],
        "description": region["description"],
        "coordinate_rule": (
            "Use global SVG coordinates. Region bounds and recognized object bboxes are already global; "
            "do not add region offsets yourself."
        ),
    }


def build_region_recognition_context(region: dict) -> dict:
    bbox = region["bbox"]
    return {
        "crop_size": {
            "width": int(bbox["width"]),
            "height": int(bbox["height"]),
        },
        "description": region["description"],
        "localization_rule": (
            "Do not output numeric bboxes during recognition. Use relative_position and extent_hint only; "
            "a later bbox worker will localize objects in crop-local coordinates."
        ),
    }


def normalize_recognition_bboxes(recognition, *, region: dict):
    region_bbox = region.get("bbox") or {}
    region_x = int(region_bbox.get("x", 0))
    region_y = int(region_bbox.get("y", 0))
    crop_width = max(int(region_bbox.get("width", 1)), 1)
    crop_height = max(int(region_bbox.get("height", 1)), 1)
    objects = list(getattr(recognition, "recognized_objects", []) or [])
    if not objects:
        return recognition

    def _box_payload(obj) -> dict | None:
        bbox = getattr(obj, "bbox", None)
        return bbox.model_dump(mode="json") if bbox is not None else None

    def _is_local(box: dict) -> bool:
        x = int(box.get("x", 0))
        y = int(box.get("y", 0))
        width = max(int(box.get("width", 1)), 1)
        height = max(int(box.get("height", 1)), 1)
        return x >= 0 and y >= 0 and x + width <= crop_width and y + height <= crop_height

    def _rebase(box: dict) -> dict:
        return {
            "x": int(box.get("x", 0)) - region_x,
            "y": int(box.get("y", 0)) - region_y,
            "width": max(int(box.get("width", 1)), 1),
            "height": max(int(box.get("height", 1)), 1),
        }

    original_boxes = [box for obj in objects if (box := _box_payload(obj)) is not None]
    if not original_boxes:
        return recognition

    original_local_count = sum(1 for box in original_boxes if _is_local(box))
    rebased_boxes = [_rebase(box) for box in original_boxes]
    rebased_local_count = sum(1 for box in rebased_boxes if _is_local(box))
    if rebased_local_count <= original_local_count:
        return recognition

    adjusted_objects = []
    for obj in objects:
        bbox_model = getattr(obj, "bbox", None)
        box = _box_payload(obj)
        if box is None:
            adjusted_objects.append(obj)
            continue
        rebased = _rebase(box)
        x = max(0, min(int(rebased["x"]), crop_width - 1 if crop_width > 0 else 0))
        y = max(0, min(int(rebased["y"]), crop_height - 1 if crop_height > 0 else 0))
        width = max(1, min(int(rebased["width"]), crop_width - x))
        height = max(1, min(int(rebased["height"]), crop_height - y))
        normalized_bbox = (
            bbox_model.__class__.model_validate(
                {
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                }
            )
            if bbox_model is not None
            else {
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            }
        )
        adjusted_objects.append(
            obj.model_copy(
                update={
                    "bbox": normalized_bbox
                }
            )
        )
    return recognition.model_copy(update={"recognized_objects": adjusted_objects})


def _bbox_payload(bbox) -> dict | None:
    if bbox is None:
        return None
    return bbox.model_dump(mode="json") if hasattr(bbox, "model_dump") else dict(bbox)


def _coerce_box_payload(box: dict, *, width: int | None = None, height: int | None = None) -> dict:
    x = int(box.get("x", 0))
    y = int(box.get("y", 0))
    box_width = max(int(box.get("width", 1)), 1)
    box_height = max(int(box.get("height", 1)), 1)
    if width is not None:
        x = max(0, min(x, max(width - 1, 0)))
        box_width = max(1, min(box_width, max(width - x, 1)))
    if height is not None:
        y = max(0, min(y, max(height - 1, 0)))
        box_height = max(1, min(box_height, max(height - y, 1)))
    return {"x": x, "y": y, "width": box_width, "height": box_height}


def local_bbox_to_global(bbox: dict, *, region: dict) -> dict:
    region_bbox = region.get("bbox") or {}
    local = _coerce_box_payload(bbox)
    return {
        "x": int(region_bbox.get("x", 0)) + local["x"],
        "y": int(region_bbox.get("y", 0)) + local["y"],
        "width": local["width"],
        "height": local["height"],
    }


def global_bbox_to_local(bbox: dict, *, region: dict) -> dict:
    region_bbox = region.get("bbox") or {}
    local = {
        "x": int(bbox.get("x", 0)) - int(region_bbox.get("x", 0)),
        "y": int(bbox.get("y", 0)) - int(region_bbox.get("y", 0)),
        "width": max(int(bbox.get("width", 1)), 1),
        "height": max(int(bbox.get("height", 1)), 1),
    }
    return _coerce_box_payload(
        local,
        width=max(int(region_bbox.get("width", 1)), 1),
        height=max(int(region_bbox.get("height", 1)), 1),
    )


def _copy_object_with_bbox(obj, bbox_payload: dict):
    bbox_model = getattr(obj, "bbox", None)
    if bbox_model is not None and hasattr(bbox_model.__class__, "model_validate"):
        bbox_value = bbox_model.__class__.model_validate(bbox_payload)
    else:
        bbox_value = bbox_payload
    return obj.model_copy(update={"bbox": bbox_value})


def _copy_object_with_bbox_and_space(obj, bbox_payload: dict, bbox_space: str):
    bbox_model = getattr(obj, "bbox", None)
    if bbox_model is not None and hasattr(bbox_model.__class__, "model_validate"):
        bbox_value = bbox_model.__class__.model_validate(bbox_payload)
    else:
        bbox_value = bbox_payload
    return obj.model_copy(update={"bbox": bbox_value, "bbox_space": bbox_space})


def recognition_bboxes_to_global(recognition, *, region: dict):
    adjusted_objects = []
    changed = False
    for obj in list(getattr(recognition, "recognized_objects", []) or []):
        box = _bbox_payload(getattr(obj, "bbox", None))
        if box is None:
            adjusted_objects.append(obj)
            continue
        global_box = local_bbox_to_global(box, region=region)
        changed = changed or global_box != box
        changed = changed or getattr(obj, "bbox_space", None) != "global"
        adjusted_objects.append(_copy_object_with_bbox_and_space(obj, global_box, "global"))
    if not changed:
        return recognition
    return recognition.model_copy(update={"recognized_objects": adjusted_objects})


def recognition_bboxes_to_global_if_local(recognition, *, region: dict):
    region_bbox = region.get("bbox") or {}
    crop_width = max(int(region_bbox.get("width", 1)), 1)
    crop_height = max(int(region_bbox.get("height", 1)), 1)
    boxes = [
        box
        for obj in list(getattr(recognition, "recognized_objects", []) or [])
        if (box := _bbox_payload(getattr(obj, "bbox", None))) is not None
    ]
    if not boxes:
        return recognition
    spaces = [getattr(obj, "bbox_space", None) for obj in list(getattr(recognition, "recognized_objects", []) or []) if _bbox_payload(getattr(obj, "bbox", None)) is not None]
    if spaces and all(space == "global" for space in spaces):
        return recognition
    if not all(space == "region_local" for space in spaces):
        local_count = 0
        for box in boxes:
            x = int(box.get("x", 0))
            y = int(box.get("y", 0))
            width = max(int(box.get("width", 1)), 1)
            height = max(int(box.get("height", 1)), 1)
            if x >= 0 and y >= 0 and x + width <= crop_width and y + height <= crop_height:
                local_count += 1
        if local_count < len(boxes):
            return recognition
    return recognition_bboxes_to_global(recognition, region=region)


def recognition_bboxes_to_crop_local(recognition, *, region: dict):
    adjusted_objects = []
    changed = False
    for obj in list(getattr(recognition, "recognized_objects", []) or []):
        box = _bbox_payload(getattr(obj, "bbox", None))
        if box is None:
            adjusted_objects.append(obj)
            continue
        local_box = global_bbox_to_local(box, region=region)
        changed = changed or local_box != box
        changed = changed or getattr(obj, "bbox_space", None) != "region_local"
        adjusted_objects.append(_copy_object_with_bbox_and_space(obj, local_box, "region_local"))
    if not changed:
        return recognition
    return recognition.model_copy(update={"recognized_objects": adjusted_objects})


def crop_object_image(
    *,
    region_crop_path: Path,
    obj: ObjectCandidate,
    object_dir: Path,
    region: dict | None = None,
    bbox_space: str = "region_local",
) -> Path:
    object_crop_path = object_dir / "crop.png"
    if obj.bbox is None:
        shutil.copy2(region_crop_path, object_crop_path)
        return object_crop_path

    with Image.open(region_crop_path) as image:
        image.load()
        bbox_payload = obj.bbox.model_dump(mode="json")
        if bbox_space == "global":
            if region is None:
                raise ValueError("region is required when cropping an object with a global bbox.")
            bbox_payload = global_bbox_to_local(bbox_payload, region=region)
        bbox = _coerce_box_payload(bbox_payload, width=image.width, height=image.height)
        x = bbox["x"]
        y = bbox["y"]
        width = bbox["width"]
        height = bbox["height"]
        image.crop((x, y, x + width, y + height)).save(object_crop_path)
    return object_crop_path
