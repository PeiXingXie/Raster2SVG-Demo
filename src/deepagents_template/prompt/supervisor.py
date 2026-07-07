"""Prompt builders for model-assisted supervisor routing and strategy decisions."""

from __future__ import annotations

import json
import textwrap

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
    strategy_clause = (
        f"""
        Include repair_plan.strategy_label, repair_plan.strategy_rationale, and repair_plan.strategy_confidence.
        {STRATEGY_CONFIDENCE_RULE}
        Keep strategy_label concise and reusable.
        """
        if strategy_enabled
        else """
        Set repair_plan.strategy_enabled to false and all strategy fields to null.
        """
    )
    system_prompt = textwrap.dedent(
        f"""
        You are a combined region review and policy advisor for a raster-to-SVG workflow.
        Review one region crop against the current SVG fragment, then emit:
        1. a concise structured review,
        2. the next repair route,
        3. termination tendencies.
        Return JSON only.

        Rules:
        - route must be either region_repair or object_repair.
        - Prefer region_repair for cross-object layout, spacing, containment, or multi-object relation issues.
        - Prefer object_repair only when remaining issues are localized inside one or a few objects.
        - acceptance_tendency must be accept or reject.
        - stop_tendency must be continue or stop.
        - review/global/object issue reasons and every rationale must stay under 24 words.
        - {PASSED_ITEMS_FORMAT_RULE}
        - Use a compact review style: capture the main unresolved issues and ignore low-value polish.
        - Prefer fewer, higher-signal issues over exhaustive coverage.
        - passed_items should stay brief and selective rather than exhaustive.
        - In global_repairs and object_issues only, criterion should be a reusable acceptance rule, preferably framed in generic object-type or layout terms rather than image-specific subject names.
        - Put image-specific identity such as left/right role, depicted subject, or local context in reason or object_id, not in criterion.
        - {ISSUE_SEVERITY_RULES}
        - For icons and symbolic objects, prioritize semantic recognizability, silhouette agreement, and appropriate structural simplification over small whitespace or micro-spacing preferences.
        - When an icon looks unlike the raster reference, report that fidelity gap explicitly instead of reframing it only as scale or placement drift.
        - Do not accept an icon only because it is semantically recognizable; check silhouette, distinctive parts, and internal strokes.
        - If any icon has a localized fidelity gap, include it in review.object_issues and prefer object_repair when no global repairs remain.
        - Keep spatial relation issues separate from fidelity issues: shared spacing, balance, and relative placement belong to region_repair; internal likeness or shape mismatch belongs to object_issues.
        - Use spacing/scale/placement issues when there is clear visual evidence of crowding, broken hierarchy, border pressure, overlap risk, or noticeably uneven balance, not merely a mild preference for more open whitespace.
        - Avoid escalating small spacing differences into repeated shrink-and-lift adjustments when the current relative layout already appears broadly consistent with the raster.
        - If bbox_constraint_feedback reports that a rendered object no longer fits its recognized bbox, treat that as real acceptance evidence and route it to repair rather than ignoring it.
        - Input roles: image 1 is the ground-truth raster crop; image 2 is the rendered preview of the current SVG.
        - Inline SVG source text is structural evidence for localization. Use the rendered preview as the primary visual comparison target.
        {history_rules_block(has_history, "region")}
        {strategy_clause}
        {json_output_contract(
            required_fields=("review", "repair_plan", "termination"),
            array_fields=(
                "prior_issue_assessment",
                "review.passed_items",
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
                "prior_issue_assessment[].status": ("resolved", "persists", "transformed", "uncertain"),
            },
        )}
        """
    ).strip()
    review_sections = compact_dict(
        {
            "checklist": review_context.get("checklist"),
            "object_index": review_context.get("object_index"),
            "bbox_constraint_feedback": review_context.get("bbox_constraint_feedback"),
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
                    "global_repairs": [{{"criterion": "brief criterion", "reason": "brief reason", "severity": "medium"}}],
                    "object_issues": [{{"object_id": "obj1", "criterion": "brief criterion", "reason": "brief reason", "severity": "medium"}}]
                  }},
                  "repair_plan": {{
                    "route": "region_repair",
                    "route_rationale": "brief reason",
                    "target_objects": [],
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
    strategy_clause = (
        f"Include strategy fields with concise label, rationale, and confidence. {STRATEGY_CONFIDENCE_RULE}"
        if strategy_enabled
        else "Set strategy_enabled to false and all strategy fields to null."
    )
    system_prompt = textwrap.dedent(
        f"""
        You are a combined object review and policy advisor for a raster-to-SVG workflow.
        Review one object SVG against its crop, then emit object review, object repair plan, and termination tendencies.
        Return JSON only.

        Rules:
        - route is always object_repair.
        - acceptance_tendency must be accept or reject.
        - stop_tendency must be continue or stop.
        - failed item reasons and all rationales must stay under 24 words.
        - {ISSUE_SEVERITY_RULES}
        - Use a compact review style: keep only the most decision-relevant unresolved object issues.
        - Ignore minor polish unless it affects semantics, identity, or readability.
        - Input roles: image 1 is the ground-truth object crop; image 2 is the rendered preview of the current SVG.
        - Inline SVG source text is structural evidence for localization. Use the rendered preview as the primary visual comparison target.
        {history_rules_block(has_history, "object")}
        {strategy_clause}
        {json_output_contract(
            required_fields=("review", "repair_plan", "termination"),
            array_fields=("prior_issue_assessment", "review.failed_items"),
            closed_value_fields={
                "repair_plan.route": ("object_repair",),
                "termination.acceptance_tendency": ("accept", "reject"),
                "termination.stop_tendency": ("continue", "stop"),
                "repair_plan.strategy_confidence": ("low", "medium", "high"),
                "review.failed_items[].severity": ("low", "medium", "high"),
                "prior_issue_assessment[].status": ("resolved", "persists", "transformed", "uncertain"),
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
                    "failed_items": [{{"criterion": "brief criterion", "reason": "brief reason", "severity": "medium"}}]
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
    final_review_context: dict,
    memory_summary: dict | None,
    strategy_enabled: bool,
    svg_source_text: str | None = None,
    svg_file_name: str | None = None,
) -> tuple[str, str]:
    has_history = memory_summary is not None or final_review_context.get("previous_decision_delta") is not None
    history_shape = history_example_block(has_history, "fusion")("")
    strategy_clause = (
        f"Include strategy fields with concise label, rationale, and confidence. {STRATEGY_CONFIDENCE_RULE}"
        if strategy_enabled
        else "Set strategy_enabled to false and all strategy fields to null."
    )
    system_prompt = textwrap.dedent(
        f"""
        You are a combined fusion review and policy advisor for a raster-to-SVG workflow.
        Review the merged SVG against the source image, then emit fusion review, repair plan, and termination tendencies.
        Return JSON only.

        Rules:
        - route is always fusion_repair.
        - acceptance_tendency must be accept or reject.
        - stop_tendency must be continue or stop.
        - review issue descriptions and all rationales must stay under 24 words.
        {FINAL_REVIEW_ISSUE_RULES}
        - Use a compact review style: capture the main cross-region and merge-relevant problems, not every small stylistic variance.
        - Prefer fewer, higher-signal issues over exhaustive lists.
        - Recommend stopping only when residual issues are low-value or unlikely to improve.
        - Input roles: image 1 is the ground-truth source image; image 2 is the rendered preview of the final SVG.
        - Inline SVG source text is structural evidence for localization. Use the rendered preview as the primary visual comparison target.
        {history_rules_block(has_history, "fusion")}
        {strategy_clause}
        {json_output_contract(
            required_fields=("review", "repair_plan", "termination"),
            array_fields=("prior_issue_assessment", "review.known_limitations"),
            closed_value_fields={
                "repair_plan.route": ("fusion_repair",),
                "termination.acceptance_tendency": ("accept", "reject"),
                "termination.stop_tendency": ("continue", "stop"),
                "repair_plan.strategy_confidence": ("low", "medium", "high"),
                "prior_issue_assessment[].status": ("resolved", "persists", "transformed", "uncertain"),
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
                    "route": "fusion_repair",
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
