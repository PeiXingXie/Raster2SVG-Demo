"""Overview: Runtime image helpers for writing cropped region assets to disk."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def crop_region_image(image: Image.Image, bbox: dict, crop_path: Path) -> None:
    crop = image.crop(
        (
            bbox["x"],
            bbox["y"],
            bbox["x"] + bbox["width"],
            bbox["y"] + bbox["height"],
        )
    )
    crop.save(crop_path)
