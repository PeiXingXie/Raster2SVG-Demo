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

    def get_existing(self, thread_id: str) -> ThreadState | None:
        with self._lock:
            state = self._threads.get(thread_id)
            return state.model_copy(deep=True) if state is not None else None

    def attach_persisted_run(self, run: ExecutionRun) -> ThreadState:
        if not run.owner_thread_id:
            raise ValueError("Saved run has no owning workspace.")
        with self._lock:
            state = self._threads.get(run.owner_thread_id)
            if state is None:
                state = ThreadState(thread_id=run.owner_thread_id)
            if state.bound_run_id not in {None, run.run_id}:
                raise ValueError("The owning workspace is already bound to another run.")
            if state.bound_run_id == run.run_id and state.current_run is not None:
                return state.model_copy(deep=True)
            state.bound_run_id = run.run_id
            state.current_run = run.model_copy(deep=True)
            state.recent_runs = [
                item for item in state.recent_runs if item.run_id != run.run_id
            ]
            self._threads[state.thread_id] = state
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
        run_id: str | None = None,
    ) -> ThreadState:
        state = self.try_begin_run(
            thread_id,
            mode=mode,
            stage=stage,
            title=title,
            detail=detail,
            project_name=project_name,
            artifact_dir=artifact_dir,
            run_id=run_id,
        )
        if state is None:
            raise RuntimeError("A run is already in progress for this thread.")
        return state

    def try_begin_run(
        self,
        thread_id: str,
        mode: str,
        stage: str,
        title: str,
        detail: str | None,
        project_name: str,
        artifact_dir: str,
        run_id: str | None = None,
    ) -> ThreadState | None:
        """Atomically start a run unless this thread already has live work."""
        with self._lock:
            state = self._threads.setdefault(thread_id, ThreadState(thread_id=thread_id))
            if state.bound_run_id is not None:
                return None
            now = utc_now()
            run = ExecutionRun(
                run_id=run_id or str(uuid4()),
                owner_thread_id=thread_id,
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
            state.bound_run_id = run.run_id
            return state.model_copy(deep=True)

    def resume_bound_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        stage: str,
        title: str,
        detail: str | None,
    ) -> ThreadState | None:
        with self._lock:
            state = self._threads.get(thread_id)
            if state is None or state.bound_run_id != run_id:
                return None
            run = state.current_run
            if run is None or run.run_id != run_id or run.status in {"queued", "running"}:
                return None
            now = utc_now()
            run.mode = "resume"
            run.status = "queued"
            run.current_stage = stage
            run.current_stage_started_at = now
            run.updated_at = now
            run.finished_at = None
            run.error = None
            run.failure_stage = None
            run.current_stage_duration_ms = 0
            run.events.append(
                ExecutionEvent(
                    timestamp=now,
                    stage=stage,
                    title=title,
                    detail=detail,
                    stage_duration_ms=0,
                )
            )
            state.recent_runs = [item for item in state.recent_runs if item.run_id != run_id]
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
                    owner_thread_id=thread_id,
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
                    owner_thread_id=thread_id,
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
            run.finished_at = now if status in {"completed", "failed", "paused", "needs_approval", "cancelled"} else None
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

            if status in {"completed", "failed", "paused", "needs_approval", "cancelled"}:
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
            if state.bound_run_id == run_id:
                state.bound_run_id = None
            state.recent_runs = [run for run in state.recent_runs if run.run_id != run_id]
            return state.model_copy(deep=True)
