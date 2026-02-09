from __future__ import annotations

import json
from typing import Any, List, Optional, Protocol

from .schemas import TaskAction, TaskStepPlan

PLAN_JSON_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "description": {"type": "string"},
            "parameters": {"type": "object"},
            "irreversible": {"type": "boolean"},
            "preconditions": {"type": "array", "items": {"type": "string"}},
            "postconditions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["action", "description"],
    },
}

PLANNER_MODE_DETERMINISTIC = "deterministic"
PLANNER_MODE_AUTO = "auto"
PLANNER_MODE_OLLAMA_REQUIRED = "ollama_required"
_VALID_PLANNER_MODES = {
    PLANNER_MODE_DETERMINISTIC,
    PLANNER_MODE_AUTO,
    PLANNER_MODE_OLLAMA_REQUIRED,
}
PLANNER_SUPPORTED_MODES = tuple(sorted(_VALID_PLANNER_MODES))


def normalize_planner_mode(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized not in _VALID_PLANNER_MODES:
        raise ValueError(
            f"invalid autonomy planner mode: {mode} "
            f"(expected one of: {', '.join(PLANNER_SUPPORTED_MODES)})"
        )
    return normalized


class AutonomyPlanner(Protocol):
    async def build_plan(self, objective: str) -> List[TaskStepPlan]:
        ...


class DeterministicAutonomyPlanner:
    def build_plan_sync(self, objective: str) -> List[TaskStepPlan]:
        text = objective.lower()
        steps: List[TaskStepPlan] = [
            TaskStepPlan(
                action=TaskAction(
                    action="observe_desktop",
                    description="Capture desktop context and active target.",
                ),
                preconditions=["runtime connected"],
                postconditions=["context snapshot captured"],
            )
        ]

        if "outlook" in text or "email" in text or "mail" in text:
            steps.append(
                TaskStepPlan(
                    action=TaskAction(
                        action="open_application",
                        parameters={"application": "Outlook"},
                        description="Open Outlook and bring it to foreground.",
                    ),
                    preconditions=["desktop unlocked"],
                    postconditions=["outlook focused"],
                )
            )

        if "search" in text:
            steps.append(
                TaskStepPlan(
                    action=TaskAction(
                        action="focus_search",
                        description="Focus search input for current app.",
                    ),
                    preconditions=["target app focused"],
                    postconditions=["search field focused"],
                )
            )

        if "reply" in text or "draft" in text or "type" in text:
            steps.append(
                TaskStepPlan(
                    action=TaskAction(
                        action="compose_text",
                        description="Generate and type response draft.",
                    ),
                    preconditions=["editable compose field available"],
                    postconditions=["draft text present"],
                )
            )

        if _contains_irreversible_action(text):
            steps.append(
                TaskStepPlan(
                    action=TaskAction(
                        action="send_or_submit",
                        description="Execute irreversible action.",
                        irreversible=True,
                    ),
                    preconditions=["review checkpoint passed"],
                    postconditions=["external side effect acknowledged"],
                )
            )

        steps.append(
            TaskStepPlan(
                action=TaskAction(
                    action="verify_outcome",
                    description="Verify objective completion and finalize task.",
                ),
                preconditions=["all prior steps executed"],
                postconditions=["objective completed"],
            )
        )
        return steps

    async def build_plan(self, objective: str) -> List[TaskStepPlan]:
        return self.build_plan_sync(objective)


class OllamaAutonomyPlanner:
    _ALLOWED_ACTIONS = {
        "observe_desktop",
        "open_application",
        "focus_search",
        "compose_text",
        "send_or_submit",
        "verify_outcome",
    }

    def __init__(
        self,
        ollama,
        fallback: Optional[AutonomyPlanner] = None,
        mode: str = PLANNER_MODE_AUTO,
    ) -> None:
        normalized_mode = normalize_planner_mode(mode)
        self._ollama = ollama
        self._fallback = fallback or DeterministicAutonomyPlanner()
        self._mode = normalized_mode

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> str:
        self._mode = normalize_planner_mode(mode)
        return self._mode

    async def build_plan(self, objective: str) -> List[TaskStepPlan]:
        if self._mode == PLANNER_MODE_DETERMINISTIC or self._ollama is None:
            return await self._fallback.build_plan(objective)

        if not await self._ollama.available():
            if self._mode == PLANNER_MODE_OLLAMA_REQUIRED:
                raise RuntimeError("ollama planner required but Ollama is unavailable")
            return await self._fallback.build_plan(objective)

        prompt = _build_plan_prompt(objective)
        response = None
        used_structured_output = False

        if hasattr(self._ollama, "chat"):
            messages = [{"role": "user", "content": prompt}]
            response = await self._ollama.chat(messages, format=PLAN_JSON_SCHEMA)
            used_structured_output = True

        if response is None:
            response = await self._ollama.generate(prompt)
            used_structured_output = False

        parsed = self._parse_response(response or "", used_structured_output=used_structured_output)
        if not parsed:
            if self._mode == PLANNER_MODE_OLLAMA_REQUIRED:
                raise RuntimeError("ollama planner required but returned invalid plan JSON")
            return await self._fallback.build_plan(objective)

        return parsed

    def _parse_response(self, response: str, used_structured_output: bool = False) -> List[TaskStepPlan]:
        text = (response or "").strip()
        if not text:
            return []
        if not used_structured_output and text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
                text = "\n".join(lines[1:-1]).strip()

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        if not payload:
            return []

        steps: List[TaskStepPlan] = []
        for item in payload:
            if not isinstance(item, dict):
                return []
            action_name = str(item.get("action", "")).strip()
            if action_name not in self._ALLOWED_ACTIONS:
                return []
            params = item.get("parameters", {})
            if not isinstance(params, dict):
                return []
            irreversible = bool(item.get("irreversible", False))
            description = str(item.get("description", "")).strip()

            steps.append(
                TaskStepPlan(
                    action=TaskAction(
                        action=action_name,
                        parameters=params,
                        description=description,
                        irreversible=irreversible,
                    ),
                    preconditions=_as_text_list(item.get("preconditions")),
                    postconditions=_as_text_list(item.get("postconditions")),
                )
            )

        has_observe = any(step.action.action == "observe_desktop" for step in steps)
        has_verify = any(step.action.action == "verify_outcome" for step in steps)
        if not has_observe:
            steps.insert(
                0,
                TaskStepPlan(
                    action=TaskAction(
                        action="observe_desktop",
                        description="Capture desktop context and active target.",
                    ),
                    preconditions=["runtime connected"],
                    postconditions=["context snapshot captured"],
                ),
            )
        if not has_verify:
            steps.append(
                TaskStepPlan(
                    action=TaskAction(
                        action="verify_outcome",
                        description="Verify objective completion and finalize task.",
                    ),
                    preconditions=["all prior steps executed"],
                    postconditions=["objective completed"],
                )
            )
        return steps


def _contains_irreversible_action(text: str) -> bool:
    keywords = {"send", "submit", "delete", "publish", "transfer", "buy", "purchase"}
    return any(word in text for word in keywords)


def _as_text_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _build_plan_prompt(objective: str) -> str:
    return (
        "Create a deterministic desktop action plan for this objective. "
        "Return JSON only, with no markdown.\n\n"
        "Response format: a JSON array of steps where each step is an object with keys:\n"
        "- action: one of observe_desktop, open_application, focus_search, compose_text, "
        "send_or_submit, verify_outcome\n"
        "- description: short string\n"
        "- parameters: object (optional)\n"
        "- irreversible: boolean (optional, true only for send_or_submit when needed)\n"
        "- preconditions: array of strings\n"
        "- postconditions: array of strings\n\n"
        "Objective:\n"
        f"{objective}"
    )
