"""Overview: Object-process node for object-level generation, review, and local repair."""

from __future__ import annotations

import concurrent.futures
import time
from pathlib import Path

from deepagents_template.debug_review import DebugObjectReviewWorkerAgent
from deepagents_template.geometry import crop_object_image
from deepagents_template.schemas import ObjectCandidate, ObjectReviewResult, ObjectSvgGenerationResult, RegionRecognitionResult, RegionReviewResult
from deepagents_template.utils.svg_rendering import wrap_svg_fragment, write_svg_review_artifacts
from deepagents_template.utils.svg_runtime import aggregate_region_object_svg
from deepagents_template.utils.tasks import create_object_task


class ObjectProcessNodeMixin:
    """Implements object-level refinement and object-to-region reintegration."""

    def _run_object_process_node(
        self,
        *,
        crop_path: Path,
        region: dict,
        checklist: dict,
        region_dir: Path,
        recognition: RegionRecognitionResult,
        object_svg_index: dict[str, str],
        object_issues: list,
    ) -> tuple[dict[str, str], list[dict]]:
        self._push_event(
            "object-process",
            f"Running object-process for {region['region_id']}",
            "Generating/refining object SVG fragments and reviewing object-scoped failures.",
            payload={"region_id": region["region_id"], "object_issues": len(object_issues), "phase": "refine"},
            status="running",
        )
        started_at = time.perf_counter()
        previous_trace_stage = self._set_current_trace_stage("refine")
        try:
            return self.workflow_agents.object.repair(
                crop_path=crop_path,
                region=region,
                checklist=checklist,
                region_dir=region_dir,
                recognition=recognition,
                object_svg_index=object_svg_index,
                object_issues=object_issues,
            )
        finally:
            self._set_current_trace_stage(previous_trace_stage)
            self._record_node_timing(
                "object-process",
                phase="repair",
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            )

    def _run_region_object_integrate_process_node(
        self,
        *,
        crop_path: Path,
        region: dict,
        checklist: dict,
        recognition: RegionRecognitionResult,
        current_region_svg: str,
        object_svg_index: dict[str, str],
        aggregate_path: Path,
    ) -> tuple[str, RegionReviewResult, str]:
        self._push_event(
            "integrate-process",
            f"Integrating object-process output for {region['region_id']}",
            "Merging object fragments back into the region SVG and re-running region review.",
            payload={"region_id": region["region_id"], "scope": "region-object", "phase": "region-object"},
            status="running",
        )
        started_at = time.perf_counter()
        previous_trace_stage = self._set_current_trace_stage("refine")
        try:
            final_svg_elements = aggregate_region_object_svg(current_region_svg, object_svg_index, region)
            self._write_text(aggregate_path, final_svg_elements)
            review, review_raw = self._review_region_svg(
                crop_path=crop_path,
                region=region,
                checklist=checklist,
                recognition=recognition,
                proposed_svg_elements=final_svg_elements,
            )
            return final_svg_elements, review, review_raw
        finally:
            self._set_current_trace_stage(previous_trace_stage)
            self._record_node_timing(
                "integrate-process",
                phase="region-object",
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            )

    def _repair_region_objects(
        self,
        *,
        crop_path: Path,
        region: dict,
        checklist: dict,
        region_dir: Path,
        recognition: RegionRecognitionResult,
        object_svg_index: dict[str, str],
        object_issues: list,
    ) -> tuple[dict[str, str], list[dict]]:
        objects_by_id = {obj.object_id: obj for obj in recognition.recognized_objects}
        objects_dir = region_dir / "objects"
        objects_dir.mkdir(parents=True, exist_ok=True)
        work_items = []
        for index, issue in enumerate(object_issues):
            obj = objects_by_id.get(issue.object_id)
            if obj is None:
                continue
            work_items.append(
                {
                    "index": index,
                    "issue": issue,
                    "obj": obj,
                    "current_object_svg": object_svg_index.get(obj.object_id, ""),
                    "objects_dir": objects_dir,
                }
            )
        if not work_items:
            return object_svg_index, []

        borrowed_slots = self._borrow_object_parallel_slots(max(0, len(work_items) - 1))
        self._push_event(
            "object-process",
            f"Object workers for {region['region_id']}",
            "Using leftover shared worker capacity for independent object repairs.",
            payload={
                "region_id": region["region_id"],
                "objects_total": len(work_items),
                "extra_object_workers": borrowed_slots,
                "phase": "refine",
            },
            status="running",
        )

        results_by_index: dict[int, dict] = {}
        try:
            first_item = work_items[0]
            results_by_index[first_item["index"]] = self._process_single_object_issue(
                crop_path=crop_path,
                region=region,
                item=first_item,
            )
            if borrowed_slots > 0 and len(work_items) > 1:
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=borrowed_slots,
                    thread_name_prefix=f"object-svg-{region['region_id']}",
                ) as executor:
                    future_to_index = {
                        executor.submit(
                            self._process_single_object_issue,
                            crop_path=crop_path,
                            region=region,
                            item=item,
                        ): item["index"]
                        for item in work_items[1:]
                    }
                    for future in concurrent.futures.as_completed(future_to_index):
                        results_by_index[future_to_index[future]] = future.result()
            else:
                for item in work_items[1:]:
                    results_by_index[item["index"]] = self._process_single_object_issue(
                        crop_path=crop_path,
                        region=region,
                        item=item,
                    )
        finally:
            self._release_object_parallel_slots(borrowed_slots)

        history = []
        for item in work_items:
            result = results_by_index[item["index"]]
            object_svg_index[result["object_id"]] = result["final_svg_elements"]
            history.append(result["record"])
        return object_svg_index, history

    def _process_single_object_issue(
        self,
        *,
        crop_path: Path,
        region: dict,
        item: dict,
    ) -> dict:
        issue = item["issue"]
        obj = item["obj"]
        previous_trace_stage = self._set_current_trace_stage("refine")
        try:
            return self._process_single_object_issue_with_trace(
                crop_path=crop_path,
                region=region,
                item=item,
            )
        finally:
            self._set_current_trace_stage(previous_trace_stage)

    def _process_single_object_issue_with_trace(
        self,
        *,
        crop_path: Path,
        region: dict,
        item: dict,
    ) -> dict:
        issue = item["issue"]
        obj = item["obj"]
        retry_task = self._object_retry_task_name(region["region_id"], issue.object_id)
        if not self._begin_retry(retry_task):
            record = {
                "object_id": issue.object_id,
                "retry_task": retry_task,
                "issue": issue.model_dump(mode="json"),
                "skipped": True,
                "skip_reason": "retry exhausted",
                "retry": self._retry_state(retry_task),
                "final_svg_elements": item["current_object_svg"],
            }
            return {
                "object_id": issue.object_id,
                "final_svg_elements": item["current_object_svg"],
                "record": record,
            }

        object_dir = item["objects_dir"] / obj.object_id
        object_dir.mkdir(parents=True, exist_ok=True)
        object_crop_path = crop_object_image(
            region_crop_path=crop_path,
            obj=obj,
            object_dir=object_dir,
            region=region,
            bbox_space="global",
        )
        failed_items = [{"criterion": issue.criterion, "reason": issue.reason}]

        current_object_svg = item["current_object_svg"]
        object_task = create_object_task(
            object_id=obj.object_id,
            object_type=obj.object_type,
            description=obj.description,
            generation_focus=obj.generation_focus,
            region_id=region["region_id"],
            bbox=obj.bbox.model_dump(mode="json") if obj.bbox else None,
            current_svg=current_object_svg,
            failed_items=failed_items,
        )
        self._write_json(object_dir / "object_task.json", object_task)

        object_generation, object_generation_raw = self._generate_object_svg(
            object_crop_path=object_crop_path,
            region=region,
            obj=obj,
            current_svg=current_object_svg,
            failed_items=failed_items,
        )
        current_object_svg = object_generation.svg_elements
        self._write_text_async(object_dir / "object_svg_gen_iter_0_raw.txt", object_generation_raw)
        self._write_text(object_dir / "object_svg_gen_iter_0.svgfrag", current_object_svg)

        object_review, object_review_raw = self._review_object_svg(
            object_crop_path=object_crop_path,
            region=region,
            obj=obj,
            object_svg=current_object_svg,
            failed_items=failed_items,
        )
        self._write_text_async(object_dir / "object_review_iter_0_raw.txt", object_review_raw)
        object_iterations = [
            {
                "iteration": 0,
                "retry": self._retry_state(retry_task),
                "generation": object_generation.model_dump(mode="json"),
                "review": object_review.model_dump(mode="json"),
            }
        ]

        object_iteration = 0
        while object_review.failed_items and self._begin_retry(retry_task):
            object_iteration += 1
            failed_items = [entry.model_dump(mode="json") for entry in object_review.failed_items]
            object_generation, object_generation_raw = self._generate_object_svg(
                object_crop_path=object_crop_path,
                region=region,
                obj=obj,
                current_svg=current_object_svg,
                failed_items=failed_items,
            )
            current_object_svg = object_generation.svg_elements
            self._write_text_async(object_dir / f"object_svg_gen_iter_{object_iteration}_raw.txt", object_generation_raw)
            self._write_text(object_dir / f"object_svg_gen_iter_{object_iteration}.svgfrag", current_object_svg)
            object_review, object_review_raw = self._review_object_svg(
                object_crop_path=object_crop_path,
                region=region,
                obj=obj,
                object_svg=current_object_svg,
                failed_items=failed_items,
            )
            self._write_text_async(object_dir / f"object_review_iter_{object_iteration}_raw.txt", object_review_raw)
            object_iterations.append(
                {
                    "iteration": object_iteration,
                    "retry": self._retry_state(retry_task),
                    "generation": object_generation.model_dump(mode="json"),
                    "review": object_review.model_dump(mode="json"),
                }
            )

        object_record = {
            "object_id": obj.object_id,
            "retry_task": retry_task,
            "issue": issue.model_dump(mode="json"),
            "iterations": object_iterations,
            "retry": self._retry_state(retry_task),
            "final_svg_elements": current_object_svg,
        }
        self._write_json(object_dir / "object_history.json", object_record)
        self._write_text(object_dir / "final_object_elements.svgfrag", current_object_svg)
        return {
            "object_id": obj.object_id,
            "final_svg_elements": current_object_svg,
            "record": object_record,
        }

    def _generate_object_svg(
        self,
        *,
        object_crop_path: Path,
        region: dict,
        obj: ObjectCandidate,
        current_svg: str = "",
        failed_items: list[dict] | None = None,
    ) -> tuple[ObjectSvgGenerationResult, str]:
        return self.workflow_agents.object.svg_worker.run(
            object_crop_path=object_crop_path,
            obj=obj,
            current_svg=current_svg,
            current_svg_file_path=(
                self.workflow_agents.object._write_svg_prompt_attachment(
                    svg_text=current_svg,
                    svg_path=self.root_intermediate_dir / "_prompt_inputs" / region["region_id"] / obj.object_id / "current_object.svg",
                )
                if current_svg
                else None
            ),
            failed_items=failed_items,
        )

    def _review_object_svg(
        self,
        *,
        object_crop_path: Path,
        region: dict,
        obj: ObjectCandidate,
        object_svg: str,
        failed_items: list[dict] | None = None,
    ) -> tuple[ObjectReviewResult, str]:
        object_bbox = obj.bbox.model_dump(mode="json") if obj.bbox else {}
        review_dir = self.root_intermediate_dir / "_review_assets" / region["region_id"] / obj.object_id
        review_dir.mkdir(parents=True, exist_ok=True)
        svg_file_name = f"object-{obj.object_id}-review.svg"
        svg_path = review_dir / svg_file_name
        png_path = review_dir / f"object-{obj.object_id}-review.png"
        wrapped_svg = wrap_svg_fragment(
            object_svg,
            view_box=(
                int(object_bbox.get("x", 0)),
                int(object_bbox.get("y", 0)),
                max(int(object_bbox.get("width", 1)), 1),
                max(int(object_bbox.get("height", 1)), 1),
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
        return DebugObjectReviewWorkerAgent(self).run(
            object_crop_path=object_crop_path,
            obj=obj,
            object_svg=object_svg,
            failed_items=failed_items,
            rendered_svg_path=rendered_svg_path,
            svg_file_path=svg_path,
            svg_file_name=svg_file_name,
        )
