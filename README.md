<p align="center">
  <img src="docs/assets/banner.svg" alt="DesktopAI" width="100%"/>
</p>

<p align="center">
  <a href="#quickstart"><strong>Quickstart</strong></a> &nbsp;&middot;&nbsp;
  <a href="#architecture"><strong>Architecture</strong></a> &nbsp;&middot;&nbsp;
  <a href="#features"><strong>Features</strong></a> &nbsp;&middot;&nbsp;
  <a href="#api-reference"><strong>API</strong></a> &nbsp;&middot;&nbsp;
  <a href="#testing"><strong>Testing</strong></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Rust-000000?style=for-the-badge&logo=rust&logoColor=white" alt="Rust"/>
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Tauri-24C8D8?style=for-the-badge&logo=tauri&logoColor=white" alt="Tauri"/>
  <img src="https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite"/>
  <img src="https://img.shields.io/badge/WSL2-FCC624?style=for-the-badge&logo=linux&logoColor=black" alt="WSL2"/>
</p>

<p align="center">
  <img src="https://github.com/nxtg-ai/DesktopAI/actions/workflows/backend-test.yml/badge.svg" alt="Backend Tests"/>
  <img src="https://github.com/nxtg-ai/DesktopAI/actions/workflows/rust-test.yml/badge.svg" alt="Rust Tests"/>
  <img src="https://img.shields.io/badge/tests-493%20passing-brightgreen" alt="Tests"/>
  <img src="https://img.shields.io/badge/cloud%20deps-zero-blue" alt="Zero cloud deps"/>
  <img src="https://img.shields.io/badge/license-private-lightgrey" alt="License"/>
</p>

---

An intelligent desktop assistant that **observes** your Windows activity in real time, **classifies** what you're doing, and can **autonomously execute** tasks like drafting emails, managing windows, and automating workflows &mdash; all running locally with zero cloud dependencies.

> *"Everyone else suggests. We execute."* &mdash; [myVISION.md](./myVISION.md)

---

## Quickstart

### 1. Backend (WSL2) &mdash; 2 minutes

```bash
git clone https://github.com/nxtg-ai/DesktopAI.git
cd DesktopAI
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt

# Start the backend
make backend-dev
```

Open **http://localhost:8000** &mdash; you should see the glassmorphism UI with dark mode, chat, and notification bell.

### 2. Windows Collector &mdash; 3 minutes

```bash
# Install cross-compilation toolchain (WSL2, one-time)
sudo apt-get update && sudo apt-get install -y mingw-w64
rustup target add x86_64-pc-windows-gnu

# Build the collector
make collector-build
# Output: collector/target/x86_64-pc-windows-gnu/release/desktopai-collector.exe
```

Copy `desktopai-collector.exe` to Windows and run:

```powershell
$env:BACKEND_WS_URL = "ws://localhost:8000/ingest"
$env:BACKEND_HTTP_URL = "http://localhost:8000/api/events"
$env:IDLE_ENABLED = "1"
$env:UIA_ENABLED = "0"
./desktopai-collector.exe
```

When connected, you'll see a notification: *"DesktopAI can now see and control your desktop."*

> **Tip:** Windows &rarr; WSL2 `localhost` forwarding is typically automatic. If not, use the WSL2 VM IP from `wsl hostname -I`.

### 3. Verify &mdash; 30 seconds

```bash
# Run tests to verify everything works
make backend-test     # 423 Python tests
cd collector && cargo test   # 70 Rust tests
```

### 4. Optional: Local LLM

```bash
# Install Ollama for AI-powered responses
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1:8b

# Backend auto-detects Ollama at localhost:11434
```

### 5. Optional: Authentication

```bash
API_TOKEN=my-secret-token make backend-dev
# All /api/* endpoints now require: Authorization: Bearer my-secret-token
```

---

## Architecture

<table>
<tr>
<td width="33%">

### Rust Collector
Windows-native observer (9 modules, 70 tests). Hooks Win32 and UI Automation APIs for foreground windows, idle/active state, recursive UIA trees, and desktop screenshots. 9 desktop commands (click, type, scroll, etc.). Heartbeat ping/pong. Ships events over WebSocket with exponential backoff reconnection.

</td>
<td width="34%">

### FastAPI Backend
Python brain running in WSL2 (423 unit tests). State management, SQLite persistence, activity classification, multi-turn chat with desktop context, notification engine (4 rules), 3 automation recipes, autonomy orchestration with approval gates, and bridge command execution to the collector.

</td>
<td width="33%">

### Web UI + Tauri Avatar
Glassmorphism UI with dark mode, multi-turn chat with conversation persistence, notification bell, recipe chips, keyboard shortcuts, agent vision panel, autonomy controls. Tauri native overlay for 3D avatar with state-driven animations.

</td>
</tr>
</table>

**Key architectural decision:** Rust owns the desktop (collector, Tauri, Win32/COM/UIA). Python owns the brain (LLM, chat, planning, orchestration). This is locked in &mdash; Python is I/O bound on LLM calls, Rust provides platform depth.

---

## Features

<table>
<tr>
<td align="center" width="25%">
<br/>
<strong>Closed-Loop Autonomy</strong><br/>
<sub>Observe &rarr; Plan &rarr; Execute &rarr; Verify. 9 desktop commands over WebSocket bridge. Vision agent with confidence gating.</sub>
<br/><br/>
</td>
<td align="center" width="25%">
<br/>
<strong>Multi-Turn Chat</strong><br/>
<sub>Conversational AI with desktop context, screenshot inclusion, recipe matching, and action intent detection.</sub>
<br/><br/>
</td>
<td align="center" width="25%">
<br/>
<strong>3 Personality Modes</strong><br/>
<sub>Co-pilot (calm), Assistant (proactive), Operator (silent execution). User selects or auto-adapts.</sub>
<br/><br/>
</td>
<td align="center" width="25%">
<br/>
<strong>Zero Cloud Dependencies</strong><br/>
<sub>Everything local. Ollama for LLM. Cloud FM is opt-in additive, never required.</sub>
<br/><br/>
</td>
</tr>
</table>

<details>
<summary><strong>All capabilities</strong></summary>
<br/>

| Capability | Description |
|---|---|
| **3-Tier Autonomy** | Supervised (every action pauses), Guided (routine free, novel pauses), Autonomous (full execution) |
| **Kill Switch** | Ctrl+Shift+X hotkey, UI button, API cancel. Instant halt mid-execution. |
| **Session Greeting** | Notification when collector connects: "DesktopAI can now see and control your desktop." |
| **Heartbeat** | Ping/pong between backend and collector (30s). Detects stale connections. |
| **Context Insights** | Detects app-toggle patterns ("switching between Outlook and Excel for 20 min") and deep focus |
| **Notification Engine** | 4 rules: idle detection, rapid app switching, session milestones, context insights |
| **Desktop Recipes** | 3 built-in automation recipes with keyword matching from chat |
| **Trajectory Learning** | Error lessons extracted from failed runs, fed back into planning |
| **Security Hardening** | Token auth, rate limiting, security headers, WebSocket connection limits |
| **Dark Mode** | CSS custom property toggle with localStorage persistence |
| **Keyboard Shortcuts** | `/` focus chat, `Escape` blur, `Ctrl+Enter` send, `Ctrl+Shift+N` new chat |
| **Voice Control** | Browser-native STT/TTS with live transcript |
| **Ollama Integration** | Vision + structured JSON output, auto-fallback, runtime model hot-swap |
| **Browser Automation** | Playwright via CDP for web-based task execution |
| **Screenshot Capture** | GDI-based with JPEG encoding, configurable downscaling |
| **UI Telemetry** | Frontend journey telemetry with session artifacts |

</details>

---

## API Reference

<details>
<summary><strong>57 endpoints</strong> &mdash; click to expand</summary>
<br/>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/chat` | Multi-turn chat with desktop context and screenshot |
| `GET` | `/api/chat/conversations` | List conversations |
| `GET` | `/api/chat/conversations/{id}` | Get conversation messages |
| `DELETE` | `/api/chat/conversations/{id}` | Delete conversation |
| | | |
| `GET` | `/api/notifications` | List notifications |
| `GET` | `/api/notifications/count` | Unread count |
| `POST` | `/api/notifications/{id}/read` | Mark as read |
| `DELETE` | `/api/notifications/{id}` | Delete notification |
| | | |
| `GET` | `/api/recipes` | Context-filtered automation recipes |
| `POST` | `/api/recipes/{id}/run` | Execute a recipe |
| | | |
| `GET` | `/api/state` | Current window state |
| `GET` | `/api/state/snapshot` | Desktop context as JSON |
| `POST` | `/api/events` | Ingest event (HTTP) |
| `GET` | `/api/events` | Recent events |
| `GET` | `/api/collector` | Collector connection status |
| | | |
| `POST` | `/api/tasks` | Create task |
| `GET` | `/api/tasks` | List tasks |
| `GET` | `/api/tasks/{id}` | Get task |
| `POST` | `/api/tasks/{id}/plan` | Attach plan steps |
| `POST` | `/api/tasks/{id}/run` | Execute plan |
| `POST` | `/api/tasks/{id}/approve` | Approve irreversible step |
| `POST` | `/api/tasks/{id}/pause` | Pause |
| `POST` | `/api/tasks/{id}/resume` | Resume |
| `POST` | `/api/tasks/{id}/cancel` | Cancel |
| | | |
| `POST` | `/api/autonomy/runs` | Start autonomous run |
| `GET` | `/api/autonomy/runs` | List runs |
| `GET` | `/api/autonomy/runs/{id}` | Get run state/log |
| `POST` | `/api/autonomy/runs/{id}/approve` | Approve next step |
| `POST` | `/api/autonomy/runs/{id}/cancel` | Cancel run |
| `GET` | `/api/autonomy/planner` | Planner mode status |
| `POST` | `/api/autonomy/planner` | Set planner mode |
| `DELETE` | `/api/autonomy/planner` | Reset to default |
| | | |
| `POST` | `/api/agent/run` | Start vision agent run |
| `GET` | `/api/agent/bridge` | Bridge connection status |
| | | |
| `GET` | `/api/readiness/status` | Readiness summary |
| `POST` | `/api/readiness/gate` | One-shot gate |
| `POST` | `/api/readiness/matrix` | Multi-objective matrix |
| `GET` | `/api/executor` | Executor runtime status |
| `GET` | `/api/executor/preflight` | Executor readiness |
| `GET` | `/api/health` | Health check (always public) |
| `GET` | `/api/selftest` | Backend self-test |
| | | |
| `GET` | `/api/ollama` | Ollama diagnostics |
| `GET` | `/api/ollama/models` | Installed models |
| `POST` | `/api/ollama/model` | Set model override |
| `DELETE` | `/api/ollama/model` | Clear override |
| `POST` | `/api/ollama/probe` | Generate probe |
| `POST` | `/api/classify` | Classify event |
| `POST` | `/api/summarize` | Context summary |
| | | |
| `POST` | `/api/ui-telemetry` | Ingest UI telemetry |
| `GET` | `/api/ui-telemetry` | List telemetry events |
| `GET` | `/api/ui-telemetry/sessions` | List sessions |
| `POST` | `/api/ui-telemetry/reset` | Clear telemetry |
| `GET` | `/api/runtime-logs` | Runtime logs |
| `GET` | `/api/runtime-logs/correlate` | Correlate to session |
| `POST` | `/api/runtime-logs/reset` | Clear logs |
| | | |
| `WS` | `/ingest` | Collector event stream + heartbeat |
| `WS` | `/ws` | UI real-time updates |

</details>

---

## Testing

```bash
# Python backend (423 unit tests)
make backend-test                              # Fast: excludes integration
make backend-test-integration                  # Requires running Ollama

# Linting & type checking
ruff check backend/app/ backend/tests/         # 0 errors expected
pyright backend/app/                           # 0 errors, 7 warnings (pre-existing)

# Rust collector (70 tests)
cd collector && cargo test
cd collector && cargo clippy --all-targets -- -D warnings

# UI (Playwright)
make ui-test                                   # Headless browser tests
make ui-test-headed                            # Watch the browser journey
```

---

## Configuration

<details>
<summary><strong>Backend environment variables</strong></summary>
<br/>

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND_HOST` | `0.0.0.0` | Server bind address |
| `BACKEND_PORT` | `8000` | Server port |
| `API_TOKEN` | *(empty)* | Bearer token (empty = no auth) |
| `BACKEND_DB_PATH` | `backend/data/desktopai.db` | SQLite database path |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API URL |
| `OLLAMA_MODEL` | `llama3.1:8b` | Default model |
| `ACTION_EXECUTOR_MODE` | `auto` | `auto` / `bridge` / `simulated` / `playwright` |
| `RATE_LIMIT_PER_MINUTE` | `60` | API rate limit per IP |
| `WS_MAX_CONNECTIONS` | `50` | Max WebSocket connections |
| `COLLECTOR_HEARTBEAT_INTERVAL_S` | `30` | Heartbeat ping interval |
| `NOTIFICATIONS_ENABLED` | `true` | Enable notification engine |
| `AUTONOMY_PLANNER_MODE` | `deterministic` | `deterministic` / `auto` / `ollama_required` |

</details>

<details>
<summary><strong>Collector environment variables</strong></summary>
<br/>

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND_WS_URL` | `ws://localhost:8000/ingest` | WebSocket endpoint |
| `BACKEND_HTTP_URL` | `http://localhost:8000/api/events` | HTTP fallback |
| `IDLE_ENABLED` | `1` | Enable idle/active events |
| `IDLE_THRESHOLD_MS` | `60000` | Idle timeout |
| `UIA_ENABLED` | `0` | Enable UI Automation snapshots |
| `ENABLE_SCREENSHOT` | `0` | Enable desktop screenshots |
| `COMMAND_ENABLED` | `1` | Enable remote command execution |

</details>

---

## Privacy

DesktopAI is **local-first and privacy-preserving**:

- No keystrokes are captured
- Screenshots are **opt-in** and disabled by default
- No data leaves your network in the core path
- Ollama runs locally &mdash; cloud LLM is opt-in additive
- UIA snapshots are optional, throttled, and depth-limited

---

<p align="center">
  <sub>Built by <a href="https://nxtg.ai">NXTG.AI</a> &mdash; <em>"We don't play with the cutting edge. We shape the bleeding edge."</em></sub>
</p>
