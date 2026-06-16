"""Helpers for rendering bbox overlays used by bbox review nodes."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


PALETTE = [
    "#e63946",
    "#1d3557",
    "#2a9d8f",
    "#f4a261",
    "#6a4c93",
    "#ff006e",
    "#118ab2",
    "#8ac926",
    "#ff7f11",
    "#3a86ff",
    "#8338ec",
    "#ffbe0b",
]


def render_bbox_overlay(
    *,
    image_path: Path,
    boxes: list[dict],
    output_path: Path,
) -> Path:
    """Render bbox rectangles on top of the given image."""

    with Image.open(image_path) as source:
        image = source.convert("RGBA")
    draw = ImageDraw.Draw(image)
    line_width = max(4, round(min(image.size) * 0.008))

    for index, item in enumerate(boxes):
        bbox = item.get("bbox") or {}
        x = int(bbox.get("x", 0))
        y = int(bbox.get("y", 0))
        width = max(1, int(bbox.get("width", 1)))
        height = max(1, int(bbox.get("height", 1)))
        color = PALETTE[index % len(PALETTE)]
        draw.rectangle(
            (x, y, x + width, y + height),
            outline=color,
            width=line_width,
        )
        label = str(item.get("label") or item.get("id") or f"box_{index + 1}")
        label_height = line_width * 3
        label_width = min(width, max(80, len(label) * 9))
        label_x = x
        label_y = y
        draw.rectangle(
            (
                label_x,
                label_y,
                label_x + label_width,
                label_y + label_height,
            ),
            fill=color,
        )
        draw.text((label_x + 4, label_y + 2), label, fill="#ffffff")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path
