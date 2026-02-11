"""Collector ingest routes: WebSocket and HTTP event ingestion."""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import settings
from ..deps import (
    _dump,
    _parse_event,
    bridge,
    classifier,
    collector_status,
    db,
    hub,
    notification_engine,
    notification_store,
    store,
)
from ..notification_engine import StateSnapshot
from ..schemas import WindowEvent

logger = logging.getLogger(__name__)

router = APIRouter()


async def _handle_event(event: WindowEvent, *, transport: str) -> None:
    logger.info(
        "event_received transport=%s type=%s source=%s title=%s",
        transport,
        event.type,
        event.source or "",
        event.title or "",
    )
    if event.type == "foreground" and not event.category:
        classification = await classifier.classify(event)
        event.category = classification.category

    await collector_status.note_event(
        event.timestamp,
        transport=transport,
        source=event.source,
        has_uia=event.uia is not None,
    )

    await db.record_event(event)
    await store.record(event)
    current = await store.current()
    count = await store.event_count()
    idle, idle_since = await store.idle_state()
    await hub.broadcast_json({"type": "event", "event": _dump(event)})
    await hub.broadcast_json(
        {
            "type": "state",
            "state": {
                "current": _dump(current) if current else None,
                "event_count": count,
                "idle": idle,
                "idle_since": idle_since.isoformat() if idle_since else None,
                "category": current.category if current else None,
            },
        }
    )

    # Evaluate notification rules
    snapshot = StateSnapshot(
        idle=idle,
        idle_since_ts=idle_since.timestamp() if idle_since else None,
        process_exe=event.process_exe or "",
        window_title=event.title or "",
        event_count=count,
    )
    await notification_engine.evaluate(snapshot)


@router.post("/api/events")
async def post_event(event: WindowEvent) -> dict:
    """Ingest a single desktop event via HTTP."""
    await _handle_event(event, transport="http")
    return {"status": "ok"}


async def _broadcast_collector_greeting() -> None:
    """Broadcast a session greeting when the collector connects."""
    try:
        # Broadcast bridge status to UI
        await hub.broadcast_json({
            "type": "bridge_status",
            "connected": True,
            "message": "Windows collector connected. Desktop actions are live.",
        })
        # Create a notification so the user sees it in the bell
        if notification_engine._enabled:
            saved = await notification_store.create(
                type="info",
                title="Desktop Connected",
                message="DesktopAI can now see and control your desktop. Say the word.",
                rule="session_greeting",
            )
            await hub.broadcast_json(
                {"type": "notification", "notification": saved}
            )
    except Exception as exc:
        logger.debug("Session greeting failed: %s", exc)


async def _broadcast_collector_disconnect() -> None:
    """Broadcast status when the collector disconnects."""
    try:
        await hub.broadcast_json({
            "type": "bridge_status",
            "connected": False,
            "message": "Windows collector disconnected.",
        })
    except Exception as exc:
        logger.debug("Disconnect broadcast failed: %s", exc)


async def _heartbeat_sender(ws: WebSocket, interval_s: int) -> None:
    """Send periodic JSON pings to the collector to detect stale connections."""
    while True:
        await asyncio.sleep(interval_s)
        try:
            await ws.send_json({"type": "ping"})
        except Exception:
            break


@router.websocket("/ingest")
async def ingest_ws(ws: WebSocket) -> None:
    """WebSocket endpoint for real-time event ingestion from the collector."""
    await ws.accept()
    await collector_status.note_ws_connected(datetime.now(timezone.utc))
    bridge.attach(ws)
    await _broadcast_collector_greeting()
    heartbeat_task = asyncio.create_task(
        _heartbeat_sender(ws, settings.collector_heartbeat_interval_s)
    )
    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "")
            if msg_type == "command_result":
                bridge.handle_result(data)
                continue
            if msg_type == "pong":
                await collector_status.note_heartbeat(datetime.now(timezone.utc))
                continue
            event = _parse_event(data)
            await _handle_event(event, transport="ws")
            await ws.send_json({"status": "ok"})
    except WebSocketDisconnect:
        bridge.detach()
        heartbeat_task.cancel()
        await _broadcast_collector_disconnect()
        await collector_status.note_ws_disconnected(datetime.now(timezone.utc))
        logger.info("Collector WS disconnected")
    except Exception as exc:
        bridge.detach()
        heartbeat_task.cancel()
        await _broadcast_collector_disconnect()
        await collector_status.note_ws_disconnected(datetime.now(timezone.utc))
        logger.exception("Collector WS error: %s", exc)
