"""Convenience container for workflow-local supervisors and workers."""

from __future__ import annotations

from .supervisors import BboxAdjustmentSupervisorAgent, FusionSupervisorAgent, LayoutPlanningSupervisorAgent, RegionSupervisorAgent


class WorkflowAgentSuite:
    """Convenience container for all workflow-local supervisor/worker agents."""

    def __init__(self, pipeline) -> None:
        self.bbox = BboxAdjustmentSupervisorAgent(pipeline)
        self.layout = LayoutPlanningSupervisorAgent(pipeline)
        self.region = RegionSupervisorAgent(pipeline)
        self.object = self.region.object_supervisor
        self.fusion = FusionSupervisorAgent(pipeline)
