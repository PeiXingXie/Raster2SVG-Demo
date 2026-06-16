"""Manual-adjustment policy engine for post-conversion refinement."""

from __future__ import annotations

from pathlib import Path

from deepagents_template.schemas import ManualAdjustmentReview, RepairAcceptanceDecision, StopDecision

from .rules import decide_manual_repair_acceptance, decide_manual_stop
from .tracing import build_policy_trace


class ManualAdjustmentPolicyEngine:
    """Unified policy layer for manual adjustment acceptance and stop decisions."""

    def __init__(self, writer) -> None:
        self.writer = writer

    def _policy_dir(self, adjustment_dir: Path) -> Path:
        policy_dir = adjustment_dir / "policy"
        policy_dir.mkdir(parents=True, exist_ok=True)
        return policy_dir

    def decide_repair_acceptance(
        self,
        *,
        adjustment_dir: Path,
        before_review: ManualAdjustmentReview,
        after_review: ManualAdjustmentReview,
        iteration: str,
    ) -> RepairAcceptanceDecision:
        final_decision, applied_rules = decide_manual_repair_acceptance(
            before_review=before_review,
            after_review=after_review,
        )
        trace = build_policy_trace(
            policy_name="manual-repair-acceptance",
            request_context={
                "before_review": before_review.model_dump(mode="json"),
                "after_review": after_review.model_dump(mode="json"),
            },
            llm_request={},
            raw_response=None,
            proposed_decision=final_decision.model_dump(mode="json"),
            final_decision=final_decision.model_dump(mode="json"),
            applied_rules=applied_rules,
            fallback_used=False,
            error=None,
        )
        self.writer(
            self._policy_dir(adjustment_dir) / f"manual_repair_acceptance_{iteration}.json",
            trace,
        )
        return final_decision

    def decide_stop(
        self,
        *,
        adjustment_dir: Path,
        review: ManualAdjustmentReview,
        budget_used: int,
        budget_limit: int,
        iteration: str,
    ) -> StopDecision:
        final_decision, applied_rules = decide_manual_stop(
            review=review,
            budget_used=budget_used,
            budget_limit=budget_limit,
        )
        trace = build_policy_trace(
            policy_name="manual-stop",
            request_context={
                "review": review.model_dump(mode="json"),
                "budget_used": budget_used,
                "budget_limit": budget_limit,
            },
            llm_request={},
            raw_response=None,
            proposed_decision=final_decision.model_dump(mode="json"),
            final_decision=final_decision.model_dump(mode="json"),
            applied_rules=applied_rules,
            fallback_used=False,
            error=None,
        )
        self.writer(
            self._policy_dir(adjustment_dir) / f"manual_stop_decision_{iteration}.json",
            trace,
        )
        return final_decision
