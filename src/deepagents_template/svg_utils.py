"""Overview: Pure SVG parsing, normalization, extraction, and merge helpers."""

from __future__ import annotations

import xml.etree.ElementTree as ET


SVG_NAMESPACE = "http://www.w3.org/2000/svg"
VISUAL_SVG_TAGS = {
    "circle",
    "ellipse",
    "image",
    "line",
    "path",
    "polygon",
    "polyline",
    "rect",
    "text",
    "use",
}
NON_VISUAL_CONTAINER_TAGS = {
    "clipPath",
    "defs",
    "filter",
    "linearGradient",
    "marker",
    "mask",
    "metadata",
    "pattern",
    "radialGradient",
    "style",
    "symbol",
    "title",
}


def extract_group_template(region: dict) -> str:
    bbox = region["bbox"]
    return (
        f'<g id="{region["region_id"]}" '
        f'data-bbox="{bbox["x"]},{bbox["y"]},{bbox["width"]},{bbox["height"]}"></g>'
    )


def ensure_region_svg_comment(svg_elements: str, region: dict) -> str:
    if "<!-- region:" in svg_elements:
        return svg_elements
    bbox = region["bbox"]
    comment = (
        f'<!-- region: bbox={bbox["x"]},{bbox["y"]},{bbox["width"]},{bbox["height"]}; '
        f'purpose={region["description"]} -->'
    )
    return f"{comment}\n{svg_elements.strip()}"


def merge_svg(template_svg: str, merged_regions: dict[str, str]) -> str:
    ET.register_namespace("", SVG_NAMESPACE)
    root = ET.fromstring(template_svg)
    for element in root.findall(f".//{{{SVG_NAMESPACE}}}g"):
        region_id = element.attrib.get("id")
        if not region_id or region_id not in merged_regions:
            continue
        fragment = merged_regions[region_id].strip()
        if not fragment:
            continue
        wrapper = ET.fromstring(f'<fragment xmlns="{SVG_NAMESPACE}">{fragment}</fragment>')
        for child in wrapper:
            element.append(child)
    return ET.tostring(root, encoding="unicode")


def normalize_svg(svg_text: str) -> str:
    root = ET.fromstring(svg_text)
    return ET.tostring(root, encoding="unicode")


def extract_object_svg_index(svg_fragment: str) -> dict[str, str]:
    """Extract top-level object fragments keyed by data-object-id from a region fragment."""

    fragment = (svg_fragment or "").strip()
    if not fragment:
        return {}
    wrapper = ET.fromstring(f'<fragment xmlns="{SVG_NAMESPACE}">{fragment}</fragment>')
    object_index: dict[str, str] = {}

    def visit(element: ET.Element, *, inside_object: bool = False) -> None:
        object_id = element.attrib.get("data-object-id")
        if object_id and not inside_object:
            object_index[object_id] = ET.tostring(element, encoding="unicode")
            inside_object = True
        for child in element:
            visit(child, inside_object=inside_object)

    visit(wrapper)
    return object_index


def find_unscoped_visual_elements(svg_fragment: str) -> list[dict[str, str]]:
    """Find visible SVG elements that are not inside any data-object-id wrapper."""

    fragment = (svg_fragment or "").strip()
    if not fragment:
        return []
    wrapper = ET.fromstring(f'<fragment xmlns="{SVG_NAMESPACE}">{fragment}</fragment>')
    warnings: list[dict[str, str]] = []

    def local_name(tag: str) -> str:
        return tag.split("}", 1)[1] if "}" in tag else tag

    def visit(element: ET.Element, *, inside_object: bool = False, inside_defs: bool = False) -> None:
        name = local_name(element.tag)
        object_id = element.attrib.get("data-object-id")
        current_inside_object = inside_object or bool(object_id)
        current_inside_defs = inside_defs or name in NON_VISUAL_CONTAINER_TAGS
        if (
            name in VISUAL_SVG_TAGS
            and not current_inside_object
            and not current_inside_defs
        ):
            warnings.append(
                {
                    "tag": name,
                    "id": element.attrib.get("id", ""),
                    "data_region_id": element.attrib.get("data-region-id", ""),
                }
            )
        for child in element:
            visit(child, inside_object=current_inside_object, inside_defs=current_inside_defs)

    for child in wrapper:
        visit(child)
    return warnings


def is_valid_svg(svg_text: str) -> bool:
    try:
        ET.fromstring(svg_text)
    except ET.ParseError:
        return False
    return True
