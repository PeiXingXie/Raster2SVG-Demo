import { fetchJson } from "./api-client.js";
import { elements } from "./dom.js?v=desktop-start-runtime-readiness-1";
import {
  applyFrontendDefaults,
  applyRuntimeOverrides,
  bindFieldListeners,
  buildInvokePayload,
  buildRuntimeOverridesPayload,
  clearUploadPreview,
  getStartRuntimeReadiness,
  getMessageEffectiveValue,
  MESSAGE_PRESET_TEXT,
  pickLocalFileFromHost,
  updateEffectiveValues,
  updateMessagePresetSelection,
  uploadLocalFile,
} from "./form.js?v=desktop-start-runtime-readiness-1";
import { appState, resetRenderState, resetUiSelections } from "./state.js";
import { renderApproval } from "./renderers/conversation.js";
import {
  clearArtifactPanel,
  createOverlayPreview,
  getLatestManualAdjustment,
  refreshWorkflowTraceLayout,
  renderArtifactFiles,
  renderManualWorkflowTrace,
  renderArtifactSummary,
  updateWorkflowTraceTimers,
} from "./renderers/artifacts.js?v=desktop-output-scroll-fix-1";
import { renderRecentRuns, renderRunSummary, renderTimeline } from "./renderers/monitor.js?v=desktop-history-preview-cache-1";
import { arrayBufferToBase64, formatElapsedDuration, scrollIntoContainerView, stableStringify } from "./utils.js";

const UI_MODE_STORAGE_KEY = "raster-svg-demo-ui-mode";
let sendButtonLockedByRuntime = false;
let sendRequestInFlight = false;

const PIPELINE_ROUTE_LABELS = {
  layout_detection: "Analyzing source structure",
  region_detection: "Detecting regions",
  region_generation: "Generating editable regions",
  object_generation: "Generating object paths",
  review: "Reviewing output quality",
  repair: "Repairing local path issues",
  integration: "Finalizing SVG asset",
  manual_adjustment: "Applying refinement",
};

const PIPELINE_KIND_LABELS = {
  root: "Preparing conversion",
  stage: "Pipeline stage",
  region: "Processing region",
  object: "Processing object",
  loop: "Repair loop",
  review: "Reviewing output",
  terminal: "Finalizing",
  node: "Pipeline step",
};

const DESKTOP_PROCESS_GUIDE = {
  upload: {
    eyebrow: "Step 1",
    title: "Upload",
    body: "Add a source image and describe the target.",
    notes: ["Paste or choose an image.", "Describe the target SVG.", "Start the conversion."],
  },
  trace: {
    eyebrow: "Step 2",
    title: "Trace",
    body: "Detect structure, regions, and vector paths.",
    notes: ["Follow trace progress.", "Review pipeline frames.", "Wait for a stable output."],
  },
  manual: {
    eyebrow: "Step 3",
    title: "Refine",
    body: "Fix local details without restarting.",
    notes: ["Open the refine panel.", "Select the target area.", "Apply a focused edit."],
  },
  download: {
    eyebrow: "Step 4",
    title: "Export",
    body: "Save the final editable SVG asset.",
    notes: ["Review the final frame.", "Check artifact files.", "Save the SVG asset."],
  },
};

function normalizeDesktopProcessStep(step) {
  if (step === "start") {
    return "upload";
  }
  return DESKTOP_PROCESS_GUIDE[step] ? step : "upload";
}

function getSelectedManualAdjustment(snapshot = appState.latestArtifactSnapshot) {
  if (!snapshot?.manual_adjustments?.length) {
    return null;
  }
  if (appState.selectedManualAdjustmentId) {
    return snapshot.manual_adjustments.find((item) => item.adjustment_id === appState.selectedManualAdjustmentId) || null;
  }
  return null;
}

function applyHostInfo(info = {}) {
  const resolvedHostMode = window.desktopHost ? "desktop" : (info.host_mode || "web");
  appState.frontendHostInfo = info;
  appState.hostCapabilities = {
    hostMode: resolvedHostMode,
    frontendUrl: info.frontend_url || null,
    platform: info.platform || null,
    canOpenLocalFilePicker: Boolean(window.desktopHost?.openLocalImage || info.can_open_local_file_picker),
  };
  if (elements.shellModeBadge) {
    elements.shellModeBadge.textContent = resolvedHostMode === "desktop" ? "local workspace" : "browser workspace";
    elements.shellModeBadge.className = `status-pill ${resolvedHostMode === "desktop" ? "running" : "queued"}`;
  }
}

function setStatus(text) {
  elements.statusText.textContent = text;
}

function updateStartRuntimeHint() {
  const readiness = getStartRuntimeReadiness();
  sendButtonLockedByRuntime = !readiness.ready;
  if (elements.startSettingsHint) {
    elements.startSettingsHint.dataset.runtimeReady = readiness.ready ? "true" : "false";
  }
  if (elements.startSettingsTitle) {
    elements.startSettingsTitle.textContent = readiness.title;
  }
  if (elements.startSettingsBody) {
    elements.startSettingsBody.textContent = readiness.body;
  }
  if (elements.sendBtn) {
    elements.sendBtn.disabled = sendButtonLockedByRuntime || sendRequestInFlight;
    elements.sendBtn.title = sendButtonLockedByRuntime
      ? "Complete runtime settings before starting a conversion."
      : sendRequestInFlight
        ? "Conversion request is being submitted."
      : "";
  }
}

const SETTINGS_FIELD_HELP = {
  "api-key": "Secret key used for model API calls; saved values stay hidden after update.",
  "base-url": "Endpoint base URL for the selected model API provider.",
  "api-provider": "Provider adapter used to create model clients for conversions.",
  "api-format": "Request protocol used when talking to the model API.",
  "agent-model": "Model used by the coordinator that plans and reviews the conversion.",
  "subagent-model": "Model used by worker agents for region and object generation.",
  "settings-workflow-mode": "Default pipeline depth for new conversions.",
  "settings-region-processing-mode": "Whether regions are processed one by one or in parallel.",
  "settings-region-concurrency": "Maximum number of regions that may run at the same time.",
  "max-budget": "Total model-call budget allowed for one conversion run.",
  "max-repair-retry": "Maximum repair attempts for SVG or local path issues.",
  "max-retries": "Low-level retry count for transient API request failures.",
  "use-previous-response-id": "Reuse previous response state when the provider supports it.",
  "recognition-bbox-refine-mode": "Method used to refine detected object bounding boxes.",
  "sam-enabled": "Enable SAM-assisted bbox refinement when available.",
  "sam-provider-mode": "Choose whether SAM runs locally or through a remote service.",
  "sam-remote-url": "Remote SAM service endpoint used when provider mode is remote.",
  "sam-fallback-to-llm": "Use LLM refinement if SAM refinement is unavailable or fails.",
  "bbox-issue-concurrency": "Maximum bbox issue refinements that may run in parallel.",
  "bbox-issue-stagnation-rounds": "Stop one bbox issue when repeated rounds stop improving.",
  "bbox-global-stagnation-rounds": "Stop global bbox refinement when issue sets keep repeating.",
  "agent-name": "Runtime name used for the coordinator agent instance.",
  "supervisor-memory-enabled": "Allow the supervisor to use memory during workflow decisions.",
  "supervisor-memory-persist-enabled": "Persist supervisor memory artifacts for later inspection or reuse.",
  "strategy-enabled": "Enable extra strategy hints in planning and review decisions.",
};

function attachSettingsFieldHelp() {
  if (!elements.runtimeConfigSection) {
    return;
  }
  const fields = elements.runtimeConfigSection.querySelectorAll("[data-field-id]");
  fields.forEach((field) => {
    const fieldId = field.getAttribute("data-field-id");
    const helpText = SETTINGS_FIELD_HELP[fieldId || ""];
    const label = field.querySelector(".field-label");
    if (!helpText || !label || label.querySelector(".settings-info-icon")) {
      return;
    }
    const infoIcon = document.createElement("span");
    infoIcon.className = "settings-info-icon";
    infoIcon.textContent = "i";
    infoIcon.tabIndex = 0;
    infoIcon.setAttribute("role", "img");
    infoIcon.setAttribute("aria-label", helpText);
    infoIcon.dataset.tooltip = helpText;
    label.appendChild(infoIcon);
  });
}

function openImageLightbox({ src, alt = "", caption = "" }) {
  if (!elements.imageLightbox || !elements.imageLightboxImage) {
    return;
  }
  if (!src) {
    return;
  }
  elements.imageLightboxImage.src = src;
  elements.imageLightboxImage.alt = alt || "Expanded preview";
  if (elements.imageLightboxCaption) {
    elements.imageLightboxCaption.textContent = caption || alt || "";
  }
  elements.imageLightbox.classList.remove("hidden");
  elements.imageLightbox.setAttribute("aria-hidden", "false");
  document.body.classList.add("lightbox-open");
}

function closeImageLightbox() {
  if (!elements.imageLightbox || !elements.imageLightboxImage) {
    return;
  }
  elements.imageLightbox.classList.add("hidden");
  elements.imageLightbox.setAttribute("aria-hidden", "true");
  elements.imageLightboxImage.removeAttribute("src");
  elements.imageLightboxImage.alt = "Expanded preview";
  if (elements.imageLightboxCaption) {
    elements.imageLightboxCaption.textContent = "";
  }
  document.body.classList.remove("lightbox-open");
}

function hasUsableArtifactOutput(snapshot) {
  return Boolean(
    snapshot?.previews?.output_svg_url
    || snapshot?.previews?.output_png_url
    || snapshot?.previews?.initial_svg_url
    || snapshot?.output_frames?.length
  );
}

function getTraceNodes(snapshot) {
  return Array.isArray(snapshot?.workflow_trace?.nodes) ? snapshot.workflow_trace.nodes.filter(Boolean) : [];
}

function getTraceSummary(snapshot) {
  return snapshot?.workflow_trace?.summary || {};
}

function getReadableTraceTitle(node) {
  if (!node) {
    return "Waiting to start";
  }
  if (node.route && PIPELINE_ROUTE_LABELS[node.route]) {
    return PIPELINE_ROUTE_LABELS[node.route];
  }
  if (node.semantic_stage) {
    return String(node.semantic_stage).replaceAll("_", " ");
  }
  if (node.kind && PIPELINE_KIND_LABELS[node.kind]) {
    return PIPELINE_KIND_LABELS[node.kind];
  }
  return node.label || "Pipeline step";
}

function getTraceNodeTime(node) {
  const raw = node?.ended_at || node?.started_at || node?.timestamp;
  const time = raw ? new Date(raw).getTime() : 0;
  return Number.isFinite(time) ? time : 0;
}

function getActiveTraceNode(snapshot) {
  const nodes = getTraceNodes(snapshot);
  const activeNodeId = getTraceSummary(snapshot).active_node_id;
  return nodes.find((node) => node.node_id === activeNodeId)
    || [...nodes].reverse().find((node) => ["running", "retrying"].includes(node.status))
    || getLatestTraceNode(snapshot)
    || null;
}

function getLatestTraceNode(snapshot) {
  return getTraceNodes(snapshot)
    .filter((node) => node.status && node.status !== "pending")
    .sort((a, b) => getTraceNodeTime(b) - getTraceNodeTime(a))[0] || null;
}

function getPipelineProgress(snapshot) {
  const nodes = getTraceNodes(snapshot).filter((node) => node.kind !== "terminal" || node.status !== "pending");
  if (nodes.length) {
    const completed = nodes.filter((node) => ["success", "completed", "failed", "issue_detected"].includes(node.status)).length;
    return `${completed} / ${nodes.length} steps`;
  }
  const milestones = [
    Boolean(appState.localUpload?.image_path || elements.imagePath.value.trim() || snapshot?.previews?.input_image_url),
    Boolean(snapshot?.regions?.length),
    hasUsableArtifactOutput(snapshot),
    Boolean(snapshot?.available),
  ];
  const completed = milestones.filter(Boolean).length;
  return `${completed} / ${milestones.length} milestones`;
}

function getPipelineElapsedInfo(snapshot) {
  const nodes = getTraceNodes(snapshot);
  const startedTimes = nodes
    .map((node) => node?.started_at)
    .filter(Boolean)
    .map((value) => new Date(value).getTime())
    .filter(Number.isFinite);
  const endedTimes = nodes
    .map((node) => node?.ended_at)
    .filter(Boolean)
    .map((value) => new Date(value).getTime())
    .filter(Number.isFinite);
  const summaryDuration = getTraceSummary(snapshot).total_duration_ms;
  const running = ["queued", "running", "needs_approval"].includes(getSelectedRun()?.status || snapshot?.status || "");
  if (startedTimes.length && running) {
    return { startedAt: new Date(Math.min(...startedTimes)).toISOString(), endedAt: "", durationMs: null };
  }
  if (startedTimes.length && endedTimes.length) {
    return { startedAt: null, endedAt: null, durationMs: Math.max(0, Math.max(...endedTimes) - Math.min(...startedTimes)) };
  }
  if (typeof summaryDuration === "number") {
    return { startedAt: null, endedAt: null, durationMs: summaryDuration };
  }
  return { startedAt: null, endedAt: null, durationMs: 0 };
}

function getExportDownloadUrl(snapshot) {
  if (!snapshot?.available) {
    return "";
  }
  const selectedAdjustment = appState.selectedManualAdjustmentId
    ? (snapshot.manual_adjustments || []).find((item) => item.adjustment_id === appState.selectedManualAdjustmentId)
    : null;
  const activeFrame = snapshot.output_frames?.[appState.selectedOutputFrameIndex] || null;
  return selectedAdjustment?.download_url
    || snapshot.previews?.output_svg_url
    || activeFrame?.download_url
    || snapshot.previews?.initial_svg_url
    || "";
}

function syncRecentRunsHeight() {
  if (!elements.recentRunsCard || !elements.recentRuns || !elements.invocationSection) {
    return;
  }
  elements.recentRunsCard.style.height = "";
  elements.recentRunsCard.style.maxHeight = "";
  elements.recentRuns.style.height = "";
  elements.recentRuns.style.maxHeight = "";

  if (document.body.dataset.desktopPage === "history") {
    return;
  }

  const sidebar = elements.recentRunsCard.closest(".sidebar");
  const currentTaskCard = sidebar?.firstElementChild instanceof HTMLElement ? sidebar.firstElementChild : null;
  if (!currentTaskCard) {
    return;
  }

  const currentTaskRect = currentTaskCard.getBoundingClientRect();
  const invocationRect = elements.invocationSection.getBoundingClientRect();
  const recentRunsHeader = elements.recentRunsCard.firstElementChild instanceof HTMLElement
    ? elements.recentRunsCard.firstElementChild
    : null;
  const headerHeight = recentRunsHeader?.getBoundingClientRect().height || 0;
  const cardPadding = 40;
  const gap = 16;
  const availableCardHeight = Math.floor(invocationRect.bottom - currentTaskRect.bottom - gap);

  if (availableCardHeight <= headerHeight + 80) {
    return;
  }

  const availableListHeight = Math.max(availableCardHeight - headerHeight - cardPadding, 96);
  elements.recentRunsCard.style.height = `${availableCardHeight}px`;
  elements.recentRunsCard.style.maxHeight = `${availableCardHeight}px`;
  elements.recentRuns.style.height = `${availableListHeight}px`;
  elements.recentRuns.style.maxHeight = `${availableListHeight}px`;
}

function applyMessagePreset(presetKey) {
  const nextValue = MESSAGE_PRESET_TEXT[presetKey] || MESSAGE_PRESET_TEXT.default;
  appState.messagePreset = presetKey;
  elements.messageInput.value = nextValue;
  elements.messageInput.dataset.messagePreset = presetKey;
  updateEffectiveValues();
  updateMessagePresetSelection();
  updateGuideContent();
}

function deriveJourneyState() {
  const artifactSnapshot = appState.latestArtifactSnapshot;
  const selectedRun = getSelectedRun();
  const hasUpload = Boolean(appState.localUpload?.image_path || elements.imagePath.value.trim());
  const hasResult = hasUsableArtifactOutput(artifactSnapshot);
  const hasManualResult = Boolean(getLatestManualAdjustment(artifactSnapshot));
  const runActive = Boolean(selectedRun && ["queued", "running", "needs_approval", "paused"].includes(selectedRun.status));
  const promptReady = Boolean(getMessageEffectiveValue().trim());
  const hasSelection = Boolean(
    appState.manualConfirmedTarget?.selectionBox
    || appState.manualSelectionBox
    || appState.selectedOverlay?.regionId
  );
  const manualGoal = elements.manualUserIntroduction?.value?.trim() || elements.manualTargetDescription?.value?.trim() || "";
  const runStatus = selectedRun?.status || null;
  const currentStage = artifactSnapshot?.current_stage || selectedRun?.current_stage || null;

  let journeyState = "empty";
  if (!hasUpload) {
    journeyState = "empty";
  } else if (!promptReady) {
    journeyState = "image_ready_needs_prompt";
  } else if (!selectedRun || (!runActive && !hasResult && runStatus !== "failed")) {
    journeyState = "ready_to_start";
  } else if (runStatus === "paused") {
    journeyState = "paused_resume_available";
  } else if (runStatus === "failed") {
    journeyState = hasResult ? "result_ready_needs_local_refine" : "failed_recoverable";
  } else if (runActive) {
    const stage = (currentStage || "").toLowerCase();
    if (stage.includes("layout")) {
      journeyState = "running_layout_analysis";
    } else if (stage.includes("region") || stage.includes("object")) {
      journeyState = "running_region_generation";
    } else if (stage.includes("repair") || stage.includes("review") || stage.includes("retry")) {
      journeyState = "running_repair";
    } else {
      journeyState = "running_trace";
    }
  } else if (hasManualResult) {
    journeyState = "manual_result_ready";
  } else if (hasResult && !hasSelection) {
    journeyState = "result_ready_review_overall";
  } else if (hasResult && hasSelection && !manualGoal) {
    journeyState = "manual_goal_missing";
  } else if (hasResult && hasSelection && manualGoal) {
    journeyState = "manual_ready_to_apply";
  } else if (hasResult) {
    journeyState = "result_ready_needs_local_refine";
  }

  const activeStep = hasManualResult
    ? "manual"
    : hasResult
      ? "download"
      : runActive
        ? "trace"
      : hasUpload
          ? "start"
          : "upload";
  return {
    journeyState,
    activeStep,
    hasUpload,
    hasResult,
    hasManualResult,
    runActive,
    promptReady,
    hasSelection,
    manualGoal,
    runStatus,
    currentStage,
  };
}

function getGuideContent() {
  const journey = deriveJourneyState();
  const stageLabel = journey.currentStage || "the active conversion";
  const contentByState = {
    empty: {
      title: "How it works",
      body: "Follow the four-step flow from source image to editable SVG asset.",
      step: journey.activeStep,
      primaryAction: { kind: "scroll", label: "Start From Input", target: "input" },
      secondaryAction: { kind: "scroll", label: "Open Refinement", target: "manual" },
    },
    image_ready_needs_prompt: {
      title: "Image ready. Add the task next.",
      body: "Keep it short and state what should be preserved or changed.",
      step: journey.activeStep,
      primaryAction: { kind: "scroll", label: "Describe Goal", target: "input" },
      secondaryAction: { kind: "scroll", label: "Open Project Library", target: "sidebar" },
    },
    ready_to_start: {
      title: "Ready to start.",
      body: "Start the conversion to see trace updates and the first output frame.",
      step: journey.activeStep,
      primaryAction: { kind: "submit", label: "Convert" },
      secondaryAction: { kind: "scroll", label: "Adjust Run Settings", target: "input" },
    },
    running_layout_analysis: {
      title: "Analyzing layout.",
      body: `${stageLabel} is running. Follow the trace until structure and bbox settle.`,
      step: journey.activeStep,
      primaryAction: { kind: "scroll", label: "Follow Process Trace", target: "trace" },
      secondaryAction: { kind: "scroll", label: "Review Input", target: "input" },
    },
    running_region_generation: {
      title: "Generating SVG regions.",
      body: `${stageLabel} is running. Review the first output frame when it appears.`,
      step: journey.activeStep,
      primaryAction: { kind: "scroll", label: "Watch Output", target: "output" },
      secondaryAction: { kind: "scroll", label: "Follow Process Trace", target: "trace" },
    },
    running_repair: {
      title: "Repairing local issues.",
      body: `${stageLabel} is running. Wait for the next stable frame, then review what still needs work.`,
      step: journey.activeStep,
      primaryAction: { kind: "scroll", label: "Follow Process Trace", target: "trace" },
      secondaryAction: { kind: "scroll", label: "Inspect Current Output", target: "output" },
    },
    running_trace: {
      title: "Conversion in progress.",
      body: `${stageLabel} is running. Follow the trace and watch for the first usable output.`,
      step: journey.activeStep,
      primaryAction: { kind: "scroll", label: "Follow Process Trace", target: "trace" },
      secondaryAction: { kind: "scroll", label: "Watch Output", target: "output" },
    },
    paused_resume_available: {
      title: "Conversion paused.",
      body: "Resume from saved artifacts instead of starting over.",
      step: journey.activeStep,
      primaryAction: { kind: "resume", label: "Resume" },
      secondaryAction: { kind: "scroll", label: "Inspect Saved Output", target: "output" },
    },
    failed_recoverable: {
      title: "Conversion stopped early.",
      body: "Check the trace, then resume or adjust the task before retrying.",
      step: journey.activeStep,
      primaryAction: { kind: "scroll", label: "Review Process Trace", target: "trace" },
      secondaryAction: { kind: "scroll", label: "Adjust Task Goal", target: "input" },
    },
    result_ready_review_overall: {
      title: "Result ready.",
      body: "Review the full output first. Use local edits only for small fixes.",
      step: journey.activeStep,
      primaryAction: { kind: "scroll", label: "Inspect Output", target: "output" },
      secondaryAction: { kind: "scroll", label: "Start Refinement", target: "manual" },
    },
    result_ready_needs_local_refine: {
      title: "Ready for local refinement.",
      body: "Inspect the output, then select the area that still needs cleanup.",
      step: journey.activeStep,
      primaryAction: { kind: "scroll", label: "Start Refinement", target: "manual" },
      secondaryAction: { kind: "scroll", label: "Inspect Output", target: "output" },
    },
    manual_goal_missing: {
      title: "Target selected.",
      body: "Describe the local change next.",
      step: "manual",
      primaryAction: { kind: "scroll", label: "Describe Local Fix", target: "manual" },
      secondaryAction: { kind: "scroll", label: "Inspect Selected Output", target: "output" },
    },
    manual_ready_to_apply: {
      title: "Local edit ready.",
      body: "Apply now, or add a reference image first if needed.",
      step: "manual",
      primaryAction: { kind: "manual-apply", label: "Apply Refinement" },
      secondaryAction: { kind: "scroll", label: "Add Reference Imagery", target: "manual" },
    },
    manual_result_ready: {
      title: "Local edit applied.",
      body: "Compare the result, refine again if needed, or export.",
      step: "manual",
      primaryAction: { kind: "scroll", label: "Compare Changes", target: "manual" },
      secondaryAction: { kind: "scroll", label: "Inspect Output", target: "output" },
    },
  };
  return contentByState[journey.journeyState] || contentByState.empty;
}

function getManualGuidanceContent() {
  const journey = deriveJourneyState();
  const contentByState = {
    empty: {
      title: "Refine unlocks after the first result.",
      body: "Start a conversion first. Local edits open once output is visible.",
    },
    image_ready_needs_prompt: {
      title: "Finish setup before local edits.",
      body: "Add the goal and start the conversion first.",
    },
    ready_to_start: {
      title: "Start the conversion first.",
      body: "Refine is for improving a generated result.",
    },
    running_layout_analysis: {
      title: "Waiting for the first usable frame.",
      body: "Local edits open after the first stable output appears.",
    },
    running_region_generation: {
      title: "Preparing editable regions.",
      body: "Watch the trace now. Start local edits when output appears.",
    },
    running_repair: {
      title: "Auto-repair is running.",
      body: "Let this pass finish, then refine only what remains.",
    },
    running_trace: {
      title: "Wait for output before local edits.",
      body: "Follow the trace until a visible frame is ready.",
    },
    paused_resume_available: {
      title: "Resume or refine.",
      body: "If the current output is close, edit locally. Otherwise resume the conversion.",
    },
    failed_recoverable: {
      title: "Conversion stopped before local edit was ready.",
      body: "Check the trace. If output exists, you can still refine it here.",
    },
    result_ready_review_overall: {
      title: "Select a target area.",
      body: "Click an overlay or draw a selection, then describe the change.",
    },
    result_ready_needs_local_refine: {
      title: "Ready for local refinement.",
      body: "Select the area that needs work, then keep the edit request specific.",
    },
    manual_goal_missing: {
      title: "Target selected.",
      body: "Describe what should change in that area.",
    },
    manual_ready_to_apply: {
      title: "Local edit ready.",
      body: "Apply now, or add a reference image first if needed.",
    },
    manual_result_ready: {
      title: "Local result ready.",
      body: "Compare with the base frame, refine again, or export.",
    },
  };
  return contentByState[journey.journeyState] || contentByState.result_ready_review_overall;
}

function runGuideAction(action) {
  if (!action) {
    return;
  }
  if (action.kind === "submit") {
    elements.sendBtn?.click();
    return;
  }
  if (action.kind === "resume") {
    void resumeRunFromArtifacts();
    return;
  }
  if (action.kind === "manual-apply") {
    void applyManualAdjustment();
    return;
  }
  if (action.kind !== "scroll") {
    return;
  }
  const targetMap = {
    input: elements.invocationSection,
    manual: elements.manualAdjustmentSection,
    sidebar: elements.recentRuns,
    trace: elements.workflowTrace,
    output: elements.compareOutput,
  };
  targetMap[action.target]?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function updateDesktopProcessGuide(guide) {
  if (!document.body.classList.contains("desktop-body")) {
    return;
  }
  const suggestedStep = normalizeDesktopProcessStep(guide?.step || deriveJourneyState().activeStep);
  const selectedStep = normalizeDesktopProcessStep(appState.desktopProcessGuideStep || suggestedStep);
  const processStage = document.querySelector(".desktop-process-stage");
  const previousStep = processStage?.dataset.activeProcess || "";
  const stepChanged = previousStep && previousStep !== selectedStep;
  const content = DESKTOP_PROCESS_GUIDE[selectedStep] || DESKTOP_PROCESS_GUIDE.upload;
  const processEyebrow = document.getElementById("desktop-process-eyebrow");
  const processTitle = document.getElementById("desktop-process-title");
  const processNotes = document.getElementById("desktop-process-notes");
  if (processStage) {
    processStage.dataset.activeProcess = selectedStep;
    if (stepChanged) {
      processStage.classList.remove("is-switching");
      void processStage.offsetWidth;
      processStage.classList.add("is-switching");
      window.setTimeout(() => {
        processStage.classList.remove("is-switching");
      }, 420);
    }
  }
  if (processEyebrow) {
    processEyebrow.textContent = content.eyebrow;
  }
  if (processTitle) {
    processTitle.textContent = content.title;
  }
  if (elements.guideBody) {
    elements.guideBody.textContent = content.body;
  }
  if (processNotes) {
    processNotes.replaceChildren(...content.notes.map((note) => {
      const item = document.createElement("li");
      item.textContent = note;
      return item;
    }));
  }
  for (const tab of document.querySelectorAll("[data-process-target]")) {
    const tabStep = normalizeDesktopProcessStep(tab.getAttribute("data-process-target"));
    const active = tabStep === selectedStep;
    const complete = ["upload", "trace", "manual", "download"].indexOf(tabStep) < ["upload", "trace", "manual", "download"].indexOf(suggestedStep);
    tab.classList.toggle("is-active", active);
    tab.classList.toggle("is-complete", complete && !active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  }
  for (const panel of document.querySelectorAll("[data-process-panel]")) {
    const panelStep = normalizeDesktopProcessStep(panel.getAttribute("data-process-panel"));
    const active = panelStep === selectedStep;
    const exiting = stepChanged && panelStep === previousStep;
    panel.classList.toggle("is-active", active);
    panel.classList.toggle("is-exiting", exiting);
    if (exiting) {
      window.setTimeout(() => {
        panel.classList.remove("is-exiting");
      }, 420);
    }
  }
}

function updateGuideContent() {
  const guide = getGuideContent();
  if (elements.guideTitle) {
    elements.guideTitle.textContent = guide.title;
  }
  if (elements.guideBody) {
    elements.guideBody.textContent = guide.body;
  }
  updateDesktopProcessGuide(guide);
  if (elements.guidePrimaryAction && !document.body.classList.contains("desktop-body")) {
    elements.guidePrimaryAction.textContent = guide.primaryAction?.label || "Continue";
    elements.guidePrimaryAction.onclick = () => runGuideAction(guide.primaryAction);
  }
  if (elements.guideSecondaryAction) {
    const secondary = guide.secondaryAction || null;
    elements.guideSecondaryAction.textContent = secondary?.label || "Next Step";
    elements.guideSecondaryAction.classList.toggle("hidden", !secondary);
    elements.guideSecondaryAction.onclick = secondary ? () => runGuideAction(secondary) : null;
  }
  if (!elements.stepBar) {
    updateManualGuidance();
    return;
  }
  if (document.body.classList.contains("desktop-body")) {
    updateManualGuidance();
    updateMessagePresetSelection();
    return;
  }
  const { hasUpload, hasResult, hasManualResult, runActive } = deriveJourneyState();
  const completed = new Set();
  if (hasUpload) {
    completed.add("upload");
  }
  if (runActive || hasResult || hasManualResult) {
    completed.add("start");
    completed.add("trace");
  }
  if (hasManualResult) {
    completed.add("manual");
  }
  if (hasResult || hasManualResult) {
    completed.add("download");
  }
  for (const item of elements.stepBar.querySelectorAll(".step-item")) {
    const step = item.dataset.step;
    item.classList.toggle("is-active", step === guide.step);
    item.classList.toggle("is-complete", completed.has(step) && step !== guide.step);
  }
  updateManualGuidance();
  updateMessagePresetSelection();
}

function setReadinessChip(element, { label, ready = false, active = false }) {
  if (!element) {
    return;
  }
  element.textContent = label;
  element.classList.toggle("is-ready", ready);
  element.classList.toggle("is-active", active);
}

function updateSimpleArtifactsReadiness(snapshot) {
  const hasInput = Boolean(snapshot?.previews?.input_image_url);
  const hasBbox = Boolean(snapshot?.regions?.length);
  const hasOutput = hasUsableArtifactOutput(snapshot);
  const localReady = hasOutput;
  const stage = (snapshot?.current_stage || "").toLowerCase();

  setReadinessChip(elements.artifactReadinessInput, {
    label: hasInput ? "Input ready" : "Input pending",
    ready: hasInput,
    active: hasInput && !hasBbox,
  });
  setReadinessChip(elements.artifactReadinessBbox, {
    label: hasBbox ? "BBox ready" : "BBox pending",
    ready: hasBbox,
    active: stage.includes("layout") || (hasBbox && !hasOutput),
  });
  setReadinessChip(elements.artifactReadinessOutput, {
    label: hasOutput ? "Output ready" : "Output pending",
    ready: hasOutput,
    active: (stage.includes("region") || stage.includes("object") || stage.includes("repair")) && !localReady,
  });
  setReadinessChip(elements.artifactReadinessManual, {
    label: localReady ? "Local edit ready" : "Local edit pending",
    ready: localReady,
    active: localReady,
  });
}

function updateWorkflowTraceSummary(snapshot) {
  const activeNode = getActiveTraceNode(snapshot);
  const latestNode = getLatestTraceNode(snapshot);
  const currentStage = activeNode ? getReadableTraceTitle(activeNode) : (snapshot?.current_stage || "Waiting to start");
  const latestUpdate = latestNode
    ? (latestNode.summary || getReadableTraceTitle(latestNode))
    : (snapshot?.available ? "Final asset is ready." : "No activity yet");
  let focus = "No active target yet";
  let next = "Start a conversion to see the trace";

  if (snapshot?.regions?.length) {
    const selectedRegionId = appState.selectedOverlay?.regionId;
    const selectedObjectId = appState.selectedOverlay?.objectId;
    if (selectedObjectId && selectedRegionId) {
      focus = `Object ${selectedObjectId} in ${selectedRegionId}`;
    } else if (selectedRegionId) {
      focus = `Region ${selectedRegionId}`;
    } else {
      focus = `${snapshot.regions.length} regions recognized`;
    }
  }

  const journey = deriveJourneyState();
  switch (journey.journeyState) {
    case "running_layout_analysis":
      next = "Wait for bbox and structure to settle.";
      break;
    case "running_region_generation":
      next = "Review the first output frame when it appears.";
      break;
    case "running_repair":
      next = "Let the current repair loop finish.";
      break;
    case "result_ready_review_overall":
      next = "Review the full output before local edits.";
      break;
    case "result_ready_needs_local_refine":
    case "manual_goal_missing":
    case "manual_ready_to_apply":
      next = "Select the target, describe the fix, then apply.";
      break;
    case "manual_result_ready":
      next = "Compare the result, refine again, or export.";
      break;
    default:
      if (snapshot?.available) {
        next = "Inspect the current output and refine only if needed.";
      }
      break;
  }

  if (elements.workflowTraceStage) {
    elements.workflowTraceStage.textContent = currentStage;
  }
  if (elements.workflowTraceFocus) {
    elements.workflowTraceFocus.textContent = focus;
  }
  if (elements.workflowTraceNext) {
    elements.workflowTraceNext.textContent = next;
  }
  if (elements.pipelineCurrentStep) {
    elements.pipelineCurrentStep.textContent = currentStage;
  }
  if (elements.pipelineProgress) {
    elements.pipelineProgress.textContent = getPipelineProgress(snapshot);
  }
  if (elements.pipelineLatestUpdate) {
    elements.pipelineLatestUpdate.textContent = latestUpdate;
  }
  if (elements.pipelineNextStep) {
    elements.pipelineNextStep.textContent = next;
  }
  if (elements.pipelineElapsed) {
    const elapsed = getPipelineElapsedInfo(snapshot);
    elements.pipelineElapsed.removeAttribute("data-elapsed-start");
    elements.pipelineElapsed.removeAttribute("data-elapsed-ended");
    elements.pipelineElapsed.removeAttribute("data-elapsed-duration");
    if (elapsed.startedAt) {
      elements.pipelineElapsed.dataset.elapsedStart = elapsed.startedAt;
      elements.pipelineElapsed.dataset.elapsedEnded = elapsed.endedAt || "";
      elements.pipelineElapsed.textContent = formatElapsedDuration(Math.max(0, Date.now() - new Date(elapsed.startedAt).getTime()));
    } else {
      elements.pipelineElapsed.dataset.elapsedDuration = String(elapsed.durationMs || 0);
      elements.pipelineElapsed.textContent = formatElapsedDuration(elapsed.durationMs || 0);
    }
  }
}

function updateWorkspaceActionAvailability(snapshot) {
  const hasOutput = hasUsableArtifactOutput(snapshot);
  const exportUrl = getExportDownloadUrl(snapshot);
  if (elements.exportSvgButton) {
    elements.exportSvgButton.disabled = !exportUrl;
    elements.exportSvgButton.dataset.downloadUrl = exportUrl || "";
    elements.exportSvgButton.classList.toggle("is-ready", Boolean(exportUrl));
    elements.exportSvgButton.title = exportUrl
      ? "Export the current editable SVG asset."
      : hasOutput
        ? "Export unlocks when the final SVG asset is ready."
        : "Export unlocks after the pipeline produces an SVG preview.";
  }
  if (elements.exportStatus) {
    elements.exportStatus.textContent = exportUrl
      ? "Ready"
      : hasOutput
        ? "Final SVG pending"
        : "Waiting for preview";
    elements.exportStatus.classList.toggle("is-ready", Boolean(exportUrl));
  }

  const refineReady = Boolean(hasOutput);
  const pipelineDone = Boolean(snapshot?.available);
  const refineMessage = refineReady
    ? pipelineDone
      ? "Ready for local fixes"
      : "Available while pipeline continues"
    : "Available after first preview";
  const refineToggle = document.getElementById("desktop-refine-toggle");
  if (refineToggle instanceof HTMLButtonElement) {
    refineToggle.disabled = !refineReady;
    refineToggle.classList.toggle("is-ready", refineReady);
    refineToggle.title = refineMessage;
  }
  if (elements.refineStatus) {
    elements.refineStatus.textContent = refineMessage;
    elements.refineStatus.classList.toggle("is-ready", refineReady);
  }
  if (!refineReady && document.body.dataset.refineSidebar === "expanded") {
    document.body.dataset.refineSidebar = "collapsed";
    refineToggle?.setAttribute("aria-expanded", "false");
  }
}

function updateManualSimpleModeVisibility(snapshot) {
  if (appState.uiMode !== "simple") {
    elements.manualWorkflowBar?.classList.remove("manual-section-collapsed");
    elements.manualEditCore?.classList.remove("manual-section-collapsed");
    elements.manualReferencePanel?.classList.remove("auto-collapsed");
    return;
  }

  const journey = deriveJourneyState();
  const hasOutput = hasUsableArtifactOutput(snapshot);
  const hasTarget = Boolean(
    appState.manualConfirmedTarget?.selectionBox
    || appState.manualSelectionBox
    || appState.selectedOverlay?.regionId
  );
  const hasGoal = Boolean((elements.manualUserIntroduction?.value || "").trim() || (elements.manualTargetDescription?.value || "").trim());
  const readyToApply = Boolean(hasOutput && hasTarget && hasGoal);

  setReadinessChip(elements.manualEntryOutput, {
    label: hasOutput ? "Output ready" : "Output pending",
    ready: hasOutput,
    active: !hasOutput,
  });
  setReadinessChip(elements.manualEntryTarget, {
    label: hasTarget ? "Target selected" : "Target not selected",
    ready: hasTarget,
    active: hasOutput && !hasTarget,
  });
  setReadinessChip(elements.manualEntryGoal, {
    label: hasGoal ? "Goal ready" : "Goal missing",
    ready: hasGoal,
    active: hasTarget && !hasGoal,
  });
  setReadinessChip(elements.manualEntryReady, {
    label: readyToApply ? "Ready to apply" : "Not ready to apply",
    ready: readyToApply,
    active: readyToApply,
  });

  if (elements.manualEntryText) {
    if (!hasOutput) {
      elements.manualEntryText.textContent = "Wait for the first usable output.";
    } else if (!hasTarget) {
      elements.manualEntryText.textContent = "Select or draw the local target.";
    } else if (!hasGoal) {
      elements.manualEntryText.textContent = "Target locked. Describe the local change.";
    } else {
      elements.manualEntryText.textContent = "Ready to apply. Add references only if needed.";
    }
  }

  const collapseWorkflow = !hasOutput;
  const collapseEditCore = !hasOutput;
  elements.manualWorkflowBar?.classList.toggle("manual-section-collapsed", collapseWorkflow);
  elements.manualEditCore?.classList.toggle("manual-section-collapsed", collapseEditCore);

  if (elements.manualReferencePanel && !elements.manualReferencePanel.matches("[open]")) {
    elements.manualReferencePanel.classList.toggle("auto-collapsed", true);
  } else {
    elements.manualReferencePanel?.classList.remove("auto-collapsed");
  }

  if (elements.manualReferencePanel && !elements.manualReferencePanel.dataset.userToggled) {
    elements.manualReferencePanel.open = Boolean(
      hasOutput
      && hasTarget
      && !hasGoal
      && elements.manualUseReferenceImages?.checked
    );
    elements.manualReferencePanel.classList.toggle("auto-collapsed", !elements.manualReferencePanel.open);
  }

  if (elements.manualTracePanel && !elements.manualTracePanel.dataset.userToggled && !getLatestManualAdjustment(snapshot)) {
    elements.manualTracePanel.open = false;
  }
}

function updateManualGuidance() {
  const content = getManualGuidanceContent();
  if (elements.manualGuidanceTitle) {
    elements.manualGuidanceTitle.textContent = content.title;
  }
  if (elements.manualGuidanceBody) {
    elements.manualGuidanceBody.textContent = content.body;
  }
}

function updateModeControls() {
  if (document.body.classList.contains("desktop-body")) {
    appState.uiMode = "simple";
  }
  const isSimple = appState.uiMode === "simple";
  document.body.dataset.uiMode = appState.uiMode;
  elements.appShell?.setAttribute("data-ui-mode", appState.uiMode);
  if (elements.uiModeBadge) {
    elements.uiModeBadge.textContent = document.body.classList.contains("desktop-body") ? "guided" : `${appState.uiMode} mode`;
    elements.uiModeBadge.className = `status-pill ${isSimple ? "queued" : "running"}`;
  }
  if (elements.simpleModeToggle) {
    elements.simpleModeToggle.classList.toggle("primary-btn", isSimple);
    elements.simpleModeToggle.classList.toggle("secondary-btn", !isSimple);
    elements.simpleModeToggle.setAttribute("aria-pressed", isSimple ? "true" : "false");
  }
  if (elements.proModeToggle) {
    elements.proModeToggle.classList.toggle("primary-btn", !isSimple);
    elements.proModeToggle.classList.toggle("ghost-btn", isSimple);
    elements.proModeToggle.setAttribute("aria-pressed", isSimple ? "false" : "true");
  }
  if (elements.runtimeConfigPanel && !document.body.classList.contains("desktop-body")) {
    if (isSimple && elements.runtimeConfigPanel.open) {
      elements.runtimeConfigPanel.open = false;
    } else if (!isSimple) {
      elements.runtimeConfigPanel.open = true;
    }
  }
  if (elements.invocationAdvancedPanel) {
    if (isSimple && elements.invocationAdvancedPanel.open) {
      elements.invocationAdvancedPanel.open = false;
    } else if (!isSimple) {
      elements.invocationAdvancedPanel.open = true;
    }
  }
  if (elements.manualAdvancedPanel) {
    if (isSimple && elements.manualAdvancedPanel.open) {
      elements.manualAdvancedPanel.open = false;
    } else if (!isSimple) {
      elements.manualAdvancedPanel.open = true;
    }
  }
  updateGuideContent();
  updateSimpleArtifactsReadiness(appState.latestArtifactSnapshot);
  updateWorkflowTraceSummary(appState.latestArtifactSnapshot);
  updateManualSimpleModeVisibility(appState.latestArtifactSnapshot);
  window.requestAnimationFrame(() => {
    syncRecentRunsHeight();
    window.requestAnimationFrame(syncRecentRunsHeight);
  });
}

function setUiMode(mode) {
  if (document.body.classList.contains("desktop-body")) {
    appState.uiMode = "simple";
    updateModeControls();
    if (appState.latestArtifactSnapshot) {
      renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
    }
    return;
  }
  if (!["simple", "pro"].includes(mode) || appState.uiMode === mode) {
    updateModeControls();
    if (appState.latestArtifactSnapshot) {
      renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
    }
    return;
  }
  appState.uiMode = mode;
  try {
    window.localStorage.setItem(UI_MODE_STORAGE_KEY, mode);
  } catch {
    // Ignore persistence failures.
  }
  updateModeControls();
  if (appState.latestArtifactSnapshot) {
    renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
  }
}

function loadUiModePreference() {
  if (document.body.classList.contains("desktop-body")) {
    appState.uiMode = "simple";
    return;
  }
  try {
    const stored = window.localStorage.getItem(UI_MODE_STORAGE_KEY);
    if (stored === "simple" || stored === "pro") {
      appState.uiMode = stored;
    }
  } catch {
    appState.uiMode = "simple";
  }
}

function getRunList(snapshot) {
  if (!snapshot) {
    return [];
  }
  const runs = [];
  if (snapshot.current_run) {
    runs.push(snapshot.current_run);
  }
  for (const run of snapshot.recent_runs || []) {
    if (!runs.some((item) => item.run_id === run.run_id)) {
      runs.push(run);
    }
  }
  return runs.sort((left, right) => {
    const leftTime = Date.parse(left?.updated_at || left?.finished_at || left?.started_at || 0);
    const rightTime = Date.parse(right?.updated_at || right?.finished_at || right?.started_at || 0);
    return rightTime - leftTime;
  });
}

function getSelectedRun(snapshot = appState.snapshot) {
  const runs = getRunList(snapshot);
  if (!runs.length) {
    return null;
  }
  if (appState.manualAdjustmentRequestInFlight && appState.manualAdjustmentBaseRunId) {
    return runs.find((run) => run.run_id === appState.manualAdjustmentBaseRunId) || runs.find((run) => run.artifact_dir) || runs[0];
  }
  if (appState.selectedRunId) {
    return runs.find((run) => run.run_id === appState.selectedRunId) || runs[0];
  }
  return snapshot?.current_run || runs[0];
}

function isLiveRunSelected(snapshot = appState.snapshot) {
  const selectedRun = getSelectedRun(snapshot);
  return Boolean(selectedRun && snapshot?.current_run && selectedRun.run_id === snapshot.current_run.run_id);
}

function renderViews() {
  const selectedRun = getSelectedRun();
  renderApproval(appState.snapshot?.approval_request || null);
  renderRunSummary(selectedRun || null, appState.selectedRunId);
  renderTimeline(selectedRun || null, appState.snapshot?.messages || [], appState.selectedEventIndex, (eventIndex, linkedMessageIndex) => {
    appState.selectedEventIndex = eventIndex;
    appState.linkedMessageIndex = linkedMessageIndex;
    renderViews();
  });
  renderRecentRuns(
    getRunList(appState.snapshot),
    appState.selectedRunId,
    (runId) => setSelectedRun(runId),
    async (run) => {
      setSelectedRun(run.run_id);
      await resumeRunForRun(run);
    },
    () => setSelectedRun(null),
    document.body.classList.contains("desktop-body")
      ? {
        pagination: {
          enabled: true,
          filterStatus: appState.desktopHistoryFilter,
          page: appState.desktopHistoryPage,
          pageSize: appState.desktopHistoryPageSize,
          search: appState.desktopHistorySearch,
          sort: appState.desktopHistorySort,
          onPageResolved: (page) => {
            appState.desktopHistoryPage = page;
          },
        },
      }
      : {},
  );
  updateGuideContent();
  updateSimpleArtifactsReadiness(appState.latestArtifactSnapshot);
  updateWorkflowTraceSummary(appState.latestArtifactSnapshot);
  updateManualSimpleModeVisibility(appState.latestArtifactSnapshot);
  window.requestAnimationFrame(() => {
    syncRecentRunsHeight();
    window.requestAnimationFrame(syncRecentRunsHeight);
  });
}

function readManualSelectionBoxFromInputs() {
  const x = Number.parseInt(elements.manualBboxX.value.trim(), 10);
  const y = Number.parseInt(elements.manualBboxY.value.trim(), 10);
  const width = Number.parseInt(elements.manualBboxWidth.value.trim(), 10);
  const height = Number.parseInt(elements.manualBboxHeight.value.trim(), 10);
  if ([x, y, width, height].some((value) => Number.isNaN(value)) || width <= 0 || height <= 0) {
    return null;
  }
  return { x, y, width, height };
}

function writeManualSelectionBox(box) {
  appState.manualSelectionBox = box;
  elements.manualBboxX.value = box ? String(box.x) : "";
  elements.manualBboxY.value = box ? String(box.y) : "";
  elements.manualBboxWidth.value = box ? String(box.width) : "";
  elements.manualBboxHeight.value = box ? String(box.height) : "";
}

function writeManualSelectionShape(selectionShape) {
  appState.manualSelectionShape = selectionShape;
  writeManualSelectionBox(selectionShape?.bbox || null);
}

function getNormalizedSelectionKind() {
  return appState.manualSelectionMode === "draw-freeform" ? "freeform" : "box";
}

function getNormalizedReferenceSelectionKind() {
  return appState.manualReferenceSelectionMode === "draw-freeform" ? "freeform" : "box";
}

function clearManualSelectionBox() {
  writeManualSelectionBox(null);
  appState.manualSelectionShape = null;
  appState.manualConfirmedTarget = null;
  appState.selectedOverlay = { type: "region", regionId: null, objectId: null };
  elements.manualObjectIds.value = "";
  elements.manualRegionId.value = "";
}

function clearManualReferenceSelection() {
  appState.manualReferenceSelectionShape = null;
  appState.manualConfirmedReferenceSelection = null;
  appState.manualCustomReferenceConfirmed = false;
  setManualReferenceSelectionMode("select");
}

function setManualSelectionMode(mode) {
  appState.manualSelectionMode = mode;
  if (mode === "draw-box" || mode === "draw-freeform") {
    appState.selectedOverlay = { type: "region", regionId: null, objectId: null };
  }
  elements.manualSelectMode.classList.toggle("primary-btn", mode === "select");
  elements.manualSelectMode.classList.toggle("secondary-btn", mode !== "select");
  elements.manualDrawBox.classList.toggle("primary-btn", mode === "draw-box");
  elements.manualDrawBox.classList.toggle("secondary-btn", mode !== "draw-box");
  elements.manualDrawFreeform.classList.toggle("primary-btn", mode === "draw-freeform");
  elements.manualDrawFreeform.classList.toggle("secondary-btn", mode !== "draw-freeform");
}

function setManualReferenceSelectionMode(mode) {
  appState.manualReferenceSelectionMode = mode;
  if (mode === "draw-box" || mode === "draw-freeform") {
    appState.selectedOverlay = { type: "region", regionId: null, objectId: null };
  }
  elements.manualReferenceDrawBox.classList.toggle("primary-btn", mode === "draw-box");
  elements.manualReferenceDrawBox.classList.toggle("secondary-btn", mode !== "draw-box");
  elements.manualReferenceDrawFreeform.classList.toggle("primary-btn", mode === "draw-freeform");
  elements.manualReferenceDrawFreeform.classList.toggle("secondary-btn", mode !== "draw-freeform");
}

function getOverlayBox(snapshot, selectedOverlay) {
  const region = snapshot?.regions?.find((item) => item.region_id === selectedOverlay.regionId);
  const object = region?.objects?.find((item) => item.object_id === selectedOverlay.objectId);
  if (object?.bbox && region?.bbox) {
    if (object.bbox_space === "global") {
      return { ...object.bbox };
    }
    return {
      x: region.bbox.x + object.bbox.x,
      y: region.bbox.y + object.bbox.y,
      width: object.bbox.width,
      height: object.bbox.height,
    };
  }
  if (region?.bbox) {
    return { ...region.bbox };
  }
  return null;
}

function boxesOverlap(a, b) {
  return !(
    a.x + a.width <= b.x ||
    b.x + b.width <= a.x ||
    a.y + a.height <= b.y ||
    b.y + b.height <= a.y
  );
}

function resolveSelectionFromCurrentState(snapshot) {
  const selectionBox = readManualSelectionBoxFromInputs() || appState.manualSelectionBox || getOverlayBox(snapshot, appState.selectedOverlay);
  const selectedRegion = snapshot?.regions?.find((item) => item.region_id === appState.selectedOverlay.regionId) || null;
  const selectedObject = selectedRegion?.objects?.find((item) => item.object_id === appState.selectedOverlay.objectId) || null;
  const overlappedObjects = [];
  const overlappedRegions = new Set();

  if (selectionBox && snapshot?.regions?.length) {
    for (const region of snapshot.regions) {
      const regionBox = region.bbox;
      if (boxesOverlap(selectionBox, regionBox)) {
        overlappedRegions.add(region.region_id);
      }
      for (const object of region.objects || []) {
        if (!object.bbox) {
          continue;
        }
        const globalBox = object.bbox_space === "global"
          ? { ...object.bbox }
          : {
              x: region.bbox.x + object.bbox.x,
              y: region.bbox.y + object.bbox.y,
              width: object.bbox.width,
              height: object.bbox.height,
            };
        if (boxesOverlap(selectionBox, globalBox)) {
          overlappedObjects.push({ regionId: region.region_id, objectId: object.object_id });
          overlappedRegions.add(region.region_id);
        }
      }
    }
  }

  if (selectedObject && !overlappedObjects.some((item) => item.objectId === selectedObject.object_id)) {
    overlappedObjects.unshift({ regionId: selectedRegion.region_id, objectId: selectedObject.object_id });
    overlappedRegions.add(selectedRegion.region_id);
  } else if (selectedRegion && !selectedObject) {
    overlappedRegions.add(selectedRegion.region_id);
  }

  const uniqueObjectIds = [...new Set(overlappedObjects.map((item) => item.objectId))];
  const regionIds = [...overlappedRegions];
  const explicitRegionId =
    selectedRegion && !selectedObject && regionIds.length <= 1
      ? selectedRegion.region_id
      : regionIds.length === 1 && !uniqueObjectIds.length
        ? regionIds[0]
        : null;
  return {
    selectionBox,
    objectIds: uniqueObjectIds,
    regionIds,
    regionId: explicitRegionId,
    selectionScope:
      uniqueObjectIds.length > 1
        ? "object_collection"
        : uniqueObjectIds.length === 1
          ? "object"
          : regionIds.length >= 1
            ? "bbox_fragment"
            : "bbox_fragment",
  };
}

function confirmManualSelection(snapshot) {
  if (!hasUsableArtifactOutput(snapshot)) {
    return;
  }
  const resolved = resolveSelectionFromCurrentState(snapshot);
  if (resolved.selectionBox) {
    writeManualSelectionBox(resolved.selectionBox);
    appState.manualSelectionShape = {
      kind: getNormalizedSelectionKind(),
      points: getNormalizedSelectionKind() === "freeform" ? appState.manualSelectionShape?.points || [] : [],
      bbox: resolved.selectionBox,
    };
  }
  elements.manualObjectIds.value = resolved.objectIds.join(", ");
  elements.manualRegionId.value = resolved.regionId || "";
  const activeFrame = snapshot?.output_frames?.[appState.selectedOutputFrameIndex] || null;
  appState.manualConfirmedTarget = {
    baseFrameId: activeFrame?.frame_id || null,
    baseFrameTitle: activeFrame?.title || null,
    selectionBox: resolved.selectionBox,
    regionId: resolved.regionId,
    regionIds: resolved.regionIds,
    objectIds: resolved.objectIds,
    selectionScope: resolved.selectionScope,
    selectionKind: appState.manualSelectionShape?.kind || getNormalizedSelectionKind(),
  };
}

function confirmManualReferenceSelection(snapshot) {
  const hasCustomPaths = getManualReferencePaths().length > 0;
  const hasDrawnSelection = Boolean(hasUsableArtifactOutput(snapshot) && appState.manualReferenceSelectionShape?.bbox);
  if (!hasCustomPaths && !hasDrawnSelection) {
    return;
  }
  if (hasDrawnSelection) {
    const activeFrame = snapshot?.output_frames?.[appState.selectedOutputFrameIndex] || null;
    appState.manualConfirmedReferenceSelection = {
      baseFrameId: activeFrame?.frame_id || null,
      baseFrameTitle: activeFrame?.title || null,
      selectionBox: appState.manualReferenceSelectionShape.bbox,
      selectionKind: appState.manualReferenceSelectionShape.kind || getNormalizedReferenceSelectionKind(),
    };
  } else {
    appState.manualConfirmedReferenceSelection = null;
  }
  appState.manualCustomReferenceConfirmed = true;
  elements.manualIncludeDefaultCrop.checked = false;
}

function getManualReferencePaths() {
  const inlinePaths = appState.uiMode === "pro"
    ? elements.manualReferencePaths.value
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean)
    : [];
  const uploadedPaths = appState.manualReferenceUploads.map((item) => item.image_path);
  return [...uploadedPaths, ...inlinePaths];
}

function releaseManualReferenceUploads() {
  for (const upload of appState.manualReferenceUploads) {
    if (upload.previewObjectUrl) {
      URL.revokeObjectURL(upload.previewObjectUrl);
    }
  }
}

function getLatestManualReferenceUpload() {
  return appState.manualReferenceUploads[appState.manualReferenceUploads.length - 1] || null;
}

function resetManualReferenceSurface() {
  elements.manualReferencePreviewImage.removeAttribute("src");
  elements.manualReferencePreviewImage.classList.add("hidden");
  elements.manualReferencePreviewEmpty.classList.remove("hidden");
  elements.manualReferencePreviewMeta.textContent =
    "Focus here, then paste an image. You can also choose a file or capture from Input.";
  elements.manualReferencePastezone.classList.add("upload-preview-empty-state");
}

function setManualReferenceSurfacePreview({ objectUrl, metaText }) {
  elements.manualReferencePreviewImage.src = objectUrl;
  elements.manualReferencePreviewImage.classList.remove("hidden");
  elements.manualReferencePreviewEmpty.classList.add("hidden");
  elements.manualReferencePreviewMeta.textContent = metaText;
  elements.manualReferencePastezone.classList.remove("upload-preview-empty-state");
}

function renderManualReferenceSurface(snapshot) {
  const latestUpload = getLatestManualReferenceUpload();
  const inlinePathCount = appState.uiMode === "pro"
    ? elements.manualReferencePaths.value
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean)
      .length
    : 0;
  if (latestUpload?.previewObjectUrl) {
    const confirmationLabel = appState.manualCustomReferenceConfirmed ? "confirmed" : "uploaded";
    setManualReferenceSurfacePreview({
      objectUrl: latestUpload.previewObjectUrl,
      metaText: `${latestUpload.filename || latestUpload.image_path} | ${confirmationLabel}`,
    });
    return;
  }
  resetManualReferenceSurface();
  const activeSelection = appState.manualConfirmedReferenceSelection || appState.manualReferenceSelectionShape;
  if (activeSelection?.bbox) {
    const bbox = activeSelection.bbox;
    const selectionLabel = appState.manualConfirmedReferenceSelection ? "Confirmed input crop ready" : "Input crop draft ready";
    elements.manualReferencePreviewMeta.textContent =
      `${selectionLabel}: ${bbox.x}, ${bbox.y}, ${bbox.width}, ${bbox.height}. Capture to use it.`;
    return;
  }
  if (inlinePathCount) {
    elements.manualReferencePreviewMeta.textContent = `${inlinePathCount} reference path(s) added. Confirm Ref Area to replace the default crop.`;
    return;
  }
  if (!snapshot?.previews?.input_image_url) {
    elements.manualReferencePreviewMeta.textContent = "Reference thumbnails appear after artifacts load.";
  }
}

function renderManualReferenceUploads() {
  elements.manualReferencePreview.innerHTML = "";
  renderManualReferenceSurface(appState.latestArtifactSnapshot);
  if (!appState.manualReferenceUploads.length) {
    elements.manualReferencePreview.className = "manual-reference-preview empty-state";
    elements.manualReferencePreview.textContent = "Reference previews appear here.";
    if (!appState.manualCustomReferenceConfirmed) {
      elements.manualUploadStatus.textContent = "No reference images uploaded.";
    }
    return;
  }

  elements.manualReferencePreview.className = "manual-reference-preview";
  for (const upload of appState.manualReferenceUploads) {
    if (upload.previewObjectUrl) {
      const preview = document.createElement("div");
      preview.className = "manual-reference-thumb";
      preview.innerHTML = `
        <img src="${upload.previewObjectUrl}" alt="${upload.filename || "Reference image"}" />
        <div class="manual-reference-thumb-footer">
          <div class="manual-reference-caption">${upload.filename || upload.image_path}</div>
          <div class="manual-reference-thumb-actions">
            <button
              class="image-zoom-button"
              type="button"
              data-zoom-src="${upload.previewObjectUrl}"
              data-zoom-alt="${upload.filename || "Reference image"}"
              data-zoom-caption="${upload.filename || upload.image_path}"
            >
              Zoom
            </button>
            <button class="ghost-btn compact-btn" type="button" data-remove-reference="${upload.image_path}">
              Remove
            </button>
          </div>
        </div>
      `;
      preview.querySelector("[data-remove-reference]")?.addEventListener("click", () => {
        if (upload.previewObjectUrl) {
          URL.revokeObjectURL(upload.previewObjectUrl);
        }
        appState.manualReferenceUploads = appState.manualReferenceUploads.filter((entry) => entry.image_path !== upload.image_path);
        appState.manualCustomReferenceConfirmed = false;
        renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
      });
      elements.manualReferencePreview.appendChild(preview);
    }
  }
  elements.manualUploadStatus.textContent = appState.manualCustomReferenceConfirmed
    ? `${appState.manualReferenceUploads.length} reference image(s) confirmed.`
    : `${appState.manualReferenceUploads.length} reference image(s) uploaded. Confirm to replace the default crop.`;
}

function renderConfirmedTargetCard(activeFrame) {
  const target = appState.manualConfirmedTarget;
  if (!target) {
    elements.manualConfirmedTarget.className = "manual-confirmed-target empty-state";
    elements.manualConfirmedTarget.textContent = "Confirm a selection to pin the target region, objects, bbox, and base output frame.";
    return;
  }
  const customReferencePaths = getManualReferencePaths();
  const confirmedCustomReference = appState.manualCustomReferenceConfirmed
    && (customReferencePaths.length > 0 || appState.manualConfirmedReferenceSelection?.selectionBox);
  const referenceSourceLabel = confirmedCustomReference
    ? appState.manualReferenceUploads.length
      ? `custom uploads (${appState.manualReferenceUploads.length})`
      : appState.manualConfirmedReferenceSelection?.selectionBox
        ? "confirmed input crop"
        : `${customReferencePaths.length} custom path(s)`
    : elements.manualUseReferenceImages.checked && elements.manualIncludeDefaultCrop.checked
      ? "default crop"
      : "none";
  elements.manualConfirmedTarget.className = "manual-confirmed-target";
  const isSimpleMode = document.body?.dataset?.uiMode === "simple";
  if (isSimpleMode) {
    elements.manualConfirmedTarget.innerHTML = `
      <div class="manual-confirmed-pill-row">
        <span class="workflow-trace-chip">${target.baseFrameTitle || activeFrame?.title || "base frame pending"}</span>
        <span class="workflow-trace-chip">${target.selectionScope || "local target"}</span>
        <span class="workflow-trace-chip">${target.regionId || (target.regionIds?.length ? target.regionIds.join(", ") : "region pending")}</span>
        <span class="workflow-trace-chip">${referenceSourceLabel}</span>
      </div>
    `;
  } else {
    elements.manualConfirmedTarget.innerHTML = `
      <div class="manual-confirmed-row"><span class="summary-label">Base frame</span><span class="summary-value">${target.baseFrameTitle || activeFrame?.title || "-"}</span></div>
      <div class="manual-confirmed-row"><span class="summary-label">Scope</span><span class="summary-value">${target.selectionScope || "-"}</span></div>
      <div class="manual-confirmed-row"><span class="summary-label">Region</span><span class="summary-value">${target.regionId || (target.regionIds?.length ? target.regionIds.join(", ") : "-")}</span></div>
      <div class="manual-confirmed-row"><span class="summary-label">Objects</span><span class="summary-value">${target.objectIds?.length ? target.objectIds.join(", ") : "-"}</span></div>
      <div class="manual-confirmed-row"><span class="summary-label">BBox</span><span class="summary-value">${target.selectionBox ? `${target.selectionBox.x}, ${target.selectionBox.y}, ${target.selectionBox.width}, ${target.selectionBox.height}` : "-"}</span></div>
      <div class="manual-confirmed-row"><span class="summary-label">Selection mode</span><span class="summary-value">${target.selectionKind || "-"}</span></div>
      <div class="manual-confirmed-row"><span class="summary-label">Reference source</span><span class="summary-value">${referenceSourceLabel}</span></div>
    `;
  }

  const snapshot = appState.latestArtifactSnapshot;
  const canvasWidth = snapshot?.canvas_width || 0;
  const canvasHeight = snapshot?.canvas_height || 0;
  const previewGrid = document.createElement("div");
  previewGrid.className = "manual-selection-preview-grid";

  const appendFocusPreview = (label, imageUrl) => {
    if (!target.selectionBox || !imageUrl || !canvasWidth || !canvasHeight) {
      return;
    }
    const { x, y, width, height } = target.selectionBox;
    const thumb = document.createElement("div");
    thumb.className = "manual-selection-thumb";
    thumb.innerHTML = `
      <div class="manual-selection-thumb-stage"></div>
      <div class="manual-reference-thumb-footer">
        <div class="manual-reference-caption">${label}</div>
        <button class="image-zoom-button" type="button" data-zoom-src="${imageUrl}" data-zoom-alt="${label}" data-zoom-caption="${label}">Zoom</button>
      </div>
    `;
    const stage = thumb.querySelector(".manual-selection-thumb-stage");
    const image = document.createElement("img");
    image.src = imageUrl;
    image.alt = label;
    stage.style.aspectRatio = `${Math.max(width, 1)} / ${Math.max(height, 1)}`;
    image.style.width = `${(canvasWidth / Math.max(width, 1)) * 100}%`;
    image.style.height = "auto";
    image.style.left = `${-(x / Math.max(width, 1)) * 100}%`;
    image.style.top = `${-(y / Math.max(height, 1)) * 100}%`;
    stage?.appendChild(image);
    previewGrid.appendChild(thumb);
  };

  appendFocusPreview(
    "Selected output area",
    activeFrame?.preview_url || snapshot?.previews?.output_svg_url || snapshot?.previews?.output_png_url || null
  );
  if (confirmedCustomReference && appState.manualReferenceUploads.length) {
    for (const upload of appState.manualReferenceUploads.slice(0, 3)) {
      if (!upload.previewObjectUrl) {
        continue;
      }
      const thumb = document.createElement("div");
      thumb.className = "manual-selection-thumb";
      thumb.innerHTML = `
        <div class="manual-selection-thumb-stage"><img src="${upload.previewObjectUrl}" alt="${upload.filename || "Reference image"}" /></div>
        <div class="manual-reference-thumb-footer">
          <div class="manual-reference-caption">${upload.filename || "Confirmed reference image"}</div>
          <button
            class="image-zoom-button"
            type="button"
            data-zoom-src="${upload.previewObjectUrl}"
            data-zoom-alt="${upload.filename || "Reference image"}"
            data-zoom-caption="${upload.filename || "Confirmed reference image"}"
          >
            Zoom
          </button>
        </div>
      `;
      previewGrid.appendChild(thumb);
    }
  } else if (confirmedCustomReference && appState.manualConfirmedReferenceSelection?.selectionBox) {
    appendFocusPreview("Confirmed reference crop", snapshot?.previews?.input_image_url || null);
  } else if (elements.manualUseReferenceImages.checked && elements.manualIncludeDefaultCrop.checked) {
    appendFocusPreview("Default source crop", snapshot?.previews?.input_image_url || null);
  }
  if (previewGrid.childElementCount > 0) {
    elements.manualConfirmedTarget.appendChild(previewGrid);
  }
}

function renderConfirmedReferenceSelection(snapshot) {
  const referenceSelection = appState.manualConfirmedReferenceSelection;
  const draftSelection = appState.manualReferenceSelectionShape;
  const activeSelection = referenceSelection || draftSelection;
  const customPathCount = getManualReferencePaths().length;
  if (!activeSelection?.bbox) {
    elements.manualReferenceSelectionSummary.textContent = appState.manualCustomReferenceConfirmed && customPathCount
      ? `Confirmed ${customPathCount} custom reference path(s). Default crop will be replaced.`
      : "You can draw a reference area directly on the Input image.";
    return;
  }
  const bbox = activeSelection.bbox;
  const label = referenceSelection ? "Confirmed reference area" : "Reference area draft";
  const replacementHint = appState.manualCustomReferenceConfirmed
    ? " Default crop will be replaced."
    : "";
  elements.manualReferenceSelectionSummary.textContent =
    `${label}: ${bbox.x}, ${bbox.y}, ${bbox.width}, ${bbox.height} (${activeSelection.kind || "box"}).${replacementHint}`;

  const previewUrl = snapshot?.previews?.input_image_url || null;
  const canvasWidth = snapshot?.canvas_width || 0;
  const canvasHeight = snapshot?.canvas_height || 0;
  if (!previewUrl || !canvasWidth || !canvasHeight) {
    return;
  }
  elements.manualReferencePreview.className = "manual-reference-preview";
  const preview = document.createElement("div");
  preview.className = "manual-reference-thumb";
  preview.innerHTML = `
    <div class="manual-selection-thumb-stage"></div>
    <div class="manual-reference-thumb-footer">
      <div class="manual-reference-caption">${referenceSelection ? "Drawn input reference area" : "Draft input reference area"}</div>
      <button
        class="image-zoom-button"
        type="button"
        data-zoom-src="${previewUrl}"
        data-zoom-alt="Reference area preview"
        data-zoom-caption="${referenceSelection ? "Drawn input reference area" : "Draft input reference area"}"
      >
        Zoom
      </button>
    </div>
  `;
  const stage = preview.querySelector(".manual-selection-thumb-stage");
  const image = document.createElement("img");
  image.src = previewUrl;
  image.alt = "Reference area preview";
  stage.style.aspectRatio = `${Math.max(bbox.width, 1)} / ${Math.max(bbox.height, 1)}`;
  image.style.width = `${(canvasWidth / Math.max(bbox.width, 1)) * 100}%`;
  image.style.height = "auto";
  image.style.left = `${-(bbox.x / Math.max(bbox.width, 1)) * 100}%`;
  image.style.top = `${-(bbox.y / Math.max(bbox.height, 1)) * 100}%`;
  stage?.appendChild(image);
  elements.manualReferencePreview.prepend(preview);
}

function renderManualAdjustmentResult(snapshot, activeFrame) {
  const latestAdjustment = getLatestManualAdjustment(snapshot);
  if (!latestAdjustment) {
    elements.manualAdjustmentResult.className = "manual-adjustment-result empty-state";
    elements.manualAdjustmentResult.textContent = "Original and refined previews appear here after refinement.";
    return;
  }

  const fallbackOutputUrl = snapshot?.previews?.output_svg_url || snapshot?.previews?.output_png_url || null;
  const basePreviewUrl = latestAdjustment.base_preview_url || activeFrame?.preview_url || fallbackOutputUrl;
  const baseDownloadUrl = latestAdjustment.base_download_url || activeFrame?.download_url || (basePreviewUrl ? `${basePreviewUrl}&download=true` : null);
  const resultGrid = document.createElement("div");
  resultGrid.className = "manual-result-compare-grid";
  resultGrid.appendChild(createOverlayPreview({
    title: latestAdjustment.base_title || activeFrame?.title || "Base SVG",
    previewUrl: basePreviewUrl,
    downloadUrl: baseDownloadUrl,
    fallbackText: "No base preview available.",
    kind: "svg",
    canvasWidth: snapshot?.canvas_width,
    canvasHeight: snapshot?.canvas_height,
  }));
  resultGrid.appendChild(createOverlayPreview({
    title: latestAdjustment.title || "Adjusted SVG",
    previewUrl: latestAdjustment.preview_url,
    downloadUrl: latestAdjustment.download_url,
    fallbackText: "No adjusted SVG preview available.",
    kind: "svg",
    canvasWidth: snapshot?.canvas_width,
    canvasHeight: snapshot?.canvas_height,
    metaText: latestAdjustment.modified_at ? `Updated ${new Date(latestAdjustment.modified_at).toLocaleString()}` : "",
  }));

  const heading = document.createElement("div");
  heading.className = "manual-result-title-row";
  heading.innerHTML = `
    <div class="compare-title">Adjustment Result</div>
    <div class="structure-meta">${latestAdjustment.adjustment_id || ""}</div>
  `;
  elements.manualAdjustmentResult.className = "manual-adjustment-result";
  elements.manualAdjustmentResult.replaceChildren(heading, resultGrid);
}

function renderManualAdjustmentPanel(snapshot) {
  const selectedOverlay = appState.selectedOverlay || { type: "region", regionId: null, objectId: null };
  const selectionBox = readManualSelectionBoxFromInputs() || appState.manualSelectionBox;
  if (selectionBox && stableStringify(selectionBox) !== stableStringify(appState.manualSelectionBox)) {
    appState.manualSelectionBox = selectionBox;
  }
  const selectedRegion = snapshot?.regions?.find((region) => region.region_id === selectedOverlay.regionId) || null;
  const selectedObject = selectedRegion?.objects?.find((item) => item.object_id === selectedOverlay.objectId) || null;

  let summary = "Select a region or object, or draw a box on the output preview.";
  if (selectedObject) {
    summary = `Selected object ${selectedObject.object_id} in ${selectedRegion.region_id}.`;
  } else if (selectedRegion) {
    summary = `Selected region ${selectedRegion.region_id}.`;
  }
  if (selectionBox) {
    summary += ` Box: ${selectionBox.x}, ${selectionBox.y}, ${selectionBox.width}, ${selectionBox.height}.`;
  }
  if (appState.manualSelectionMode === "draw-freeform") {
    summary += " Freeform drawing mode is active.";
  } else if (appState.manualSelectionMode === "draw-box") {
    summary += " Box drawing mode is active.";
  }
  const generatedRegionId = elements.manualRegionId.value.trim();
  const generatedObjectIds = elements.manualObjectIds.value.trim();
  if (generatedRegionId || generatedObjectIds) {
    summary += ` Target params: region=${generatedRegionId || "-"} objects=${generatedObjectIds || "-"}.`;
  }
  if (appState.manualConfirmedTarget?.selectionScope) {
    summary += ` Confirmed scope=${appState.manualConfirmedTarget.selectionScope}.`;
  }
  elements.manualTargetSummary.textContent = summary;
  const activeFrame = snapshot?.output_frames?.[appState.selectedOutputFrameIndex] || null;
  const selectedManualAdjustment = getSelectedManualAdjustment(snapshot);
  elements.manualBaseFrame.value = activeFrame ? `${activeFrame.title} (${activeFrame.frame_id})` : "";
  const usableOutputReady = hasUsableArtifactOutput(snapshot);
  elements.manualApplyButton.disabled = !usableOutputReady || appState.manualAdjustmentRequestInFlight;
  elements.manualConfirmSelection.disabled = !usableOutputReady;
  elements.manualReferenceConfirmSelection.disabled = !usableOutputReady;
  elements.manualReferenceClearSelection.disabled = !usableOutputReady;
  elements.manualReferencePaths.disabled = !elements.manualUseReferenceImages.checked;
  elements.manualPasteReferenceButton.disabled = !elements.manualUseReferenceImages.checked;
  elements.manualReferenceCaptureButton.disabled =
    !elements.manualUseReferenceImages.checked || !snapshot?.previews?.input_image_url;
  elements.manualReferencePastezone.tabIndex = elements.manualUseReferenceImages.checked ? 0 : -1;
  elements.manualUploadButton.disabled = !elements.manualUseReferenceImages.checked;
  elements.manualUploadInput.disabled = !elements.manualUseReferenceImages.checked;
  elements.manualIncludeDefaultCrop.disabled = !elements.manualUseReferenceImages.checked;
  renderConfirmedTargetCard(activeFrame);
  renderManualAdjustmentResult(snapshot, activeFrame);
  renderManualWorkflowTrace(selectedManualAdjustment || snapshot, (node) => {
    if (node?.event_index == null) {
      return;
    }
    appState.selectedEventIndex = node.event_index;
    appState.linkedMessageIndex = null;
    renderViews();
    scrollIntoContainerView(elements.timeline, `[data-event-index="${node.event_index}"]`);
  });
  renderManualReferenceUploads();
  renderConfirmedReferenceSelection(snapshot);
  updateManualSimpleModeVisibility(snapshot);
}

function stopManualAdjustmentPolling() {
  if (appState.manualAdjustmentPollTimer) {
    window.clearInterval(appState.manualAdjustmentPollTimer);
    appState.manualAdjustmentPollTimer = null;
  }
}

function startManualAdjustmentPolling() {
  stopManualAdjustmentPolling();
  appState.manualAdjustmentPollTimer = window.setInterval(async () => {
    if (!appState.manualAdjustmentRequestInFlight) {
      stopManualAdjustmentPolling();
      return;
    }
    try {
      await refreshSnapshot({ silent: true });
      await refreshArtifactsForSelection({ silent: true, force: true });
    } catch {
      // Keep polling quietly while the request is still in flight.
    }
  }, 1200);
}

async function uploadManualReferenceFiles(files) {
  if (!files?.length) {
    return;
  }
  setStatus("Uploading manual references...");
  appState.manualCustomReferenceConfirmed = false;
  for (const file of files) {
    const buffer = await file.arrayBuffer();
    const data = await fetchJson("/uploads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: file.name,
        content_base64: arrayBufferToBase64(buffer),
      }),
    });
    appState.manualReferenceUploads = [...appState.manualReferenceUploads, { ...data, previewObjectUrl: URL.createObjectURL(file) }];
  }
  renderManualReferenceUploads();
  setStatus("Manual references uploaded");
}

function loadImageElement(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Failed to load the input image for cropping."));
    image.src = src;
  });
}

async function captureReferenceImageFromInput(snapshot) {
  if (!hasUsableArtifactOutput(snapshot) || !snapshot?.previews?.input_image_url) {
    throw new Error("Input preview is not ready yet.");
  }
  const selection =
    appState.manualReferenceSelectionShape?.bbox
    || appState.manualConfirmedReferenceSelection?.selectionBox
    || null;
  if (!selection) {
    throw new Error("Draw or confirm a reference area on the Input image first.");
  }

  const sourceImage = await loadImageElement(snapshot.previews.input_image_url);
  const canvasWidth = Math.max(snapshot.canvas_width || sourceImage.naturalWidth || 0, 1);
  const canvasHeight = Math.max(snapshot.canvas_height || sourceImage.naturalHeight || 0, 1);
  const scaleX = (sourceImage.naturalWidth || canvasWidth) / canvasWidth;
  const scaleY = (sourceImage.naturalHeight || canvasHeight) / canvasHeight;
  const sx = Math.max(0, Math.round(selection.x * scaleX));
  const sy = Math.max(0, Math.round(selection.y * scaleY));
  const sw = Math.max(1, Math.round(selection.width * scaleX));
  const sh = Math.max(1, Math.round(selection.height * scaleY));

  const canvas = document.createElement("canvas");
  canvas.width = sw;
  canvas.height = sh;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("Canvas cropping is unavailable in this browser.");
  }
  context.drawImage(sourceImage, sx, sy, sw, sh, 0, 0, sw, sh);

  const blob = await new Promise((resolve) => {
    canvas.toBlob(resolve, "image/png");
  });
  if (!blob) {
    throw new Error("Failed to export the captured reference image.");
  }

  const timestamp = new Date().toISOString().replaceAll(":", "-").replaceAll(".", "-");
  const file = new File([blob], `input-crop-reference-${timestamp}.png`, {
    type: "image/png",
    lastModified: Date.now(),
  });
  await uploadManualReferenceFiles([file]);
  appState.manualCustomReferenceConfirmed = true;
  elements.manualIncludeDefaultCrop.checked = false;
  elements.manualUploadStatus.textContent = "Input crop captured and confirmed as a reference image.";
  setStatus("Reference crop captured");
}

function buildManualAdjustmentPayload(snapshot) {
  const targetObjectIds = elements.manualObjectIds.value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  let targetRegionId = elements.manualRegionId.value.trim() || null;
  const activeFrame = snapshot.output_frames?.[appState.selectedOutputFrameIndex] || null;
  const confirmedTarget = appState.manualConfirmedTarget;
  if (!targetObjectIds.length && !targetRegionId) {
    if (confirmedTarget?.objectIds?.length) {
      targetObjectIds.push(...confirmedTarget.objectIds);
    } else if (confirmedTarget?.regionId) {
      targetRegionId = confirmedTarget.regionId;
    } else if (appState.selectedOverlay.objectId) {
      targetObjectIds.push(appState.selectedOverlay.objectId);
    } else if (appState.selectedOverlay.regionId) {
      targetRegionId = appState.selectedOverlay.regionId;
    }
  }

  const useReferenceImages = elements.manualUseReferenceImages.checked;
  const confirmedCustomReferences = appState.manualCustomReferenceConfirmed;
  const payload = {
    thread_id: appState.threadId,
    run_id: snapshot.run_id,
    base_frame_id: confirmedTarget?.baseFrameId || activeFrame?.frame_id || null,
    mode: elements.manualMode.value || "worker",
    target_object_ids: targetObjectIds,
    target_region_id: targetRegionId,
    target_description: elements.manualTargetDescription.value.trim() || null,
    user_introduction: elements.manualUserIntroduction.value.trim(),
    use_reference_images: useReferenceImages,
    reference_image_paths: useReferenceImages && confirmedCustomReferences ? getManualReferencePaths() : [],
    include_default_crop: useReferenceImages && (!confirmedCustomReferences && elements.manualIncludeDefaultCrop.checked),
    include_no_image: !useReferenceImages,
  };
  const selectionBox = confirmedTarget?.selectionBox || readManualSelectionBoxFromInputs() || appState.manualSelectionBox;
  if (selectionBox) {
    payload.selection_bbox = selectionBox;
  }
  if (confirmedTarget?.selectionScope === "bbox_fragment" && !targetObjectIds.length) {
    payload.target_region_id = null;
  }
  const referenceSelectionBox =
    confirmedCustomReferences
      ? (appState.manualConfirmedReferenceSelection?.selectionBox || null)
      : null;
  if (referenceSelectionBox && useReferenceImages) {
    payload.reference_selection_bbox = referenceSelectionBox;
  }
  if (payload.mode === "agent") {
    const agentBudget = Number.parseInt(elements.manualAgentBudget.value.trim(), 10);
    if (!Number.isNaN(agentBudget)) {
      payload.agent_budget = agentBudget;
    }
  }
  return payload;
}

async function applyManualAdjustment() {
  const snapshot = appState.latestArtifactSnapshot;
  const hasOutput = hasUsableArtifactOutput(snapshot);
  if (!appState.threadId || !hasOutput || !snapshot?.run_id) {
    setStatus("Output is not ready for refinement.");
    return;
  }
  const goal = elements.manualUserIntroduction.value.trim() || elements.manualTargetDescription.value.trim();
  if (!goal) {
    setStatus("Please describe the target adjustment goal.");
    elements.manualSubmitStatus.textContent = "Add a refinement goal before applying.";
    return;
  }

  const baseRunId = snapshot.run_id;
  appState.manualAdjustmentBaseRunId = baseRunId;
  appState.selectedRunId = baseRunId;
  appState.manualAdjustmentRequestInFlight = true;
  elements.manualApplyButton.disabled = true;
  elements.manualSubmitStatus.textContent = "Applying refinement...";
  setStatus("Running refinement...");
  startManualAdjustmentPolling();
  try {
    const payload = buildManualAdjustmentPayload(snapshot);
    const response = await fetchJson(`/threads/${appState.threadId}/manual-adjust`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    appState.artifactCache.set(snapshot.run_id, {
      signature: stableStringify({
        runId: response.artifact_snapshot.run_id,
        status: response.artifact_snapshot.status,
        updatedAt: getSelectedRun()?.updated_at,
        currentStage: response.artifact_snapshot.current_stage,
      }),
      snapshot: response.artifact_snapshot,
    });
    appState.latestArtifactSnapshot = response.artifact_snapshot;
    const latestManualAdjustment = (response.artifact_snapshot.manual_adjustments || []).at(-1) || null;
    appState.selectedManualAdjustmentId = latestManualAdjustment?.adjustment_id || null;
    elements.manualSubmitStatus.textContent = response.notes?.length
      ? `${response.edit_strategy ? `[${response.edit_strategy}] ` : ""}${response.notes.join(" | ")}`
      : "Refinement applied.";
    await refreshSnapshot({ silent: true });
    renderArtifactViews(response.artifact_snapshot);
    setStatus("Refinement complete");
  } catch (error) {
    const responseData = error.responseData || {};
    if (responseData.artifact_snapshot) {
      appState.latestArtifactSnapshot = responseData.artifact_snapshot;
      renderArtifactViews(responseData.artifact_snapshot);
    }
    const errorLabel = responseData.error_type ? `${responseData.error_type}: ` : "";
    elements.manualSubmitStatus.textContent = `${errorLabel}${error.message || "Refinement failed."}`;
    setStatus(error.message || "Refinement failed");
  } finally {
    appState.manualAdjustmentRequestInFlight = false;
    appState.manualAdjustmentBaseRunId = null;
    appState.selectedRunId = baseRunId;
    stopManualAdjustmentPolling();
    elements.manualApplyButton.disabled = false;
  }
}

function setSelectedRun(runId = null) {
  const previousRunId = getSelectedRun()?.run_id || null;
  appState.selectedRunId = runId;
  const nextRunId = getSelectedRun()?.run_id || null;
  if (previousRunId !== nextRunId) {
    appState.selectedEventIndex = null;
    appState.linkedMessageIndex = null;
    appState.selectedOverlay = { type: "region", regionId: null, objectId: null };
    appState.selectedOutputFrameIndex = 0;
    appState.selectedManualAdjustmentId = null;
    appState.latestArtifactSnapshot = null;
    appState.manualSelectionBox = null;
    appState.manualSelectionShape = null;
    appState.manualConfirmedTarget = null;
    appState.manualReferenceSelectionShape = null;
    appState.manualConfirmedReferenceSelection = null;
    appState.manualCustomReferenceConfirmed = false;
    appState.manualReferenceSelectionMode = "select";
    releaseManualReferenceUploads();
    appState.manualReferenceUploads = [];
  }
  renderViews();
  void refreshArtifactsForSelection({ silent: true, force: true });
  schedulePolling();
}

function applySnapshot(snapshot) {
  appState.snapshot = snapshot;
  appState.threadId = snapshot.thread_id;
  elements.threadId.textContent = appState.threadId;
  appState.pendingApproval = snapshot.approval_request || null;
  const currentRunRevision = snapshot.current_run?.artifact_revision || null;
  if (currentRunRevision) {
    const cached = appState.artifactCache.get(snapshot.current_run.run_id);
    if (cached && cached.snapshot?.artifact_revision !== currentRunRevision) {
      appState.artifactCache.delete(snapshot.current_run.run_id);
    }
  }

  if (appState.selectedRunId && !getRunList(snapshot).some((run) => run.run_id === appState.selectedRunId)) {
    appState.selectedRunId = null;
  }

  renderViews();
  schedulePolling();
}

function getSnapshotPollDelay() {
  if (document.hidden || !appState.threadId) {
    return 0;
  }
  const status = appState.snapshot?.status;
  if (status === "queued") {
    return isLiveRunSelected() ? 1500 : 4000;
  }
  if (status === "running") {
    return isLiveRunSelected() ? 1200 : 4000;
  }
  if (status === "needs_approval" || status === "paused") {
    return 4000;
  }
  return 0;
}

function getArtifactPollDelay() {
  if (document.hidden || !appState.threadId) {
    return 0;
  }
  const selectedRun = getSelectedRun();
  if (!selectedRun || !selectedRun.artifact_dir || !isLiveRunSelected()) {
    return 0;
  }
  if (selectedRun.status === "running" || selectedRun.status === "queued") {
    return 2400;
  }
  if (selectedRun.status === "needs_approval" || selectedRun.status === "paused") {
    return 4500;
  }
  return 0;
}

function stopSnapshotPolling() {
  if (appState.snapshotTimer) {
    window.clearTimeout(appState.snapshotTimer);
    appState.snapshotTimer = null;
  }
}

function stopArtifactPolling() {
  if (appState.artifactTimer) {
    window.clearTimeout(appState.artifactTimer);
    appState.artifactTimer = null;
  }
}

function scheduleSnapshotPolling() {
  stopSnapshotPolling();
  const delay = getSnapshotPollDelay();
  if (!delay) {
    return;
  }
  appState.snapshotTimer = window.setTimeout(async () => {
    try {
      await refreshSnapshot({ silent: true });
    } catch {
      setStatus("Polling failed");
      scheduleSnapshotPolling();
    }
  }, delay);
}

function scheduleArtifactPolling() {
  stopArtifactPolling();
  const delay = getArtifactPollDelay();
  if (!delay) {
    return;
  }
  appState.artifactTimer = window.setTimeout(async () => {
    try {
      await refreshArtifactsForSelection({ silent: true });
    } catch {
      setStatus("Artifact refresh failed");
      scheduleArtifactPolling();
    }
  }, delay);
}

function schedulePolling() {
  scheduleSnapshotPolling();
  scheduleArtifactPolling();
}

async function loadFrontendDefaults() {
  const data = await fetchJson("/config/defaults");
  applyFrontendDefaults(data);
  updateStartRuntimeHint();
}

async function loadFrontendHostInfo() {
  const data = await fetchJson("/frontend/host-info");
  applyHostInfo(data);
}

async function loadRuntimeOverrides() {
  const data = await fetchJson("/config/runtime-overrides");
  applyRuntimeOverrides(data);
  elements.runtimeConfigStatus.textContent = "Loaded";
  updateStartRuntimeHint();
}

async function saveRuntimeOverrides() {
  elements.runtimeConfigSave.disabled = true;
  elements.runtimeConfigStatus.textContent = "Saving...";
  try {
    const data = await fetchJson("/config/runtime-overrides", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildRuntimeOverridesPayload()),
    });
    applyRuntimeOverrides(data);
    updateStartRuntimeHint();
    elements.runtimeConfigStatus.textContent = "Saved";
    setStatus("Global runtime config updated");
  } catch (error) {
    elements.runtimeConfigStatus.textContent = "Save failed";
    setStatus(error.message || "Global runtime config update failed");
  } finally {
    elements.runtimeConfigSave.disabled = false;
  }
}

async function refreshArtifactsForSelection({ silent = false, force = false } = {}) {
  if (!appState.threadId || appState.artifactRequestInFlight) {
    return;
  }
  const selectedRun = getSelectedRun();
  if (!selectedRun || !selectedRun.artifact_dir) {
    appState.latestArtifactSnapshot = null;
    clearArtifactPanel();
    renderManualAdjustmentPanel(null);
    updateWorkflowTraceSummary(null);
    updateWorkspaceActionAvailability(null);
    return;
  }

  const cacheKey = selectedRun.run_id;
  const liveRunSelected = isLiveRunSelected();
  const shouldBypassArtifactCache = liveRunSelected && (selectedRun.status === "running" || selectedRun.status === "queued");
  const cached = appState.artifactCache.get(cacheKey);
  const artifactRevision = selectedRun.artifact_revision || null;
  const cacheSignature = stableStringify({
    runId: selectedRun.run_id,
    status: selectedRun.status,
    updatedAt: selectedRun.updated_at,
    currentStage: selectedRun.current_stage,
    artifactRevision,
  });
  if (!force && !shouldBypassArtifactCache && cached && cached.signature === cacheSignature) {
    appState.latestArtifactSnapshot = cached.snapshot;
    renderArtifactViews(cached.snapshot);
    return;
  }

  appState.artifactRequestInFlight = true;
  try {
    const runQuery = selectedRun.run_id ? `?run_id=${encodeURIComponent(selectedRun.run_id)}` : "";
    const data = await fetchJson(`/threads/${appState.threadId}/artifacts${runQuery}`);
    appState.artifactCache.set(cacheKey, { signature: cacheSignature, snapshot: data });
    appState.latestArtifactSnapshot = data;
    renderArtifactViews(data);
    if (!silent) {
      setStatus("Artifacts refreshed");
    }
  } finally {
    appState.artifactRequestInFlight = false;
    scheduleArtifactPolling();
  }
}

function renderArtifactViews(snapshot) {
  const overlaySelectionAllowed =
    appState.manualSelectionMode === "select" && appState.manualReferenceSelectionMode === "select";
  if (!overlaySelectionAllowed && appState.selectedOverlay.objectId) {
    appState.selectedOverlay = { type: "region", regionId: appState.selectedOverlay.regionId, objectId: null };
  }
  if (appState.selectedOutputFrameIndex >= (snapshot?.output_frames?.length || 1)) {
    appState.selectedOutputFrameIndex = Math.max((snapshot?.output_frames?.length || 1) - 1, 0);
  }
  if (
    appState.selectedManualAdjustmentId &&
    !(snapshot?.manual_adjustments || []).some((item) => item.adjustment_id === appState.selectedManualAdjustmentId)
  ) {
    appState.selectedManualAdjustmentId = null;
  }
  const confirmedTargetSelection = appState.manualConfirmedTarget?.selectionBox
    ? {
        kind: appState.manualConfirmedTarget.selectionKind || "box",
        points: [],
        bbox: appState.manualConfirmedTarget.selectionBox,
      }
    : null;
  const inputSelectionState =
    appState.manualReferenceSelectionMode === "draw-box" || appState.manualReferenceSelectionMode === "draw-freeform"
      ? appState.manualReferenceSelectionShape
      : confirmedTargetSelection;
  const outputSelectionState =
    appState.manualSelectionMode === "draw-box" || appState.manualSelectionMode === "draw-freeform"
      ? appState.manualSelectionShape
      : confirmedTargetSelection;
  renderArtifactSummary(
    snapshot,
    appState.selectedOverlay,
    appState.selectedOutputFrameIndex,
    (overlay) => {
      appState.selectedOverlay = overlay;
      renderArtifactViews(snapshot);
    },
    (index) => {
      appState.selectedOutputFrameIndex = index;
      appState.selectedManualAdjustmentId = null;
      renderArtifactViews(snapshot);
    },
    {
      inputSelectionState,
      inputSelectionMode: appState.manualReferenceSelectionMode,
      onInputSelectionChange: (selection) => {
        appState.manualReferenceSelectionShape = selection;
        appState.manualCustomReferenceConfirmed = false;
        renderArtifactViews(snapshot);
      },
      outputSelectionState,
      outputSelectionMode: appState.manualSelectionMode,
      onOutputSelectionChange: (selection) => {
        writeManualSelectionShape(selection);
        renderArtifactViews(snapshot);
      },
    },
    appState.selectedManualAdjustmentId,
    (adjustmentId) => {
      appState.selectedManualAdjustmentId = adjustmentId || null;
      renderArtifactViews(snapshot);
    },
    (node) => {
      if (node?.event_index == null) {
        return;
      }
      appState.selectedEventIndex = node.event_index;
      appState.linkedMessageIndex = null;
      renderViews();
      scrollIntoContainerView(elements.timeline, `[data-event-index="${node.event_index}"]`);
    }
  );
  updateSimpleArtifactsReadiness(snapshot);
  updateWorkflowTraceSummary(snapshot);
  updateWorkspaceActionAvailability(snapshot);
  renderArtifactFiles(snapshot);
  renderManualAdjustmentPanel(snapshot);
  updateWorkflowTraceTimers();
  updateGuideContent();
}

async function refreshSnapshot({ silent = false } = {}) {
  if (!appState.threadId || appState.snapshotRequestInFlight) {
    return;
  }
  appState.snapshotRequestInFlight = true;
  try {
    const data = await fetchJson(`/threads/${appState.threadId}/snapshot`);
    applySnapshot(data);
    await refreshArtifactsForSelection({ silent: true, force: true });
    if (!silent) {
      setStatus("Monitor refreshed");
    }
  } finally {
    appState.snapshotRequestInFlight = false;
    scheduleSnapshotPolling();
  }
}

async function createThread() {
  const data = await fetchJson("/threads", { method: "POST" });
  appState.threadId = data.thread_id;
  elements.threadId.textContent = appState.threadId;
  appState.artifactCache.clear();
  releaseManualReferenceUploads();
  clearUploadPreview();
  resetUiSelections();
  resetRenderState();
  clearArtifactPanel();
  renderManualAdjustmentPanel(null);
  updateWorkflowTraceSummary(null);
  updateWorkspaceActionAvailability(null);
  updateEffectiveValues();
}

async function sendMessage() {
  const readiness = getStartRuntimeReadiness();
  if (!readiness.ready) {
    updateStartRuntimeHint();
    setStatus("Complete runtime settings before starting a conversion");
    return;
  }

  sendRequestInFlight = true;
  updateStartRuntimeHint();
  setStatus("Request accepted. Processing...");
  try {
    if (!appState.threadId) {
      await createThread();
    }
    const data = await fetchJson("/invoke", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildInvokePayload(appState.threadId)),
    });
    appState.threadId = data.thread_id;
    elements.threadId.textContent = appState.threadId;
    resetUiSelections();
    setStatus("Running");
    await refreshSnapshot({ silent: true });
  } catch (error) {
    setStatus(error.message || "Send failed");
  } finally {
    sendRequestInFlight = false;
    updateStartRuntimeHint();
  }
}

async function resumeApproval(decision) {
  if (!appState.threadId || !appState.pendingApproval) {
    return;
  }

  const action = decision === "approve" ? "approval" : "rejection";
  setStatus(`Legacy ${action} flow is no longer supported. Use Resume Run from saved artifacts instead.`);
}

async function resumeRunForRun(run) {
  if (!run?.artifact_dir) {
    setStatus("No resumable run is available.");
    return;
  }

  const extraBudgetRaw = elements.resumeExtraBudget.value.trim();
  const payload = {
    run_dir: run.artifact_dir,
    thread_id: appState.threadId,
  };
  if (extraBudgetRaw) {
    const extraBudget = Number.parseInt(extraBudgetRaw, 10);
    if (!Number.isNaN(extraBudget)) {
      payload.extra_budget = extraBudget;
      payload.budget_mode = "top_up";
    }
  }

  setStatus("Resuming from saved artifacts...");
  elements.resumeRun.disabled = true;
  try {
    const data = await fetchJson("/runs/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    appState.threadId = data.thread_id;
    elements.threadId.textContent = appState.threadId;
    resetUiSelections();
    await refreshSnapshot({ silent: true });
    setStatus("Resumed");
  } catch (error) {
    setStatus(error.message || "Resume failed");
  } finally {
    elements.resumeRun.disabled = false;
  }
}

async function resumeRunFromArtifacts() {
  if (!appState.latestArtifactSnapshot?.artifact_dir || !appState.latestArtifactSnapshot?.resume?.available) {
    setStatus("No resumable run is available.");
    return;
  }
  const selectedRun = getSelectedRun();
  await resumeRunForRun({
    artifact_dir: appState.latestArtifactSnapshot.artifact_dir,
    run_id: selectedRun?.run_id || appState.latestArtifactSnapshot.run_id,
  });
}

function bindFormEvents() {
  async function handleInputImageUpload(file, failureMessage = "Upload failed.") {
    if (!file) {
      return;
    }
    try {
      await uploadLocalFile(file, setStatus);
    } catch (error) {
      elements.uploadStatus.textContent = failureMessage;
      setStatus(error.message || failureMessage);
    }
  }

  async function handleManualReferenceUpload(file, failureMessage = "Reference upload failed.") {
    if (!file) {
      return;
    }
    try {
      await uploadManualReferenceFiles([file]);
      renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
    } catch (error) {
      elements.manualUploadStatus.textContent = failureMessage;
      setStatus(error.message || failureMessage);
    }
  }

  function extractClipboardImageFile(event) {
    const items = Array.from(event.clipboardData?.items || []);
    const imageItem = items.find((item) => item.kind === "file" && item.type.startsWith("image/"));
    return imageItem?.getAsFile() || null;
  }

  function openInputImagePicker() {
    elements.uploadFileInput.click();
  }

  function bindUploadSurface(surface, { enableDragAndDrop = false, focusOnly = false } = {}) {
    surface.addEventListener("click", () => {
      if (focusOnly) {
        surface.focus();
        elements.uploadStatus.textContent = "";
        return;
      }
      openInputImagePicker();
    });

    surface.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        if (focusOnly) {
          surface.focus();
          elements.uploadStatus.textContent = "";
        } else {
          openInputImagePicker();
        }
      }
    });

    surface.addEventListener("paste", async (event) => {
      const imageFile = extractClipboardImageFile(event);
      if (!imageFile) {
        return;
      }
      event.preventDefault();
      elements.uploadStatus.textContent = "Pasted image detected. Uploading...";
      await handleInputImageUpload(imageFile, "Clipboard image upload failed.");
    });

    if (!enableDragAndDrop) {
      return;
    }

    ["dragenter", "dragover"].forEach((type) => {
      surface.addEventListener(type, (event) => {
        event.preventDefault();
        surface.classList.add("dragover");
      });
    });

    ["dragleave", "drop"].forEach((type) => {
      surface.addEventListener(type, (event) => {
        event.preventDefault();
        surface.classList.remove("dragover");
      });
    });

    surface.addEventListener("drop", async (event) => {
      const [file] = event.dataTransfer?.files || [];
      if (!file) {
        return;
      }
      await handleInputImageUpload(file, "Upload failed.");
    });
  }

  elements.composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = getMessageEffectiveValue().trim();
    if (!message) {
      setStatus("Please enter a task description.");
      return;
    }
    await sendMessage();
  });

  elements.uploadFileButton.addEventListener("click", (event) => {
    event.stopPropagation();
    void (async () => {
      if (appState.hostCapabilities.canOpenLocalFilePicker && window.desktopHost) {
        const imagePath = await pickLocalFileFromHost();
        if (imagePath) {
          elements.imagePath.value = imagePath;
          elements.uploadStatus.textContent = "Selected local image from local workspace.";
          updateEffectiveValues();
          updateGuideContent();
          return;
        }
      }
      elements.uploadFileInput.click();
    })();
  });

  elements.uploadFileInput.addEventListener("change", async (event) => {
    const [file] = event.target.files || [];
    if (!file) {
      return;
    }
    try {
      await handleInputImageUpload(file, "Upload failed.");
    } finally {
      event.target.value = "";
    }
  });

  bindUploadSurface(elements.uploadPreviewPanel, { enableDragAndDrop: true, focusOnly: true });

  function bindManualReferenceSurface(surface) {
    surface.addEventListener("click", () => {
      surface.focus();
      elements.manualUploadStatus.textContent = "Thumbnail focused. Paste a clipboard image, drag in a file, or use the actions on the right.";
    });
    surface.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        surface.focus();
        elements.manualUploadStatus.textContent = "Thumbnail focused. Paste a clipboard image, drag in a file, or use the actions on the right.";
      }
    });
    surface.addEventListener("paste", async (event) => {
      const imageFile = extractClipboardImageFile(event);
      if (!imageFile) {
        return;
      }
      event.preventDefault();
      elements.manualUploadStatus.textContent = "Pasted reference detected. Uploading...";
      await handleManualReferenceUpload(imageFile, "Clipboard reference upload failed.");
    });
    ["dragenter", "dragover"].forEach((type) => {
      surface.addEventListener(type, (event) => {
        event.preventDefault();
        surface.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach((type) => {
      surface.addEventListener(type, (event) => {
        event.preventDefault();
        surface.classList.remove("dragover");
      });
    });
    surface.addEventListener("drop", async (event) => {
      const [file] = event.dataTransfer?.files || [];
      if (!file) {
        return;
      }
      await handleManualReferenceUpload(file, "Reference upload failed.");
    });
  }

  bindManualReferenceSurface(elements.manualReferencePastezone);

  document.addEventListener("paste", async (event) => {
    if (event.defaultPrevented) {
      return;
    }
    const activeElement = document.activeElement;
    if (
      activeElement instanceof HTMLInputElement
      || activeElement instanceof HTMLTextAreaElement
      || activeElement?.isContentEditable
    ) {
      return;
    }
    const imageFile = extractClipboardImageFile(event);
    if (!imageFile) {
      return;
    }
    event.preventDefault();
    elements.uploadStatus.textContent = "Pasted image detected. Uploading...";
    await handleInputImageUpload(imageFile, "Clipboard image upload failed.");
  });

  [elements.manualBboxX, elements.manualBboxY, elements.manualBboxWidth, elements.manualBboxHeight].forEach((element) => {
    element.addEventListener("input", () => {
      appState.manualSelectionBox = readManualSelectionBoxFromInputs();
      if (appState.manualSelectionBox) {
        appState.manualSelectionShape = {
          kind: getNormalizedSelectionKind(),
          points: appState.manualSelectionShape?.points || [],
          bbox: appState.manualSelectionBox,
        };
      }
      renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
      if (appState.latestArtifactSnapshot) {
        renderArtifactViews(appState.latestArtifactSnapshot);
      }
    });
  });

  elements.manualReferencePaths.addEventListener("input", () => {
    appState.manualCustomReferenceConfirmed = false;
    renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
  });

  [elements.manualReferencePanel, elements.manualTracePanel].forEach((details) => {
    details?.addEventListener("toggle", () => {
      details.dataset.userToggled = "true";
      details.classList.toggle("auto-collapsed", !details.open);
      window.requestAnimationFrame(refreshWorkflowTraceLayout);
    });
  });

  elements.messageInput.addEventListener("input", () => {
    const currentValue = elements.messageInput.value.trim();
    const matchedPreset = Object.entries(MESSAGE_PRESET_TEXT).find(([, value]) => value.trim() === currentValue)?.[0] || null;
    appState.messagePreset = matchedPreset || "custom";
    elements.messageInput.dataset.messagePreset = appState.messagePreset;
    updateMessagePresetSelection();
  });
}

function bindStartRuntimeHintUpdates() {
  const watchedElements = [
    elements.apiKey,
    elements.baseUrl,
    elements.apiProvider,
    elements.apiFormat,
    elements.agentModel,
    elements.subagentModel,
  ];
  for (const element of watchedElements) {
    element?.addEventListener("input", updateStartRuntimeHint);
    element?.addEventListener("change", updateStartRuntimeHint);
  }
}

function bindActionEvents() {
  elements.messagePresetBar?.addEventListener("click", (event) => {
    const presetButton = event.target instanceof Element ? event.target.closest("[data-preset]") : null;
    const presetKey = presetButton?.getAttribute("data-preset");
    if (!presetKey) {
      return;
    }
    event.preventDefault();
    applyMessagePreset(presetKey);
  });

  elements.messagePresetDefault?.addEventListener("click", (event) => {
    event.preventDefault();
    applyMessagePreset("default");
  });

  elements.messagePresetIconFaithful?.addEventListener("click", (event) => {
    event.preventDefault();
    applyMessagePreset("iconFaithful");
  });

  elements.messagePresetRelaxed?.addEventListener("click", (event) => {
    event.preventDefault();
    applyMessagePreset("relaxed");
  });

  elements.simpleModeToggle?.addEventListener("click", () => {
    setUiMode("simple");
  });

  elements.proModeToggle?.addEventListener("click", () => {
    setUiMode("pro");
  });

  elements.runtimeConfigSave.addEventListener("click", async () => {
    await saveRuntimeOverrides();
  });

  elements.newThread.addEventListener("click", async () => {
    stopSnapshotPolling();
    stopArtifactPolling();
    stopManualAdjustmentPolling();
    await createThread();
  });

  elements.refreshMonitor.addEventListener("click", async () => {
    try {
      await refreshSnapshot();
    } catch (error) {
      setStatus(error.message || "Monitor refresh failed");
    }
  });

  elements.refreshArtifacts.addEventListener("click", async () => {
    try {
      await refreshArtifactsForSelection({ force: true });
    } catch (error) {
      setStatus(error.message || "Artifact refresh failed");
    }
  });

  elements.resumeRun.addEventListener("click", async () => {
    await resumeRunFromArtifacts();
  });

  elements.exportSvgButton?.addEventListener("click", () => {
    const url = elements.exportSvgButton.dataset.downloadUrl || "";
    if (!url || elements.exportSvgButton.disabled) {
      return;
    }
    window.open(url.includes("download=true") ? url : `${url}${url.includes("?") ? "&" : "?"}download=true`, "_blank", "noopener,noreferrer");
  });

  elements.manualUseSelection.addEventListener("click", () => {
    const snapshot = appState.latestArtifactSnapshot;
    if (!hasUsableArtifactOutput(snapshot)) {
      return;
    }
    const nextBox = getOverlayBox(snapshot, appState.selectedOverlay);
    if (nextBox) {
      writeManualSelectionBox(nextBox);
      appState.manualSelectionShape = { kind: "box", points: [], bbox: nextBox };
      renderArtifactViews(snapshot);
    }
  });

  elements.manualSelectMode.addEventListener("click", () => {
    setManualSelectionMode("select");
    renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
    if (appState.latestArtifactSnapshot) {
      renderArtifactViews(appState.latestArtifactSnapshot);
    }
  });

  elements.manualDrawBox.addEventListener("click", () => {
    setManualSelectionMode("draw-box");
    renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
    if (appState.latestArtifactSnapshot) {
      renderArtifactViews(appState.latestArtifactSnapshot);
    }
  });

  elements.manualDrawFreeform.addEventListener("click", () => {
    setManualSelectionMode("draw-freeform");
    renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
    if (appState.latestArtifactSnapshot) {
      renderArtifactViews(appState.latestArtifactSnapshot);
    }
  });

  elements.manualConfirmSelection.addEventListener("click", () => {
    confirmManualSelection(appState.latestArtifactSnapshot);
    if (appState.latestArtifactSnapshot) {
      renderArtifactViews(appState.latestArtifactSnapshot);
    }
  });

  elements.manualClearSelection.addEventListener("click", () => {
    clearManualSelectionBox();
    if (appState.latestArtifactSnapshot) {
      renderArtifactViews(appState.latestArtifactSnapshot);
    }
  });

  elements.manualReferenceDrawBox.addEventListener("click", () => {
    setManualReferenceSelectionMode("draw-box");
    renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
    if (appState.latestArtifactSnapshot) {
      renderArtifactViews(appState.latestArtifactSnapshot);
    }
  });

  elements.manualReferenceDrawFreeform.addEventListener("click", () => {
    setManualReferenceSelectionMode("draw-freeform");
    renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
    if (appState.latestArtifactSnapshot) {
      renderArtifactViews(appState.latestArtifactSnapshot);
    }
  });

  elements.manualReferenceConfirmSelection.addEventListener("click", () => {
    confirmManualReferenceSelection(appState.latestArtifactSnapshot);
    if (appState.latestArtifactSnapshot) {
      renderArtifactViews(appState.latestArtifactSnapshot);
    }
  });

  elements.manualReferenceClearSelection.addEventListener("click", () => {
    clearManualReferenceSelection();
    if (appState.latestArtifactSnapshot) {
      renderArtifactViews(appState.latestArtifactSnapshot);
    }
  });

  elements.manualUploadButton.addEventListener("click", (event) => {
    event.stopPropagation();
    elements.manualUploadInput.click();
  });

  elements.manualUploadInput.addEventListener("change", async (event) => {
    const files = Array.from(event.target.files || []);
    try {
      await uploadManualReferenceFiles(files);
      renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
    } catch (error) {
      setStatus(error.message || "Reference upload failed");
      elements.manualUploadStatus.textContent = "Reference upload failed.";
    } finally {
      event.target.value = "";
    }
  });

  elements.manualPasteReferenceButton.addEventListener("click", async (event) => {
    event.stopPropagation();
    try {
      let file = null;
      if (navigator.clipboard?.read) {
        const clipboardItems = await navigator.clipboard.read();
        for (const item of clipboardItems) {
          const mimeType = item.types.find((type) => type.startsWith("image/"));
          if (!mimeType) {
            continue;
          }
          const blob = await item.getType(mimeType);
          file = new File([blob], `clipboard-reference.${mimeType.split("/")[1] || "png"}`, {
            type: mimeType,
            lastModified: Date.now(),
          });
          break;
        }
      }
      if (!file) {
        elements.manualReferencePastezone.focus();
        elements.manualUploadStatus.textContent = "Focus the paste zone and press Ctrl+V to paste a reference image.";
        return;
      }
      elements.manualUploadStatus.textContent = "Clipboard reference detected. Uploading...";
      await uploadManualReferenceFiles([file]);
      renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
    } catch (error) {
      elements.manualReferencePastezone.focus();
      elements.manualUploadStatus.textContent = "Clipboard read failed. Focus the paste zone and press Ctrl+V.";
      setStatus(error.message || "Clipboard reference upload failed");
    }
  });

  elements.manualReferenceCaptureButton.addEventListener("click", async (event) => {
    event.stopPropagation();
    try {
      elements.manualUploadStatus.textContent = "Capturing the selected input area...";
      await captureReferenceImageFromInput(appState.latestArtifactSnapshot);
      renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
    } catch (error) {
      elements.manualUploadStatus.textContent = error.message || "Failed to capture the input crop.";
      setStatus(error.message || "Reference capture failed");
    }
  });

  elements.manualUseReferenceImages.addEventListener("change", () => {
    if (!elements.manualUseReferenceImages.checked) {
      appState.manualCustomReferenceConfirmed = false;
    }
    renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
  });

  elements.manualApplyButton.addEventListener("click", async () => {
    await applyManualAdjustment();
  });

  elements.approveBtn.addEventListener("click", async () => {
    await resumeApproval("approve");
  });

  elements.rejectBtn.addEventListener("click", async () => {
    await resumeApproval("reject");
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopSnapshotPolling();
      stopArtifactPolling();
      stopManualAdjustmentPolling();
    } else {
      schedulePolling();
      if (appState.manualAdjustmentRequestInFlight) {
        startManualAdjustmentPolling();
      }
      void refreshSnapshot({ silent: true });
      void refreshArtifactsForSelection({ silent: true, force: true });
      window.requestAnimationFrame(refreshWorkflowTraceLayout);
    }
  });

  window.addEventListener("beforeunload", () => {
    stopSnapshotPolling();
    stopArtifactPolling();
    stopManualAdjustmentPolling();
  });

  window.addEventListener("resize", () => {
    window.requestAnimationFrame(syncRecentRunsHeight);
    window.requestAnimationFrame(refreshWorkflowTraceLayout);
  });

  window.addEventListener("desktop-history-change", () => {
    renderViews();
    window.requestAnimationFrame(syncRecentRunsHeight);
  });

  window.addEventListener("desktop-process-guide-change", () => {
    updateGuideContent();
  });

  document.addEventListener("click", (event) => {
    const zoomButton = event.target instanceof Element ? event.target.closest(".image-zoom-button") : null;
    if (zoomButton instanceof HTMLButtonElement) {
      event.preventDefault();
      openImageLightbox({
        src: zoomButton.dataset.zoomSrc || "",
        alt: zoomButton.dataset.zoomAlt || "",
        caption: zoomButton.dataset.zoomCaption || "",
      });
      return;
    }
    if (event.target === elements.imageLightboxBackdrop || event.target === elements.imageLightboxClose) {
      event.preventDefault();
      closeImageLightbox();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && elements.imageLightbox && !elements.imageLightbox.classList.contains("hidden")) {
      closeImageLightbox();
    }
  });
}

export async function initApp() {
  loadUiModePreference();
  bindFieldListeners();
  bindFormEvents();
  bindStartRuntimeHintUpdates();
  bindActionEvents();
  attachSettingsFieldHelp();
  window.setInterval(() => {
    updateWorkflowTraceTimers();
  }, 500);
  updateModeControls();

  try {
    setStatus("Creating thread...");
    await Promise.all([createThread(), loadFrontendDefaults(), loadFrontendHostInfo(), loadRuntimeOverrides()]);
    setManualSelectionMode("select");
    setManualReferenceSelectionMode("select");
    updateEffectiveValues();
    updateStartRuntimeHint();
    updateMessagePresetSelection();
    await refreshSnapshot({ silent: true });
    updateModeControls();
    setStatus("Ready");
  } catch {
    setStatus("Backend unavailable");
  }
}
