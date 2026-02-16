"""Tests for TTS routes."""

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from app.main import app
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def mock_engine_available():
    """Mock a TTS engine that is available and can synthesize."""
    engine = MagicMock()
    type(engine).available = PropertyMock(return_value=True)
    engine.list_voices.return_value = ["af_bella", "af_sarah", "am_adam"]
    engine.synthesize = AsyncMock(return_value=b"RIFF" + b"\x00" * 40)
    with patch("app.routes.tts.tts_engine", engine):
        yield engine


@pytest.fixture
def mock_engine_unavailable():
    """Mock TTS engine as None (unavailable)."""
    with patch("app.routes.tts.tts_engine", None):
        yield


@pytest.mark.asyncio
async def test_post_tts_returns_wav_audio(mock_engine_available):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/tts", json={"text": "Hello world"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    mock_engine_available.synthesize.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_tts_empty_text_400(mock_engine_available):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/tts", json={"text": "   "})
    assert resp.status_code == 400
    assert "text is required" in resp.json()["error"]


@pytest.mark.asyncio
async def test_post_tts_engine_unavailable_503(mock_engine_unavailable):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/tts", json={"text": "Hello"})
    assert resp.status_code == 503
    assert "not available" in resp.json()["error"]


@pytest.mark.asyncio
async def test_post_tts_custom_voice(mock_engine_available):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/tts", json={"text": "Hi", "voice": "bf_emma"})
    assert resp.status_code == 200
    call_kwargs = mock_engine_available.synthesize.call_args
    assert call_kwargs.kwargs["voice"] == "bf_emma"


@pytest.mark.asyncio
async def test_post_tts_custom_speed(mock_engine_available):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/tts", json={"text": "Hi", "speed": 1.5})
    assert resp.status_code == 200
    call_kwargs = mock_engine_available.synthesize.call_args
    assert call_kwargs.kwargs["speed"] == 1.5


@pytest.mark.asyncio
async def test_post_tts_synthesis_failure_500(mock_engine_available):
    mock_engine_available.synthesize = AsyncMock(return_value=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/tts", json={"text": "Hello"})
    assert resp.status_code == 500
    assert "synthesis failed" in resp.json()["error"]


@pytest.mark.asyncio
async def test_get_voices_returns_list(mock_engine_available):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/tts/voices")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert "af_bella" in data["voices"]
    assert "default" in data


@pytest.mark.asyncio
async def test_get_voices_engine_unavailable(mock_engine_unavailable):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/tts/voices")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert data["voices"] == []


@pytest.mark.asyncio
async def test_readiness_includes_tts():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/readiness/status")
    data = resp.json()
    check_names = [c["name"] for c in data["checks"]]
    assert "tts_available" in check_names
    assert "tts_available" in data["summary"]
    assert "tts_engine" in data["summary"]
