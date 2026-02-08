from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .classifier import ActivityClassifier
from .collector_status import CollectorStatusStore
from .config import settings
from .db import EventDatabase
from .action_executor import build_action_executor
from .ollama import OllamaClient
from .autonomy import AutonomousRunner
from .orchestrator import TaskOrchestrator
from .planner import (
    DeterministicAutonomyPlanner,
    OllamaAutonomyPlanner,
    PLANNER_MODE_OLLAMA_REQUIRED,
    PLANNER_SUPPORTED_MODES,
)
from .schemas import (
    AutonomyApproveRequest,
    AutonomyPlannerModeRequest,
    AutonomyStartRequest,
    ClassifyRequest,
    OllamaModelRequest,
    OllamaProbeRequest,
    StateResponse,
    ReadinessGateRequest,
    ReadinessMatrixRequest,
    TaskApproveRequest,
    TaskCreateRequest,
    TaskPlanRequest,
    UiTelemetryIngestRequest,
    WindowEvent,
)
from .selftest import run_selftest
from .state import StateStore
from .runtime_logs import RuntimeLogHandler, RuntimeLogStore
from .ui_telemetry import UiTelemetryStore
from .ws import WebSocketHub

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("desktopai.backend")
runtime_logs = RuntimeLogStore(max_entries=settings.runtime_log_max_entries)
runtime_log_handler = RuntimeLogHandler(runtime_logs)
root_logger = logging.getLogger()
if not any(isinstance(handler, RuntimeLogHandler) for handler in root_logger.handlers):
    root_logger.addHandler(runtime_log_handler)

RUNTIME_SETTING_PLANNER_MODE = "autonomy_planner_mode"
RUNTIME_SETTING_OLLAMA_MODEL = "ollama_model"
PLANNER_SOURCE_CONFIG_DEFAULT = "config_default"
PLANNER_SOURCE_RUNTIME_OVERRIDE = "runtime_override"
planner_mode_source = PLANNER_SOURCE_CONFIG_DEFAULT
ollama_model_source = PLANNER_SOURCE_CONFIG_DEFAULT


def _dump(model):
    # Always return JSON-safe primitives (e.g. datetime -> ISO string)
    return jsonable_encoder(model)


def _parse_event(data):
    if hasattr(WindowEvent, "model_validate"):
        return WindowEvent.model_validate(data)
    return WindowEvent.parse_obj(data)


def _parse_iso_timestamp(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ollama_unavailable_detail(*, ollama_required: bool, diagnostics: dict) -> str:
    base = (
        "Ollama unavailable; planner is configured as required."
        if ollama_required
        else "Ollama unavailable; summary/planner features limited."
    )
    last_error = str(diagnostics.get("last_error") or "").strip()
    last_status = diagnostics.get("last_http_status")
    if last_error:
        return f"{base} Last check: {last_error}"
    if isinstance(last_status, int):
        return f"{base} Last check HTTP status: {last_status}."
    return base

store = StateStore(max_events=settings.event_log_max)
ui_telemetry = UiTelemetryStore(
    artifact_dir=settings.ui_telemetry_artifact_dir,
    max_events=settings.ui_telemetry_max_events,
)
hub = WebSocketHub()
ollama = OllamaClient(settings.ollama_url, settings.ollama_model)
db = EventDatabase(
    settings.db_path,
    settings.db_retention_days,
    settings.db_max_events,
    settings.db_max_autonomy_runs,
    settings.db_autonomy_retention_days,
    settings.db_max_task_records,
    settings.db_task_retention_days,
)
collector_status = CollectorStatusStore()
classifier = ActivityClassifier(
    ollama,
    default_category=settings.classifier_default,
    use_ollama=settings.classifier_use_ollama,
)
deterministic_planner = DeterministicAutonomyPlanner()
planner = OllamaAutonomyPlanner(
    ollama=ollama,
    fallback=deterministic_planner,
    mode=settings.autonomy_planner_mode,
)
action_executor = build_action_executor(
    mode=settings.action_executor_mode,
    powershell_executable=settings.action_executor_powershell,
    timeout_s=settings.action_executor_timeout_s,
    default_compose_text=settings.action_executor_default_compose_text,
)


async def _persist_task_update(task) -> None:
    try:
        await db.upsert_task_record(task)
    except Exception as exc:
        logger.exception("Failed to persist task update: %s", exc)


tasks = TaskOrchestrator(
    on_task_update=_persist_task_update,
    action_executor=action_executor,
    executor_retry_count=settings.action_executor_retry_count,
    executor_retry_delay_ms=settings.action_executor_retry_delay_ms,
)


async def _publish_autonomy_update(run) -> None:
    try:
        await hub.broadcast_json({"type": "autonomy_run", "run": _dump(run)})
    except Exception as exc:
        logger.exception("Failed to broadcast autonomy run update: %s", exc)
    try:
        await asyncio.shield(db.upsert_autonomy_run(run))
    except Exception as exc:
        logger.exception("Failed to persist autonomy run update: %s", exc)


autonomy = AutonomousRunner(tasks, on_run_update=_publish_autonomy_update, planner=planner)


async def _restore_runtime_planner_mode() -> None:
    global planner_mode_source
    try:
        saved_mode = await db.get_runtime_setting(RUNTIME_SETTING_PLANNER_MODE)
    except Exception as exc:
        logger.warning("Failed to load runtime planner mode: %s", exc)
        planner_mode_source = PLANNER_SOURCE_CONFIG_DEFAULT
        return
    if not saved_mode:
        planner_mode_source = PLANNER_SOURCE_CONFIG_DEFAULT
        return
    try:
        planner.set_mode(saved_mode)
        planner_mode_source = PLANNER_SOURCE_RUNTIME_OVERRIDE
        logger.info("Restored runtime planner mode from DB: %s", planner.mode)
    except Exception as exc:
        planner_mode_source = PLANNER_SOURCE_CONFIG_DEFAULT
        logger.warning("Ignoring invalid persisted planner mode %r: %s", saved_mode, exc)


async def _restore_runtime_ollama_model() -> None:
    global ollama_model_source
    try:
        saved_model = await db.get_runtime_setting(RUNTIME_SETTING_OLLAMA_MODEL)
    except Exception as exc:
        logger.warning("Failed to load runtime Ollama model override: %s", exc)
        ollama_model_source = PLANNER_SOURCE_CONFIG_DEFAULT
        ollama.reset_active_model()
        return

    if not saved_model:
        ollama_model_source = PLANNER_SOURCE_CONFIG_DEFAULT
        ollama.reset_active_model()
        return

    try:
        ollama.set_active_model(saved_model)
        ollama_model_source = PLANNER_SOURCE_RUNTIME_OVERRIDE
        logger.info("Restored runtime Ollama model override from DB: %s", ollama.model)
    except Exception as exc:
        logger.warning("Ignoring invalid persisted Ollama model override %r: %s", saved_model, exc)
        ollama_model_source = PLANNER_SOURCE_CONFIG_DEFAULT
        ollama.reset_active_model()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    current, events, idle, idle_since = await db.load_snapshot(settings.event_log_max)
    await store.hydrate(events, current, idle, idle_since)
    task_records = await db.list_task_records(limit=500)
    await tasks.hydrate_tasks(task_records)
    runs = await db.list_autonomy_runs(limit=200)
    await autonomy.hydrate_runs(runs)
    await _restore_runtime_ollama_model()
    await _restore_runtime_planner_mode()
    try:
        yield
    finally:
        await autonomy.shutdown()
        drained = await tasks.drain_updates(timeout_s=2.0)
        if not drained:
            logger.warning("Timed out while draining pending task persistence updates.")


app = FastAPI(title="DesktopAI Backend", version="0.1.0", lifespan=_lifespan)

if settings.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def root() -> HTMLResponse:
    index_path = WEB_DIR / "index.html"
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/selftest")
async def selftest() -> dict:
    return run_selftest()


@app.get("/api/state", response_model=StateResponse)
async def get_state() -> StateResponse:
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


@app.get("/api/events")
async def get_events(limit: Optional[int] = None) -> dict:
    if limit is None:
        limit = settings.event_limit_default
    events = await store.events(limit=limit)
    return {"events": [_dump(event) for event in events]}


@app.get("/api/collector")
async def get_collector_status() -> dict:
    """Debug endpoint: is the Windows collector connected and sending UIA?"""
    return await collector_status.snapshot()


@app.get("/api/executor")
async def get_executor_status() -> dict:
    return tasks.executor_status()


@app.get("/api/executor/preflight")
async def get_executor_preflight() -> dict:
    return await tasks.executor_preflight()


@app.get("/api/readiness/status")
async def get_readiness_status() -> dict:
    preflight = await tasks.executor_preflight()
    collector = await collector_status.snapshot()
    ollama_available = await ollama.available()
    ollama_diagnostics = ollama.diagnostics()
    latest_runs = await autonomy.list_runs(limit=1)
    latest_run = latest_runs[0] if latest_runs else None
    latest_sessions = await ui_telemetry.list_sessions(limit=1)
    latest_session = latest_sessions[0] if latest_sessions else None
    runtime_log_entries = runtime_logs.count()

    collector_connected = bool(collector.get("ws_connected", False))
    planner_mode = planner.mode
    ollama_required = planner_mode == PLANNER_MODE_OLLAMA_REQUIRED
    checks = [
        {
            "name": "executor_preflight",
            "ok": bool(preflight.get("ok", False)),
            "required": True,
            "detail": preflight.get("message", ""),
        },
        {
            "name": "collector_connected",
            "ok": collector_connected,
            "required": False,
            "detail": "Windows collector websocket connected."
            if collector_connected
            else "Windows collector websocket not connected.",
        },
        {
            "name": "runtime_log_buffer",
            "ok": True,
            "required": True,
            "detail": f"{runtime_log_entries} buffered runtime logs.",
        },
        {
            "name": "ollama_available",
            "ok": bool(ollama_available),
            "required": ollama_required,
            "detail": "Ollama available for local summaries and planner mode."
            if ollama_available
            else _ollama_unavailable_detail(
                ollama_required=ollama_required,
                diagnostics=ollama_diagnostics,
            ),
        },
    ]

    ok = all(item["ok"] for item in checks if item.get("required", True))
    required_checks = [item for item in checks if item.get("required", True)]
    required_total = len(required_checks)
    required_failed = sum(1 for item in required_checks if not item.get("ok", False))
    required_passed = required_total - required_failed
    warning_count = sum(1 for item in checks if not item.get("ok", False) and not item.get("required", True))
    return {
        "ok": ok,
        "checks": checks,
        "summary": {
            "executor_mode": preflight.get("mode"),
            "autonomy_planner_mode": planner_mode,
            "autonomy_planner_source": planner_mode_source,
            "collector_connected": collector_connected,
            "collector_total_events": int(collector.get("total_events", 0) or 0),
            "latest_autonomy_run_id": latest_run.run_id if latest_run else None,
            "latest_autonomy_status": latest_run.status if latest_run else None,
            "latest_telemetry_session_id": latest_session.get("session_id") if latest_session else None,
            "runtime_log_entries": runtime_log_entries,
            "ollama_available": bool(ollama_available),
            "ollama_model_source": ollama_model_source,
            "ollama_configured_model": ollama_diagnostics.get("configured_model"),
            "ollama_active_model": ollama_diagnostics.get("active_model"),
            "ollama_last_check_at": ollama_diagnostics.get("last_check_at"),
            "ollama_last_check_source": ollama_diagnostics.get("last_check_source"),
            "ollama_last_http_status": ollama_diagnostics.get("last_http_status"),
            "ollama_last_error": ollama_diagnostics.get("last_error"),
            "required_total": required_total,
            "required_passed": required_passed,
            "required_failed": required_failed,
            "warning_count": warning_count,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/ui-telemetry")
async def post_ui_telemetry(request: UiTelemetryIngestRequest) -> dict:
    accepted, artifact_files = await ui_telemetry.ingest(request.events)
    return {
        "accepted": accepted,
        "artifact_file": artifact_files[0] if len(artifact_files) == 1 else None,
        "artifact_files": artifact_files,
    }


@app.get("/api/ui-telemetry")
async def list_ui_telemetry(session_id: Optional[str] = None, limit: int = 200) -> dict:
    events = await ui_telemetry.list_events(session_id=session_id, limit=limit)
    return {"events": [_dump(event) for event in events]}


@app.get("/api/ui-telemetry/sessions")
async def list_ui_telemetry_sessions(limit: int = 100) -> dict:
    sessions = await ui_telemetry.list_sessions(limit=limit)
    return {"sessions": sessions}


@app.post("/api/ui-telemetry/reset")
async def reset_ui_telemetry(clear_artifacts: bool = True) -> dict:
    cleared = await ui_telemetry.reset(clear_artifacts=clear_artifacts)
    return {"cleared": cleared}


@app.get("/api/runtime-logs")
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


@app.post("/api/runtime-logs/reset")
async def reset_runtime_logs() -> dict:
    cleared = runtime_logs.clear()
    return {"cleared": cleared}


@app.get("/api/runtime-logs/correlate")
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


def _task_http_error(exc: Exception) -> HTTPException:
    message = str(exc)
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=message)
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=message)
    return HTTPException(status_code=409, detail=message)


def _autonomy_http_error(exc: Exception) -> HTTPException:
    message = str(exc)
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=message)
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=message)
    if "ollama planner required" in message.lower():
        return HTTPException(status_code=503, detail=message)
    return HTTPException(status_code=409, detail=message)


async def _planner_status_payload() -> dict:
    available = await ollama.available()
    diagnostics = ollama.diagnostics()
    mode = planner.mode
    return {
        "mode": mode,
        "source": planner_mode_source,
        "configured_default_mode": settings.autonomy_planner_mode,
        "supported_modes": list(PLANNER_SUPPORTED_MODES),
        "ollama_available": bool(available),
        "ollama_required": mode == PLANNER_MODE_OLLAMA_REQUIRED,
        "last_check_at": diagnostics.get("last_check_at"),
        "last_check_source": diagnostics.get("last_check_source"),
        "last_http_status": diagnostics.get("last_http_status"),
        "last_error": diagnostics.get("last_error"),
    }


async def _ollama_status_payload() -> dict:
    available = await ollama.available()
    payload = ollama.diagnostics()
    payload.update(
        {
            "available": bool(available),
            "url": settings.ollama_url,
            "model": payload.get("active_model") or settings.ollama_model,
            "ollama_model_source": ollama_model_source,
            "autonomy_planner_mode": planner.mode,
            "autonomy_planner_source": planner_mode_source,
            "autonomy_planner_use_ollama": planner.mode != "deterministic",
        }
    )
    return payload


@app.post("/api/tasks")
async def create_task(request: TaskCreateRequest) -> dict:
    task = await tasks.create_task(request.objective)
    return {"task": _dump(task)}


@app.get("/api/tasks")
async def list_tasks(limit: int = 50) -> dict:
    items = await tasks.list_tasks(limit=limit)
    return {"tasks": [_dump(item) for item in items]}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str) -> dict:
    task = await tasks.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    return {"task": _dump(task)}


@app.post("/api/tasks/{task_id}/plan")
async def plan_task(task_id: str, request: TaskPlanRequest) -> dict:
    try:
        task = await tasks.set_plan(task_id, request)
    except Exception as exc:
        raise _task_http_error(exc)
    return {"task": _dump(task)}


@app.post("/api/tasks/{task_id}/run")
async def run_task(task_id: str) -> dict:
    try:
        task = await tasks.run_task(task_id)
    except Exception as exc:
        raise _task_http_error(exc)
    return {"task": _dump(task)}


@app.post("/api/tasks/{task_id}/approve")
async def approve_task(task_id: str, request: TaskApproveRequest) -> dict:
    try:
        task = await tasks.approve(task_id, request)
    except Exception as exc:
        raise _task_http_error(exc)
    return {"task": _dump(task)}


@app.post("/api/tasks/{task_id}/pause")
async def pause_task(task_id: str) -> dict:
    try:
        task = await tasks.pause_task(task_id)
    except Exception as exc:
        raise _task_http_error(exc)
    return {"task": _dump(task)}


@app.post("/api/tasks/{task_id}/resume")
async def resume_task(task_id: str) -> dict:
    try:
        task = await tasks.resume_task(task_id)
    except Exception as exc:
        raise _task_http_error(exc)
    return {"task": _dump(task)}


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict:
    try:
        task = await tasks.cancel_task(task_id)
    except Exception as exc:
        raise _task_http_error(exc)
    return {"task": _dump(task)}


@app.post("/api/autonomy/runs")
async def start_autonomy_run(request: AutonomyStartRequest) -> dict:
    try:
        run = await autonomy.start(request)
    except Exception as exc:
        raise _autonomy_http_error(exc)
    return {"run": _dump(run)}


@app.get("/api/autonomy/planner")
async def get_autonomy_planner() -> dict:
    return await _planner_status_payload()


@app.post("/api/autonomy/planner")
async def set_autonomy_planner(request: AutonomyPlannerModeRequest) -> dict:
    global planner_mode_source
    planner.set_mode(request.mode)
    await db.set_runtime_setting(RUNTIME_SETTING_PLANNER_MODE, planner.mode)
    planner_mode_source = PLANNER_SOURCE_RUNTIME_OVERRIDE
    return await _planner_status_payload()


@app.delete("/api/autonomy/planner")
async def clear_autonomy_planner_override() -> dict:
    global planner_mode_source
    await db.delete_runtime_setting(RUNTIME_SETTING_PLANNER_MODE)
    planner.set_mode(settings.autonomy_planner_mode)
    planner_mode_source = PLANNER_SOURCE_CONFIG_DEFAULT
    return await _planner_status_payload()


@app.get("/api/autonomy/runs")
async def list_autonomy_runs(limit: int = 50) -> dict:
    runs = await autonomy.list_runs(limit=limit)
    return {"runs": [_dump(run) for run in runs]}


@app.get("/api/autonomy/runs/{run_id}")
async def get_autonomy_run(run_id: str) -> dict:
    run = await autonomy.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return {"run": _dump(run)}


@app.post("/api/autonomy/runs/{run_id}/approve")
async def approve_autonomy_run(run_id: str, request: AutonomyApproveRequest) -> dict:
    try:
        run = await autonomy.approve(run_id, request)
    except Exception as exc:
        raise _autonomy_http_error(exc)
    return {"run": _dump(run)}


@app.post("/api/autonomy/runs/{run_id}/cancel")
async def cancel_autonomy_run(run_id: str) -> dict:
    try:
        run = await autonomy.cancel(run_id)
    except Exception as exc:
        raise _autonomy_http_error(exc)
    return {"run": _dump(run)}


async def _execute_readiness_gate(request: ReadinessGateRequest) -> dict:
    started_at = datetime.now(timezone.utc)
    preflight = await tasks.executor_preflight()
    cleanup = {"attempted": False, "cancelled": False, "error": None}

    async def _cleanup_run(run_obj):
        if run_obj is None:
            return None
        if not request.cleanup_on_exit:
            return run_obj
        if run_obj.status in {"completed", "failed", "cancelled"}:
            return run_obj
        cleanup["attempted"] = True
        try:
            cancelled = await autonomy.cancel(run_obj.run_id)
            cleanup["cancelled"] = cancelled.status == "cancelled"
            return cancelled
        except Exception as exc:
            cleanup["error"] = str(exc)
            return run_obj

    def _result(*, ok: bool, reason: str, run_obj, timeline: list[dict]) -> dict:
        finished_at = datetime.now(timezone.utc)
        return {
            "ok": ok,
            "reason": reason,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "elapsed_ms": int((finished_at - started_at).total_seconds() * 1000),
            "preflight": preflight,
            "run": _dump(run_obj) if run_obj is not None else None,
            "timeline": timeline,
            "cleanup": cleanup,
        }

    if request.require_preflight_ok and not bool(preflight.get("ok", False)):
        return _result(ok=False, reason="preflight_failed", run_obj=None, timeline=[])

    start_req = AutonomyStartRequest(
        objective=request.objective,
        max_iterations=request.max_iterations,
        parallel_agents=request.parallel_agents,
        auto_approve_irreversible=False,
    )
    run = await autonomy.start(start_req)
    timeline = [
        {
            "status": run.status,
            "iteration": run.iteration,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    ]
    last_status = run.status

    deadline = started_at.timestamp() + request.timeout_s
    poll_s = request.poll_interval_ms / 1000.0
    terminal = {"completed", "failed", "cancelled"}

    while datetime.now(timezone.utc).timestamp() < deadline:
        current = await autonomy.get_run(run.run_id)
        if current is None:
            return _result(ok=False, reason="run_not_found", run_obj=None, timeline=timeline)

        if current.status != last_status:
            last_status = current.status
            timeline.append(
                {
                    "status": current.status,
                    "iteration": current.iteration,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

        if current.status == "waiting_approval":
            if request.auto_approve_irreversible and current.approval_token:
                current = await autonomy.approve(
                    current.run_id,
                    AutonomyApproveRequest(approval_token=current.approval_token),
                )
                if current.status != last_status:
                    last_status = current.status
                    timeline.append(
                        {
                            "status": current.status,
                            "iteration": current.iteration,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                if current.status in terminal:
                    ok = current.status == "completed"
                    return _result(
                        ok=ok,
                        reason="completed" if ok else f"run_{current.status}",
                        run_obj=current,
                        timeline=timeline,
                    )
            else:
                cleaned = await _cleanup_run(current)
                return _result(
                    ok=False,
                    reason="approval_required",
                    run_obj=cleaned,
                    timeline=timeline,
                )

        if current.status in terminal:
            ok = current.status == "completed"
            return _result(
                ok=ok,
                reason="completed" if ok else f"run_{current.status}",
                run_obj=current,
                timeline=timeline,
            )

        await asyncio.sleep(poll_s)

    timeout_run = await autonomy.get_run(run.run_id)
    cleaned_timeout = await _cleanup_run(timeout_run)
    return _result(
        ok=False,
        reason="timeout",
        run_obj=cleaned_timeout,
        timeline=timeline,
    )


@app.post("/api/readiness/gate")
async def run_readiness_gate(request: ReadinessGateRequest) -> dict:
    return await _execute_readiness_gate(request)


@app.post("/api/readiness/matrix")
async def run_readiness_matrix(request: ReadinessMatrixRequest) -> dict:
    started_at = datetime.now(timezone.utc)
    results = []
    passed = 0
    failed = 0

    for objective in request.objectives:
        objective_text = (objective or "").strip()
        if not objective_text:
            continue
        gate_request = ReadinessGateRequest(
            objective=objective_text,
            timeout_s=request.timeout_s,
            poll_interval_ms=request.poll_interval_ms,
            max_iterations=request.max_iterations,
            parallel_agents=request.parallel_agents,
            auto_approve_irreversible=request.auto_approve_irreversible,
            require_preflight_ok=request.require_preflight_ok,
            cleanup_on_exit=request.cleanup_on_exit,
        )
        report = await _execute_readiness_gate(gate_request)
        ok = bool(report.get("ok", False))
        if ok:
            passed += 1
        else:
            failed += 1
        results.append({"objective": objective_text, "report": report})

        if request.stop_on_failure and not ok:
            break

    finished_at = datetime.now(timezone.utc)
    return {
        "ok": failed == 0 and len(results) > 0,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "elapsed_ms": int((finished_at - started_at).total_seconds() * 1000),
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "results": results,
    }


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


@app.post("/api/events")
async def post_event(event: WindowEvent) -> dict:
    await _handle_event(event, transport="http")
    return {"status": "ok"}


@app.websocket("/ingest")
async def ingest_ws(ws: WebSocket) -> None:
    await ws.accept()
    await collector_status.note_ws_connected(datetime.now(timezone.utc))
    try:
        while True:
            data = await ws.receive_json()
            event = _parse_event(data)
            await _handle_event(event, transport="ws")
            await ws.send_json({"status": "ok"})
    except WebSocketDisconnect:
        await collector_status.note_ws_disconnected(datetime.now(timezone.utc))
        logger.info("Collector WS disconnected")
    except Exception as exc:
        await collector_status.note_ws_disconnected(datetime.now(timezone.utc))
        logger.exception("Collector WS error: %s", exc)


@app.websocket("/ws")
async def ui_ws(ws: WebSocket) -> None:
    await hub.add(ws)
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


@app.get("/api/ollama")
async def ollama_status() -> dict:
    return await _ollama_status_payload()


@app.get("/api/ollama/models")
async def ollama_models() -> dict:
    models = await ollama.list_models()
    payload = await _ollama_status_payload()
    return {
        "models": models,
        "configured_model": payload.get("configured_model"),
        "active_model": payload.get("active_model"),
        "source": payload.get("ollama_model_source"),
        "available": payload.get("available"),
    }


@app.post("/api/ollama/model")
async def set_ollama_model(request: OllamaModelRequest) -> dict:
    global ollama_model_source
    selected = str(request.model or "").strip()
    if not selected:
        raise HTTPException(status_code=422, detail="model is required")
    models = await ollama.list_models()
    if selected not in models:
        raise HTTPException(status_code=404, detail=f"ollama model not installed: {selected}")
    ollama.set_active_model(selected)
    await db.set_runtime_setting(RUNTIME_SETTING_OLLAMA_MODEL, selected)
    ollama_model_source = PLANNER_SOURCE_RUNTIME_OVERRIDE
    return await _ollama_status_payload()


@app.delete("/api/ollama/model")
async def clear_ollama_model_override() -> dict:
    global ollama_model_source
    await db.delete_runtime_setting(RUNTIME_SETTING_OLLAMA_MODEL)
    ollama.reset_active_model()
    ollama_model_source = PLANNER_SOURCE_CONFIG_DEFAULT
    return await _ollama_status_payload()


@app.post("/api/ollama/probe")
async def ollama_probe(request: OllamaProbeRequest) -> dict:
    probe = await ollama.probe(
        prompt=request.prompt,
        timeout_s=request.timeout_s,
        allow_fallback=request.allow_fallback,
    )
    payload = await _ollama_status_payload()
    payload["ok"] = bool(probe.get("ok", False))
    payload["probe"] = probe
    return payload


@app.post("/api/summarize")
async def summarize() -> dict:
    available = await ollama.available()
    if not available:
        raise HTTPException(status_code=503, detail="Ollama not available")

    current, events = await store.snapshot()
    if not current and not events:
        return {"summary": "No events yet."}

    recent = [event for event in events if event.type == "foreground"][
        -settings.summary_event_count :
    ]
    lines = []
    if current:
        lines.append(
            f"Current window: {current.title} | {current.process_exe} (pid {current.pid})"
        )
    if recent:
        lines.append("Recent window changes:")
        for ev in recent:
            lines.append(
                f"- {ev.timestamp.isoformat()} | {ev.title} | {ev.process_exe} (pid {ev.pid})"
            )

    prompt = (
        "Summarize the user's current context in 2-4 sentences. "
        "Focus on what app/task they are in and any obvious transitions.\n\n"
        + "\n".join(lines)
    )

    summary = await ollama.summarize(prompt)
    if summary is None:
        raise HTTPException(status_code=502, detail="Ollama summarize failed")
    return {"summary": summary.strip()}


@app.post("/api/classify")
async def classify(request: ClassifyRequest) -> dict:
    event = WindowEvent(
        type=request.type,
        hwnd="0x0",
        title=request.title,
        process_exe=request.process_exe,
        pid=request.pid,
        timestamp=datetime.now(timezone.utc),
        source="api",
        uia=request.uia,
    )
    result = await classifier.classify(event, use_ollama=request.use_ollama)
    return {"category": result.category, "source": result.source}
