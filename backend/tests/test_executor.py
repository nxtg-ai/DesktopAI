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

    async def execute(self, action: TaskAction, *, objective: str) -> ActionExecutionResult:
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

    async def execute(self, action: TaskAction, *, objective: str) -> ActionExecutionResult:
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
    monkeypatch.setattr("app.action_executor.shutil.which", lambda _name: "/usr/bin/pwsh")

    executor = build_action_executor(
        mode="auto",
        powershell_executable="pwsh",
        timeout_s=20,
    )
    assert executor.mode == "simulated"


def test_windows_executor_reports_unavailable_off_windows(monkeypatch):
    monkeypatch.setattr("app.action_executor._is_windows_platform", lambda: False)
    monkeypatch.setattr("app.action_executor.shutil.which", lambda _name: "/usr/bin/pwsh")

    executor = WindowsPowerShellActionExecutor(powershell_executable="pwsh")
    status = executor.status()
    assert status["available"] is False
    assert "Windows-only" in status["message"]


def test_build_action_executor_auto_uses_windows_on_windows(monkeypatch):
    monkeypatch.setattr("app.action_executor._is_windows_platform", lambda: True)
    monkeypatch.setattr(
        "app.action_executor.shutil.which",
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
        monkeypatch.setattr("app.action_executor._is_windows_platform", lambda: False)
        monkeypatch.setattr("app.action_executor.shutil.which", lambda _name: "/usr/bin/pwsh")

        executor = WindowsPowerShellActionExecutor(powershell_executable="pwsh")
        report = await executor.preflight()
        assert report["ok"] is False
        windows_check = next(item for item in report["checks"] if item["name"] == "windows_host")
        assert windows_check["ok"] is False

    asyncio.run(scenario())


def test_windows_executor_preflight_reports_success_on_windows(monkeypatch):
    async def scenario():
        monkeypatch.setattr("app.action_executor._is_windows_platform", lambda: True)
        monkeypatch.setattr(
            "app.action_executor.shutil.which",
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
