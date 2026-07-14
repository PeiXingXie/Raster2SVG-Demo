"""Prompt builders for model-assisted supervisor routing and strategy decisions."""

from __future__ import annotations

import json
import textwrap

from deepagents_template.prompt.bbox_conventions import (
    BBOX_COORDINATE_CONVENTION_RULE,
    GLOBAL_BBOX_COORDINATE_RULE,
    GLOBAL_CROP_VISUAL_EVIDENCE_RULE,
    GLOBAL_NO_LOCAL_COORDINATE_GUESS_RULE,
    GLOBAL_NO_OFFSET_REAPPLICATION_RULE,
)
from deepagents_template.prompt.final import FINAL_REVIEW_ISSUE_RULES, final_review_result_json_example
from deepagents_template.utils.prompting import (
    compact_dict,
    inline_text_file_section,
    join_sections,
    json_output_contract,
    json_section,
    section,
)

STRATEGY_CONFIDENCE_RULE = (
    'strategy_confidence must be exactly "low", "medium", or "high" as a JSON string. '
    "Never return numeric scores or percentages."
)

PASSED_ITEMS_FORMAT_RULE = (
    "review.passed_items must be a JSON array of plain strings, each a brief note about what already looks acceptable. "
    "Never put {criterion, reason, severity} objects in passed_items; that object shape is only for global_repairs and object_issues."
)

ISSUE_SEVERITY_RULES = (
    'Every review issue must include severity exactly as "low", "medium", or "high". '
    "Judge severity by visual/material impact, not by wording style. "
    "Use low only for cosmetic differences that preserve identity, structure, readability, containment, and editability. "
    "Use medium for visible fidelity mismatches that preserve identity and core structure. "
    "Use high for missing/wrong/generic objects, broken structure, unreadable text, clipping/out-of-bounds content, wrong identity, or layout hierarchy failure."
)

SYMBOLIC_FIDELITY_TERMS = (
    "icon",
    "badge",
    "emblem",
    "mark",
    "logo",
)

GENERIC_ICON_FIDELITY_GOALS = (
    "Preserve visible symbolic form beyond recognizability.",
    "Preserve contours, internal marks, and owned-part relationships.",
    "Avoid generic same-category replacement.",
)

GENERIC_OWNED_SYMBOL_FIDELITY_GOALS = (
    "Preserve owned symbolic details inside the object.",
    "Preserve symbol contours, internal marks, and local style.",
    "Avoid generic replacement of owned symbols or badges.",
)

GENERIC_LOCAL_FIDELITY_GOALS_BY_TYPE = {
    "background": (
        "Preserve local fill, extent, and layering role.",
        "Preserve local visual style inside the object bbox.",
    ),
    "container": (
        "Preserve the container's own contour, border, and fill.",
        "Preserve local decorations or owned parts inside the container.",
    ),
    "connector": (
        "Preserve connector endpoints, direction, and local stroke style.",
        "Preserve local connector structure inside the object bbox.",
    ),
    "diagram": (
        "Preserve local diagram marks, labels, and internal structure.",
        "Preserve local visual encoding inside the object bbox.",
    ),
    "fig": (
        "Preserve the local visible placeholder shape and dominant appearance.",
        "Preserve local crop or block structure inside the object bbox.",
    ),
    "text": (
        "Preserve text content, readability, and local typography.",
        "Preserve local text layout inside the object bbox.",
    ),
}

REPLACEMENT_ISSUE_REFS_FORMAT_RULE = (
    "prior_issue_assessment[].replacement_issue_refs must be a JSON array of objects with issue_id and label fields. "
    "Never return plain strings, criterion names, or JSON paths in replacement_issue_refs. "
    "Use [] when status is resolved, persists, or uncertain with no replacement issue. "
    "When status is transformed, list each replacement as "
    '{"issue_id": "stable_issue_id", "label": "brief label"}.'
)

PRIOR_ISSUE_STATUS_RULE = (
    'prior_issue_assessment[].status must be exactly one of "resolved", "persists", "transformed", or "uncertain". '
    'Never use synonyms such as "unresolved" or "open".'
)

COMMON_SCOPE_BOUNDARY_RULES = textwrap.dedent(
    """
    - Object-local issues are defects inside one recognized object.
    - Internal layout inside one recognized object is object-local, including relative placement, overlap, z-order, grouping, and proportions among elements owned by that object.
    - Region/global issues are defects that require moving, resizing, aligning, spacing, layering, or merging multiple objects or the whole region.
    - If a relative placement problem is between elements owned by the same recognized object, treat it as object-local.
    - If a relative placement, spacing, alignment, scale, overlap, or relationship problem is between two recognized objects, treat it as region/global.
    - Object-local checks must be decidable from that object's own bbox or owned SVG group; sibling-object spacing, scale balance, alignment, and region padding are region/global.
    - If the visual cause belongs to a neighboring object, do not assign the issue to the current object.
    """
).strip()

REGION_SCOPE_CLASSIFICATION_RULES = textwrap.dedent(
    f"""
    - Put region/global issues in review.global_repairs.
    - Put object-local issues in review.object_issues.
    - Do not duplicate the same issue in both lists.
    {COMMON_SCOPE_BOUNDARY_RULES}
    """
).strip()

OBJECT_SCOPE_REVIEW_RULES = textwrap.dedent(
    f"""
    - Judge only the target object described in the Object payload.
    - Do not report region/global issues, neighboring object issues, global alignment issues, or merge issues.
    - Do not ask for whole-region changes.
    - route is always object_repair.
    - repair_plan must describe the smallest object-local SVG edit likely to improve the target object.
    {COMMON_SCOPE_BOUNDARY_RULES}
    """
).strip()

REGION_ISSUE_TAXONOMY_RULES = textwrap.dedent(
    """
    - Every review.global_repairs[] item must include issue_family from the closed region issue families:
      layout_relation, containment_boundary, coverage_completeness, visual_consistency, editability_structure.
    - layout_relation: multi-object position, spacing, alignment, scale, z-order, hierarchy, or relationship mismatch.
    - containment_boundary: visible content is outside, clipped by, pressed against, or incorrectly contained by a region/object boundary.
    - coverage_completeness: required region content is missing, duplicated, extra, or semantically incomplete.
    - visual_consistency: cross-object or whole-region color, stroke, typography, visual weight, or style consistency mismatch.
    - editability_structure: SVG grouping, object ownership, data-object-id, wrapper, or mergeability structure is wrong.
    - Choose editability_structure first for SVG grouping/mergeability defects.
    - Otherwise choose coverage_completeness for missing, duplicated, extra, or absent content.
    - Otherwise choose containment_boundary for out-of-bounds, clipping, edge pressure, or containment defects.
    - Otherwise choose layout_relation for multi-object position, spacing, alignment, scale, z-order, or hierarchy defects.
    - Otherwise choose visual_consistency for cross-object or whole-region style and visual coherence defects.
    - Every review.object_issues[] item must include issue_family from the closed object-local issue families:
      content_accuracy, shape_fidelity, internal_structure, style_appearance, containment_boundary.
    - content_accuracy: object content, text, data value, semantic identity, or required owned part is wrong, missing, extra, unreadable, or misleading.
    - shape_fidelity: outer silhouette, contour, geometry, proportions, or recognizable shape likeness differs from the raster.
    - internal_structure: owned sub-elements, internal strokes, z-order, grouping, relative placement, or internal layout inside the object is wrong.
    - Do not use object_issues for sibling-object spacing, cross-object scale balance, region padding, or content-stack alignment; use layout_relation.
    - style_appearance: color, fill, stroke, typography, opacity, visual weight, or object-local styling differs while content and structure remain intact.
    - For object_issues, choose containment_boundary first for clipping or out-of-bounds defects, then content_accuracy, internal_structure, shape_fidelity, and style_appearance.
    """
).strip()

LAYOUT_STYLE_TOLERANCE_RULES = textwrap.dedent(
    """
    - Do not report minor font-size, stroke-width, color tone, whitespace, shape proportion, or small position differences unless they materially harm semantics, readability, containment, object identity, or mergeability.
    - Do not repeatedly optimize layout/style when the current relative layout is broadly consistent with the raster.
    - Prefer passing or low severity for style_appearance or visual_consistency issues when content, object identity, structure, and readability are preserved.
    - Medium/high severity should be reserved for visible failures that change identity, break hierarchy, cause crowding/overlap, reduce readability, or damage mergeability.
    """
).strip()

OBJECT_ISSUE_TAXONOMY_RULES = textwrap.dedent(
    """
    - Every review.failed_items[] item must include issue_family.
    - issue_family must use exactly one of the closed object-local issue families:
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


def history_rules_block(enabled: bool, variant: str) -> str:
    if not enabled:
        return ""
    audience = {
        "region": "review.global_repairs or review.object_issues",
        "object": "review.failed_items",
        "fusion": "the current review",
    }[variant]
    return textwrap.dedent(
        f"""
        - previous_decision_delta and memory delta are historical hints only. They must not override current visual evidence.
        - previous_decision_delta.prior_issues_to_verify are claims to verify, not issues to copy forward.
        - First assess each prior issue against the current images, then write the current review from scratch.
        - If a prior issue is resolved, do not restate it in {audience}.
        - If a prior issue evolved into a different problem, mark it transformed and describe the current issue freshly.
        {PRIOR_ISSUE_STATUS_RULE}
        {REPLACEMENT_ISSUE_REFS_FORMAT_RULE}
        - prior_issue_assessment and review must be mutually consistent.
        """
    ).strip()


def history_example_block(enabled: bool, variant: str) -> str:
    if not enabled:
        return lambda _context_id: ""
    return {
        "region": lambda context_id: textwrap.dedent(
            f"""
            "prior_issue_assessment": [
              {{
                "issue_id": "region:{context_id}:spacing_crowded",
                "status": "resolved",
                "current_reason": "Card spacing now matches the raster.",
                "replacement_issue_refs": []
              }},
              {{
                "issue_id": "object:{context_id}:title_text:Icon silhouette mismatch",
                "status": "transformed",
                "current_reason": "Icon placement is fixed, but stroke weight still looks too heavy.",
                "replacement_issue_refs": [
                  {{
                    "issue_id": "object:{context_id}:title_text:Stroke weight too heavy",
                    "label": "stroke_weight_heavy"
                  }}
                ]
              }}
            ],
            """
        ).strip(),
        "object": lambda context_id: textwrap.dedent(
            f"""
            "prior_issue_assessment": [
              {{
                "issue_id": "object:{context_id}:bbox clips visible content",
                "status": "resolved",
                "current_reason": "Glyph clipping is no longer visible.",
                "replacement_issue_refs": []
              }},
              {{
                "issue_id": "object:{context_id}:Icon silhouette mismatch",
                "status": "transformed",
                "current_reason": "Silhouette is closer, but internal stroke detail still diverges.",
                "replacement_issue_refs": [
                  {{
                    "issue_id": "object:{context_id}:Internal stroke detail mismatch",
                    "label": "internal_stroke_detail"
                  }}
                ]
              }}
            ],
            """
        ).strip(),
        "fusion": lambda _context_id: textwrap.dedent(
            """
            "prior_issue_assessment": [
              {
                "issue_id": "fusion:layout_fidelity:r1,r2:card_spacing_compressed",
                "status": "resolved",
                "current_reason": "Inter-card gap now matches the source stack.",
                "replacement_issue_refs": []
              },
              {
                "issue_id": "fusion:object_consistency:r1,r2:text_style_weight_mismatch",
                "status": "transformed",
                "current_reason": "Text weight improved, but card borders still read too heavy.",
                "replacement_issue_refs": [
                  {
                    "issue_id": "fusion:visual_quality:r1,r2:border_stroke_heavy",
                    "label": "border_stroke_heavy"
                  }
                ]
              }
            ],
            """
        ).strip(),
    }[variant]


def history_array_fields(enabled: bool, *fields: str) -> tuple[str, ...]:
    if not enabled:
        return tuple(fields)
    return ("prior_issue_assessment", *fields)


def history_closed_value_fields(enabled: bool) -> dict[str, tuple[str, ...]]:
    if not enabled:
        return {}
    return {"prior_issue_assessment[].status": ("resolved", "persists", "transformed", "uncertain")}


def history_section_block(enabled: bool, variant: str) -> str:
    if not enabled:
        return ""
    return textwrap.dedent(
        f"""
        History rules:
        - Only include prior_issue_assessment when previous_decision_delta or supervisor memory delta is provided.
        - Historical issues are hints to verify, not issues to copy forward.
        - Current visual evidence is authoritative.
        {history_rules_block(enabled, variant)}
        """
    ).strip()


def object_has_symbolic_fidelity_content(obj: dict) -> bool:
    if str(obj.get("object_type") or "").strip().lower() == "icon":
        return True
    text_parts: list[str] = []
    for key in ("included_elements", "generation_focus"):
        values = obj.get(key) or []
        if isinstance(values, list):
            text_parts.extend(str(item) for item in values)
    hints = obj.get("fidelity_hints") or {}
    if isinstance(hints, dict):
        goals = hints.get("fidelity_goals") or []
        if isinstance(goals, list):
            text_parts.extend(str(item) for item in goals)
    text = " ".join(text_parts).lower()
    return any(term in text for term in SYMBOLIC_FIDELITY_TERMS)


def build_required_fidelity_checks(object_index: dict) -> list[dict]:
    required_fidelity_checks = []
    for obj in object_index.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        object_id = obj.get("object_id")
        if not object_id:
            continue
        object_type = str(obj.get("object_type") or "").strip().lower()
        hints = obj.get("fidelity_hints") or {}
        goals: list[str] = []
        verify_required = False
        if isinstance(hints, dict):
            verify_required = bool(hints.get("verify_required"))
            goals = [
                str(goal).strip()
                for goal in (hints.get("fidelity_goals") or [])
                if str(goal).strip()
            ][:5]
        if not (verify_required or object_has_symbolic_fidelity_content(obj)):
            continue
        has_symbolic_content = object_has_symbolic_fidelity_content(obj)
        if object_type == "icon":
            fallback_goals = list(GENERIC_ICON_FIDELITY_GOALS)
        elif has_symbolic_content:
            fallback_goals = list(GENERIC_OWNED_SYMBOL_FIDELITY_GOALS)
        else:
            fallback_goals = list(GENERIC_LOCAL_FIDELITY_GOALS_BY_TYPE.get(object_type, ()))
        for fallback_goal in fallback_goals:
            if len(goals) >= 5:
                break
            if fallback_goal not in goals:
                goals.append(fallback_goal)
        required_fidelity_checks.append(
            {
                "object_id": object_id,
                "object_type": obj.get("object_type"),
                "fidelity_goals": goals[:5],
            }
        )
    return required_fidelity_checks


def build_region_combined_policy_prompts(
    *,
    region: dict,
    review_context: dict,
    memory_summary: dict | None,
    retry_context_summary: dict,
    strategy_enabled: bool,
    svg_source_text: str | None = None,
    svg_file_name: str | None = None,
) -> tuple[str, str]:
    has_history = memory_summary is not None or review_context.get("previous_decision_delta") is not None
    history_shape = history_example_block(has_history, "region")(region.get("region_id", ""))
    object_index = review_context.get("object_index") or {}
    required_fidelity_checks = build_required_fidelity_checks(object_index)
    compact_object_index = {"objects": []}
    for obj in object_index.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        compact_obj = {key: value for key, value in obj.items() if key != "fidelity_hints"}
        compact_object_index["objects"].append(compact_obj)
    strategy_clause = (
        f"""
        - If a useful repair strategy exists, provide repair_plan.strategy_label, repair_plan.strategy_rationale, and repair_plan.strategy_confidence.
        - If no useful strategy exists, set repair_plan.strategy_label, repair_plan.strategy_rationale, and repair_plan.strategy_confidence to null.
        {STRATEGY_CONFIDENCE_RULE}
        - Keep strategy_label concise and reusable.
        """
        if strategy_enabled
        else """
        - Set repair_plan.strategy_enabled to false and all strategy fields to null.
        """
    )
    system_prompt = textwrap.dedent(
        f"""
        You are a region-level review and routing advisor for a raster-to-SVG workflow.
        Compare image 1, the source region crop, with image 2, the rendered preview of the current SVG.
        Use the inline SVG only as structural evidence for locating objects and groups.
        Return JSON only.
        Do not generate or edit SVG in this call.

        Your output has three jobs:
        1. review: identify unresolved visual or structural issues.
        2. repair_plan: choose the next repair route.
        3. termination: decide whether the current result should be accepted or refined.

        Review rules:
        {REGION_SCOPE_CLASSIFICATION_RULES}
        {REGION_ISSUE_TAXONOMY_RULES}
        {LAYOUT_STYLE_TOLERANCE_RULES}
        - {GLOBAL_BBOX_COORDINATE_RULE}
        - Object bboxes in review_context.object_index and bbox_constraint_feedback follow this global coordinate frame.
        - {GLOBAL_CROP_VISUAL_EVIDENCE_RULE}
        - {GLOBAL_NO_OFFSET_REAPPLICATION_RULE}
        - {GLOBAL_NO_LOCAL_COORDINATE_GUESS_RULE}
        - {BBOX_COORDINATE_CONVENTION_RULE}
        - {PASSED_ITEMS_FORMAT_RULE}
        - Prefer fewer, higher-signal issues over exhaustive coverage.
        - passed_items should stay brief and selective rather than exhaustive.
        - Ignore low-impact polish unless it affects identity, readability, containment, editability, or mergeability.
        - In global_repairs and object_issues only, criterion should be a reusable acceptance rule, preferably framed in generic object-type or layout terms rather than image-specific subject names.
        - Put image-specific identity such as left/right role, depicted subject, or local context in reason or object_id, not in criterion.
        - review/global/object issue reasons must stay under 24 words; every rationale should stay under 20 words.

        Routing rules:
        - repair_plan.route is the primary repair route; it is not permission to omit other material issues.
        - Choose region_repair as the primary route when any review.global_repairs remain.
        - Choose object_repair as the primary route when all remaining issues are localized object issues and object repair is available.
        - If object repair is unavailable, choose region_repair.
        - target_objects must contain only object IDs from the provided object_index.
        - Global repairs do not suppress object-local fidelity issues.
        - Always report material review.object_issues even when review.global_repairs also exist.
        - The executor may repair selected global and object issues in the same round.

        Severity rules:
        - {ISSUE_SEVERITY_RULES}

        Special visual rules:
        - Required object fidelity checks are listed separately in the user prompt.
        - Before writing passed_items, inspect required_fidelity_checks and look for object-local visual-form mismatches.
        - For every object in required_fidelity_checks, silently compare the rendered visual appearance against its fidelity_goals before deciding acceptance.
        - For every object in required_fidelity_checks, output exactly one review.fidelity_verifications item with object_id, checks, and reason.
        - checks must contain exactly these keys with "Y" or "N" values: vf, is, op, ls, si.
        - fidelity_verifications checks are object-local diagnostic axes; review.object_issues issue_family is the repair taxonomy for routing.
        - Use checks to state where the object-local visual evidence fails; use object_issues to describe the material repairable defect.
        - Object fidelity verification is object-local: judge only the checked object's bbox or owned SVG group.
        - vf: visible-form fidelity. Check the object's outer contour, silhouette, major shape, proportions, and distinctive visible outline against the raster. Use "N" when the object keeps the same broad identity but its source-visible outer form is materially wrong, missing, substituted, distorted, or proportionally different.
        - is: internal-structure fidelity. Check source-visible internal marks, strokes, subparts, repeated motifs, connectivity, grouping, z-order, internal layout, and count/placement of meaningful internal elements. Use "N" when those visible internal details are missing, materially altered, wrongly counted, wrongly connected/grouped, misplaced, or visually substituted, even if the object remains semantically recognizable.
        - op: owned-part relationship fidelity. Check only relationships among parts owned by this object, including relative position, overlap, containment, attachment, and local z-order. Use "N" when owned parts are arranged differently enough to change the object's local structure; do not use op for sibling-object spacing, region padding, or layout among separately recognized objects.
        - ls: local-style fidelity. Check object-local stroke/fill language, color treatment, opacity, visual weight, texture, and pictogram style against the raster. Use "N" when local appearance materially changes the object's visual language while its form and structure may still be recognizable.
        - si: structural-integrity fidelity. Check whether the object remains visually coherent and usable as one intended object. Use "N" when it appears broken, collapsed, disconnected, malformed, clipped, self-overlapping in a confusing way, or structurally nonsensical.
        - Sibling-object spacing, cross-object scale balance, content-stack alignment, and region padding are not object fidelity failures; report those in review.global_repairs with issue_family="layout_relation".
        - Container checks cover the container's own contour, border, fill, local decorations, and owned parts only; they do not judge the layout among separate child/sibling objects.
        - Text checks cover local text content, readability, typography, and owned marks only; they do not judge spacing relative to separate objects.
        - reason must be concise visual evidence, preferably separated by semicolons when noting multiple points.
        - Each fidelity_verifications reason must stay under 32 words.
        - verification reason must cite concrete source-visible evidence from the checked axis; a reason that only states semantic identity, broad recognizability, or overall acceptability is insufficient.
        - Do not use reason to override checks.
        - Do not output a separate per-goal checklist; fidelity_verifications is one compact axis judgment per checked object, and object_issues contains material failures.
        - A generic pass such as "recognizable", "semantically faithful", "same category", or "looks correct" is insufficient for verify_required objects.
        - Do not use passed_items to merely restate fidelity_goals. If uncertain, prefer one concise object_issue over a generic pass.
        - If a required fidelity object passes, passed_items must mention concrete visible agreement in the rendered preview, not just the requested goal text.
        - If any fidelity goal materially fails, report it in review.object_issues on the owning object_id.
        - If any fidelity_verifications check is "N", also add a matching review.object_issues item for the same object_id.
        - If a fidelity_verifications reason describes a mismatch, missing detail, wrong form, generic replacement, or uncertainty, also add a matching review.object_issues item for the same object_id.
        - For required fidelity objects, report medium object_issues for visible visual-form mismatch even when semantic identity is preserved.
        - Do not require wrong identity before reporting shape_fidelity, internal_structure, or style_appearance on verify_required objects.
        - For every recognized object with object_type="icon", explicitly verify icon fidelity before deciding acceptance.
        - For icon or symbolic objects, prioritize semantic recognizability, silhouette/contour agreement, distinctive parts, coherent internal structure/topology, internal strokes/marks, owned-part proportions/overlap, z-order, and local pictogram style.
        - Treat outline weight as secondary unless it changes the object identity, local style, or visual weight.
        - When an icon materially fails fidelity, report it in review.object_issues with issue_family="content_accuracy" for wrong/generic semantics or missing identity, "shape_fidelity" for wrong silhouette/contour/proportion, or "internal_structure" for missing distinctive parts/internal strokes/z-order/internal layout.
        - When an icon looks unlike the raster reference, report that fidelity gap explicitly instead of reframing it only as scale or placement drift.
        - Do not accept an icon only because it is semantically recognizable; check silhouette/contour, distinctive parts, internal structure, internal strokes/marks, and owned-part relationships.
        - For verify_required objects, use content_accuracy for missing/wrong required visible detail, shape_fidelity for failed silhouette/contour goals, internal_structure for failed internal marks/strokes/topology/z-order/relative layout goals, and style_appearance for failed color/stroke/visual-weight goals.
        - For verify_required objects, medium severity means the object has the same broad semantics but a visible fidelity goal fails; high severity means generic substitution, missing key goal, wrong identity, or broken internal structure.
        - Layout/style tolerance does not suppress required symbol/icon fidelity checks.
        - For verify_required icons, visible contour, internal-structure, or local-style mismatch is not minor polish when it changes the symbol's visual identity.
        - Example fidelity verification: {{"object_id": "cloud_code_icon", "checks": {{"vf": "Y", "is": "Y", "op": "Y", "ls": "Y", "si": "Y"}}, "reason": "Cloud contour matches; window placement and code marks match the raster icon."}}
        - Example fidelity verification: {{"object_id": "calendar_icon", "checks": {{"vf": "Y", "is": "N", "op": "Y", "ls": "Y", "si": "Y"}}, "reason": "Outer calendar shape is close; date grid rows are missing and top rings are simplified."}}
        - Example object issue: {{"object_id": "icon_1", "issue_family": "internal_structure", "criterion": "Preserve symbol internal structure.", "reason": "Internal marks or topology differ from the raster symbol.", "severity": "medium"}}
        - Example object issue: {{"object_id": "icon_2", "issue_family": "shape_fidelity", "criterion": "Preserve symbol visible form.", "reason": "Outer contour or part proportions differ from the raster symbol.", "severity": "medium"}}
        - Example object issue: {{"object_id": "icon_3", "issue_family": "style_appearance", "criterion": "Preserve symbol local style.", "reason": "Local pictogram style looks like a different symbol system.", "severity": "medium"}}
        - Use spacing/scale/placement issues when there is clear visual evidence of crowding, broken hierarchy, border pressure, overlap risk, or noticeably uneven balance, not merely a mild preference for more open whitespace.
        - Avoid escalating small spacing differences into repeated shrink-and-lift adjustments when the current relative layout already appears broadly consistent with the raster.
        - If bbox_constraint_feedback reports that a rendered object no longer fits its recognized bbox, treat that as real acceptance evidence and route it to repair rather than ignoring it.

        Termination rules:
        - acceptance_tendency is accept only when no material issues remain, or only low-severity residuals remain.
        - stop_tendency is continue when another focused repair is likely to improve a medium or high issue.
        - stop_tendency is stop when retry constraints are exhausted or remaining issues are unlikely to improve.

        {history_section_block(has_history, "region")}

        Strategy rules:
        {strategy_clause}

        {json_output_contract(
            required_fields=("review", "repair_plan", "termination"),
            array_fields=history_array_fields(
                has_history,
                "review.passed_items",
                "review.fidelity_verifications",
                "review.global_repairs",
                "review.object_issues",
                "repair_plan.target_objects",
            ),
            closed_value_fields={
                "repair_plan.route": ("region_repair", "object_repair"),
                "termination.acceptance_tendency": ("accept", "reject"),
                "termination.stop_tendency": ("continue", "stop"),
                "repair_plan.strategy_confidence": ("low", "medium", "high"),
                "review.global_repairs[].severity": ("low", "medium", "high"),
                "review.object_issues[].severity": ("low", "medium", "high"),
                "review.global_repairs[].issue_family": (
                    "layout_relation",
                    "containment_boundary",
                    "coverage_completeness",
                    "visual_consistency",
                    "editability_structure",
                ),
                "review.object_issues[].issue_family": (
                    "content_accuracy",
                    "shape_fidelity",
                    "internal_structure",
                    "style_appearance",
                    "containment_boundary",
                ),
                **history_closed_value_fields(has_history),
            },
        )}
        """
    ).strip()
    review_sections = compact_dict(
        {
            "checklist": review_context.get("checklist"),
            "object_index": compact_object_index,
            "required_fidelity_checks": required_fidelity_checks,
            "bbox_constraint_feedback": review_context.get("bbox_constraint_feedback"),
            "fidelity_verification_retry": review_context.get("fidelity_verification_retry"),
            "previous_decision_delta": review_context.get("previous_decision_delta"),
        }
    )
    strategy_confidence_example = '"medium"' if strategy_enabled else "null"
    user_prompt = join_sections(
        section(
            "Region combined review/policy request",
            "Attached images are, in order: 1) the source raster crop, 2) the rendered preview of the provided SVG.",
        ),
        json_section("Region", region),
        json_section("Review context", review_sections),
        inline_text_file_section(
            "Current region SVG source",
            file_name=svg_file_name or f"region-{region.get('region_id', 'unknown')}.svg",
            content=svg_source_text or "",
            role="Structural SVG source that corresponds to the rendered preview image.",
        ),
        section("Supervisor memory delta", json.dumps(memory_summary, ensure_ascii=False, indent=2) if memory_summary is not None else ""),
        json_section("Execution constraints", retry_context_summary),
        section(
            "Return this JSON shape",
            textwrap.dedent(
                f"""
                {{
                  {history_shape}
                  "review": {{
                    "region_id": "{region.get("region_id", "")}",
                    "passed_items": [
                      "Rounded card border reads clearly.",
                      "Title and description hierarchy preserved."
                    ],
                    "fidelity_verifications": [{{"object_id": "cloud_code_icon", "checks": {{"vf": "Y", "is": "Y", "op": "Y", "ls": "Y", "si": "Y"}}, "reason": "Cloud contour and code badge match the raster icon."}}],
                    "global_repairs": [{{"issue_family": "layout_relation", "criterion": "brief criterion", "reason": "brief reason", "severity": "medium"}}],
                    "object_issues": [{{"object_id": "obj1", "issue_family": "shape_fidelity", "criterion": "brief criterion", "reason": "brief reason", "severity": "medium"}}]
                  }},
                  "repair_plan": {{
                    "route": "region_repair",
                    "route_rationale": "brief reason",
                    "target_objects": [],
                    "strategy_enabled": {str(strategy_enabled).lower()},
                    "strategy_label": {"\"increase_cta_gap\"" if strategy_enabled else "null"},
                    "strategy_rationale": {"\"Move the CTA lower while preserving card padding.\"" if strategy_enabled else "null"},
                    "strategy_confidence": {strategy_confidence_example}
                  }},
                  "termination": {{
                    "acceptance_tendency": "reject",
                    "acceptance_rationale": "brief reason",
                    "stop_tendency": "continue",
                    "stop_rationale": "brief reason"
                  }}
                }}
                """
            ).strip(),
        ),
    )
    return system_prompt, user_prompt


def build_object_combined_policy_prompts(
    *,
    obj: dict,
    review_context: dict,
    memory_summary: dict | None,
    strategy_enabled: bool,
    svg_source_text: str | None = None,
    svg_file_name: str | None = None,
) -> tuple[str, str]:
    has_history = memory_summary is not None or review_context.get("previous_decision_delta") is not None
    history_shape = history_example_block(has_history, "object")(obj.get("object_id", ""))
    object_history_rule = (
        "- Treat failed_items, previous_decision_delta, and memory as hypotheses to verify against the current images, not facts to copy forward."
        if has_history
        else "- Treat failed_items as hypotheses to verify against the current images, not facts to copy forward."
    )
    strategy_clause = (
        f"Include strategy fields with concise label, rationale, and confidence. {STRATEGY_CONFIDENCE_RULE}"
        if strategy_enabled
        else "Set strategy_enabled to false and all strategy fields to null."
    )
    system_prompt = textwrap.dedent(
        f"""
        You are an object-scoped review and refinement policy worker for a raster-to-SVG workflow.
        Review one target object SVG against its object crop, then emit object review, object-local repair plan, and termination tendencies.
        Return JSON only.

        Rules:
        {OBJECT_SCOPE_REVIEW_RULES}
        - acceptance_tendency must be accept or reject.
        - stop_tendency must be continue or stop.
        - failed item reasons must stay under 24 words; all rationales should stay under 20 words.
        {OBJECT_ISSUE_TAXONOMY_RULES}
        - {ISSUE_SEVERITY_RULES}
        {object_history_rule}
        - Use a compact review style: keep only the most decision-relevant unresolved object issues.
        - Ignore minor polish unless it affects semantics, identity, or readability.
        - If Object.fidelity_hints.verify_required is true, evaluate Object.fidelity_hints.fidelity_goals before accepting.
        - Generic pass reasoning such as recognizable, semantically faithful, or same-category is insufficient for verify_required objects.
        - For verify_required objects, fail materially unmet goals: missing required detail, generic substitution, wrong silhouette, changed internal marks/strokes/topology, wrong z-order, or wrong visual weight.
        - For text objects, fail unreadable, wrong, missing, clipped, or materially mis-styled text.
        - For icon objects, do not accept semantic-category approximations alone.
        - Icon SVG must preserve the raster icon's intended structure, distinctive silhouette, meaningful subparts, internal strokes, visual weight, z-order, and internal element layout.
        - Fail generic substitutions, missing distinctive parts, wrong silhouette, excessive appearance drift, broken or missing internal strokes, wrong z-order, misplaced internal elements, incorrect relative proportions, or visibly malformed contours.
        - Fail any icon that looks arbitrary, structurally broken, unintentionally jagged, visually nonsensical, or damaged, even if it loosely matches the source category.
        - A repaired icon may have small visual differences, but it must remain a coherent, meaningful, same-semantics icon rather than a distorted trace.
        - For container/background objects, fail wrong extent, fill, border, hierarchy, or clipping.
        - For connector objects, fail broken endpoints, wrong direction, or missing connection semantics.
        - For diagram objects, fail wrong scale, encoding, value, missing mark, broken axis/legend, unreadable label, or misleading internal layout.
        - For fig objects, simple color-block abstraction is acceptable; fail only when the main visual block, dominant color/shape, crop, or semantic placeholder is missing or misleading.
        - The fig color-block allowance applies only to object_type="fig"; never apply it to icon objects.
        - For icon objects, high severity means wrong/generic icon, missing key distinctive parts, malformed or damaged contour, broken core internal structure, or wrong intended semantics.
        - For icon objects, medium severity means a recognizable same-semantics icon with visible silhouette, proportion, stroke-weight, z-order, or internal-layout mismatch.
        - For icon objects, low severity means tiny visual differences that preserve identity, silhouette, internal structure, visual weight, and readability.
        - Input roles: image 1 is the ground-truth object crop; image 2 is the rendered preview of the current SVG.
        - Inline SVG source text is structural evidence for localization. Use the rendered preview as the primary visual comparison target.
        - {GLOBAL_BBOX_COORDINATE_RULE}
        - The Object payload bbox follows this global coordinate frame.
        - {GLOBAL_CROP_VISUAL_EVIDENCE_RULE}
        - {GLOBAL_NO_OFFSET_REAPPLICATION_RULE}
        - {GLOBAL_NO_LOCAL_COORDINATE_GUESS_RULE}
        - {BBOX_COORDINATE_CONVENTION_RULE}
        - If review.failed_items is empty, acceptance_tendency must be "accept" and stop_tendency must be "stop".
        - For icon objects, wrong identity, generic substitution, malformed contours, or missing distinctive parts are never low-impact cosmetic issues.
        - If medium/high object-local issues remain and another SVG edit is likely to improve them, use reject + continue.
        - If only low-impact cosmetic differences remain, usually use accept + stop.
        - If the remaining issue cannot be fixed by editing this object alone, use reject + stop and explain briefly.
        - For icon object_repair, strategy_label should name the main object-local repair dimension when possible: restore_silhouette, add_distinctive_parts, repair_internal_strokes, fix_visual_weight, fix_z_order, fix_internal_layout, fix_relative_proportions, repair_malformed_contour, or remove_generic_substitution.
        - strategy_rationale should state the concrete visual target to repair, not a generic "improve fidelity".
        {history_section_block(has_history, "object")}
        {strategy_clause}
        {json_output_contract(
            required_fields=("review", "repair_plan", "termination"),
            array_fields=history_array_fields(has_history, "review.failed_items"),
            closed_value_fields={
                "repair_plan.route": ("object_repair",),
                "termination.acceptance_tendency": ("accept", "reject"),
                "termination.stop_tendency": ("continue", "stop"),
                "repair_plan.strategy_confidence": ("low", "medium", "high"),
                "review.failed_items[].severity": ("low", "medium", "high"),
                "review.failed_items[].issue_family": (
                    "content_accuracy",
                    "shape_fidelity",
                    "internal_structure",
                    "style_appearance",
                    "containment_boundary",
                ),
                **history_closed_value_fields(has_history),
            },
        )}
        """
    ).strip()
    review_sections = compact_dict(
        {
            "failed_items": review_context.get("failed_items"),
            "previous_decision_delta": review_context.get("previous_decision_delta"),
        }
    )
    strategy_confidence_example = '"medium"' if strategy_enabled else "null"
    user_prompt = join_sections(
        section(
            "Object combined review/policy request",
            "Attached images are, in order: 1) the source object crop, 2) the rendered preview of the provided SVG.",
        ),
        json_section("Object", obj),
        json_section("Review context", review_sections),
        inline_text_file_section(
            "Current object SVG source",
            file_name=svg_file_name or f"object-{obj.get('object_id', 'unknown')}.svg",
            content=svg_source_text or "",
            role="Structural SVG source that corresponds to the rendered preview image.",
        ),
        section("Supervisor memory delta", json.dumps(memory_summary, ensure_ascii=False, indent=2) if memory_summary is not None else ""),
        section(
            "Return this JSON shape",
            textwrap.dedent(
                f"""
                {{
                  {history_shape}
                  "review": {{
                    "object_id": "{obj.get("object_id", "")}",
                    "failed_items": [{{"issue_family": "shape_fidelity", "criterion": "brief criterion", "reason": "brief reason", "severity": "medium"}}]
                  }},
                  "repair_plan": {{
                    "route": "object_repair",
                    "route_rationale": "brief reason",
                    "strategy_enabled": {str(strategy_enabled).lower()},
                    "strategy_label": null,
                    "strategy_rationale": null,
                    "strategy_confidence": {strategy_confidence_example}
                  }},
                  "termination": {{
                    "acceptance_tendency": "reject",
                    "acceptance_rationale": "brief reason",
                    "stop_tendency": "continue",
                    "stop_rationale": "brief reason"
                  }}
                }}
                """
            ).strip(),
        ),
    )
    return system_prompt, user_prompt


def build_fusion_combined_policy_prompts(
    *,
    user_request: str | None = None,
    final_review_context: dict,
    memory_summary: dict | None,
    strategy_enabled: bool,
    svg_source_text: str | None = None,
    svg_file_name: str | None = None,
) -> tuple[str, str]:
    has_history = memory_summary is not None or final_review_context.get("previous_decision_delta") is not None
    history_shape = history_example_block(has_history, "fusion")("")
    strategy_clause = (
        f"""
        Include strategy fields with a concise, actionable, merge-specific label, rationale, and confidence.
        Good strategy_label examples include reconnect_cross_region_connector, remove_duplicate_boundary,
        align_region_boundary, and normalize_repeated_marker_style.
        Do not propose broad redraw or cosmetic cleanup strategies.
        {STRATEGY_CONFIDENCE_RULE}
        """
        if strategy_enabled
        else "Set strategy_enabled to false and all strategy fields to null."
    )
    system_prompt = textwrap.dedent(
        f"""
        You are a fusion-quality review and policy advisor for a raster-to-SVG workflow.
        Your scope is the merged full-image SVG after region fragments have been combined.
        Report only issues that are global, cross-region, boundary-related, merge-induced,
        or clearly visible in the full merged result.
        Do not report ordinary single-region imperfections unless they create a visible
        full-image or boundary-level problem.

        Review the merged SVG against the source image, then emit:
        1. a compact fusion review,
        2. a merge-specific repair plan,
        3. termination tendencies.
        Return JSON only.

        Rules:
        - Do not output repair_plan.route; the backend inserts the fixed fusion_repair route.
        - acceptance_tendency must be accept or reject.
        - stop_tendency must be continue or stop.
        - review issue descriptions must stay under 24 words; all rationales should stay under 20 words.
        {FINAL_REVIEW_ISSUE_RULES}
        - Use a compact review style: capture the main cross-region and merge-relevant problems, not every small stylistic variance.
        - Prefer fewer, higher-signal issues over exhaustive lists.
        - Do not chase tiny local imperfections, microscopic alignment drift, or cosmetic style preferences.
        - Spatial and logical fusion issues determine repair and termination.
        - Visual-quality issues are diagnostic only unless they are clearly caused by merging or region-boundary interaction.
        - Do not recommend repair for purely local or cosmetic visual-quality issues.
        - Use high severity for missing, broken, duplicated, disconnected, cropped, or misleading cross-region structure.
        - Use medium severity for visible alignment, spacing, scale, or boundary problems that affect the full composition.
        - Use low severity for small residual seams, tiny style drift, or cosmetic polish that does not affect readability or structure.
        - Set acceptance_tendency to accept when no actionable spatial/logical fusion issues remain, or only low-severity residuals remain.
        - Set stop_tendency to continue only when there are actionable medium/high spatial or logical fusion issues that a conservative merge-time SVG repair can plausibly improve.
        - Set stop_tendency to stop when issues are absent, only low-severity, purely local, purely cosmetic, ambiguous, or unlikely to improve through merge-time repair.
        - Input roles: image 1 is the ground-truth source image; image 2 is the rendered preview of the final SVG.
        - Inline SVG source text is structural evidence for localization. Use the rendered preview as the primary visual comparison target.
        {history_section_block(has_history, "fusion")}
        {strategy_clause}
        {json_output_contract(
            required_fields=("review", "repair_plan", "termination"),
            array_fields=history_array_fields(has_history, "review.known_limitations"),
            closed_value_fields={
                "termination.acceptance_tendency": ("accept", "reject"),
                "termination.stop_tendency": ("continue", "stop"),
                "repair_plan.strategy_confidence": ("low", "medium", "high"),
                **history_closed_value_fields(has_history),
            },
        )}
        """
    ).strip()
    review_sections = compact_dict(
        {
            "checklist": final_review_context.get("checklist"),
            "previous_decision_delta": final_review_context.get("previous_decision_delta"),
        }
    )
    strategy_confidence_example = '"medium"' if strategy_enabled else "null"
    user_prompt = join_sections(
        section(
            "Fusion combined review/policy request",
            "Attached images are, in order: 1) the original source image, 2) the rendered preview of the provided final SVG.",
        ),
        section("User request", user_request),
        json_section("Review context", review_sections),
        inline_text_file_section(
            "Current merged SVG source",
            file_name=svg_file_name or "merged_final.svg",
            content=svg_source_text or "",
            role="Structural SVG source that corresponds to the rendered preview image.",
        ),
        section("Supervisor memory delta", json.dumps(memory_summary, ensure_ascii=False, indent=2) if memory_summary is not None else ""),
        section(
            "Return this JSON shape",
            textwrap.dedent(
                f"""
                {{
                  {history_shape}
                  "review": {final_review_result_json_example()},
                  "repair_plan": {{
                    "route_rationale": "brief reason",
                    "strategy_enabled": {str(strategy_enabled).lower()},
                    "strategy_label": null,
                    "strategy_rationale": null,
                    "strategy_confidence": {strategy_confidence_example}
                  }},
                  "termination": {{
                    "acceptance_tendency": "reject",
                    "acceptance_rationale": "brief reason",
                    "stop_tendency": "continue",
                    "stop_rationale": "brief reason"
                  }}
                }}
                """
            ).strip(),
        ),
    )
    return system_prompt, user_prompt
