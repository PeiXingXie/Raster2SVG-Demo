import { elements } from "../dom.js";
import { renderState } from "../state.js?v=workspace-session-isolation-5";
import { renderLoadingState } from "../components/loading-state.js";
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

function getHistoryFilterLabel(status) {
  if (status === "all") {
    return "projects";
  }
  return `${status} projects`;
}

function runMatchesHistoryFilter(run, filterStatus) {
  if (filterStatus === "all") {
    return true;
  }
  if (filterStatus === "paused") {
    return String(run.status || "").startsWith("paused");
  }
  return run.status === filterStatus;
}

function updateDesktopHistoryPagination(pagination, pageInfo) {
  const root = document.getElementById("desktop-history-pagination");
  const prevButton = document.getElementById("desktop-history-prev");
  const nextButton = document.getElementById("desktop-history-next");
  const status = document.getElementById("desktop-history-page-status");
  const pageInput = document.getElementById("desktop-history-page-input");
  const pageTotal = document.getElementById("desktop-history-page-total");
  if (!root || !prevButton || !nextButton || !status) {
    return;
  }
  const visible = Boolean(
    pagination?.enabled
    && (pageInfo.totalRuns > 0 || pageInfo.page > 1 || pageInfo.endItem > 0)
  );
  root.classList.toggle("hidden", !visible);
  if (!visible) {
    return;
  }
  const filterLabel = getHistoryFilterLabel(pagination.filterStatus || "all");
  const totalKnown = Number.isFinite(pageInfo.totalRuns) && Number.isFinite(pageInfo.totalPages);
  status.textContent = totalKnown
    ? `${pageInfo.startItem}-${pageInfo.endItem} of ${pageInfo.totalRuns} ${filterLabel} | Page ${pageInfo.page} / ${pageInfo.totalPages}`
    : `${pageInfo.startItem}-${pageInfo.endItem} ${filterLabel} | Page ${pageInfo.page}`;
  prevButton.disabled = pageInfo.page <= 1;
  nextButton.disabled = pagination?.serverPaginated
    ? !pageInfo.hasMore
    : pageInfo.page >= pageInfo.totalPages;
  if (pageInput instanceof HTMLInputElement) {
    pageInput.min = "1";
    if (totalKnown) {
      pageInput.max = String(pageInfo.totalPages);
    } else {
      pageInput.removeAttribute("max");
    }
    pageInput.value = String(pageInfo.page);
  }
  if (pageTotal) {
    pageTotal.textContent = totalKnown ? `/ ${pageInfo.totalPages}` : "";
  }
}

function getRunSearchText(run) {
  return [
    run.project_name,
    run.status,
    run.current_stage,
    run.run_id,
    run.artifact_revision,
  ].filter(Boolean).join(" ").toLowerCase();
}

function sortRunsForLibrary(runs, sortKey) {
  const sorted = [...runs];
  if (sortKey === "name_asc") {
    sorted.sort((a, b) => String(a.project_name || "Untitled project").localeCompare(String(b.project_name || "Untitled project")));
    return sorted;
  }
  if (sortKey === "status_asc") {
    sorted.sort((a, b) => String(a.status || "").localeCompare(String(b.status || "")) || new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime());
    return sorted;
  }
  sorted.sort((a, b) => new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime());
  return sorted;
}

function formatProjectStatus(status) {
  const normalized = String(status || "unknown").replaceAll("_", " ");
  return normalized.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatHistoryDuration(run) {
  if (!run) {
    return "0 min";
  }
  let durationMs = typeof run.duration_ms === "number" ? run.duration_ms : null;
  if (durationMs == null && run.started_at) {
    durationMs = Math.max(0, Date.now() - new Date(run.started_at).getTime());
  }
  const minutes = Math.max(0, (durationMs || 0) / 60_000);
  if (minutes > 0 && minutes < 1) {
    return "<1 min";
  }
  if (minutes < 10) {
    return `${minutes.toFixed(1)} min`;
  }
  return `${Math.round(minutes)} min`;
}

export function renderRecentRuns(runs, selectedRunId, onReviewRun, onResumeRun, onReturnLive, options = {}) {
  const pagination = options.pagination || null;
  const isLoading = Boolean(options.loading);
  const filterStatus = pagination?.filterStatus || "all";
  const isDesktopPaginated = Boolean(pagination?.enabled);
  const isServerPaginated = Boolean(pagination?.serverPaginated);
  const searchQuery = String(pagination?.search || "").trim().toLowerCase();
  const statusFilteredRuns = !isServerPaginated && isDesktopPaginated && filterStatus !== "all"
    ? runs.filter((run) => runMatchesHistoryFilter(run, filterStatus))
    : runs;
  const searchedRuns = !isServerPaginated && searchQuery
    ? statusFilteredRuns.filter((run) => getRunSearchText(run).includes(searchQuery))
    : statusFilteredRuns;
  const filteredRuns = isDesktopPaginated && !isServerPaginated
    ? sortRunsForLibrary(searchedRuns, pagination?.sort || "updated_desc")
    : searchedRuns;
  const pageSize = Math.max(1, Number.parseInt(pagination?.pageSize || filteredRuns.length || 1, 10));
  const requestedPage = Math.max(1, Number.parseInt(pagination?.page || 1, 10));
  const serverTotalPages = Number.isFinite(pagination?.totalPages) ? pagination.totalPages : null;
  const totalPages = isServerPaginated
    ? serverTotalPages
    : Math.max(1, Math.ceil(filteredRuns.length / pageSize));
  const page = isServerPaginated || totalPages == null
    ? requestedPage
    : Math.min(requestedPage, totalPages);
  const pageStartIndex = isDesktopPaginated ? (page - 1) * pageSize : 0;
  const pageRuns = isServerPaginated
    ? filteredRuns
    : isDesktopPaginated
      ? filteredRuns.slice(pageStartIndex, pageStartIndex + pageSize)
      : filteredRuns;
  const totalRuns = isServerPaginated
    ? (Number.isFinite(pagination?.totalRuns) ? pagination.totalRuns : null)
    : filteredRuns.length;
  const pageInfo = {
    page,
    pageSize,
    totalPages,
    totalRuns,
    hasMore: isServerPaginated ? Boolean(pagination?.hasMore) : page < totalPages,
    startItem: pageRuns.length ? pageStartIndex + 1 : 0,
    endItem: pageStartIndex + pageRuns.length,
  };
  const signature = stableStringify({
    runs: pageRuns,
    selectedRunId,
    isLoading,
    filterStatus,
    searchQuery,
    sort: pagination?.sort || "updated_desc",
    pageInfo,
    hasRenameAction: typeof options.onRenameRun === "function",
    hasDeleteAction: typeof options.onDeleteRun === "function",
  });
  if (renderState.recentRunsSig === signature) {
    updateDesktopHistoryPagination(pagination, pageInfo);
    return;
  }

  elements.recentRuns.innerHTML = "";
  if (isLoading) {
    elements.recentRuns.className = "recent-runs recent-runs-sidebar is-loading";
    elements.recentRunsClearSelection.classList.add("hidden");
    for (let index = 0; index < pageSize; index += 1) {
      const card = document.createElement("article");
      card.className = "history-skeleton-card";
      card.setAttribute("aria-hidden", "true");
      renderLoadingState(card, {
        label: "Loading project",
        message: "Reading project summary...",
        compact: true,
        className: "desktop-history-loading-state",
      });
      elements.recentRuns.appendChild(card);
    }
    updateDesktopHistoryPagination(pagination, {
      page: 1,
      pageSize: Math.max(1, Number.parseInt(pagination?.pageSize || 1, 10)),
      totalPages: 1,
      totalRuns: 0,
      startItem: 0,
      endItem: 0,
    });
    renderState.recentRunsSig = signature;
    return;
  }
  if (!pageRuns.length) {
    elements.recentRuns.textContent = searchQuery
      ? "No projects match your search."
      : isDesktopPaginated && filterStatus !== "all"
        ? `No ${filterStatus} projects.`
        : "No saved projects yet.";
    elements.recentRuns.className = "recent-runs recent-runs-sidebar empty-state";
    elements.recentRunsClearSelection.classList.add("hidden");
    updateDesktopHistoryPagination(pagination, pageInfo);
    renderState.recentRunsSig = signature;
    return;
  }

  elements.recentRuns.className = "recent-runs recent-runs-sidebar";
  elements.recentRunsClearSelection.classList.toggle("hidden", !selectedRunId);
  elements.recentRunsClearSelection.onclick = () => onReturnLive();
  const selectedRun = pageRuns.find((run) => run.run_id === selectedRunId) || (isDesktopPaginated ? null : pageRuns[0]);
  const isDesktop = document.body.classList.contains("desktop-body");

  for (const run of pageRuns) {
    const card = document.createElement("article");
    card.className = `run-chip ${run.status}${selectedRun?.run_id === run.run_id ? " selected" : ""}`;
    card.dataset.runId = run.run_id || "";
    const projectName = escapeHtml(run.project_name || "Untitled project");
    const durationLabel = isDesktopPaginated ? formatHistoryDuration(run) : formatDuration(run);
    const headerMarkup = isDesktopPaginated
      ? `
      <div class="run-chip-top">
        <strong>${formatProjectStatus(run.status)}</strong>
        <div class="run-chip-project">${projectName}</div>
        <span class="run-chip-duration">${durationLabel}</span>
      </div>`
      : `
      <div class="run-chip-top">
        <strong>${formatProjectStatus(run.status)}</strong>
        <span class="run-chip-duration">${durationLabel}</span>
      </div>
      <div class="run-chip-project">${projectName}</div>`;
    const metaMarkup = isDesktopPaginated
      ? `<div class="run-chip-meta-row"><span class="run-chip-time">${formatDate(run.updated_at)}</span></div>`
      : `
      <div class="run-chip-meta-row">
        <span class="run-chip-stage">${escapeHtml(run.current_stage || "-")}</span>
        <span class="run-chip-time">${formatDate(run.updated_at)}</span>
      </div>`;
    const revisionMarkup = !isDesktopPaginated && run.artifact_revision
      ? `<div class="run-chip-meta-row"><span class="run-chip-stage">rev ${escapeHtml(String(run.artifact_revision).slice(0, 8))}</span></div>`
      : "";
    card.innerHTML = `
      ${headerMarkup}
      ${isDesktop ? `
        <div class="run-chip-preview" data-preview-state="loading">
          <div class="run-chip-preview-pane">
            <div class="run-chip-preview-label">Input</div>
            <div class="run-chip-preview-frame"><div class="run-chip-preview-empty">Loading</div></div>
          </div>
          <div class="run-chip-preview-pane">
            <div class="run-chip-preview-label">Output</div>
            <div class="run-chip-preview-frame"><div class="run-chip-preview-empty">Loading</div></div>
          </div>
        </div>
      ` : ""}
      ${metaMarkup}
      ${revisionMarkup}
    `;

    const actions = document.createElement("div");
    actions.className = "run-chip-actions";

    const reviewBtn = document.createElement("button");
    reviewBtn.className = isDesktopPaginated ? "secondary-btn run-chip-primary-action" : "ghost-btn";
    reviewBtn.type = "button";
    reviewBtn.textContent = "Open";
    reviewBtn.disabled = selectedRun?.run_id === run.run_id;
    reviewBtn.addEventListener("click", () => onReviewRun(run.run_id));

    if (isDesktopPaginated && typeof options.onRenameRun === "function") {
      const renameBtn = document.createElement("button");
      renameBtn.className = "ghost-btn";
      renameBtn.type = "button";
      renameBtn.textContent = "Rename";
      renameBtn.dataset.historyManagement = "rename";
      renameBtn.addEventListener("click", async () => options.onRenameRun(run));
      actions.appendChild(renameBtn);
    }

    if (isDesktopPaginated && typeof options.onDeleteRun === "function") {
      const deleteBtn = document.createElement("button");
      deleteBtn.className = "ghost-btn danger-btn";
      deleteBtn.type = "button";
      deleteBtn.textContent = "Delete";
      deleteBtn.dataset.historyManagement = "delete";
      deleteBtn.addEventListener("click", async () => options.onDeleteRun(run));
      actions.appendChild(deleteBtn);
    }

    actions.appendChild(reviewBtn);

    if (!isDesktopPaginated && run.artifact_dir) {
      const resumeBtn = document.createElement("button");
      resumeBtn.className = "secondary-btn";
      resumeBtn.type = "button";
      resumeBtn.textContent = "Resume";
      resumeBtn.addEventListener("click", async () => onResumeRun(run));
      actions.appendChild(resumeBtn);
    }

    if (isDesktopPaginated) {
      const metaRow = card.querySelector(".run-chip-meta-row");
      const footer = document.createElement("div");
      footer.className = "run-chip-footer";
      if (metaRow) {
        footer.appendChild(metaRow);
      }
      footer.appendChild(actions);
      card.appendChild(footer);
    } else {
      card.appendChild(actions);
    }
    elements.recentRuns.appendChild(card);
  }

  updateDesktopHistoryPagination(pagination, pageInfo);
  if (isDesktopPaginated && typeof pagination?.onPageResolved === "function") {
    pagination.onPageResolved(page);
  }
  renderState.recentRunsSig = signature;
}
