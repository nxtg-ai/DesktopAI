"""Tests for autonomy run management routes."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")
os.environ.setdefault("CLASSIFIER_USE_OLLAMA", "0")
os.environ.setdefault("CLASSIFIER_DEFAULT", "docs")
os.environ.setdefault("UI_TELEMETRY_ARTIFACT_DIR", "/tmp/desktopai-ui-telemetry-test")

import pytest
from app.main import app
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_promotion_status():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/autonomy/promotion")
    assert resp.status_code == 200
    data = resp.json()
    assert "recommended_level" in data
    assert "current_level" in data
    assert "auto_promote_enabled" in data


@pytest.mark.asyncio
async def test_list_runs():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/autonomy/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data
    assert isinstance(data["runs"], list)


@pytest.mark.asyncio
async def test_get_nonexistent_run():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/autonomy/runs/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_start_run():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/autonomy/runs", json={
            "objective": "Test objective",
            "max_iterations": 1,
        })
    assert resp.status_code == 200
    data = resp.json()
    assert "run" in data
    assert "run_id" in data["run"]


@pytest.mark.asyncio
async def test_start_and_get_run():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        start_resp = await ac.post("/api/autonomy/runs", json={
            "objective": "Test get",
            "max_iterations": 1,
        })
        run_id = start_resp.json()["run"]["run_id"]
        get_resp = await ac.get(f"/api/autonomy/runs/{run_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["run"]["run_id"] == run_id


@pytest.mark.asyncio
async def test_cancel_nonexistent_run():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/autonomy/runs/nonexistent-id/cancel")
    # Returns 404 (KeyError mapped to 404 by _autonomy_http_error)
    assert resp.status_code in {404, 409}


@pytest.mark.asyncio
async def test_cancel_all_runs():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/autonomy/cancel-all")
    assert resp.status_code == 200
    data = resp.json()
    assert "cancelled" in data
    assert isinstance(data["cancelled"], int)


@pytest.mark.asyncio
async def test_planner_get():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/autonomy/planner")
    assert resp.status_code == 200
    data = resp.json()
    assert "mode" in data
    assert "source" in data


@pytest.mark.asyncio
async def test_planner_set_and_clear():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Set to deterministic
        set_resp = await ac.post("/api/autonomy/planner", json={"mode": "deterministic"})
        assert set_resp.status_code == 200
        assert set_resp.json()["mode"] == "deterministic"

        # Clear override
        clear_resp = await ac.delete("/api/autonomy/planner")
        assert clear_resp.status_code == 200
