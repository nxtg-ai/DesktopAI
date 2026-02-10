import asyncio

import pytest
from app.autonomy import AutonomousRunner
from app.orchestrator import TaskOrchestrator
from app.planner import DeterministicAutonomyPlanner, OllamaAutonomyPlanner
from app.schemas import AutonomyStartRequest, TaskAction, TaskStepPlan


class _DummyOllama:
    def __init__(self, available: bool, response: str | None):
        self._available = available
        self._response = response
        self.generate_calls = 0

    async def available(self) -> bool:
        return self._available

    async def generate(self, _prompt: str) -> str | None:
        self.generate_calls += 1
        return self._response


class _StubPlanner:
    async def build_plan(self, _objective: str):
        return [
            TaskStepPlan(
                action=TaskAction(action="focus_search", description="Focus search"),
                preconditions=["target app focused"],
                postconditions=["search field focused"],
            )
        ]


async def _wait_for_status(runner: AutonomousRunner, run_id: str, expected: str, timeout_s: float = 1.5):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        run = await runner.get_run(run_id)
        if run is not None and run.status == expected:
            return run
        await asyncio.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach {expected}")


def test_ollama_planner_builds_steps_from_json_response():
    async def scenario():
        fallback = DeterministicAutonomyPlanner()
        ollama = _DummyOllama(
            available=True,
            response=(
                '[{"action":"observe_desktop","description":"Capture context","preconditions":["runtime connected"],'
                '"postconditions":["context snapshot captured"]},'
                '{"action":"send_or_submit","description":"Send reply","irreversible":true,'
                '"preconditions":["review checkpoint passed"],"postconditions":["external side effect acknowledged"]},'
                '{"action":"verify_outcome","description":"Verify completion","preconditions":["all prior steps executed"],'
                '"postconditions":["objective completed"]}]'
            ),
        )
        planner = OllamaAutonomyPlanner(ollama=ollama, fallback=fallback, mode="auto")

        steps = await planner.build_plan("Send the draft email")
        assert len(steps) == 3
        assert steps[1].action.action == "send_or_submit"
        assert steps[1].action.irreversible is True

    asyncio.run(scenario())


def test_ollama_planner_falls_back_when_model_output_invalid():
    async def scenario():
        fallback = DeterministicAutonomyPlanner()
        ollama = _DummyOllama(available=True, response="this is not json")
        planner = OllamaAutonomyPlanner(ollama=ollama, fallback=fallback, mode="auto")

        steps = await planner.build_plan("Observe desktop and verify outcome")
        assert len(steps) == 2
        assert steps[0].action.action == "observe_desktop"
        assert steps[-1].action.action == "verify_outcome"

    asyncio.run(scenario())


def test_ollama_planner_falls_back_when_unavailable():
    async def scenario():
        fallback = DeterministicAutonomyPlanner()
        ollama = _DummyOllama(available=False, response=None)
        planner = OllamaAutonomyPlanner(ollama=ollama, fallback=fallback, mode="auto")

        steps = await planner.build_plan("Observe desktop and verify outcome")
        assert len(steps) == 2
        assert steps[0].action.action == "observe_desktop"
        assert steps[-1].action.action == "verify_outcome"

    asyncio.run(scenario())


def test_ollama_planner_mode_deterministic_skips_ollama_calls():
    async def scenario():
        fallback = DeterministicAutonomyPlanner()
        ollama = _DummyOllama(
            available=True,
            response='[{"action":"compose_text","description":"not used"}]',
        )
        planner = OllamaAutonomyPlanner(ollama=ollama, fallback=fallback, mode="deterministic")

        steps = await planner.build_plan("Observe desktop and verify outcome")
        assert len(steps) == 2
        assert steps[0].action.action == "observe_desktop"
        assert steps[-1].action.action == "verify_outcome"
        assert ollama.generate_calls == 0

    asyncio.run(scenario())


def test_ollama_planner_mode_required_raises_when_unavailable():
    async def scenario():
        fallback = DeterministicAutonomyPlanner()
        ollama = _DummyOllama(available=False, response=None)
        planner = OllamaAutonomyPlanner(ollama=ollama, fallback=fallback, mode="ollama_required")
        with pytest.raises(RuntimeError, match="required"):
            await planner.build_plan("Observe desktop and verify outcome")

    asyncio.run(scenario())


def test_ollama_planner_mode_required_raises_on_invalid_output():
    async def scenario():
        fallback = DeterministicAutonomyPlanner()
        ollama = _DummyOllama(available=True, response="not-json")
        planner = OllamaAutonomyPlanner(ollama=ollama, fallback=fallback, mode="ollama_required")
        with pytest.raises(RuntimeError, match="invalid"):
            await planner.build_plan("Observe desktop and verify outcome")

    asyncio.run(scenario())


def test_ollama_planner_set_mode_validates_values():
    async def scenario():
        fallback = DeterministicAutonomyPlanner()
        planner = OllamaAutonomyPlanner(ollama=_DummyOllama(True, "[]"), fallback=fallback, mode="auto")
        planner.set_mode("deterministic")
        assert planner.mode == "deterministic"
        with pytest.raises(ValueError, match="invalid autonomy planner mode"):
            planner.set_mode("invalid")

    asyncio.run(scenario())


class _ChatCapturingOllama:
    def __init__(self, available: bool, response: str | None):
        self._available = available
        self._response = response
        self.chat_calls = []

    async def available(self) -> bool:
        return self._available

    async def generate(self, prompt: str) -> str | None:
        return self._response

    async def chat(self, messages: list, format=None) -> str | None:
        self.chat_calls.append(messages)
        return self._response


def test_ollama_planner_includes_desktop_context_in_prompt():
    async def scenario():
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock

        from app.schemas import WindowEvent

        event = WindowEvent(
            hwnd="0x1234",
            title="Outlook - Inbox",
            process_exe="outlook.exe",
            pid=100,
            timestamp=datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        mock_store = AsyncMock()
        mock_store.current = AsyncMock(return_value=event)

        ollama = _ChatCapturingOllama(
            available=True,
            response='[{"action":"observe_desktop","description":"obs"},{"action":"verify_outcome","description":"ver"}]',
        )
        planner = OllamaAutonomyPlanner(
            ollama=ollama,
            mode="auto",
            state_store=mock_store,
        )
        steps = await planner.build_plan("reply to email")
        assert len(steps) == 2
        assert ollama.chat_calls
        prompt = ollama.chat_calls[0][0]["content"]
        assert "Outlook - Inbox" in prompt
        assert "outlook.exe" in prompt

    asyncio.run(scenario())


def test_ollama_planner_works_without_state_store():
    async def scenario():
        ollama = _ChatCapturingOllama(
            available=True,
            response='[{"action":"observe_desktop","description":"obs"},{"action":"verify_outcome","description":"ver"}]',
        )
        planner = OllamaAutonomyPlanner(
            ollama=ollama,
            mode="auto",
        )
        steps = await planner.build_plan("check desktop")
        assert len(steps) == 2
        assert ollama.chat_calls
        prompt = ollama.chat_calls[0][0]["content"]
        assert "Current Desktop State" not in prompt

    asyncio.run(scenario())


class _TrajectoryCapturingOllama:
    def __init__(self, available: bool, response: str | None):
        self._available = available
        self._response = response
        self.chat_calls = []

    async def available(self) -> bool:
        return self._available

    async def generate(self, prompt: str) -> str | None:
        return self._response

    async def chat(self, messages: list, format=None) -> str | None:
        self.chat_calls.append(messages)
        return self._response


def test_ollama_planner_includes_trajectory_context_in_prompt():
    async def scenario():
        from unittest.mock import AsyncMock

        from app.memory import Trajectory

        traj = Trajectory(
            trajectory_id="t1",
            objective="reply to email",
            steps_json='[{"action": "click", "reasoning": "click reply", "error": null}]',
            outcome="completed",
            step_count=1,
            created_at="2025-07-01T00:00:00+00:00",
        )

        traj_store = AsyncMock()
        traj_store.find_similar = AsyncMock(return_value=[traj])

        ollama = _TrajectoryCapturingOllama(
            available=True,
            response='[{"action":"observe_desktop","description":"obs"},{"action":"verify_outcome","description":"ver"}]',
        )
        planner = OllamaAutonomyPlanner(
            ollama=ollama,
            mode="auto",
            trajectory_store=traj_store,
        )
        steps = await planner.build_plan("reply to email")
        assert len(steps) == 2
        assert ollama.chat_calls
        prompt = ollama.chat_calls[0][0]["content"]
        assert "Past Experience" in prompt
        assert "reply to email" in prompt

    asyncio.run(scenario())


def test_ollama_planner_trajectory_failure_nonfatal():
    async def scenario():
        from unittest.mock import AsyncMock

        traj_store = AsyncMock()
        traj_store.find_similar = AsyncMock(side_effect=RuntimeError("db gone"))

        ollama = _TrajectoryCapturingOllama(
            available=True,
            response='[{"action":"observe_desktop","description":"obs"},{"action":"verify_outcome","description":"ver"}]',
        )
        planner = OllamaAutonomyPlanner(
            ollama=ollama,
            mode="auto",
            trajectory_store=traj_store,
        )
        # Should not raise
        steps = await planner.build_plan("test objective")
        assert len(steps) == 2

    asyncio.run(scenario())


def test_ollama_planner_no_trajectory_store_works():
    async def scenario():
        ollama = _TrajectoryCapturingOllama(
            available=True,
            response='[{"action":"observe_desktop","description":"obs"},{"action":"verify_outcome","description":"ver"}]',
        )
        planner = OllamaAutonomyPlanner(
            ollama=ollama,
            mode="auto",
            trajectory_store=None,
        )
        steps = await planner.build_plan("test objective")
        assert len(steps) == 2
        prompt = ollama.chat_calls[0][0]["content"]
        assert "Past Experience" not in prompt

    asyncio.run(scenario())


def test_autonomous_runner_uses_injected_planner_steps():
    async def scenario():
        orchestrator = TaskOrchestrator()
        runner = AutonomousRunner(orchestrator, planner=_StubPlanner())

        run = await runner.start(
            AutonomyStartRequest(
                objective="No search keyword in objective",
                max_iterations=8,
                auto_approve_irreversible=False,
            )
        )

        await _wait_for_status(runner, run.run_id, "completed")
        task = await orchestrator.get_task(run.task_id)
        assert task is not None
        assert [step.action.action for step in task.steps] == ["focus_search"]

    asyncio.run(scenario())
