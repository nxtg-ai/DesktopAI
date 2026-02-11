/** Shared DOM references and application state. */

import { AvatarEngine } from "/static/avatar.js";

// ── DOM References ──

export const statusEl = document.getElementById("status");
export const currentTitleEl = document.getElementById("current-title");
export const currentMetaEl = document.getElementById("current-meta");
export const currentCategoryEl = document.getElementById("current-category");
export const currentIdleEl = document.getElementById("current-idle");
export const currentTimeEl = document.getElementById("current-time");
export const currentAppEl = document.getElementById("current-app");
export const eventCountEl = document.getElementById("event-count");
export const eventsEl = document.getElementById("events");
export const eventSearchEl = document.getElementById("event-search");
export const eventCategoryEl = document.getElementById("event-category");
export const eventTypeEl = document.getElementById("event-type");
export const ollamaStatusEl = document.getElementById("ollama-status");
export const ollamaDetailEl = document.getElementById("ollama-detail");
export const ollamaModelSelectEl = document.getElementById("ollama-model-select");
export const ollamaModelRefreshBtn = document.getElementById("ollama-model-refresh-btn");
export const ollamaModelApplyBtn = document.getElementById("ollama-model-apply-btn");
export const ollamaModelResetBtn = document.getElementById("ollama-model-reset-btn");
export const ollamaModelMetaEl = document.getElementById("ollama-model-meta");
export const ollamaProbeBtn = document.getElementById("ollama-probe-btn");
export const ollamaProbeResultEl = document.getElementById("ollama-probe-result");
export const summaryBtn = document.getElementById("summary-btn");
export const summaryReadBtn = document.getElementById("summary-read-btn");
export const summaryText = document.getElementById("summary-text");
export const executorStatusEl = document.getElementById("executor-status");
export const executorPreflightResultEl = document.getElementById("executor-preflight-result");
export const executorPreflightBtn = document.getElementById("executor-preflight-btn");
export const executorPreflightChecksEl = document.getElementById("executor-preflight-checks");
export const plannerModeSelectEl = document.getElementById("planner-mode-select");
export const plannerModeApplyBtn = document.getElementById("planner-mode-apply-btn");
export const plannerModeResetBtn = document.getElementById("planner-mode-reset-btn");
export const plannerModeMetaEl = document.getElementById("planner-mode-meta");
export const readinessStatusResultEl = document.getElementById("readiness-status-result");
export const readinessStatusRefreshBtn = document.getElementById("readiness-status-refresh-btn");
export const readinessStatusChecksEl = document.getElementById("readiness-status-checks");
export const avatarCanvas = document.getElementById("avatar-canvas");
export const voiceStateEl = document.getElementById("voice-state");
export const voiceEngineEl = document.getElementById("voice-engine");
export const voiceTextEl = document.getElementById("voice-text");
export const voiceTranscriptEl = document.getElementById("voice-transcript");
export const micBtn = document.getElementById("mic-btn");
export const speakBtn = document.getElementById("speak-btn");
export const sttStatusEl = document.getElementById("stt-status");
export const autonomyStatusEl = document.getElementById("autonomy-status");
export const autonomyObjectiveEl = document.getElementById("autonomy-objective");
export const autonomyMaxIterationsEl = document.getElementById("autonomy-max-iterations");
export const autonomyParallelAgentsEl = document.getElementById("autonomy-parallel-agents");
export const autonomyLevelEl = document.getElementById("autonomy-level");
export const autonomyStartBtn = document.getElementById("autonomy-start-btn");
export const autonomyApproveBtn = document.getElementById("autonomy-approve-btn");
export const autonomyCancelBtn = document.getElementById("autonomy-cancel-btn");
export const readinessGateBtn = document.getElementById("readiness-gate-btn");
export const autonomyRunMetaEl = document.getElementById("autonomy-run-meta");
export const readinessGateResultEl = document.getElementById("readiness-gate-result");
export const readinessMatrixObjectivesEl = document.getElementById("readiness-matrix-objectives");
export const readinessMatrixBtn = document.getElementById("readiness-matrix-btn");
export const readinessMatrixResultEl = document.getElementById("readiness-matrix-result");
export const readinessMatrixResultsEl = document.getElementById("readiness-matrix-results");
export const autonomyLogEl = document.getElementById("autonomy-log");
export const journeySessionEl = document.getElementById("journey-session");
export const journeyRefreshBtn = document.getElementById("journey-refresh-btn");
export const journeyMetaEl = document.getElementById("journey-meta");
export const journeyEventsEl = document.getElementById("journey-events");
export const journeyEventCountEl = document.getElementById("journey-event-count");
export const runtimeLogsRefreshBtn = document.getElementById("runtime-logs-refresh-btn");
export const runtimeLogsMetaEl = document.getElementById("runtime-logs-meta");
export const runtimeLogCountEl = document.getElementById("runtime-log-count");
export const runtimeLogsEl = document.getElementById("runtime-logs");
export const runtimeLogsSearchEl = document.getElementById("runtime-logs-search");
export const runtimeLogsLevelEl = document.getElementById("runtime-logs-level");
export const runtimeLogsClearBtn = document.getElementById("runtime-logs-clear-btn");
export const runtimeLogsCorrelateBtn = document.getElementById("runtime-logs-correlate-btn");
export const collectorStatusEl = document.getElementById("collector-status");
export const personalityModeEl = document.getElementById("personality-mode");
export const chatStatusEl = document.getElementById("chat-status");
export const chatContextIndicatorEl = document.getElementById("chat-context-indicator");
export const chatMessagesEl = document.getElementById("chat-messages");
export const chatWelcomeEl = document.getElementById("chat-welcome");
export const chatInputEl = document.getElementById("chat-input");
export const chatSendBtn = document.getElementById("chat-send-btn");
export const chatSuggestionBtns = document.querySelectorAll(".chat-suggestion");
export const visionStatusEl = document.getElementById("vision-status");
export const visionWindowTitleEl = document.getElementById("vision-window-title");
export const visionProcessEl = document.getElementById("vision-process");
export const visionTimestampEl = document.getElementById("vision-timestamp");
export const visionUiaTextEl = document.getElementById("vision-uia-text");
export const visionScreenshotStatusEl = document.getElementById("vision-screenshot-status");
export const visionRefreshBtn = document.getElementById("vision-refresh-btn");

// ── Avatar ──

export const avatar = new AvatarEngine(avatarCanvas);

// ── Constants ──

export const MAX_EVENTS = 50;
export const TELEMETRY_BATCH_SIZE = 50;
export const TELEMETRY_FLUSH_INTERVAL_MS = 4000;
export const JOURNEY_POLL_MS = 5000;
export const RUNTIME_LOG_LIMIT = 120;

// ── Mutable App State ──

export const appState = {
  events: [],
  ws: null,
  recognition: null,
  recognitionActive: false,
  recognitionSupported: false,
  recognitionTranscript: "",
  mediaStream: null,
  audioContext: null,
  analyser: null,
  audioData: null,
  meterRaf: null,
  currentUtterance: null,
  speechActive: false,
  activeRunId: null,
  activeApprovalToken: null,
  lastWindowFingerprint: "",
  lastStatusText: "",
  lastRunFingerprint: "",
  telemetryQueue: [],
  telemetryFlushTimer: null,
  telemetryFlushInFlight: false,
  journeyPollTimer: null,
  activeJourneySessionId: "",
  runtimeLogsViewMode: "live",
  runtimeLogsCorrelatedSessionId: "",
  chatSending: false,
  lastVisionContext: null,
  conversationId: null,
};

// ── Telemetry Session ID ──

export const telemetrySessionId = (() => {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return `ui-${window.crypto.randomUUID()}`;
  }
  return `ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
})();
window.__desktopaiTelemetrySessionId = telemetrySessionId;

// ── Helpers ──

export function formatTime(ts) {
  if (!ts) return "\u2014";
  const date = new Date(ts);
  return date.toLocaleString();
}
