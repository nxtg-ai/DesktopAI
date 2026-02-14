# Claudio Mission 05: UAT Fix Sprint

**Source:** UAT-Guide.md (Sections 1-3.5, tested by CEO on 2026-02-13)
**Priority:** Ship-blocking fixes first, then polish

---

## Critical Fixes (Blocking Production)

### C1: "scroll" missing from action keywords
**UAT:** 3.5 — AI hallucinated "Scrolled down in Notepad" without triggering any action.
**Root cause:** "scroll" is not in `_ACTION_KEYWORDS` in `backend/app/routes/agent.py`.
**Fix:** Add "scroll" to the `_ACTION_KEYWORDS` set. Verify the set includes all 9 collector commands: click, type, send_keys, scroll, double_click, right_click, open, focus, observe.
**Test:** Send "scroll down" in chat with `allow_actions=true` — should produce an action badge.

### C2: VisionAgent doesn't detect success — runs all 24 iterations
**UAT:** 3.1 — "Open Notepad" succeeded on iteration 1, but agent kept retrying `open_application` 24 times.
**Root cause:** VisionAgent's observe-act loop doesn't verify if the objective was already achieved. The `done` action is never emitted.
**Fix:** In `backend/app/vision_agent.py`, after each action execution, the VLM prompt should ask "Has the objective been achieved? If yes, respond with action: done." Also consider: if the same action is repeated 3+ times consecutively, auto-emit `done` with a note.
**Test:** "Open Notepad" should complete in 2-3 iterations, not 24.

### C3: Window targeting for type_text — types into wrong window
**UAT:** 3.3 — Agent typed "Hello from DesktopAI" 24 times into the browser chat input instead of Notepad.
**Root cause:** `type_text` sends keystrokes to whatever window has focus. The user was in the browser (web UI) when the agent started typing. No `focus_window` command was sent first.
**Fix:** In the VisionAgent's action planning, when the objective mentions a target app (e.g., "into Notepad"), the agent should emit `focus_window` before `type_text`. Consider adding a pre-flight step in the bridge executor: if the target window is known, focus it before typing.
**Files:** `backend/app/vision_agent.py` (prompt engineering), `collector/src/command.rs` (consider `focus_window` + `type_text` as atomic pair).
**Test:** "Type 'Hello' into Notepad" should first focus Notepad, then type.

### C4: Screenshot/UIA not captured for vision actions
**UAT:** 3.2 — Agent Vision shows "Screenshot: unavailable", "No UIA data captured".
**Root cause:** Screenshots and UIA are **disabled by default** in collector config (`enable_screenshot: false`, `uia_enabled: false`). The VisionAgent needs these to observe the desktop.
**Fix:** Update `.env` to enable screenshots and UIA for UAT:
```
ENABLE_SCREENSHOT=true
UIA_ENABLED=true
```
Also update `UAT-Guide.md` Step 3 to mention these env vars must be set on the collector side (Windows). The collector reads these from its own environment, not the backend.
**Collector env vars (Windows):**
```powershell
$env:ENABLE_SCREENSHOT="true"
$env:UIA_ENABLED="true"
C:\temp\desktopai\desktopai-collector.exe
```
**Test:** After enabling, `GET /api/state/snapshot` should include screenshot_b64 and UIA data.

---

## High Priority Fixes

### H1: Recipe keyword matching not triggering
**UAT:** 3.4 — "Draft a reply to this email" did NOT match `reply_to_email` recipe.
**Root cause:** Check `match_recipe_by_keywords()` in `backend/app/recipes.py`. The keyword set likely doesn't include "draft" + "reply" as a matching pair. The function may require both keywords to appear, or the keywords may be too narrow.
**Fix:** Read `recipes.py`, check the keyword lists for `reply_to_email`. Ensure "draft", "reply", "email" are all trigger keywords. Test with: "draft a reply", "reply to this email", "draft email reply".
**Test:** `match_recipe_by_keywords("draft a reply to this email")` should return the `reply_to_email` recipe.

### H2: Suggestion chips don't appear on new chat
**UAT:** 1.5 — BLOCKED. After clicking "New Chat", no suggestion chips appear.
**Root cause:** The welcome chips (e.g., "What am I doing?") are rendered in the initial state but may be cleared and never re-rendered when starting a new chat.
**Fix:** In `backend/web/modules/chat.js` (or wherever new chat logic lives), when clearing the chat for "New Chat", re-render the welcome screen with suggestion chips. Look for the new chat handler and ensure it calls the same initialization that renders chips.
**Test:** Click "New Chat" — chips like "What am I doing?" should appear.

### H3: Welcome message missing on new chat
**UAT:** 1.4 — After "New Chat", only the context bar shows. No welcome message.
**Root cause:** Same as H2 — the new chat handler clears messages but doesn't re-render the welcome state.
**Fix:** Same fix as H2. The new chat flow should reset to the initial welcome state with greeting + chips.
**Test:** Click "New Chat" — should show welcome message and suggestion chips.

### H4: Personality prompt tuning
**UAT:** 2.1 — Copilot is too verbose, Operator still has pleasantries.
**Root cause:** System prompts in `_PERSONALITY_PROMPTS` dict (in `backend/app/routes/agent.py`) need tighter constraints.
**Fix:** Find `_PERSONALITY_PROMPTS` in `agent.py` and tighten:
- **Copilot:** Add "Be concise. Maximum 3-5 bullet points. Skip explanations unless asked."
- **Operator:** Add "Never use greetings or pleasantries. Start with the action. Use imperative sentences only. Maximum 2-3 sentences."
**Test:** Same prompt in each mode should produce visibly different lengths and tones.

---

## Medium Priority (Polish)

### M1: AI chat bubble color should match avatar
**UAT:** 1.1 feedback — "Change the AI Chat Bubble to match the Avatar's color."
**Fix:** In `backend/web/style.css` or chat module CSS, change the assistant message bubble background to use the avatar accent color (likely a CSS variable).

### M2: Typing indicator glowing effect
**UAT:** 1.1 feedback — "I like the animation - add a glowing effect."
**Fix:** Add a CSS `box-shadow` animation or `@keyframes` glow to the typing indicator element in the chat UI.

### M3: Desktop context doesn't mention most recently opened app
**UAT:** 1.2 — User opened Notepad but AI didn't mention it, even though it appeared in Recent Events.
**Root cause:** The LLM system prompt includes `DesktopContext.to_llm_prompt()` which uses `store.current()` — the current foreground window. If the user switches back to the browser to chat, the "current" window is the browser, not Notepad.
**Fix:** Enrich the system prompt with recent window history (last 3-5 apps), not just the current one. The session summary already has `top_apps` — include recent transitions too.
**Files:** `backend/app/desktop_context.py` (add recent apps to prompt), `backend/app/routes/agent.py` (include recent events in system prompt).

---

## Already Fixed (During UAT Session)

- **.env model config:** Fixed `OLLAMA_MODEL=qwen2.5:7b` (was qwen2.5vl:3b)
- **Rate limit:** Bumped from 60/min to 300/min
- **Chat timeout:** Bumped from 30s to 60s for cold model loads
- **Collector startup logs:** Added `println!` messages for debugging

---

## Execution Order

1. **C1** (scroll keyword) — 5 min, one-line fix
2. **H1** (recipe keywords) — 15 min, check + fix keywords
3. **H4** (personality prompts) — 15 min, prompt tuning
4. **H2 + H3** (new chat welcome + chips) — 30 min, UI fix
5. **C4** (enable screenshot/UIA) — 10 min, config + docs
6. **C2** (vision agent done detection) — 45 min, prompt + logic
7. **C3** (window targeting) — 45 min, focus_window pre-flight
8. **M1-M3** (polish) — 30 min each

**Estimated total:** ~4 hours of focused work

---

## Testing Protocol

After each fix:
1. Run `pytest backend/tests/ -m "not integration" -q` — must stay at 491+
2. Run `ruff check backend/app/ backend/tests/` — must be clean
3. Run `pyright backend/app/` — must be clean
4. Manual verification of the specific UAT test case
