"""Overview: Central registry describing and exporting agent-callable utility functions."""

from __future__ import annotations

from deepagents_template.utils.assets import inspect_local_raster_asset
from deepagents_template.utils.planning import (
    summarize_conversion_requirements,
)
from deepagents_template.utils.reports import assemble_conversion_report
from deepagents_template.utils.svg_runtime import aggregate_object_svg_fragments
from deepagents_template.utils.svg_templates import build_svg_template
from deepagents_template.utils.tasks import create_object_task, create_region_task


def list_available_tools() -> list[dict[str, str]]:
    """Describe the raster-to-SVG tool surface available to the agent."""

    return [
        {"name": "summarize_conversion_requirements", "purpose": "Map a user request to task-book-aligned conversion goals and priorities."},
        {"name": "build_svg_template", "purpose": "Generate the global SVG scaffold with per-region groups and shared defs."},
        {"name": "create_region_task", "purpose": "Package one region into a ReAct-style worker task with retry-aware checks."},
        {"name": "create_object_task", "purpose": "Package one recognized object for localized SVG generation or repair."},
        {"name": "aggregate_object_svg_fragments", "purpose": "Merge region-level and object-level SVG fragments into one region fragment."},
        {"name": "inspect_local_raster_asset", "purpose": "Read basic local raster metadata from a provided image path."},
        {"name": "assemble_conversion_report", "purpose": "Build the final summary report matching the task-book output shape."},
    ]


def build_tool_registry() -> list:
    """Return the tool list used by the coordinator and child agents."""

    return [
        summarize_conversion_requirements,
        build_svg_template,
        create_region_task,
        create_object_task,
        aggregate_object_svg_fragments,
        inspect_local_raster_asset,
        assemble_conversion_report,
        list_available_tools,
    ]
