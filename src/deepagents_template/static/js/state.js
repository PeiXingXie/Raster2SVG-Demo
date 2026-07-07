export const DEFAULT_MESSAGE = "Convert this image into SVG format";

export const renderState = {
  messagesSig: null,
  approvalSig: null,
  recentRunsSig: null,
  runSummarySig: null,
  timelineSig: null,
  artifactSig: null,
  artifactFilesSig: null,
  effectiveSig: null,
};

export const appState = {
  artifactCache: new Map(),
  artifactRequestInFlight: false,
  defaults: null,
  defaultsLoaded: false,
  frontendHostInfo: null,
  hostCapabilities: {
    hostMode: "web",
    frontendUrl: null,
    platform: null,
    canOpenLocalFilePicker: false,
  },
  latestArtifactSnapshot: null,
  linkedMessageIndex: null,
  localUpload: null,
  desktopHistoryFilter: "all",
  desktopHistoryPage: 1,
  desktopHistoryPageSize: 6,
  desktopHistorySearch: "",
  desktopHistorySort: "updated_desc",
  desktopProcessGuideStep: null,
  runtimeOverrides: null,
  manualAdjustmentBaseRunId: null,
  manualAdjustmentRequestInFlight: false,
  manualAdjustmentPollTimer: null,
  manualConfirmedTarget: null,
  manualConfirmedReferenceSelection: null,
  manualCustomReferenceConfirmed: false,
  manualReferenceUploads: [],
  manualReferenceSelectionMode: "select",
  manualReferenceSelectionShape: null,
  manualSelectionBox: null,
  manualSelectionMode: "select",
  manualSelectionShape: null,
  messagePreset: "default",
  pendingApproval: null,
  selectedEventIndex: null,
  selectedManualAdjustmentId: null,
  selectedOutputFrameIndex: 0,
  selectedOverlay: { type: "region", regionId: null, objectId: null },
  selectedRunId: null,
  snapshot: null,
  snapshotRequestInFlight: false,
  snapshotTimer: null,
  artifactTimer: null,
  threadId: null,
  uiMode: "simple",
};

export function resetRenderState() {
  for (const key of Object.keys(renderState)) {
    renderState[key] = null;
  }
}

export function resetUiSelections() {
  appState.selectedRunId = null;
  appState.selectedEventIndex = null;
  appState.linkedMessageIndex = null;
  appState.selectedOverlay = { type: "region", regionId: null, objectId: null };
  appState.selectedManualAdjustmentId = null;
  appState.selectedOutputFrameIndex = 0;
  appState.manualSelectionBox = null;
  appState.manualSelectionShape = null;
  appState.manualSelectionMode = "select";
  appState.manualConfirmedTarget = null;
  appState.manualConfirmedReferenceSelection = null;
  appState.manualCustomReferenceConfirmed = false;
  appState.manualReferenceSelectionMode = "select";
  appState.manualReferenceSelectionShape = null;
  appState.manualReferenceUploads = [];
}
