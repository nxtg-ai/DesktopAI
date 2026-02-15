/**
 * DesktopAI Command Palette
 *
 * Ctrl+Space → type → Enter → response → Escape → focus returns.
 * Connects to /api/chat endpoint.
 */

const BACKEND = "http://localhost:8000";
const palette = document.getElementById("palette");
const input = document.getElementById("palette-input");
const responseEl = document.getElementById("palette-response");
const responseText = document.getElementById("response-text");

let conversationId = null;

// Auto-focus and reset when the window becomes visible
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    input.value = "";
    responseEl.classList.add("hidden");
    palette.classList.remove("loading");
    input.focus();
    resizeForResponse(false);
  }
});

window.addEventListener("DOMContentLoaded", () => {
  input.focus();
});

// Keyboard handling
input.addEventListener("keydown", async (e) => {
  if (e.key === "Escape") {
    e.preventDefault();
    dismiss();
    return;
  }
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    await sendCommand(message);
  }
});

async function sendCommand(message) {
  palette.classList.add("loading");

  try {
    const body = { message, allow_actions: true };
    if (conversationId) {
      body.conversation_id = conversationId;
    }

    const resp = await fetch(`${BACKEND}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!resp.ok) {
      showResponse(`Error: ${resp.status} ${resp.statusText}`);
      return;
    }

    const data = await resp.json();
    conversationId = data.conversation_id || conversationId;

    const reply = data.response || "Done.";
    const source = data.source || "";

    // Always clear input after successful response
    input.value = "";

    // Sync message to avatar overlay
    if (window.__TAURI__) {
      window.__TAURI__.event.emit("palette-message", {
        user: message,
        agent: reply,
        source: source,
        action_triggered: data.action_triggered,
        conversation_id: conversationId,
      });
    }

    // Fast responses (greeting, direct bridge): show briefly, auto-dismiss
    if (source === "greeting" || source === "direct") {
      showResponse(reply);
      setTimeout(() => dismiss(), source === "greeting" ? 800 : 1200);
      return;
    }

    // LLM or async agent responses
    showResponse(reply);

    // Auto-dismiss after showing for action triggers
    if (data.action_triggered) {
      setTimeout(() => dismiss(), 2000);
    }
  } catch (err) {
    showResponse(`Connection error: ${err.message}`);
  } finally {
    palette.classList.remove("loading");
  }
}

function showResponse(text) {
  responseText.textContent = text;
  responseEl.classList.remove("hidden");
  resizeForResponse(true);
}

async function dismiss() {
  responseEl.classList.add("hidden");
  input.value = "";
  palette.classList.remove("loading");
  resizeForResponse(false);

  // Invoke Rust command to hide palette and restore foreground window
  if (window.__TAURI__) {
    try {
      await window.__TAURI__.core.invoke("dismiss_palette");
    } catch {
      try {
        const win = window.__TAURI__.window.getCurrentWindow();
        await win.hide();
      } catch {
        // Non-critical
      }
    }
  }
}

async function resizeForResponse(expanded) {
  if (!window.__TAURI__) return;
  try {
    const win = window.__TAURI__.window.getCurrentWindow();
    const size = expanded
      ? new window.__TAURI__.window.LogicalSize(640, 280)
      : new window.__TAURI__.window.LogicalSize(640, 72);
    await win.setSize(size);
  } catch {
    // Non-critical
  }
}
