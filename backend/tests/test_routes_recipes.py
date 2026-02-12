"""Tests for recipe routes."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")
os.environ.setdefault("CLASSIFIER_USE_OLLAMA", "0")
os.environ.setdefault("CLASSIFIER_DEFAULT", "docs")
os.environ.setdefault("UI_TELEMETRY_ARTIFACT_DIR", "/tmp/desktopai-ui-telemetry-test")

import pytest
from app.main import app
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_list_recipes_returns_recipes():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/recipes")
    assert resp.status_code == 200
    data = resp.json()
    assert "recipes" in data
    assert "total_available" in data
    assert isinstance(data["recipes"], list)
    assert data["total_available"] >= 3


@pytest.mark.asyncio
async def test_list_recipes_structure():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/recipes")
    data = resp.json()
    # Without desktop context, all recipes are returned (no context filtering)
    for recipe in data["recipes"]:
        assert "recipe_id" in recipe
        assert "name" in recipe
        assert "description" in recipe
        assert "steps" in recipe


@pytest.mark.asyncio
async def test_run_nonexistent_recipe():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/recipes/nonexistent-recipe/run")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_run_valid_recipe():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/recipes/reply_to_email/run")
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert "recipe" in data
    assert data["recipe"]["recipe_id"] == "reply_to_email"
