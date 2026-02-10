/** Chat message handling, typing indicator, and context bar. */

import {
  appState, chatStatusEl, chatContextIndicatorEl, chatMessagesEl, chatWelcomeEl,
  chatInputEl, chatSendBtn, formatTime,
} from "./state.js";
import { queueTelemetry } from "./telemetry.js";

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

export function updateChatContextBar(ctx) {
  if (!ctx) {
    chatContextIndicatorEl.textContent = "No desktop context";
    chatContextIndicatorEl.classList.remove("live");
    return;
  }
  const parts = [ctx.window_title || "Unknown window"];
  if (ctx.process_exe) parts[0] += ` (${ctx.process_exe})`;
  if (ctx.screenshot_available) parts.push("screenshot available");
  chatContextIndicatorEl.textContent = parts.join(" \u00b7 ");
  chatContextIndicatorEl.classList.add("live");
}

export async function sendChatMessage(text) {
  const message = (text || "").trim();
  if (!message || appState.chatSending) return;
  appState.chatSending = true;
  chatSendBtn.disabled = true;
  chatInputEl.disabled = true;
  chatStatusEl.textContent = "thinking\u2026";
  chatStatusEl.dataset.tone = "neutral";
  appendChatMessage("user", message);
  chatInputEl.value = "";
  showChatTyping();
  queueTelemetry("chat_sent", "chat message sent", { chars: message.length });
  try {
    const resp = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, allow_actions: true }) });
    const data = await resp.json();
    hideChatTyping();
    if (!resp.ok) {
      appendChatMessage("agent", data.detail || "Something went wrong.");
      chatStatusEl.textContent = "error";
      chatStatusEl.dataset.tone = "warn";
      queueTelemetry("chat_error", "chat request failed", { status: resp.status });
      return;
    }
    appendChatMessage("agent", data.response, { source: data.source, action_triggered: data.action_triggered, run_id: data.run_id });
    chatStatusEl.textContent = "ready";
    chatStatusEl.dataset.tone = "good";
    if (data.desktop_context) updateChatContextBar(data.desktop_context);
    if (data.action_triggered && data.run_id) {
      appState.activeRunId = data.run_id;
      queueTelemetry("chat_action_triggered", "chat triggered action", { run_id: data.run_id });
    }
    queueTelemetry("chat_received", "chat response received", { source: data.source, action_triggered: Boolean(data.action_triggered), chars: (data.response || "").length });
  } catch (err) {
    hideChatTyping();
    appendChatMessage("agent", "Failed to reach the backend. Is the server running?");
    chatStatusEl.textContent = "offline";
    chatStatusEl.dataset.tone = "warn";
    queueTelemetry("chat_failed", "chat request failed", { error: String(err) });
  } finally {
    appState.chatSending = false;
    chatSendBtn.disabled = false;
    chatInputEl.disabled = false;
    chatInputEl.focus();
  }
}
