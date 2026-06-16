"""Prompt builders for post-conversion manual SVG adjustment."""

from __future__ import annotations

import json
import textwrap

from deepagents_template.utils.prompting import (
    inline_text_file_section,
    join_sections,
    json_output_contract,
    json_section,
    section,
    svg_output_contract,
)


def build_manual_adjustment_pre_edit_prompts(
    *,
    target_summary: dict,
    user_introduction: str,
    current_svg_fragment: str,
    svg_file_name: str = "current_fragment.svg",
) -> tuple[str, str]:
    system_prompt = textwrap.dedent(
        f"""
        You are a post-conversion SVG local-edit analyst.
        Analyze the user's goal and the provided inline local SVG fragment before any edit happens.
        Return JSON only.

        Rules:
        - Focus on the selected local target only.
        - desired_outcomes describe the final state to achieve.
        - constraints describe what must not be broken or changed.
        - review_checks describe what to inspect after editing.
        - baseline_issues describe what is currently missing or wrong.
        - edit_strategy should prefer the smallest stable replacement scope.
        - rewrite_policy should prefer patch-like local updates unless a rewrite is truly necessary.
        {json_output_contract(
            required_fields=("goal_summary", "desired_outcomes", "constraints", "review_checks", "baseline_issues", "edit_strategy", "rewrite_policy"),
            array_fields=("desired_outcomes", "constraints", "review_checks", "baseline_issues"),
            closed_value_fields={
                "edit_strategy": ("object", "object_collection", "subtree", "region", "bbox_fragment"),
                "rewrite_policy": ("patch_preferred", "rewrite_allowed", "rewrite_required"),
            },
        )}
        """
    ).strip()
    user_prompt = join_sections(
        section(
            "Task framing",
            "Analyze the current local SVG fragment and infer a stable local-edit plan before editing.",
        ),
        json_section("Target summary", target_summary),
        section("User introduction / goal", user_introduction),
        inline_text_file_section(
            "Current local SVG fragment",
            file_name=svg_file_name,
            content=current_svg_fragment,
            role="Authoritative current-state SVG fragment for the selected target.",
        ),
        section(
            "Return this JSON shape",
            textwrap.dedent(
                """
                {
                  "goal_summary": "brief goal summary",
                  "desired_outcomes": ["final target state"],
                  "constraints": ["hard boundary or preservation requirement"],
                  "review_checks": ["post-edit check item"],
                  "baseline_issues": [
                    {
                      "criterion": "what is not yet satisfied",
                      "reason": "why the current fragment misses it"
                    }
                  ],
                  "edit_strategy": "object|object_collection|subtree|region|bbox_fragment",
                  "rewrite_policy": "patch_preferred|rewrite_allowed|rewrite_required"
                }
                """
            ).strip(),
        ),
    )
    return system_prompt, user_prompt


def build_manual_adjustment_agent_edit_prompts(
    *,
    target_summary: dict,
    desired_outcomes: list[str],
    constraints: list[str],
    user_introduction: str,
    review_checks: list[str],
    edit_strategy: str,
    rewrite_policy: str,
    current_svg_fragment: str,
    svg_file_name: str = "current_fragment.svg",
) -> tuple[str, str]:
    system_prompt = textwrap.dedent(
        f"""
        You are a post-conversion SVG adjustment worker for agent mode.
        Edit only the provided inline local SVG fragment for the selected target.
        Return JSON only.

        Rules:
        - Follow the target scope exactly.
        - Stay within the selected target. Do not introduce unrelated elements.
        - Preserve stable IDs and grouping whenever possible.
        - Prefer minimal, modular edits when rewrite_policy is patch_preferred.
        - Use a larger rewrite only when it is necessary to satisfy the goal cleanly.
        - Return only the adjusted fragment, not an outer <svg>.
        {json_output_contract(
            required_fields=("svg_fragment", "edit_operation", "target_ids", "preserved_ids", "new_ids", "rewrite_used", "change_summary", "remaining_limitations"),
            array_fields=("target_ids", "preserved_ids", "new_ids", "change_summary", "remaining_limitations"),
            closed_value_fields={
                "edit_operation": ("replace_object", "replace_object_collection", "replace_subtree", "replace_region", "replace_bbox_fragment"),
            },
        )}
        {svg_output_contract(field_name="svg_fragment", mode="fragment")}
        """
    ).strip()
    user_prompt = join_sections(
        section(
            "Task framing",
            "Edit only the selected local SVG fragment. Read the inline SVG source directly and return the updated fragment only.",
        ),
        json_section("Target summary", target_summary),
        section("User introduction / goal", user_introduction),
        json_section("Desired outcomes", desired_outcomes),
        json_section("Constraints", constraints),
        json_section("Review checks", review_checks),
        section("Edit strategy", edit_strategy),
        section("Rewrite policy", rewrite_policy),
        inline_text_file_section(
            "Current local SVG fragment to edit",
            file_name=svg_file_name,
            content=current_svg_fragment,
            role="Authoritative current-state SVG fragment to update.",
        ),
        section(
            "Return this JSON shape",
            textwrap.dedent(
                """
                {
                  "svg_fragment": "<g ...>...</g>",
                  "edit_operation": "replace_object|replace_object_collection|replace_subtree|replace_region|replace_bbox_fragment",
                  "target_ids": ["declared edited ids"],
                  "preserved_ids": ["ids intentionally preserved"],
                  "new_ids": ["ids intentionally introduced"],
                  "rewrite_used": false,
                  "change_summary": ["brief human-readable result summary"],
                  "remaining_limitations": ["optional limitation"]
                }
                """
            ).strip(),
        ),
    )
    return system_prompt, user_prompt


def build_manual_adjustment_worker_mode_prompts(
    *,
    target_summary: dict,
    user_introduction: str,
    current_svg_fragment: str,
    svg_file_name: str = "current_fragment.svg",
) -> tuple[str, str]:
    system_prompt = textwrap.dedent(
        f"""
        You are a post-conversion SVG local-edit worker for worker mode.
        In a single pass, first analyze the selected local target and then produce the updated SVG fragment.
        Return JSON only.

        Rules:
        - Stage 1: infer desired_outcomes, constraints, review_checks, baseline_issues, edit_strategy, and rewrite_policy from the goal and the inline SVG fragment.
        - Stage 2: edit only the provided local SVG fragment according to that inferred plan.
        - Stay within the selected target. Do not introduce unrelated elements.
        - Preserve stable IDs and grouping whenever possible.
        - Prefer minimal, modular edits unless rewrite is clearly necessary.
        - Return only the adjusted fragment, not an outer <svg>.
        {json_output_contract(
            required_fields=("goal_summary", "desired_outcomes", "constraints", "review_checks", "baseline_issues", "edit_strategy", "rewrite_policy", "svg_fragment", "edit_operation", "target_ids", "preserved_ids", "new_ids", "rewrite_used", "change_summary", "remaining_limitations"),
            array_fields=("desired_outcomes", "constraints", "review_checks", "baseline_issues", "target_ids", "preserved_ids", "new_ids", "change_summary", "remaining_limitations"),
            closed_value_fields={
                "edit_strategy": ("object", "object_collection", "subtree", "region", "bbox_fragment"),
                "rewrite_policy": ("patch_preferred", "rewrite_allowed", "rewrite_required"),
                "edit_operation": ("replace_object", "replace_object_collection", "replace_subtree", "replace_region", "replace_bbox_fragment"),
            },
        )}
        {svg_output_contract(field_name="svg_fragment", mode="fragment")}
        """
    ).strip()
    user_prompt = join_sections(
        section(
            "Task framing",
            "First analyze the local target, then update only the provided inline SVG fragment in one pass.",
        ),
        json_section("Target summary", target_summary),
        section("User introduction / goal", user_introduction),
        inline_text_file_section(
            "Current local SVG fragment to analyze and edit",
            file_name=svg_file_name,
            content=current_svg_fragment,
            role="Authoritative current-state SVG fragment for this single-pass adjustment.",
        ),
        section(
            "Return this JSON shape",
            textwrap.dedent(
                """
                {
                  "goal_summary": "brief goal summary",
                  "desired_outcomes": ["final target state"],
                  "constraints": ["hard boundary or preservation requirement"],
                  "review_checks": ["post-edit check item"],
                  "baseline_issues": [
                    {
                      "criterion": "what is not yet satisfied",
                      "reason": "why the current fragment misses it"
                    }
                  ],
                  "edit_strategy": "object|object_collection|subtree|region|bbox_fragment",
                  "rewrite_policy": "patch_preferred|rewrite_allowed|rewrite_required",
                  "svg_fragment": "<g ...>...</g>",
                  "edit_operation": "replace_object|replace_object_collection|replace_subtree|replace_region|replace_bbox_fragment",
                  "target_ids": ["declared edited ids"],
                  "preserved_ids": ["ids intentionally preserved"],
                  "new_ids": ["ids intentionally introduced"],
                  "rewrite_used": false,
                  "change_summary": ["brief human-readable result summary"],
                  "remaining_limitations": ["optional limitation"]
                }
                """
            ).strip(),
        ),
    )
    return system_prompt, user_prompt


def build_manual_adjustment_review_prompts(
    *,
    target_summary: dict,
    desired_outcomes: list[str],
    constraints: list[str],
    review_checks: list[str],
    adjusted_fragment: str,
    svg_file_name: str = "adjusted_fragment.svg",
) -> tuple[str, str]:
    system_prompt = textwrap.dedent(
        f"""
        You are a post-conversion SVG adjustment reviewer.
        Judge whether the provided inline local SVG fragment satisfies the intended local goal.
        Return JSON only.

        Rules:
        - Review against desired outcomes, constraints, and review checks.
        - remaining_issues should describe unsatisfied criteria or regressions, not fixes.
        - regression_detected should be true when the new fragment is worse than the baseline on any constraint.
        {json_output_contract(
            required_fields=("passed", "regression_detected", "remaining_issues", "summary"),
            array_fields=("remaining_issues",),
        )}
        """
    ).strip()
    user_prompt = join_sections(
        section(
            "Task framing",
            "Review the candidate local SVG fragment against the desired outcomes and constraints.",
        ),
        json_section("Target summary", target_summary),
        json_section("Desired outcomes", desired_outcomes),
        json_section("Constraints", constraints),
        json_section("Review checks", review_checks),
        inline_text_file_section(
            "Adjusted local SVG fragment to review",
            file_name=svg_file_name,
            content=adjusted_fragment,
            role="Authoritative candidate SVG fragment for this review pass.",
        ),
        section(
            "Return this JSON shape",
            textwrap.dedent(
                """
                {
                  "passed": true,
                  "regression_detected": false,
                  "remaining_issues": [
                    {
                      "criterion": "goal not fully met",
                      "reason": "brief issue description"
                    }
                  ],
                  "summary": "brief review summary"
                }
                """
            ).strip(),
        ),
    )
    return system_prompt, user_prompt
