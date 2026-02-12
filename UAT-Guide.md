# DesktopAI - User Acceptance Testing Guide

**Tester:** ___________________
**Date:** ___________________
**Environment:** Windows 11 + WSL2 backend + Ollama local

---

## Prerequisites Checklist

Before testing, confirm the stack is running:

```bash
# 1. Ollama running with models pulled
ollama list   # Expect: qwen2.5:7b, qwen2.5vl:7b

# 2. Start the backend (from WSL2)
cd /home/axw/projects/DesktopAI
source .venv/bin/activate
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000

# 3. Start the collector (from Windows)
C:\temp\desktopai\desktopai-collector.exe

# 4. Open the Tauri app OR the web UI
#    Web UI: http://localhost:8000/
#    Tauri:  cargo tauri dev  (from tauri-app/)
```

**Verification:**
- [ ] Backend is running at http://localhost:8000
- [ ] `GET http://localhost:8000/api/readiness/status` returns `{"ok": true}`
- [ ] Ollama is accessible at http://localhost:11434
- [ ] Collector is connected (check `GET http://localhost:8000/api/agent/bridge`)

**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

---

## Section 1: Core Chat

### 1.1 Basic Chat (No Actions)

**Steps:**
1. Open the Tauri avatar (or web UI)
2. Type "Hello, what can you do?" in the chat input
3. Press Enter or click the send button

**Expected:**
- Message appears in chat as a user bubble
- Typing indicator shows while waiting
- AI response appears as an assistant bubble
- Response describes DesktopAI's capabilities
- Source should be "ollama" (if Ollama is running)

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 1.2 Desktop Context Awareness

**Steps:**
1. Open Notepad (or any recognizable app) on Windows
2. Wait 2-3 seconds for the collector to send the event
3. In the chat, ask "What am I working on?"

**Expected:**
- Response mentions the app you have open (e.g., "You're currently in Notepad")
- Context bar in the UI updates to show the current app
- Response may include UIA element names if UIA is enabled

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 1.3 Multi-Turn Conversation Persistence

**Steps:**
1. Send: "My name is Alex"
2. Send: "What did I just tell you?"

**Expected:**
- Second response references "Alex" (proving conversation memory)
- Both messages appear in the chat history
- conversation_id stays the same across both messages

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 1.4 New Chat

**Steps:**
1. Have an existing conversation with messages
2. Click the "New Chat" button (or press `Ctrl+Shift+N`)

**Expected:**
- Chat messages clear
- Welcome screen reappears with suggestion chips
- Sending a new message creates a fresh conversation_id

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 1.5 Suggestion Chips

**Steps:**
1. Start a New Chat (so the welcome screen is visible)
2. Click the "What am I doing?" chip

**Expected:**
- Chip text is sent as a chat message
- AI responds with desktop context information

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

---

## Section 2: Personality Modes

### 2.1 Switch Personality Mode

**Steps:**
1. Click the "Copilot" pill in the chat header
2. Send: "Help me organize my files"
3. Click the "Operator" pill
4. Send: "Help me organize my files"

**Expected:**
- Copilot response is concise, technical, jargon-heavy
- Operator response is minimal, action-focused, no pleasantries
- Active pill is visually highlighted

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 2.2 Personality Status API

**Steps:**
1. Open browser: `http://localhost:8000/api/personality`

**Expected:**
- JSON with: `current_mode`, `auto_adapt_enabled`, `session_energy`, `recommended_mode`, `session_summary`
- `session_summary` shows `app_switches`, `unique_apps`, `session_duration_s`

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

---

## Section 3: Desktop Actions (The Core Feature)

### 3.1 Action Intent Detection

**Steps:**
1. Make sure `allow_actions: true` (default in Tauri/web UI)
2. Type: "Open Notepad"

**Expected:**
- Response acknowledges an action was triggered
- An autonomy run starts (check action badge or run status)
- If collector is connected: Notepad actually opens on Windows

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 3.2 Click Action via VisionAgent

**Steps:**
1. Open an app with a visible button (e.g., Calculator, Notepad with File menu)
2. Type: "Click on File"

**Expected:**
- VisionAgent run starts (bridge connected + vision enabled)
- Agent observes the desktop (screenshot + UIA tree)
- Agent reasons about what to click
- File menu opens on the Windows desktop
- Run completes with status "completed"

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 3.3 Type Text Action

**Steps:**
1. Open Notepad and ensure cursor is in the text area
2. Type in chat: "Type 'Hello from DesktopAI' into the current window"

**Expected:**
- Text "Hello from DesktopAI" appears in Notepad
- Agent sends type_text command via bridge to collector

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 3.4 Draft Email Reply (Recipe)

**Steps:**
1. Open Outlook (or any email client)
2. Open an email you want to reply to
3. In chat, type: "Draft a reply"

**Expected:**
- Recipe keyword match triggers `reply_to_email` recipe
- Autonomy run starts with the recipe steps
- Agent observes desktop, composes reply text, may attempt to send

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 3.5 Scroll Action

**Steps:**
1. Open a webpage or document with scrollable content
2. In chat: "Scroll down"

**Expected:**
- Page scrolls down on the Windows desktop
- Agent confirms the scroll action completed

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

---

## Section 4: Autonomy System

### 4.1 Start an Autonomy Run (API)

**Steps:**
```bash
curl -X POST http://localhost:8000/api/autonomy/runs \
  -H "Content-Type: application/json" \
  -d '{"objective": "Check what app is currently open", "max_iterations": 5}'
```

**Expected:**
- Response contains `run.run_id`, `run.status` (running or completed)
- Run appears in `GET /api/autonomy/runs`

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 4.2 List and Get Runs

**Steps:**
1. `GET http://localhost:8000/api/autonomy/runs`
2. Copy a run_id from the list
3. `GET http://localhost:8000/api/autonomy/runs/{run_id}`

**Expected:**
- List returns `{"runs": [...]}` sorted by updated_at descending
- Single run returns full details with agent_log entries

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 4.3 Cancel a Run

**Steps:**
1. Start a run with high max_iterations (e.g., 100)
2. `POST http://localhost:8000/api/autonomy/runs/{run_id}/cancel`

**Expected:**
- Run status changes to "cancelled"
- Agent stops executing further steps

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 4.4 Kill Switch (Cancel All)

**Steps:**
1. Start 2-3 runs quickly
2. Click the red kill button in Tauri (or press `Ctrl+Shift+X`)
   - OR: `POST http://localhost:8000/api/autonomy/cancel-all`

**Expected:**
- All running/waiting runs are cancelled
- Kill button pulses red while active, then hides when no runs are active
- Response: `{"cancelled": N, "runs": [...]}`

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 4.5 Run Status Display (Tauri)

**Steps:**
1. Start a run that takes multiple iterations
2. Watch the Tauri avatar during execution

**Expected:**
- Avatar orb changes color to indicate running state
- Step-by-step progress appears in the UI
- Agent log entries show reasoning and actions taken
- Status icon (spinner, checkmark, or X) shown per step

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

---

## Section 5: VisionAgent

### 5.1 VisionAgent Run (API)

**Steps:**
```bash
curl -X POST http://localhost:8000/api/agent/run \
  -H "Content-Type: application/json" \
  -d '{"objective": "Describe what you see on the screen", "max_iterations": 3}'
```

**Expected:**
- Returns 200 with `{"run": {...}}` if bridge is connected + vision agent enabled
- Returns 503 if bridge is disconnected or vision agent disabled
- Agent takes screenshots, reasons with VLM (qwen2.5vl:7b), and acts

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 5.2 VisionAgent Confidence Gating

**Steps:**
1. Give the agent an ambiguous objective: "Click the most important button"
2. Watch the agent log for confidence scores

**Expected:**
- Agent reports confidence per action (0.0-1.0)
- Actions below `VISION_AGENT_MIN_CONFIDENCE` (0.3) are skipped
- Agent may complete early if unsure about what to do

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 5.3 Bridge Status

**Steps:**
1. `GET http://localhost:8000/api/agent/bridge`

**Expected:**
- `{"connected": true}` when collector is running
- `{"connected": false}` when collector is stopped

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

---

## Section 6: Notifications

### 6.1 Notification Bell (Tauri)

**Steps:**
1. Click the bell icon in the Tauri title bar

**Expected:**
- Dropdown appears with notification list (may be empty initially)
- Badge shows unread count (0 if none)

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 6.2 Idle Notification

**Steps:**
1. Stop using the keyboard/mouse for 5+ minutes (or set `NOTIFICATION_IDLE_THRESHOLD_S=30` for faster testing)
2. Resume activity

**Expected:**
- An idle notification appears ("You've been idle for X minutes")
- Bell badge count increments
- Clicking the notification marks it as read

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 6.3 App Switch Notification

**Steps:**
1. Rapidly switch between 10+ apps within 60 seconds

**Expected:**
- "Frequent app switching" notification triggers
- Notification suggests focusing on one task

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 6.4 Session Milestone Notification

**Steps:**
1. Keep the backend running for 1+ hour with the collector connected

**Expected:**
- At 1 hour: session milestone notification ("1 hour session")
- Additional milestones at 2h, 4h

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 6.5 Notification API

**Steps:**
```bash
# List notifications
curl http://localhost:8000/api/notifications

# Unread count
curl http://localhost:8000/api/notifications/count

# Mark as read (use a real notification_id)
curl -X POST http://localhost:8000/api/notifications/{id}/read

# Delete
curl -X DELETE http://localhost:8000/api/notifications/{id}
```

**Expected:**
- Each endpoint returns correct JSON
- 404 for nonexistent notification IDs

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

---

## Section 7: Recipes

### 7.1 Context-Filtered Recipe List

**Steps:**
1. Open Outlook/mail client on Windows
2. `GET http://localhost:8000/api/recipes`

**Expected:**
- `reply_to_email` recipe appears in the filtered list (matched by "outlook/mail" pattern)
- `total_available` is 3 (the total built-in count)

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 7.2 Recipe Chips in Tauri

**Steps:**
1. Open Outlook/mail client
2. Wait for context to update in Tauri (2-3 seconds)

**Expected:**
- Recipe chips appear below the chat input
- Chips show relevant recipes for the current app
- Clicking a chip sends the recipe command as a chat message

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 7.3 Run a Recipe (API)

**Steps:**
```bash
curl -X POST http://localhost:8000/api/recipes/schedule_focus/run
```

**Expected:**
- Returns `{"run_id": "...", "recipe": {...}}`
- Autonomy run starts with the recipe's steps

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

---

## Section 8: Desktop State & Observation

### 8.1 Desktop Snapshot

**Steps:**
1. `GET http://localhost:8000/api/state/snapshot`

**Expected:**
- JSON with current desktop state
- Includes `window_title`, `process_exe`, timestamps
- If UIA enabled: includes element tree
- If screenshot enabled: includes `screenshot_b64`

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 8.2 Event Stream

**Steps:**
1. `GET http://localhost:8000/api/state/events?limit=10`

**Expected:**
- Returns recent foreground/idle events
- Each event has: type, title, process_exe, timestamp

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 8.3 Session Summary

**Steps:**
1. `GET http://localhost:8000/api/state/session`

**Expected:**
- Summary with: app_switches, unique_apps, session_duration_s, top_apps[]
- top_apps sorted by dwell time

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 8.4 Collector Status

**Steps:**
1. `GET http://localhost:8000/api/state/collector`

**Expected:**
- Shows heartbeat_age_s and connected boolean
- connected=true when collector is sending events

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

---

## Section 9: Tauri Avatar UI

### 9.1 Window Dragging

**Steps:**
1. Click and drag the avatar area or the top drag handle

**Expected:**
- Window moves freely on the desktop
- No click events fire on draggable regions

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 9.2 Compact Mode

**Steps:**
1. Click the compact toggle button (arrows icon)

**Expected:**
- Chat section hides, window shrinks to avatar-only mode
- Click again to expand back to full chat

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 9.3 Close to Tray

**Steps:**
1. Click the X button in the title bar

**Expected:**
- Window hides (minimizes to system tray)
- App is still running in background
- Click tray icon to restore

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 9.4 Context Bar

**Steps:**
1. Switch between apps on Windows
2. Watch the context bar below the avatar

**Expected:**
- Context bar updates with the current app name/title
- Small icon shows to the left

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 9.5 Status Indicator

**Steps:**
1. Observe the status dot below the avatar

**Expected:**
- Shows "connecting" initially
- Changes to "connected" when backend is reachable
- Updates with collector status

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

---

## Section 10: Keyboard Shortcuts

| Shortcut | Action | Expected |
|---|---|---|
| `/` | Focus chat input | Chat input gets focus |
| `Escape` | Blur and clear input | Input clears and loses focus |
| `Ctrl+Enter` | Send message | Same as clicking Send |
| `Ctrl+Shift+N` | New conversation | Clears chat, resets conversation |
| `Ctrl+Shift+X` | Kill all actions | Cancels all running autonomy runs |

**Steps:** Test each shortcut in the Tauri app.

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

---

## Section 11: Ollama & Model Management

### 11.1 Ollama Status

**Steps:**
1. `GET http://localhost:8000/api/ollama`

**Expected:**
- `{"ok": true, "model": "qwen2.5:7b", "url": "http://localhost:11434"}`

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 11.2 Model Override

**Steps:**
```bash
# Set model
curl -X POST http://localhost:8000/api/ollama/model \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen2.5:3b"}'

# Check it stuck
curl http://localhost:8000/api/ollama

# Clear override
curl -X DELETE http://localhost:8000/api/ollama/model
```

**Expected:**
- Model changes to qwen2.5:3b after POST
- Reverts to default (qwen2.5:7b) after DELETE

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 11.3 Ollama Probe

**Steps:**
```bash
curl -X POST http://localhost:8000/api/ollama/probe \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Say hello", "timeout_s": 10}'
```

**Expected:**
- Returns `{"ok": true, "response": "...", "latency_ms": N}`
- Response contains the LLM's greeting

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

---

## Section 12: Autonomy Planner

### 12.1 Planner Mode

**Steps:**
```bash
# Check current mode
curl http://localhost:8000/api/autonomy/planner

# Set to deterministic
curl -X POST http://localhost:8000/api/autonomy/planner \
  -H "Content-Type: application/json" \
  -d '{"mode": "deterministic"}'

# Set to auto (uses Ollama when available)
curl -X POST http://localhost:8000/api/autonomy/planner \
  -H "Content-Type: application/json" \
  -d '{"mode": "auto"}'

# Clear override
curl -X DELETE http://localhost:8000/api/autonomy/planner
```

**Expected:**
- GET shows mode, source (config_default or runtime_override), and ollama status
- POST changes mode and source to runtime_override
- DELETE resets to config default (auto)

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 12.2 Autonomy Promotion

**Steps:**
1. `GET http://localhost:8000/api/autonomy/promotion`

**Expected:**
- Returns: `recommended_level`, `current_level`, `consecutive_successes`, `reason`, `auto_promote_enabled`
- After 5 consecutive successful runs: recommended_level promotes from supervised to guided

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

---

## Section 13: System Readiness

### 13.1 Readiness Status

**Steps:**
1. `GET http://localhost:8000/api/readiness/status`

**Expected:**
- `{"ok": true/false, "checks": [...], "summary": "...", "generated_at": "..."}`
- Checks include: ollama, database, executor availability
- Each check has: name, ok, required

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 13.2 Executor Preflight

**Steps:**
1. `GET http://localhost:8000/api/executor/preflight`

**Expected:**
- Shows executor mode, availability, and any issues
- `{"ok": true, "mode": "bridge", "checks": [...]}`

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 13.3 Self-Test

**Steps:**
1. `GET http://localhost:8000/api/selftest`

**Expected:**
- Returns system health diagnostics
- Tests internal subsystems are functional

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

---

## Section 14: Chat History

### 14.1 List Conversations

**Steps:**
1. Have at least 2 chat conversations
2. `GET http://localhost:8000/api/chat/conversations`

**Expected:**
- Returns list of conversations with IDs and titles
- Most recent conversations first

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 14.2 Get Conversation Messages

**Steps:**
1. Copy a conversation_id from the list above
2. `GET http://localhost:8000/api/chat/conversations/{id}`

**Expected:**
- Returns all messages in the conversation
- Each message has: role (user/assistant), content, timestamp

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 14.3 Delete Conversation

**Steps:**
1. `DELETE http://localhost:8000/api/chat/conversations/{id}`
2. Verify it's gone from the list

**Expected:**
- Returns success
- Conversation no longer appears in list

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

---

## Section 15: End-to-End Scenarios

These are real-world workflows that chain multiple features together.

### 15.1 "Morning Standup" Flow

**Steps:**
1. Open your IDE/editor and email client
2. Ask: "What have I been working on?"
3. Ask: "Summarize my current activity"
4. Ask: "Draft a status update"

**Expected:**
- DesktopAI tracks your app usage across the session
- Summarize response covers your recent activity patterns
- Draft response creates a coherent status update
- Actions trigger if bridge is connected

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 15.2 "Email Triage" Flow

**Steps:**
1. Open Outlook/email client
2. Open an email
3. Ask: "Draft a reply"
4. Watch the VisionAgent observe and act

**Expected:**
- Recipe `reply_to_email` is matched
- Agent observes the email content
- Agent composes and potentially types a reply
- Run completes with steps visible in UI

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 15.3 "Focus Mode" Flow

**Steps:**
1. Have multiple apps open
2. Ask: "Start a focus session"

**Expected:**
- Recipe `schedule_focus` triggers
- Agent focuses the current window
- Notification about focus mode appears

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 15.4 "Kill Switch Under Pressure"

**Steps:**
1. Start 3 autonomy runs rapidly via chat:
   - "Open Calculator"
   - "Open Notepad"
   - "Click the Start button"
2. Immediately press `Ctrl+Shift+X`

**Expected:**
- All 3 runs cancel
- Kill button appears and pulses red
- Kill button disappears after all runs cancel
- No stale actions continue executing

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

---

## Section 16: Error Handling & Edge Cases

### 16.1 Chat Without Ollama

**Steps:**
1. Stop Ollama: `ollama stop` or kill the process
2. Send a chat message

**Expected:**
- Response falls back to context-based response (not an error)
- Source should be "context" instead of "ollama"
- No server crash or 500 error

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 16.2 Actions Without Collector

**Steps:**
1. Stop the collector on Windows
2. Ask: "Open Notepad"

**Expected:**
- Action triggers but falls back gracefully
- If VisionAgent: 503 error or graceful fallback
- If orchestrator: uses simulated executor (acknowledges without real action)
- Chat response should still be coherent

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 16.3 Empty Chat Input

**Steps:**
1. Try to send an empty message (just spaces or nothing)

**Expected:**
- Message is not sent
- No error displayed
- Input stays focused for retry

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

### 16.4 Rapid-Fire Messages

**Steps:**
1. Send 5 messages in quick succession

**Expected:**
- All messages are queued and processed
- No messages are lost
- Each gets a response (may take time)
- No duplicate responses

**Result:** [ ] PASS  [ ] FAIL  [ ] PARTIAL
**Feedback:**
```
_____________________________________________________________________
_____________________________________________________________________
```

---

## Overall Assessment

### Summary

| Section | Status | Notes |
|---|---|---|
| 1. Core Chat | | |
| 2. Personality Modes | | |
| 3. Desktop Actions | | |
| 4. Autonomy System | | |
| 5. VisionAgent | | |
| 6. Notifications | | |
| 7. Recipes | | |
| 8. Desktop State | | |
| 9. Tauri Avatar UI | | |
| 10. Keyboard Shortcuts | | |
| 11. Ollama Management | | |
| 12. Autonomy Planner | | |
| 13. System Readiness | | |
| 14. Chat History | | |
| 15. E2E Scenarios | | |
| 16. Error Handling | | |

### Top Issues Found
```
1. ___________________________________________________________________
2. ___________________________________________________________________
3. ___________________________________________________________________
4. ___________________________________________________________________
5. ___________________________________________________________________
```

### What Worked Well
```
_____________________________________________________________________
_____________________________________________________________________
```

### What Needs Improvement
```
_____________________________________________________________________
_____________________________________________________________________
```

### Blockers for Production
```
_____________________________________________________________________
_____________________________________________________________________
```

---

**Test Counts:**
- 491 automated Python tests passing
- 72 automated Rust tests passing
- 16 UAT sections above with 40+ manual test cases
- All lint (ruff, clippy) and type checks (pyright) clean
