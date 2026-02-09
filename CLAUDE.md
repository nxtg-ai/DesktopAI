# DesktopAI - Claude Code Project Guide

## Project Vision
An intelligent desktop assistant that observes user activity and can autonomously execute tasks like drafting emails, managing windows, and automating workflows.

## Goals
- Ship working MVP with real Windows desktop integration
- Real-time responsiveness with low-latency observation and execution

## Architecture Overview
- **Windows Collector (Rust):** 8 modules (config, event, network, idle, uia, windows, screenshot, lib). Captures foreground window changes, idle/active state, recursive UIA element trees, and opt-in desktop screenshots. Compiles for `x86_64-pc-windows-gnu`, 55 tests run on Linux via `#[cfg(windows)]` gates.
- **WSL2 Backend (FastAPI):** State management, SQLite persistence, activity classification (rules + Ollama), autonomy orchestration, Playwright browser automation via CDP. OllamaClient supports `/api/chat` with vision + structured JSON output, auto-fallback on model-not-found.
- **Web UI:** Live state display, category filters, autonomy controls, telemetry dashboard

## Key Directories
```
backend/app/       - FastAPI application code
backend/tests/     - pytest test suite
backend/web/       - Static web UI (HTML/CSS/JS)
collector/         - Rust collector source
ui-tests/          - Playwright end-to-end tests
evals/             - Skill evaluation fixtures
artifacts/         - Test artifacts and telemetry logs
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
make backend-test              # Run 125 unit tests (excludes integration)
make backend-test-integration  # Run 8 real Ollama integration tests

# Rust Collector
cd collector && cargo test     # Run 55 unit tests (Linux-testable)
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

## Testing Standards
- New features require test coverage
- Edge cases and error paths must be tested
- UI journeys emit telemetry for validation
- Pre-commit hooks run linting

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
