"""Command history API routes."""
from __future__ import annotations

from fastapi import APIRouter

from ..deps import command_history

router = APIRouter()


@router.get("/api/commands/history")
async def get_command_history(limit: int = 20):
    """Return recent command history entries.

    Args:
        limit: Maximum entries to return (capped at 100).

    Returns:
        Dict with ``commands`` list and ``available`` flag.
    """
    if command_history is None:
        return {"commands": [], "available": False}
    entries = await command_history.recent(limit=min(limit, 100))
    return {"commands": entries, "available": True}


@router.get("/api/commands/last-undoable")
async def get_last_undoable():
    """Return the most recent reversible command that has not been undone.

    Returns:
        Dict with ``entry`` (or None) and ``available`` flag.
    """
    if command_history is None:
        return {"entry": None, "available": False}
    entry = await command_history.last_undoable()
    return {"entry": entry, "available": True}
