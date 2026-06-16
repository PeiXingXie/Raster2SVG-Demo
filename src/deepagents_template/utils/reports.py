"""Overview: Unified report builders for merged markdown/JSON conversion outputs."""

from __future__ import annotations

from deepagents_template.checklist import final_review_issue_groups, flatten_checklists


def assemble_conversion_report(
    *,
    input_section: dict,
    checklist: dict,
    regions: list[dict],
    region_results: list[dict],
    initial_review: dict,
    final_review: dict,
    final_svg_path: str,
    final_svg_valid: bool,
    node_timings: dict[str, dict],
    error_summary: dict | None = None,
    known_limitations: list[str] | None = None,
) -> dict:
    """Build the unified report payload used for both markdown and JSON output."""

    region_status_rows = []
    residual_region_total = 0
    residual_object_total = 0
    residual_by_region = []
    objects_total = 0

    reviews_available = any(result.get("review") for result in region_results)
    for result in region_results:
        recognized_objects = result.get("generation", {}).get("recognized_objects") or []
        objects_total += len(recognized_objects)
        review = result.get("review") or {}
        region_issues = review.get("global_repairs") or []
        object_issues = review.get("object_issues") or []
        residual_region_total += len(region_issues)
        residual_object_total += len(object_issues)
        region_status_rows.append(
            {
                "region_id": result["region_id"],
                "objects_total": len(recognized_objects),
                "region_issue_count": len(region_issues),
                "object_issue_count": len(object_issues),
                "retry_exhausted": bool(result.get("retry_exhausted")),
            }
        )
        residual_by_region.append(
            {
                "region_id": result["region_id"],
                "region_issues": list(region_issues),
                "object_issues": list(object_issues),
            }
        )

    report = {
        "status": "completed" if final_svg_valid else "partially_completed",
        "metrics": {
            "regions_total": len(regions),
            "regions_clean": sum(
                1
                for row in region_status_rows
                if row["region_issue_count"] == 0 and row["object_issue_count"] == 0
            ),
            "regions_with_residual_issues": sum(
                1
                for row in region_status_rows
                if row["region_issue_count"] > 0 or row["object_issue_count"] > 0
            ),
            "regions_retry_exhausted": sum(1 for row in region_status_rows if row["retry_exhausted"]),
            "objects_total": objects_total,
        },
        "input": input_section,
        "checklists": checklist,
        "checklist": [
            {
                "stage": item.get("stage"),
                "item_id": item.get("item_id"),
                "criterion": item.get("criterion"),
                "scope": item.get("scope"),
                "region_id": item.get("region_id"),
            }
            for item in flatten_checklists(checklist)
        ],
        "regions": [
            {
                "region_id": region.get("region_id"),
                "description": region.get("description"),
                "bbox": region.get("bbox"),
            }
            for region in regions
        ],
        "region_results": region_status_rows,
        "reviews": {
            "initial": {
                "issues": final_review_issue_groups(initial_review),
                "known_limitations": list(initial_review.get("known_limitations") or []),
            },
            "final": {
                "issues": final_review_issue_groups(final_review),
                "known_limitations": list(final_review.get("known_limitations") or []),
            },
        },
        "residual_issues": {
            "available": reviews_available,
            "region_issues_total": residual_region_total if reviews_available else None,
            "object_issues_total": residual_object_total if reviews_available else None,
            "by_region": residual_by_region if reviews_available else [],
        },
        "output": {
            "final_svg_path": final_svg_path,
            "final_svg_valid": final_svg_valid,
            "objects_total": objects_total,
        },
        "node_timings": node_timings,
        "errors": error_summary
        or {
            "warnings_total": 0,
            "errors_total": 0,
            "items": [],
        },
        "known_limitations": known_limitations
        or [
            "Small decorative details may be simplified.",
            "Photo-like regions may be represented by annotated placeholders.",
        ],
    }
    return report


def render_conversion_report_markdown(report: dict) -> str:
    """Render the unified report payload as markdown for terminal and artifact output."""

    input_section = report["input"]
    metrics = report["metrics"]
    output_section = report["output"]
    node_timings = report["node_timings"]
    residual = report["residual_issues"]
    error_summary = report.get("errors") or {"warnings_total": 0, "errors_total": 0, "items": []}

    lines = [
        "# Raster-to-SVG Report",
        "",
        "## Status",
        f"- Run status: `{report['status']}`",
        f"- Final SVG valid: `{output_section['final_svg_valid']}`",
        f"- Regions total: `{metrics['regions_total']}`",
        f"- Regions clean: `{metrics['regions_clean']}`",
        f"- Regions with residual issues: `{metrics['regions_with_residual_issues']}`",
        f"- Regions retry exhausted: `{metrics['regions_retry_exhausted']}`",
        f"- Objects total: `{metrics['objects_total']}`",
        "",
        "## Input",
        f"- Image: `{input_section['file_name']}`",
        f"- Size: `{input_section['width']}x{input_section['height']}`",
        f"- API provider: `{input_section['api_provider']}`",
        f"- API format: `{input_section['api_format']}`",
        f"- Max retry per repair task: `{input_section['max_retry']}`",
        f"- Max API budget: `{input_section['max_budget']}`",
        f"- API calls used: `{input_section['api_calls_used']}`",
        f"- Run elapsed: `{input_section['run_elapsed_ms']} ms`",
        (
            f"- Region processing: `{input_section['region_processing_mode']}` "
            f"(concurrency `{input_section['region_concurrency']}`)"
        ),
        f"- Workflow mode: `{input_section['workflow_mode']}`",
        f"- Request: {input_section['request_message']}",
        "",
        "## Node Timings",
    ]
    for node_name, timing in node_timings.items():
        phase_parts = [
            f"{phase}={phase_payload['total_ms']} ms/{phase_payload['runs']} run(s)"
            for phase, phase_payload in timing.get("phases", {}).items()
        ]
        phase_suffix = f" | phases: {', '.join(phase_parts)}" if phase_parts else ""
        lines.append(
            f"- {node_name}: total={timing['total_ms']} ms, runs={timing['runs']}{phase_suffix}"
        )

    lines.extend(["", "## Errors"])
    lines.append(f"- Warnings total: `{error_summary.get('warnings_total', 0)}`")
    lines.append(f"- Errors total: `{error_summary.get('errors_total', 0)}`")
    error_items = error_summary.get("items") or []
    if error_items:
        for item in error_items:
            label = item.get("level", "info")
            summary = item.get("summary") or item.get("title") or "error event"
            lines.append(f"- [{label}] {summary}")
            if item.get("detail"):
                lines.append(f"  - detail: {item['detail']}")
            if item.get("response_model"):
                lines.append(f"  - schema: {item['response_model']}")
            if item.get("request_path"):
                lines.append(f"  - request: `{item['request_path']}`")
            if item.get("raw_response_path"):
                lines.append(f"  - raw response: `{item['raw_response_path']}`")
    else:
        lines.append("- none")

    lines.extend(["", "## Checklist"])
    lines.extend(
        (
            f"- [{item.get('stage', 'unknown')}] {item['item_id']}: {item['criterion']}"
            + (f" (region: {item['region_id']})" if item.get("region_id") else "")
        )
        for item in report["checklist"]
    )

    lines.extend(["", "## Regions"])
    lines.extend(
        f"- {region['region_id']}: {region['description']}"
        for region in report["regions"]
    )

    lines.extend(["", "## Region Results"])
    for result in report["region_results"]:
        lines.append(
            f"- {result['region_id']}: objects={result['objects_total']}, "
            f"residual_region_issues={result['region_issue_count']}, "
            f"residual_object_issues={result['object_issue_count']}, "
            f"retry_exhausted={result['retry_exhausted']}"
        )

    lines.extend(_render_review_section("Initial Review Issues", report["reviews"]["initial"]))
    lines.extend(_render_review_section("Final Review Issues", report["reviews"]["final"]))

    lines.extend(["", "## Residual Region/Object Issues"])
    if residual["available"]:
        lines.append(f"- Residual region issues total: `{residual['region_issues_total']}`")
        lines.append(f"- Residual object issues total: `{residual['object_issues_total']}`")
        for region_payload in residual["by_region"]:
            region_id = region_payload["region_id"]
            region_issues = region_payload["region_issues"]
            object_issues = region_payload["object_issues"]
            lines.append(
                f"- {region_id}: region_issues={len(region_issues)}, object_issues={len(object_issues)}"
            )
            for issue in region_issues:
                lines.append(
                    f"  - [region] {issue.get('criterion', 'issue')}: {issue.get('reason', '')}"
                )
            for issue in object_issues:
                lines.append(
                    f"  - [object:{issue.get('object_id', 'unknown')}] "
                    f"{issue.get('criterion', 'issue')}: {issue.get('reason', '')}"
                )
    else:
        lines.append("- Residual region/object issues: `not evaluated in initial_only mode`")

    lines.extend(
        [
            "",
            "## Output",
            f"- Final SVG: `{output_section['final_svg_path']}`",
            f"- Objects total: `{output_section['objects_total']}`",
            "",
            "## Known Limitations",
        ]
    )
    lines.extend(f"- {item}" for item in report["known_limitations"])
    return "\n".join(lines) + "\n"


def _render_review_section(title: str, review_payload: dict) -> list[str]:
    issue_groups = review_payload["issues"]
    lines = ["", f"## {title}"]
    lines.extend(_render_issue_bucket("Spatial Relation", issue_groups["spatial_relation"]))
    lines.extend(_render_issue_bucket("Logical Relation", issue_groups["logical_relation"]))
    lines.extend(_render_issue_bucket("Visual Quality", issue_groups["visual_quality"]))
    limitations = review_payload.get("known_limitations") or []
    lines.append("- Known limitations:")
    if limitations:
        lines.extend(f"  - {item}" for item in limitations)
    else:
        lines.append("  - none")
    return lines


def _render_issue_bucket(title: str, bucket: dict[str, list[dict]]) -> list[str]:
    lines = [f"### {title}"]
    issue_total = sum(len(items) for items in bucket.values())
    if issue_total == 0:
        lines.append("- none")
        return lines
    for issue_list_name, items in bucket.items():
        label = issue_list_name.replace("_issues", "").replace("_", " ")
        lines.append(f"- {label}:")
        for issue in items:
            related_regions = ", ".join(issue.get("related_regions") or []) or "none"
            related_objects = ", ".join(issue.get("related_objects") or []) or "none"
            lines.append(
                f"  - [{issue.get('severity', 'unknown')}] {issue.get('description', '')} "
                f"(regions: {related_regions}; objects: {related_objects})"
            )
    return lines
