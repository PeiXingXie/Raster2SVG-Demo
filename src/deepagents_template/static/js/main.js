import { fetchJson } from "./api-client.js";
import { elements } from "./dom.js?v=refine-activity-feed-1";
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
} from "./form.js?v=run-start-state-boundary-1";
import { appState, resetRenderState, resetUiSelections } from "./state.js?v=run-start-state-boundary-1";
import { applySettingsLabelMappings } from "./settings-labels.js?v=desktop-history-jump-1";
import { renderApproval } from "./renderers/conversation.js?v=run-start-state-boundary-1";
import {
  clearArtifactPanel,
  createOverlayPreview,
  getLatestManualAdjustment,
  refreshWorkflowTraceLayout,
  renderArtifactFiles,
  renderManualRecentActivity,
  renderManualWorkflowTrace,
  renderArtifactSummary,
  renderWorkspaceArtifactLoadingState,
  updateWorkflowTraceTimers,
} from "./renderers/artifacts.js?v=refine-activity-feed-1";
import { renderRecentRuns, renderRunSummary, renderTimeline } from "./renderers/monitor.js?v=run-start-state-boundary-1";
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
    body: "Add a source image, complete the needed configuration, and describe the target.",
    notes: ["Paste or choose an image.", "Review or complete Settings if needed.", "Start the conversion."],
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

let desktopToastTimer = null;

function showDesktopToast(message) {
  if (!elements.desktopToast) {
    return;
  }
  window.clearTimeout(desktopToastTimer);
  elements.desktopToast.textContent = message;
  elements.desktopToast.classList.remove("hidden");
  desktopToastTimer = window.setTimeout(() => {
    elements.desktopToast.classList.add("hidden");
  }, 3200);
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
  "api-provider": "Compatibility protocol used to connect this app to the model service.",
  "api-format": "Request format used by that API protocol.",
  "agent-model": "Model used by the coordinator that plans and reviews the conversion.",
  "subagent-model": "Model used by worker agents for region and object generation.",
  "settings-workflow-mode": "How deeply the app refines the SVG after the first draft. Full Detail is slower but usually more accurate.",
  "settings-region-processing-mode": "Whether detected areas are processed one at a time or in parallel.",
  "settings-region-concurrency": "Maximum number of regions that may run at the same time.",
  "max-budget": "Total model-call budget allowed for one conversion run.",
  "max-repair-retry": "Maximum repair attempts for SVG or local path issues.",
  "max-retries": "Low-level retry count for transient API request failures.",
  "use-previous-response-id": "Reuse previous response state when the provider supports it.",
  "recognition-bbox-refine-mode": "Method used to improve detected object boxes before SVG generation.",
  "sam-enabled": "Enable SAM-assisted bbox refinement when available.",
  "sam-provider-mode": "Choose whether segmentation assistance runs on this computer or through a remote service.",
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

function applyFriendlySettingsLabels() {
  applySettingsLabelMappings(document);
}

const imageLightboxState = {
  scale: 1,
  translateX: 0,
  translateY: 0,
  isDragging: false,
  dragStartX: 0,
  dragStartY: 0,
  dragOriginX: 0,
  dragOriginY: 0,
  surface: null,
};

function updateImageLightboxTransform() {
  if (!imageLightboxState.surface) {
    return;
  }
  imageLightboxState.surface.style.transform =
    `translate(${imageLightboxState.translateX}px, ${imageLightboxState.translateY}px) scale(${imageLightboxState.scale})`;
  if (elements.imageLightboxZoomReset) {
    elements.imageLightboxZoomReset.textContent = `${Math.round(imageLightboxState.scale * 100)}%`;
  }
}

function resetImageLightboxZoom() {
  imageLightboxState.scale = 1;
  imageLightboxState.translateX = 0;
  imageLightboxState.translateY = 0;
  updateImageLightboxTransform();
}

function setImageLightboxScale(nextScale, anchor = null) {
  const previousScale = imageLightboxState.scale;
  const scale = Math.min(6, Math.max(0.25, nextScale));
  if (Math.abs(scale - previousScale) < 0.001) {
    return;
  }
  if (anchor && elements.imageLightboxStage) {
    const rect = elements.imageLightboxStage.getBoundingClientRect();
    const offsetX = anchor.clientX - rect.left - rect.width / 2 - imageLightboxState.translateX;
    const offsetY = anchor.clientY - rect.top - rect.height / 2 - imageLightboxState.translateY;
    const ratio = scale / previousScale;
    imageLightboxState.translateX -= offsetX * (ratio - 1);
    imageLightboxState.translateY -= offsetY * (ratio - 1);
  }
  imageLightboxState.scale = scale;
  if (scale <= 1) {
    imageLightboxState.translateX = 0;
    imageLightboxState.translateY = 0;
  }
  updateImageLightboxTransform();
}

function prepareImageLightboxSurface({ src, alt = "", crop = null }) {
  if (!elements.imageLightboxStage || !elements.imageLightboxImage) {
    return null;
  }
  const surface = document.createElement("div");
  surface.className = "image-lightbox-zoom-surface";
  elements.imageLightboxImage.remove();
  elements.imageLightboxImage.src = src;
  elements.imageLightboxImage.alt = alt || "Expanded preview";
  if (crop) {
    const frame = document.createElement("div");
    frame.className = "image-lightbox-crop-frame";
    const cropWidth = Math.max(crop.width, 1);
    const cropHeight = Math.max(crop.height, 1);
    const cropRatio = cropWidth / cropHeight;
    const maxFrameWidth = Math.max(260, Math.min(920, window.innerWidth - 140));
    const maxFrameHeight = Math.max(180, window.innerHeight - 220);
    let frameWidth = Math.min(maxFrameWidth, maxFrameHeight * cropRatio);
    let frameHeight = frameWidth / cropRatio;
    if (frameHeight > maxFrameHeight) {
      frameHeight = maxFrameHeight;
      frameWidth = frameHeight * cropRatio;
    }
    const cropScale = frameWidth / cropWidth;
    frame.style.width = `${Math.round(frameWidth)}px`;
    frame.style.height = `${Math.round(frameHeight)}px`;
    elements.imageLightboxImage.style.width = `${Math.max(crop.canvasWidth, 1) * cropScale}px`;
    elements.imageLightboxImage.style.height = `${Math.max(crop.canvasHeight, 1) * cropScale}px`;
    elements.imageLightboxImage.style.left = `${-crop.x * cropScale}px`;
    elements.imageLightboxImage.style.top = `${-crop.y * cropScale}px`;
    frame.appendChild(elements.imageLightboxImage);
    surface.appendChild(frame);
  } else {
    elements.imageLightboxImage.style.removeProperty("width");
    elements.imageLightboxImage.style.removeProperty("height");
    elements.imageLightboxImage.style.removeProperty("left");
    elements.imageLightboxImage.style.removeProperty("top");
    surface.appendChild(elements.imageLightboxImage);
  }
  elements.imageLightboxStage.replaceChildren(surface);
  imageLightboxState.surface = surface;
  resetImageLightboxZoom();
  return surface;
}

function openImageLightbox({ src, alt = "", caption = "", crop = null }) {
  if (!elements.imageLightbox || !elements.imageLightboxImage || !elements.imageLightboxStage) {
    return;
  }
  if (!src) {
    return;
  }
  prepareImageLightboxSurface({ src, alt, crop });
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
  elements.imageLightboxImage.style.removeProperty("width");
  elements.imageLightboxImage.style.removeProperty("height");
  elements.imageLightboxImage.style.removeProperty("left");
  elements.imageLightboxImage.style.removeProperty("top");
  elements.imageLightboxStage?.replaceChildren(elements.imageLightboxImage);
  imageLightboxState.surface = null;
  imageLightboxState.isDragging = false;
  if (elements.imageLightboxCaption) {
    elements.imageLightboxCaption.textContent = "";
  }
  document.body.classList.remove("lightbox-open");
}

function confirmDesktopAction({
  title = "Confirm Action",
  message = "",
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
} = {}) {
  return openDesktopActionDialog({
    title,
    message,
    confirmLabel,
    cancelLabel,
    mode: "confirm",
  });
}

function showDesktopErrorDialog({ title = "Run Failed", message = "" } = {}) {
  showDesktopToast(title);
  return openDesktopActionDialog({
    title,
    message,
    confirmLabel: "OK",
    cancelLabel: "Dismiss",
    mode: "notice",
  });
}

function promptDesktopText({
  title = "Enter Value",
  message = "",
  label = "Value",
  value = "",
  confirmLabel = "Save",
  cancelLabel = "Cancel",
} = {}) {
  return openDesktopActionDialog({
    title,
    message,
    confirmLabel,
    cancelLabel,
    inputLabel: label,
    inputValue: value,
    mode: "prompt",
  });
}

function openDesktopActionDialog({
  title,
  message,
  confirmLabel,
  cancelLabel,
  inputLabel = "",
  inputValue = "",
  mode = "confirm",
} = {}) {
  if (!elements.desktopConfirmModal) {
    if (mode === "prompt") {
      return Promise.resolve(window.prompt(message || title, inputValue));
    }
    if (mode === "notice") {
      window.alert(message || title);
      return Promise.resolve(true);
    }
    return Promise.resolve(window.confirm(message || title));
  }
  const isPrompt = mode === "prompt";
  const isNotice = mode === "notice";
  elements.desktopConfirmTitle.textContent = title;
  elements.desktopConfirmMessage.textContent = message;
  elements.desktopConfirmOk.textContent = confirmLabel;
  elements.desktopConfirmCancel.textContent = cancelLabel;
  elements.desktopConfirmCancel.classList.toggle("hidden", isNotice);
  elements.desktopConfirmOk.classList.toggle("danger-primary-btn", !isPrompt);
  if (elements.desktopConfirmInputWrap && elements.desktopConfirmInput) {
    elements.desktopConfirmInputWrap.classList.toggle("hidden", !isPrompt);
    elements.desktopConfirmInput.value = isPrompt ? inputValue : "";
    if (elements.desktopConfirmInputLabel) {
      elements.desktopConfirmInputLabel.textContent = inputLabel;
    }
  }
  elements.desktopConfirmModal.classList.remove("hidden");
  elements.desktopConfirmModal.setAttribute("aria-hidden", "false");
  document.body.classList.add("lightbox-open");

  return new Promise((resolve) => {
    const cleanup = (result) => {
      elements.desktopConfirmModal.classList.add("hidden");
      elements.desktopConfirmModal.setAttribute("aria-hidden", "true");
      document.body.classList.remove("lightbox-open");
      elements.desktopConfirmModal.removeEventListener("click", handleClick);
      document.removeEventListener("keydown", handleKeydown);
      elements.desktopConfirmOk.classList.add("danger-primary-btn");
      elements.desktopConfirmCancel.classList.remove("hidden");
      if (elements.desktopConfirmInputWrap && elements.desktopConfirmInput) {
        elements.desktopConfirmInputWrap.classList.add("hidden");
        elements.desktopConfirmInput.value = "";
      }
      resolve(result);
    };
    const handleClick = (event) => {
      const action = event.target instanceof Element ? event.target.closest("[data-confirm-action]")?.getAttribute("data-confirm-action") : null;
      if (action === "confirm") {
        cleanup(isPrompt ? elements.desktopConfirmInput?.value ?? "" : true);
      } else if (action === "cancel" && !isNotice) {
        cleanup(isPrompt ? null : false);
      }
    };
    const handleKeydown = (event) => {
      if (event.key === "Escape") {
        cleanup(isPrompt ? null : false);
      } else if (isPrompt && event.key === "Enter" && event.target === elements.desktopConfirmInput) {
        event.preventDefault();
        cleanup(elements.desktopConfirmInput.value);
      }
    };
    elements.desktopConfirmModal.addEventListener("click", handleClick);
    document.addEventListener("keydown", handleKeydown);
    if (isPrompt && elements.desktopConfirmInput) {
      elements.desktopConfirmInput.focus();
      elements.desktopConfirmInput.select();
    } else {
      elements.desktopConfirmOk.focus();
    }
  });
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
  const hasSelection = hasManualRefineTarget();
  const manualGoal = getManualGoalText();
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
      secondaryAction: { kind: "scroll", label: "Open Refine", target: "manual" },
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
      body: "Review the full output first. Use Refine only for small fixes.",
      step: journey.activeStep,
      primaryAction: { kind: "scroll", label: "Inspect Output", target: "output" },
      secondaryAction: { kind: "scroll", label: "Start Refine", target: "manual" },
    },
    result_ready_needs_local_refine: {
      title: "Ready to refine.",
      body: "Inspect the output, then select the area that still needs cleanup.",
      step: journey.activeStep,
      primaryAction: { kind: "scroll", label: "Start Refine", target: "manual" },
      secondaryAction: { kind: "scroll", label: "Inspect Output", target: "output" },
    },
    manual_goal_missing: {
      title: "Target selected.",
      body: "Describe the refinement goal next.",
      step: "manual",
      primaryAction: { kind: "scroll", label: "Describe Goal", target: "manual" },
      secondaryAction: { kind: "scroll", label: "Inspect Selected Output", target: "output" },
    },
    manual_ready_to_apply: {
      title: "Ready to refine.",
      body: "Apply now, or add a reference image only if needed.",
      step: "manual",
      primaryAction: { kind: "manual-apply", label: "Apply Refinement" },
      secondaryAction: { kind: "scroll", label: "Add References", target: "manual" },
    },
    manual_result_ready: {
      title: "Refinement applied.",
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
  const readiness = getManualReadinessState();
  if (readiness.canOpenRefine) {
    if (readiness.hasManualResult) {
      return {
        title: "Refined result ready.",
        body: "Compare with the base frame, refine again, or export.",
      };
    }
    if (!readiness.hasTarget) {
      return {
        title: "Select a target.",
        body: "Click an overlay or draw an area on the output preview.",
      };
    }
    if (!readiness.hasGoal) {
      return {
        title: "Describe the change.",
        body: "Keep the refinement goal specific to the selected target.",
      };
    }
    return {
      title: "Ready to refine.",
      body: "Apply refinement now, or add a reference image only if needed.",
    };
  }
  const contentByState = {
    empty: {
      title: "Refine is locked.",
      body: "Run the conversion first. Refine unlocks after the main flow finishes with a usable output.",
    },
    image_ready_needs_prompt: {
      title: "Refine is locked.",
      body: "Add the conversion goal and start the run first.",
    },
    ready_to_start: {
      title: "Refine is locked.",
      body: "Start the conversion first; refine improves an existing result.",
    },
    running_layout_analysis: {
      title: "Refine is locked.",
      body: "Waiting for the first usable output frame.",
    },
    running_region_generation: {
      title: "Refine is locked.",
      body: "Preparing editable regions. Refine unlocks when output appears.",
    },
    running_repair: {
      title: "Refine is locked.",
      body: "Auto-repair is running. Refine after this pass if anything remains.",
    },
    running_trace: {
      title: "Refine is locked.",
      body: "Follow the trace until a visible output frame is ready.",
    },
    paused_resume_available: {
      title: "Refine may be available.",
      body: "If output is visible, select a target. Otherwise resume the conversion.",
    },
    failed_recoverable: {
      title: "Check output availability.",
      body: "If output exists, select a target to refine. Otherwise inspect the trace.",
    },
    result_ready_review_overall: {
      title: "Select a target.",
      body: "Click an overlay or draw an area on the output preview.",
    },
    result_ready_needs_local_refine: {
      title: "Select a target.",
      body: "Choose the area that needs work, then describe the change.",
    },
    manual_goal_missing: {
      title: "Describe the change.",
      body: "Keep the refinement goal specific to the selected target.",
    },
    manual_ready_to_apply: {
      title: "Ready to refine.",
      body: "Apply refinement now, or add a reference image only if needed.",
    },
    manual_result_ready: {
      title: "Refined result ready.",
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
  if (action.target === "trace") {
    document.querySelector('[data-workspace-sidebar-tab="trace"]')?.click();
  }
  if (action.target === "manual") {
    document.querySelector('[data-workspace-sidebar-tab="refine"]')?.click();
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

function isMainFlowComplete(snapshot = appState.latestArtifactSnapshot) {
  const runStatus = String(snapshot?.status || "").toLowerCase();
  if (!runStatus) {
    return Boolean(snapshot?.available);
  }
  return !["queued", "running"].includes(runStatus);
}

function getManualGoalText() {
  return elements.manualUserIntroduction?.value?.trim()
    || elements.manualTargetDescription?.value?.trim()
    || "";
}

function hasManualRefineTarget() {
  return Boolean(
    appState.manualConfirmedTarget?.selectionBox
    || appState.manualSelectionBox
    || appState.selectedOverlay?.regionId
    || appState.selectedOverlay?.objectId
  );
}

function refreshManualRefineReadiness(snapshot = appState.latestArtifactSnapshot) {
  renderManualAdjustmentPanel(snapshot);
  updateGuideContent();
}

function getRefineReadinessState(snapshot = appState.latestArtifactSnapshot) {
  const hasOutput = hasUsableArtifactOutput(snapshot);
  const mainFlowDone = isMainFlowComplete(snapshot);
  const hasTarget = hasManualRefineTarget();
  const hasGoal = Boolean(getManualGoalText());
  const hasManualResult = Boolean(getLatestManualAdjustment(snapshot));
  const canOpenRefine = Boolean(mainFlowDone && hasOutput);
  const readyToApply = Boolean(canOpenRefine && hasTarget && hasGoal);
  const title = canOpenRefine
    ? "Open local refinement tools."
    : mainFlowDone
      ? "Refine unlocks when the finished run has a usable output."
      : "Refine unlocks after the main flow finishes.";
  return {
    mainFlowDone,
    hasOutput,
    hasTarget,
    hasGoal,
    hasManualResult,
    canOpenRefine,
    canSelectTarget: canOpenRefine,
    canApply: readyToApply,
    readyToApply,
    label: !canOpenRefine ? "Locked" : readyToApply ? "Ready" : "Available",
    title,
  };
}

function getManualReadinessState(snapshot = appState.latestArtifactSnapshot) {
  return getRefineReadinessState(snapshot);
}

function syncRefineActionButton(button, readiness, { readyLabel = "Open Refine", lockedLabel = "Locked", updateLabel = false } = {}) {
  if (!(button instanceof HTMLButtonElement)) {
    return;
  }
  const enabled = Boolean(readiness.canOpenRefine);
  button.disabled = !enabled;
  button.classList.toggle("is-ready", enabled);
  button.title = readiness.title;
  button.setAttribute("aria-disabled", enabled ? "false" : "true");
  if (updateLabel) {
    button.textContent = enabled ? readyLabel : lockedLabel;
  }
}

function updateSimpleArtifactsReadiness(snapshot) {
  const hasInput = Boolean(snapshot?.previews?.input_image_url);
  const hasBbox = Boolean(snapshot?.regions?.length);
  const hasOutput = hasUsableArtifactOutput(snapshot);
  const localReady = getRefineReadinessState(snapshot).canOpenRefine;
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
    label: localReady ? "Refine ready" : "Refine locked",
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
      next = "Review the full output before refining.";
      break;
    case "result_ready_needs_local_refine":
    case "manual_goal_missing":
    case "manual_ready_to_apply":
      next = "Select the target, describe the refinement goal, then apply.";
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
  const readiness = getRefineReadinessState(snapshot);
  const refineReady = readiness.canOpenRefine;
  document.body.dataset.refineLocked = refineReady ? "false" : "true";
  const refineToggle = document.getElementById("desktop-refine-toggle");
  syncRefineActionButton(refineToggle, readiness);
  const traceRefineButton = document.querySelector(".trace-refine-guide-btn");
  syncRefineActionButton(traceRefineButton, readiness, { updateLabel: true });
  if (elements.refineStatus) {
    elements.refineStatus.textContent = readiness.label;
    elements.refineStatus.title = readiness.title;
    elements.refineStatus.classList.toggle("is-ready", refineReady);
  }
  if (
    !refineReady
    && document.body.dataset.workspaceSidebar === "expanded"
    && document.body.dataset.workspaceSidebarActivePanel === "refine"
  ) {
    document.querySelector('[data-workspace-sidebar-tab="trace"]')?.click();
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

  const { canOpenRefine, hasTarget, hasGoal, readyToApply } = getRefineReadinessState(snapshot);

  [elements.manualEntryOutput, elements.manualEntryTarget, elements.manualEntryGoal].forEach((chip) => {
    chip?.classList.add("hidden");
  });
  setReadinessChip(elements.manualEntryReady, {
    label: !canOpenRefine ? "Locked" : readyToApply ? "Ready" : "Available",
    ready: canOpenRefine,
    active: readyToApply || !canOpenRefine,
  });

  if (elements.manualEntryText) {
    if (!canOpenRefine) {
      elements.manualEntryText.textContent = "Refine is locked until the main flow finishes with a usable output.";
    } else if (!hasTarget) {
      elements.manualEntryText.textContent = "Refine is available. Select a target to continue.";
    } else if (!hasGoal) {
      elements.manualEntryText.textContent = "Target is set. Describe the refinement goal.";
    } else {
      elements.manualEntryText.textContent = "Ready to apply refinement.";
    }
  }
  if (elements.manualSubmitStatus && !appState.manualAdjustmentRequestInFlight) {
    if (!canOpenRefine) {
      elements.manualSubmitStatus.textContent = "Refine unlocks after the main flow finishes with a usable output.";
    } else if (!hasTarget) {
      elements.manualSubmitStatus.textContent = "Select a target before applying refinement.";
    } else if (!hasGoal) {
      elements.manualSubmitStatus.textContent = "Describe the refinement goal before applying.";
    } else {
      elements.manualSubmitStatus.textContent = "Ready to apply refinement.";
    }
  }

  const collapseWorkflow = !canOpenRefine;
  const collapseEditCore = !canOpenRefine;
  elements.manualWorkflowBar?.classList.toggle("manual-section-collapsed", collapseWorkflow);
  elements.manualEditCore?.classList.toggle("manual-section-collapsed", collapseEditCore);

  if (elements.manualReferencePanel && !elements.manualReferencePanel.dataset.userToggled) {
    const nextOpen = Boolean(appState.manualReferenceAutoOpenedForTarget);
    if (elements.manualReferencePanel.open !== nextOpen) {
      elements.manualReferencePanel.dataset.programmaticToggle = "true";
      elements.manualReferencePanel.open = nextOpen;
    }
  }
  elements.manualReferencePanel?.classList.toggle("auto-collapsed", !elements.manualReferencePanel.open);

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

function isDeletedRun(run) {
  if (!run) {
    return false;
  }
  return Boolean(
    (run.run_id && appState.deletedRunIds.has(run.run_id))
    || (run.artifact_dir && appState.deletedRunArtifactDirs.has(run.artifact_dir))
  );
}

function filterDeletedRunsFromSnapshot(snapshot) {
  if (!snapshot) {
    return snapshot;
  }
  const currentRun = isDeletedRun(snapshot.current_run) ? null : snapshot.current_run;
  return {
    ...snapshot,
    current_run: currentRun,
    recent_runs: (snapshot.recent_runs || []).filter((run) => !isDeletedRun(run)),
    status: currentRun ? snapshot.status : (snapshot.approval_request ? "needs_approval" : "completed"),
  };
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

function removeRunFromSnapshot(runId, artifactDir = null) {
  if (!appState.snapshot || !runId) {
    return;
  }
  appState.deletedRunIds.add(runId);
  if (artifactDir) {
    appState.deletedRunArtifactDirs.add(artifactDir);
  }
  const matchesDeletedRun = (run) => {
    if (!run) {
      return false;
    }
    if (run.run_id === runId) {
      return true;
    }
    return Boolean(artifactDir && run.artifact_dir === artifactDir);
  };
  const nextSnapshot = {
    ...appState.snapshot,
    current_run: matchesDeletedRun(appState.snapshot.current_run) ? null : appState.snapshot.current_run,
    recent_runs: (appState.snapshot.recent_runs || []).filter((run) => !matchesDeletedRun(run)),
  };
  if (matchesDeletedRun(appState.snapshot.current_run)) {
    nextSnapshot.status = nextSnapshot.approval_request ? "needs_approval" : "completed";
  }
  appState.snapshot = nextSnapshot;
  appState.artifactCache.delete(runId);
  if (artifactDir) {
    for (const [cacheKey, cached] of appState.artifactCache.entries()) {
      if (cached?.snapshot?.artifact_dir === artifactDir) {
        appState.artifactCache.delete(cacheKey);
      }
    }
  }
  if (matchesDeletedRun(appState.latestArtifactSnapshot)) {
    appState.latestArtifactSnapshot = null;
  }
  if (appState.selectedRunId === runId || matchesDeletedRun(getSelectedRun(nextSnapshot))) {
    appState.selectedRunId = null;
  }
}

function updateRunProjectNameInSnapshot(updatedRun) {
  if (!updatedRun?.run_id || !appState.snapshot) {
    return;
  }
  const matchesUpdatedRun = (run) => run && (
    run.run_id === updatedRun.run_id
    || (updatedRun.artifact_dir && run.artifact_dir === updatedRun.artifact_dir)
  );
  const mergeRun = (run) => (matchesUpdatedRun(run) ? { ...run, ...updatedRun } : run);
  appState.snapshot = {
    ...appState.snapshot,
    current_run: mergeRun(appState.snapshot.current_run),
    recent_runs: (appState.snapshot.recent_runs || []).map(mergeRun),
  };
  if (matchesUpdatedRun(appState.latestArtifactSnapshot)) {
    appState.latestArtifactSnapshot = {
      ...appState.latestArtifactSnapshot,
      project_name: updatedRun.project_name,
      updated_at: updatedRun.updated_at || appState.latestArtifactSnapshot.updated_at,
    };
  }
}

async function renameRunProject(run) {
  if (!appState.threadId || !run?.run_id) {
    return;
  }
  const currentName = run.project_name || "Untitled project";
  const nextName = await promptDesktopText({
    title: "Rename Project",
    message: "Update the display name for this saved project.",
    label: "Project name",
    value: currentName,
    confirmLabel: "Rename",
    cancelLabel: "Cancel",
  });
  if (nextName == null) {
    return;
  }
  const normalizedName = nextName.trim().replace(/\s+/g, " ");
  if (!normalizedName || normalizedName === currentName) {
    return;
  }
  setStatus("Renaming project...");
  try {
    const updatedRun = await fetchJson(`/threads/${encodeURIComponent(appState.threadId)}/runs/${encodeURIComponent(run.run_id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_name: normalizedName }),
    });
    updateRunProjectNameInSnapshot(updatedRun);
    renderState.recentRunsSig = null;
    renderViews();
    const successMessage = `Renamed to "${normalizedName}"`;
    setStatus(successMessage);
    showDesktopToast(successMessage);
    await refreshSnapshot({ silent: true });
  } catch (error) {
    setStatus(error.message || "Rename failed");
  }
}

async function deleteRunProject(run) {
  if (!appState.threadId || !run?.run_id) {
    return;
  }
  const projectName = run.project_name || "Untitled project";
  const confirmed = await confirmDesktopAction({
    title: "Delete Project",
    message: `Delete "${projectName}" and its saved artifacts? This cannot be undone.`,
    confirmLabel: "Delete",
    cancelLabel: "Cancel",
  });
  if (!confirmed) {
    return;
  }
  setStatus("Deleting project...");
  try {
    const artifactQuery = run.artifact_dir ? `?artifact_dir=${encodeURIComponent(run.artifact_dir)}` : "";
    const deleted = await fetchJson(`/threads/${encodeURIComponent(appState.threadId)}/runs/${encodeURIComponent(run.run_id)}${artifactQuery}`, {
      method: "DELETE",
    });
    const deletedRunId = deleted.run_id || run.run_id;
    removeRunFromSnapshot(deletedRunId, deleted.artifact_dir || run.artifact_dir || null);
    const remainingRuns = getRunList(appState.snapshot);
    const pageSize = appState.desktopHistoryPageSize || 6;
    const maxPage = Math.max(1, Math.ceil(remainingRuns.length / pageSize));
    appState.desktopHistoryPage = Math.min(appState.desktopHistoryPage || 1, maxPage);
    renderState.recentRunsSig = null;
    renderViews();
    const deletedName = deleted.project_name || projectName;
    const successMessage = `Deleted "${deletedName}"`;
    setStatus(successMessage);
    showDesktopToast(successMessage);
    await refreshSnapshot({ silent: true });
    await refreshArtifactsForSelection({ silent: true, force: true });
  } catch (error) {
    setStatus(error.message || "Delete failed");
  }
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
        loading: !appState.snapshot && appState.snapshotRequestInFlight,
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
        onRenameRun: renameRunProject,
        onDeleteRun: deleteRunProject,
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
  if (!getRefineReadinessState(snapshot).canSelectTarget) {
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
  if (!appState.manualReferenceAutoOpenedForTarget && elements.manualReferencePanel) {
    appState.manualReferenceAutoOpenedForTarget = true;
    setManualReferenceMode("default", { render: false });
    elements.manualReferencePanel.dataset.programmaticToggle = "true";
    elements.manualReferencePanel.open = true;
    elements.manualReferencePanel.classList.remove("auto-collapsed");
  }
}

function confirmManualReferenceSelection(snapshot) {
  const hasCustomPaths = getManualReferencePaths().length > 0;
  const hasDrawnSelection = Boolean(getRefineReadinessState(snapshot).canSelectTarget && appState.manualReferenceSelectionShape?.bbox);
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
  appState.manualReferenceMode = "capture";
  elements.manualUseReferenceImages.checked = true;
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

function getManualReferenceMode() {
  return appState.manualReferenceMode || (
    !elements.manualUseReferenceImages.checked
      ? "none"
      : elements.manualIncludeDefaultCrop.checked
        ? "default"
        : "add"
  );
}

function getManualReferenceContainer() {
  return elements.manualReferencePanel?.querySelector(".manual-reference-upload") || null;
}

function updateManualReferenceModeControls() {
  const mode = getManualReferenceMode();
  const uploadPanelOpen = Boolean(elements.manualReferenceUploadPanel?.open);
  const uploadCount = appState.manualReferenceUploads.length;
  const container = getManualReferenceContainer();
  if (container) {
    container.dataset.referenceMode = mode;
  }
  elements.manualReferenceUseDefault?.classList.toggle("is-active", mode === "default");
  elements.manualReferenceCaptureRef?.classList.toggle("is-active", mode === "capture");
  elements.manualReferenceAddImage?.classList.toggle("is-active", mode === "add");
  elements.manualReferenceAddImage?.classList.toggle("is-upload-active", uploadPanelOpen);
  elements.manualReferenceNoRef?.classList.toggle("is-active", mode === "none");
  elements.manualReferenceAddImage?.setAttribute("aria-expanded", uploadPanelOpen ? "true" : "false");
  if (elements.manualUploadStatus) {
    elements.manualUploadStatus.textContent = uploadCount
      ? `${uploadCount} image${uploadCount === 1 ? "" : "s"}`
      : uploadPanelOpen
        ? "Ready"
        : "No images";
  }
}

function setManualReferenceMode(mode, { openUpload = false, render = true } = {}) {
  appState.manualReferenceMode = mode;
  if (mode === "none") {
    elements.manualUseReferenceImages.checked = false;
    elements.manualIncludeDefaultCrop.checked = false;
    appState.manualCustomReferenceConfirmed = false;
    appState.manualConfirmedReferenceSelection = null;
    if (elements.manualReferenceUploadPanel) {
      elements.manualReferenceUploadPanel.open = false;
    }
  } else if (mode === "add") {
    elements.manualUseReferenceImages.checked = true;
    elements.manualIncludeDefaultCrop.checked = false;
    appState.manualCustomReferenceConfirmed = appState.manualReferenceUploads.length > 0;
    appState.manualConfirmedReferenceSelection = null;
    if (elements.manualReferenceUploadPanel) {
      elements.manualReferenceUploadPanel.open = true;
    }
  } else if (mode === "capture") {
    elements.manualUseReferenceImages.checked = true;
    elements.manualIncludeDefaultCrop.checked = !appState.manualConfirmedReferenceSelection?.selectionBox;
    appState.manualCustomReferenceConfirmed = Boolean(appState.manualConfirmedReferenceSelection?.selectionBox);
    if (elements.manualReferenceUploadPanel) {
      elements.manualReferenceUploadPanel.open = false;
    }
  } else {
    elements.manualUseReferenceImages.checked = true;
    elements.manualIncludeDefaultCrop.checked = true;
    appState.manualCustomReferenceConfirmed = false;
    appState.manualConfirmedReferenceSelection = null;
    if (elements.manualReferenceUploadPanel) {
      elements.manualReferenceUploadPanel.open = false;
    }
  }
  updateManualReferenceModeControls();
  if (render) {
    renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
  }
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
    "Focus here, then paste an image. You can also choose a local image file.";
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
    elements.manualReferencePreviewMeta.textContent = `${inlinePathCount} reference path(s) added. Confirm Area to replace the default crop.`;
    return;
  }
  if (!snapshot?.previews?.input_image_url) {
    elements.manualReferencePreviewMeta.textContent = "Reference thumbnails appear after artifacts load.";
  }
}

function renderManualReferenceUploads() {
  elements.manualReferencePreview.innerHTML = "";
  renderManualReferenceSurface(appState.latestArtifactSnapshot);
  if (getManualReferenceMode() !== "add" || !appState.manualReferenceUploads.length) {
    elements.manualReferencePreview.className = "hidden";
    elements.manualReferencePreview.textContent = "";
    updateManualReferenceModeControls();
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
  updateManualReferenceModeControls();
}

function renderConfirmedTargetCard(activeFrame) {
  const target = appState.manualConfirmedTarget;
  if (!target) {
    elements.manualConfirmedTarget.className = "hidden";
    elements.manualConfirmedTarget.textContent = "Set a target to pin the region, bbox, and base frame.";
    return;
  }
  const referenceMode = getManualReferenceMode();
  const addImagePaths = getManualReferencePaths();
  const hasCapturedReference = Boolean(appState.manualConfirmedReferenceSelection?.selectionBox);
  const referenceSourceLabel = referenceMode === "none"
    ? "none"
    : referenceMode === "add"
      ? addImagePaths.length
        ? `custom uploads (${addImagePaths.length})`
        : "custom upload pending"
      : referenceMode === "capture"
        ? hasCapturedReference
          ? "confirmed input crop"
          : "input crop pending"
        : "default crop";
  const isDesktop = document.body.classList.contains("desktop-body");
  const isSimpleMode = document.body?.dataset?.uiMode === "simple";
  elements.manualConfirmedTarget.className = isDesktop
    ? "manual-confirmed-target manual-target-confirmed-preview"
    : "manual-confirmed-target";
  if (isDesktop) {
    elements.manualConfirmedTarget.replaceChildren();
  } else if (isSimpleMode) {
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

  const appendFocusPreview = (label, imageUrl, kind = "reference") => {
    if (!target.selectionBox || !imageUrl || !canvasWidth || !canvasHeight) {
      return;
    }
    const { x, y, width, height } = target.selectionBox;
    const thumb = document.createElement("div");
    thumb.className = `manual-selection-thumb manual-selection-thumb--${kind}`;
    thumb.dataset.previewKind = kind;
    thumb.innerHTML = `
      <div class="manual-selection-thumb-stage"></div>
      <div class="manual-reference-thumb-footer">
        <div class="manual-reference-caption">${label}</div>
        <button
          class="image-zoom-button"
          type="button"
          data-zoom-src="${imageUrl}"
          data-zoom-alt="${label}"
          data-zoom-caption="${label}"
          data-zoom-crop="true"
          data-zoom-crop-x="${x}"
          data-zoom-crop-y="${y}"
          data-zoom-crop-width="${width}"
          data-zoom-crop-height="${height}"
          data-zoom-canvas-width="${canvasWidth}"
          data-zoom-canvas-height="${canvasHeight}"
        >
          Zoom
        </button>
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
    activeFrame?.preview_url || snapshot?.previews?.output_svg_url || snapshot?.previews?.output_png_url || null,
    "output"
  );
  if (referenceMode === "add" && appState.manualReferenceUploads.length) {
    for (const upload of appState.manualReferenceUploads.slice(0, 3)) {
      if (!upload.previewObjectUrl) {
        continue;
      }
      const thumb = document.createElement("div");
      thumb.className = "manual-selection-thumb manual-selection-thumb--reference";
      thumb.dataset.previewKind = "reference";
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
  } else if (referenceMode === "capture" && hasCapturedReference) {
    appendFocusPreview("Confirmed reference crop", snapshot?.previews?.input_image_url || null, "reference");
  } else if (referenceMode === "default" || (referenceMode === "capture" && !hasCapturedReference)) {
    appendFocusPreview("Default source crop", snapshot?.previews?.input_image_url || null, "reference");
  }
  if (previewGrid.childElementCount > 0) {
    elements.manualConfirmedTarget.appendChild(previewGrid);
  } else if (isDesktop) {
    elements.manualConfirmedTarget.className = "hidden";
  }
}

function renderConfirmedReferenceSelection(snapshot) {
  if (getManualReferenceMode() !== "capture") {
    return;
  }
  const referenceSelection = appState.manualConfirmedReferenceSelection;
  const draftSelection = appState.manualReferenceSelectionShape;
  const activeSelection = referenceSelection || draftSelection;
  const customPathCount = getManualReferencePaths().length;
  if (!activeSelection?.bbox) {
    elements.manualReferenceSelectionSummary.textContent = appState.manualCustomReferenceConfirmed && customPathCount
      ? `Confirmed ${customPathCount} custom reference path(s). Default crop will be replaced.`
      : "Draw a reference area on Input, then confirm it as the reference crop.";
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
        data-zoom-crop="true"
        data-zoom-crop-x="${bbox.x}"
        data-zoom-crop-y="${bbox.y}"
        data-zoom-crop-width="${bbox.width}"
        data-zoom-crop-height="${bbox.height}"
        data-zoom-canvas-width="${canvasWidth}"
        data-zoom-canvas-height="${canvasHeight}"
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
  if (document.body.classList.contains("desktop-body")) {
    elements.manualAdjustmentResult.className = "hidden";
    elements.manualAdjustmentResult.replaceChildren();
    return;
  }
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
    <div class="compare-title">Refined Result</div>
    <div class="structure-meta">${latestAdjustment.adjustment_id || ""}</div>
  `;
  elements.manualAdjustmentResult.className = "manual-adjustment-result";
  elements.manualAdjustmentResult.replaceChildren(heading, resultGrid);
}

function renderManualRecentActivityPanel(snapshot) {
  if (!elements.manualRecentActivity) {
    return;
  }
  const selectedManualAdjustment = getSelectedManualAdjustment(snapshot);
  const trace = selectedManualAdjustment?.workflow_trace || snapshot?.manual_workflow_trace || null;
  const hasTraceNodes = Array.isArray(trace?.nodes) && trace.nodes.length > 0;
  const shouldShow = Boolean(appState.manualAdjustmentRequestInFlight || selectedManualAdjustment || hasTraceNodes);
  if (!shouldShow) {
    elements.manualRecentActivity.className = "manual-recent-activity hidden";
    elements.manualRecentActivity.replaceChildren();
    return;
  }
  elements.manualRecentActivity.className = "manual-recent-activity";
  renderManualRecentActivity(elements.manualRecentActivity, { manual_workflow_trace: trace });
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
  const readiness = getRefineReadinessState(snapshot);
  const canConfigureReferences = Boolean(readiness.canOpenRefine);
  const referenceImagesEnabled = Boolean(canConfigureReferences && elements.manualUseReferenceImages.checked);
  elements.manualApplyButton.disabled = !readiness.canApply || appState.manualAdjustmentRequestInFlight;
  elements.manualConfirmSelection.disabled = !readiness.canSelectTarget;
  if (elements.manualReferenceUseDefault) {
    elements.manualReferenceUseDefault.disabled = !canConfigureReferences;
  }
  if (elements.manualReferenceCaptureRef) {
    elements.manualReferenceCaptureRef.disabled = !canConfigureReferences;
  }
  if (elements.manualReferenceAddImage) {
    elements.manualReferenceAddImage.disabled = !canConfigureReferences;
  }
  if (elements.manualReferenceNoRef) {
    elements.manualReferenceNoRef.disabled = !canConfigureReferences;
  }
  elements.manualReferenceConfirmSelection.disabled = !readiness.canSelectTarget;
  elements.manualReferenceClearSelection.disabled = !readiness.canSelectTarget;
  elements.manualReferencePaths.disabled = !referenceImagesEnabled;
  elements.manualPasteReferenceButton.disabled = !referenceImagesEnabled;
  if (elements.manualReferenceCaptureButton) {
    elements.manualReferenceCaptureButton.disabled =
    !referenceImagesEnabled || !snapshot?.previews?.input_image_url;
  }
  elements.manualReferencePastezone.tabIndex = referenceImagesEnabled ? 0 : -1;
  elements.manualUploadButton.disabled = !referenceImagesEnabled;
  elements.manualUploadInput.disabled = !referenceImagesEnabled;
  elements.manualIncludeDefaultCrop.disabled = !referenceImagesEnabled;
  updateManualReferenceModeControls();
  renderManualRecentActivityPanel(snapshot);
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
  appState.manualReferenceMode = "add";
  elements.manualUseReferenceImages.checked = true;
  elements.manualIncludeDefaultCrop.checked = false;
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
  if (!getRefineReadinessState(snapshot).canOpenRefine || !snapshot?.previews?.input_image_url) {
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
  appState.manualReferenceMode = "add";
  elements.manualUseReferenceImages.checked = true;
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

  const referenceMode = getManualReferenceMode();
  const useReferenceImages = referenceMode !== "none";
  const addImageReferencePaths = referenceMode === "add" ? getManualReferencePaths() : [];
  const captureReferenceBox = referenceMode === "capture"
    ? (appState.manualConfirmedReferenceSelection?.selectionBox || null)
    : null;
  const payload = {
    thread_id: appState.threadId,
    run_id: snapshot.run_id,
    base_frame_id: confirmedTarget?.baseFrameId || activeFrame?.frame_id || null,
    mode: elements.manualMode.value || "worker",
    target_object_ids: targetObjectIds,
    target_region_id: targetRegionId,
    target_description: elements.manualTargetDescription?.value?.trim() || null,
    user_introduction: elements.manualUserIntroduction?.value?.trim() || getManualGoalText(),
    use_reference_images: useReferenceImages,
    reference_image_paths: useReferenceImages ? addImageReferencePaths : [],
    include_default_crop: useReferenceImages && (referenceMode === "default" || (referenceMode === "capture" && !captureReferenceBox)),
    include_no_image: !useReferenceImages,
  };
  const selectionBox = confirmedTarget?.selectionBox || readManualSelectionBoxFromInputs() || appState.manualSelectionBox;
  if (selectionBox) {
    payload.selection_bbox = selectionBox;
  }
  if (confirmedTarget?.selectionScope === "bbox_fragment" && !targetObjectIds.length) {
    payload.target_region_id = null;
  }
  if (captureReferenceBox && useReferenceImages) {
    payload.reference_selection_bbox = captureReferenceBox;
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
  const readiness = getRefineReadinessState(snapshot);
  if (!appState.threadId || !readiness.canOpenRefine || !snapshot?.run_id) {
    setStatus(readiness.title || "Output is not ready for refinement.");
    if (elements.manualSubmitStatus) {
      elements.manualSubmitStatus.textContent = readiness.title || "Refine is locked.";
    }
    return;
  }
  if (!readiness.hasTarget) {
    setStatus("Please select a refinement target.");
    elements.manualSubmitStatus.textContent = "Select a target before applying refinement.";
    return;
  }
  const goal = getManualGoalText();
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
  renderManualRecentActivityPanel(snapshot);
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
    elements.manualApplyButton.disabled = !getRefineReadinessState(appState.latestArtifactSnapshot).canApply;
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
    appState.outputFrameFollowMode = "auto";
    appState.outputFrameAutoFollow = true;
    appState.selectedOutputFrameId = null;
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
  if (previousRunId !== nextRunId) {
    const selectedRun = getSelectedRun();
    renderWorkspaceArtifactLoadingState(selectedRun);
    updateWorkspaceActionAvailability({ status: selectedRun?.status || null, available: false });
  }
  void refreshArtifactsForSelection({ silent: true, force: true });
  schedulePolling();
}

function buildFailureDialogMessage(run) {
  const diagnostic = run?.failure_diagnostic || {};
  const lines = [];
  const summary = diagnostic.summary || run?.error || "The conversion pipeline failed.";
  lines.push(summary);
  if (diagnostic.root_cause_type || diagnostic.root_cause_message) {
    lines.push(`${diagnostic.root_cause_type || "Root cause"}: ${diagnostic.root_cause_message || "-"}`);
  } else if (diagnostic.error_type || diagnostic.error_message) {
    lines.push(`${diagnostic.error_type || "Error"}: ${diagnostic.error_message || "-"}`);
  }
  const renderLog = (diagnostic.artifact_hints || []).find((item) => item.kind === "render-error");
  if (renderLog?.relative_path) {
    lines.push(`Render error log: ${renderLog.relative_path}`);
  }
  return lines.filter(Boolean).join("\n\n");
}

function maybeShowRunFailureDialog(snapshot) {
  const run = snapshot?.current_run;
  if (!run || run.status !== "failed" || !isLiveRunSelected(snapshot)) {
    return;
  }
  const key = `${run.run_id || "unknown"}:${run.updated_at || run.error || "failed"}`;
  if (appState.dismissedFailureDialogs.has(key)) {
    return;
  }
  appState.dismissedFailureDialogs.add(key);
  const diagnostic = run.failure_diagnostic || {};
  const isRenderFailure = diagnostic.error_type === "SvgPreviewRenderError"
    || diagnostic.root_cause_type === "SvgPreviewRenderError"
    || String(diagnostic.error_message || run.error || "").includes("SVG preview render failed");
  void showDesktopErrorDialog({
    title: isRenderFailure ? "SVG Preview Render Failed" : "Conversion Failed",
    message: buildFailureDialogMessage(run),
  });
}

function applySnapshot(snapshot) {
  const filteredSnapshot = filterDeletedRunsFromSnapshot(snapshot);
  appState.snapshot = filteredSnapshot;
  appState.threadId = filteredSnapshot.thread_id;
  elements.threadId.textContent = appState.threadId;
  appState.pendingApproval = filteredSnapshot.approval_request || null;
  const currentRunRevision = filteredSnapshot.current_run?.artifact_revision || null;
  if (currentRunRevision) {
    const cached = appState.artifactCache.get(filteredSnapshot.current_run.run_id);
    if (cached && cached.snapshot?.artifact_revision !== currentRunRevision) {
      appState.artifactCache.delete(filteredSnapshot.current_run.run_id);
    }
  }

  if (appState.selectedRunId && !getRunList(filteredSnapshot).some((run) => run.run_id === appState.selectedRunId)) {
    appState.selectedRunId = null;
  }

  renderViews();
  maybeShowRunFailureDialog(filteredSnapshot);
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

function invalidateLiveRequests() {
  appState.snapshotRequestGeneration += 1;
  appState.artifactRequestGeneration += 1;
  appState.snapshotRequestInFlight = false;
  appState.artifactRequestInFlight = false;
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
  const submittedApiKey = Boolean(elements.apiKey?.value?.trim?.());
  try {
    const data = await fetchJson("/config/runtime-overrides", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildRuntimeOverridesPayload()),
    });
    if (submittedApiKey && !data.api_key_configured) {
      throw new Error("API key was submitted but was not confirmed by saved settings.");
    }
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

async function resetRuntimeOverrides() {
  if (!window.confirm("Reset saved settings to the app defaults? This will not change your .env file or saved projects.")) {
    return;
  }
  elements.runtimeConfigReset.disabled = true;
  elements.runtimeConfigSave.disabled = true;
  elements.runtimeConfigStatus.textContent = "Resetting...";
  try {
    const data = await fetchJson("/config/runtime-overrides", { method: "DELETE" });
    applyRuntimeOverrides(data);
    await loadFrontendDefaults();
    updateStartRuntimeHint();
    elements.runtimeConfigStatus.textContent = "Defaults restored";
    setStatus("Runtime settings reset to defaults");
  } catch (error) {
    elements.runtimeConfigStatus.textContent = "Reset failed";
    setStatus(error.message || "Runtime settings reset failed");
  } finally {
    elements.runtimeConfigReset.disabled = false;
    elements.runtimeConfigSave.disabled = false;
  }
}

async function refreshArtifactsForSelection({ silent = false, force = false, showLoading = false } = {}) {
  if (!appState.threadId || (appState.artifactRequestInFlight && !force)) {
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

  const requestGeneration = appState.artifactRequestGeneration;
  const requestThreadId = appState.threadId;
  const requestRunId = selectedRun.run_id || null;
  appState.artifactRequestInFlight = true;
  const currentArtifactMatchesSelection = Boolean(
    appState.latestArtifactSnapshot
    && (
      appState.latestArtifactSnapshot.run_id === selectedRun.run_id
      || (
        appState.latestArtifactSnapshot.artifact_dir
        && selectedRun.artifact_dir
        && appState.latestArtifactSnapshot.artifact_dir === selectedRun.artifact_dir
      )
    )
  );
  if (showLoading || !currentArtifactMatchesSelection) {
    renderWorkspaceArtifactLoadingState(selectedRun);
    updateWorkspaceActionAvailability({ status: selectedRun.status, available: false });
  }
  try {
    const runQuery = selectedRun.run_id ? `?run_id=${encodeURIComponent(selectedRun.run_id)}` : "";
    const data = await fetchJson(`/threads/${requestThreadId}/artifacts${runQuery}`);
    if (
      requestGeneration !== appState.artifactRequestGeneration
      || requestThreadId !== appState.threadId
      || requestRunId !== (getSelectedRun()?.run_id || null)
    ) {
      return;
    }
    appState.artifactCache.set(cacheKey, { signature: cacheSignature, snapshot: data });
    appState.latestArtifactSnapshot = data;
    renderArtifactViews(data);
    if (!silent) {
      setStatus("Artifacts refreshed");
    }
  } finally {
    if (requestGeneration === appState.artifactRequestGeneration) {
      appState.artifactRequestInFlight = false;
      scheduleArtifactPolling();
    }
  }
}

function getOutputFrames(snapshot) {
  return Array.isArray(snapshot?.output_frames) ? snapshot.output_frames : [];
}

function isWorkspaceOutputFrameVisible(frame) {
  return frame?.scope !== "region-final";
}

function getDisplayArtifactSnapshot(snapshot) {
  const frames = getOutputFrames(snapshot);
  if (!frames.length) {
    return snapshot;
  }
  const visibleFrames = frames.filter(isWorkspaceOutputFrameVisible);
  if (visibleFrames.length === frames.length || !visibleFrames.length) {
    return snapshot;
  }
  return {
    ...snapshot,
    output_frames: visibleFrames,
    output_frames_total: frames.length,
  };
}

function getOutputFrameKey(frame, index) {
  return frame?.frame_id ? String(frame.frame_id) : `index:${index}`;
}

function clampOutputFrameIndex(frames, index) {
  if (!frames.length) {
    return 0;
  }
  const numericIndex = Number.isFinite(index) ? index : 0;
  return Math.max(0, Math.min(frames.length - 1, numericIndex));
}

function syncOutputFrameSelection(snapshot) {
  const frames = getOutputFrames(snapshot);
  if (!frames.length) {
    appState.selectedOutputFrameIndex = 0;
    appState.selectedOutputFrameId = null;
    return;
  }

  const followMode = appState.outputFrameFollowMode === "manual" ? "manual" : "auto";
  appState.outputFrameFollowMode = followMode;
  appState.outputFrameAutoFollow = followMode === "auto";

  if (followMode === "auto") {
    const latestIndex = frames.length - 1;
    appState.selectedOutputFrameIndex = latestIndex;
    appState.selectedOutputFrameId = getOutputFrameKey(frames[latestIndex], latestIndex);
    return;
  }

  const selectedId = appState.selectedOutputFrameId ? String(appState.selectedOutputFrameId) : null;
  const idIndex = selectedId
    ? frames.findIndex((frame, index) => getOutputFrameKey(frame, index) === selectedId)
    : -1;
  const selectedIndex = idIndex >= 0
    ? idIndex
    : clampOutputFrameIndex(frames, appState.selectedOutputFrameIndex);
  appState.selectedOutputFrameIndex = selectedIndex;
  appState.selectedOutputFrameId = getOutputFrameKey(frames[selectedIndex], selectedIndex);
}

function setSelectedOutputFrame(snapshot, index, options = {}) {
  const frames = getOutputFrames(snapshot);
  const selectedIndex = clampOutputFrameIndex(frames, index);
  if (options.source === "user") {
    appState.outputFrameFollowMode = "manual";
    appState.outputFrameAutoFollow = false;
  }
  appState.selectedOutputFrameIndex = selectedIndex;
  appState.selectedOutputFrameId = frames.length ? getOutputFrameKey(frames[selectedIndex], selectedIndex) : null;
}

function renderArtifactViews(snapshot) {
  const displaySnapshot = getDisplayArtifactSnapshot(snapshot);
  const overlaySelectionAllowed =
    appState.manualSelectionMode === "select" && appState.manualReferenceSelectionMode === "select";
  if (!overlaySelectionAllowed && appState.selectedOverlay.objectId) {
    appState.selectedOverlay = { type: "region", regionId: appState.selectedOverlay.regionId, objectId: null };
  }
  syncOutputFrameSelection(displaySnapshot);
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
    displaySnapshot,
    appState.selectedOverlay,
    appState.selectedOutputFrameIndex,
    (overlay) => {
      appState.selectedOverlay = overlay;
      renderArtifactViews(snapshot);
      refreshManualRefineReadiness(snapshot);
    },
    (index, options = {}) => {
      setSelectedOutputFrame(displaySnapshot, index, options);
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
        refreshManualRefineReadiness(snapshot);
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

async function refreshSnapshot({ silent = false, force = false } = {}) {
  if (!appState.threadId || (appState.snapshotRequestInFlight && !force)) {
    return;
  }
  const requestGeneration = appState.snapshotRequestGeneration;
  const requestThreadId = appState.threadId;
  appState.snapshotRequestInFlight = true;
  if (!appState.snapshot) {
    renderViews();
  }
  try {
    const data = await fetchJson(`/threads/${requestThreadId}/snapshot`);
    if (requestGeneration !== appState.snapshotRequestGeneration || requestThreadId !== appState.threadId) {
      return;
    }
    applySnapshot(data);
    await refreshArtifactsForSelection({ silent: true, force: true });
    if (!silent) {
      setStatus("Monitor refreshed");
    }
  } finally {
    if (requestGeneration === appState.snapshotRequestGeneration) {
      appState.snapshotRequestInFlight = false;
      if (!appState.snapshot) {
        renderViews();
      }
      scheduleSnapshotPolling();
    }
  }
}

function applyRunStartSnapshot(data) {
  if (!data?.thread_id || !data?.run) {
    return;
  }
  const optimisticSnapshot = {
    thread_id: data.thread_id,
    status: data.run.status || "queued",
    content: null,
    approval_request: null,
    messages: data.messages || appState.snapshot?.messages || [],
    current_run: data.run,
    recent_runs: [
      data.run,
      ...(appState.snapshot?.recent_runs || []).filter((run) => run?.run_id !== data.run.run_id),
    ],
  };
  applySnapshot(optimisticSnapshot);
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
    stopSnapshotPolling();
    stopArtifactPolling();
    invalidateLiveRequests();
    appState.threadId = data.thread_id;
    elements.threadId.textContent = appState.threadId;
    appState.latestArtifactSnapshot = null;
    appState.artifactCache.clear();
    resetUiSelections();
    resetRenderState();
    clearArtifactPanel();
    renderManualAdjustmentPanel(null);
    updateWorkflowTraceSummary(null);
    renderWorkspaceArtifactLoadingState(data.run);
    updateWorkspaceActionAvailability({ status: data.run?.status || "queued", available: false });
    applyRunStartSnapshot(data);
    if (document.body.classList.contains("desktop-body")) {
      window.dispatchEvent(new CustomEvent("desktop-open-workspace-trace"));
    }
    setStatus("Running");
    await refreshSnapshot({ silent: true, force: true });
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
    appState.manualReferenceMode = "add";
    elements.manualUseReferenceImages.checked = true;
    elements.manualIncludeDefaultCrop.checked = false;
    renderManualAdjustmentPanel(appState.latestArtifactSnapshot);
  });

  [elements.manualUserIntroduction, elements.manualTargetDescription].forEach((element) => {
    element?.addEventListener("input", () => {
      refreshManualRefineReadiness(appState.latestArtifactSnapshot);
    });
  });

  [elements.manualReferencePanel, elements.manualTracePanel].forEach((details) => {
    details?.addEventListener("toggle", () => {
      if (details.dataset.programmaticToggle === "true") {
        delete details.dataset.programmaticToggle;
        details.classList.toggle("auto-collapsed", !details.open);
        window.requestAnimationFrame(refreshWorkflowTraceLayout);
        return;
      }
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

  elements.runtimeConfigReset?.addEventListener("click", async () => {
    await resetRuntimeOverrides();
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

  elements.resumeRun.addEventListener("click", async () => {
    await resumeRunFromArtifacts();
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
    refreshManualRefineReadiness(appState.latestArtifactSnapshot);
    if (appState.latestArtifactSnapshot) {
      renderArtifactViews(appState.latestArtifactSnapshot);
    }
  });

  elements.manualClearSelection.addEventListener("click", () => {
    clearManualSelectionBox();
    refreshManualRefineReadiness(appState.latestArtifactSnapshot);
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

  elements.manualReferenceUseDefault?.addEventListener("click", () => {
    setManualReferenceMode("default");
  });

  elements.manualReferenceCaptureRef?.addEventListener("click", () => {
    setManualReferenceMode("capture");
  });

  elements.manualReferenceAddImage?.addEventListener("click", () => {
    setManualReferenceMode("add", { openUpload: true });
  });

  elements.manualReferenceNoRef?.addEventListener("click", () => {
    setManualReferenceMode("none");
  });

  elements.manualReferenceUploadPanel?.addEventListener("toggle", () => {
    updateManualReferenceModeControls();
  });

  elements.manualUploadButton.addEventListener("click", (event) => {
    event.stopPropagation();
    setManualReferenceMode("add", { openUpload: true, render: false });
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
    setManualReferenceMode("add", { openUpload: true, render: false });
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

  elements.manualReferenceCaptureButton?.addEventListener("click", async (event) => {
    event.stopPropagation();
    setManualReferenceMode("add", { openUpload: true, render: false });
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

  elements.manualIncludeDefaultCrop.addEventListener("change", () => {
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
      const crop = zoomButton.dataset.zoomCrop === "true"
        ? {
          x: Number.parseFloat(zoomButton.dataset.zoomCropX || "0"),
          y: Number.parseFloat(zoomButton.dataset.zoomCropY || "0"),
          width: Number.parseFloat(zoomButton.dataset.zoomCropWidth || "0"),
          height: Number.parseFloat(zoomButton.dataset.zoomCropHeight || "0"),
          canvasWidth: Number.parseFloat(zoomButton.dataset.zoomCanvasWidth || "0"),
          canvasHeight: Number.parseFloat(zoomButton.dataset.zoomCanvasHeight || "0"),
        }
        : null;
      openImageLightbox({
        src: zoomButton.dataset.zoomSrc || "",
        alt: zoomButton.dataset.zoomAlt || "",
        caption: zoomButton.dataset.zoomCaption || "",
        crop: crop && crop.width && crop.height && crop.canvasWidth && crop.canvasHeight ? crop : null,
      });
      return;
    }
    const previewButton = event.target instanceof Element ? event.target.closest(".run-chip-preview-zoom") : null;
    if (previewButton instanceof HTMLButtonElement) {
      event.preventDefault();
      event.stopPropagation();
      openImageLightbox({
        src: previewButton.dataset.previewSrc || "",
        alt: previewButton.dataset.previewAlt || "",
        caption: previewButton.dataset.previewCaption || previewButton.dataset.previewAlt || "",
      });
      return;
    }
    const lightboxZoomAction = event.target instanceof Element
      ? event.target.closest("[data-lightbox-zoom]")?.getAttribute("data-lightbox-zoom")
      : null;
    if (lightboxZoomAction && elements.imageLightbox && !elements.imageLightbox.classList.contains("hidden")) {
      event.preventDefault();
      if (lightboxZoomAction === "in") {
        setImageLightboxScale(imageLightboxState.scale * 1.2);
      } else if (lightboxZoomAction === "out") {
        setImageLightboxScale(imageLightboxState.scale / 1.2);
      } else if (lightboxZoomAction === "reset") {
        resetImageLightboxZoom();
      }
      return;
    }
    if (event.target === elements.imageLightboxBackdrop || event.target === elements.imageLightboxClose) {
      event.preventDefault();
      closeImageLightbox();
    }
  });

  elements.imageLightboxStage?.addEventListener("wheel", (event) => {
    if (!elements.imageLightbox || elements.imageLightbox.classList.contains("hidden")) {
      return;
    }
    event.preventDefault();
    const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
    setImageLightboxScale(imageLightboxState.scale * factor, event);
  }, { passive: false });

  elements.imageLightboxStage?.addEventListener("pointerdown", (event) => {
    if (imageLightboxState.scale <= 1 || !imageLightboxState.surface) {
      return;
    }
    event.preventDefault();
    imageLightboxState.isDragging = true;
    imageLightboxState.dragStartX = event.clientX;
    imageLightboxState.dragStartY = event.clientY;
    imageLightboxState.dragOriginX = imageLightboxState.translateX;
    imageLightboxState.dragOriginY = imageLightboxState.translateY;
    elements.imageLightboxStage?.classList.add("is-dragging");
    elements.imageLightboxStage?.setPointerCapture?.(event.pointerId);
  });

  elements.imageLightboxStage?.addEventListener("pointermove", (event) => {
    if (!imageLightboxState.isDragging) {
      return;
    }
    imageLightboxState.translateX = imageLightboxState.dragOriginX + event.clientX - imageLightboxState.dragStartX;
    imageLightboxState.translateY = imageLightboxState.dragOriginY + event.clientY - imageLightboxState.dragStartY;
    updateImageLightboxTransform();
  });

  const stopLightboxDrag = (event) => {
    if (!imageLightboxState.isDragging) {
      return;
    }
    imageLightboxState.isDragging = false;
    elements.imageLightboxStage?.classList.remove("is-dragging");
    if (event?.pointerId != null) {
      elements.imageLightboxStage?.releasePointerCapture?.(event.pointerId);
    }
  };
  elements.imageLightboxStage?.addEventListener("pointerup", stopLightboxDrag);
  elements.imageLightboxStage?.addEventListener("pointercancel", stopLightboxDrag);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && elements.imageLightbox && !elements.imageLightbox.classList.contains("hidden")) {
      closeImageLightbox();
    } else if ((event.key === "+" || event.key === "=") && elements.imageLightbox && !elements.imageLightbox.classList.contains("hidden")) {
      setImageLightboxScale(imageLightboxState.scale * 1.2);
    } else if (event.key === "-" && elements.imageLightbox && !elements.imageLightbox.classList.contains("hidden")) {
      setImageLightboxScale(imageLightboxState.scale / 1.2);
    } else if (event.key === "0" && elements.imageLightbox && !elements.imageLightbox.classList.contains("hidden")) {
      resetImageLightboxZoom();
    }
  });
}

export async function initApp() {
  loadUiModePreference();
  applyFriendlySettingsLabels();
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
