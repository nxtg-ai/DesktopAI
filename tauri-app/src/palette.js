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

// ── Mic state ──
const micBtn = document.getElementById("palette-mic-btn");
let micStream = null, micRecorder = null, micChunks = [], micRecording = false;

// Auto-focus and reset when the window becomes visible
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    input.value = "";
    responseEl.classList.add("hidden");
    palette.classList.remove("loading");
    if (micRecording) stopPaletteMic();
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
    const body = { message, allow_actions: true, stream: true };
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

    // Always clear input after successful response
    input.value = "";

    // SSE streaming response
    if (resp.headers.get("content-type")?.includes("text/event-stream")) {
      showResponse("");
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalMeta = {};

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (event.error) {
              responseText.textContent += " [Error]";
              break;
            }
            if (event.token) responseText.textContent += event.token;
            if (event.done) finalMeta = event;
          } catch { /* skip bad JSON */ }
        }
      }

      conversationId = finalMeta.conversation_id || conversationId;
      const source = finalMeta.source || "ollama";

      if (window.__TAURI__) {
        window.__TAURI__.event.emit("palette-message", {
          user: message,
          agent: responseText.textContent,
          source: source,
          action_triggered: finalMeta.action_triggered,
          conversation_id: conversationId,
        });
      }
      speakPaletteResponse(responseText.textContent);
      return;
    }

    // Non-streaming JSON response (greeting, direct, fallback)
    const data = await resp.json();
    conversationId = data.conversation_id || conversationId;

    const reply = data.response || "Done.";
    const source = data.source || "";

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
    speakPaletteResponse(reply);

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

// ── Mic functions ──

async function startPaletteMic() {
  try {
    if (!micStream) {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    }
    micChunks = [];
    const mimeType = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
    micRecorder = mimeType
      ? new MediaRecorder(micStream, { mimeType })
      : new MediaRecorder(micStream);
    micRecorder.ondataavailable = (e) => { if (e.data.size > 0) micChunks.push(e.data); };
    micRecorder.onstop = () => handleMicStop();
    micRecorder.start();
    micRecording = true;
    if (micBtn) micBtn.classList.add("recording");
    input.placeholder = "Listening\u2026 (click mic to stop)";
  } catch {
    // getUserMedia denied or unavailable — silently fail
    micRecording = false;
  }
}

function stopPaletteMic() {
  if (micRecorder && micRecorder.state === "recording") {
    if (micBtn) {
      micBtn.classList.remove("recording");
      micBtn.classList.add("processing");
    }
    micRecorder.stop();
  }
  micRecording = false;
}

async function handleMicStop() {
  if (micBtn) micBtn.classList.remove("processing");
  input.placeholder = "Ask DesktopAI anything...";
  if (micChunks.length === 0) return;
  const blob = new Blob(micChunks, { type: micRecorder?.mimeType || "audio/webm" });
  const form = new FormData();
  form.append("file", blob, "recording.webm");
  try {
    const resp = await fetch(`${BACKEND}/api/stt`, { method: "POST", body: form });
    if (resp.ok) {
      const data = await resp.json();
      const text = (data.text || "").trim();
      if (text) {
        input.value = text;
        await sendCommand(text);
      }
    }
  } catch {
    // STT unavailable — ignore
  }
}

async function speakPaletteResponse(text) {
  const clean = (text || "").trim();
  if (!clean) return;
  try {
    const resp = await fetch(`${BACKEND}/api/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: clean }),
    });
    if (resp.ok) {
      const buf = await resp.arrayBuffer();
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const decoded = await ctx.decodeAudioData(buf);
      const src = ctx.createBufferSource();
      src.buffer = decoded;
      src.connect(ctx.destination);
      src.onended = () => ctx.close();
      src.start();
    }
  } catch {
    // TTS unavailable — silent failure
  }
}

// ── Mic click handler ──
if (micBtn) {
  micBtn.addEventListener("click", () => {
    if (micRecording) {
      stopPaletteMic();
    } else {
      startPaletteMic();
    }
  });
}

function showResponse(text) {
  responseText.textContent = text;
  responseEl.classList.remove("hidden");
  resizeForResponse(true);
}

async function dismiss() {
  if (micRecording) stopPaletteMic();
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

// Kill-confirmed visual feedback: flash palette border red
if (window.__TAURI__) {
  window.__TAURI__.event.listen("kill-confirmed", () => {
    const pal = document.getElementById("palette");
    if (pal) {
      pal.classList.add("kill-flash");
      pal.addEventListener("animationend", () => pal.classList.remove("kill-flash"), { once: true });
    }
  });
}
