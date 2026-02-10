"""DesktopAI Backend — FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .auth import TokenAuthMiddleware
from .config import settings
from .runtime_logs import RuntimeLogHandler

# Import deps to initialize singletons (db, store, ollama, etc.)
from . import deps as _deps

# Import route modules
from .routes.state import router as state_router
from .routes.tasks import router as tasks_router
from .routes.autonomy import router as autonomy_router
from .routes.ollama_routes import router as ollama_router
from .routes.telemetry import router as telemetry_router
from .routes.readiness import router as readiness_router
from .routes.agent import router as agent_router
from .routes.ingest import router as ingest_router
from .routes.ws_route import router as ws_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("desktopai.backend")

runtime_log_handler = RuntimeLogHandler(_deps.runtime_logs)
root_logger = logging.getLogger()
if not any(isinstance(handler, RuntimeLogHandler) for handler in root_logger.handlers):
    root_logger.addHandler(runtime_log_handler)


async def _restore_runtime_planner_mode() -> None:
    try:
        saved_mode = await _deps.db.get_runtime_setting(_deps.RUNTIME_SETTING_PLANNER_MODE)
    except Exception as exc:
        logger.warning("Failed to load runtime planner mode: %s", exc)
        _deps.planner_mode_source = _deps.PLANNER_SOURCE_CONFIG_DEFAULT
        return
    if not saved_mode:
        _deps.planner_mode_source = _deps.PLANNER_SOURCE_CONFIG_DEFAULT
        return
    try:
        _deps.planner.set_mode(saved_mode)
        _deps.planner_mode_source = _deps.PLANNER_SOURCE_RUNTIME_OVERRIDE
        logger.info("Restored runtime planner mode from DB: %s", _deps.planner.mode)
    except Exception as exc:
        _deps.planner_mode_source = _deps.PLANNER_SOURCE_CONFIG_DEFAULT
        logger.warning("Ignoring invalid persisted planner mode %r: %s", saved_mode, exc)


async def _restore_runtime_ollama_model() -> None:
    try:
        saved_model = await _deps.db.get_runtime_setting(_deps.RUNTIME_SETTING_OLLAMA_MODEL)
    except Exception as exc:
        logger.warning("Failed to load runtime Ollama model override: %s", exc)
        _deps.ollama_model_source = _deps.PLANNER_SOURCE_CONFIG_DEFAULT
        _deps.ollama.reset_active_model()
        return

    if not saved_model:
        _deps.ollama_model_source = _deps.PLANNER_SOURCE_CONFIG_DEFAULT
        _deps.ollama.reset_active_model()
        return

    try:
        _deps.ollama.set_active_model(saved_model)
        _deps.ollama_model_source = _deps.PLANNER_SOURCE_RUNTIME_OVERRIDE
        logger.info("Restored runtime Ollama model override from DB: %s", _deps.ollama.model)
    except Exception as exc:
        logger.warning("Ignoring invalid persisted Ollama model override %r: %s", saved_model, exc)
        _deps.ollama_model_source = _deps.PLANNER_SOURCE_CONFIG_DEFAULT
        _deps.ollama.reset_active_model()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    current, events, idle, idle_since = await _deps.db.load_snapshot(settings.event_log_max)
    await _deps.store.hydrate(events, current, idle, idle_since)
    task_records = await _deps.db.list_task_records(limit=500)
    await _deps.tasks.hydrate_tasks(task_records)
    runs = await _deps.db.list_autonomy_runs(limit=200)
    await _deps.autonomy.hydrate_runs(runs)
    await _restore_runtime_ollama_model()
    await _restore_runtime_planner_mode()
    try:
        yield
    finally:
        await _deps.autonomy.shutdown()
        drained = await _deps.tasks.drain_updates(timeout_s=2.0)
        if not drained:
            logger.warning("Timed out while draining pending task persistence updates.")


app = FastAPI(title="DesktopAI Backend", version="0.1.0", lifespan=_lifespan)

if settings.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )

app.add_middleware(TokenAuthMiddleware)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

# Include all route modules
app.include_router(state_router)
app.include_router(tasks_router)
app.include_router(autonomy_router)
app.include_router(ollama_router)
app.include_router(telemetry_router)
app.include_router(readiness_router)
app.include_router(agent_router)
app.include_router(ingest_router)
app.include_router(ws_router)


@app.get("/", response_class=HTMLResponse)
async def root() -> HTMLResponse:
    index_path = WEB_DIR / "index.html"
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


# Re-export singletons and helpers from deps for backward compatibility with tests
# and any code that imports from app.main directly.
store = _deps.store
ollama = _deps.ollama
db = _deps.db
autonomy = _deps.autonomy
tasks = _deps.tasks
planner = _deps.planner
runtime_logs = _deps.runtime_logs
bridge = _deps.bridge
hub = _deps.hub
ui_telemetry = _deps.ui_telemetry
collector_status = _deps.collector_status
trajectory_store = _deps.trajectory_store
classifier = _deps.classifier
action_executor = _deps.action_executor
