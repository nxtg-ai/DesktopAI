import asyncio

from app.action_executor import (
    ActionExecutionResult,
    TaskActionExecutor,
    WindowsPowerShellActionExecutor,
    build_action_executor,
)
from app.orchestrator import TaskOrchestrator
from app.schemas import TaskAction, TaskPlanRequest, TaskStepPlan


class _FailingExecutor(TaskActionExecutor):
    mode = "test-failing"

    async def execute(self, action: TaskAction, *, objective: str, desktop_context=None) -> ActionExecutionResult:
        return ActionExecutionResult(
            ok=False,
            error=f"forced failure for {action.action}",
            result={"executor": self.mode, "action": action.action, "ok": False},
        )

    def status(self):
        return {"mode": self.mode, "available": True}


class _FlakyExecutor(TaskActionExecutor):
    mode = "test-flaky"

    def __init__(self, failures_before_success: int = 1, error: str = "transient failure"):
        self.failures_before_success = max(0, failures_before_success)
        self.error = error
        self.calls = 0

    async def execute(self, action: TaskAction, *, objective: str, desktop_context=None) -> ActionExecutionResult:
        self.calls += 1
        if self.calls <= self.failures_before_success:
            return ActionExecutionResult(
                ok=False,
                error=self.error,
                result={"executor": self.mode, "action": action.action, "ok": False},
            )
        return ActionExecutionResult(
            ok=True,
            result={"executor": self.mode, "action": action.action, "ok": True},
        )

    def status(self):
        return {"mode": self.mode, "available": True}


def test_orchestrator_marks_task_failed_when_executor_fails():
    async def scenario():
        orchestrator = TaskOrchestrator(action_executor=_FailingExecutor())
        created = await orchestrator.create_task("Failure path")
        await orchestrator.set_plan(
            created.task_id,
            TaskPlanRequest(
                steps=[
                    TaskStepPlan(
                        action=TaskAction(action="observe_desktop", description="Should fail"),
                    )
                ]
            ),
        )

        failed = await orchestrator.run_task(created.task_id)
        assert failed.status == "failed"
        assert failed.last_error is not None
        assert "forced failure" in failed.last_error
        assert failed.steps[0].status == "failed"
        assert failed.steps[0].result is not None
        assert failed.steps[0].result.get("executor") == "test-failing"

    asyncio.run(scenario())


def test_orchestrator_retries_transient_executor_failures():
    async def scenario():
        executor = _FlakyExecutor(failures_before_success=1, error="temporary unavailable")
        orchestrator = TaskOrchestrator(
            action_executor=executor,
            executor_retry_count=2,
            executor_retry_delay_ms=1,
        )
        created = await orchestrator.create_task("Retry transient failure")
        await orchestrator.set_plan(
            created.task_id,
            TaskPlanRequest(
                steps=[
                    TaskStepPlan(
                        action=TaskAction(action="observe_desktop", description="Should retry then pass"),
                    )
                ]
            ),
        )

        done = await orchestrator.run_task(created.task_id)
        assert done.status == "completed"
        assert executor.calls == 2
        assert done.steps[0].result is not None
        assert done.steps[0].result.get("attempts") == 2

    asyncio.run(scenario())


def test_orchestrator_does_not_retry_unsupported_action_errors():
    async def scenario():
        executor = _FlakyExecutor(failures_before_success=3, error="unsupported action for executor")
        orchestrator = TaskOrchestrator(
            action_executor=executor,
            executor_retry_count=4,
            executor_retry_delay_ms=1,
        )
        created = await orchestrator.create_task("Unsupported should fail once")
        await orchestrator.set_plan(
            created.task_id,
            TaskPlanRequest(
                steps=[
                    TaskStepPlan(
                        action=TaskAction(action="observe_desktop", description="Unsupported"),
                    )
                ]
            ),
        )

        failed = await orchestrator.run_task(created.task_id)
        assert failed.status == "failed"
        assert executor.calls == 1
        assert failed.steps[0].result is not None
        assert failed.steps[0].result.get("attempts") == 1

    asyncio.run(scenario())


def test_build_action_executor_auto_uses_simulated_off_windows(monkeypatch):
    monkeypatch.setattr("app.action_executor._is_windows_platform", lambda: False)

    executor = build_action_executor(
        mode="auto",
        powershell_executable="pwsh",
        timeout_s=20,
    )
    assert executor.mode == "simulated"


def test_windows_executor_reports_unavailable_off_windows(monkeypatch):
    monkeypatch.setattr("app.action_executor.powershell._is_windows_platform", lambda: False)
    monkeypatch.setattr("app.action_executor.powershell.shutil.which", lambda _name: "/usr/bin/pwsh")

    executor = WindowsPowerShellActionExecutor(powershell_executable="pwsh")
    status = executor.status()
    assert status["available"] is False
    assert "Windows-only" in status["message"]


def test_build_action_executor_auto_uses_windows_on_windows(monkeypatch):
    monkeypatch.setattr("app.action_executor._is_windows_platform", lambda: True)
    monkeypatch.setattr("app.action_executor.powershell._is_windows_platform", lambda: True)
    monkeypatch.setattr(
        "app.action_executor.powershell.shutil.which",
        lambda _name: "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
    )

    executor = build_action_executor(
        mode="auto",
        powershell_executable="powershell.exe",
        timeout_s=20,
    )
    assert executor.mode == "windows-powershell"


def test_simulated_executor_preflight_is_ok():
    async def scenario():
        executor = build_action_executor(
            mode="simulated",
            powershell_executable="powershell.exe",
            timeout_s=20,
        )
        report = await executor.preflight()
        assert report["ok"] is True
        assert report["mode"] == "simulated"
        assert report["checks"]

    asyncio.run(scenario())


def test_windows_executor_preflight_reports_non_windows_host(monkeypatch):
    async def scenario():
        monkeypatch.setattr("app.action_executor.powershell._is_windows_platform", lambda: False)
        monkeypatch.setattr("app.action_executor.powershell.shutil.which", lambda _name: "/usr/bin/pwsh")

        executor = WindowsPowerShellActionExecutor(powershell_executable="pwsh")
        report = await executor.preflight()
        assert report["ok"] is False
        windows_check = next(item for item in report["checks"] if item["name"] == "windows_host")
        assert windows_check["ok"] is False

    asyncio.run(scenario())


def test_windows_executor_preflight_reports_success_on_windows(monkeypatch):
    async def scenario():
        monkeypatch.setattr("app.action_executor.powershell._is_windows_platform", lambda: True)
        monkeypatch.setattr(
            "app.action_executor.powershell.shutil.which",
            lambda _name: "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
        )

        async def fake_run(_script):
            return "ok"

        executor = WindowsPowerShellActionExecutor(powershell_executable="powershell.exe")
        monkeypatch.setattr(executor, "_run_powershell", fake_run)
        report = await executor.preflight()
        assert report["ok"] is True
        assert all(item["ok"] is True for item in report["checks"])

    asyncio.run(scenario())


# --- DesktopContext integration tests ---

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from app.desktop_context import DesktopContext
from app.schemas import WindowEvent


def _make_context(**kwargs):
    defaults = dict(
        window_title="Outlook - Inbox",
        process_exe="outlook.exe",
        timestamp=datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        uia_summary='Focused: Reply Button\nControl: Button',
        screenshot_b64=None,
    )
    defaults.update(kwargs)
    return DesktopContext(**defaults)


def test_simulated_executor_accepts_desktop_context():
    async def scenario():
        from app.action_executor import SimulatedTaskActionExecutor
        executor = SimulatedTaskActionExecutor()
        ctx = _make_context()
        result = await executor.execute(
            TaskAction(action="observe_desktop", description="test"),
            objective="test",
            desktop_context=ctx,
        )
        assert result.ok is True
        assert result.result["action"] == "observe_desktop"

    asyncio.run(scenario())


def test_windows_executor_observe_desktop_returns_context(monkeypatch):
    async def scenario():
        monkeypatch.setattr("app.action_executor.powershell._is_windows_platform", lambda: True)
        monkeypatch.setattr(
            "app.action_executor.powershell.shutil.which",
            lambda _name: "C:/Windows/System32/powershell.exe",
        )
        executor = WindowsPowerShellActionExecutor(powershell_executable="powershell.exe")
        ctx = _make_context(uia_summary="Focused: Reply Button")
        result = await executor.execute(
            TaskAction(action="observe_desktop", description="test"),
            objective="test",
            desktop_context=ctx,
        )
        assert result.ok is True
        output = json.loads(result.result["output"])
        assert output["window_title"] == "Outlook - Inbox"
        assert output["process"] == "outlook.exe"
        assert "Reply Button" in output["uia_summary"]
        assert output["screenshot_available"] is False

    asyncio.run(scenario())


def test_windows_executor_observe_desktop_without_context_falls_through(monkeypatch):
    async def scenario():
        monkeypatch.setattr("app.action_executor.powershell._is_windows_platform", lambda: True)
        monkeypatch.setattr(
            "app.action_executor.powershell.shutil.which",
            lambda _name: "C:/Windows/System32/powershell.exe",
        )

        async def fake_run(_script):
            return "Test Window Title"

        executor = WindowsPowerShellActionExecutor(powershell_executable="powershell.exe")
        monkeypatch.setattr(executor, "_run_powershell", fake_run)
        result = await executor.execute(
            TaskAction(action="observe_desktop", description="test"),
            objective="test",
            desktop_context=None,
        )
        assert result.ok is True
        assert result.result["output"] == "Test Window Title"

    asyncio.run(scenario())


def test_windows_executor_compose_text_with_ollama(monkeypatch):
    async def scenario():
        monkeypatch.setattr("app.action_executor.powershell._is_windows_platform", lambda: True)
        monkeypatch.setattr(
            "app.action_executor.powershell.shutil.which",
            lambda _name: "C:/Windows/System32/powershell.exe",
        )
        mock_ollama = AsyncMock()
        mock_ollama.chat = AsyncMock(return_value="Dear colleague, thank you for your email.")
        executor = WindowsPowerShellActionExecutor(
            powershell_executable="powershell.exe",
            ollama=mock_ollama,
        )
        ctx = _make_context()

        ps_output = []

        async def fake_run(script):
            ps_output.append(script)
            return "sent-keys:ok"

        monkeypatch.setattr(executor, "_run_powershell", fake_run)
        result = await executor.execute(
            TaskAction(action="compose_text", description="test"),
            objective="reply to email",
            desktop_context=ctx,
        )
        assert result.ok is True
        mock_ollama.chat.assert_called_once()
        # The composed text should appear in the SendKeys script
        assert ps_output
        assert "colleague" in ps_output[0] or "thank you" in ps_output[0]

    asyncio.run(scenario())


def test_windows_executor_compose_text_falls_back_without_ollama(monkeypatch):
    async def scenario():
        monkeypatch.setattr("app.action_executor.powershell._is_windows_platform", lambda: True)
        monkeypatch.setattr(
            "app.action_executor.powershell.shutil.which",
            lambda _name: "C:/Windows/System32/powershell.exe",
        )
        executor = WindowsPowerShellActionExecutor(powershell_executable="powershell.exe")

        ps_output = []

        async def fake_run(script):
            ps_output.append(script)
            return "sent-keys:ok"

        monkeypatch.setattr(executor, "_run_powershell", fake_run)
        result = await executor.execute(
            TaskAction(action="compose_text", description="test"),
            objective="reply to email",
            desktop_context=_make_context(),
        )
        assert result.ok is True
        # Should use default text since no ollama
        assert ps_output
        assert "Draft generated by DesktopAI" in ps_output[0]

    asyncio.run(scenario())


def test_windows_executor_compose_text_uses_vision_with_screenshot(monkeypatch):
    import base64
    async def scenario():
        monkeypatch.setattr("app.action_executor.powershell._is_windows_platform", lambda: True)
        monkeypatch.setattr(
            "app.action_executor.powershell.shutil.which",
            lambda _name: "C:/Windows/System32/powershell.exe",
        )
        mock_ollama = AsyncMock()
        mock_ollama.chat_with_images = AsyncMock(return_value="Vision-generated text.")
        mock_ollama.chat = AsyncMock(return_value="Text-only fallback.")
        executor = WindowsPowerShellActionExecutor(
            powershell_executable="powershell.exe",
            ollama=mock_ollama,
        )
        b64 = base64.b64encode(b"fake-jpeg").decode()
        ctx = _make_context(screenshot_b64=b64)

        async def fake_run(script):
            return "sent-keys:ok"

        monkeypatch.setattr(executor, "_run_powershell", fake_run)
        result = await executor.execute(
            TaskAction(action="compose_text", description="test"),
            objective="reply to email",
            desktop_context=ctx,
        )
        assert result.ok is True
        mock_ollama.chat_with_images.assert_called_once()
        mock_ollama.chat.assert_not_called()

    asyncio.run(scenario())


def test_windows_executor_verify_outcome_detects_change(monkeypatch):
    async def scenario():
        monkeypatch.setattr("app.action_executor.powershell._is_windows_platform", lambda: True)
        monkeypatch.setattr(
            "app.action_executor.powershell.shutil.which",
            lambda _name: "C:/Windows/System32/powershell.exe",
        )
        after_event = WindowEvent(
            hwnd="0x1234",
            title="Outlook - Sent",
            process_exe="outlook.exe",
            pid=100,
            timestamp=datetime(2025, 6, 1, 12, 0, 1, tzinfo=timezone.utc),
        )
        mock_store = AsyncMock()
        mock_store.current = AsyncMock(return_value=after_event)
        executor = WindowsPowerShellActionExecutor(
            powershell_executable="powershell.exe",
            state_store=mock_store,
        )
        before_ctx = _make_context(window_title="Outlook - Inbox")
        result = await executor.execute(
            TaskAction(action="verify_outcome", description="test"),
            objective="send email",
            desktop_context=before_ctx,
        )
        assert result.ok is True
        assert "Outlook - Sent" in result.result["output"]
        assert "window changed" in result.result["output"]

    asyncio.run(scenario())


def test_windows_executor_verify_outcome_no_change(monkeypatch):
    async def scenario():
        monkeypatch.setattr("app.action_executor.powershell._is_windows_platform", lambda: True)
        monkeypatch.setattr(
            "app.action_executor.powershell.shutil.which",
            lambda _name: "C:/Windows/System32/powershell.exe",
        )
        after_event = WindowEvent(
            hwnd="0x1234",
            title="Outlook - Inbox",
            process_exe="outlook.exe",
            pid=100,
            timestamp=datetime(2025, 6, 1, 12, 0, 1, tzinfo=timezone.utc),
        )
        mock_store = AsyncMock()
        mock_store.current = AsyncMock(return_value=after_event)
        executor = WindowsPowerShellActionExecutor(
            powershell_executable="powershell.exe",
            state_store=mock_store,
        )
        before_ctx = _make_context(window_title="Outlook - Inbox", uia_summary="")
        result = await executor.execute(
            TaskAction(action="verify_outcome", description="test"),
            objective="check email",
            desktop_context=before_ctx,
        )
        assert result.ok is True
        assert "no observable state change" in result.result["output"]

    asyncio.run(scenario())


def test_windows_executor_verify_outcome_without_state_store(monkeypatch):
    async def scenario():
        monkeypatch.setattr("app.action_executor.powershell._is_windows_platform", lambda: True)
        monkeypatch.setattr(
            "app.action_executor.powershell.shutil.which",
            lambda _name: "C:/Windows/System32/powershell.exe",
        )
        executor = WindowsPowerShellActionExecutor(powershell_executable="powershell.exe")

        async def fake_run(_script):
            return "verified"

        monkeypatch.setattr(executor, "_run_powershell", fake_run)
        before_ctx = _make_context()
        result = await executor.execute(
            TaskAction(action="verify_outcome", description="test"),
            objective="check email",
            desktop_context=before_ctx,
        )
        assert result.ok is True
        assert result.result["output"] == "verified"

    asyncio.run(scenario())


def test_build_action_executor_passes_state_store_and_ollama(monkeypatch):
    monkeypatch.setattr("app.action_executor.powershell._is_windows_platform", lambda: True)
    monkeypatch.setattr(
        "app.action_executor.powershell.shutil.which",
        lambda _name: "C:/Windows/System32/powershell.exe",
    )
    mock_store = object()
    mock_ollama = object()
    executor = build_action_executor(
        mode="windows",
        powershell_executable="powershell.exe",
        timeout_s=20,
        state_store=mock_store,
        ollama=mock_ollama,
    )
    assert executor.mode == "windows-powershell"
    assert executor._state_store is mock_store
    assert executor._ollama is mock_ollama
