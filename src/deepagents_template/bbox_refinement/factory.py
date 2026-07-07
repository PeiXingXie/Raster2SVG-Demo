"""Factory helpers for issue-level object bbox refinement providers."""

from __future__ import annotations

from deepagents_template.bbox_refinement.providers import (
    HybridRecognitionBboxRefiner,
    LLMRecognitionBboxRefiner,
    SamLocalRecognitionBboxRefiner,
    SamRemoteRecognitionBboxRefiner,
)


def build_object_bbox_refinement_provider(pipeline, *, bbox_worker):
    """Build the configured refinement provider for recognition-stage object bboxes."""

    llm_refiner = LLMRecognitionBboxRefiner(bbox_worker)
    mode = getattr(pipeline, "recognition_bbox_refine_mode", "llm")
    sam_provider_mode = getattr(pipeline, "sam_provider_mode", "remote")
    sam_enabled = bool(getattr(pipeline, "sam_enabled", False))
    sam_fallback_to_llm = bool(getattr(pipeline, "sam_fallback_to_llm", True))
    sam_remote_url = getattr(pipeline, "sam_remote_url", None)

    if not sam_enabled or mode == "llm":
        return llm_refiner

    sam_refiner = (
        SamLocalRecognitionBboxRefiner()
        if sam_provider_mode == "local"
        else SamRemoteRecognitionBboxRefiner(remote_url=sam_remote_url)
    )
    if mode == "sam" and not sam_fallback_to_llm:
        return sam_refiner
    if mode == "sam":
        return HybridRecognitionBboxRefiner(primary_refiner=sam_refiner, fallback_refiner=llm_refiner)
    if mode == "hybrid":
        return HybridRecognitionBboxRefiner(primary_refiner=sam_refiner, fallback_refiner=llm_refiner)
    return llm_refiner
