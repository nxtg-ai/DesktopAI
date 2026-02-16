"""Tests for personality mode state synchronization (F010/F008/F009)."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")

import pytest
from app.main import app
from httpx import ASGITransport, AsyncClient


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
def _reset_personality_mode():
    """Reset the mutable personality mode between tests."""
    from app import deps

    deps._active_personality_mode = None
    yield
    deps._active_personality_mode = None


@pytest.mark.anyio
async def test_put_personality_mode_updates_state(client):
    """PUT then GET: verify mode changed."""
    put_resp = await client.put(
        "/api/personality", json={"mode": "operator"}
    )
    assert put_resp.status_code == 200
    assert put_resp.json() == {"mode": "operator"}

    get_resp = await client.get("/api/personality")
    assert get_resp.status_code == 200
    assert get_resp.json()["current_mode"] == "operator"


@pytest.mark.anyio
async def test_put_personality_mode_invalid_rejects(client):
    """PUT with invalid mode returns 400."""
    resp = await client.put(
        "/api/personality", json={"mode": "invalid_mode"}
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "error" in data


@pytest.mark.anyio
async def test_personality_mode_default_from_config(client):
    """GET before any PUT returns config default."""
    from app.config import settings

    resp = await client.get("/api/personality")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_mode"] == settings.personality_mode


# ── Prompt tuning tests (F008/F009) ──────────────────────────────────


def test_copilot_prompt_tightened():
    """F008: Copilot prompt limits to 3 bullet points and 5 sentences."""
    from app.routes.agent import _PERSONALITY_PROMPTS

    prompt = _PERSONALITY_PROMPTS["copilot"]
    assert "3 bullet points" in prompt.lower()
    assert "5 sentences" in prompt.lower()


def test_operator_prompt_forbids_pleasantry_words():
    """F009: Operator prompt explicitly forbids 'Sure', 'Let me', etc."""
    from app.routes.agent import _PERSONALITY_PROMPTS

    prompt = _PERSONALITY_PROMPTS["operator"]
    assert "Sure" in prompt
    assert "Let me" in prompt
    assert "Of course" in prompt
    assert "Certainly" in prompt
    assert "action verb" in prompt.lower()


@pytest.mark.anyio
async def test_put_personality_mode_copilot(client):
    """PUT copilot mode and verify it's accepted."""
    resp = await client.put("/api/personality", json={"mode": "copilot"})
    assert resp.status_code == 200
    assert resp.json() == {"mode": "copilot"}


@pytest.mark.anyio
async def test_put_personality_mode_assistant(client):
    """PUT assistant mode and verify it's accepted."""
    resp = await client.put("/api/personality", json={"mode": "assistant"})
    assert resp.status_code == 200
    assert resp.json() == {"mode": "assistant"}


@pytest.mark.anyio
async def test_get_personality_after_multiple_puts(client):
    """Multiple PUTs: last one wins."""
    await client.put("/api/personality", json={"mode": "copilot"})
    await client.put("/api/personality", json={"mode": "operator"})
    await client.put("/api/personality", json={"mode": "assistant"})

    resp = await client.get("/api/personality")
    assert resp.status_code == 200
    assert resp.json()["current_mode"] == "assistant"
