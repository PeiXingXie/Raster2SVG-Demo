"""Overview: In-memory thread and run store used by the UI-facing runtime."""

from __future__ import annotations

from threading import Lock
from uuid import uuid4

from deepagents_template.schemas import (
    ApprovalRequest,
    ChatMessage,
    ExecutionEvent,
    FailureDiagnostic,
    ExecutionRun,
    ThreadState,
    WorkerStatus,
    utc_now,
)


class ThreadStore:
    """In-memory thread store used for UI-friendly short-term memory."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._threads: dict[str, ThreadState] = {}

    def create_thread(self) -> ThreadState:
        with self._lock:
            thread_id = str(uuid4())
            state = ThreadState(thread_id=thread_id)
            self._threads[thread_id] = state
            return state.model_copy(deep=True)

    def get_or_create(self, thread_id: str | None) -> ThreadState:
        if not thread_id:
            return self.create_thread()

        with self._lock:
            state = self._threads.get(thread_id)
            if state is None:
                state = ThreadState(thread_id=thread_id)
                self._threads[thread_id] = state
            return state.model_copy(deep=True)

    def get(self, thread_id: str) -> ThreadState:
        with self._lock:
            state = self._threads.get(thread_id)
            if state is None:
                state = ThreadState(thread_id=thread_id)
                self._threads[thread_id] = state
            return state.model_copy(deep=True)

    def append_message(self, thread_id: str, message: ChatMessage) -> ThreadState:
        with self._lock:
            state = self._threads.setdefault(thread_id, ThreadState(thread_id=thread_id))
            state.messages.append(message)
            return state.model_copy(deep=True)

    def set_pending_approval(
        self,
        thread_id: str,
        approval_request: ApprovalRequest | None,
    ) -> ThreadState:
        with self._lock:
            state = self._threads.setdefault(thread_id, ThreadState(thread_id=thread_id))
            state.pending_approval = approval_request
            return state.model_copy(deep=True)

    def begin_run(
        self,
        thread_id: str,
        mode: str,
        stage: str,
        title: str,
        detail: str | None,
        project_name: str,
        artifact_dir: str,
    ) -> ThreadState:
        with self._lock:
            state = self._threads.setdefault(thread_id, ThreadState(thread_id=thread_id))
            now = utc_now()
            run = ExecutionRun(
                run_id=str(uuid4()),
                mode=mode,
                status="queued",
                current_stage=stage,
                started_at=now,
                current_stage_started_at=now,
                updated_at=now,
                current_stage_duration_ms=0,
                project_name=project_name,
                artifact_dir=artifact_dir,
                events=[
                    ExecutionEvent(
                        timestamp=now,
                        stage=stage,
                        title=title,
                        detail=detail,
                        stage_duration_ms=0,
                    )
                ],
            )
            state.current_run = run
            return state.model_copy(deep=True)

    def push_event(
        self,
        thread_id: str,
        *,
        stage: str,
        title: str,
        detail: str | None = None,
        level: str = "info",
        payload: dict | None = None,
        status: str | None = None,
        worker_statuses: list[dict] | list[WorkerStatus] | None = None,
    ) -> ThreadState:
        with self._lock:
            state = self._threads.setdefault(thread_id, ThreadState(thread_id=thread_id))
            if state.current_run is None:
                now = utc_now()
                state.current_run = ExecutionRun(
                    run_id=str(uuid4()),
                    mode="invoke",
                    status="queued",
                    current_stage=stage,
                    started_at=now,
                    current_stage_started_at=now,
                    updated_at=now,
                    current_stage_duration_ms=0,
                    project_name="agent-run",
                    artifact_dir=None,
                )
            now = utc_now()
            if state.current_run.current_stage != stage:
                state.current_run.current_stage = stage
                state.current_run.current_stage_started_at = now
            state.current_run.updated_at = now
            state.current_run.current_stage_duration_ms = int(
                (now - state.current_run.current_stage_started_at).total_seconds() * 1000
            )
            if status is not None:
                state.current_run.status = status
            if worker_statuses is not None:
                state.current_run.worker_statuses = [
                    item if isinstance(item, WorkerStatus) else WorkerStatus.model_validate(item)
                    for item in worker_statuses
                ]
            state.current_run.events.append(
                ExecutionEvent(
                    timestamp=now,
                    stage=stage,
                    title=title,
                    detail=detail,
                    level=level,
                    stage_duration_ms=state.current_run.current_stage_duration_ms,
                    payload=payload,
                )
            )
            return state.model_copy(deep=True)

    def finish_run(
        self,
        thread_id: str,
        *,
        status: str,
        stage: str,
        failure_stage: str | None = None,
        title: str,
        detail: str | None = None,
        level: str = "success",
        payload: dict | None = None,
        error: str | None = None,
        failure_diagnostic: FailureDiagnostic | None = None,
        worker_statuses: list[dict] | list[WorkerStatus] | None = None,
    ) -> ThreadState:
        with self._lock:
            state = self._threads.setdefault(thread_id, ThreadState(thread_id=thread_id))
            if state.current_run is None:
                now = utc_now()
                state.current_run = ExecutionRun(
                    run_id=str(uuid4()),
                    mode="invoke",
                    status=status,
                    current_stage=stage,
                    started_at=now,
                    current_stage_started_at=now,
                    updated_at=now,
                    current_stage_duration_ms=0,
                    project_name="agent-run",
                    artifact_dir=None,
                )
            now = utc_now()
            run = state.current_run
            run.status = status
            if failure_stage:
                run.failure_stage = failure_stage
            if run.current_stage != stage:
                run.current_stage = stage
                run.current_stage_started_at = now
            run.updated_at = now
            run.current_stage_duration_ms = int((now - run.current_stage_started_at).total_seconds() * 1000)
            run.finished_at = now if status in {"completed", "failed", "paused", "needs_approval"} else None
            run.duration_ms = int((run.updated_at - run.started_at).total_seconds() * 1000)
            run.error = error
            run.failure_diagnostic = failure_diagnostic
            if worker_statuses is not None:
                run.worker_statuses = [
                    item if isinstance(item, WorkerStatus) else WorkerStatus.model_validate(item)
                    for item in worker_statuses
                ]
            run.events.append(
                ExecutionEvent(
                    timestamp=now,
                    stage=stage,
                    title=title,
                    detail=detail,
                    level=level,
                    stage_duration_ms=run.current_stage_duration_ms,
                    payload=payload,
                )
            )

            if status in {"completed", "failed", "paused", "needs_approval"}:
                state.recent_runs = ([run.model_copy(deep=True)] + state.recent_runs)[:8]

            return state.model_copy(deep=True)

    def update_run_project_name(self, thread_id: str, run_id: str, project_name: str) -> ThreadState:
        with self._lock:
            state = self._threads.setdefault(thread_id, ThreadState(thread_id=thread_id))
            now = utc_now()
            if state.current_run is not None and state.current_run.run_id == run_id:
                state.current_run.project_name = project_name
                state.current_run.updated_at = now
            for run in state.recent_runs:
                if run.run_id == run_id:
                    run.project_name = project_name
                    run.updated_at = now
            return state.model_copy(deep=True)

    def remove_run(self, thread_id: str, run_id: str) -> ThreadState:
        with self._lock:
            state = self._threads.setdefault(thread_id, ThreadState(thread_id=thread_id))
            if state.current_run is not None and state.current_run.run_id == run_id:
                state.current_run = None
                state.pending_approval = None
            state.recent_runs = [run for run in state.recent_runs if run.run_id != run_id]
            return state.model_copy(deep=True)
