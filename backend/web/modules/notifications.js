/** Notification bell, dropdown, and real-time badge updates. */

import { queueTelemetry } from "./telemetry.js";

const bellBtn = document.getElementById("notification-bell");
const badgeEl = document.getElementById("notification-count");
const dropdownEl = document.getElementById("notification-dropdown");

let dropdownOpen = false;

export async function refreshNotificationCount() {
  try {
    const resp = await fetch("/api/notifications/count");
    if (!resp.ok) return;
    const data = await resp.json();
    updateBadge(data.unread_count || 0);
  } catch { /* ignore */ }
}

function updateBadge(count) {
  if (!badgeEl) return;
  if (count > 0) {
    badgeEl.textContent = count > 99 ? "99+" : String(count);
    badgeEl.hidden = false;
  } else {
    badgeEl.hidden = true;
  }
}

export function handleNotificationWsMessage(notification) {
  refreshNotificationCount();
  queueTelemetry("notification_received", "notification received", { rule: notification.rule });
}

async function toggleDropdown() {
  if (!dropdownEl) return;
  dropdownOpen = !dropdownOpen;
  if (dropdownOpen) {
    dropdownEl.hidden = false;
    await loadNotifications();
  } else {
    dropdownEl.hidden = true;
  }
}

async function loadNotifications() {
  if (!dropdownEl) return;
  try {
    const resp = await fetch("/api/notifications?limit=10");
    if (!resp.ok) return;
    const data = await resp.json();
    renderNotifications(data.notifications || []);
  } catch { /* ignore */ }
}

function renderNotifications(items) {
  if (!dropdownEl) return;
  if (items.length === 0) {
    dropdownEl.innerHTML = '<p class="notification-empty">No notifications</p>';
    return;
  }
  dropdownEl.innerHTML = items.map((n) => {
    const readClass = n.read_at ? "read" : "unread";
    return `<div class="notification-item ${readClass}" data-id="${n.notification_id}">
      <strong>${n.title}</strong>
      <p>${n.message}</p>
      <span class="notification-time">${n.created_at}</span>
    </div>`;
  }).join("");

  dropdownEl.querySelectorAll(".notification-item.unread").forEach((el) => {
    el.addEventListener("click", async () => {
      const id = el.dataset.id;
      await fetch(`/api/notifications/${id}/read`, { method: "POST" });
      el.classList.remove("unread");
      el.classList.add("read");
      refreshNotificationCount();
    });
  });
}

// Wire up bell click
if (bellBtn) bellBtn.addEventListener("click", () => void toggleDropdown());

// Close dropdown on outside click
document.addEventListener("click", (e) => {
  if (dropdownOpen && dropdownEl && bellBtn && !bellBtn.contains(e.target) && !dropdownEl.contains(e.target)) {
    dropdownOpen = false;
    dropdownEl.hidden = true;
  }
});
