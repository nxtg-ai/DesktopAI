"""Sprint 3 tests: personality modes, action_executor subpackage, error learning."""

import pytest
from app.memory import (
    ErrorLesson,
    TrajectoryStore,
    format_error_lessons,
)
from app.schemas import ChatRequest, PersonalityMode
from app.vision_agent import AgentAction, AgentStep

# ── Personality mode schema tests ────────────────────────────────────────

def test_personality_mode_literal_values():
    assert PersonalityMode.__args__ == ("copilot", "assistant", "operator")


def test_chat_request_default_personality():
    req = ChatRequest(message="hello")
    assert req.personality_mode is None


def test_chat_request_copilot_mode():
    req = ChatRequest(message="hello", personality_mode="copilot")
    assert req.personality_mode == "copilot"


def test_chat_request_operator_mode():
    req = ChatRequest(message="hello", personality_mode="operator")
    assert req.personality_mode == "operator"


def test_chat_request_invalid_personality_rejected():
    with pytest.raises(Exception):
        ChatRequest(message="hello", personality_mode="robot")


# ── Action executor subpackage import tests ──────────────────────────────

def test_subpackage_exports_all_classes():
    from app.action_executor import (
        ActionExecutionResult,
        BridgeActionExecutor,
        SimulatedTaskActionExecutor,
        TaskActionExecutor,
        WindowsPowerShellActionExecutor,
        build_action_executor,
        build_action_executors,
    )
    assert ActionExecutionResult is not None
    assert TaskActionExecutor is not None
    assert SimulatedTaskActionExecutor is not None
    assert WindowsPowerShellActionExecutor is not None
    assert BridgeActionExecutor is not None
    assert build_action_executor is not None
    assert build_action_executors is not None


def test_subpackage_submodule_imports():
    from app.action_executor.base import ActionExecutionResult, TaskActionExecutor
    from app.action_executor.bridge import BridgeActionExecutor
    from app.action_executor.powershell import WindowsPowerShellActionExecutor
    from app.action_executor.simulated import SimulatedTaskActionExecutor
    assert ActionExecutionResult is not None
    assert TaskActionExecutor is not None
    assert SimulatedTaskActionExecutor is not None
    assert WindowsPowerShellActionExecutor is not None
    assert BridgeActionExecutor is not None


def test_playwright_executor_imports_from_subpackage():
    """Verify PlaywrightExecutor still imports base types from the subpackage."""
    from app.action_executor import TaskActionExecutor
    from app.playwright_executor import PlaywrightExecutor
    assert issubclass(PlaywrightExecutor, TaskActionExecutor)


# ── Error learning tests ─────────────────────────────────────────────────

def _make_store():
    return TrajectoryStore(path=":memory:")


def _make_step(action: str, error: str = None, reasoning: str = ""):
    return AgentStep(
        observation=None,
        action=AgentAction(
            action=action,
            parameters={},
            reasoning=reasoning,
            confidence=0.8,
        ),
        result={"ok": error is None} if error is None else {"ok": False, "error": error},
        error=error,
    )


@pytest.mark.asyncio
async def test_extract_error_lessons_from_failed_trajectory():
    store = _make_store()
    steps = [
        _make_step("open_application", reasoning="opening outlook"),
        _make_step("click", error="element not found", reasoning="clicking reply"),
    ]
    await store.save_trajectory("t1", "reply to email", steps, "failed")
    lessons = await store.extract_error_lessons("reply to email", limit=5)
    assert len(lessons) == 1
    assert lessons[0].action == "click"
    assert "element not found" in lessons[0].error
    assert lessons[0].objective == "reply to email"


@pytest.mark.asyncio
async def test_extract_error_lessons_empty_when_no_failures():
    store = _make_store()
    steps = [_make_step("open_application", reasoning="opened outlook")]
    await store.save_trajectory("t1", "open outlook", steps, "completed")
    lessons = await store.extract_error_lessons("open outlook", limit=5)
    assert len(lessons) == 0


@pytest.mark.asyncio
async def test_extract_error_lessons_falls_back_to_recent():
    store = _make_store()
    steps = [_make_step("type_text", error="window lost focus", reasoning="typing text")]
    await store.save_trajectory("t1", "write document", steps, "failed")
    # Search for something completely different
    lessons = await store.extract_error_lessons("unrelated task xyz", limit=5)
    # Should still find the failure via fallback
    assert len(lessons) == 1
    assert lessons[0].action == "type_text"


@pytest.mark.asyncio
async def test_extract_error_lessons_respects_limit():
    store = _make_store()
    for i in range(10):
        steps = [_make_step(f"action_{i}", error=f"error_{i}", reasoning=f"step_{i}")]
        await store.save_trajectory(f"t{i}", f"task {i}", steps, "failed")
    lessons = await store.extract_error_lessons("task", limit=3)
    assert len(lessons) <= 3


def test_format_error_lessons_empty():
    assert format_error_lessons([]) == ""


def test_format_error_lessons_content():
    lessons = [
        ErrorLesson(
            objective="reply to email",
            action="click",
            error="element not found",
            reasoning="clicking reply button",
            trajectory_id="t1",
        ),
    ]
    result = format_error_lessons(lessons)
    assert "LESSONS FROM PAST FAILURES" in result
    assert "click" in result
    assert "element not found" in result
    assert "reply to email" in result


def test_format_error_lessons_truncation():
    lessons = [
        ErrorLesson(
            objective="x" * 200,
            action="action",
            error="e" * 200,
            reasoning="r" * 200,
            trajectory_id=f"t{i}",
        )
        for i in range(20)
    ]
    result = format_error_lessons(lessons, max_chars=200)
    assert len(result) <= 200
    assert result.endswith("...")


def test_error_lesson_dataclass():
    lesson = ErrorLesson(
        objective="test",
        action="click",
        error="not found",
        reasoning="clicking button",
        trajectory_id="t1",
    )
    assert lesson.objective == "test"
    assert lesson.action == "click"
    assert lesson.error == "not found"


# ── Personality prompt routing test ──────────────────────────────────────

def test_personality_prompts_defined():
    from app.routes.agent import _PERSONALITY_PROMPTS
    assert "copilot" in _PERSONALITY_PROMPTS
    assert "assistant" in _PERSONALITY_PROMPTS
    assert "operator" in _PERSONALITY_PROMPTS
    assert "concise" in _PERSONALITY_PROMPTS["copilot"].lower()
    assert "friendly" in _PERSONALITY_PROMPTS["assistant"].lower()
    assert "imperative" in _PERSONALITY_PROMPTS["operator"].lower()


def test_action_intent_detection():
    from app.routes.agent import _is_action_intent
    assert _is_action_intent("draft a reply") is True
    assert _is_action_intent("open outlook") is True
    assert _is_action_intent("what is the weather") is False
    assert _is_action_intent("how are you") is False
