"""Backward-compatible exports for workflow orchestration classes."""

from deepagents_template.workflow_orchestration import (
    BaseWorkflowAgent,
    BboxAdjustmentSupervisorAgent,
    BboxAdjustmentWorkerAgent,
    FusionSupervisorAgent,
    IntegratedSvgRepairWorkerAgent,
    LayoutPlanningSupervisorAgent,
    ObjectRepairSupervisorAgent,
    RegionRecognitionWorkerAgent,
    RegionSupervisorAgent,
    RegionSvgWorkerAgent,
    WorkflowAgentSuite,
)

__all__ = [
    "BaseWorkflowAgent",
    "BboxAdjustmentSupervisorAgent",
    "BboxAdjustmentWorkerAgent",
    "FusionSupervisorAgent",
    "IntegratedSvgRepairWorkerAgent",
    "LayoutPlanningSupervisorAgent",
    "ObjectRepairSupervisorAgent",
    "RegionRecognitionWorkerAgent",
    "RegionSupervisorAgent",
    "RegionSvgWorkerAgent",
    "WorkflowAgentSuite",
]
