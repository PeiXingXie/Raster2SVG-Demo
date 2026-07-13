"""Overview: Prompt builders for image-level layout detection and region planning."""

from __future__ import annotations

import textwrap

from deepagents_template.prompt.bbox_conventions import BBOX_COORDINATE_CONVENTION_RULE


def build_layout_detection_prompts(
    *,
    width: int,
    height: int,
) -> tuple[str, str]:
    system_prompt = textwrap.dedent(
        f"""
        You are a multimodal layout detection planner for raster-to-SVG conversion.
        Analyze the full image and return a region split plan.
        Return JSON only.

        Rules:

        1. Overall goal
        - Produce the weakest region split that still supports accurate reconstruction.
        - Region granularity must support stable downstream recognition, SVG generation, and repair, not just a plausible visual grouping.
        - Decide region granularity from the overall image complexity, structural diversity, and independence of content groups.
        - Do not split just for the sake of splitting.

        2. Granularity and split strength
        - First judge the image complexity as simple, moderate, or complex.
        - Then judge the split strength as minimal, moderate, or strong.
        - Simple images with one coherent composition should usually use a minimal split, often a single region.
        - Increase the number of regions only when there are clearly independent panels, sections, zones, or content groups that benefit from separate reconstruction.
        - If one very large region would force many independent editable objects into one crowded crop, prefer a moderate split along strong structural boundaries.
        - Repeated card grids, stacked horizontal bands, independent headers/footers, sidebars, and detached summary bars often benefit from separate regions when they are visually and semantically distinct.
        - Do not over-segment closely related content, and do not create trivial fragments around isolated labels, icons, or small local shapes.
        - Do not equate "whole image looks coherent" with "must be one region"; choose the weakest split that still makes downstream editing stable.

        3. Type-adaptive defaults
        - Natural photos, single logos/icons, and single cohesive charts usually prefer a minimal split.
        - Multi-panel figures, dashboards, infographics, slide-like card layouts, or document pages with independent header/footer/sidebar zones may require a moderate split.
        - Use strong splitting only when the image truly contains several mostly independent sections that would be awkward to reconstruct together.

        4. Region quality
        - Each region must stay inside the canvas.
        - Regions should be semantically meaningful, self-contained content groups, not tiny fragments.
        - Region boxes should be chosen so the main content is reasonably centered and not awkwardly clipped.
        - Small overlap between adjacent regions is allowed when it prevents important content from being cut at the boundary.
        - Avoid large redundant overlap or duplicate coverage of the same main content.
        - Prefer splitting along strong visual separators such as panel borders, row bands, columns, gutters, header/footer boundaries, or clearly detached bars.
        - Do not split based only on whitespace texture, tiny decorations, or weak local saliency.

        5. Coverage and completeness
        - Regions should collectively cover the full source image.
        - Treat near-full-image coverage as a hard preference: the union of all region boxes should approximately fill the entire image.
        - Do not leave meaningful content, visible decorative content, or broad visible canvas/background areas uncovered.
        - If multiple regions are used, their union should still account for the whole composition, including margins, headers, footers, side bands, and background areas whenever they participate in the visible layout.
        - When unsure, prefer weak broad coverage over narrow salient-object-only coverage.

        6. Output requirements
        - Start with an overview of the complete image.
        - After the overview, output a brief complexity assessment and split rationale before listing regions.
        - {BBOX_COORDINATE_CONVENTION_RULE}
        - Do not output priority or status.
        """
    ).strip()
    user_prompt = textwrap.dedent(
        f"""
        Canvas size:
        width={width}, height={height}

        Region planning guidance:
        - First assess the overall image complexity and how strong the split should be.
        - Prefer the minimum number of regions that preserves meaningful independent structure and stable downstream editability.
        - If the image behaves as one coherent composition, return one region rather than several local crops.
        - Use multiple regions only when they correspond to clearly separable structures or when one large region would crowd many independent editable units together.
        - Split only along strong boundaries such as panels, rows, columns, headers, footers, sidebars, or detached bars.
        - Avoid fragmenting small labels, icons, or decorations into their own regions.
        - Make sure the final set of regions covers the complete image composition rather than only the most salient objects.
        - The union of all region boxes should approximately fill the full image extent so every visible element is considered somewhere.

        Return this JSON shape:
        {{
          "canvas_width": {width},
          "canvas_height": {height},
          "overview": "complete image overview before region details",
          "complexity_assessment": {{
            "complexity": "simple",
            "split_strength": "minimal",
            "rationale": "brief reason for the chosen split granularity"
          }},
          "regions": [
            {{
              "region_id": "r1",
              "bbox": {{"x": 0, "y": 0, "width": 1200, "height": 100}},
              "description": "what is in this layout region"
            }}
          ]
        }}
        """
    ).strip()
    return system_prompt, user_prompt
