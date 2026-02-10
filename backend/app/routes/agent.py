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
    chat_memory,
    ollama,
    store,
    trajectory_store,
)
from ..recipes import match_recipe_by_keywords
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

    # Resolve or create conversation
    conversation_id = request.conversation_id
    if not conversation_id:
        conversation_id = await chat_memory.create_conversation(title=message[:80])

    # Load conversation history
    history = await chat_memory.get_messages(conversation_id, limit=20)

    action_triggered = False
    run_id = None

    # Check for recipe keyword match first
    recipe = match_recipe_by_keywords(message) if request.allow_actions else None
    if recipe:
        try:
            start_req = AutonomyStartRequest(
                objective=recipe.description,
                max_iterations=len(recipe.steps) + 5,
                parallel_agents=1,
                auto_approve_irreversible=False,
            )
            run = await autonomy.start(start_req)
            action_triggered = True
            run_id = run.run_id
        except Exception as exc:
            logger.warning("Recipe execution failed: %s", exc)

    if not action_triggered and request.allow_actions and _is_action_intent(message):
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

    # Save user message
    await chat_memory.save_message(
        conversation_id, "user", message, desktop_context=ctx_dict
    )

    is_available = await ollama.available()
    if is_available:
        # Build multi-turn messages array
        llm_messages = []
        system_parts = [
            "You are DesktopAI, an intelligent desktop assistant. "
            "Respond concisely and helpfully.",
        ]
        if ctx:
            system_parts.append(f"\nCurrent desktop state:\n{ctx.to_llm_prompt()}")
        if action_triggered:
            system_parts.append(
                f"\nI've started an autonomous task for: {message}. "
                "Acknowledge this and describe what you're doing."
            )
        llm_messages.append({"role": "system", "content": "\n".join(system_parts)})

        # Add conversation history (excluding the just-saved user message)
        for msg in history:
            llm_messages.append({"role": msg["role"], "content": msg["content"]})

        # Add new user message
        llm_messages.append({"role": "user", "content": message})

        llm_response = await ollama.chat(llm_messages)
        if llm_response and llm_response.strip():
            response_text = llm_response.strip()
            await chat_memory.save_message(
                conversation_id, "assistant", response_text
            )
            return {
                "response": response_text,
                "source": "ollama",
                "desktop_context": ctx_dict,
                "action_triggered": action_triggered,
                "run_id": run_id,
                "conversation_id": conversation_id,
            }

    if action_triggered:
        response = f"Got it — I've started working on: **{message}**."
        if ctx:
            response += f" I can see you're in {ctx.window_title}."
    else:
        response = _build_context_response(ctx)

    await chat_memory.save_message(conversation_id, "assistant", response)

    return {
        "response": response,
        "source": "context",
        "desktop_context": ctx_dict,
        "action_triggered": action_triggered,
        "run_id": run_id,
        "conversation_id": conversation_id,
    }
