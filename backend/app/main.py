from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .ollama import OllamaClient
from .schemas import StateResponse, WindowEvent
from .state import StateStore
from .ws import WebSocketHub

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("desktopai.backend")

def _dump(model):
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _parse_event(data):
    if hasattr(WindowEvent, "model_validate"):
        return WindowEvent.model_validate(data)
    return WindowEvent.parse_obj(data)

app = FastAPI(title="DesktopAI Backend", version="0.1.0")

store = StateStore(max_events=settings.event_log_max)
hub = WebSocketHub()
ollama = OllamaClient(settings.ollama_url, settings.ollama_model)

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


@app.get("/api/state", response_model=StateResponse)
async def get_state() -> StateResponse:
    current = await store.current()
    count = await store.event_count()
    return StateResponse(current=current, event_count=count)


@app.get("/api/events")
async def get_events(limit: Optional[int] = None) -> dict:
    if limit is None:
        limit = settings.event_limit_default
    events = await store.events(limit=limit)
    return {"events": [_dump(event) for event in events]}


async def _handle_event(event: WindowEvent) -> None:
    await store.record(event)
    count = await store.event_count()
    await hub.broadcast_json({"type": "event", "event": _dump(event)})
    await hub.broadcast_json(
        {"type": "state", "state": {"current": _dump(event), "event_count": count}}
    )


@app.post("/api/events")
async def post_event(event: WindowEvent) -> dict:
    await _handle_event(event)
    return {"status": "ok"}


@app.websocket("/ingest")
async def ingest_ws(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            data = await ws.receive_json()
            event = _parse_event(data)
            await _handle_event(event)
            await ws.send_json({"status": "ok"})
    except WebSocketDisconnect:
        logger.info("Collector WS disconnected")
    except Exception as exc:
        logger.exception("Collector WS error: %s", exc)


@app.websocket("/ws")
async def ui_ws(ws: WebSocket) -> None:
    await hub.add(ws)
    current, events = await store.snapshot()
    await ws.send_json(
        {
            "type": "snapshot",
            "state": {"current": _dump(current) if current else None, "event_count": len(events)},
            "events": [_dump(event) for event in events[-settings.event_limit_default :]],
        }
    )
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await hub.remove(ws)


@app.get("/api/ollama")
async def ollama_status() -> dict:
    available = await ollama.available()
    return {"available": available, "url": settings.ollama_url, "model": settings.ollama_model}


@app.post("/api/summarize")
async def summarize() -> dict:
    available = await ollama.available()
    if not available:
        raise HTTPException(status_code=503, detail="Ollama not available")

    current, events = await store.snapshot()
    if not current and not events:
        return {"summary": "No events yet."}

    recent = events[-settings.summary_event_count :]
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
