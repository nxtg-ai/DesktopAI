"""Tests for readiness, executor, and selftest routes."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")
os.environ.setdefault("CLASSIFIER_USE_OLLAMA", "0")
os.environ.setdefault("CLASSIFIER_DEFAULT", "docs")
os.environ.setdefault("UI_TELEMETRY_ARTIFACT_DIR", "/tmp/desktopai-ui-telemetry-test")

import pytest
from app.main import app
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_readiness_status_returns_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/readiness/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "ok" in data
    assert "checks" in data
    assert "summary" in data
    assert "generated_at" in data


@pytest.mark.asyncio
async def test_readiness_checks_structure():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/readiness/status")
    checks = resp.json()["checks"]
    assert isinstance(checks, list)
    for check in checks:
        assert "name" in check
        assert "ok" in check
        assert "required" in check


@pytest.mark.asyncio
async def test_executor_status():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/executor")
    assert resp.status_code == 200
    data = resp.json()
    assert "mode" in data


@pytest.mark.asyncio
async def test_executor_preflight():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/executor/preflight")
    assert resp.status_code == 200
    data = resp.json()
    assert "ok" in data
    assert "mode" in data
    assert "checks" in data


@pytest.mark.asyncio
async def test_readiness_includes_detection_check():
    """Readiness checks include detection_model_available entry."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/readiness/status")
    checks = resp.json()["checks"]
    names = [c["name"] for c in checks]
    assert "detection_model_available" in names
    det_check = next(c for c in checks if c["name"] == "detection_model_available")
    assert det_check["required"] is False


@pytest.mark.asyncio
async def test_readiness_summary_has_vision_mode():
    """Readiness summary includes vision_mode and detection fields."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/readiness/status")
    summary = resp.json()["summary"]
    assert "vision_mode" in summary
    assert "detection_model_available" in summary
    assert "detection_model_path" in summary


@pytest.mark.asyncio
async def test_selftest():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/selftest")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
