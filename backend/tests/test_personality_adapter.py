"""Tests for automatic personality adaptation based on session energy."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from app.config import settings
from app.main import app, ollama, store
from app.personality_adapter import PersonalityAdapter
from httpx import ASGITransport, AsyncClient


@contextmanager
def _override_setting(name: str, value):
    """Temporarily override a frozen Settings field."""
    original = getattr(settings, name)
    object.__setattr__(settings, name, value)
    try:
        yield
    finally:
        object.__setattr__(settings, name, original)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
async def _reset_store():
    await store.hydrate([], None, False, None)
    yield
    await store.hydrate([], None, False, None)


def _make_session(app_switches: int = 0, unique_apps: int = 0, **kwargs) -> dict:
    return {
        "app_switches": app_switches,
        "unique_apps": unique_apps,
        "top_apps": kwargs.get("top_apps", []),
        "session_duration_s": kwargs.get("session_duration_s", 600),
    }


# ── Classification tests ──────────────────────────────────────────────


def test_empty_session_returns_calm():
    """No activity = calm."""
    adapter = PersonalityAdapter()
    session = _make_session(app_switches=0, unique_apps=0)
    assert adapter.classify_energy(session) == "calm"


def test_low_switches_returns_calm():
    """1-2 switches, 1-2 apps = copilot mode."""
    adapter = PersonalityAdapter()
    session = _make_session(app_switches=2, unique_apps=2)
    assert adapter.classify_energy(session) == "calm"


def test_moderate_activity_returns_active():
    """5-10 switches, 3-4 apps = assistant mode."""
    adapter = PersonalityAdapter()
    session = _make_session(app_switches=8, unique_apps=4)
    assert adapter.classify_energy(session) == "active"


def test_high_switches_returns_urgent():
    """20+ switches = operator mode."""
    adapter = PersonalityAdapter()
    session = _make_session(app_switches=20, unique_apps=4)
    assert adapter.classify_energy(session) == "urgent"


def test_many_unique_apps_returns_urgent():
    """6+ unique apps = operator even with moderate switches."""
    adapter = PersonalityAdapter()
    session = _make_session(app_switches=10, unique_apps=6)
    assert adapter.classify_energy(session) == "urgent"


# ── Recommendation mapping tests ──────────────────────────────────────


def test_recommend_maps_calm_to_copilot():
    """Energy 'calm' maps to 'copilot' personality mode."""
    adapter = PersonalityAdapter()
    session = _make_session(app_switches=1, unique_apps=1)
    assert adapter.recommend(session) == "copilot"


def test_recommend_maps_active_to_assistant():
    """Energy 'active' maps to 'assistant' personality mode."""
    adapter = PersonalityAdapter()
    session = _make_session(app_switches=10, unique_apps=4)
    assert adapter.recommend(session) == "assistant"


def test_recommend_maps_urgent_to_operator():
    """Energy 'urgent' maps to 'operator' personality mode."""
    adapter = PersonalityAdapter()
    session = _make_session(app_switches=25, unique_apps=8)
    assert adapter.recommend(session) == "operator"


# ── Custom threshold tests ────────────────────────────────────────────


def test_custom_thresholds():
    """Custom thresholds change classification boundaries."""
    adapter = PersonalityAdapter(
        calm_max_switches=1,
        active_max_switches=5,
        calm_max_unique_apps=1,
        active_max_unique_apps=3,
    )
    # 2 switches with default would be calm, but with custom threshold it's active
    session = _make_session(app_switches=2, unique_apps=2)
    assert adapter.classify_energy(session) == "active"


# ── Integration tests ─────────────────────────────────────────────────


@pytest.mark.anyio
async def test_chat_auto_adapts_personality(client):
    """When PERSONALITY_AUTO_ADAPT=true, chat uses adapted mode."""
    urgent_session = _make_session(app_switches=20, unique_apps=6)

    with _override_setting("personality_auto_adapt", True):
        with patch.object(store, "session_summary", new_callable=AsyncMock, return_value=urgent_session):
            with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
                resp = await client.post("/api/chat", json={"message": "hello"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["personality_mode"] == "operator"


@pytest.mark.anyio
async def test_chat_explicit_mode_overrides_auto(client):
    """Explicit personality_mode in request overrides auto-adapt."""
    urgent_session = _make_session(app_switches=20, unique_apps=6)

    with _override_setting("personality_auto_adapt", True):
        with patch.object(store, "session_summary", new_callable=AsyncMock, return_value=urgent_session):
            with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
                resp = await client.post(
                    "/api/chat",
                    json={"message": "hello", "personality_mode": "copilot"},
                )

    assert resp.status_code == 200
    data = resp.json()
    assert data["personality_mode"] == "copilot"


@pytest.mark.anyio
async def test_personality_status_endpoint(client):
    """GET /api/personality returns energy and recommendation."""
    resp = await client.get("/api/personality")
    assert resp.status_code == 200
    data = resp.json()
    assert "current_mode" in data
    assert "auto_adapt_enabled" in data
    assert "session_energy" in data
    assert "recommended_mode" in data
    assert "session_summary" in data
    assert data["session_energy"] in {"calm", "active", "urgent"}
    assert data["recommended_mode"] in {"copilot", "assistant", "operator"}
