"""Tests for task orchestration routes."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")
os.environ.setdefault("CLASSIFIER_USE_OLLAMA", "0")
os.environ.setdefault("CLASSIFIER_DEFAULT", "docs")
os.environ.setdefault("UI_TELEMETRY_ARTIFACT_DIR", "/tmp/desktopai-ui-telemetry-test")

import pytest
from app.main import app
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_list_tasks_empty():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data
    assert isinstance(data["tasks"], list)


@pytest.mark.asyncio
async def test_create_task():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/tasks", json={"objective": "Test task"})
    assert resp.status_code == 200
    data = resp.json()
    assert "task" in data
    assert data["task"]["objective"] == "Test task"
    assert data["task"]["status"] == "created"


@pytest.mark.asyncio
async def test_get_task_not_found():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/tasks/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_and_get_task():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        create_resp = await ac.post("/api/tasks", json={"objective": "Retrieve me"})
        task_id = create_resp.json()["task"]["task_id"]
        get_resp = await ac.get(f"/api/tasks/{task_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["task"]["task_id"] == task_id


@pytest.mark.asyncio
async def test_create_task_missing_objective():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/tasks", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_cancel_nonexistent_task():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/tasks/missing-id/cancel")
    assert resp.status_code in {404, 409}
