"""Overview: Main raster-to-SVG workflow orchestration, loops, and gate control."""

from __future__ import annotations

import json
import shutil
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable
from uuid import uuid4

from PIL import Image

from deepagents_template.checklist import final_review_issues
from deepagents_template.config import get_settings
from deepagents_template.error_reporting import build_failure_diagnostic_from_exception
from deepagents_template.geometry import recognition_bboxes_to_global_if_local
from deepagents_template.memory import ThreadStore
from deepagents_template.modeling.executor import MultimodalJsonCaller
from deepagents_template.resume import create_run_state, load_run_state, write_run_state
from deepagents_template.schemas import (
    AgentRequest,
    ExecutionRun,
    FinalReviewResult,
    RegionRecognitionResult,
    RegionResumeState,
    RegionSvgGenerationResult,
    RunState,
    WorkerStatus,
    utc_now,
)
from deepagents_template.svg_utils import is_valid_svg
from deepagents_template.utils.assets import inspect_local_raster_asset
from deepagents_template.utils.context_payloads import (
    clear_context_payload_warning_callback,
    set_context_payload_warning_callback,
)
from deepagents_template.utils.reports import (
    assemble_conversion_report,
    render_conversion_report_markdown,
)
from deepagents_template.workflow import RasterToSvgNodeMixin
from deepagents_template.workflow_agents import WorkflowAgentSuite


class BudgetExceededError(RuntimeError):
    """Raised before a model call when the run-level API budget is exhausted."""


class RasterToSvgPipeline(RasterToSvgNodeMixin):
    """Executable raster-to-SVG pipeline with persisted intermediates."""

    def __init__(
        self,
        *,
        thread_store: ThreadStore,
        thread_id: str,
        artifact_dir: Path,
        request: AgentRequest,
        agent_model: str,
        subagent_model: str,
        event_callback: Callable[[ExecutionRun], None] | None = None,
    ) -> None:
        self.thread_store = thread_store
        self.thread_id = thread_id
        self.artifact_dir = artifact_dir
        self.request = request
        self.agent_model = agent_model
        self.subagent_model = subagent_model
        self.event_callback = event_callback
        self._context_payload_warning_callback = self._record_context_payload_warning
        self._previous_context_payload_warning_callback = set_context_payload_warning_callback(
            self._context_payload_warning_callback
        )
        settings = get_settings()
        self.api_provider = settings.resolved_api_provider(request.api_provider)
        self.api_key = settings.resolved_api_key(request.api_key)
        self.base_url = settings.resolved_base_url(request.base_url)
        self.api_format = settings.resolved_api_format(request.api_format)
        self.max_retries = settings.resolved_max_retries(request.max_retries)
        self.user_message = settings.resolved_user_input(request.message)
        self.max_retry = settings.resolved_max_retry(request.max_retry)
        self.fusion_max_retry = settings.resolved_fusion_max_retry(request.fusion_max_retry)
        self.max_budget = settings.resolved_max_budget(request.max_budget)
        self.supervisor_memory_enabled = settings.resolved_supervisor_memory_enabled(
            request.supervisor_memory_enabled
        )
        self.supervisor_memory_persist_enabled = settings.resolved_supervisor_memory_persist_enabled(
            request.supervisor_memory_persist_enabled
        )
        self.strategy_enabled = settings.resolved_strategy_enabled(request.strategy_enabled)
        self.recognition_bbox_refine_mode = settings.resolved_recognition_bbox_refine_mode(
            request.recognition_bbox_refine_mode
        )
        self.sam_provider_mode = settings.resolved_sam_provider_mode(request.sam_provider_mode)
        self.sam_remote_url = settings.resolved_sam_remote_url(request.sam_remote_url)
        self.sam_enabled = settings.resolved_sam_enabled(request.sam_enabled)
        self.sam_fallback_to_llm = settings.resolved_sam_fallback_to_llm(
            request.sam_fallback_to_llm
        )
        self.region_processing_mode = settings.resolved_region_processing_mode(
            request.region_processing_mode
        )
        self.region_concurrency = settings.resolved_region_concurrency(
            request.region_processing_mode,
            request.region_concurrency,
        )
        self.bbox_issue_concurrency = settings.resolved_bbox_issue_concurrency(
            request.bbox_issue_concurrency
        )
        self.bbox_issue_stagnation_rounds = settings.resolved_bbox_issue_stagnation_rounds(
            request.bbox_issue_stagnation_rounds
        )
        self.bbox_global_stagnation_rounds = settings.resolved_bbox_global_stagnation_rounds(
            request.bbox_global_stagnation_rounds
        )
        self.workflow_mode = settings.resolved_workflow_mode(request.workflow_mode)
        self.root_input_dir = artifact_dir / "input"
        self.root_intermediate_dir = artifact_dir / "intermediate"
        self.root_output_dir = artifact_dir / "output"
        self.root_logs_dir = artifact_dir / "logs"
        self._run_state_lock = threading.RLock()
        self._model_call_lock = threading.Lock()
        self._model_call_count = 0
        self._retry_lock = threading.Lock()
        self._retry_counts: dict[str, int] = {}
        self._retry_exhausted_tasks: set[str] = set()
        self._parallel_budget_lock = threading.Lock()
        self._active_region_workers = 0
        self._pending_region_tasks = 0
        self._borrowed_object_workers = 0
        self._worker_status_lock = threading.Lock()
        self._worker_statuses: dict[str, WorkerStatus] = {}
        self._node_timing_lock = threading.Lock()
        self._node_timings: dict[str, dict] = {}
        self._file_log_lock = threading.Lock()
        self._file_log_entries: list[dict] = []
        self._overview_lock = threading.Lock()
        self._trace_context = threading.local()
        self._async_io_lock = threading.Lock()
        self._async_io_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="artifact-writer")
        self._async_io_futures: list[Future] = []
        self._runtime_logs_dirty = False
        self._runtime_logs_future: Future | None = None
        self._overview_payload: dict = {
            "request_message": self.request.message,
            "image_path": self.request.image_path,
            "workflow_mode": self.workflow_mode,
            "supervisor_memory_enabled": self.supervisor_memory_enabled,
            "supervisor_memory_persist_enabled": self.supervisor_memory_persist_enabled,
            "strategy_enabled": self.strategy_enabled,
            "recognition_bbox_refine_mode": self.recognition_bbox_refine_mode,
            "sam_provider_mode": self.sam_provider_mode,
            "sam_remote_url": self.sam_remote_url,
            "sam_enabled": self.sam_enabled,
            "sam_fallback_to_llm": self.sam_fallback_to_llm,
            "bbox_issue_concurrency": self.bbox_issue_concurrency,
            "bbox_issue_stagnation_rounds": self.bbox_issue_stagnation_rounds,
            "bbox_global_stagnation_rounds": self.bbox_global_stagnation_rounds,
            "fusion_max_retry": self.fusion_max_retry,
        }
        for directory in (
            self.root_input_dir,
            self.root_intermediate_dir,
            self.root_output_dir,
            self.root_logs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        self.region_caller = MultimodalJsonCaller(
            subagent_model,
            api_key=self.api_key,
            base_url=self.base_url,
            max_retries=self.max_retries,
            api_provider=self.api_provider,
            api_format=self.api_format,
            response_callback=self._record_model_response,
            request_callback=self._record_model_request,
            warning_callback=self._record_model_warning,
        )
        self.final_caller = MultimodalJsonCaller(
            agent_model,
            api_key=self.api_key,
            base_url=self.base_url,
            max_retries=self.max_retries,
            api_provider=self.api_provider,
            api_format=self.api_format,
            response_callback=self._record_model_response,
            request_callback=self._record_model_request,
            warning_callback=self._record_model_warning,
        )
        self.workflow_agents = WorkflowAgentSuite(self)
        self.run_state = self._load_or_init_run_state()
        self._restore_runtime_counters_from_state()

    @staticmethod
    def _normalize_trace_stage(value: object) -> str | None:
        stage = str(value or "").strip().lower().replace("_", "-")
        aliases = {
            "loading-input": "prepare-input",
            "input": "prepare-input",
            "prepare": "prepare-input",
            "layout-detection": "layout",
            "layout detection": "layout",
            "initial-generation": "initial-generate",
            "initial": "initial-generate",
            "initial-integration": "initial-integrate",
            "final-integration": "final-integrate",
            "final": "final-integrate",
            "region-process-initial": "initial-generate",
            "region-process-refine": "refine",
        }
        stage = aliases.get(stage, stage)
        if stage in {
            "prepare-input",
            "layout",
            "initial-generate",
            "initial-integrate",
            "refine",
            "final-integrate",
        }:
            return stage
        return None

    @classmethod
    def _trace_stage_for_event(cls, stage: str | None, payload: dict | None = None) -> str | None:
        payload = payload or {}
        explicit_stage = cls._normalize_trace_stage(payload.get("trace_stage"))
        if explicit_stage:
            return explicit_stage

        value = str(stage or "").strip().lower()
        phase = str(payload.get("phase") or "").strip().lower()
        if value in {"queued", "preparing-context", "loading-input", "running-conversion"}:
            return "prepare-input"
        if value == "layout detection" or "layout" in value:
            return "layout"
        if value in {"planning", "region-cropping"}:
            return "initial-generate"
        if value == "region-process":
            return "refine" if phase in {"refine", "repair", "region-object"} else "initial-generate"
        if value == "object-process":
            return "refine"
        if value == "integrate-process":
            if phase == "initial":
                return "initial-integrate"
            if phase in {"final", "region-object"}:
                return "final-integrate" if phase == "final" else "refine"
        if value in {"summarizing-result", "completed", "paused-budget", "failed"}:
            return "final-integrate"
        return None

    def _current_trace_stage(self) -> str | None:
        return self._normalize_trace_stage(getattr(self._trace_context, "stage", None))

    def _set_current_trace_stage(self, trace_stage: str | None) -> str | None:
        previous = getattr(self._trace_context, "stage", None)
        if trace_stage is None:
            if hasattr(self._trace_context, "stage"):
                delattr(self._trace_context, "stage")
        else:
            self._trace_context.stage = trace_stage
        return previous

    def _resolve_trace_stage(
        self,
        stage: str | None,
        payload: dict | None = None,
        explicit: str | None = None,
    ) -> str | None:
        return (
            self._normalize_trace_stage(explicit)
            or self._trace_stage_for_event(stage, payload)
            or self._current_trace_stage()
        )

    def _load_or_init_run_state(self) -> RunState:
        existing = load_run_state(self.artifact_dir)
        if existing is not None:
            return existing
        state = create_run_state(
            run_id=str(uuid4()),
            thread_id=self.thread_id,
            project_name=self.artifact_dir.name,
            request=self.request,
            budget_limit=self.max_budget,
            max_retry=self.max_retry,
        )
        write_run_state(self.artifact_dir, state)
        return state

    def _save_run_state(self) -> None:
        with self._run_state_lock:
            self.run_state.timestamps.updated_at = utc_now()
            self.run_state.budget.limit = self.max_budget
            self.run_state.budget.used = self._model_call_count
            self.run_state.budget.remaining = max(self.max_budget - self._model_call_count, 0)
            self.run_state.retry.max_retry = self.max_retry
            self.run_state.retry.counts = dict(self._retry_counts)
            self.run_state.retry.exhausted_tasks = sorted(self._retry_exhausted_tasks)
            write_run_state(self.artifact_dir, self.run_state)

    def _restore_runtime_counters_from_state(self) -> None:
        with self._run_state_lock:
            self._model_call_count = self.run_state.budget.used
            self._retry_counts = dict(self.run_state.retry.counts)
            self._retry_exhausted_tasks = set(self.run_state.retry.exhausted_tasks)

    def _mark_stage_started(self, stage: str) -> None:
        with self._run_state_lock:
            self.run_state.status = "running"
            self.run_state.current_stage = stage
            self.run_state.pause_reason = None
            self.run_state.failure.type = None
            self.run_state.failure.message = None
            self._save_run_state()

    def _mark_checkpoint(self, checkpoint_key: str, stage: str) -> None:
        with self._run_state_lock:
            self.run_state.current_stage = stage
            self.run_state.checkpoints[checkpoint_key] = True
            self._save_run_state()

    def _mark_region_state(
        self,
        region_id: str,
        *,
        status: str,
        phase: str | None,
        last_completed_step: str | None,
        retry_exhausted: bool = False,
    ) -> None:
        with self._run_state_lock:
            artifact_dir = str((self.root_intermediate_dir / "regions" / region_id).relative_to(self.artifact_dir))
            region_index = next(
                (index for index, item in enumerate(self.run_state.regions) if item.region_id == region_id),
                None,
            )
            payload = {
                "region_id": region_id,
                "status": status,
                "phase": phase,
                "last_completed_step": last_completed_step,
                "retry_exhausted": retry_exhausted,
                "artifact_dir": artifact_dir,
            }
            if region_index is None:
                self.run_state.regions.append(RegionResumeState.model_validate(payload))
            else:
                self.run_state.regions[region_index] = self.run_state.regions[region_index].model_copy(update=payload)
            self._save_run_state()

    def _mark_paused(self, reason: str, exc: Exception) -> None:
        with self._run_state_lock:
            self.run_state.status = "paused"
            self.run_state.pause_reason = reason
            self.run_state.failure.type = type(exc).__name__
            self.run_state.failure.message = str(exc)
            self.run_state.failure.failure_stage = self.run_state.current_stage
            diagnostic = build_failure_diagnostic_from_exception(
                exc,
                run=self.thread_store.get(self.thread_id).current_run,
                terminal_stage="paused-budget",
                artifact_dir=str(self.artifact_dir),
                failure_stage=self.run_state.current_stage,
                status="paused",
            )
            self.run_state.failure.root_cause_type = diagnostic.root_cause_type
            self.run_state.failure.root_cause_message = diagnostic.root_cause_message
            self.run_state.failure.diagnostic = diagnostic
            self.run_state.timestamps.paused_at = utc_now()
            self._save_run_state()

    def _mark_completed(self) -> None:
        with self._run_state_lock:
            self.run_state.status = "completed"
            self.run_state.current_stage = "completed"
            self.run_state.timestamps.finished_at = utc_now()
            self._save_run_state()

    def _mark_failed(self, exc: Exception) -> None:
        with self._run_state_lock:
            self.run_state.status = "failed"
            self.run_state.failure.type = type(exc).__name__
            self.run_state.failure.message = str(exc)
            self.run_state.failure.failure_stage = self.run_state.current_stage
            diagnostic = build_failure_diagnostic_from_exception(
                exc,
                run=self.thread_store.get(self.thread_id).current_run,
                terminal_stage="failed",
                artifact_dir=str(self.artifact_dir),
                failure_stage=self.run_state.current_stage,
                status="failed",
            )
            self.run_state.failure.root_cause_type = diagnostic.root_cause_type
            self.run_state.failure.root_cause_message = diagnostic.root_cause_message
            self.run_state.failure.diagnostic = diagnostic
            self.run_state.timestamps.finished_at = utc_now()
            self._save_run_state()

    def _load_json_payload(self, path: Path) -> dict | list:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_text_payload(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def _load_initial_region_results_from_artifacts(self) -> list[dict]:
        results: list[dict] = []
        for region in self._load_json_payload(self.root_intermediate_dir / "regions.json"):
            region_id = region["region_id"]
            region_dir = self.root_intermediate_dir / "regions" / region_id
            initial_result_path = region_dir / "initial_result.json"
            if initial_result_path.is_file():
                payload = self._load_json_payload(initial_result_path)
                payload["crop_path"] = region_dir / "crop.png"
                payload["region_dir"] = region_dir
                recognition_model = RegionRecognitionResult.model_validate(payload["recognition"])
                recognition_model = recognition_bboxes_to_global_if_local(recognition_model, region=payload["region"])
                payload["recognition_model"] = recognition_model
                payload["recognition"] = recognition_model.model_dump(mode="json")
                payload["region_svg_generation_model"] = RegionSvgGenerationResult.model_validate(
                    payload["region_svg_generation"]
                )
                results.append(payload)
                continue

            recognition = self._load_json_payload(region_dir / "recognition.json")
            recognition_model = RegionRecognitionResult.model_validate(recognition)
            recognition_model = recognition_bboxes_to_global_if_local(recognition_model, region=region)
            recognition = recognition_model.model_dump(mode="json")
            region_svg_generation = self._load_json_payload(region_dir / "region_svg_gen.json")
            initial_svg_elements = self._load_text_payload(region_dir / "region_svg_gen.svgfrag")
            generation = self._load_json_payload(region_dir / "generation.json")
            task = self._load_json_payload(region_dir / "region_task.json")
            results.append(
                {
                    "region_id": region_id,
                    "region": region,
                    "crop_path": region_dir / "crop.png",
                    "region_dir": region_dir,
                    "task": task,
                    "recognition_model": recognition_model,
                    "region_svg_generation_model": RegionSvgGenerationResult.model_validate(region_svg_generation),
                    "recognition": recognition,
                    "region_svg_generation": region_svg_generation,
                    "generation": generation,
                    "initial_svg_elements": initial_svg_elements,
                    "initial_object_svg_index": {},
                }
            )
        return results

    def _load_final_region_results_from_artifacts(self) -> list[dict]:
        payload = self._load_json_payload(self.root_intermediate_dir / "region_results.json")
        results = []
        for item in payload:
            region_id = item["region_id"]
            final_svg_path = self.root_intermediate_dir / "regions" / region_id / "final_region_elements.svgfrag"
            item["final_svg_elements"] = self._load_text_payload(final_svg_path)
            results.append(item)
        return results

    def run(self) -> str:
        try:
            run_started_at = time.perf_counter()
            image_path = Path(self.request.image_path or "")
            if not image_path.exists():
                raise FileNotFoundError(f"Input image was not found: {image_path}")

            copied_input_path = self.root_input_dir / image_path.name
            self._mark_stage_started("loading-input")
            self._write_json(self.root_input_dir / "request.json", self.request.model_dump(mode="json"))
            if self.run_state.checkpoints.get("input_prepared") and copied_input_path.is_file():
                input_metadata = self._load_json_payload(self.root_input_dir / "input_metadata.json")
                self._push_event("loading-input", "Resuming from prepared input", f"Reusing copied input image {copied_input_path}.", trace_stage="prepare-input")
            else:
                self._push_event("loading-input", "Loading input image", f"Reading raster image from {image_path}.", trace_stage="prepare-input")
                inspection = inspect_local_raster_asset(str(image_path))
                shutil.copy2(image_path, copied_input_path)
                with Image.open(copied_input_path) as prepared_image:
                    prepared_image.load()
                    width, height = prepared_image.size
                    input_metadata = {
                        **inspection,
                        "width": width,
                        "height": height,
                        "image_format": prepared_image.format,
                        "image_mode": prepared_image.mode,
                        "copied_input_path": str(copied_input_path),
                    }
                self._write_json(self.root_input_dir / "input_metadata.json", input_metadata)
                self._mark_checkpoint("input_prepared", "loading-input")

            with Image.open(copied_input_path) as image:
                image.load()
                width = int(input_metadata["width"])
                height = int(input_metadata["height"])

                self._mark_stage_started("layout-detection")
                if self.run_state.checkpoints.get("layout_completed"):
                    checklist = self._load_json_payload(self.root_intermediate_dir / "checklist.json")
                    regions = self._load_json_payload(self.root_intermediate_dir / "regions.json")
                    svg_template = self._load_text_payload(self.root_intermediate_dir / "template.svg")
                    self._push_event("layout detection", "Resuming from completed layout", "Reusing checklist, region split, and SVG template from artifacts.", trace_stage="layout")
                else:
                    (
                        _layout_result,
                        _layout_raw,
                        checklist,
                        regions,
                        svg_template,
                    ) = self._timed_node_call(
                        "layout detection",
                        phase="main",
                        func=self._run_layout_detection_node,
                        copied_input_path=copied_input_path,
                        width=width,
                        height=height,
                    )
                    self._mark_checkpoint("layout_completed", "layout-detection")

                self._mark_stage_started("region-cropping")
                if self.run_state.checkpoints.get("crops_completed"):
                    region_work_items = [
                        {
                            "region": region,
                            "region_dir": self.root_intermediate_dir / "regions" / region["region_id"],
                            "crop_path": self.root_intermediate_dir / "regions" / region["region_id"] / "crop.png",
                        }
                        for region in regions
                    ]
                    self._push_event("region-cropping", "Resuming from cropped regions", f"Reusing {len(region_work_items)} existing region crops.", trace_stage="initial-generate")
                else:
                    region_work_items = self._timed_node_call(
                        "region-cropping",
                        phase="main",
                        func=self._run_region_cropping_node,
                        image=image,
                        regions=regions,
                    )
                    self._mark_checkpoint("crops_completed", "region-cropping")

                self._mark_stage_started("region-process-refine" if self.workflow_mode != "initial_only" else "region-process-initial")
                if self.run_state.checkpoints.get("initial_regions_completed"):
                    initial_region_results = self._load_initial_region_results_from_artifacts()
                    self._push_event("region-process", "Resuming from initial region outputs", f"Reusing {len(initial_region_results)} initial region results.", trace_stage="initial-generate")
                else:
                    initial_region_results = self._timed_node_call(
                        "region-process",
                        phase="initial",
                        func=self._run_region_process_node,
                        checklist=checklist,
                        region_work_items=region_work_items,
                    )
                    self._mark_checkpoint("initial_regions_completed", "region-process-initial")

                initial_region_map = {
                    result["region_id"]: result["initial_svg_elements"] for result in initial_region_results
                }
                self._mark_stage_started("initial-integration")
                if self.run_state.checkpoints.get("initial_svg_completed"):
                    initial_review = FinalReviewResult.model_validate(
                        self._load_json_payload(self.root_intermediate_dir / "initial_review.json")
                    )
                    self._push_event("integrate-process", "Resuming from initial integrated SVG", "Reusing the existing initial SVG and review artifacts.", trace_stage="initial-integrate")
                else:
                    _initial_svg, initial_review, _initial_review_raw = self._timed_node_call(
                        "integrate-process",
                        phase="initial",
                        func=self._run_integrate_process_node,
                        copied_input_path=copied_input_path,
                        checklist=checklist,
                        svg_template=svg_template,
                        merged_regions=initial_region_map,
                        output_path=self.root_intermediate_dir / "initial.svg",
                        review_raw_path=self.root_intermediate_dir / "initial_review_raw.txt",
                        review_json_path=self.root_intermediate_dir / "initial_review.json",
                        detail="Combining the first-pass region SVG fragments into the initial full SVG.",
                        trace_phase="initial",
                    )
                    self._mark_checkpoint("initial_svg_completed", "initial-integration")

            merged_svg_path = self.root_output_dir / "final.svg"
            if self.workflow_mode == "initial_only":
                region_results = [
                    self._finalize_region_result_without_refinement(result)
                    for result in initial_region_results
                ]
                merged_regions = initial_region_map
                self.run_state.checkpoints["refinement_completed"] = True
                self._save_run_state()
            else:
                self._mark_stage_started("region-process-refine")
                if self.run_state.checkpoints.get("refinement_completed") and (self.root_intermediate_dir / "region_results.json").is_file():
                    region_results = self._load_final_region_results_from_artifacts()
                    self._push_event("region-process", "Resuming from refined region outputs", f"Reusing {len(region_results)} completed region refinement results.", trace_stage="refine")
                else:
                    region_results = self._timed_node_call(
                        "region-process",
                        phase="refine",
                        func=self._run_region_process_node,
                        checklist=checklist,
                        initial_region_results=initial_region_results,
                    )
                    self._write_json(
                        self.root_intermediate_dir / "region_results.json",
                        [{key: value for key, value in item.items() if key != "final_svg_elements"} for item in region_results],
                    )
                    self._mark_checkpoint("refinement_completed", "region-process-refine")
                merged_regions = {
                    result["region_id"]: result["final_svg_elements"] for result in region_results
                }
            if not (self.root_intermediate_dir / "region_results.json").is_file() or self.workflow_mode == "initial_only":
                self._write_json(
                    self.root_intermediate_dir / "region_results.json",
                    [{key: value for key, value in item.items() if key != "final_svg_elements"} for item in region_results],
                )
            self._mark_stage_started("final-integration")
            if self.run_state.checkpoints.get("final_svg_completed") and merged_svg_path.is_file():
                merged_svg = self._load_text_payload(merged_svg_path)
                final_review = FinalReviewResult.model_validate(
                    self._load_json_payload(self.root_output_dir / "final_review.json")
                )
                self._push_event("integrate-process", "Resuming from final integrated SVG", "Reusing the existing final SVG and review artifacts.", trace_stage="final-integrate")
            else:
                merged_svg, final_review, _final_review_raw = self._timed_node_call(
                    "integrate-process",
                    phase="final",
                    func=self._run_integrate_process_node,
                    copied_input_path=copied_input_path,
                    checklist=checklist,
                    svg_template=svg_template,
                    merged_regions=merged_regions,
                    output_path=merged_svg_path,
                    review_raw_path=self.root_output_dir / "final_review_raw.txt",
                    review_json_path=self.root_output_dir / "final_review.json",
                    detail="Combining the latest region SVG fragments into the final SVG.",
                    trace_phase="final",
                )
                self._mark_checkpoint("final_svg_completed", "final-integration")

            run_elapsed_ms = int((time.perf_counter() - run_started_at) * 1000)
            input_section = self._build_input_section(input_metadata=input_metadata, run_elapsed_ms=run_elapsed_ms)
            node_timings = self._node_timings_snapshot()
            error_summary = self._build_report_error_summary()
            report = assemble_conversion_report(
                input_section=input_section,
                checklist=checklist,
                regions=regions,
                region_results=region_results,
                initial_review=initial_review.model_dump(mode="json"),
                final_review=final_review.model_dump(mode="json"),
                final_svg_path=str(merged_svg_path),
                final_svg_valid=is_valid_svg(merged_svg) and not final_review_issues(final_review.model_dump(mode="json")),
                node_timings=node_timings,
                error_summary=error_summary,
                known_limitations=final_review.known_limitations,
            )
            self._mark_stage_started("summarizing-result")
            self._write_json(self.root_output_dir / "report.json", report)
            rendered_report = render_conversion_report_markdown(report)
            self._write_text(self.root_output_dir / "report.md", rendered_report)
            self._mark_checkpoint("report_completed", "summarizing-result")
            self._mark_completed()
            return rendered_report
        except BudgetExceededError as exc:
            self._mark_paused("budget_exhausted", exc)
            raise
        except Exception as exc:
            self._mark_failed(exc)
            raise
        finally:
            clear_context_payload_warning_callback(self._context_payload_warning_callback)
            if self._previous_context_payload_warning_callback is not None:
                set_context_payload_warning_callback(self._previous_context_payload_warning_callback)
            self._flush_async_io()
            self._persist_runtime_logs(rescan=True)
            self._shutdown_async_io()

    def _build_input_section(self, *, input_metadata: dict, run_elapsed_ms: int) -> dict:
        return {
            "file_name": input_metadata["file_name"],
            "width": input_metadata["width"],
            "height": input_metadata["height"],
            "api_provider": self.api_provider,
            "api_format": self.api_format,
            "max_retry": self.max_retry,
            "fusion_max_retry": self.fusion_max_retry,
            "max_budget": self.max_budget,
            "api_calls_used": self._model_call_count,
            "supervisor_memory_enabled": self.supervisor_memory_enabled,
            "supervisor_memory_persist_enabled": self.supervisor_memory_persist_enabled,
            "strategy_enabled": self.strategy_enabled,
            "region_processing_mode": self.region_processing_mode,
            "region_concurrency": self.region_concurrency,
            "recognition_bbox_refine_mode": self.recognition_bbox_refine_mode,
            "sam_provider_mode": self.sam_provider_mode,
            "sam_remote_url": self.sam_remote_url,
            "sam_enabled": self.sam_enabled,
            "sam_fallback_to_llm": self.sam_fallback_to_llm,
            "bbox_issue_concurrency": self.bbox_issue_concurrency,
            "bbox_issue_stagnation_rounds": self.bbox_issue_stagnation_rounds,
            "bbox_global_stagnation_rounds": self.bbox_global_stagnation_rounds,
            "workflow_mode": self.workflow_mode,
            "request_message": self.user_message,
            "run_elapsed_ms": run_elapsed_ms,
        }

    def _timed_node_call(
        self,
        node_name: str,
        *,
        phase: str,
        func: Callable,
        **kwargs,
    ):
        started_at = time.perf_counter()
        trace_stage = self._trace_stage_for_event(node_name, {"phase": phase})
        previous_trace_stage = self._set_current_trace_stage(trace_stage)
        try:
            return func(**kwargs)
        finally:
            self._set_current_trace_stage(previous_trace_stage)
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            self._record_node_timing(node_name, phase=phase, elapsed_ms=elapsed_ms)

    def _record_node_timing(self, node_name: str, *, phase: str, elapsed_ms: int) -> None:
        with self._node_timing_lock:
            timing = self._node_timings.setdefault(
                node_name,
                {
                    "total_ms": 0,
                    "runs": 0,
                    "phases": {},
                },
            )
            timing["total_ms"] += elapsed_ms
            timing["runs"] += 1
            phase_timing = timing["phases"].setdefault(phase, {"total_ms": 0, "runs": 0})
            phase_timing["total_ms"] += elapsed_ms
            phase_timing["runs"] += 1

    def _node_timings_snapshot(self) -> dict[str, dict]:
        with self._node_timing_lock:
            return {
                node_name: {
                    "total_ms": payload["total_ms"],
                    "runs": payload["runs"],
                    "phases": {
                        phase: {
                            "total_ms": phase_payload["total_ms"],
                            "runs": phase_payload["runs"],
                        }
                        for phase, phase_payload in sorted(payload["phases"].items())
                    },
                }
                for node_name, payload in sorted(self._node_timings.items())
            }

    def _set_worker_status(
        self,
        *,
        worker_id: str,
        status: str,
        stage: str,
        task_id: str | None = None,
        detail: str | None = None,
        semantic_stage: str | None = None,
    ) -> list[dict]:
        now = utc_now()
        with self._worker_status_lock:
            existing = self._worker_statuses.get(worker_id)
            started_at = (
                existing.started_at
                if existing and existing.stage == stage and existing.task_id == task_id and existing.started_at
                else now
            )
            duration_ms = int((now - started_at).total_seconds() * 1000) if started_at else None
            self._worker_statuses[worker_id] = WorkerStatus(
                worker_id=worker_id,
                status=status,
                stage=stage,
                task_id=task_id,
                detail=detail,
                semantic_stage=semantic_stage,
                started_at=started_at,
                updated_at=now,
                duration_ms=duration_ms,
            )
            return [item.model_dump(mode="json") for item in self._worker_statuses.values()]

    def _begin_region_phase(self, total_tasks: int) -> None:
        with self._parallel_budget_lock:
            self._pending_region_tasks = max(0, total_tasks)
            self._active_region_workers = 0
            self._borrowed_object_workers = 0

    def _end_region_phase(self) -> None:
        with self._parallel_budget_lock:
            self._pending_region_tasks = 0
            self._active_region_workers = 0
            self._borrowed_object_workers = 0

    def _mark_region_worker_started(self) -> None:
        with self._parallel_budget_lock:
            if self._pending_region_tasks > 0:
                self._pending_region_tasks -= 1
            self._active_region_workers += 1

    def _mark_region_worker_finished(self) -> None:
        with self._parallel_budget_lock:
            self._active_region_workers = max(0, self._active_region_workers - 1)

    def _borrow_object_parallel_slots(self, requested_slots: int) -> int:
        if requested_slots <= 0 or self.region_concurrency <= 1:
            return 0
        with self._parallel_budget_lock:
            if self._pending_region_tasks > 0:
                return 0
            available = self.region_concurrency - self._active_region_workers - self._borrowed_object_workers
            borrowed = max(0, min(requested_slots, available))
            self._borrowed_object_workers += borrowed
            return borrowed

    def _release_object_parallel_slots(self, borrowed_slots: int) -> None:
        if borrowed_slots <= 0:
            return
        with self._parallel_budget_lock:
            self._borrowed_object_workers = max(0, self._borrowed_object_workers - borrowed_slots)

    def _worker_status_snapshot(self) -> list[dict]:
        with self._worker_status_lock:
            return [
                self._worker_statuses[worker_id].model_dump(mode="json")
                for worker_id in sorted(self._worker_statuses)
            ]

    def _set_overview(self, payload: dict) -> None:
        with self._overview_lock:
            self._overview_payload.update(payload)
        self._schedule_runtime_logs()

    def _record_written_file(self, path: Path, *, kind: str, schedule_logs: bool = True) -> None:
        if self.root_logs_dir in path.parents or path == self.root_logs_dir:
            return
        entry = {
            "timestamp": utc_now().isoformat(),
            "kind": kind,
            "path": str(path),
            "relative_path": str(path.relative_to(self.artifact_dir)),
            "size_bytes": path.stat().st_size if path.exists() else None,
        }
        with self._file_log_lock:
            self._file_log_entries = [item for item in self._file_log_entries if item["path"] != entry["path"]]
            self._file_log_entries.append(entry)
            self._file_log_entries.sort(key=lambda item: item["relative_path"])
        if schedule_logs:
            self._schedule_runtime_logs()

    def _persist_runtime_logs(self, *, rescan: bool = False) -> None:
        state = self.thread_store.get(self.thread_id)
        run = state.current_run

        if run is not None:
            timeline_payload = [event.model_dump(mode="json") for event in run.events]
            (self.root_logs_dir / "timeline.json").write_text(
                json.dumps(timeline_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            timeline_lines = ["# Timeline", ""]
            for event in run.events:
                timeline_lines.append(
                    f"- [{event.timestamp.isoformat()}] {event.stage} | {event.title} | "
                    f"stage_elapsed_ms={event.stage_duration_ms or 0}"
                )
                if event.detail:
                    timeline_lines.append(f"  detail: {event.detail}")
            (self.root_logs_dir / "timeline.md").write_text("\n".join(timeline_lines) + "\n", encoding="utf-8")

        with self._file_log_lock:
            known_paths = {item["path"] for item in self._file_log_entries}
            if rescan:
                for path in self.artifact_dir.rglob("*"):
                    if not path.is_file():
                        continue
                    if self.root_logs_dir in path.parents:
                        continue
                    if str(path) in known_paths:
                        continue
                    self._file_log_entries.append(
                        {
                            "timestamp": utc_now().isoformat(),
                            "kind": path.suffix.lstrip(".") or "file",
                            "path": str(path),
                            "relative_path": str(path.relative_to(self.artifact_dir)),
                            "size_bytes": path.stat().st_size,
                        }
                    )
            self._file_log_entries.sort(key=lambda item: item["relative_path"])
            file_payload = list(self._file_log_entries)
        (self.root_logs_dir / "files.json").write_text(json.dumps(file_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        file_lines = ["# Written Files", ""]
        for item in file_payload:
            file_lines.append(f"- {item['relative_path']} | kind={item['kind']} | path={item['path']}")
        (self.root_logs_dir / "files.md").write_text("\n".join(file_lines) + "\n", encoding="utf-8")

        with self._overview_lock:
            overview_payload = dict(self._overview_payload)
        (self.root_logs_dir / "overview.json").write_text(
            json.dumps(overview_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        overview_lines = ["# Overview", ""]
        for key, value in overview_payload.items():
            overview_lines.append(f"- {key}: {json.dumps(value, ensure_ascii=False)}")
        (self.root_logs_dir / "overview.txt").write_text("\n".join(overview_lines) + "\n", encoding="utf-8")

    def _region_retry_task_name(self, region_id: str) -> str:
        return f"region:{region_id}:repair"

    def _object_retry_task_name(self, region_id: str, object_id: str) -> str:
        return f"object:{region_id}:{object_id}:repair"

    def _begin_retry(self, task_name: str) -> bool:
        with self._retry_lock:
            used = self._retry_counts.get(task_name, 0)
            if used >= self.max_retry:
                self._retry_exhausted_tasks.add(task_name)
                self._save_run_state()
                return False
            self._retry_counts[task_name] = used + 1
        self._save_run_state()
        return True

    def _retry_state(self, task_name: str) -> dict[str, int | str | bool]:
        with self._retry_lock:
            used = self._retry_counts.get(task_name, 0)
            return {
                "task": task_name,
                "limit": self.max_retry,
                "used": used,
                "exhausted": used >= self.max_retry or task_name in self._retry_exhausted_tasks,
            }

    def _retry_exhausted(self, task_name: str) -> bool:
        with self._retry_lock:
            return (
                self._retry_counts.get(task_name, 0) >= self.max_retry
                or task_name in self._retry_exhausted_tasks
            )

    def _has_object_retry_capacity(
        self,
        region_id: str,
        recognition: RegionRecognitionResult,
        object_issues: list,
    ) -> bool:
        objects_by_id = {obj.object_id for obj in recognition.recognized_objects}
        with self._retry_lock:
            if not object_issues:
                return any(
                    self._retry_counts.get(self._object_retry_task_name(region_id, object_id), 0) < self.max_retry
                    for object_id in objects_by_id
                )
            for issue in object_issues:
                if issue.object_id not in objects_by_id:
                    continue
                task_name = self._object_retry_task_name(region_id, issue.object_id)
                if self._retry_counts.get(task_name, 0) < self.max_retry:
                    return True
                self._retry_exhausted_tasks.add(task_name)
        return False

    def _retry_summary_for_region(self, region_id: str) -> dict[str, dict[str, int | str | bool]]:
        prefixes = (f"region:{region_id}:", f"object:{region_id}:")
        with self._retry_lock:
            task_names = {
                task_name
                for task_name in set(self._retry_counts) | self._retry_exhausted_tasks
                if task_name.startswith(prefixes)
            }
        return {task_name: self._retry_state(task_name) for task_name in sorted(task_names)}

    def _write_json(self, path: Path, payload: dict | list) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._record_written_file(path, kind="json")

    def use_supervisor_memory(self) -> bool:
        """Return whether supervisor memory is allowed to influence prompts or decisions."""

        return bool(self.supervisor_memory_enabled)

    def persist_supervisor_memory(self) -> bool:
        """Return whether supervisor memory artifacts should be written to disk."""

        return bool(self.supervisor_memory_persist_enabled)

    def _write_text(self, path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        self._record_written_file(path, kind=path.suffix.lstrip(".") or "text")

    def _write_json_async(self, path: Path, payload: dict | list) -> None:
        self._submit_async_io(self._write_json_direct, path, payload)

    def _write_text_async(self, path: Path, text: str) -> None:
        self._submit_async_io(self._write_text_direct, path, text)

    def _write_json_direct(self, path: Path, payload: dict | list) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._record_written_file(path, kind="json", schedule_logs=False)
        self._schedule_runtime_logs()

    def _write_text_direct(self, path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        self._record_written_file(path, kind=path.suffix.lstrip(".") or "text", schedule_logs=False)
        self._schedule_runtime_logs()

    def _submit_async_io(self, fn, *args) -> None:
        with self._async_io_lock:
            self._async_io_futures = [future for future in self._async_io_futures if not future.done()]
            self._async_io_futures.append(self._async_io_executor.submit(fn, *args))

    def _flush_async_io(self) -> None:
        with self._async_io_lock:
            futures = list(self._async_io_futures)
            runtime_logs_future = self._runtime_logs_future
        for future in futures:
            future.result()
        if runtime_logs_future is not None:
            runtime_logs_future.result()

    def _shutdown_async_io(self) -> None:
        with self._async_io_lock:
            self._async_io_futures = []
            self._runtime_logs_future = None
        self._async_io_executor.shutdown(wait=True)

    def _schedule_runtime_logs(self) -> None:
        with self._async_io_lock:
            self._runtime_logs_dirty = True
            if self._runtime_logs_future is not None and not self._runtime_logs_future.done():
                return
            self._runtime_logs_future = self._async_io_executor.submit(self._drain_runtime_logs)

    def _drain_runtime_logs(self) -> None:
        while True:
            with self._async_io_lock:
                if not self._runtime_logs_dirty:
                    self._runtime_logs_future = None
                    return
                self._runtime_logs_dirty = False
            self._persist_runtime_logs(rescan=False)

    def _record_model_request(self, payload: dict) -> int:
        trace_stage = self._normalize_trace_stage(payload.get("trace_stage")) or self._current_trace_stage()
        if trace_stage:
            payload = {**payload, "trace_stage": trace_stage}
        with self._model_call_lock:
            if self._model_call_count >= self.max_budget:
                raise BudgetExceededError(
                    f"MAX_BUDGET exhausted: used {self._model_call_count}/{self.max_budget} API calls."
                )
            self._model_call_count += 1
            call_index = self._model_call_count
        self._save_run_state()
        response_model = payload.get("response_model", "model")
        safe_model_name = "".join(
            char if char.isalnum() or char in {"_", "-"} else "_"
            for char in str(response_model)
        )
        model_call_dir = self.root_intermediate_dir / "model_calls"
        model_call_dir.mkdir(parents=True, exist_ok=True)
        self._write_json_async(
            model_call_dir / f"{call_index:03d}_{safe_model_name}_sent_message.json",
            {
                "call_index": call_index,
                "api_budget": {
                    "limit": self.max_budget,
                    "used": call_index,
                    "remaining": max(self.max_budget - call_index, 0),
                },
                **payload,
            },
        )
        return call_index

    @staticmethod
    def _safe_model_response_name(response_model: object) -> str:
        return "".join(
            char if char.isalnum() or char in {"_", "-"} else "_"
            for char in str(response_model or "model")
        )

    def _model_call_relative_path(self, call_index: int | None, response_model: object, suffix: str) -> str | None:
        if not isinstance(call_index, int):
            return None
        safe_model_name = self._safe_model_response_name(response_model)
        return str(Path("intermediate") / "model_calls" / f"{call_index:03d}_{safe_model_name}_{suffix}")

    def _push_event(
        self,
        stage: str,
        title: str,
        detail: str,
        payload: dict | None = None,
        status: str | None = "running",
        worker_statuses: list[dict] | None = None,
        level: str = "info",
        trace_stage: str | None = None,
    ) -> None:
        worker_snapshot = worker_statuses if worker_statuses is not None else self._worker_status_snapshot()
        enriched_payload = dict(payload or {})
        resolved_trace_stage = self._resolve_trace_stage(stage, enriched_payload, trace_stage)
        if resolved_trace_stage:
            enriched_payload["trace_stage"] = resolved_trace_stage
        enriched_payload["parallel_scheduler"] = self._parallel_scheduler_snapshot()
        if worker_snapshot:
            enriched_payload["worker_statuses"] = worker_snapshot
        state = self.thread_store.push_event(
            self.thread_id,
            stage=stage,
            title=title,
            detail=detail,
            level=level,
            payload=enriched_payload or None,
            status=status,
            worker_statuses=worker_snapshot or None,
        )
        self._schedule_runtime_logs()
        if self.event_callback is not None and state.current_run is not None:
            self.event_callback(state.current_run)

    def _parallel_scheduler_snapshot(self) -> dict[str, int | str]:
        with self._parallel_budget_lock:
            available = max(
                self.region_concurrency - self._active_region_workers - self._borrowed_object_workers,
                0,
            )
            return {
                "region_processing_mode": self.region_processing_mode,
                "region_concurrency": self.region_concurrency,
                "pending_region_tasks": self._pending_region_tasks,
                "active_region_workers": self._active_region_workers,
                "borrowed_object_workers": self._borrowed_object_workers,
                "available_worker_slots": available,
            }

    def _record_model_response(self, overview: dict) -> None:
        trace_stage = self._normalize_trace_stage(overview.get("trace_stage")) or self._current_trace_stage()
        if trace_stage:
            overview = {**overview, "trace_stage": trace_stage}
        call_index = overview.get("call_index")
        response_model = overview.get("response_model", "model")
        raw_text = overview.get("raw_text")
        raw_response_relative_path = self._model_call_relative_path(call_index, response_model, "response_raw.txt")
        request_relative_path = self._model_call_relative_path(call_index, response_model, "sent_message.json")
        if isinstance(call_index, int) and isinstance(raw_text, str):
            self._write_text_async(self.artifact_dir / raw_response_relative_path, raw_text)

        event_overview = {key: value for key, value in overview.items() if key != "raw_text"}
        if raw_response_relative_path:
            event_overview["raw_response_path"] = raw_response_relative_path.replace("/", "\\")
        if request_relative_path:
            event_overview["request_path"] = request_relative_path.replace("/", "\\")
        status = overview.get("status")
        title = "Model response received" if status == "ok" else "Model response failed"
        detail = (
            f"{overview.get('response_model')} via {overview.get('model')} "
            f"in {overview.get('duration_ms')} ms; raw={overview.get('raw_chars')} chars."
        )
        if status != "ok" and overview.get("error"):
            detail = f"{detail} Error: {overview['error']}"
        if status != "ok" and overview.get("invalid_response_preview"):
            detail = (
                f"{detail} Invalid response preview: "
                f"{str(overview['invalid_response_preview']).replace(chr(10), ' ')[:240]}"
            )
        if raw_response_relative_path:
            detail = f"{detail} Raw saved at {raw_response_relative_path.replace('/', '\\')}."
        self._push_event(
            "model-response",
            title,
            detail,
            payload=event_overview,
            status="running",
            trace_stage=trace_stage,
        )

    def _record_model_warning(self, overview: dict) -> None:
        trace_stage = self._normalize_trace_stage(overview.get("trace_stage")) or self._current_trace_stage()
        if trace_stage:
            overview = {**overview, "trace_stage": trace_stage}
        call_index = overview.get("call_index")
        response_model = overview.get("response_model", "model")
        raw_text = overview.get("raw_text")
        raw_response_relative_path = self._model_call_relative_path(call_index, response_model, "response_raw.txt")
        request_relative_path = self._model_call_relative_path(call_index, response_model, "sent_message.json")
        if isinstance(raw_text, str) and raw_response_relative_path:
            self._write_text_async(self.artifact_dir / raw_response_relative_path, raw_text)
        event_overview = {key: value for key, value in overview.items() if key != "raw_text"}
        if raw_response_relative_path:
            event_overview["raw_response_path"] = raw_response_relative_path.replace("/", "\\")
        if request_relative_path:
            event_overview["request_path"] = request_relative_path.replace("/", "\\")
        detail = (
            f"{overview.get('response_model')} returned an unexpected payload on attempt "
            f"{overview.get('attempt')}/{overview.get('attempts_total')}; retrying. "
            f"raw={overview.get('raw_chars')} chars. Warning: {overview.get('warning')}"
        )
        if overview.get("failure_kind"):
            detail = f"{detail} Failure kind: {overview.get('failure_kind')}."
        if overview.get("invalid_response_preview"):
            detail = (
                f"{detail} Invalid response preview: "
                f"{str(overview['invalid_response_preview']).replace(chr(10), ' ')[:240]}"
            )
        if raw_response_relative_path:
            detail = f"{detail} Raw saved at {raw_response_relative_path.replace('/', '\\')}."
        self._push_event(
            "model-response",
            "Model response format warning",
            detail,
            payload=event_overview,
            status="running",
            level="warning",
            trace_stage=trace_stage,
        )

    def _record_context_payload_warning(self, overview: dict) -> None:
        trace_stage = self._normalize_trace_stage(overview.get("trace_stage")) or self._current_trace_stage()
        if trace_stage:
            overview = {**overview, "trace_stage": trace_stage}
        if overview.get("budget_kind") == "item_count":
            detail = (
                f"{overview.get('builder')} preserved {overview.get('actual_item_count')} items in "
                f"{overview.get('field')} for {overview.get('scope')}:{overview.get('target_id')} "
                f"(limit {overview.get('suggested_item_limit')})."
            )
        else:
            detail = (
                f"{overview.get('builder')} preserved over-budget text in {overview.get('field')} "
                f"for {overview.get('scope')}:{overview.get('target_id')} "
                f"({overview.get('actual_word_count')}/{overview.get('suggested_word_limit')} words)."
            )
        title = (
            "Review budget warning"
            if str(overview.get("builder", "")).startswith("clean_")
            else "Context payload budget warning"
        )
        self._push_event(
            "context-payload",
            title,
            detail,
            payload=overview,
            status="running",
            level="warning",
            trace_stage=trace_stage,
        )

    def _build_report_error_summary(self) -> dict:
        state = self.thread_store.get(self.thread_id)
        run = state.current_run
        if run is None:
            return {"warnings_total": 0, "errors_total": 0, "items": []}
        items: list[dict] = []
        warnings_total = 0
        errors_total = 0
        for event in run.events:
            if event.level not in {"warning", "error"}:
                continue
            if event.level == "warning":
                warnings_total += 1
            if event.level == "error":
                errors_total += 1
            payload = event.payload or {}
            item = {
                "timestamp": event.timestamp.isoformat(),
                "stage": event.stage,
                "title": event.title,
                "level": event.level,
                "summary": payload.get("warning") or payload.get("error") or event.title,
                "detail": event.detail,
                "response_model": payload.get("response_model"),
                "request_path": payload.get("request_path"),
                "raw_response_path": payload.get("raw_response_path"),
            }
            items.append(item)
        return {
            "warnings_total": warnings_total,
            "errors_total": errors_total,
            "items": items,
        }
