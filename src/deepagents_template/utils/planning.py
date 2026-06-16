"""Overview: Planning helpers for requirements, checklists, and starter region layouts."""

from __future__ import annotations

def summarize_conversion_requirements(user_requirements: str = "") -> dict:
    """Return task-book-aligned conversion goals, priorities, and non-goals."""

    normalized = user_requirements.lower()
    goals = [
        "Keep the overall layout consistent with the raster source.",
        "Preserve major content blocks and keep them editable in SVG.",
        "Represent recognized text as SVG text whenever practical.",
        "Express flowcharts, lines, and diagrams with semantic SVG primitives.",
        "Allow complex imagery to fall back to color-block placeholders when needed.",
    ]
    priorities = [
        "SVG validity and renderability",
        "Global layout fidelity",
        "Major content completeness",
        "Semantic editability",
        "Text preservation",
    ]
    if "chart" in normalized or "鍥捐〃" in user_requirements:
        priorities.append("Approximate chart axes, labels, and data trends.")
    if "flow" in normalized or "娴佺▼" in user_requirements:
        priorities.append("Keep node order, connectors, arrow direction, and labels.")

    return {
        "task_name": "Raster-to-SVG automated conversion agent demo",
        "planner_mode": "Planner + ReAct",
        "goals": goals,
        "priorities": priorities,
        "non_goals": [
            "Pixel-perfect SVG reproduction.",
            "High-fidelity vectorization of photos or QR codes.",
            "Exact restoration of every font, shadow, or gradient.",
        ],
        "user_requirements": user_requirements or "No extra user requirements provided.",
    }


def build_acceptance_checklist(
    user_requirements: str = "",
    *,
    image_metadata: dict | None = None,
) -> list[dict]:
    """Legacy helper kept only as an explicit non-runtime stub."""

    raise NotImplementedError(
        "Checklist generation is model-only in the current pipeline and no local fallback is available."
    )
