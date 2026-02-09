# Architecture

## System Overview

DesktopAI is a three-tier local-first desktop assistant: a **Rust collector** on Windows captures desktop context, a **FastAPI backend** on WSL2 processes and orchestrates, and a **Web UI** provides real-time visibility and control.

```
Windows Host                      WSL2 (Linux)
+-----------------------+         +---------------------------+
| Rust Collector        |  WS/HTTP| FastAPI Backend            |
|  - foreground hooks   | ------> |  - state management       |
|  - idle detection     |         |  - SQLite persistence     |
|  - UIA tree walker    |         |  - activity classification|
|  - screenshot capture |         |  - autonomy orchestration |
+-----------------------+         |  - action execution       |
                                  +---------------------------+
                                        |  WS
                                        v
                                  +---------------------------+
                                  | Web UI (SPA)              |
                                  |  - live event stream      |
                                  |  - autonomy controls      |
                                  |  - telemetry dashboard    |
                                  +---------------------------+
```

## Components

### 1. Windows Collector (Rust)

8-module library compiled for `x86_64-pc-windows-gnu`. 55 unit tests run on Linux via `#[cfg(windows)]` conditional compilation.

| Module | Responsibility |
|--------|---------------|
| `config.rs` | Environment-driven configuration (env_bool, env_u64, env_usize, env_u32, env_u8) |
| `event.rs` | Data structures: WindowEvent, UiaSnapshot, UiaElement, build_activity_event |
| `windows.rs` | Win32 hooks (SetWinEventHook), window title, process path, event dispatch |
| `uia.rs` | UI Automation tree walker with recursive depth-limited element capture, pattern detection |
| `idle.rs` | Idle/active state machine via GetLastInputInfo polling |
| `network.rs` | WebSocket connection (tungstenite) with HTTP POST fallback |
| `screenshot.rs` | GDI-based desktop capture, JPEG encoding, 5-frame ring buffer, base64 |
| `lib.rs` | Module declarations, re-exports, main `run()` orchestration |

**Key behaviors:**
- Event-driven (no polling for foreground changes)
- UIA capture: recursive tree walk with configurable max depth, 20-child cap, pattern detection (Value, Toggle, Invoke)
- Screenshot: opt-in (`ENABLE_SCREENSHOT=1`), downscaled to configurable max dimensions, JPEG-compressed

### 2. FastAPI Backend (Python)

19 source files, 125 unit tests + 8 integration tests. Runs on WSL2.

| Module | Responsibility |
|--------|---------------|
| `main.py` | App factory, WebSocket endpoints (`/ingest`, `/ws`), REST routes |
| `state.py` | In-memory state + event ring buffer, WebSocket broadcast |
| `db.py` | SQLite persistence with retention pruning |
| `ollama.py` | OllamaClient: `/api/chat` (vision, structured JSON output), `/api/generate`, auto-fallback |
| `classifier.py` | Activity classification: rule engine + optional Ollama LLM fallback |
| `planner.py` | Autonomy planning: deterministic + Ollama-powered with structured output |
| `action_executor.py` | Multi-executor: Simulated, WindowsPowerShell, Playwright-CDP |
| `playwright_executor.py` | Browser automation via Chrome DevTools Protocol |
| `schemas.py` | Pydantic models for all API contracts |
| `config.py` | Environment-based settings with `_env()` / `_env_bool()` / `_env_int()` helpers |

### 3. Web UI (Static SPA)

Vanilla HTML/CSS/JS served from `backend/web/`. Real-time updates via WebSocket.

## Interfaces

### Collector -> Backend
- **WebSocket (preferred):** `ws://<host>:<port>/ingest` — JSON WindowEvent per message
- **HTTP fallback:** `POST /api/events` — JSON WindowEvent body

### Backend -> UI
- **WebSocket:** `ws://<host>:<port>/ws`
  - `{"type":"snapshot","state":...,"events":[...]}`
  - `{"type":"event","event":...}`
  - `{"type":"state","state":...}`
- **REST:** 40+ endpoints under `/api/`

## Data Model

### WindowEvent
| Field | Type | Notes |
|---|---|---|
| type | string | `foreground`, `idle`, `active` |
| hwnd | string | Hex HWND |
| title | string | Window title |
| process_exe | string | Full exe path |
| pid | int | Process ID |
| timestamp | datetime | RFC3339 UTC |
| source | string | `"collector"` |
| idle_ms | int? | Idle duration (idle/active events) |
| category | string? | Activity category |
| uia | UiaSnapshot? | UI Automation data |

### UiaSnapshot
| Field | Type | Notes |
|---|---|---|
| focused_name | string | Focused element name |
| control_type | string | Focused element type |
| document_text | string | Truncated text content |
| focused_element | UiaElement? | Detailed focused element tree |
| window_tree | UiaElement[] | Full window element hierarchy |

### UiaElement (recursive)
| Field | Type | Notes |
|---|---|---|
| automation_id | string | AutomationId property |
| name | string | Name property |
| control_type | string | ControlType (Button, Edit, etc.) |
| class_name | string | ClassName |
| bounding_rect | int[4]? | [x, y, width, height] |
| is_enabled | bool | Enabled state |
| is_offscreen | bool | Offscreen state |
| patterns | string[] | Detected patterns (Value, Toggle, Invoke) |
| value | string? | Value pattern text |
| toggle_state | string? | Off/On/Indeterminate |
| children | UiaElement[] | Child elements (depth-limited) |

### TaskRecord
| Field | Type | Notes |
|---|---|---|
| task_id | string | UUID |
| objective | string | User-provided goal |
| status | TaskStatus | created/planned/running/waiting_approval/paused/completed/failed/cancelled |
| steps | TaskStep[] | Ordered action steps |
| approval_token | string? | For irreversible step approval |

### AutonomyRunRecord
| Field | Type | Notes |
|---|---|---|
| run_id | string | UUID |
| objective | string | Goal to achieve |
| planner_mode | string | deterministic/auto/ollama_required |
| status | AutonomyRunStatus | running/waiting_approval/completed/failed/cancelled |
| iteration | int | Current iteration count |
| agent_log | AgentLogEntry[] | Execution trace |

## Autonomy Pipeline

```
Objective
    |
    v
[Planner] -- deterministic (keyword rules)
    |      -- auto (try Ollama, fall back to deterministic)
    |      -- ollama_required (structured JSON output via /api/chat)
    v
[Plan: TaskStepPlan[]]
    |
    v
[Executor] -- simulated (dry run)
    |       -- windows-powershell (SendKeys, Start-Process)
    |       -- playwright-cdp (navigate, click, fill, screenshot)
    v
[Approval Gate] -- irreversible actions require token approval
    |
    v
[Verifier] -- verify_outcome step
```

## Ollama Integration

The OllamaClient supports:
- **`/api/chat`**: Vision (base64 images), structured JSON output (format=JSON schema), multi-turn messages
- **`/api/generate`**: Legacy text generation
- **Auto-fallback**: If configured model not found, discovers available models and picks best match
- **Multi-model**: Per-role models (classifier, planner, executor) via config
- **Health tracking**: TTL-based availability cache with diagnostics

## Action Executors

| Mode | Description |
|------|-------------|
| `simulated` | Dry-run, returns success without side effects |
| `windows-powershell` | Real Windows automation via PowerShell COM (SendKeys, Start-Process) |
| `playwright-cdp` | Browser automation via Chrome DevTools Protocol (navigate, click, fill, read_text, screenshot, evaluate) |
| `auto` | Windows: try PowerShell, fall back to simulated. Non-Windows: simulated |

## Security & Privacy

- **Local-first**: No data leaves the network in the core path
- **No keystrokes captured**: Only window metadata and optional UIA/screenshots
- **Screenshots opt-in**: Disabled by default (`ENABLE_SCREENSHOT=0`)
- **Optional auth**: Bearer token via `API_TOKEN` env var
- **CORS**: Configurable allow-list via `ALLOWED_ORIGINS`
- **Localhost binding**: Default `0.0.0.0` for WSL2 forwarding; restrict as needed

## Deployment

```
WSL2:  uvicorn serves backend + UI on localhost:8000
Windows: desktopai-collector.exe sends to ws://localhost:8000/ingest
```

WSL2 localhost forwarding allows Windows to reach the backend. If not available, use the WSL2 VM IP from `wsl hostname -I`.

## CI/CD

| Workflow | Trigger | Description |
|----------|---------|-------------|
| `backend-test.yml` | Push to main, PRs | Python unit tests + pip-audit |
| `llm-integration.yml` | Push to main | Real Ollama tests with qwen3:1.7b |
| `rust-test.yml` | Push to main, PRs | Rust collector unit tests |
| `skills-validate.yml` | PRs | Skill fixture validation |
| `skills-score.yml` | PRs | Skill scoring |
| `ui-gate.yml` | PRs | Playwright UI telemetry gate |
