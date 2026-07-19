import { elements } from "./dom.js";
import { appState, renderState, DEFAULT_MESSAGE } from "./state.js?v=workspace-session-isolation-5";
import {
  arrayBufferToBase64,
  normalizeDisplayValue,
  setElementValue,
  stableStringify,
  truncate,
} from "./utils.js";
import { fetchJson } from "./api-client.js?v=workspace-session-isolation-5";
import { getSettingsValueLabel } from "./settings-labels.js?v=desktop-settings-labels-1";

function guessExtensionFromMimeType(mimeType) {
  switch ((mimeType || "").toLowerCase()) {
    case "image/jpeg":
      return ".jpg";
    case "image/webp":
      return ".webp";
    case "image/gif":
      return ".gif";
    case "image/bmp":
      return ".bmp";
    case "image/svg+xml":
      return ".svg";
    case "image/png":
    default:
      return ".png";
  }
}

function ensureNamedUploadFile(file, source = "upload") {
  if (!file) {
    return file;
  }
  if (file.name && file.name.trim()) {
    return file;
  }
  const extension = guessExtensionFromMimeType(file.type);
  const timestamp = new Date().toISOString().replaceAll(":", "-").replaceAll(".", "-");
  const filename = `${source}-${timestamp}${extension}`;
  return new File([file], filename, {
    type: file.type || "image/png",
    lastModified: Date.now(),
  });
}

export function getMessageEffectiveValue() {
  return elements.messageInput.value.trim() || appState.defaults?.default_user_input || DEFAULT_MESSAGE;
}

export const MESSAGE_PRESET_TEXT = {
  default: DEFAULT_MESSAGE,
  iconFaithful: `${DEFAULT_MESSAGE}\n\nAdditional constraints: preserve icon silhouettes, spacing relationships, and small emblem details as faithfully as possible. Avoid replacing icons with generic simplified shapes unless the source is unreadable.`,
  relaxed: `${DEFAULT_MESSAGE}\n\nRelaxed acceptance: prioritize a clean, editable SVG and readable structure over exact visual fidelity. Minor differences in spacing, decorative detail, or local styling are acceptable if the overall layout and semantics stay clear.`,
};

function getImagePathEffectiveValue() {
  return elements.imagePath.value.trim() || "not set";
}

function getProjectNameEffectiveValue() {
  return elements.projectName.value.trim() || "auto from image/message";
}

function getApiKeyEffectiveValue() {
  if (elements.apiKey.value.trim()) {
    return "manual override";
  }
  if (appState.runtimeOverrides?.api_key_configured) {
    return "configured in settings";
  }
  return appState.defaults?.api_key_configured ? "configured in .env" : "not configured";
}

export const FIELD_SPECS = [
  { id: "message-input", key: "default_user_input", summary: true, custom: getMessageEffectiveValue },
  { id: "image-path", custom: getImagePathEffectiveValue },
  { id: "project-name", custom: getProjectNameEffectiveValue },
  { id: "workflow-mode", key: "workflow_mode", summary: true },
  { id: "region-processing-mode", key: "region_processing_mode", summary: true },
  { id: "region-concurrency", key: "region_concurrency", summary: true },
];

export const RUNTIME_FIELD_SPECS = [
  { id: "api-key", key: "api_key", custom: getApiKeyEffectiveValue },
  { id: "base-url", key: "base_url" },
  { id: "api-provider", key: "api_provider" },
  { id: "api-format", key: "api_format" },
  { id: "settings-workflow-mode", key: "workflow_mode", summaryLabel: "refinement depth", summary: true, summaryOrder: 1, summarySpan: 2 },
  { id: "settings-region-processing-mode", key: "region_processing_mode", summaryLabel: "processing schedule", summary: true, summaryOrder: 2, summarySpan: 2 },
  { id: "run-model-call-budget", key: "run_model_call_budget", type: "integer", min: 1, preserveBlankWithoutOverride: true, summaryLabel: "model budget", summary: true, summaryOrder: 3, summarySuffix: "calls" },
  { id: "settings-region-concurrency", key: "region_concurrency", type: "integer", min: 1, summaryLabel: "region concurrency", summary: true, summaryOrder: 4 },
  { id: "bbox-refinement-max-rounds", key: "bbox_refinement_max_rounds", type: "integer", min: 0, preserveBlankWithoutOverride: true },
  { id: "region-repair-max-attempts", key: "region_repair_max_attempts", type: "integer", min: 0, preserveBlankWithoutOverride: true },
  { id: "object-repair-max-attempts", key: "object_repair_max_attempts", type: "integer", min: 0, preserveBlankWithoutOverride: true },
  { id: "fusion-repair-max-attempts", key: "fusion_repair_max_attempts", type: "integer", min: 0, preserveBlankWithoutOverride: true },
  { id: "manual-refine-worker-budget", key: "manual_refine_worker_budget", type: "integer", min: 1, preserveBlankWithoutOverride: true },
  { id: "agent-model", key: "agent_model", summaryLabel: "Coordinator Model", summary: true, summaryOrder: 8, summarySpan: 2 },
  { id: "subagent-model", key: "subagent_model", summaryLabel: "Worker Model", summary: true, summaryOrder: 9, summarySpan: 2 },
  { id: "agent-name", key: "agent_name" },
  { id: "use-previous-response-id", key: "use_previous_response_id" },
  { id: "supervisor-memory-enabled", key: "supervisor_memory_enabled" },
  { id: "supervisor-memory-persist-enabled", key: "supervisor_memory_persist_enabled" },
  { id: "strategy-enabled", key: "strategy_enabled" },
  { id: "recognition-bbox-refine-mode", key: "recognition_bbox_refine_mode" },
  { id: "sam-provider-mode", key: "sam_provider_mode" },
  { id: "sam-remote-url", key: "sam_remote_url" },
  { id: "sam-enabled", key: "sam_enabled" },
  { id: "sam-fallback-to-llm", key: "sam_fallback_to_llm" },
];

const COMPUTED_RUNTIME_SUMMARY_SPECS = [
  {
    label: "region / object repair",
    order: 5,
    getValue: () => `${getEffectiveRuntimeValueByKey("region_repair_max_attempts")} / ${getEffectiveRuntimeValueByKey("object_repair_max_attempts")}`,
  },
  {
    label: "bbox / fusion depth",
    order: 6,
    getValue: () => `${getEffectiveRuntimeValueByKey("bbox_refinement_max_rounds")} / ${getEffectiveRuntimeValueByKey("fusion_repair_max_attempts")}`,
  },
];

export function getElementByFieldId(fieldId) {
  switch (fieldId) {
    case "message-input":
      return elements.messageInput;
    case "image-path":
      return elements.imagePath;
    case "project-name":
      return elements.projectName;
    case "workflow-mode":
      return elements.workflowMode;
    case "settings-workflow-mode":
      return elements.settingsWorkflowMode;
    case "region-processing-mode":
      return elements.regionProcessingMode;
    case "settings-region-processing-mode":
      return elements.settingsRegionProcessingMode;
    case "region-concurrency":
      return elements.regionConcurrency;
    case "settings-region-concurrency":
      return elements.settingsRegionConcurrency;
    case "api-key":
      return elements.apiKey;
    case "base-url":
      return elements.baseUrl;
    case "api-provider":
      return elements.apiProvider;
    case "api-format":
      return elements.apiFormat;
    case "agent-model":
      return elements.agentModel;
    case "subagent-model":
      return elements.subagentModel;
    case "agent-name":
      return elements.agentName;
    case "use-previous-response-id":
      return elements.usePreviousResponseId;
    case "supervisor-memory-enabled":
      return elements.supervisorMemoryEnabled;
    case "supervisor-memory-persist-enabled":
      return elements.supervisorMemoryPersistEnabled;
    case "strategy-enabled":
      return elements.strategyEnabled;
    case "recognition-bbox-refine-mode":
      return elements.recognitionBboxRefineMode;
    case "sam-provider-mode":
      return elements.samProviderMode;
    case "sam-remote-url":
      return elements.samRemoteUrl;
    case "sam-enabled":
      return elements.samEnabled;
    case "sam-fallback-to-llm":
      return elements.samFallbackToLlm;
    default:
      return document.getElementById(fieldId);
  }
}

function getEffectiveRuntimeValueByKey(key) {
  const spec = RUNTIME_FIELD_SPECS.find((item) => item.key === key);
  return spec ? getEffectiveValue(spec) : normalizeDisplayValue(appState.defaults?.[key]);
}

export function getEffectiveValue(spec) {
  if (typeof spec.custom === "function") {
    return spec.custom();
  }

  const element = getElementByFieldId(spec.id);
  const rawValue = element?.value?.trim?.() ?? element?.value ?? "";
  if (rawValue !== "") {
    return rawValue;
  }

  const fallback = appState.defaults?.[spec.key];
  return normalizeDisplayValue(fallback);
}

function getDisplayValueForSpec(spec, value) {
  if (value === "" || value == null) {
    return value;
  }
  return getSettingsValueLabel(spec.key || spec.id, value);
}

function getResolvedRuntimeValue(spec) {
  if (spec.id === "api-key") {
    if (appState.runtimeOverrides?.api_key) {
      return appState.runtimeOverrides.api_key;
    }
    return "";
  }
  if (!spec.key) {
    return "";
  }
  const overrideValue = appState.runtimeOverrides?.[spec.key];
  if (overrideValue != null && overrideValue !== "") {
    return overrideValue;
  }
  return appState.defaults?.[spec.key] ?? "";
}

function markOverrideState(element, hasOverride) {
  if (!element) {
    return;
  }
  element.dataset.overrideActive = hasOverride ? "true" : "false";
}

function updateApiKeyPlaceholder() {
  if (!elements.apiKey) {
    return;
  }
  if (appState.runtimeOverrides?.api_key_configured) {
    elements.apiKey.placeholder = "Configured in settings";
    return;
  }
  elements.apiKey.placeholder = appState.defaults?.api_key_configured ? "Configured in .env" : "Not configured in .env";
}

function getRuntimeDefaultValue(spec) {
  if (spec.id === "api-key") {
    if (appState.runtimeOverrides?.api_key_configured) {
      return "configured in settings";
    }
    return appState.defaults?.api_key_configured ? "configured in .env" : "not configured";
  }
  if (!spec.key) {
    return "-";
  }
  return normalizeDisplayValue(appState.defaults?.[spec.key]);
}

function hasConfiguredApiKey() {
  return Boolean(
    elements.apiKey.value.trim()
    || appState.runtimeOverrides?.api_key
    || appState.runtimeOverrides?.api_key_configured
    || appState.defaults?.api_key_configured
  );
}

function hasUsableRuntimeValue(fieldId) {
  const spec = RUNTIME_FIELD_SPECS.find((item) => item.id === fieldId);
  if (!spec) {
    return false;
  }
  const value = getEffectiveValue(spec);
  if (fieldId === "api-key") {
    return hasConfiguredApiKey();
  }
  const normalized = value == null ? "" : String(value).trim();
  return Boolean(normalized && normalized !== "default" && normalized !== "not configured");
}

export function getStartRuntimeReadiness() {
  if (!appState.defaultsLoaded) {
    return {
      ready: false,
      missing: ["runtime defaults"],
      title: "Checking runtime settings...",
      body: "Loading connection and model defaults before conversion can start.",
    };
  }

  const requiredFields = [
    ["api-key", "API key"],
    ["base-url", "Base URL"],
    ["api-provider", "API protocol"],
    ["api-format", "request format"],
    ["agent-model", "Coordinator model"],
    ["subagent-model", "Worker model"],
  ];
  const missing = requiredFields
    .filter(([fieldId]) => !hasUsableRuntimeValue(fieldId))
    .map(([, label]) => label);

  if (missing.length) {
    const visibleMissing = missing.slice(0, 3).join(", ");
    const suffix = missing.length > 3 ? ` and ${missing.length - 3} more` : "";
    return {
      ready: false,
      missing,
      title: "Runtime settings need attention.",
      body: `${visibleMissing}${suffix} ${missing.length === 1 ? "needs" : "need"} to be configured before conversion.`,
    };
  }

  return {
    ready: true,
    missing: [],
    title: "Default settings are ready.",
    body: "Tune model, budget, or workflow if needed.",
  };
}

function getFieldDisplayValue(spec) {
  const effectiveValue = getEffectiveValue(spec);
  if (effectiveValue === "" || effectiveValue == null) {
    return "-";
  }
  return truncate(String(getDisplayValueForSpec(spec, effectiveValue)), 34);
}

export function updateEffectiveValues() {
  const signature = stableStringify({
    defaults: appState.defaults || {},
    runtimeOverrides: appState.runtimeOverrides || {},
    values: FIELD_SPECS.map((spec) => [spec.id, getElementByFieldId(spec.id)?.value ?? null]),
    runtimeValues: RUNTIME_FIELD_SPECS.map((spec) => [spec.id, getElementByFieldId(spec.id)?.value ?? null]),
    upload: appState.localUpload?.image_path || null,
  });
  if (renderState.effectiveSig === signature) {
    return;
  }

  const runtimeSummaryParts = [];
  for (const spec of [...FIELD_SPECS, ...RUNTIME_FIELD_SPECS]) {
    const effectiveValue = getEffectiveValue(spec);
    const slot = document.getElementById(`effective-${spec.id}`);
    if (slot) {
      slot.textContent = getFieldDisplayValue(spec);
      const titleValue = effectiveValue === "" || effectiveValue == null
        ? (RUNTIME_FIELD_SPECS.includes(spec) ? getRuntimeDefaultValue(spec) : "-")
        : getDisplayValueForSpec(spec, effectiveValue);
      slot.title = String(titleValue);
    }
    if (spec.summary && RUNTIME_FIELD_SPECS.includes(spec)) {
      const targetParts = runtimeSummaryParts;
      const displayValue = String(getDisplayValueForSpec(spec, effectiveValue));
      targetParts.push({
        label: spec.summaryLabel || spec.id.replaceAll("-", " "),
        value: displayValue === "-" || !spec.summarySuffix
          ? displayValue
          : `${displayValue} ${spec.summarySuffix}`,
        order: spec.summaryOrder ?? Number.MAX_SAFE_INTEGER,
        span: spec.summarySpan ?? 1,
      });
    }
  }
  for (const spec of COMPUTED_RUNTIME_SUMMARY_SPECS) {
    runtimeSummaryParts.push({
      label: spec.label,
      value: String(spec.getValue()),
      order: spec.order,
      span: spec.span ?? 1,
    });
  }

  if (elements.runtimeConfigSummary) {
    elements.runtimeConfigSummary.innerHTML = "";
    runtimeSummaryParts.sort((left, right) => left.order - right.order);
    for (const part of runtimeSummaryParts) {
      const chip = document.createElement("span");
      chip.className = "effective-chip";
      chip.classList.add(`effective-chip--span-${part.span}`);
      chip.title = `${part.label}: ${part.value}`;
      const label = document.createElement("span");
      label.className = "effective-chip-label";
      label.textContent = part.label;
      label.title = part.label;
      const value = document.createElement("span");
      value.className = "effective-chip-value";
      value.textContent = part.value;
      value.title = part.value;
      chip.append(label, value);
      elements.runtimeConfigSummary.appendChild(chip);
    }
  }

  renderState.effectiveSig = signature;
}

export function applyFrontendDefaults(defaults) {
  if (!defaults) {
    return;
  }
  appState.defaults = defaults;
  if (!elements.messageInput.value.trim()) {
    elements.messageInput.value = defaults.default_user_input || MESSAGE_PRESET_TEXT.default;
    appState.messagePreset = "default";
    elements.messageInput.dataset.messagePreset = "default";
  }
  setElementValue(elements.regionProcessingMode, defaults.region_processing_mode || "");
  setElementValue(elements.regionConcurrency, defaults.region_concurrency ?? "");
  setElementValue(elements.workflowMode, defaults.workflow_mode || "");
  updateApiKeyPlaceholder();
  appState.defaultsLoaded = true;
  if (appState.runtimeOverrides) {
    applyRuntimeOverrides(appState.runtimeOverrides);
    return;
  }
  updateEffectiveValues();
}

export function applyRuntimeOverrides(overrides) {
  appState.runtimeOverrides = overrides || {};
  updateApiKeyPlaceholder();
  for (const spec of RUNTIME_FIELD_SPECS) {
    const element = getElementByFieldId(spec.id);
    if (!element) {
      continue;
    }
    const hasOverride = Object.prototype.hasOwnProperty.call(appState.runtimeOverrides || {}, spec.key || spec.id);
    markOverrideState(element, spec.id === "api-key" ? Boolean(appState.runtimeOverrides?.api_key_configured) : hasOverride);
    const resolvedValue = getResolvedRuntimeValue(spec);
    if (element.tagName === "SELECT") {
      setElementValue(element, resolvedValue === "" ? String(appState.defaults?.[spec.key] ?? "") : resolvedValue);
    } else if (spec.preserveBlankWithoutOverride && !hasOverride) {
      setElementValue(element, "");
      const defaultValue = normalizeDisplayValue(appState.defaults?.[spec.key]);
      element.placeholder = defaultValue === "-" ? "Uses environment default" : `Default: ${defaultValue}`;
    } else {
      setElementValue(element, resolvedValue);
    }
  }
  updateEffectiveValues();
}

export function clearUploadPreview() {
  if (appState.localUpload?.previewObjectUrl) {
    URL.revokeObjectURL(appState.localUpload.previewObjectUrl);
  }
  appState.localUpload = null;
  elements.uploadPreviewImage.removeAttribute("src");
  elements.uploadPreviewImage.classList.add("hidden");
  elements.uploadPreviewEmpty.classList.remove("hidden");
  elements.uploadPreviewMeta.textContent = document.body.classList.contains("desktop-body")
    ? ""
    : "Focus here, then paste with Ctrl+V or choose a file below.";
  elements.uploadPreviewPanel.classList.add("upload-preview-empty-state");
  elements.uploadStatus.textContent = document.body.classList.contains("desktop-body") ? "" : "No local file uploaded.";
}

export function syncUploadPreviewFromState() {
  const upload = appState.localUpload;
  if (upload?.previewObjectUrl) {
    elements.uploadPreviewImage.src = upload.previewObjectUrl;
    elements.uploadPreviewImage.classList.remove("hidden");
    elements.uploadPreviewEmpty.classList.add("hidden");
    elements.uploadPreviewPanel.classList.remove("upload-preview-empty-state");
    elements.uploadPreviewMeta.textContent = upload.previewMeta
      || `${upload.filename || "Uploaded image"} | ${Math.max(1, Math.round((upload.size_bytes || 0) / 1024))} KB`;
    elements.uploadStatus.textContent = upload.filename
      ? `${upload.filename} uploaded (${upload.size_bytes || 0} bytes)`
      : "Image uploaded";
    return;
  }
  elements.uploadPreviewImage.removeAttribute("src");
  elements.uploadPreviewImage.classList.add("hidden");
  elements.uploadPreviewEmpty.classList.remove("hidden");
  elements.uploadPreviewMeta.textContent = document.body.classList.contains("desktop-body")
    ? ""
    : "Focus here, then paste with Ctrl+V or choose a file below.";
  elements.uploadPreviewPanel.classList.add("upload-preview-empty-state");
  elements.uploadStatus.textContent = document.body.classList.contains("desktop-body") ? "" : "No local file uploaded.";
}

export function resetInputImageSelection() {
  clearUploadPreview();
  elements.imagePath.value = "";
  elements.uploadFileInput.value = "";
  updateEffectiveValues();
}

function setUploadPreview(file, objectUrl) {
  elements.uploadPreviewImage.src = objectUrl;
  elements.uploadPreviewMeta.textContent = `${file.name} | ${Math.max(1, Math.round(file.size / 1024))} KB`;
  elements.uploadPreviewImage.classList.remove("hidden");
  elements.uploadPreviewEmpty.classList.add("hidden");
  elements.uploadPreviewPanel.classList.remove("upload-preview-empty-state");
}

export async function uploadLocalFile(file, setStatus, { shouldApply = () => true } = {}) {
  if (!file) {
    return;
  }
  const normalizedFile = ensureNamedUploadFile(file, "input-image");
  setStatus("Uploading local file...");
  elements.uploadStatus.textContent = `Uploading ${normalizedFile.name}...`;
  const buffer = await normalizedFile.arrayBuffer();
  const contentBase64 = arrayBufferToBase64(buffer);
  const data = await fetchJson("/uploads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: normalizedFile.name,
      content_base64: contentBase64,
    }),
  });

  const previewObjectUrl = URL.createObjectURL(normalizedFile);
  const upload = {
    ...data,
    previewObjectUrl,
    previewMeta: `${normalizedFile.name} | ${Math.max(1, Math.round(normalizedFile.size / 1024))} KB`,
  };
  if (!shouldApply()) {
    return upload;
  }
  if (appState.localUpload?.previewObjectUrl) {
    URL.revokeObjectURL(appState.localUpload.previewObjectUrl);
  }
  appState.localUpload = upload;
  elements.imagePath.value = data.image_path;
  elements.uploadStatus.textContent = `${data.filename} uploaded (${data.size_bytes} bytes)`;
  setUploadPreview(normalizedFile, previewObjectUrl);
  updateEffectiveValues();
  setStatus("Upload complete");
  return upload;
}

export async function pickLocalFileFromHost() {
  const host = window.desktopHost;
  if (!host?.openLocalImage) {
    return null;
  }
  const imagePath = await host.openLocalImage();
  if (!imagePath) {
    return null;
  }
  return imagePath;
}

export function bindFieldListeners() {
  for (const spec of [...FIELD_SPECS, ...RUNTIME_FIELD_SPECS]) {
    const element = getElementByFieldId(spec.id);
    if (!element) {
      continue;
    }
    element.addEventListener("input", () => {
      if (spec.id === "image-path" && appState.localUpload && element.value.trim() !== appState.localUpload.image_path) {
        clearUploadPreview();
      }
      if (RUNTIME_FIELD_SPECS.includes(spec)) {
        markOverrideState(element, true);
        elements.runtimeConfigStatus.textContent = "Unsaved changes";
      }
      updateEffectiveValues();
    });
    element.addEventListener("change", () => {
      if (RUNTIME_FIELD_SPECS.includes(spec)) {
        markOverrideState(element, true);
        elements.runtimeConfigStatus.textContent = "Unsaved changes";
      }
      updateEffectiveValues();
    });
  }
}

export function bindPromptButtons() {
  for (const button of document.querySelectorAll(".prompt-chip")) {
    button.addEventListener("click", () => {
      const prompt = button.dataset.prompt;
      elements.messageInput.value = prompt || DEFAULT_MESSAGE;
      updateEffectiveValues();
    });
  }
}

export function updateMessagePresetSelection() {
  if (!elements.messagePresetBar) {
    return;
  }
  const currentValue = elements.messageInput.value.trim();
  const derivedPreset = Object.entries(MESSAGE_PRESET_TEXT).find(([, value]) => value.trim() === currentValue)?.[0] || null;
  const storedPreset = elements.messageInput.dataset.messagePreset || appState.messagePreset || "default";
  const activePreset = derivedPreset || storedPreset;
  const presetButtons = [
    [elements.messagePresetDefault, "default"],
    [elements.messagePresetIconFaithful, "iconFaithful"],
    [elements.messagePresetRelaxed, "relaxed"],
  ];
  for (const [button, presetKey] of presetButtons) {
    if (!button) {
      continue;
    }
    button.classList.toggle("is-active", presetKey === activePreset);
  }
}

export function buildInvokePayload(threadId, draft = null) {
  const message = draft?.message ?? elements.messageInput.value;
  const imagePath = draft?.imagePath ?? elements.imagePath.value;
  const projectName = draft?.projectName ?? elements.projectName.value;
  const workflowMode = draft?.workflowMode ?? elements.workflowMode.value;
  const regionProcessingMode = draft?.regionProcessingMode ?? elements.regionProcessingMode.value;
  const regionConcurrencyRaw = draft?.regionConcurrency ?? elements.regionConcurrency.value;
  const payload = {
    thread_id: threadId,
    message: String(message).trim(),
  };

  const normalizedImagePath = String(imagePath).trim();
  const normalizedProjectName = String(projectName).trim();
  const normalizedRegionConcurrency = String(regionConcurrencyRaw).trim();

  if (normalizedImagePath) {
    payload.image_path = normalizedImagePath;
  }
  if (normalizedProjectName) {
    payload.project_name = normalizedProjectName;
  }
  if (workflowMode) {
    payload.workflow_mode = workflowMode;
  }
  if (regionProcessingMode) {
    payload.region_processing_mode = regionProcessingMode;
  }
  if (normalizedRegionConcurrency) {
    const regionConcurrency = Number.parseInt(normalizedRegionConcurrency, 10);
    if (!Number.isNaN(regionConcurrency)) {
      payload.region_concurrency = regionConcurrency;
    }
  }

  return payload;
}

export function buildRuntimeOverridesPayload() {
  const payload = {};
  const runtimeSpecsByKey = new Map(RUNTIME_FIELD_SPECS.map((spec) => [spec.key || spec.id, spec]));

  for (const [key, spec] of runtimeSpecsByKey.entries()) {
    const element = getElementByFieldId(spec.id);
    if (!element) {
      continue;
    }
    const rawValue = element.value?.trim?.() ?? element.value ?? "";
    if (element.dataset.overrideActive !== "true" && rawValue === "") {
      continue;
    }
    if (element.dataset.overrideActive === "true" && rawValue === "") {
      payload[key] = null;
      continue;
    }
    if (spec.type === "integer") {
      const parsed = Number.parseInt(rawValue, 10);
      if (!Number.isNaN(parsed) && (spec.min == null || parsed >= spec.min)) {
        payload[key] = parsed;
      }
      continue;
    }
    switch (key) {
      case "api_key":
      case "base_url":
      case "api_provider":
      case "api_format":
      case "workflow_mode":
      case "region_processing_mode":
      case "agent_model":
      case "subagent_model":
      case "agent_name":
      case "recognition_bbox_refine_mode":
      case "sam_provider_mode":
      case "sam_remote_url":
        if (rawValue) {
          payload[key] = rawValue;
        }
        break;
      case "use_previous_response_id":
      case "supervisor_memory_enabled":
      case "supervisor_memory_persist_enabled":
      case "strategy_enabled":
      case "sam_enabled":
      case "sam_fallback_to_llm":
        if (rawValue === "true") {
          payload[key] = true;
        } else if (rawValue === "false") {
          payload[key] = false;
        }
        break;
      default:
        break;
    }
  }
  return payload;
}
