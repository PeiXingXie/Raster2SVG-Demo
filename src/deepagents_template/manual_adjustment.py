"""Post-conversion manual SVG adjustment service."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image

from deepagents_template.atomic_files import atomic_write_text
from deepagents_template.artifacts import ArtifactStore
from deepagents_template.config import get_settings
from deepagents_template.modeling.executor import MultimodalJsonCaller
from deepagents_template.policy.manual import ManualAdjustmentPolicyEngine
from deepagents_template.prompt import (
    build_manual_adjustment_agent_edit_prompts,
    build_manual_adjustment_pre_edit_prompts,
    build_manual_adjustment_review_prompts,
    build_manual_adjustment_worker_mode_prompts,
)
from deepagents_template.resume import load_request_from_run_dir
from deepagents_template.runtime import get_thread_store
from deepagents_template.retry_policy import resolve_retry_limits
from deepagents_template.schemas import (
    ArtifactSnapshot,
    ManualAdjustmentPreEditAnalysis,
    ManualAdjustmentRequest,
    ManualAdjustmentReview,
    ManualAdjustmentWorkerPassResult,
    ManualSvgAdjustmentResult,
)
from deepagents_template.svg_utils import SVG_NAMESPACE, extract_object_svg_index, merge_svg, normalize_svg


@dataclass
class ManualTarget:
    scope: str
    target_ids: list[str]
    region_ids: list[str]
    summary: dict
    current_svg_fragment: str
    default_crop_path: Path | None
    object_region_map: dict[str, str]
    bbox: dict | None = None
    fragment_file_path: Path | None = None
    merge_scope: str = "object"
    object_target_keys: list[tuple[str, str]] = field(default_factory=list)


MANUAL_REGION_ATTR = "data-manual-region-id"
MANUAL_OBJECT_ATTR = "data-manual-object-id"
MANUAL_TARGET_KEY_ATTR = "data-manual-target-key"


class ManualAdjustmentBudgetExceededError(RuntimeError):
    """Raised when a manual adjustment session runs out of model-call budget."""


class ManualAdjustmentService:
    """Apply post-conversion user-directed manual adjustments to an existing run."""

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        thread,
        run,
    ) -> None:
        self.artifact_store = artifact_store
        self.thread = thread
        self.run = run
        self.thread_store = get_thread_store()
        self.run_dir = artifact_store.resolve_run_dir(run.artifact_dir)
        if self.run_dir is None:
            raise FileNotFoundError("Artifact run directory is unavailable.")
        self.request = load_request_from_run_dir(self.run_dir)
        settings = get_settings()
        self.retry_limits = resolve_retry_limits(settings, self.request)
        self.api_key = settings.resolved_api_key(self.request.api_key)
        self.base_url = settings.resolved_base_url(self.request.base_url)
        self.api_provider = settings.resolved_api_provider(self.request.api_provider)
        self.api_format = settings.resolved_api_format(self.request.api_format)
        self.max_retries = self.retry_limits.model_retry_limit()
        self.agent_model = settings.resolved_agent_model(self.request.agent_model)
        self.subagent_model = settings.resolved_subagent_model(self.request.subagent_model)
        self.worker_caller = MultimodalJsonCaller(
            self.subagent_model,
            api_key=self.api_key,
            base_url=self.base_url,
            max_retries=self.max_retries,
            response_validation_max_attempts=self.retry_limits.response_validation_max_attempts,
            api_provider=self.api_provider,
            api_format=self.api_format,
            response_callback=self._record_model_response,
            request_callback=self._record_model_request,
            warning_callback=self._record_model_warning,
        )
        self.agent_caller = MultimodalJsonCaller(
            self.agent_model,
            api_key=self.api_key,
            base_url=self.base_url,
            max_retries=self.max_retries,
            response_validation_max_attempts=self.retry_limits.response_validation_max_attempts,
            api_provider=self.api_provider,
            api_format=self.api_format,
            response_callback=self._record_model_response,
            request_callback=self._record_model_request,
            warning_callback=self._record_model_warning,
        )
        self.manual_root = self.run_dir / "output" / "manual_adjustments"
        self.manual_root.mkdir(parents=True, exist_ok=True)
        self.region_root = self.run_dir / "intermediate" / "regions"
        self.policy = ManualAdjustmentPolicyEngine(self._write_json)
        self._active_adjustment_dir: Path | None = None
        self._manual_call_index = 0
        self._manual_budget_limit = 0
        self._manual_budget_used = 0

    def execute(self, payload: ManualAdjustmentRequest, *, artifact_snapshot: ArtifactSnapshot) -> dict:
        base_svg_text = self._load_base_svg_text(payload, artifact_snapshot) or self._load_current_final_svg_text()
        adjustment_dir = self.manual_root / f"adjustment-{len(list(self.manual_root.glob('adjustment-*'))) + 1:03d}"
        adjustment_dir.mkdir(parents=True, exist_ok=True)
        self._active_adjustment_dir = adjustment_dir
        self._manual_call_index = 0
        if base_svg_text:
            self._write_text(adjustment_dir / "base_before_adjustment.svg", normalize_svg(base_svg_text))
        target = self._resolve_target(
            payload,
            artifact_snapshot,
            adjustment_dir=adjustment_dir,
            base_svg_text=base_svg_text,
        )
        image_paths = self._resolve_reference_images(payload, target, adjustment_dir=adjustment_dir)
        call_budget = max(3, int(payload.agent_budget or 3)) if payload.mode == "agent" else 1
        self._manual_budget_limit = call_budget
        self._manual_budget_used = 0
        self._write_json(adjustment_dir / "request.json", payload.model_dump(mode="json"))
        self._write_json(adjustment_dir / "target_summary.json", target.summary)
        self._update_session_state(
            adjustment_dir,
            mode=payload.mode,
            scope=target.scope,
            target_ids=target.target_ids,
            status="running",
            current_step="prepare",
            step_statuses={
                "prepare": {"status": "success", "summary": f"Prepared {target.scope} target."},
                "analyze": {"status": "pending"},
                "edit": {"status": "pending"},
                "review": {"status": "pending"},
                "apply": {"status": "pending"},
                "complete": {"status": "pending"},
            },
        )
        self._push_monitor_event(
            "manual-adjustment",
            "Manual adjustment started",
            f"Preparing {payload.mode}-mode manual adjustment for {target.scope}.",
            payload={
                "adjustment_dir": str(adjustment_dir.relative_to(self.run_dir)).replace("/", "\\"),
                "scope": target.scope,
                "target_ids": target.target_ids,
                "agent_budget": call_budget,
                "merge_scope": target.merge_scope,
            },
        )

        desired_outcomes = [payload.user_introduction] if payload.user_introduction else []
        constraints = [f"Only modify the selected {target.scope} target."]
        review_checks = desired_outcomes[:]
        edit_strategy = target.merge_scope
        rewrite_policy = "patch_preferred"
        max_iterations = 1
        baseline_review = None
        baseline_review_raw = None
        notes: list[str] = []
        repair_history: list[dict] = []
        final_result: ManualSvgAdjustmentResult | None = None

        try:
            if payload.mode == "agent":
                self._update_session_state(
                    adjustment_dir,
                    status="running",
                    current_step="analyze",
                    step_statuses={"analyze": {"status": "running", "summary": "Reviewing target and planning local edit."}},
                )
                analysis, analysis_raw = self._analyze_pre_edit(target, payload, image_paths)
                self._write_text(adjustment_dir / "pre_edit_analysis_raw.txt", analysis_raw)
                self._write_json(adjustment_dir / "pre_edit_analysis.json", analysis.model_dump(mode="json"))
                desired_outcomes = analysis.desired_outcomes or desired_outcomes
                constraints = analysis.constraints or constraints
                review_checks = analysis.review_checks or desired_outcomes
                edit_strategy = analysis.edit_strategy or edit_strategy
                rewrite_policy = analysis.rewrite_policy or rewrite_policy
                max_iterations = max(1, call_budget - self._manual_budget_used)
                baseline_review = ManualAdjustmentReview(
                    passed=not analysis.baseline_issues,
                    regression_detected=False,
                    remaining_issues=analysis.baseline_issues,
                    summary=analysis.goal_summary,
                )
                baseline_review_raw = analysis_raw
                self._write_text(adjustment_dir / "review_iter_0_raw.txt", baseline_review_raw)
                self._write_json(adjustment_dir / "review_iter_0.json", baseline_review.model_dump(mode="json"))
                self._update_session_state(
                    adjustment_dir,
                    status="running",
                    current_step="edit",
                    step_statuses={
                        "analyze": {"status": "success", "summary": analysis.goal_summary or "Prepared edit strategy."},
                        "review": {"status": "success", "summary": baseline_review.summary or "Baseline review captured."},
                        "edit": {"status": "running", "summary": "Generating the first adjustment pass."},
                    },
                    current_iteration=0,
                )
                current_fragment = target.current_svg_fragment
                for iteration in range(1, max_iterations + 1):
                    previous_fragment = current_fragment
                    self._update_session_state(
                        adjustment_dir,
                        status="running",
                        current_step="edit",
                        current_iteration=iteration,
                        step_statuses={"edit": {"status": "running", "summary": f"Running edit iteration {iteration}."}},
                    )
                    result, raw = self._run_agent_edit_worker(
                        target=target,
                        current_fragment=current_fragment,
                        desired_outcomes=desired_outcomes,
                        constraints=constraints,
                        review_checks=review_checks,
                        user_introduction=payload.user_introduction,
                        edit_strategy=edit_strategy,
                        rewrite_policy=rewrite_policy,
                        image_paths=image_paths,
                    )
                    self._validate_worker_result(target, result)
                    self._write_text(adjustment_dir / f"worker_iter_{iteration}_raw.txt", raw)
                    self._write_json(adjustment_dir / f"worker_iter_{iteration}.json", result.model_dump(mode="json"))
                    final_result = result
                    current_fragment = result.svg_fragment

                    self._update_session_state(
                        adjustment_dir,
                        status="running",
                        current_step="review",
                        current_iteration=iteration,
                        step_statuses={
                            "edit": {"status": "success", "summary": f"Generated iteration {iteration}."},
                            "review": {"status": "running", "summary": f"Reviewing iteration {iteration}."},
                        },
                    )
                    review, review_raw = self._review_adjustment(
                        target=target,
                        adjusted_fragment=current_fragment,
                        desired_outcomes=desired_outcomes,
                        constraints=constraints,
                        review_checks=review_checks,
                        image_paths=image_paths,
                    )
                    self._write_text(adjustment_dir / f"review_iter_{iteration}_raw.txt", review_raw)
                    self._write_json(adjustment_dir / f"review_iter_{iteration}.json", review.model_dump(mode="json"))
                    notes.append(review.summary)
                    acceptance = self.policy.decide_repair_acceptance(
                        adjustment_dir=adjustment_dir,
                        before_review=baseline_review or review,
                        after_review=review,
                        iteration=str(iteration),
                    )
                    accepted = acceptance.accept_repair and not review.regression_detected
                    if not accepted:
                        current_fragment = previous_fragment
                        result = result.model_copy(update={"svg_fragment": previous_fragment})
                        final_result = result
                        notes.append(f"Rejected iter {iteration}: {acceptance.rationale}")
                    else:
                        baseline_review = review

                    stop_decision = self.policy.decide_stop(
                        adjustment_dir=adjustment_dir,
                        review=baseline_review or review,
                        budget_used=self._manual_budget_used,
                        budget_limit=call_budget,
                        iteration=str(iteration),
                    )
                    repair_history.append(
                        {
                            "iteration": iteration,
                            "result": result.model_dump(mode="json"),
                            "review": review.model_dump(mode="json"),
                            "acceptance": acceptance.model_dump(mode="json"),
                            "stop_decision": stop_decision.model_dump(mode="json"),
                        }
                    )
                    review_status = "success" if stop_decision.outcome in {"accept", "stop"} else ("retrying" if review.remaining_issues else "issue_detected")
                    self._update_session_state(
                        adjustment_dir,
                        status="running",
                        current_step="review",
                        current_iteration=iteration,
                        step_statuses={
                            "review": {"status": review_status, "summary": review.summary or acceptance.rationale or stop_decision.reason},
                            "edit": {"status": "retrying" if stop_decision.outcome == "continue" else "success"},
                        },
                        repair_history=repair_history,
                    )
                    if stop_decision.outcome in {"accept", "stop"} or self._manual_budget_used >= call_budget:
                        break
                    review_checks = [item.criterion for item in review.remaining_issues] or review_checks
                    desired_outcomes = desired_outcomes + [item.criterion for item in review.remaining_issues[:2]]
            else:
                self._update_session_state(
                    adjustment_dir,
                    status="running",
                    current_step="edit",
                    step_statuses={"edit": {"status": "running", "summary": "Running worker-mode local edit."}},
                )
                worker_pass, raw = self._run_worker_mode_pass(
                    target=target,
                    user_introduction=payload.user_introduction,
                    image_paths=image_paths,
                )
                desired_outcomes = worker_pass.desired_outcomes or desired_outcomes
                constraints = worker_pass.constraints or constraints
                review_checks = worker_pass.review_checks or review_checks
                edit_strategy = worker_pass.edit_strategy or edit_strategy
                rewrite_policy = worker_pass.rewrite_policy or rewrite_policy
                self._write_text(adjustment_dir / "worker_pass_raw.txt", raw)
                self._write_json(adjustment_dir / "worker_pass.json", worker_pass.model_dump(mode="json"))
                notes.append(worker_pass.goal_summary)
                final_result = ManualSvgAdjustmentResult(
                    svg_fragment=worker_pass.svg_fragment,
                    edit_operation=worker_pass.edit_operation,
                    target_ids=worker_pass.target_ids,
                    preserved_ids=worker_pass.preserved_ids,
                    new_ids=worker_pass.new_ids,
                    rewrite_used=worker_pass.rewrite_used,
                    change_summary=worker_pass.change_summary,
                    remaining_limitations=worker_pass.remaining_limitations,
                )
                self._validate_worker_result(target, final_result)
                self._update_session_state(
                    adjustment_dir,
                    status="running",
                    current_step="apply",
                    step_statuses={
                        "edit": {"status": "success", "summary": worker_pass.goal_summary or "Worker pass finished."},
                        "apply": {"status": "running", "summary": "Applying merged SVG output."},
                    },
                )

            if repair_history:
                self._write_json(adjustment_dir / "repair_history.json", repair_history)

            if final_result is None:
                raise RuntimeError("Manual adjustment did not produce any SVG fragment.")

            self._update_session_state(
                adjustment_dir,
                status="running",
                current_step="apply",
                step_statuses={"apply": {"status": "running", "summary": "Writing final adjusted SVG and merging into output."}},
            )
            applied_files = self._apply_adjustment(target, final_result.svg_fragment, adjustment_dir, base_svg_text)
            notes.extend(final_result.change_summary)
            notes.extend(final_result.remaining_limitations)
            notes.extend(self._build_merge_notes(target, final_result))
            self._update_session_state(
                adjustment_dir,
                status="completed",
                current_step="complete",
                step_statuses={
                    "apply": {"status": "success", "summary": "Applied manual SVG changes to the output."},
                    "complete": {"status": "success", "summary": "Manual adjustment completed."},
                },
            )
        except Exception as exc:
            self._record_manual_error(adjustment_dir, exc)
            raise

        return {
            "run_id": self.run.run_id,
            "scope": target.scope,
            "target_ids": target.target_ids,
            "applied_files": applied_files,
            "notes": [note for note in notes if note],
            "edit_strategy": edit_strategy,
        }

    def _record_manual_error(self, adjustment_dir: Path, exc: Exception) -> None:
        error_payload = {
            "message": str(exc),
            "error_type": type(exc).__name__,
            "budget": {
                "limit": self._manual_budget_limit,
                "used": self._manual_budget_used,
                "remaining": max(self._manual_budget_limit - self._manual_budget_used, 0),
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._write_json(adjustment_dir / "error.json", error_payload)
        current_state = self._load_json_file(adjustment_dir / "session_state.json")
        current_step = current_state.get("current_step") if isinstance(current_state, dict) else "edit"
        self._update_session_state(
            adjustment_dir,
            status="failed",
            current_step=current_step,
            error=error_payload,
            step_statuses={current_step: {"status": "failed", "summary": str(exc)}},
        )
        self._push_monitor_event(
            "manual-adjustment",
            "Manual adjustment failed",
            f"{type(exc).__name__}: {exc}",
            payload=error_payload,
            level="error",
        )

    @staticmethod
    def _safe_model_response_name(response_model: object) -> str:
        return "".join(
            char if char.isalnum() or char in {"_", "-"} else "_"
            for char in str(response_model or "model")
        )

    def _model_call_dir(self) -> Path:
        if self._active_adjustment_dir is None:
            raise RuntimeError("Manual adjustment model call directory is unavailable.")
        model_call_dir = self._active_adjustment_dir / "model_calls"
        model_call_dir.mkdir(parents=True, exist_ok=True)
        return model_call_dir

    def _record_model_request(self, payload: dict) -> int:
        if self._manual_budget_used >= self._manual_budget_limit:
            raise ManualAdjustmentBudgetExceededError(
                f"MANUAL_BUDGET exhausted: used {self._manual_budget_used}/{self._manual_budget_limit} model calls."
            )
        self._manual_budget_used += 1
        self._manual_call_index += 1
        call_index = self._manual_call_index
        safe_model_name = self._safe_model_response_name(payload.get("response_model"))
        request_path = self._model_call_dir() / f"{call_index:03d}_{safe_model_name}_sent_message.json"
        atomic_write_text(
            request_path,
            json.dumps(
                {
                    "call_index": call_index,
                    "manual_budget": {
                        "limit": self._manual_budget_limit,
                        "used": self._manual_budget_used,
                        "remaining": max(self._manual_budget_limit - self._manual_budget_used, 0),
                    },
                    **payload,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        return call_index

    def _record_model_response(self, overview: dict) -> None:
        self._persist_manual_model_event(overview, status=overview.get("status", "ok"))

    def _record_model_warning(self, overview: dict) -> None:
        self._persist_manual_model_event(overview, status="warning")

    def _persist_manual_model_event(self, overview: dict, *, status: str) -> None:
        call_index = overview.get("call_index")
        response_model = overview.get("response_model", "model")
        raw_text = overview.get("raw_text")
        raw_response_path = None
        request_path = None
        if isinstance(call_index, int):
            safe_model_name = self._safe_model_response_name(response_model)
            raw_response_file = self._model_call_dir() / f"{call_index:03d}_{safe_model_name}_response_raw.txt"
            request_file = self._model_call_dir() / f"{call_index:03d}_{safe_model_name}_sent_message.json"
            if isinstance(raw_text, str):
                atomic_write_text(raw_response_file, raw_text)
            raw_response_path = str(raw_response_file.relative_to(self.run_dir)).replace("/", "\\")
            request_path = str(request_file.relative_to(self.run_dir)).replace("/", "\\")

        payload = {key: value for key, value in overview.items() if key != "raw_text"}
        if raw_response_path:
            payload["raw_response_path"] = raw_response_path
        if request_path:
            payload["request_path"] = request_path
        payload["manual_budget"] = {
            "limit": self._manual_budget_limit,
            "used": self._manual_budget_used,
            "remaining": max(self._manual_budget_limit - self._manual_budget_used, 0),
        }

        if status == "warning":
            title = "Model response format warning"
            detail = (
                f"{response_model} returned an unexpected payload on attempt "
                f"{overview.get('attempt')}/{overview.get('attempts_total')}; retrying. "
                f"raw={overview.get('raw_chars')} chars. Warning: {overview.get('warning')}"
            )
            level = "warning"
        elif status == "error":
            title = "Model response failed"
            detail = (
                f"{response_model} via {overview.get('model')} "
                f"in {overview.get('duration_ms')} ms; raw={overview.get('raw_chars')} chars. "
                f"Error: {overview.get('error')}"
            )
            level = "error"
        else:
            title = "Model response received"
            detail = (
                f"{response_model} via {overview.get('model')} "
                f"in {overview.get('duration_ms')} ms; raw={overview.get('raw_chars')} chars."
            )
            level = "info"
        if overview.get("invalid_response_preview"):
            detail = (
                f"{detail} Invalid response preview: "
                f"{str(overview['invalid_response_preview']).replace(chr(10), ' ')[:240]}"
            )
        if overview.get("failure_kind"):
            detail = f"{detail} Failure kind: {overview.get('failure_kind')}."
        if raw_response_path:
            detail = f"{detail} Raw saved at {raw_response_path}."
        self._push_monitor_event("model-response", title, detail, payload=payload, level=level)

    def _push_monitor_event(
        self,
        stage: str,
        title: str,
        detail: str,
        *,
        payload: dict | None = None,
        level: str = "info",
    ) -> None:
        thread = self.thread_store.push_event(
            self.thread.thread_id,
            stage=stage,
            title=title,
            detail=detail,
            level=level,
            payload=payload,
        )
        self.artifact_store.write_metadata(thread)

    def _resolve_target(
        self,
        payload: ManualAdjustmentRequest,
        artifact_snapshot: ArtifactSnapshot,
        *,
        adjustment_dir: Path,
        base_svg_text: str | None,
    ) -> ManualTarget:
        overlays = artifact_snapshot.regions
        requested_object_ids = [item for item in payload.target_object_ids if item]
        selection_bbox = payload.selection_bbox.model_dump(mode="json") if payload.selection_bbox else None
        object_entries: list[tuple[str, str, dict, dict]] = []
        region_meta: dict[str, dict] = {}
        for region in overlays:
            region_meta[region.region_id] = region.model_dump(mode="json")
            for obj in region.objects:
                if requested_object_ids and obj.object_id in requested_object_ids:
                    if payload.target_region_id and region.region_id != payload.target_region_id:
                        continue
                    obj_bbox = obj.model_dump(mode="json").get("bbox")
                    bbox_space = obj.model_dump(mode="json").get("bbox_space") or "global"
                    if selection_bbox and obj_bbox:
                        global_box = self._object_global_bbox(region_meta[region.region_id]["bbox"], obj_bbox, bbox_space)
                        if not self._boxes_overlap(selection_bbox, global_box):
                            continue
                    object_entries.append((region.region_id, obj.object_id, obj.model_dump(mode="json"), region_meta[region.region_id]))

        if object_entries:
            entry_lookup = {(region_id, object_id): object_meta for region_id, object_id, object_meta, _region_meta in object_entries}
            target_object_keys: list[tuple[str, str]] = []
            for requested_id in requested_object_ids:
                for region_id, object_id, _object_meta, _region_entry in object_entries:
                    if object_id == requested_id:
                        target_object_keys.append((region_id, object_id))
            if not target_object_keys:
                target_object_keys = [(region_id, object_id) for region_id, object_id, _obj, _reg in object_entries]
            target_regions = list(dict.fromkeys(region_id for region_id, _object_id in target_object_keys))
            fragments_by_region: dict[str, dict[str, str]] = {}
            for region_id in target_regions:
                region_fragment = self._load_region_fragment(region_id, base_svg_text=base_svg_text)
                fragments_by_region[region_id] = extract_object_svg_index(region_fragment)
            current_fragment = "\n".join(
                self._annotate_object_fragment(fragments_by_region.get(region_id, {}).get(object_id, ""), region_id, object_id).strip()
                for region_id, object_id in target_object_keys
                if fragments_by_region.get(region_id, {}).get(object_id)
            ).strip()
            bbox = self._union_global_bbox(
                [
                    self._object_global_bbox(
                        region_meta[region_id]["bbox"],
                        entry_lookup[(region_id, object_id)]["bbox"],
                        entry_lookup[(region_id, object_id)].get("bbox_space") or "global",
                    )
                    for region_id, object_id in target_object_keys
                    if entry_lookup[(region_id, object_id)].get("bbox")
                ]
            )
            fragment_file_path = adjustment_dir / "current_fragment.svgfrag"
            self._write_text(fragment_file_path, current_fragment)
            scope = "object_collection" if len(target_object_keys) > 1 else "object"
            return ManualTarget(
                scope=scope,
                target_ids=[object_id for _region_id, object_id in target_object_keys],
                region_ids=target_regions,
                summary={
                    "scope": scope,
                    "objects": [
                        {
                            **entry_lookup[(region_id, object_id)],
                            "region_id": region_id,
                            "target_key": self._manual_target_key_text(region_id, object_id),
                        }
                        for region_id, object_id in target_object_keys
                    ],
                    "regions": [region_meta[item] for item in target_regions],
                    "target_description": payload.target_description or "",
                },
                current_svg_fragment=current_fragment,
                default_crop_path=self._crop_global_bbox(bbox, adjustment_dir / "default-target-crop.png") if bbox else None,
                object_region_map={
                    self._manual_target_key_text(region_id, object_id): region_id
                    for region_id, object_id in target_object_keys
                },
                bbox=bbox,
                fragment_file_path=fragment_file_path,
                merge_scope=scope,
                object_target_keys=target_object_keys,
            )

        if payload.target_region_id and payload.target_region_id in region_meta:
            region_id = payload.target_region_id
            region_fragment = self._load_region_fragment(region_id, base_svg_text=base_svg_text)
            bbox = region_meta[region_id]["bbox"]
            fragment_file_path = adjustment_dir / "current_fragment.svgfrag"
            self._write_text(fragment_file_path, region_fragment)
            return ManualTarget(
                scope="region",
                target_ids=[region_id],
                region_ids=[region_id],
                summary={
                    "scope": "region",
                    "region": region_meta[region_id],
                    "target_description": payload.target_description or "",
                },
                current_svg_fragment=region_fragment,
                default_crop_path=self._crop_global_bbox(bbox, adjustment_dir / "default-target-crop.png"),
                object_region_map={},
                bbox=bbox,
                fragment_file_path=fragment_file_path,
                merge_scope="region",
            )

        if payload.selection_bbox:
            bbox = payload.selection_bbox.model_dump(mode="json")
            overlapping_objects = []
            overlapping_regions = []
            for region in overlays:
                if region.bbox and self._boxes_overlap(bbox, region.bbox.model_dump(mode="json")):
                    overlapping_regions.append(region.region_id)
                for obj in region.objects:
                    if not obj.bbox:
                        continue
                    global_box = self._object_global_bbox(
                        region.bbox.model_dump(mode="json"),
                        obj.bbox.model_dump(mode="json"),
                        obj.model_dump(mode="json").get("bbox_space") or "global",
                    )
                    if self._boxes_overlap(bbox, global_box):
                        overlapping_objects.append(obj.object_id)
            if overlapping_objects:
                clone = payload.model_copy(update={"target_object_ids": overlapping_objects})
                return self._resolve_target(clone, artifact_snapshot, adjustment_dir=adjustment_dir, base_svg_text=base_svg_text)
            if overlapping_regions:
                fragment_parts = []
                for region_id in overlapping_regions:
                    region_fragment = self._load_region_fragment(region_id, base_svg_text=base_svg_text)
                    fragment_parts.append(f'<!-- bbox-fragment:{region_id} -->\n{region_fragment}')
                current_fragment = "\n".join(fragment_parts).strip()
                fragment_file_path = adjustment_dir / "current_fragment.svgfrag"
                self._write_text(fragment_file_path, current_fragment)
                return ManualTarget(
                    scope="bbox_fragment",
                    target_ids=overlapping_regions,
                    region_ids=overlapping_regions,
                    summary={
                        "scope": "bbox_fragment",
                        "bbox": bbox,
                        "region_ids": overlapping_regions,
                        "target_description": payload.target_description or "",
                    },
                    current_svg_fragment=current_fragment,
                    default_crop_path=self._crop_global_bbox(bbox, adjustment_dir / "default-target-crop.png"),
                    object_region_map={},
                    bbox=bbox,
                    fragment_file_path=fragment_file_path,
                    merge_scope="bbox_fragment",
                )

        raise ValueError("No valid target was selected for manual adjustment.")

    def _resolve_reference_images(
        self,
        payload: ManualAdjustmentRequest,
        target: ManualTarget,
        *,
        adjustment_dir: Path,
    ) -> list[Path] | None:
        if not payload.use_reference_images or payload.include_no_image:
            return None
        images: list[Path] = []
        if payload.include_default_crop and target.default_crop_path is not None and target.default_crop_path.is_file():
            images.append(target.default_crop_path)
        if payload.reference_selection_bbox:
            reference_crop = self._crop_global_bbox(
                payload.reference_selection_bbox.model_dump(mode="json"),
                adjustment_dir / "reference-selection-crop.png",
            )
            if reference_crop is not None and reference_crop.is_file():
                images.append(reference_crop)
        for item in payload.reference_image_paths:
            candidate = Path(item)
            if candidate.is_file():
                images.append(candidate)
        return images or None

    def _analyze_pre_edit(
        self,
        target: ManualTarget,
        payload: ManualAdjustmentRequest,
        image_paths: list[Path] | None,
    ) -> tuple[ManualAdjustmentPreEditAnalysis, str]:
        fragment_path = self._write_phase_fragment("analysis_current_fragment.svg", target.current_svg_fragment)
        system_prompt, user_prompt = build_manual_adjustment_pre_edit_prompts(
            target_summary=target.summary,
            user_introduction=payload.user_introduction,
            current_svg_fragment=target.current_svg_fragment,
            svg_file_name=fragment_path.name,
        )
        return self.agent_caller.call_json(
            ManualAdjustmentPreEditAnalysis,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=image_paths,
        )

    def _run_agent_edit_worker(
        self,
        *,
        target: ManualTarget,
        current_fragment: str,
        desired_outcomes: list[str],
        constraints: list[str],
        review_checks: list[str],
        user_introduction: str,
        edit_strategy: str,
        rewrite_policy: str,
        image_paths: list[Path] | None,
    ) -> tuple[ManualSvgAdjustmentResult, str]:
        fragment_path = self._write_phase_fragment("agent_edit_current_fragment.svg", current_fragment)
        system_prompt, user_prompt = build_manual_adjustment_agent_edit_prompts(
            target_summary=target.summary,
            desired_outcomes=desired_outcomes,
            constraints=constraints,
            user_introduction=user_introduction,
            review_checks=review_checks,
            edit_strategy=edit_strategy,
            rewrite_policy=rewrite_policy,
            current_svg_fragment=current_fragment,
            svg_file_name=fragment_path.name,
        )
        return self.worker_caller.call_json(
            ManualSvgAdjustmentResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=image_paths,
        )

    def _run_worker_mode_pass(
        self,
        *,
        target: ManualTarget,
        user_introduction: str,
        image_paths: list[Path] | None,
    ) -> tuple[ManualAdjustmentWorkerPassResult, str]:
        fragment_path = self._write_phase_fragment("worker_mode_current_fragment.svg", target.current_svg_fragment)
        system_prompt, user_prompt = build_manual_adjustment_worker_mode_prompts(
            target_summary=target.summary,
            user_introduction=user_introduction,
            current_svg_fragment=target.current_svg_fragment,
            svg_file_name=fragment_path.name,
        )
        return self.worker_caller.call_json(
            ManualAdjustmentWorkerPassResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=image_paths,
        )

    def _review_adjustment(
        self,
        *,
        target: ManualTarget,
        adjusted_fragment: str,
        desired_outcomes: list[str],
        constraints: list[str],
        review_checks: list[str],
        image_paths: list[Path] | None,
    ) -> tuple[ManualAdjustmentReview, str]:
        fragment_path = self._write_phase_fragment("review_adjusted_fragment.svg", adjusted_fragment)
        system_prompt, user_prompt = build_manual_adjustment_review_prompts(
            target_summary=target.summary,
            desired_outcomes=desired_outcomes,
            constraints=constraints,
            review_checks=review_checks,
            adjusted_fragment=adjusted_fragment,
            svg_file_name=fragment_path.name,
        )
        return self.agent_caller.call_json(
            ManualAdjustmentReview,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=image_paths,
        )

    def _write_phase_fragment(self, filename: str, fragment: str) -> Path:
        if self._active_adjustment_dir is None:
            raise RuntimeError("Manual adjustment model call directory is unavailable.")
        path = self._active_adjustment_dir / filename
        self._write_text(path, fragment)
        return path

    def _validate_worker_result(self, target: ManualTarget, result: ManualSvgAdjustmentResult) -> None:
        if not result.svg_fragment.strip():
            raise ValueError("Worker returned an empty SVG fragment.")
        if target.scope in {"object", "object_collection"}:
            expected = set(target.target_ids)
            declared = set(result.target_ids or target.target_ids)
            if not declared.issubset(expected):
                raise ValueError("Worker declared target IDs outside the selected object scope.")
            if not result.preserved_ids:
                result.preserved_ids = target.target_ids[:]
            if not expected.intersection(set(result.preserved_ids)):
                raise ValueError("Worker failed to preserve any selected target IDs.")

    def _build_merge_notes(self, target: ManualTarget, result: ManualSvgAdjustmentResult) -> list[str]:
        notes = []
        if result.rewrite_used:
            notes.append(f"Rewrite used within {target.scope} scope under {target.merge_scope} merge policy.")
        elif not result.change_summary:
            notes.append(f"Local replacement completed within {target.scope} scope.")
        return notes

    @staticmethod
    def _manual_target_key_text(region_id: str, object_id: str) -> str:
        return f"{region_id}::{object_id}"

    def _annotate_object_fragment(self, fragment: str, region_id: str, object_id: str) -> str:
        text = (fragment or "").strip()
        if not text:
            return ""
        wrapper = ET.fromstring(text)
        wrapper.attrib[MANUAL_REGION_ATTR] = region_id
        wrapper.attrib[MANUAL_OBJECT_ATTR] = object_id
        wrapper.attrib[MANUAL_TARGET_KEY_ATTR] = self._manual_target_key_text(region_id, object_id)
        return ET.tostring(wrapper, encoding="unicode")

    def _apply_adjustment(
        self,
        target: ManualTarget,
        adjusted_fragment: str,
        adjustment_dir: Path,
        base_svg_text: str | None,
    ) -> list[str]:
        applied_files: list[str] = []
        fragment_path = adjustment_dir / "adjusted_fragment.svgfrag"
        self._write_text(fragment_path, adjusted_fragment)
        applied_files.append(str(fragment_path.relative_to(self.run_dir)))

        base_svg = base_svg_text or self._load_current_final_svg_text()
        if not base_svg:
            raise FileNotFoundError("No base SVG is available for manual adjustment.")
        adjusted_svg = self._merge_adjustment_into_base_svg(base_svg, target, adjusted_fragment)

        versioned_svg = adjustment_dir / "final_after_adjustment.svg"
        self._write_text(versioned_svg, adjusted_svg)
        applied_files.append(str(versioned_svg.relative_to(self.run_dir)))
        return applied_files

    def _merge_adjustment_into_base_svg(
        self,
        base_svg_text: str,
        target: ManualTarget,
        adjusted_fragment: str,
    ) -> str:
        ET.register_namespace("", SVG_NAMESPACE)
        root = ET.fromstring(base_svg_text)
        if target.merge_scope == "region":
            region_id = target.region_ids[0]
            if not self._replace_region_group(root, region_id, adjusted_fragment):
                raise ValueError(f"Base SVG does not contain region group {region_id}.")
        elif target.merge_scope in {"object", "object_collection"}:
            target_keys = target.object_target_keys or [
                (target.object_region_map.get(object_id, ""), object_id) for object_id in target.target_ids
            ]
            fragments = self._extract_manual_object_fragments(adjusted_fragment)
            if not fragments and len(target_keys) == 1:
                fragments[target_keys[0]] = adjusted_fragment
            replaced_any = False
            for region_id, object_id in target_keys:
                fragment = fragments.get((region_id, object_id))
                if fragment is None and len(target_keys) == 1:
                    fragment = next(iter(fragments.values()), "")
                if not fragment:
                    continue
                replaced_any = self._replace_object_group(root, region_id, object_id, fragment) or replaced_any
            if not replaced_any:
                raise ValueError("Base SVG does not contain any selected object group.")
        elif target.merge_scope == "bbox_fragment":
            for region_id in target.region_ids:
                region_fragment = self._fragment_for_region_marker(adjusted_fragment, region_id)
                if region_fragment is None:
                    region_fragment = adjusted_fragment if len(target.region_ids) == 1 else ""
                if not self._replace_region_group(root, region_id, region_fragment):
                    raise ValueError(f"Base SVG does not contain bbox-fragment region group {region_id}.")
        else:
            raise ValueError(f"Unsupported manual merge scope: {target.merge_scope}")
        return normalize_svg(ET.tostring(root, encoding="unicode"))

    def _replace_region_group(self, root: ET.Element, region_id: str, adjusted_fragment: str) -> bool:
        region_group = next((element for element in root.iter() if element.attrib.get("id") == region_id), None)
        if region_group is None:
            return False
        region_group.text = None
        for child in list(region_group):
            region_group.remove(child)
        for child in self._parse_fragment_children(adjusted_fragment):
            region_group.append(child)
        return True

    def _replace_object_group(self, root: ET.Element, region_id: str, object_id: str, adjusted_fragment: str) -> bool:
        replacement_children = self._parse_fragment_children(adjusted_fragment, strip_manual_attrs=True)
        if not replacement_children:
            return False

        region_group = next((element for element in root.iter() if element.attrib.get("id") == region_id), None)
        if region_group is None:
            return False

        def visit(parent: ET.Element) -> bool:
            for index, child in enumerate(list(parent)):
                if child.attrib.get("data-object-id") == object_id:
                    parent.remove(child)
                    for offset, replacement in enumerate(replacement_children):
                        parent.insert(index + offset, replacement)
                    return True
                if visit(child):
                    return True
            return False

        return visit(region_group)

    @staticmethod
    def _parse_fragment_children(fragment: str, *, strip_manual_attrs: bool = False) -> list[ET.Element]:
        text = (fragment or "").strip()
        if not text:
            return []
        wrapper = ET.fromstring(f'<fragment xmlns="{SVG_NAMESPACE}">{text}</fragment>')
        children = list(wrapper)
        if strip_manual_attrs:
            for child in children:
                ManualAdjustmentService._strip_manual_target_attrs(child)
        return children

    @staticmethod
    def _strip_manual_target_attrs(element: ET.Element) -> None:
        for attr in (MANUAL_REGION_ATTR, MANUAL_OBJECT_ATTR, MANUAL_TARGET_KEY_ATTR):
            element.attrib.pop(attr, None)
        for child in list(element):
            ManualAdjustmentService._strip_manual_target_attrs(child)

    def _extract_manual_object_fragments(self, fragment: str) -> dict[tuple[str, str], str]:
        text = (fragment or "").strip()
        if not text:
            return {}
        wrapper = ET.fromstring(f'<fragment xmlns="{SVG_NAMESPACE}">{text}</fragment>')
        fragments: dict[tuple[str, str], str] = {}
        for child in list(wrapper):
            region_id = str(child.attrib.get(MANUAL_REGION_ATTR) or "").strip()
            object_id = str(child.attrib.get(MANUAL_OBJECT_ATTR) or child.attrib.get("data-object-id") or "").strip()
            if not object_id:
                continue
            key = (region_id, object_id)
            fragments[key] = ET.tostring(child, encoding="unicode")
        return fragments

    @staticmethod
    def _fragment_for_region_marker(fragment: str, region_id: str) -> str | None:
        marker = f"<!-- bbox-fragment:{region_id} -->"
        if marker not in fragment:
            return None
        tail = fragment.split(marker, 1)[1].strip()
        next_marker_index = tail.find("<!-- bbox-fragment:")
        if next_marker_index >= 0:
            tail = tail[:next_marker_index].strip()
        return tail.strip() or None

    def _rebuild_final_svg(self) -> None:
        template_path = self.run_dir / "intermediate" / "template.svg"
        template_svg = template_path.read_text(encoding="utf-8")
        merged_regions: dict[str, str] = {}
        for region_path in sorted(self.region_root.glob("*/final_region_elements.svgfrag")):
            merged_regions[region_path.parent.name] = region_path.read_text(encoding="utf-8")
        final_svg = merge_svg(template_svg, merged_regions)
        final_svg = normalize_svg(final_svg)
        atomic_write_text(self.run_dir / "output" / "final.svg", final_svg)

    def _load_region_fragment(self, region_id: str, *, base_svg_text: str | None = None) -> str:
        if base_svg_text:
            extracted = self._extract_region_fragment_from_merged_svg(base_svg_text, region_id)
            if extracted:
                return extracted
        region_path = self.region_root / region_id / "final_region_elements.svgfrag"
        return region_path.read_text(encoding="utf-8")

    def _load_base_svg_text(
        self,
        payload: ManualAdjustmentRequest,
        artifact_snapshot: ArtifactSnapshot,
    ) -> str | None:
        if not payload.base_frame_id:
            return None
        frame = next((item for item in artifact_snapshot.output_frames if item.frame_id == payload.base_frame_id), None)
        if not frame:
            return None
        frame_path = self.run_dir / frame.relative_path.replace("\\", "/")
        if not frame_path.is_file():
            return None
        return frame_path.read_text(encoding="utf-8")

    def _load_current_final_svg_text(self) -> str | None:
        final_svg_path = self.run_dir / "output" / "final.svg"
        if not final_svg_path.is_file():
            return None
        return final_svg_path.read_text(encoding="utf-8")

    def _crop_global_bbox(self, bbox: dict, output_path: Path) -> Path | None:
        image_path = self.request.image_path
        if not image_path:
            return None
        source = Path(image_path)
        if not source.is_file():
            input_candidates = sorted((self.run_dir / "input").glob("*"))
            source = input_candidates[0] if input_candidates else source
        if not source.is_file():
            return None
        with Image.open(source) as image:
            image.load()
            x = max(0, min(int(bbox["x"]), image.width - 1 if image.width > 0 else 0))
            y = max(0, min(int(bbox["y"]), image.height - 1 if image.height > 0 else 0))
            width = max(1, min(int(bbox["width"]), image.width - x))
            height = max(1, min(int(bbox["height"]), image.height - y))
            image.crop((x, y, x + width, y + height)).save(output_path)
        return output_path

    @staticmethod
    def _object_global_bbox(region_bbox: dict, object_bbox: dict, bbox_space: str = "region_local") -> dict:
        if bbox_space == "global":
            return {
                "x": int(object_bbox["x"]),
                "y": int(object_bbox["y"]),
                "width": int(object_bbox["width"]),
                "height": int(object_bbox["height"]),
            }
        return {
            "x": int(region_bbox["x"]) + int(object_bbox["x"]),
            "y": int(region_bbox["y"]) + int(object_bbox["y"]),
            "width": int(object_bbox["width"]),
            "height": int(object_bbox["height"]),
        }

    @staticmethod
    def _union_global_bbox(boxes: list[dict]) -> dict | None:
        if not boxes:
            return None
        x0 = min(box["x"] for box in boxes)
        y0 = min(box["y"] for box in boxes)
        x1 = max(box["x"] + box["width"] for box in boxes)
        y1 = max(box["y"] + box["height"] for box in boxes)
        return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}

    @staticmethod
    def _boxes_overlap(a: dict, b: dict) -> bool:
        return not (
            a["x"] + a["width"] <= b["x"]
            or b["x"] + b["width"] <= a["x"]
            or a["y"] + a["height"] <= b["y"]
            or b["y"] + b["height"] <= a["y"]
        )

    @staticmethod
    def _extract_region_fragment_from_merged_svg(svg_text: str, region_id: str) -> str | None:
        if not svg_text.strip():
            return None
        root = ET.fromstring(svg_text)
        namespace = {"svg": SVG_NAMESPACE}
        region_group = root.find(f".//svg:g[@id='{region_id}']", namespace)
        if region_group is None:
            return None
        parts = [ET.tostring(child, encoding="unicode") for child in list(region_group)]
        return "\n".join(part.strip() for part in parts if part.strip()).strip() or None

    @staticmethod
    def _load_json_file(path: Path) -> dict | list | None:
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _update_session_state(
        self,
        adjustment_dir: Path,
        *,
        mode: str | None = None,
        scope: str | None = None,
        target_ids: list[str] | None = None,
        status: str | None = None,
        current_step: str | None = None,
        current_iteration: int | None = None,
        step_statuses: dict | None = None,
        repair_history: list[dict] | None = None,
        error: dict | None = None,
    ) -> None:
        path = adjustment_dir / "session_state.json"
        existing = self._load_json_file(path)
        state = existing if isinstance(existing, dict) else {}
        state.setdefault("created_at", datetime.now(UTC).isoformat())
        state["updated_at"] = datetime.now(UTC).isoformat()
        if mode is not None:
            state["mode"] = mode
        if scope is not None:
            state["scope"] = scope
        if target_ids is not None:
            state["target_ids"] = target_ids
        if status is not None:
            state["status"] = status
        if current_step is not None:
            state["current_step"] = current_step
        if current_iteration is not None:
            state["current_iteration"] = current_iteration
        if repair_history is not None:
            state["repair_iterations"] = len(repair_history)
        if error is not None:
            state["error"] = error
        steps = state.setdefault("steps", {})
        if step_statuses:
            for step_name, step_payload in step_statuses.items():
                step_entry = steps.setdefault(step_name, {})
                step_entry.update(step_payload)
                if "started_at" not in step_entry:
                    step_entry["started_at"] = datetime.now(UTC).isoformat()
                if step_payload.get("status") in {"success", "failed", "blocked"}:
                    step_entry["ended_at"] = datetime.now(UTC).isoformat()
        self._write_json(path, state)

    @staticmethod
    def _write_json(path: Path, payload: dict | list) -> None:
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        atomic_write_text(path, text)
