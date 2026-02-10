import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.161.0/build/three.module.js";

// ── Config ──────────────────────────────────────────────────────────
const API_BASE = "http://localhost:8000";
const WS_URL = "ws://localhost:8000/ws";

// ── Tauri API ───────────────────────────────────────────────────────
const { invoke } = window.__TAURI__.core;

// ── DOM refs ────────────────────────────────────────────────────────
const $ = (s) => document.getElementById(s);
const app = $("app");
const canvas = $("avatar-canvas");
const statusDot = $("status-dot");
const statusText = $("status-text");
const contextBar = $("context-bar");
const contextText = $("context-text");
const chatMessages = $("chat-messages");
const chatWelcome = $("chat-welcome");
const chatInput = $("chat-input");
const sendBtn = $("send-btn");
const compactToggle = $("compact-toggle");
const closeBtn = $("close-btn");

// ── State ───────────────────────────────────────────────────────────
let ws = null;
let wsRetryMs = 1000;
let isCompact = false;
let desktopContext = null;
let isSending = false;

// ── Avatar Engine (Three.js) ────────────────────────────────────────
const STATUS_COLORS = {
  connecting: 0xff8c42,
  live: 0x00d4aa,
  warn: 0xff5c5c,
  idle: 0x6f8f7a,
};

class AvatarEngine {
  constructor(cvs) {
    this.canvas = cvs;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
    this.camera.position.set(0, 0, 5.2);
    this.renderer = new THREE.WebGLRenderer({
      canvas: cvs,
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(cvs.clientWidth, cvs.clientHeight, false);

    this.timeStart = performance.now();
    this.energy = 0;
    this.listenLevel = 0;
    this.listenLevelTarget = 0;
    this.speaking = false;
    this.targetColor = new THREE.Color(STATUS_COLORS.connecting);
    this.currentColor = new THREE.Color(STATUS_COLORS.connecting);
    this.connection = "connecting";
    this.isIdle = false;

    this._setupLights();
    this._setupMeshes();
    this._bindResize();
    this._animate = this._animate.bind(this);
    this._rafId = requestAnimationFrame(this._animate);
  }

  _setupLights() {
    const key = new THREE.DirectionalLight(0xffffff, 1.0);
    key.position.set(2, 3, 4);
    this.scene.add(key);

    const rim = new THREE.DirectionalLight(0x87fff2, 0.9);
    rim.position.set(-3, -1, 2);
    this.scene.add(rim);

    this.scene.add(new THREE.AmbientLight(0x5bd8cf, 0.6));
  }

  _setupMeshes() {
    this.root = new THREE.Group();
    this.scene.add(this.root);

    // Core orb
    const orbGeo = new THREE.SphereGeometry(1.0, 64, 64);
    this.orbMat = new THREE.MeshStandardMaterial({
      color: STATUS_COLORS.connecting,
      roughness: 0.35,
      metalness: 0.45,
      emissive: STATUS_COLORS.connecting,
      emissiveIntensity: 0.12,
    });
    this.orb = new THREE.Mesh(orbGeo, this.orbMat);
    this.root.add(this.orb);

    // Glass shell
    const shellGeo = new THREE.SphereGeometry(1.2, 48, 48);
    this.shellMat = new THREE.MeshPhysicalMaterial({
      color: 0xffffff,
      transmission: 0.92,
      transparent: true,
      opacity: 0.3,
      roughness: 0.05,
      metalness: 0.0,
      clearcoat: 1,
      clearcoatRoughness: 0.02,
      ior: 1.3,
    });
    this.shell = new THREE.Mesh(shellGeo, this.shellMat);
    this.root.add(this.shell);

    // Orbital rings
    const ringGeo = new THREE.TorusGeometry(1.72, 0.06, 32, 160);
    this.ringMat = new THREE.MeshStandardMaterial({
      color: STATUS_COLORS.connecting,
      emissive: STATUS_COLORS.connecting,
      emissiveIntensity: 0.22,
      metalness: 0.85,
      roughness: 0.25,
    });
    this.ringA = new THREE.Mesh(ringGeo, this.ringMat);
    this.ringA.rotation.x = Math.PI * 0.28;
    this.root.add(this.ringA);

    this.ringB = new THREE.Mesh(ringGeo, this.ringMat.clone());
    this.ringB.rotation.y = Math.PI * 0.44;
    this.ringB.rotation.x = Math.PI * 0.74;
    this.root.add(this.ringB);

    // Pulse ring
    const pulseGeo = new THREE.RingGeometry(1.8, 2.15, 96);
    this.pulseMat = new THREE.MeshBasicMaterial({
      color: STATUS_COLORS.connecting,
      transparent: true,
      opacity: 0.2,
      side: THREE.DoubleSide,
    });
    this.pulse = new THREE.Mesh(pulseGeo, this.pulseMat);
    this.pulse.rotation.x = Math.PI / 2;
    this.pulse.position.y = -1.4;
    this.root.add(this.pulse);
  }

  _bindResize() {
    const resize = () => {
      const w = Math.max(200, this.canvas.clientWidth);
      const h = Math.max(100, this.canvas.clientHeight);
      this.renderer.setSize(w, h, false);
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
    };
    this._resizeHandler = resize;
    resize();
    window.addEventListener("resize", resize);
  }

  setConnection(state) {
    this.connection = state;
    const c = STATUS_COLORS[state] ?? STATUS_COLORS.connecting;
    this.targetColor.setHex(c);
  }

  setIdle(idle) {
    this.isIdle = Boolean(idle);
    if (this.isIdle) {
      this.targetColor.setHex(STATUS_COLORS.idle);
    } else if (this.connection === "live") {
      this.targetColor.setHex(STATUS_COLORS.live);
    }
  }

  bump(amount = 0.28) {
    this.energy = Math.min(1.8, this.energy + amount);
  }

  setSpeaking(on) {
    this.speaking = Boolean(on);
  }

  _animate() {
    const t = (performance.now() - this.timeStart) / 1000;
    this.energy = Math.max(0, this.energy * 0.965);
    this.listenLevel += (this.listenLevelTarget - this.listenLevel) * 0.15;
    this.currentColor.lerp(this.targetColor, 0.06);

    // Apply color
    this.orbMat.color.copy(this.currentColor);
    this.orbMat.emissive.copy(this.currentColor);
    this.ringMat.color.copy(this.currentColor);
    this.ringMat.emissive.copy(this.currentColor);
    this.ringB.material.color.copy(this.currentColor);
    this.ringB.material.emissive.copy(this.currentColor);
    this.pulseMat.color.copy(this.currentColor);

    // Orb breathing
    const speechKick = this.speaking ? 0.1 : 0;
    const voiceKick = this.listenLevel * 0.14;
    const basePulse = this.isIdle ? 0.96 : 1.0;
    const wave = Math.sin(t * (this.isIdle ? 1.2 : 2.8)) * (this.isIdle ? 0.03 : 0.06);
    const kick = this.energy * 0.08 + speechKick + voiceKick;
    const scale = basePulse + wave + kick;
    this.orb.scale.setScalar(scale);
    this.shell.scale.setScalar(1.12 + wave * 0.6 + kick * 0.7);

    // Rings spin
    this.ringA.rotation.z += 0.004 + this.energy * 0.003 + this.listenLevel * 0.01;
    this.ringA.rotation.x += 0.0012 + this.listenLevel * 0.002;
    this.ringB.rotation.y -= 0.005 + this.energy * 0.004 + this.listenLevel * 0.012;
    this.ringB.rotation.x -= 0.001 + this.listenLevel * 0.002;

    // Pulse disc
    const ps = 1 + Math.sin(t * 2) * 0.06 + this.energy * 0.12 + this.listenLevel * 0.24;
    this.pulse.scale.setScalar(ps);
    this.pulseMat.opacity = 0.08 + this.energy * 0.15 + this.listenLevel * 0.22;

    // Slow wobble
    this.root.rotation.y = Math.sin(t * 0.28) * 0.24;
    this.root.rotation.x = Math.cos(t * 0.22) * 0.08 + this.listenLevel * 0.06;

    this.renderer.render(this.scene, this.camera);
    this._rafId = requestAnimationFrame(this._animate);
  }

  destroy() {
    cancelAnimationFrame(this._rafId);
    window.removeEventListener("resize", this._resizeHandler);
    this.renderer.dispose();
  }
}

// ── Init Avatar ─────────────────────────────────────────────────────
const avatar = new AvatarEngine(canvas);

// ── WebSocket ───────────────────────────────────────────────────────
function connectWS() {
  if (ws && ws.readyState <= 1) return;
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    wsRetryMs = 1000;
    setStatus("live", "connected");
    avatar.setConnection("live");
  };

  ws.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data);
      handleWSMessage(data);
    } catch {}
  };

  ws.onclose = () => {
    setStatus("connecting", "reconnecting...");
    avatar.setConnection("connecting");
    setTimeout(connectWS, wsRetryMs);
    wsRetryMs = Math.min(wsRetryMs * 1.5, 10000);
  };

  ws.onerror = () => ws.close();
}

function handleWSMessage(data) {
  avatar.bump(0.15);

  if (data.type === "snapshot") {
    const current = data.state?.current;
    if (current) updateContext(current);
  }

  if (data.type === "state") {
    const current = data.state?.current;
    if (current) updateContext(current);
  }

  if (data.type === "event") {
    const event = data.event;
    if (event) updateContext(event);
  }

  if (data.type === "autonomy_run") {
    const run = data.run;
    if (run) handleAutonomyUpdate(run);
  }
}

// ── Status ──────────────────────────────────────────────────────────
function setStatus(state, text) {
  statusDot.className = "status-dot";
  if (state === "live") statusDot.classList.add("live");
  if (state === "error") statusDot.classList.add("error");
  statusText.textContent = text;
}

// ── Context ─────────────────────────────────────────────────────────
function updateContext(data) {
  const title = data.window_title || data.title || "";
  const process = data.process_exe || "";
  if (!title && !process) return;

  const display = process ? `${process} — ${title}` : title;
  contextText.textContent = display;
  contextBar.classList.add("has-context");
  desktopContext = data;
}

async function fetchContext() {
  try {
    const r = await fetch(`${API_BASE}/api/state/snapshot`);
    if (r.ok) {
      const data = await r.json();
      if (data.context) updateContext(data.context);
    }
  } catch {}
}

// ── Markdown ─────────────────────────────────────────────────────────
function renderMarkdown(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br>");
}

// ── Autonomy Run Status ──────────────────────────────────────────────
function handleAutonomyUpdate(run) {
  let runEl = document.getElementById("run-status");
  if (!runEl) {
    runEl = document.createElement("div");
    runEl.id = "run-status";
    runEl.className = "run-status";
    contextBar.parentElement.insertBefore(runEl, contextBar.nextSibling);
  }

  if (run.status === "running") {
    runEl.textContent = `\u27F3 ${run.objective}`;
    runEl.className = "run-status running";
  } else if (run.status === "completed") {
    runEl.textContent = `\u2713 ${run.objective}`;
    runEl.className = "run-status completed";
    setTimeout(() => runEl.remove(), 5000);
  } else if (run.status === "failed") {
    runEl.textContent = `\u2717 ${run.last_error || run.objective}`;
    runEl.className = "run-status failed";
    setTimeout(() => runEl.remove(), 8000);
  }
}

// ── Chat ────────────────────────────────────────────────────────────
function appendMessage(role, text, meta = {}) {
  if (chatWelcome) chatWelcome.style.display = "none";

  const msg = document.createElement("div");
  msg.className = `msg ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  if (role === "agent") {
    bubble.innerHTML = renderMarkdown(text);
  } else {
    bubble.textContent = text;
  }
  msg.appendChild(bubble);

  // Meta row
  const metaRow = document.createElement("div");
  metaRow.className = "msg-meta";

  const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const timeSpan = document.createElement("span");
  timeSpan.textContent = time;
  metaRow.appendChild(timeSpan);

  if (meta.source) {
    const badge = document.createElement("span");
    badge.className = "badge source";
    badge.textContent = meta.source;
    metaRow.appendChild(badge);
  }

  if (meta.action_triggered) {
    const badge = document.createElement("span");
    badge.className = "badge action";
    badge.textContent = "action";
    metaRow.appendChild(badge);
  }

  msg.appendChild(metaRow);
  chatMessages.appendChild(msg);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function showTyping() {
  const el = document.createElement("div");
  el.className = "typing";
  el.id = "typing-indicator";
  el.innerHTML = "<span></span><span></span><span></span>";
  chatMessages.appendChild(el);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function hideTyping() {
  const el = document.getElementById("typing-indicator");
  if (el) el.remove();
}

async function sendMessage(text) {
  if (!text.trim() || isSending) return;

  isSending = true;
  sendBtn.disabled = true;
  chatInput.value = "";

  appendMessage("user", text);
  avatar.bump(0.3);
  showTyping();
  avatar.setSpeaking(true);

  try {
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, allow_actions: true }),
    });

    hideTyping();

    if (res.ok) {
      const data = await res.json();
      avatar.bump(0.4);
      appendMessage("agent", data.response || "No response", {
        source: data.source,
        action_triggered: data.action_triggered,
      });
      if (data.desktop_context) {
        updateContext(data.desktop_context);
      }
    } else {
      appendMessage("agent", "Something went wrong. Backend may be offline.", {
        source: "error",
      });
    }
  } catch (err) {
    hideTyping();
    appendMessage("agent", "Cannot reach backend. Is it running?", {
      source: "error",
    });
  } finally {
    avatar.setSpeaking(false);
    isSending = false;
    sendBtn.disabled = false;
    chatInput.focus();
  }
}

// ── Event Listeners ─────────────────────────────────────────────────
sendBtn.addEventListener("click", () => sendMessage(chatInput.value));

chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage(chatInput.value);
  }
});

// Suggestion chips
document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    sendMessage(chip.dataset.msg);
  });
});

// Compact mode
compactToggle.addEventListener("click", () => {
  isCompact = !isCompact;
  app.classList.toggle("compact", isCompact);
  invoke("set_compact_mode", { compact: isCompact });
});

// Close to tray
closeBtn.addEventListener("click", () => {
  invoke("toggle_visibility");
});

// ── Boot ────────────────────────────────────────────────────────────
setStatus("connecting", "connecting...");
fetchContext();
connectWS();
