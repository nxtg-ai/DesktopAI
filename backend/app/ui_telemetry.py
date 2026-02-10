"""UI telemetry ingestion, session tracking, and artifact storage."""

from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from datetime import datetime
from itertools import chain
from pathlib import Path
from typing import Iterable, Optional

from fastapi.encoders import jsonable_encoder

from .schemas import UiTelemetryEvent

_SAFE_SESSION_RE = re.compile(r"[^A-Za-z0-9._-]+")


class UiTelemetryStore:
    def __init__(self, artifact_dir: str, max_events: int = 5000):
        self._artifact_dir = Path(artifact_dir)
        self._max_events = max(1, max_events)
        self._events: list[UiTelemetryEvent] = []
        self._lock = asyncio.Lock()

    def _artifact_path_for_session(self, session_id: str) -> Path:
        safe = _SAFE_SESSION_RE.sub("_", (session_id or "").strip()) or "session"
        return self._artifact_dir / f"{safe}.jsonl"

    def _parse_event(self, payload: dict) -> UiTelemetryEvent:
        if hasattr(UiTelemetryEvent, "model_validate"):
            return UiTelemetryEvent.model_validate(payload)
        return UiTelemetryEvent.parse_obj(payload)

    def _read_artifact_events(self, session_id: str, limit: int) -> list[UiTelemetryEvent]:
        path = self._artifact_path_for_session(session_id)
        if not path.exists():
            return []

        events: list[UiTelemetryEvent] = []
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                    event = self._parse_event(payload)
                except Exception:
                    continue
                events.append(event)
                if len(events) > limit:
                    events = events[-limit:]
        return events

    def _summarize_events(self, events: Iterable[UiTelemetryEvent]) -> dict[str, dict]:
        summaries: dict[str, dict] = {}
        for event in events:
            session_id = event.session_id
            summary = summaries.get(session_id)
            ts = event.timestamp
            if summary is None:
                summaries[session_id] = {
                    "session_id": session_id,
                    "event_count": 1,
                    "first_timestamp": ts,
                    "last_timestamp": ts,
                }
                continue
            summary["event_count"] += 1
            if isinstance(summary["first_timestamp"], datetime) and ts < summary["first_timestamp"]:
                summary["first_timestamp"] = ts
            if isinstance(summary["last_timestamp"], datetime) and ts > summary["last_timestamp"]:
                summary["last_timestamp"] = ts
        return summaries

    def _summarize_artifacts(self, exclude_sessions: set[str]) -> dict[str, dict]:
        if not self._artifact_dir.exists():
            return {}
        summaries: dict[str, dict] = {}
        for path in self._artifact_dir.glob("*.jsonl"):
            events: list[UiTelemetryEvent] = []
            with path.open("r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                        event = self._parse_event(payload)
                    except Exception:
                        continue
                    if event.session_id in exclude_sessions:
                        events = []
                        break
                    events.append(event)
            if not events:
                continue
            summaries.update(self._summarize_events(events))
        return summaries

    def _append_files(self, events: Iterable[UiTelemetryEvent]) -> list[str]:
        grouped: dict[Path, list[str]] = defaultdict(list)
        for event in events:
            payload = jsonable_encoder(event)
            grouped[self._artifact_path_for_session(event.session_id)].append(json.dumps(payload))

        if not grouped:
            return []

        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        files = []
        for path, lines in grouped.items():
            with path.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines))
                f.write("\n")
            files.append(str(path.resolve()))
        files.sort()
        return files

    async def ingest(self, events: list[UiTelemetryEvent]) -> tuple[int, list[str]]:
        if not events:
            return 0, []
        async with self._lock:
            self._events.extend(events)
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events :]
        files = self._append_files(events)
        return len(events), files

    async def list_events(self, session_id: Optional[str] = None, limit: int = 200) -> list[UiTelemetryEvent]:
        cap = max(1, min(limit, self._max_events))
        async with self._lock:
            if session_id:
                filtered = [item for item in self._events if item.session_id == session_id]
            else:
                filtered = self._events
            in_memory = filtered[-cap:]
        if in_memory:
            return in_memory
        if session_id:
            return self._read_artifact_events(session_id, cap)
        return []

    async def list_sessions(self, limit: int = 100) -> list[dict]:
        cap = max(1, min(limit, self._max_events))
        async with self._lock:
            in_memory = list(self._events)

        summaries = self._summarize_events(in_memory)
        artifact_summaries = self._summarize_artifacts(exclude_sessions=set(summaries.keys()))
        combined = dict(chain(summaries.items(), artifact_summaries.items()))
        if not combined:
            return []

        items = list(combined.values())
        items.sort(
            key=lambda item: (
                item["last_timestamp"],
                item["session_id"],
            ),
            reverse=True,
        )
        items = items[:cap]

        return [
            {
                "session_id": item["session_id"],
                "event_count": item["event_count"],
                "first_timestamp": item["first_timestamp"].isoformat(),
                "last_timestamp": item["last_timestamp"].isoformat(),
                "artifact_file": str(self._artifact_path_for_session(item["session_id"]).resolve()),
            }
            for item in items
        ]

    async def reset(self, clear_artifacts: bool = True) -> int:
        async with self._lock:
            cleared = len(self._events)
            self._events = []
        if clear_artifacts and self._artifact_dir.exists():
            for path in self._artifact_dir.glob("*.jsonl"):
                path.unlink(missing_ok=True)
        return cleared
