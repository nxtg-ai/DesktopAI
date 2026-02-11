# DesktopAI - Claude Code Project Guide

## Project Vision
An intelligent desktop assistant that observes user activity and can autonomously execute tasks like drafting emails, managing windows, and automating workflows. Read `myVISION.md` for the canonical product vision — every feature must trace back to it.

## Goals
- Ship working MVP with real Windows desktop integration
- Real-time responsiveness with low-latency observation and execution
- Dogfood daily — we are the user

## Architecture Overview
- **Windows Collector (Rust):** 9 modules (config, event, network, idle, uia, windows, screenshot, command, lib). 9 desktop commands (observe, click, type_text, send_keys, open_application, focus_window, scroll, double_click, right_click). Heartbeat ping/pong. Compiles for `x86_64-pc-windows-gnu`, 70 tests run on Linux via `#[cfg(windows)]` gates.
- **WSL2 Backend (FastAPI):** State management, SQLite persistence, activity classification (rules + Ollama), autonomy orchestration, Playwright browser automation via CDP. OllamaClient supports `/api/chat` with vision + structured JSON output. Multi-turn chat memory, notification engine (4 rules: idle, app-switch, milestone, context-insight), desktop automation recipes.
- **Web UI:** Glassmorphism design with dark mode toggle, chat with conversation persistence, notification bell, recipe chips, keyboard shortcuts, agent vision, autonomy controls, telemetry dashboard.
- **Closed-loop agent:** Collector -> StateStore -> DesktopContext -> Executor/Orchestrator/Planner. The observe->decide->act->verify loop uses real desktop state (UIA trees, screenshots).

## Architecture Decision: Rust + Python Split (Locked In)
- **Rust owns the desktop**: collector, Tauri, Win32/COM/UIA, small binary
- **Python owns the brain**: LLM orchestration, chat, planning, context, FastAPI
- Rationale: Python is I/O bound (LLM calls), Rust for platform depth. Ship fast > rewrite.

## Key Directories
```
backend/app/          - FastAPI application code
backend/app/routes/   - 12 route modules
backend/tests/        - pytest test suite (423 unit tests)
backend/web/          - Static web UI (HTML/CSS/JS)
backend/web/modules/  - 10 ES modules
collector/            - Rust collector source (70 tests)
tauri-app/            - Tauri native desktop app (avatar overlay)
ui-tests/             - Playwright end-to-end tests
```

## Development Workflow

### TDD Loop (Strict)
1. Write/update a test and prove it fails
2. Implement the smallest change to pass
3. Refactor while keeping tests green
4. Run targeted tests first, then full suite

### Quick Commands
```bash
# Backend
cd /home/axw/projects/DesktopAI
source .venv/bin/activate
pytest backend/tests/ -m "not integration" -q   # 423 unit tests
uvicorn app.main:app --app-dir backend           # Dev server

# Linting & Type Checking
ruff check backend/app/ backend/tests/           # Python linting
pyright backend/app/                              # Type checking (0 errors expected)
cd collector && cargo clippy --all-targets -- -D warnings  # Rust linting

# Rust Collector
cd collector && cargo test                        # 70 tests (Linux-testable)

# UI Testing
make ui-test                                      # Headless Playwright
```

## API Conventions
- REST endpoints under `/api/`
- WebSocket for real-time: `/ingest` (collector), `/ws` (UI)
- All endpoints return JSON
- Error responses include `error` field with message

## Key API Endpoints
- `POST /api/chat` — Multi-turn chat with desktop context (conversation_id, screenshot_b64)
- `GET /api/chat/conversations` — List chat conversations
- `GET /api/notifications` — List notifications (query: unread_only, limit)
- `GET /api/recipes` — Context-filtered automation recipes
- `GET /api/state/snapshot` — Current desktop context as JSON
- `GET /api/readiness/status` — System readiness checks
- `POST /api/agent/run` — Start vision-based autonomous agent run
- `POST /api/autonomy/start` — Start orchestrator-based autonomous run

## Testing Standards
- 423 Python unit tests, 70 Rust tests — never decrease
- New features require test coverage
- Edge cases and error paths must be tested
- CI runs ruff, pyright, and clippy before tests
- `conftest.py` sets `ACTION_EXECUTOR_MODE=simulated` — executor tested separately

## Key Patterns
- SQLite stores: separate DB file, `threading.Lock`, `asyncio.to_thread`, WAL mode
- Notification rules: extend `NotificationRule`, implement `check(snapshot)`, return dict or None
- Chat action intent: recipe keyword match first, then `_ACTION_KEYWORDS` set
- Bridge executor passes commands through to Rust collector via WebSocket
- Pydantic v2 only — use `model_copy(deep=True)`, no v1 shims

## Critical Gotchas
- **Bridge startup race**: `build_action_executor(auto)` runs at startup before collector connects. NEVER check `bridge.connected` in the factory. BridgeActionExecutor handles disconnection gracefully at runtime.
- **MagicMock truthy attrs**: `MagicMock().connected` is truthy. Always set `mock.connected = False` explicitly.
- **conftest.py**: Must set `ACTION_EXECUTOR_MODE=simulated` for test isolation.
- **WindowEvent**: Uses `ConfigDict(extra="allow")` — access `screenshot_b64` via `getattr(event, "screenshot_b64", None)`.
- **Dev server**: `uvicorn app.main:app --app-dir backend` (not `backend.app.main`).

## CI/CD
- `.github/workflows/backend-test.yml` — Lint (ruff) -> Type check (pyright) -> Test (pytest)
- `.github/workflows/rust-test.yml` — Clippy -> Test (cargo test)
- `.github/workflows/llm-integration.yml` — Real Ollama integration tests
- Config: `pyproject.toml` (ruff + pyright settings)

## What's Shipped (Sprints 1-5)
- Closed-loop autonomy (observe->plan->execute->verify)
- 3-tier autonomy levels (supervised/guided/autonomous)
- 3 personality modes (copilot/assistant/operator)
- Kill switch (Ctrl+Shift+X, UI button, API)
- Vision agent with confidence gating
- Trajectory-based error learning
- Multi-turn chat memory with conversation persistence
- Notification engine with 4 rules (idle, app-switch, milestone, context-insight)
- 3 desktop automation recipes
- Security hardening (auth, rate limiting, headers, WS limits)
- Session greeting on collector connect
- Heartbeat ping/pong
- 9 collector desktop commands
- Chat screenshot inclusion
- Dark mode, keyboard shortcuts, glassmorphism UI

## What's Next (Sprint 6+ — see BACKLOG.md)
- Automatic personality adaptation based on session energy
- Autonomy auto-promotion (supervised->guided->autonomous) via success rate
- 3D Blender avatar with WebGL/WebGPU renderer
- Avatar expandable limbs (context/log/reasoning panels)
- Avatar marketplace (skins + skill packs)
- Developer quickstart README
