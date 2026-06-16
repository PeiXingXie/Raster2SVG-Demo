"""Helpers for persisted run state and checkpoint-based resume planning."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from deepagents_template.schemas import (
    AgentRequest,
    ArtifactResumeInfo,
    BudgetSnapshot,
    ResumePlan,
    RetrySnapshot,
    RunFailureSnapshot,
    RunState,
    RunTimestampsSnapshot,
)
from deepagents_template.schemas import utc_now


RUN_STATE_FILENAME = "run_state.json"

CHECKPOINT_STAGE_BY_FLAG = (
    ("report_completed", "summarizing-result"),
    ("final_svg_completed", "final-integration"),
    ("refinement_completed", "region-process-refine"),
    ("initial_svg_completed", "initial-integration"),
    ("initial_regions_completed", "region-process-initial"),
    ("crops_completed", "region-cropping"),
    ("layout_completed", "layout-detection"),
    ("input_prepared", "loading-input"),
)


def run_state_path(run_dir: Path) -> Path:
    return run_dir / RUN_STATE_FILENAME


def load_run_state(run_dir: Path) -> RunState | None:
    path = run_state_path(run_dir)
    if not path.is_file():
        return None
    try:
        return RunState.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_run_state(run_dir: Path, state: RunState) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_state_path(run_dir)
    temp_path: Path | None = None
    payload = state.model_dump_json(indent=2)
    try:
        with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=run_dir, suffix=".tmp") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)

        for attempt in range(8):
            try:
                os.replace(temp_path, target)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def create_run_state(
    *,
    run_id: str,
    thread_id: str | None,
    project_name: str,
    request: AgentRequest,
    budget_limit: int,
    max_retry: int,
) -> RunState:
    now = utc_now()
    return RunState(
        run_id=run_id,
        thread_id=thread_id,
        project_name=project_name,
        status="queued",
        current_stage="queued",
        resume_token=str(uuid4()),
        request=request.model_dump(mode="json"),
        budget=BudgetSnapshot(limit=budget_limit, used=0, remaining=budget_limit, mode="top_up"),
        retry=RetrySnapshot(max_retry=max_retry),
        checkpoints={
            "input_prepared": False,
            "layout_completed": False,
            "crops_completed": False,
            "initial_regions_completed": False,
            "initial_svg_completed": False,
            "refinement_completed": False,
            "final_svg_completed": False,
            "report_completed": False,
        },
        failure=RunFailureSnapshot(),
        timestamps=RunTimestampsSnapshot(started_at=now, updated_at=now),
    )


def resume_stage_from_state(state: RunState) -> str | None:
    for checkpoint_key, stage_name in CHECKPOINT_STAGE_BY_FLAG:
        if state.checkpoints.get(checkpoint_key):
            continue
        return stage_name
    return None if state.status == "completed" else "summarizing-result"


def build_resume_plan(run_dir: Path) -> ResumePlan:
    state = load_run_state(run_dir)
    if state is None:
        return ResumePlan(
            available=False,
            run_dir=str(run_dir),
            reason="No persisted run_state.json was found.",
        )

    completed_regions = [region.region_id for region in state.regions if region.status == "completed"]
    pending_regions = [region.region_id for region in state.regions if region.status != "completed"]
    resume_stage = resume_stage_from_state(state)
    available = state.status in {"paused", "failed", "queued", "running"} and resume_stage is not None
    reason = state.pause_reason or state.failure.message
    return ResumePlan(
        available=available,
        run_dir=str(run_dir),
        current_stage=state.current_stage,
        resume_stage=resume_stage,
        reason=reason,
        status=state.status,
        budget=state.budget,
        completed_regions=completed_regions,
        pending_regions=pending_regions,
    )


def build_artifact_resume_info(run_dir: Path) -> ArtifactResumeInfo:
    state = load_run_state(run_dir)
    plan = build_resume_plan(run_dir)
    if state is None:
        return ArtifactResumeInfo()
    completed_regions = len(plan.completed_regions)
    pending_regions = len(plan.pending_regions)
    return ArtifactResumeInfo(
        available=plan.available,
        reason=plan.reason,
        current_stage=plan.current_stage,
        resume_stage=plan.resume_stage,
        pause_reason=state.pause_reason,
        budget_used=state.budget.used,
        budget_limit=state.budget.limit,
        budget_remaining=state.budget.remaining,
        completed_regions=completed_regions,
        pending_regions=pending_regions,
    )


def load_request_from_run_dir(run_dir: Path) -> AgentRequest:
    payload = json.loads((run_dir / "input" / "request.json").read_text(encoding="utf-8"))
    return AgentRequest.model_validate(payload)
