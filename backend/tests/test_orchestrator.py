import asyncio

from app.orchestrator import TaskOrchestrator
from app.schemas import TaskAction, TaskApproveRequest, TaskPlanRequest, TaskStepPlan


def test_drain_updates_waits_for_pending_callbacks():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def on_update(task):
            started.set()
            await release.wait()
            calls.append(task.task_id)

        orchestrator = TaskOrchestrator(on_task_update=on_update)
        await orchestrator.create_task("drain pending callbacks")
        await asyncio.wait_for(started.wait(), timeout=0.5)

        drain_job = asyncio.create_task(orchestrator.drain_updates(timeout_s=0.5))
        await asyncio.sleep(0.05)
        assert not drain_job.done()

        release.set()
        drained = await asyncio.wait_for(drain_job, timeout=0.5)
        assert drained is True
        assert len(calls) == 1

    asyncio.run(scenario())


def test_drain_updates_timeout_reports_pending_jobs():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        async def on_update(_task):
            started.set()
            await release.wait()

        orchestrator = TaskOrchestrator(on_task_update=on_update)
        await orchestrator.create_task("timeout path")
        await asyncio.wait_for(started.wait(), timeout=0.5)

        drained = await orchestrator.drain_updates(timeout_s=0.01)
        assert drained is False

        release.set()
        drained_after_release = await orchestrator.drain_updates(timeout_s=0.5)
        assert drained_after_release is True

    asyncio.run(scenario())


def test_get_task_returns_copy_not_internal_reference():
    async def scenario():
        orchestrator = TaskOrchestrator()
        created = await orchestrator.create_task("copy safety")

        first = await orchestrator.get_task(created.task_id)
        assert first is not None
        first.status = "failed"
        first.last_error = "mutated externally"

        second = await orchestrator.get_task(created.task_id)
        assert second is not None
        assert second.status != "failed" or second.last_error != "mutated externally"

    asyncio.run(scenario())


def test_list_tasks_returns_copies_not_internal_references():
    async def scenario():
        orchestrator = TaskOrchestrator()
        await orchestrator.create_task("list copy safety")

        listed = await orchestrator.list_tasks(limit=10)
        assert listed
        listed[0].status = "failed"
        listed[0].last_error = "mutated list item"

        latest = await orchestrator.list_tasks(limit=1)
        assert latest
        assert latest[0].status != "failed" or latest[0].last_error != "mutated list item"

    asyncio.run(scenario())


def test_hydrate_marks_waiting_approval_task_failed():
    async def scenario():
        orchestrator = TaskOrchestrator()
        created = await orchestrator.create_task("Approval workflow")
        await orchestrator.set_plan(
            created.task_id,
            TaskPlanRequest(
                steps=[
                    TaskStepPlan(
                        action=TaskAction(
                            action="send_or_submit",
                            description="Requires approval",
                            irreversible=True,
                        ),
                        preconditions=[],
                        postconditions=[],
                    )
                ]
            ),
        )
        waiting = await orchestrator.run_task(created.task_id)
        assert waiting.status == "waiting_approval"
        assert waiting.approval_token

        restored = TaskOrchestrator()
        await restored.hydrate_tasks([waiting])
        hydrated = await restored.get_task(waiting.task_id)
        assert hydrated is not None
        assert hydrated.status == "failed"
        assert hydrated.approval_token is None
        assert "restored after restart" in (hydrated.last_error or "")

    asyncio.run(scenario())


def test_approve_resumes_waiting_task_and_completes():
    async def scenario():
        orchestrator = TaskOrchestrator()
        created = await orchestrator.create_task("approve and continue")
        await orchestrator.set_plan(
            created.task_id,
            TaskPlanRequest(
                steps=[
                    TaskStepPlan(
                        action=TaskAction(
                            action="send_or_submit",
                            description="Requires approval",
                            irreversible=True,
                        ),
                        preconditions=[],
                        postconditions=[],
                    ),
                    TaskStepPlan(
                        action=TaskAction(
                            action="verify_outcome",
                            description="Finalize task",
                        ),
                        preconditions=[],
                        postconditions=[],
                    ),
                ]
            ),
        )

        waiting = await orchestrator.run_task(created.task_id)
        assert waiting.status == "waiting_approval"
        assert waiting.approval_token

        completed = await orchestrator.approve(
            created.task_id,
            TaskApproveRequest(approval_token=waiting.approval_token),
        )
        assert completed.status == "completed"
        assert completed.approval_token is None
        assert completed.current_step_index is None
        assert all(step.status == "succeeded" for step in completed.steps)

    asyncio.run(scenario())


# --- DesktopContext capture tests ---

from datetime import datetime, timezone
from unittest.mock import AsyncMock

from app.action_executor import ActionExecutionResult, TaskActionExecutor
from app.schemas import WindowEvent


class _ContextCapturingExecutor(TaskActionExecutor):
    mode = "test-capture"

    def __init__(self):
        self.captured_contexts = []

    async def execute(self, action: TaskAction, *, objective: str, desktop_context=None) -> ActionExecutionResult:
        self.captured_contexts.append(desktop_context)
        return ActionExecutionResult(
            ok=True,
            result={"executor": self.mode, "action": action.action, "ok": True},
        )

    def status(self):
        return {"mode": self.mode, "available": True}


def test_orchestrator_captures_context_from_state_store():
    async def scenario():
        event = WindowEvent(
            hwnd="0x1234",
            title="Outlook - Inbox",
            process_exe="outlook.exe",
            pid=100,
            timestamp=datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        mock_store = AsyncMock()
        mock_store.current = AsyncMock(return_value=event)

        executor = _ContextCapturingExecutor()
        orchestrator = TaskOrchestrator(
            action_executor=executor,
            state_store=mock_store,
        )
        created = await orchestrator.create_task("Test context capture")
        await orchestrator.set_plan(
            created.task_id,
            TaskPlanRequest(
                steps=[
                    TaskStepPlan(
                        action=TaskAction(action="observe_desktop", description="observe"),
                    )
                ]
            ),
        )
        result = await orchestrator.run_task(created.task_id)
        assert result.status == "completed"
        assert len(executor.captured_contexts) == 1
        ctx = executor.captured_contexts[0]
        assert ctx is not None
        assert ctx.window_title == "Outlook - Inbox"
        assert ctx.process_exe == "outlook.exe"

    asyncio.run(scenario())


def test_orchestrator_works_without_state_store():
    async def scenario():
        executor = _ContextCapturingExecutor()
        orchestrator = TaskOrchestrator(action_executor=executor)
        created = await orchestrator.create_task("No state store")
        await orchestrator.set_plan(
            created.task_id,
            TaskPlanRequest(
                steps=[
                    TaskStepPlan(
                        action=TaskAction(action="observe_desktop", description="observe"),
                    )
                ]
            ),
        )
        result = await orchestrator.run_task(created.task_id)
        assert result.status == "completed"
        assert len(executor.captured_contexts) == 1
        assert executor.captured_contexts[0] is None

    asyncio.run(scenario())


def test_orchestrator_handles_empty_state_store():
    async def scenario():
        mock_store = AsyncMock()
        mock_store.current = AsyncMock(return_value=None)

        executor = _ContextCapturingExecutor()
        orchestrator = TaskOrchestrator(
            action_executor=executor,
            state_store=mock_store,
        )
        created = await orchestrator.create_task("Empty state store")
        await orchestrator.set_plan(
            created.task_id,
            TaskPlanRequest(
                steps=[
                    TaskStepPlan(
                        action=TaskAction(action="observe_desktop", description="observe"),
                    )
                ]
            ),
        )
        result = await orchestrator.run_task(created.task_id)
        assert result.status == "completed"
        assert len(executor.captured_contexts) == 1
        assert executor.captured_contexts[0] is None

    asyncio.run(scenario())
