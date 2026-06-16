import { elements } from "./dom.js";
import { appState, renderState, DEFAULT_MESSAGE } from "./state.js";
import {
  arrayBufferToBase64,
  normalizeDisplayValue,
  setElementValue,
  stableStringify,
  truncate,
} from "./utils.js";
import { fetchJson } from "./api-client.js";

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
  { id: "api-key", custom: getApiKeyEffectiveValue },
  { id: "base-url", key: "base_url" },
  { id: "api-provider", key: "api_provider" },
  { id: "api-format", key: "api_format" },
  { id: "max-retries", key: "max_retries", summary: true },
  { id: "agent-model", key: "agent_model" },
  { id: "subagent-model", key: "subagent_model" },
  { id: "agent-name", key: "agent_name" },
  { id: "use-previous-response-id", key: "use_previous_response_id" },
  { id: "max-repair-retry", key: "max_retry", summary: true },
  { id: "max-budget", key: "max_budget", summary: true },
  { id: "supervisor-memory-enabled", key: "supervisor_memory_enabled" },
  { id: "supervisor-memory-persist-enabled", key: "supervisor_memory_persist_enabled" },
  { id: "strategy-enabled", key: "strategy_enabled" },
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
    case "region-processing-mode":
      return elements.regionProcessingMode;
    case "region-concurrency":
      return elements.regionConcurrency;
    case "api-key":
      return elements.apiKey;
    case "base-url":
      return elements.baseUrl;
    case "api-provider":
      return elements.apiProvider;
    case "api-format":
      return elements.apiFormat;
    case "max-retries":
      return elements.maxRetries;
    case "agent-model":
      return elements.agentModel;
    case "subagent-model":
      return elements.subagentModel;
    case "agent-name":
      return elements.agentName;
    case "use-previous-response-id":
      return elements.usePreviousResponseId;
    case "max-repair-retry":
      return elements.maxRepairRetry;
    case "max-budget":
      return elements.maxBudget;
    case "supervisor-memory-enabled":
      return elements.supervisorMemoryEnabled;
    case "supervisor-memory-persist-enabled":
      return elements.supervisorMemoryPersistEnabled;
    case "strategy-enabled":
      return elements.strategyEnabled;
    default:
      return null;
  }
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

function getRuntimeDefaultValue(spec) {
  if (spec.id === "api-key") {
    return appState.defaults?.api_key_configured ? "configured in .env" : "not configured";
  }
  if (!spec.key) {
    return "-";
  }
  return normalizeDisplayValue(appState.defaults?.[spec.key]);
}

function getFieldDisplayValue(spec) {
  const effectiveValue = getEffectiveValue(spec);
  if (effectiveValue === "" || effectiveValue == null) {
    return "-";
  }
  return truncate(String(effectiveValue), 34);
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
      slot.title = String(
        effectiveValue === "" || effectiveValue == null
          ? (RUNTIME_FIELD_SPECS.includes(spec) ? getRuntimeDefaultValue(spec) : "-")
          : effectiveValue
      );
    }
    if (spec.summary && RUNTIME_FIELD_SPECS.includes(spec)) {
      const targetParts = runtimeSummaryParts;
      targetParts.push({
        label: spec.id.replaceAll("-", " "),
        value: truncate(effectiveValue, 24),
      });
    }
  }

  if (elements.runtimeConfigSummary) {
    elements.runtimeConfigSummary.innerHTML = "";
    for (const part of runtimeSummaryParts) {
      const chip = document.createElement("span");
      chip.className = "effective-chip";
      chip.textContent = `${part.label}: ${part.value}`;
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
  elements.apiKey.placeholder = defaults.api_key_configured ? "Configured in .env" : "Not configured in .env";
  appState.defaultsLoaded = true;
  if (appState.runtimeOverrides) {
    applyRuntimeOverrides(appState.runtimeOverrides);
    return;
  }
  updateEffectiveValues();
}

export function applyRuntimeOverrides(overrides) {
  appState.runtimeOverrides = overrides || {};
  for (const spec of RUNTIME_FIELD_SPECS) {
    const element = getElementByFieldId(spec.id);
    if (!element) {
      continue;
    }
    const hasOverride = Object.prototype.hasOwnProperty.call(appState.runtimeOverrides || {}, spec.key || spec.id);
    markOverrideState(element, hasOverride);
    const resolvedValue = getResolvedRuntimeValue(spec);
    if (element.tagName === "SELECT") {
      setElementValue(element, resolvedValue === "" ? String(appState.defaults?.[spec.key] ?? "") : resolvedValue);
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
  elements.uploadPreviewMeta.textContent =
    "Focus here, then paste with Ctrl+V or choose a file below.";
  elements.uploadPreviewPanel.classList.add("upload-preview-empty-state");
  elements.uploadStatus.textContent = "No local file uploaded.";
}

function setUploadPreview(file, objectUrl) {
  elements.uploadPreviewImage.src = objectUrl;
  elements.uploadPreviewMeta.textContent = `${file.name} | ${Math.max(1, Math.round(file.size / 1024))} KB`;
  elements.uploadPreviewImage.classList.remove("hidden");
  elements.uploadPreviewEmpty.classList.add("hidden");
  elements.uploadPreviewPanel.classList.remove("upload-preview-empty-state");
}

export async function uploadLocalFile(file, setStatus) {
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

  if (appState.localUpload?.previewObjectUrl) {
    URL.revokeObjectURL(appState.localUpload.previewObjectUrl);
  }
  const previewObjectUrl = URL.createObjectURL(normalizedFile);
  appState.localUpload = { ...data, previewObjectUrl };
  elements.imagePath.value = data.image_path;
  elements.uploadStatus.textContent = `${data.filename} uploaded (${data.size_bytes} bytes)`;
  setUploadPreview(normalizedFile, previewObjectUrl);
  updateEffectiveValues();
  setStatus("Upload complete");
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

export function buildInvokePayload(threadId) {
  const payload = {
    thread_id: threadId,
    message: elements.messageInput.value.trim(),
  };

  const imagePath = elements.imagePath.value.trim();
  const projectName = elements.projectName.value.trim();
  const workflowMode = elements.workflowMode.value;
  const regionProcessingMode = elements.regionProcessingMode.value;
  const regionConcurrencyRaw = elements.regionConcurrency.value.trim();

  if (imagePath) {
    payload.image_path = imagePath;
  }
  if (projectName) {
    payload.project_name = projectName;
  }
  if (workflowMode) {
    payload.workflow_mode = workflowMode;
  }
  if (regionProcessingMode) {
    payload.region_processing_mode = regionProcessingMode;
  }
  if (regionConcurrencyRaw) {
    const regionConcurrency = Number.parseInt(regionConcurrencyRaw, 10);
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
    if (!element || element.dataset.overrideActive !== "true") {
      continue;
    }
    const rawValue = element.value?.trim?.() ?? element.value ?? "";
    switch (key) {
      case "api_key":
      case "base_url":
      case "api_provider":
      case "api_format":
      case "agent_model":
      case "subagent_model":
      case "agent_name":
        if (rawValue) {
          payload[key] = rawValue;
        }
        break;
      case "max_retries":
      case "max_retry":
      case "max_budget": {
        if (!rawValue) {
          break;
        }
        const parsed = Number.parseInt(rawValue, 10);
        if (!Number.isNaN(parsed)) {
          payload[key] = parsed;
        }
        break;
      }
      case "use_previous_response_id":
      case "supervisor_memory_enabled":
      case "supervisor_memory_persist_enabled":
      case "strategy_enabled":
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
