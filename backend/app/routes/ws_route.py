"""UI WebSocket route."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import settings
from ..deps import _dump, autonomy, hub, store

router = APIRouter()


@router.websocket("/ws")
async def ui_ws(ws: WebSocket) -> None:
    accepted = await hub.add(ws)
    if not accepted:
        return
    current, events = await store.snapshot()
    idle, idle_since = await store.idle_state()
    runs = await autonomy.list_runs(limit=1)
    latest_run = runs[0] if runs else None
    await ws.send_json(
        {
            "type": "snapshot",
            "state": {
                "current": _dump(current) if current else None,
                "event_count": len(events),
                "idle": idle,
                "idle_since": idle_since.isoformat() if idle_since else None,
                "category": current.category if current else None,
            },
            "events": [_dump(event) for event in events[-settings.event_limit_default :]],
            "autonomy_run": _dump(latest_run) if latest_run else None,
        }
    )
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await hub.remove(ws)
