"""Overview: Builds specialized planning and region-worker subagents for the coordinator."""

from __future__ import annotations

from deepagents import CompiledSubAgent
from langchain.agents import create_agent

from deepagents_template.config import get_settings
from deepagents_template.modeling.factory import build_chat_model
from deepagents_template.schemas import AgentRequest, RegionExecutionNote, RequirementPlan
from deepagents_template.utils.registry import build_tool_registry


def build_subagents(*, api_format: str | None = None, request: AgentRequest | None = None) -> list:
    """Build the specialized subagents used by the coordinator."""

    settings = get_settings()
    model = build_chat_model(
        settings.resolved_subagent_model(request.subagent_model if request else None),
        api_format=api_format,
        api_key=request.api_key if request else None,
        base_url=request.base_url if request else None,
        max_retries=request.max_retries if request else None,
        use_previous_response_id=request.use_previous_response_id if request else None,
        settings=settings,
    )
    shared_tools = build_tool_registry()

    planning_subagent = {
        "name": "requirement-planner",
        "description": "Turns raster-to-SVG requests into goals, checklists, and region strategies.",
        "system_prompt": (
            "You are a requirement planning specialist for a raster-to-SVG conversion demo. "
            "Translate user intent into acceptance criteria, planning assumptions, and a concrete "
            "region-processing strategy aligned with the Planner + ReAct workflow."
        ),
        "tools": shared_tools,
        "model": model,
        "response_format": RequirementPlan,
    }

    region_worker_graph = create_agent(
        model=model,
        tools=shared_tools,
        system_prompt=(
            "You are a region worker in a raster-to-SVG pipeline. "
            "Focus on one region at a time: first recognize objects, then plan region-level SVG, "
            "separate whole-region review failures from object-scoped failures, use object-level "
            "generation/review for localized fixes, and describe how object fragments aggregate "
            "back into the region SVG."
        ),
        response_format=RegionExecutionNote,
    )
    region_worker = CompiledSubAgent(
        name="region-worker",
        description="Plans recognition, SVG generation, checking, and repair for a single region.",
        runnable=region_worker_graph,
    )

    return [planning_subagent, region_worker]
