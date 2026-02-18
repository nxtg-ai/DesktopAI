"""Tests for action_executor module: validation, quoting, encoding, factories."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")
os.environ.setdefault("CLASSIFIER_USE_OLLAMA", "0")
os.environ.setdefault("CLASSIFIER_DEFAULT", "docs")
os.environ.setdefault("UI_TELEMETRY_ARTIFACT_DIR", "/tmp/desktopai-ui-telemetry-test")

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.action_executor import (
    BridgeActionExecutor,
    SimulatedTaskActionExecutor,
    WindowsPowerShellActionExecutor,
    build_action_executor,
)
from app.schemas import TaskAction

# ── _ps_quote tests ──────────────────────────────────────────────────────

def _make_ps_executor(**kwargs):
    """Create a WindowsPowerShellActionExecutor for testing helper methods."""
    with patch.object(WindowsPowerShellActionExecutor, "_resolve_powershell", return_value="/usr/bin/pwsh"):
        return WindowsPowerShellActionExecutor(**kwargs)


def test_ps_quote_normal_string():
    exe = _make_ps_executor()
    assert exe._ps_quote("hello") == "'hello'"


def test_ps_quote_single_quotes():
    exe = _make_ps_executor()
    assert exe._ps_quote("it's a test") == "'it''s a test'"


def test_ps_quote_special_characters():
    exe = _make_ps_executor()
    result = exe._ps_quote("$var & (cmd)")
    assert result == "'$var & (cmd)'"


def test_ps_quote_null_byte_rejected():
    exe = _make_ps_executor()
    with pytest.raises(ValueError, match="null bytes"):
        exe._ps_quote("hello\x00world")


def test_ps_quote_overlength_rejected():
    exe = _make_ps_executor()
    with pytest.raises(ValueError, match="too long"):
        exe._ps_quote("x" * 9000)


def test_ps_quote_max_length_accepted():
    exe = _make_ps_executor()
    value = "a" * 8192
    result = exe._ps_quote(value)
    assert result.startswith("'")


# ── _validate_command_input tests ─────────────────────────────────────────

def test_validate_known_actions():
    exe = _make_ps_executor()
    for action in ["observe_desktop", "open_application", "focus_search",
                    "compose_text", "send_or_submit", "verify_outcome"]:
        exe._validate_command_input(action)  # should not raise


def test_validate_unknown_action_rejected():
    exe = _make_ps_executor()
    with pytest.raises(RuntimeError, match="unsupported action"):
        exe._validate_command_input("drop_table")


# ── _encode_sendkeys_text tests ───────────────────────────────────────────

def test_encode_sendkeys_normal_text():
    exe = _make_ps_executor()
    assert exe._encode_sendkeys_text("Hello") == "Hello"


def test_encode_sendkeys_special_keys():
    exe = _make_ps_executor()
    result = exe._encode_sendkeys_text("a+b^c")
    assert "{+}" in result
    assert "{^}" in result


def test_encode_sendkeys_newline():
    exe = _make_ps_executor()
    result = exe._encode_sendkeys_text("line1\nline2")
    assert "{ENTER}" in result


def test_encode_sendkeys_empty():
    exe = _make_ps_executor()
    assert exe._encode_sendkeys_text("") == ""


# ── _map_application_alias tests ──────────────────────────────────────────

def test_map_known_alias():
    exe = _make_ps_executor()
    assert exe._map_application_alias("notepad") == "notepad.exe"
    assert exe._map_application_alias("outlook") == "outlook.exe"
    assert exe._map_application_alias("chrome") == "chrome.exe"


def test_map_unknown_alias_passthrough():
    exe = _make_ps_executor()
    assert exe._map_application_alias("custom-app.exe") == "custom-app.exe"


# ── BridgeActionExecutor tests ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bridge_not_connected():
    mock_bridge = MagicMock()
    mock_bridge.connected = False
    exe = BridgeActionExecutor(bridge=mock_bridge)
    action = TaskAction(action="observe_desktop", description="test")
    result = await exe.execute(action, objective="test")
    assert not result.ok
    assert result.error is not None
    assert "not connected" in result.error


@pytest.mark.asyncio
async def test_bridge_execute_success():
    mock_bridge = MagicMock()
    mock_bridge.connected = True
    mock_bridge.execute = AsyncMock(return_value={"ok": True, "result": "observed"})
    exe = BridgeActionExecutor(bridge=mock_bridge)
    action = TaskAction(action="observe_desktop", description="test")
    result = await exe.execute(action, objective="test")
    assert result.ok


@pytest.mark.asyncio
async def test_bridge_execute_exception():
    mock_bridge = MagicMock()
    mock_bridge.connected = True
    mock_bridge.execute = AsyncMock(side_effect=TimeoutError("bridge timeout"))
    exe = BridgeActionExecutor(bridge=mock_bridge)
    action = TaskAction(action="click", description="test")
    result = await exe.execute(action, objective="test", desktop_context=None)
    assert not result.ok
    assert result.error is not None
    assert "bridge timeout" in result.error


@pytest.mark.asyncio
async def test_bridge_unknown_action_passthrough():
    mock_bridge = MagicMock()
    mock_bridge.connected = True
    mock_bridge.execute = AsyncMock(return_value={"ok": True, "result": "done"})
    exe = BridgeActionExecutor(bridge=mock_bridge)
    action = TaskAction(action="custom_action", description="test")
    result = await exe.execute(action, objective="test")
    assert result.ok
    mock_bridge.execute.assert_called_once_with("custom_action", {}, timeout_s=10)


# ── SimulatedTaskActionExecutor tests ─────────────────────────────────────

@pytest.mark.asyncio
async def test_simulated_executor_always_ok():
    exe = SimulatedTaskActionExecutor()
    action = TaskAction(action="anything", description="test")
    result = await exe.execute(action, objective="test objective")
    assert result.ok
    assert result.result["executor"] == "backend-simulated"
    assert result.result["objective"] == "test objective"


def test_simulated_executor_status():
    exe = SimulatedTaskActionExecutor()
    status = exe.status()
    assert status["available"] is True
    assert status["mode"] == "simulated"


# ── build_action_executor factory tests ───────────────────────────────────

def test_build_simulated_executor():
    exe = build_action_executor(mode="simulated", powershell_executable="", timeout_s=5)
    assert isinstance(exe, SimulatedTaskActionExecutor)


def test_build_sim_alias():
    exe = build_action_executor(mode="sim", powershell_executable="", timeout_s=5)
    assert isinstance(exe, SimulatedTaskActionExecutor)


def test_build_bridge_executor_requires_bridge():
    with pytest.raises(ValueError, match="no bridge"):
        build_action_executor(mode="bridge", powershell_executable="", timeout_s=5, bridge=None)


def test_build_bridge_executor_with_bridge():
    mock_bridge = MagicMock()
    exe = build_action_executor(mode="bridge", powershell_executable="", timeout_s=5, bridge=mock_bridge)
    assert isinstance(exe, BridgeActionExecutor)


def test_build_unsupported_mode():
    with pytest.raises(ValueError, match="unsupported"):
        build_action_executor(mode="quantum", powershell_executable="", timeout_s=5)


def test_build_auto_non_windows_no_bridge():
    with patch("app.action_executor._is_windows_platform", return_value=False):
        exe = build_action_executor(mode="auto", powershell_executable="", timeout_s=5)
        assert isinstance(exe, SimulatedTaskActionExecutor)


def test_auto_mode_prefers_bridge_when_provided():
    mock_bridge = MagicMock()
    with patch("app.action_executor._is_windows_platform", return_value=False):
        exe = build_action_executor(mode="auto", powershell_executable="", timeout_s=5, bridge=mock_bridge)
        assert isinstance(exe, BridgeActionExecutor)


def test_auto_mode_falls_back_without_bridge():
    with patch("app.action_executor._is_windows_platform", return_value=False):
        exe = build_action_executor(mode="auto", powershell_executable="", timeout_s=5, bridge=None)
        assert isinstance(exe, SimulatedTaskActionExecutor)


def test_bridge_mode_raises_without_bridge():
    with pytest.raises(ValueError, match="no bridge"):
        build_action_executor(mode="bridge", powershell_executable="", timeout_s=5, bridge=None)


def test_auto_mode_bridge_none_no_crash():
    """Passing bridge=None to auto mode should not crash, just fall back."""
    with patch("app.action_executor._is_windows_platform", return_value=False):
        exe = build_action_executor(mode="auto", powershell_executable="", timeout_s=5, bridge=None)
        assert isinstance(exe, SimulatedTaskActionExecutor)


def test_auto_mode_prefers_bridge_even_when_not_connected():
    """Auto mode must return BridgeActionExecutor even when bridge.connected=False.

    The executor is built once at startup before the collector connects.
    BridgeActionExecutor handles disconnection gracefully at runtime.
    This test guards against the regression from Sprint 3 (e2c0288) which
    re-introduced a `connected` check that broke the startup path.
    """
    mock_bridge = MagicMock()
    mock_bridge.connected = False  # Simulates startup state before collector connects
    with patch("app.action_executor._is_windows_platform", return_value=False):
        exe = build_action_executor(mode="auto", powershell_executable="", timeout_s=5, bridge=mock_bridge)
        assert isinstance(exe, BridgeActionExecutor), (
            "auto mode must select BridgeActionExecutor at startup even when "
            "bridge is not yet connected — runtime disconnection is handled by "
            "BridgeActionExecutor.execute(), not the factory"
        )


# ── _ps_quote metacharacter validation tests ─────────────────────────────

def test_ps_quote_rejects_dollar_sign():
    """PowerShell $variable metacharacter must be rejected in app names."""
    exe = _make_ps_executor()
    with pytest.raises(ValueError, match="metacharacter"):
        exe._ps_quote_app_name("$env:USERPROFILE")


def test_ps_quote_rejects_backtick():
    """PowerShell backtick escape must be rejected in app names."""
    exe = _make_ps_executor()
    with pytest.raises(ValueError, match="metacharacter"):
        exe._ps_quote_app_name("app`whoami")


def test_ps_quote_rejects_pipe():
    """PowerShell pipe must be rejected in app names."""
    exe = _make_ps_executor()
    with pytest.raises(ValueError, match="metacharacter"):
        exe._ps_quote_app_name("app|evil")


def test_ps_quote_rejects_ampersand():
    """PowerShell ampersand (command chaining) must be rejected in app names."""
    exe = _make_ps_executor()
    with pytest.raises(ValueError, match="metacharacter"):
        exe._ps_quote_app_name("app&calc")


def test_ps_quote_rejects_semicolon():
    """PowerShell semicolon (statement separator) must be rejected in app names."""
    exe = _make_ps_executor()
    with pytest.raises(ValueError, match="metacharacter"):
        exe._ps_quote_app_name("app;rm -rf /")


def test_ps_quote_app_name_allows_clean_names():
    """Normal application names should pass validation."""
    exe = _make_ps_executor()
    for name in ["notepad.exe", "Code.exe", "chrome.exe", "ms-teams.exe", "outlook"]:
        result = exe._ps_quote_app_name(name)
        assert result.startswith("'")
        assert result.endswith("'")


def test_ps_quote_app_name_allows_paths():
    """Application paths with backslashes and spaces should pass."""
    exe = _make_ps_executor()
    result = exe._ps_quote_app_name("C:\\Program Files\\App\\app.exe")
    assert "C:\\Program Files\\App\\app.exe" in result


def test_ps_quote_app_name_escapes_single_quotes():
    """Single quotes in app names should still be escaped."""
    exe = _make_ps_executor()
    result = exe._ps_quote_app_name("it's app.exe")
    assert "''" in result
