"""Overview: Prompt builders for object-level SVG generation and object review calls."""

from __future__ import annotations

import textwrap

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


def build_object_svg_generation_prompts(
    *,
    obj: ObjectCandidate,
    current_svg: str,
    failed_items: list[dict] | None,
    strategy_hint: dict | None = None,
) -> tuple[str, str]:
    system_prompt = textwrap.dedent(
        f"""
        You are a multimodal object SVG generation worker.
        Generate or update editable SVG for one object only.
        Return JSON only.

        Rules:

        Output shape:
          - svg_elements must contain only this object's SVG elements, not an outer <svg>.
          - Include all relevant included_elements that are semantically owned by this object.
          - Do not create sibling object groups for sub-elements owned by this object.

        By object_type (follow the matching line):
          - background: preserve extent, fill, border, framing, and layer role.
          - icon: build editable shapes approximating the original icon; preserve silhouette, distinctive parts, internal strokes, and visual weight.
          - text: preserve text content and formatting.
          - container: preserve container/block formatting and position.
          - connector: preserve style and connection relationships.
          - diagram: preserve scales, encodings, values, completeness, and readability.
          - fig: use color-block replacements for natural images or barcodes/QR codes.

        Checklist fixes:
          - Fix the provided failed_items without changing unrelated objects.
          - Treat strategy_hint as expected outcome guidance only, not step-by-step edit instructions.
          - If this object is a grouped set, keep it same-class and logically cohesive rather than mixing unrelated classes.
          - For icon repairs, do not replace the source with a generic category symbol when the raster has distinctive lobes, windows, nodes, terminals, or emblem strokes.
          - For icon repairs, keep the object inside its recognized bbox while improving likeness before optimizing small spacing differences.
          - If current SVG source text is provided inline, treat it as the editable base to update rather than re-planning from scratch.
          - Use a compact, high-signal style and focus on the main semantic or readability problems first.
          - generation_notes should stay short and only mention the most meaningful edits.
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
    user_prompt = join_sections(
        section("Object SVG generation/update request", ""),
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
        Each failed item must include severity exactly as "low", "medium", or "high".
        Judge severity by visual/material impact, not by wording style.
        low means cosmetic only; object identity, structure, readability, containment, and editability remain intact.
        medium means visible mismatch weakens fidelity but preserves identity and core structure.
        high means wrong/generic identity, missing key parts, broken internal layout, unreadable text, clipping, or out-of-bounds content.
        Each failed_items.reason must be brief, clear, and no more than 15 words.
        Reasons must state what is wrong, not how to fix it.
        Input roles: image 1 is the ground-truth object crop; image 2 is the rendered preview of the proposed SVG.
        Inline SVG source text is structural evidence for locating issues. Use the rendered preview as the primary visual comparison target.
        {json_output_contract(
            required_fields=("object_id", "failed_items"),
            array_fields=("failed_items",),
            closed_value_fields={"failed_items[].severity": ("low", "medium", "high")},
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
