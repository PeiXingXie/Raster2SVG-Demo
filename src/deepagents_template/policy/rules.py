"""Explicit hard rules that constrain model-assisted supervisor policies."""

from __future__ import annotations

from typing import Any

from deepagents_template.checklist import final_review_spatial_logical_issues, fusion_review_issue_id
from deepagents_template.utils.context_payloads import check_item_budget, check_word_budget
from deepagents_template.schemas import (
    BboxAdjustmentResult,
    BboxCombinedPolicyModelResult,
    BboxPolicyDecision,
    BboxSupervisorMemory,
    FusionCombinedPolicyModelResult,
    FusionPolicyDecision,
    FusionSupervisorMemory,
    FinalReviewResult,
    IssueRef,
    ManualAdjustmentReview,
    ObjectCombinedPolicyModelResult,
    ObjectPolicyDecision,
    ObjectReviewResult,
    ObjectRepairSupervisorMemory,
    RepairAcceptanceDecision,
    RegionCombinedPolicyModelResult,
    RegionPolicyDecision,
    RegionReviewResult,
    RegionSupervisorMemory,
    StopDecision,
)


def _rule(
    rule_id: str,
    *,
    changed: bool,
    reason: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "changed": changed,
        "reason": reason,
        "before": before,
        "after": after,
    }


def _issue_ref(issue_id: str, label: str) -> dict[str, str]:
    return IssueRef(
        issue_id=issue_id,
        label=_truncate_words(label, max_words=10, max_chars=80),
    ).model_dump(mode="json")


def _issue_refs(items: list[SupervisorIssueMemory], *, max_items: int = 2) -> list[dict[str, str]]:
    return [
        _issue_ref(
            item.issue_id,
            " ".join(part for part in [item.target_id, item.criterion, item.reason] if part),
        )
        for item in items[-max_items:]
    ]


def build_region_memory_summary(memory: RegionSupervisorMemory) -> dict[str, Any]:
    return {
        "last_iteration": memory.iteration,
        "recent_strategies": [
            *memory.attempted_region_strategies[-1:],
            *memory.attempted_object_strategies[-1:],
        ],
        "recent_route_notes": [item.action for item in memory.review_route_history[-2:]],
        "stop_reason": memory.stop_reason,
    }


def build_fusion_memory_summary(memory: FusionSupervisorMemory) -> dict[str, Any]:
    return {
        "last_iteration": memory.iteration,
        "recent_strategies": memory.attempted_merge_strategies[-2:],
        "stable_regions": memory.stable_regions[-2:],
        "unstable_boundaries": memory.unstable_boundaries[-2:],
        "stop_reason": memory.stop_reason,
    }


def build_object_memory_summary(memory: ObjectRepairSupervisorMemory, *, object_id: str) -> dict[str, Any]:
    return {
        "region_id": memory.region_id,
        "object_id": object_id,
        "attempts": memory.object_attempts.get(object_id, 0),
        "last_failure": memory.object_last_failure.get(object_id),
        "recent_strategies": [item.action for item in memory.routing_notes[-2:]],
        "stop_reason": memory.stop_reason,
    }


def build_bbox_memory_summary(memory: BboxSupervisorMemory) -> dict[str, Any]:
    return {
        "scope": memory.scope,
        "scope_key": memory.scope_key,
        "last_iteration": memory.iteration,
        "last_adjustment_type": memory.attempted_adjustment_types[-1] if memory.attempted_adjustment_types else None,
        "newly_resolved": [],
        "still_open": _issue_refs(memory.issue_history, max_items=4),
        "recent_policy_notes": [item.rationale for item in memory.decision_notes[-2:]],
    }


def _truncate_words(text: str | None, *, max_words: int = 24, max_chars: int = 160) -> str:
    compact = " ".join(str(text or "").strip().split())
    if not compact:
        return ""
    parts = compact.split()
    return " ".join(parts[:max_words])[:max_chars].strip()


REGION_REVIEW_PASSED_ITEMS_SOFT_LIMIT = 8
REGION_REVIEW_ISSUES_SOFT_LIMIT = 8
REGION_REVIEW_CRITERION_WORD_LIMIT = 12
REGION_REVIEW_REASON_WORD_LIMIT = 24
REGION_REVIEW_PASSED_ITEM_WORD_LIMIT = 8
FINAL_REVIEW_ISSUES_SOFT_LIMIT = 8
FINAL_REVIEW_DESCRIPTION_WORD_LIMIT = 24
FINAL_REVIEW_LIMITATION_WORD_LIMIT = 16
FINAL_REVIEW_LIMITATIONS_SOFT_LIMIT = 6
OBJECT_REVIEW_FAILED_ITEMS_SOFT_LIMIT = 6


def _clean_region_review(review: RegionReviewResult) -> RegionReviewResult:
    check_item_budget(
        review.passed_items,
        max_items=REGION_REVIEW_PASSED_ITEMS_SOFT_LIMIT,
        builder="clean_region_review",
        field="passed_items",
        scope="region",
        target_id=review.region_id,
    )
    check_item_budget(
        review.global_repairs,
        max_items=REGION_REVIEW_ISSUES_SOFT_LIMIT,
        builder="clean_region_review",
        field="global_repairs",
        scope="region",
        target_id=review.region_id,
    )
    check_item_budget(
        review.object_issues,
        max_items=REGION_REVIEW_ISSUES_SOFT_LIMIT,
        builder="clean_region_review",
        field="object_issues",
        scope="region",
        target_id=review.region_id,
    )
    for index, item in enumerate(review.passed_items):
        check_word_budget(
            item,
            max_words=REGION_REVIEW_PASSED_ITEM_WORD_LIMIT,
            max_chars=64,
            builder="clean_region_review",
            field=f"passed_items[{index}]",
            scope="region",
            target_id=review.region_id,
        )
    for index, issue in enumerate(review.global_repairs):
        check_word_budget(
            issue.criterion,
            max_words=REGION_REVIEW_CRITERION_WORD_LIMIT,
            max_chars=72,
            builder="clean_region_review",
            field=f"global_repairs[{index}].criterion",
            scope="region",
            target_id=review.region_id,
        )
        check_word_budget(
            issue.reason,
            max_words=REGION_REVIEW_REASON_WORD_LIMIT,
            max_chars=160,
            builder="clean_region_review",
            field=f"global_repairs[{index}].reason",
            scope="region",
            target_id=review.region_id,
        )
    for index, issue in enumerate(review.object_issues):
        check_word_budget(
            issue.criterion,
            max_words=REGION_REVIEW_CRITERION_WORD_LIMIT,
            max_chars=72,
            builder="clean_region_review",
            field=f"object_issues[{index}].criterion",
            scope="region",
            target_id=review.region_id,
        )
        check_word_budget(
            issue.reason,
            max_words=REGION_REVIEW_REASON_WORD_LIMIT,
            max_chars=160,
            builder="clean_region_review",
            field=f"object_issues[{index}].reason",
            scope="region",
            target_id=review.region_id,
        )
    return review


def _clean_object_review(review: ObjectReviewResult) -> ObjectReviewResult:
    check_item_budget(
        review.failed_items,
        max_items=OBJECT_REVIEW_FAILED_ITEMS_SOFT_LIMIT,
        builder="clean_object_review",
        field="failed_items",
        scope="object",
        target_id=review.object_id,
    )
    for index, item in enumerate(review.failed_items):
        check_word_budget(
            item.criterion,
            max_words=REGION_REVIEW_CRITERION_WORD_LIMIT,
            max_chars=72,
            builder="clean_object_review",
            field=f"failed_items[{index}].criterion",
            scope="object",
            target_id=review.object_id,
        )
        check_word_budget(
            item.reason,
            max_words=REGION_REVIEW_REASON_WORD_LIMIT,
            max_chars=160,
            builder="clean_object_review",
            field=f"failed_items[{index}].reason",
            scope="object",
            target_id=review.object_id,
        )
    return review


def _clean_final_review(review: dict[str, Any]) -> dict[str, Any]:
    for section_name in ("spatial_relation_issues", "logical_relation_issues", "visual_quality_issues"):
        section = dict(review.get(section_name) or {})
        for key, issues in section.items():
            check_item_budget(
                issues,
                max_items=FINAL_REVIEW_ISSUES_SOFT_LIMIT,
                builder="clean_final_review",
                field=f"{section_name}.{key}",
                scope="fusion",
                target_id="global",
            )
            for index, issue in enumerate(issues):
                check_word_budget(
                    issue.get("criterion"),
                    max_words=8,
                    max_chars=48,
                    builder="clean_final_review",
                    field=f"{section_name}.{key}[{index}].criterion",
                    scope="fusion",
                    target_id="global",
                )
                check_word_budget(
                    issue.get("description"),
                    max_words=FINAL_REVIEW_DESCRIPTION_WORD_LIMIT,
                    max_chars=160,
                    builder="clean_final_review",
                    field=f"{section_name}.{key}[{index}].description",
                    scope="fusion",
                    target_id="global",
                )
    check_item_budget(
        review.get("known_limitations") or [],
        max_items=FINAL_REVIEW_LIMITATIONS_SOFT_LIMIT,
        builder="clean_final_review",
        field="known_limitations",
        scope="fusion",
        target_id="global",
    )
    for index, item in enumerate(review.get("known_limitations") or []):
        check_word_budget(
            item,
            max_words=FINAL_REVIEW_LIMITATION_WORD_LIMIT,
            max_chars=120,
            builder="clean_final_review",
            field=f"known_limitations[{index}]",
            scope="fusion",
            target_id="global",
        )
    return review


def default_region_combined_result(region_id: str, *, strategy_enabled: bool) -> RegionCombinedPolicyModelResult:
    return RegionCombinedPolicyModelResult.model_validate(
        {
            "prior_issue_assessment": [],
            "review": {"region_id": region_id, "passed_items": [], "global_repairs": [], "object_issues": []},
            "repair_plan": {
                "route": "region_repair",
                "route_rationale": "Fallback route from current region review context.",
                "target_objects": [],
                "strategy_enabled": strategy_enabled,
                "strategy_label": "repair_region_global_issues" if strategy_enabled else None,
                "strategy_rationale": "Fallback strategy from unresolved region issues." if strategy_enabled else None,
                "strategy_confidence": "medium" if strategy_enabled else None,
            },
            "termination": {
                "acceptance_tendency": "reject",
                "acceptance_rationale": "Fallback keeps refinement active until rules accept the result.",
                "stop_tendency": "continue",
                "stop_rationale": "Fallback continues unless rules detect a safe stop condition.",
            },
        }
    )


def default_object_combined_result(object_id: str, *, strategy_enabled: bool) -> ObjectCombinedPolicyModelResult:
    return ObjectCombinedPolicyModelResult.model_validate(
        {
            "prior_issue_assessment": [],
            "review": {"object_id": object_id, "failed_items": []},
            "repair_plan": {
                "route": "object_repair",
                "route_rationale": "Fallback object repair route.",
                "strategy_enabled": strategy_enabled,
                "strategy_label": "repair_object_failed_items" if strategy_enabled else None,
                "strategy_rationale": "Fallback object strategy from failed checks." if strategy_enabled else None,
                "strategy_confidence": "medium" if strategy_enabled else None,
            },
            "termination": {
                "acceptance_tendency": "reject",
                "acceptance_rationale": "Fallback keeps object refinement active until rules accept the result.",
                "stop_tendency": "continue",
                "stop_rationale": "Fallback continues unless rules detect a safe stop condition.",
            },
        }
    )


def default_fusion_combined_result(*, strategy_enabled: bool) -> FusionCombinedPolicyModelResult:
    return FusionCombinedPolicyModelResult.model_validate(
        {
            "prior_issue_assessment": [],
            "review": FinalReviewResult().model_dump(mode="json"),
            "repair_plan": {
                "route": "fusion_repair",
                "route_rationale": "Fallback fusion repair route.",
                "strategy_enabled": strategy_enabled,
                "strategy_label": "conservative_merge_repair" if strategy_enabled else None,
                "strategy_rationale": "Fallback fusion strategy from unresolved cross-region issues." if strategy_enabled else None,
                "strategy_confidence": "medium" if strategy_enabled else None,
            },
            "termination": {
                "acceptance_tendency": "reject",
                "acceptance_rationale": "Fallback keeps fusion refinement active until rules accept the result.",
                "stop_tendency": "continue",
                "stop_rationale": "Fallback continues unless rules detect a safe stop condition.",
            },
        }
    )


def default_bbox_combined_result(*, scope: str, region_id: str = "") -> BboxCombinedPolicyModelResult:
    return BboxCombinedPolicyModelResult.model_validate(
        {
            "scope": scope,
            "region_id": region_id,
            "candidate_review": {
                "overview": "",
                "issues": [],
                "needs_adjustment": False,
            },
            "termination": {
                "acceptance_tendency": "reject",
                "acceptance_rationale": "Fallback keeps bbox refinement active until rules accept or stop.",
                "stop_tendency": "continue",
                "stop_rationale": "Fallback continues unless rules allow acceptance or require stopping.",
            },
        }
    )


def _region_issue_ids(review: RegionReviewResult) -> set[str]:
    return {
        *{f"region:{issue.criterion}" for issue in review.global_repairs},
        *{f"object:{issue.object_id}:{issue.criterion}" for issue in review.object_issues},
    }


def _fusion_issue_ids(final_review: dict[str, Any]) -> set[str]:
    return {
        fusion_review_issue_id(issue, issue_kind=issue.get("issue_kind"))
        for issue in final_review_spatial_logical_issues(final_review)
    }


def _text_issue_severity(*parts: str | None) -> str:
    text = " ".join(part or "" for part in parts).lower()
    high_tokens = (
        "missing",
        "absent",
        "silhouette",
        "likeness",
        "generic",
        "over-simplified",
        "oversimplified",
        "emblem",
        "distinctive",
        "wrong text",
        "incorrect text",
        "unreadable",
        "overlap",
        "outside",
        "out of bounds",
        "cropped",
        "truncated",
        "disconnected",
        "broken",
        "duplicate",
        "misleading",
    )
    low_tokens = (
        "slight",
        "slightly",
        "minor",
        "small",
        "subtle",
        "tiny",
        "polish",
        "weight",
        "thickness",
        "stroke",
        "spacing",
        "kerning",
        "low-impact",
    )
    if any(token in text for token in high_tokens):
        return "high"
    if any(token in text for token in low_tokens):
        return "low"
    return "medium"


def _severity_score(level: str) -> int:
    return {"low": 1, "medium": 3, "high": 6}.get(level, 3)


def _explicit_issue_severity(value: str | None) -> str:
    return value if value in {"low", "medium", "high"} else "medium"


def _is_minor_residuals(severities: list[str]) -> bool:
    return bool(severities) and len(severities) <= 2 and all(level == "low" for level in severities)


def _can_accept_progressive_target_improvement(
    *,
    targeted_issues: list[dict[str, Any]],
    targeted_severities: list[str],
    review_needs_adjustment: bool,
    accept_tendency: str,
    stop_tendency: str,
) -> bool:
    if not targeted_issues or not review_needs_adjustment:
        return False
    if accept_tendency != "reject" or stop_tendency != "continue":
        return False
    if any(level == "high" for level in targeted_severities):
        if len(targeted_issues) > 2:
            return False
        return True
    return bool(targeted_severities) and all(level == "medium" for level in targeted_severities)


def _bbox_issue_entries(review: dict[str, Any]) -> list[dict[str, str]]:
    issues = review.get("issues") or []
    return [
        {
            "issue_id": str(item.get("canonical_issue_id") or f"{item.get('target_id', '')}:{item.get('issue_code') or item.get('criterion', '')}"),
            "severity": _bbox_issue_severity(item),
            "issue_code": str(item.get("issue_code") or ""),
        }
        for item in issues
        if item.get("target_id") and (item.get("issue_code") or item.get("criterion"))
    ]


def _bbox_issue_severity(item: dict[str, Any]) -> str:
    explicit = str(item.get("severity", "medium"))
    issue_code = str(item.get("issue_code") or "")
    if issue_code in {"target_not_contained", "target_clipped", "invalid_bbox"}:
        return "high" if explicit == "low" else explicit
    inferred = _text_issue_severity(str(item.get("criterion", "")), str(item.get("reason", "")))
    return inferred if _severity_score(inferred) > _severity_score(explicit) else explicit


def _has_hard_bbox_residual(review: dict[str, Any]) -> bool:
    return any(
        str(item.get("issue_code") or "") in {"target_not_contained", "target_clipped", "invalid_bbox"}
        for item in review.get("issues") or []
    )


def _bbox_target_split(
    review: dict[str, Any],
    *,
    target_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    issues = review.get("issues") or []
    targeted = [item for item in issues if str(item.get("target_id", "")) in target_ids]
    remaining = [item for item in issues if str(item.get("target_id", "")) not in target_ids]
    return targeted, remaining


def apply_bbox_combined_policy_rules(
    *,
    proposal: BboxAdjustmentResult,
    combined: BboxCombinedPolicyModelResult,
    memory: BboxSupervisorMemory,
    retry_exhausted: bool,
) -> tuple[BboxPolicyDecision, list[dict[str, Any]]]:
    rules: list[dict[str, Any]] = []
    review = combined.candidate_review.model_copy(
        update={
            "overview": _truncate_words(combined.candidate_review.overview, max_words=28, max_chars=180),
            "issues": [
                issue.model_copy(
                    update={
                        "criterion": _truncate_words(issue.criterion, max_words=12, max_chars=96),
                        "reason": _truncate_words(issue.reason, max_words=20, max_chars=140),
                    }
                )
                for issue in combined.candidate_review.issues[:8]
            ],
        }
    )

    accept_current = combined.termination.acceptance_tendency == "accept"
    continue_refinement = combined.termination.stop_tendency == "continue"
    review_payload = review.model_dump(mode="json")
    severities = [entry["severity"] for entry in _bbox_issue_entries(review_payload)]
    only_minor = _is_minor_residuals(severities)
    target_ids = {item for item in proposal.target_ids if item}
    targeted_issues, remaining_issues = _bbox_target_split(review_payload, target_ids=target_ids)
    targeted_severities = [_bbox_issue_severity(item) for item in targeted_issues]
    remaining_severities = [_bbox_issue_severity(item) for item in remaining_issues]
    targeted_stable = bool(target_ids) and (not targeted_issues or all(level == "low" for level in targeted_severities))
    targeted_progressive = bool(target_ids) and _can_accept_progressive_target_improvement(
        targeted_issues=targeted_issues,
        targeted_severities=targeted_severities,
        review_needs_adjustment=review.needs_adjustment,
        accept_tendency=combined.termination.acceptance_tendency,
        stop_tendency=combined.termination.stop_tendency,
    )
    remaining_major_elsewhere = any(level != "low" for level in remaining_severities)
    hard_bbox_residual = _has_hard_bbox_residual(review_payload)
    final_reason = ""
    if proposal.scope == "layout":
        current_region_count = len(getattr(memory, "region_ids", []) or [])
        candidate_region_count = len(proposal.adjusted_regions or [])
        layout_repartition = proposal.adjustment_type in {
            "split_independent_bands",
            "split_independent_panels",
            "repartition_overcoarse_layout",
        }
        if layout_repartition and candidate_region_count > 0:
            if candidate_region_count > max(current_region_count + 3, 4):
                accept_current = False
                continue_refinement = False if retry_exhausted else continue_refinement
                rules.append(
                    _rule(
                        "bbox-combined.reject-layout-overfragmentation",
                        changed=True,
                        reason="Reject layout repartition proposals that grow region count too aggressively.",
                    )
                )
            elif not review.issues or only_minor:
                accept_current = True
                continue_refinement = False
                final_reason = "Accepted conservative layout repartition that resolves major coarse-region issues."
                rules.append(
                    _rule(
                        "bbox-combined.accept-conservative-layout-repartition",
                        changed=True,
                        reason="Accept conservative region repartition when candidate review shows the coarse-layout issue is resolved.",
                    )
                )

    if not review.issues or not review.needs_adjustment:
        accept_current = True
        continue_refinement = False
        rules.append(_rule("bbox-combined.clean-review-terminal", changed=True, reason="Accept when candidate review has no meaningful remaining bbox issues."))
    elif only_minor and not hard_bbox_residual:
        accept_current = True
        continue_refinement = False
        rules.append(_rule("bbox-combined.accept-minor-residuals", changed=True, reason="Allow minor low-severity bbox residuals to pass."))
    elif retry_exhausted:
        continue_refinement = False
        rules.append(_rule("bbox-combined.stop-when-retry-exhausted", changed=True, reason="Stop bbox refinement when retry capacity is exhausted."))
    else:
        accept_current = False

    if targeted_stable and remaining_major_elsewhere and not retry_exhausted:
        accept_current = True
        continue_refinement = True
        final_reason = "Accepted stable targeted bbox improvements; continue refining other objects with remaining major issues."
        rules.append(
            _rule(
                "bbox-combined.accept-stable-targeted-improvements",
                changed=True,
                reason="Persist improved target boxes even when other objects still need bbox refinement.",
                before={"accept_current_result": False, "continue_refinement": False},
                after={"accept_current_result": True, "continue_refinement": True},
            )
        )
    elif targeted_progressive and not retry_exhausted:
        accept_current = True
        continue_refinement = True
        final_reason = "Accepted the improved target bbox for progressive refinement; continue later cleanup from the better state."
        rules.append(
            _rule(
                "bbox-combined.accept-progressive-targeted-improvement",
                changed=True,
                reason="Persist materially improved target boxes even when the same target still has light-to-moderate residual cleanup left.",
                before={"accept_current_result": False, "continue_refinement": False},
                after={"accept_current_result": True, "continue_refinement": True},
            )
        )

    if not proposal.needs_adjustment:
        accept_current = True
        continue_refinement = False
        rules.append(_rule("bbox-combined.no-proposal-no-refinement", changed=True, reason="Stop when the proposal worker found no worthwhile bbox adjustment."))

    if combined.termination.stop_tendency == "stop" and not accept_current and not retry_exhausted and review.issues and not only_minor:
        continue_refinement = False
        rules.append(_rule("bbox-combined.honor-stop-tendency", changed=False, reason="Honor model stop tendency when major issues seem unlikely to improve."))

    decision = BboxPolicyDecision(
        review=review,
        accept_current_result=accept_current,
        continue_refinement=continue_refinement,
        final_reason=_truncate_words(
            final_reason or (combined.termination.acceptance_rationale if accept_current else combined.termination.stop_rationale),
            max_words=24,
            max_chars=160,
        ),
        applied_rules=[item["rule_id"] for item in rules if item.get("changed")],
    )
    return decision, rules


def _region_issue_entries(review: RegionReviewResult) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for issue in review.global_repairs:
        entries.append(
            {
                "issue_id": f"region:{review.region_id}:{issue.criterion}",
                "severity": _explicit_issue_severity(getattr(issue, "severity", None)),
            }
        )
    for issue in review.object_issues:
        entries.append(
            {
                "issue_id": f"object:{review.region_id}:{issue.object_id}:{issue.criterion}",
                "severity": _explicit_issue_severity(getattr(issue, "severity", None)),
            }
        )
    return entries


def _object_issue_entries(review: ObjectReviewResult) -> list[dict[str, str]]:
    return [
        {
            "issue_id": f"object:{review.object_id}:{item.criterion}",
            "severity": _explicit_issue_severity(getattr(item, "severity", None)),
        }
        for item in review.failed_items
    ]


def _fusion_issue_entries(final_review: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "issue_id": f"fusion:{fusion_review_issue_id(issue, issue_kind=issue.get('issue_kind'))}",
            "severity": str(issue.get("severity", "medium")),
        }
        for issue in final_review_spatial_logical_issues(final_review)
    ]


def _assessment_consistency_rules(
    *,
    assessments: list[Any],
    current_issue_ids: set[str],
    review_scope: str,
) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for assessment in assessments:
        issue_id = str(getattr(assessment, "issue_id", "") or "").strip()
        status = str(getattr(assessment, "status", "") or "").strip()
        if not issue_id or not status:
            continue
        if status == "resolved" and issue_id in current_issue_ids:
            rules.append(
                _rule(
                    f"{review_scope}.assessment-resolved-conflict",
                    changed=False,
                    reason="Assessment marked an issue resolved but the same issue_id still appears in the current review.",
                    before={"issue_id": issue_id, "status": status},
                    after={"current_issue_ids": sorted(current_issue_ids)},
                )
            )
        replacement_refs = getattr(assessment, "replacement_issue_refs", []) or []
        if status == "transformed" and replacement_refs:
            replacement_ids = set()
            for item in replacement_refs:
                if isinstance(item, dict):
                    candidate = str(item.get("issue_id") or "").strip()
                else:
                    candidate = str(getattr(item, "issue_id", "") or "").strip()
                if candidate:
                    replacement_ids.add(candidate)
            if replacement_ids and replacement_ids.isdisjoint(current_issue_ids):
                rules.append(
                    _rule(
                        f"{review_scope}.assessment-transformed-missing-replacement",
                        changed=False,
                        reason="Assessment declared a transformed issue but none of its replacement refs appear in the current review.",
                        before={"issue_id": issue_id, "replacement_issue_ids": sorted(replacement_ids)},
                        after={"current_issue_ids": sorted(current_issue_ids)},
                    )
                )
    return rules


def apply_region_combined_policy_rules(
    *,
    combined: RegionCombinedPolicyModelResult,
    memory: RegionSupervisorMemory,
    valid_object_ids: set[str],
    can_object_repair: bool,
    region_retry_exhausted: bool,
    strategy_enabled: bool,
    use_memory: bool = True,
) -> tuple[RegionPolicyDecision, list[dict[str, Any]]]:
    review = _clean_region_review(combined.review)
    rules: list[dict[str, Any]] = []
    current_issue_ids = {entry["issue_id"] for entry in _region_issue_entries(review)}
    rules.extend(
        _assessment_consistency_rules(
            assessments=combined.prior_issue_assessment,
            current_issue_ids=current_issue_ids,
            review_scope="region-combined",
        )
    )
    target_objects = [item for item in combined.repair_plan.target_objects if item in valid_object_ids]
    if target_objects != combined.repair_plan.target_objects:
        rules.append(_rule("region-combined.filter-target-objects", changed=True, reason="Drop invalid object targets."))
    if review.object_issues and not target_objects:
        target_objects = [issue.object_id for issue in review.object_issues if issue.object_id in valid_object_ids]
        if target_objects:
            rules.append(_rule("region-combined.fill-target-objects", changed=True, reason="Fill object targets from unresolved object issues."))

    route = combined.repair_plan.route
    if route == "object_repair" and (not can_object_repair or not target_objects):
        route = "region_repair"
        rules.append(_rule("region-combined.guard-object-route", changed=True, reason="Fallback to region repair when object repair is unavailable or empty."))
    if route == "object_repair" and review.global_repairs:
        route = "region_repair"
        rules.append(_rule("region-combined.prioritize-global-repairs", changed=True, reason="Prefer region repair while whole-region issues remain unresolved."))
    if route == "region_repair" and not review.global_repairs and review.object_issues and can_object_repair and target_objects:
        route = "object_repair"
        rules.append(_rule("region-combined.localize-to-object-route", changed=True, reason="Use object repair when only localized object issues remain."))

    severities = [entry["severity"] for entry in _region_issue_entries(review)]
    only_minor = _is_minor_residuals(severities)
    accept_current = combined.termination.acceptance_tendency == "accept"
    continue_refinement = combined.termination.stop_tendency == "continue"
    if not review.global_repairs and not review.object_issues:
        accept_current = True
        continue_refinement = False
        rules.append(_rule("region-combined.clean-review-terminal", changed=True, reason="Stop when no unresolved region or object issues remain."))
    elif only_minor:
        accept_current = True
        continue_refinement = False
        rules.append(_rule("region-combined.accept-minor-residuals", changed=True, reason="Allow minor low-severity residual issues to pass."))
    elif region_retry_exhausted:
        continue_refinement = False
        rules.append(_rule("region-combined.stop-when-retry-exhausted", changed=True, reason="Stop when region retry budget is exhausted."))
    else:
        accept_current = False

    final_strategy_label = None
    final_strategy_rationale = None
    if strategy_enabled and combined.repair_plan.strategy_enabled:
        label = (combined.repair_plan.strategy_label or "").strip()
        if label:
            repeated = use_memory and any(label in item for item in memory.attempted_region_strategies[-3:])
            if repeated and combined.repair_plan.strategy_confidence == "low":
                rules.append(_rule("region-combined.drop-low-confidence-repeated-strategy", changed=True, reason="Drop repeated low-confidence region strategies."))
            else:
                final_strategy_label = label
                final_strategy_rationale = _truncate_words(combined.repair_plan.strategy_rationale)

    decision = RegionPolicyDecision(
        prior_issue_assessment=list(combined.prior_issue_assessment),
        review=review,
        final_route=route,
        final_route_reason=_truncate_words(combined.repair_plan.route_rationale),
        final_target_objects=target_objects if route == "object_repair" else [],
        strategy_enabled=bool(strategy_enabled and final_strategy_label),
        final_strategy_label=final_strategy_label,
        final_strategy_rationale=final_strategy_rationale,
        accept_current_result=accept_current,
        continue_refinement=continue_refinement,
        final_reason=_truncate_words(
            combined.termination.stop_rationale if not continue_refinement else combined.termination.acceptance_rationale
        ),
        applied_rules=[item["rule_id"] for item in rules if item.get("changed")],
    )
    return decision, rules


def apply_object_combined_policy_rules(
    *,
    combined: ObjectCombinedPolicyModelResult,
    memory: ObjectRepairSupervisorMemory,
    retry_exhausted: bool,
    strategy_enabled: bool,
    use_memory: bool = True,
) -> tuple[ObjectPolicyDecision, list[dict[str, Any]]]:
    review = _clean_object_review(combined.review)
    rules: list[dict[str, Any]] = []
    current_issue_ids = {entry["issue_id"] for entry in _object_issue_entries(review)}
    rules.extend(
        _assessment_consistency_rules(
            assessments=combined.prior_issue_assessment,
            current_issue_ids=current_issue_ids,
            review_scope="object-combined",
        )
    )
    severities = [entry["severity"] for entry in _object_issue_entries(review)]
    only_minor = _is_minor_residuals(severities)
    accept_current = combined.termination.acceptance_tendency == "accept"
    continue_refinement = combined.termination.stop_tendency == "continue"
    if not review.failed_items:
        accept_current = True
        continue_refinement = False
        rules.append(_rule("object-combined.clean-review-terminal", changed=True, reason="Stop when object review has no failed items."))
    elif only_minor:
        accept_current = True
        continue_refinement = False
        rules.append(_rule("object-combined.accept-minor-residuals", changed=True, reason="Allow minor low-severity residual object issues to pass."))
    elif retry_exhausted:
        continue_refinement = False
        rules.append(_rule("object-combined.stop-when-retry-exhausted", changed=True, reason="Stop when object retry budget is exhausted."))
    else:
        accept_current = False

    final_strategy_label = None
    final_strategy_rationale = None
    if strategy_enabled and combined.repair_plan.strategy_enabled:
        label = (combined.repair_plan.strategy_label or "").strip()
        attempts = memory.object_attempts.get(review.object_id, 0) if use_memory else 0
        if label and not (attempts >= 1 and combined.repair_plan.strategy_confidence == "low"):
            final_strategy_label = label
            final_strategy_rationale = _truncate_words(combined.repair_plan.strategy_rationale)
        elif label:
            rules.append(_rule("object-combined.drop-low-confidence-repeat", changed=True, reason="Drop low-confidence object strategies after prior attempts."))

    decision = ObjectPolicyDecision(
        prior_issue_assessment=list(combined.prior_issue_assessment),
        review=review,
        final_route_reason=_truncate_words(combined.repair_plan.route_rationale),
        strategy_enabled=bool(strategy_enabled and final_strategy_label),
        final_strategy_label=final_strategy_label,
        final_strategy_rationale=final_strategy_rationale,
        accept_current_result=accept_current,
        continue_refinement=continue_refinement,
        final_reason=_truncate_words(
            combined.termination.stop_rationale if not continue_refinement else combined.termination.acceptance_rationale
        ),
        applied_rules=[item["rule_id"] for item in rules if item.get("changed")],
    )
    return decision, rules


def apply_fusion_combined_policy_rules(
    *,
    combined: FusionCombinedPolicyModelResult,
    memory: FusionSupervisorMemory,
    retry_exhausted: bool,
    strategy_enabled: bool,
    use_memory: bool = True,
) -> tuple[FusionPolicyDecision, list[dict[str, Any]]]:
    review_payload = _clean_final_review(combined.review.model_dump(mode="json"))
    review = FinalReviewResult.model_validate(review_payload)
    rules: list[dict[str, Any]] = []
    current_issue_ids = {entry["issue_id"] for entry in _fusion_issue_entries(review_payload)}
    rules.extend(
        _assessment_consistency_rules(
            assessments=combined.prior_issue_assessment,
            current_issue_ids=current_issue_ids,
            review_scope="fusion-combined",
        )
    )
    severities = [entry["severity"] for entry in _fusion_issue_entries(review_payload)]
    only_minor = _is_minor_residuals(severities)
    accept_current = combined.termination.acceptance_tendency == "accept"
    continue_refinement = combined.termination.stop_tendency == "continue"
    has_issues = bool(final_review_spatial_logical_issues(review_payload))
    if not has_issues:
        accept_current = True
        continue_refinement = False
        rules.append(_rule("fusion-combined.clean-review-terminal", changed=True, reason="Stop when no spatial/logical fusion issues remain."))
    elif only_minor:
        accept_current = True
        continue_refinement = False
        rules.append(_rule("fusion-combined.accept-minor-residuals", changed=True, reason="Allow minor low-severity residual fusion issues to pass."))
    elif retry_exhausted:
        continue_refinement = False
        rules.append(_rule("fusion-combined.stop-when-retry-exhausted", changed=True, reason="Stop when additional fusion repair is no longer allowed."))
    else:
        accept_current = False

    final_strategy_label = None
    final_strategy_rationale = None
    if strategy_enabled and combined.repair_plan.strategy_enabled:
        label = (combined.repair_plan.strategy_label or "").strip()
        repeated_low_confidence = use_memory and label in memory.attempted_merge_strategies[-2:] and combined.repair_plan.strategy_confidence == "low"
        if label and not repeated_low_confidence:
            final_strategy_label = label
            final_strategy_rationale = _truncate_words(combined.repair_plan.strategy_rationale)
        elif label:
            rules.append(_rule("fusion-combined.drop-low-confidence-repeat", changed=True, reason="Drop repeated low-confidence fusion strategies."))

    decision = FusionPolicyDecision(
        prior_issue_assessment=list(combined.prior_issue_assessment),
        review=review,
        final_route_reason=_truncate_words(combined.repair_plan.route_rationale),
        strategy_enabled=bool(strategy_enabled and final_strategy_label),
        final_strategy_label=final_strategy_label,
        final_strategy_rationale=final_strategy_rationale,
        accept_current_result=accept_current,
        continue_refinement=continue_refinement,
        final_reason=_truncate_words(
            combined.termination.stop_rationale if not continue_refinement else combined.termination.acceptance_rationale
        ),
        applied_rules=[item["rule_id"] for item in rules if item.get("changed")],
    )
    return decision, rules


def decide_region_repair_acceptance(
    *,
    before_review: RegionReviewResult,
    after_review: RegionReviewResult,
) -> tuple[RepairAcceptanceDecision, list[dict[str, Any]]]:
    rules: list[dict[str, Any]] = []
    before_entries = _region_issue_entries(before_review)
    after_entries = _region_issue_entries(after_review)
    before_ids = {entry["issue_id"] for entry in before_entries}
    after_ids = {entry["issue_id"] for entry in after_entries}
    before_score = sum(_severity_score(entry["severity"]) for entry in before_entries)
    after_score = sum(_severity_score(entry["severity"]) for entry in after_entries)
    after_severities = [entry["severity"] for entry in after_entries]
    resolved = sorted(before_ids - after_ids)
    new_issues = sorted(after_ids - before_ids)

    accept = True
    rationale = "Accept repair because it preserved or improved the region issue set."
    if _is_minor_residuals(after_severities) and after_score <= before_score:
        rationale = "Accept repair because only minor low-severity residual issues remain."
        rules.append(
            _rule(
                "region-repair-acceptance.tolerate-minor-residuals",
                changed=False,
                reason="Low-severity residual issues can be ignored when the overall severity budget improved or stayed flat.",
                before={"severity_score": before_score, "issue_ids": sorted(before_ids)},
                after={"severity_score": after_score, "issue_ids": sorted(after_ids)},
            )
        )
    elif after_score > before_score and not resolved:
        accept = False
        rationale = "Reject repair because it increased unresolved severity without resolving earlier issues."
        rules.append(
            _rule(
                "region-repair-acceptance.reject-regression",
                changed=True,
                reason="Reject region repairs that strictly worsen severity.",
                before={"severity_score": before_score, "issue_ids": sorted(before_ids)},
                after={"severity_score": after_score, "issue_ids": sorted(after_ids)},
            )
        )
    else:
        rules.append(
            _rule(
                "region-repair-acceptance.accept-non-regression",
                changed=False,
                reason="Accept region repairs that do not strictly worsen unresolved severity.",
                before={"severity_score": before_score, "issue_ids": sorted(before_ids)},
                after={"severity_score": after_score, "issue_ids": sorted(after_ids)},
            )
        )

    return (
        RepairAcceptanceDecision(
            accept_repair=accept,
            rationale=rationale,
            resolved_issue_ids=resolved,
            new_issue_ids=new_issues,
            confidence="high" if resolved or not new_issues else "medium",
        ),
        rules,
    )


def decide_fusion_repair_acceptance(
    *,
    before_review: dict[str, Any],
    after_review: dict[str, Any],
) -> tuple[RepairAcceptanceDecision, list[dict[str, Any]]]:
    rules: list[dict[str, Any]] = []
    before_entries = _fusion_issue_entries(before_review)
    after_entries = _fusion_issue_entries(after_review)
    before_ids = {entry["issue_id"] for entry in before_entries}
    after_ids = {entry["issue_id"] for entry in after_entries}
    before_score = sum(_severity_score(entry["severity"]) for entry in before_entries)
    after_score = sum(_severity_score(entry["severity"]) for entry in after_entries)
    after_severities = [entry["severity"] for entry in after_entries]
    resolved = sorted(before_ids - after_ids)
    new_issues = sorted(after_ids - before_ids)

    accept = True
    rationale = "Accept fusion repair because it preserved or improved cross-region issue coverage."
    if _is_minor_residuals(after_severities) and after_score <= before_score:
        rationale = "Accept fusion repair because only minor low-severity cross-region issues remain."
        rules.append(
            _rule(
                "fusion-repair-acceptance.tolerate-minor-residuals",
                changed=False,
                reason="Low-severity cross-region residuals can be ignored when overall severity improved or stayed flat.",
                before={"severity_score": before_score, "issue_ids": sorted(before_ids)},
                after={"severity_score": after_score, "issue_ids": sorted(after_ids)},
            )
        )
    elif after_score > before_score and not resolved:
        accept = False
        rationale = "Reject fusion repair because it increased unresolved cross-region severity without any offsetting resolution."
        rules.append(
            _rule(
                "fusion-repair-acceptance.reject-regression",
                changed=True,
                reason="Reject fusion repairs that strictly worsen cross-region severity.",
                before={"severity_score": before_score, "issue_ids": sorted(before_ids)},
                after={"severity_score": after_score, "issue_ids": sorted(after_ids)},
            )
        )
    else:
        rules.append(
            _rule(
                "fusion-repair-acceptance.accept-non-regression",
                changed=False,
                reason="Accept fusion repairs that do not strictly worsen cross-region severity.",
                before={"severity_score": before_score, "issue_ids": sorted(before_ids)},
                after={"severity_score": after_score, "issue_ids": sorted(after_ids)},
            )
        )

    return (
        RepairAcceptanceDecision(
            accept_repair=accept,
            rationale=rationale,
            resolved_issue_ids=resolved,
            new_issue_ids=new_issues,
            confidence="high" if resolved or not new_issues else "medium",
        ),
        rules,
    )


def decide_region_stop(
    *,
    unresolved_issue_ids: list[str],
    retry_summary: dict[str, Any],
) -> tuple[StopDecision, list[dict[str, Any]]]:
    rules: list[dict[str, Any]] = []
    if not unresolved_issue_ids:
        decision = StopDecision(outcome="accept", reason="review passed", confidence="high")
        rules.append(
            _rule(
                "region-stop.accept-clean-review",
                changed=False,
                reason="Accept the region once no unresolved issues remain.",
            )
        )
        return decision, rules

    severities = [_text_issue_severity(issue_id) for issue_id in unresolved_issue_ids]
    if _is_minor_residuals(severities):
        decision = StopDecision(
            outcome="accept",
            reason="accept with minor residual issues",
            confidence="medium",
        )
        rules.append(
            _rule(
                "region-stop.accept-minor-residuals",
                changed=False,
                reason="Allow completion when only a few low-severity residual issues remain.",
            )
        )
        return decision, rules

    exhausted = any(item.get("exhausted") for item in retry_summary.values())
    if exhausted:
        decision = StopDecision(
            outcome="stop",
            reason="retry exhausted with residual issues",
            confidence="high",
        )
        rules.append(
            _rule(
                "region-stop.stop-on-exhausted-retry",
                changed=False,
                reason="Stop the region refinement loop when retry capacity is exhausted and issues remain.",
            )
        )
        return decision, rules

    decision = StopDecision(
        outcome="continue",
        reason="residual issues remain after current refinement round",
        confidence="medium",
    )
    rules.append(
        _rule(
            "region-stop.continue-with-open-issues",
            changed=False,
            reason="Continue is the default when unresolved issues remain and retry capacity still exists.",
        )
    )
    return decision, rules


def decide_fusion_stop(*, remaining_issue_ids: list[str]) -> tuple[StopDecision, list[dict[str, Any]]]:
    rules: list[dict[str, Any]] = []
    if not remaining_issue_ids:
        decision = StopDecision(outcome="accept", reason="fusion review passed", confidence="high")
        rules.append(
            _rule(
                "fusion-stop.accept-clean-review",
                changed=False,
                reason="Accept the merged SVG when no cross-region issues remain.",
            )
        )
        return decision, rules

    severities = [_text_issue_severity(issue_id) for issue_id in remaining_issue_ids]
    if _is_minor_residuals(severities):
        decision = StopDecision(
            outcome="accept",
            reason="accept with minor residual cross-region issues",
            confidence="medium",
        )
        rules.append(
            _rule(
                "fusion-stop.accept-minor-residuals",
                changed=False,
                reason="Allow completion when only a few low-severity cross-region issues remain.",
            )
        )
        return decision, rules

    decision = StopDecision(
        outcome="stop",
        reason="fusion review completed with residual cross-region issues",
        confidence="medium",
    )
    rules.append(
        _rule(
            "fusion-stop.stop-with-residual-issues",
            changed=False,
            reason="Fusion stops after the conservative merge decision cycle when issues remain.",
        )
    )
    return decision, rules


def decide_object_repair_acceptance(
    *,
    before_review: ObjectReviewResult,
    after_review: ObjectReviewResult,
) -> tuple[RepairAcceptanceDecision, list[dict[str, Any]]]:
    rules: list[dict[str, Any]] = []
    before_entries = _object_issue_entries(before_review)
    after_entries = _object_issue_entries(after_review)
    before_ids = {entry["issue_id"] for entry in before_entries}
    after_ids = {entry["issue_id"] for entry in after_entries}
    before_score = sum(_severity_score(entry["severity"]) for entry in before_entries)
    after_score = sum(_severity_score(entry["severity"]) for entry in after_entries)
    after_severities = [entry["severity"] for entry in after_entries]
    resolved = sorted(before_ids - after_ids)
    new_issues = sorted(after_ids - before_ids)

    accept = True
    rationale = "Accept object repair because it preserved or improved the object issue set."
    if _is_minor_residuals(after_severities) and after_score <= before_score:
        rationale = "Accept object repair because only minor low-severity residual issues remain."
        rules.append(
            _rule(
                "object-repair-acceptance.tolerate-minor-residuals",
                changed=False,
                reason="Allow a small amount of low-severity object polish debt.",
                before={"severity_score": before_score, "issue_ids": sorted(before_ids)},
                after={"severity_score": after_score, "issue_ids": sorted(after_ids)},
            )
        )
    elif after_score > before_score and not resolved:
        accept = False
        rationale = "Reject object repair because it increased unresolved severity without resolving earlier issues."
        rules.append(
            _rule(
                "object-repair-acceptance.reject-regression",
                changed=True,
                reason="Reject object repairs that strictly worsen unresolved severity.",
                before={"severity_score": before_score, "issue_ids": sorted(before_ids)},
                after={"severity_score": after_score, "issue_ids": sorted(after_ids)},
            )
        )
    else:
        rules.append(
            _rule(
                "object-repair-acceptance.accept-non-regression",
                changed=False,
                reason="Accept object repairs that do not strictly worsen unresolved severity.",
                before={"severity_score": before_score, "issue_ids": sorted(before_ids)},
                after={"severity_score": after_score, "issue_ids": sorted(after_ids)},
            )
        )

    return (
        RepairAcceptanceDecision(
            accept_repair=accept,
            rationale=rationale,
            resolved_issue_ids=resolved,
            new_issue_ids=new_issues,
            confidence="high" if resolved or not new_issues else "medium",
        ),
        rules,
    )


def decide_object_stop(
    *,
    review: ObjectReviewResult,
    retry_state: dict[str, Any],
) -> tuple[StopDecision, list[dict[str, Any]]]:
    rules: list[dict[str, Any]] = []
    if not review.failed_items:
        decision = StopDecision(outcome="accept", reason="object review passed", confidence="high")
        rules.append(
            _rule(
                "object-stop.accept-clean-review",
                changed=False,
                reason="Accept the object once no failed checks remain.",
            )
        )
        return decision, rules

    severities = [entry["severity"] for entry in _object_issue_entries(review)]
    if _is_minor_residuals(severities):
        decision = StopDecision(
            outcome="accept",
            reason="accept object with minor residual issues",
            confidence="medium",
        )
        rules.append(
            _rule(
                "object-stop.accept-minor-residuals",
                changed=False,
                reason="Allow completion when only a few low-severity object issues remain.",
            )
        )
        return decision, rules

    if retry_state.get("exhausted"):
        decision = StopDecision(
            outcome="stop",
            reason="object retry exhausted with residual issues",
            confidence="high",
        )
        rules.append(
            _rule(
                "object-stop.stop-on-exhausted-retry",
                changed=False,
                reason="Stop object repair when retry capacity is exhausted.",
            )
        )
        return decision, rules

    decision = StopDecision(
        outcome="continue",
        reason="object residual issues remain",
        confidence="medium",
    )
    rules.append(
        _rule(
            "object-stop.continue-with-open-issues",
            changed=False,
            reason="Continue object repair while unresolved issues remain and retry capacity still exists.",
        )
    )
    return decision, rules


def _manual_issue_entries(review: ManualAdjustmentReview) -> list[dict[str, str]]:
    return [
        {
            "issue_id": item.criterion,
            "severity": _text_issue_severity(item.criterion, item.reason),
        }
        for item in review.remaining_issues
    ]


def decide_manual_repair_acceptance(
    *,
    before_review: ManualAdjustmentReview,
    after_review: ManualAdjustmentReview,
) -> tuple[RepairAcceptanceDecision, list[dict[str, Any]]]:
    rules: list[dict[str, Any]] = []
    before_entries = _manual_issue_entries(before_review)
    after_entries = _manual_issue_entries(after_review)
    before_ids = {entry["issue_id"] for entry in before_entries}
    after_ids = {entry["issue_id"] for entry in after_entries}
    before_score = sum(_severity_score(entry["severity"]) for entry in before_entries)
    after_score = sum(_severity_score(entry["severity"]) for entry in after_entries)
    after_severities = [entry["severity"] for entry in after_entries]
    resolved = sorted(before_ids - after_ids)
    new_issues = sorted(after_ids - before_ids)

    accept = True
    rationale = "Accept manual adjustment because it preserved or improved the requested target outcome."
    if after_review.passed:
        rules.append(
            _rule(
                "manual-repair-acceptance.accept-passed-review",
                changed=False,
                reason="Accept immediately when the manual review passes.",
                before={"severity_score": before_score, "issue_ids": sorted(before_ids)},
                after={"severity_score": after_score, "issue_ids": sorted(after_ids)},
            )
        )
    elif _is_minor_residuals(after_severities) and after_score <= before_score:
        rationale = "Accept manual adjustment because only minor low-severity residual issues remain."
        rules.append(
            _rule(
                "manual-repair-acceptance.tolerate-minor-residuals",
                changed=False,
                reason="Allow manual edits to finish when only small low-impact residual issues remain.",
                before={"severity_score": before_score, "issue_ids": sorted(before_ids)},
                after={"severity_score": after_score, "issue_ids": sorted(after_ids)},
            )
        )
    elif after_score > before_score and not resolved:
        accept = False
        rationale = "Reject manual adjustment because it increased unresolved severity without resolving earlier issues."
        rules.append(
            _rule(
                "manual-repair-acceptance.reject-regression",
                changed=True,
                reason="Reject regressive manual edits that strictly worsen the requested target quality.",
                before={"severity_score": before_score, "issue_ids": sorted(before_ids)},
                after={"severity_score": after_score, "issue_ids": sorted(after_ids)},
            )
        )
    else:
        rules.append(
            _rule(
                "manual-repair-acceptance.accept-non-regression",
                changed=False,
                reason="Accept manual edits that do not strictly worsen unresolved severity.",
                before={"severity_score": before_score, "issue_ids": sorted(before_ids)},
                after={"severity_score": after_score, "issue_ids": sorted(after_ids)},
            )
        )

    return (
        RepairAcceptanceDecision(
            accept_repair=accept,
            rationale=rationale,
            resolved_issue_ids=resolved,
            new_issue_ids=new_issues,
            confidence="high" if after_review.passed or resolved or not new_issues else "medium",
        ),
        rules,
    )


def decide_manual_stop(
    *,
    review: ManualAdjustmentReview,
    budget_used: int,
    budget_limit: int,
) -> tuple[StopDecision, list[dict[str, Any]]]:
    rules: list[dict[str, Any]] = []
    if review.passed or not review.remaining_issues:
        decision = StopDecision(outcome="accept", reason="manual review passed", confidence="high")
        rules.append(
            _rule(
                "manual-stop.accept-clean-review",
                changed=False,
                reason="Accept the manual adjustment once the review passes.",
            )
        )
        return decision, rules

    severities = [entry["severity"] for entry in _manual_issue_entries(review)]
    if _is_minor_residuals(severities):
        decision = StopDecision(
            outcome="accept",
            reason="accept manual adjustment with minor residual issues",
            confidence="medium",
        )
        rules.append(
            _rule(
                "manual-stop.accept-minor-residuals",
                changed=False,
                reason="Allow manual adjustments to finish when only low-severity residual issues remain.",
            )
        )
        return decision, rules

    if budget_used >= budget_limit:
        decision = StopDecision(
            outcome="stop",
            reason="manual adjustment budget exhausted with residual issues",
            confidence="high",
        )
        rules.append(
            _rule(
                "manual-stop.stop-on-budget",
                changed=False,
                reason="Stop the manual agent loop when the dedicated budget is exhausted.",
            )
        )
        return decision, rules

    decision = StopDecision(
        outcome="continue",
        reason="manual residual issues remain",
        confidence="medium",
    )
    rules.append(
        _rule(
            "manual-stop.continue-with-open-issues",
            changed=False,
            reason="Continue the manual agent loop while unresolved issues remain and budget still exists.",
        )
    )
    return decision, rules
