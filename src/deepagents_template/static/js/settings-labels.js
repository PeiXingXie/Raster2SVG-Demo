const FIELD_LABELS = {
  "workflow-mode": "Refinement Depth",
  "settings-workflow-mode": "Refinement Depth",
  "region-processing-mode": "Processing Schedule",
  "settings-region-processing-mode": "Processing Schedule",
  "manual-refine-worker-budget": "Manual Refine Depth",
  "api-provider": "API Protocol",
  "api-format": "Request Format",
  "recognition-bbox-refine-mode": "Detection Box Refinement",
  "sam-provider-mode": "Segmentation Service",
};

const VALUE_LABELS = {
  workflow_mode: {
    initial_only: "Quick Draft - basic conversion only",
    region: "Region Refinement - improve each detected area",
    region_object: "Full Detail - refine regions and individual objects",
  },
  region_processing_mode: {
    serial: "One at a time - slower, steadier",
    parallel: "Faster parallel processing",
  },
  api_format: {
    openai_chat_completions: "Chat Completions API",
    openai_responses: "Responses API",
  },
  recognition_bbox_refine_mode: {
    llm: "AI vision review",
    sam: "Segmentation model",
    hybrid: "Segmentation + AI review",
  },
  sam_provider_mode: {
    local: "Run on this computer",
    remote: "Use remote service",
  },
};

export function getSettingsFieldLabel(fieldId, fallbackLabel = "") {
  return FIELD_LABELS[fieldId] || fallbackLabel || fieldId;
}

export function getSettingsValueLabel(key, value) {
  const normalizedValue = value == null ? "" : String(value);
  if (!normalizedValue) {
    return normalizedValue;
  }
  return VALUE_LABELS[key]?.[normalizedValue] || normalizedValue;
}

export function applySettingsLabelMappings(root = document) {
  for (const [fieldId, label] of Object.entries(FIELD_LABELS)) {
    const field = root.querySelector(`[data-field-id="${fieldId}"]`);
    const labelNode = field?.querySelector(".field-label");
    if (labelNode) {
      const infoIcon = labelNode.querySelector(".settings-info-icon");
      labelNode.textContent = label;
      if (infoIcon) {
        labelNode.appendChild(infoIcon);
      }
    }
  }

  for (const select of root.querySelectorAll("select")) {
    const field = select.closest("[data-field-id]");
    const fieldId = field?.getAttribute("data-field-id") || "";
    const key = fieldIdToBackendKey(fieldId);
    if (!key || !VALUE_LABELS[key]) {
      continue;
    }
    for (const option of select.options) {
      if (option.value) {
        option.textContent = getSettingsValueLabel(key, option.value);
      }
    }
  }
}

function fieldIdToBackendKey(fieldId) {
  switch (fieldId) {
    case "workflow-mode":
    case "settings-workflow-mode":
      return "workflow_mode";
    case "region-processing-mode":
    case "settings-region-processing-mode":
      return "region_processing_mode";
    case "api-format":
      return "api_format";
    case "recognition-bbox-refine-mode":
      return "recognition_bbox_refine_mode";
    case "sam-provider-mode":
      return "sam_provider_mode";
    default:
      return "";
  }
}
