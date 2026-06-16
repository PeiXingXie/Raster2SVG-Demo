export function truncate(text, maxLength = 220) {
  if (!text) {
    return "";
  }
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

export function formatDate(isoString) {
  if (!isoString) {
    return "-";
  }
  return new Date(isoString).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatDuration(run) {
  if (!run) {
    return "0 ms";
  }
  if (typeof run.duration_ms === "number") {
    return `${run.duration_ms} ms`;
  }
  if (!run.started_at) {
    return "0 ms";
  }
  return `${Math.max(0, Date.now() - new Date(run.started_at).getTime())} ms`;
}

export function formatElapsedDuration(durationMs) {
  const safe = Math.max(0, Number(durationMs) || 0);
  if (safe < 1000) {
    return `${safe} ms`;
  }
  if (safe < 60_000) {
    return `${(safe / 1000).toFixed(safe < 10_000 ? 1 : 0)} s`;
  }
  const minutes = Math.floor(safe / 60_000);
  const seconds = Math.floor((safe % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

export function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function stableStringify(value) {
  return JSON.stringify(value);
}

export function captureDetailsState(root) {
  const state = new Map();
  for (const details of root.querySelectorAll("details[data-persist-key]")) {
    state.set(details.dataset.persistKey, details.open);
  }
  return state;
}

export function restoreDetailsState(root, state) {
  if (!state || state.size === 0) {
    return;
  }
  for (const details of root.querySelectorAll("details[data-persist-key]")) {
    if (state.has(details.dataset.persistKey)) {
      details.open = state.get(details.dataset.persistKey);
    }
  }
}

export function createCollapsibleContent(text, { maxLength = 320, key = null } = {}) {
  if (!text) {
    return document.createTextNode("");
  }

  if (text.length <= maxLength) {
    const paragraph = document.createElement("p");
    paragraph.className = "plain-text";
    paragraph.textContent = text;
    return paragraph;
  }

  const details = document.createElement("details");
  details.className = "collapsible";
  if (key) {
    details.dataset.persistKey = key;
  }

  const summary = document.createElement("summary");
  summary.textContent = truncate(text, maxLength);
  details.appendChild(summary);

  const full = document.createElement("pre");
  full.className = "long-content";
  full.textContent = text;
  details.appendChild(full);
  return details;
}

export function normalizeTime(isoString) {
  const value = new Date(isoString || 0).getTime();
  return Number.isNaN(value) ? 0 : value;
}

export function findNearestIndex(items, timestampKey, targetIso) {
  if (!items?.length || !targetIso) {
    return null;
  }
  const targetTime = normalizeTime(targetIso);
  let nearestIndex = null;
  let nearestDistance = Number.POSITIVE_INFINITY;
  for (const [index, item] of items.entries()) {
    const distance = Math.abs(normalizeTime(item[timestampKey]) - targetTime);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestIndex = index;
    }
  }
  return nearestIndex;
}

export function scrollIntoContainerView(container, selector) {
  const node = container.querySelector(selector);
  if (!node) {
    return;
  }
  node.scrollIntoView({ block: "center", behavior: "smooth" });
}

export function setElementValue(element, value) {
  if (!element || value == null) {
    return;
  }
  element.value = String(value);
}

export function normalizeDisplayValue(value) {
  if (value == null || value === "") {
    return "default";
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return String(value);
}

export function arrayBufferToBase64(buffer) {
  let binary = "";
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return window.btoa(binary);
}
