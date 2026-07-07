"""Overview: Task payload builders for region-level and object-level reconstruction work."""

from __future__ import annotations

from deepagents_template.schemas import ObjectCandidate, RegionTask


def create_region_task(
    region_id: str,
    region_description: str,
    svg_group_template: str,
    checklist_focus: list[str] | None = None,
) -> dict:
    """Create a region-level work package for a ReAct worker."""

    task = RegionTask(
        region_id=region_id,
        region_description=region_description,
        svg_group_template=svg_group_template,
        checklist_focus=checklist_focus or [
            "Region content stays inside the bounding box.",
            "Main objects are represented with editable SVG primitives.",
            "Region output remains mergeable into the global SVG.",
        ],
        output_requirements=[
            "Summarize observed objects.",
            "Describe the intended SVG structure.",
            "Call out known limitations when placeholders are used.",
        ],
    )
    return task.model_dump(mode="json")


def create_object_task(
    object_id: str,
    object_type: str,
    description: str,
    *,
    included_elements: list[str] | None = None,
    generation_focus: list[str] | None = None,
    region_id: str = "",
    bbox: dict | None = None,
    current_svg: str | None = None,
    failed_items: list[dict] | None = None,
) -> dict:
    """Create an object-level work package for localized SVG generation or repair."""

    normalized = ObjectCandidate(
        object_id=object_id,
        object_type=object_type,
        description=description,
        included_elements=included_elements or [],
        generation_focus=generation_focus or [],
        bbox=bbox,
    )
    return {
        "region_id": region_id,
        "object": normalized.model_dump(mode="json"),
        "current_svg": current_svg or "",
        "failed_items": failed_items or [],
        "checklist_focus": [
            "Object SVG must stay editable and semantically tagged.",
            "Object geometry should remain inside the object or region bounds.",
            "Object output must be mergeable into the parent region group.",
        ],
        "output_requirements": [
            "Return only SVG elements for this object, not an outer <svg>.",
            "Include concise object comments and data-object-id attributes.",
            "Document remaining limitations when exact reconstruction is not possible.",
        ],
    }
