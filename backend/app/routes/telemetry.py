"""UI telemetry and runtime log routes."""

from typing import Optional

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..deps import _dump, _parse_iso_timestamp, runtime_logs, ui_telemetry
from ..schemas import UiTelemetryIngestRequest

router = APIRouter()


@router.post("/api/ui-telemetry")
async def post_ui_telemetry(request: UiTelemetryIngestRequest) -> dict:
    accepted, artifact_files = await ui_telemetry.ingest(request.events)
    return {
        "accepted": accepted,
        "artifact_file": artifact_files[0] if len(artifact_files) == 1 else None,
        "artifact_files": artifact_files,
    }


@router.get("/api/ui-telemetry")
async def list_ui_telemetry(session_id: Optional[str] = None, limit: int = 200) -> dict:
    events = await ui_telemetry.list_events(session_id=session_id, limit=limit)
    return {"events": [_dump(event) for event in events]}


@router.get("/api/ui-telemetry/sessions")
async def list_ui_telemetry_sessions(limit: int = 100) -> dict:
    sessions = await ui_telemetry.list_sessions(limit=limit)
    return {"sessions": sessions}


@router.post("/api/ui-telemetry/reset")
async def reset_ui_telemetry(clear_artifacts: bool = True) -> dict:
    cleared = await ui_telemetry.reset(clear_artifacts=clear_artifacts)
    return {"cleared": cleared}


@router.get("/api/runtime-logs")
async def list_runtime_logs(
    limit: int = 200,
    level: Optional[str] = None,
    contains: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> dict:
    if since and _parse_iso_timestamp(since) is None:
        raise HTTPException(status_code=400, detail="invalid since timestamp")
    if until and _parse_iso_timestamp(until) is None:
        raise HTTPException(status_code=400, detail="invalid until timestamp")
    logs = runtime_logs.list_entries(
        limit=limit,
        level=level,
        contains=contains,
        since=since,
        until=until,
    )
    return {"logs": logs}


@router.post("/api/runtime-logs/reset")
async def reset_runtime_logs() -> dict:
    cleared = runtime_logs.clear()
    return {"cleared": cleared}


@router.get("/api/runtime-logs/correlate")
async def correlate_runtime_logs(
    session_id: str,
    limit: int = 200,
    level: Optional[str] = None,
    contains: Optional[str] = None,
) -> dict:
    session = (session_id or "").strip()
    if not session:
        raise HTTPException(status_code=400, detail="session_id is required")

    telemetry_events = await ui_telemetry.list_events(session_id=session, limit=settings.ui_telemetry_max_events)
    parsed_times = [
        ts
        for ts in (_parse_iso_timestamp(getattr(event, "timestamp", None)) for event in telemetry_events)
        if ts is not None
    ]
    if not parsed_times:
        return {
            "session_id": session,
            "event_count": len(telemetry_events),
            "window": None,
            "logs": [],
        }

    since_dt = min(parsed_times)
    until_dt = max(parsed_times)
    logs = runtime_logs.list_entries(
        limit=limit,
        level=level,
        contains=contains,
        since=since_dt.isoformat(),
        until=until_dt.isoformat(),
    )
    return {
        "session_id": session,
        "event_count": len(telemetry_events),
        "window": {
            "since": since_dt.isoformat(),
            "until": until_dt.isoformat(),
        },
        "logs": logs,
    }
