"""Collector ingest routes: WebSocket and HTTP event ingestion."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..deps import (
    _dump,
    _parse_event,
    bridge,
    classifier,
    collector_status,
    db,
    hub,
    store,
)
from ..config import settings
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


@router.post("/api/events")
async def post_event(event: WindowEvent) -> dict:
    await _handle_event(event, transport="http")
    return {"status": "ok"}


@router.websocket("/ingest")
async def ingest_ws(ws: WebSocket) -> None:
    await ws.accept()
    await collector_status.note_ws_connected(datetime.now(timezone.utc))
    bridge.attach(ws)
    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "")
            if msg_type == "command_result":
                bridge.handle_result(data)
                continue
            event = _parse_event(data)
            await _handle_event(event, transport="ws")
            await ws.send_json({"status": "ok"})
    except WebSocketDisconnect:
        bridge.detach()
        await collector_status.note_ws_disconnected(datetime.now(timezone.utc))
        logger.info("Collector WS disconnected")
    except Exception as exc:
        bridge.detach()
        await collector_status.note_ws_disconnected(datetime.now(timezone.utc))
        logger.exception("Collector WS error: %s", exc)
