/** Telemetry queue, batching, and flush logic. */

import {
  appState, telemetrySessionId, TELEMETRY_BATCH_SIZE, TELEMETRY_FLUSH_INTERVAL_MS,
  journeySessionEl, journeyMetaEl, journeyEventsEl, journeyEventCountEl,
  journeyRefreshBtn, JOURNEY_POLL_MS, runtimeLogsMetaEl, runtimeLogCountEl,
  runtimeLogsEl, runtimeLogsSearchEl, runtimeLogsLevelEl, runtimeLogsClearBtn,
  runtimeLogsCorrelateBtn, RUNTIME_LOG_LIMIT, formatTime,
} from "./state.js";

function scheduleTelemetryFlush() {
  if (appState.telemetryFlushTimer) return;
  appState.telemetryFlushTimer = setTimeout(() => {
    appState.telemetryFlushTimer = null;
    void flushTelemetry();
  }, TELEMETRY_FLUSH_INTERVAL_MS);
}

export function queueTelemetry(kind, message, data = {}) {
  appState.telemetryQueue.push({
    session_id: telemetrySessionId,
    kind,
    message,
    timestamp: new Date().toISOString(),
    data,
  });
  if (appState.telemetryQueue.length >= TELEMETRY_BATCH_SIZE) {
    void flushTelemetry();
    return;
  }
  scheduleTelemetryFlush();
}

export async function flushTelemetry(options = {}) {
  const force = Boolean(options.force);
  if (appState.telemetryFlushInFlight || appState.telemetryQueue.length === 0) return;
  appState.telemetryFlushInFlight = true;
  if (appState.telemetryFlushTimer) {
    clearTimeout(appState.telemetryFlushTimer);
    appState.telemetryFlushTimer = null;
  }
  const batch = appState.telemetryQueue.slice(0, TELEMETRY_BATCH_SIZE);
  try {
    const resp = await fetch("/api/ui-telemetry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events: batch }),
      keepalive: force,
    });
    if (resp.ok) {
      appState.telemetryQueue = appState.telemetryQueue.slice(batch.length);
    }
  } catch (err) {
    console.debug("telemetry flush failed", err);
  } finally {
    appState.telemetryFlushInFlight = false;
    if (appState.telemetryQueue.length > 0) scheduleTelemetryFlush();
  }
}

export function flushTelemetryOnUnload() {
  if (appState.telemetryQueue.length === 0 || !navigator.sendBeacon) return;
  const batch = appState.telemetryQueue.slice(0, TELEMETRY_BATCH_SIZE);
  const blob = new Blob([JSON.stringify({ events: batch })], { type: "application/json" });
  const sent = navigator.sendBeacon("/api/ui-telemetry", blob);
  if (sent) {
    appState.telemetryQueue = appState.telemetryQueue.slice(batch.length);
  }
}

// ── Journey Console ──

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
    title.textContent = `${item.kind || "event"}${item.message ? ` \u00b7 ${item.message}` : ""}`;
    const meta = document.createElement("p");
    meta.className = "event-meta";
    meta.textContent = formatTime(item.timestamp);
    li.appendChild(title);
    li.appendChild(meta);
    frag.appendChild(li);
  }
  journeyEventsEl.appendChild(frag);
}

function applyJourneySessionOptions(sessions) {
  const previous = appState.activeJourneySessionId || journeySessionEl.value || telemetrySessionId;
  const options = [];
  const seen = new Set();
  const addSession = (sessionId, label) => {
    const id = (sessionId || "").trim();
    if (!id || seen.has(id)) return;
    seen.add(id);
    options.push({ sessionId: id, label });
  };
  addSession(telemetrySessionId, `this session \u00b7 ${telemetrySessionId}`);
  for (const session of sessions) {
    const sessionId = String(session.session_id || "").trim();
    const count = Number(session.event_count || 0);
    addSession(sessionId, `${sessionId} \u00b7 ${count} events`);
  }
  journeySessionEl.innerHTML = "";
  for (const option of options) {
    const node = document.createElement("option");
    node.value = option.sessionId;
    node.textContent = option.label;
    journeySessionEl.appendChild(node);
  }
  const exists = options.some((o) => o.sessionId === previous);
  appState.activeJourneySessionId = exists ? previous : telemetrySessionId;
  journeySessionEl.value = appState.activeJourneySessionId;
}

export async function refreshJourneyConsole() {
  try {
    await flushTelemetry({ force: true });
    const sessions = await fetchJourneySessions();
    applyJourneySessionOptions(sessions);
    const events = await fetchJourneyEvents(appState.activeJourneySessionId);
    renderJourneyEvents(events);
    journeyMetaEl.textContent = `Session: ${appState.activeJourneySessionId} \u00b7 source: live telemetry`;
  } catch (err) {
    journeyMetaEl.textContent = "Session: telemetry unavailable";
    journeyEventCountEl.textContent = "0";
    journeyEventsEl.innerHTML = "";
    console.error("journey console refresh failed", err);
  }
}

// ── Runtime Logs ──

function getRuntimeLogFilters() {
  const contains = (runtimeLogsSearchEl.value || "").trim();
  const level = (runtimeLogsLevelEl.value || "").trim();
  return { contains, level };
}

function runtimeFilterSuffix() {
  const filters = getRuntimeLogFilters();
  const parts = [];
  if (filters.level) parts.push(`level=${filters.level}`);
  if (filters.contains) parts.push(`contains=${filters.contains}`);
  return parts.length > 0 ? ` \u00b7 ${parts.join(" \u00b7 ")}` : "";
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
    title.textContent = `${item.level || "INFO"} \u00b7 ${item.logger || "logger"}`;
    const meta = document.createElement("p");
    meta.className = "event-meta";
    meta.textContent = `${formatTime(item.timestamp)} \u00b7 ${item.message || ""}`;
    li.appendChild(title);
    li.appendChild(meta);
    frag.appendChild(li);
  }
  runtimeLogsEl.appendChild(frag);
}

export async function refreshRuntimeLogs() {
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

export async function correlateRuntimeLogsWithSession(options = {}) {
  const skipJourneyRefresh = Boolean(options.skipJourneyRefresh);
  runtimeLogsCorrelateBtn.disabled = true;
  try {
    if (!skipJourneyRefresh) await refreshJourneyConsole();
    const sessionId = (
      options.sessionId ||
      appState.runtimeLogsCorrelatedSessionId ||
      appState.activeJourneySessionId ||
      journeySessionEl.value ||
      telemetrySessionId ||
      ""
    ).trim();
    if (!sessionId) throw new Error("session unavailable");
    const payload = await fetchCorrelatedRuntimeLogs(sessionId);
    const logs = Array.isArray(payload.logs) ? payload.logs : [];
    renderRuntimeLogs(logs);
    const windowInfo = payload.window
      ? `${formatTime(payload.window.since)} \u2192 ${formatTime(payload.window.until)}`
      : "no telemetry window";
    runtimeLogsMetaEl.textContent = `Logs: session ${sessionId} \u00b7 ${windowInfo}${runtimeFilterSuffix()}`;
    appState.runtimeLogsViewMode = "correlated";
    appState.runtimeLogsCorrelatedSessionId = (sessionId || "").trim();
    queueTelemetry("runtime_logs_correlated", "runtime logs correlated to session", {
      session_id: sessionId, logs: logs.length, has_window: Boolean(payload.window),
    });
  } catch (err) {
    runtimeLogsMetaEl.textContent = "Logs: correlation failed";
    console.error("runtime logs correlate failed", err);
    queueTelemetry("runtime_logs_correlate_failed", "runtime log correlation failed", { error: String(err) });
  } finally {
    runtimeLogsCorrelateBtn.disabled = false;
  }
}

export async function clearRuntimeLogs() {
  runtimeLogsClearBtn.disabled = true;
  try {
    const resp = await fetch("/api/runtime-logs/reset", { method: "POST" });
    if (!resp.ok) throw new Error("failed to clear runtime logs");
    appState.runtimeLogsViewMode = "live";
    appState.runtimeLogsCorrelatedSessionId = "";
    await refreshRuntimeLogs();
  } catch (err) {
    runtimeLogsMetaEl.textContent = "Logs: clear failed";
    console.error("runtime logs clear failed", err);
  } finally {
    runtimeLogsClearBtn.disabled = false;
  }
}

export function startJourneyPolling() {
  if (appState.journeyPollTimer) clearInterval(appState.journeyPollTimer);
  appState.journeyPollTimer = setInterval(() => {
    void refreshJourneyConsole();
    if (appState.runtimeLogsViewMode === "live") void refreshRuntimeLogs();
  }, JOURNEY_POLL_MS);
}
