import { elements } from "../dom.js";
import { renderState } from "../state.js";
import {
  captureDetailsState,
  createCollapsibleContent,
  escapeHtml,
  formatDate,
  formatElapsedDuration,
  restoreDetailsState,
  stableStringify,
  truncate,
} from "../utils.js";

const traceViewportState = new WeakMap();

const SIMPLE_TRACE_KIND_LABELS = {
  root: "Run Overview",
  region: "Region Pass",
  object: "Object Pass",
  loop: "Repair Loop",
  review: "Review Step",
  node: "Workflow Step",
};

const SIMPLE_TRACE_ROUTE_LABELS = {
  layout_detection: "Analyze overall layout",
  region_detection: "Split the image into regions",
  region_generation: "Generate region SVG content",
  object_generation: "Generate local SVG objects",
  review: "Review the current result",
  repair: "Repair local issues",
  integration: "Integrate the final SVG",
  manual_adjustment: "Apply a local manual adjustment",
};

function normalizeObjectBox(region, object) {
  if (!region?.bbox || !object?.bbox) {
    return null;
  }
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

function shouldShowOverlayLabel(overlay, canvasWidth, canvasHeight) {
  if (!overlay?.bbox || !canvasWidth || !canvasHeight) {
    return false;
  }
  if (overlay.kind === "region") {
    return true;
  }
  return Boolean(overlay.active);
}

function formatOverlayLabel(overlay) {
  const raw = overlay?.label || "";
  if (overlay?.kind !== "object") {
    return raw;
  }
  return raw.replaceAll("_", " ");
}

function getSimpleTraceTitle(node) {
  if (node?.route && SIMPLE_TRACE_ROUTE_LABELS[node.route]) {
    return SIMPLE_TRACE_ROUTE_LABELS[node.route];
  }
  if (node?.kind && SIMPLE_TRACE_KIND_LABELS[node.kind]) {
    return SIMPLE_TRACE_KIND_LABELS[node.kind];
  }
  return node?.label || "Workflow Step";
}

function createImageZoomButton({ src, alt, caption = "" }) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "image-zoom-button";
  button.textContent = "Zoom";
  button.dataset.zoomSrc = src || "";
  button.dataset.zoomAlt = alt || "";
  button.dataset.zoomCaption = caption || "";
  button.setAttribute("aria-label", `Zoom image${alt ? `: ${alt}` : ""}`);
  return button;
}

function buildSelectionOverlay(selectionState, canvasWidth, canvasHeight) {
  if (!selectionState || !selectionState.bbox || !canvasWidth || !canvasHeight) {
    return null;
  }
  const selectionBox = selectionState.bbox;
  if (selectionState.kind === "freeform" && Array.isArray(selectionState.points) && selectionState.points.length > 1) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "selection-shape-overlay");
    svg.setAttribute("viewBox", `0 0 ${canvasWidth} ${canvasHeight}`);
    const polygon = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
    polygon.setAttribute(
      "points",
      selectionState.points.map((point) => `${point.x},${point.y}`).join(" ")
    );
    polygon.setAttribute("class", "selection-shape-polygon");
    svg.appendChild(polygon);

    const bboxElement = document.createElement("div");
    bboxElement.className = "overlay-box selection active";
    bboxElement.style.left = `${(selectionBox.x / canvasWidth) * 100}%`;
    bboxElement.style.top = `${(selectionBox.y / canvasHeight) * 100}%`;
    bboxElement.style.width = `${(selectionBox.width / canvasWidth) * 100}%`;
    bboxElement.style.height = `${(selectionBox.height / canvasHeight) * 100}%`;
    const wrapper = document.createElement("div");
    wrapper.className = "selection-shape-wrapper";
    wrapper.appendChild(svg);
    wrapper.appendChild(bboxElement);
    return wrapper;
  }

  const element = document.createElement("div");
  element.className = "overlay-box selection active";
  element.style.left = `${(selectionBox.x / canvasWidth) * 100}%`;
  element.style.top = `${(selectionBox.y / canvasHeight) * 100}%`;
  element.style.width = `${(selectionBox.width / canvasWidth) * 100}%`;
  element.style.height = `${(selectionBox.height / canvasHeight) * 100}%`;
  const label = document.createElement("div");
  label.className = "overlay-label";
  label.textContent = selectionState.kind === "freeform" ? "freeform" : "selection";
  element.appendChild(label);
  return element;
}

export function buildOverlayBoxes(overlays, canvasWidth, canvasHeight, onSelectOverlay, overlaySelectionEnabled = true) {
  const layer = document.createElement("div");
  layer.className = "overlay-layer";
  if (!canvasWidth || !canvasHeight) {
    return layer;
  }

  for (const overlay of overlays || []) {
    const box = overlay.bbox;
    if (!box) {
      continue;
    }
    const element = document.createElement("div");
    element.className = `overlay-box ${overlay.kind || "region"}${overlay.active ? " active" : ""}`;
    element.style.left = `${(box.x / canvasWidth) * 100}%`;
    element.style.top = `${(box.y / canvasHeight) * 100}%`;
    element.style.width = `${(box.width / canvasWidth) * 100}%`;
    element.style.height = `${(box.height / canvasHeight) * 100}%`;
    if (onSelectOverlay && overlay.selection) {
      element.classList.add("selection");
    }
    if (typeof onSelectOverlay === "function" && overlay.selection !== true && overlaySelectionEnabled) {
      element.role = "button";
      element.tabIndex = 0;
      element.addEventListener("click", (event) => {
        event.stopPropagation();
        onSelectOverlay({
          type: overlay.kind === "object" ? "object" : "region",
          regionId: overlay.regionId || null,
          objectId: overlay.objectId || null,
        });
      });
      element.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelectOverlay({
            type: overlay.kind === "object" ? "object" : "region",
            regionId: overlay.regionId || null,
            objectId: overlay.objectId || null,
          });
        }
      });
    }

    if (shouldShowOverlayLabel(overlay, canvasWidth, canvasHeight)) {
      const label = document.createElement("div");
      label.className = "overlay-label";
      label.textContent = formatOverlayLabel(overlay);
      element.appendChild(label);
    }
    if (overlay.kind === "object") {
      element.title = overlay.label || "";
    }
    layer.appendChild(element);
  }

  return layer;
}

export function createOverlayPreview({
  title,
  previewUrl,
  downloadUrl,
  fallbackText,
  kind,
  canvasWidth,
  canvasHeight,
  overlays = [],
  metaText = "",
  onSelectOverlay = null,
  selectionState = null,
  selectionMode = "select",
  onSelectionChange = null,
}) {
  const wrapper = document.createElement("div");
  if (!previewUrl) {
    wrapper.className = "compare-body empty-state";
    wrapper.textContent = fallbackText;
    return wrapper;
  }

  wrapper.className = "compare-body";
  const stage = document.createElement("div");
  stage.className = "compare-stage";
  const metaRow = document.createElement("div");
  metaRow.className = "compare-stage-meta";
  const titleElement = document.createElement("span");
  titleElement.textContent = title;
  metaRow.appendChild(titleElement);
  const actionGroup = document.createElement("div");
  actionGroup.className = "compare-stage-actions";
  const downloadLink = document.createElement("a");
  downloadLink.href = downloadUrl || previewUrl;
  downloadLink.target = "_blank";
  downloadLink.rel = "noreferrer";
  downloadLink.textContent = "Download";
  actionGroup.appendChild(downloadLink);
  metaRow.appendChild(actionGroup);
  stage.appendChild(metaRow);
  if (metaText) {
    const meta = document.createElement("div");
    meta.className = "output-progress-meta";
    meta.textContent = metaText;
    stage.appendChild(meta);
  }

  const frame = document.createElement("div");
  frame.className = "overlay-stage";
  if (canvasWidth && canvasHeight) {
    frame.style.aspectRatio = `${canvasWidth} / ${canvasHeight}`;
  }
  frame.appendChild(createImageZoomButton({
    src: previewUrl,
    alt: title,
    caption: metaText ? `${title} | ${metaText}` : title,
  }));
  const media = document.createElement("img");
  media.className = kind === "svg" ? "preview-media svg-preview" : "preview-media";
  media.src = previewUrl;
  media.alt = title;
  frame.appendChild(media);
  const overlaySelectionEnabled = selectionMode === "select";
  const overlayLayer = buildOverlayBoxes(
    overlays,
    canvasWidth,
    canvasHeight,
    onSelectOverlay,
    overlaySelectionEnabled,
  );
  const selectionElement = buildSelectionOverlay(selectionState, canvasWidth, canvasHeight);
  if (selectionElement) {
    overlayLayer.appendChild(selectionElement);
  }
  frame.appendChild(overlayLayer);
  const drawingEnabled = selectionMode === "draw-box" || selectionMode === "draw-freeform";
  if (drawingEnabled && typeof onSelectionChange === "function" && canvasWidth && canvasHeight) {
    const drawingSurface = document.createElement("div");
    drawingSurface.className = `drawing-surface ${selectionMode}`;
    const draftLayer = document.createElement("div");
    draftLayer.className = "drawing-surface-draft";
    drawingSurface.appendChild(draftLayer);
    frame.appendChild(drawingSurface);

    let dragStart = null;
    let freeformPoints = [];
    let isDrawing = false;
    let draftShape = null;

    const toCanvasPoint = (pointerEvent) => {
      const rect = drawingSurface.getBoundingClientRect();
      const x = ((pointerEvent.clientX - rect.left) / rect.width) * canvasWidth;
      const y = ((pointerEvent.clientY - rect.top) / rect.height) * canvasHeight;
      return {
        x: Math.max(0, Math.min(canvasWidth, Math.round(x))),
        y: Math.max(0, Math.min(canvasHeight, Math.round(y))),
      };
    };

    const toCanvasBox = (startEvent, moveEvent) => {
      const rect = drawingSurface.getBoundingClientRect();
      const x0 = ((startEvent.clientX - rect.left) / rect.width) * canvasWidth;
      const y0 = ((startEvent.clientY - rect.top) / rect.height) * canvasHeight;
      const x1 = ((moveEvent.clientX - rect.left) / rect.width) * canvasWidth;
      const y1 = ((moveEvent.clientY - rect.top) / rect.height) * canvasHeight;
      const x = Math.max(0, Math.min(x0, x1));
      const y = Math.max(0, Math.min(y0, y1));
      const width = Math.max(1, Math.min(canvasWidth, Math.abs(x1 - x0)));
      const height = Math.max(1, Math.min(canvasHeight, Math.abs(y1 - y0)));
      return {
        x: Math.round(x),
        y: Math.round(y),
        width: Math.round(width),
        height: Math.round(height),
      };
    };

    const toPointSelection = (points) => {
      const xs = points.map((point) => point.x);
      const ys = points.map((point) => point.y);
      const x = Math.min(...xs);
      const y = Math.min(...ys);
      const width = Math.max(1, Math.max(...xs) - x);
      const height = Math.max(1, Math.max(...ys) - y);
      return {
        kind: "freeform",
        points,
        bbox: { x, y, width, height },
        };
    };

    const renderDraftBox = (box) => {
      draftLayer.innerHTML = "";
      draftShape = document.createElement("div");
      draftShape.className = "overlay-box selection drafting";
      draftShape.style.left = `${(box.x / canvasWidth) * 100}%`;
      draftShape.style.top = `${(box.y / canvasHeight) * 100}%`;
      draftShape.style.width = `${(box.width / canvasWidth) * 100}%`;
      draftShape.style.height = `${(box.height / canvasHeight) * 100}%`;
      draftLayer.appendChild(draftShape);
    };

    const renderDraftFreeform = (points) => {
      draftLayer.innerHTML = "";
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "selection-shape-overlay");
      svg.setAttribute("viewBox", `0 0 ${canvasWidth} ${canvasHeight}`);
      const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      polyline.setAttribute("points", points.map((point) => `${point.x},${point.y}`).join(" "));
      polyline.setAttribute("class", "selection-shape-polygon");
      svg.appendChild(polyline);
      draftLayer.appendChild(svg);
    };

    drawingSurface.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (selectionMode === "draw-freeform") {
        freeformPoints = [toCanvasPoint(event)];
        isDrawing = true;
        renderDraftFreeform(freeformPoints);
      } else {
        dragStart = event;
      }
      drawingSurface.setPointerCapture?.(event.pointerId);
    });
    drawingSurface.addEventListener("pointermove", (event) => {
      if (selectionMode === "draw-freeform") {
        if (!isDrawing) {
          return;
        }
        const point = toCanvasPoint(event);
        const lastPoint = freeformPoints[freeformPoints.length - 1];
        if (!lastPoint || Math.abs(point.x - lastPoint.x) + Math.abs(point.y - lastPoint.y) >= 6) {
          freeformPoints = [...freeformPoints, point];
          renderDraftFreeform(freeformPoints);
        }
      } else {
        if (!dragStart) {
          return;
        }
        renderDraftBox(toCanvasBox(dragStart, event));
      }
    });
    drawingSurface.addEventListener("pointerup", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (selectionMode === "draw-freeform") {
        if (!isDrawing) {
          return;
        }
        const point = toCanvasPoint(event);
        freeformPoints = [...freeformPoints, point];
        isDrawing = false;
        draftLayer.innerHTML = "";
        onSelectionChange(toPointSelection(freeformPoints));
      } else {
        if (!dragStart) {
          return;
        }
        const selection = toCanvasBox(dragStart, event);
        dragStart = null;
        draftLayer.innerHTML = "";
        onSelectionChange({
          kind: "box",
          points: [],
          bbox: selection,
        });
      }
      dragStart = null;
      drawingSurface.releasePointerCapture?.(event.pointerId);
    });
    drawingSurface.addEventListener("pointercancel", () => {
      dragStart = null;
      isDrawing = false;
      draftLayer.innerHTML = "";
    });
    drawingSurface.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
  }
  stage.appendChild(frame);
  wrapper.appendChild(stage);
  return wrapper;
}

export function getActiveOverlays(snapshot, selectedOverlay) {
  const overlays = [];
  const selectedRegionId = selectedOverlay?.regionId || null;
  const selectedObjectId = selectedOverlay?.objectId || null;
  const isObjectSelected = Boolean(selectedObjectId);
  for (const region of snapshot?.regions || []) {
    const isActiveRegion = selectedRegionId
      ? region.region_id === selectedRegionId
      : false;
    overlays.push({
      kind: "region",
      label: region.region_id,
      bbox: region.bbox,
      active: isActiveRegion && !selectedObjectId,
      regionId: region.region_id,
      objectId: null,
    });
    if (!selectedRegionId || region.region_id !== selectedRegionId) {
      continue;
    }
    for (const object of region.objects || []) {
      if (!object.bbox) {
        continue;
      }
      overlays.push({
        kind: "object",
        label: object.object_id,
        bbox: normalizeObjectBox(region, object),
        active: isObjectSelected && object.object_id === selectedObjectId,
        regionId: region.region_id,
        objectId: object.object_id,
      });
    }
  }
  return overlays;
}

function hasRefinedObjectOverlays(snapshot) {
  return Boolean(snapshot?.bbox_overlays_ready && snapshot?.regions?.some((region) => (region.objects || []).length));
}

export function renderArtifactStructure(snapshot, selectedOverlay, onSelectOverlay) {
  elements.artifactStructure.innerHTML = "";
  if (!snapshot?.regions?.length) {
    elements.artifactStructure.className = "artifact-structure empty-state";
    elements.artifactStructure.textContent = "No region split yet.";
    return;
  }

  elements.artifactStructure.className = "artifact-structure";
  for (const region of snapshot.regions) {
    const regionCard = document.createElement("article");
    const regionSelected = selectedOverlay.regionId === region.region_id;
    const regionActive = regionSelected && !selectedOverlay.objectId;
    regionCard.className = `structure-card${regionActive ? " active" : ""}`;
    regionCard.innerHTML = `
      <div class="structure-title-row">
        <div class="structure-title">${escapeHtml(region.region_id)}</div>
        <div class="structure-meta">${region.retry_used ?? 0}/${region.retry_limit ?? "-"} retries${region.retry_exhausted ? " | exhausted" : ""}</div>
      </div>
      <div class="structure-meta">bbox ${region.bbox.x}, ${region.bbox.y}, ${region.bbox.width}, ${region.bbox.height}</div>
      <div class="structure-description">${escapeHtml(truncate(region.description, 180))}</div>
    `;
    regionCard.addEventListener("click", () => onSelectOverlay({ type: "region", regionId: region.region_id, objectId: null }));

    const objectList = document.createElement("div");
    objectList.className = "structure-object-list";
    for (const object of region.objects || []) {
      const objectCard = document.createElement("div");
      const objectActive = selectedOverlay.objectId === object.object_id;
      objectCard.className = `structure-object${objectActive ? " active" : ""}`;
      objectCard.innerHTML = `
        <div class="structure-title-row">
          <div class="structure-title">${escapeHtml(object.object_id)}</div>
          <div class="structure-meta">${escapeHtml(object.object_type || "-")}</div>
        </div>
        <div class="structure-meta">${object.retry_used ?? 0}/${object.retry_limit ?? "-"} retries${object.retry_exhausted ? " | exhausted" : ""}</div>
        <div class="structure-description">${escapeHtml(truncate(object.description, 140))}</div>
      `;
      objectCard.addEventListener("click", (event) => {
        event.stopPropagation();
        onSelectOverlay({ type: "object", regionId: region.region_id, objectId: object.object_id });
      });
      objectList.appendChild(objectCard);
    }
    if (objectList.childElementCount > 0 && regionSelected) {
      regionCard.appendChild(objectList);
    }
    elements.artifactStructure.appendChild(regionCard);
  }
}

export function renderOutputProgress(snapshot, selectedOutputFrameIndex, onFrameChange) {
  elements.outputProgress.innerHTML = "";
  elements.outputProgressSlider.innerHTML = "";
  if (!snapshot?.output_frames?.length) {
    elements.outputProgress.className = "output-progress empty-state";
    elements.outputProgress.textContent = "No progressive output frames yet.";
    elements.outputProgressSlider.className = "output-progress output-progress-inline empty-state";
    elements.outputProgressSlider.textContent = "No output frames yet.";
    elements.outputProgressDetails.className = "output-progress-details hidden";
    elements.outputProgressDetails.textContent = "";
    return;
  }

  elements.outputProgress.className = "output-progress";
  elements.outputProgressSlider.className = "output-progress output-progress-inline";
  const sliderShell = document.createElement("div");
  sliderShell.className = "output-progress-slider-shell";
  sliderShell.style.setProperty("--output-frame-count", String(snapshot.output_frames.length));
  const range = document.createElement("input");
  range.type = "range";
  range.className = "output-progress-range";
  range.min = "0";
  range.max = String(snapshot.output_frames.length - 1);
  range.value = String(selectedOutputFrameIndex);
  range.step = "1";
  range.addEventListener("input", (event) => {
    onFrameChange(Number.parseInt(event.target.value, 10) || 0);
  });
  sliderShell.appendChild(range);

  const markerRow = document.createElement("div");
  markerRow.className = "output-progress-marker-row";
  for (const [index, frameItem] of snapshot.output_frames.entries()) {
    const marker = document.createElement("button");
    marker.type = "button";
    marker.className = `output-progress-marker${index === selectedOutputFrameIndex ? " active" : ""}`;
    marker.title = `${index + 1}. ${frameItem.title}`;
    marker.setAttribute("aria-label", `View output version ${index + 1}: ${frameItem.title}`);
    marker.addEventListener("click", () => {
      onFrameChange(index);
    });
    markerRow.appendChild(marker);
  }
  sliderShell.appendChild(markerRow);
  elements.outputProgressSlider.appendChild(sliderShell);

  const frame = snapshot.output_frames[selectedOutputFrameIndex];
  const frameCard = document.createElement("div");
  frameCard.className = "output-progress-frame";
  frameCard.innerHTML = `
    <div class="structure-title-row">
      <div class="structure-title">${escapeHtml(frame.title)}</div>
      <div class="structure-meta">${selectedOutputFrameIndex + 1}/${snapshot.output_frames.length}</div>
    </div>
    <div class="output-progress-meta">Version: ${escapeHtml(frame.scope)}${frame.target_id ? ` | ${escapeHtml(frame.target_id)}` : ""}${frame.iteration != null ? ` | iter ${frame.iteration}` : ""}</div>
  `;
  frameCard.appendChild(buildOutputProgressSections(frame));
  elements.outputProgress.appendChild(frameCard);
  elements.outputProgressDetails.className = "output-progress-details hidden";
  elements.outputProgressDetails.innerHTML = "";
}

function buildOutputProgressSections(frame) {
  const wrapper = document.createElement("div");
  wrapper.className = "output-progress-sections";
  const updateSummary = frame?.update_summary || [];
  const remainingIssues = frame?.remaining_issues || [];
  wrapper.innerHTML = `
    <div class="output-progress-section">
      <div class="output-progress-section-title">Changes</div>
      ${
        updateSummary.length
          ? `<ul class="output-progress-list">${updateSummary.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
          : `<div class="output-progress-empty">No explicit change summary was recorded for this version.</div>`
      }
    </div>
    <div class="output-progress-section">
      <div class="output-progress-section-title">Issues</div>
      ${
        remainingIssues.length
          ? `<ul class="output-progress-list">${remainingIssues.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
          : `<div class="output-progress-empty">No remaining issues were recorded for this version.</div>`
      }
    </div>
  `;
  return wrapper;
}

function computeNodeElapsed(node) {
  if (typeof node?.duration_ms === "number") {
    return node.duration_ms;
  }
  if (node?.started_at && node?.ended_at) {
    return Math.max(0, new Date(node.ended_at).getTime() - new Date(node.started_at).getTime());
  }
  if (node?.started_at) {
    return Math.max(0, Date.now() - new Date(node.started_at).getTime());
  }
  return 0;
}

function createDurationElement(node) {
  const duration = document.createElement("span");
  duration.className = "workflow-trace-duration";
  const live = node?.status === "running" || node?.status === "retrying";
  if (!live && typeof node?.duration_ms === "number") {
    duration.dataset.elapsedDuration = String(node.duration_ms);
  }
  if (live && node?.started_at) {
    duration.dataset.elapsedStart = node.started_at;
    duration.dataset.elapsedEnded = node.ended_at || "";
  }
  duration.textContent = formatElapsedDuration(computeNodeElapsed(node));
  return duration;
}

function createTraceCard(node, activeNodeId, onNodeSelect) {
  const card = document.createElement(node.event_index != null ? "button" : "div");
  card.className = `workflow-trace-card ${node.status} ${node.kind}${activeNodeId === node.node_id ? " active" : ""}`;
  if (card instanceof HTMLButtonElement) {
    card.type = "button";
    card.addEventListener("click", () => onNodeSelect?.(node));
  }

  const top = document.createElement("div");
  top.className = "workflow-trace-card-top";
  const title = document.createElement("div");
  title.className = "workflow-trace-card-title";
  title.textContent = document.body?.dataset?.uiMode === "simple" ? getSimpleTraceTitle(node) : node.label;
  top.appendChild(title);
  top.appendChild(createDurationElement(node));
  card.appendChild(top);

  if (node.semantic_stage && (node.kind === "region" || node.kind === "loop")) {
    const stage = document.createElement("div");
    stage.className = `workflow-trace-stage ${node.status}`;
    stage.textContent = node.semantic_stage;
    card.appendChild(stage);
  }

  const badgeRow = document.createElement("div");
  badgeRow.className = "workflow-trace-badges";
  const statusBadge = document.createElement("span");
  statusBadge.className = `workflow-trace-badge ${node.status}`;
  statusBadge.textContent = node.status.replaceAll("_", " ");
  badgeRow.appendChild(statusBadge);
  if (node.execution_mode === "parallel") {
    const badge = document.createElement("span");
    badge.className = "workflow-trace-badge neutral";
    badge.textContent = "parallel";
    badgeRow.appendChild(badge);
  }
  if (node.route) {
    const badge = document.createElement("span");
    badge.className = "workflow-trace-badge neutral";
    badge.textContent = node.route;
    badgeRow.appendChild(badge);
  }
  if (typeof node.iteration === "number") {
    const badge = document.createElement("span");
    badge.className = "workflow-trace-badge neutral";
    badge.textContent = `iter ${node.iteration}`;
    badgeRow.appendChild(badge);
  }
  const retries = Number(node.meta?.retries_total || node.meta?.retry_used || 0);
  if (retries > 0) {
    const badge = document.createElement("span");
    badge.className = "workflow-trace-badge neutral";
    badge.textContent = `loop x${retries}`;
    badgeRow.appendChild(badge);
  }
  card.appendChild(badgeRow);

  if (node.summary) {
    const summary = document.createElement("div");
    summary.className = "workflow-trace-summary-text";
    summary.textContent = node.summary;
    card.appendChild(summary);
  }
  return card;
}

function buildTraceTree(node, childrenByParent, activeNodeId, onNodeSelect, depth = 0) {
  const lane = document.createElement("div");
  lane.className = `workflow-trace-lane ${depth === 0 ? "root-lane" : "nested-lane"}`;
  lane.appendChild(createTraceCard(node, activeNodeId, onNodeSelect));
  const children = childrenByParent.get(node.node_id) || [];
  if (children.length) {
    const branch = document.createElement("div");
    branch.className = `workflow-trace-branch ${children.length > 1 ? "parallel" : "serial"}`;
    if (node.kind === "region" && children.length === 1 && children[0]?.kind === "loop") {
      lane.classList.add("has-sidecar-loop");
      branch.classList.add("sidecar-loop");
    }
    for (const child of children) {
      branch.appendChild(buildTraceTree(child, childrenByParent, activeNodeId, onNodeSelect, depth + 1));
    }
    lane.appendChild(branch);
  }
  return lane;
}

function filterTraceNodes(nodes = []) {
  const visibleNodeIds = new Set();
  for (const node of nodes) {
    if (!node) {
      continue;
    }
    if (node.status !== "pending" || node.kind === "stage" || node.kind === "terminal") {
      visibleNodeIds.add(node.node_id);
    }
  }
  if (!visibleNodeIds.size) {
    return [];
  }
  const nodesById = new Map(nodes.map((node) => [node.node_id, node]));
  for (const nodeId of [...visibleNodeIds]) {
    let current = nodesById.get(nodeId);
    while (current?.parent_node_id) {
      visibleNodeIds.add(current.parent_node_id);
      current = nodesById.get(current.parent_node_id);
    }
  }
  return nodes.filter((node) => visibleNodeIds.has(node.node_id));
}

export function renderTraceInto(container, trace, emptyText, onNodeSelect = () => {}) {
  container.innerHTML = "";
  const visibleNodes = filterTraceNodes(trace?.nodes || []);
  if (!visibleNodes.length) {
    container.className = "workflow-trace empty-state";
    container.textContent = emptyText;
    return;
  }

  const summary = trace.summary || {};
  container.className = "workflow-trace";
  const controls = document.createElement("div");
  controls.className = "workflow-trace-controls";
  controls.innerHTML = `
    <div class="workflow-trace-toolbar">
      <div class="workflow-trace-summary">
        <span class="workflow-trace-chip">${escapeHtml(summary.status || "idle")}</span>
        <span class="workflow-trace-chip workflow-trace-total-duration">${formatElapsedDuration(summary.total_duration_ms || 0)} total</span>
        <span class="workflow-trace-chip">${summary.loop_iterations_total || 0} loop iterations</span>
        <span class="workflow-trace-chip">${summary.regions_total || 0} regions</span>
        <span class="workflow-trace-chip">${summary.retrying_regions || 0} retrying</span>
        <span class="workflow-trace-chip">${summary.blocked_regions || 0} blocked</span>
      </div>
      <div class="workflow-trace-zoom-group">
        <span class="workflow-trace-controls-label">View</span>
        <button class="workflow-trace-control-btn" type="button" data-trace-zoom="out">-</button>
        <button class="workflow-trace-control-btn" type="button" data-trace-zoom="reset">Reset</button>
        <button class="workflow-trace-control-btn" type="button" data-trace-zoom="in">+</button>
      </div>
    </div>
  `;
  container.appendChild(controls);

  const viewport = document.createElement("div");
  viewport.className = "workflow-trace-viewport";
  const canvas = document.createElement("div");
  canvas.className = "workflow-trace-canvas";
  const body = document.createElement("div");
  body.className = "workflow-trace-body";
  const childrenByParent = new Map();
  const roots = [];
  for (const node of visibleNodes) {
    const parentId = node.parent_node_id || "__root__";
    if (!childrenByParent.has(parentId)) {
      childrenByParent.set(parentId, []);
    }
    childrenByParent.get(parentId).push(node);
    if (!node.parent_node_id) {
      roots.push(node);
    }
  }
  for (const node of roots) {
    body.appendChild(buildTraceTree(node, childrenByParent, summary.active_node_id, onNodeSelect));
  }
  canvas.appendChild(body);
  viewport.appendChild(canvas);
  container.appendChild(viewport);

  initializeTraceViewport(viewport, canvas, body, controls);
  if ((summary.status === "running" || summary.status === "retrying") && trace?.nodes?.length) {
    const startedCandidates = trace.nodes
      .map((node) => node?.started_at)
      .filter(Boolean)
      .map((value) => new Date(value).getTime())
      .filter((value) => Number.isFinite(value));
    const earliestStart = startedCandidates.length ? Math.min(...startedCandidates) : null;
    const totalChip = controls.querySelector(".workflow-trace-total-duration");
    if (earliestStart && totalChip instanceof HTMLElement) {
      totalChip.dataset.elapsedStart = new Date(earliestStart).toISOString();
      totalChip.dataset.elapsedEnded = "";
    }
  }
  requestAnimationFrame(refreshWorkflowTraceLayout);
}

export function renderWorkflowTrace(snapshot, onNodeSelect = () => {}) {
  const trace = snapshot?.workflow_trace;
  renderTraceInto(
    elements.workflowTrace,
    trace || null,
    "Workflow trace appears here when the run starts.",
    onNodeSelect,
  );
}

export function renderManualWorkflowTrace(snapshot, onNodeSelect = () => {}) {
  renderTraceInto(
    elements.manualAdjustmentTrace,
    snapshot?.manual_workflow_trace || null,
    "Manual Adjustment trace appears here after you start it.",
    onNodeSelect,
  );
  const errorPayload = snapshot?.manual_adjustment_error;
  if (errorPayload?.message) {
    elements.manualAdjustmentError.classList.remove("hidden");
    elements.manualAdjustmentError.textContent = `${errorPayload.error_type || "Error"}: ${errorPayload.message}`;
  } else {
    elements.manualAdjustmentError.classList.add("hidden");
    elements.manualAdjustmentError.textContent = "";
  }
}

function appendFailureDiagnostic(container, diagnostic) {
  if (!diagnostic) {
    return;
  }
  const panel = document.createElement("div");
  panel.className = "error-box diagnostic-card";
  const header = document.createElement("div");
  header.className = "diagnostic-card-header";
  header.innerHTML = `
    <div class="diagnostic-card-heading">
      <strong class="diagnostic-card-title">Failed at ${escapeHtml(diagnostic.failure_stage || diagnostic.terminal_stage || "-")}</strong>
      <p class="diagnostic-card-message">${escapeHtml(diagnostic.summary || diagnostic.error_message || "Execution failed.")}</p>
    </div>
  `;
  panel.appendChild(header);

  const meta = document.createElement("div");
  meta.className = "diagnostic-card-meta";
  const rows = [];
  if (diagnostic.error_type || diagnostic.error_message) {
    rows.push(`<div><span class="summary-label">Error</span><span class="summary-value">${escapeHtml(`${diagnostic.error_type || "Error"}${diagnostic.error_message ? ` | ${diagnostic.error_message}` : ""}`)}</span></div>`);
  }
  if (diagnostic.root_cause_type || diagnostic.root_cause_message) {
    rows.push(`<div><span class="summary-label">Root cause</span><span class="summary-value">${escapeHtml(`${diagnostic.root_cause_type || "-"}${diagnostic.root_cause_message ? ` | ${diagnostic.root_cause_message}` : ""}`)}</span></div>`);
  }
  if (diagnostic.last_event_title) {
    rows.push(`<div><span class="summary-label">Last event</span><span class="summary-value">${escapeHtml(diagnostic.last_event_title)}</span></div>`);
  }
  if (diagnostic.attempt != null || diagnostic.attempts_total != null) {
    rows.push(`<div><span class="summary-label">Attempt</span><span class="summary-value">${escapeHtml(`${diagnostic.attempt ?? "-"} / ${diagnostic.attempts_total ?? "-"}`)}</span></div>`);
  }
  meta.innerHTML = rows.join("");
  panel.appendChild(meta);

  const links = [];
  if (diagnostic.request_path) {
    links.push(`Request payload: ${diagnostic.request_path}`);
  }
  if (diagnostic.raw_response_path) {
    links.push(`Raw response: ${diagnostic.raw_response_path}`);
  }
  if (diagnostic.artifact_hints?.length) {
    for (const item of diagnostic.artifact_hints) {
      links.push(`${item.label}: ${item.relative_path}`);
    }
  }
  if (links.length) {
    const linkBox = document.createElement("div");
    linkBox.className = "diagnostic-card-links";
    linkBox.innerHTML = links.map((item) => `<span class="diagnostic-link-chip">${escapeHtml(item)}</span>`).join("");
    panel.appendChild(linkBox);
  }
  container.appendChild(panel);
}

export function refreshWorkflowTraceLayout() {
  for (const viewport of document.querySelectorAll(".workflow-trace-viewport")) {
    const canvas = viewport.querySelector(".workflow-trace-canvas");
    const body = viewport.querySelector(".workflow-trace-body");
    if (!(viewport instanceof HTMLElement) || !(canvas instanceof HTMLElement) || !(body instanceof HTMLElement)) {
      continue;
    }
    const viewportWidth = viewport.clientWidth;
    const contentWidth = body.scrollWidth;
    const contentHeight = body.scrollHeight;
    if (!viewportWidth || !contentWidth) {
      body.style.removeProperty("--trace-scale");
      canvas.style.removeProperty("width");
      canvas.style.removeProperty("height");
      continue;
    }
    const state = traceViewportState.get(viewport) || {
      fitScale: 1,
      zoomMultiplier: 1,
      dragPointerId: null,
      dragStartX: 0,
      dragStartY: 0,
      dragScrollLeft: 0,
      dragScrollTop: 0,
      controls: null,
    };
    const fitScale = Math.min(1, viewportWidth / contentWidth);
    state.fitScale = fitScale || 1;
    const currentScale = Math.max(0.2, Math.min(4, state.fitScale * (state.zoomMultiplier || 1)));
    traceViewportState.set(viewport, state);
    body.style.setProperty("--trace-scale", String(currentScale));
    canvas.style.width = `${Math.ceil(contentWidth * currentScale)}px`;
    canvas.style.height = `${Math.ceil(contentHeight * currentScale)}px`;
    updateTraceControlState(viewport);
  }
}

function updateTraceControlState(viewport) {
  const state = traceViewportState.get(viewport);
  if (!state?.controls) {
    return;
  }
  const label = state.controls.querySelector(".workflow-trace-controls-label");
  if (label) {
    const viewPercent = Math.max(20, Math.min(400, Math.round((state.zoomMultiplier || 1) * 100)));
    label.textContent = `View ${viewPercent}%`;
  }
}

function initializeTraceViewport(viewport, canvas, body, controls) {
  const previous = traceViewportState.get(viewport);
  const state = previous || {
    fitScale: 1,
    zoomMultiplier: 1,
    dragPointerId: null,
    dragStartX: 0,
    dragStartY: 0,
    dragScrollLeft: 0,
    dragScrollTop: 0,
    controls,
  };
  state.controls = controls;
  traceViewportState.set(viewport, state);

  if (viewport.dataset.traceViewportInitialized === "true") {
    return;
  }
  viewport.dataset.traceViewportInitialized = "true";

  controls.addEventListener("click", (event) => {
    const liveState = traceViewportState.get(viewport);
    const target = event.target instanceof Element ? event.target.closest("[data-trace-zoom]") : null;
    const action = target?.getAttribute("data-trace-zoom");
    if (!action || !liveState) {
      return;
    }
    event.preventDefault();
    if (action === "in") {
      liveState.zoomMultiplier = Math.min(4, (liveState.zoomMultiplier || 1) * 1.15);
    } else if (action === "out") {
      liveState.zoomMultiplier = Math.max(0.2, (liveState.zoomMultiplier || 1) / 1.15);
    } else {
      liveState.zoomMultiplier = 1;
      viewport.scrollLeft = 0;
      viewport.scrollTop = 0;
    }
    refreshWorkflowTraceLayout();
  });

  viewport.addEventListener("pointerdown", (event) => {
    const liveState = traceViewportState.get(viewport);
    if (!liveState) {
      return;
    }
    if (event.target instanceof Element && event.target.closest(".workflow-trace-control-btn, .workflow-trace-card")) {
      return;
    }
    liveState.dragPointerId = event.pointerId;
    liveState.dragStartX = event.clientX;
    liveState.dragStartY = event.clientY;
    liveState.dragScrollLeft = viewport.scrollLeft;
    liveState.dragScrollTop = viewport.scrollTop;
    viewport.classList.add("is-dragging");
    viewport.setPointerCapture?.(event.pointerId);
  });

  viewport.addEventListener("pointermove", (event) => {
    const liveState = traceViewportState.get(viewport);
    if (!liveState || liveState.dragPointerId !== event.pointerId) {
      return;
    }
    event.preventDefault();
    viewport.scrollLeft = liveState.dragScrollLeft - (event.clientX - liveState.dragStartX);
    viewport.scrollTop = liveState.dragScrollTop - (event.clientY - liveState.dragStartY);
  });

  const stopDrag = (event) => {
    const liveState = traceViewportState.get(viewport);
    if (!liveState || liveState.dragPointerId !== event.pointerId) {
      return;
    }
    liveState.dragPointerId = null;
    viewport.classList.remove("is-dragging");
    viewport.releasePointerCapture?.(event.pointerId);
  };
  viewport.addEventListener("pointerup", stopDrag);
  viewport.addEventListener("pointercancel", stopDrag);
}

export function updateWorkflowTraceTimers() {
  for (const element of document.querySelectorAll("[data-elapsed-start]")) {
    const startedAt = element.dataset.elapsedStart;
    const endedAt = element.dataset.elapsedEnded;
    const frozenDuration = Number.parseInt(element.dataset.elapsedDuration || "", 10);
    if (!startedAt) {
      continue;
    }
    let durationMs = 0;
    if (Number.isFinite(frozenDuration) && frozenDuration > 0) {
      durationMs = frozenDuration;
    } else if (endedAt) {
      durationMs = Math.max(0, new Date(endedAt).getTime() - new Date(startedAt).getTime());
    } else {
      durationMs = Math.max(0, Date.now() - new Date(startedAt).getTime());
    }
    element.textContent = formatElapsedDuration(durationMs);
  }
}

export function getLatestManualAdjustment(snapshot) {
  const versions = snapshot?.manual_adjustments || [];
  return versions.length ? versions[versions.length - 1] : null;
}

function renderOutputVersionOptions(snapshot, selectedManualAdjustmentId, onManualAdjustmentChange) {
  elements.outputVersionSelect.innerHTML = "";
  const baseOption = document.createElement("button");
  baseOption.type = "button";
  baseOption.className = `ghost-btn compact-btn${selectedManualAdjustmentId ? "" : " active-version"}`;
  baseOption.textContent = "Pipeline";
  baseOption.addEventListener("click", () => onManualAdjustmentChange(null));
  elements.outputVersionSelect.appendChild(baseOption);

  for (const adjustment of snapshot?.manual_adjustments || []) {
    const option = document.createElement("button");
    option.type = "button";
    option.className = `ghost-btn compact-btn${selectedManualAdjustmentId === adjustment.adjustment_id ? " active-version" : ""}`;
    option.textContent = adjustment.title;
    option.addEventListener("click", () => onManualAdjustmentChange(adjustment.adjustment_id));
    elements.outputVersionSelect.appendChild(option);
  }
}

export function renderArtifactSummary(
  snapshot,
  selectedOverlay,
  selectedOutputFrameIndex,
  onSelectOverlay,
  onFrameChange,
  previewState = {},
  selectedManualAdjustmentId = null,
  onManualAdjustmentChange = () => {},
  onTraceNodeSelect = () => {}
) {
  const {
    inputSelectionState = null,
    inputSelectionMode = "select",
    onInputSelectionChange = null,
    outputSelectionState = null,
    outputSelectionMode = "select",
    onOutputSelectionChange = null,
  } = previewState || {};
  const signature = stableStringify({
    snapshot: snapshot || { available: false },
    selectedOverlay,
    selectedOutputFrameIndex,
    selectedManualAdjustmentId,
    inputSelectionState,
    inputSelectionMode,
    outputSelectionState,
    outputSelectionMode,
  });
  if (renderState.artifactSig === signature) {
    return;
  }

  const hasSnapshot = Boolean(snapshot);
  const hasInputPreview = Boolean(snapshot?.previews?.input_image_url);
  const hasRegionData = Boolean(snapshot?.regions?.length);
  const hasRegionOverlayData = hasRegionData;
  const hasRefinedOverlayData = hasRefinedObjectOverlays(snapshot);
  const hasOutputPreview = Boolean(
    snapshot?.previews?.output_svg_url
    || snapshot?.previews?.output_png_url
    || snapshot?.previews?.initial_svg_url
  );
  const hasOutputFrames = Boolean(snapshot?.output_frames?.length);
  const hasUsableOutput = hasOutputPreview || hasOutputFrames;
  const isArtifactReady = Boolean(snapshot?.available);

  if (!hasSnapshot) {
    elements.resumeRun.disabled = true;
    elements.artifactStatus.textContent = "No artifacts yet.";
    elements.artifactSummary.className = "artifact-summary";
    elements.artifactSummaryContent.className = "artifact-summary-content empty-state";
    elements.artifactSummaryContent.textContent = "Run files, previews, and downloads appear here.";
    elements.artifactMonitorPanel.open = false;
    elements.compareInput.replaceChildren(createOverlayPreview({
      title: "Input",
      previewUrl: null,
      fallbackText: "No input preview yet.",
    }));
    elements.outputVersionSelect.innerHTML = "";
    elements.compareOutput.replaceChildren(createOverlayPreview({
      title: "Output",
      previewUrl: null,
      fallbackText: "No output preview yet.",
    }));
    elements.artifactStructure.className = "artifact-structure empty-state";
    elements.artifactStructure.textContent = "No region split yet.";
    elements.workflowTrace.className = "workflow-trace empty-state";
    elements.workflowTrace.textContent = "Workflow trace appears here when the run starts.";
    elements.outputProgress.className = "output-progress empty-state";
    elements.outputProgress.textContent = "No progressive output frames yet.";
    elements.outputProgressSlider.className = "output-progress output-progress-inline empty-state";
    elements.outputProgressSlider.textContent = "No output frames yet.";
    elements.outputProgressDetails.className = "output-progress-details hidden";
    elements.outputProgressDetails.textContent = "";
    renderState.artifactSig = signature;
    return;
  }

  if (!isArtifactReady) {
    elements.resumeRun.disabled = true;
    const stageText = snapshot?.failure_stage || snapshot?.current_stage || "-";
    elements.artifactStatus.textContent = `${snapshot?.project_name || "artifact"} | ${snapshot?.status || "in progress"} | ${stageText}`;
    elements.artifactSummary.className = "artifact-summary";
    elements.artifactSummaryContent.className = "artifact-summary-content empty-state";
    elements.artifactSummaryContent.textContent = hasRefinedOverlayData
      ? "Region and object boxes are ready."
      : hasRegionData
        ? "Region boxes are ready. Object boxes will appear after refine finishes."
        : "Preparing artifact data.";

    const activeOverlays = hasRegionOverlayData ? getActiveOverlays(snapshot, selectedOverlay) : [];
    elements.compareInput.replaceChildren(createOverlayPreview({
      title: "Input image",
      previewUrl: hasInputPreview ? snapshot.previews.input_image_url : null,
      downloadUrl: hasInputPreview ? `${snapshot.previews.input_image_url}&download=true` : null,
      fallbackText: "No input preview yet.",
      kind: "image",
      canvasWidth: snapshot?.canvas_width,
      canvasHeight: snapshot?.canvas_height,
      overlays: activeOverlays,
      onSelectOverlay,
      selectionState: inputSelectionState,
      selectionMode: inputSelectionMode,
      onSelectionChange: onInputSelectionChange,
    }));

    elements.compareOutput.replaceChildren(createOverlayPreview({
      title: "Output",
      previewUrl: hasOutputPreview
        ? (snapshot.previews.output_svg_url || snapshot.previews.output_png_url || snapshot.previews.initial_svg_url)
        : null,
      downloadUrl: hasOutputPreview
        ? `${snapshot.previews.output_svg_url || snapshot.previews.output_png_url || snapshot.previews.initial_svg_url}&download=true`
        : null,
      fallbackText: "Output preview will appear once the current stage produces it.",
      kind: "svg",
      canvasWidth: snapshot?.canvas_width,
      canvasHeight: snapshot?.canvas_height,
      overlays: activeOverlays,
      onSelectOverlay,
      selectionState: outputSelectionState,
      selectionMode: outputSelectionMode,
      onSelectionChange: onOutputSelectionChange,
    }));

    renderArtifactStructure(hasRegionOverlayData ? snapshot : { ...snapshot, regions: [] }, selectedOverlay, onSelectOverlay);
    renderWorkflowTrace(snapshot, onTraceNodeSelect);
    renderOutputVersionOptions(snapshot, selectedManualAdjustmentId, onManualAdjustmentChange);
    if (hasOutputFrames) {
      renderOutputProgress(snapshot, selectedOutputFrameIndex, onFrameChange);
    } else {
      elements.outputProgress.className = "output-progress empty-state";
      elements.outputProgress.textContent = hasUsableOutput
        ? "The current preview is available before progressive frames are recorded."
        : "Progressive output frames will appear when available.";
      elements.outputProgressSlider.className = "output-progress output-progress-inline empty-state";
      elements.outputProgressSlider.textContent = hasUsableOutput ? "Preview ready." : "No output frames yet.";
      elements.outputProgressDetails.className = "output-progress-details hidden";
      elements.outputProgressDetails.textContent = "";
    }
    renderState.artifactSig = signature;
    return;
  }

  elements.artifactStatus.textContent = `${snapshot.project_name || "artifact"} | ${snapshot.status || "unknown"} | ${snapshot.failure_stage || snapshot.current_stage || "-"}`;
  elements.artifactSummary.className = "artifact-summary";
  elements.artifactSummaryContent.className = "artifact-summary-content";
  const detailsState = captureDetailsState(elements.artifactSummaryContent);
  elements.artifactSummaryContent.innerHTML = "";
  appendFailureDiagnostic(elements.artifactSummaryContent, snapshot.failure_diagnostic);

  const request = snapshot.request || {};
  const overview = snapshot.overview || {};
  const resume = snapshot.resume || {};
  const quickSummary = document.createElement("div");
  quickSummary.className = "artifact-summary-quick-grid";
  quickSummary.innerHTML = `
    <div class="artifact-summary-quick-card">
      <span class="summary-label">Run state</span>
      <span class="summary-value">${escapeHtml(snapshot.status || "-")}</span>
    </div>
    <div class="artifact-summary-quick-card">
      <span class="summary-label">Stage</span>
      <span class="summary-value">${escapeHtml(snapshot.failure_stage || snapshot.current_stage || "-")}</span>
    </div>
    <div class="artifact-summary-quick-card">
      <span class="summary-label">Resume</span>
      <span class="summary-value">${resume.available ? escapeHtml(resume.resume_stage || "available") : "not available"}</span>
    </div>
    <div class="artifact-summary-quick-card">
      <span class="summary-label">Budget</span>
      <span class="summary-value">${resume.budget_used ?? "-"} / ${resume.budget_limit ?? request.max_budget ?? "-"}</span>
    </div>
    <div class="artifact-summary-quick-card">
      <span class="summary-label">Workflow</span>
      <span class="summary-value">${escapeHtml(request.workflow_mode || "-")} / ${escapeHtml(request.region_processing_mode || "-")}</span>
    </div>
    <div class="artifact-summary-quick-card">
      <span class="summary-label">Canvas</span>
      <span class="summary-value">${snapshot.canvas_width ?? "-"} x ${snapshot.canvas_height ?? "-"}</span>
    </div>
  `;
  elements.artifactSummaryContent.appendChild(quickSummary);

  const details = document.createElement("details");
  details.className = "artifact-summary-details";
  details.dataset.persistKey = "artifact-summary-details";
  const summary = document.createElement("summary");
  summary.innerHTML = `
    <div class="artifact-summary-details-title">
      <span class="artifact-summary-details-label">Run Details</span>
      <span class="artifact-summary-details-copy">Full request, runtime, and captured overview.</span>
    </div>
    <span class="artifact-summary-details-state">Expand</span>
  `;
  details.appendChild(summary);
  const detailsBody = document.createElement("div");
  detailsBody.className = "artifact-summary-details-body";
  const summaryList = document.createElement("div");
  summaryList.className = "summary-grid artifact-summary-section-grid";
  summaryList.innerHTML = `
    <div><span class="summary-label">Run ID</span><span class="summary-value">${escapeHtml(snapshot.run_id || "-")}</span></div>
    <div><span class="summary-label">Artifact dir</span><span class="summary-value">${escapeHtml(snapshot.artifact_dir || "-")}</span></div>
    <div><span class="summary-label">Resume</span><span class="summary-value">${resume.available ? "available" : "no"}</span></div>
    <div><span class="summary-label">Resume stage</span><span class="summary-value">${escapeHtml(resume.resume_stage || "-")}</span></div>
    <div><span class="summary-label">Pause reason</span><span class="summary-value">${escapeHtml(resume.pause_reason || resume.reason || "-")}</span></div>
    <div><span class="summary-label">Budget used</span><span class="summary-value">${resume.budget_used ?? "-"} / ${resume.budget_limit ?? "-"}</span></div>
    <div><span class="summary-label">Budget remaining</span><span class="summary-value">${resume.budget_remaining ?? "-"}</span></div>
    <div><span class="summary-label">Completed / Pending regions</span><span class="summary-value">${resume.completed_regions ?? 0} / ${resume.pending_regions ?? 0}</span></div>
    <div><span class="summary-label">Image path</span><span class="summary-value">${escapeHtml(request.image_path || "-")}</span></div>
    <div><span class="summary-label">Base URL</span><span class="summary-value">${escapeHtml(request.base_url || "-")}</span></div>
    <div><span class="summary-label">API</span><span class="summary-value">${escapeHtml(request.api_provider || "-")} / ${escapeHtml(request.api_format || "-")}</span></div>
    <div><span class="summary-label">API retries</span><span class="summary-value">${request.max_retries ?? "-"}</span></div>
    <div><span class="summary-label">Agent models</span><span class="summary-value">${escapeHtml(request.agent_model || "-")} / ${escapeHtml(request.subagent_model || "-")}</span></div>
    <div><span class="summary-label">Agent name</span><span class="summary-value">${escapeHtml(request.agent_name || "-")}</span></div>
    <div><span class="summary-label">Use previous response ID</span><span class="summary-value">${request.use_previous_response_id ?? "-"}</span></div>
    <div><span class="summary-label">Repair / Budget</span><span class="summary-value">${request.max_retry ?? "-"} / ${request.max_budget ?? "-"}</span></div>
    <div><span class="summary-label">Supervisor memory use</span><span class="summary-value">${request.supervisor_memory_enabled ?? "-"}</span></div>
    <div><span class="summary-label">Memory artifact persist</span><span class="summary-value">${request.supervisor_memory_persist_enabled ?? "-"}</span></div>
    <div><span class="summary-label">Strategy hints</span><span class="summary-value">${request.strategy_enabled ?? "-"}</span></div>
    <div><span class="summary-label">Workflow</span><span class="summary-value">${escapeHtml(request.workflow_mode || "-")}</span></div>
    <div><span class="summary-label">Region mode</span><span class="summary-value">${escapeHtml(request.region_processing_mode || "-")} / ${request.region_concurrency || "-"}</span></div>
    <div><span class="summary-label">Regions total</span><span class="summary-value">${overview.regions_total ?? "-"}</span></div>
    <div><span class="summary-label">Canvas</span><span class="summary-value">${snapshot.canvas_width ?? "-"} x ${snapshot.canvas_height ?? "-"}</span></div>
  `;
  detailsBody.appendChild(summaryList);
  elements.resumeRun.disabled = !resume.available;

  const noteGrid = document.createElement("div");
  noteGrid.className = "artifact-note-grid";
  if (request.message) {
    const messageCard = document.createElement("div");
    messageCard.className = "artifact-note";
    messageCard.innerHTML = '<div class="artifact-note-title">Task Message</div>';
    messageCard.appendChild(
      createCollapsibleContent(request.message, {
        maxLength: 260,
        key: "artifact-request-message",
        })
    );
    noteGrid.appendChild(messageCard);
  }

  if (overview.layout_overview) {
    const overviewCard = document.createElement("div");
    overviewCard.className = "artifact-note";
    overviewCard.innerHTML = '<div class="artifact-note-title">Layout Overview</div>';
    overviewCard.appendChild(
      createCollapsibleContent(overview.layout_overview, {
        maxLength: 260,
        key: "artifact-layout-overview",
        })
    );
    noteGrid.appendChild(overviewCard);
  }
  if (noteGrid.childElementCount > 0) {
    detailsBody.appendChild(noteGrid);
  }
  details.appendChild(detailsBody);
  details.addEventListener("toggle", () => {
    const stateLabel = summary.querySelector(".artifact-summary-details-state");
    if (stateLabel) {
      stateLabel.textContent = details.open ? "Collapse" : "Expand";
    }
  });
  elements.artifactSummaryContent.appendChild(details);
  restoreDetailsState(elements.artifactSummaryContent, detailsState);
  if (!detailsState.has("artifact-summary-details")) {
    details.open = false;
  }
  const stateLabel = summary.querySelector(".artifact-summary-details-state");
  if (stateLabel) {
    stateLabel.textContent = details.open ? "Collapse" : "Expand";
  }

  const inputUrl = snapshot.previews?.input_image_url || null;
  const outputUrl = snapshot.previews?.output_svg_url || snapshot.previews?.output_png_url || snapshot.previews?.initial_svg_url || null;
  const activeOverlays = getActiveOverlays(snapshot, selectedOverlay);
  const activeFrame = snapshot.output_frames?.[selectedOutputFrameIndex] || null;
  const activeAdjustment = (snapshot.manual_adjustments || []).find(
    (item) => item.adjustment_id === selectedManualAdjustmentId
  ) || null;
  renderOutputVersionOptions(snapshot, selectedManualAdjustmentId, onManualAdjustmentChange);
  elements.compareInput.replaceChildren(createOverlayPreview({
    title: "Input image",
    previewUrl: inputUrl,
    downloadUrl: inputUrl ? `${inputUrl}&download=true` : null,
    fallbackText: "No input preview yet.",
    kind: "image",
    canvasWidth: snapshot.canvas_width,
    canvasHeight: snapshot.canvas_height,
    overlays: activeOverlays,
    onSelectOverlay,
    selectionState: inputSelectionState,
    selectionMode: inputSelectionMode,
    onSelectionChange: onInputSelectionChange,
  }));
  elements.compareOutput.replaceChildren(createOverlayPreview({
    title: activeAdjustment?.title || activeFrame?.title || (snapshot.previews?.output_svg_url ? "Final SVG" : snapshot.previews?.output_png_url ? "Final PNG" : "Initial SVG"),
    previewUrl: activeAdjustment?.preview_url || activeFrame?.preview_url || outputUrl,
    downloadUrl: activeAdjustment?.download_url || activeFrame?.download_url || (outputUrl ? `${outputUrl}&download=true` : null),
    fallbackText: "No output preview yet.",
    kind: "svg",
    canvasWidth: snapshot.canvas_width,
    canvasHeight: snapshot.canvas_height,
    overlays: activeOverlays,
    metaText: activeAdjustment
      ? `Adjusted${activeAdjustment.base_title ? ` | base ${activeAdjustment.base_title}` : ""}`
      : activeFrame
        ? `${activeFrame.scope}${activeFrame.iteration != null ? ` | iter ${activeFrame.iteration}` : ""}`
        : "",
    onSelectOverlay,
    selectionState: outputSelectionState,
    selectionMode: outputSelectionMode,
    onSelectionChange: onOutputSelectionChange,
  }));

  renderArtifactStructure(snapshot, selectedOverlay, onSelectOverlay);
  renderWorkflowTrace(snapshot, onTraceNodeSelect);
  renderOutputProgress(snapshot, selectedOutputFrameIndex, onFrameChange);
  renderState.artifactSig = signature;
}

export function renderArtifactFiles(snapshot) {
  const signature = stableStringify({
    files: snapshot?.files || [],
    runId: snapshot?.run_id || null,
  });
  if (renderState.artifactFilesSig === signature) {
    return;
  }

  elements.artifactFiles.innerHTML = "";
  if (!snapshot || !snapshot.available || !snapshot.files || snapshot.files.length === 0) {
    elements.artifactFiles.className = "artifact-files empty-state";
    elements.artifactFiles.textContent = "No artifact files yet.";
    renderState.artifactFilesSig = signature;
    return;
  }

  elements.artifactFiles.className = "artifact-files";
  for (const file of snapshot.files) {
    const item = document.createElement("article");
    item.className = "artifact-file";
    const previewLink = file.preview_url
      ? `<a href="${file.preview_url}" target="_blank" rel="noreferrer">Preview</a>`
      : "";
    item.innerHTML = `
      <div class="artifact-file-main">
        <div class="artifact-file-name">${escapeHtml(file.relative_path)}</div>
        <div class="artifact-file-meta">${escapeHtml(file.kind)} | ${file.size_bytes} bytes | ${formatDate(file.modified_at)}</div>
      </div>
      <div class="artifact-file-actions">
        ${previewLink}
        <a href="${file.download_url}" target="_blank" rel="noreferrer">Download</a>
      </div>
    `;
    elements.artifactFiles.appendChild(item);
  }
  renderState.artifactFilesSig = signature;
}

export function clearArtifactPanel() {
  renderArtifactSummary({ available: false }, { type: "region", regionId: null, objectId: null }, 0, () => {}, () => {}, {});
  renderArtifactFiles({ available: false, files: [] });
}
