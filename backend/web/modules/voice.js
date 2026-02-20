/** STT, TTS, and audio meter. */

import {
  appState, avatar, voiceStateEl, voiceEngineEl, voiceTextEl, voiceTranscriptEl,
  micBtn, sttStatusEl,
} from "./state.js";
import { queueTelemetry } from "./telemetry.js";

export function setVoiceState(text, tone = "neutral") {
  voiceStateEl.textContent = text;
  voiceStateEl.dataset.tone = tone;
}

function pickVoice() {
  const voices = window.speechSynthesis ? window.speechSynthesis.getVoices() : [];
  if (!voices || voices.length === 0) return null;
  const preferred = voices.find((v) => /microsoft|aria|jenny|guy/i.test(v.name) && /^en/i.test(v.lang));
  return preferred || voices.find((v) => /^en/i.test(v.lang)) || voices[0];
}

function _speakBrowser(text) {
  if (!("speechSynthesis" in window)) {
    setVoiceState("tts unavailable", "warn");
    return;
  }
  if (appState.currentUtterance) {
    window.speechSynthesis.cancel();
    appState.currentUtterance = null;
  }
  const utter = new SpeechSynthesisUtterance(text);
  const voice = pickVoice();
  if (voice) utter.voice = voice;
  utter.rate = 1.0;
  utter.pitch = 1.02;
  utter.volume = 1.0;
  utter.onstart = () => {
    appState.speechActive = true;
    avatar.setSpeaking(true);
    setVoiceState("speaking", "good");
    queueTelemetry("tts_started", "speech started (browser)");
  };
  utter.onboundary = () => avatar.bump();
  utter.onerror = () => {
    appState.speechActive = false;
    avatar.setSpeaking(false);
    setVoiceState(appState.recognitionActive ? "listening" : "standby", appState.recognitionActive ? "good" : "neutral");
    queueTelemetry("tts_error", "speech failed");
  };
  utter.onend = () => {
    appState.speechActive = false;
    avatar.setSpeaking(false);
    setVoiceState(appState.recognitionActive ? "listening" : "standby", appState.recognitionActive ? "good" : "neutral");
    queueTelemetry("tts_completed", "speech completed");
  };
  appState.currentUtterance = utter;
  window.speechSynthesis.speak(utter);
}

export async function speakText(text) {
  const clean = (text || "").trim();
  if (!clean) return;
  try {
    const resp = await fetch("/api/tts", {
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
      appState.speechActive = true;
      avatar.setSpeaking(true);
      setVoiceState("speaking", "good");
      queueTelemetry("tts_started", "speech started (kokoro)");
      src.onended = () => {
        appState.speechActive = false;
        avatar.setSpeaking(false);
        setVoiceState(appState.recognitionActive ? "listening" : "standby", appState.recognitionActive ? "good" : "neutral");
        queueTelemetry("tts_completed", "speech completed");
        ctx.close();
      };
      src.start();
      return;
    }
  } catch { /* fall through to browser fallback */ }
  _speakBrowser(clean);
}

export function stopMeterLoop() {
  if (appState.meterRaf) {
    cancelAnimationFrame(appState.meterRaf);
    appState.meterRaf = null;
  }
}

function startMeterLoop() {
  if (!appState.analyser || appState.meterRaf) return;
  const loop = () => {
    if (!appState.analyser) { appState.meterRaf = null; return; }
    appState.analyser.getByteTimeDomainData(appState.audioData);
    let sumSquares = 0;
    for (let i = 0; i < appState.audioData.length; i += 1) {
      const centered = (appState.audioData[i] - 128) / 128;
      sumSquares += centered * centered;
    }
    const rms = Math.sqrt(sumSquares / appState.audioData.length);
    const gain = appState.recognitionActive ? 7.5 : 3.0;
    avatar.setListeningLevel(Math.max(0, Math.min(1, rms * gain)));
    appState.meterRaf = requestAnimationFrame(loop);
  };
  appState.meterRaf = requestAnimationFrame(loop);
}

export async function ensureMicrophone() {
  if (appState.mediaStream && appState.analyser) return true;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return false;
  try {
    appState.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    appState.audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const source = appState.audioContext.createMediaStreamSource(appState.mediaStream);
    appState.analyser = appState.audioContext.createAnalyser();
    appState.analyser.fftSize = 1024;
    appState.audioData = new Uint8Array(appState.analyser.fftSize);
    source.connect(appState.analyser);
    startMeterLoop();
    sttStatusEl.textContent = "Mic: ready";
    queueTelemetry("mic_ready", "microphone ready");
    return true;
  } catch (err) {
    console.error("mic setup failed", err);
    sttStatusEl.textContent = "Mic: permission denied";
    setVoiceState("mic blocked", "warn");
    queueTelemetry("mic_denied", "microphone permission denied", { error: String(err) });
    return false;
  }
}

// ── Voice auto-submit ────────────────────────────────────────────
let voiceAutoSubmit = true;

export function setVoiceAutoSubmit(enabled) {
  voiceAutoSubmit = enabled;
}

// ── Server-side STT (faster-whisper) ────────────────────────────
let _serverSttAvailable = null;

export async function checkServerStt() {
  try {
    const resp = await fetch("/api/stt/status");
    if (resp.ok) {
      const data = await resp.json();
      _serverSttAvailable = data.available === true;
    } else {
      _serverSttAvailable = false;
    }
  } catch {
    _serverSttAvailable = false;
  }
  return _serverSttAvailable;
}

export async function startServerRecording() {
  if (!appState.mediaStream) {
    const ok = await ensureMicrophone();
    if (!ok) return null;
  }
  const recorder = new MediaRecorder(appState.mediaStream, { mimeType: "audio/webm" });
  const chunks = [];
  recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
  appState._serverRecorder = recorder;
  appState._serverChunks = chunks;
  recorder.start();
  appState.recognitionActive = true;
  micBtn.textContent = "Stop Listening";
  setVoiceState("listening (server)", "good");
  sttStatusEl.textContent = "Mic: recording for server STT";
  queueTelemetry("stt_server_recording", "server STT recording started");
  return recorder;
}

export async function stopServerRecording() {
  const recorder = appState._serverRecorder;
  const chunks = appState._serverChunks;
  if (!recorder || recorder.state !== "recording") return null;
  return new Promise((resolve) => {
    recorder.onstop = async () => {
      appState.recognitionActive = false;
      micBtn.textContent = "Start Listening";
      setVoiceState("transcribing…", "neutral");
      sttStatusEl.textContent = "Mic: transcribing…";
      const blob = new Blob(chunks, { type: "audio/webm" });
      const form = new FormData();
      form.append("file", blob, "recording.webm");
      try {
        const resp = await fetch("/api/stt", { method: "POST", body: form });
        if (resp.ok) {
          const data = await resp.json();
          const text = data.text || "";
          if (text) {
            appState.recognitionTranscript = `${appState.recognitionTranscript} ${text}`.trim();
            voiceTextEl.value = appState.recognitionTranscript;
            avatar.bump();
            if (voiceAutoSubmit && text.trim()) {
              document.dispatchEvent(new CustomEvent("voice-command", {
                detail: { text: text.trim(), source: "voice" },
              }));
            }
          }
          setVoiceState("standby", "neutral");
          sttStatusEl.textContent = "Mic: standby";
          queueTelemetry("stt_server_result", "server STT completed", { text_length: text.length });
          resolve(text);
        } else {
          setVoiceState("stt error", "warn");
          sttStatusEl.textContent = "Mic: server STT failed";
          queueTelemetry("stt_server_error", "server STT request failed");
          resolve(null);
        }
      } catch (err) {
        setVoiceState("stt error", "warn");
        sttStatusEl.textContent = `Mic: ${err.message || "error"}`;
        queueTelemetry("stt_server_error", "server STT network error", { error: String(err) });
        resolve(null);
      }
    };
    recorder.stop();
  });
}

export async function setupSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  appState.recognitionSupported = Boolean(SpeechRecognition);
  if (!appState.recognitionSupported) {
    voiceEngineEl.textContent = "stt unavailable";
    micBtn.disabled = true;
    sttStatusEl.textContent = "Mic: browser STT not supported";
    return;
  }
  appState.recognition = new SpeechRecognition();
  appState.recognition.continuous = true;
  appState.recognition.interimResults = true;
  appState.recognition.lang = "en-US";
  appState.recognition.onstart = () => {
    appState.recognitionActive = true;
    micBtn.textContent = "Stop Listening";
    setVoiceState(appState.speechActive ? "speaking" : "listening", "good");
    sttStatusEl.textContent = "Mic: listening";
    queueTelemetry("stt_listening", "speech recognition started");
  };
  appState.recognition.onend = () => {
    appState.recognitionActive = false;
    micBtn.textContent = "Start Listening";
    setVoiceState(appState.speechActive ? "speaking" : "standby", appState.speechActive ? "good" : "neutral");
    sttStatusEl.textContent = "Mic: standby";
    avatar.setListeningLevel(0);
    queueTelemetry("stt_stopped", "speech recognition stopped");
  };
  appState.recognition.onerror = (event) => {
    appState.recognitionActive = false;
    micBtn.textContent = "Start Listening";
    setVoiceState("stt error", "warn");
    sttStatusEl.textContent = `Mic: ${event.error || "error"}`;
    queueTelemetry("stt_error", "speech recognition error", { error: event.error || "error" });
  };
  appState.recognition.onresult = (event) => {
    let interim = "";
    let finals = "";
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const transcript = event.results[i][0].transcript || "";
      if (event.results[i].isFinal) finals += `${transcript} `;
      else interim += transcript;
    }
    if (finals.trim()) {
      appState.recognitionTranscript = `${appState.recognitionTranscript} ${finals}`.trim();
      voiceTextEl.value = appState.recognitionTranscript;
      avatar.bump();
    }
    voiceTranscriptEl.textContent = interim.trim() || finals.trim() || "Listening\u2026";
  };
}
