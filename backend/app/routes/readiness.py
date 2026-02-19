"""Readiness, executor, and selftest routes."""

import os
from datetime import datetime, timezone

from fastapi import APIRouter

import app.deps as _deps

from ..config import settings
from ..deps import (
    PLANNER_MODE_OLLAMA_REQUIRED,
    _ollama_unavailable_detail,
    autonomy,
    bridge,
    collector_status,
    ollama,
    planner,
    runtime_logs,
    stt_engine,
    tasks,
    tts_engine,
    ui_telemetry,
)
from ..selftest import run_selftest

router = APIRouter()


@router.get("/api/executor")
async def get_executor_status() -> dict:
    """Return current action executor mode and availability."""
    return tasks.executor_status()


@router.get("/api/executor/preflight")
async def get_executor_preflight() -> dict:
    """Run executor preflight checks and return results."""
    return await tasks.executor_preflight()


@router.get("/api/readiness/status")
async def get_readiness_status() -> dict:
    """Return comprehensive system readiness with all subsystem checks."""
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
        {
            "name": "tts_available",
            "ok": tts_engine is not None and tts_engine.available,
            "required": False,
            "detail": "TTS engine (kokoro-82m) loaded."
            if tts_engine is not None and tts_engine.available
            else "TTS engine unavailable — browser fallback active.",
        },
        {
            "name": "stt_available",
            "ok": stt_engine is not None and stt_engine.available,
            "required": False,
            "detail": f"STT engine (faster-whisper {settings.stt_model_size}) loaded."
            if stt_engine is not None and stt_engine.available
            else "STT engine unavailable — browser fallback active.",
        },
        {
            "name": "detection_model_available",
            "ok": os.path.isfile(settings.detection_model_path),
            "required": False,
            "detail": f"Detection model loaded from {settings.detection_model_path}."
            if os.path.isfile(settings.detection_model_path)
            else f"Detection model not found at {settings.detection_model_path} — VLM fallback active.",
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
            "autonomy_planner_source": _deps.planner_mode_source,
            "collector_connected": collector_connected,
            "collector_total_events": int(collector.get("total_events", 0) or 0),
            "latest_autonomy_run_id": latest_run.run_id if latest_run else None,
            "latest_autonomy_status": latest_run.status if latest_run else None,
            "latest_telemetry_session_id": latest_session.get("session_id") if latest_session else None,
            "runtime_log_entries": runtime_log_entries,
            "ollama_available": bool(ollama_available),
            "ollama_model_source": _deps.ollama_model_source,
            "ollama_configured_model": ollama_diagnostics.get("configured_model"),
            "ollama_active_model": ollama_diagnostics.get("active_model"),
            "ollama_last_check_at": ollama_diagnostics.get("last_check_at"),
            "ollama_last_check_source": ollama_diagnostics.get("last_check_source"),
            "ollama_last_http_status": ollama_diagnostics.get("last_http_status"),
            "ollama_last_error": ollama_diagnostics.get("last_error"),
            "ollama_consecutive_failures": ollama_diagnostics.get("consecutive_failures", 0),
            "ollama_circuit_open": ollama_diagnostics.get("circuit_open", False),
            "ollama_fallback_model": ollama_diagnostics.get("fallback_model", ""),
            "ollama_vision_model": settings.ollama_vision_model,
            "bridge_connected": bridge.connected,
            "tts_available": tts_engine is not None and tts_engine.available,
            "tts_engine": "kokoro-82m" if tts_engine is not None and tts_engine.available else "unavailable",
            "stt_available": stt_engine is not None and stt_engine.available,
            "stt_engine": f"faster-whisper-{settings.stt_model_size}" if stt_engine is not None and stt_engine.available else "unavailable",
            "detection_model_available": os.path.isfile(settings.detection_model_path),
            "detection_model_path": settings.detection_model_path,
            "vision_mode": settings.vision_mode,
            "vision_agent_enabled": settings.vision_agent_enabled,
            "required_total": required_total,
            "required_passed": required_passed,
            "required_failed": required_failed,
            "warning_count": warning_count,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/selftest")
async def selftest() -> dict:
    """Run internal self-test diagnostics."""
    return run_selftest()
