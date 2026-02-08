import asyncio
import time

from app.autonomy import AutonomousRunner
from app.orchestrator import TaskOrchestrator
from app.schemas import AutonomyApproveRequest, AutonomyStartRequest


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


def test_approve_update_callback_can_read_runner_without_deadlock():
    async def scenario():
        orchestrator = TaskOrchestrator()
        runner = None

        async def on_run_update(_run):
            # Re-entrant read should not deadlock against runner lock.
            assert runner is not None
            await runner.list_runs(limit=5)

        runner = AutonomousRunner(orchestrator, on_run_update=on_run_update)
        started = await runner.start(
            AutonomyStartRequest(
                objective="Open outlook, draft reply, then send email",
                max_iterations=20,
                auto_approve_irreversible=False,
            )
        )

        waiting = await _wait_for_status(runner, started.run_id, "waiting_approval")
        assert waiting.approval_token

        approved = await asyncio.wait_for(
            runner.approve(
                started.run_id, AutonomyApproveRequest(approval_token=waiting.approval_token)
            ),
            timeout=0.5,
        )
        assert approved.status == "completed"

    asyncio.run(scenario())


def test_fail_path_update_callback_can_read_runner_without_deadlock(monkeypatch):
    async def scenario():
        orchestrator = TaskOrchestrator()
        runner = None

        async def on_run_update(_run):
            assert runner is not None
            await runner.list_runs(limit=5)

        async def fail_run_task(_task_id):
            raise RuntimeError("boom")

        monkeypatch.setattr(orchestrator, "run_task", fail_run_task)
        runner = AutonomousRunner(orchestrator, on_run_update=on_run_update)
        started = await runner.start(
            AutonomyStartRequest(
                objective="Observe desktop and verify outcome",
                max_iterations=5,
                auto_approve_irreversible=False,
            )
        )

        failed = await _wait_for_status(runner, started.run_id, "failed")
        assert failed.last_error is not None
        assert "boom" in failed.last_error

    asyncio.run(scenario())


def test_cancel_update_callback_can_read_runner_without_deadlock():
    async def scenario():
        orchestrator = TaskOrchestrator()
        runner = None

        async def on_run_update(_run):
            assert runner is not None
            await runner.list_runs(limit=5)

        runner = AutonomousRunner(orchestrator, on_run_update=on_run_update)
        started = await runner.start(
            AutonomyStartRequest(
                objective="Open outlook, draft reply, then send email",
                max_iterations=20,
                auto_approve_irreversible=False,
            )
        )

        waiting = await _wait_for_status(runner, started.run_id, "waiting_approval")
        assert waiting.approval_token

        cancelled = await asyncio.wait_for(runner.cancel(started.run_id), timeout=0.5)
        assert cancelled.status == "cancelled"

    asyncio.run(scenario())


def test_get_run_returns_copy_not_internal_reference():
    async def scenario():
        runner = AutonomousRunner(TaskOrchestrator())
        started = await runner.start(
            AutonomyStartRequest(
                objective="Observe desktop and verify outcome",
                max_iterations=5,
                auto_approve_irreversible=False,
            )
        )

        first = await runner.get_run(started.run_id)
        assert first is not None
        first.status = "failed"
        first.last_error = "mutated externally"

        second = await runner.get_run(started.run_id)
        assert second is not None
        assert second.status != "failed" or second.last_error != "mutated externally"

    asyncio.run(scenario())


def test_list_runs_returns_copies_not_internal_references():
    async def scenario():
        runner = AutonomousRunner(TaskOrchestrator())
        started = await runner.start(
            AutonomyStartRequest(
                objective="Observe desktop and verify outcome",
                max_iterations=5,
                auto_approve_irreversible=False,
            )
        )

        runs = await runner.list_runs(limit=10)
        assert runs
        runs[0].status = "failed"
        runs[0].last_error = "mutated list item"

        latest = await runner.get_run(started.run_id)
        assert latest is not None
        assert latest.status != "failed" or latest.last_error != "mutated list item"

    asyncio.run(scenario())


def test_shutdown_marks_inflight_runs_failed():
    async def scenario():
        runner = AutonomousRunner(TaskOrchestrator())
        started = await runner.start(
            AutonomyStartRequest(
                objective="Open outlook, draft reply, then send email",
                max_iterations=20,
                auto_approve_irreversible=False,
            )
        )

        waiting = await _wait_for_status(runner, started.run_id, "waiting_approval")
        assert waiting.approval_token

        await runner.shutdown()
        after = await runner.get_run(started.run_id)
        assert after is not None
        assert after.status == "failed"
        assert after.finished_at is not None
        assert after.approval_token is None
        assert "shutdown" in (after.last_error or "").lower()

    asyncio.run(scenario())
