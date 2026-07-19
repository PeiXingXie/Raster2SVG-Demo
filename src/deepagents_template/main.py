"""Overview: CLI entrypoint for Shape Studio conversion runs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from deepagents_template.artifacts import ArtifactStore
from deepagents_template.config import get_settings
from deepagents_template.conversion import RasterToSvgPipeline
from deepagents_template.runtime import get_thread_store
from deepagents_template.schemas import AgentRequest, ChatMessage, ExecutionRun
from deepagents_template.schemas import utc_now


def _format_duration(milliseconds: int | None) -> str:
    if milliseconds is None:
        return "0.0s"
    seconds = milliseconds / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remaining_seconds = divmod(int(seconds), 60)
    return f"{minutes}m {remaining_seconds}s"


def _run_elapsed_ms(run: ExecutionRun) -> int:
    return int((utc_now() - run.started_at).total_seconds() * 1000)


def _summarize_exception(exc: Exception) -> str:
    error_count = getattr(exc, "error_count", None)
    if callable(error_count):
        return f"{type(exc).__name__}: {error_count()} validation errors"
    return f"{type(exc).__name__}: {str(exc).splitlines()[0]}"


class CliRunMonitor:
    """Small stdout monitor for synchronous CLI conversion runs."""

    def __init__(self) -> None:
        self._last_event_count = 0

    def print_static_overview(
        self,
        *,
        request: AgentRequest,
        run_dir: Path,
        agent_model: str,
        subagent_model: str,
    ) -> None:
        settings = get_settings()
        print("[run] Shape Studio conversion")
        print(f"[run] image={request.image_path or 'none'}")
        region_mode = settings.resolved_region_processing_mode(request.region_processing_mode)
        region_concurrency = settings.resolved_region_concurrency(
            request.region_processing_mode,
            request.region_concurrency,
        )
        print(
            f"[run] region_processing_mode={region_mode} "
            f"region_concurrency={region_concurrency}"
        )
        print(f"[run] workflow_mode={settings.resolved_workflow_mode(request.workflow_mode)}")
        print(
            f"[run] api_provider={settings.resolved_api_provider(request.api_provider)} "
            f"api_format={settings.resolved_api_format(request.api_format)}"
        )
        print(
            "[run] supervisor_memory_enabled="
            f"{settings.resolved_supervisor_memory_enabled(request.supervisor_memory_enabled)}"
        )
        print(
            "[run] supervisor_memory_persist_enabled="
            f"{settings.resolved_supervisor_memory_persist_enabled(request.supervisor_memory_persist_enabled)}"
        )
        print(f"[run] max_retry={settings.max_retry} max_budget={settings.max_budget}")
        print(f"[run] agent_model={agent_model} subagent_model={subagent_model}")
        print(f"[run] artifacts={run_dir}")
        print("[run] ---")

    def __call__(self, run: ExecutionRun) -> None:
        new_events = run.events[self._last_event_count :]
        self._last_event_count = len(run.events)
        for event in new_events:
            elapsed = _format_duration(_run_elapsed_ms(run))
            stage_elapsed = _format_duration(event.stage_duration_ms)
            prefix = f"[{elapsed}] [{run.status}] [{event.stage}] [stage:{stage_elapsed}]"
            print(f"{prefix} {event.title}")
            if event.detail:
                print(f"  {event.detail}")
            if run.worker_statuses:
                worker_summary = ", ".join(
                    f"{worker.worker_id}:{worker.status}:{worker.stage}"
                    + (f":{worker.task_id}" if worker.task_id else "")
                    for worker in run.worker_statuses
                )
                print(f"  workers={worker_summary}")
            if event.payload and event.stage == "model-response":
                overview = event.payload
                status = overview.get("status", "unknown")
                model = overview.get("model", "unknown")
                response_model = overview.get("response_model", "unknown")
                duration = overview.get("duration_ms", 0)
                raw_chars = overview.get("raw_chars", 0)
                print(
                    "  response_overview="
                    f"status:{status}, model:{model}, schema:{response_model}, "
                    f"duration:{duration}ms, raw_chars:{raw_chars}"
                )
                if overview.get("raw_response_path"):
                    print(f"  raw_response_path={overview['raw_response_path']}")
                if overview.get("error"):
                    print(f"  error={overview['error']}")
                if overview.get("invalid_response_preview"):
                    print(f"  invalid_response_preview={overview['invalid_response_preview']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Shape Studio conversion from the command line.")
    parser.add_argument(
        "message",
        nargs="?",
        default=None,
        help="The Shape Studio conversion request to send to the pipeline. When omitted, the .env default is used.",
    )
    parser.add_argument("--image-path", help="Required local raster image path for conversion.")
    parser.add_argument(
        "--api-provider",
        help="Optional API provider override, for example: openai_compatible.",
    )
    parser.add_argument(
        "--api-format",
        choices=["openai_chat_completions", "openai_responses"],
        help="Optional API format override for multimodal calls.",
    )
    parser.add_argument(
        "--region-processing-mode",
        choices=["serial", "parallel"],
        help="Run region SVG generation serially or through a bounded parallel task pool.",
    )
    parser.add_argument(
        "--region-concurrency",
        type=int,
        help=(
            "Shared worker budget when --region-processing-mode parallel is used. "
            "Each active region reserves one worker; any leftover workers may be borrowed for object-level parallelism."
        ),
    )
    parser.add_argument(
        "--workflow-mode",
        choices=["initial_only", "region", "region_object"],
        help="Stop after the initial merged SVG, run only region refinement, or continue to object refinement.",
    )
    parser.add_argument(
        "--supervisor-memory-enabled",
        choices=["true", "false"],
        help="Enable or disable lightweight structured supervisor working memory.",
    )
    parser.add_argument(
        "--strategy-enabled",
        choices=["true", "false"],
        help="Enable or disable optional strategy hints inside combined policy decisions.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    resolved_message = settings.resolved_user_input(args.message)
    if not args.image_path:
        print("[error] --image-path is required for CLI conversion runs.")
        sys.exit(2)

    artifact_store = ArtifactStore()
    run_dir = artifact_store.create_run_dir()
    run_id = run_dir.name
    project_name = run_id
    thread_store = get_thread_store()
    thread = thread_store.get_or_create("cli-demo-thread")
    thread_store.append_message(
        thread.thread_id,
        ChatMessage(role="user", content=resolved_message),
    )
    request = AgentRequest(
        message=resolved_message,
        api_provider=args.api_provider,
        api_format=args.api_format,
        image_path=args.image_path,
        region_processing_mode=args.region_processing_mode,
        region_concurrency=args.region_concurrency,
        workflow_mode=args.workflow_mode,
        supervisor_memory_enabled=(
            True
            if args.supervisor_memory_enabled == "true"
            else False if args.supervisor_memory_enabled == "false" else None
        ),
        supervisor_memory_persist_enabled=None,
        strategy_enabled=(
            True if args.strategy_enabled == "true" else False if args.strategy_enabled == "false" else None
        ),
    )
    monitor = CliRunMonitor()
    monitor.print_static_overview(
        request=request,
        run_dir=run_dir,
        agent_model=settings.agent_model,
        subagent_model=settings.subagent_model,
    )
    thread = thread_store.begin_run(
        thread.thread_id,
        mode="invoke",
        stage="queued",
        title="CLI run accepted",
        detail="The command line conversion run is starting.",
        project_name=project_name,
        artifact_dir=str(run_dir),
        run_id=run_id,
    )
    monitor(thread.current_run)
    pipeline = RasterToSvgPipeline(
        thread_store=thread_store,
        thread_id=thread.thread_id,
        artifact_dir=Path(run_dir),
        request=request,
        agent_model=settings.agent_model,
        subagent_model=settings.subagent_model,
        run_id=run_id,
        project_name=project_name,
        event_callback=monitor,
    )
    try:
        summary = pipeline.run()
    except Exception as exc:
        error_summary = _summarize_exception(exc)
        thread = thread_store.finish_run(
            thread.thread_id,
            status="failed",
            stage="failed",
            title="Run failed",
            detail=error_summary,
            level="error",
            error=error_summary,
        )
        monitor(thread.current_run)
        print(f"[error] {error_summary}")
        print(f"[artifacts] {run_dir}")
        sys.exit(1)

    thread = thread_store.finish_run(
        thread.thread_id,
        status="completed",
        stage="completed",
        title="Run completed",
        detail="The final SVG and report were written to the output directory.",
    )
    monitor(thread.current_run)
    print(summary)
    print(f"[artifacts] {run_dir}")


if __name__ == "__main__":
    main()
