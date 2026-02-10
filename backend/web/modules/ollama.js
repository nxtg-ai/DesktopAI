/** Ollama model management, probe, and diagnostics. */

import {
  ollamaStatusEl, ollamaDetailEl, ollamaModelSelectEl, ollamaModelRefreshBtn,
  ollamaModelApplyBtn, ollamaModelResetBtn, ollamaModelMetaEl, ollamaProbeBtn,
  ollamaProbeResultEl, summaryBtn, plannerModeSelectEl, plannerModeMetaEl,
  plannerModeApplyBtn, plannerModeResetBtn, executorStatusEl, executorPreflightBtn,
  executorPreflightResultEl, executorPreflightChecksEl, readinessStatusResultEl,
  readinessStatusRefreshBtn, readinessStatusChecksEl, formatTime,
} from "./state.js";
import { queueTelemetry } from "./telemetry.js";

function buildOllamaDiagnosticText(data) {
  const parts = [];
  const lastError = (data && data.last_error ? String(data.last_error) : "").trim();
  const lastStatus = data && Number.isInteger(data.last_http_status) ? data.last_http_status : null;
  const source = (data && data.last_check_source ? String(data.last_check_source) : "").trim();
  const checkedAt = data && data.last_check_at ? formatTime(data.last_check_at) : "";
  const configuredModel = (data && data.configured_model ? String(data.configured_model) : "").trim();
  const activeModel = (data && data.active_model ? String(data.active_model) : "").trim();
  if (activeModel) {
    parts.push(configuredModel && configuredModel !== activeModel
      ? `model ${activeModel} (fallback from ${configuredModel})` : `model ${activeModel}`);
  }
  if (lastError) parts.push(lastError);
  else if (lastStatus !== null) parts.push(`HTTP ${lastStatus}`);
  if (source) parts.push(`via ${source}`);
  if (checkedAt && checkedAt !== "Invalid Date") parts.push(`at ${checkedAt}`);
  return parts.length === 0 ? "no diagnostic details yet" : parts.join(" | ");
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
  ollamaModelMetaEl.textContent = `Ollama model: ${active} | configured ${configured} | source ${source} | installed ${models.length}`;
}

export async function refreshOllamaModels() {
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
      active_model: data.active_model || null, source: data.source || null,
    });
    return data;
  } catch (err) {
    if (ollamaModelMetaEl) ollamaModelMetaEl.textContent = "Ollama model: unavailable";
    console.error("ollama model list error", err);
    queueTelemetry("ollama_models_failed", "ollama model list failed", { error: String(err) });
    return null;
  } finally {
    ollamaModelRefreshBtn.disabled = false;
  }
}

export async function checkOllama() {
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
      if (ollamaDetailEl) ollamaDetailEl.textContent = `Ollama diagnostics: ${buildOllamaDiagnosticText(data)}`;
      summaryBtn.disabled = false;
      queueTelemetry("ollama_status", "ollama available", {
        source: data.last_check_source || null, configured_model: data.configured_model || null,
        active_model: data.active_model || data.model || null,
      });
    } else {
      ollamaStatusEl.textContent = "offline";
      const detailText = buildOllamaDiagnosticText(data);
      ollamaStatusEl.setAttribute("title", detailText);
      if (ollamaDetailEl) ollamaDetailEl.textContent = `Ollama diagnostics: ${detailText}`;
      summaryBtn.disabled = true;
      queueTelemetry("ollama_status", "ollama offline", {
        source: data.last_check_source || null, last_http_status: data.last_http_status ?? null,
        last_error: data.last_error || null, configured_model: data.configured_model || null,
        active_model: data.active_model || data.model || null,
      });
    }
    if (ollamaModelSelectEl && data.active_model) {
      const active = String(data.active_model);
      const option = Array.from(ollamaModelSelectEl.options).find((item) => item.value === active);
      if (option) ollamaModelSelectEl.value = active;
    }
    if (ollamaModelMetaEl) {
      const source = data.ollama_model_source || "unknown";
      const configured = data.configured_model || "unknown";
      const active = data.active_model || data.model || "unknown";
      ollamaModelMetaEl.textContent = `Ollama model: ${active} | configured ${configured} | source ${source}`;
    }
  } catch (err) {
    ollamaStatusEl.textContent = "unknown";
    ollamaStatusEl.removeAttribute("title");
    if (ollamaDetailEl) ollamaDetailEl.textContent = "Ollama diagnostics: status request failed";
    summaryBtn.disabled = true;
    queueTelemetry("ollama_status", "ollama status unknown", { error: String(err) });
  }
}

export async function applyOllamaModelOverride() {
  if (!ollamaModelSelectEl || !ollamaModelApplyBtn) return;
  const selected = String(ollamaModelSelectEl.value || "").trim();
  if (!selected) return;
  ollamaModelApplyBtn.disabled = true;
  if (ollamaModelMetaEl) ollamaModelMetaEl.textContent = `Ollama model: applying ${selected}\u2026`;
  queueTelemetry("ollama_model_update_requested", "ollama model override requested", { model: selected });
  try {
    const resp = await fetch("/api/ollama/model", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model: selected }) });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "ollama model update failed");
    queueTelemetry("ollama_model_updated", "ollama model override updated", { active_model: data.active_model || selected, source: data.ollama_model_source || null });
    await checkOllama();
    await refreshOllamaModels();
    await refreshReadinessStatus();
  } catch (err) {
    if (ollamaModelMetaEl) ollamaModelMetaEl.textContent = `Ollama model: update failed (${String(err)})`;
    console.error("ollama model update error", err);
    queueTelemetry("ollama_model_update_failed", "ollama model override failed", { model: selected, error: String(err) });
  } finally {
    ollamaModelApplyBtn.disabled = false;
  }
}

export async function resetOllamaModelOverride() {
  if (!ollamaModelResetBtn) return;
  ollamaModelResetBtn.disabled = true;
  if (ollamaModelMetaEl) ollamaModelMetaEl.textContent = "Ollama model: reverting to configured default\u2026";
  queueTelemetry("ollama_model_reset_requested", "ollama model override reset requested");
  try {
    const resp = await fetch("/api/ollama/model", { method: "DELETE" });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "ollama model reset failed");
    queueTelemetry("ollama_model_reset", "ollama model override reset", { active_model: data.active_model || null, source: data.ollama_model_source || null });
    await checkOllama();
    await refreshOllamaModels();
    await refreshReadinessStatus();
  } catch (err) {
    if (ollamaModelMetaEl) ollamaModelMetaEl.textContent = `Ollama model: reset failed (${String(err)})`;
    console.error("ollama model reset error", err);
    queueTelemetry("ollama_model_reset_failed", "ollama model reset failed", { error: String(err) });
  } finally {
    ollamaModelResetBtn.disabled = false;
  }
}

export async function runOllamaProbe() {
  if (!ollamaProbeBtn) return;
  ollamaProbeBtn.disabled = true;
  if (ollamaProbeResultEl) ollamaProbeResultEl.textContent = "Probe: running\u2026";
  queueTelemetry("ollama_probe_requested", "ollama probe requested");
  try {
    const resp = await fetch("/api/ollama/probe", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: "Respond with exactly: OK", timeout_s: 8.0, allow_fallback: false }) });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "ollama probe failed");
    const probe = data.probe || {};
    const ok = Boolean(probe.ok);
    const model = probe.model || data.active_model || "unknown";
    const elapsedMs = Number(probe.elapsed_ms || 0);
    if (ok) {
      if (ollamaProbeResultEl) ollamaProbeResultEl.textContent = `Probe: ok | model ${model} | ${elapsedMs} ms`;
      queueTelemetry("ollama_probe_completed", "ollama probe completed", { ok: true, model, elapsed_ms: elapsedMs });
    } else {
      const errorText = String(probe.error || "probe failed");
      if (ollamaProbeResultEl) ollamaProbeResultEl.textContent = `Probe: failed | model ${model} | ${elapsedMs} ms | ${errorText}`;
      queueTelemetry("ollama_probe_completed", "ollama probe completed", { ok: false, model, elapsed_ms: elapsedMs, error: errorText });
    }
    await checkOllama();
    await refreshReadinessStatus();
  } catch (err) {
    if (ollamaProbeResultEl) ollamaProbeResultEl.textContent = `Probe: error (${String(err)})`;
    console.error("ollama probe error", err);
    queueTelemetry("ollama_probe_failed", "ollama probe failed", { error: String(err) });
  } finally {
    ollamaProbeBtn.disabled = false;
  }
}

// ── Planner Mode ──

function renderPlannerModeStatus(data) {
  const mode = data && data.mode ? data.mode : "unknown";
  const available = Boolean(data && data.ollama_available);
  const required = Boolean(data && data.ollama_required);
  const source = data && data.source ? data.source : "unknown";
  const configuredDefault = data && data.configured_default_mode ? data.configured_default_mode : "unknown";
  if (plannerModeSelectEl && mode && plannerModeSelectEl.querySelector(`option[value="${mode}"]`)) {
    plannerModeSelectEl.value = mode;
  }
  plannerModeMetaEl.textContent =
    `Planner mode: ${mode} | source ${source} | default ${configuredDefault} | ` +
    `${available ? "ollama up" : "ollama down"} | ${required ? "required" : "optional"}`;
}

export async function refreshPlannerModeStatus() {
  try {
    const resp = await fetch("/api/autonomy/planner");
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "planner status failed");
    renderPlannerModeStatus(data);
    return data;
  } catch (err) {
    plannerModeMetaEl.textContent = "Planner mode: error";
    console.error("planner status error", err);
    queueTelemetry("planner_mode_status_failed", "planner mode status failed", { error: String(err) });
    return null;
  }
}

export async function applyPlannerMode() {
  const mode = plannerModeSelectEl.value;
  plannerModeApplyBtn.disabled = true;
  plannerModeMetaEl.textContent = `Planner mode: applying ${mode}\u2026`;
  queueTelemetry("planner_mode_update_requested", "planner mode update requested", { mode });
  try {
    const resp = await fetch("/api/autonomy/planner", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode }) });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "planner mode update failed");
    renderPlannerModeStatus(data);
    queueTelemetry("planner_mode_updated", "planner mode updated", { mode: data.mode || mode, ollama_required: Boolean(data.ollama_required) });
    await refreshReadinessStatus();
    await checkOllama();
  } catch (err) {
    plannerModeMetaEl.textContent = `Planner mode: update failed (${String(err)})`;
    console.error("planner mode update error", err);
    queueTelemetry("planner_mode_update_failed", "planner mode update failed", { mode, error: String(err) });
  } finally {
    plannerModeApplyBtn.disabled = false;
  }
}

export async function resetPlannerModeOverride() {
  plannerModeResetBtn.disabled = true;
  plannerModeMetaEl.textContent = "Planner mode: reverting to configured default\u2026";
  queueTelemetry("planner_mode_reset_requested", "planner mode reset requested");
  try {
    const resp = await fetch("/api/autonomy/planner", { method: "DELETE" });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "planner mode reset failed");
    renderPlannerModeStatus(data);
    queueTelemetry("planner_mode_reset", "planner mode reset to configured default", { mode: data.mode || null, source: data.source || null });
    await refreshReadinessStatus();
    await checkOllama();
  } catch (err) {
    plannerModeMetaEl.textContent = `Planner mode: reset failed (${String(err)})`;
    console.error("planner mode reset error", err);
    queueTelemetry("planner_mode_reset_failed", "planner mode reset failed", { error: String(err) });
  } finally {
    plannerModeResetBtn.disabled = false;
  }
}

// ── Executor / Readiness ──

export async function refreshExecutorStatus() {
  try {
    const resp = await fetch("/api/executor");
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "executor status failed");
    executorStatusEl.textContent = `Executor: ${data.mode || "unknown"} (${data.available ? "available" : "unavailable"})`;
  } catch (err) {
    executorStatusEl.textContent = "Executor: status unavailable";
    console.error("executor status error", err);
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
    title.textContent = `${item.name || "check"} \u00b7 ${item.ok ? "ok" : "fail"}`;
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
    title.textContent = `${item.name || "check"} \u00b7 ${item.ok ? "ok" : "warn"} \u00b7 ${item.required === false ? "optional" : "required"}`;
    const meta = document.createElement("p");
    meta.className = "event-meta";
    meta.textContent = item.detail || "";
    li.appendChild(title);
    li.appendChild(meta);
    frag.appendChild(li);
  }
  readinessStatusChecksEl.appendChild(frag);
}

export async function runExecutorPreflight() {
  executorPreflightBtn.disabled = true;
  executorPreflightResultEl.textContent = "Preflight: running\u2026";
  queueTelemetry("executor_preflight_requested", "executor preflight requested");
  try {
    const resp = await fetch("/api/executor/preflight");
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "executor preflight failed");
    const checks = Array.isArray(data.checks) ? data.checks : [];
    renderExecutorPreflightChecks(checks);
    const failed = checks.filter((item) => !item.ok);
    executorPreflightResultEl.textContent = data.ok
      ? `Preflight: passed (${checks.length} checks)`
      : `Preflight: failed (${failed[0]?.name || "unknown"})`;
    queueTelemetry("executor_preflight_completed", "executor preflight completed", { ok: Boolean(data.ok), mode: data.mode || null, check_count: checks.length });
    await refreshExecutorStatus();
  } catch (err) {
    executorPreflightResultEl.textContent = "Preflight: error";
    renderExecutorPreflightChecks([{ name: "request", ok: false, detail: String(err) }]);
    console.error("executor preflight error", err);
    queueTelemetry("executor_preflight_failed", "executor preflight failed", { error: String(err) });
  } finally {
    executorPreflightBtn.disabled = false;
  }
}

export async function refreshReadinessStatus() {
  readinessStatusRefreshBtn.disabled = true;
  readinessStatusResultEl.textContent = "Readiness: running\u2026";
  queueTelemetry("readiness_status_requested", "readiness status requested");
  try {
    const resp = await fetch("/api/readiness/status");
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "readiness status failed");
    const checks = Array.isArray(data.checks) ? data.checks : [];
    renderReadinessStatusChecks(checks);
    const summary = data.summary || {};
    const requiredTotal = Number(summary.required_total ?? checks.filter((i) => i.required !== false).length) || 0;
    const requiredPassed = Number(summary.required_passed ?? checks.filter((i) => i.required !== false && i.ok).length) || 0;
    const warningCount = Number(summary.warning_count ?? checks.filter((i) => i.required === false && !i.ok).length) || 0;
    const headline = data.ok ? "Readiness: ready" : "Readiness: check warnings";
    const ollamaCheck = checks.find((i) => i.name === "ollama_available");
    const ollamaSuffix = ollamaCheck && !ollamaCheck.ok && ollamaCheck.detail ? ` | ollama ${String(ollamaCheck.detail).slice(0, 120)}` : "";
    readinessStatusResultEl.textContent = `${headline} | required ${requiredPassed}/${requiredTotal} | warnings ${warningCount}${ollamaSuffix}`;
    queueTelemetry("readiness_status_completed", "readiness status completed", { ok: Boolean(data.ok), checks: checks.length, collector_connected: Boolean(data.summary && data.summary.collector_connected) });
  } catch (err) {
    readinessStatusResultEl.textContent = "Readiness: error";
    renderReadinessStatusChecks([{ name: "status_request", ok: false, required: true, detail: String(err) }]);
    console.error("readiness status error", err);
    queueTelemetry("readiness_status_failed", "readiness status failed", { error: String(err) });
  } finally {
    readinessStatusRefreshBtn.disabled = false;
  }
}
