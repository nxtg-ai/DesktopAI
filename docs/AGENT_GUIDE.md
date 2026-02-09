# DesktopAI Autonomous Agent — Setup & Usage Guide

Get the full autonomous agent running on your Windows machine with real
desktop observation, real LLM-powered planning, and real action execution.

---

## What You Need

| Component | Purpose | Install |
|-----------|---------|---------|
| **Windows 10/11** | The desktop you're automating | You're on it |
| **WSL2** | Runs the Python backend | [Install WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) |
| **Python 3.10+** | Backend runtime | `sudo apt install python3 python3-venv` in WSL2 |
| **Rust toolchain** | Build the collector | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` in WSL2 |
| **MinGW cross-compiler** | Cross-compile collector for Windows | `sudo apt install mingw-w64` in WSL2 |
| **Ollama** | Local LLM — the agent's brain | [ollama.com](https://ollama.com) — install the Windows version |

---

## Step 1: Install Ollama and Pull Models

On **Windows**, install Ollama from [ollama.com](https://ollama.com), then open a terminal:

```powershell
# Pull a general model (planning, classification, text drafting):
ollama pull llama3.1:8b

# Pull a vision model (reads screenshots — needed for compose_text with images):
ollama pull llava:7b
```

Verify it's running:
```powershell
curl http://localhost:11434/api/tags
```

You should see your models listed.

---

## Step 2: Start the Backend (WSL2)

Open your WSL2 terminal:

```bash
cd /path/to/DesktopAI
source .venv/bin/activate
pip install -r backend/requirements.txt   # first time only
```

Create a `.env` file in the project root with these settings:

```bash
# .env — real agent configuration

# Executor: real Windows PowerShell actions
ACTION_EXECUTOR_MODE=windows

# Planner: use Ollama to generate action plans
AUTONOMY_PLANNER_MODE=auto

# Ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
OLLAMA_VISION_MODEL=llava:7b

# Enable Ollama for activity classification too
CLASSIFIER_USE_OLLAMA=1
```

Start the backend:

```bash
make backend-dev
```

Verify:
```bash
curl http://localhost:8000/api/health
# → {"status":"ok"}

curl http://localhost:8000/api/ollama
# → "available": true
```

If `"available": false`, Ollama isn't reachable from WSL2. Check that Ollama is
running on Windows and try `curl http://$(hostname).local:11434/api/tags` to
find the right address. Update `OLLAMA_URL` in `.env` accordingly.

---

## Step 3: Build and Run the Windows Collector

### Build (in WSL2)

```bash
# One-time setup:
rustup target add x86_64-pc-windows-gnu

# Build:
make collector-build
```

The binary is at `collector/target/x86_64-pc-windows-gnu/release/desktopai-collector.exe`.

### Run (on Windows)

Copy the `.exe` to a folder on Windows, then in PowerShell:

```powershell
# Connect to the backend
$env:BACKEND_WS_URL = "ws://localhost:8000/ingest"
$env:BACKEND_HTTP_URL = "http://localhost:8000/api/events"

# Enable UI Automation tree capture (the agent needs this to "see" UI elements)
$env:UIA_ENABLED = "1"
$env:UIA_MAX_DEPTH = "3"

# Enable desktop screenshots (the agent uses these for vision-powered text drafting)
$env:ENABLE_SCREENSHOT = "1"
$env:SCREENSHOT_QUALITY = "85"

# Enable idle detection
$env:IDLE_ENABLED = "1"
$env:IDLE_THRESHOLD_MS = "60000"

./desktopai-collector.exe
```

You should see log output showing events being sent.

### Verify the connection

Back in WSL2:

```bash
curl http://localhost:8000/api/collector
```

You need to see:
```json
{"ws_connected": true, "total_events": ...}
```

Now switch between a couple windows on your desktop and check:

```bash
curl http://localhost:8000/api/state/snapshot
```

You should see your actual desktop state:
```json
{
  "context": {
    "window_title": "Inbox - you@company.com - Outlook",
    "process_exe": "OUTLOOK.EXE",
    "uia_summary": "Focused: Reply\nControl: Button\nTree:\n  ...",
    "screenshot_available": true
  }
}
```

If `window_title` shows your real window and `screenshot_available` is `true`,
the collector is working.

---

## Step 4: Verify All Systems

Run the consolidated readiness check:

```bash
curl http://localhost:8000/api/readiness/status | python3 -m json.tool
```

**All four checks must pass:**

| Check | What it means |
|-------|---------------|
| `executor_preflight: ok` | PowerShell is available and can execute commands |
| `collector_connected: ok` | The Windows collector is sending desktop state |
| `ollama_available: ok` | Ollama is reachable with a model loaded |
| `runtime_log_buffer: ok` | Backend logging is working |

If any check fails, fix it before continuing. The executor preflight
runs several sub-checks:

```bash
curl http://localhost:8000/api/executor/preflight | python3 -m json.tool
```

This tests: Windows host detected, PowerShell found, PowerShell roundtrip works,
WScript.Shell COM object available (needed for SendKeys).

---

## Step 5: Run a Real Autonomous Task

### From the Web UI

1. Open **http://localhost:8000** in your browser
2. In the **Autonomy** section, type your objective, for example:
   - `draft email reply in Outlook`
   - `open Notepad and type a meeting summary`
   - `search for recent emails`
3. Click **Start Run**
4. Watch the steps execute in real time
5. When a step is **irreversible** (like Send), you'll see an **Approve** button — the agent **will not proceed** without your click

### From the command line

```bash
# Start a run:
curl -X POST http://localhost:8000/api/autonomy/runs \
  -H "Content-Type: application/json" \
  -d '{"objective": "draft email reply in Outlook"}'
```

Copy the `run_id` from the response, then monitor:

```bash
# Check status:
curl http://localhost:8000/api/autonomy/runs/RUN_ID_HERE | python3 -m json.tool
```

### What happens during a real run

Using "draft email reply in Outlook" as an example:

| Step | Action | What actually happens |
|------|--------|----------------------|
| 1 | `observe_desktop` | Reads the collector's latest event: window title, UIA tree, screenshot. Returns JSON with what's on screen. |
| 2 | `open_application` | PowerShell runs `Start-Process outlook.exe` to launch/focus Outlook. |
| 3 | `compose_text` | Ollama receives the desktop context + screenshot and generates a draft reply. PowerShell types it into the active window via SendKeys. |
| 4 | `send_or_submit` | **PAUSED.** Waits for your approval. Only after you approve does PowerShell send Ctrl+Enter. |
| 5 | `verify_outcome` | Reads the desktop state again and compares it to the state before step 4. Reports what changed (window title, UI elements). |

---

## Approving Irreversible Actions

The agent **never** sends, submits, deletes, or publishes without asking first.

When a run pauses:

**Web UI:** Click the **Approve** button next to the run.

**Command line:**
```bash
# Get the run (includes approval_token):
curl http://localhost:8000/api/autonomy/runs/RUN_ID_HERE

# Approve with the token:
curl -X POST http://localhost:8000/api/autonomy/runs/RUN_ID_HERE/approve \
  -H "Content-Type: application/json" \
  -d '{"approval_token": "TOKEN_FROM_RESPONSE"}'
```

To **cancel** instead:
```bash
curl -X POST http://localhost:8000/api/autonomy/runs/RUN_ID_HERE/cancel
```

---

## How the Agent Sees Your Desktop

```
┌─────────────────────┐
│  Your Windows       │
│  Desktop            │
│  (Outlook, Chrome,  │
│   VS Code, etc.)    │
└─────────┬───────────┘
          │ Win32 + UI Automation + GDI Screenshot
          ▼
┌─────────────────────┐
│  Rust Collector     │──── WebSocket ────▶ Backend StateStore
│  (desktopai-        │                         │
│   collector.exe)    │                   DesktopContext:
└─────────────────────┘                   • window_title
                                          • process_exe
                                          • uia_summary (UI tree, max 2KB)
                                          • screenshot_b64 (JPEG)
                                                │
                         ┌──────────────────────┼──────────────────────┐
                         ▼                      ▼                      ▼
                   Planner                Orchestrator              Executor
                   adds desktop           captures state         observe: returns
                   context to LLM         before each step       what's on screen
                   prompt so plans                               compose: LLM sees
                   match reality                                 context + screenshot
                                                                 verify: diff before
                                                                 vs after state
```

---

## Troubleshooting

### Collector won't connect

```bash
# Check from WSL2:
curl http://localhost:8000/api/collector
```

- `"ws_connected": false` — The collector can't reach the backend.
  Make sure WSL2 localhost forwarding works: from Windows PowerShell,
  `curl http://localhost:8000/api/health` should return `{"status":"ok"}`.
- Collector crashes on start — Check the PowerShell output for errors.
  Common issue: antivirus blocking the `.exe`.

### Ollama not available

```bash
curl http://localhost:8000/api/ollama
```

- `"available": false` — Ollama not reachable. Is it running on Windows?
  Try `ollama list` in Windows PowerShell.
- `"last_error": "..."` — Check the error. Common: wrong URL, model not pulled.
- Run a test probe:
  ```bash
  curl -X POST http://localhost:8000/api/ollama/probe \
    -H "Content-Type: application/json" \
    -d '{"prompt": "say hello in one sentence"}'
  ```

### Executor preflight fails

```bash
curl http://localhost:8000/api/executor/preflight | python3 -m json.tool
```

- `windows_host: false` — Backend doesn't detect Windows. Expected on WSL2;
  the executor uses `powershell.exe` which WSL2 can access.
- `powershell_available: false` — PowerShell not in PATH. Try:
  `which powershell.exe` in WSL2. If missing, set `ACTION_EXECUTOR_POWERSHELL`
  to the full path (e.g., `/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe`).
- `wscript_shell_com: false` — COM object unavailable. This is needed for SendKeys.

### Agent sees blank desktop state

```bash
curl http://localhost:8000/api/state/snapshot
# → {"context": null}
```

No events have been received. Check:
1. Is the collector running?
2. Switch windows on your desktop — each switch triggers an event.
3. Check `curl http://localhost:8000/api/events?limit=3` for recent events.

### Agent drafts garbage text

The compose_text quality depends on the model. Try:
- A larger model: `ollama pull llama3.1:70b` (if you have the VRAM)
- A different model: `qwen2.5:7b` handles structured tasks well
- Switch at runtime:
  ```bash
  curl -X POST http://localhost:8000/api/ollama/model \
    -H "Content-Type: application/json" \
    -d '{"model": "qwen2.5:7b"}'
  ```

---

## Configuration Reference

All settings go in `.env` or as environment variables before `make backend-dev`.

### Must-set for real usage

| Variable | Value | Why |
|----------|-------|-----|
| `ACTION_EXECUTOR_MODE` | `windows` | Real PowerShell execution |
| `AUTONOMY_PLANNER_MODE` | `auto` | LLM-powered planning |
| `OLLAMA_MODEL` | `llama3.1:8b` | General model for planning + drafting |
| `OLLAMA_VISION_MODEL` | `llava:7b` | Vision model for screenshot analysis |

### Collector settings (set on Windows before running collector)

| Variable | Value | Why |
|----------|-------|-----|
| `BACKEND_WS_URL` | `ws://localhost:8000/ingest` | Connect to backend |
| `UIA_ENABLED` | `1` | Agent sees UI elements |
| `UIA_MAX_DEPTH` | `3` | How deep to scan UI tree |
| `ENABLE_SCREENSHOT` | `1` | Agent gets visual context |
| `SCREENSHOT_QUALITY` | `85` | JPEG quality |

---

## End-to-End Smoke Test

Run this after everything is set up to confirm the full loop works:

```bash
# 1. Verify all systems
curl http://localhost:8000/api/readiness/status | python3 -m json.tool
# All checks must be "ok": true

# 2. Verify desktop state is flowing
curl http://localhost:8000/api/state/snapshot | python3 -m json.tool
# Must show your actual window title, not null

# 3. Run a safe test (observe + verify only, no Send action)
curl -X POST http://localhost:8000/api/autonomy/runs \
  -H "Content-Type: application/json" \
  -d '{"objective": "observe what I am currently doing"}'

# 4. Check the run completed
curl http://localhost:8000/api/autonomy/runs | python3 -m json.tool
# Latest run should show status: "completed"
```

If all four steps succeed, the agent is fully operational.
