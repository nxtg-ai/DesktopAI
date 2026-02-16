"""TTS synthesis routes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from ..config import settings
from ..deps import tts_engine

router = APIRouter()


class TtsRequest(BaseModel):
    text: str
    voice: str = ""
    speed: float = 1.0


@router.post("/api/tts")
async def post_tts(req: TtsRequest) -> Response:
    if not req.text.strip():
        return Response(
            content='{"error":"text is required"}',
            status_code=400,
            media_type="application/json",
        )
    if tts_engine is None or not tts_engine.available:
        return Response(
            content='{"error":"TTS engine not available"}',
            status_code=503,
            media_type="application/json",
        )
    voice = req.voice or settings.tts_default_voice
    speed = req.speed if req.speed > 0 else settings.tts_default_speed
    wav = await tts_engine.synthesize(req.text, voice=voice, speed=speed)
    if wav is None:
        return Response(
            content='{"error":"synthesis failed"}',
            status_code=500,
            media_type="application/json",
        )
    return Response(content=wav, media_type="audio/wav")


@router.get("/api/tts/voices")
async def get_voices() -> dict:
    if tts_engine is None or not tts_engine.available:
        return {
            "voices": [],
            "default": settings.tts_default_voice,
            "available": False,
        }
    return {
        "voices": tts_engine.list_voices(),
        "default": settings.tts_default_voice,
        "available": True,
    }
