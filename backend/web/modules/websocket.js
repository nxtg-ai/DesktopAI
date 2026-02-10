/** WebSocket connection and real-time event handling. */

import { appState, statusEl, avatar, MAX_EVENTS } from "./state.js";
import { queueTelemetry } from "./telemetry.js";
import { renderEvents, updateCurrent } from "./events.js";
import { applyRunUiState } from "./autonomy.js";
import { refreshAgentVision } from "./agent-vision.js";
import { handleNotificationWsMessage } from "./notifications.js";

function setStatus(text, tone) {
  statusEl.textContent = text;
  statusEl.style.color = tone === "good" ? "#00b8a9" : tone === "warn" ? "#ff4d4d" : "#5b6470";
  if (appState.lastStatusText !== text) {
    queueTelemetry("connection_status", text, { tone });
    appState.lastStatusText = text;
  }
  if (tone === "good") avatar.setConnection("live");
  if (tone === "warn") avatar.setConnection("warn");
  if (tone !== "good" && tone !== "warn") avatar.setConnection("connecting");
}

export async function fetchSnapshot() {
  try {
    const [stateResp, eventsResp] = await Promise.all([fetch("/api/state"), fetch(`/api/events?limit=${MAX_EVENTS}`)]);
    const state = await stateResp.json();
    const eventsData = await eventsResp.json();
    appState.events = eventsData.events || [];
    updateCurrent(state);
    renderEvents();
    queueTelemetry("snapshot_fetched", "initial snapshot fetched", { events: appState.events.length, has_current: Boolean(state.current) });
  } catch (err) {
    console.error("snapshot error", err);
    queueTelemetry("snapshot_failed", "initial snapshot failed", { error: String(err) });
  }
}

export function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  appState.ws = new WebSocket(`${proto}://${location.host}/ws`);
  setStatus("connecting", "neutral");
  appState.ws.onopen = () => {
    setStatus("live", "good");
    queueTelemetry("ws_open", "ui websocket connected");
  };
  appState.ws.onmessage = (message) => {
    try {
      const payload = JSON.parse(message.data);
      if (payload.type === "snapshot") {
        appState.events = payload.events || [];
        updateCurrent(payload.state);
        renderEvents();
        applyRunUiState(payload.autonomy_run || null);
        queueTelemetry("ws_snapshot", "ws snapshot received", { events: appState.events.length, has_run: Boolean(payload.autonomy_run) });
      }
      if (payload.type === "event" && payload.event) {
        appState.events.push(payload.event);
        if (appState.events.length > MAX_EVENTS) appState.events = appState.events.slice(-MAX_EVENTS);
        avatar.bump();
        renderEvents();
        void refreshAgentVision();
        queueTelemetry("event_stream_received", "live event received", { type: payload.event.type || "foreground", process_exe: payload.event.process_exe || "", title: payload.event.title || "" });
      }
      if (payload.type === "state") {
        updateCurrent(payload.state);
        void refreshAgentVision();
      }
      if (payload.type === "autonomy_run" && payload.run) {
        if (!appState.activeRunId || payload.run.run_id === appState.activeRunId) applyRunUiState(payload.run);
      }
      if (payload.type === "notification" && payload.notification) {
        handleNotificationWsMessage(payload.notification);
      }
    } catch (err) {
      console.error("ws message error", err);
      queueTelemetry("ws_message_error", "ws payload parse failed", { error: String(err) });
    }
  };
  appState.ws.onclose = () => {
    setStatus("disconnected", "warn");
    queueTelemetry("ws_closed", "ui websocket disconnected");
    setTimeout(connectWs, 1500);
  };
  appState.ws.onerror = () => {
    queueTelemetry("ws_error", "ui websocket error");
    appState.ws.close();
  };
}
