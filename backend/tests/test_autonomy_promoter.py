"""Tests for autonomy auto-promotion based on run success history."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from app.autonomy_promoter import AutonomyPromoter
from app.config import settings
from app.main import app, autonomy, db, store
from app.schemas import AutonomyRunRecord
from httpx import ASGITransport, AsyncClient


def _mock_run_record(**overrides) -> AutonomyRunRecord:
    """Create a minimal AutonomyRunRecord for mocking autonomy.start()."""
    now = datetime.now(timezone.utc)
    defaults = {
        "run_id": "test-run-id",
        "task_id": "test-task-id",
        "objective": "test objective",
        "planner_mode": "deterministic",
        "status": "running",
        "iteration": 0,
        "max_iterations": 5,
        "parallel_agents": 1,
        "auto_approve_irreversible": False,
        "autonomy_level": "supervised",
        "started_at": now,
        "updated_at": now,
        "agent_log": [],
    }
    defaults.update(overrides)
    return AutonomyRunRecord(**defaults)


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


@contextmanager
def _override_setting(name: str, value):
    """Temporarily override a frozen Settings field."""
    original = getattr(settings, name)
    object.__setattr__(settings, name, value)
    try:
        yield
    finally:
        object.__setattr__(settings, name, original)


def _run(level: str, status: str) -> dict:
    """Helper to create a run outcome dict."""
    return {"autonomy_level": level, "status": status}


# ── Core recommendation tests ─────────────────────────────────────────


def test_no_history_returns_supervised():
    """No runs = supervised (conservative start)."""
    promoter = AutonomyPromoter()
    result = promoter.recommend([])
    assert result["recommended_level"] == "supervised"
    assert result["consecutive_successes"] == 0
    assert "no run history" in result["reason"]


def test_single_success_stays_supervised():
    """One success isn't enough to promote."""
    promoter = AutonomyPromoter()
    runs = [_run("supervised", "completed")]
    result = promoter.recommend(runs)
    assert result["recommended_level"] == "supervised"
    assert result["consecutive_successes"] == 1
    assert result["current_level"] == "supervised"


def test_five_successes_promotes_to_guided():
    """5 consecutive supervised successes -> guided."""
    promoter = AutonomyPromoter()
    runs = [_run("supervised", "completed") for _ in range(5)]
    result = promoter.recommend(runs)
    assert result["recommended_level"] == "guided"
    assert result["consecutive_successes"] == 5
    assert "promoted" in result["reason"].lower()


def test_five_guided_successes_promotes_to_autonomous():
    """5 consecutive guided successes -> autonomous."""
    promoter = AutonomyPromoter()
    runs = [_run("guided", "completed") for _ in range(5)]
    result = promoter.recommend(runs)
    assert result["recommended_level"] == "autonomous"
    assert result["consecutive_successes"] == 5


def test_failure_demotes_to_supervised():
    """Any failure -> drop to supervised."""
    promoter = AutonomyPromoter()
    runs = [_run("guided", "failed")]
    result = promoter.recommend(runs)
    assert result["recommended_level"] == "supervised"
    assert "demoted" in result["reason"].lower()


def test_cancelled_counts_as_failure():
    """Cancelled run breaks the streak."""
    promoter = AutonomyPromoter()
    runs = [
        _run("supervised", "cancelled"),
        _run("supervised", "completed"),
        _run("supervised", "completed"),
    ]
    result = promoter.recommend(runs)
    assert result["recommended_level"] == "supervised"
    assert "demoted" in result["reason"].lower()


def test_mixed_levels_uses_most_recent():
    """Current level is determined by the most recent run."""
    promoter = AutonomyPromoter()
    runs = [
        _run("guided", "completed"),
        _run("guided", "completed"),
        _run("guided", "completed"),
        _run("guided", "completed"),
        _run("guided", "completed"),
        # older runs at supervised level — shouldn't matter
        _run("supervised", "completed"),
        _run("supervised", "completed"),
    ]
    result = promoter.recommend(runs)
    assert result["current_level"] == "guided"
    assert result["recommended_level"] == "autonomous"


def test_already_autonomous_stays():
    """Can't promote beyond autonomous."""
    promoter = AutonomyPromoter()
    runs = [_run("autonomous", "completed") for _ in range(10)]
    result = promoter.recommend(runs)
    assert result["recommended_level"] == "autonomous"
    assert "maximum" in result["reason"].lower()


def test_custom_threshold():
    """Custom promote_threshold changes the required streak."""
    promoter = AutonomyPromoter(promote_threshold=3)
    runs = [_run("supervised", "completed") for _ in range(3)]
    result = promoter.recommend(runs)
    assert result["recommended_level"] == "guided"
    assert result["consecutive_successes"] == 3


# ── Integration tests ─────────────────────────────────────────────────


@pytest.mark.anyio
async def test_promotion_status_endpoint(client):
    """GET /api/autonomy/promotion returns recommendation."""
    resp = await client.get("/api/autonomy/promotion")
    assert resp.status_code == 200
    data = resp.json()
    assert "recommended_level" in data
    assert "current_level" in data
    assert "consecutive_successes" in data
    assert "reason" in data
    assert "auto_promote_enabled" in data
    assert data["recommended_level"] in {"supervised", "guided", "autonomous"}


@pytest.mark.anyio
async def test_start_run_auto_promotes(client):
    """When auto-promote enabled with good history, run starts at promoted level."""
    good_history = [_run("supervised", "completed") for _ in range(5)]

    with _override_setting("autonomy_auto_promote", True):
        with patch.object(db, "recent_autonomy_outcomes", new_callable=AsyncMock, return_value=good_history):
            with patch.object(autonomy, "start", new_callable=AsyncMock) as mock_start:
                mock_start.return_value = _mock_run_record(autonomy_level="guided")
                resp = await client.post(
                    "/api/autonomy/runs",
                    json={"objective": "test task", "max_iterations": 5},
                )

    assert resp.status_code == 200
    # Verify autonomy.start was called with promoted level
    call_args = mock_start.call_args[0][0]
    assert call_args.autonomy_level == "guided"


@pytest.mark.anyio
async def test_start_run_explicit_level_not_overridden(client):
    """Explicit autonomy_level in request is respected even with auto-promote."""
    good_history = [_run("supervised", "completed") for _ in range(5)]

    with _override_setting("autonomy_auto_promote", True):
        with patch.object(db, "recent_autonomy_outcomes", new_callable=AsyncMock, return_value=good_history):
            with patch.object(autonomy, "start", new_callable=AsyncMock) as mock_start:
                mock_start.return_value = _mock_run_record(autonomy_level="autonomous")
                resp = await client.post(
                    "/api/autonomy/runs",
                    json={
                        "objective": "test task",
                        "max_iterations": 5,
                        "autonomy_level": "autonomous",
                    },
                )

    assert resp.status_code == 200
    # Explicit level should not be overridden
    call_args = mock_start.call_args[0][0]
    assert call_args.autonomy_level == "autonomous"
