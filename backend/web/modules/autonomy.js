/** Autonomy controls, readiness gate, and readiness matrix. */

import {
  appState, autonomyStatusEl, autonomyObjectiveEl, autonomyMaxIterationsEl,
  autonomyParallelAgentsEl, autonomyAutoApproveEl, autonomyStartBtn, autonomyApproveBtn,
  autonomyCancelBtn, autonomyRunMetaEl, autonomyLogEl, readinessGateBtn,
  readinessGateResultEl, readinessMatrixObjectivesEl, readinessMatrixBtn,
  readinessMatrixResultEl, readinessMatrixResultsEl, formatTime,
} from "./state.js";
import { queueTelemetry } from "./telemetry.js";

function setAutonomyStatus(status) {
  autonomyStatusEl.textContent = status || "idle";
  if (status === "completed" || status === "running") autonomyStatusEl.dataset.tone = "good";
  else if (status === "failed" || status === "cancelled") autonomyStatusEl.dataset.tone = "warn";
  else autonomyStatusEl.dataset.tone = "neutral";
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
    title.textContent = `${item.agent || "agent"} \u00b7 ${item.message || ""}`;
    const meta = document.createElement("p");
    meta.className = "event-meta";
    meta.textContent = formatTime(item.timestamp);
    li.appendChild(title);
    li.appendChild(meta);
    frag.appendChild(li);
  }
  autonomyLogEl.appendChild(frag);
}

export function applyRunUiState(run) {
  if (!run) {
    appState.activeRunId = null;
    appState.activeApprovalToken = null;
    appState.lastRunFingerprint = "";
    setAutonomyStatus("idle");
    autonomyRunMetaEl.textContent = "Run: \u2014";
    autonomyApproveBtn.disabled = true;
    autonomyCancelBtn.disabled = true;
    autonomyStartBtn.disabled = false;
    renderAutonomyLog([]);
    return;
  }
  appState.activeRunId = run.run_id;
  appState.activeApprovalToken = run.approval_token || null;
  setAutonomyStatus(run.status);
  const runPlannerMode = run.planner_mode || "deterministic";
  const runFingerprint = `${run.run_id}|${run.status}|${run.iteration}|${appState.activeApprovalToken ? "1" : "0"}|${runPlannerMode}`;
  if (runFingerprint !== appState.lastRunFingerprint) {
    if (run.status === "waiting_approval") {
      queueTelemetry("autonomy_waiting_approval", "autonomy run waiting approval", { run_id: run.run_id, iteration: run.iteration, planner_mode: runPlannerMode });
    } else {
      queueTelemetry("autonomy_status_changed", "autonomy run status changed", { run_id: run.run_id, status: run.status, iteration: run.iteration, planner_mode: runPlannerMode });
    }
    appState.lastRunFingerprint = runFingerprint;
  }
  autonomyRunMetaEl.textContent = `Run: ${run.run_id} \u00b7 mode ${runPlannerMode} \u00b7 iteration ${run.iteration}/${run.max_iterations}`;
  autonomyApproveBtn.disabled = run.status !== "waiting_approval" || !appState.activeApprovalToken;
  autonomyCancelBtn.disabled = ["completed", "failed", "cancelled"].includes(run.status);
  autonomyStartBtn.disabled = run.status === "running" || run.status === "waiting_approval";
  renderAutonomyLog(run.agent_log || []);
}

export async function startAutonomyRun() {
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
  queueTelemetry("autonomy_start_requested", "start clicked", { objective, ...body });
  try {
    const resp = await fetch("/api/autonomy/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const payload = await resp.json();
    if (!resp.ok) throw new Error(payload.detail || "failed to start run");
    applyRunUiState(payload.run);
    queueTelemetry("autonomy_started", "autonomy run started", { run_id: payload.run.run_id, status: payload.run.status });
  } catch (err) {
    setAutonomyStatus("start failed");
    autonomyStatusEl.dataset.tone = "warn";
    console.error("autonomy start error", err);
    queueTelemetry("autonomy_start_failed", "autonomy start failed", { error: String(err) });
  } finally {
    if (!appState.activeRunId || autonomyStatusEl.textContent !== "running") autonomyStartBtn.disabled = false;
  }
}

export async function approveAutonomyRun() {
  if (!appState.activeRunId || !appState.activeApprovalToken) return;
  queueTelemetry("autonomy_approve_requested", "approve clicked", { run_id: appState.activeRunId });
  try {
    const resp = await fetch(`/api/autonomy/runs/${appState.activeRunId}/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approval_token: appState.activeApprovalToken }) });
    const payload = await resp.json();
    if (!resp.ok) throw new Error(payload.detail || "approve failed");
    applyRunUiState(payload.run);
    queueTelemetry("autonomy_approved", "autonomy approval accepted", { run_id: payload.run.run_id, status: payload.run.status });
  } catch (err) {
    setAutonomyStatus("approve failed");
    autonomyStatusEl.dataset.tone = "warn";
    console.error("autonomy approve error", err);
    queueTelemetry("autonomy_approve_failed", "autonomy approval failed", { run_id: appState.activeRunId, error: String(err) });
  }
}

export async function cancelAutonomyRun() {
  if (!appState.activeRunId) return;
  queueTelemetry("autonomy_cancel_requested", "cancel clicked", { run_id: appState.activeRunId });
  try {
    const resp = await fetch(`/api/autonomy/runs/${appState.activeRunId}/cancel`, { method: "POST" });
    const payload = await resp.json();
    if (!resp.ok) throw new Error(payload.detail || "cancel failed");
    applyRunUiState(payload.run);
    queueTelemetry("autonomy_cancelled", "autonomy run cancelled", { run_id: payload.run.run_id, status: payload.run.status });
  } catch (err) {
    setAutonomyStatus("cancel failed");
    autonomyStatusEl.dataset.tone = "warn";
    console.error("autonomy cancel error", err);
    queueTelemetry("autonomy_cancel_failed", "autonomy cancel failed", { run_id: appState.activeRunId, error: String(err) });
  }
}

export async function runReadinessGateFromUi() {
  const objective = (autonomyObjectiveEl.value || "").trim();
  if (!objective) {
    readinessGateResultEl.textContent = "Readiness Gate: objective required";
    queueTelemetry("readiness_gate_rejected", "objective required");
    return;
  }
  const body = {
    objective, timeout_s: 30,
    max_iterations: Number(autonomyMaxIterationsEl.value || 24),
    parallel_agents: Number(autonomyParallelAgentsEl.value || 3),
    auto_approve_irreversible: Boolean(autonomyAutoApproveEl.checked),
    require_preflight_ok: true,
  };
  readinessGateBtn.disabled = true;
  readinessGateResultEl.textContent = "Readiness Gate: running\u2026";
  queueTelemetry("readiness_gate_requested", "readiness gate requested", { objective, auto_approve_irreversible: body.auto_approve_irreversible });
  try {
    const resp = await fetch("/api/readiness/gate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const payload = await resp.json();
    if (!resp.ok) throw new Error(payload.detail || "readiness gate failed");
    const reason = payload.reason || "unknown";
    const elapsedMs = Number(payload.elapsed_ms || 0);
    readinessGateResultEl.textContent = `Readiness Gate: ${reason} (${elapsedMs} ms)`;
    queueTelemetry("readiness_gate_completed", "readiness gate completed", { ok: Boolean(payload.ok), reason, elapsed_ms: elapsedMs });
    if (payload.run) applyRunUiState(payload.run);
  } catch (err) {
    readinessGateResultEl.textContent = "Readiness Gate: error";
    queueTelemetry("readiness_gate_failed", "readiness gate failed", { error: String(err) });
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
    title.textContent = `${item && item.objective ? item.objective : "objective"} \u00b7 ${report.reason || "unknown"}`;
    const meta = document.createElement("p");
    meta.className = "event-meta";
    meta.textContent = `ok=${Boolean(report.ok)} \u00b7 ${Number(report.elapsed_ms || 0)} ms`;
    li.appendChild(title);
    li.appendChild(meta);
    frag.appendChild(li);
  }
  readinessMatrixResultsEl.appendChild(frag);
}

export async function runReadinessMatrixFromUi() {
  const raw = (readinessMatrixObjectivesEl.value || "").trim();
  const objectives = raw.split("\n").map((i) => i.trim()).filter((i) => i.length > 0);
  if (objectives.length === 0) {
    readinessMatrixResultEl.textContent = "Readiness Matrix: objective list required";
    queueTelemetry("readiness_matrix_rejected", "objective list required");
    return;
  }
  const body = {
    objectives, timeout_s: 30,
    max_iterations: Number(autonomyMaxIterationsEl.value || 24),
    parallel_agents: Number(autonomyParallelAgentsEl.value || 3),
    auto_approve_irreversible: Boolean(autonomyAutoApproveEl.checked),
    require_preflight_ok: true, stop_on_failure: false,
  };
  readinessMatrixBtn.disabled = true;
  readinessMatrixResultEl.textContent = "Readiness Matrix: running\u2026";
  queueTelemetry("readiness_matrix_requested", "readiness matrix requested", { objectives: objectives.length, auto_approve_irreversible: body.auto_approve_irreversible });
  try {
    const resp = await fetch("/api/readiness/matrix", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const payload = await resp.json();
    if (!resp.ok) throw new Error(payload.detail || "readiness matrix failed");
    const passed = Number(payload.passed || 0);
    const total = Number(payload.total || 0);
    const elapsedMs = Number(payload.elapsed_ms || 0);
    readinessMatrixResultEl.textContent = `Readiness Matrix: ${passed}/${total} passed (${elapsedMs} ms)`;
    renderReadinessMatrixResults(payload.results || []);
    queueTelemetry("readiness_matrix_completed", "readiness matrix completed", { ok: Boolean(payload.ok), passed, total, elapsed_ms: elapsedMs });
  } catch (err) {
    readinessMatrixResultEl.textContent = "Readiness Matrix: error";
    renderReadinessMatrixResults([]);
    queueTelemetry("readiness_matrix_failed", "readiness matrix failed", { error: String(err) });
    console.error("readiness matrix error", err);
  } finally {
    readinessMatrixBtn.disabled = false;
  }
}
