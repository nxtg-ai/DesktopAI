/** Health ribbon — polls /api/readiness/status and updates sticky bar. */

const POLL_INTERVAL_MS = 10_000;

const hrOllama = document.getElementById("hr-ollama");
const hrBridge = document.getElementById("hr-bridge");
const hrCollector = document.getElementById("hr-collector");
const hrOllamaDetail = document.getElementById("hr-ollama-detail");
const hrBridgeDetail = document.getElementById("hr-bridge-detail");
const hrCollectorDetail = document.getElementById("hr-collector-detail");
const hrSummary = document.getElementById("hr-summary");

function setStatus(el, detailEl, state, detail) {
  if (!el) return;
  el.classList.remove("ok", "warn", "down");
  el.classList.add(state);
  if (detailEl) {
    detailEl.textContent = detail;
    detailEl.title = detail;
  }
}

export async function refreshHealth() {
  try {
    const resp = await fetch("/api/readiness/status");
    const data = await resp.json();
    if (!resp.ok) throw new Error("readiness fetch failed");

    const summary = data.summary || {};

    // Ollama
    const ollamaOk = Boolean(summary.ollama_available);
    const ollamaModel = summary.ollama_active_model || summary.ollama_configured_model || "";
    const ollamaError = summary.ollama_last_error || "";
    if (ollamaOk) {
      setStatus(hrOllama, hrOllamaDetail, "ok", ollamaModel);
    } else {
      const shortErr = ollamaError.length > 40 ? ollamaError.slice(0, 40) + "\u2026" : ollamaError;
      setStatus(hrOllama, hrOllamaDetail, "down", shortErr || "unavailable");
    }

    // Bridge
    const bridgeOk = Boolean(summary.bridge_connected);
    const executorMode = summary.executor_mode || "";
    if (bridgeOk) {
      setStatus(hrBridge, hrBridgeDetail, "ok", executorMode);
    } else {
      setStatus(hrBridge, hrBridgeDetail, "down", "disconnected");
    }

    // Collector
    const collectorOk = Boolean(summary.collector_connected);
    const events = Number(summary.collector_total_events || 0);
    if (collectorOk) {
      setStatus(hrCollector, hrCollectorDetail, "ok", `${events} events`);
    } else {
      setStatus(hrCollector, hrCollectorDetail, "down", "no connection");
    }

    // Summary
    const required = Number(summary.required_passed || 0);
    const total = Number(summary.required_total || 0);
    const warnings = Number(summary.warning_count || 0);
    if (hrSummary) {
      const parts = [`${required}/${total} required`];
      if (warnings > 0) parts.push(`${warnings} warn`);
      hrSummary.textContent = parts.join(" \u00b7 ");
    }
  } catch {
    setStatus(hrOllama, hrOllamaDetail, "down", "fetch failed");
    setStatus(hrBridge, hrBridgeDetail, "down", "fetch failed");
    setStatus(hrCollector, hrCollectorDetail, "down", "fetch failed");
    if (hrSummary) hrSummary.textContent = "health check failed";
  }
}

let pollTimer = null;

export function startHealthPolling() {
  refreshHealth();
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(refreshHealth, POLL_INTERVAL_MS);
}
