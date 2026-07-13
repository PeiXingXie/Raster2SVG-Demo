"""Overview: Prompt builders for image-aware checklist planning."""

from __future__ import annotations

import json
import textwrap

from deepagents_template.checklist import CHECKLIST_STAGE_BUDGETS
from deepagents_template.geometry import compact_regions_for_prompt
from deepagents_template.utils.prompting import json_output_contract


def build_checklist_plan_prompts(
    *,
    user_request: str,
    layout_overview: str,
    regions: list[dict],
) -> tuple[str, str]:
    budgets = dict(CHECKLIST_STAGE_BUDGETS)
    system_prompt = textwrap.dedent(
        f"""
        You are a raster-to-SVG acceptance planner.
        Build stage-specific acceptance checklists for the downstream pipeline.
        Return JSON only.

        Core definition:
        - Checklist items are high-level semantic and intent constraints.
        - They are acceptance rules, not execution plans or repair instructions.
        - Keep focus on major issues and ignore low-value visual detail.

        Stage 1: element presence
        - For every region, output Y/N for whether each element type exists:
          background, icon, text, container, connector, diagram, fig.
        - Each element_presence flag must be exactly "Y" or "N".

        Stage 2: checklist planning
        - Produce three checklist sections:
          recognition, generation_refine, fusion.
        - recognition covers visible element-type coverage, semantic grouping, major structural roles, and visual-form fidelity hints for symbols/icons.
        - generation_refine covers region reconstruction acceptance after generation and refinement.
        - fusion covers merged-result consistency, continuity, and seam-free composition.

        Scope rules:
        - scope="common": applies to all relevant regions inside that stage.
        - scope="region": applies to one specific region only.
        - common and region are parallel range labels, not hierarchy levels.
        - scope must be exactly "common" or "region".

        Region-scope rules:
        - region items may express object-type constraints.
        - region items must not express object-instance constraints.
        - Allowed: icon recognizability, symbol/icon visual-form fidelity, text-role preservation, container framing, connector directionality.
        - Not allowed: left icon vs right icon, exact icon pairs, exact object combinations, exact text strings.
        - Region criteria should remain reusable across similar regions; name the object type or semantic role, not a specific depicted subject.
        - Prefer generic criteria such as "Keep icons recognizable and semantically faithful." over subject-specific forms such as "Keep AI icons recognizable."
        - For regions containing symbols/icons, include recognition and generation_refine coverage for visible-form fidelity, not only semantic category.
        - Visual-form fidelity criteria should stay generic and high-level, such as preserving symbols' visible form, distinctive structure, and visual style.

        Coverage rules:
        - If an element type is marked Y in a region, the relevant stage checklist must include
          at least one correctly scoped applicable constraint for that type.
        - Prefer common when the same type-level requirement applies across regions.
        - Do not over-focus on text; balance coverage across visible icons, text, containers,
          backgrounds, connectors, diagrams, and figures according to semantic importance.

        Writing rules:
        - Keep item_id values stable and sequential, such as C1, C2, C3.
        - Criterion must be imperative, clear, non-overlapping, and under 15 words.
        - Do not write object-instance checks, exact text snippets, bbox values, or tiny visual details.
        - For symbols/icons, visible-form fidelity is a recognition and generation acceptance concern.
        - Criterion should describe the acceptance rule itself, not a concrete object in this one image.
        - Prefer one main idea per criterion.
        - Use a minimalist checklist style: cover major semantics and structure, and ignore low-value detail.
        - When several candidate checks overlap, keep the broader and more reusable one.
        - Prefer "grab the big picture and let go of minor polish" over exhaustive coverage.

        Budget rules:
        - recognition: at most {budgets["recognition"]["common"]} common items, {budgets["recognition"]["region"]} region items per region, {budgets["recognition"]["total"]} total.
        - generation_refine: at most {budgets["generation_refine"]["common"]} common items, {budgets["generation_refine"]["region"]} region items per region, {budgets["generation_refine"]["total"]} total.
        - fusion: at most {budgets["fusion"]["common"]} common items and {budgets["fusion"]["total"]} total.
        - Overall total checklist items must stay within {budgets["total"]}.
        {json_output_contract(
            required_fields=("element_presence", "checklists"),
            array_fields=(
                "element_presence",
                "checklists.recognition.common",
                "checklists.generation_refine.common",
                "checklists.fusion.common",
            ),
            closed_value_fields={
                "element_presence[].background": ("Y", "N"),
                "element_presence[].icon": ("Y", "N"),
                "element_presence[].text": ("Y", "N"),
                "element_presence[].container": ("Y", "N"),
                "element_presence[].connector": ("Y", "N"),
                "element_presence[].diagram": ("Y", "N"),
                "element_presence[].fig": ("Y", "N"),
                "checklists.*.common[].scope": ("common", "region"),
                "checklists.*.regions[*][].scope": ("common", "region"),
            },
        )}
        """
    ).strip()
    user_prompt = textwrap.dedent(
        f"""
        User instruction:
        {user_request}

        Layout overview:
        {layout_overview}

        Regions:
        {json.dumps(compact_regions_for_prompt(regions), ensure_ascii=False, indent=2)}

        Return this JSON shape:
        {{
          "element_presence": [
            {{"region_id": "r1_header", "background": "Y", "icon": "N", "text": "Y", "container": "N", "connector": "N", "diagram": "N", "fig": "N"}}
          ],
          "checklists": {{
            "recognition": {{
              "common": [
                {{
                  "item_id": "C1",
                  "scope": "common",
                  "criterion": "Cover all visible major element types."
                }},
                {{
                  "item_id": "C2",
                  "scope": "common",
                  "criterion": "Record visual-form fidelity for symbols."
                }}
              ],
              "regions": {{
                "r1_header": [
                  {{
                    "item_id": "C3",
                    "scope": "region",
                    "criterion": "Preserve text as a distinct information element."
                  }}
                ]
              }}
            }},
            "generation_refine": {{
              "common": [
                {{
                  "item_id": "C4",
                  "scope": "common",
                  "criterion": "Preserve major semantic grouping and layout hierarchy."
                }}
              ],
              "regions": {{
                "r1_header": [
                  {{
                    "item_id": "C5",
                    "scope": "region",
                    "criterion": "Keep icons recognizable and semantically faithful."
                  }},
                  {{
                    "item_id": "C6",
                    "scope": "region",
                    "criterion": "Preserve symbols' visible form, structure, and style."
                  }}
                ]
              }}
            }},
            "fusion": {{
              "common": [
                {{
                  "item_id": "C7",
                  "scope": "common",
                  "criterion": "Keep merged region boundaries continuous and artifact-free."
                }}
              ],
              "regions": {{}}
            }}
          }}
        }}
        """
    ).strip()
    return system_prompt, user_prompt
