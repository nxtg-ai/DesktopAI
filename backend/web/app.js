/** DesktopAI Web UI — entry point. */

import {
  appState, avatar,
  eventSearchEl, eventCategoryEl, eventTypeEl,
  summaryBtn, summaryReadBtn, summaryText,
  ollamaModelRefreshBtn, ollamaModelApplyBtn, ollamaModelResetBtn, ollamaProbeBtn,
  executorPreflightBtn,
  plannerModeApplyBtn, plannerModeResetBtn,
  readinessStatusRefreshBtn,
  voiceTextEl, voiceTranscriptEl, speakBtn, micBtn,
  autonomyStartBtn, autonomyApproveBtn, autonomyCancelBtn,
  readinessGateBtn, readinessMatrixBtn,
  chatSendBtn, chatInputEl, chatSuggestionBtns, personalityModeEl,
  visionRefreshBtn,
  journeySessionEl, journeyRefreshBtn,
  runtimeLogsRefreshBtn, runtimeLogsCorrelateBtn, runtimeLogsClearBtn,
  runtimeLogsLevelEl, runtimeLogsSearchEl,
  telemetrySessionId,
} from "./modules/state.js";

import {
  queueTelemetry, flushTelemetryOnUnload,
  refreshJourneyConsole, refreshRuntimeLogs, correlateRuntimeLogsWithSession,
  clearRuntimeLogs, startJourneyPolling,
} from "./modules/telemetry.js";

import { renderEvents } from "./modules/events.js";
import { fetchSnapshot, connectWs } from "./modules/websocket.js";

import {
  checkOllama, refreshOllamaModels, applyOllamaModelOverride, resetOllamaModelOverride,
  runOllamaProbe, refreshPlannerModeStatus, applyPlannerMode, resetPlannerModeOverride,
  refreshExecutorStatus, runExecutorPreflight, refreshReadinessStatus,
} from "./modules/ollama.js";

import {
  startAutonomyRun, approveAutonomyRun, cancelAutonomyRun,
  runReadinessGateFromUi, runReadinessMatrixFromUi,
} from "./modules/autonomy.js";

import {
  setVoiceState, speakText, stopMeterLoop, ensureMicrophone, setupSpeechRecognition,
} from "./modules/voice.js";

import { sendChatMessage, startNewChat, refreshRecipeSuggestions } from "./modules/chat.js";
import { refreshAgentVision } from "./modules/agent-vision.js";
import { refreshNotificationCount } from "./modules/notifications.js";
import { initShortcuts } from "./modules/shortcuts.js";

// ── Event Listeners ──

// Chat
chatSendBtn.addEventListener("click", () => void sendChatMessage(chatInputEl.value));
document.getElementById("chat-new-btn")?.addEventListener("click", startNewChat);
chatInputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void sendChatMessage(chatInputEl.value); }
});
chatSuggestionBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    const msg = btn.dataset.message || btn.textContent;
    chatInputEl.value = msg;
    void sendChatMessage(msg);
  });
});

// Agent Vision
visionRefreshBtn.addEventListener("click", () => void refreshAgentVision());

// Summary
summaryBtn.addEventListener("click", async () => {
  summaryBtn.disabled = true;
  summaryText.textContent = "Summarizing\u2026";
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

// Ollama
ollamaModelRefreshBtn.addEventListener("click", () => void refreshOllamaModels());
ollamaModelApplyBtn.addEventListener("click", () => void applyOllamaModelOverride());
ollamaModelResetBtn.addEventListener("click", () => void resetOllamaModelOverride());
ollamaProbeBtn.addEventListener("click", () => void runOllamaProbe());

// Executor / Planner / Readiness
executorPreflightBtn.addEventListener("click", () => void runExecutorPreflight());
plannerModeApplyBtn.addEventListener("click", () => void applyPlannerMode());
plannerModeResetBtn.addEventListener("click", () => void resetPlannerModeOverride());
readinessStatusRefreshBtn.addEventListener("click", () => void refreshReadinessStatus());

// Voice
speakBtn.addEventListener("click", () => {
  const text = (voiceTextEl.value || "").trim() || (voiceTranscriptEl.textContent || "").trim();
  queueTelemetry("speak_requested", "speak button clicked", { chars: text.length });
  speakText(text);
});
micBtn.addEventListener("click", async () => {
  if (!appState.recognitionSupported || !appState.recognition) return;
  const ok = await ensureMicrophone();
  if (!ok) return;
  if (appState.recognitionActive) {
    queueTelemetry("stt_stop_requested", "stop listening clicked");
    appState.recognition.stop();
  } else {
    try {
      if (appState.audioContext && appState.audioContext.state === "suspended") await appState.audioContext.resume();
      queueTelemetry("stt_start_requested", "start listening clicked");
      appState.recognition.start();
    } catch (err) {
      console.error("recognition start failed", err);
      setVoiceState("stt start failed", "warn");
      queueTelemetry("stt_start_failed", "start listening failed", { error: String(err) });
    }
  }
});

// Autonomy
autonomyStartBtn.addEventListener("click", () => void startAutonomyRun());
autonomyApproveBtn.addEventListener("click", () => void approveAutonomyRun());
autonomyCancelBtn.addEventListener("click", () => void cancelAutonomyRun());
readinessGateBtn.addEventListener("click", () => void runReadinessGateFromUi());
readinessMatrixBtn.addEventListener("click", () => void runReadinessMatrixFromUi());

// Event filters
eventSearchEl.addEventListener("input", () => renderEvents());
eventCategoryEl.addEventListener("change", () => renderEvents());
eventTypeEl.addEventListener("change", () => renderEvents());

// Journey console
journeySessionEl.addEventListener("change", async () => {
  appState.activeJourneySessionId = journeySessionEl.value || telemetrySessionId;
  await refreshJourneyConsole();
});
journeyRefreshBtn.addEventListener("click", () => void refreshJourneyConsole());

// Runtime logs
runtimeLogsRefreshBtn.addEventListener("click", async () => {
  appState.runtimeLogsViewMode = "live";
  appState.runtimeLogsCorrelatedSessionId = "";
  await refreshRuntimeLogs();
});
runtimeLogsCorrelateBtn.addEventListener("click", () => void correlateRuntimeLogsWithSession());
runtimeLogsClearBtn.addEventListener("click", () => void clearRuntimeLogs());
runtimeLogsLevelEl.addEventListener("change", async () => {
  if (appState.runtimeLogsViewMode === "correlated") {
    await correlateRuntimeLogsWithSession({ skipJourneyRefresh: true, sessionId: appState.runtimeLogsCorrelatedSessionId });
    return;
  }
  await refreshRuntimeLogs();
});
runtimeLogsSearchEl.addEventListener("keydown", async (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  if (appState.runtimeLogsViewMode === "correlated") {
    await correlateRuntimeLogsWithSession({ skipJourneyRefresh: true, sessionId: appState.runtimeLogsCorrelatedSessionId });
    return;
  }
  await refreshRuntimeLogs();
});

// Unload
window.addEventListener("beforeunload", () => {
  if (appState.journeyPollTimer) { clearInterval(appState.journeyPollTimer); appState.journeyPollTimer = null; }
  stopMeterLoop();
  if (appState.recognitionActive && appState.recognition) appState.recognition.stop();
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  if (appState.mediaStream) appState.mediaStream.getTracks().forEach((t) => t.stop());
  if (appState.audioContext) appState.audioContext.close();
  avatar.destroy();
  flushTelemetryOnUnload();
});

// Theme toggle
document.getElementById("theme-toggle")?.addEventListener("click", () => {
  const html = document.documentElement;
  const current = html.getAttribute("data-theme");
  const next = current === "dark" ? "" : "dark";
  if (next) {
    html.setAttribute("data-theme", next);
  } else {
    html.removeAttribute("data-theme");
  }
  const icon = document.getElementById("theme-icon");
  if (icon) icon.textContent = next === "dark" ? "\u2600" : "\u263E";
  try { localStorage.setItem("desktopai-theme", next); } catch {}
});

// Restore theme from localStorage
try {
  const saved = localStorage.getItem("desktopai-theme");
  if (saved === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
    const icon = document.getElementById("theme-icon");
    if (icon) icon.textContent = "\u2600";
  }
} catch {}

// Personality mode persistence
if (personalityModeEl) {
  try {
    const savedMode = localStorage.getItem("desktopai-personality");
    if (savedMode && personalityModeEl.querySelector(`option[value="${savedMode}"]`)) {
      personalityModeEl.value = savedMode;
    }
  } catch {}
  personalityModeEl.addEventListener("change", () => {
    try { localStorage.setItem("desktopai-personality", personalityModeEl.value); } catch {}
  });
}

// ── Boot ──

initShortcuts();
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
refreshNotificationCount();
refreshRecipeSuggestions();
startJourneyPolling();
