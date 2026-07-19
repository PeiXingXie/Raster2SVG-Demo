"""Overview: Runtime SVG fragment aggregation, normalization, and merge helpers."""

from __future__ import annotations

from pathlib import Path

from deepagents_template.atomic_files import atomic_write_text
from deepagents_template.svg_utils import (
    ensure_region_svg_comment,
    extract_object_svg_index,
    find_unscoped_visual_elements,
    merge_svg,
    normalize_svg,
)


def aggregate_object_svg_fragments(
    region_svg_elements: str,
    object_svg_index: dict[str, str],
    *,
    region_comment: str = "",
) -> str:
    """Aggregate object SVG fragments into a complete region fragment."""

    fragments: list[str] = []
    if region_comment:
        fragments.append(region_comment.strip())
    if region_svg_elements.strip():
        fragments.append(region_svg_elements.strip())
    for object_id, svg_fragment in object_svg_index.items():
        fragment = (svg_fragment or "").strip()
        if not fragment:
            continue
        if f'data-object-id="{object_id}"' not in fragment and f"object: {object_id}" not in fragment:
            fragment = f'<!-- object: {object_id}; type=unknown; request=object-level SVG update -->\n{fragment}'
        fragments.append(fragment)
    return "\n".join(fragments).strip()


def finalize_region_svg(svg_elements: str, region: dict) -> tuple[str, dict[str, str], list[dict[str, str]]]:
    final_svg_elements = ensure_region_svg_comment(svg_elements, region)
    object_svg_index = extract_object_svg_index(final_svg_elements)
    unscoped_visuals = find_unscoped_visual_elements(final_svg_elements)
    return final_svg_elements, object_svg_index, unscoped_visuals


def aggregate_region_object_svg(
    current_region_svg: str,
    object_svg_index: dict[str, str],
    region: dict,
) -> str:
    return ensure_region_svg_comment(
        aggregate_object_svg_fragments(current_region_svg, object_svg_index),
        region,
    )


def persist_merged_svg(
    *,
    svg_template: str,
    merged_regions: dict[str, str],
    output_path: Path,
) -> str:
    merged_svg = merge_svg(svg_template, merged_regions)
    merged_svg = normalize_svg(merged_svg)
    atomic_write_text(output_path, merged_svg)
    return merged_svg
