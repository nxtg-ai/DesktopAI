/** Event list rendering and filtering. */

import {
  appState, eventsEl, eventCountEl, eventSearchEl, eventCategoryEl, eventTypeEl,
  currentTitleEl, currentMetaEl, currentCategoryEl, currentIdleEl, currentTimeEl,
  currentAppEl, avatar, formatTime,
} from "./state.js";
import { queueTelemetry } from "./telemetry.js";

function applyFilters(items) {
  let filtered = items.slice();
  const query = (eventSearchEl.value || "").trim().toLowerCase();
  const category = eventCategoryEl.value;
  const type = eventTypeEl.value;
  if (type !== "all") filtered = filtered.filter((ev) => (ev.type || "foreground") === type);
  if (category !== "all") filtered = filtered.filter((ev) => (ev.category || "uncategorized") === category);
  if (query) {
    filtered = filtered.filter((ev) => {
      const uia = ev.uia || {};
      const haystack = [ev.title, ev.process_exe, ev.category, ev.type, uia.focused_name, uia.control_type, uia.document_text]
        .filter(Boolean).join(" ").toLowerCase();
      return haystack.includes(query);
    });
  }
  return filtered;
}

export function renderEvents() {
  eventsEl.innerHTML = "";
  const frag = document.createDocumentFragment();
  const filtered = applyFilters(appState.events);
  filtered.slice().reverse().forEach((ev) => {
    const li = document.createElement("li");
    li.className = "event-item";
    const title = document.createElement("p");
    title.className = "event-title";
    if (ev.title) title.textContent = ev.title;
    else if (ev.type === "idle") title.textContent = "Idle";
    else if (ev.type === "active") title.textContent = "Active";
    else title.textContent = "(untitled window)";
    const meta = document.createElement("p");
    meta.className = "event-meta";
    const parts = [formatTime(ev.timestamp)];
    if (ev.process_exe) parts.push(ev.process_exe);
    if (ev.pid) parts.push(`pid ${ev.pid}`);
    if (ev.idle_ms !== null && ev.idle_ms !== undefined) parts.push(`idle ${(ev.idle_ms / 1000).toFixed(0)}s`);
    meta.textContent = parts.join(" \u00b7 ");
    const tags = document.createElement("div");
    tags.className = "event-tags";
    const cat = ev.category || (ev.type === "foreground" ? "uncategorized" : null);
    if (cat) { const tag = document.createElement("span"); tag.className = "tag"; tag.textContent = cat; tags.appendChild(tag); }
    if (ev.type) { const tag = document.createElement("span"); tag.className = `tag type-${ev.type}`; tag.textContent = ev.type; tags.appendChild(tag); }
    li.appendChild(title);
    li.appendChild(meta);
    if (tags.childNodes.length > 0) li.appendChild(tags);
    frag.appendChild(li);
  });
  eventsEl.appendChild(frag);
  eventCountEl.textContent = String(filtered.length);
}

export function updateCurrent(state) {
  const idleLabel = state && typeof state.idle === "boolean" ? (state.idle ? "Idle" : "Active") : "\u2014";
  currentIdleEl.textContent = `Status: ${idleLabel}`;
  const categoryLabel = state && state.current ? state.current.category || state.category || "uncategorized" : "\u2014";
  currentCategoryEl.textContent = `Category: ${categoryLabel}`;
  avatar.setActivity({ idle: state ? state.idle : false });
  if (!state || !state.current) {
    currentTitleEl.textContent = "Waiting for events\u2026";
    currentMetaEl.textContent = "\u2014";
    currentTimeEl.textContent = "\u2014";
    currentAppEl.textContent = "\u2014";
    return;
  }
  const ev = state.current;
  const fingerprint = `${ev.timestamp || ""}|${ev.hwnd || ""}|${ev.title || ""}|${ev.process_exe || ""}`;
  if (fingerprint !== appState.lastWindowFingerprint) {
    queueTelemetry("current_window_changed", "foreground window changed", {
      title: ev.title || "", process_exe: ev.process_exe || "", pid: ev.pid || 0,
      category: ev.category || state.category || null, idle: Boolean(state.idle), event_count: state.event_count || 0,
    });
    appState.lastWindowFingerprint = fingerprint;
  }
  currentTitleEl.textContent = ev.title || "(untitled window)";
  currentMetaEl.textContent = `${ev.process_exe || "unknown"} \u00b7 pid ${ev.pid}`;
  currentTimeEl.textContent = formatTime(ev.timestamp);
  currentAppEl.textContent = ev.type || "foreground";
}
