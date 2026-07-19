"""Overview: Prompt builders for full-image integrated SVG review and final checks."""

from __future__ import annotations

import textwrap

from deepagents_template.utils.prompting import (
    inline_text_file_section,
    join_sections,
    json_output_contract,
    json_section,
    section,
    svg_output_contract,
)

FINAL_REVIEW_ISSUE_RULES = """
Each issue object must use this shape:
{
  "criterion": "short_snake_case_label",
  "severity": "low|medium|high",
  "description": "...",
  "related_regions": ["r1"],
  "related_objects": ["object_id"]
}
Use criterion as a concise reusable label. Do not use category, issue, or rationale fields.
known_limitations must be a list of plain strings, not objects.
"""


def final_review_result_json_example() -> str:
    return textwrap.dedent(
        """
        {
          "spatial_relation_issues": {
            "layout_fidelity_issues": [
              {
                "criterion": "panel_layout_shift",
                "severity": "high",
                "description": "The merged SVG shifts the main panel relative to the source layout.",
                "related_regions": ["r2_main"],
                "related_objects": []
              }
            ],
            "dimension_fidelity_issues": []
          },
          "logical_relation_issues": {
            "redundancy_issues": [
              {
                "criterion": "cross_region_connector_split",
                "severity": "medium",
                "description": "A connector crossing two regions is represented as two disconnected line segments.",
                "related_regions": ["r2_left", "r3_right"],
                "related_objects": ["cross_region_connector"]
              }
            ],
            "boundary_issues": [
              {
                "criterion": "panel_boundary_fill_gap",
                "severity": "low",
                "description": "A background fill changes abruptly at a region boundary.",
                "related_regions": ["r2_panel", "r3_panel"],
                "related_objects": []
              }
            ]
          },
          "visual_quality_issues": {
            "consistency_issues": [
              {
                "criterion": "arrowhead_style_mismatch",
                "severity": "medium",
                "description": "Repeated arrowheads use different marker geometry or colors across regions.",
                "related_regions": ["r1_header", "r4_footer"],
                "related_objects": ["arrow_connector"]
              }
            ],
            "visual_reasonableness_issues": [
              {
                "criterion": "background_uniformity",
                "severity": "medium",
                "description": "A merged decorative shape has a visibly broken fill and malformed outline.",
                "related_regions": ["r5_background"],
                "related_objects": []
              }
            ]
          },
          "known_limitations": ["optional limitation about fusion quality"]
        }
        """
    ).strip()


def build_integrated_svg_repair_prompts(
    *,
    user_request: str,
    merged_svg: str,
    final_review: dict,
    svg_file_name: str = "merged_final.svg",
) -> tuple[str, str]:
    system_prompt = textwrap.dedent(
        f"""
        You are a merge-time SVG repair specialist for a raster-to-SVG pipeline.
        Your task is to repair only merge/fusion-level defects in the provided
        complete SVG document after region fragments have been combined.
        Return JSON only.

        Input priority:
        1. The original raster image is the visual ground truth.
        2. The inline merged SVG source is the editable base document.
        3. The review findings define the primary repair scope.

        Repair scope:
        Fix only spatial-relation and logical-relation problems that are obvious in the
        merged result or explicitly listed in the review findings:
        - layout shifts or misalignment between merged regions
        - wrong relative spacing or scale after merge
        - duplicated elements introduced by merge
        - broken, truncated, doubled, or disconnected cross-region connectors/arrows
        - boundary seams that cause logical fragmentation or overlap

        Do not perform general cosmetic polishing, style redesign, or broad SVG simplification.
        Visual-quality changes are allowed only when they are necessary to resolve a spatial
        or logical merge defect, such as a broken connector marker or boundary style discontinuity.
        Apply a conservative one-pass repair.

        Preservation rules:
        - Preserve the outer SVG canvas size, viewBox, namespaces, defs, styles, and metadata
          unless a review finding explicitly requires changing them.
        - Preserve existing region group ids, data-bbox attributes, data-region-id attributes,
          data-object-id attributes, and semantic grouping wherever possible.
        - Do not rewrite unaffected regions or objects.
        - Prefer the smallest localized SVG edit that resolves the reviewed merge issue.
        - Do not invent new content that is not supported by the source image.
        - For every important review finding, either repair it or mention why it remains in
          remaining_limitations.

        Return the repaired SVG as a complete SVG document string.
        {json_output_contract(
            required_fields=("repaired_svg", "repairs_applied", "remaining_limitations"),
            array_fields=("repairs_applied", "remaining_limitations"),
        )}
        {svg_output_contract(field_name="repaired_svg", mode="document")}
        """
    ).strip()
    user_prompt = join_sections(
        section("User request", user_request),
        inline_text_file_section(
            "Current merged SVG source",
            file_name=svg_file_name,
            content=merged_svg,
            role="Editable base SVG source to repair. Read this inline text directly.",
        ),
        json_section("Review findings to address", final_review),
        section(
            "Return this JSON shape",
            textwrap.dedent(
                """
                {
                  "repaired_svg": "<svg ...>...</svg>",
                  "repairs_applied": [
                    "Merged duplicate connector fragments across r2 and r3.",
                    "Adjusted panel alignment to remove a cross-region overlap."
                  ],
                  "remaining_limitations": [
                    "Optional note if a spatial/logical issue could not be fully corrected."
                  ]
                }
                """
            ).strip(),
        ),
    )
    return system_prompt, user_prompt
