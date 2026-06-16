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


def build_final_review_prompts(
    *,
    checklist_criteria: list[dict],
    merged_svg: str,
    svg_file_name: str = "merged_final.svg",
) -> tuple[str, str]:
    system_prompt = textwrap.dedent(
        f"""
        You are a final fusion-quality reviewer for a raster-to-SVG pipeline.
        Review the merged SVG after all region fragments have been combined.
        Return JSON only.

        Your scope is fusion quality after merging, not single-region generation quality.
        Focus on obvious, global, or clearly visible problems that affect the merged result.
        Do not over-index on tiny local imperfections, microscopic alignment drift, or
        arguable stylistic differences unless they are visually obvious or materially affect
        the overall composition.
        Evaluate these dimensions:
        - Layout fidelity: the merged SVG preserves the source's overall layout hierarchy,
          relative positions, spacing, and visual flow.
        - Dimension fidelity: the final canvas size, aspect ratio, region sizes, and object
          scale relationships match the source image.
        - Same-class/repeated-object consistency: repeated arrows, connectors, icons, labels,
          nodes, chart marks, and other same-class objects use consistent SVG structure,
          color, stroke, markers, typography, and composition across regions.
        - Visual reasonableness: detect obvious visual mistakes or low-quality rendering in the
          merged SVG, such as malformed shapes, broken strokes, distorted markers, unreadable
          text rendering, accidental fills, jagged overlaps, or other visually incorrect output.
          Focus only on whether the rendering looks visually correct, not on logic, semantics,
          or faithfulness to the source structure.
        - Redundant objects: objects split across region boundaries should not remain as
          duplicated or fragmented pieces when they should be one semantic object, such as
          a connector line cut into two line segments by neighboring regions.
        - Region boundary smoothness: seams between regions should be visually continuous;
          connectors, backgrounds, outlines, labels, and repeated elements should cross or
          meet boundaries cleanly without gaps, overlaps, double strokes, or abrupt style changes.

        Do not focus on minor object-level imperfections unless they affect the merged result
        across regions, except for clearly visible low-quality rendering that belongs in visual
        reasonableness. Output issue descriptions, not repaired SVG.
        Group all issues into exactly three top-level buckets:
        - spatial_relation_issues
        - logical_relation_issues
        - visual_quality_issues
        Put each issue only in its matching list under the correct top-level bucket.
        {FINAL_REVIEW_ISSUE_RULES}
        Do not return passed-item summaries. Report only actual issues and known limitations.
        Input roles: image 1 is the ground-truth source image; image 2 is the rendered preview of the final SVG.
        Inline SVG source text is structural evidence for localization. Use the rendered preview as the primary visual comparison target.
        {json_output_contract(
            required_fields=("spatial_relation_issues", "logical_relation_issues", "visual_quality_issues", "known_limitations"),
            array_fields=(
                "spatial_relation_issues.layout_fidelity_issues",
                "spatial_relation_issues.dimension_fidelity_issues",
                "logical_relation_issues.redundancy_issues",
                "logical_relation_issues.boundary_issues",
                "visual_quality_issues.consistency_issues",
                "visual_quality_issues.visual_reasonableness_issues",
                "known_limitations",
            ),
            closed_value_fields={"*.severity": ("low", "medium", "high")},
        )}
        """
    ).strip()
    user_prompt = join_sections(
        section(
            "Final review request",
            (
                "Attached images are, in order: "
                "1) the original source image, 2) the rendered preview of the provided final SVG."
            ),
        ),
        json_section("Fusion-scope checklist criteria", checklist_criteria),
        inline_text_file_section(
            "Final SVG source",
            file_name=svg_file_name,
            content=merged_svg,
            role="Structural SVG source that corresponds to the rendered preview image.",
        ),
        section(
            "Return this JSON shape",
            final_review_result_json_example(),
        ),
    )
    return system_prompt, user_prompt


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
        Your job is to repair only the merged SVG after region fragments have been combined.
        Return JSON only.

        Focus only on spatial-relation and logical-relation problems that are obvious in the
        merged result:
        - layout shifts or misalignment between merged regions
        - wrong relative spacing or scale after merge
        - duplicated elements introduced by merge
        - broken, truncated, doubled, or disconnected cross-region connectors/arrows
        - boundary seams that cause logical fragmentation or overlap

        Do not chase tiny local cleanup opportunities. Do not rewrite the SVG for cosmetic
        polish. Ignore purely visual-quality issues unless fixing them is necessary to resolve
        a spatial or logical problem. Apply a conservative one-pass repair.
        If merged SVG source text is provided inline, treat it as the editable base document to repair.

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
