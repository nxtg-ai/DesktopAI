# DesktopAI - Claude Code Project Guide

## Project Vision
An intelligent desktop assistant that observes user activity and can autonomously execute tasks like drafting emails, managing windows, and automating workflows.

## Goals
- Ship working MVP with real Windows desktop integration
- Real-time responsiveness with low-latency observation and execution

## Architecture Overview
- **Windows Collector (Rust):** 9 modules (config, event, network, idle, uia, windows, screenshot, command, lib). Captures foreground window changes, idle/active state, recursive UIA element trees, and opt-in desktop screenshots. Compiles for `x86_64-pc-windows-gnu`, 64 tests run on Linux via `#[cfg(windows)]` gates.
- **WSL2 Backend (FastAPI):** State management, SQLite persistence, activity classification (rules + Ollama), autonomy orchestration, Playwright browser automation via CDP. OllamaClient supports `/api/chat` with vision + structured JSON output, auto-fallback on model-not-found. Multi-turn chat memory, notification engine, desktop automation recipes.
- **Web UI:** Glassmorphism design with dark mode toggle, chat with conversation persistence, notification bell, recipe chips, keyboard shortcuts, agent vision, autonomy controls, telemetry dashboard.

## Key Directories
```
backend/app/          - FastAPI application code
backend/app/routes/   - 12 route modules (agent, autonomy, chat_history, ingest, notifications, ollama_routes, readiness, recipes, state, telemetry, ui_telemetry, vision)
backend/tests/        - pytest test suite (286 unit tests)
backend/web/          - Static web UI (HTML/CSS/JS)
backend/web/modules/  - 10 ES modules (state, chat, websocket, events, ollama, autonomy, voice, telemetry, agent-vision, notifications, shortcuts)
collector/            - Rust collector source (64 tests)
ui-tests/             - Playwright end-to-end tests
evals/                - Skill evaluation fixtures
artifacts/            - Test artifacts and telemetry logs
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
make backend-dev               # Start dev server
make backend-test              # Run 286 unit tests (excludes integration)
make backend-test-integration  # Run integration tests with real Ollama

# Linting & Type Checking
ruff check backend/app/ backend/tests/    # Python linting
pyright backend/app/                       # Type checking
cd collector && cargo clippy --all-targets -- -D warnings  # Rust linting

# Rust Collector
cd collector && cargo test     # Run 64 unit tests (Linux-testable)
make collector-build           # Build Windows binary

# UI Testing
make ui-test              # Headless Playwright tests
make ui-test-headed       # Watch browser journey
make ui-gate              # Telemetry validation gate
```

### Environment Setup
```bash
cd /home/axw/projects/DesktopAI
source .venv/bin/activate
pip install -r backend/requirements.txt
```

## API Conventions
- REST endpoints under `/api/`
- WebSocket for real-time: `/ingest` (collector), `/ws` (UI)
- All endpoints return JSON
- Error responses include `error` field with message

## Key API Endpoints
- `POST /api/chat` — Multi-turn chat with desktop context (conversation_id for persistence)
- `GET /api/chat/conversations` — List chat conversations
- `GET /api/notifications` — List notifications (query: unread_only, limit)
- `GET /api/notifications/count` — Unread notification count
- `GET /api/recipes` — Context-filtered automation recipes
- `POST /api/recipes/{id}/run` — Execute a recipe
- `GET /api/state/snapshot` — Current desktop context as JSON
- `GET /api/readiness/status` — System readiness checks

## Testing Standards
- New features require test coverage
- Edge cases and error paths must be tested
- UI journeys emit telemetry for validation
- CI runs ruff, pyright, and clippy before tests

## CI/CD
- `.github/workflows/backend-test.yml` — Lint (ruff) → Type check (pyright) → Test (pytest) → Audit (pip-audit)
- `.github/workflows/rust-test.yml` — Clippy → Test (cargo test)
- `.github/workflows/llm-integration.yml` — Real Ollama integration tests
- Config: `pyproject.toml` (ruff + pyright settings)

## NXTG-Forge

This project uses NXTG-Forge for AI-powered development governance.

- **Vision:** Intelligent desktop assistant with autonomous task execution
- **Goals:** Ship working MVP, Real-time responsiveness
- **Commands:** Type `/[FRG]-` to see available Forge commands
- **Governance:** Project state tracked in `.claude/governance.json`

### Quick Commands
- `/[FRG]-status` — Project status dashboard
- `/[FRG]-feature` — Plan a new feature
- `/[FRG]-gap-analysis` — Analyze project gaps
- `/[FRG]-test` — Run tests with analysis
