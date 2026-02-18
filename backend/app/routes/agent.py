"""Agent, vision, chat, and bridge routes."""

import asyncio
import json
import logging
import random
import re
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

from ..config import settings
from ..deps import (
    _dump,
    autonomy,
    bridge,
    chat_memory,
    get_personality_mode,
    llm,
    ollama,
    personality_adapter,
    set_personality_mode,
    store,
    trajectory_store,
    vision_runner,
)
from ..recipes import match_recipe_by_keywords, recipe_to_plan_steps
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
        "Maximum 3 bullet points. Never more than 5 sentences total. "
        "Skip explanations unless asked."
    ),
    "assistant": (
        "You are DesktopAI, an intelligent desktop assistant. "
        "Be friendly and explanatory. Offer proactive suggestions. "
        "Respond concisely and helpfully."
    ),
    "operator": (
        "You are DesktopAI in operator mode. "
        "Never use greetings or pleasantries. "
        "Never say 'Sure', 'Let me', 'Of course', 'Certainly'. "
        "Start every response with the action verb. "
        "Use imperative sentences only. Maximum 2-3 sentences. "
        "Treat every message as a command. Execute first, explain only if asked."
    ),
}


def _is_action_intent(message: str) -> bool:
    words = set(message.lower().split())
    return bool(words & _ACTION_KEYWORDS)


# Browser window title fragments — used to detect when the browser has focus
# so that "scroll down" targets the previous non-browser window instead.
_BROWSER_TITLE_FRAGMENTS = (
    "mozilla firefox", "chrome", "edge", "desktopai live context", "localhost",
)

# Patterns for direct bridge commands (no vision needed).
# Each tuple: (compiled regex, action name, param builder).
_DIRECT_PATTERNS: list[tuple[re.Pattern, str, Callable[[re.Match], dict[str, Any]]]] = [
    (re.compile(r"^(?:open|launch|start)\s+(.+)$", re.I),
     "open_application", lambda m: {"application": m.group(1).strip()}),
    (re.compile(r"^(?:focus|switch\s+to|go\s+to)\s+(.+)$", re.I),
     "focus_window", lambda m: {"title": m.group(1).strip()}),
    # "scroll down in Notepad" — explicit target window (must come before generic scroll)
    (re.compile(r"^scroll\s+(up|down)\s+(?:in|on)\s+(.+)$", re.I),
     "_scroll_in_window", lambda m: {"direction": m.group(1).lower(), "amount": 3, "window": m.group(2).strip()}),
    (re.compile(r"^scroll\s+(up|down)(?:\s+(\d+))?$", re.I),
     "scroll", lambda m: {"direction": m.group(1).lower(), "amount": int(m.group(2) or 3)}),
    (re.compile(r"^(?:press|send(?:\s+keys?)?)\s+(.+)$", re.I),
     "send_keys", lambda m: {"keys": m.group(1).strip()}),
    # Click patterns — UIA name resolution in collector (no vision needed)
    (re.compile(r"^(?:click|tap|hit|select)\s+(?:on\s+)?(?:the\s+)?['\"]?(.+?)['\"]?(?:\s+button)?$", re.I),
     "click", lambda m: {"name": m.group(1).strip()}),
    (re.compile(r"^double[- ]?click\s+(?:on\s+)?(?:the\s+)?['\"]?(.+?)['\"]?$", re.I),
     "double_click", lambda m: {"name": m.group(1).strip()}),
    (re.compile(r"^right[- ]?click\s+(?:on\s+)?(?:the\s+)?['\"]?(.+?)['\"]?$", re.I),
     "right_click", lambda m: {"name": m.group(1).strip()}),
    # Type patterns (must come after click to avoid "type" matching "click type...")
    (re.compile(r"^type\s+['\"]?(.+?)['\"]?\s+(?:in|into)\s+(.+)$", re.I),
     "_type_in_window", lambda m: {"text": m.group(1), "window": m.group(2).strip()}),
    (re.compile(r"^type\s+['\"]?(.+?)['\"]?\s*$", re.I),
     "type_text", lambda m: {"text": m.group(1).strip()}),
    # Kill switch: stop/kill/cancel/abort all actions
    (re.compile(r"^(?:stop|kill|cancel|abort)(?:\s+(?:all|everything|actions?))?$", re.I),
     "_cancel_all", lambda m: {}),
]


def _match_direct_pattern(message: str) -> Optional[tuple[str, dict[str, Any]]]:
    """Pure pattern match — no bridge call. Returns (action, params) or None."""
    stripped = message.strip()
    for pattern, action, param_fn in _DIRECT_PATTERNS:
        match = pattern.match(stripped)
        if match:
            return action, param_fn(match)
    return None


async def _cancel_all_runs() -> int:
    """Cancel all in-progress autonomy and vision runs. Returns count cancelled."""
    cancelled = 0
    for run in await autonomy.list_runs(limit=100):
        if run.status in {"running", "waiting_approval"}:
            try:
                await autonomy.cancel(run.run_id)
                cancelled += 1
            except Exception:
                pass
    for run in await vision_runner.list_runs(limit=100):
        if run.status in {"running", "waiting_approval"}:
            try:
                await vision_runner.cancel(run.run_id)
                cancelled += 1
            except Exception:
                pass
    return cancelled


async def _find_last_non_browser_window() -> Optional[str]:
    """Return the title of the most recent foreground window that is NOT a browser.

    Searches the last 60 seconds of foreground switches and returns the first
    (most recent) title that doesn't match any browser title fragment.
    """
    switches = await store.recent_switches(since_s=60)
    for sw in switches:
        title_lower = (sw.get("title") or "").lower()
        if not title_lower:
            continue
        if any(frag in title_lower for frag in _BROWSER_TITLE_FRAGMENTS):
            continue
        return sw["title"]
    return None


async def _try_direct_command(message: str) -> Optional[dict]:
    """Try to match message to a direct bridge command.

    Returns a result dict on match, or None to fall through to VisionAgent.
    """
    matched = _match_direct_pattern(message)
    if not matched:
        return None

    action, params = matched

    # Cancel-all doesn't need the bridge
    if action == "_cancel_all":
        cancelled = await _cancel_all_runs()
        return {"action": action, "parameters": params, "result": {"cancelled": cancelled}}

    if not bridge.connected:
        return None

    if action == "_type_in_window":
        await bridge.execute("focus_window", {"title": params["window"]}, timeout_s=5)
        await asyncio.sleep(0.4)  # Let window fully receive input focus
        result = await bridge.execute("type_text", {"text": params["text"]}, timeout_s=5)
    elif action == "_scroll_in_window":
        # "scroll down in Notepad" — focus the named window, then scroll
        await bridge.execute("focus_window", {"title": params["window"]}, timeout_s=5)
        await asyncio.sleep(0.3)
        result = await bridge.execute(
            "scroll", {"direction": params["direction"], "amount": params["amount"]}, timeout_s=5,
        )
    elif action == "scroll":
        # Bare "scroll down" — focus last non-browser window first so the
        # scroll event doesn't land on the browser the user just typed in.
        target = await _find_last_non_browser_window()
        if target:
            await bridge.execute("focus_window", {"title": target}, timeout_s=5)
            await asyncio.sleep(0.3)
        result = await bridge.execute(action, params, timeout_s=5)
    else:
        result = await bridge.execute(action, params, timeout_s=5)

    return {"action": action, "parameters": params, "result": result}


_GREETING_WORDS = {"hello", "hi", "hey", "sup", "yo", "howdy", "hola", "greetings"}

_GREETING_RESPONSES = [
    "Hey! What can I help you with?",
    "Hi there! What do you need?",
    "Hey! Ready when you are.",
]


def _is_greeting(message: str) -> bool:
    """Check if message is a simple greeting (no action intent)."""
    words = message.lower().strip().rstrip("!?.").split()
    return len(words) <= 3 and bool(set(words) & _GREETING_WORDS)


def _build_context_response(ctx) -> str:
    if ctx is None:
        return "I don't have visibility into your desktop right now. Connect the Windows collector to give me eyes on your screen."
    parts = [f"You're currently in **{ctx.window_title}**"]
    if ctx.process_exe:
        parts[0] += f" ({ctx.process_exe})"
    parts[0] += "."
    return " ".join(parts)


_VALID_PERSONALITY_MODES = {"copilot", "assistant", "operator"}


@router.put("/api/personality")
async def put_personality_mode(body: dict):  # -> dict | JSONResponse
    """Update the active personality mode at runtime."""
    from fastapi.responses import JSONResponse

    mode = body.get("mode", "")
    if mode not in _VALID_PERSONALITY_MODES:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid mode '{mode}'. Must be one of: {sorted(_VALID_PERSONALITY_MODES)}"},
        )
    set_personality_mode(mode)
    return {"mode": mode}


@router.get("/api/personality")
async def get_personality_status() -> dict:
    """Return current personality mode and auto-adaptation state."""
    session = await store.session_summary()
    energy = personality_adapter.classify_energy(session)
    recommended = personality_adapter.recommend(session)
    return {
        "current_mode": get_personality_mode(),
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

    cua_model = settings.ollama_cua_model.strip()
    use_coordinates = bool(cua_model)
    vision_model = cua_model if use_coordinates else (settings.ollama_vision_model or None)

    return VisionAgent(
        bridge=bridge,
        ollama=ollama,
        max_iterations=max_iterations or settings.vision_agent_max_iterations,
        vision_model=vision_model,
        min_confidence=settings.vision_agent_min_confidence,
        max_consecutive_errors=settings.vision_agent_max_consecutive_errors,
        error_backoff_ms=settings.vision_agent_error_backoff_ms,
        trajectory_store=trajectory_store,
        trajectory_max_chars=settings.trajectory_context_max_chars,
        trajectory_max_results=settings.trajectory_context_max_results,
        use_coordinates=use_coordinates,
        vision_mode=settings.vision_mode,
        detection_merge_iou=settings.detection_merge_iou,
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
async def chat_endpoint(request: ChatRequest):  # -> dict | StreamingResponse
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
            plan_steps = recipe_to_plan_steps(recipe)
            start_req = AutonomyStartRequest(
                objective=recipe.description,
                max_iterations=len(recipe.steps) + 5,
                parallel_agents=1,
                auto_approve_irreversible=False,
            )
            run = await autonomy.start_with_plan(start_req, plan_steps)
            action_triggered = True
            run_id = run.run_id
        except Exception as exc:
            logger.warning("Recipe execution failed: %s", exc)

    # Fast path: direct bridge command for simple actions (no VLM needed).
    # Pattern match gates action_triggered — prevents VisionAgent from also
    # firing on the same command even if bridge execution fails or is offline.
    direct_result = None
    direct_match = _match_direct_pattern(message) if request.allow_actions else None
    if not action_triggered and direct_match:
        action_triggered = True
        # _cancel_all works without bridge; other commands need it
        needs_bridge = direct_match[0] != "_cancel_all"
        if not needs_bridge or bridge.connected:
            try:
                direct_result = await _try_direct_command(message)
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

    # Personality mode: explicit request > auto-adapt > config default
    # Computed early so all return paths (greeting, direct, LLM) use it.
    session = await store.session_summary()
    if request.personality_mode:
        mode = request.personality_mode
    elif settings.personality_auto_adapt:
        mode = personality_adapter.recommend(session)
    else:
        mode = get_personality_mode()

    # Greeting fast path: instant response, no LLM call
    if not action_triggered and _is_greeting(message):
        response = random.choice(_GREETING_RESPONSES)
        await chat_memory.save_message(conversation_id, "assistant", response)
        result = {
            "response": response,
            "source": "greeting",
            "desktop_context": ctx_dict,
            "action_triggered": False,
            "run_id": None,
            "conversation_id": conversation_id,
            "personality_mode": mode,
        }
        if screenshot_b64:
            result["screenshot_b64"] = screenshot_b64
        return result

    # Direct commands: return immediately — no LLM call needed
    if direct_result or direct_match:
        if direct_result:
            action = direct_result["action"]
            params = direct_result["parameters"]
        elif direct_match:
            action, params = direct_match
        else:
            action, params = "unknown", {}
        friendly = action.replace("_", " ")
        if action == "_cancel_all":
            count = direct_result["result"]["cancelled"] if direct_result else 0
            response = f"Killed {count} running action(s)." if count > 0 else "No actions were running."
        elif action == "_type_in_window":
            friendly = f"typed in {params.get('window', '')}"
            response = f"Done — {friendly}."
        elif action == "_scroll_in_window":
            friendly = f"scrolled {params.get('direction', 'down')} in {params.get('window', '')}"
            response = f"Done — {friendly}."
        else:
            response = f"Done — {friendly}."
        await chat_memory.save_message(conversation_id, "assistant", response)
        result = {
            "response": response,
            "source": "direct",
            "desktop_context": ctx_dict,
            "action_triggered": True,
            "run_id": None,
            "conversation_id": conversation_id,
            "personality_mode": mode,
        }
        if screenshot_b64:
            result["screenshot_b64"] = screenshot_b64
        return result

    is_available = await llm.available()
    if is_available:
        fg_switches = await store.recent_switches(since_s=120)
        llm_messages = _build_llm_messages(
            mode=mode, ctx=ctx, message=message,
            action_triggered=action_triggered, run_id=run_id,
            session=session, history=history,
            recent_events=(await store.snapshot())[1],
            recent_switches=fg_switches,
        )

        # SSE streaming branch
        if request.stream:
            return StreamingResponse(
                _stream_chat_response(
                    llm_messages=llm_messages,
                    conversation_id=conversation_id,
                    ctx_dict=ctx_dict,
                    action_triggered=action_triggered,
                    run_id=run_id,
                    mode=mode,
                    screenshot_b64=screenshot_b64,
                ),
                media_type="text/event-stream",
            )

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

    # Fetch recent foreground switches for context enrichment
    recent_apps = await store.recent_switches(since_s=120)

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
        "recent_apps": recent_apps,
    }
    if screenshot_b64:
        result["screenshot_b64"] = screenshot_b64
    return result


def _build_llm_messages(
    *,
    mode: str,
    ctx,
    message: str,
    action_triggered: bool,
    run_id: Optional[str],
    session: dict,
    history: list,
    recent_events: list,
    recent_switches: Optional[list] = None,
) -> list[dict]:
    """Build the multi-turn messages array for the LLM call."""
    llm_messages: list[dict] = []
    system_parts = [
        _PERSONALITY_PROMPTS.get(mode, _PERSONALITY_PROMPTS["assistant"]),
    ]
    if ctx:
        if action_triggered or _is_action_intent(message):
            system_parts.append(f"\nCurrent desktop state:\n{ctx.to_llm_prompt()}")
        else:
            parts = []
            if ctx.window_title:
                parts.append(f"User is in: {ctx.window_title}")
            if ctx.process_exe:
                parts.append(f"App: {ctx.process_exe}")
            if parts:
                system_parts.append("\n" + ". ".join(parts) + ".")
    if recent_switches:
        switch_lines = [
            f"{s['process_exe']}: {s['title']}" for s in recent_switches
        ]
        if switch_lines:
            system_parts.append(
                "\nRECENTLY OPENED (last 2 minutes): " + "; ".join(switch_lines)
            )
    if recent_events:
        seen: set[str] = set()
        recent_apps: list[str] = []
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
        system_parts.append(
            f"\nAn autonomous agent is now working on: {message}. "
            "Tell the user the task is IN PROGRESS — do NOT say it is done or complete. "
            "Say something like 'Working on it now' or 'I'm on it'. "
            "The agent runs in the background and results will appear shortly."
        )
    elif action_triggered:
        system_parts.append(
            f"\nI just executed a direct desktop command for: {message}. "
            "Confirm what you did briefly."
        )
    llm_messages.append({"role": "system", "content": "\n".join(system_parts)})

    for msg in history:
        llm_messages.append({"role": msg["role"], "content": msg["content"]})

    llm_messages.append({"role": "user", "content": message})
    return llm_messages


async def _stream_chat_response(
    *,
    llm_messages: list[dict],
    conversation_id: str,
    ctx_dict: Optional[dict],
    action_triggered: bool,
    run_id: Optional[str],
    mode: str,
    screenshot_b64: Optional[str],
):
    """Async generator that yields SSE events from Ollama streaming."""
    accumulated = []
    had_error = False

    try:
        async for chunk in ollama.chat_stream(llm_messages):
            token = chunk.get("token", "")
            done = chunk.get("done", False)
            error = chunk.get("error")

            if error:
                had_error = True
                event = {"token": "", "done": True, "error": error}
                yield f"data: {json.dumps(event)}\n\n"
                return

            if token:
                accumulated.append(token)

            if not done:
                event = {"token": token, "done": False}
                yield f"data: {json.dumps(event)}\n\n"
            else:
                # Final event with metadata
                full_response = "".join(accumulated).strip()
                if full_response:
                    await chat_memory.save_message(
                        conversation_id, "assistant", full_response,
                    )
                final: dict[str, Any] = {
                    "token": "",
                    "done": True,
                    "conversation_id": conversation_id,
                    "source": "ollama",
                    "desktop_context": ctx_dict,
                    "action_triggered": action_triggered,
                    "run_id": run_id,
                    "personality_mode": mode,
                }
                if screenshot_b64:
                    final["screenshot_b64"] = screenshot_b64
                yield f"data: {json.dumps(final)}\n\n"
                return

    except Exception as exc:
        logger.warning("Stream error: %s", exc)
        if not had_error:
            event = {"token": "", "done": True, "error": str(exc)}
            yield f"data: {json.dumps(event)}\n\n"

    # If we get here without a done event, send final
    full_response = "".join(accumulated).strip()
    if full_response:
        await chat_memory.save_message(
            conversation_id, "assistant", full_response,
        )
    final_event: dict[str, Any] = {
        "token": "",
        "done": True,
        "conversation_id": conversation_id,
        "source": "ollama",
        "action_triggered": action_triggered,
        "run_id": run_id,
        "personality_mode": mode,
    }
    yield f"data: {json.dumps(final_event)}\n\n"
