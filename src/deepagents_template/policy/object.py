"""Object-level policy engine built from a combined policy-model call plus hard-rule reconciliation."""

from __future__ import annotations

from pathlib import Path

from deepagents_template.prompt import build_object_combined_policy_prompts
from deepagents_template.schemas import ObjectPolicyDecision, ObjectRepairSupervisorMemory

from .failures import fail_policy_evaluation
from .rules import (
    apply_object_combined_policy_rules,
    build_object_memory_summary,
    default_object_combined_result,
)
from .tracing import build_policy_trace


class ObjectPolicyEngine:
    """Unified object policy engine: one model call plus hard-rule reconciliation."""

    def __init__(self, pipeline, *, combined_worker=None) -> None:
        self.pipeline = pipeline
        self.combined_worker = combined_worker

    def _policy_dir(self, object_dir: Path) -> Path:
        policy_dir = object_dir / "policy"
        policy_dir.mkdir(parents=True, exist_ok=True)
        return policy_dir

    def evaluate(
        self,
        *,
        object_crop_path: Path,
        object_dir: Path,
        obj: dict,
        review_context: dict,
        memory: ObjectRepairSupervisorMemory,
        retry_exhausted: bool,
        iteration: str,
        rendered_svg_path: Path | None = None,
        svg_file_path: Path | None = None,
    ) -> ObjectPolicyDecision:
        strategy_enabled = bool(getattr(self.pipeline, "strategy_enabled", True))
        pipeline_use_memory = getattr(self.pipeline, "use_supervisor_memory", None)
        use_memory = bool(pipeline_use_memory()) if callable(pipeline_use_memory) else bool(
            getattr(self.pipeline, "supervisor_memory_enabled", False)
        )
        memory_summary = build_object_memory_summary(memory, object_id=obj["object_id"]) if use_memory else None
        svg_file_name = review_context.get("svg_file_name")
        prompt_review_context = {
            key: value for key, value in review_context.items() if key != "svg_file_name"
        }
        history_delta_used = bool(memory_summary is not None or prompt_review_context.get("previous_decision_delta") is not None)
        prompt_request = {
            "obj": obj,
            "review_context": prompt_review_context,
            "memory_summary": memory_summary,
            "strategy_enabled": strategy_enabled,
            "svg_file_name": svg_file_name,
        }
        system_prompt, user_prompt = build_object_combined_policy_prompts(**prompt_request)
        request_context = {
            "obj": obj,
            "review_context": prompt_review_context,
            "strategy_enabled": strategy_enabled,
        }
        if memory_summary is not None:
            request_context["memory_delta"] = memory_summary
        llm_request = {"system_prompt": system_prompt, "user_prompt": user_prompt}
        trace_path = self._policy_dir(object_dir) / f"object_combined_policy_decision_{iteration}.json"
        raw_response: str | None = None
        if self.combined_worker is not None:
            try:
                proposed, raw_response = self.combined_worker.run(
                    object_crop_path=object_crop_path,
                    obj=obj,
                    review_context=review_context,
                    memory_summary=memory_summary,
                    strategy_enabled=strategy_enabled,
                    rendered_svg_path=rendered_svg_path,
                    svg_file_path=svg_file_path,
                )
            except Exception as exc:
                fail_policy_evaluation(
                    self.pipeline,
                    trace_path=trace_path,
                    policy_name="object-combined-policy",
                    request_context=request_context,
                    llm_request=llm_request,
                    exc=exc,
                    raw_response=raw_response,
                    supervisor_memory_used=use_memory,
                    history_delta_used=history_delta_used,
                )
        else:
            proposed = default_object_combined_result(
                obj["object_id"],
                strategy_enabled=strategy_enabled,
            )

        final_decision, applied_rules = apply_object_combined_policy_rules(
            combined=proposed,
            memory=memory,
            retry_exhausted=retry_exhausted,
            strategy_enabled=strategy_enabled,
            use_memory=use_memory,
        )
        trace = build_policy_trace(
            policy_name="object-combined-policy",
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
