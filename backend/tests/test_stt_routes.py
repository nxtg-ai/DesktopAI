"""Tests for STT routes."""

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from app.main import app
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def mock_engine_available():
    """Mock an STT engine that is available and can transcribe."""
    engine = MagicMock()
    type(engine).available = PropertyMock(return_value=True)
    engine.transcribe = AsyncMock(return_value="Hello world")
    with patch("app.routes.stt.stt_engine", engine):
        yield engine


@pytest.fixture
def mock_engine_unavailable():
    """Mock STT engine as None (unavailable)."""
    with patch("app.routes.stt.stt_engine", None):
        yield


@pytest.mark.asyncio
async def test_post_stt_returns_text(mock_engine_available):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/stt",
            files={"file": ("test.wav", b"RIFF" + b"\x00" * 40, "audio/wav")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "Hello world"
    mock_engine_available.transcribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_stt_empty_file_400(mock_engine_available):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/stt",
            files={"file": ("empty.wav", b"", "audio/wav")},
        )
    assert resp.status_code == 400
    assert "empty" in resp.json()["error"]


@pytest.mark.asyncio
async def test_post_stt_engine_unavailable_503(mock_engine_unavailable):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/stt",
            files={"file": ("test.wav", b"RIFF" + b"\x00" * 40, "audio/wav")},
        )
    assert resp.status_code == 503
    assert "not available" in resp.json()["error"]


@pytest.mark.asyncio
async def test_post_stt_transcription_failure_500(mock_engine_available):
    mock_engine_available.transcribe = AsyncMock(return_value=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/stt",
            files={"file": ("test.wav", b"RIFF" + b"\x00" * 40, "audio/wav")},
        )
    assert resp.status_code == 500
    assert "transcription failed" in resp.json()["error"]


@pytest.mark.asyncio
async def test_get_stt_status_available(mock_engine_available):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/stt/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert "model_size" in data
    assert "device" in data


@pytest.mark.asyncio
async def test_get_stt_status_unavailable(mock_engine_unavailable):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/stt/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False


@pytest.mark.asyncio
async def test_post_stt_oversized_file_413(mock_engine_available):
    big_payload = b"RIFF" + b"\x00" * (10 * 1024 * 1024 + 1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/stt",
            files={"file": ("big.wav", big_payload, "audio/wav")},
        )
    assert resp.status_code == 413
    assert "too large" in resp.json()["error"]


@pytest.mark.asyncio
async def test_get_stt_status_always_returns_all_fields(mock_engine_unavailable):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/stt/status")
    data = resp.json()
    assert data["available"] is False
    assert "model_size" in data
    assert "device" in data
    assert "compute_type" in data
    assert "language" in data


@pytest.mark.asyncio
async def test_readiness_includes_stt():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/readiness/status")
    data = resp.json()
    check_names = [c["name"] for c in data["checks"]]
    assert "stt_available" in check_names
    assert "stt_available" in data["summary"]
    assert "stt_engine" in data["summary"]
