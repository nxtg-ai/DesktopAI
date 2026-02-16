"""Reactive vision agent using VLM-guided observe-reason-act loop."""

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
- {{"action": "click", "parameters": {{"name": "ButtonName"}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "click", "parameters": {{"automation_id": "btn_id"}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "type_text", "parameters": {{"text": "content to type"}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "send_keys", "parameters": {{"keys": "ctrl+c"}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "open_application", "parameters": {{"application": "notepad.exe"}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "focus_window", "parameters": {{"title": "Window Title"}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "scroll", "parameters": {{"direction": "down", "amount": 3}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "double_click", "parameters": {{"name": "ItemName"}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "right_click", "parameters": {{"name": "ItemName"}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "wait", "parameters": {{}}, "reasoning": "waiting for UI to update", "confidence": 1.0}}
- {{"action": "done", "parameters": {{}}, "reasoning": "objective completed because...", "confidence": 0.95}}

CURRENT OBSERVATION:
Window: {window_title}
Process: {process_exe}
{uia_section}

{history_section}

{trajectory_section}
RULES:
1. Respond with ONLY a JSON object. No markdown, no explanation.
2. Each action should move you closer to the objective.
3. IMPORTANT: After each action, check if the objective has ALREADY been achieved. If yes, respond with action "done".
4. Use "wait" if you need the UI to settle after a previous action.
5. If stuck after 3 attempts, try a different approach.
6. Include a "confidence" field (0.0 to 1.0) indicating how sure you are this action is correct.
7. Do NOT repeat the same action more than twice. If the objective appears achieved, use "done".
8. IMPORTANT: Before typing text, ALWAYS use "focus_window" first to ensure the correct window has focus. Never type_text without first confirming the target window is focused.

Your action:"""

DETECTION_AGENT_PROMPT = """\
You are DesktopAI, an autonomous desktop agent. You can see a numbered list of UI elements detected on the user's screen.

OBJECTIVE: {objective}

DETECTED UI ELEMENTS:
{element_list}

Window: {window_title}
Process: {process_exe}

AVAILABLE ACTIONS (respond with exactly one JSON object):
- {{"action": "click", "parameters": {{"element_id": 3}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "click", "parameters": {{"x": 450, "y": 320}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "type_text", "parameters": {{"text": "content to type"}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "send_keys", "parameters": {{"keys": "ctrl+c"}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "open_application", "parameters": {{"application": "notepad.exe"}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "focus_window", "parameters": {{"title": "Window Title"}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "scroll", "parameters": {{"direction": "down", "amount": 3}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "double_click", "parameters": {{"element_id": 5}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "right_click", "parameters": {{"element_id": 5}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "wait", "parameters": {{}}, "reasoning": "waiting for UI to update", "confidence": 1.0}}
- {{"action": "done", "parameters": {{}}, "reasoning": "objective completed because...", "confidence": 0.95}}

{history_section}

{trajectory_section}
RULES:
1. Prefer clicking by element_id when the target is in the element list.
2. Use x/y coordinates (center of bbox) when element_id is ambiguous.
3. Respond with ONLY a JSON object. No markdown, no explanation.
4. Each action should move you closer to the objective.
5. IMPORTANT: After each action, check if the objective has ALREADY been achieved. If yes, respond with action "done".
6. Use "wait" if you need the UI to settle after a previous action.
7. If stuck after 3 attempts, try a different approach.
8. Include a "confidence" field (0.0 to 1.0).
9. Do NOT repeat the same action more than twice.
10. Before typing text, ALWAYS use "focus_window" first.

Your action:"""

CUA_AGENT_PROMPT = """\
You are DesktopAI, a computer-use agent. You can see the user's screen and control their Windows desktop using pixel coordinates.

OBJECTIVE: {objective}

AVAILABLE ACTIONS (respond with exactly one JSON object):
- {{"action": "click", "parameters": {{"x": 450, "y": 320}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "double_click", "parameters": {{"x": 450, "y": 320}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "right_click", "parameters": {{"x": 450, "y": 320}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "type_text", "parameters": {{"text": "content to type"}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "send_keys", "parameters": {{"keys": "ctrl+c"}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "open_application", "parameters": {{"application": "notepad.exe"}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "focus_window", "parameters": {{"title": "Window Title"}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "scroll", "parameters": {{"direction": "down", "amount": 3}}, "reasoning": "why", "confidence": 0.9}}
- {{"action": "wait", "parameters": {{}}, "reasoning": "waiting for UI to update", "confidence": 1.0}}
- {{"action": "done", "parameters": {{}}, "reasoning": "objective completed because...", "confidence": 0.95}}

CURRENT OBSERVATION:
Window: {window_title}
Process: {process_exe}
{uia_section}

{history_section}

{trajectory_section}
RULES:
1. Respond with ONLY a JSON object. No markdown, no explanation.
2. For click/double_click/right_click, use pixel coordinates (x, y) from the screenshot.
3. Each action should move you closer to the objective.
4. IMPORTANT: After each action, check if the objective has ALREADY been achieved. If yes, respond with action "done".
5. Use "wait" if you need the UI to settle after a previous action.
6. If stuck after 3 attempts, try a different approach.
7. Include a "confidence" field (0.0 to 1.0) indicating how sure you are this action is correct.
8. Do NOT repeat the same action more than twice.
9. Before typing text, ALWAYS use "focus_window" first.

Your action:"""


@dataclass(frozen=True)
class AgentObservation:
    screenshot_b64: Optional[str]
    uia_summary: Optional[str]
    window_title: str
    process_exe: str
    timestamp: datetime
    detections: Optional[List[Dict[str, Any]]] = None
    uia_elements: Optional[List[Dict[str, Any]]] = None


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
        min_confidence: float = 0.3,
        max_consecutive_errors: int = 3,
        error_backoff_ms: int = 500,
        trajectory_store=None,
        trajectory_max_chars: int = 1500,
        trajectory_max_results: int = 3,
        use_coordinates: bool = False,
        vision_mode: str = "auto",
        detection_merge_iou: float = 0.3,
    ) -> None:
        self._bridge = bridge
        self._ollama = ollama
        self._max_iterations = max(1, max_iterations)
        self._vision_model = vision_model
        self._min_confidence = max(0.0, min(1.0, min_confidence))
        self._max_consecutive_errors = max(1, max_consecutive_errors)
        self._error_backoff_ms = max(0, error_backoff_ms)
        self._trajectory_store = trajectory_store
        self._trajectory_max_chars = trajectory_max_chars
        self._trajectory_max_results = trajectory_max_results
        self._use_coordinates = use_coordinates
        self._vision_mode = vision_mode
        self._detection_merge_iou = detection_merge_iou
        self._merged_elements: Optional[List] = None

    async def run(
        self,
        objective: str,
        on_step: Optional[Callable[[AgentStep], Any]] = None,
    ) -> List[AgentStep]:
        import asyncio

        steps: List[AgentStep] = []
        consecutive_errors = 0
        consecutive_ollama_failures = 0

        # Query trajectory memory once at start
        trajectory_context = ""
        if self._trajectory_store:
            try:
                from .memory import format_error_lessons, format_trajectory_context
                similar = await self._trajectory_store.find_similar(
                    objective, limit=self._trajectory_max_results,
                )
                trajectory_context = format_trajectory_context(
                    similar, max_chars=self._trajectory_max_chars,
                )
                # Append error lessons from failed trajectories
                lessons = await self._trajectory_store.extract_error_lessons(
                    objective, limit=5,
                )
                if lessons:
                    lesson_text = format_error_lessons(lessons, max_chars=600)
                    if lesson_text:
                        trajectory_context = (
                            (trajectory_context + "\n\n" + lesson_text)
                            if trajectory_context
                            else lesson_text
                        )
            except Exception as exc:
                logger.warning("VisionAgent: trajectory lookup failed: %s", exc)

        _repeat_threshold = 3

        for _ in range(self._max_iterations):
            # Auto-done: if the same action has been repeated _repeat_threshold times
            if len(steps) >= _repeat_threshold:
                recent = steps[-_repeat_threshold:]
                actions = [s.action.action for s in recent]
                if len(set(actions)) == 1 and actions[0] not in ("wait", "done", "observe"):
                    logger.info(
                        "VisionAgent: action '%s' repeated %d times, auto-completing",
                        actions[0], _repeat_threshold,
                    )
                    done_action = AgentAction(
                        action="done",
                        parameters={},
                        reasoning=f"Auto-done: '{actions[0]}' repeated {_repeat_threshold} times — objective likely achieved or stuck",
                        confidence=0.7,
                    )
                    done_step = AgentStep(
                        observation=steps[-1].observation,
                        action=done_action,
                        result={"status": "completed", "reasoning": done_action.reasoning},
                    )
                    steps.append(done_step)
                    if on_step:
                        on_step(done_step)
                    break

            observation = await self._observe()
            action = await self._reason(objective, observation, steps, trajectory_context=trajectory_context)

            # Track consecutive Ollama failures (None/empty → wait fallback)
            if action.action == "wait" and "empty response" in action.reasoning:
                consecutive_ollama_failures += 1
                if consecutive_ollama_failures >= 2:
                    logger.warning(
                        "VisionAgent: %d consecutive Ollama failures, aborting",
                        consecutive_ollama_failures,
                    )
                    abort_action = AgentAction(
                        action="abort",
                        parameters={},
                        reasoning="LLM unavailable — 2 consecutive failures",
                    )
                    abort_step = AgentStep(
                        observation=observation,
                        action=abort_action,
                        result={"status": "failed", "reasoning": abort_action.reasoning},
                    )
                    steps.append(abort_step)
                    if on_step:
                        on_step(abort_step)
                    break
            else:
                consecutive_ollama_failures = 0

            step = AgentStep(observation=observation, action=action)

            if action.action == "done":
                step.result = {"status": "completed", "reasoning": action.reasoning}
                steps.append(step)
                if on_step:
                    on_step(step)
                break

            # Confidence gating: downgrade low-confidence actions to wait
            if action.action not in ("wait", "done") and action.confidence < self._min_confidence:
                logger.info(
                    "VisionAgent: confidence %.2f below threshold %.2f, waiting",
                    action.confidence, self._min_confidence,
                )
                gated = AgentAction(
                    action="wait",
                    parameters={},
                    reasoning=f"low confidence ({action.confidence:.2f}): {action.reasoning}",
                    confidence=action.confidence,
                )
                step = AgentStep(observation=observation, action=gated)
                step.result = {"status": "waiting", "gated_action": action.action}
                steps.append(step)
                if on_step:
                    on_step(step)
                await asyncio.sleep(0.5)
                continue

            if action.action == "wait":
                step.result = {"status": "waiting"}
                steps.append(step)
                if on_step:
                    on_step(step)
                await asyncio.sleep(0.5)
                continue

            try:
                result = await self._act(action)
                step.result = result
                consecutive_errors = 0
            except Exception as exc:
                step.error = str(exc)
                step.result = {"ok": False, "error": str(exc)}
                consecutive_errors += 1

                if consecutive_errors >= self._max_consecutive_errors:
                    logger.warning(
                        "VisionAgent: %d consecutive errors, aborting",
                        consecutive_errors,
                    )
                    steps.append(step)
                    if on_step:
                        on_step(step)
                    break

                # Exponential backoff on errors
                backoff_s = (self._error_backoff_ms / 1000.0) * (2 ** (consecutive_errors - 1))
                logger.info(
                    "VisionAgent: error %d/%d, backing off %.1fs",
                    consecutive_errors, self._max_consecutive_errors, backoff_s,
                )
                await asyncio.sleep(backoff_s)

            steps.append(step)
            if on_step:
                on_step(step)

        return steps

    async def _observe(self) -> AgentObservation:
        result = await self._bridge.execute("observe", timeout_s=10)
        uia_raw = result.get("uia")
        uia_elements = None
        if uia_raw and isinstance(uia_raw, dict):
            uia_elements = uia_raw.get("window_tree", [])
        return AgentObservation(
            screenshot_b64=result.get("screenshot_b64"),
            uia_summary=json.dumps(uia_raw) if uia_raw else None,
            window_title=result.get("result", {}).get("window_title", ""),
            process_exe=result.get("result", {}).get("process_exe", ""),
            timestamp=datetime.now(timezone.utc),
            detections=result.get("detections"),
            uia_elements=uia_elements,
        )

    def _should_use_detection(self, observation: AgentObservation) -> bool:
        """Decide whether to use the detection (text-only LLM) path."""
        if self._vision_mode == "vlm":
            return False
        if self._vision_mode == "detection":
            return True
        # "auto": use detection if we have detections
        return bool(observation.detections)

    async def _reason(
        self,
        objective: str,
        observation: AgentObservation,
        history: List[AgentStep],
        trajectory_context: str = "",
    ) -> AgentAction:
        if self._should_use_detection(observation):
            return await self._reason_detection(
                objective, observation, history, trajectory_context,
            )
        return await self._reason_vlm(
            objective, observation, history, trajectory_context,
        )

    async def _reason_detection(
        self,
        objective: str,
        observation: AgentObservation,
        history: List[AgentStep],
        trajectory_context: str = "",
    ) -> AgentAction:
        """Text-only reasoning using detected element list (no screenshot sent)."""
        from .detection_merger import format_element_list, merge_detections_with_uia

        detections = observation.detections or []
        uia_elements = observation.uia_elements or []

        merged = merge_detections_with_uia(
            detections,
            uia_elements,
            image_width=1024,
            image_height=768,
            iou_threshold=self._detection_merge_iou,
        )
        self._merged_elements = merged
        element_list = format_element_list(merged) if merged else "(no elements detected)"

        history_section = self._build_history_section(history)
        trajectory_section = ""
        if trajectory_context:
            trajectory_section = f"PAST EXPERIENCE (similar objectives attempted before):\n{trajectory_context}"

        prompt = DETECTION_AGENT_PROMPT.format(
            objective=objective,
            element_list=element_list,
            window_title=observation.window_title,
            process_exe=observation.process_exe,
            history_section=history_section,
            trajectory_section=trajectory_section,
        )

        messages = [{"role": "user", "content": prompt}]

        try:
            response = await self._ollama.chat(messages)
        except Exception as exc:
            logger.warning("VisionAgent detection reasoning failed: %s", exc)
            return AgentAction(action="wait", parameters={}, reasoning=f"reasoning error: {exc}")

        action = self._parse_action(response)

        # Resolve element_id → x/y coordinates for click actions
        if action.action in ("click", "double_click", "right_click"):
            params = dict(action.parameters)
            element_id = params.get("element_id")
            if element_id is not None and merged:
                idx = int(element_id)
                if 0 <= idx < len(merged):
                    el = merged[idx]
                    cx = el.bbox[0] + el.bbox[2] // 2
                    cy = el.bbox[1] + el.bbox[3] // 2
                    # If merged element has UIA name, prefer name-based click
                    if el.uia_name:
                        params["name"] = el.uia_name
                    elif el.uia_automation_id:
                        params["automation_id"] = el.uia_automation_id
                    else:
                        params["x"] = cx
                        params["y"] = cy
                    params.pop("element_id", None)
                    return AgentAction(
                        action=action.action,
                        parameters=params,
                        reasoning=action.reasoning,
                        confidence=action.confidence,
                    )

        return action

    async def _reason_vlm(
        self,
        objective: str,
        observation: AgentObservation,
        history: List[AgentStep],
        trajectory_context: str = "",
    ) -> AgentAction:
        """VLM reasoning with screenshot (original path)."""
        uia_section = ""
        if observation.uia_summary:
            uia_section = f"UI Elements:\n{observation.uia_summary[:2000]}"

        history_section = self._build_history_section(history)
        trajectory_section = ""
        if trajectory_context:
            trajectory_section = f"PAST EXPERIENCE (similar objectives attempted before):\n{trajectory_context}"

        prompt_template = CUA_AGENT_PROMPT if self._use_coordinates else VISION_AGENT_PROMPT
        prompt = prompt_template.format(
            objective=objective,
            window_title=observation.window_title,
            process_exe=observation.process_exe,
            uia_section=uia_section,
            history_section=history_section,
            trajectory_section=trajectory_section,
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

    @staticmethod
    def _build_history_section(history: List[AgentStep]) -> str:
        history_lines = []
        for i, step in enumerate(history[-5:]):
            history_lines.append(
                f"Step {i+1}: action={step.action.action}, "
                f"reasoning={step.action.reasoning}, "
                f"result={'ok' if step.error is None else f'error: {step.error}'}"
            )
        return "HISTORY:\n" + "\n".join(history_lines) if history_lines else ""

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
