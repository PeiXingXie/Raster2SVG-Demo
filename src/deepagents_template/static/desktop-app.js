import { fetchJson } from "./js/api-client.js";
import { appState } from "./js/state.js";
import { renderState } from "./js/state.js";

const casePreviewCache = new Map();
const casePreviewRequestCache = new Map();
const casePreviewImageCache = new Map();
const casePreviewInFlight = new Set();
const casePreviewQueued = new Set();
let casePreviewPumpScheduled = false;
let casePreviewObserver = null;
const PROCESS_GUIDE_ORDER = ["upload", "trace", "manual", "download"];
const PROCESS_GUIDE_AUTOPLAY_MS = 5000;
let processGuideAutoplayTimer = null;

appState.desktopHistoryPageSize = 6;

function refreshDesktopHistory() {
  renderState.recentRunsSig = null;
  try {
    window.dispatchEvent(new CustomEvent("desktop-history-change"));
  } catch {
    window.dispatchEvent(new Event("resize"));
  }
}

function setHistoryFilter(status) {
  const validStatuses = new Set(["all", "completed", "failed", "paused"]);
  appState.desktopHistoryFilter = validStatuses.has(status) ? status : "all";
  appState.desktopHistoryPage = 1;
  for (const button of document.querySelectorAll(".desktop-history-filter")) {
    const active = button.getAttribute("data-history-status") === appState.desktopHistoryFilter;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  }
  refreshDesktopHistory();
}

function setupDesktopHistoryControls() {
  for (const button of document.querySelectorAll(".desktop-history-filter")) {
    button.addEventListener("click", () => {
      setHistoryFilter(button.getAttribute("data-history-status") || "all");
    });
  }
  const searchInput = document.getElementById("desktop-history-search");
  if (searchInput instanceof HTMLInputElement) {
    searchInput.value = appState.desktopHistorySearch || "";
    searchInput.addEventListener("input", () => {
      appState.desktopHistorySearch = searchInput.value;
      appState.desktopHistoryPage = 1;
      refreshDesktopHistory();
    });
  }
  const sortSelect = document.getElementById("desktop-history-sort");
  if (sortSelect instanceof HTMLSelectElement) {
    sortSelect.value = appState.desktopHistorySort || "updated_desc";
    sortSelect.addEventListener("change", () => {
      appState.desktopHistorySort = sortSelect.value;
      appState.desktopHistoryPage = 1;
      refreshDesktopHistory();
    });
  }
  document.getElementById("desktop-history-prev")?.addEventListener("click", () => {
    appState.desktopHistoryPage = Math.max(1, appState.desktopHistoryPage - 1);
    refreshDesktopHistory();
  });
  document.getElementById("desktop-history-next")?.addEventListener("click", () => {
    appState.desktopHistoryPage += 1;
    refreshDesktopHistory();
  });
  setHistoryFilter(appState.desktopHistoryFilter || "all");
}

function dispatchProcessGuideChange() {
  try {
    window.dispatchEvent(new CustomEvent("desktop-process-guide-change"));
  } catch {
    window.dispatchEvent(new Event("resize"));
  }
}

function setProcessGuideStep(step) {
  appState.desktopProcessGuideStep = PROCESS_GUIDE_ORDER.includes(step) ? step : PROCESS_GUIDE_ORDER[0];
  dispatchProcessGuideChange();
}

function scheduleProcessGuideAutoplay() {
  window.clearTimeout(processGuideAutoplayTimer);
  processGuideAutoplayTimer = window.setTimeout(() => {
    if (document.hidden || document.body.dataset.desktopPage !== "start") {
      scheduleProcessGuideAutoplay();
      return;
    }
    const currentStep = PROCESS_GUIDE_ORDER.includes(appState.desktopProcessGuideStep)
      ? appState.desktopProcessGuideStep
      : PROCESS_GUIDE_ORDER[0];
    const nextIndex = (PROCESS_GUIDE_ORDER.indexOf(currentStep) + 1) % PROCESS_GUIDE_ORDER.length;
    setProcessGuideStep(PROCESS_GUIDE_ORDER[nextIndex]);
    scheduleProcessGuideAutoplay();
  }, PROCESS_GUIDE_AUTOPLAY_MS);
}

function setupDesktopProcessGuideControls() {
  for (const button of document.querySelectorAll("[data-process-target]")) {
    button.addEventListener("click", () => {
      setProcessGuideStep(button.getAttribute("data-process-target") || "upload");
      scheduleProcessGuideAutoplay();
    });
  }
  setProcessGuideStep(appState.desktopProcessGuideStep || PROCESS_GUIDE_ORDER[0]);
  scheduleProcessGuideAutoplay();
}

function setupDesktopChrome() {
  const navButtons = Array.from(document.querySelectorAll("[data-desktop-page-target]"));
  const validPages = new Set(["start", "history", "workspace", "settings"]);
  const refineToggle = document.getElementById("desktop-refine-toggle");
  const refineClose = document.getElementById("desktop-refine-close");
  const refreshTraceLayout = () => {
    window.setTimeout(() => {
      try {
        window.dispatchEvent(new Event("resize"));
      } catch {
        // Ignore resize notification failures.
      }
    }, 40);
  };

  const setDesktopPage = (page) => {
    const nextPage = validPages.has(page) ? page : "start";
    document.body.dataset.desktopPage = nextPage;
    for (const button of navButtons) {
      button.classList.toggle("is-active", button.getAttribute("data-desktop-page-target") === nextPage);
    }
    if (nextPage !== "workspace") {
      document.body.dataset.refineSidebar = "collapsed";
      if (refineToggle) {
        refineToggle.setAttribute("aria-expanded", "false");
      }
    }
    if (nextPage === "workspace") {
      refreshTraceLayout();
    }
    if (nextPage === "start") {
      scheduleProcessGuideAutoplay();
    }
  };

  document.body.dataset.uiMode = "simple";
  document.body.dataset.refineSidebar = document.body.dataset.refineSidebar || "collapsed";
  document.getElementById("app-shell")?.setAttribute("data-ui-mode", "simple");

  for (const button of navButtons) {
    button.addEventListener("click", () => {
      setDesktopPage(button.getAttribute("data-desktop-page-target"));
    });
  }

  document.addEventListener(
    "click",
    (event) => {
      const target = event.target instanceof Element ? event.target : null;
      if (!target) {
        return;
      }
      if (target.closest("#send-btn")) {
        window.setTimeout(() => setDesktopPage("workspace"), 0);
      }
      if (target.closest("#recent-runs button") && !target.closest(".run-chip-preview-zoom")) {
        window.setTimeout(() => setDesktopPage("workspace"), 0);
      }
    },
    true,
  );

  refineToggle?.addEventListener("click", () => {
    const expanded = document.body.dataset.refineSidebar === "expanded";
    document.body.dataset.refineSidebar = expanded ? "collapsed" : "expanded";
    refineToggle.setAttribute("aria-expanded", expanded ? "false" : "true");
    refreshTraceLayout();
  });

  refineClose?.addEventListener("click", () => {
    document.body.dataset.refineSidebar = "collapsed";
    refineToggle?.setAttribute("aria-expanded", "false");
    refreshTraceLayout();
  });

  setDesktopPage(document.body.dataset.desktopPage || "start");
}

function getDesktopRunList() {
  const snapshot = appState.snapshot;
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
  return runs;
}

function getPreviewUrl(snapshot, kind) {
  if (kind === "input") {
    return snapshot?.previews?.input_image_url || null;
  }
  return snapshot?.previews?.output_svg_url
    || snapshot?.previews?.output_png_url
    || snapshot?.previews?.initial_svg_url
    || null;
}

function decodeCasePreviewImage(url) {
  if (!url) {
    return Promise.resolve(null);
  }
  if (casePreviewImageCache.has(url)) {
    return casePreviewImageCache.get(url);
  }
  const promise = new Promise((resolve, reject) => {
    const image = new Image();
    image.decoding = "async";
    image.loading = "eager";
    image.onload = async () => {
      try {
        if (typeof image.decode === "function") {
          await image.decode();
        }
      } catch {
        // Some browsers report decode failures for already-loaded SVGs; keep the loaded image.
      }
      resolve(url);
    };
    image.onerror = () => reject(new Error(`Preview failed to load: ${url}`));
    image.src = url;
  });
  casePreviewImageCache.set(url, promise);
  promise.catch(() => {
    casePreviewImageCache.delete(url);
  });
  return promise;
}

function preloadCasePreviewUrls(urls) {
  return Promise.allSettled((urls || []).filter(Boolean).map((url) => decodeCasePreviewImage(url)));
}

function createPreviewPane(label, url, emptyText = "Preview pending") {
  const pane = document.createElement("div");
  pane.className = "run-chip-preview-pane";

  const labelNode = document.createElement("div");
  labelNode.className = "run-chip-preview-label";
  labelNode.textContent = label;

  const frame = document.createElement("div");
  frame.className = "run-chip-preview-frame";

  if (url) {
    const button = document.createElement("button");
    button.className = "run-chip-preview-zoom";
    button.type = "button";
    button.dataset.previewSrc = url;
    button.dataset.previewAlt = `${label} preview`;
    button.dataset.previewCaption = label;
    button.title = `Open ${label.toLowerCase()} preview`;

    const img = document.createElement("img");
    img.src = url;
    img.alt = `${label} preview`;
    img.decoding = "async";
    img.loading = "eager";
    img.addEventListener("error", () => {
      frame.replaceChildren(createPreviewEmpty("Preview unavailable"));
    }, { once: true });

    button.appendChild(img);
    frame.appendChild(button);
  } else {
    frame.appendChild(createPreviewEmpty(emptyText));
  }

  pane.append(labelNode, frame);
  return pane;
}

function createPreviewEmpty(text) {
  const empty = document.createElement("div");
  empty.className = "run-chip-preview-empty";
  empty.textContent = text;
  return empty;
}

function getCasePreviewCacheKey(run) {
  return `${run?.run_id || ""}:${run?.artifact_revision || ""}`;
}

async function getCasePreviewSnapshot(threadId, run) {
  const cacheKey = getCasePreviewCacheKey(run);
  if (casePreviewCache.has(cacheKey)) {
    return casePreviewCache.get(cacheKey);
  }
  if (!casePreviewRequestCache.has(cacheKey)) {
    const request = fetchJson(`/threads/${encodeURIComponent(threadId)}/artifacts?run_id=${encodeURIComponent(run.run_id)}`)
      .then((snapshot) => {
        casePreviewCache.set(cacheKey, snapshot);
        return snapshot;
      })
      .catch((error) => {
        casePreviewRequestCache.delete(cacheKey);
        throw error;
      });
    casePreviewRequestCache.set(cacheKey, request);
  }
  return casePreviewRequestCache.get(cacheKey);
}

async function hydrateCasePreview(card) {
  const runId = card.dataset.runId;
  const run = getDesktopRunList().find((item) => item.run_id === runId);
  const preview = card.querySelector(".run-chip-preview");
  if (!runId || !run?.artifact_dir || !preview) {
    return;
  }
  if (preview.dataset.previewState === "ready" && preview.querySelector(".run-chip-preview-zoom")) {
    return;
  }
  const threadId = appState.threadId || document.getElementById("thread-id")?.textContent?.trim();
  if (!threadId || threadId === "Not created yet") {
    return;
  }
  const loadToken = getCasePreviewCacheKey(run);
  preview.dataset.previewState = "loading";
  preview.dataset.previewToken = loadToken;
  const snapshot = await getCasePreviewSnapshot(threadId, run);
  const inputUrl = getPreviewUrl(snapshot, "input");
  const outputUrl = getPreviewUrl(snapshot, "output");
  if (!inputUrl && !outputUrl) {
    if (preview.dataset.previewToken === loadToken) {
      preview.replaceChildren(
        createPreviewPane("Input", null),
        createPreviewPane("Output", null),
      );
      preview.dataset.previewState = "empty";
    }
    return;
  }
  await preloadCasePreviewUrls([inputUrl, outputUrl]);
  if (!card.isConnected || preview.dataset.previewToken !== loadToken) {
    return;
  }
  preview.replaceChildren(
    createPreviewPane("Input", inputUrl),
    createPreviewPane("Output", outputUrl),
  );
  preview.dataset.previewState = inputUrl || outputUrl ? "ready" : "empty";
}

function shouldDeferCasePreview(card) {
  if (!casePreviewObserver || typeof card.getBoundingClientRect !== "function") {
    return false;
  }
  const rect = card.getBoundingClientRect();
  const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
  return rect.top > viewportHeight + 160 || rect.bottom < -160;
}

function queueCasePreview(card) {
  const runId = card.dataset.runId;
  const run = getDesktopRunList().find((item) => item.run_id === runId);
  const cacheKey = getCasePreviewCacheKey(run);
  if (shouldDeferCasePreview(card)) {
    casePreviewObserver.observe(card);
    return;
  }
  if (!runId || casePreviewCache.has(cacheKey) || casePreviewInFlight.has(runId)) {
    if (casePreviewCache.has(cacheKey)) {
      void hydrateCasePreview(card);
    }
    return;
  }
  casePreviewQueued.add(runId);
  if (casePreviewPumpScheduled) {
    return;
  }
  casePreviewPumpScheduled = true;
  window.setTimeout(pumpCasePreviewQueue, 80);
}

function pumpCasePreviewQueue() {
  casePreviewPumpScheduled = false;
  if (casePreviewInFlight.size >= 3) {
    window.setTimeout(pumpCasePreviewQueue, 120);
    return;
  }
  const [runId] = casePreviewQueued;
  if (!runId) {
    return;
  }
  casePreviewQueued.delete(runId);
  const card = Array.from(document.querySelectorAll("#recent-runs .run-chip"))
    .find((item) => item.dataset.runId === runId);
  if (!card) {
    window.setTimeout(pumpCasePreviewQueue, 0);
    return;
  }
  casePreviewInFlight.add(runId);
  hydrateCasePreview(card)
    .catch(() => {
      const preview = card.querySelector(".run-chip-preview");
      if (preview) {
        preview.dataset.previewState = "failed";
      }
    })
    .finally(() => {
      casePreviewInFlight.delete(runId);
      if (casePreviewQueued.size) {
        window.setTimeout(pumpCasePreviewQueue, 0);
      }
    });
  if (casePreviewQueued.size && casePreviewInFlight.size < 3) {
    window.setTimeout(pumpCasePreviewQueue, 0);
  }
}

function ensureCasePreviewSlots() {
  if (!document.body.classList.contains("desktop-body")) {
    return;
  }
  const runs = getDesktopRunList();
  for (const [index, card] of Array.from(document.querySelectorAll("#recent-runs .run-chip")).entries()) {
    const run = card.dataset.runId
      ? runs.find((item) => item.run_id === card.dataset.runId) || null
      : runs[index] || null;
    if (run?.run_id && card.dataset.runId !== run.run_id) {
      card.dataset.runId = run.run_id;
    }
    if (card.querySelector(".run-chip-preview")) {
      queueCasePreview(card);
      continue;
    }
    const preview = document.createElement("div");
    preview.className = "run-chip-preview";
    preview.dataset.previewState = "reserved";
    preview.replaceChildren(
      createPreviewPane("Input", null),
      createPreviewPane("Output", null),
    );
    const metaRow = card.querySelector(".run-chip-meta-row");
    if (metaRow) {
      card.insertBefore(preview, metaRow);
    } else {
      card.appendChild(preview);
    }
    queueCasePreview(card);
  }
}

function setupCasePreviewSlotObserver() {
  ensureCasePreviewSlots();
  const recentRuns = document.getElementById("recent-runs");
  if (!recentRuns || !("MutationObserver" in window)) {
    return;
  }
  if ("IntersectionObserver" in window) {
    casePreviewObserver = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) {
          continue;
        }
        casePreviewObserver?.unobserve(entry.target);
        if (entry.target instanceof HTMLElement) {
          queueCasePreview(entry.target);
        }
      }
    }, { root: recentRuns, rootMargin: "180px 0px" });
  }
  const observer = new MutationObserver((mutations) => {
    if (!mutations.some((mutation) => mutation.addedNodes.length || mutation.removedNodes.length)) {
      return;
    }
    window.requestAnimationFrame(ensureCasePreviewSlots);
  });
  observer.observe(recentRuns, { childList: true });
}

function setupDesktopImageLightbox() {
  const lightbox = document.getElementById("image-lightbox");
  const image = document.getElementById("image-lightbox-image");
  const caption = document.getElementById("image-lightbox-caption");
  const closeButton = document.getElementById("image-lightbox-close");
  const backdrop = document.getElementById("image-lightbox-backdrop");

  const openLightbox = (button) => {
    if (!lightbox || !image) {
      return;
    }
    const src = button.dataset.previewSrc || "";
    if (!src) {
      return;
    }
    image.src = src;
    image.alt = button.dataset.previewAlt || "Expanded preview";
    if (caption) {
      caption.textContent = button.dataset.previewCaption || button.dataset.previewAlt || "";
    }
    lightbox.classList.remove("hidden");
    lightbox.setAttribute("aria-hidden", "false");
    document.body.classList.add("lightbox-open");
  };

  const closeLightbox = () => {
    if (!lightbox || !image) {
      return;
    }
    lightbox.classList.add("hidden");
    lightbox.setAttribute("aria-hidden", "true");
    image.removeAttribute("src");
    image.alt = "Expanded preview";
    if (caption) {
      caption.textContent = "";
    }
    document.body.classList.remove("lightbox-open");
  };

  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const previewButton = target?.closest(".run-chip-preview-zoom");
    if (previewButton instanceof HTMLButtonElement) {
      event.preventDefault();
      event.stopPropagation();
      openLightbox(previewButton);
      return;
    }
    if (event.target === backdrop || event.target === closeButton) {
      event.preventDefault();
      closeLightbox();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && lightbox && !lightbox.classList.contains("hidden")) {
      closeLightbox();
    }
  });
}

setupDesktopChrome();
setupDesktopHistoryControls();
setupDesktopProcessGuideControls();
setupCasePreviewSlotObserver();
setupDesktopImageLightbox();

void (async () => {
  try {
    const { initApp } = await import("./js/main.js?v=desktop-history-layout-fit-1");
    await initApp();
  } catch (error) {
    console.error("Desktop app initialization failed", error);
    const statusText = document.getElementById("status-text");
    if (statusText) {
      statusText.textContent = "Backend unavailable";
    }
  }
})();
