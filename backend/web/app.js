const statusEl = document.getElementById("status");
const currentTitleEl = document.getElementById("current-title");
const currentMetaEl = document.getElementById("current-meta");
const currentCategoryEl = document.getElementById("current-category");
const currentIdleEl = document.getElementById("current-idle");
const currentTimeEl = document.getElementById("current-time");
const currentAppEl = document.getElementById("current-app");
const eventCountEl = document.getElementById("event-count");
const eventsEl = document.getElementById("events");
const eventSearchEl = document.getElementById("event-search");
const eventCategoryEl = document.getElementById("event-category");
const eventTypeEl = document.getElementById("event-type");
const ollamaStatusEl = document.getElementById("ollama-status");
const summaryBtn = document.getElementById("summary-btn");
const summaryText = document.getElementById("summary-text");

const MAX_EVENTS = 50;
let events = [];
let ws;

function formatTime(ts) {
  if (!ts) return "—";
  const date = new Date(ts);
  return date.toLocaleString();
}

function updateCurrent(state) {
  const idleLabel = state && typeof state.idle === "boolean" ? (state.idle ? "Idle" : "Active") : "—";
  currentIdleEl.textContent = `Status: ${idleLabel}`;
  const categoryLabel =
    state && state.current ? state.current.category || state.category || "uncategorized" : "—";
  currentCategoryEl.textContent = `Category: ${categoryLabel}`;
  if (!state || !state.current) {
    currentTitleEl.textContent = "Waiting for events…";
    currentMetaEl.textContent = "—";
    currentTimeEl.textContent = "—";
    currentAppEl.textContent = "—";
    return;
  }
  const ev = state.current;
  currentTitleEl.textContent = ev.title || "(untitled window)";
  currentMetaEl.textContent = `${ev.process_exe || "unknown"} · pid ${ev.pid}`;
  currentTimeEl.textContent = formatTime(ev.timestamp);
  currentAppEl.textContent = ev.type || "foreground";
}

function applyFilters(items) {
  let filtered = items.slice();
  const query = (eventSearchEl.value || "").trim().toLowerCase();
  const category = eventCategoryEl.value;
  const type = eventTypeEl.value;

  if (type !== "all") {
    filtered = filtered.filter((ev) => (ev.type || "foreground") === type);
  }
  if (category !== "all") {
    filtered = filtered.filter((ev) => (ev.category || "uncategorized") === category);
  }
  if (query) {
    filtered = filtered.filter((ev) => {
      const uia = ev.uia || {};
      const haystack = [
        ev.title,
        ev.process_exe,
        ev.category,
        ev.type,
        uia.focused_name,
        uia.control_type,
        uia.document_text,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }
  return filtered;
}

function renderEvents() {
  eventsEl.innerHTML = "";
  const frag = document.createDocumentFragment();
  const filtered = applyFilters(events);
  filtered.slice().reverse().forEach((ev) => {
    const li = document.createElement("li");
    li.className = "event-item";

    const title = document.createElement("p");
    title.className = "event-title";
    if (ev.title) {
      title.textContent = ev.title;
    } else if (ev.type === "idle") {
      title.textContent = "Idle";
    } else if (ev.type === "active") {
      title.textContent = "Active";
    } else {
      title.textContent = "(untitled window)";
    }

    const meta = document.createElement("p");
    meta.className = "event-meta";
    const parts = [formatTime(ev.timestamp)];
    if (ev.process_exe) {
      parts.push(ev.process_exe);
    }
    if (ev.pid) {
      parts.push(`pid ${ev.pid}`);
    }
    if (ev.idle_ms !== null && ev.idle_ms !== undefined) {
      parts.push(`idle ${(ev.idle_ms / 1000).toFixed(0)}s`);
    }
    meta.textContent = parts.join(" · ");

    const tags = document.createElement("div");
    tags.className = "event-tags";
    const category = ev.category || (ev.type === "foreground" ? "uncategorized" : null);
    if (category) {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = category;
      tags.appendChild(tag);
    }
    if (ev.type) {
      const tag = document.createElement("span");
      tag.className = `tag type-${ev.type}`;
      tag.textContent = ev.type;
      tags.appendChild(tag);
    }

    li.appendChild(title);
    li.appendChild(meta);
    if (tags.childNodes.length > 0) {
      li.appendChild(tags);
    }
    frag.appendChild(li);
  });
  eventsEl.appendChild(frag);
  eventCountEl.textContent = String(filtered.length);
}

function setStatus(text, tone) {
  statusEl.textContent = text;
  statusEl.style.color = tone === "good" ? "#0f8b8d" : tone === "warn" ? "#b85b2b" : "#5b6470";
}

async function fetchSnapshot() {
  try {
    const [stateResp, eventsResp] = await Promise.all([
      fetch("/api/state"),
      fetch(`/api/events?limit=${MAX_EVENTS}`),
    ]);
    const state = await stateResp.json();
    const eventsData = await eventsResp.json();
    events = eventsData.events || [];
    updateCurrent(state);
    renderEvents();
  } catch (err) {
    console.error("snapshot error", err);
  }
}

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  setStatus("connecting", "neutral");

  ws.onopen = () => {
    setStatus("live", "good");
  };

  ws.onmessage = (message) => {
    try {
      const payload = JSON.parse(message.data);
      if (payload.type === "snapshot") {
        events = payload.events || [];
        updateCurrent(payload.state);
        renderEvents();
      }
      if (payload.type === "event") {
        if (payload.event) {
          events.push(payload.event);
          if (events.length > MAX_EVENTS) {
            events = events.slice(-MAX_EVENTS);
          }
          renderEvents();
        }
      }
      if (payload.type === "state") {
        updateCurrent(payload.state);
      }
    } catch (err) {
      console.error("ws message error", err);
    }
  };

  ws.onclose = () => {
    setStatus("disconnected", "warn");
    setTimeout(connectWs, 1500);
  };

  ws.onerror = () => {
    ws.close();
  };
}

async function checkOllama() {
  try {
    const resp = await fetch("/api/ollama");
    const data = await resp.json();
    if (data.available) {
      ollamaStatusEl.textContent = "available";
      summaryBtn.disabled = false;
    } else {
      ollamaStatusEl.textContent = "offline";
      summaryBtn.disabled = true;
    }
  } catch (err) {
    ollamaStatusEl.textContent = "unknown";
    summaryBtn.disabled = true;
  }
}

summaryBtn.addEventListener("click", async () => {
  summaryBtn.disabled = true;
  summaryText.textContent = "Summarizing…";
  try {
    const resp = await fetch("/api/summarize", { method: "POST" });
    if (!resp.ok) {
      const err = await resp.json();
      summaryText.textContent = err.detail || "Summary failed";
    } else {
      const data = await resp.json();
      summaryText.textContent = data.summary || "No summary.";
    }
  } catch (err) {
    summaryText.textContent = "Summary failed";
  } finally {
    await checkOllama();
  }
});

eventSearchEl.addEventListener("input", () => renderEvents());
eventCategoryEl.addEventListener("change", () => renderEvents());
eventTypeEl.addEventListener("change", () => renderEvents());

fetchSnapshot();
connectWs();
checkOllama();
