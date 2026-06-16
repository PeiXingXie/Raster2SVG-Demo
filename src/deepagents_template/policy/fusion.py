"""Fusion-level policy engine built from a combined policy-model call plus hard-rule reconciliation."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from deepagents_template.prompt import build_fusion_combined_policy_prompts
from deepagents_template.schemas import FusionPolicyDecision, FusionSupervisorMemory

from .failures import fail_policy_evaluation
from .rules import (
    apply_fusion_combined_policy_rules,
    build_fusion_memory_summary,
)
from .tracing import build_policy_trace

if TYPE_CHECKING:
    from deepagents_template.conversion import RasterToSvgPipeline
    from deepagents_template.workflow_orchestration.workers import FusionCombinedPolicyModelWorker


class FusionPolicyEngine:
    """Unified fusion policy engine: one model call plus hard-rule reconciliation."""

    def __init__(
        self,
        pipeline: RasterToSvgPipeline,
        *,
        combined_worker: FusionCombinedPolicyModelWorker,
    ) -> None:
        self.pipeline = pipeline
        self.combined_worker = combined_worker

    def _policy_dir(self) -> Path:
        policy_dir = self.pipeline.root_output_dir / "policy"
        policy_dir.mkdir(parents=True, exist_ok=True)
        return policy_dir

    def evaluate(
        self,
        *,
        copied_input_path: Path,
        final_review_context: dict,
        memory: FusionSupervisorMemory,
        retry_exhausted: bool,
        iteration: str,
        rendered_svg_path: Path | None = None,
        svg_file_path: Path | None = None,
    ) -> FusionPolicyDecision:
        strategy_enabled = bool(getattr(self.pipeline, "strategy_enabled", True))
        pipeline_use_memory = getattr(self.pipeline, "use_supervisor_memory", None)
        use_memory = bool(pipeline_use_memory()) if callable(pipeline_use_memory) else bool(
            getattr(self.pipeline, "supervisor_memory_enabled", False)
        )
        memory_summary = build_fusion_memory_summary(memory) if use_memory else None
        svg_file_name = final_review_context.get("svg_file_name")
        prompt_review_context = {
            key: value for key, value in final_review_context.items() if key != "svg_file_name"
        }
        history_delta_used = bool(memory_summary is not None or prompt_review_context.get("previous_decision_delta") is not None)
        prompt_request = {
            "final_review_context": prompt_review_context,
            "memory_summary": memory_summary,
            "strategy_enabled": strategy_enabled,
            "svg_file_name": svg_file_name,
        }
        system_prompt, user_prompt = build_fusion_combined_policy_prompts(**prompt_request)
        request_context = {
            "final_review_context": prompt_review_context,
            "strategy_enabled": strategy_enabled,
        }
        if memory_summary is not None:
            request_context["memory_delta"] = memory_summary
        llm_request = {"system_prompt": system_prompt, "user_prompt": user_prompt}
        trace_path = self._policy_dir() / f"fusion_combined_policy_decision_{iteration}.json"
        raw_response: str | None = None
        try:
            proposed, raw_response = self.combined_worker.run(
                copied_input_path=copied_input_path,
                final_review_context=final_review_context,
                memory_summary=memory_summary,
                strategy_enabled=strategy_enabled,
                rendered_svg_path=rendered_svg_path,
                svg_file_path=svg_file_path,
            )
        except Exception as exc:
            fail_policy_evaluation(
                self.pipeline,
                trace_path=trace_path,
                policy_name="fusion-combined-policy",
                request_context=request_context,
                llm_request=llm_request,
                exc=exc,
                raw_response=raw_response,
                supervisor_memory_used=use_memory,
                history_delta_used=history_delta_used,
            )

        final_decision, applied_rules = apply_fusion_combined_policy_rules(
            combined=proposed,
            memory=memory,
            retry_exhausted=retry_exhausted,
            strategy_enabled=strategy_enabled,
            use_memory=use_memory,
        )
        trace = build_policy_trace(
            policy_name="fusion-combined-policy",
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
