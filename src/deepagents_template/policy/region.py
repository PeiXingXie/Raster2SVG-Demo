"""Region-level policy engine built from a combined policy-model call plus hard-rule reconciliation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepagents_template.prompt import build_region_combined_policy_prompts
from deepagents_template.prompt.supervisor import build_required_fidelity_checks
from deepagents_template.schemas import RegionCombinedPolicyModelResult, RegionPolicyDecision, RegionSupervisorMemory
from deepagents_template.taxonomy import SYMBOL_FIDELITY_CHECK_KEYS
from deepagents_template.workflow_errors import BudgetExceededError, RunCancelledError

from .failures import fail_policy_evaluation
from .rules import (
    apply_region_combined_policy_rules,
    build_region_memory_summary,
)
from .tracing import build_policy_trace

if TYPE_CHECKING:
    from deepagents_template.conversion import RasterToSvgPipeline
    from deepagents_template.workflow_orchestration.workers import RegionCombinedPolicyModelWorker


FIDELITY_GENERIC_REASONS = {
    "pass",
    "ok",
    "looks good",
    "looks correct",
    "recognizable",
    "same category",
    "semantically faithful",
}

class FidelityVerificationValidationError(ValueError):
    """Recoverable contract error for required fidelity verification output."""

    def __init__(self, message: str, object_ids: list[str]) -> None:
        self.object_ids = list(dict.fromkeys(object_id for object_id in object_ids if object_id))
        super().__init__(message)


class RegionPolicyEngine:
    """Unified region policy engine: one model call plus hard-rule reconciliation."""

    def __init__(
        self,
        pipeline: RasterToSvgPipeline,
        *,
        combined_worker: RegionCombinedPolicyModelWorker,
    ) -> None:
        self.pipeline = pipeline
        self.combined_worker = combined_worker

    def _policy_dir(self, region_dir: Path) -> Path:
        policy_dir = region_dir / "policy"
        policy_dir.mkdir(parents=True, exist_ok=True)
        return policy_dir

    @staticmethod
    def _validate_fidelity_verifications(proposed, required_fidelity_checks: list[dict]) -> None:
        if not required_fidelity_checks:
            return
        required_ids = [str(item.get("object_id") or "").strip() for item in required_fidelity_checks]
        required_ids = [object_id for object_id in required_ids if object_id]
        if not required_ids:
            return

        verifications = list(getattr(proposed.review, "fidelity_verifications", []) or [])
        by_object: dict[str, list[Any]] = {}
        for item in verifications:
            object_id = str(getattr(item, "object_id", "") or "").strip()
            if object_id:
                by_object.setdefault(object_id, []).append(item)

        missing = [object_id for object_id in required_ids if object_id not in by_object]
        duplicates = [object_id for object_id, results in by_object.items() if object_id in required_ids and len(results) > 1]
        if missing:
            raise FidelityVerificationValidationError(
                f"RegionCombinedPolicyModelResult missing fidelity_verifications for: {', '.join(missing)}",
                missing,
            )
        if duplicates:
            raise FidelityVerificationValidationError(
                f"RegionCombinedPolicyModelResult duplicated fidelity_verifications for: {', '.join(duplicates)}",
                duplicates,
            )

        material_issue_object_ids = {
            str(issue.object_id).strip()
            for issue in proposed.review.object_issues
            if issue.severity in {"medium", "high"}
        }

        for object_id in required_ids:
            verification = by_object[object_id][0]
            reason = str(getattr(verification, "reason", "") or "").strip()
            normalized = " ".join(reason.lower().split())
            if not normalized or normalized in FIDELITY_GENERIC_REASONS or len(normalized.split()) < 4:
                raise FidelityVerificationValidationError(
                    f"RegionCombinedPolicyModelResult has generic fidelity verification reason for: {object_id}",
                    [object_id],
                )
            checks = getattr(verification, "checks", None)
            checks_payload = checks.model_dump(mode="json") if hasattr(checks, "model_dump") else checks
            if not isinstance(checks_payload, dict) or set(checks_payload) != set(SYMBOL_FIDELITY_CHECK_KEYS):
                raise FidelityVerificationValidationError(
                    f"RegionCombinedPolicyModelResult has invalid fidelity check keys for: {object_id}",
                    [object_id],
                )
            invalid_values = [
                key
                for key, value in checks_payload.items()
                if str(value).strip().upper() not in {"Y", "N"}
            ]
            if invalid_values:
                raise FidelityVerificationValidationError(
                    f"RegionCombinedPolicyModelResult has invalid fidelity check values for: {object_id}",
                    [object_id],
                )
            failed_axes = [
                key
                for key in SYMBOL_FIDELITY_CHECK_KEYS
                if str(checks_payload.get(key)).strip().upper() == "N"
            ]
            if failed_axes and object_id not in material_issue_object_ids:
                raise FidelityVerificationValidationError(
                    "RegionCombinedPolicyModelResult has failed fidelity checks without object_issues of material severity for: "
                    + object_id,
                    [object_id],
                )

    @staticmethod
    def _merge_fidelity_retry_result(
        original: RegionCombinedPolicyModelResult,
        retry_result: RegionCombinedPolicyModelResult,
        target_object_ids: list[str],
    ) -> RegionCombinedPolicyModelResult:
        target_ids = {str(object_id).strip() for object_id in target_object_ids if str(object_id).strip()}
        if not target_ids:
            return original

        retry_verifications = {
            str(item.object_id).strip(): item
            for item in retry_result.review.fidelity_verifications
            if str(item.object_id).strip() in target_ids
        }
        merged_verifications = [
            item
            for item in original.review.fidelity_verifications
            if str(item.object_id).strip() not in target_ids
        ]
        merged_verifications.extend(retry_verifications[object_id] for object_id in target_ids if object_id in retry_verifications)

        retry_object_issues = [
            item
            for item in retry_result.review.object_issues
            if str(item.object_id).strip() in target_ids
        ]
        merged_object_issues = [
            item
            for item in original.review.object_issues
            if str(item.object_id).strip() not in target_ids
        ]
        merged_object_issues.extend(retry_object_issues)

        merged_review = original.review.model_copy(
            update={
                "fidelity_verifications": merged_verifications,
                "object_issues": merged_object_issues,
            }
        )
        return original.model_copy(update={"review": merged_review})

    @staticmethod
    def _drop_fidelity_verifications(
        proposed: RegionCombinedPolicyModelResult,
        object_ids: list[str],
    ) -> RegionCombinedPolicyModelResult:
        """Remove invalid diagnostic verifications while preserving the ordinary review."""

        target_ids = {str(object_id).strip() for object_id in object_ids if str(object_id).strip()}
        filtered = [
            item
            for item in proposed.review.fidelity_verifications
            if str(item.object_id).strip() not in target_ids
        ]
        return proposed.model_copy(
            update={"review": proposed.review.model_copy(update={"fidelity_verifications": filtered})}
        )

    @staticmethod
    def _filter_payload_by_object_ids(payload: Any, object_ids: set[str]) -> Any:
        if isinstance(payload, list):
            filtered = [
                item
                for item in (
                    RegionPolicyEngine._filter_payload_by_object_ids(item, object_ids)
                    for item in payload
                )
                if item is not None
            ]
            return filtered
        if not isinstance(payload, dict):
            return payload
        object_id = payload.get("object_id")
        if object_id is not None and str(object_id) not in object_ids:
            return None
        filtered: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(key, str) and key in object_ids:
                filtered[key] = value
                continue
            if isinstance(value, (dict, list)):
                narrowed = RegionPolicyEngine._filter_payload_by_object_ids(value, object_ids)
                if narrowed is None:
                    continue
                filtered[key] = narrowed
            else:
                filtered[key] = value
        return filtered

    @staticmethod
    def _narrow_review_context_for_fidelity_retry(review_context: dict, object_ids: list[str]) -> dict:
        object_id_set = set(object_ids)
        narrowed = deepcopy(review_context)
        object_index = narrowed.get("object_index") or {}
        objects = object_index.get("objects") or []
        narrowed["object_index"] = {
            **object_index,
            "objects": [
                obj
                for obj in objects
                if isinstance(obj, dict) and str(obj.get("object_id") or "") in object_id_set
            ],
        }
        if "bbox_constraint_feedback" in narrowed:
            narrowed["bbox_constraint_feedback"] = RegionPolicyEngine._filter_payload_by_object_ids(
                narrowed.get("bbox_constraint_feedback"),
                object_id_set,
            )
        narrowed.pop("previous_decision_delta", None)
        narrowed["fidelity_verification_retry"] = {
            "target_object_ids": list(object_ids),
            "instruction": "Re-run region policy only for these required fidelity objects.",
        }
        return narrowed

    def _run_combined_policy(
        self,
        *,
        crop_path: Path,
        region: dict,
        review_context: dict,
        memory_summary: dict | None,
        retry_context_summary: dict,
        strategy_enabled: bool,
        rendered_svg_path: Path | None,
        svg_file_path: Path | None,
    ):
        return self.combined_worker.run(
            crop_path=crop_path,
            region=region,
            review_context=review_context,
            memory_summary=memory_summary,
            retry_context_summary=retry_context_summary,
            strategy_enabled=strategy_enabled,
            rendered_svg_path=rendered_svg_path,
            svg_file_path=svg_file_path,
        )

    def evaluate(
        self,
        *,
        crop_path: Path,
        region: dict,
        region_dir: Path,
        review_context: dict,
        memory: RegionSupervisorMemory,
        retry_context_summary: dict,
        valid_object_ids: set[str],
        can_object_repair: bool,
        region_retry_exhausted: bool,
        iteration: str,
        region_retry_task: str | None = None,
        fidelity_retry_task: str | None = None,
        rendered_svg_path: Path | None = None,
        svg_file_path: Path | None = None,
    ) -> RegionPolicyDecision:
        strategy_enabled = bool(getattr(self.pipeline, "strategy_enabled", True))
        pipeline_use_memory = getattr(self.pipeline, "use_supervisor_memory", None)
        use_memory = bool(pipeline_use_memory()) if callable(pipeline_use_memory) else bool(
            getattr(self.pipeline, "supervisor_memory_enabled", False)
        )
        memory_summary = build_region_memory_summary(memory) if use_memory else None
        svg_file_name = review_context.get("svg_file_name")
        prompt_review_context = {
            key: value for key, value in review_context.items() if key != "svg_file_name"
        }
        history_delta_used = bool(memory_summary is not None or prompt_review_context.get("previous_decision_delta") is not None)
        prompt_request = {
            "region": region,
            "review_context": prompt_review_context,
            "memory_summary": memory_summary,
            "retry_context_summary": retry_context_summary,
            "strategy_enabled": strategy_enabled,
            "svg_file_name": svg_file_name,
        }
        system_prompt, user_prompt = build_region_combined_policy_prompts(**prompt_request)
        request_context = {
            "region": region,
            "review_context": prompt_review_context,
            "execution_constraints": retry_context_summary,
            "strategy_enabled": strategy_enabled,
        }
        required_fidelity_checks = build_required_fidelity_checks(prompt_review_context.get("object_index") or {})
        if required_fidelity_checks:
            request_context["required_fidelity_checks"] = required_fidelity_checks
        if memory_summary is not None:
            request_context["memory_delta"] = memory_summary
        llm_request = {"system_prompt": system_prompt, "user_prompt": user_prompt}
        trace_path = self._policy_dir(region_dir) / f"region_combined_policy_decision_{iteration}.json"
        raw_response: str | None = None
        retry_raw_response: str | None = None
        effective_region_retry_exhausted = region_retry_exhausted
        if region_retry_task is None:
            task_name_builder = getattr(self.pipeline, "_region_retry_task_name", None)
            if callable(task_name_builder):
                region_retry_task = task_name_builder(str(region.get("region_id") or ""))
        if fidelity_retry_task is None:
            fidelity_retry_task = region_retry_task
        fidelity_shares_region_budget = fidelity_retry_task == region_retry_task
        try:
            proposed, raw_response = self._run_combined_policy(
                crop_path=crop_path,
                region=region,
                review_context=review_context,
                memory_summary=memory_summary,
                retry_context_summary=retry_context_summary,
                strategy_enabled=strategy_enabled,
                rendered_svg_path=rendered_svg_path,
                svg_file_path=svg_file_path,
            )
            try:
                self._validate_fidelity_verifications(proposed, required_fidelity_checks)
            except FidelityVerificationValidationError as fidelity_exc:
                begin_retry = getattr(self.pipeline, "_begin_retry", None)
                if not fidelity_retry_task or not callable(begin_retry) or not begin_retry(fidelity_retry_task):
                    request_context["fidelity_verification_retry"] = {
                        "trigger_error": str(fidelity_exc),
                        "target_object_ids": fidelity_exc.object_ids,
                        "used": False,
                        "skip_reason": "region retry exhausted",
                        "retry_task": fidelity_retry_task,
                    }
                    retry_state = getattr(self.pipeline, "_retry_state", None)
                    if fidelity_retry_task and callable(retry_state):
                        request_context["fidelity_verification_retry"]["retry_state"] = retry_state(fidelity_retry_task)
                    proposed = self._drop_fidelity_verifications(proposed, fidelity_exc.object_ids)
                    request_context["fidelity_verification_retry"]["degraded"] = True
                else:
                    retry_review_context = self._narrow_review_context_for_fidelity_retry(
                        review_context,
                        fidelity_exc.object_ids,
                    )
                    retry_prompt_review_context = {
                        key: value for key, value in retry_review_context.items() if key != "svg_file_name"
                    }
                    retry_required_checks = build_required_fidelity_checks(
                        retry_prompt_review_context.get("object_index") or {}
                    )
                    request_context["fidelity_verification_retry"] = {
                        "trigger_error": str(fidelity_exc),
                        "target_object_ids": fidelity_exc.object_ids,
                        "required_fidelity_checks": retry_required_checks,
                        "retry_task": fidelity_retry_task,
                    }
                    try:
                        if not retry_required_checks:
                            raise fidelity_exc
                        retry_state = getattr(self.pipeline, "_retry_state", None)
                        if callable(retry_state):
                            retry_state_payload = retry_state(fidelity_retry_task)
                            request_context["fidelity_verification_retry"]["retry_state"] = retry_state_payload
                            if fidelity_shares_region_budget:
                                effective_region_retry_exhausted = bool(retry_state_payload.get("exhausted"))
                        else:
                            retry_exhausted = getattr(self.pipeline, "_retry_exhausted", None)
                            if callable(retry_exhausted):
                                effective_region_retry_exhausted = bool(retry_exhausted(region_retry_task))
                        retry_context_for_retry = {
                            **retry_context_summary,
                            "region_retry_available": not effective_region_retry_exhausted,
                            "fidelity_verification_retry_consumed_region_retry": True,
                        }
                        if callable(retry_state):
                            if region_retry_task:
                                retry_context_for_retry["region_retry_state"] = retry_state(region_retry_task)
                            retry_context_for_retry["fidelity_retry_state"] = retry_state(fidelity_retry_task)
                        retry_prompt_request = {
                            **prompt_request,
                            "review_context": retry_prompt_review_context,
                            "retry_context_summary": retry_context_for_retry,
                        }
                        retry_system_prompt, retry_user_prompt = build_region_combined_policy_prompts(**retry_prompt_request)
                        llm_request["fidelity_verification_retry"] = {
                            "system_prompt": retry_system_prompt,
                            "user_prompt": retry_user_prompt,
                        }
                        retry_proposed, retry_raw_response = self._run_combined_policy(
                            crop_path=crop_path,
                            region=region,
                            review_context=retry_review_context,
                            memory_summary=memory_summary,
                            retry_context_summary=retry_context_for_retry,
                            strategy_enabled=strategy_enabled,
                            rendered_svg_path=rendered_svg_path,
                            svg_file_path=svg_file_path,
                        )
                        self._validate_fidelity_verifications(retry_proposed, retry_required_checks)
                        proposed = self._merge_fidelity_retry_result(
                            proposed,
                            retry_proposed,
                            fidelity_exc.object_ids,
                        )
                        self._validate_fidelity_verifications(proposed, required_fidelity_checks)
                        request_context["fidelity_verification_retry"]["used"] = True
                    except (BudgetExceededError, RunCancelledError):
                        raise
                    except Exception as retry_exc:
                        proposed = self._drop_fidelity_verifications(proposed, fidelity_exc.object_ids)
                        request_context["fidelity_verification_retry"].update(
                            {
                                "used": True,
                                "degraded": True,
                                "retry_error": f"{type(retry_exc).__name__}: {retry_exc}",
                            }
                        )
                if request_context["fidelity_verification_retry"].get("degraded"):
                    push_event = getattr(self.pipeline, "_push_event", None)
                    if callable(push_event):
                        push_event(
                            "region-process",
                            f"Fidelity verification degraded for {region.get('region_id')}",
                            "Structured fidelity verification remained unavailable; continuing with the ordinary visual review.",
                            payload={
                                "region_id": region.get("region_id"),
                                "object_ids": fidelity_exc.object_ids,
                                "fidelity_verification_retry": request_context["fidelity_verification_retry"],
                            },
                            status="running",
                            level="warning",
                        )
        except (BudgetExceededError, RunCancelledError):
            raise
        except Exception as exc:
            fail_policy_evaluation(
                self.pipeline,
                trace_path=trace_path,
                policy_name="region-combined-policy",
                request_context=request_context,
                llm_request=llm_request,
                exc=exc,
                raw_response=retry_raw_response or raw_response,
                supervisor_memory_used=use_memory,
                history_delta_used=history_delta_used,
            )

        final_decision, applied_rules = apply_region_combined_policy_rules(
            combined=proposed,
            memory=memory,
            valid_object_ids=valid_object_ids,
            can_object_repair=can_object_repair,
            region_retry_exhausted=effective_region_retry_exhausted,
            strategy_enabled=strategy_enabled,
            use_memory=use_memory,
        )
        trace = build_policy_trace(
            policy_name="region-combined-policy",
            request_context=request_context,
            llm_request=llm_request,
            raw_response=retry_raw_response or raw_response,
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
