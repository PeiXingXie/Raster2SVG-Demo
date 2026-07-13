"""Overview: Region-process node for region-level generation, review, and repair loops."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
from threading import current_thread

from deepagents_template.debug_review import DebugRegionReviewWorkerAgent
from deepagents_template.geometry import build_region_context, recognition_bboxes_to_global_if_local
from deepagents_template.schemas import RegionRecognitionResult, RegionRepairResult, RegionReviewResult, RegionSvgGenerationResult
from deepagents_template.svg_utils import extract_group_template
from deepagents_template.utils.svg_rendering import wrap_svg_fragment, write_svg_review_artifacts
from deepagents_template.utils.svg_runtime import finalize_region_svg
from deepagents_template.utils.tasks import create_region_task


class RegionProcessNodeMixin:
    """Implements region-level generation, review, and repair workflow behavior."""

    def _warn_unscoped_visuals(
        self,
        *,
        region: dict,
        phase: str,
        unscoped_visuals: list[dict[str, str]],
    ) -> None:
        if not unscoped_visuals:
            return
        sample = ", ".join(
            item["tag"] + (f"#{item['id']}" if item.get("id") else "")
            for item in unscoped_visuals[:5]
        )
        self._push_event(
            "region-process",
            f"Unscoped visual elements detected in {region['region_id']}",
            (
                f"{len(unscoped_visuals)} visible SVG element(s) are outside object groups during {phase}. "
                f"Sample: {sample or 'n/a'}."
            ),
            payload={
                "region_id": region["region_id"],
                "phase": phase,
                "unscoped_visual_count": len(unscoped_visuals),
                "unscoped_visuals": unscoped_visuals[:10],
            },
            status="running",
            level="warning",
        )

    def _serialize_initial_region_result(self, result: dict) -> dict:
        return {
            "region_id": result["region_id"],
            "region": result["region"],
            "task": result["task"],
            "recognition": result["recognition"],
            "region_svg_generation": result["region_svg_generation"],
            "generation": result["generation"],
            "initial_svg_elements": result["initial_svg_elements"],
            "initial_object_svg_index": result["initial_object_svg_index"],
        }

    def _load_cached_initial_region_result(self, region_id: str) -> dict | None:
        region_dir = self.root_intermediate_dir / "regions" / region_id
        path = region_dir / "initial_result.json"
        if not path.is_file():
            return None
        payload = self._load_json_payload(path)
        payload["crop_path"] = region_dir / "crop.png"
        payload["region_dir"] = region_dir
        recognition_model = RegionRecognitionResult.model_validate(payload["recognition"])
        recognition_model = recognition_bboxes_to_global_if_local(recognition_model, region=payload["region"])
        payload["recognition_model"] = recognition_model
        payload["recognition"] = recognition_model.model_dump(mode="json")
        payload["region_svg_generation_model"] = RegionSvgGenerationResult.model_validate(
            payload["region_svg_generation"]
        )
        return payload

    def _load_cached_final_region_result(self, region_id: str) -> dict | None:
        region_dir = self.root_intermediate_dir / "regions" / region_id
        path = region_dir / "final_result.json"
        if not path.is_file():
            return None
        payload = self._load_json_payload(path)
        final_svg_path = region_dir / "final_region_elements.svgfrag"
        payload["final_svg_elements"] = self._load_text_payload(final_svg_path)
        return payload

    def _run_region_process_node(
        self,
        *,
        checklist: dict,
        region_work_items: list[dict] | None = None,
        initial_region_results: list[dict] | None = None,
    ) -> list[dict]:
        if region_work_items is not None:
            self._push_event(
                "region-process",
                "Running region-process node",
                "Producing the first-pass SVG fragment for every region before any refinement loop.",
                payload={
                    "regions_total": len(region_work_items),
                    "mode": self.region_processing_mode,
                    "concurrency": self.region_concurrency,
                    "phase": "initial",
                },
                status="running",
            )
            return self._process_regions_initial(region_work_items, checklist)
        if initial_region_results is None:
            return []
        self._push_event(
            "region-process",
            "Running region-process node",
            (
                "Applying region-level refinement after the initial integrated SVG. "
                f"Workflow mode: {self.workflow_mode}."
            ),
            payload={
                "workflow_mode": self.workflow_mode,
                "regions_total": len(initial_region_results),
                "phase": "refine",
            },
            status="running",
        )
        return self._refine_regions(initial_region_results, checklist)

    def _process_regions_parallel(
        self,
        region_work_items: list[dict],
        worker,
        checklist: dict,
    ) -> list[dict]:
        results_by_index: dict[int, dict] = {}
        first_exception: Exception | None = None
        max_workers = max(1, min(self.region_concurrency, len(region_work_items)))
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="region-svg",
        ) as executor:
            future_to_item = {
                executor.submit(worker, item, checklist): (index, item)
                for index, item in enumerate(region_work_items)
            }
            for future in concurrent.futures.as_completed(future_to_item):
                index, item = future_to_item[future]
                region = item.get("region") or item["initial_result"]["region"]
                try:
                    result = future.result()
                except Exception as exc:
                    if first_exception is None:
                        first_exception = exc
                    continue
                self._push_event(
                    "region-process",
                    f"Completed {region['region_id']}",
                    region["description"],
                    payload={
                        "region_id": region["region_id"],
                        "bbox": region["bbox"],
                        "phase": "refine" if "initial_result" in item else "initial",
                    },
                    worker_statuses=self._worker_status_snapshot(),
                    status="running",
                )
                results_by_index[index] = result
        if first_exception is not None:
            raise first_exception
        return [results_by_index[index] for index in range(len(region_work_items))]

    def _process_regions_initial(self, region_work_items: list[dict], checklist: dict) -> list[dict]:
        self._begin_region_phase(len(region_work_items))
        try:
            pending_items = []
            results_by_region: dict[str, dict] = {}
            for item in region_work_items:
                region_id = item["region"]["region_id"]
                cached = self._load_cached_initial_region_result(region_id)
                if cached is not None:
                    results_by_region[region_id] = cached
                else:
                    pending_items.append(item)

            if pending_items:
                if self.region_processing_mode == "parallel" and len(pending_items) > 1:
                    pending_results = self._process_regions_parallel(
                        pending_items,
                        self._process_region_initial_work_item,
                        checklist,
                    )
                else:
                    pending_results = [self._process_region_initial_work_item(item, checklist) for item in pending_items]
                for result in pending_results:
                    results_by_region[result["region_id"]] = result
            return [results_by_region[item["region"]["region_id"]] for item in region_work_items]
        finally:
            self._end_region_phase()

    def _refine_regions(self, initial_region_results: list[dict], checklist: dict) -> list[dict]:
        region_work_items = [{"initial_result": result} for result in initial_region_results]
        self._begin_region_phase(len(region_work_items))
        try:
            pending_items = []
            results_by_region: dict[str, dict] = {}
            for item in region_work_items:
                region_id = item["initial_result"]["region_id"]
                cached = self._load_cached_final_region_result(region_id)
                if cached is not None:
                    results_by_region[region_id] = cached
                else:
                    pending_items.append(item)

            if pending_items:
                if self.region_processing_mode == "parallel" and len(pending_items) > 1:
                    pending_results = self._process_regions_parallel(
                        pending_items,
                        self._refine_region_work_item,
                        checklist,
                    )
                else:
                    pending_results = [self._refine_region_work_item(item, checklist) for item in pending_items]
                for result in pending_results:
                    results_by_region[result["region_id"]] = result
            return [results_by_region[item["initial_result"]["region_id"]] for item in region_work_items]
        finally:
            self._end_region_phase()

    def _process_region_initial_work_item(self, item: dict, checklist: dict) -> dict:
        region = item["region"]
        worker_id = current_thread().name
        self._mark_region_worker_started()
        worker_statuses = self._set_worker_status(
            worker_id=worker_id,
            status="running",
            stage="region-process",
            task_id=region["region_id"],
            detail=region["description"],
        )
        self._push_event(
            "region-process",
            f"Initial pass for {region['region_id']}",
            region["description"],
            payload={"region_id": region["region_id"], "bbox": region["bbox"], "phase": "initial"},
            worker_statuses=worker_statuses,
            status="running",
        )
        previous_trace_stage = self._set_current_trace_stage("initial-generate")
        try:
            return self._process_region_initial(
                crop_path=item["crop_path"],
                region=region,
                checklist=checklist,
                region_dir=item["region_dir"],
            )
        finally:
            self._set_current_trace_stage(previous_trace_stage)
            self._mark_region_worker_finished()
            worker_statuses = self._set_worker_status(
                worker_id=worker_id,
                status="completed",
                stage="region-process",
                task_id=region["region_id"],
                detail=f"Completed {region['region_id']}",
            )
            self._push_event(
                "region-process",
                f"Completed initial pass for {region['region_id']}",
                region["description"],
                payload={"region_id": region["region_id"], "bbox": region["bbox"], "phase": "initial"},
                worker_statuses=worker_statuses,
                status="running",
            )

    def _refine_region_work_item(self, item: dict, checklist: dict) -> dict:
        initial_result = item["initial_result"]
        region = initial_result["region"]
        worker_id = current_thread().name
        self._mark_region_worker_started()
        worker_statuses = self._set_worker_status(
            worker_id=worker_id,
            status="running",
            stage="region-process",
            task_id=region["region_id"],
            detail=region["description"],
        )
        self._push_event(
            "region-process",
            f"Refining {region['region_id']}",
            region["description"],
            payload={
                "region_id": region["region_id"],
                "bbox": region["bbox"],
                "workflow_mode": self.workflow_mode,
                "phase": "refine",
            },
            worker_statuses=worker_statuses,
            status="running",
        )
        previous_trace_stage = self._set_current_trace_stage("refine")
        try:
            return self._refine_region(initial_result=initial_result, checklist=checklist)
        finally:
            self._set_current_trace_stage(previous_trace_stage)
            self._mark_region_worker_finished()
            worker_statuses = self._set_worker_status(
                worker_id=worker_id,
                status="completed",
                stage="region-process",
                task_id=region["region_id"],
                detail=f"Completed {region['region_id']}",
            )
            self._push_event(
                "region-process",
                f"Completed refinement for {region['region_id']}",
                region["description"],
                payload={
                    "region_id": region["region_id"],
                    "bbox": region["bbox"],
                    "workflow_mode": self.workflow_mode,
                    "phase": "refine",
                },
                worker_statuses=worker_statuses,
                status="running",
            )

    def _process_region_initial(
        self,
        *,
        crop_path: Path,
        region: dict,
        checklist: dict,
        region_dir: Path,
    ) -> dict:
        result = self.workflow_agents.region.process_initial(
            crop_path=crop_path,
            region=region,
            checklist=checklist,
            region_dir=region_dir,
        )
        self._write_json(region_dir / "initial_result.json", self._serialize_initial_region_result(result))
        self._mark_region_state(
            region["region_id"],
            status="completed",
            phase="initial",
            last_completed_step="initial_result",
        )
        return result

    def _finalize_region_result_without_refinement(self, initial_result: dict) -> dict:
        region_dir = initial_result["region_dir"]
        initial_svg_elements = initial_result["initial_svg_elements"]
        review_history: list[dict] = []
        repair_history: list[dict] = []
        object_history: list[dict] = []
        retry_summary = self._retry_summary_for_region(initial_result["region_id"])
        self._write_json(region_dir / "review_history.json", review_history)
        self._write_json(region_dir / "repair_history.json", repair_history)
        self._write_json(region_dir / "object_history.json", object_history)
        self._write_json(region_dir / "retry_summary.json", retry_summary)
        self._write_text(region_dir / "final_region_elements.svgfrag", initial_svg_elements)
        result = {
            "region_id": initial_result["region_id"],
            "task": initial_result["task"],
            "recognition": initial_result["recognition"],
            "region_svg_generation": initial_result["region_svg_generation"],
            "generation": {**initial_result["generation"], "svg_elements": initial_svg_elements},
            "review": None,
            "repair": None,
            "review_history": review_history,
            "repair_history": repair_history,
            "object_history": object_history,
            "retry_summary": retry_summary,
            "retry_exhausted": any(item["exhausted"] for item in retry_summary.values()),
            "final_svg_elements": initial_svg_elements,
        }
        self._write_json(region_dir / "final_result.json", {key: value for key, value in result.items() if key != "final_svg_elements"})
        self._mark_region_state(
            initial_result["region_id"],
            status="completed",
            phase="refine",
            last_completed_step="final_region_elements",
            retry_exhausted=result["retry_exhausted"],
        )
        return result

    def _refine_region(
        self,
        *,
        initial_result: dict,
        checklist: dict,
    ) -> dict:
        result = self.workflow_agents.region.refine(
            initial_result=initial_result,
            checklist=checklist,
        )
        region_id = initial_result["region_id"]
        region_dir = initial_result["region_dir"]
        self._write_json(region_dir / "final_result.json", {key: value for key, value in result.items() if key != "final_svg_elements"})
        self._mark_region_state(
            region_id,
            status="completed",
            phase="refine",
            last_completed_step="final_region_elements",
            retry_exhausted=result["retry_exhausted"],
        )
        return result

    def _recognize_region(
        self,
        *,
        crop_path: Path,
        region: dict,
        checklist: dict,
        region_task: dict,
    ) -> tuple[RegionRecognitionResult, str]:
        return self.workflow_agents.region.recognition_worker.run(
            crop_path=crop_path,
            region=region,
            checklist=checklist,
        )

    def _generate_region_svg(
        self,
        *,
        crop_path: Path,
        region: dict,
        checklist: dict,
        region_task: dict,
        recognition: RegionRecognitionResult,
        current_svg_elements: str | None = None,
        failed_items: list[dict] | None = None,
    ) -> tuple[RegionSvgGenerationResult, str]:
        return self.workflow_agents.region.svg_worker.run(
            crop_path=crop_path,
            region=region,
            checklist=checklist,
            recognition=recognition,
            current_svg_elements=current_svg_elements,
            current_svg_file_path=(
                self.workflow_agents.region._write_svg_prompt_attachment(
                    svg_text=current_svg_elements,
                    svg_path=self.root_intermediate_dir / "_prompt_inputs" / region["region_id"] / "current_region.svg",
                )
                if current_svg_elements
                else None
            ),
            failed_items=failed_items,
        )

    def _review_region_svg(
        self,
        *,
        crop_path: Path,
        region: dict,
        checklist: dict,
        recognition: RegionRecognitionResult,
        proposed_svg_elements: str,
    ) -> tuple[RegionReviewResult, str]:
        bbox = region.get("bbox") or {}
        review_dir = self.root_intermediate_dir / "_review_assets" / region["region_id"]
        review_dir.mkdir(parents=True, exist_ok=True)
        svg_file_name = f"region-{region['region_id']}-review.svg"
        svg_path = review_dir / svg_file_name
        png_path = review_dir / f"region-{region['region_id']}-review.png"
        wrapped_svg = wrap_svg_fragment(
            proposed_svg_elements,
            view_box=(
                int(bbox.get("x", 0)),
                int(bbox.get("y", 0)),
                max(int(bbox.get("width", 1)), 1),
                max(int(bbox.get("height", 1)), 1),
            ),
        )
        _, rendered_svg_path = write_svg_review_artifacts(
            svg_text=wrapped_svg,
            svg_path=svg_path,
            png_path=png_path,
        )
        self._record_written_file(svg_path, kind="svg")
        if rendered_svg_path is not None:
            self._record_written_file(rendered_svg_path, kind="png")
        return DebugRegionReviewWorkerAgent(self).run(
            crop_path=crop_path,
            region=region,
            checklist=checklist,
            recognition=recognition,
            proposed_svg_elements=proposed_svg_elements,
            rendered_svg_path=rendered_svg_path,
            svg_file_path=svg_path,
            svg_file_name=svg_file_name,
        )

    def _run_region_repair_loop(
        self,
        *,
        crop_path: Path,
        region: dict,
        checklist: dict,
        region_dir: Path,
        region_task: dict,
        recognition: RegionRecognitionResult,
        review: RegionReviewResult,
        review_history: list[dict],
        repair_history: list[dict],
        current_svg_elements: str,
        region_retry_task: str,
        repair_iteration: int,
    ) -> tuple[str, dict[str, str], RegionReviewResult, RegionRepairResult | None, int]:
        repair_payload = None
        object_svg_index = {}
        while review.global_repairs and self._begin_retry(region_retry_task):
            repair_iteration += 1
            region_svg_update, repair_raw = self._generate_region_svg(
                crop_path=crop_path,
                region=region,
                checklist=checklist,
                region_task=region_task,
                recognition=recognition,
                current_svg_elements=current_svg_elements,
                failed_items=[item.model_dump(mode="json") for item in review.global_repairs],
            )
            current_svg_elements, object_svg_index, unscoped_visuals = finalize_region_svg(region_svg_update.svg_elements, region)
            self._warn_unscoped_visuals(
                region=region,
                phase=f"region_repair_{repair_iteration}",
                unscoped_visuals=unscoped_visuals,
            )
            repair_payload = RegionRepairResult(
                region_id=region["region_id"],
                repaired_svg_elements=current_svg_elements,
                repairs_applied=region_svg_update.generation_notes,
            )
            repair_history.append(
                {
                    "iteration": repair_iteration,
                    "retry": self._retry_state(region_retry_task),
                    "repair": repair_payload.model_dump(mode="json"),
                    "raw": repair_raw,
                }
            )
            self._write_text_async(region_dir / f"region_svg_update_iter_{repair_iteration}_raw.txt", repair_raw)
            self._write_json(
                region_dir / f"region_svg_update_iter_{repair_iteration}.json",
                region_svg_update.model_dump(mode="json"),
            )
            self._write_text(region_dir / f"region_svg_update_iter_{repair_iteration}.svgfrag", current_svg_elements)
            review, review_raw = self._review_region_svg(
                crop_path=crop_path,
                region=region,
                checklist=checklist,
                recognition=recognition,
                proposed_svg_elements=current_svg_elements,
            )
            review_history.append({"iteration": repair_iteration, "review": review.model_dump(mode="json"), "raw": review_raw})
            self._write_text_async(region_dir / f"review_iter_{repair_iteration}_raw.txt", review_raw)
        if not object_svg_index:
            _final_svg, object_svg_index, unscoped_visuals = finalize_region_svg(current_svg_elements, region)
            self._warn_unscoped_visuals(region=region, phase="finalize_cache_fill", unscoped_visuals=unscoped_visuals)
        return current_svg_elements, object_svg_index, review, repair_payload, repair_iteration

    @staticmethod
    def _region_checklist(checklist: dict, region_id: str) -> list[str]:
        from deepagents_template.checklist import select_checklist_for_region

        return select_checklist_for_region(checklist, region_id, stage="generation_refine")
