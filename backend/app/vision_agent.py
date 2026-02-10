from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

VISION_AGENT_PROMPT = """\
You are DesktopAI, an autonomous desktop agent. You can see the user's screen and control their Windows desktop.

OBJECTIVE: {objective}

AVAILABLE ACTIONS (respond with exactly one JSON object):
- {{"action": "click", "parameters": {{"name": "ButtonName"}}, "reasoning": "why"}}
- {{"action": "click", "parameters": {{"automation_id": "btn_id"}}, "reasoning": "why"}}
- {{"action": "type_text", "parameters": {{"text": "content to type"}}, "reasoning": "why"}}
- {{"action": "send_keys", "parameters": {{"keys": "ctrl+c"}}, "reasoning": "why"}}
- {{"action": "open_application", "parameters": {{"application": "notepad.exe"}}, "reasoning": "why"}}
- {{"action": "focus_window", "parameters": {{"title": "Window Title"}}, "reasoning": "why"}}
- {{"action": "wait", "parameters": {{}}, "reasoning": "waiting for UI to update"}}
- {{"action": "done", "parameters": {{}}, "reasoning": "objective completed because..."}}

CURRENT OBSERVATION:
Window: {window_title}
Process: {process_exe}
{uia_section}

{history_section}

RULES:
1. Respond with ONLY a JSON object. No markdown, no explanation.
2. Each action should move you closer to the objective.
3. Use "done" when the objective is complete.
4. Use "wait" if you need the UI to settle after a previous action.
5. If stuck after 3 attempts, try a different approach.

Your action:"""


@dataclass(frozen=True)
class AgentObservation:
    screenshot_b64: Optional[str]
    uia_summary: Optional[str]
    window_title: str
    process_exe: str
    timestamp: datetime


@dataclass(frozen=True)
class AgentAction:
    action: str
    parameters: Dict[str, Any]
    reasoning: str
    confidence: float = 1.0


@dataclass
class AgentStep:
    observation: AgentObservation
    action: AgentAction
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class VisionAgent:
    def __init__(
        self,
        bridge,
        ollama,
        max_iterations: int = 15,
        vision_model: Optional[str] = None,
    ) -> None:
        self._bridge = bridge
        self._ollama = ollama
        self._max_iterations = max(1, max_iterations)
        self._vision_model = vision_model

    async def run(
        self,
        objective: str,
        on_step: Optional[Callable[[AgentStep], Any]] = None,
    ) -> List[AgentStep]:
        steps: List[AgentStep] = []

        for _ in range(self._max_iterations):
            observation = await self._observe()
            action = await self._reason(objective, observation, steps)

            step = AgentStep(observation=observation, action=action)

            if action.action == "done":
                step.result = {"status": "completed", "reasoning": action.reasoning}
                steps.append(step)
                if on_step:
                    on_step(step)
                break

            if action.action == "wait":
                step.result = {"status": "waiting"}
                steps.append(step)
                if on_step:
                    on_step(step)
                import asyncio
                await asyncio.sleep(0.5)
                continue

            try:
                result = await self._act(action)
                step.result = result
            except Exception as exc:
                step.error = str(exc)
                step.result = {"ok": False, "error": str(exc)}

            steps.append(step)
            if on_step:
                on_step(step)

        return steps

    async def _observe(self) -> AgentObservation:
        result = await self._bridge.execute("observe", timeout_s=10)
        return AgentObservation(
            screenshot_b64=result.get("screenshot_b64"),
            uia_summary=json.dumps(result.get("uia")) if result.get("uia") else None,
            window_title=result.get("result", {}).get("window_title", ""),
            process_exe=result.get("result", {}).get("process_exe", ""),
            timestamp=datetime.now(timezone.utc),
        )

    async def _reason(
        self,
        objective: str,
        observation: AgentObservation,
        history: List[AgentStep],
    ) -> AgentAction:
        uia_section = ""
        if observation.uia_summary:
            uia_section = f"UI Elements:\n{observation.uia_summary[:2000]}"

        history_lines = []
        for i, step in enumerate(history[-5:]):  # Last 5 steps for context
            history_lines.append(
                f"Step {i+1}: action={step.action.action}, "
                f"reasoning={step.action.reasoning}, "
                f"result={'ok' if step.error is None else f'error: {step.error}'}"
            )
        history_section = "HISTORY:\n" + "\n".join(history_lines) if history_lines else ""

        prompt = VISION_AGENT_PROMPT.format(
            objective=objective,
            window_title=observation.window_title,
            process_exe=observation.process_exe,
            uia_section=uia_section,
            history_section=history_section,
        )

        messages = [{"role": "user", "content": prompt}]

        try:
            if observation.screenshot_b64 and hasattr(self._ollama, "chat_with_images"):
                import base64
                screenshot_bytes = base64.b64decode(observation.screenshot_b64)
                response = await self._ollama.chat_with_images(
                    messages, [screenshot_bytes], model=self._vision_model,
                )
            else:
                response = await self._ollama.chat(messages)
        except Exception as exc:
            logger.warning("VisionAgent reasoning failed: %s", exc)
            return AgentAction(action="wait", parameters={}, reasoning=f"reasoning error: {exc}")

        return self._parse_action(response)

    async def _act(self, action: AgentAction) -> Dict[str, Any]:
        return await self._bridge.execute(
            action.action,
            action.parameters,
            timeout_s=10,
        )

    @staticmethod
    def _parse_action(response: Optional[str]) -> AgentAction:
        if not response:
            return AgentAction(action="wait", parameters={}, reasoning="empty response")

        text = response.strip()

        # Try to extract JSON from response
        # Handle cases where VLM wraps in markdown code blocks
        if "```" in text:
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_block = not in_block
                    continue
                if in_block:
                    json_lines.append(line)
            if json_lines:
                text = "\n".join(json_lines).strip()

        try:
            data = json.loads(text)
            return AgentAction(
                action=str(data.get("action", "wait")),
                parameters=dict(data.get("parameters", {})),
                reasoning=str(data.get("reasoning", "")),
                confidence=float(data.get("confidence", 1.0)),
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            logger.warning("VisionAgent: failed to parse action JSON: %s", text[:200])
            return AgentAction(action="wait", parameters={}, reasoning=f"parse error: {text[:100]}")
