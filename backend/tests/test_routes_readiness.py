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
async def test_selftest():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/selftest")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
