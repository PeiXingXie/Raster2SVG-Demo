"""Build a compact workflow trace for the frontend artifact panel."""

from __future__ import annotations

from datetime import datetime

from deepagents_template.schemas import ExecutionRun, WorkflowTrace, WorkflowTraceNode, WorkflowTraceSummary


MAIN_STAGES: list[tuple[str, str]] = [
    ("prepare-input", "Prepare Input"),
    ("layout", "Layout"),
    ("initial-region-build", "Initial Region Build"),
    ("initial-integrate", "Initial Integrate"),
    ("refine", "Refine"),
    ("final-integrate", "Final Integrate"),
    ("final-decision", "Final Decision"),
]

STAGE_INDEX = {key: index for index, (key, _) in enumerate(MAIN_STAGES)}
TERMINAL_RUN_STATUSES = {"completed", "failed", "paused", "needs_approval"}
PREPARE_INPUT_STAGES = {"queued", "preparing-context", "loading-input", "running-conversion"}
FINAL_DECISION_STAGES = {"summarizing-result", "completed", "paused-budget", "failed"}


def _event_time(event: dict | object) -> datetime | None:
    return getattr(event, "timestamp", None)


def _payload(event: dict | object) -> dict:
    payload = getattr(event, "payload", None)
    return payload if isinstance(payload, dict) else {}


def _duration_ms(started_at: datetime | None, ended_at: datetime | None) -> int | None:
    if started_at is None or ended_at is None:
        return None
    return max(0, int((ended_at - started_at).total_seconds() * 1000))


def _stage_key_for_runtime(stage: str | None) -> str:
    value = (stage or "").strip().lower()
    if value in PREPARE_INPUT_STAGES or value in {"model-response", "context-payload"}:
        return "prepare-input"
    if "layout" in value:
        return "layout"
    if "initial" in value and "integrat" in value:
        return "initial-integrate"
    if "final" in value and "integrat" in value:
        return "final-integrate"
    if "refine" in value:
        return "refine"
    if "region-process" in value:
        return "initial-region-build"
    if "summariz" in value or value in FINAL_DECISION_STAGES:
        return "final-decision"
    return "prepare-input"


def _effective_failure_stage_key(run: ExecutionRun | None) -> str | None:
    if run is None:
        return None
    failure_stage = run.failure_stage or getattr(run.failure_diagnostic, "failure_stage", None)
    if failure_stage:
        return _stage_key_for_runtime(failure_stage)
    return _stage_key_for_runtime(run.current_stage)


def _stage_key_for_direct_event(stage: str | None, *, integrate_count: int) -> str | None:
    value = (stage or "").strip().lower()
    if value in PREPARE_INPUT_STAGES:
        return "prepare-input"
    if value == "layout detection":
        return "layout"
    if value in {"planning", "region-cropping", "region-process"}:
        return "initial-region-build" if integrate_count == 0 else "refine"
    if value == "integrate-process":
        return "initial-integrate" if integrate_count == 0 else "final-integrate"
    if value in FINAL_DECISION_STAGES:
        return "final-decision"
    return None


def _build_stage_spans(run: ExecutionRun | None) -> tuple[dict[str, dict], str]:
    if run is None:
        return {}, "prepare-input"

    spans: dict[str, dict] = {}
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
    return spans, active_stage_key


def _find_target_event_index(run: ExecutionRun | None, *, region_id: str | None = None, object_id: str | None = None) -> int | None:
    if run is None:
        return None
    matched = None
    for index, event in enumerate(run.events or []):
        payload = _payload(event)
        if region_id and payload.get("region_id") != region_id:
            continue
        if object_id and payload.get("object_id") != object_id:
            continue
        if region_id or object_id:
            matched = index
    return matched


def _target_matches(payload: dict, *, region_id: str | None = None, object_id: str | None = None) -> bool:
    if region_id:
        if payload.get("region_id") != region_id:
            return False
        if object_id:
            target_ids = payload.get("target_ids")
            if payload.get("object_id") != object_id and payload.get("target_id") != object_id and (
                not isinstance(target_ids, list) or object_id not in target_ids
            ):
                return False
        return True
    if object_id:
        target_ids = payload.get("target_ids")
        return payload.get("object_id") == object_id or payload.get("target_id") == object_id or (
            isinstance(target_ids, list) and object_id in target_ids
        )
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


def _worker_by_task(run: ExecutionRun | None) -> dict[str, dict]:
    mapping: dict[str, dict] = {}
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
    stage_spans: dict[str, dict],
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
                if run.status == "completed" and stage_key == "final-decision":
                    status = "success"
                    summary = "Workflow completed"
                elif run.status in {"failed"}:
                    status = "failed" if stage_key == current_stage_key else ("success" if index < current_index else "pending")
                    summary = (
                        getattr(run.failure_diagnostic, "summary", None)
                        or getattr(run.failure_diagnostic, "error_message", None)
                        or run.error
                        or "Execution failed"
                    )
                elif run.status == "paused":
                    status = "blocked" if stage_key == "final-decision" else ("retrying" if stage_key == "refine" else "running")
                    summary = "Paused for resume" if stage_key == "final-decision" else None
                else:
                    status = "retrying" if stage_key == "refine" else "running"
            elif run.status == "completed" and stage_key == "final-decision":
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
                kind="terminal" if stage_key == "final-decision" else "stage",
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


def _safe_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _region_route(result: dict) -> str | None:
    review_history = _safe_list(result.get("review_history"))
    for item in reversed(review_history):
        if isinstance(item, dict):
            decision = item.get("decision") or {}
            route = decision.get("final_route")
            if route:
                return str(route)
    return None


def _region_reason(result: dict) -> str | None:
    review_history = _safe_list(result.get("review_history"))
    for item in reversed(review_history):
        if isinstance(item, dict):
            decision = item.get("decision") or {}
            for key in ("final_reason", "route_rationale", "rationale"):
                if decision.get(key):
                    return str(decision[key])
    return None


def _region_timing(run: ExecutionRun | None, region_id: str, worker_status: dict | None) -> dict[str, object]:
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
    worker_status: dict | None,
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


def _region_status(
    *,
    current_stage_key: str,
    run: ExecutionRun | None,
    region: dict,
    result: dict,
    worker_status: dict | None,
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
    if run is not None and run.status == "running" and current_stage_key == "refine":
        if total_retries > 0:
            return "retrying", _region_reason(result) or "Refinement loop still active"
        return "issue_detected", "Waiting for review route"
    if total_retries > 0:
        return "success", f"Accepted after {total_retries} retr{ 'y' if total_retries == 1 else 'ies' }"
    if run is not None and run.status in {"completed", "paused", "failed"}:
        return "success", None
    return "pending", None


def _build_refine_nodes(
    run: ExecutionRun | None,
    *,
    current_stage_key: str,
    regions: list[dict],
    region_results: list[dict],
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

    for region in regions:
        region_id = region.get("region_id") or ""
        result = results_by_id.get(region_id, {})
        worker_status = workers.get(region_id)
        status, summary = _region_status(
            current_stage_key=current_stage_key,
            run=run,
            region=region,
            result=result,
            worker_status=worker_status,
        )
        route = _region_route(result)
        retries_total = int(region.get("retry_used") or 0) + sum(
            int(item.get("retry_used") or 0)
            for item in _safe_list(region.get("objects"))
        )
        loop_count = max(0, retries_total)
        if status == "retrying":
            retrying_regions += 1
        if status == "blocked":
            blocked_regions += 1
        if status == "success" and retries_total == 0:
            direct_accept_regions += 1
        if active_node_id is None and status in {"running", "retrying"}:
            active_node_id = f"region:{region_id}"
        region_meta = {
            "retries_total": retries_total,
            "retry_used": region.get("retry_used") or 0,
            "objects_with_retries": sum(
                1
                for item in _safe_list(region.get("objects"))
                if int(item.get("retry_used") or 0) > 0 or item.get("retry_exhausted")
            ),
        }
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
                label=f"Region {region_id}",
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
                meta=region_meta,
            )
        )
        if loop_count > 0 or route or status in {"running", "retrying", "issue_detected", "blocked"}:
            loop_summary: list[str] = []
            if loop_count > 0:
                loop_summary.append(f"{loop_count} retr{'y' if loop_count == 1 else 'ies'}")
            if route:
                loop_summary.append(f"route {route}")
            region_nodes.append(
                WorkflowTraceNode(
                    node_id=f"region:{region_id}:loop",
                    parent_node_id=f"region:{region_id}",
                    label="Refine Loop",
                    kind="loop",
                    status="blocked" if status == "blocked" else ("retrying" if status == "retrying" else "success"),
                    summary=" · ".join(loop_summary) or summary,
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
                    meta={"retries_total": loop_count},
                )
            )
        for obj in _safe_list(region.get("objects")):
            object_id = obj.get("object_id") or ""
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
                continue
            object_status = "success"
            object_summary = None
            if retry_exhausted or has_failed_items:
                object_status = "blocked"
                object_summary = "Retry exhausted" if retry_exhausted else "Still unresolved after repair"
            elif retry_used > 0:
                object_status = "success"
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
                    label=f"Object {object_id}",
                    kind="object",
                    status=object_status,
                    summary=object_summary,
                    target_type="object",
                    target_id=object_id,
                    started_at=object_timing.get("started_at"),
                    ended_at=object_timing.get("ended_at") if object_status not in {"running", "retrying"} else None,
                    duration_ms=object_timing.get("duration_ms"),
                    event_index=object_timing.get("event_index"),
                    meta={"retry_used": retry_used, "object_type": obj.get("object_type") or ""},
                )
            )

    if regions:
        branch_status = "pending"
        if current_stage_key == "refine":
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


def _build_initial_region_nodes(
    run: ExecutionRun | None,
    *,
    current_stage_key: str,
    regions: list[dict],
) -> list[WorkflowTraceNode]:
    if not regions:
        return []

    current_index = STAGE_INDEX.get(current_stage_key, 0)
    initial_index = STAGE_INDEX["initial-region-build"]
    branch_status = "pending"
    if current_index > initial_index or (run is not None and run.status in TERMINAL_RUN_STATUSES and current_index >= initial_index):
        branch_status = "success"
    elif current_stage_key == "initial-region-build":
        branch_status = "running"

    branch_started_at = None
    branch_ended_at = None
    branch_event_index = None
    nodes = [
        WorkflowTraceNode(
            node_id="initial-region-build:parallel",
            parent_node_id="initial-region-build",
            label="Parallel Region Branches",
            kind="stage",
            status=branch_status,
            summary=f"{len(regions)} region branch{'es' if len(regions) != 1 else ''}",
            execution_mode="parallel",
        )
    ]

    workers = _worker_by_task(run)
    for region in regions:
        region_id = region.get("region_id") or ""
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
        elif current_stage_key == "initial-region-build" and started_at is not None:
            status = "running"

        object_count = len(_safe_list(region.get("objects")))
        summary = f"{object_count} object{'s' if object_count != 1 else ''}" if object_count else "Initial region branch prepared."
        nodes.append(
            WorkflowTraceNode(
                node_id=f"initial-region:{region_id}",
                parent_node_id="initial-region-build:parallel",
                label=f"Region {region_id}",
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
                meta={"objects_total": object_count},
            )
        )

    nodes[0].started_at = branch_started_at
    nodes[0].ended_at = branch_ended_at if branch_status == "success" else None
    nodes[0].duration_ms = _duration_ms(branch_started_at, branch_ended_at)
    nodes[0].event_index = branch_event_index
    return nodes


def _build_layout_loop_node(
    run: ExecutionRun | None,
    *,
    current_stage_key: str,
    stage_spans: dict[str, dict],
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
    if current_stage_key == "layout":
        status = "retrying" if adjustment_calls > 1 or policy_calls > 0 else "running"
    elif run.status == "failed" and current_stage_key == "layout":
        status = "failed"
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
        summary=" · ".join(summary_parts) if summary_parts else None,
        started_at=loop_started_at,
        ended_at=loop_ended_at if status not in {"running", "retrying"} else None,
        duration_ms=_duration_ms(loop_started_at, loop_ended_at),
        event_index=loop_event_index if isinstance(loop_event_index, int) else start_index,
        meta={"retries_total": adjustment_calls},
    )


def build_workflow_trace(
    run: ExecutionRun | None,
    *,
    regions: list[dict] | None = None,
    region_results: list[dict] | None = None,
) -> WorkflowTrace:
    region_list = regions or []
    region_result_list = region_results or []
    stage_spans, active_stage_key = _build_stage_spans(run)
    nodes = _build_main_stage_nodes(run, active_stage_key=active_stage_key, stage_spans=stage_spans)
    nodes.extend(
        _build_initial_region_nodes(
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
    loop_iterations_total = 0
    for node in nodes:
        if node.kind != "loop":
            continue
        if isinstance(node.iteration, int):
            loop_iterations_total = max(loop_iterations_total, node.iteration)
            continue
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
                node.summary = " · ".join(parts)
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
    return WorkflowTrace(summary=summary, nodes=nodes)
