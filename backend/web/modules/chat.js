/** Chat message handling, typing indicator, context bar, and conversation management. */

import {
  appState, chatStatusEl, chatContextIndicatorEl, chatMessagesEl, chatWelcomeEl,
  chatInputEl, chatSendBtn, personalityModeEl, personalityEnergyBadgeEl, formatTime,
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
    if (meta.personality_mode) {
      const badge = document.createElement("span");
      badge.className = "chat-badge personality";
      badge.textContent = meta.personality_mode;
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

export async function refreshRecipeSuggestions() {
  const container = document.getElementById("recipe-suggestions");
  if (!container) return;
  try {
    const resp = await fetch("/api/recipes");
    if (!resp.ok) return;
    const data = await resp.json();
    container.innerHTML = "";
    for (const recipe of (data.recipes || [])) {
      const btn = document.createElement("button");
      btn.className = "chat-suggestion recipe-chip";
      btn.textContent = recipe.name;
      btn.title = recipe.description;
      btn.addEventListener("click", () => void sendChatMessage(recipe.keywords[0] || recipe.name));
      container.appendChild(btn);
    }
  } catch { /* ignore */ }
}

export function startNewChat() {
  appState.conversationId = null;
  // Remove all children except the welcome div, then re-show it
  const children = Array.from(chatMessagesEl.children);
  for (const child of children) {
    if (child.id !== "chat-welcome") child.remove();
  }
  if (chatWelcomeEl && chatMessagesEl.contains(chatWelcomeEl)) {
    chatWelcomeEl.style.display = "";
  } else {
    // Welcome was destroyed — recreate it
    const welcome = document.createElement("div");
    welcome.className = "chat-welcome";
    welcome.id = "chat-welcome";
    welcome.innerHTML = `
      <p>Ask me anything about your desktop, or tell me to do something.</p>
      <div class="chat-suggestions">
        <button class="chat-suggestion" data-message="What am I working on?">What am I working on?</button>
        <button class="chat-suggestion" data-message="Summarize my current activity">Summarize my activity</button>
        <button class="chat-suggestion" data-message="Draft a reply to this email">Draft email reply</button>
        <button class="chat-suggestion" data-message="Open Notepad and write a meeting summary">Open Notepad</button>
      </div>`;
    welcome.querySelectorAll(".chat-suggestion").forEach((btn) => {
      btn.addEventListener("click", () => {
        const msg = btn.dataset.message || btn.textContent;
        chatInputEl.value = msg;
        void sendChatMessage(msg);
      });
    });
    chatMessagesEl.appendChild(welcome);
  }
  chatInputEl.value = "";
  const titleEl = document.getElementById("chat-conversation-title");
  if (titleEl) {
    titleEl.textContent = "New Conversation";
    delete titleEl.dataset.set;
  }
  queueTelemetry("chat_new", "new chat started");
}

export async function fetchPersonalityStatus() {
  if (!personalityEnergyBadgeEl) return;
  try {
    const resp = await fetch("/api/personality");
    if (!resp.ok) return;
    const data = await resp.json();
    const energy = data.energy || "calm";
    personalityEnergyBadgeEl.textContent = energy;
    personalityEnergyBadgeEl.className = `status-badge ${energy}`;
  } catch { /* ignore */ }
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
    const personality = (personalityModeEl && personalityModeEl.value) || "assistant";
    const payload = { message, allow_actions: true, personality_mode: personality };
    if (appState.conversationId) payload.conversation_id = appState.conversationId;
    const resp = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await resp.json();
    hideChatTyping();
    if (!resp.ok) {
      appendChatMessage("agent", data.detail || "Something went wrong.");
      chatStatusEl.textContent = "error";
      chatStatusEl.dataset.tone = "warn";
      queueTelemetry("chat_error", "chat request failed", { status: resp.status });
      return;
    }
    if (data.conversation_id) {
      appState.conversationId = data.conversation_id;
      const titleEl = document.getElementById("chat-conversation-title");
      if (titleEl && !titleEl.dataset.set) {
        titleEl.textContent = message.length > 40 ? message.slice(0, 40) + "\u2026" : message;
        titleEl.dataset.set = "1";
      }
    }
    appendChatMessage("agent", data.response, { source: data.source, action_triggered: data.action_triggered, run_id: data.run_id, personality_mode: data.personality_mode });
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
