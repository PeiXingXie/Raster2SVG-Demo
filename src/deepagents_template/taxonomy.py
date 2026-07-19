"""Canonical object-issue taxonomy and symbol-fidelity contracts."""

from __future__ import annotations

import textwrap
from typing import Literal


ObjectIssueFamily = Literal[
    "content_correctness",
    "external_form",
    "internal_composition",
    "visual_style",
    "visual_integrity",
]

OBJECT_ISSUE_FAMILIES = (
    "content_correctness",
    "external_form",
    "internal_composition",
    "visual_style",
    "visual_integrity",
)

OBJECT_ISSUE_REPAIR_PRIORITY = {
    "visual_integrity": 0,
    "content_correctness": 1,
    "external_form": 2,
    "internal_composition": 2,
    "visual_style": 3,
}

SYMBOL_FIDELITY_CHECK_KEYS = ("form", "composition", "style", "integrity")


def build_object_issue_taxonomy_rules(field_path: str) -> str:
    """Build one shared, mutually exclusive taxonomy contract for a model-output field."""

    return textwrap.dedent(
        f"""
        Object-local issue taxonomy:
        - Every {field_path} item must include exactly one issue_family from:
          content_correctness, external_form, internal_composition, visual_style, visual_integrity.
        - Classify the defect by its primary repair cause, not by every visible symptom.
        - visual_integrity: the current object is intrinsically broken even without comparing it with the reference, such as unintended clipping, broken paths, collapse, severe self-intersection, malformed geometry, or unintelligible overlap. Intentional source cropping is not a failure.
        - content_correctness: semantic identity, text, required semantic parts, or part counts are wrong, missing, extra, unreadable, or misleading. A cleanly absent required part belongs here; a present but broken or clipped part belongs to visual_integrity.
        - external_form: the object is complete and valid, but its external contour, major geometry, or identity-bearing overall proportions materially differ from the reference.
        - internal_composition: required parts are present and intact, but their topology, connectivity, relative placement, overlap, z-order, or internal organization materially differs from the reference.
        - visual_style: content and geometry are acceptable, but fill/stroke language, dominant color treatment, opacity, typography, texture, or visual weight materially differs.
        - Use this exclusive decision order: visual_integrity, content_correctness, external_form, internal_composition, visual_style.
        - Split independently repairable defects into separate items; do not assign one defect to multiple families.
        """
    ).strip()


SYMBOL_FIDELITY_CHECK_RULES = textwrap.dedent(
    """
    Symbol fidelity checks:
    - checks must contain exactly these keys with "Y" or "N" values: form, composition, style, integrity.
    - Y means acceptable for conversion, not pixel-identical. Minor cosmetic deviations remain Y and must not trigger refinement.
    - N is reserved for a material defect that warrants a medium- or high-severity object issue.
    - form: compare the complete valid object's external contour, major geometry, and identity-bearing overall proportions. Ignore small curvature, corner-radius, or proportion differences that preserve identity.
    - composition: compare topology, connectivity, relative placement, overlap, z-order, and organization among present intact owned parts. Missing semantic parts belong to content_correctness; clipped or broken parts belong to visual_integrity.
    - style: compare fill/stroke language, dominant color treatment, opacity, texture, and visual weight. Ignore small hue or stroke-width differences that preserve the pictogram's visual language.
    - integrity: judge intrinsic completeness without relying on the reference. Fail unintended clipping, broken paths, collapse, severe self-intersection, malformed geometry, or unintelligible overlap; do not fail intentional source cropping or mere edge proximity.
    """
).strip()


OBJECT_REPAIR_GUIDANCE = textwrap.dedent(
    """
    Repair by issue family:
    - content_correctness: add, remove, or correct semantic content without redrawing correct geometry.
    - external_form: adjust the outer contour or major proportions while preserving correct internal details.
    - internal_composition: adjust owned-part topology, connection, hierarchy, or placement while preserving correct parts.
    - visual_style: prefer fill, stroke, font, opacity, or other presentation-attribute edits without changing correct paths.
    - visual_integrity: repair clipping, overflow, broken or collapsed paths, malformed geometry, and unintended occlusion first.
    """
).strip()
