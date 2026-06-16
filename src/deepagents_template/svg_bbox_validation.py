"""SVG-to-bbox acceptance helpers that emit evidence but never mutate geometry."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from deepagents_template.schemas import RegionRecognitionResult


SVG_NS = {"svg": "http://www.w3.org/2000/svg"}


def build_region_bbox_review_feedback(
    *,
    svg_fragment: str,
    recognition: RegionRecognitionResult,
    region_bbox: dict | None = None,
) -> list[dict]:
    fragment = (svg_fragment or "").strip()
    if not fragment:
        return []
    wrapper = ET.fromstring(f'<fragment xmlns="http://www.w3.org/2000/svg">{fragment}</fragment>')
    feedback: list[dict] = []

    offset_x = int((region_bbox or {}).get("x", 0))
    offset_y = int((region_bbox or {}).get("y", 0))
    for obj in recognition.recognized_objects:
        bbox = obj.bbox.model_dump(mode="json") if obj.bbox is not None else None
        if bbox is None:
            continue
        group = wrapper.find(f'.//*[@data-object-id="{obj.object_id}"]')
        if group is None:
            feedback.append(
                {
                    "object_id": obj.object_id,
                    "status": "missing_object_group",
                    "detail": "No rendered object group matched this recognized object id.",
                }
            )
            continue

        issues: list[str] = []
        for text in group.findall(".//svg:text", SVG_NS):
            try:
                x = float(text.attrib.get("x", "0"))
                y = float(text.attrib.get("y", "0"))
            except ValueError:
                continue
            left = bbox["x"] + offset_x
            top = bbox["y"] + offset_y
            right = left + bbox["width"]
            bottom = top + bbox["height"]
            if not (left <= x <= right):
                issues.append("text anchor x falls outside bbox")
            if not (top <= y <= bottom):
                issues.append("text anchor y falls outside bbox")

        if issues:
            feedback.append(
                {
                    "object_id": obj.object_id,
                    "status": "bbox_constraint_risk",
                    "detail": "; ".join(issues[:3]),
                    "bbox": bbox,
                }
            )
    return feedback
