"""Convenience container for workflow-local supervisors and workers."""

from __future__ import annotations

from deepagents_template.bbox_refinement import build_object_bbox_refinement_provider

from .supervisors import BboxAdjustmentSupervisorAgent, FusionSupervisorAgent, LayoutPlanningSupervisorAgent, RegionSupervisorAgent


class WorkflowAgentSuite:
    """Convenience container for all workflow-local supervisor/worker agents."""

    def __init__(self, pipeline) -> None:
        self.bbox = BboxAdjustmentSupervisorAgent(pipeline)
        self.object_bbox_refiner = build_object_bbox_refinement_provider(
            pipeline,
            bbox_worker=self.bbox.worker,
        )
        self.layout = LayoutPlanningSupervisorAgent(pipeline)
        self.region = RegionSupervisorAgent(pipeline)
        self.object = self.region.object_supervisor
        self.fusion = FusionSupervisorAgent(pipeline)
