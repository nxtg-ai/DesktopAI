"""Ollama model management and probe routes."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..deps import (
    _dump,
    _ollama_status_payload,
    classifier,
    db,
    ollama,
    store,
    PLANNER_SOURCE_CONFIG_DEFAULT,
    PLANNER_SOURCE_RUNTIME_OVERRIDE,
    RUNTIME_SETTING_OLLAMA_MODEL,
)
from ..schemas import (
    ClassifyRequest,
    OllamaModelRequest,
    OllamaProbeRequest,
    WindowEvent,
)
import app.deps as _deps

router = APIRouter()


@router.get("/api/ollama")
async def ollama_status() -> dict:
    return await _ollama_status_payload()


@router.get("/api/ollama/models")
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


@router.post("/api/ollama/model")
async def set_ollama_model(request: OllamaModelRequest) -> dict:
    selected = str(request.model or "").strip()
    if not selected:
        raise HTTPException(status_code=422, detail="model is required")
    models = await ollama.list_models()
    if selected not in models:
        raise HTTPException(status_code=404, detail=f"ollama model not installed: {selected}")
    ollama.set_active_model(selected)
    await db.set_runtime_setting(RUNTIME_SETTING_OLLAMA_MODEL, selected)
    _deps.ollama_model_source = PLANNER_SOURCE_RUNTIME_OVERRIDE
    return await _ollama_status_payload()


@router.delete("/api/ollama/model")
async def clear_ollama_model_override() -> dict:
    await db.delete_runtime_setting(RUNTIME_SETTING_OLLAMA_MODEL)
    ollama.reset_active_model()
    _deps.ollama_model_source = PLANNER_SOURCE_CONFIG_DEFAULT
    return await _ollama_status_payload()


@router.post("/api/ollama/probe")
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


@router.post("/api/summarize")
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


@router.post("/api/classify")
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
