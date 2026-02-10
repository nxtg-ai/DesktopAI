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
