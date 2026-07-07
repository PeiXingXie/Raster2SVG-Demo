"""Object-bbox refinement providers used after region recognition."""

from deepagents_template.bbox_refinement.factory import build_object_bbox_refinement_provider
from deepagents_template.bbox_refinement.providers import (
    HybridRecognitionBboxRefiner,
    LLMRecognitionBboxRefiner,
    SamLocalRecognitionBboxRefiner,
    SamRemoteRecognitionBboxRefiner,
)

__all__ = [
    "build_object_bbox_refinement_provider",
    "HybridRecognitionBboxRefiner",
    "LLMRecognitionBboxRefiner",
    "SamLocalRecognitionBboxRefiner",
    "SamRemoteRecognitionBboxRefiner",
]
