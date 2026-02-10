"""Agent, vision, chat, and bridge routes."""

import logging

from fastapi import APIRouter, HTTPException

from ..autonomy import VisionAutonomousRunner
from ..config import settings
from ..deps import (
    _dump,
    _publish_autonomy_update,
    autonomy,
    bridge,
    ollama,
    store,
    trajectory_store,
)
from ..schemas import AutonomyStartRequest, ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter()


_ACTION_KEYWORDS = {
    "draft", "reply", "send", "open", "type", "search", "click",
    "launch", "compose", "write", "submit", "delete", "forward",
    "close", "switch",
}


def _is_action_intent(message: str) -> bool:
    words = set(message.lower().split())
    return bool(words & _ACTION_KEYWORDS)


def _build_context_response(ctx) -> str:
    if ctx is None:
        return "I don't have visibility into your desktop right now. Connect the Windows collector to give me eyes on your screen."
    parts = [f"You're currently in **{ctx.window_title}**"]
    if ctx.process_exe:
        parts[0] += f" ({ctx.process_exe})"
    parts[0] += "."
    if ctx.uia_summary:
        elements = ctx.uia_summary[:300]
        parts.append(f"I can see these UI elements: {elements}")
    if ctx.screenshot_b64:
        parts.append("I also have a screenshot of your desktop.")
    return " ".join(parts)


@router.get("/api/agent/bridge")
async def get_bridge_status() -> dict:
    return bridge.status()


@router.post("/api/agent/run")
async def run_vision_agent(request: AutonomyStartRequest) -> dict:
    from ..vision_agent import VisionAgent

    if not bridge.connected:
        raise HTTPException(status_code=503, detail="collector bridge not connected")

    if not settings.vision_agent_enabled:
        raise HTTPException(status_code=503, detail="vision agent disabled")

    agent = VisionAgent(
        bridge=bridge,
        ollama=ollama,
        max_iterations=request.max_iterations or settings.vision_agent_max_iterations,
        vision_model=settings.ollama_vision_model or None,
        min_confidence=settings.vision_agent_min_confidence,
        max_consecutive_errors=settings.vision_agent_max_consecutive_errors,
        error_backoff_ms=settings.vision_agent_error_backoff_ms,
        trajectory_store=trajectory_store,
        trajectory_max_chars=settings.trajectory_context_max_chars,
        trajectory_max_results=settings.trajectory_context_max_results,
    )
    runner = VisionAutonomousRunner(
        vision_agent=agent,
        on_run_update=_publish_autonomy_update,
        trajectory_store=trajectory_store,
    )
    run = await runner.start(request)
    return {"run": _dump(run)}


@router.post("/api/chat")
async def chat_endpoint(request: ChatRequest) -> dict:
    from ..desktop_context import DesktopContext

    current_event = await store.current()
    ctx = DesktopContext.from_event(current_event) if current_event else None
    ctx_dict = None
    if ctx:
        ctx_dict = {
            "window_title": ctx.window_title,
            "process_exe": ctx.process_exe,
            "uia_summary": ctx.uia_summary[:500] if ctx.uia_summary else "",
            "screenshot_available": ctx.screenshot_b64 is not None,
        }

    message = request.message.strip()

    action_triggered = False
    run_id = None
    if request.allow_actions and _is_action_intent(message):
        try:
            start_req = AutonomyStartRequest(
                objective=message,
                max_iterations=24,
                parallel_agents=3,
                auto_approve_irreversible=False,
            )
            if bridge.connected and settings.vision_agent_enabled:
                from ..vision_agent import VisionAgent

                agent = VisionAgent(
                    bridge=bridge,
                    ollama=ollama,
                    max_iterations=start_req.max_iterations,
                    vision_model=settings.ollama_vision_model or None,
                    min_confidence=settings.vision_agent_min_confidence,
                    max_consecutive_errors=settings.vision_agent_max_consecutive_errors,
                    error_backoff_ms=settings.vision_agent_error_backoff_ms,
                    trajectory_store=trajectory_store,
                    trajectory_max_chars=settings.trajectory_context_max_chars,
                    trajectory_max_results=settings.trajectory_context_max_results,
                )
                runner = VisionAutonomousRunner(
                    vision_agent=agent,
                    on_run_update=_publish_autonomy_update,
                    trajectory_store=trajectory_store,
                )
                run = await runner.start(start_req)
            else:
                run = await autonomy.start(start_req)
            action_triggered = True
            run_id = run.run_id
        except Exception as exc:
            logger.warning("Chat action trigger failed: %s", exc)

    is_available = await ollama.available()
    if is_available:
        prompt_parts = [
            "You are DesktopAI, an intelligent desktop assistant. "
            "Respond concisely and helpfully.",
        ]
        if ctx:
            prompt_parts.append(f"\nCurrent desktop state:\n{ctx.to_llm_prompt()}")
        if action_triggered:
            prompt_parts.append(
                f"\nI've started an autonomous task for: {message}. "
                "Acknowledge this and describe what you're doing."
            )
        prompt_parts.append(f"\nUser: {message}")

        messages = [{"role": "user", "content": "\n".join(prompt_parts)}]
        llm_response = await ollama.chat(messages)
        if llm_response and llm_response.strip():
            return {
                "response": llm_response.strip(),
                "source": "ollama",
                "desktop_context": ctx_dict,
                "action_triggered": action_triggered,
                "run_id": run_id,
            }

    if action_triggered:
        response = f"Got it — I've started working on: **{message}**."
        if ctx:
            response += f" I can see you're in {ctx.window_title}."
    else:
        response = _build_context_response(ctx)

    return {
        "response": response,
        "source": "context",
        "desktop_context": ctx_dict,
        "action_triggered": action_triggered,
        "run_id": run_id,
    }
