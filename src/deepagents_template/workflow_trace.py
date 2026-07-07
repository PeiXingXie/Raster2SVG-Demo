"""Build a compact workflow trace for the frontend artifact panel."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from deepagents_template.schemas import ExecutionRun, WorkflowTrace, WorkflowTraceNode, WorkflowTraceSummary


MAIN_STAGES: list[tuple[str, str]] = [
    ("prepare-input", "Prepare Input"),
    ("layout", "Layout Detect"),
    ("initial-generate", "Initial Generate"),
    ("initial-integrate", "Integrate"),
    ("refine", "Refine"),
    ("final-integrate", "Integrate"),
]

STAGE_INDEX = {key: index for index, (key, _) in enumerate(MAIN_STAGES)}
TERMINAL_RUN_STATUSES = {"completed", "failed", "paused", "needs_approval"}
PREPARE_INPUT_STAGES = {"queued", "preparing-context", "loading-input", "running-conversion"}
INITIAL_REGION_RESPONSE_MODELS = {
    "RegionRecognitionResult",
    "BboxAdjustmentResult",
    "BboxCombinedPolicyModelResult",
    "ObjectBboxCandidateGenerationResult",
    "ObjectBboxCandidateSelectionResult",
    "RegionSvgGenerationResult",
}
REGION_REVIEW_RESPONSE_MODELS = {"RegionCombinedPolicyModelResult"}
REGION_REPAIR_RESPONSE_MODELS = {"RegionSvgGenerationResult"}
OBJECT_REPAIR_RESPONSE_MODELS = {"ObjectCombinedPolicyModelResult", "ObjectSvgGenerationResult"}
MODEL_CALL_FILENAME_RE = re.compile(r"^(?P<call_index>\d+)_(?P<response_model>.+)_sent_message\.json$")
MODEL_CALL_STAGE_BY_RESPONSE_MODEL = {
    "LayoutDetectionResult": "layout",
    "BboxAdjustmentResult": "layout",
    "BboxCombinedPolicyModelResult": "layout",
    "ChecklistPlanResult": "prepare-input",
    "RegionRecognitionResult": "initial-generate",
    "ObjectInitialBboxResult": "initial-generate",
    "ObjectBboxCandidateGenerationResult": "initial-generate",
    "ObjectBboxCandidateSelectionResult": "initial-generate",
    "RegionSvgGenerationResult": "initial-generate",
    "RegionCombinedPolicyModelResult": "refine",
    "ObjectCombinedPolicyModelResult": "refine",
    "ObjectSvgGenerationResult": "refine",
    "FusionCombinedPolicyModelResult": "initial-integrate",
    "IntegratedSvgRepairResult": "final-integrate",
}


def _event_time(event: dict | object) -> datetime | None:
    return getattr(event, "timestamp", None)


def _payload(event: dict | object) -> dict:
    payload = getattr(event, "payload", None)
    return payload if isinstance(payload, dict) else {}


def _duration_ms(started_at: datetime | None, ended_at: datetime | None) -> int | None:
    if started_at is None or ended_at is None:
        return None
    return max(0, int((ended_at - started_at).total_seconds() * 1000))


def _safe_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _event_budget_used(event: dict | object) -> int | None:
    payload = _payload(event)
    value = payload.get("call_index")
    if value is None:
        api_budget = payload.get("api_budget")
        if isinstance(api_budget, dict):
            value = api_budget.get("used")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _coerce_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _load_json_file(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_text_id(raw_text: str, key: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]+)"', raw_text)
    return match.group(1) if match else None


def _object_region_index(run_dir: Path) -> dict[str, str]:
    index: dict[str, str] = {}
    region_root = run_dir / "intermediate" / "regions"
    if not region_root.is_dir():
        return index
    for initial_result_path in region_root.glob("*/initial_result.json"):
        payload = _load_json_file(initial_result_path)
        region_id = str(payload.get("region_id") or initial_result_path.parent.name)
        recognition = payload.get("recognition") if isinstance(payload.get("recognition"), dict) else {}
        objects = payload.get("recognized_objects") or payload.get("objects") or recognition.get("recognized_objects") or []
        if not isinstance(objects, list):
            continue
        for item in objects:
            if not isinstance(item, dict):
                continue
            object_id = item.get("object_id")
            if object_id:
                index[str(object_id)] = region_id
    return index


def _model_call_stage(response_model: str | None, call_index: int | None) -> str | None:
    if response_model in {"BboxAdjustmentResult", "BboxCombinedPolicyModelResult"} and call_index is not None and call_index > 4:
        return "initial-generate"
    if response_model == "RegionSvgGenerationResult" and call_index is not None and call_index >= 40:
        return "refine"
    return MODEL_CALL_STAGE_BY_RESPONSE_MODEL.get(str(response_model or ""))


def _model_call_records(run: ExecutionRun | None) -> list[tuple[int, object, dict]]:
    if run is None or not run.artifact_dir:
        return []
    model_call_dir = Path(run.artifact_dir) / "intermediate" / "model_calls"
    if not model_call_dir.is_dir():
        return []

    object_regions = _object_region_index(Path(run.artifact_dir))
    records: list[tuple[int, object, dict]] = []
    for request_path in sorted(model_call_dir.glob("*_sent_message.json")):
        match = MODEL_CALL_FILENAME_RE.match(request_path.name)
        if not match:
            continue
        call_index = _coerce_int(match.group("call_index"))
        request_payload = _load_json_file(request_path)
        response_model = str(request_payload.get("response_model") or match.group("response_model"))
        raw_path = request_path.with_name(request_path.name.replace("_sent_message.json", "_response_raw.txt"))
        raw_text = ""
        try:
            raw_text = raw_path.read_text(encoding="utf-8", errors="replace") if raw_path.is_file() else ""
        except OSError:
            raw_text = ""
        prompt_payload = request_payload.get("prompt") if isinstance(request_payload.get("prompt"), dict) else {}
        prompt_text = "\n".join(
            str(prompt_payload.get(key) or "")
            for key in ("user", "system")
        )

        region_id = request_payload.get("region_id") or _extract_text_id(prompt_text, "region_id") or _extract_text_id(raw_text, "region_id")
        object_id = request_payload.get("object_id") or _extract_text_id(prompt_text, "object_id") or _extract_text_id(raw_text, "object_id")
        if object_id and not region_id:
            region_id = object_regions.get(str(object_id))
        api_budget = request_payload.get("api_budget") if isinstance(request_payload.get("api_budget"), dict) else {}
        payload = {
            "call_index": call_index,
            "response_model": response_model,
            "region_id": str(region_id) if region_id else None,
            "object_id": str(object_id) if object_id else None,
            "target_id": str(object_id or region_id) if (object_id or region_id) else None,
            "target_type": "object" if object_id else ("region" if region_id else None),
            "api_budget": api_budget,
            "trace_stage": _model_call_stage(response_model, call_index),
            "request_path": str(request_path.relative_to(Path(run.artifact_dir))).replace("/", "\\"),
        }
        if raw_path.is_file():
            payload["raw_response_path"] = str(raw_path.relative_to(Path(run.artifact_dir))).replace("/", "\\")
        records.append((call_index if call_index is not None else len(records), None, payload))
    return records


def _stage_key_for_runtime(stage: str | None) -> str:
    value = (stage or "").strip().lower()
    if value in PREPARE_INPUT_STAGES or value in {"model-response", "context-payload", "summarizing-result", "completed", "paused-budget"}:
        return "prepare-input"
    if "layout" in value:
        return "layout"
    if value in {"planning", "region-cropping"}:
        return "initial-generate"
    if "initial" in value and "integrat" in value:
        return "initial-integrate"
    if "final" in value and "integrat" in value:
        return "final-integrate"
    if "refine" in value:
        return "refine"
    if "region-process" in value:
        return "refine" if "refine" in value else "initial-generate"
    if value == "integrate-process":
        return "initial-integrate"
    return "prepare-input"


def _run_failure_stage(run: ExecutionRun | None) -> str | None:
    if run is None:
        return None
    diagnostic_stage = getattr(getattr(run, "failure_diagnostic", None), "failure_stage", None)
    candidates = [
        run.failure_stage,
        diagnostic_stage,
        run.current_stage,
    ]
    for candidate in candidates:
        value = str(candidate or "").strip().lower()
        if "refine" in value:
            return str(candidate)
    for candidate in candidates:
        if candidate:
            return str(candidate)
    return None


def _effective_failure_stage_key(run: ExecutionRun | None) -> str | None:
    if run is None:
        return None
    failure_stage = _run_failure_stage(run)
    if failure_stage:
        return _stage_key_for_runtime(failure_stage)
    return _stage_key_for_runtime(run.current_stage)


def _is_budget_exhausted_failure(run: ExecutionRun | None) -> bool:
    if run is None:
        return False
    diagnostic = getattr(run, "failure_diagnostic", None)
    values = [
        getattr(diagnostic, "root_cause_type", None),
        getattr(diagnostic, "error_type", None),
        getattr(diagnostic, "root_cause_message", None),
        getattr(diagnostic, "error_message", None),
        run.error,
    ]
    return any("budgetexceedederror" in str(value or "").lower() or "max_budget exhausted" in str(value or "").lower() for value in values)


def _budget_exhausted_target(run: ExecutionRun | None) -> dict[str, str | None]:
    if not _is_budget_exhausted_failure(run):
        return {"region_id": None, "object_id": None}
    event_records = [
        _payload(event)
        for event in (run.events if run is not None else [])
        if getattr(event, "stage", None) == "model-response"
        and _model_call_stage(_payload(event).get("response_model"), _coerce_int(_payload(event).get("call_index"))) == "refine"
    ]
    records = [
        item[2]
        for item in _model_call_records(run)
        if item[2].get("trace_stage") == "refine"
    ]
    records.extend(event_records)
    records.sort(key=lambda payload: _coerce_int(payload.get("call_index")) or 0)
    for payload in reversed(records):
        region_id = payload.get("region_id")
        object_id = payload.get("object_id")
        if region_id or object_id:
            return {
                "region_id": str(region_id) if region_id else None,
                "object_id": str(object_id) if object_id else None,
            }
    return {"region_id": None, "object_id": None}


def _stage_key_for_direct_event(stage: str | None, *, integrate_count: int) -> str | None:
    value = (stage or "").strip().lower()
    if value in PREPARE_INPUT_STAGES:
        return "prepare-input"
    if value == "layout detection":
        return "layout"
    if value in {"planning", "region-cropping"}:
        return "initial-generate"
    if value == "region-process":
        return "initial-generate" if integrate_count == 0 else "refine"
    if value == "integrate-process":
        return "initial-integrate" if integrate_count == 0 else "final-integrate"
    if value in {"summarizing-result", "completed", "paused-budget", "failed"}:
        return "final-integrate" if integrate_count > 1 else "prepare-input"
    return None


def _build_stage_spans(run: ExecutionRun | None) -> tuple[dict[str, dict[str, Any]], str]:
    if run is None:
        return {}, "prepare-input"

    spans: dict[str, dict[str, Any]] = {}
    current_stage_key: str | None = None
    integrate_count = 0

    for index, event in enumerate(run.events or []):
        event_time = _event_time(event)
        if event_time is None:
            continue
        direct_stage_key = _stage_key_for_direct_event(getattr(event, "stage", None), integrate_count=integrate_count)
        if direct_stage_key is not None:
            if current_stage_key and current_stage_key != direct_stage_key:
                current_span = spans[current_stage_key]
                if current_span.get("ended_at") is None:
                    current_span["ended_at"] = event_time
                    current_span["duration_ms"] = _duration_ms(current_span.get("started_at"), event_time)
            current_stage_key = direct_stage_key
            span = spans.setdefault(
                direct_stage_key,
                {
                    "stage_key": direct_stage_key,
                    "started_at": event_time,
                    "ended_at": None,
                    "duration_ms": None,
                    "event_index": index,
                    "last_event_index": index,
                },
            )
            span["last_event_index"] = index
            if direct_stage_key in {"initial-integrate", "final-integrate"}:
                integrate_count += 1
        elif current_stage_key is not None:
            spans[current_stage_key]["last_event_index"] = index

    if current_stage_key and current_stage_key in spans:
        current_span = spans[current_stage_key]
        if run.status in TERMINAL_RUN_STATUSES and run.finished_at is not None:
            current_span["ended_at"] = run.finished_at
            current_span["duration_ms"] = _duration_ms(current_span.get("started_at"), run.finished_at)

    active_stage_key = current_stage_key or _stage_key_for_runtime(run.current_stage)
    if run.status in {"paused", "failed"}:
        active_stage_key = _effective_failure_stage_key(run) or active_stage_key
    return spans, active_stage_key


def _find_target_event_index(run: ExecutionRun | None, *, region_id: str | None = None, object_id: str | None = None) -> int | None:
    if run is None:
        return None
    matched = None
    for index, event in enumerate(run.events or []):
        payload = _payload(event)
        if region_id and payload.get("region_id") != region_id:
            continue
        if object_id:
            target_ids = payload.get("target_ids")
            if payload.get("object_id") != object_id and payload.get("target_id") != object_id and (
                not isinstance(target_ids, list) or object_id not in target_ids
            ):
                continue
        matched = index
    return matched


def _target_matches(payload: dict, *, region_id: str | None = None, object_id: str | None = None) -> bool:
    target_type = str(payload.get("target_type") or "").lower()
    target_id = payload.get("target_id")
    target_ids = payload.get("target_ids")
    if region_id:
        region_matches = (
            payload.get("region_id") == region_id
            or (target_type == "region" and target_id == region_id)
            or (not object_id and target_id == region_id)
        )
        if not region_matches and object_id:
            region_matches = payload.get("region_id") in {None, "", region_id}
        if not region_matches:
            return False
        if object_id:
            if payload.get("object_id") != object_id and payload.get("target_id") != object_id and (
                not isinstance(target_ids, list) or object_id not in target_ids
            ):
                return False
        return True
    if object_id:
        return payload.get("object_id") == object_id or payload.get("target_id") == object_id or (
            isinstance(target_ids, list) and object_id in target_ids
        )
    return False


def _event_in_stage_span(index: int, stage_spans: dict[str, dict[str, Any]], stage_key: str | None) -> bool:
    if not stage_key:
        return True
    if index < 0:
        return False
    span = stage_spans.get(stage_key) or {}
    start_index = span.get("event_index")
    end_index = span.get("last_event_index")
    if not isinstance(start_index, int) or not isinstance(end_index, int):
        return True
    return start_index <= index <= end_index


def _node_target_matches_event(node: WorkflowTraceNode, payload: dict) -> bool:
    if node.target_type == "object" and node.target_id:
        region_id = None
        if node.parent_node_id and node.parent_node_id.startswith("region:"):
            region_id = node.parent_node_id.split(":", 1)[1]
        elif node.node_id.startswith("object:"):
            parts = node.node_id.split(":")
            region_id = parts[1] if len(parts) > 2 else None
        return _target_matches(payload, region_id=region_id, object_id=str(node.target_id))
    if node.target_type == "region" and node.target_id:
        return _target_matches(payload, region_id=str(node.target_id))
    return True


def _node_operation_matches_event(
    node: WorkflowTraceNode,
    *,
    event_index: int,
    payload: dict,
    stage_spans: dict[str, dict[str, Any]],
) -> bool:
    response_models = node.meta.get("budget_response_models")
    if response_models:
        response_model = payload.get("response_model")
        if response_model not in set(response_models):
            return False
        if payload.get("trace_stage"):
            return payload.get("trace_stage") == node.meta.get("budget_stage_key") and _node_target_matches_event(node, payload)
        if not _event_in_stage_span(event_index, stage_spans, node.meta.get("budget_stage_key")):
            return False
        return _node_target_matches_event(node, payload)
    return False


def _target_event_span(
    run: ExecutionRun | None,
    *,
    region_id: str | None = None,
    object_id: str | None = None,
) -> dict[str, object]:
    if run is None:
        return {}
    started_at = None
    ended_at = None
    event_index = None
    last_event_index = None
    for index, event in enumerate(run.events or []):
        payload = _payload(event)
        if not _target_matches(payload, region_id=region_id, object_id=object_id):
            continue
        event_time = _event_time(event)
        if started_at is None:
            started_at = event_time
            event_index = index
        ended_at = event_time
        last_event_index = index
    return {
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": _duration_ms(started_at, ended_at),
        "event_index": event_index,
        "last_event_index": last_event_index,
    }


def _annotate_node_budgets(
    nodes: list[WorkflowTraceNode],
    run: ExecutionRun | None,
    *,
    stage_spans: dict[str, dict[str, Any]],
    budget_limit: int | None,
) -> None:
    if run is None:
        return
    response_events = [
        (index, event, _payload(event))
        for index, event in enumerate(run.events or [])
        if getattr(event, "stage", None) == "model-response"
    ]
    records_by_call: dict[int, tuple[int, object, dict]] = {}
    records_without_call: list[tuple[int, object, dict]] = []
    for item in [*response_events, *_model_call_records(run)]:
        call_index = _coerce_int(item[2].get("call_index"))
        if call_index is None:
            records_without_call.append(item)
            continue
        records_by_call[call_index] = item
    response_events = [*records_by_call.values(), *records_without_call]
    response_events.sort(key=lambda item: (_coerce_int(item[2].get("call_index")) is None, _coerce_int(item[2].get("call_index")) or item[0]))
    if not response_events:
        return

    def budget_level_for(node: WorkflowTraceNode) -> str:
        if node.target_type == "object" or node.kind == "object":
            return "object"
        if node.target_type == "region" or node.kind == "region":
            return "region"
        if node.kind == "loop":
            return "repair"
        return "stage"

    for node in nodes:
        matched: list[tuple[int, object, dict]] = []
        if node.meta.get("budget_response_models"):
            matched = [
                item for item in response_events
                if _node_operation_matches_event(
                    node,
                    event_index=item[0],
                    payload=item[2],
                    stage_spans=stage_spans,
                )
            ]
        elif node.target_type == "object" and node.target_id:
            region_id = None
            if node.parent_node_id and node.parent_node_id.startswith("region:"):
                region_id = node.parent_node_id.split(":", 1)[1]
            elif node.node_id.startswith("object:"):
                parts = node.node_id.split(":")
                region_id = parts[1] if len(parts) > 2 else None
            matched = [
                item for item in response_events
                if _target_matches(item[2], region_id=region_id, object_id=str(node.target_id))
            ]
        elif node.target_type == "region" and node.target_id:
            matched = [
                item for item in response_events
                if _target_matches(item[2], region_id=str(node.target_id))
            ]
        elif node.stage_key:
            trace_stage_matches = [
                item for item in response_events
                if item[2].get("trace_stage") == node.stage_key
            ]
            if trace_stage_matches:
                matched = trace_stage_matches
            else:
                span = stage_spans.get(node.stage_key) or {}
                start_index = span.get("event_index")
                end_index = span.get("last_event_index")
                if isinstance(start_index, int) and isinstance(end_index, int):
                    matched = [
                        item for item in response_events
                        if start_index <= item[0] <= end_index
                    ]
                else:
                    models_for_stage = {
                        model
                        for model, stage_key in MODEL_CALL_STAGE_BY_RESPONSE_MODEL.items()
                        if stage_key == node.stage_key
                    }
                    matched = [
                        item for item in response_events
                        if item[2].get("response_model") in models_for_stage
                    ]

        if not matched:
            continue
        node.meta["budget_used"] = len(matched)
        node.meta["budget_last"] = _event_budget_used(matched[-1][1])
        if budget_limit is not None:
            node.meta["budget_limit"] = budget_limit
        node.meta["budget_scope"] = "node"
        node.meta["budget_level"] = budget_level_for(node)


def _worker_by_task(run: ExecutionRun | None) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    if run is None:
        return mapping
    for worker in run.worker_statuses or []:
        if worker.task_id:
            mapping[worker.task_id] = worker.model_dump(mode="python")
    return mapping


def _build_main_stage_nodes(
    run: ExecutionRun | None,
    *,
    active_stage_key: str,
    stage_spans: dict[str, dict[str, Any]],
) -> list[WorkflowTraceNode]:
    current_stage_key = _effective_failure_stage_key(run) if run is not None and run.status == "failed" else active_stage_key
    current_index = STAGE_INDEX.get(current_stage_key, 0)
    nodes: list[WorkflowTraceNode] = []
    for index, (stage_key, label) in enumerate(MAIN_STAGES):
        status = "pending"
        summary = None
        span = stage_spans.get(stage_key, {})
        if run is not None:
            if index < current_index:
                status = "success"
            elif index == current_index:
                if run.status == "failed":
                    status = "failed" if stage_key == current_stage_key else ("success" if index < current_index else "pending")
                    summary = (
                        getattr(run.failure_diagnostic, "summary", None)
                        or getattr(run.failure_diagnostic, "error_message", None)
                        or run.error
                        or "Execution failed"
                    )
                elif run.status == "paused":
                    status = "blocked" if stage_key == current_stage_key else "pending"
                    summary = "Paused for resume" if stage_key == current_stage_key else None
                elif run.status == "completed" and stage_key == "final-integrate":
                    status = "success"
                    summary = "Workflow completed"
                else:
                    status = "running"
            elif run.status == "completed" and stage_key == "final-integrate":
                status = "success"
        started_at = span.get("started_at")
        ended_at = span.get("ended_at")
        duration_ms = span.get("duration_ms")
        if run is not None and started_at is not None and duration_ms is None and status in {"running", "retrying"}:
            duration_ms = _duration_ms(started_at, run.updated_at)
        nodes.append(
            WorkflowTraceNode(
                node_id=stage_key,
                label=label,
                kind="stage",
                status=status,
                summary=summary,
                stage_key=stage_key,
                event_index=span.get("event_index"),
                started_at=started_at,
                ended_at=ended_at if status in {"success", "failed", "blocked"} else None,
                duration_ms=duration_ms,
            )
        )
    return nodes


def _region_route(result: dict[str, Any]) -> str | None:
    review_history = _safe_list(result.get("review_history"))
    for item in reversed(review_history):
        if isinstance(item, dict):
            decision = item.get("decision") or {}
            route = decision.get("final_route")
            if route:
                return str(route)
    return None


def _region_reason(result: dict[str, Any]) -> str | None:
    review_history = _safe_list(result.get("review_history"))
    for item in reversed(review_history):
        if isinstance(item, dict):
            decision = item.get("decision") or {}
            for key in ("final_reason", "final_route_reason", "route_rationale", "rationale"):
                if decision.get(key):
                    return str(decision[key])
    return None


def _region_timing(run: ExecutionRun | None, region_id: str, worker_status: dict[str, Any] | None) -> dict[str, object]:
    if worker_status:
        started_at = worker_status.get("started_at")
        updated_at = worker_status.get("updated_at")
        duration_ms = worker_status.get("duration_ms")
        ended_at = updated_at if worker_status.get("status") in {"completed", "failed"} else None
        return {
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_ms": duration_ms if isinstance(duration_ms, int) else _duration_ms(started_at, ended_at),
            "event_index": _find_target_event_index(run, region_id=region_id),
        }
    return _target_event_span(run, region_id=region_id)


def _region_semantic_stage(
    *,
    run: ExecutionRun | None,
    worker_status: dict[str, Any] | None,
    region_id: str,
    phase: str,
    fallback: str | None = None,
) -> str | None:
    if worker_status and worker_status.get("semantic_stage"):
        return str(worker_status["semantic_stage"])
    if run is not None:
        for event in reversed(run.events or []):
            payload = _payload(event)
            if payload.get("region_id") != region_id:
                continue
            if payload.get("phase") != phase:
                continue
            semantic_stage = payload.get("semantic_stage")
            if semantic_stage:
                return str(semantic_stage)
    return fallback


def _build_layout_loop_node(
    run: ExecutionRun | None,
    *,
    current_stage_key: str,
    stage_spans: dict[str, dict[str, Any]],
) -> WorkflowTraceNode | None:
    if run is None:
        return None
    layout_span = stage_spans.get("layout")
    if not layout_span:
        return None
    start_index = layout_span.get("event_index")
    end_index = layout_span.get("last_event_index")
    if not isinstance(start_index, int) or not isinstance(end_index, int):
        return None

    adjustment_calls = 0
    policy_calls = 0
    loop_started_at = None
    loop_ended_at = None
    loop_event_index = None
    issues_count = 0
    stop_reason = None

    for offset, event in enumerate((run.events or [])[start_index : end_index + 1]):
        payload = _payload(event)
        response_model = payload.get("response_model")
        if response_model in {"BboxAdjustmentResult", "BboxCombinedPolicyModelResult"}:
            event_time = _event_time(event)
            if loop_started_at is None:
                loop_started_at = event_time
                loop_event_index = start_index + offset
            loop_ended_at = event_time
            if response_model == "BboxAdjustmentResult":
                adjustment_calls += 1
            else:
                policy_calls += 1
        if getattr(event, "stage", "") == "layout detection" and "bbox supervisor loop" in (getattr(event, "title", "") or "").lower():
            issues = payload.get("issues")
            if isinstance(issues, list):
                issues_count = len(issues)
            stop_reason = payload.get("stop_reason")
            loop_ended_at = _event_time(event)

    if adjustment_calls == 0 and policy_calls == 0 and not stop_reason:
        return None

    status = "success"
    if run.status == "failed" and current_stage_key == "layout":
        status = "failed"
    elif current_stage_key == "layout":
        status = "retrying" if adjustment_calls > 1 or policy_calls > 0 else "running"
    elif issues_count:
        status = "blocked"

    summary_parts = []
    if adjustment_calls:
        summary_parts.append(f"{adjustment_calls} iteration{'s' if adjustment_calls != 1 else ''}")
    if issues_count:
        summary_parts.append(f"{issues_count} residual issue{'s' if issues_count != 1 else ''}")
    if stop_reason:
        summary_parts.append(str(stop_reason))

    return WorkflowTraceNode(
        node_id="layout:bbox-loop",
        parent_node_id="layout",
        label="Layout BBox Loop",
        kind="loop",
        status=status,
        summary=" | ".join(summary_parts) if summary_parts else None,
        started_at=loop_started_at,
        ended_at=loop_ended_at if status not in {"running", "retrying"} else None,
        duration_ms=_duration_ms(loop_started_at, loop_ended_at),
        event_index=loop_event_index if isinstance(loop_event_index, int) else start_index,
        meta={
            "retries_total": adjustment_calls,
            "budget_stage_key": "layout",
            "budget_response_models": ["BboxAdjustmentResult", "BboxCombinedPolicyModelResult"],
        },
    )


def _build_initial_generate_nodes(
    run: ExecutionRun | None,
    *,
    current_stage_key: str,
    regions: list[dict[str, Any]],
) -> list[WorkflowTraceNode]:
    if not regions:
        return []

    current_index = STAGE_INDEX.get(current_stage_key, 0)
    initial_index = STAGE_INDEX["initial-generate"]
    branch_status = "pending"
    if current_index > initial_index or (run is not None and run.status in TERMINAL_RUN_STATUSES and current_index >= initial_index):
        branch_status = "success"
    elif current_stage_key == "initial-generate":
        branch_status = "running"

    branch_started_at = None
    branch_ended_at = None
    branch_event_index = None
    nodes = [
        WorkflowTraceNode(
            node_id="initial-generate:parallel",
            parent_node_id="initial-generate",
            label="Parallel Region Branches",
            kind="stage",
            status=branch_status,
            summary=f"{len(regions)} region branch{'es' if len(regions) != 1 else ''}",
            execution_mode="parallel",
        )
    ]

    workers = _worker_by_task(run)
    for region in regions:
        region_id = str(region.get("region_id") or "")
        worker_status = workers.get(region_id)
        timing = _target_event_span(run, region_id=region_id)
        started_at = timing.get("started_at")
        ended_at = timing.get("ended_at")
        duration_ms = timing.get("duration_ms")
        event_index = timing.get("event_index")
        if branch_started_at is None or (started_at is not None and started_at < branch_started_at):
            branch_started_at = started_at
        if branch_ended_at is None or (ended_at is not None and ended_at > branch_ended_at):
            branch_ended_at = ended_at
        if branch_event_index is None and event_index is not None:
            branch_event_index = event_index

        status = "pending"
        if current_index > initial_index or (run is not None and run.status in TERMINAL_RUN_STATUSES and current_index >= initial_index):
            status = "success"
        elif current_stage_key == "initial-generate" and started_at is not None:
            status = "running"

        object_count = len(_safe_list(region.get("objects")))
        summary = f"{object_count} object{'s' if object_count != 1 else ''}" if object_count else "Initial region branch prepared."
        nodes.append(
            WorkflowTraceNode(
                node_id=f"initial-region:{region_id}",
                parent_node_id="initial-generate:parallel",
                label="Region Pass",
                kind="region",
                status=status,
                summary=summary,
                semantic_stage=_region_semantic_stage(
                    run=run,
                    worker_status=worker_status,
                    region_id=region_id,
                    phase="initial",
                    fallback="Prepared" if status == "success" else None,
                ),
                target_type="region",
                target_id=region_id,
                started_at=started_at,
                ended_at=ended_at if status == "success" else None,
                duration_ms=duration_ms,
                event_index=event_index,
                meta={
                    "objects_total": object_count,
                    "budget_stage_key": "initial-generate",
                    "budget_response_models": sorted(INITIAL_REGION_RESPONSE_MODELS),
                },
            )
        )

    nodes[0].started_at = branch_started_at
    nodes[0].ended_at = branch_ended_at if branch_status == "success" else None
    nodes[0].duration_ms = _duration_ms(branch_started_at, branch_ended_at)
    nodes[0].event_index = branch_event_index
    return nodes


def _refine_region_status(
    *,
    current_stage_key: str,
    run: ExecutionRun | None,
    region: dict[str, Any],
    result: dict[str, Any],
    worker_status: dict[str, Any] | None,
    budget_blocked_region_id: str | None = None,
) -> tuple[str, str | None]:
    retry_used = int(region.get("retry_used") or 0)
    object_retries = sum(int(item.get("retry_used") or 0) for item in _safe_list(region.get("objects")))
    total_retries = retry_used + object_retries
    before_refine = STAGE_INDEX.get(current_stage_key, 0) < STAGE_INDEX["refine"]
    if before_refine:
        return "pending", None
    if worker_status and worker_status.get("status") == "running":
        return ("retrying" if total_retries > 0 else "running"), worker_status.get("detail")
    if result.get("retry_exhausted") or region.get("retry_exhausted"):
        return "blocked", _region_reason(result) or "Retry exhausted"
    if budget_blocked_region_id and str(region.get("region_id") or "") == budget_blocked_region_id:
        return "blocked", "Run budget exhausted during refinement"
    if run is not None and run.status == "running" and current_stage_key == "refine":
        if total_retries > 0:
            return "retrying", _region_reason(result) or "Refinement loop still active"
        return "issue_detected", "Waiting for review route"
    if total_retries > 0:
        return "success", f"Accepted after {total_retries} retr{'y' if total_retries == 1 else 'ies'}"
    if run is not None and run.status in {"completed", "paused", "failed"}:
        return "success", None
    return "pending", None


def _build_refine_nodes(
    run: ExecutionRun | None,
    *,
    current_stage_key: str,
    regions: list[dict[str, Any]],
    region_results: list[dict[str, Any]],
) -> tuple[list[WorkflowTraceNode], WorkflowTraceSummary]:
    results_by_id = {
        item.get("region_id"): item
        for item in region_results
        if isinstance(item, dict) and item.get("region_id")
    }
    workers = _worker_by_task(run)
    nodes: list[WorkflowTraceNode] = []
    retrying_regions = 0
    blocked_regions = 0
    direct_accept_regions = 0
    active_node_id = None
    region_nodes: list[WorkflowTraceNode] = []
    branch_started_at = None
    branch_ended_at = None
    branch_event_index = None
    budget_exhausted_in_refine = run is not None and run.status in {"failed", "paused"} and current_stage_key == "refine" and _is_budget_exhausted_failure(run)
    budget_target = _budget_exhausted_target(run) if budget_exhausted_in_refine else {"region_id": None, "object_id": None}
    budget_blocked_region_id = budget_target.get("region_id")
    budget_blocked_object_id = budget_target.get("object_id")

    for region in regions:
        region_id = str(region.get("region_id") or "")
        result = results_by_id.get(region_id, {})
        worker_status = workers.get(region_id)
        status, summary = _refine_region_status(
            current_stage_key=current_stage_key,
            run=run,
            region=region,
            result=result,
            worker_status=worker_status,
            budget_blocked_region_id=budget_blocked_region_id,
        )
        route = _region_route(result)
        retries_total = int(region.get("retry_used") or 0) + sum(
            int(item.get("retry_used") or 0)
            for item in _safe_list(region.get("objects"))
        )
        if status == "retrying":
            retrying_regions += 1
        if status == "blocked":
            blocked_regions += 1
        if status == "success" and retries_total == 0:
            direct_accept_regions += 1
        if active_node_id is None and status in {"running", "retrying"}:
            active_node_id = f"region:{region_id}"
        if status == "blocked" and budget_blocked_region_id == region_id:
            active_node_id = f"object:{region_id}:{budget_blocked_object_id}" if budget_blocked_object_id else f"region:{region_id}"
        region_timing = _region_timing(run, region_id, worker_status)
        region_started_at = region_timing.get("started_at")
        region_ended_at = region_timing.get("ended_at")
        region_duration_ms = region_timing.get("duration_ms")
        if branch_started_at is None or (region_started_at is not None and region_started_at < branch_started_at):
            branch_started_at = region_started_at
        if branch_ended_at is None or (region_ended_at is not None and region_ended_at > branch_ended_at):
            branch_ended_at = region_ended_at
        if branch_event_index is None and region_timing.get("event_index") is not None:
            branch_event_index = region_timing.get("event_index")

        region_nodes.append(
            WorkflowTraceNode(
                node_id=f"region:{region_id}",
                parent_node_id="refine:parallel",
                label="Region Pass",
                kind="region",
                status=status,
                summary=summary,
                semantic_stage=_region_semantic_stage(
                    run=run,
                    worker_status=worker_status,
                    region_id=region_id,
                    phase="refine",
                ),
                target_type="region",
                target_id=region_id,
                route=route,
                started_at=region_started_at,
                ended_at=region_ended_at if status not in {"running", "retrying"} else None,
                duration_ms=region_duration_ms,
                event_index=region_timing.get("event_index"),
                meta={
                    "retries_total": retries_total,
                    "retry_used": region.get("retry_used") or 0,
                    "objects_with_retries": sum(
                        1
                        for item in _safe_list(region.get("objects"))
                        if int(item.get("retry_used") or 0) > 0 or item.get("retry_exhausted")
                    ),
                    "budget_stage_key": "refine",
                    "budget_response_models": sorted(REGION_REVIEW_RESPONSE_MODELS),
                },
            )
        )

        if retries_total > 0 or route or status in {"running", "retrying", "issue_detected", "blocked"}:
            loop_status = "blocked" if status == "blocked" else ("retrying" if status in {"running", "retrying"} else "success")
            loop_summary: list[str] = []
            if retries_total > 0:
                loop_summary.append(f"{retries_total} retr{'y' if retries_total == 1 else 'ies'}")
            if route:
                loop_summary.append(f"route {route}")
            region_nodes.append(
                WorkflowTraceNode(
                    node_id=f"region:{region_id}:loop",
                    parent_node_id=f"region:{region_id}",
                    label="Repair Loop",
                    kind="loop",
                    status=loop_status,
                    summary=" | ".join(loop_summary) or summary,
                    semantic_stage=_region_semantic_stage(
                        run=run,
                        worker_status=worker_status,
                        region_id=region_id,
                        phase="refine",
                    ),
                    target_type="region",
                    target_id=region_id,
                    route=route,
                    iteration=retries_total if retries_total > 0 else None,
                    started_at=region_started_at,
                    ended_at=region_ended_at if loop_status not in {"running", "retrying"} else None,
                    duration_ms=region_duration_ms,
                    event_index=region_timing.get("event_index"),
                    meta={
                        "retries_total": retries_total,
                        "budget_stage_key": "refine",
                        "budget_response_models": sorted(REGION_REPAIR_RESPONSE_MODELS),
                    },
                )
            )

        budget_object_node_added = False
        for obj in _safe_list(region.get("objects")):
            object_id = str(obj.get("object_id") or "")
            retry_used = int(obj.get("retry_used") or 0)
            retry_exhausted = bool(obj.get("retry_exhausted"))
            object_history = next(
                (
                    item for item in _safe_list(result.get("object_history"))
                    if isinstance(item, dict) and item.get("object_id") == object_id
                ),
                {},
            )
            final_decision = object_history.get("final_decision") or {}
            final_review = final_decision.get("review") or {}
            has_failed_items = bool(_safe_list(final_review.get("failed_items")))
            if retry_used <= 0 and not retry_exhausted and not object_history:
                if not (budget_blocked_region_id == region_id and budget_blocked_object_id == object_id):
                    continue
            if budget_blocked_region_id == region_id and budget_blocked_object_id == object_id:
                budget_object_node_added = True
            if retry_used <= 0 and not retry_exhausted and not object_history and not budget_object_node_added:
                continue
            object_status = "success"
            object_summary = None
            if budget_blocked_region_id == region_id and budget_blocked_object_id == object_id:
                object_status = "blocked"
                object_summary = "Run budget exhausted during object review"
            elif retry_exhausted or has_failed_items:
                object_status = "blocked"
                object_summary = "Retry exhausted" if retry_exhausted else "Still unresolved after repair"
            elif retry_used > 0:
                object_summary = f"Accepted after {retry_used} retr{'y' if retry_used == 1 else 'ies'}"
            object_timing = _target_event_span(run, region_id=region_id, object_id=object_id)
            if object_timing.get("started_at") is None:
                object_timing = {
                    "started_at": region_started_at,
                    "ended_at": region_ended_at,
                    "duration_ms": region_duration_ms,
                    "event_index": region_timing.get("event_index"),
                }
            region_nodes.append(
                WorkflowTraceNode(
                    node_id=f"object:{region_id}:{object_id}",
                    parent_node_id=f"region:{region_id}",
                    label="Object Pass",
                    kind="object",
                    status=object_status,
                    summary=object_summary,
                    target_type="object",
                    target_id=object_id,
                    started_at=object_timing.get("started_at"),
                    ended_at=object_timing.get("ended_at") if object_status not in {"running", "retrying"} else None,
                    duration_ms=object_timing.get("duration_ms"),
                    event_index=object_timing.get("event_index"),
                    meta={
                        "retry_used": retry_used,
                        "object_type": obj.get("object_type") or "",
                        "budget_stage_key": "refine",
                        "budget_response_models": sorted(OBJECT_REPAIR_RESPONSE_MODELS),
                    },
                )
            )
        if budget_blocked_region_id == region_id and budget_blocked_object_id and not budget_object_node_added:
            object_timing = _target_event_span(run, region_id=region_id, object_id=budget_blocked_object_id)
            if object_timing.get("started_at") is None:
                object_timing = {
                    "started_at": region_started_at,
                    "ended_at": region_ended_at,
                    "duration_ms": region_duration_ms,
                    "event_index": region_timing.get("event_index"),
                }
            region_nodes.append(
                WorkflowTraceNode(
                    node_id=f"object:{region_id}:{budget_blocked_object_id}",
                    parent_node_id=f"region:{region_id}",
                    label="Object Pass",
                    kind="object",
                    status="blocked",
                    summary="Run budget exhausted during object review",
                    target_type="object",
                    target_id=budget_blocked_object_id,
                    started_at=object_timing.get("started_at"),
                    ended_at=object_timing.get("ended_at"),
                    duration_ms=object_timing.get("duration_ms"),
                    event_index=object_timing.get("event_index"),
                    meta={
                        "retry_used": 0,
                        "budget_stage_key": "refine",
                        "budget_response_models": sorted(OBJECT_REPAIR_RESPONSE_MODELS),
                    },
                )
            )

    if regions:
        branch_status = "pending"
        if budget_exhausted_in_refine:
            branch_status = "blocked"
        elif current_stage_key == "refine":
            branch_status = "retrying" if retrying_regions else "running"
        elif blocked_regions:
            branch_status = "blocked"
        elif STAGE_INDEX.get(current_stage_key, 0) > STAGE_INDEX["refine"] or (run is not None and run.status in TERMINAL_RUN_STATUSES):
            branch_status = "success"
        nodes.append(
            WorkflowTraceNode(
                node_id="refine:parallel",
                parent_node_id="refine",
                label="Parallel Region Branches",
                kind="stage",
                status=branch_status,
                summary=f"{len(regions)} region branch{'es' if len(regions) != 1 else ''}",
                execution_mode="parallel",
                started_at=branch_started_at,
                ended_at=branch_ended_at if branch_status not in {"running", "retrying"} else None,
                duration_ms=_duration_ms(branch_started_at, branch_ended_at),
                event_index=branch_event_index,
            )
        )
    nodes.extend(region_nodes)

    summary = WorkflowTraceSummary(
        status=run.status if run is not None else "idle",
        active_node_id=active_node_id,
        regions_total=len(regions),
        retrying_regions=retrying_regions,
        blocked_regions=blocked_regions,
        direct_accept_regions=direct_accept_regions,
    )
    return nodes, summary


def build_workflow_trace(
    run: ExecutionRun | None,
    *,
    regions: list[dict[str, Any]] | None = None,
    region_results: list[dict[str, Any]] | None = None,
) -> WorkflowTrace:
    region_list = regions or []
    region_result_list = region_results or []
    stage_spans, active_stage_key = _build_stage_spans(run)
    nodes = _build_main_stage_nodes(run, active_stage_key=active_stage_key, stage_spans=stage_spans)
    nodes.extend(
        _build_initial_generate_nodes(
            run,
            current_stage_key=active_stage_key,
            regions=region_list,
        )
    )
    layout_loop_node = _build_layout_loop_node(run, current_stage_key=active_stage_key, stage_spans=stage_spans)
    if layout_loop_node is not None:
        nodes.append(layout_loop_node)
    refine_nodes, summary = _build_refine_nodes(
        run,
        current_stage_key=active_stage_key,
        regions=region_list,
        region_results=region_result_list,
    )
    nodes.extend(refine_nodes)

    budget_limit = None
    budget_used = None
    if run is not None:
        start_event = next((event for event in run.events or [] if getattr(event, "stage", None) == "running-conversion"), None)
        if start_event and isinstance(start_event.payload, dict):
            budget_limit = start_event.payload.get("max_budget")
        response_events = [event for event in run.events or [] if getattr(event, "stage", None) == "model-response"]
        event_budget_values: list[int] = []
        for event in response_events:
            payload = _payload(event)
            api_budget = payload.get("api_budget")
            if isinstance(api_budget, dict) and budget_limit is None and api_budget.get("limit") is not None:
                budget_limit = api_budget.get("limit")
            value = _coerce_int(payload.get("call_index"))
            if value is None:
                if isinstance(api_budget, dict):
                    value = _coerce_int(api_budget.get("used"))
            if value is not None:
                event_budget_values.append(value)
        if event_budget_values:
            budget_used = max(event_budget_values)
        if budget_used is None:
            model_call_records = _model_call_records(run)
            latest_call = max((_coerce_int(item[2].get("call_index")) or 0 for item in model_call_records), default=0)
            budget_used = latest_call or len(response_events)
        if budget_limit is None:
            model_call_records = _model_call_records(run)
            for item in reversed(model_call_records):
                api_budget = item[2].get("api_budget")
                if isinstance(api_budget, dict) and api_budget.get("limit") is not None:
                    budget_limit = api_budget.get("limit")
                    break

    loop_iterations_total = 0
    for node in nodes:
        if node.kind != "loop":
            continue
        if isinstance(node.iteration, int):
            loop_iterations_total += max(node.iteration, 0)
        else:
            loop_iterations_total += int(node.meta.get("retries_total") or 0)

    if layout_loop_node is not None and layout_loop_node.status in {"running", "retrying"}:
        summary.active_node_id = layout_loop_node.node_id

    for node in nodes:
        if node.node_id == "refine":
            if summary.regions_total:
                parts = [f"{summary.regions_total} regions"]
                if summary.retrying_regions:
                    parts.append(f"{summary.retrying_regions} retrying")
                if summary.blocked_regions:
                    parts.append(f"{summary.blocked_regions} blocked")
                if summary.direct_accept_regions:
                    parts.append(f"{summary.direct_accept_regions} direct accept")
                node.summary = " | ".join(parts)
            node.execution_mode = "parallel"
            if run is not None and active_stage_key == "refine" and node.status == "running":
                node.status = "retrying" if summary.retrying_regions else "running"

    if summary.active_node_id is None:
        summary.active_node_id = next(
            (
                node.node_id
                for node in nodes
                if node.status in {"running", "retrying"}
            ),
            None,
        )

    if run is not None and run.started_at is not None:
        trace_end = run.finished_at or run.updated_at
        if trace_end is not None:
            summary.total_duration_ms = max(0, int((trace_end - run.started_at).total_seconds() * 1000))
    summary.loop_iterations_total = loop_iterations_total
    summary.budget_used = budget_used
    summary.budget_limit = budget_limit
    _annotate_node_budgets(
        nodes,
        run,
        stage_spans=stage_spans,
        budget_limit=budget_limit,
    )
    return WorkflowTrace(summary=summary, nodes=nodes)
