"""BBox policy engine built from a candidate-judgement model call plus hard-rule reconciliation."""

from __future__ import annotations

import hashlib
from pathlib import Path

from deepagents_template.prompt import (
    build_layout_bbox_combined_policy_prompts,
    build_recognition_bbox_combined_policy_prompts,
)
from deepagents_template.schemas import BboxAdjustmentResult, BboxPolicyDecision, BboxSupervisorMemory

from .failures import fail_policy_evaluation
from .rules import (
    apply_bbox_combined_policy_rules,
    build_bbox_memory_summary,
)
from .tracing import build_policy_trace


def compact_bbox_iteration_label(iteration: str) -> str:
    """Return a filesystem-safe short label for bbox policy trace filenames."""

    text = str(iteration).strip()
    if not text:
        return "0"
    normalized = text.replace(":", "_").replace("/", "_").replace("\\", "_").replace(" ", "_")
    normalized = "_".join(part for part in normalized.split("_") if part)
    if len(normalized) <= 24:
        return normalized
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"{normalized[:15]}_{digest}"


class BboxPolicyEngine:
    """Unified bbox policy engine: one candidate-judgement model call plus hard-rule reconciliation."""

    def __init__(self, pipeline, *, combined_worker) -> None:
        self.pipeline = pipeline
        self.combined_worker = combined_worker

    def _policy_dir(self, *, scope: str, region_dir: Path | None = None) -> Path:
        if scope == "layout":
            policy_dir = self.pipeline.root_intermediate_dir / "policy"
        else:
            assert region_dir is not None
            policy_dir = region_dir / "policy"
        policy_dir.mkdir(parents=True, exist_ok=True)
        return policy_dir

    def evaluate(
        self,
        *,
        scope: str,
        proposal: BboxAdjustmentResult,
        memory: BboxSupervisorMemory,
        retry_exhausted: bool,
        iteration: str,
        copied_input_path: Path | None = None,
        crop_path: Path | None = None,
        current_overlay_path: Path,
        candidate_overlay_path: Path,
        width: int | None = None,
        height: int | None = None,
        current_regions: list[dict] | None = None,
        candidate_regions: list[dict] | None = None,
        region: dict | None = None,
        current_objects: list[dict] | None = None,
        candidate_objects: list[dict] | None = None,
        validation_feedback: list[dict] | None = None,
        candidate_changed: bool = False,
        region_dir: Path | None = None,
    ) -> BboxPolicyDecision:
        pipeline_use_memory = getattr(self.pipeline, "use_supervisor_memory", None)
        use_memory = bool(pipeline_use_memory()) if callable(pipeline_use_memory) else bool(
            getattr(self.pipeline, "supervisor_memory_enabled", False)
        )
        memory_summary = build_bbox_memory_summary(memory) if use_memory else None
        history_delta_used = memory_summary is not None
        request_context = {
            "scope": scope,
            "proposal": proposal.model_dump(mode="json"),
            "candidate_changed": candidate_changed,
        }
        if memory_summary is not None:
            request_context["memory_delta"] = memory_summary
        policy_name = f"bbox-{scope}-combined-policy"
        trace_label = compact_bbox_iteration_label(iteration)
        trace_path = self._policy_dir(scope=scope, region_dir=region_dir) / f"bbox_policy_{trace_label}.json"
        raw_response: str | None = None
        if scope == "layout":
            assert copied_input_path is not None
            assert width is not None and height is not None
            system_prompt, user_prompt = build_layout_bbox_combined_policy_prompts(
                width=width,
                height=height,
                current_regions=current_regions or [],
                candidate_regions=candidate_regions or [],
                proposal_result=proposal.model_dump(mode="json"),
                memory_summary=memory_summary,
                candidate_changed=candidate_changed,
            )
            llm_request = {"system_prompt": system_prompt, "user_prompt": user_prompt}
            try:
                proposed, raw_response = self.combined_worker.run_layout(
                    copied_input_path=copied_input_path,
                    current_overlay_path=current_overlay_path,
                    candidate_overlay_path=candidate_overlay_path,
                    width=width,
                    height=height,
                    current_regions=current_regions or [],
                    candidate_regions=candidate_regions or [],
                    proposal_result=proposal.model_dump(mode="json"),
                    memory_summary=memory_summary,
                    candidate_changed=candidate_changed,
                )
            except Exception as exc:
                fail_policy_evaluation(
                    self.pipeline,
                    trace_path=trace_path,
                    policy_name=policy_name,
                    request_context=request_context,
                    llm_request=llm_request,
                    exc=exc,
                    raw_response=raw_response,
                    supervisor_memory_used=use_memory,
                    history_delta_used=history_delta_used,
                )
        else:
            assert crop_path is not None
            assert region is not None
            system_prompt, user_prompt = build_recognition_bbox_combined_policy_prompts(
                region=region,
                current_objects=current_objects or [],
                candidate_objects=candidate_objects or [],
                proposal_result=proposal.model_dump(mode="json"),
                validation_feedback=[],
                memory_summary=memory_summary,
                candidate_changed=candidate_changed,
            )
            llm_request = {"system_prompt": system_prompt, "user_prompt": user_prompt}
            try:
                proposed, raw_response = self.combined_worker.run_recognition(
                    crop_path=crop_path,
                    current_overlay_path=current_overlay_path,
                    candidate_overlay_path=candidate_overlay_path,
                    region=region,
                    current_objects=current_objects or [],
                    candidate_objects=candidate_objects or [],
                    proposal_result=proposal.model_dump(mode="json"),
                    validation_feedback=[],
                    memory_summary=memory_summary,
                    candidate_changed=candidate_changed,
                )
            except Exception as exc:
                fail_policy_evaluation(
                    self.pipeline,
                    trace_path=trace_path,
                    policy_name=policy_name,
                    request_context=request_context,
                    llm_request=llm_request,
                    exc=exc,
                    raw_response=raw_response,
                    supervisor_memory_used=use_memory,
                    history_delta_used=history_delta_used,
                )

        final_decision, applied_rules = apply_bbox_combined_policy_rules(
            proposal=proposal,
            combined=proposed,
            memory=memory,
            retry_exhausted=retry_exhausted,
        )
        trace = build_policy_trace(
            policy_name=policy_name,
            request_context=request_context,
            llm_request=llm_request,
            raw_response=raw_response,
            proposed_decision=proposed.model_dump(mode="json"),
            final_decision=final_decision.model_dump(mode="json"),
            applied_rules=applied_rules,
            fallback_used=False,
            error=None,
            error_type=None,
            supervisor_memory_used=use_memory,
            supervisor_memory_persisted=(
                bool(self.pipeline.persist_supervisor_memory())
                if callable(getattr(self.pipeline, "persist_supervisor_memory", None))
                else bool(getattr(self.pipeline, "supervisor_memory_persist_enabled", False))
            ),
            history_delta_used=history_delta_used,
        )
        self.pipeline._write_json(trace_path, trace)
        return final_decision
