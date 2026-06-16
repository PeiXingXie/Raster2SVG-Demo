"""Overview: File-level asset inspection helpers for local raster inputs."""

from __future__ import annotations

from pathlib import Path


def inspect_local_raster_asset(image_path: str) -> dict:
    """Return basic file metadata for a local raster asset path."""

    path = Path(image_path)
    exists = path.exists()
    return {
        "image_path": str(path),
        "exists": exists,
        "file_name": path.name,
        "suffix": path.suffix.lower(),
        "size_bytes": path.stat().st_size if exists and path.is_file() else None,
        "is_supported_raster": path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"},
    }
