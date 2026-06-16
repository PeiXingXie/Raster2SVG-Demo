import { elements } from "../dom.js";
import { renderState } from "../state.js";
import {
  captureDetailsState,
  createCollapsibleContent,
  escapeHtml,
  findNearestIndex,
  formatDate,
  formatDuration,
  restoreDetailsState,
  stableStringify,
} from "../utils.js";

export function getRunBudget(run) {
  const startEvent = run?.events?.find((event) => event.stage === "running-conversion");
  return startEvent?.payload?.max_budget ?? null;
}

export function summarizeEvent(event, run, counters) {
  const payload = event.payload || {};
  if (event.stage !== "model-response" || !payload.response_model) {
    return {
      title: event.title,
      meta: `${event.stage}${event.stage_duration_ms != null ? ` | stage ${formatDuration({ duration_ms: event.stage_duration_ms })}` : ""}`,
      detail: event.detail,
    };
  }

  const responseModel = payload.response_model;
  const targetId = payload.target_id || payload.worker_statuses?.[0]?.task_id || null;
  const counterKey = `${responseModel}:${targetId || "global"}`;
  const passIndex = (counters.get(counterKey) || 0) + 1;
  counters.set(counterKey, passIndex);
  const budgetLimit = getRunBudget(run);
  const parts = [responseModel];
  if (targetId) {
    parts.push(targetId);
  }
  if (passIndex > 1) {
    parts.push(`pass ${passIndex}`);
  }
  if (payload.call_index != null) {
    parts.push(
      budgetLimit != null
        ? `budget ${payload.call_index}/${budgetLimit}`
        : `call ${payload.call_index}`
    );
  }
  return {
    title: parts.join(" | "),
    meta: `${payload.model || "-"} | ${payload.duration_ms != null ? formatDuration({ duration_ms: payload.duration_ms }) : "-"} | raw ${payload.raw_chars ?? 0} chars`,
    detail: buildModelResponseDetail(event.detail, payload),
  };
}

function buildModelResponseDetail(detail, payload) {
  const lines = [];
  if (detail) {
    lines.push(detail);
  }
  if (payload?.raw_response_path) {
    lines.push(`Saved raw response: ${payload.raw_response_path}`);
  }
  if (payload?.request_path) {
    lines.push(`Saved request payload: ${payload.request_path}`);
  }
  if (payload?.invalid_response_preview) {
    lines.push("Invalid response preview:");
    lines.push(payload.invalid_response_preview);
  }
  return lines.join("\n");
}

function renderFailureDiagnostic(container, diagnostic, fallbackError = "") {
  if (!diagnostic && !fallbackError) {
    return;
  }
  const errorBox = document.createElement("div");
  errorBox.className = "error-box diagnostic-card";
  if (!diagnostic) {
    errorBox.textContent = fallbackError;
    container.appendChild(errorBox);
    return;
  }
  const summary = document.createElement("div");
  summary.className = "diagnostic-card-summary";
  summary.innerHTML = `
    <strong>Failed at ${escapeHtml(diagnostic.failure_stage || diagnostic.terminal_stage || "-")}</strong><br>
    ${escapeHtml(diagnostic.summary || diagnostic.error_message || fallbackError || "Execution failed.")}
  `;
  errorBox.appendChild(summary);

  const meta = document.createElement("div");
  meta.className = "diagnostic-card-meta";
  const rows = [];
  if (diagnostic.error_type || diagnostic.error_message) {
    rows.push(`<div><span class="summary-label">Error</span><span class="summary-value">${escapeHtml(`${diagnostic.error_type || "Error"}${diagnostic.error_message ? ` | ${diagnostic.error_message}` : ""}`)}</span></div>`);
  }
  if (diagnostic.root_cause_type || diagnostic.root_cause_message) {
    rows.push(`<div><span class="summary-label">Root cause</span><span class="summary-value">${escapeHtml(`${diagnostic.root_cause_type || "-"}${diagnostic.root_cause_message ? ` | ${diagnostic.root_cause_message}` : ""}`)}</span></div>`);
  }
  if (diagnostic.response_model || diagnostic.model_name) {
    rows.push(`<div><span class="summary-label">Model call</span><span class="summary-value">${escapeHtml(`${diagnostic.response_model || "-"}${diagnostic.model_name ? ` via ${diagnostic.model_name}` : ""}`)}</span></div>`);
  }
  if (diagnostic.attempt != null || diagnostic.attempts_total != null) {
    rows.push(`<div><span class="summary-label">Attempt</span><span class="summary-value">${escapeHtml(`${diagnostic.attempt ?? "-"} / ${diagnostic.attempts_total ?? "-"}`)}</span></div>`);
  }
  if (diagnostic.last_event_title) {
    rows.push(`<div><span class="summary-label">Last event</span><span class="summary-value">${escapeHtml(diagnostic.last_event_title)}</span></div>`);
  }
  if (diagnostic.last_success_stage) {
    rows.push(`<div><span class="summary-label">Last success</span><span class="summary-value">${escapeHtml(diagnostic.last_success_stage)}</span></div>`);
  }
  meta.innerHTML = rows.join("");
  errorBox.appendChild(meta);

  if (diagnostic.artifact_hints?.length) {
    const artifactList = document.createElement("div");
    artifactList.className = "diagnostic-card-links";
    artifactList.innerHTML = diagnostic.artifact_hints
      .map((item) => `<span class="diagnostic-link-chip">${escapeHtml(item.label)}: ${escapeHtml(item.relative_path)}</span>`)
      .join("");
    errorBox.appendChild(artifactList);
  }
  container.appendChild(errorBox);
}

export function renderRunSummary(run, selectedRunId) {
  const signature = stableStringify({
    run: run || null,
    selectedRunId,
  });
  if (renderState.runSummarySig === signature) {
    return;
  }

  elements.monitorContext.textContent = selectedRunId ? `Reviewing run ${run?.run_id?.slice(0, 8) || "-"}` : "Live run view";
  if (!run) {
    elements.runSummary.className = "run-summary empty-state";
    elements.runSummary.textContent = "Submit a request to see live status, timing, and worker activity.";
    elements.schedulerSummary.className = "run-summary empty-state";
    elements.schedulerSummary.textContent = "Parallel scheduler activity will appear here when region or object workers are active.";
    renderState.runSummarySig = signature;
    return;
  }

  const lastEvent = run.events?.[run.events.length - 1];
  elements.runSummary.className = "run-summary";
  elements.runSummary.innerHTML = "";

  const header = document.createElement("div");
  header.className = "run-summary-header";
  header.innerHTML = `
    <span class="status-pill ${run.status}">${run.status}</span>
    <span class="run-id">run ${run.run_id.slice(0, 8)}</span>
  `;
  elements.runSummary.appendChild(header);

  const summaryText = document.createElement("div");
  summaryText.className = "run-summary-text";
  const workerStatusText = run.worker_statuses?.length
    ? run.worker_statuses
        .map((worker) => `${worker.worker_id}: ${worker.status} / ${worker.stage}${worker.task_id ? ` / ${worker.task_id}` : ""}`)
        .join("<br>")
    : "No worker activity";
  summaryText.innerHTML = `
    <p><strong>Stage:</strong> ${escapeHtml(run.current_stage || "-")}</p>
    <p><strong>Stage elapsed:</strong> ${run.current_stage_duration_ms != null ? formatDuration({ duration_ms: run.current_stage_duration_ms }) : "0 ms"}</p>
    <p><strong>Started:</strong> ${formatDate(run.started_at)}</p>
    <p><strong>Last event:</strong> ${escapeHtml(lastEvent ? lastEvent.title : "No event yet")}</p>
    <p><strong>Artifact dir:</strong> ${escapeHtml(run.artifact_dir || "-")}</p>
    <p><strong>Workers:</strong><br>${workerStatusText}</p>
  `;
  elements.runSummary.appendChild(summaryText);

  renderFailureDiagnostic(elements.runSummary, run.failure_diagnostic, run.error);

  renderSchedulerSummary(run);

  renderState.runSummarySig = signature;
}

function renderSchedulerSummary(run) {
  const scheduler =
    [...(run.events || [])].reverse().find((event) => event.payload?.parallel_scheduler)?.payload?.parallel_scheduler
    || null;
  if (!scheduler) {
    elements.schedulerSummary.className = "run-summary empty-state";
    elements.schedulerSummary.textContent = "No parallel scheduling snapshot has been recorded for this run yet.";
    return;
  }

  const workerDetails = run.worker_statuses?.length
    ? run.worker_statuses
        .map((worker) => `${worker.worker_id}: ${worker.status} / ${worker.stage}${worker.task_id ? ` / ${worker.task_id}` : ""}`)
        .join("<br>")
    : "No active workers recorded.";

  elements.schedulerSummary.className = "run-summary";
  elements.schedulerSummary.innerHTML = `
    <div class="run-summary-header">
      <span class="status-pill running">scheduler</span>
      <span class="run-id">${escapeHtml(scheduler.region_processing_mode || "-")} / concurrency ${scheduler.region_concurrency ?? "-"}</span>
    </div>
    <div class="run-summary-text">
      <p><strong>Pending region tasks:</strong> ${scheduler.pending_region_tasks ?? 0}</p>
      <p><strong>Active region workers:</strong> ${scheduler.active_region_workers ?? 0}</p>
      <p><strong>Borrowed object workers:</strong> ${scheduler.borrowed_object_workers ?? 0}</p>
      <p><strong>Available worker slots:</strong> ${scheduler.available_worker_slots ?? 0}</p>
      <p><strong>Worker allocation:</strong><br>${workerDetails}</p>
    </div>
  `;
}

export function renderTimeline(run, messages, selectedEventIndex, onEventSelect) {
  const timelineData = run?.events || [];
  const signature = stableStringify({
    timelineData,
    selectedEventIndex,
    selectedRunId: run?.run_id || null,
  });
  if (renderState.timelineSig === signature) {
    return;
  }

  const detailsState = captureDetailsState(elements.timeline);
  elements.timeline.innerHTML = "";
  if (!run || !run.events || run.events.length === 0) {
    elements.timeline.className = "timeline empty-state";
    elements.timeline.textContent = "No execution events yet.";
    renderState.timelineSig = signature;
    return;
  }

  elements.timeline.className = "timeline";
  const eventCounters = new Map();
  for (const [index, event] of run.events.entries()) {
    const summary = summarizeEvent(event, run, eventCounters);
    const item = document.createElement("article");
    item.className = `timeline-item ${event.level}${selectedEventIndex === index ? " selected" : ""}`;
    item.dataset.eventIndex = String(index);
    const linkedMessageIndex = findNearestIndex(messages || [], "created_at", event.timestamp);
    item.addEventListener("click", () => onEventSelect(index, linkedMessageIndex));

    const top = document.createElement("div");
    top.className = "timeline-top";
    top.innerHTML = `
      <span class="timeline-title">${escapeHtml(summary.title)}</span>
      <span class="timeline-time">${formatDate(event.timestamp)}</span>
    `;
    item.appendChild(top);

    const meta = document.createElement("div");
    meta.className = "timeline-meta";
    meta.textContent = summary.meta;
    item.appendChild(meta);

    if (summary.detail) {
      item.appendChild(
        createCollapsibleContent(summary.detail, {
          maxLength: 220,
          key: `timeline-detail:${index}:${event.timestamp}`,
        })
      );
    }

    if (event.payload && Object.keys(event.payload).length > 0) {
      const details = document.createElement("details");
      details.className = "collapsible";
      details.dataset.persistKey = `timeline-payload:${index}:${event.timestamp}`;
      const summaryNode = document.createElement("summary");
      summaryNode.textContent = "View payload";
      details.appendChild(summaryNode);
      const pre = document.createElement("pre");
      pre.className = "long-content";
      pre.textContent = JSON.stringify(event.payload, null, 2);
      details.appendChild(pre);
      item.appendChild(details);
    }

    elements.timeline.appendChild(item);
  }

  restoreDetailsState(elements.timeline, detailsState);
  renderState.timelineSig = signature;
}

export function renderRecentRuns(runs, selectedRunId, onReviewRun, onResumeRun, onReturnLive) {
  const signature = stableStringify({
    runs,
    selectedRunId,
  });
  if (renderState.recentRunsSig === signature) {
    return;
  }

  elements.recentRuns.innerHTML = "";
  if (!runs.length) {
    elements.recentRuns.textContent = "No runs yet.";
    elements.recentRuns.className = "recent-runs recent-runs-sidebar empty-state";
    elements.recentRunsClearSelection.classList.add("hidden");
    renderState.recentRunsSig = signature;
    return;
  }

  elements.recentRuns.className = "recent-runs recent-runs-sidebar";
  elements.recentRunsClearSelection.classList.toggle("hidden", !selectedRunId);
  elements.recentRunsClearSelection.onclick = () => onReturnLive();
  const selectedRun = runs.find((run) => run.run_id === selectedRunId) || runs[0];

  for (const run of runs) {
    const card = document.createElement("article");
    card.className = `run-chip ${run.status}${selectedRun?.run_id === run.run_id ? " selected" : ""}`;
    card.innerHTML = `
      <div class="run-chip-top">
        <strong>${run.status}</strong>
        <span>${formatDuration(run)}</span>
      </div>
      <div class="run-chip-project">${escapeHtml(run.project_name || "Unnamed project")}</div>
      <div class="run-chip-meta-row">
        <span class="run-chip-stage">${escapeHtml(run.current_stage || "-")}</span>
        <span class="run-chip-time">${formatDate(run.updated_at)}</span>
      </div>
    `;

    const actions = document.createElement("div");
    actions.className = "run-chip-actions";

    const reviewBtn = document.createElement("button");
    reviewBtn.className = "ghost-btn";
    reviewBtn.type = "button";
    reviewBtn.textContent = selectedRun?.run_id === run.run_id ? "Viewing" : "Review";
    reviewBtn.disabled = selectedRun?.run_id === run.run_id;
    reviewBtn.addEventListener("click", () => onReviewRun(run.run_id));
    actions.appendChild(reviewBtn);

    if (run.artifact_dir) {
      const resumeBtn = document.createElement("button");
      resumeBtn.className = "secondary-btn";
      resumeBtn.type = "button";
      resumeBtn.textContent = "Resume";
      resumeBtn.addEventListener("click", async () => onResumeRun(run));
      actions.appendChild(resumeBtn);
    }

    card.appendChild(actions);
    elements.recentRuns.appendChild(card);
  }

  renderState.recentRunsSig = signature;
}
