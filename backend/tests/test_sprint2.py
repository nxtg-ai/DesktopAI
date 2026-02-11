"""Tests for Sprint 2 features: bridge timeout, autonomy levels, session context, LLM provider."""

import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from app.autonomy import AutonomousRunner
from app.config import Settings
from app.llm_provider import LLMProvider, OpenAIProvider
from app.orchestrator import TaskOrchestrator
from app.schemas import AutonomyStartRequest, WindowEvent
from app.state import StateStore

# ── Bridge Timeout ──────────────────────────────────────────────────────


def test_bridge_timeout_default_is_20():
    s = Settings()
    assert s.action_executor_bridge_timeout_s == 20


# ── Autonomy Level Schema ──────────────────────────────────────────────


def test_autonomy_start_request_default_level():
    req = AutonomyStartRequest(objective="test")
    assert req.autonomy_level == "supervised"
    assert req.auto_approve_irreversible is False


def test_autonomy_start_request_guided_level():
    req = AutonomyStartRequest(objective="test", autonomy_level="guided")
    assert req.autonomy_level == "guided"


def test_autonomy_start_request_autonomous_level():
    req = AutonomyStartRequest(objective="test", autonomy_level="autonomous")
    assert req.autonomy_level == "autonomous"


def test_autonomy_start_request_invalid_level_rejected():
    with pytest.raises(Exception):
        AutonomyStartRequest(objective="test", autonomy_level="yolo")


# ── Autonomy Level Behaviour ───────────────────────────────────────────


async def _wait_for_status(
    runner: AutonomousRunner, run_id: str, expected: str, timeout_s: float = 1.5
):
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        run = await runner.get_run(run_id)
        if run is not None:
            last = run.status
            if run.status == expected:
                return run
        await asyncio.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach {expected}, last status={last}")


_OBJECTIVE_WITH_IRREVERSIBLE = "Open outlook, draft reply, then send email"


@pytest.mark.asyncio
async def test_supervised_level_blocks_on_approval():
    """supervised level should block on irreversible steps."""
    orchestrator = TaskOrchestrator()
    runner = AutonomousRunner(orchestrator, on_run_update=AsyncMock())
    started = await runner.start(
        AutonomyStartRequest(
            objective=_OBJECTIVE_WITH_IRREVERSIBLE,
            max_iterations=20,
            autonomy_level="supervised",
        )
    )
    assert started.autonomy_level == "supervised"
    waiting = await _wait_for_status(runner, started.run_id, "waiting_approval")
    assert waiting.approval_token is not None


@pytest.mark.asyncio
async def test_guided_level_auto_approves():
    """guided level should auto-approve irreversible steps."""
    orchestrator = TaskOrchestrator()
    runner = AutonomousRunner(orchestrator, on_run_update=AsyncMock())
    started = await runner.start(
        AutonomyStartRequest(
            objective=_OBJECTIVE_WITH_IRREVERSIBLE,
            max_iterations=20,
            autonomy_level="guided",
        )
    )
    assert started.autonomy_level == "guided"
    # guided auto-approves, so it should complete (not block on approval)
    completed = await _wait_for_status(
        runner, started.run_id, "completed", timeout_s=2.0
    )
    assert completed.status == "completed"


@pytest.mark.asyncio
async def test_autonomous_level_auto_approves():
    """autonomous level should also auto-approve."""
    orchestrator = TaskOrchestrator()
    runner = AutonomousRunner(orchestrator, on_run_update=AsyncMock())
    started = await runner.start(
        AutonomyStartRequest(
            objective=_OBJECTIVE_WITH_IRREVERSIBLE,
            max_iterations=20,
            autonomy_level="autonomous",
        )
    )
    assert started.autonomy_level == "autonomous"
    completed = await _wait_for_status(
        runner, started.run_id, "completed", timeout_s=2.0
    )
    assert completed.status == "completed"


# ── Session Context ─────────────────────────────────────────────────────


def _make_event(
    process: str, title: str, ts: datetime | None = None, event_type: str = "foreground",
) -> WindowEvent:
    return WindowEvent(
        type=event_type,
        hwnd="0x1234",
        timestamp=ts or datetime.now(timezone.utc),
        process_exe=process,
        title=title,
    )


@pytest.mark.asyncio
async def test_session_summary_empty():
    store = StateStore(max_events=100)
    summary = await store.session_summary()
    assert summary["app_switches"] == 0
    assert summary["unique_apps"] == 0
    assert summary["top_apps"] == []
    assert summary["session_duration_s"] == 0


@pytest.mark.asyncio
async def test_session_summary_tracks_foreground_switches():
    store = StateStore(max_events=100)
    now = datetime.now(timezone.utc)
    await store.record(_make_event("code.exe", "VS Code", now))
    await store.record(_make_event("outlook.exe", "Outlook", now))
    await store.record(_make_event("code.exe", "VS Code", now))

    summary = await store.session_summary()
    assert summary["app_switches"] == 3
    assert summary["unique_apps"] == 2
    assert len(summary["top_apps"]) == 2


@pytest.mark.asyncio
async def test_session_summary_ignores_non_foreground():
    store = StateStore(max_events=100)
    now = datetime.now(timezone.utc)
    await store.record(_make_event("code.exe", "VS Code", now))
    # idle event should not be counted as an app switch
    await store.record(
        WindowEvent(type="idle", hwnd="0x0", timestamp=now, process_exe="", title="")
    )

    summary = await store.session_summary()
    assert summary["app_switches"] == 1


@pytest.mark.asyncio
async def test_session_summary_reset_clears():
    store = StateStore(max_events=100)
    await store.record(_make_event("code.exe", "VS Code"))
    await store.reset()
    summary = await store.session_summary()
    assert summary["app_switches"] == 0


@pytest.mark.asyncio
async def test_session_summary_session_duration():
    store = StateStore(max_events=100)
    await store.record(_make_event("code.exe", "VS Code"))
    summary = await store.session_summary()
    assert summary["session_duration_s"] >= 0


# ── LLM Provider Protocol ──────────────────────────────────────────────


def test_ollama_client_satisfies_llm_provider_protocol():
    from app.ollama import OllamaClient

    client = OllamaClient("http://localhost:11434", "test")
    assert isinstance(client, LLMProvider)


def test_openai_provider_satisfies_llm_provider_protocol():
    provider = OpenAIProvider(api_key="test", model="gpt-4o")
    assert isinstance(provider, LLMProvider)


@pytest.mark.asyncio
async def test_openai_provider_generate_delegates_to_chat():
    """generate() should send a user message via chat()."""
    provider = OpenAIProvider(api_key="test-key", model="gpt-4o")
    with patch.object(provider, "chat", new_callable=AsyncMock, return_value="hello") as mock_chat:
        result = await provider.generate("say hi")
        assert result == "hello"
        mock_chat.assert_called_once()
        call_args = mock_chat.call_args
        messages = call_args[0][0]
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "say hi"


@pytest.mark.asyncio
async def test_openai_provider_chat_with_images_returns_none_for_empty():
    provider = OpenAIProvider(api_key="test", model="gpt-4o")
    result = await provider.chat_with_images([], [])
    assert result is None


def test_openai_provider_diagnostics():
    provider = OpenAIProvider(api_key="test", model="gpt-4o", base_url="http://localhost:8080")
    diag = provider.diagnostics()
    assert diag["provider"] == "openai"
    assert diag["model"] == "gpt-4o"
    assert diag["base_url"] == "http://localhost:8080"
    assert diag["available"] is False


# ── Config Provider Selection ───────────────────────────────────────────


def test_config_default_provider_is_ollama():
    s = Settings()
    assert s.llm_provider == "ollama"


def test_config_has_openai_fields():
    s = Settings()
    assert s.openai_api_key == ""
    assert s.openai_model == "gpt-4o"
    assert "openai.com" in s.openai_base_url
