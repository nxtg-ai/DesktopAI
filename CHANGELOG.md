# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added
- **Rate limiting** — per-IP sliding-window rate limiter on all API endpoints (429 with `Retry-After`). Configurable via `RATE_LIMIT_PER_MINUTE`.
- **Module-level docstrings** across all 28 Python modules in `backend/app/`.
- **Pinned dependencies** — `backend/requirements.lock` with exact versions for reproducible production builds.
- **`.env.example`** — comprehensive environment variable reference with defaults and comments.
- **Test coverage** — 25 new tests for `action_executor.py`, 7 new auth edge-case tests (248 total).

### Changed
- **Extracted route modules** — split 1273-line `main.py` monolith into 9 focused APIRouter modules under `backend/app/routes/`.
- **Shared singletons** — moved all module-level singletons to `backend/app/deps.py`.
- **CORS hardened** — restricted `allow_methods` and `allow_headers` from wildcards to explicit lists.
- **PowerShell escaping hardened** — added null-byte rejection, length limits, and action allowlisting in `_ps_quote()`.

### Fixed
- **11 silent exception handlers** across `ollama.py`, `autonomy.py`, `orchestrator.py`, and `planner.py` now log with `logger.debug()` instead of silently swallowing errors.

## [0.5.0] — 2026-02-08

### Added
- **Trajectory memory** — SQLite-backed `TrajectoryStore` with FTS5 full-text search for agent experience replay.
- **Vision agent confidence gating** — low-confidence actions downgraded to "wait" (configurable `VISION_AGENT_MIN_CONFIDENCE`).
- **Trajectory-informed planning** — Ollama planner injects similar past trajectories as context.
- **Tauri voice integration** — STT/TTS support in the Tauri desktop overlay.
- **Test DB isolation** — each test gets its own in-memory database to prevent cross-test interference.

## [0.4.0] — 2026-02-06

### Added
- **Windows command bridge** — bidirectional WebSocket protocol between Python backend and Rust collector for real-time desktop control.
- **Reactive vision agent** — VLM-guided observe-reason-act loop with error recovery and exponential backoff.
- **Bridge action executor** — maps high-level actions to native Windows commands via the bridge.

### Fixed
- **WebSocket/fetch data extraction** — corrected event parsing in ingest and state endpoints.
- **Markdown chat rendering** — chat responses now render markdown properly in the web UI.

## [0.3.0] — 2026-02-04

### Added
- **Tauri v2 floating avatar overlay** — always-on-top transparent window for Windows desktop.
- **Chat interface** — message bubbles, typing indicator, suggestion chips, context bar with live/offline status.
- **Agent vision panel** — real-time display of window title, process name, UIA element tree, and screenshot status.
- **Setup guide** — interactive readiness checks and configuration walkthrough in the web UI.

## [0.2.0] — 2026-01-30

### Added
- **Closed-loop agent pipeline** — observe-decide-act-verify loop using real desktop state (UIA trees, screenshots).
- **`DesktopContext`** — frozen dataclass wrapping window title, process, UIA summary, and optional screenshot.
- **Enhanced executor actions** — `observe_desktop`, `compose_text` (LLM + vision), `verify_outcome` (before/after diff).
- **Debug endpoint** — `GET /api/state/snapshot` returns current desktop context as JSON.

## [0.1.0] — 2026-01-25

### Added
- **Rust collector** — 9 modules capturing foreground windows, idle state, UIA element trees, and screenshots. Cross-compiles for `x86_64-pc-windows-gnu`.
- **FastAPI backend** — event storage (SQLite), activity classification, autonomy orchestration, Playwright CDP executor.
- **OllamaClient** — async HTTP client with `/api/chat` for vision + structured output, auto-fallback on model-not-found.
- **Web UI** — glassmorphism design with avatar canvas, voice STT/TTS, autonomy controls, telemetry dashboard.
- **API token authentication** — optional `API_TOKEN` env var with Bearer header and WebSocket query param support.
- **CI pipelines** — GitHub Actions for backend tests, LLM integration tests, and Rust CI.
