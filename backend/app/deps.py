"""Shared singletons and helpers used by route modules."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi.encoders import jsonable_encoder

from .action_executor import build_action_executor
from .autonomy import AutonomousRunner, VisionAutonomousRunner
from .autonomy_promoter import AutonomyPromoter
from .bridge import CommandBridge
from .chat_memory import ChatMemoryStore
from .classifier import ActivityClassifier
from .collector_status import CollectorStatusStore
from .config import settings
from .db import EventDatabase
from .llm_provider import LLMProvider, OpenAIProvider
from .memory import TrajectoryStore
from .notification_engine import NotificationEngine
from .notifications import NotificationStore
from .ollama import OllamaClient
from .orchestrator import TaskOrchestrator
from .personality_adapter import PersonalityAdapter
from .planner import (
    PLANNER_MODE_OLLAMA_REQUIRED,
    PLANNER_SUPPORTED_MODES,
    DeterministicAutonomyPlanner,
    OllamaAutonomyPlanner,
)
from .runtime_logs import RuntimeLogStore
from .schemas import (
    WindowEvent,
)
from .state import StateStore
from .ui_telemetry import UiTelemetryStore
from .ws import WebSocketHub

load_dotenv()

logger = logging.getLogger("desktopai.backend")

# ── Runtime settings state ────────────────────────────────────────────────

RUNTIME_SETTING_PLANNER_MODE = "autonomy_planner_mode"
RUNTIME_SETTING_OLLAMA_MODEL = "ollama_model"
PLANNER_SOURCE_CONFIG_DEFAULT = "config_default"
PLANNER_SOURCE_RUNTIME_OVERRIDE = "runtime_override"
planner_mode_source: str = PLANNER_SOURCE_CONFIG_DEFAULT
ollama_model_source: str = PLANNER_SOURCE_CONFIG_DEFAULT

# ── Singletons ────────────────────────────────────────────────────────────

store = StateStore(max_events=settings.event_log_max)
ui_telemetry = UiTelemetryStore(
    artifact_dir=settings.ui_telemetry_artifact_dir,
    max_events=settings.ui_telemetry_max_events,
)
hub = WebSocketHub(max_connections=settings.ws_max_connections)
ollama = OllamaClient(settings.ollama_url, settings.ollama_model)

# LLM provider: defaults to Ollama, can be swapped to OpenAI-compatible
llm: LLMProvider
if settings.llm_provider == "openai" and settings.openai_api_key:
    llm = OpenAIProvider(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        base_url=settings.openai_base_url,
    )
else:
    llm = ollama

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
bridge = CommandBridge(default_timeout_s=settings.action_executor_bridge_timeout_s)
trajectory_store = TrajectoryStore(
    path=settings.db_path.replace(".db", "-trajectories.db"),
)
chat_memory = ChatMemoryStore(
    path=settings.db_path.replace(".db", "-chat.db"),
    max_conversations=settings.chat_memory_max_conversations,
    max_messages_per_conversation=settings.chat_memory_max_messages,
)
notification_store = NotificationStore(
    path=settings.db_path.replace(".db", "-notifications.db"),
    max_notifications=settings.notification_max_count,
)
notification_engine = NotificationEngine(
    store=notification_store,
    hub=hub,
    enabled=settings.notifications_enabled,
    idle_threshold_s=settings.notification_idle_threshold_s,
)
personality_adapter = PersonalityAdapter()
autonomy_promoter = AutonomyPromoter()
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
    state_store=store,
    trajectory_store=trajectory_store,
    trajectory_max_chars=settings.trajectory_context_max_chars,
    trajectory_max_results=settings.trajectory_context_max_results,
)
action_executor = build_action_executor(
    mode=settings.action_executor_mode,
    powershell_executable=settings.action_executor_powershell,
    timeout_s=settings.action_executor_timeout_s,
    default_compose_text=settings.action_executor_default_compose_text,
    state_store=store,
    ollama=ollama,
    bridge=bridge,
)
runtime_logs = RuntimeLogStore(max_entries=settings.runtime_log_max_entries)


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
    state_store=store,
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
vision_runner = VisionAutonomousRunner(
    on_run_update=_publish_autonomy_update,
    trajectory_store=trajectory_store,
)


# ── Helpers ───────────────────────────────────────────────────────────────

def _dump(model):
    return jsonable_encoder(model)


def _parse_event(data):
    return WindowEvent.model_validate(data)


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
