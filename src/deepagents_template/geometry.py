"""Overview: Geometry helpers for regions, bounding boxes, and crop-local coordinates."""

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
        "bbox": region["bbox"],
        "description": region["description"],
        "coordinate_rule": "Use global SVG coordinates: crop-local x/y plus bbox.x/bbox.y.",
    }


def build_region_recognition_context(region: dict) -> dict:
    bbox = region["bbox"]
    return {
        "crop_size": {
            "width": int(bbox["width"]),
            "height": int(bbox["height"]),
        },
        "description": region["description"],
        "coordinate_rule": (
            "All object bboxes must be crop-local coordinates inside this cropped region. "
            "Treat the crop top-left as (0, 0) and do not add the region bbox offset."
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


def crop_object_image(
    *,
    region_crop_path: Path,
    obj: ObjectCandidate,
    object_dir: Path,
) -> Path:
    object_crop_path = object_dir / "crop.png"
    if obj.bbox is None:
        shutil.copy2(region_crop_path, object_crop_path)
        return object_crop_path

    with Image.open(region_crop_path) as image:
        image.load()
        bbox = obj.bbox
        x = max(0, min(int(bbox.x), image.width - 1 if image.width > 0 else 0))
        y = max(0, min(int(bbox.y), image.height - 1 if image.height > 0 else 0))
        width = max(1, min(int(bbox.width), image.width - x))
        height = max(1, min(int(bbox.height), image.height - y))
        image.crop((x, y, x + width, y + height)).save(object_crop_path)
    return object_crop_path
