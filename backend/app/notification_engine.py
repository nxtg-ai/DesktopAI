"""Rule-based notification engine evaluated on event ingestion."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional, Set

from .notifications import NotificationStore
from .ws import WebSocketHub


@dataclass
class StateSnapshot:
    """Minimal snapshot of desktop state for rule evaluation."""

    idle: bool = False
    idle_since_ts: Optional[float] = None  # epoch seconds
    process_exe: str = ""
    window_title: str = ""
    event_count: int = 0


class NotificationRule(ABC):
    """Base class for notification rules."""

    @abstractmethod
    def check(self, snapshot: StateSnapshot) -> Optional[Dict[str, Any]]:
        """Return notification kwargs dict if rule triggers, else None."""


class IdleRule(NotificationRule):
    """Alert after continuous idle exceeds threshold."""

    def __init__(self, threshold_s: int = 300) -> None:
        self._threshold_s = threshold_s
        self._notified = False

    def check(self, snapshot: StateSnapshot) -> Optional[Dict[str, Any]]:
        if not snapshot.idle or snapshot.idle_since_ts is None:
            self._notified = False
            return None
        elapsed = time.time() - snapshot.idle_since_ts
        if elapsed >= self._threshold_s and not self._notified:
            self._notified = True
            minutes = int(elapsed // 60)
            return {
                "type": "info",
                "title": "Idle Detected",
                "message": f"You've been idle for {minutes} minute{'s' if minutes != 1 else ''}.",
                "rule": "idle",
            }
        return None


class AppSwitchRule(NotificationRule):
    """Alert if too many app switches in a short window (possible distraction)."""

    def __init__(self, max_switches: int = 10, window_s: int = 60) -> None:
        self._max_switches = max_switches
        self._window_s = window_s
        self._timestamps: Deque[float] = deque()
        self._last_process: str = ""
        self._notified_at: float = 0

    def check(self, snapshot: StateSnapshot) -> Optional[Dict[str, Any]]:
        if not snapshot.process_exe or snapshot.process_exe == self._last_process:
            return None
        self._last_process = snapshot.process_exe
        now = time.time()
        self._timestamps.append(now)
        # Trim old entries
        cutoff = now - self._window_s
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        if len(self._timestamps) > self._max_switches and (now - self._notified_at) > self._window_s:
            self._notified_at = now
            return {
                "type": "warning",
                "title": "Rapid App Switching",
                "message": f"You've switched apps {len(self._timestamps)} times in the last {self._window_s}s. Consider focusing.",
                "rule": "app_switch",
            }
        return None


class SessionMilestoneRule(NotificationRule):
    """Notify at session duration milestones (1h, 2h, 4h)."""

    def __init__(self) -> None:
        self._start_time: Optional[float] = None
        self._milestones_hours = [1, 2, 4]
        self._notified_milestones: Set[int] = set()

    def check(self, snapshot: StateSnapshot) -> Optional[Dict[str, Any]]:
        if snapshot.event_count == 0:
            return None
        if self._start_time is None:
            self._start_time = time.time()
            return None
        elapsed_h = (time.time() - self._start_time) / 3600
        for milestone in self._milestones_hours:
            if elapsed_h >= milestone and milestone not in self._notified_milestones:
                self._notified_milestones.add(milestone)
                return {
                    "type": "info",
                    "title": "Session Milestone",
                    "message": f"You've been working for {milestone} hour{'s' if milestone > 1 else ''}. Consider a break.",
                    "rule": "session_milestone",
                }
        return None


class ContextInsightRule(NotificationRule):
    """Detect patterns like toggling between two apps or dwelling on a document.

    Vision: "you've been switching between Outlook and this spreadsheet for 20 min"
    """

    def __init__(
        self,
        toggle_window_s: int = 1200,  # 20 min window
        toggle_min_switches: int = 6,  # at least 6 switches between the pair
        dwell_threshold_s: int = 1800,  # 30 min on same app
    ) -> None:
        self._toggle_window_s = toggle_window_s
        self._toggle_min_switches = toggle_min_switches
        self._dwell_threshold_s = dwell_threshold_s
        # Track recent (timestamp, process) pairs
        self._recent: Deque[tuple[float, str]] = deque(maxlen=200)
        self._last_process: str = ""
        self._dwell_start: float = 0.0
        self._dwell_process: str = ""
        self._notified_toggle_pair: Optional[tuple[str, str]] = None
        self._notified_toggle_at: float = 0.0
        self._notified_dwell_process: str = ""

    def _short_name(self, process_exe: str) -> str:
        """Extract readable app name from process path."""
        name = process_exe.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        if name.lower().endswith(".exe"):
            name = name[:-4]
        return name

    def check(self, snapshot: StateSnapshot) -> Optional[Dict[str, Any]]:
        if not snapshot.process_exe:
            return None
        now = time.time()
        proc = snapshot.process_exe

        # Track process changes
        if proc != self._last_process:
            self._recent.append((now, proc))
            self._last_process = proc

            # Reset dwell tracking on switch
            self._dwell_start = now
            self._dwell_process = proc
            self._notified_dwell_process = ""

            # Check for toggle pattern: same two apps back and forth
            result = self._check_toggle(now)
            if result:
                return result
        else:
            # Same app — check dwell
            result = self._check_dwell(now, proc)
            if result:
                return result

        return None

    def _check_toggle(self, now: float) -> Optional[Dict[str, Any]]:
        """Detect A→B→A→B toggle pattern within the time window."""
        cutoff = now - self._toggle_window_s
        recent_in_window = [(ts, p) for ts, p in self._recent if ts >= cutoff]

        if len(recent_in_window) < self._toggle_min_switches:
            return None

        # Count transitions between each pair
        pair_counts: Dict[tuple[str, str], int] = {}
        for i in range(1, len(recent_in_window)):
            a = recent_in_window[i - 1][1]
            b = recent_in_window[i][1]
            if a != b:
                pair = tuple(sorted([a, b]))
                pair_counts[pair] = pair_counts.get(pair, 0) + 1  # type: ignore[assignment]

        # Find dominant pair
        for pair, count in pair_counts.items():
            if count >= self._toggle_min_switches:
                # Suppress duplicate notifications for same pair
                if pair == self._notified_toggle_pair and (now - self._notified_toggle_at) < self._toggle_window_s:
                    continue
                self._notified_toggle_pair = pair  # type: ignore[assignment]
                self._notified_toggle_at = now
                a_name = self._short_name(pair[0])
                b_name = self._short_name(pair[1])
                minutes = int(self._toggle_window_s / 60)
                return {
                    "type": "insight",
                    "title": "Context Insight",
                    "message": (
                        f"You've been switching between {a_name} and {b_name} "
                        f"for the last {minutes} minutes. Working on something "
                        f"across both? I can help."
                    ),
                    "rule": "context_insight_toggle",
                }
        return None

    def _check_dwell(self, now: float, proc: str) -> Optional[Dict[str, Any]]:
        """Detect prolonged focus on a single application."""
        if not self._dwell_process or self._dwell_process != proc:
            return None
        elapsed = now - self._dwell_start
        if elapsed >= self._dwell_threshold_s and self._notified_dwell_process != proc:
            self._notified_dwell_process = proc
            name = self._short_name(proc)
            minutes = int(elapsed // 60)
            return {
                "type": "insight",
                "title": "Deep Focus",
                "message": (
                    f"You've been in {name} for {minutes} minutes straight. "
                    f"Nice focus! Need any help with what you're working on?"
                ),
                "rule": "context_insight_dwell",
            }
        return None


class NotificationEngine:
    """Evaluates notification rules against state snapshots."""

    def __init__(
        self,
        store: NotificationStore,
        hub: WebSocketHub,
        enabled: bool = True,
        idle_threshold_s: int = 300,
    ) -> None:
        self._store = store
        self._hub = hub
        self._enabled = enabled
        self._rules: List[NotificationRule] = [
            IdleRule(threshold_s=idle_threshold_s),
            AppSwitchRule(),
            SessionMilestoneRule(),
            ContextInsightRule(),
        ]

    async def evaluate(self, snapshot: StateSnapshot) -> None:
        if not self._enabled:
            return
        for rule in self._rules:
            result = rule.check(snapshot)
            if result:
                saved = await self._store.create(**result)
                await self._hub.broadcast_json(
                    {"type": "notification", "notification": saved}
                )
