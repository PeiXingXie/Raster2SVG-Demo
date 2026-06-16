"""Overview: Prompt builders for bbox quality review and correction."""

from __future__ import annotations

import json
import textwrap


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
        "- Supervisor memory delta and execution constraints are historical hints only. "
        "They must not override current visual evidence."
        if enabled
        else "- Execution constraints are operational hints only. They must not override current visual evidence."
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


def build_layout_bbox_adjustment_prompts(
    *,
    width: int,
    height: int,
    regions: list[dict],
    memory_summary: dict | None,
    retry_state: dict,
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
    user_prompt = textwrap.dedent(
        f"""
        Canvas size:
        width={width}, height={height}

        Current regions:
        {json.dumps(regions, ensure_ascii=False, indent=2)}

        Layout coverage reminder:
        - The adjusted region set should approximately fill the full image extent as a union.
        - Do not optimize only for salient local objects while leaving visible areas outside every region.
        - Prefer a region plan that will make downstream object recognition and repair stable across many image types.

        {memory_section}

        Execution constraints:
        {json.dumps(retry_state, ensure_ascii=False, indent=2)}

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
    ).strip()
    return system_prompt, user_prompt


def build_recognition_bbox_adjustment_prompts(
    *,
    region: dict,
    recognized_objects: list[dict],
    validation_feedback: list[dict] | None,
    memory_summary: dict | None,
    retry_state: dict,
) -> tuple[str, str]:
    has_memory = memory_summary is not None
    memory_rule = history_rules_block(has_memory)
    memory_section = history_example_block(has_memory, memory_summary)
    system_prompt = textwrap.dedent(
        f"""
        You are a bbox quality worker for region-recognition object planning.
        You receive two images in order: the region crop, then the current object-bbox overlay.
        Review object bbox spatial quality and, when helpful, propose one conservative adjustment attempt.
        Return JSON only.

        Core scope:
        - Focus only on bbox spatial quality: centering, obvious overreach, missing object content, clipping, and unrelated-content inclusion.
        - Catch big problems, not tiny edge padding details.
        - Prefer stable slightly generous boxes over razor-tight boxes; moderate empty padding is acceptable and often desirable.
        - Allow some empty margin when it prevents clipping, preserves labels, or avoids retry churn.
        - Prefer boxes with a small but clear safety margin on all sides; do not keep bbox edges pressed tightly against the content.
        - Every object bbox must completely surround the target content it refers to; the bbox border must not lie on top of the target's visible pixels, strokes, glyphs, dots, or endpoints.
        - If a bbox edge overlaps the target content boundary or leaves any visible target content outside the box, treat that as a major issue.
        - Prefer editing existing bbox coordinates of recognized objects.
        - Do not add objects, remove objects, split objects, or merge objects.
        - Do not repeat object metadata that is unchanged; return bbox updates only.
        - Object bboxes are crop-local coordinates inside the region crop.
        - Bboxes should keep the object reasonably centered while avoiding unrelated nearby content when possible.
        - If structured validation feedback is provided, treat it as acceptance evidence about which bbox edges still overlap visible content.
        - Use validation feedback to decide which edges should move outward or inward, but still verify against the images.
        - This worker is batch-limited. When many objects need changes, choose only the highest-priority subset for this attempt.
        - Prioritize objects with severe clipping, strong validation failures, text truncation, connector endpoint loss, or large visible border overlap.
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
        - strategy_enabled should be true only when one concise strategy label meaningfully explains the proposed adjustment.
        - strategy_label should summarize the intended bbox move family, not execution details.
        - strategy_confidence must be exactly "low", "medium", or "high" as a JSON string. Never return numeric scores or percentages.
        - target_ids should list only the main objects being adjusted.
        - target_ids may contain at most 6 object ids. If more than 6 objects need changes, pick only the 6 highest-priority failures for this attempt.
        - adjusted_object_bboxes must include only changed or reasserted bbox updates as {{target_id, bbox}} items.
        - adjusted_object_bboxes may contain at most 12 items.
        - Do not mention deferred, omitted, remaining, or future objects inside target_ids or adjusted_object_bboxes; this output is only the current batch.
        - Never include chain-of-thought, reasoning text, or any text outside the JSON object.
        - When no worthwhile change is needed, set needs_adjustment=false, adjustment_type="none", and leave adjusted_object_bboxes empty.

        {TEXT_RULES}
        """
    ).strip()
    user_prompt = textwrap.dedent(
        f"""
        Region:
        {json.dumps(region, ensure_ascii=False, indent=2)}

        Current recognized objects:
        {json.dumps(recognized_objects, ensure_ascii=False, indent=2)}

        Validation feedback from bbox acceptance checks:
        {json.dumps(validation_feedback or [], ensure_ascii=False, indent=2)}

        {memory_section}

        Execution constraints:
        {json.dumps(retry_state, ensure_ascii=False, indent=2)}

        Return this JSON shape:
        {{
          "scope": "recognition",
          "region_id": "{region['region_id']}",
          "overview": "title and subtitle box clips the lower text",
          "issues": [
            {{
              "target_id": "title_system",
              "criterion": "bbox clips visible content",
              "reason": "subtitle falls below the box",
              "severity": "high"
            }}
          ],
          "adjustment_type": "expand_for_missing_content",
          "target_ids": ["title_system"],
          "adjusted_regions": [],
          "adjusted_object_bboxes": [
            {{
              "target_id": "title_system",
              "bbox": {{"x": 24, "y": 12, "width": 280, "height": 96}}
            }}
          ],
          "strategy_enabled": true,
          "strategy_label": "expand_title_system",
          "strategy_rationale": "Recover the clipped subtitle as one block.",
          "strategy_confidence": "high",
          "changes_applied": ["expanded title_system downward"],
          "needs_adjustment": true
        }}
        """
    ).strip()
    return system_prompt, user_prompt


def build_layout_bbox_combined_policy_prompts(
    *,
    width: int,
    height: int,
    current_regions: list[dict],
    candidate_regions: list[dict],
    proposal_result: dict,
    memory_summary: dict | None,
    retry_state: dict,
    candidate_changed: bool,
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
        - Do not consider retry budget. The supervisor will enforce retry limits separately.
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
    user_prompt = textwrap.dedent(
        f"""
        Canvas size:
        width={width}, height={height}

        Candidate changed from current:
        {json.dumps(candidate_changed, ensure_ascii=False)}

        Current regions:
        {json.dumps(current_regions, ensure_ascii=False, indent=2)}

        Candidate regions:
        {json.dumps(candidate_regions, ensure_ascii=False, indent=2)}

        Coverage reminder:
        - Prefer candidates whose region union approximately fills the full image extent.
        - Penalize candidates that leave visible content or broad visible layout areas outside every region.

        Current worker review and proposal:
        {json.dumps(proposal_result, ensure_ascii=False, indent=2)}

        {memory_section}

        Execution constraints:
        {json.dumps(retry_state, ensure_ascii=False, indent=2)}

        Return this JSON shape:
        {{
          "scope": "layout",
          "region_id": "",
          "candidate_review": {{
            "overview": "header band is cleaner but footer remains oversized",
            "issues": [
              {{
                "target_id": "r2",
                "criterion": "bbox includes unrelated content",
                "reason": "footer band still spills upward",
                "severity": "medium"
              }}
            ],
            "needs_adjustment": true
          }},
          "termination": {{
            "acceptance_tendency": "accept",
            "acceptance_rationale": "Accept if only minor footer spill remains.",
            "stop_tendency": "continue",
            "stop_rationale": "Retry while a meaningful footer issue remains."
          }}
        }}
        """
    ).strip()
    return system_prompt, user_prompt


def build_recognition_bbox_combined_policy_prompts(
    *,
    region: dict,
    current_objects: list[dict],
    candidate_objects: list[dict],
    proposal_result: dict,
    validation_feedback: list[dict] | None,
    memory_summary: dict | None,
    retry_state: dict,
    candidate_changed: bool,
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
        - Focus only on major bbox quality: clipping, missing object content, overreach into unrelated nearby content, and obvious off-center placement.
        - Eliminate major problems when possible.
        - Small residual low-severity issues may be accepted.
        - Prefer stable slightly generous candidates over razor-tight boxes; do not penalize moderate empty padding by itself.
        - For connector-like objects, prioritize full coverage of endpoints, junctions, and connection continuity over tight isolation.
        - For connector-like objects, unavoidable overlap into nearby content or whitespace may be acceptable when needed to preserve the full path.
        - If any bbox edge visibly crosses through the target object's pixels, strokes, glyphs, or endpoints, or sits on top of that content boundary, treat that as a major unresolved issue.
        - Do not accept or stop when text, icon silhouettes, shape strokes, terminal dots, or endpoints are still cut by or pressed against the bbox edge.
        - Do not accept a candidate that still leaves any visible target content outside its bbox.
        - If structured validation feedback reports unresolved edge overlap or clipping on a candidate bbox, treat that as strong rejection evidence unless the feedback is clearly contradicted by the images.
        - If the candidate is clearly worse or does not improve meaningful problems, do not accept it.
        - A candidate may still be acceptable if it materially improves its targeted objects while remaining major issues are elsewhere.
        - Recommend continued refinement only when major issues remain and another conservative bbox attempt is still worthwhile.
        - Do not add/remove/split/merge objects here. Review and termination judgment only.
        - Do not consider retry budget. The supervisor will enforce retry limits separately.
        - Input roles: image 1 is the ground-truth region crop; image 2 is the current overlay; image 3 is the candidate overlay.
        - The overlays are localization evidence only. Prefer visual comparison between the crop and candidate overlay state.
        {memory_rule}

        Output contract:
        - scope must be "recognition".
        - region_id must match the current region.
        - candidate_review must describe the candidate overlay only.
        - {SEVERITY_RULE}
        - termination.acceptance_tendency must be accept or reject.
        - termination.stop_tendency must be continue or stop.
        - acceptance should tolerate only minor low-severity residual issues.

        {POLICY_TEXT_RULES}
        """
    ).strip()
    user_prompt = textwrap.dedent(
        f"""
        Region:
        {json.dumps(region, ensure_ascii=False, indent=2)}

        Candidate changed from current:
        {json.dumps(candidate_changed, ensure_ascii=False)}

        Current recognized objects:
        {json.dumps(current_objects, ensure_ascii=False, indent=2)}

        Candidate recognized objects:
        {json.dumps(candidate_objects, ensure_ascii=False, indent=2)}

        Current worker review and proposal:
        {json.dumps(proposal_result, ensure_ascii=False, indent=2)}

        Validation feedback from bbox acceptance checks:
        {json.dumps(validation_feedback or [], ensure_ascii=False, indent=2)}

        {memory_section}

        Execution constraints:
        {json.dumps(retry_state, ensure_ascii=False, indent=2)}

        Return this JSON shape:
        {{
          "scope": "recognition",
          "region_id": "{region['region_id']}",
          "candidate_review": {{
            "overview": "title box is improved but still slightly low",
            "issues": [
              {{
                "target_id": "title_system",
                "criterion": "content is off-center",
                "reason": "text block still sits low",
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
    ).strip()
    return system_prompt, user_prompt
