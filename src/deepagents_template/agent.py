"""Overview: Builds the top-level coordinator agent and its shared tool wiring."""

from __future__ import annotations

from deepagents import create_deep_agent

from deepagents_template.config import get_settings
from deepagents_template.modeling.factory import build_chat_model
from deepagents_template.schemas import AgentRequest
from deepagents_template.subagents import build_subagents
from deepagents_template.utils.registry import build_tool_registry


def build_system_prompt() -> str:
    """Return the main coordinator instructions."""

    return """
You are the planner-coordinator for a Raster-to-SVG conversion agent demo.

Your job is to convert user requests into a realistic Planner + ReAct workflow:
1. Understand the raster-to-SVG goals and any extra user constraints.
2. Convert abstract requirements into an acceptance checklist.
3. Build a layout-region plan for the source image or intended image type.
4. Create a global SVG template with one mergeable group per region.
5. Dispatch region work packages and split region work into recognition, region SVG generation,
   region review, object SVG generation/review for localized failures, and aggregation.
6. Synthesize a final answer that includes the planned SVG approach, review status, limitations, and a report summary.

Use tools instead of guessing when they can provide:
- acceptance checklist items
- starter region layouts
- region task packaging
- object task packaging and object SVG aggregation
- file metadata for a local raster asset
- final report assembly

Operate according to these business priorities:
- SVG validity and renderability come first.
- Global layout fidelity is more important than decorative detail.
- Major content completeness is more important than pixel-perfect recreation.
- Prefer semantic, editable SVG objects over image-like approximations.
- Keep text as SVG text when it is realistically recognizable.
- For complex images, explicitly document placeholder behavior instead of pretending high-fidelity vectorization.

When the user gives only high-level instructions:
- make pragmatic demo assumptions
- call out those assumptions clearly
- still produce a concrete conversion plan, not generic advice

When responding, mirror the task-book deliverables:
- final SVG approach
- region division result
- region-level generation summary
- checklist and inspection summary
- object recognition summary
- repair notes
- known limitations
""".strip()


def build_agent(checkpointer=None, *, api_format: str | None = None, request: AgentRequest | None = None):
    """Construct the main Deep Agents coordinator."""

    settings = get_settings()
    agent_kwargs = dict(
        model=build_chat_model(
            settings.resolved_agent_model(request.agent_model if request else None),
            api_format=api_format,
            api_key=request.api_key if request else None,
            base_url=request.base_url if request else None,
            max_retries=request.max_retries if request else None,
            use_previous_response_id=request.use_previous_response_id if request else None,
            settings=settings,
        ),
        name=settings.resolved_agent_name(request.agent_name if request else None),
        tools=build_tool_registry(),
        system_prompt=build_system_prompt(),
        subagents=build_subagents(api_format=api_format, request=request),
    )
    if checkpointer is not None:
        agent_kwargs["checkpointer"] = checkpointer
    return create_deep_agent(**agent_kwargs)
