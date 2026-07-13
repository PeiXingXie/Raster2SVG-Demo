const DEFAULT_LOADING_ICON_URL = "/static/assets/icon/icon-transparent.png";

export function createLoadingState({
  label = "Loading",
  message = "Please wait...",
  iconUrl = DEFAULT_LOADING_ICON_URL,
  fill = true,
  compact = false,
  className = "",
} = {}) {
  const root = document.createElement("div");
  root.className = [
    "desktop-loading-state",
    fill ? "desktop-loading-state--fill" : "",
    compact ? "desktop-loading-state--compact" : "",
    className,
  ].filter(Boolean).join(" ");
  root.dataset.loadingStateRoot = "true";
  root.setAttribute("role", "status");
  root.setAttribute("aria-live", "polite");

  const visual = document.createElement("div");
  visual.className = "desktop-loading-state__visual";
  visual.setAttribute("aria-hidden", "true");

  const icon = document.createElement("div");
  icon.className = "desktop-loading-state__icon";
  icon.style.setProperty("--desktop-loading-icon-url", `url("${iconUrl}")`);

  const baseLayer = document.createElement("span");
  baseLayer.className = "desktop-loading-state__icon-layer desktop-loading-state__icon-layer--base";

  const sweepLayer = document.createElement("span");
  sweepLayer.className = "desktop-loading-state__icon-layer desktop-loading-state__icon-layer--sweep";

  icon.append(baseLayer, sweepLayer);
  visual.appendChild(icon);
  root.appendChild(visual);

  if (label) {
    const labelNode = document.createElement("div");
    labelNode.className = "desktop-loading-state__label";
    labelNode.textContent = label;
    root.appendChild(labelNode);
  }

  if (message) {
    const messageNode = document.createElement("div");
    messageNode.className = "desktop-loading-state__message";
    messageNode.textContent = message;
    root.appendChild(messageNode);
  }

  return root;
}

export function renderLoadingState(container, options = {}) {
  if (!(container instanceof HTMLElement)) {
    return null;
  }
  const loadingState = createLoadingState(options);
  container.replaceChildren(loadingState);
  return loadingState;
}
