"""Tests for the desktop automation recipes system."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")

from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from app.main import app, ollama, store
from app.recipes import BUILTIN_RECIPES, match_recipe_by_keywords, match_recipes
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def _reset_store():
    await store.hydrate([], None, False, None)
    yield
    await store.hydrate([], None, False, None)


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@dataclass
class FakeContext:
    process_exe: str = ""
    window_title: str = ""


def test_match_recipes_outlook():
    ctx = FakeContext(process_exe="OUTLOOK.EXE", window_title="Inbox - Outlook")
    matched = match_recipes(ctx)
    ids = {r.recipe_id for r in matched}
    assert "reply_to_email" in ids
    assert "schedule_focus" in ids  # available everywhere


def test_match_recipes_no_context():
    matched = match_recipes(None)
    assert matched == []


def test_match_recipe_by_keywords():
    recipe = match_recipe_by_keywords("please draft reply to this email")
    assert recipe is not None
    assert recipe.recipe_id == "reply_to_email"


def test_match_recipe_uat_phrases():
    """UAT phrases that must all match reply_to_email."""
    for phrase in [
        "draft a reply to this email",
        "reply to this email",
        "Draft email reply",
    ]:
        recipe = match_recipe_by_keywords(phrase)
        assert recipe is not None, f"Failed to match: {phrase!r}"
        assert recipe.recipe_id == "reply_to_email"


def test_no_keyword_match():
    recipe = match_recipe_by_keywords("what is the weather today?")
    assert recipe is None


def test_builtin_recipes_valid():
    assert len(BUILTIN_RECIPES) >= 3
    for recipe in BUILTIN_RECIPES:
        assert recipe.recipe_id
        assert recipe.name
        assert recipe.steps
        assert recipe.context_patterns
        assert recipe.keywords


@pytest.mark.anyio
async def test_recipe_endpoint_list(client):
    resp = await client.get("/api/recipes")
    assert resp.status_code == 200
    data = resp.json()
    assert "recipes" in data
    assert "total_available" in data


@pytest.mark.anyio
async def test_recipe_endpoint_run(client):
    resp = await client.post("/api/recipes/reply_to_email/run")
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert data["recipe"]["recipe_id"] == "reply_to_email"


@pytest.mark.anyio
async def test_recipe_execution_creates_run(client):
    """Running a recipe via chat keyword match triggers a run."""
    from app.schemas import WindowEvent

    event = WindowEvent(
        type="foreground", hwnd="0x1", title="Inbox - Outlook",
        process_exe="OUTLOOK.EXE", pid=1, timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    await store.record(event)

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post(
            "/api/chat", json={"message": "please draft reply to this email"}
        )
    data = resp.json()
    assert data["action_triggered"] is True
    assert data["run_id"] is not None
