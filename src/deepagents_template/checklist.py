"""Overview: Checklist selection, budgeting, flattening, and issue aggregation helpers."""

from __future__ import annotations

CHECKLIST_STAGE_BUDGETS = {
    "recognition": {"common": 4, "region": 3, "total": 10},
    "generation_refine": {"common": 4, "region": 3, "total": 10},
    "fusion": {"common": 5, "region": 0, "total": 5},
    "total": 25,
}


def shorten_checklist_criterion(criterion: str, max_words: int = 15) -> str:
    words = criterion.strip().split()
    if len(words) <= max_words:
        return criterion.strip()
    shortened = " ".join(words[:max_words]).rstrip(".,;:")
    return f"{shortened}."


def compact_checklist_item(item: dict) -> dict:
    compact = {
        "item_id": item.get("item_id"),
        "scope": item.get("scope", "common"),
        "criterion": shorten_checklist_criterion(str(item.get("criterion", ""))),
    }
    if item.get("region_id"):
        compact["region_id"] = item["region_id"]
    return compact


def _stage_section(checklists: dict, stage: str) -> dict:
    return dict((checklists or {}).get(stage) or {})


def _compact_items(items: list[dict]) -> list[dict]:
    return [compact_checklist_item(item) for item in items if compact_checklist_item(item).get("criterion")]


def flatten_stage_checklist(checklists: dict, stage: str) -> list[dict]:
    section = _stage_section(checklists, stage)
    flattened = _compact_items(section.get("common") or [])
    for region_id in sorted((section.get("regions") or {}).keys()):
        flattened.extend(_compact_items((section.get("regions") or {}).get(region_id) or []))
    return flattened


def flatten_checklists(checklists: dict) -> list[dict]:
    flattened: list[dict] = []
    for stage in ("recognition", "generation_refine", "fusion"):
        for item in flatten_stage_checklist(checklists, stage):
            flattened.append({"stage": stage, **item})
    return flattened


def select_checklist_for_region(checklists: dict, region_id: str, *, stage: str) -> list[str]:
    return [
        item["criterion"]
        for item in select_checklist_payload_for_region(checklists, region_id, stage=stage)
        if item.get("criterion")
    ]


def select_checklist_payload_for_region(checklists: dict, region_id: str, *, stage: str) -> list[dict]:
    section = _stage_section(checklists, stage)
    common_items = _compact_items(section.get("common") or [])
    region_items = _compact_items(((section.get("regions") or {}).get(region_id)) or [])
    return [*common_items, *region_items]


def select_checklist_for_fusion(checklists: dict) -> list[str]:
    return [
        item["criterion"]
        for item in select_checklist_payload_for_fusion(checklists)
        if item.get("criterion")
    ]


def select_checklist_payload_for_fusion(checklists: dict) -> list[dict]:
    section = _stage_section(checklists, "fusion")
    return _compact_items(section.get("common") or [])


def checklist_budget_summary(checklists: dict) -> dict:
    summary: dict[str, dict] = {}
    grand_total = 0
    for stage in ("recognition", "generation_refine", "fusion"):
        section = _stage_section(checklists, stage)
        common_count = len(section.get("common") or [])
        region_counts = {
            region_id: len(items or [])
            for region_id, items in (section.get("regions") or {}).items()
        }
        stage_total = common_count + sum(region_counts.values())
        grand_total += stage_total
        summary[stage] = {
            "common": common_count,
            "per_region": region_counts,
            "total": stage_total,
            "limits": dict(CHECKLIST_STAGE_BUDGETS[stage]),
        }
    return {
        "stages": summary,
        "total": grand_total,
        "limits": {"total": CHECKLIST_STAGE_BUDGETS["total"]},
    }


def checklist_budget_issues(checklists: dict) -> list[str]:
    summary = checklist_budget_summary(checklists)
    issues: list[str] = []
    if summary["total"] > summary["limits"]["total"]:
        issues.append(f"Total checklist items exceed the budget of {summary['limits']['total']}.")
    for stage in ("recognition", "generation_refine", "fusion"):
        stage_summary = summary["stages"][stage]
        stage_limits = stage_summary["limits"]
        if stage_summary["common"] > stage_limits["common"]:
            issues.append(
                f"{stage} common checklist items exceed the budget of {stage_limits['common']}."
            )
        if stage_summary["total"] > stage_limits["total"]:
            issues.append(f"{stage} checklist items exceed the budget of {stage_limits['total']}.")
        for region_id, count in stage_summary["per_region"].items():
            if count > stage_limits["region"]:
                issues.append(
                    f"{stage} region {region_id} has more than {stage_limits['region']} region-scoped checklist items."
                )
    return issues


def checklist_criteria(items: list[dict]) -> list[str]:
    criteria: list[str] = []
    for item in items:
        criterion = compact_checklist_item(item).get("criterion")
        if criterion:
            criteria.append(criterion)
    return criteria


def region_review_issues(review: dict) -> list:
    return [
        *(review.get("global_repairs") or []),
        *(review.get("object_issues") or []),
    ]


FINAL_REVIEW_ISSUE_LISTS: tuple[tuple[str, str, str], ...] = (
    ("spatial_relation_issues", "layout_fidelity_issues", "layout_fidelity"),
    ("spatial_relation_issues", "dimension_fidelity_issues", "dimension_fidelity"),
    ("logical_relation_issues", "redundancy_issues", "redundant_object"),
    ("logical_relation_issues", "boundary_issues", "region_boundary"),
    ("visual_quality_issues", "consistency_issues", "object_consistency"),
    ("visual_quality_issues", "visual_reasonableness_issues", "visual_reasonableness"),
)


def flatten_final_review_issues(final_review: dict, *, include_visual: bool = True) -> list[dict]:
    issues: list[dict] = []
    for section_key, list_key, issue_kind in FINAL_REVIEW_ISSUE_LISTS:
        if not include_visual and section_key == "visual_quality_issues":
            continue
        section = final_review.get(section_key) or {}
        for raw in section.get(list_key) or []:
            if not isinstance(raw, dict):
                continue
            issues.append({**raw, "issue_kind": issue_kind})
    return issues


def fusion_review_issue_id(issue: dict, *, issue_kind: str | None = None) -> str:
    kind = issue_kind or issue.get("issue_kind") or "fusion"
    regions = ",".join(issue.get("related_regions") or []) or "global"
    criterion = str(issue.get("criterion") or "fusion_issue")
    return f"{kind}:{regions}:{criterion}"


def final_review_issues(final_review: dict) -> list:
    return flatten_final_review_issues(final_review, include_visual=True)


def final_review_spatial_logical_issues(final_review: dict) -> list:
    return flatten_final_review_issues(final_review, include_visual=False)


def final_review_issue_groups(final_review: dict) -> dict[str, dict[str, list]]:
    spatial = final_review.get("spatial_relation_issues") or {}
    logical = final_review.get("logical_relation_issues") or {}
    visual = final_review.get("visual_quality_issues") or {}
    return {
        "spatial_relation": {
            "layout_fidelity_issues": spatial.get("layout_fidelity_issues") or [],
            "dimension_fidelity_issues": spatial.get("dimension_fidelity_issues") or [],
        },
        "logical_relation": {
            "redundancy_issues": logical.get("redundancy_issues") or [],
            "boundary_issues": logical.get("boundary_issues") or [],
        },
        "visual_quality": {
            "consistency_issues": visual.get("consistency_issues") or [],
            "visual_reasonableness_issues": visual.get("visual_reasonableness_issues") or [],
        },
    }
