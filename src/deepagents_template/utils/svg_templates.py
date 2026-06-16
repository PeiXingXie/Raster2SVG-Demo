"""Overview: SVG template construction helpers for region-based document scaffolds."""

from __future__ import annotations

import json


def build_svg_template(
    canvas_width: int,
    canvas_height: int,
    regions_json: str,
) -> str:
    """Create a scaffold SVG with one group per planned region."""

    regions = json.loads(regions_json)
    lines = [
        f'<svg width="{canvas_width}" height="{canvas_height}" viewBox="0 0 {canvas_width} {canvas_height}" xmlns="http://www.w3.org/2000/svg">',
        "  <defs>",
        '    <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">',
        '      <polygon points="0 0, 10 3.5, 0 7" fill="#334155" />',
        "    </marker>",
        "  </defs>",
        "  <style>",
        "    text { font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; }",
        "  </style>",
    ]
    for region in regions:
        bbox = region["bbox"]
        lines.append(
            f'  <!-- Region {region["region_id"]}: {region["description"]}, '
            f'bbox=({bbox["x"]},{bbox["y"]},{bbox["width"]},{bbox["height"]}) -->'
        )
        lines.append(
            f'  <g id="{region["region_id"]}" '
            f'data-bbox="{bbox["x"]},{bbox["y"]},{bbox["width"]},{bbox["height"]}"></g>'
        )
    lines.append("</svg>")
    return "\n".join(lines)
