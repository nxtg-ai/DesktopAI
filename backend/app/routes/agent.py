"""Agent, vision, chat, and bridge routes."""

import logging
import re
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..deps import (
    _dump,
    autonomy,
    bridge,
    chat_memory,
    llm,
    ollama,
    personality_adapter,
    store,
    trajectory_store,
    vision_runner,
)
from ..recipes import match_recipe_by_keywords
from ..schemas import AutonomyStartRequest, ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter()


_ACTION_KEYWORDS = {
    "draft", "reply", "send", "open", "type", "search", "click",
    "launch", "compose", "write", "submit", "delete", "forward",
    "close", "switch", "scroll", "focus", "observe",
}

_PERSONALITY_PROMPTS = {
    "copilot": (
        "You are DesktopAI in co-pilot mode. Be concise and technical. "
        "Use jargon freely. Focus on code, workflows, and productivity. "
        "Skip pleasantries — the user is in flow state. "
        "Maximum 3-5 bullet points. Skip explanations unless asked."
    ),
    "assistant": (
        "You are DesktopAI, an intelligent desktop assistant. "
        "Be friendly and explanatory. Offer proactive suggestions. "
        "Respond concisely and helpfully."
    ),
    "operator": (
        "You are DesktopAI in operator mode. "
        "Never use greetings or pleasantries. Start with the action. "
        "Use imperative sentences only. Maximum 2-3 sentences. "
        "Treat every message as a command. Execute first, explain only if asked."
    ),
}


def _is_action_intent(message: str) -> bool:
    words = set(message.lower().split())
    return bool(words & _ACTION_KEYWORDS)


# Patterns for direct bridge commands (no vision needed).
# Each tuple: (compiled regex, action name, param builder).
_DIRECT_PATTERNS: list[tuple[re.Pattern, str, Callable[[re.Match], dict[str, Any]]]] = [
    (re.compile(r"^(?:open|launch|start)\s+(.+)$", re.I),
     "open_application", lambda m: {"application": m.group(1).strip()}),
    (re.compile(r"^(?:focus|switch\s+to|go\s+to)\s+(.+)$", re.I),
     "focus_window", lambda m: {"title": m.group(1).strip()}),
    (re.compile(r"^scroll\s+(up|down)(?:\s+(\d+))?", re.I),
     "scroll", lambda m: {"direction": m.group(1).lower(), "amount": int(m.group(2) or 3)}),
    (re.compile(r"^(?:press|send(?:\s+keys?)?)\s+(.+)$", re.I),
     "send_keys", lambda m: {"keys": m.group(1).strip()}),
    (re.compile(r"^type\s+['\"]?(.+?)['\"]?\s+(?:in|into)\s+(.+)$", re.I),
     "_type_in_window", lambda m: {"text": m.group(1), "window": m.group(2).strip()}),
    (re.compile(r"^type\s+['\"]?(.+?)['\"]?\s*$", re.I),
     "type_text", lambda m: {"text": m.group(1).strip()}),
]


async def _try_direct_command(message: str) -> Optional[dict]:
    """Try to match message to a direct bridge command.

    Returns a result dict on match, or None to fall through to VisionAgent.
    """
    if not bridge.connected:
        return None

    stripped = message.strip()
    for pattern, action, param_fn in _DIRECT_PATTERNS:
        match = pattern.match(stripped)
        if not match:
            continue
        params = param_fn(match)

        if action == "_type_in_window":
            await bridge.execute("focus_window", {"title": params["window"]}, timeout_s=5)
            result = await bridge.execute("type_text", {"text": params["text"]}, timeout_s=5)
        else:
            result = await bridge.execute(action, params, timeout_s=5)

        return {"action": action, "parameters": params, "result": result}

    return None


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


@router.get("/api/personality")
async def get_personality_status() -> dict:
    """Return current personality mode and auto-adaptation state."""
    session = await store.session_summary()
    energy = personality_adapter.classify_energy(session)
    recommended = personality_adapter.recommend(session)
    return {
        "current_mode": settings.personality_mode,
        "auto_adapt_enabled": settings.personality_auto_adapt,
        "session_energy": energy,
        "recommended_mode": recommended,
        "session_summary": {
            "app_switches": session.get("app_switches", 0),
            "unique_apps": session.get("unique_apps", 0),
            "session_duration_s": session.get("session_duration_s", 0),
        },
    }


@router.get("/api/agent/bridge")
async def get_bridge_status() -> dict:
    """Return the current collector bridge connection status."""
    return bridge.status()


def _build_vision_agent(max_iterations: int = 0):
    """Build a VisionAgent with current settings."""
    from ..vision_agent import VisionAgent

    return VisionAgent(
        bridge=bridge,
        ollama=ollama,
        max_iterations=max_iterations or settings.vision_agent_max_iterations,
        vision_model=settings.ollama_vision_model or None,
        min_confidence=settings.vision_agent_min_confidence,
        max_consecutive_errors=settings.vision_agent_max_consecutive_errors,
        error_backoff_ms=settings.vision_agent_error_backoff_ms,
        trajectory_store=trajectory_store,
        trajectory_max_chars=settings.trajectory_context_max_chars,
        trajectory_max_results=settings.trajectory_context_max_results,
    )


@router.post("/api/agent/run")
async def run_vision_agent(request: AutonomyStartRequest) -> dict:
    """Start a vision-based autonomous agent run via the collector bridge."""
    if not bridge.connected:
        raise HTTPException(status_code=503, detail="collector bridge not connected")

    if not settings.vision_agent_enabled:
        raise HTTPException(status_code=503, detail="vision agent disabled")

    agent = _build_vision_agent(request.max_iterations or 0)
    vision_runner.set_agent(agent)
    run = await vision_runner.start(request)
    return {"run": _dump(run)}


@router.post("/api/chat")
async def chat_endpoint(request: ChatRequest) -> dict:
    """Process a chat message with desktop context and optional action execution."""
    from ..desktop_context import DesktopContext

    current_event = await store.current()
    ctx = DesktopContext.from_event(current_event) if current_event else None
    ctx_dict = None
    screenshot_b64 = None
    if ctx:
        screenshot_b64 = ctx.screenshot_b64
        ctx_dict = {
            "window_title": ctx.window_title,
            "process_exe": ctx.process_exe,
            "uia_summary": ctx.uia_summary[:500] if ctx.uia_summary else "",
            "screenshot_available": screenshot_b64 is not None,
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

    # Fast path: direct bridge command for simple actions (no VLM needed)
    direct_result = None
    if not action_triggered and request.allow_actions and bridge.connected:
        try:
            direct_result = await _try_direct_command(message)
            if direct_result:
                action_triggered = True
        except Exception as exc:
            logger.warning("Direct command failed: %s", exc)

    # Slow path: VisionAgent for complex/ambiguous actions
    if not action_triggered and request.allow_actions and _is_action_intent(message):
        try:
            start_req = AutonomyStartRequest(
                objective=message,
                max_iterations=24,
                parallel_agents=3,
                auto_approve_irreversible=False,
            )
            if bridge.connected and settings.vision_agent_enabled:
                agent = _build_vision_agent(start_req.max_iterations)
                vision_runner.set_agent(agent)
                run = await vision_runner.start(start_req)
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

    # Direct commands: return immediately — no LLM call needed
    if direct_result:
        action = direct_result["action"]
        friendly = action.replace("_", " ")
        if action == "_type_in_window":
            friendly = f"typed in {direct_result['parameters']['window']}"
        response = f"Done — {friendly}."
        await chat_memory.save_message(conversation_id, "assistant", response)
        result = {
            "response": response,
            "source": "direct",
            "desktop_context": ctx_dict,
            "action_triggered": True,
            "run_id": None,
            "conversation_id": conversation_id,
            "personality_mode": settings.personality_mode,
        }
        if screenshot_b64:
            result["screenshot_b64"] = screenshot_b64
        return result

    # Fetch session summary for enriched context
    session = await store.session_summary()

    # Personality mode: explicit request > auto-adapt > config default
    if request.personality_mode:
        mode = request.personality_mode
    elif settings.personality_auto_adapt:
        mode = personality_adapter.recommend(session)
    else:
        mode = settings.personality_mode

    is_available = await llm.available()
    if is_available:
        # Build multi-turn messages array
        llm_messages = []
        system_parts = [
            _PERSONALITY_PROMPTS.get(mode, _PERSONALITY_PROMPTS["assistant"]),
        ]
        if ctx:
            system_parts.append(f"\nCurrent desktop state:\n{ctx.to_llm_prompt()}")
        # Include recent app transitions so LLM knows what user was doing
        _, recent_events = await store.snapshot()
        if recent_events:
            seen = set()
            recent_apps = []
            for ev in reversed(recent_events[-10:]):
                key = f"{ev.process_exe}|{ev.title}"
                if key not in seen:
                    seen.add(key)
                    recent_apps.append(f"{ev.process_exe}: {ev.title}")
                if len(recent_apps) >= 5:
                    break
            if recent_apps:
                system_parts.append(
                    "\nRecent apps (most recent first): " + "; ".join(recent_apps)
                )
        if session.get("app_switches", 0) > 0:
            top = ", ".join(
                f"{a['process']} ({a['dwell_s']}s)"
                for a in session.get("top_apps", [])[:3]
            )
            system_parts.append(
                f"\nSession: {session['app_switches']} app switches, "
                f"{session['unique_apps']} unique apps, "
                f"session {round(session.get('session_duration_s', 0) / 60, 1)} min. "
                f"Top: {top}"
            )
        if action_triggered and run_id:
            # Async VisionAgent / orchestrator — still in progress
            system_parts.append(
                f"\nAn autonomous agent is now working on: {message}. "
                "Tell the user the task is IN PROGRESS — do NOT say it is done or complete. "
                "Say something like 'Working on it now' or 'I'm on it'. "
                "The agent runs in the background and results will appear shortly."
            )
        elif action_triggered:
            # Direct bridge command — already executed
            system_parts.append(
                f"\nI just executed a direct desktop command for: {message}. "
                "Confirm what you did briefly."
            )
        llm_messages.append({"role": "system", "content": "\n".join(system_parts)})

        # Add conversation history (excluding the just-saved user message)
        for msg in history:
            llm_messages.append({"role": msg["role"], "content": msg["content"]})

        # Add new user message
        llm_messages.append({"role": "user", "content": message})

        llm_response = await llm.chat(llm_messages)
        if llm_response and llm_response.strip():
            response_text = llm_response.strip()
            await chat_memory.save_message(
                conversation_id, "assistant", response_text
            )
            result = {
                "response": response_text,
                "source": "ollama",
                "desktop_context": ctx_dict,
                "action_triggered": action_triggered,
                "run_id": run_id,
                "conversation_id": conversation_id,
                "personality_mode": mode,
            }
            if screenshot_b64:
                result["screenshot_b64"] = screenshot_b64
            return result

    if action_triggered:
        response = f"Got it — I've started working on: **{message}**."
        if ctx:
            response += f" I can see you're in {ctx.window_title}."
    else:
        response = _build_context_response(ctx)

    await chat_memory.save_message(conversation_id, "assistant", response)

    result = {
        "response": response,
        "source": "context",
        "desktop_context": ctx_dict,
        "action_triggered": action_triggered,
        "run_id": run_id,
        "conversation_id": conversation_id,
        "personality_mode": mode,
    }
    if screenshot_b64:
        result["screenshot_b64"] = screenshot_b64
    return result
