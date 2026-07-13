"""Overview: Prompt builders for object-level SVG generation and object review calls."""

from __future__ import annotations

import textwrap

from deepagents_template.prompt.bbox_conventions import (
    BBOX_COORDINATE_CONVENTION_RULE,
    GLOBAL_BBOX_COORDINATE_RULE,
    GLOBAL_CROP_VISUAL_EVIDENCE_RULE,
    GLOBAL_NO_LOCAL_COORDINATE_GUESS_RULE,
    GLOBAL_NO_OFFSET_REAPPLICATION_RULE,
    GLOBAL_SVG_OUTPUT_COORDINATE_RULE,
)
from deepagents_template.schemas import ObjectCandidate
from deepagents_template.utils.context_payloads import build_object_generation_payload, build_object_policy_payload
from deepagents_template.utils.prompting import (
    compact_dict,
    inline_text_file_section,
    json_output_contract,
    join_sections,
    json_section,
    optional_section,
    section,
    svg_output_contract,
)

OBJECT_ISSUE_TAXONOMY_RULES = textwrap.dedent(
    """
    Object-local issue taxonomy:
    - Every failed_items[] item must include issue_family.
    - issue_family must use exactly one of:
      content_accuracy, shape_fidelity, internal_structure, style_appearance, containment_boundary.
    - content_accuracy: object content, text, data value, semantic identity, or required owned part is wrong, missing, extra, unreadable, or misleading.
    - shape_fidelity: outer silhouette, contour, geometry, proportions, or recognizable shape likeness differs from the raster.
    - internal_structure: owned sub-elements, internal strokes, z-order, grouping, relative placement, or internal layout inside the object is wrong.
    - style_appearance: color, fill, stroke, typography, opacity, visual weight, or object-local styling differs while content and structure remain intact.
    - containment_boundary: object-local content is clipped, outside its bbox, pressed against an edge, or incorrectly contained by its own extent.
    - Choose containment_boundary first for clipping, out-of-bounds, edge pressure, or containment defects.
    - Otherwise choose content_accuracy for wrong, missing, extra, unreadable, or misleading object content or semantic identity.
    - Otherwise choose internal_structure for wrong owned sub-element arrangement, z-order, grouping, or internal layout.
    - Otherwise choose shape_fidelity for outer silhouette, contour, geometry, or proportion mismatches.
    - Otherwise choose style_appearance for color, stroke, typography, opacity, visual weight, or local style mismatches.
    """
).strip()


def build_object_svg_generation_prompts(
    *,
    obj: ObjectCandidate,
    current_svg: str,
    failed_items: list[dict] | None,
    strategy_hint: dict | None = None,
) -> tuple[str, str]:
    system_prompt = textwrap.dedent(
        f"""
        You are a multimodal object SVG worker for a raster-to-SVG workflow.
        Generate or update editable SVG for exactly one recognized object.
        Return JSON only.

        Mode selection:
          - If current SVG source text is provided, treat it as the editable base and update it.
          - If current SVG source text is absent or empty, generate a new object SVG fragment from the object crop.
          - If failed_items are provided, prioritize fixing them.
          - If failed_items are absent, produce the best faithful initial object representation.
          - Regenerate from scratch during update only when the current SVG is empty, structurally unusable, or clearly incompatible with the target object.

        Coordinate rules:
          - {GLOBAL_BBOX_COORDINATE_RULE}
          - The object bbox follows this global coordinate frame.
          - {GLOBAL_SVG_OUTPUT_COORDINATE_RULE}
          - {GLOBAL_CROP_VISUAL_EVIDENCE_RULE}
          - For fresh generation, map the object's visible proportions from the crop into the provided global bbox.
          - For update, preserve the current SVG's global coordinate frame.
          - {GLOBAL_NO_OFFSET_REAPPLICATION_RULE}
          - {BBOX_COORDINATE_CONVENTION_RULE}
          - Keep visible object geometry inside its recognized bbox unless a small overhang is necessary to avoid clipping faithful strokes.

        Output shape:
          - svg_elements must contain only this object's SVG elements, not an outer <svg>.
          - Prefer one top-level wrapper: <g data-object-id="..." data-object-type="...">...</g>.
          - Preserve data-object-id and data-object-type when updating existing SVG.
          - Include all relevant included_elements that are semantically owned by this object.
          - Do not create sibling object groups for sub-elements owned by this object.
          - Do not include unrelated objects, region wrappers, global templates, viewBox, or embedded raster images.

        Editing behavior:
          - During update, make the smallest useful change that resolves failed_items.
          - Preserve correct existing geometry, text, style, grouping, transforms, and editability.
          - Do not re-plan or simplify correct details just because they are not mentioned in failed_items.
          - Do not compensate for region/global layout defects, neighboring-object defects, or merge issues; only repair this object's own SVG.
          - In update mode, compare current SVG source against the object crop, failed_items, and strategy_hint; preserve correct existing parts and modify only defective parts.
          - Treat strategy_hint as expected outcome guidance only, not step-by-step edit instructions.
          - Use compact, high-signal SVG. Prefer editable primitives over opaque paths when practical, but fidelity is more important than over-abstracting.
          - If Object.fidelity_hints.verify_required is true, use Object.fidelity_hints.fidelity_goals as concrete visual obligations.
          - Do not substitute a cleaner generic same-category icon, symbol, badge, code window, node-link diagram, emblem, or mark when fidelity goals describe specific visible structure.
          - If a fidelity goal describes an owned detail inside a non-icon object, preserve that detail inside the owning object.
          - Small simplification is acceptable only when it preserves the goal's silhouette, internal structure, relative layout, z-order, and visual weight.

        By object_type (follow the matching line):
          - background: preserve extent, fill, border, framing, and layer role.
          - icon: build a coherent, meaningful, same-semantics icon; preserve the raster icon's distinctive silhouette, meaningful subparts, internal strokes, visual weight, z-order, and internal element layout.
          - text: preserve exact visible text content, line breaks, alignment, approximate weight, and readability.
          - container: preserve block shape, border, fill, spacing role, and containment.
          - connector: preserve endpoints, stroke style, arrowheads, and connection relationships.
          - diagram: preserve scales, encodings, values, labels, and readable structure.
          - fig: use editable color-block approximations for natural images, barcodes, or QR-like content; do not embed bitmap images.

        Response rules:
          - If this object is a grouped set, keep it same-class and logically cohesive rather than mixing unrelated classes.
          - For icon repairs, do not replace the source with a generic category symbol when the raster has distinctive lobes, windows, nodes, terminals, or emblem strokes.
          - For icon repairs, avoid arbitrary, structurally broken, unintentionally jagged, visually nonsensical, damaged, or distorted-trace contours.
          - For icon repairs, fix the main fidelity dimension named by failed_items or strategy_hint: silhouette, distinctive parts, internal strokes, visual weight, z-order, internal layout, malformed contour, or relative proportions.
          - For icon repairs, fix identity-level defects before small spacing, smoothing, or decorative polish.
          - The fig color-block replacement rule applies only to object_type="fig"; never apply it to icon objects.
          - generation_notes should stay short and only mention meaningful edits or generated structure.
          - In update mode, mention what changed and any important structure that was preserved.
          - In fresh generation mode, mention the main represented visual components.
        {json_output_contract(
            required_fields=("object_id", "svg_elements", "generation_notes"),
            array_fields=("generation_notes",),
        )}
        {svg_output_contract(field_name="svg_elements", mode="fragment")}
        """
    ).strip()
    compact_strategy_hint = compact_dict(
        {
            "label": (strategy_hint or {}).get("strategy_label") or (strategy_hint or {}).get("label"),
            "desired_outcome": ((strategy_hint or {}).get("desired_outcomes") or [None])[0]
            if isinstance((strategy_hint or {}).get("desired_outcomes"), list)
            else (strategy_hint or {}).get("desired_outcome"),
        }
    )
    task_mode = "update_existing_svg" if (current_svg or "").strip() else "fresh_generation"
    user_prompt = join_sections(
        section("Object SVG generation/update request", ""),
        section("Task mode", task_mode),
        json_section("Object", build_object_generation_payload(obj)),
        optional_section(
            bool((current_svg or "").strip()),
            lambda: inline_text_file_section(
                "Current object SVG source, if any",
                file_name=f"object-{obj.object_id}-current.svg",
                content=current_svg,
                role="Editable base SVG source for this object update. Read this inline text directly.",
            ),
        ),
        optional_section(
            bool(failed_items),
            lambda: json_section("Failed items to fix", failed_items or []),
        ),
        optional_section(
            bool(compact_strategy_hint),
            lambda: json_section("Strategy hint from the supervisor", compact_strategy_hint),
        ),
        section(
            "Return this JSON shape",
            textwrap.dedent(
                f"""
                {{
                  "object_id": "{obj.object_id}",
                  "svg_elements": "<!-- object: {obj.object_id}; type={obj.object_type}; request=... -->\\n<g data-object-id=\\"{obj.object_id}\\" data-object-type=\\"{obj.object_type}\\">\\n  ...object-specific SVG elements...\\n</g>",
                  "generation_notes": ["what changed"]
                }}
                """
            ).strip(),
        ),
    )
    return system_prompt, user_prompt


def build_object_review_prompts(
    *,
    obj: ObjectCandidate,
    object_svg: str,
    failed_items: list[dict] | None,
    svg_file_name: str = "proposed_object.svg",
) -> tuple[str, str]:
    system_prompt = textwrap.dedent(
        f"""
        You are a multimodal object SVG reviewer.
        Compare one object crop with the proposed object SVG.
        Return JSON only.

        Judge only this object. Do not ask for whole-region changes.
        Be tolerant of small low-impact visual differences when the object's main semantics,
        content, and local relationships are already correct.
        Do not fail for slight spacing, tone, or proportion differences unless they materially
        change meaning, readability, or object identity.
        For icon objects, object identity requires more than category recognizability:
        the silhouette, distinctive parts, internal strokes, and visual weight should match the raster.
        Fail generic or over-simplified icon substitutions even if their placement is acceptable.
        If Object.fidelity_hints.verify_required is true, evaluate Object.fidelity_hints.fidelity_goals before accepting.
        Generic pass reasoning such as recognizable, semantically faithful, or same-category is insufficient for verify_required objects.
        For verify_required objects, fail materially unmet goals: missing required detail, generic substitution, wrong silhouette, changed internal marks/strokes/topology, wrong z-order, or wrong visual weight.
        Each failed item must include severity exactly as "low", "medium", or "high".
        Judge severity by visual/material impact, not by wording style.
        low means cosmetic only; object identity, structure, readability, containment, and editability remain intact.
        medium means visible mismatch weakens fidelity but preserves identity and core structure.
        high means wrong/generic identity, missing key parts, broken internal layout, unreadable text, clipping, or out-of-bounds content.
        Each failed_items.reason must be brief, clear, and no more than 15 words.
        Reasons must state what is wrong, not how to fix it.
        {OBJECT_ISSUE_TAXONOMY_RULES}
        Input roles: image 1 is the ground-truth object crop; image 2 is the rendered preview of the proposed SVG.
        Inline SVG source text is structural evidence for locating issues. Use the rendered preview as the primary visual comparison target.
        Coordinate rules:
        - {GLOBAL_BBOX_COORDINATE_RULE}
        - The Object payload bbox follows this global coordinate frame.
        - {GLOBAL_CROP_VISUAL_EVIDENCE_RULE}
        - {GLOBAL_NO_OFFSET_REAPPLICATION_RULE}
        - {GLOBAL_NO_LOCAL_COORDINATE_GUESS_RULE}
        - {BBOX_COORDINATE_CONVENTION_RULE}
        {json_output_contract(
            required_fields=("object_id", "failed_items"),
            array_fields=("failed_items",),
            closed_value_fields={
                "failed_items[].severity": ("low", "medium", "high"),
                "failed_items[].issue_family": (
                    "content_accuracy",
                    "shape_fidelity",
                    "internal_structure",
                    "style_appearance",
                    "containment_boundary",
                ),
            },
        )}
        """
    ).strip()
    user_prompt = join_sections(
        section(
            "Object review request",
            (
                "Attached images are, in order: "
                "1) the source object crop, 2) the rendered preview of the provided SVG."
            ),
        ),
        json_section("Object", build_object_policy_payload(obj)),
        inline_text_file_section(
            "Proposed object SVG source",
            file_name=svg_file_name,
            content=object_svg,
            role="Structural SVG source that corresponds to the rendered preview image.",
        ),
        json_section("Expected fixes or inherited failed items", failed_items or []),
        section(
            "Return this JSON shape",
            textwrap.dedent(
                f"""
                {{
                  "object_id": "{obj.object_id}",
                  "failed_items": [
                    {{
                      "issue_family": "shape_fidelity",
                      "criterion": "criterion text",
                      "reason": "brief problem description",
                      "severity": "medium"
                    }}
                  ]
                }}
                """
            ).strip(),
        ),
    )
    return system_prompt, user_prompt
