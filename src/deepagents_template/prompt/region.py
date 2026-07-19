"""Overview: Prompt builders for region recognition, generation, repair, and review."""

from __future__ import annotations

import json
import textwrap

from deepagents_template.prompt.bbox_conventions import (
    BBOX_COORDINATE_CONVENTION_RULE,
    GLOBAL_BBOX_COORDINATE_RULE,
    GLOBAL_CROP_VISUAL_EVIDENCE_RULE,
    GLOBAL_NO_OFFSET_REAPPLICATION_RULE,
    GLOBAL_SVG_OUTPUT_COORDINATE_RULE,
)
from deepagents_template.schemas import RegionRecognitionResult
from deepagents_template.utils.context_payloads import build_recognition_generation_payload
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




def build_region_recognition_prompts(
    *,
    region: dict,
    region_context: dict,
    checklist_criteria: list[dict],
) -> tuple[str, str]:
    """Build Stage-1 prompts for frozen object structure and ownership only."""

    system_prompt = textwrap.dedent(
        f"""
        You identify editable object structure inside one cropped raster region.
        Inspect the crop and return only the object identity, type, description, and ownership structure.
        Return JSON only.

        Scope:
        - Identify independently editable semantic objects.
        - Assign each object a stable object_id and one object_type.
        - Describe each object's visible content and role.
        - List concrete visible elements semantically owned by each object.
        - Decide object granularity and ownership only. Do not plan SVG generation, bbox localization, or visual fidelity checks.

        Output rules:
        - Output valid JSON without markdown fences.
        - The image input is only the crop for this region, not the full source image.
        - recognized_objects must cover all visible content except the region wrapper itself.
        - Return recognized_objects=[] only when the crop genuinely contains no editable visible content.
        - object_id must be unique, stable, lowercase snake_case, and semantically meaningful.
        - object_id and description must be non-empty for every object.
        - region_id must exactly match the requested region_id shown in the output shape.
        - object_type must be one of: background, icon, text, container, connector, diagram, fig.
        - description must state visible content and role; transcribe readable text as accurately as possible.
        - included_elements lists concrete visible parts semantically owned by the object and must contain at most 6 short items.
        - Every visible primitive belongs to exactly one root-level object, directly or as an included_element.
        - Do not output generation_focus, relative_position, extent_hint, fidelity_hints, bbox, or bbox_space.
        - Do not include object bbox coordinates or infer global coordinates.
        - Use checklist criteria only as high-level coverage guidance.

        Granularity and ownership:
        - Output independently editable semantic units, not every primitive.
        - Prefer one object for a subject plus attached parts that are edited together.
        - A process or flowchart box with its internal label is usually one container object.
        - Attached labels, markers, internal strokes, annotations, and decorations belong to the owning object when they do not function independently.
        - Do not create a separate object for an element already listed in another object's included_elements.
        - Spatial containment alone does not imply ownership; backgrounds and frames may surround independent foreground objects.
        - Do not split one tightly coupled unit into many tiny objects or merge unrelated classes into one oversized object.
        - Keep independent side-by-side icons separate; group icons only when they form one inseparable composite mark or repeated decorative set.
        - Treat a tightly related connector/arrow/line network as one connector object.

        Object type definitions:
        - background: panel, fill, backdrop, halo, or framing shape.
        - icon: independently editable pictogram or symbolic mark.
        - text: words, labels, or numbers.
        - container: process node, box, card, or shape container with owned parts.
        - connector: connector, arrow, divider, edge, or local connector network.
        - diagram: chart, plot, axis-based, or encoded visual.
        - fig: natural image, barcode, or QR code.

        {json_output_contract(
            required_fields=("region_id", "observation", "recognized_objects"),
            array_fields=("recognized_objects", "recognized_objects[].included_elements"),
            closed_value_fields={
                "recognized_objects[].object_type": ("background", "icon", "text", "container", "connector", "diagram", "fig"),
            },
        )}
        """
    ).strip()
    user_prompt = textwrap.dedent(
        f"""
        Object-structure request:
        Identify the editable object structure in this cropped region: {region['description']}

        Region context:
        {json.dumps(region_context, ensure_ascii=False, indent=2)}

        Coordinate note:
        Use the crop image as visual evidence only; do not add the region bbox offset
        or infer global object coordinates.

        Applicable checklist criteria:
        {json.dumps(checklist_criteria, ensure_ascii=False, indent=2)}

        Return this JSON shape:
        {{
          "region_id": "{region['region_id']}",
          "observation": "short structural observation",
          "recognized_objects": [
            {{
              "object_id": "meaningful_object_name",
              "object_type": "icon",
              "description": "visible content and semantic role",
              "included_elements": ["outer symbol shape", "internal marks"]
            }}
          ]
        }}
        """
    ).strip()
    return system_prompt, user_prompt


def build_region_contract_enrichment_prompts(
    *,
    region: dict,
    recognized_objects: list[dict],
    checklist_criteria: list[dict],
) -> tuple[str, str]:
    """Build Stage-2 prompts that enrich a frozen object structure."""

    system_prompt = textwrap.dedent(
        f"""
        You enrich frozen object records with generation contract fields for a raster-to-SVG workflow.
        Inspect the source crop and return JSON only.

        Frozen-structure rules:
        - Use the provided object_id list as the complete and only set of objects.
        - Do not add, remove, split, merge, rename, or reclassify objects.
        - Do not change description, included_elements, ownership, or granularity.
        - object_updates may contain only object_id, generation_focus, relative_position, extent_hint, and fidelity_hints.

        Contract rules for every object:
        - generation_focus must contain 1-3 short, concrete preservation goals useful for SVG generation.
        - relative_position must describe crop-local position using semantic landmarks, not numeric coordinates.
        - extent_hint must state what visual extent should be included or avoided, naming important extremities when relevant.
        - fidelity_hints must be null unless the object needs the fidelity verification described below.
        - Keep all fields compact and grounded in visible evidence rather than generic quality language.

        Fidelity applicability:
        - Every object_type="icon" must set fidelity_hints.verify_required=true.
        - For an icon, target_elements must be exactly [object_id].
        - For non-icon objects, fidelity_hints is optional. Add it only when the owner contains an identity-bearing icon, badge, emblem, logo, mark, glyph, pictogram, or other symbolic visual detail that should not be replaced by a generic same-category substitute.
        - Do not add fidelity_hints merely for ordinary borders, fills, backgrounds, text grouping, spacing, alignment, cross-object layout, or non-identity-bearing decoration.
        - When verify_required=true, provide 1-5 short fidelity_goals naming concrete source-visible contour, distinctive parts, internal marks/strokes, topology, relative layout, z-order, proportions, visual weight, or local style.
        - For a non-icon owner, target_elements must name the owned symbolic content to inspect; it does not create another recognized object.
        - Do not use generic goals such as preserve the icon, keep visual fidelity, match the reference, or remain recognizable.

        {json_output_contract(
            required_fields=(
                "region_id",
                "object_updates",
                "object_updates[].object_id",
                "object_updates[].generation_focus",
                "object_updates[].relative_position",
                "object_updates[].extent_hint",
                "object_updates[].fidelity_hints",
            ),
            array_fields=("object_updates", "object_updates[].generation_focus"),
            extra_rules=(
                "The top-level value must be a JSON object, never an array.",
                "Return exactly one object_updates item for each frozen object_id and no other object_ids.",
                "Every object_updates item must include generation_focus, relative_position, extent_hint, and fidelity_hints.",
                "Do not add wrapper fields such as enrichment, text_elements, symbol_fidelity, visual_requirements, stage, role, or key_relations.",
            ),
        )}

        Return exactly this top-level shape:
        {{
          "region_id": "...",
          "object_updates": [
            {{
              "object_id": "...",
              "generation_focus": ["..."],
              "relative_position": "...",
              "extent_hint": "...",
              "fidelity_hints": null
            }}
          ]
        }}
        """
    ).strip()
    user_prompt = textwrap.dedent(
        f"""
        Object-contract enrichment request for region {region['region_id']}.

        Frozen object structure:
        {json.dumps(recognized_objects, ensure_ascii=False, indent=2)}

        Applicable checklist criteria:
        {json.dumps(checklist_criteria, ensure_ascii=False, indent=2)}

        Return object_updates for the provided object IDs only. Do not repeat or modify structure fields.
        """
    ).strip()
    return system_prompt, user_prompt


def build_targeted_contract_completion_prompts(
    *,
    region: dict,
    objects_to_complete: list[dict],
) -> tuple[str, str]:
    """Build Stage-3 prompts for field-level completion of audited contracts."""

    system_prompt = textwrap.dedent(
        f"""
        You complete requested invalid object contract fields for a raster-to-SVG workflow.
        Object identity, type, description, included_elements, ownership, and granularity are fixed and frozen.
        Inspect the source crop and return JSON only.

        Repair only the explicitly listed invalid_fields for the requested object IDs.
        Do not return unrequested objects, and do not return fields listed under accepted_contract.
        Do not add, remove, split, merge, rename, or reclassify objects.

        Field rules:
        - generation_focus: 1-3 short, concrete SVG preservation goals.
        - relative_position: crop-local semantic position without numeric coordinates.
        - extent_hint: concrete bbox inclusion/exclusion guidance without numeric coordinates.
        - fidelity_hints: for icons set verify_required=true, target_elements=[object_id], and provide 1-5 concrete source-visible goals; for an explicitly requested non-icon hint, scope targets to its owned symbolic content.
        - Never use generic fidelity goals such as preserve the icon, keep visual fidelity, match the reference, or remain recognizable.

        {json_output_contract(
            required_fields=("region_id", "object_updates", "object_updates[].object_id"),
            array_fields=(
                "object_updates",
                "object_updates[].generation_focus",
                "object_updates[].fidelity_hints.target_elements",
                "object_updates[].fidelity_hints.fidelity_goals",
            ),
            extra_rules=(
                "The top-level value must be a JSON object, never an array.",
                "Return only object_updates items for object IDs listed in the request.",
                "Each object_updates item may contain only object_id plus fields listed in that object's invalid_fields.",
                "Omit every accepted_contract field; do not echo accepted fields back.",
                "Do not add wrapper fields such as patch, enrichment, text_elements, symbol_fidelity, visual_requirements, stage, role, or key_relations.",
            ),
        )}

        Return exactly this top-level shape:
        {{
          "region_id": "...",
          "object_updates": [
            {{
              "object_id": "...",
              "generation_focus": ["..."]
            }}
          ]
        }}
        """
    ).strip()
    user_prompt = textwrap.dedent(
        f"""
        Targeted contract completion request for region {region['region_id']}.

        Requested objects, frozen structure, accepted fields, and validation issues:
        {json.dumps(objects_to_complete, ensure_ascii=False, indent=2)}

        Return only patches for invalid_fields. Omit every field that is already accepted.
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
        - Each recognized object's included_elements are owned by that object and should render inside that object's group.
        - For objects with fidelity_hints.verify_required=true, use fidelity_hints.target_elements as the visual focus and fidelity_hints.fidelity_goals as concrete visual obligations.
        - Do not substitute a cleaner generic same-category icon, symbol, badge, code window, network diagram, emblem, or mark when fidelity goals describe specific visible structure.
        - If a fidelity goal describes an owned detail inside a non-icon object, render that detail inside the owning object rather than dropping or simplifying it.
        - Small simplification is acceptable only when it preserves the goal's silhouette, internal structure, relative layout, z-order, and visual weight.
        - If current SVG source text is provided inline, treat it as the editable base to update rather than something to re-describe.
        - Failed items define the current repair target; do not invent unrelated new issues.
        - {GLOBAL_BBOX_COORDINATE_RULE}
        - Region bounds and recognized object bboxes follow this global coordinate frame.
        - {GLOBAL_SVG_OUTPUT_COORDINATE_RULE}
        - {GLOBAL_CROP_VISUAL_EVIDENCE_RULE}
        - {GLOBAL_NO_OFFSET_REAPPLICATION_RULE}
        - Treat recognized object bboxes as layout constraints, not loose hints.
        - {BBOX_COORDINATE_CONVENTION_RULE}
        - Keep each object's visible SVG geometry inside that object's bbox unless the failed_items explicitly request a bbox-related repair first.
        - If bbox validation feedback is provided, use it as acceptance evidence about which recognized objects still have risky bbox containment.
        - Follow a compact, pragmatic style: fix the main structural and semantic issues first, and do not over-explain.
        - Use comments:
          <!-- region: bbox=<x,y,width,height> -->
          <!-- object: <object_id> -->
        - Organize SVG as a human-friendly region-object hierarchy.
        - Return exactly one top-level region wrapper group for the region.
        - Every visible child under the region wrapper must belong to a top-level object group with data-object-id and data-object-type.
        - Do not create sibling object groups for sub-elements owned through another object's included_elements.
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
                  "svg_elements": "<!-- region: bbox=<global_x,global_y,width,height> -->\\n<g id=\\"region-{region['region_id']}\\" data-region-id=\\"{region['region_id']}\\">\\n  <g data-object-id=\\"background_panel\\" data-object-type=\\"background\\">...</g>\\n  <g data-object-id=\\"title_system\\" data-object-type=\\"text\\">...</g>\\n</g>",
                  "generation_notes": ["what was generated or updated"]
                }}
                """
            ).strip(),
        ),
    )
    return system_prompt, user_prompt
