"""State and event query routes."""

from typing import Optional

from fastapi import APIRouter

from ..config import settings
from ..deps import _dump, collector_status, store
from ..schemas import StateResponse

router = APIRouter()


@router.get("/api/state", response_model=StateResponse)
async def get_state() -> StateResponse:
    """Return the current event state with idle status."""
    current = await store.current()
    count = await store.event_count()
    idle, idle_since = await store.idle_state()
    category = current.category if current else None
    return StateResponse(
        current=current,
        event_count=count,
        idle=idle,
        idle_since=idle_since,
        category=category,
    )


@router.get("/api/state/snapshot")
async def get_desktop_snapshot() -> dict:
    """Return a desktop context snapshot for the agent vision panel."""
    from ..desktop_context import DesktopContext

    current = await store.current()
    if current is None:
        return {"context": None}
    ctx = DesktopContext.from_event(current)
    if ctx is None:
        return {"context": None}
    return {
        "context": {
            "window_title": ctx.window_title,
            "process_exe": ctx.process_exe,
            "timestamp": ctx.timestamp.isoformat(),
            "uia_summary": ctx.uia_summary,
            "screenshot_available": ctx.screenshot_b64 is not None,
        }
    }


@router.get("/api/state/session")
async def get_session_summary() -> dict:
    """Return a rolling 30-minute session summary with app switches and dwell times."""
    return await store.session_summary()


@router.get("/api/events")
async def get_events(limit: Optional[int] = None) -> dict:
    """List recent desktop events."""
    if limit is None:
        limit = settings.event_limit_default
    events = await store.events(limit=limit)
    return {"events": [_dump(event) for event in events]}


@router.get("/api/collector")
async def get_collector_status() -> dict:
    """Return Windows collector connection status and event counters."""
    return await collector_status.snapshot()
