"""Overview: Prompt builders for region recognition, generation, repair, and review."""

from __future__ import annotations

import json
import textwrap

from deepagents_template.schemas import RegionRecognitionResult
from deepagents_template.utils.context_payloads import build_recognition_generation_payload
from deepagents_template.utils.prompting import (
    compact_dict,
    inline_text_file_section,
    json_output_contract,
    join_sections,
    json_section,
    list_section,
    optional_section,
    section,
    svg_output_contract,
)


def build_region_recognition_prompts(
    *,
    region: dict,
    region_context: dict,
    checklist_criteria: list[dict],
) -> tuple[str, str]:
    system_prompt = textwrap.dedent(
        f"""
        You are a multimodal region recognition worker.
        Read the cropped raster region and identify the objects that must later become editable SVG.
        Return JSON only.

        Rules:

        1. Basic requirements
        - Output valid JSON without markdown fences.
        - The image input is only the crop for this region, not the full source image.
        - description states what the object is and its visible role.
        - generation_focus states what later SVG generation must preserve for that object.
        - recognized_objects must be a list of object records.
        - Use the applicable checklist criteria as high-level guidance only.
        - Recognize only element types that visibly exist in this cropped region.
        - object_type must be one of: background, icon, text, container, connector, diagram, fig.
        - Include bbox when you can estimate the object bounds in crop-local coordinates.
        - recognized_objects must cover all visible content in the region except the region wrapper itself.
        - Every visible primitive should belong to exactly one object, either standalone or via a same-class collection object.
        - Use a compact, high-signal writing style and avoid low-value adjectives.
        - observation should stay short and focused, ideally within 1-2 short sentences.
        - Each object description should stay compact and high-signal rather than exhaustive.
        - generation_focus must contain at most 3 short items.
        - When you provide bbox, it must fully enclose all visible pixels of that object, including strokes, endpoints, and text descenders.
        - Use a slightly generous bbox by default: keep a visible safety margin between the content and every bbox edge rather than tracing the content too tightly.
        - Never let a bbox edge cut through visible content; if uncertain, expand the box outward instead of risking a tight crop.
        - Treat bbox overlap with the object's own visible content as a hard error, not a cosmetic issue.
        - Prefer a stable roomy box that cleanly contains the full object over a tight minimal box that hugs the silhouette.

        2. Object granularity
        - Keep object granularity semantically meaningful: each object should be a relatively complete unit.
        - Do not split one tightly coupled semantic unit into many tiny objects.
        - Strongly related and spatially adjacent elements may be grouped into one object when they form one semantic unit. (For example, stacked CNN layers may be treated as one object)
        - Annotation text, icon labels, captions, or other local labels that primarily describe one nearby object should usually be grouped with that object rather than recognized as a separate text object.
        - Text that is visually embedded inside a container, process node, card, box, legend chip, or flow block should usually stay grouped with that host object rather than becoming a separate text object.
        - A flowchart/process box together with its internal label is usually one container object, not one container plus one separate text object.
        - A legend mark together with its short nearby explanation is usually one semantic object when they function as one local key.
        - A small icon or pose glyph together with its immediately attached local label should usually be grouped as one object unless the label behaves as an independent region element.
        - Prefer one composite semantic object for "node + embedded text + immediately attached local annotation" when they are edited together in practice.
        - Use a separate text object only when the text functions as an independent region element rather than a local annotation of one object.
        - A "collection object" or "grouped set" means logically related same-class elements that are individually too small or fragmented to manage well as separate objects.
        - Use grouped sets mainly for fragmented same-class content such as connector networks, repeated decorations, or multi-line title/subtitle text systems.
        - Do not create oversized mixed-class objects just to reduce count; grouped sets should remain same-class and logically cohesive.
        - Treat repeated or fragmentary connective content as a grouped connector object when appropriate.
        - Multiple connector lines or arrows that work together should usually be one connector object.
        - Small repeated decorative marks should usually be one grouped icon object.
        - Background fills, panels, halos, or framing shapes should usually be one background object.
        - When the crop contains many small fragments, prefer semantically coherent grouped objects over exhaustive enumeration.
        - When a region is structurally dense, prefer fewer complete semantic units over many visually atomic fragments.
        - Do not merge separate icons into one object when they are independent symbols with no logical relation, hierarchy, nesting, overlap, or shared shape structure.
        - Side-by-side icons that could reasonably be edited independently should usually be separate icon objects, even if they appear in one row or header area.
        - Only group multiple icons when they form one inseparable composite mark or one repeated decorative set.

        Object description rules:
        - description must state the visible content, role, and key visual traits.
        - For text, description must include the readable text content or best-effort transcription.
        - For connector, describe what endpoints or objects are connected.
        - For diagram, describe axes/encodings/data marks when visible.
        - For fig, describe the natural image/barcode/QR placeholder subject.
        - Favor major semantic role and recognizable content over low-value micro-detail.
        Element type definitions and object requests:
        - background: panel, fill, backdrop, halo, or framing shape; preserve extent, color, border, and layering role.
        - icon: pictogram or symbolic mark; use editable SVG shapes to approximate appearance.
        - text: words, labels, or numbers; preserve content, formatting, typography, placement.
        - container: process node, box, card, or shape container; preserve formatting, position, grouping, and order.
        - connector: connector, arrow, divider, or edge; preserve style, endpoints, direction, relationships.
          Treat all tightly related connector/arrow/line work in one local network as one combined connector object.
        - diagram: chart, plot, axis-based or encoded visual; preserve scales, encodings, values, readability.
        - fig: natural image, barcode, or QR code; use color-block placeholders, not forced detail.
        {json_output_contract(
            required_fields=("region_id", "observation", "recognized_objects"),
            array_fields=("recognized_objects", "generation_focus"),
            closed_value_fields={
                "recognized_objects[].object_type": ("background", "icon", "text", "container", "connector", "diagram", "fig"),
            },
        )}
        """
    ).strip()
    user_prompt = textwrap.dedent(
        f"""
        Region-specific request:
        Convert this cropped region into editable SVG while preserving: {region['description']}

        Region context:
        {json.dumps(region_context, ensure_ascii=False, indent=2)}

        Applicable checklist criteria:
        {json.dumps(checklist_criteria, ensure_ascii=False, indent=2)}

        Return this JSON shape:
        {{
          "region_id": "{region['region_id']}",
          "observation": "short observation",
          "recognized_objects": [
            {{
              "object_id": "meaningful_object_name",
              "object_type": "text",
              "description": "readable text content and visual role, or visible object content and traits",
              "generation_focus": ["preserve wording", "preserve bold emphasis"],
              "bbox": {{"x": 0, "y": 0, "width": 100, "height": 40}}
            }}
          ]
        }}
        """
    ).strip()
    return system_prompt, user_prompt


def build_region_svg_generation_prompts(
    *,
    region: dict,
    region_context: dict,
    checklist_criteria: list[dict],
    recognition: RegionRecognitionResult,
    bbox_validation_feedback: list[dict] | None,
    current_svg_elements: str | None,
    failed_items: list[dict] | None,
    strategy_hint: dict | None = None,
) -> tuple[str, str]:
    system_prompt = textwrap.dedent(
        f"""
        You are a multimodal region SVG generation worker.
        Generate or update SVG code for the whole region.
        Return JSON only.

        Rules:
        - Output valid JSON without markdown fences.
        - svg_elements must contain only inner SVG elements for the region group, not an outer <svg>.
        - The image input is only the crop for this region, not the full source image.
        - The recognition result is an object index and preservation brief, not a fresh instruction to re-plan the region.
        - If current SVG source text is provided inline, treat it as the editable base to update rather than something to re-describe.
        - Failed items define the current repair target; do not invent unrelated new issues.
        - Convert crop-local positions to global SVG coordinates by adding bbox.x and bbox.y.
        - Treat recognized object bboxes as layout constraints, not loose hints.
        - Keep each object's visible SVG geometry inside that object's bbox unless the failed_items explicitly request a bbox-related repair first.
        - If bbox validation feedback is provided, use it as acceptance evidence about which recognized objects still have risky bbox containment.
        - Follow a compact, pragmatic style: fix the main structural and semantic issues first, and do not over-explain.
        - Use comments:
          <!-- region: bbox=<x,y,width,height> -->
          <!-- object: <object_id> -->
        - Organize SVG as a human-friendly region-object hierarchy.
        - Return exactly one top-level region wrapper group for the region.
        - Every visible child under the region wrapper must belong to a top-level object group with data-object-id and data-object-type.
        - Do not place visible shapes, text, or images directly under the region wrapper outside an object group.
        - Non-visual metadata such as comments or defs are allowed, but visible rendering content must be object-scoped.
        - Same-class grouped sets are allowed for fragmented content such as background pieces, connector networks, decorative clusters, and main/subtitle text systems.
        - generation_notes should stay short and mention only the most meaningful edits or preserved structures.
        {json_output_contract(
            required_fields=("region_id", "svg_elements", "generation_notes"),
            array_fields=("generation_notes",),
        )}
        {svg_output_contract(field_name="svg_elements", mode="fragment")}
        """
    ).strip()
    recognition_summary = build_recognition_generation_payload(recognition)
    compact_strategy_hint = compact_dict(
        {
            "label": (strategy_hint or {}).get("label"),
            "desired_outcome": (strategy_hint or {}).get("desired_outcome"),
        }
    )
    user_prompt = join_sections(
        section(
            "Region SVG generation/update request",
            f"Convert this cropped region into editable SVG while preserving: {region['description']}",
        ),
        json_section("Region context", region_context),
        json_section("Applicable checklist criteria", checklist_criteria),
        json_section("Recognition object index and generation focus", recognition_summary),
        optional_section(
            bool(bbox_validation_feedback),
            lambda: json_section("BBox validation feedback", bbox_validation_feedback or []),
        ),
        optional_section(
            bool((current_svg_elements or "").strip()),
            lambda: inline_text_file_section(
                "Current SVG source, if this is an update",
                file_name=f"region-{region['region_id']}-current.svg",
                content=current_svg_elements or "",
                role="Editable base SVG source to update. Read this inline text directly.",
            ),
        ),
        optional_section(
            bool(failed_items),
            lambda: json_section("Failed region-level items to fix", failed_items or []),
        ),
        optional_section(
            bool(compact_strategy_hint),
            lambda: json_section(
                "Strategy hint from the supervisor",
                compact_strategy_hint,
            ),
        ),
        section(
            "Return this JSON shape",
            textwrap.dedent(
                f"""
                {{
                  "region_id": "{region['region_id']}",
                  "svg_elements": "<!-- region: bbox=0,0,100,100 -->\\n<g id=\\"region-{region['region_id']}\\" data-region-id=\\"{region['region_id']}\\">\\n  <g data-object-id=\\"background_panel\\" data-object-type=\\"background\\">...</g>\\n  <g data-object-id=\\"title_system\\" data-object-type=\\"text\\">...</g>\\n</g>",
                  "generation_notes": ["what was generated or updated"]
                }}
                """
            ).strip(),
        ),
    )
    return system_prompt, user_prompt


def build_region_review_prompts(
    *,
    region: dict,
    region_context: dict,
    checklist_criteria: list[dict],
    proposed_svg_elements: str,
    object_summary: list[dict],
    svg_file_name: str = "proposed_region.svg",
) -> tuple[str, str]:
    system_prompt = textwrap.dedent(
        """
        You are a multimodal region SVG reviewer.
        Compare the cropped raster region with the proposed SVG fragment.
        Return JSON only.

        Responsibilities:

        1. Review scope
        - Evaluate region-level checklist violations such as layout, containment, coverage,
          global alignment, color/style consistency, and mergeability.
        - Evaluate every recognized object for quality and completeness.

        2. Issue routing
        - Put whole-region problems in global_repairs as {criterion, reason}.
        - Put localized single-object problems in object_issues as {object_id, criterion, reason}.
        - criterion should state the generic acceptance rule being violated, preferably in reusable object-type terms, not in image-specific subject terms.
        - Put the concrete object identity, side, or local context in reason and object_id, not in criterion.
        - If a checklist violation is caused by a specific object, put it only in object_issues.
        - Keep global_repairs and object_issues clearly separated with no duplicated issue content.
        - Use global_repairs only for region-wide structure, cross-object alignment, coverage,
          or mergeability problems that cannot be assigned to one object.
        - Any issue about relative position, layout relationship, spacing, or offset between multiple objects belongs in global_repairs.
        - Use object_issues only when the problem is internal to one object rather than its relationship to neighboring objects.
        - Use object_issues only for isolated single-object fidelity or completeness problems.
        - Do not use a fidelity criterion to report a purely spatial relation problem; route shared spacing, balance, or relative placement problems through global_repairs instead.
        - Do not use a spatial-layout criterion to hide an internal fidelity mismatch; if shape, silhouette, or structural likeness is wrong, report that explicitly in object_issues.
        - When an icon differs in recognizable shape, silhouette structure, or internal simplification, record that fidelity problem explicitly instead of collapsing it into a generic spacing issue.
        - For icons and symbolic marks, preserve semantic recognizability, silhouette agreement, and structural simplicity before optimizing small whitespace preferences or tiny proportion tweaks.
        - If a reported layout issue is mainly a consequence of one object's incorrect shape or visual weight, still mention the underlying object fidelity problem explicitly.

        3. Review tolerance
        - Be tolerant of minor low-impact differences when the overall standalone region semantics
          and major visual structure are correct.
        - Do not fail for slight background tone, small proportion, spacing, or placement differences
          unless they materially harm semantics, readability, or mergeability.
        - Do not infer "too large", "too low", "too close", or similar spatial defects from a mild stylistic preference alone; require clear visual evidence such as crowding, broken hierarchy, reduced readability, border pressure, or noticeably uneven balance versus the raster.
        - Moderate differences in whitespace or spacing may be acceptable when object identity, recognizability, and overall composition remain intact.

        4. Output style
        - Diagnose and route problems only. Do not provide repair plans or suggestions.
        - The output schema is problem-only: reason fields explain what is wrong, not how to fix it.
        - Every reason must be brief, clear, and no more than 15 words.
        - Input roles: image 1 is the ground-truth raster crop; image 2 is the rendered preview of the proposed SVG.
        - Inline SVG source text is structural evidence for locating issues. Use the rendered preview as the primary visual comparison target.
        """
    ).strip()
    user_prompt = join_sections(
        section(
            "Region review request",
            (
                "Attached images are, in order: "
                "1) the source raster crop, 2) the rendered preview of the provided SVG.\n"
                f"Review whether the SVG fragment accurately reconstructs this cropped region: {region['description']}"
            ),
        ),
        json_section("Region context", region_context),
        json_section("Applicable checklist criteria", checklist_criteria),
        inline_text_file_section(
            "Proposed region SVG source",
            file_name=svg_file_name,
            content=proposed_svg_elements,
            role="Structural SVG source that corresponds to the rendered preview image.",
        ),
        json_section("Recognized objects", object_summary),
        section(
            "Return this JSON shape",
            textwrap.dedent(
                f"""
                {{
                  "region_id": "{region['region_id']}",
                  "passed_items": ["criterion text"],
                  "global_repairs": [
                    {{
                      "criterion": "criterion text",
                      "reason": "A brief description of the problem"
                    }}
                  ],
                  "object_issues": [
                    {{
                      "object_id": "object_id",
                      "criterion": "criterion text",
                      "reason": "A brief description of the problem"
                    }}
                  ]
                }}
                """
            ).strip(),
        ),
    )
    return system_prompt, user_prompt
