"""Overview: Prompt builders for bbox quality review and correction."""

from __future__ import annotations

import json
import textwrap

from deepagents_template.schemas import BBOX_ISSUE_CODES, BBOX_ISSUE_EDGES


TEXT_RULES = """
Text limits:
- overview: exactly 1 sentence, at most 20 words.
- issues: at most 5 items.
- each issue.criterion: at most 8 words.
- each issue.reason: at most 12 words.
- strategy_rationale: exactly 1 sentence, at most 16 words.
- changes_applied: at most 4 items.
- each changes_applied item: at most 12 words.
- Write only major spatial defects or major accepted adjustments.
- Do not mention minor padding, tiny spacing, or cosmetic details.
""".strip()

POLICY_TEXT_RULES = """
Text limits:
- candidate_review.overview: exactly 1 sentence, at most 20 words.
- candidate_review.issues: at most 5 items.
- each issue.criterion: at most 8 words.
- each issue.reason: at most 12 words.
- decision.rationale: exactly 1 sentence, at most 16 words.
- resolved_issue_ids and new_issue_ids: short stable ids only.
- Focus on major bbox problems; allow small residual low-severity issues to pass.
""".strip()

SEVERITY_RULE = (
    'issues[].severity must be exactly one of "low", "medium", or "high" as a JSON string.'
)

BBOX_ISSUE_CODE_RULE = (
    "bbox issue family fields must be exactly one of these JSON string values: "
    + ", ".join(BBOX_ISSUE_CODES)
    + ". Use the broad issue family only; do not invent edge-specific suffixes such as _left or _bottom."
)

BBOX_ISSUE_FAMILY_RULE = (
    "Closed bbox issue family definitions: "
    "target_not_contained = visible target content lies outside the bbox; "
    "target_clipped = a bbox edge crosses, touches, presses against, or truncates target pixels, strokes, glyphs, or endpoints; "
    "excessive_padding = the target is contained and unclipped, but the bbox includes too much avoidable whitespace or unrelated content; "
    "off_center = the target is contained and unclipped, but is visibly biased within the bbox; "
    "invalid_bbox = the bbox is missing, malformed, out of bounds, zero-area, or geometrically nonsensical."
)

BBOX_ISSUE_EDGES_RULE = (
    'edges must be an array using only "'
    + '", "'.join(BBOX_ISSUE_EDGES)
    + '"; include every bbox edge involved in that issue, or [] when the issue is not edge-specific. '
    'Never use vague edge values such as "multi", "all", "vertical", "horizontal", "x", or "y".'
)

LAYOUT_BBOX_ADJUSTMENT_TYPES = (
    "none",
    "tighten_overreach",
    "expand_for_missing_content",
    "recenter_within_local_context",
    "merge_background_bands",
    "split_independent_bands",
    "split_independent_panels",
    "repartition_overcoarse_layout",
    "mixed",
)

RECOGNITION_BBOX_ADJUSTMENT_TYPES = (
    "none",
    "tighten_overreach",
    "expand_for_missing_content",
    "recenter_within_local_context",
    "merge_background_bands",
    "mixed",
)

LAYOUT_BBOX_ADJUSTMENT_TYPE_RULE = (
    "adjustment_type must be exactly one of these JSON string values: "
    + ", ".join(LAYOUT_BBOX_ADJUSTMENT_TYPES)
    + ". Never invent new labels such as reposition_and_expand. "
    "When the adjustment combines multiple move families, use mixed."
)

RECOGNITION_BBOX_ADJUSTMENT_TYPE_RULE = (
    "adjustment_type must be exactly one of these JSON string values: "
    + ", ".join(RECOGNITION_BBOX_ADJUSTMENT_TYPES)
    + ". Never invent new labels such as reposition_and_expand. "
    "When the adjustment combines multiple move families, use mixed."
)


def history_rules_block(enabled: bool) -> str:
    return (
        "- Supervisor memory delta is historical hint only. "
        "They must not override current visual evidence."
        if enabled
        else ""
    )


def history_example_block(enabled: bool, memory_summary: dict | None) -> str:
    if not enabled or memory_summary is None:
        return ""
    return textwrap.dedent(
        f"""
        Supervisor memory delta:
        {json.dumps(memory_summary, ensure_ascii=False, indent=2)}
        """
    ).strip()


def optional_json_block(title: str, value: object) -> str:
    if not value:
        return ""
    return textwrap.dedent(
        f"""
        {title}:
        {json.dumps(value, ensure_ascii=False, indent=2)}
        """
    ).strip()


def json_block(title: str, value: object) -> str:
    return textwrap.dedent(
        f"""
        {title}:
        {json.dumps(value, ensure_ascii=False, indent=2)}
        """
    ).strip()


def join_prompt_sections(*sections: str) -> str:
    return "\n\n".join(section.strip() for section in sections if section and section.strip())


def build_object_initial_bbox_prompts(
    *,
    region: dict,
    recognized_objects: list[dict],
    checklist_criteria: list[dict] | None = None,
) -> tuple[str, str]:
    system_prompt = textwrap.dedent(
        f"""
        You are an initial object bbox localization worker.
        You receive two images in order: the original region crop, then a grid reference image for the same crop.
        Generate exactly one generous crop-local bbox for each recognized object.
        Return JSON only.

        Core rules:
        - All bbox coordinates must use the original region crop coordinate system, not scaled display pixels.
        - The grid image may be visually enlarged or padded, but its labels still refer to original crop coordinates.
        - Do not output coordinates in any padded label margin outside the real crop content.
        - Generate one bbox per object_id from the object list.
        - Prefer generous boxes that fully contain the target object over tight boxes.
        - Do not cut target pixels, strokes, glyphs, endpoints, descenders, or panel borders.
        - Try to avoid overlap between different object bboxes when feasible.
        - If no-overlap conflicts with containing the target, prioritize target containment.
        - Container and background objects may cover broad areas or overlap other objects when that matches their role.
        - Use the object description, relative_position, and extent_hint as the object identity contract.

        Output contract:
        - region_id must match the current region.
        - object_bboxes must contain objects with object_id, bbox, coverage_confidence, overlap_risk, and rationale.
        - coverage_confidence and overlap_risk must be exactly "low", "medium", or "high".
        - bbox fields must be integer x, y, width, height in crop-local coordinates.
        - Do not include extra top-level fields.
        """
    ).strip()
    user_prompt = join_prompt_sections(
        json_block("Region", region),
        optional_json_block("Recognized objects without bboxes", recognized_objects),
        optional_json_block("Applicable checklist criteria", checklist_criteria or []),
        textwrap.dedent(
            f"""
            Return this JSON shape:
            {{
              "region_id": "{region['region_id']}",
              "object_bboxes": [
                {{
                  "object_id": "heading_text",
                  "bbox": {{"x": 70, "y": 96, "width": 150, "height": 52}},
                  "coverage_confidence": "medium",
                  "overlap_risk": "low",
                  "rationale": "Covers the full heading with safety margin while staying above subtitle."
                }}
              ]
            }}
            """
        ),
    )
    return system_prompt, user_prompt


def build_object_bbox_candidate_generation_prompts(
    *,
    region: dict,
    recognized_objects: list[dict],
    current_issues: list[dict],
) -> tuple[str, str]:
    system_prompt = textwrap.dedent(
        f"""
        You are a bbox candidate generation worker for selected object bbox issues.
        You receive three images in order: the original region crop, a grid reference image, and the current all-object bbox overlay.
        For each selected issue, generate compact, balanced, and roomy bbox candidates for that same object.
        Return JSON only.

        Core rules:
        - All bbox coordinates must use the original region crop coordinate system.
        - The grid image may be enlarged or padded, but its labels still refer to original crop coordinates.
        - Do not output coordinates in padded label margins outside the real crop content.
        - Generate candidates only for the listed issues.
        - Do not add, remove, split, merge, or rename objects.
        - Each issue must have exactly one candidate_set and candidates named compact, balanced, roomy.
        - compact means smallest reasonable improvement, not a risky tight crop.
        - balanced means the recommended candidate for target coverage with reasonable padding.
        - roomy means prioritize target coverage even with more padding.
        - If the issue is excessive_padding or off_center, candidates may shrink or recenter, but must not introduce target clipping.
        - Target containment and no target clipping have priority over tightness or overlap reduction.

        Output contract:
        - region_id must match the current region.
        - candidate_sets[].issue_family must follow the closed set from the bbox issue rules.
        - candidate_sets[].edges must be a list using only "left", "top", "right", "bottom"; use [] for non-edge-specific issues.
        - Do not use vague edge values such as "multi", "all", "vertical", or "horizontal".
        - bbox fields must be integer x, y, width, height in crop-local coordinates.
        - Do not include canonical_issue_id; the system derives stable ids.
        - {BBOX_ISSUE_CODE_RULE}
        - {BBOX_ISSUE_FAMILY_RULE}
        - {BBOX_ISSUE_EDGES_RULE}
        """
    ).strip()
    user_prompt = join_prompt_sections(
        json_block("Region", region),
        optional_json_block("Current recognized objects", recognized_objects),
        optional_json_block("Selected issues", current_issues),
        textwrap.dedent(
            f"""
            Return this JSON shape:
            {{
              "region_id": "{region['region_id']}",
              "candidate_sets": [
                {{
                  "object_id": "heading_text",
                  "issue_family": "target_clipped",
                  "edges": ["top"],
                  "candidates": [
                    {{"candidate_id": "compact", "bbox": {{"x": 76, "y": 100, "width": 138, "height": 44}}, "intent": "minimal safe expansion"}},
                    {{"candidate_id": "balanced", "bbox": {{"x": 70, "y": 96, "width": 150, "height": 52}}, "intent": "recommended coverage"}},
                    {{"candidate_id": "roomy", "bbox": {{"x": 62, "y": 90, "width": 166, "height": 64}}, "intent": "maximize target coverage"}}
                  ]
                }}
              ]
            }}
            """
        ),
    )
    return system_prompt, user_prompt


def build_object_bbox_candidate_selection_prompts(
    *,
    region: dict,
    target_object: dict,
    issue: dict,
    candidates: list[dict],
    current_objects: list[dict],
) -> tuple[str, str]:
    system_prompt = textwrap.dedent(
        f"""
        You are an object bbox candidate selection policy.
        You receive three images in order: the original region crop, the current all-object bbox overlay, and the candidate overlay for one target object.
        Select the best candidate for the target object.
        Return JSON only.

        Core rules:
        - Select exactly one candidate from compact, balanced, or roomy.
        - Candidate overlay color rule is fixed and unlabeled: compact is red, balanced is dark blue, and roomy is teal/green.
        - The best candidate and whether the issue is fully resolved are separate decisions.
        - Always choose the candidate closest to solving the current issue, even if residual cleanup remains.
        - Prefer target containment and no target clipping over tightness.
        - Do not reject all candidates; select the best available candidate.
        - Small excessive padding or slight off-center residuals can remain if the candidate improves target coverage.
        - Do not add, remove, split, merge, or rename objects.
        - All bbox coordinates in the output must match the selected candidate bbox.

        Output contract:
        - object_id must match the target object.
        - selected_candidate_id must be exactly "compact", "balanced", or "roomy".
        - issue_resolved is true only if the selected candidate resolves the selected issue.
        - residual_issue may be null when resolved.
        - residual_issue.issue_family must follow the closed set from the bbox issue rules.
        - residual_issue.edges must use only "left", "top", "right", "bottom"; use [] for non-edge-specific issues.
        - Do not use vague edge values such as "multi", "all", "vertical", or "horizontal".
        - {BBOX_ISSUE_CODE_RULE}
        - {BBOX_ISSUE_FAMILY_RULE}
        - {BBOX_ISSUE_EDGES_RULE}
        """
    ).strip()
    user_prompt = join_prompt_sections(
        json_block("Region", region),
        json_block("Target object", target_object),
        json_block("Selected issue", issue),
        optional_json_block("Candidates", candidates),
        optional_json_block("All recognized objects for context", current_objects),
        textwrap.dedent(
            """
            Return this JSON shape:
            {
              "object_id": "heading_text",
              "selected_candidate_id": "balanced",
              "selected_bbox": {"x": 70, "y": 96, "width": 150, "height": 52},
              "issue_resolved": false,
              "residual_issue": {
                "issue_family": "target_clipped",
                "edges": ["top"],
                "severity": "medium",
                "reason": "top edge may still press the heading"
              },
              "selection_rationale": "balanced improves coverage most without excessive subtitle overlap"
            }
            """
        ),
    )
    return system_prompt, user_prompt


def build_layout_bbox_adjustment_prompts(
    *,
    width: int,
    height: int,
    regions: list[dict],
    memory_summary: dict | None,
    retry_state: dict | None = None,
) -> tuple[str, str]:
    has_memory = memory_summary is not None
    memory_rule = history_rules_block(has_memory)
    memory_section = history_example_block(has_memory, memory_summary)
    system_prompt = textwrap.dedent(
        f"""
        You are a bbox quality worker for layout-stage region planning.
        You receive two images in order: the original image, then the current region-bbox overlay.
        Review bbox spatial quality and, when helpful, propose one conservative adjustment attempt.
        Return JSON only.

        Core scope:
        - Focus on layout-stage region adequacy and bbox spatial quality: whether the current region split is too coarse, too fragmented, or spatially misfit for downstream reconstruction.
        - Catch big problems, not tiny details.
        - Prefer stable slightly generous boxes over razor-tight boxes; moderate empty padding is acceptable when it avoids clipping.
        - Every bbox must fully enclose the visible content it is responsible for; the bbox border must stay outside that content rather than cutting through it.
        - If a bbox edge overlaps the target content boundary, strokes, glyphs, or filled area, treat that as a major defect, not acceptable tightness.
        - First judge whether the current region set is already an adequate downstream editing plan.
        - If the current region set is adequate, prefer adjusting x/y/width/height of existing regions over changing the region set.
        - If one region is clearly overcoarse and mixes several independent structural units, you may repartition it into a small number of clearer regions.
        - Only repartition along strong structural boundaries such as panel borders, stacked horizontal bands, columns, headers, footers, sidebars, or detached bars.
        - Never repartition based only on weak whitespace changes, tiny decorations, or isolated labels.
        - Do not create trivial fragments or many tiny regions.
        - Keep repartitioning conservative: each attempt should replace at most one obviously overcoarse area with a small number of stronger regions.
        - Treat near-full-image coverage as an explicit layout goal: the union of all region bboxes should approximately fill the image so all visible content is considered.
        - Do not merge regions except for background-like bands such as title/header/footer/caption background areas.
        - If you merge background-like regions, keep the result weak, stable, semantically broad, and conservative.
        - Each adjusted region must stay inside the canvas.
        - Bboxes should keep the corresponding visible content reasonably centered while avoiding unrelated content when possible.
        - Prioritize full containment over tightness: never trade away visible target content just to reduce padding.
        - If the current union leaves visible areas or elements uncovered, treat that as a major issue unless the omission is truly negligible.
        - Input roles: image 1 is the ground-truth source image; image 2 is the current bbox overlay used only for localization.
        {memory_rule}

        Output contract:
        - scope must be "layout".
        - {LAYOUT_BBOX_ADJUSTMENT_TYPE_RULE}
        - {SEVERITY_RULE}
        - strategy_enabled should be true only when one concise strategy label meaningfully explains the proposed adjustment.
        - strategy_label should summarize the intended bbox move family, not execution details.
        - strategy_confidence must be exactly "low", "medium", or "high" as a JSON string. Never return numeric scores or percentages.
        - target_ids should list only the main regions being adjusted.
        - adjusted_regions must be the full authoritative region list after the proposed adjustment attempt.
        - adjusted_regions may replace the current region set only when the current plan is clearly overcoarse or structurally awkward.
        - If you repartition, keep the total region count conservative and ensure every new region remains semantically meaningful.
        - Never grow the total region count aggressively; use the smallest improved set.
        - When no worthwhile change is needed, set needs_adjustment=false, adjustment_type="none", and leave adjusted_regions empty.

        {TEXT_RULES}
        """
    ).strip()
    user_prompt = join_prompt_sections(
        textwrap.dedent(
            f"""
            Canvas size:
            width={width}, height={height}
            """
        ),
        optional_json_block("Current regions", regions),
        textwrap.dedent(
            """
            Layout coverage reminder:
            - The adjusted region set should approximately fill the full image extent as a union.
            - Do not optimize only for salient local objects while leaving visible areas outside every region.
            - Prefer a region plan that will make downstream object recognition and repair stable across many image types.
            """
        ),
        memory_section,
        textwrap.dedent(
            """
            Return this JSON shape:
        {{
          "scope": "layout",
          "region_id": "",
          "overview": "header and footer bands remain fragmented",
          "issues": [
            {{
              "target_id": "r1",
              "criterion": "bbox includes unrelated content",
              "reason": "box spills into the main panel",
              "severity": "medium"
            }}
          ],
          "adjustment_type": "tighten_overreach",
          "target_ids": ["r1"],
          "adjusted_regions": [
            {{
              "region_id": "r1",
              "bbox": {{"x": 0, "y": 0, "width": 1200, "height": 120}},
              "description": "header band with title and subtitle",
              "priority": 1,
              "status": "planned"
            }}
          ],
          "adjusted_object_bboxes": [],
          "strategy_enabled": true,
          "strategy_label": "tighten_header_band",
          "strategy_rationale": "Constrain the header to its own band.",
          "strategy_confidence": "medium",
          "changes_applied": ["tightened r1 to the header band"],
          "needs_adjustment": true
        }}
        """
        ),
    )
    return system_prompt, user_prompt


def build_recognition_bbox_adjustment_prompts(
    *,
    region: dict,
    recognized_objects: list[dict],
    validation_feedback: list[dict] | None,
    memory_summary: dict | None,
    retry_state: dict | None = None,
    exempted_issue_ids: list[str] | None = None,
    recently_resolved_issue_ids: list[str] | None = None,
) -> tuple[str, str]:
    has_memory = memory_summary is not None
    memory_rule = history_rules_block(has_memory)
    memory_section = history_example_block(has_memory, memory_summary)
    system_prompt = textwrap.dedent(
        f"""
        You are a bbox quality worker for region-recognition object planning.
        You receive two images in order: the region crop, then the current object-bbox overlay.
        Review object bbox spatial quality and propose issue records only.
        Return JSON only.

        Core scope:
        - Focus only on bbox spatial quality under four acceptance rules: contain the target object, do not cut the target, avoid excessive padding, and avoid obvious off-center placement.
        - Catch big problems, not tiny edge padding details.
        - Prefer stable slightly generous boxes over razor-tight boxes; moderate empty padding is acceptable and often desirable.
        - Allow some empty margin when it prevents clipping, preserves labels, or avoids retry churn.
        - Prefer boxes with a small but clear safety margin on all sides; do not keep bbox edges pressed tightly against the content.
        - Every object bbox must completely surround the target content it refers to; the bbox border must not lie on top of the target's visible pixels, strokes, glyphs, dots, or endpoints.
        - If a bbox edge overlaps the target content boundary or leaves any visible target content outside the box, treat that as a major issue.
        - Do not add objects, remove objects, split objects, or merge objects.
        - Do not propose bbox coordinates in this scan step.
        - Do not repeat object metadata that is unchanged; return issue records only.
        - Object bboxes are crop-local coordinates inside the region crop.
        - Bboxes should keep the object reasonably centered while avoiding unrelated nearby content when possible.
        - Including unrelated nearby content is allowed when needed to avoid cutting the target, but large avoidable padding should be reduced.
        - Target containment and no target clipping are hard requirements; padding and centering are quality controls.
        - This worker must return at most 3 issues, ordered from highest to lowest priority.
        - Prioritize target not contained, target clipped, text truncation, connector endpoint loss, then excessive padding or obvious off-center placement.
        - Do not propose issues whose canonical ids appear in the exempted issue list unless the images clearly show a materially different defect.
        - Do not re-open issues whose canonical ids appear in the recently resolved list unless the candidate overlay clearly reintroduced the same defect.
        - For connector-like objects, prioritize full coverage of endpoints, junctions, and connection continuity over tight isolation.
        - For connector-like objects, unavoidable overlap with nearby objects or whitespace is acceptable when needed to preserve the full path.
        - If a bbox edge visibly crosses through the object's pixels, strokes, glyphs, or endpoints, treat it as a major issue that requires refinement.
        - For text objects, clipping any character body, descender, ascender, or punctuation is a major issue.
        - For icons and shapes, clipping outer strokes, terminal dots, or silhouette edges is a major issue.
        - If the box technically contains the content but hugs it too tightly with little or no breathing room, prefer expanding it slightly unless that would introduce obvious unrelated content.
        - When uncertain, err on the side of slightly larger containment rather than risking overlap with or omission of target content.
        - Input roles: image 1 is the ground-truth region crop; image 2 is the current bbox overlay used only for localization.
        {memory_rule}

        Output contract:
        - scope must be "recognition".
        - region_id must match the current region.
        - {RECOGNITION_BBOX_ADJUSTMENT_TYPE_RULE}
        - {SEVERITY_RULE}
        - {BBOX_ISSUE_CODE_RULE}
        - {BBOX_ISSUE_FAMILY_RULE}
        - {BBOX_ISSUE_EDGES_RULE}
        - issues must contain at most 3 items.
        - every issue must include object_id, issue_family, edges, severity, criterion, and reason.
        - issue_family must use the closed bbox issue family; do not output issue_code.
        - object_id is mapped to target_id by the system for compatibility.
        - issue_family is mapped to issue_code by the system for compatibility.
        - canonical_issue_id is generated by the system and any model-provided value will be ignored.
        - target_ids must be [].
        - adjusted_regions must be [].
        - adjusted_object_bboxes must be [].
        - strategy_enabled must be false.
        - changes_applied must be [].
        - Never include chain-of-thought, reasoning text, or any text outside the JSON object.
        - When no worthwhile issue exists, set needs_adjustment=false, adjustment_type="none", and leave issues empty.

        {TEXT_RULES}
        """
    ).strip()
    user_prompt = join_prompt_sections(
        json_block("Region", region),
        optional_json_block("Current recognized objects", recognized_objects),
        optional_json_block("Exempted issue ids", exempted_issue_ids),
        optional_json_block("Recently resolved issue ids", recently_resolved_issue_ids),
        memory_section,
        textwrap.dedent(
            f"""
            Return this JSON shape:
        {{
          "scope": "recognition",
          "region_id": "{region['region_id']}",
          "overview": "heading box clips the upper text strokes",
          "issues": [
            {{
              "object_id": "heading_text",
              "issue_family": "target_clipped",
              "edges": ["top"],
              "criterion": "bbox cuts target",
              "reason": "top edge crosses letters",
              "severity": "high"
            }}
          ],
          "adjustment_type": "expand_for_missing_content",
          "target_ids": [],
          "adjusted_regions": [],
          "adjusted_object_bboxes": [],
          "strategy_enabled": false,
          "strategy_label": null,
          "strategy_rationale": null,
          "strategy_confidence": null,
          "changes_applied": [],
          "needs_adjustment": true
        }}
        """
        ),
    )
    return system_prompt, user_prompt


def build_layout_bbox_combined_policy_prompts(
    *,
    width: int,
    height: int,
    current_regions: list[dict],
    candidate_regions: list[dict],
    proposal_result: dict,
    memory_summary: dict | None,
    candidate_changed: bool,
    retry_state: dict | None = None,
) -> tuple[str, str]:
    has_memory = memory_summary is not None
    memory_rule = history_rules_block(has_memory)
    memory_section = history_example_block(has_memory, memory_summary)
    system_prompt = textwrap.dedent(
        f"""
        You are a combined bbox policy advisor for layout-stage region planning.
        You receive three images in order: the original image, the current bbox overlay, and the candidate bbox overlay.
        Review the candidate bbox state, then emit termination tendencies for the supervisor.
        Return JSON only.

        Core policy principles:
        - Focus only on major bbox quality: clipping, missing important content, overreach into unrelated content, and obvious off-center placement.
        - Treat under-coverage as a major layout defect: the union of candidate regions should approximately fill the image and not omit visible content bands or broad background areas.
        - Eliminate major problems when possible.
        - Small residual low-severity issues may be accepted.
        - Prefer stable slightly generous candidates over razor-tight boxes; do not penalize moderate empty padding by itself.
        - If any bbox edge visibly crosses through content it is supposed to contain, or lies on top of target strokes/fills, treat that as a major unresolved issue.
        - Do not accept a candidate if any target bbox still fails to fully enclose its intended visible content.
        - If the candidate is clearly worse or does not improve meaningful problems, do not accept it.
        - A candidate may still be acceptable if it materially improves its targeted boxes while remaining major issues are elsewhere.
        - Recommend continued refinement only when major issues remain and another conservative bbox attempt is still worthwhile.
        - Do not propose new bbox coordinates here. Review and termination judgment only.
        - Input roles: image 1 is the ground-truth source image; image 2 is the current overlay; image 3 is the candidate overlay.
        - The overlays are localization evidence only. Prefer visual comparison between the source image and candidate overlay state.
        {memory_rule}

        Output contract:
        - scope must be "layout".
        - candidate_review must describe the candidate overlay only.
        - {SEVERITY_RULE}
        - termination.acceptance_tendency must be accept or reject.
        - termination.stop_tendency must be continue or stop.
        - acceptance should tolerate only minor low-severity residual issues.

        {POLICY_TEXT_RULES}
        """
    ).strip()
    user_prompt = join_prompt_sections(
        textwrap.dedent(
            f"""
            Canvas size:
            width={width}, height={height}
            """
        ),
        textwrap.dedent(
            f"""
            Candidate changed from current:
            {json.dumps(candidate_changed, ensure_ascii=False)}
            """
        ),
        optional_json_block("Current regions", current_regions),
        optional_json_block("Candidate regions", candidate_regions),
        textwrap.dedent(
            """
            Coverage reminder:
            - Prefer candidates whose region union approximately fills the full image extent.
            - Penalize candidates that leave visible content or broad visible layout areas outside every region.
            """
        ),
        optional_json_block("Current worker review and proposal", proposal_result),
        memory_section,
        textwrap.dedent(
            """
            Return this JSON shape:
        {
          "scope": "layout",
          "region_id": "",
          "candidate_review": {
            "overview": "header band is cleaner but footer remains oversized",
            "issues": [
              {
                "target_id": "r2",
                "criterion": "bbox includes unrelated content",
                "reason": "footer band still spills upward",
                "severity": "medium"
              }
            ],
            "needs_adjustment": true
          },
          "termination": {
            "acceptance_tendency": "accept",
            "acceptance_rationale": "Accept if only minor footer spill remains.",
            "stop_tendency": "continue",
            "stop_rationale": "Retry while a meaningful footer issue remains."
          }
        }
        """
        ),
    )
    return system_prompt, user_prompt


def build_recognition_bbox_combined_policy_prompts(
    *,
    region: dict,
    current_objects: list[dict],
    candidate_objects: list[dict],
    proposal_result: dict,
    validation_feedback: list[dict] | None,
    memory_summary: dict | None,
    candidate_changed: bool,
    retry_state: dict | None = None,
) -> tuple[str, str]:
    has_memory = memory_summary is not None
    memory_rule = history_rules_block(has_memory)
    memory_section = history_example_block(has_memory, memory_summary)
    system_prompt = textwrap.dedent(
        f"""
        You are a combined bbox policy advisor for region-recognition object planning.
        You receive three images in order: the region crop, the current bbox overlay, and the candidate bbox overlay.
        Review the candidate object-bbox state, then emit termination tendencies for the supervisor.
        Return JSON only.

        Core policy principles:
        - Focus only on major bbox quality under four acceptance rules: contain the target object, do not cut the target, avoid excessive padding, and avoid obvious off-center placement.
        - Eliminate major problems when possible.
        - Small residual low-severity issues may be accepted.
        - Prefer stable slightly generous candidates over razor-tight boxes; do not penalize moderate empty padding by itself.
        - Including unrelated nearby content is allowed when needed to avoid cutting the target; only excessive avoidable padding should block or continue refinement.
        - For connector-like objects, prioritize full coverage of endpoints, junctions, and connection continuity over tight isolation.
        - For connector-like objects, unavoidable overlap into nearby content or whitespace may be acceptable when needed to preserve the full path.
        - If any bbox edge visibly crosses through the target object's pixels, strokes, glyphs, or endpoints, or sits on top of that content boundary, treat that as a major unresolved issue.
        - Do not accept or stop when text, icon silhouettes, shape strokes, terminal dots, or endpoints are still cut by or pressed against the bbox edge.
        - Do not accept a candidate that still leaves any visible target content outside its bbox.
        - If the candidate is clearly worse or does not improve meaningful problems, do not accept it.
        - A candidate may still be acceptable if it materially improves its targeted objects while remaining major issues are elsewhere.
        - Recommend continued refinement only when major issues remain and another conservative bbox attempt is still worthwhile.
        - Do not add/remove/split/merge objects here. Review and termination judgment only.
        - Input roles: image 1 is the ground-truth region crop; image 2 is the current overlay; image 3 is the candidate overlay.
        - The overlays are localization evidence only. Prefer visual comparison between the crop and candidate overlay state.
        {memory_rule}

        Output contract:
        - scope must be "recognition".
        - region_id must match the current region.
        - candidate_review must describe the candidate overlay only.
        - {SEVERITY_RULE}
        - {BBOX_ISSUE_CODE_RULE}
        - {BBOX_ISSUE_FAMILY_RULE}
        - {BBOX_ISSUE_EDGES_RULE}
        - candidate_review.issues[] must use object_id and issue_family for recognition issues.
        - Do not output canonical_issue_id; the system derives stable ids.
        - termination.acceptance_tendency must be accept or reject.
        - termination.stop_tendency must be continue or stop.
        - acceptance should reject target_not_contained or target_clipped residuals, but may tolerate low-severity excessive_padding or off_center residuals.

        {POLICY_TEXT_RULES}
        """
    ).strip()
    user_prompt = join_prompt_sections(
        json_block("Region", region),
        textwrap.dedent(
            f"""
            Candidate changed from current:
            {json.dumps(candidate_changed, ensure_ascii=False)}
            """
        ),
        optional_json_block("Current recognized objects", current_objects),
        optional_json_block("Candidate recognized objects", candidate_objects),
        optional_json_block("Current worker review and proposal", proposal_result),
        memory_section,
        textwrap.dedent(
            f"""
            Return this JSON shape:
        {{
          "scope": "recognition",
          "region_id": "{region['region_id']}",
          "candidate_review": {{
            "overview": "heading box is improved but still slightly low",
            "issues": [
              {{
                "object_id": "heading_text",
                "issue_family": "off_center",
                "edges": [],
                "criterion": "target is off-center",
                "reason": "text sits slightly low",
                "severity": "low"
              }}
            ],
            "needs_adjustment": true
          }},
          "termination": {{
            "acceptance_tendency": "accept",
            "acceptance_rationale": "Accept if only slight centering drift remains.",
            "stop_tendency": "stop",
            "stop_rationale": "Stop once only minor residual drift remains."
          }}
        }}
        """
        ),
    )
    return system_prompt, user_prompt
