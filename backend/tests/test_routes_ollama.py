"""Tests for Ollama model management and probe routes."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")
os.environ.setdefault("CLASSIFIER_USE_OLLAMA", "0")
os.environ.setdefault("CLASSIFIER_DEFAULT", "docs")
os.environ.setdefault("UI_TELEMETRY_ARTIFACT_DIR", "/tmp/desktopai-ui-telemetry-test")

from unittest.mock import AsyncMock, patch

import pytest
from app.main import app
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_ollama_status():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/ollama")
    assert resp.status_code == 200
    data = resp.json()
    assert "available" in data
    assert "url" in data


@pytest.mark.asyncio
async def test_ollama_models():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/ollama/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "models" in data


@pytest.mark.asyncio
async def test_set_ollama_model_empty():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/ollama/model", json={"model": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_set_ollama_model_not_installed():
    with patch("app.deps.ollama.list_models", new_callable=AsyncMock, return_value=["llama3"]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/ollama/model", json={"model": "nonexistent-model"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_clear_ollama_model_override():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.delete("/api/ollama/model")
    assert resp.status_code == 200
    data = resp.json()
    assert "available" in data


@pytest.mark.asyncio
async def test_classify_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/classify",
            json={"title": "VS Code", "process_exe": "Code.exe"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "category" in data
    assert "source" in data


@pytest.mark.asyncio
async def test_summarize_no_ollama():
    with patch("app.deps.ollama.available", new_callable=AsyncMock, return_value=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/summarize")
    assert resp.status_code == 503
