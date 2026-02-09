import { AvatarEngine } from "/static/avatar.js";

const statusEl = document.getElementById("status");
const currentTitleEl = document.getElementById("current-title");
const currentMetaEl = document.getElementById("current-meta");
const currentCategoryEl = document.getElementById("current-category");
const currentIdleEl = document.getElementById("current-idle");
const currentTimeEl = document.getElementById("current-time");
const currentAppEl = document.getElementById("current-app");
const eventCountEl = document.getElementById("event-count");
const eventsEl = document.getElementById("events");
const eventSearchEl = document.getElementById("event-search");
const eventCategoryEl = document.getElementById("event-category");
const eventTypeEl = document.getElementById("event-type");
const ollamaStatusEl = document.getElementById("ollama-status");
const ollamaDetailEl = document.getElementById("ollama-detail");
const ollamaModelSelectEl = document.getElementById("ollama-model-select");
const ollamaModelRefreshBtn = document.getElementById("ollama-model-refresh-btn");
const ollamaModelApplyBtn = document.getElementById("ollama-model-apply-btn");
const ollamaModelResetBtn = document.getElementById("ollama-model-reset-btn");
const ollamaModelMetaEl = document.getElementById("ollama-model-meta");
const ollamaProbeBtn = document.getElementById("ollama-probe-btn");
const ollamaProbeResultEl = document.getElementById("ollama-probe-result");
const summaryBtn = document.getElementById("summary-btn");
const summaryReadBtn = document.getElementById("summary-read-btn");
const summaryText = document.getElementById("summary-text");
const executorStatusEl = document.getElementById("executor-status");
const executorPreflightResultEl = document.getElementById("executor-preflight-result");
const executorPreflightBtn = document.getElementById("executor-preflight-btn");
const executorPreflightChecksEl = document.getElementById("executor-preflight-checks");
const plannerModeSelectEl = document.getElementById("planner-mode-select");
const plannerModeApplyBtn = document.getElementById("planner-mode-apply-btn");
const plannerModeResetBtn = document.getElementById("planner-mode-reset-btn");
const plannerModeMetaEl = document.getElementById("planner-mode-meta");
const readinessStatusResultEl = document.getElementById("readiness-status-result");
const readinessStatusRefreshBtn = document.getElementById("readiness-status-refresh-btn");
const readinessStatusChecksEl = document.getElementById("readiness-status-checks");
const avatarCanvas = document.getElementById("avatar-canvas");
const voiceStateEl = document.getElementById("voice-state");
const voiceEngineEl = document.getElementById("voice-engine");
const voiceTextEl = document.getElementById("voice-text");
const voiceTranscriptEl = document.getElementById("voice-transcript");
const micBtn = document.getElementById("mic-btn");
const speakBtn = document.getElementById("speak-btn");
const sttStatusEl = document.getElementById("stt-status");
const autonomyStatusEl = document.getElementById("autonomy-status");
const autonomyObjectiveEl = document.getElementById("autonomy-objective");
const autonomyMaxIterationsEl = document.getElementById("autonomy-max-iterations");
const autonomyParallelAgentsEl = document.getElementById("autonomy-parallel-agents");
const autonomyAutoApproveEl = document.getElementById("autonomy-auto-approve");
const autonomyStartBtn = document.getElementById("autonomy-start-btn");
const autonomyApproveBtn = document.getElementById("autonomy-approve-btn");
const autonomyCancelBtn = document.getElementById("autonomy-cancel-btn");
const readinessGateBtn = document.getElementById("readiness-gate-btn");
const autonomyRunMetaEl = document.getElementById("autonomy-run-meta");
const readinessGateResultEl = document.getElementById("readiness-gate-result");
const readinessMatrixObjectivesEl = document.getElementById("readiness-matrix-objectives");
const readinessMatrixBtn = document.getElementById("readiness-matrix-btn");
const readinessMatrixResultEl = document.getElementById("readiness-matrix-result");
const readinessMatrixResultsEl = document.getElementById("readiness-matrix-results");
const autonomyLogEl = document.getElementById("autonomy-log");
const journeySessionEl = document.getElementById("journey-session");
const journeyRefreshBtn = document.getElementById("journey-refresh-btn");
const journeyMetaEl = document.getElementById("journey-meta");
const journeyEventsEl = document.getElementById("journey-events");
const journeyEventCountEl = document.getElementById("journey-event-count");
const runtimeLogsRefreshBtn = document.getElementById("runtime-logs-refresh-btn");
const runtimeLogsMetaEl = document.getElementById("runtime-logs-meta");
const runtimeLogCountEl = document.getElementById("runtime-log-count");
const runtimeLogsEl = document.getElementById("runtime-logs");
const runtimeLogsSearchEl = document.getElementById("runtime-logs-search");
const runtimeLogsLevelEl = document.getElementById("runtime-logs-level");
const runtimeLogsClearBtn = document.getElementById("runtime-logs-clear-btn");
const runtimeLogsCorrelateBtn = document.getElementById("runtime-logs-correlate-btn");

const chatStatusEl = document.getElementById("chat-status");
const chatContextIndicatorEl = document.getElementById("chat-context-indicator");
const chatMessagesEl = document.getElementById("chat-messages");
const chatWelcomeEl = document.getElementById("chat-welcome");
const chatInputEl = document.getElementById("chat-input");
const chatSendBtn = document.getElementById("chat-send-btn");
const chatSuggestionBtns = document.querySelectorAll(".chat-suggestion");

const visionStatusEl = document.getElementById("vision-status");
const visionWindowTitleEl = document.getElementById("vision-window-title");
const visionProcessEl = document.getElementById("vision-process");
const visionTimestampEl = document.getElementById("vision-timestamp");
const visionUiaTextEl = document.getElementById("vision-uia-text");
const visionScreenshotStatusEl = document.getElementById("vision-screenshot-status");
const visionRefreshBtn = document.getElementById("vision-refresh-btn");

const avatar = new AvatarEngine(avatarCanvas);
const MAX_EVENTS = 50;
const TELEMETRY_BATCH_SIZE = 50;
const TELEMETRY_FLUSH_INTERVAL_MS = 4000;
const JOURNEY_POLL_MS = 5000;
const RUNTIME_LOG_LIMIT = 120;

let events = [];
let ws;

let recognition = null;
let recognitionActive = false;
let recognitionSupported = false;
let recognitionTranscript = "";

let mediaStream = null;
let audioContext = null;
let analyser = null;
let audioData = null;
let meterRaf = null;

let currentUtterance = null;
let speechActive = false;
let activeRunId = null;
let activeApprovalToken = null;
let lastWindowFingerprint = "";
let lastStatusText = "";
let lastRunFingerprint = "";

let telemetryQueue = [];
let telemetryFlushTimer = null;
let telemetryFlushInFlight = false;
let journeyPollTimer = null;
let activeJourneySessionId = "";
let runtimeLogsViewMode = "live";
let runtimeLogsCorrelatedSessionId = "";
let chatSending = false;
let lastVisionContext = null;
const telemetrySessionId = (() => {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return `ui-${window.crypto.randomUUID()}`;
  }
  return `ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
})();
window.__desktopaiTelemetrySessionId = telemetrySessionId;

function scheduleTelemetryFlush() {
  if (telemetryFlushTimer) return;
  telemetryFlushTimer = setTimeout(() => {
    telemetryFlushTimer = null;
    void flushTelemetry();
  }, TELEMETRY_FLUSH_INTERVAL_MS);
}

function queueTelemetry(kind, message, data = {}) {
  telemetryQueue.push({
    session_id: telemetrySessionId,
    kind,
    message,
    timestamp: new Date().toISOString(),
    data,
  });
  if (telemetryQueue.length >= TELEMETRY_BATCH_SIZE) {
    void flushTelemetry();
    return;
  }
  scheduleTelemetryFlush();
}

async function flushTelemetry(options = {}) {
  const force = Boolean(options.force);
  if (telemetryFlushInFlight || telemetryQueue.length === 0) return;
  telemetryFlushInFlight = true;
  if (telemetryFlushTimer) {
    clearTimeout(telemetryFlushTimer);
    telemetryFlushTimer = null;
  }
  const batch = telemetryQueue.slice(0, TELEMETRY_BATCH_SIZE);
  try {
    const resp = await fetch("/api/ui-telemetry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events: batch }),
      keepalive: force,
    });
    if (resp.ok) {
      telemetryQueue = telemetryQueue.slice(batch.length);
    }
  } catch (err) {
    console.debug("telemetry flush failed", err);
  } finally {
    telemetryFlushInFlight = false;
    if (telemetryQueue.length > 0) scheduleTelemetryFlush();
  }
}

function flushTelemetryOnUnload() {
  if (telemetryQueue.length === 0 || !navigator.sendBeacon) return;
  const batch = telemetryQueue.slice(0, TELEMETRY_BATCH_SIZE);
  const blob = new Blob([JSON.stringify({ events: batch })], {
    type: "application/json",
  });
  const sent = navigator.sendBeacon("/api/ui-telemetry", blob);
  if (sent) {
    telemetryQueue = telemetryQueue.slice(batch.length);
  }
}

function formatTime(ts) {
  if (!ts) return "—";
  const date = new Date(ts);
  return date.toLocaleString();
}

function setVoiceState(text, tone = "neutral") {
  voiceStateEl.textContent = text;
  voiceStateEl.dataset.tone = tone;
}

function setStatus(text, tone) {
  statusEl.textContent = text;
  statusEl.style.color = tone === "good" ? "#00b8a9" : tone === "warn" ? "#ff4d4d" : "#5b6470";
  if (lastStatusText !== text) {
    queueTelemetry("connection_status", text, { tone });
    lastStatusText = text;
  }

  if (tone === "good") avatar.setConnection("live");
  if (tone === "warn") avatar.setConnection("warn");
  if (tone !== "good" && tone !== "warn") avatar.setConnection("connecting");
}

function buildOllamaDiagnosticText(data) {
  const parts = [];
  const lastError = (data && data.last_error ? String(data.last_error) : "").trim();
  const lastStatus = data && Number.isInteger(data.last_http_status) ? data.last_http_status : null;
  const source = (data && data.last_check_source ? String(data.last_check_source) : "").trim();
  const checkedAt = data && data.last_check_at ? formatTime(data.last_check_at) : "";
  const configuredModel = (data && data.configured_model ? String(data.configured_model) : "").trim();
  const activeModel = (data && data.active_model ? String(data.active_model) : "").trim();

  if (activeModel) {
    if (configuredModel && configuredModel !== activeModel) {
      parts.push(`model ${activeModel} (fallback from ${configuredModel})`);
    } else {
      parts.push(`model ${activeModel}`);
    }
  }

  if (lastError) {
    parts.push(lastError);
  } else if (lastStatus !== null) {
    parts.push(`HTTP ${lastStatus}`);
  }
  if (source) parts.push(`via ${source}`);
  if (checkedAt && checkedAt !== "Invalid Date") parts.push(`at ${checkedAt}`);
  if (parts.length === 0) return "no diagnostic details yet";
  return parts.join(" | ");
}

function renderOllamaModelOptions(models, activeModel) {
  if (!ollamaModelSelectEl) return;
  const list = Array.isArray(models) ? models : [];
  const selected = String(activeModel || "").trim();
  ollamaModelSelectEl.innerHTML = "";

  if (list.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Model: none detected";
    ollamaModelSelectEl.appendChild(option);
    ollamaModelSelectEl.value = "";
    return;
  }

  const hasSelected = list.includes(selected);
  for (const name of list) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    ollamaModelSelectEl.appendChild(option);
  }
  ollamaModelSelectEl.value = hasSelected ? selected : list[0];
}

function renderOllamaModelMeta(data) {
  if (!ollamaModelMetaEl) return;
  const configured = data && data.configured_model ? String(data.configured_model) : "unknown";
  const active = data && data.active_model ? String(data.active_model) : "unknown";
  const source = data && data.source ? String(data.source) : "unknown";
  const models = Array.isArray(data && data.models) ? data.models : [];
  ollamaModelMetaEl.textContent =
    `Ollama model: ${active} | configured ${configured} | source ${source} | installed ${models.length}`;
}

async function refreshOllamaModels() {
  if (!ollamaModelRefreshBtn) return null;
  ollamaModelRefreshBtn.disabled = true;
  try {
    const resp = await fetch("/api/ollama/models");
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "ollama model listing failed");
    renderOllamaModelOptions(data.models, data.active_model);
    renderOllamaModelMeta(data);
    queueTelemetry("ollama_models_loaded", "ollama model list loaded", {
      installed: Array.isArray(data.models) ? data.models.length : 0,
      active_model: data.active_model || null,
      source: data.source || null,
    });
    return data;
  } catch (err) {
    if (ollamaModelMetaEl) ollamaModelMetaEl.textContent = "Ollama model: unavailable";
    console.error("ollama model list error", err);
    queueTelemetry("ollama_models_failed", "ollama model list failed", {
      error: String(err),
    });
    return null;
  } finally {
    ollamaModelRefreshBtn.disabled = false;
  }
}

async function applyOllamaModelOverride() {
  if (!ollamaModelSelectEl || !ollamaModelApplyBtn) return;
  const selected = String(ollamaModelSelectEl.value || "").trim();
  if (!selected) return;
  ollamaModelApplyBtn.disabled = true;
  if (ollamaModelMetaEl) {
    ollamaModelMetaEl.textContent = `Ollama model: applying ${selected}…`;
  }
  queueTelemetry("ollama_model_update_requested", "ollama model override requested", {
    model: selected,
  });
  try {
    const resp = await fetch("/api/ollama/model", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: selected }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "ollama model update failed");
    queueTelemetry("ollama_model_updated", "ollama model override updated", {
      active_model: data.active_model || selected,
      source: data.ollama_model_source || null,
    });
    await checkOllama();
    await refreshOllamaModels();
    await refreshReadinessStatus();
  } catch (err) {
    if (ollamaModelMetaEl) {
      ollamaModelMetaEl.textContent = `Ollama model: update failed (${String(err)})`;
    }
    console.error("ollama model update error", err);
    queueTelemetry("ollama_model_update_failed", "ollama model override failed", {
      model: selected,
      error: String(err),
    });
  } finally {
    ollamaModelApplyBtn.disabled = false;
  }
}

async function resetOllamaModelOverride() {
  if (!ollamaModelResetBtn) return;
  ollamaModelResetBtn.disabled = true;
  if (ollamaModelMetaEl) {
    ollamaModelMetaEl.textContent = "Ollama model: reverting to configured default…";
  }
  queueTelemetry("ollama_model_reset_requested", "ollama model override reset requested");
  try {
    const resp = await fetch("/api/ollama/model", { method: "DELETE" });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "ollama model reset failed");
    queueTelemetry("ollama_model_reset", "ollama model override reset", {
      active_model: data.active_model || null,
      source: data.ollama_model_source || null,
    });
    await checkOllama();
    await refreshOllamaModels();
    await refreshReadinessStatus();
  } catch (err) {
    if (ollamaModelMetaEl) {
      ollamaModelMetaEl.textContent = `Ollama model: reset failed (${String(err)})`;
    }
    console.error("ollama model reset error", err);
    queueTelemetry("ollama_model_reset_failed", "ollama model reset failed", {
      error: String(err),
    });
  } finally {
    ollamaModelResetBtn.disabled = false;
  }
}

async function runOllamaProbe() {
  if (!ollamaProbeBtn) return;
  ollamaProbeBtn.disabled = true;
  if (ollamaProbeResultEl) {
    ollamaProbeResultEl.textContent = "Probe: running…";
  }
  queueTelemetry("ollama_probe_requested", "ollama probe requested");
  try {
    const resp = await fetch("/api/ollama/probe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: "Respond with exactly: OK",
        timeout_s: 8.0,
        allow_fallback: false,
      }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "ollama probe failed");
    const probe = data.probe || {};
    const ok = Boolean(probe.ok);
    const model = probe.model || data.active_model || "unknown";
    const elapsedMs = Number(probe.elapsed_ms || 0);
    if (ok) {
      if (ollamaProbeResultEl) {
        ollamaProbeResultEl.textContent = `Probe: ok | model ${model} | ${elapsedMs} ms`;
      }
      queueTelemetry("ollama_probe_completed", "ollama probe completed", {
        ok: true,
        model,
        elapsed_ms: elapsedMs,
      });
    } else {
      const errorText = String(probe.error || "probe failed");
      if (ollamaProbeResultEl) {
        ollamaProbeResultEl.textContent = `Probe: failed | model ${model} | ${elapsedMs} ms | ${errorText}`;
      }
      queueTelemetry("ollama_probe_completed", "ollama probe completed", {
        ok: false,
        model,
        elapsed_ms: elapsedMs,
        error: errorText,
      });
    }
    await checkOllama();
    await refreshReadinessStatus();
  } catch (err) {
    if (ollamaProbeResultEl) {
      ollamaProbeResultEl.textContent = `Probe: error (${String(err)})`;
    }
    console.error("ollama probe error", err);
    queueTelemetry("ollama_probe_failed", "ollama probe failed", {
      error: String(err),
    });
  } finally {
    ollamaProbeBtn.disabled = false;
  }
}

function updateCurrent(state) {
  const idleLabel = state && typeof state.idle === "boolean" ? (state.idle ? "Idle" : "Active") : "—";
  currentIdleEl.textContent = `Status: ${idleLabel}`;
  const categoryLabel =
    state && state.current ? state.current.category || state.category || "uncategorized" : "—";
  currentCategoryEl.textContent = `Category: ${categoryLabel}`;
  avatar.setActivity({ idle: state ? state.idle : false });

  if (!state || !state.current) {
    currentTitleEl.textContent = "Waiting for events…";
    currentMetaEl.textContent = "—";
    currentTimeEl.textContent = "—";
    currentAppEl.textContent = "—";
    return;
  }

  const ev = state.current;
  const fingerprint = `${ev.timestamp || ""}|${ev.hwnd || ""}|${ev.title || ""}|${ev.process_exe || ""}`;
  if (fingerprint !== lastWindowFingerprint) {
    queueTelemetry("current_window_changed", "foreground window changed", {
      title: ev.title || "",
      process_exe: ev.process_exe || "",
      pid: ev.pid || 0,
      category: ev.category || state.category || null,
      idle: Boolean(state.idle),
      event_count: state.event_count || 0,
    });
    lastWindowFingerprint = fingerprint;
  }
  currentTitleEl.textContent = ev.title || "(untitled window)";
  currentMetaEl.textContent = `${ev.process_exe || "unknown"} · pid ${ev.pid}`;
  currentTimeEl.textContent = formatTime(ev.timestamp);
  currentAppEl.textContent = ev.type || "foreground";
}

function applyFilters(items) {
  let filtered = items.slice();
  const query = (eventSearchEl.value || "").trim().toLowerCase();
  const category = eventCategoryEl.value;
  const type = eventTypeEl.value;

  if (type !== "all") {
    filtered = filtered.filter((ev) => (ev.type || "foreground") === type);
  }
  if (category !== "all") {
    filtered = filtered.filter((ev) => (ev.category || "uncategorized") === category);
  }
  if (query) {
    filtered = filtered.filter((ev) => {
      const uia = ev.uia || {};
      const haystack = [
        ev.title,
        ev.process_exe,
        ev.category,
        ev.type,
        uia.focused_name,
        uia.control_type,
        uia.document_text,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }
  return filtered;
}

function renderEvents() {
  eventsEl.innerHTML = "";
  const frag = document.createDocumentFragment();
  const filtered = applyFilters(events);
  filtered
    .slice()
    .reverse()
    .forEach((ev) => {
      const li = document.createElement("li");
      li.className = "event-item";

      const title = document.createElement("p");
      title.className = "event-title";
      if (ev.title) {
        title.textContent = ev.title;
      } else if (ev.type === "idle") {
        title.textContent = "Idle";
      } else if (ev.type === "active") {
        title.textContent = "Active";
      } else {
        title.textContent = "(untitled window)";
      }

      const meta = document.createElement("p");
      meta.className = "event-meta";
      const parts = [formatTime(ev.timestamp)];
      if (ev.process_exe) parts.push(ev.process_exe);
      if (ev.pid) parts.push(`pid ${ev.pid}`);
      if (ev.idle_ms !== null && ev.idle_ms !== undefined) {
        parts.push(`idle ${(ev.idle_ms / 1000).toFixed(0)}s`);
      }
      meta.textContent = parts.join(" · ");

      const tags = document.createElement("div");
      tags.className = "event-tags";
      const category = ev.category || (ev.type === "foreground" ? "uncategorized" : null);
      if (category) {
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = category;
        tags.appendChild(tag);
      }
      if (ev.type) {
        const tag = document.createElement("span");
        tag.className = `tag type-${ev.type}`;
        tag.textContent = ev.type;
        tags.appendChild(tag);
      }

      li.appendChild(title);
      li.appendChild(meta);
      if (tags.childNodes.length > 0) li.appendChild(tags);
      frag.appendChild(li);
    });
  eventsEl.appendChild(frag);
  eventCountEl.textContent = String(filtered.length);
}

function setAutonomyStatus(status) {
  autonomyStatusEl.textContent = status || "idle";
  if (status === "completed" || status === "running") {
    autonomyStatusEl.dataset.tone = "good";
  } else if (status === "failed" || status === "cancelled") {
    autonomyStatusEl.dataset.tone = "warn";
  } else {
    autonomyStatusEl.dataset.tone = "neutral";
  }
}

function renderAutonomyLog(entries) {
  autonomyLogEl.innerHTML = "";
  const list = Array.isArray(entries) ? entries : [];
  const recent = list.slice(-12).reverse();
  const frag = document.createDocumentFragment();
  for (const item of recent) {
    const li = document.createElement("li");
    li.className = "event-item";
    const title = document.createElement("p");
    title.className = "event-title";
    title.textContent = `${item.agent || "agent"} · ${item.message || ""}`;
    const meta = document.createElement("p");
    meta.className = "event-meta";
    meta.textContent = formatTime(item.timestamp);
    li.appendChild(title);
    li.appendChild(meta);
    frag.appendChild(li);
  }
  autonomyLogEl.appendChild(frag);
}

function renderJourneyEvents(entries) {
  journeyEventsEl.innerHTML = "";
  const list = Array.isArray(entries) ? entries.slice().reverse() : [];
  journeyEventCountEl.textContent = String(list.length);
  const frag = document.createDocumentFragment();
  for (const item of list) {
    const li = document.createElement("li");
    li.className = "event-item";
    const title = document.createElement("p");
    title.className = "event-title";
    const kind = item.kind || "event";
    const message = item.message || "";
    title.textContent = `${kind}${message ? ` · ${message}` : ""}`;
    const meta = document.createElement("p");
    meta.className = "event-meta";
    meta.textContent = formatTime(item.timestamp);
    li.appendChild(title);
    li.appendChild(meta);
    frag.appendChild(li);
  }
  journeyEventsEl.appendChild(frag);
}

function renderRuntimeLogs(entries) {
  runtimeLogsEl.innerHTML = "";
  const list = Array.isArray(entries) ? entries.slice().reverse() : [];
  runtimeLogCountEl.textContent = String(list.length);
  const frag = document.createDocumentFragment();
  for (const item of list) {
    const li = document.createElement("li");
    li.className = "event-item";

    const title = document.createElement("p");
    title.className = "event-title";
    const loggerName = item.logger || "logger";
    const level = item.level || "INFO";
    title.textContent = `${level} · ${loggerName}`;

    const meta = document.createElement("p");
    meta.className = "event-meta";
    const message = item.message || "";
    meta.textContent = `${formatTime(item.timestamp)} · ${message}`;

    li.appendChild(title);
    li.appendChild(meta);
    frag.appendChild(li);
  }
  runtimeLogsEl.appendChild(frag);
}

async function fetchJourneySessions() {
  const resp = await fetch("/api/ui-telemetry/sessions?limit=40");
  if (!resp.ok) throw new Error("failed to load telemetry sessions");
  const payload = await resp.json();
  return Array.isArray(payload.sessions) ? payload.sessions : [];
}

async function fetchJourneyEvents(sessionId) {
  const id = encodeURIComponent(sessionId);
  const resp = await fetch(`/api/ui-telemetry?session_id=${id}&limit=120`);
  if (!resp.ok) throw new Error("failed to load telemetry events");
  const payload = await resp.json();
  return Array.isArray(payload.events) ? payload.events : [];
}

async function fetchRuntimeLogs() {
  const filters = getRuntimeLogFilters();
  const params = new URLSearchParams();
  params.set("limit", String(RUNTIME_LOG_LIMIT));
  if (filters.contains) params.set("contains", filters.contains);
  if (filters.level) params.set("level", filters.level);

  const resp = await fetch(`/api/runtime-logs?${params.toString()}`);
  if (!resp.ok) throw new Error("failed to load runtime logs");
  const payload = await resp.json();
  return Array.isArray(payload.logs) ? payload.logs : [];
}

function getRuntimeLogFilters() {
  const contains = (runtimeLogsSearchEl.value || "").trim();
  const level = (runtimeLogsLevelEl.value || "").trim();
  return { contains, level };
}

async function fetchCorrelatedRuntimeLogs(sessionId) {
  const params = new URLSearchParams();
  params.set("limit", String(RUNTIME_LOG_LIMIT));
  params.set("session_id", sessionId);
  const filters = getRuntimeLogFilters();
  if (filters.contains) params.set("contains", filters.contains);
  if (filters.level) params.set("level", filters.level);
  const resp = await fetch(`/api/runtime-logs/correlate?${params.toString()}`);
  if (!resp.ok) throw new Error("failed to correlate runtime logs");
  return await resp.json();
}

function runtimeFilterSuffix() {
  const filters = getRuntimeLogFilters();
  const filterParts = [];
  if (filters.level) filterParts.push(`level=${filters.level}`);
  if (filters.contains) filterParts.push(`contains=${filters.contains}`);
  return filterParts.length > 0 ? ` · ${filterParts.join(" · ")}` : "";
}

function setRuntimeLogsLiveMode() {
  runtimeLogsViewMode = "live";
  runtimeLogsCorrelatedSessionId = "";
}

function setRuntimeLogsCorrelatedMode(sessionId) {
  runtimeLogsViewMode = "correlated";
  runtimeLogsCorrelatedSessionId = (sessionId || "").trim();
}

async function refreshRuntimeLogs() {
  try {
    const logs = await fetchRuntimeLogs();
    renderRuntimeLogs(logs);
    runtimeLogsMetaEl.textContent = `Logs: latest ${logs.length} entries${runtimeFilterSuffix()}`;
  } catch (err) {
    runtimeLogsMetaEl.textContent = "Logs: unavailable";
    runtimeLogCountEl.textContent = "0";
    runtimeLogsEl.innerHTML = "";
    console.error("runtime logs refresh failed", err);
  }
}

async function correlateRuntimeLogsWithSession(options = {}) {
  const skipJourneyRefresh = Boolean(options.skipJourneyRefresh);
  runtimeLogsCorrelateBtn.disabled = true;
  try {
    if (!skipJourneyRefresh) {
      await refreshJourneyConsole();
    }
    const sessionId = (
      options.sessionId ||
      runtimeLogsCorrelatedSessionId ||
      activeJourneySessionId ||
      journeySessionEl.value ||
      telemetrySessionId ||
      ""
    ).trim();
    if (!sessionId) throw new Error("session unavailable");
    const payload = await fetchCorrelatedRuntimeLogs(sessionId);
    const logs = Array.isArray(payload.logs) ? payload.logs : [];
    renderRuntimeLogs(logs);
    const windowInfo = payload.window
      ? `${formatTime(payload.window.since)} → ${formatTime(payload.window.until)}`
      : "no telemetry window";
    runtimeLogsMetaEl.textContent = `Logs: session ${sessionId} · ${windowInfo}${runtimeFilterSuffix()}`;
    setRuntimeLogsCorrelatedMode(sessionId);
    queueTelemetry("runtime_logs_correlated", "runtime logs correlated to session", {
      session_id: sessionId,
      logs: logs.length,
      has_window: Boolean(payload.window),
    });
  } catch (err) {
    runtimeLogsMetaEl.textContent = "Logs: correlation failed";
    console.error("runtime logs correlate failed", err);
    queueTelemetry("runtime_logs_correlate_failed", "runtime log correlation failed", {
      error: String(err),
    });
  } finally {
    runtimeLogsCorrelateBtn.disabled = false;
  }
}

function applyJourneySessionOptions(sessions) {
  const previous = activeJourneySessionId || journeySessionEl.value || telemetrySessionId;
  const options = [];
  const seen = new Set();

  const addSession = (sessionId, label) => {
    const id = (sessionId || "").trim();
    if (!id || seen.has(id)) return;
    seen.add(id);
    options.push({ sessionId: id, label });
  };

  addSession(telemetrySessionId, `this session · ${telemetrySessionId}`);
  for (const session of sessions) {
    const sessionId = String(session.session_id || "").trim();
    const count = Number(session.event_count || 0);
    addSession(sessionId, `${sessionId} · ${count} events`);
  }

  journeySessionEl.innerHTML = "";
  for (const option of options) {
    const node = document.createElement("option");
    node.value = option.sessionId;
    node.textContent = option.label;
    journeySessionEl.appendChild(node);
  }

  const exists = options.some((option) => option.sessionId === previous);
  activeJourneySessionId = exists ? previous : telemetrySessionId;
  journeySessionEl.value = activeJourneySessionId;
}

async function refreshJourneyConsole() {
  try {
    await flushTelemetry({ force: true });
    const sessions = await fetchJourneySessions();
    applyJourneySessionOptions(sessions);
    const events = await fetchJourneyEvents(activeJourneySessionId);
    renderJourneyEvents(events);
    journeyMetaEl.textContent = `Session: ${activeJourneySessionId} · source: live telemetry`;
  } catch (err) {
    journeyMetaEl.textContent = "Session: telemetry unavailable";
    journeyEventCountEl.textContent = "0";
    journeyEventsEl.innerHTML = "";
    console.error("journey console refresh failed", err);
  }
}

async function clearRuntimeLogs() {
  runtimeLogsClearBtn.disabled = true;
  try {
    const resp = await fetch("/api/runtime-logs/reset", { method: "POST" });
    if (!resp.ok) throw new Error("failed to clear runtime logs");
    setRuntimeLogsLiveMode();
    await refreshRuntimeLogs();
  } catch (err) {
    runtimeLogsMetaEl.textContent = "Logs: clear failed";
    console.error("runtime logs clear failed", err);
  } finally {
    runtimeLogsClearBtn.disabled = false;
  }
}

function startJourneyPolling() {
  if (journeyPollTimer) clearInterval(journeyPollTimer);
  journeyPollTimer = setInterval(() => {
    void refreshJourneyConsole();
    if (runtimeLogsViewMode === "live") {
      void refreshRuntimeLogs();
    }
  }, JOURNEY_POLL_MS);
}

function applyRunUiState(run) {
  if (!run) {
    activeRunId = null;
    activeApprovalToken = null;
    lastRunFingerprint = "";
    setAutonomyStatus("idle");
    autonomyRunMetaEl.textContent = "Run: —";
    autonomyApproveBtn.disabled = true;
    autonomyCancelBtn.disabled = true;
    autonomyStartBtn.disabled = false;
    renderAutonomyLog([]);
    return;
  }

  activeRunId = run.run_id;
  activeApprovalToken = run.approval_token || null;
  setAutonomyStatus(run.status);
  const runPlannerMode = run.planner_mode || "deterministic";
  const runFingerprint = `${run.run_id}|${run.status}|${run.iteration}|${activeApprovalToken ? "1" : "0"}|${runPlannerMode}`;
  if (runFingerprint !== lastRunFingerprint) {
    if (run.status === "waiting_approval") {
      queueTelemetry("autonomy_waiting_approval", "autonomy run waiting approval", {
        run_id: run.run_id,
        iteration: run.iteration,
        planner_mode: runPlannerMode,
      });
    } else {
      queueTelemetry("autonomy_status_changed", "autonomy run status changed", {
        run_id: run.run_id,
        status: run.status,
        iteration: run.iteration,
        planner_mode: runPlannerMode,
      });
    }
    lastRunFingerprint = runFingerprint;
  }
  autonomyRunMetaEl.textContent = `Run: ${run.run_id} · mode ${runPlannerMode} · iteration ${run.iteration}/${run.max_iterations}`;
  autonomyApproveBtn.disabled = run.status !== "waiting_approval" || !activeApprovalToken;
  autonomyCancelBtn.disabled = ["completed", "failed", "cancelled"].includes(run.status);
  autonomyStartBtn.disabled = run.status === "running" || run.status === "waiting_approval";
  renderAutonomyLog(run.agent_log || []);
}

async function startAutonomyRun() {
  const objective = (autonomyObjectiveEl.value || "").trim();
  if (!objective) {
    setAutonomyStatus("objective required");
    autonomyStatusEl.dataset.tone = "warn";
    queueTelemetry("autonomy_start_rejected", "objective required");
    return;
  }
  const body = {
    objective,
    max_iterations: Number(autonomyMaxIterationsEl.value || 24),
    parallel_agents: Number(autonomyParallelAgentsEl.value || 3),
    auto_approve_irreversible: Boolean(autonomyAutoApproveEl.checked),
  };

  autonomyStartBtn.disabled = true;
  queueTelemetry("autonomy_start_requested", "start clicked", {
    objective,
    max_iterations: body.max_iterations,
    parallel_agents: body.parallel_agents,
    auto_approve_irreversible: body.auto_approve_irreversible,
  });
  try {
    const resp = await fetch("/api/autonomy/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await resp.json();
    if (!resp.ok) {
      throw new Error(payload.detail || "failed to start run");
    }
    applyRunUiState(payload.run);
    queueTelemetry("autonomy_started", "autonomy run started", {
      run_id: payload.run.run_id,
      status: payload.run.status,
    });
  } catch (err) {
    setAutonomyStatus("start failed");
    autonomyStatusEl.dataset.tone = "warn";
    console.error("autonomy start error", err);
    queueTelemetry("autonomy_start_failed", "autonomy start failed", {
      error: String(err),
    });
  } finally {
    if (!activeRunId || autonomyStatusEl.textContent !== "running") {
      autonomyStartBtn.disabled = false;
    }
  }
}

async function approveAutonomyRun() {
  if (!activeRunId || !activeApprovalToken) return;
  queueTelemetry("autonomy_approve_requested", "approve clicked", { run_id: activeRunId });
  try {
    const resp = await fetch(`/api/autonomy/runs/${activeRunId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approval_token: activeApprovalToken }),
    });
    const payload = await resp.json();
    if (!resp.ok) {
      throw new Error(payload.detail || "approve failed");
    }
    applyRunUiState(payload.run);
    queueTelemetry("autonomy_approved", "autonomy approval accepted", {
      run_id: payload.run.run_id,
      status: payload.run.status,
    });
  } catch (err) {
    setAutonomyStatus("approve failed");
    autonomyStatusEl.dataset.tone = "warn";
    console.error("autonomy approve error", err);
    queueTelemetry("autonomy_approve_failed", "autonomy approval failed", {
      run_id: activeRunId,
      error: String(err),
    });
  }
}

async function cancelAutonomyRun() {
  if (!activeRunId) return;
  queueTelemetry("autonomy_cancel_requested", "cancel clicked", { run_id: activeRunId });
  try {
    const resp = await fetch(`/api/autonomy/runs/${activeRunId}/cancel`, { method: "POST" });
    const payload = await resp.json();
    if (!resp.ok) {
      throw new Error(payload.detail || "cancel failed");
    }
    applyRunUiState(payload.run);
    queueTelemetry("autonomy_cancelled", "autonomy run cancelled", {
      run_id: payload.run.run_id,
      status: payload.run.status,
    });
  } catch (err) {
    setAutonomyStatus("cancel failed");
    autonomyStatusEl.dataset.tone = "warn";
    console.error("autonomy cancel error", err);
    queueTelemetry("autonomy_cancel_failed", "autonomy cancel failed", {
      run_id: activeRunId,
      error: String(err),
    });
  }
}

async function runReadinessGateFromUi() {
  const objective = (autonomyObjectiveEl.value || "").trim();
  if (!objective) {
    readinessGateResultEl.textContent = "Readiness Gate: objective required";
    queueTelemetry("readiness_gate_rejected", "objective required");
    return;
  }

  const body = {
    objective,
    timeout_s: 30,
    max_iterations: Number(autonomyMaxIterationsEl.value || 24),
    parallel_agents: Number(autonomyParallelAgentsEl.value || 3),
    auto_approve_irreversible: Boolean(autonomyAutoApproveEl.checked),
    require_preflight_ok: true,
  };

  readinessGateBtn.disabled = true;
  readinessGateResultEl.textContent = "Readiness Gate: running…";
  queueTelemetry("readiness_gate_requested", "readiness gate requested", {
    objective,
    auto_approve_irreversible: body.auto_approve_irreversible,
  });
  try {
    const resp = await fetch("/api/readiness/gate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await resp.json();
    if (!resp.ok) {
      throw new Error(payload.detail || "readiness gate failed");
    }
    const reason = payload.reason || "unknown";
    const elapsedMs = Number(payload.elapsed_ms || 0);
    readinessGateResultEl.textContent = `Readiness Gate: ${reason} (${elapsedMs} ms)`;
    queueTelemetry("readiness_gate_completed", "readiness gate completed", {
      ok: Boolean(payload.ok),
      reason,
      elapsed_ms: elapsedMs,
    });
    if (payload.run) {
      applyRunUiState(payload.run);
    }
  } catch (err) {
    readinessGateResultEl.textContent = "Readiness Gate: error";
    queueTelemetry("readiness_gate_failed", "readiness gate failed", {
      error: String(err),
    });
    console.error("readiness gate error", err);
  } finally {
    readinessGateBtn.disabled = false;
  }
}

function renderReadinessMatrixResults(items) {
  readinessMatrixResultsEl.innerHTML = "";
  const list = Array.isArray(items) ? items : [];
  const frag = document.createDocumentFragment();
  for (const item of list) {
    const report = item && item.report ? item.report : {};
    const li = document.createElement("li");
    li.className = "event-item";

    const title = document.createElement("p");
    title.className = "event-title";
    const objective = item && item.objective ? item.objective : "objective";
    const reason = report.reason || "unknown";
    title.textContent = `${objective} · ${reason}`;

    const meta = document.createElement("p");
    meta.className = "event-meta";
    const elapsedMs = Number(report.elapsed_ms || 0);
    meta.textContent = `ok=${Boolean(report.ok)} · ${elapsedMs} ms`;

    li.appendChild(title);
    li.appendChild(meta);
    frag.appendChild(li);
  }
  readinessMatrixResultsEl.appendChild(frag);
}

async function runReadinessMatrixFromUi() {
  const raw = (readinessMatrixObjectivesEl.value || "").trim();
  const objectives = raw
    .split("\n")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);

  if (objectives.length === 0) {
    readinessMatrixResultEl.textContent = "Readiness Matrix: objective list required";
    queueTelemetry("readiness_matrix_rejected", "objective list required");
    return;
  }

  const body = {
    objectives,
    timeout_s: 30,
    max_iterations: Number(autonomyMaxIterationsEl.value || 24),
    parallel_agents: Number(autonomyParallelAgentsEl.value || 3),
    auto_approve_irreversible: Boolean(autonomyAutoApproveEl.checked),
    require_preflight_ok: true,
    stop_on_failure: false,
  };

  readinessMatrixBtn.disabled = true;
  readinessMatrixResultEl.textContent = "Readiness Matrix: running…";
  queueTelemetry("readiness_matrix_requested", "readiness matrix requested", {
    objectives: objectives.length,
    auto_approve_irreversible: body.auto_approve_irreversible,
  });
  try {
    const resp = await fetch("/api/readiness/matrix", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await resp.json();
    if (!resp.ok) {
      throw new Error(payload.detail || "readiness matrix failed");
    }
    const passed = Number(payload.passed || 0);
    const total = Number(payload.total || 0);
    const elapsedMs = Number(payload.elapsed_ms || 0);
    readinessMatrixResultEl.textContent = `Readiness Matrix: ${passed}/${total} passed (${elapsedMs} ms)`;
    renderReadinessMatrixResults(payload.results || []);
    queueTelemetry("readiness_matrix_completed", "readiness matrix completed", {
      ok: Boolean(payload.ok),
      passed,
      total,
      elapsed_ms: elapsedMs,
    });
  } catch (err) {
    readinessMatrixResultEl.textContent = "Readiness Matrix: error";
    renderReadinessMatrixResults([]);
    queueTelemetry("readiness_matrix_failed", "readiness matrix failed", {
      error: String(err),
    });
    console.error("readiness matrix error", err);
  } finally {
    readinessMatrixBtn.disabled = false;
  }
}

async function fetchSnapshot() {
  try {
    const [stateResp, eventsResp] = await Promise.all([fetch("/api/state"), fetch(`/api/events?limit=${MAX_EVENTS}`)]);
    const state = await stateResp.json();
    const eventsData = await eventsResp.json();
    events = eventsData.events || [];
    updateCurrent(state);
    renderEvents();
    queueTelemetry("snapshot_fetched", "initial snapshot fetched", {
      events: events.length,
      has_current: Boolean(state.current),
    });
  } catch (err) {
    console.error("snapshot error", err);
    queueTelemetry("snapshot_failed", "initial snapshot failed", { error: String(err) });
  }
}

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  setStatus("connecting", "neutral");

  ws.onopen = () => {
    setStatus("live", "good");
    queueTelemetry("ws_open", "ui websocket connected");
  };

  ws.onmessage = (message) => {
    try {
      const payload = JSON.parse(message.data);
      if (payload.type === "snapshot") {
        events = payload.events || [];
        updateCurrent(payload.state);
        renderEvents();
        applyRunUiState(payload.autonomy_run || null);
        queueTelemetry("ws_snapshot", "ws snapshot received", {
          events: events.length,
          has_run: Boolean(payload.autonomy_run),
        });
      }
      if (payload.type === "event" && payload.event) {
        events.push(payload.event);
        if (events.length > MAX_EVENTS) events = events.slice(-MAX_EVENTS);
        avatar.bump();
        renderEvents();
        void refreshAgentVision();
        queueTelemetry("event_stream_received", "live event received", {
          type: payload.event.type || "foreground",
          process_exe: payload.event.process_exe || "",
          title: payload.event.title || "",
        });
      }
      if (payload.type === "state") {
        updateCurrent(payload.state);
        void refreshAgentVision();
      }
      if (payload.type === "autonomy_run" && payload.run) {
        if (!activeRunId || payload.run.run_id === activeRunId) {
          applyRunUiState(payload.run);
        }
      }
    } catch (err) {
      console.error("ws message error", err);
      queueTelemetry("ws_message_error", "ws payload parse failed", { error: String(err) });
    }
  };

  ws.onclose = () => {
    setStatus("disconnected", "warn");
    queueTelemetry("ws_closed", "ui websocket disconnected");
    setTimeout(connectWs, 1500);
  };

  ws.onerror = () => {
    queueTelemetry("ws_error", "ui websocket error");
    ws.close();
  };
}

async function checkOllama() {
  try {
    const resp = await fetch("/api/ollama");
    const data = await resp.json();
    if (data.autonomy_planner_mode && plannerModeSelectEl) {
      if (plannerModeSelectEl.querySelector(`option[value="${data.autonomy_planner_mode}"]`)) {
        plannerModeSelectEl.value = data.autonomy_planner_mode;
      }
    }
    if (data.available) {
      ollamaStatusEl.textContent = "available";
      ollamaStatusEl.removeAttribute("title");
      if (ollamaDetailEl) {
        ollamaDetailEl.textContent = `Ollama diagnostics: ${buildOllamaDiagnosticText(data)}`;
      }
      summaryBtn.disabled = false;
      queueTelemetry("ollama_status", "ollama available", {
        source: data.last_check_source || null,
        configured_model: data.configured_model || null,
        active_model: data.active_model || data.model || null,
      });
    } else {
      ollamaStatusEl.textContent = "offline";
      const detailText = buildOllamaDiagnosticText(data);
      ollamaStatusEl.setAttribute("title", detailText);
      if (ollamaDetailEl) {
        ollamaDetailEl.textContent = `Ollama diagnostics: ${detailText}`;
      }
      summaryBtn.disabled = true;
      queueTelemetry("ollama_status", "ollama offline", {
        source: data.last_check_source || null,
        last_http_status: data.last_http_status ?? null,
        last_error: data.last_error || null,
        configured_model: data.configured_model || null,
        active_model: data.active_model || data.model || null,
      });
    }
    if (ollamaModelSelectEl && data.active_model) {
      const active = String(data.active_model);
      const option = Array.from(ollamaModelSelectEl.options).find((item) => item.value === active);
      if (option) {
        ollamaModelSelectEl.value = active;
      }
    }
    if (ollamaModelMetaEl) {
      const source = data.ollama_model_source || "unknown";
      const configured = data.configured_model || "unknown";
      const active = data.active_model || data.model || "unknown";
      ollamaModelMetaEl.textContent =
        `Ollama model: ${active} | configured ${configured} | source ${source}`;
    }
  } catch (err) {
    ollamaStatusEl.textContent = "unknown";
    ollamaStatusEl.removeAttribute("title");
    if (ollamaDetailEl) {
      ollamaDetailEl.textContent = "Ollama diagnostics: status request failed";
    }
    summaryBtn.disabled = true;
    queueTelemetry("ollama_status", "ollama status unknown", { error: String(err) });
  }
}

async function refreshExecutorStatus() {
  try {
    const resp = await fetch("/api/executor");
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "executor status failed");
    const mode = data.mode || "unknown";
    const available = data.available ? "available" : "unavailable";
    executorStatusEl.textContent = `Executor: ${mode} (${available})`;
  } catch (err) {
    executorStatusEl.textContent = "Executor: status unavailable";
    console.error("executor status error", err);
  }
}

function renderPlannerModeStatus(data) {
  const mode = data && data.mode ? data.mode : "unknown";
  const available = Boolean(data && data.ollama_available);
  const required = Boolean(data && data.ollama_required);
  const source = data && data.source ? data.source : "unknown";
  const configuredDefault =
    data && data.configured_default_mode ? data.configured_default_mode : "unknown";
  if (plannerModeSelectEl && mode && plannerModeSelectEl.querySelector(`option[value="${mode}"]`)) {
    plannerModeSelectEl.value = mode;
  }
  const availabilityLabel = available ? "ollama up" : "ollama down";
  const requirementLabel = required ? "required" : "optional";
  plannerModeMetaEl.textContent =
    `Planner mode: ${mode} | source ${source} | default ${configuredDefault} | ` +
    `${availabilityLabel} | ${requirementLabel}`;
}

async function refreshPlannerModeStatus() {
  try {
    const resp = await fetch("/api/autonomy/planner");
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "planner status failed");
    renderPlannerModeStatus(data);
    return data;
  } catch (err) {
    plannerModeMetaEl.textContent = "Planner mode: error";
    console.error("planner status error", err);
    queueTelemetry("planner_mode_status_failed", "planner mode status failed", {
      error: String(err),
    });
    return null;
  }
}

async function applyPlannerMode() {
  const mode = plannerModeSelectEl.value;
  plannerModeApplyBtn.disabled = true;
  plannerModeMetaEl.textContent = `Planner mode: applying ${mode}…`;
  queueTelemetry("planner_mode_update_requested", "planner mode update requested", { mode });
  try {
    const resp = await fetch("/api/autonomy/planner", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "planner mode update failed");
    renderPlannerModeStatus(data);
    queueTelemetry("planner_mode_updated", "planner mode updated", {
      mode: data.mode || mode,
      ollama_required: Boolean(data.ollama_required),
    });
    await refreshReadinessStatus();
    await checkOllama();
  } catch (err) {
    plannerModeMetaEl.textContent = `Planner mode: update failed (${String(err)})`;
    console.error("planner mode update error", err);
    queueTelemetry("planner_mode_update_failed", "planner mode update failed", {
      mode,
      error: String(err),
    });
  } finally {
    plannerModeApplyBtn.disabled = false;
  }
}

async function resetPlannerModeOverride() {
  plannerModeResetBtn.disabled = true;
  plannerModeMetaEl.textContent = "Planner mode: reverting to configured default…";
  queueTelemetry("planner_mode_reset_requested", "planner mode reset requested");
  try {
    const resp = await fetch("/api/autonomy/planner", { method: "DELETE" });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "planner mode reset failed");
    renderPlannerModeStatus(data);
    queueTelemetry("planner_mode_reset", "planner mode reset to configured default", {
      mode: data.mode || null,
      source: data.source || null,
    });
    await refreshReadinessStatus();
    await checkOllama();
  } catch (err) {
    plannerModeMetaEl.textContent = `Planner mode: reset failed (${String(err)})`;
    console.error("planner mode reset error", err);
    queueTelemetry("planner_mode_reset_failed", "planner mode reset failed", {
      error: String(err),
    });
  } finally {
    plannerModeResetBtn.disabled = false;
  }
}

function renderExecutorPreflightChecks(checks) {
  executorPreflightChecksEl.innerHTML = "";
  const list = Array.isArray(checks) ? checks : [];
  const frag = document.createDocumentFragment();
  for (const item of list) {
    const li = document.createElement("li");
    li.className = "event-item";

    const title = document.createElement("p");
    title.className = "event-title";
    const status = item.ok ? "ok" : "fail";
    title.textContent = `${item.name || "check"} · ${status}`;

    const meta = document.createElement("p");
    meta.className = "event-meta";
    meta.textContent = item.detail || "";

    li.appendChild(title);
    li.appendChild(meta);
    frag.appendChild(li);
  }
  executorPreflightChecksEl.appendChild(frag);
}

function renderReadinessStatusChecks(checks) {
  readinessStatusChecksEl.innerHTML = "";
  const list = Array.isArray(checks) ? checks : [];
  const frag = document.createDocumentFragment();
  for (const item of list) {
    const li = document.createElement("li");
    li.className = "event-item";

    const title = document.createElement("p");
    title.className = "event-title";
    const status = item.ok ? "ok" : "warn";
    const required = item.required === false ? "optional" : "required";
    title.textContent = `${item.name || "check"} · ${status} · ${required}`;

    const meta = document.createElement("p");
    meta.className = "event-meta";
    meta.textContent = item.detail || "";

    li.appendChild(title);
    li.appendChild(meta);
    frag.appendChild(li);
  }
  readinessStatusChecksEl.appendChild(frag);
}

async function runExecutorPreflight() {
  executorPreflightBtn.disabled = true;
  executorPreflightResultEl.textContent = "Preflight: running…";
  queueTelemetry("executor_preflight_requested", "executor preflight requested");
  try {
    const resp = await fetch("/api/executor/preflight");
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "executor preflight failed");
    const checks = Array.isArray(data.checks) ? data.checks : [];
    renderExecutorPreflightChecks(checks);
    const failed = checks.filter((item) => !item.ok);
    if (data.ok) {
      executorPreflightResultEl.textContent = `Preflight: passed (${checks.length} checks)`;
    } else {
      const firstFailure = failed[0]?.name || "unknown";
      executorPreflightResultEl.textContent = `Preflight: failed (${firstFailure})`;
    }
    queueTelemetry("executor_preflight_completed", "executor preflight completed", {
      ok: Boolean(data.ok),
      mode: data.mode || null,
      check_count: checks.length,
    });
    await refreshExecutorStatus();
  } catch (err) {
    executorPreflightResultEl.textContent = "Preflight: error";
    renderExecutorPreflightChecks([
      {
        name: "request",
        ok: false,
        detail: String(err),
      },
    ]);
    console.error("executor preflight error", err);
    queueTelemetry("executor_preflight_failed", "executor preflight failed", {
      error: String(err),
    });
  } finally {
    executorPreflightBtn.disabled = false;
  }
}

async function refreshReadinessStatus() {
  readinessStatusRefreshBtn.disabled = true;
  readinessStatusResultEl.textContent = "Readiness: running…";
  queueTelemetry("readiness_status_requested", "readiness status requested");
  try {
    const resp = await fetch("/api/readiness/status");
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "readiness status failed");
    const checks = Array.isArray(data.checks) ? data.checks : [];
    renderReadinessStatusChecks(checks);
    const summary = data.summary || {};
    const requiredTotal =
      Number(summary.required_total ?? checks.filter((item) => item.required !== false).length) || 0;
    const requiredPassed =
      Number(summary.required_passed ?? checks.filter((item) => item.required !== false && item.ok).length) || 0;
    const warningCount =
      Number(summary.warning_count ?? checks.filter((item) => item.required === false && !item.ok).length) || 0;
    const headline = data.ok ? "Readiness: ready" : "Readiness: check warnings";
    const ollamaCheck = checks.find((item) => item.name === "ollama_available");
    const ollamaSuffix =
      ollamaCheck && !ollamaCheck.ok && ollamaCheck.detail
        ? ` | ollama ${String(ollamaCheck.detail).slice(0, 120)}`
        : "";
    readinessStatusResultEl.textContent =
      `${headline} | required ${requiredPassed}/${requiredTotal} | warnings ${warningCount}` + ollamaSuffix;
    queueTelemetry("readiness_status_completed", "readiness status completed", {
      ok: Boolean(data.ok),
      checks: checks.length,
      collector_connected: Boolean(data.summary && data.summary.collector_connected),
    });
  } catch (err) {
    readinessStatusResultEl.textContent = "Readiness: error";
    renderReadinessStatusChecks([
      {
        name: "status_request",
        ok: false,
        required: true,
        detail: String(err),
      },
    ]);
    console.error("readiness status error", err);
    queueTelemetry("readiness_status_failed", "readiness status failed", {
      error: String(err),
    });
  } finally {
    readinessStatusRefreshBtn.disabled = false;
  }
}

function pickVoice() {
  const voices = window.speechSynthesis ? window.speechSynthesis.getVoices() : [];
  if (!voices || voices.length === 0) return null;
  const preferred = voices.find((v) => /microsoft|aria|jenny|guy/i.test(v.name) && /^en/i.test(v.lang));
  if (preferred) return preferred;
  return voices.find((v) => /^en/i.test(v.lang)) || voices[0];
}

function speakText(text) {
  const clean = (text || "").trim();
  if (!clean) return;
  if (!("speechSynthesis" in window)) {
    setVoiceState("tts unavailable", "warn");
    return;
  }

  if (currentUtterance) {
    window.speechSynthesis.cancel();
    currentUtterance = null;
  }

  const utter = new SpeechSynthesisUtterance(clean);
  const voice = pickVoice();
  if (voice) utter.voice = voice;
  utter.rate = 1.0;
  utter.pitch = 1.02;
  utter.volume = 1.0;

  utter.onstart = () => {
    speechActive = true;
    avatar.setSpeaking(true);
    setVoiceState("speaking", "good");
    queueTelemetry("tts_started", "speech started");
  };
  utter.onboundary = () => avatar.bump();
  utter.onerror = () => {
    speechActive = false;
    avatar.setSpeaking(false);
    setVoiceState(recognitionActive ? "listening" : "standby", recognitionActive ? "good" : "neutral");
    queueTelemetry("tts_error", "speech failed");
  };
  utter.onend = () => {
    speechActive = false;
    avatar.setSpeaking(false);
    setVoiceState(recognitionActive ? "listening" : "standby", recognitionActive ? "good" : "neutral");
    queueTelemetry("tts_completed", "speech completed");
  };

  currentUtterance = utter;
  window.speechSynthesis.speak(utter);
}

function stopMeterLoop() {
  if (meterRaf) {
    cancelAnimationFrame(meterRaf);
    meterRaf = null;
  }
}

function startMeterLoop() {
  if (!analyser || meterRaf) return;
  const loop = () => {
    if (!analyser) {
      meterRaf = null;
      return;
    }
    analyser.getByteTimeDomainData(audioData);
    let sumSquares = 0;
    for (let i = 0; i < audioData.length; i += 1) {
      const centered = (audioData[i] - 128) / 128;
      sumSquares += centered * centered;
    }
    const rms = Math.sqrt(sumSquares / audioData.length);
    const gain = recognitionActive ? 7.5 : 3.0;
    const level = Math.max(0, Math.min(1, rms * gain));
    avatar.setListeningLevel(level);
    meterRaf = requestAnimationFrame(loop);
  };
  meterRaf = requestAnimationFrame(loop);
}

async function ensureMicrophone() {
  if (mediaStream && analyser) return true;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return false;
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const source = audioContext.createMediaStreamSource(mediaStream);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 1024;
    audioData = new Uint8Array(analyser.fftSize);
    source.connect(analyser);
    startMeterLoop();
    sttStatusEl.textContent = "Mic: ready";
    queueTelemetry("mic_ready", "microphone ready");
    return true;
  } catch (err) {
    console.error("mic setup failed", err);
    sttStatusEl.textContent = "Mic: permission denied";
    setVoiceState("mic blocked", "warn");
    queueTelemetry("mic_denied", "microphone permission denied", { error: String(err) });
    return false;
  }
}

async function setupSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognitionSupported = Boolean(SpeechRecognition);
  if (!recognitionSupported) {
    voiceEngineEl.textContent = "stt unavailable";
    micBtn.disabled = true;
    sttStatusEl.textContent = "Mic: browser STT not supported";
    return;
  }

  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = "en-US";

  recognition.onstart = () => {
    recognitionActive = true;
    micBtn.textContent = "Stop Listening";
    setVoiceState(speechActive ? "speaking" : "listening", "good");
    sttStatusEl.textContent = "Mic: listening";
    queueTelemetry("stt_listening", "speech recognition started");
  };

  recognition.onend = () => {
    recognitionActive = false;
    micBtn.textContent = "Start Listening";
    setVoiceState(speechActive ? "speaking" : "standby", speechActive ? "good" : "neutral");
    sttStatusEl.textContent = "Mic: standby";
    avatar.setListeningLevel(0);
    queueTelemetry("stt_stopped", "speech recognition stopped");
  };

  recognition.onerror = (event) => {
    recognitionActive = false;
    micBtn.textContent = "Start Listening";
    setVoiceState("stt error", "warn");
    sttStatusEl.textContent = `Mic: ${event.error || "error"}`;
    queueTelemetry("stt_error", "speech recognition error", { error: event.error || "error" });
  };

  recognition.onresult = (event) => {
    let interim = "";
    let finals = "";
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const transcript = event.results[i][0].transcript || "";
      if (event.results[i].isFinal) finals += `${transcript} `;
      else interim += transcript;
    }

    if (finals.trim()) {
      recognitionTranscript = `${recognitionTranscript} ${finals}`.trim();
      voiceTextEl.value = recognitionTranscript;
      avatar.bump();
    }
    const preview = interim.trim() || finals.trim() || "Listening…";
    voiceTranscriptEl.textContent = preview;
  };
}

// ── Chat Functions ──

function appendChatMessage(role, text, meta = {}) {
  if (chatWelcomeEl) chatWelcomeEl.style.display = "none";

  const msg = document.createElement("div");
  msg.className = `chat-msg ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "chat-msg-bubble";
  bubble.textContent = text;
  msg.appendChild(bubble);

  if (role === "agent") {
    const badges = document.createElement("div");
    badges.className = "chat-msg-badges";
    if (meta.source) {
      const badge = document.createElement("span");
      badge.className = "chat-badge source";
      badge.textContent = meta.source;
      badges.appendChild(badge);
    }
    if (meta.action_triggered) {
      const badge = document.createElement("span");
      badge.className = "chat-badge action";
      badge.textContent = meta.run_id ? `action: ${meta.run_id.slice(0, 8)}` : "action started";
      badges.appendChild(badge);
    }
    if (badges.childNodes.length > 0) msg.appendChild(badges);
  }

  const metaEl = document.createElement("div");
  metaEl.className = "chat-msg-meta";
  metaEl.textContent = formatTime(new Date().toISOString());
  msg.appendChild(metaEl);

  chatMessagesEl.appendChild(msg);
  chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
}

function showChatTyping() {
  const el = document.createElement("div");
  el.className = "chat-typing";
  el.id = "chat-typing-indicator";
  el.innerHTML = '<div class="chat-typing-dots"><span></span><span></span><span></span></div>';
  chatMessagesEl.appendChild(el);
  chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
}

function hideChatTyping() {
  const el = document.getElementById("chat-typing-indicator");
  if (el) el.remove();
}

async function sendChatMessage(text) {
  const message = (text || "").trim();
  if (!message || chatSending) return;

  chatSending = true;
  chatSendBtn.disabled = true;
  chatInputEl.disabled = true;
  chatStatusEl.textContent = "thinking…";
  chatStatusEl.dataset.tone = "neutral";

  appendChatMessage("user", message);
  chatInputEl.value = "";
  showChatTyping();

  queueTelemetry("chat_sent", "chat message sent", { chars: message.length });

  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, allow_actions: true }),
    });
    const data = await resp.json();
    hideChatTyping();

    if (!resp.ok) {
      appendChatMessage("agent", data.detail || "Something went wrong.");
      chatStatusEl.textContent = "error";
      chatStatusEl.dataset.tone = "warn";
      queueTelemetry("chat_error", "chat request failed", { status: resp.status });
      return;
    }

    appendChatMessage("agent", data.response, {
      source: data.source,
      action_triggered: data.action_triggered,
      run_id: data.run_id,
    });

    chatStatusEl.textContent = "ready";
    chatStatusEl.dataset.tone = "good";

    if (data.desktop_context) {
      updateChatContextBar(data.desktop_context);
    }

    if (data.action_triggered && data.run_id) {
      activeRunId = data.run_id;
      queueTelemetry("chat_action_triggered", "chat triggered action", { run_id: data.run_id });
    }

    queueTelemetry("chat_received", "chat response received", {
      source: data.source,
      action_triggered: Boolean(data.action_triggered),
      chars: (data.response || "").length,
    });
  } catch (err) {
    hideChatTyping();
    appendChatMessage("agent", "Failed to reach the backend. Is the server running?");
    chatStatusEl.textContent = "offline";
    chatStatusEl.dataset.tone = "warn";
    queueTelemetry("chat_failed", "chat request failed", { error: String(err) });
  } finally {
    chatSending = false;
    chatSendBtn.disabled = false;
    chatInputEl.disabled = false;
    chatInputEl.focus();
  }
}

function updateChatContextBar(ctx) {
  if (!ctx) {
    chatContextIndicatorEl.textContent = "No desktop context";
    chatContextIndicatorEl.classList.remove("live");
    return;
  }
  const parts = [ctx.window_title || "Unknown window"];
  if (ctx.process_exe) parts[0] += ` (${ctx.process_exe})`;
  if (ctx.screenshot_available) parts.push("screenshot available");
  chatContextIndicatorEl.textContent = parts.join(" · ");
  chatContextIndicatorEl.classList.add("live");
}

// ── Agent Vision Functions ──

async function refreshAgentVision() {
  try {
    const resp = await fetch("/api/state/snapshot");
    const data = await resp.json();

    if (!data.context) {
      visionStatusEl.textContent = "offline";
      visionStatusEl.dataset.tone = "warn";
      visionWindowTitleEl.textContent = "No desktop context";
      visionProcessEl.textContent = "Process: —";
      visionTimestampEl.textContent = "Last update: —";
      visionUiaTextEl.textContent = "No UIA data available";
      visionScreenshotStatusEl.textContent = "Screenshot: unavailable";
      lastVisionContext = null;
      updateChatContextBar(null);
      return;
    }

    const ctx = data.context;
    lastVisionContext = ctx;
    visionStatusEl.textContent = "live";
    visionStatusEl.dataset.tone = "good";
    visionWindowTitleEl.textContent = ctx.window_title || "Unknown window";
    visionProcessEl.textContent = `Process: ${ctx.process_exe || "unknown"}`;
    visionTimestampEl.textContent = `Last update: ${formatTime(ctx.timestamp)}`;
    visionUiaTextEl.textContent = ctx.uia_summary || "No UIA data captured";
    visionScreenshotStatusEl.textContent = ctx.screenshot_available
      ? "Screenshot: available"
      : "Screenshot: unavailable";
    updateChatContextBar(ctx);
  } catch (err) {
    visionStatusEl.textContent = "error";
    visionStatusEl.dataset.tone = "warn";
    console.error("agent vision refresh failed", err);
  }
}

// ── Chat Event Listeners ──

chatSendBtn.addEventListener("click", () => {
  void sendChatMessage(chatInputEl.value);
});

chatInputEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void sendChatMessage(chatInputEl.value);
  }
});

chatSuggestionBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    const message = btn.dataset.message || btn.textContent;
    chatInputEl.value = message;
    void sendChatMessage(message);
  });
});

// ── Agent Vision Event Listeners ──

visionRefreshBtn.addEventListener("click", () => {
  void refreshAgentVision();
});

summaryBtn.addEventListener("click", async () => {
  summaryBtn.disabled = true;
  summaryText.textContent = "Summarizing…";
  queueTelemetry("summary_requested", "summary button clicked");
  try {
    const resp = await fetch("/api/summarize", { method: "POST" });
    if (!resp.ok) {
      const err = await resp.json();
      summaryText.textContent = err.detail || "Summary failed";
      queueTelemetry("summary_failed", "summary request failed", { detail: err.detail || "Summary failed" });
    } else {
      const data = await resp.json();
      summaryText.textContent = data.summary || "No summary.";
      queueTelemetry("summary_completed", "summary received", { has_summary: Boolean(data.summary) });
    }
  } catch (err) {
    summaryText.textContent = "Summary failed";
    queueTelemetry("summary_failed", "summary request failed", { error: String(err) });
  } finally {
    await checkOllama();
  }
});

summaryReadBtn.addEventListener("click", () => {
  queueTelemetry("summary_read_requested", "read summary clicked");
  speakText(summaryText.textContent);
});

ollamaModelRefreshBtn.addEventListener("click", async () => {
  await refreshOllamaModels();
});
ollamaModelApplyBtn.addEventListener("click", async () => {
  await applyOllamaModelOverride();
});
ollamaModelResetBtn.addEventListener("click", async () => {
  await resetOllamaModelOverride();
});
ollamaProbeBtn.addEventListener("click", async () => {
  await runOllamaProbe();
});

executorPreflightBtn.addEventListener("click", async () => {
  await runExecutorPreflight();
});
plannerModeApplyBtn.addEventListener("click", async () => {
  await applyPlannerMode();
});
plannerModeResetBtn.addEventListener("click", async () => {
  await resetPlannerModeOverride();
});
readinessStatusRefreshBtn.addEventListener("click", async () => {
  await refreshReadinessStatus();
});

speakBtn.addEventListener("click", () => {
  const text = (voiceTextEl.value || "").trim() || (voiceTranscriptEl.textContent || "").trim();
  queueTelemetry("speak_requested", "speak button clicked", { chars: text.length });
  speakText(text);
});

micBtn.addEventListener("click", async () => {
  if (!recognitionSupported || !recognition) return;
  const ok = await ensureMicrophone();
  if (!ok) return;

  if (recognitionActive) {
    queueTelemetry("stt_stop_requested", "stop listening clicked");
    recognition.stop();
  } else {
    try {
      if (audioContext && audioContext.state === "suspended") {
        await audioContext.resume();
      }
      queueTelemetry("stt_start_requested", "start listening clicked");
      recognition.start();
    } catch (err) {
      console.error("recognition start failed", err);
      setVoiceState("stt start failed", "warn");
      queueTelemetry("stt_start_failed", "start listening failed", { error: String(err) });
    }
  }
});

autonomyStartBtn.addEventListener("click", async () => {
  await startAutonomyRun();
});

autonomyApproveBtn.addEventListener("click", async () => {
  await approveAutonomyRun();
});

autonomyCancelBtn.addEventListener("click", async () => {
  await cancelAutonomyRun();
});

readinessGateBtn.addEventListener("click", async () => {
  await runReadinessGateFromUi();
});

readinessMatrixBtn.addEventListener("click", async () => {
  await runReadinessMatrixFromUi();
});

eventSearchEl.addEventListener("input", () => renderEvents());
eventCategoryEl.addEventListener("change", () => renderEvents());
eventTypeEl.addEventListener("change", () => renderEvents());
journeySessionEl.addEventListener("change", async () => {
  activeJourneySessionId = journeySessionEl.value || telemetrySessionId;
  await refreshJourneyConsole();
});
journeyRefreshBtn.addEventListener("click", async () => {
  await refreshJourneyConsole();
});
runtimeLogsRefreshBtn.addEventListener("click", async () => {
  setRuntimeLogsLiveMode();
  await refreshRuntimeLogs();
});
runtimeLogsCorrelateBtn.addEventListener("click", async () => {
  await correlateRuntimeLogsWithSession();
});
runtimeLogsClearBtn.addEventListener("click", async () => {
  await clearRuntimeLogs();
});
runtimeLogsLevelEl.addEventListener("change", async () => {
  if (runtimeLogsViewMode === "correlated") {
    await correlateRuntimeLogsWithSession({
      skipJourneyRefresh: true,
      sessionId: runtimeLogsCorrelatedSessionId,
    });
    return;
  }
  await refreshRuntimeLogs();
});
runtimeLogsSearchEl.addEventListener("keydown", async (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  if (runtimeLogsViewMode === "correlated") {
    await correlateRuntimeLogsWithSession({
      skipJourneyRefresh: true,
      sessionId: runtimeLogsCorrelatedSessionId,
    });
    return;
  }
  await refreshRuntimeLogs();
});

window.addEventListener("beforeunload", () => {
  if (journeyPollTimer) {
    clearInterval(journeyPollTimer);
    journeyPollTimer = null;
  }
  stopMeterLoop();
  if (recognitionActive && recognition) recognition.stop();
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
  }
  if (audioContext) audioContext.close();
  avatar.destroy();
  flushTelemetryOnUnload();
});

setVoiceState("standby", "neutral");
queueTelemetry("ui_boot", "ui booted", { user_agent: navigator.userAgent });
fetchSnapshot();
connectWs();
checkOllama();
refreshOllamaModels();
refreshExecutorStatus();
refreshPlannerModeStatus();
setupSpeechRecognition();
refreshJourneyConsole();
refreshRuntimeLogs();
refreshReadinessStatus();
refreshAgentVision();
startJourneyPolling();
scheduleTelemetryFlush();
