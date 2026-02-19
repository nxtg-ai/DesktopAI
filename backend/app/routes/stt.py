"""STT transcription routes."""

from __future__ import annotations

from fastapi import APIRouter, UploadFile

from ..config import settings
from ..deps import stt_engine

router = APIRouter()

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/api/stt")
async def post_stt(file: UploadFile):
    from fastapi.responses import JSONResponse

    if stt_engine is None or not stt_engine.available:
        return JSONResponse(
            status_code=503,
            content={"error": "STT engine not available"},
        )

    audio_bytes = await file.read()
    if not audio_bytes:
        return JSONResponse(
            status_code=400,
            content={"error": "empty audio file"},
        )
    if len(audio_bytes) > _MAX_UPLOAD_BYTES:
        return JSONResponse(
            status_code=413,
            content={"error": f"file too large (max {_MAX_UPLOAD_BYTES // (1024*1024)} MB)"},
        )

    text = await stt_engine.transcribe(audio_bytes)
    if text is None:
        return JSONResponse(
            status_code=500,
            content={"error": "transcription failed"},
        )

    return {"text": text}


@router.get("/api/stt/status")
async def get_stt_status() -> dict:
    if stt_engine is None or not stt_engine.available:
        return {
            "available": False,
            "model_size": settings.stt_model_size,
            "device": settings.stt_device,
        }
    return {
        "available": True,
        "model_size": settings.stt_model_size,
        "device": settings.stt_device,
        "compute_type": settings.stt_compute_type,
        "language": settings.stt_language,
    }
