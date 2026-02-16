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
const micBtn = $("mic-btn");
const voiceState = $("voice-state");
const compactToggle = $("compact-toggle");
const closeBtn = $("close-btn");
const killBtn = $("kill-btn");

// ── State ───────────────────────────────────────────────────────────
let ws = null;
let wsRetryMs = 1000;
let activeRunIds = new Set();
let isCompact = false;
let desktopContext = null;
let isSending = false;
let conversationId = null;

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

  setColor(hex) {
    this.targetColor.setHex(hex);
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

// ── Voice Module ────────────────────────────────────────────────────
let recognition = null;
let recognitionActive = false;
let mediaStream = null;
let audioContext = null;
let analyser = null;
let audioData = null;
let meterRaf = null;
let speechActive = false;

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const hasSpeechRecognition = Boolean(SpeechRecognition);
const hasSpeechSynthesis = "speechSynthesis" in window;

// Hide mic button if STT unavailable
if (!hasSpeechRecognition && micBtn) {
  micBtn.classList.add("hidden");
}

async function ensureMicrophone() {
  if (mediaStream) return true;
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 1024;
    audioData = new Uint8Array(analyser.frequencyBinCount);
    const source = audioContext.createMediaStreamSource(mediaStream);
    source.connect(analyser);
    return true;
  } catch {
    return false;
  }
}

function startMeterLoop() {
  if (meterRaf) return;
  function tick() {
    if (!analyser || !audioData) { meterRaf = null; return; }
    analyser.getByteFrequencyData(audioData);
    let sum = 0;
    for (let i = 0; i < audioData.length; i++) sum += audioData[i];
    const avg = sum / audioData.length;
    avatar.listenLevelTarget = Math.min(1, avg / 80);
    meterRaf = requestAnimationFrame(tick);
  }
  meterRaf = requestAnimationFrame(tick);
}

function stopMeterLoop() {
  if (meterRaf) { cancelAnimationFrame(meterRaf); meterRaf = null; }
  avatar.listenLevelTarget = 0;
}

function setupSTT() {
  if (!hasSpeechRecognition) return;
  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = "en-US";

  let finalTranscript = "";

  recognition.onresult = (event) => {
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript;
      if (event.results[i].isFinal) {
        finalTranscript += transcript;
      } else {
        interim += transcript;
      }
    }
    chatInput.value = finalTranscript + interim;
  };

  recognition.onend = () => {
    if (recognitionActive) {
      try { recognition.start(); } catch {}
    } else {
      finalTranscript = "";
    }
  };

  recognition.onerror = (event) => {
    if (event.error === "not-allowed" || event.error === "service-not-available") {
      stopListening();
    }
  };
}

async function startListening() {
  if (!recognition) setupSTT();
  if (!recognition) return;

  const micOk = await ensureMicrophone();
  if (!micOk) return;

  recognitionActive = true;
  try { recognition.start(); } catch {}
  startMeterLoop();
  micBtn.classList.add("active");
  voiceState.textContent = "listening";
  voiceState.className = "voice-pill listening";
}

function stopListening() {
  recognitionActive = false;
  if (recognition) {
    try { recognition.stop(); } catch {}
  }
  stopMeterLoop();
  micBtn.classList.remove("active");
  voiceState.className = "voice-pill hidden";
}

function toggleListening() {
  if (recognitionActive) {
    stopListening();
  } else {
    startListening();
  }
}

function pickVoice() {
  const voices = speechSynthesis.getVoices();
  const preferred = ["Microsoft", "Aria", "Jenny", "Zira", "Google US English"];
  for (const name of preferred) {
    const match = voices.find((v) => v.name.includes(name) && v.lang.startsWith("en"));
    if (match) return match;
  }
  return voices.find((v) => v.lang.startsWith("en")) || voices[0] || null;
}

function speakText(text) {
  if (!hasSpeechSynthesis || !text) return;
  speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  const voice = pickVoice();
  if (voice) utterance.voice = voice;
  utterance.rate = 1.0;
  utterance.pitch = 1.0;

  utterance.onstart = () => {
    speechActive = true;
    avatar.setSpeaking(true);
    voiceState.textContent = "speaking";
    voiceState.className = "voice-pill speaking";
  };

  utterance.onboundary = () => {
    avatar.bump(0.08);
  };

  utterance.onend = () => {
    speechActive = false;
    avatar.setSpeaking(false);
    if (!recognitionActive) {
      voiceState.className = "voice-pill hidden";
    } else {
      voiceState.textContent = "listening";
      voiceState.className = "voice-pill listening";
    }
  };

  utterance.onerror = () => {
    speechActive = false;
    avatar.setSpeaking(false);
    if (!recognitionActive) {
      voiceState.className = "voice-pill hidden";
    }
  };

  speechSynthesis.speak(utterance);
}

// Preload voices
if (hasSpeechSynthesis) {
  speechSynthesis.getVoices();
  speechSynthesis.addEventListener("voiceschanged", () => {});
}

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

  if (data.type === "notification") {
    fetchNotificationCount();
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
  fetchRecipes(); // Refresh context-aware recipe chips
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

// ── Notifications ────────────────────────────────────────────────────
const notifBtn = $("notif-btn");
const notifBadge = $("notif-badge");
const notifDropdown = $("notif-dropdown");
const notifList = $("notif-list");

async function fetchNotificationCount() {
  try {
    const r = await fetch(`${API_BASE}/api/notifications/count`);
    if (r.ok) {
      const data = await r.json();
      const count = data.unread_count || 0;
      if (notifBadge) {
        notifBadge.textContent = count > 99 ? "99+" : String(count);
        notifBadge.classList.toggle("hidden", count === 0);
      }
    }
  } catch {}
}

async function fetchNotifications() {
  try {
    const r = await fetch(`${API_BASE}/api/notifications?limit=5&unread_only=true`);
    if (r.ok) {
      const data = await r.json();
      renderNotifications(data.notifications || []);
    }
  } catch {}
}

function renderNotifications(notifications) {
  if (!notifList) return;
  if (notifications.length === 0) {
    notifList.innerHTML = '<div class="notif-empty">No notifications</div>';
    return;
  }
  notifList.innerHTML = notifications.map((n) =>
    `<div class="notif-item" data-id="${n.id}">
      <div class="notif-title">${n.title || n.type}</div>
      <div class="notif-body">${n.message || ""}</div>
    </div>`
  ).join("");

  notifList.querySelectorAll(".notif-item").forEach((el) => {
    el.addEventListener("click", async () => {
      const id = el.dataset.id;
      await fetch(`${API_BASE}/api/notifications/${id}/read`, { method: "POST" });
      el.remove();
      fetchNotificationCount();
    });
  });
}

if (notifBtn) {
  notifBtn.addEventListener("click", () => {
    if (notifDropdown) {
      notifDropdown.classList.toggle("hidden");
      if (!notifDropdown.classList.contains("hidden")) {
        fetchNotifications();
      }
    }
  });
}

// Close dropdown when clicking outside
document.addEventListener("click", (e) => {
  if (notifDropdown && !notifDropdown.contains(e.target) && e.target !== notifBtn && !notifBtn.contains(e.target)) {
    notifDropdown.classList.add("hidden");
  }
});

// Poll notification count every 30s
setInterval(fetchNotificationCount, 30000);
fetchNotificationCount();

// ── Recipe Chips ─────────────────────────────────────────────────────
const recipeChipsEl = $("recipe-chips");

async function fetchRecipes() {
  try {
    const r = await fetch(`${API_BASE}/api/recipes`);
    if (r.ok) {
      const data = await r.json();
      renderRecipeChips(data.recipes || []);
    }
  } catch {}
}

function renderRecipeChips(recipes) {
  if (!recipeChipsEl) return;
  if (recipes.length === 0) {
    recipeChipsEl.classList.add("hidden");
    return;
  }
  recipeChipsEl.classList.remove("hidden");
  recipeChipsEl.innerHTML = recipes.map((r) =>
    `<button class="recipe-chip" data-desc="${r.description}">${r.name}</button>`
  ).join("");

  recipeChipsEl.querySelectorAll(".recipe-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      sendMessage(btn.dataset.desc);
    });
  });
}

fetchRecipes();

// ── Personality Mode ─────────────────────────────────────────────────
let personalityMode = "assistant";

document.querySelectorAll(".persona-pill").forEach((pill) => {
  pill.addEventListener("click", () => {
    document.querySelectorAll(".persona-pill").forEach((p) => p.classList.remove("active"));
    pill.classList.add("active");
    personalityMode = pill.dataset.mode;
  });
});

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

  // Build header + step log
  const icon = run.status === "running" ? "\u27F3"
    : run.status === "completed" ? "\u2713"
    : run.status === "cancelled" ? "\u2718"
    : "\u2717";

  const headerText = run.status === "failed"
    ? (run.last_error || run.objective)
    : run.status === "cancelled"
    ? `Cancelled: ${run.objective}`
    : run.objective;

  const iterInfo = run.iteration > 0 ? ` (step ${run.iteration})` : "";

  runEl.innerHTML = `<div class="run-header">${icon} ${headerText}${iterInfo}</div>`;

  // Show last 3 agent log entries for running status
  if (run.status === "running" && run.agent_log && run.agent_log.length > 0) {
    const stepsEl = document.createElement("div");
    stepsEl.className = "run-steps";
    const recent = run.agent_log.slice(-3);
    stepsEl.textContent = recent.map((e) => e.message).join(" \u2192 ");
    runEl.appendChild(stepsEl);
  }

  if (run.status === "running") {
    activeRunIds.add(run.run_id);
    runEl.className = "run-status running";
    avatar.setColor(0x4488ff);
  } else if (run.status === "completed") {
    activeRunIds.delete(run.run_id);
    runEl.className = "run-status completed";
    setTimeout(() => runEl.remove(), 5000);
  } else if (run.status === "failed") {
    activeRunIds.delete(run.run_id);
    runEl.className = "run-status failed";
    setTimeout(() => runEl.remove(), 8000);
  } else if (run.status === "cancelled") {
    activeRunIds.delete(run.run_id);
    runEl.className = "run-status failed";
    setTimeout(() => runEl.remove(), 3000);
  }

  // Show/hide kill button based on active runs
  if (killBtn) {
    killBtn.classList.toggle("hidden", activeRunIds.size === 0);
  }
  if (activeRunIds.size === 0) {
    avatar.setColor(STATUS_COLORS.live);
  }
}

async function killAllRuns() {
  try {
    const res = await fetch(`${API_BASE}/api/autonomy/cancel-all`, {
      method: "POST",
    });
    if (res.ok) {
      const data = await res.json();
      if (data.cancelled > 0) {
        appendMessage("agent", `Killed ${data.cancelled} running action(s).`, { source: "system" });
      }
    }
  } catch {
    appendMessage("agent", "Could not reach backend to kill runs.", { source: "error" });
  }
  activeRunIds.clear();
  if (killBtn) killBtn.classList.add("hidden");
  avatar.setColor(STATUS_COLORS.live);
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
      body: JSON.stringify({
        message: text,
        allow_actions: true,
        conversation_id: conversationId,
        personality_mode: personalityMode,
        stream: true,
      }),
    });

    hideTyping();

    if (!res.ok) {
      appendMessage("agent", "Something went wrong. Backend may be offline.", {
        source: "error",
      });
      return;
    }

    // SSE streaming response
    if (res.headers.get("content-type")?.includes("text/event-stream")) {
      const msg = document.createElement("div");
      msg.className = "msg agent streaming";
      const bubble = document.createElement("div");
      bubble.className = "msg-bubble";
      msg.appendChild(bubble);
      if (chatWelcome) chatWelcome.style.display = "none";
      chatMessages.appendChild(msg);

      const reader = res.body.getReader();
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
            if (event.token) bubble.textContent += event.token;
            if (event.done) finalMeta = event;
          } catch { /* skip */ }
        }
        chatMessages.scrollTop = chatMessages.scrollHeight;
        avatar.bump(0.05);
      }

      msg.classList.remove("streaming");
      // Render markdown in final bubble
      bubble.innerHTML = renderMarkdown(bubble.textContent);
      // Add meta row
      const metaRow = document.createElement("div");
      metaRow.className = "msg-meta";
      const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      const timeSpan = document.createElement("span");
      timeSpan.textContent = time;
      metaRow.appendChild(timeSpan);
      if (finalMeta.source) {
        const badge = document.createElement("span");
        badge.className = "badge source";
        badge.textContent = finalMeta.source;
        metaRow.appendChild(badge);
      }
      msg.appendChild(metaRow);

      if (finalMeta.conversation_id) conversationId = finalMeta.conversation_id;
      if (finalMeta.desktop_context) updateContext(finalMeta.desktop_context);
      avatar.bump(0.4);
      speakText(bubble.textContent);
      return;
    }

    // Non-streaming JSON response (greeting, direct, fallback)
    const data = await res.json();
    if (data.conversation_id) {
      conversationId = data.conversation_id;
    }
    avatar.bump(0.4);
    const agentText = data.response || "No response";
    appendMessage("agent", agentText, {
      source: data.source,
      action_triggered: data.action_triggered,
    });
    if (data.desktop_context) {
      updateContext(data.desktop_context);
    }
    speakText(agentText);
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

function startNewChat() {
  conversationId = null;
  // Clear all messages except the welcome element
  Array.from(chatMessages.children).forEach((child) => {
    if (child !== chatWelcome) child.remove();
  });
  if (chatWelcome) chatWelcome.style.display = "";
  chatInput.value = "";
  chatInput.focus();
}

// ── Event Listeners ─────────────────────────────────────────────────
sendBtn.addEventListener("click", () => sendMessage(chatInput.value));

const newChatBtn = $("new-chat-btn");
if (newChatBtn) {
  newChatBtn.addEventListener("click", startNewChat);
}

if (killBtn) {
  killBtn.addEventListener("click", killAllRuns);
}

micBtn.addEventListener("click", toggleListening);

chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage(chatInput.value);
  }
});

document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.shiftKey && e.key === "N") {
    e.preventDefault();
    startNewChat();
  }
  if (e.ctrlKey && e.shiftKey && e.key === "X") {
    e.preventDefault();
    killAllRuns();
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

// ── Cleanup ──────────────────────────────────────────────────────────
window.addEventListener("beforeunload", () => {
  stopListening();
  if (hasSpeechSynthesis) speechSynthesis.cancel();
  if (audioContext) { try { audioContext.close(); } catch {} }
  if (mediaStream) { mediaStream.getTracks().forEach((t) => t.stop()); }
});

// ── Health Chips ────────────────────────────────────────────────────
async function pollHealth() {
  try {
    const r = await fetch(`${API_BASE}/api/readiness/status`);
    const data = await r.json();
    const s = data.summary || {};
    setHealthChip("hc-ollama", s.ollama_available, s.ollama_active_model || "");
    setHealthChip("hc-bridge", s.bridge_connected, s.executor_mode || "");
    setHealthChip("hc-collector", s.collector_connected, `${s.collector_total_events || 0} events`);
  } catch {
    ["hc-ollama", "hc-bridge", "hc-collector"].forEach(id => setHealthChip(id, false, "offline"));
  }
}

function setHealthChip(id, ok, detail) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("ok", "down");
  el.classList.add(ok ? "ok" : "down");
  el.title = detail;
}

setInterval(pollHealth, 10000);

// ── Boot ────────────────────────────────────────────────────────────
setStatus("connecting", "connecting...");
fetchContext();
connectWS();
pollHealth();

// Listen for palette messages and display in avatar chat
if (window.__TAURI__) {
  window.__TAURI__.event.listen("palette-message", (event) => {
    const { user, agent, source, action_triggered, conversation_id: cid } = event.payload;
    if (cid) conversationId = cid;
    appendMessage("user", user);
    appendMessage("agent", agent, { source, action_triggered });
  });

  // Kill-confirmed visual feedback: flash orb red + show message
  window.__TAURI__.event.listen("kill-confirmed", (event) => {
    const { cancelled } = event.payload || {};
    const msg = cancelled > 0
      ? `Killed ${cancelled} running action(s).`
      : "No actions were running.";
    appendMessage("agent", msg, { source: "system" });

    // Flash orb red for 1.5s
    avatar.setColor(STATUS_COLORS.warn);
    setTimeout(() => avatar.setColor(STATUS_COLORS.live), 1500);

    // Flash app border
    const app = document.getElementById("app");
    if (app) {
      app.classList.add("kill-flash");
      app.addEventListener("animationend", () => app.classList.remove("kill-flash"), { once: true });
    }

    activeRunIds.clear();
    if (killBtn) killBtn.classList.add("hidden");
  });
}
