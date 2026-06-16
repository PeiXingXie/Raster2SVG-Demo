"""Overview: Workflow package exposing node mixins for raster-to-SVG execution."""

from deepagents_template.workflow.integrate_process_node import IntegrateProcessNodeMixin
from deepagents_template.workflow.layout_detection_node import LayoutDetectionNodeMixin
from deepagents_template.workflow.object_process_node import ObjectProcessNodeMixin
from deepagents_template.workflow.region_cropping_node import RegionCroppingNodeMixin
from deepagents_template.workflow.region_process_node import RegionProcessNodeMixin


class RasterToSvgNodeMixin(
    LayoutDetectionNodeMixin,
    RegionCroppingNodeMixin,
    ObjectProcessNodeMixin,
    IntegrateProcessNodeMixin,
    RegionProcessNodeMixin,
):
    """Aggregate all workflow node mixins into one pipeline-facing surface."""


__all__ = ["RasterToSvgNodeMixin"]
