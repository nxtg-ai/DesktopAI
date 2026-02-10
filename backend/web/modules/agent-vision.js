/** Agent vision panel: desktop context display. */

import {
  appState, visionStatusEl, visionWindowTitleEl, visionProcessEl,
  visionTimestampEl, visionUiaTextEl, visionScreenshotStatusEl, formatTime,
} from "./state.js";
import { updateChatContextBar } from "./chat.js";

export async function refreshAgentVision() {
  try {
    const resp = await fetch("/api/state/snapshot");
    const data = await resp.json();
    if (!data.context) {
      visionStatusEl.textContent = "offline";
      visionStatusEl.dataset.tone = "warn";
      visionWindowTitleEl.textContent = "No desktop context";
      visionProcessEl.textContent = "Process: \u2014";
      visionTimestampEl.textContent = "Last update: \u2014";
      visionUiaTextEl.textContent = "No UIA data available";
      visionScreenshotStatusEl.textContent = "Screenshot: unavailable";
      appState.lastVisionContext = null;
      updateChatContextBar(null);
      return;
    }
    const ctx = data.context;
    appState.lastVisionContext = ctx;
    visionStatusEl.textContent = "live";
    visionStatusEl.dataset.tone = "good";
    visionWindowTitleEl.textContent = ctx.window_title || "Unknown window";
    visionProcessEl.textContent = `Process: ${ctx.process_exe || "unknown"}`;
    visionTimestampEl.textContent = `Last update: ${formatTime(ctx.timestamp)}`;
    visionUiaTextEl.textContent = ctx.uia_summary || "No UIA data captured";
    visionScreenshotStatusEl.textContent = ctx.screenshot_available ? "Screenshot: available" : "Screenshot: unavailable";
    updateChatContextBar(ctx);
  } catch (err) {
    visionStatusEl.textContent = "error";
    visionStatusEl.dataset.tone = "warn";
    console.error("agent vision refresh failed", err);
  }
}
