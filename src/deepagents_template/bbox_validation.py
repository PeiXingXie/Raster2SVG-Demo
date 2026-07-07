"""Evidence-only bbox validation helpers used for acceptance and retry feedback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(slots=True)
class BboxEdgeEvidence:
    edge: str
    issue_type: str
    detail: str
    severity: str = "high"


@dataclass(slots=True)
class BboxValidationFeedback:
    target_id: str
    passed: bool
    summary: str
    failures: list[BboxEdgeEvidence]

    def to_prompt_payload(self) -> dict:
        return {
            "target_id": self.target_id,
            "passed": self.passed,
            "summary": self.summary,
            "failures": [
                {
                    "edge": item.edge,
                    "issue_type": item.issue_type,
                    "detail": item.detail,
                    "severity": item.severity,
                }
                for item in self.failures
            ],
        }


def _luminance(pixel: tuple[int, ...]) -> float:
    if len(pixel) >= 3:
        r, g, b = pixel[:3]
        return 0.299 * r + 0.587 * g + 0.114 * b
    value = pixel[0]
    return float(value)


def _is_foreground(pixel: tuple[int, ...], *, threshold: int) -> bool:
    return _luminance(pixel) < threshold


def _safe_band_length(length: int) -> int:
    return max(1, min(length, 3))


def _edge_foreground_ratio(
    image: Image.Image,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    edge: str,
    threshold: int,
) -> float:
    if width <= 0 or height <= 0:
        return 0.0

    fg = 0
    total = 0
    if edge in {"left", "right"}:
        band = _safe_band_length(width)
        x_start = x if edge == "left" else x + width - band
        for px in range(x_start, x_start + band):
            for py in range(y, y + height):
                total += 1
                if _is_foreground(image.getpixel((px, py)), threshold=threshold):
                    fg += 1
    else:
        band = _safe_band_length(height)
        y_start = y if edge == "top" else y + height - band
        for py in range(y_start, y_start + band):
            for px in range(x, x + width):
                total += 1
                if _is_foreground(image.getpixel((px, py)), threshold=threshold):
                    fg += 1
    return (fg / total) if total else 0.0


def validate_crop_local_bbox(
    *,
    crop_path: Path,
    target_id: str,
    bbox: dict | None,
    foreground_threshold: int = 235,
    edge_ratio_threshold: float = 0.22,
) -> BboxValidationFeedback:
    if not crop_path.is_file():
        return BboxValidationFeedback(
            target_id=target_id,
            passed=True,
            summary="crop image unavailable; skipped bbox edge validation",
            failures=[],
        )
    if bbox is None:
        return BboxValidationFeedback(
            target_id=target_id,
            passed=False,
            summary="bbox is missing",
            failures=[
                BboxEdgeEvidence(
                    edge="all",
                    issue_type="bbox_missing",
                    detail="No bbox was provided for this object.",
                )
            ],
        )

    with Image.open(crop_path) as source:
        image = source.convert("RGBA")

    img_width, img_height = image.size
    x = max(0, min(int(bbox.get("x", 0)), max(img_width - 1, 0)))
    y = max(0, min(int(bbox.get("y", 0)), max(img_height - 1, 0)))
    width = max(1, min(int(bbox.get("width", 1)), max(img_width - x, 1)))
    height = max(1, min(int(bbox.get("height", 1)), max(img_height - y, 1)))

    failures: list[BboxEdgeEvidence] = []
    for edge in ("left", "top", "right", "bottom"):
        ratio = _edge_foreground_ratio(
            image,
            x=x,
            y=y,
            width=width,
            height=height,
            edge=edge,
            threshold=foreground_threshold,
        )
        if ratio >= edge_ratio_threshold:
            failures.append(
                BboxEdgeEvidence(
                    edge=edge,
                    issue_type="edge_intersects_foreground",
                    detail=(
                        f"{edge} edge intersects visible foreground pixels (ratio={ratio:.3f}). "
                        "Review whether the intersected content belongs to the target object."
                    ),
                )
            )

    passed = not failures
    summary = (
        "bbox edges do not intersect visible foreground"
        if passed
        else "bbox edge evidence suggests visible foreground intersects the box boundary"
    )
    return BboxValidationFeedback(
        target_id=target_id,
        passed=passed,
        summary=summary,
        failures=failures,
    )
