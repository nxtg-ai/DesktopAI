# DesktopAI Phase 2

Local‑first desktop context pipeline:
- **Windows collector (Rust):** foreground window changes + idle/active signal + optional UIA snapshot
- **WSL2 backend (FastAPI):** state + SQLite persistence + classification + Web UI
- **Web UI:** live state, category + idle status, filter/search

## Quickstart (WSL2 backend)
```bash
cd /home/axw/projects/DesktopAI
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# run backend
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --reload
```
Open `http://localhost:8000` in a browser (Windows or WSL2).

## Windows collector (build from WSL2)
The collector runs on Windows, but you can build it from WSL2 using the GNU Windows target.

### 1) Install toolchain (WSL2)
```bash
sudo apt-get update
sudo apt-get install -y mingw-w64
rustup target add x86_64-pc-windows-gnu
```

### 2) Build collector
```bash
cargo build --manifest-path collector/Cargo.toml --release --target x86_64-pc-windows-gnu
```

The binary will be at:
```
collector/target/x86_64-pc-windows-gnu/release/desktopai-collector.exe
```

### 3) Run collector on Windows
Copy the `.exe` to Windows and run:
```powershell
$env:BACKEND_WS_URL = "ws://localhost:8000/ingest"
$env:BACKEND_HTTP_URL = "http://localhost:8000/api/events"
$env:IDLE_ENABLED = "1"
$env:IDLE_THRESHOLD_MS = "60000"
$env:UIA_ENABLED = "0"
./desktopai-collector.exe
```

> Note: Windows → WSL2 `localhost` forwarding is typically enabled. If it isn't, set `BACKEND_WS_URL` and `BACKEND_HTTP_URL` to the WSL2 VM IP (from `wsl hostname -I`).

### Collector settings
- `IDLE_ENABLED` (default `1`): enable idle/active events.
- `IDLE_THRESHOLD_MS` (default `60000`): idle threshold.
- `IDLE_POLL_MS` (default `1000`): idle polling interval.
- `UIA_ENABLED` (default `0`): enable UI Automation snapshotting.
- `UIA_THROTTLE_MS` (default `1000`): throttle UIA snapshots.
- `UIA_TEXT_MAX_CHARS` (default `240`): max UIA text length.

## Ollama (optional)
If Ollama is running locally, the backend will expose `/api/summarize`.
- Default URL: `http://localhost:11434`
- Configure via `OLLAMA_URL` and `OLLAMA_MODEL`.
- Configure autonomy planner mode with:
  `AUTONOMY_PLANNER_MODE=deterministic|auto|ollama_required`.
  - `deterministic`: always use local deterministic planner.
  - `auto`: try Ollama first, fallback to deterministic if unavailable/invalid.
  - `ollama_required`: require valid Ollama plan; run start fails when unavailable/invalid.
  - In `ollama_required` mode, `POST /api/autonomy/runs` returns `503` when Ollama is unavailable.

If Ollama is not available, the summary endpoint returns 503 and the UI disables the button.
If `/api/generate` fails (for example 404 from a misconfigured endpoint), backend availability is
temporarily downgraded to avoid repeated failing planner/summary calls until the next health-check window.
If the configured `OLLAMA_MODEL` is missing but other local models exist, DesktopAI retries once with an
installed fallback model and reports both configured and active models in diagnostics.

## Persistence (SQLite)
The backend stores events and derived state in SQLite for durability across restarts.
- Configure the DB path with `BACKEND_DB_PATH` (default `backend/data/desktopai.db`).
- Retention controls:
  - `DB_MAX_EVENTS` limits total rows (oldest pruned).
  - `DB_RETENTION_DAYS` prunes events older than the cutoff.
  - `DB_MAX_AUTONOMY_RUNS` limits persisted autonomy run records (oldest pruned by `updated_at`).
  - `DB_AUTONOMY_RETENTION_DAYS` prunes autonomy run records older than the cutoff (`0` disables age pruning).
  - `DB_MAX_TASK_RECORDS` limits persisted task records (oldest pruned by `updated_at`).
  - `DB_TASK_RETENTION_DAYS` prunes task records older than the cutoff (`0` disables age pruning).
- Autonomy runs are also persisted; on restart, in-flight runs are restored as failed and require explicit restart.
- On backend shutdown, in-flight autonomy runs are marked failed and persisted before exit.
- Task records (including steps/status) are persisted and restored on startup.
- On startup, in-flight task records (`running` / `waiting_approval`) are restored as failed and require explicit rerun.
- On backend shutdown, pending task-record persistence callbacks are drained (up to 2 seconds) before exit.

## Classification
The backend assigns categories to foreground events:
`coding`, `docs`, `comms`, `web`, `terminal`, `meeting`.

By default it uses rules. To allow a local Ollama fallback, set:
`CLASSIFIER_USE_OLLAMA=1`.

## API
- `GET /api/selftest` — local backend self-test (DB path writability, SQLite write probe, config surface)
- `POST /api/events` — ingest event (HTTP)
- `GET /api/state` — current state
- `GET /api/events?limit=N` — recent events
- `POST /api/classify` — classify an event payload
- `GET /api/executor` — action-executor runtime status (`simulated` or `windows-powershell`)
- `GET /api/executor/preflight` — executor readiness checks (platform, PowerShell, COM probe)
- `GET /api/readiness/status` — consolidated readiness summary (executor preflight, collector connection, runtime log buffer, latest autonomy/telemetry pointers, Ollama diagnostic metadata)
- `POST /api/ui-telemetry` — ingest frontend UI telemetry batch and append session artifact logs
- `GET /api/ui-telemetry?session_id=<id>&limit=N` — read recent frontend telemetry events
- `GET /api/ui-telemetry/sessions?limit=N` — list telemetry sessions with event counts and timestamps
- `POST /api/ui-telemetry/reset` — clear in-memory telemetry buffer (and optionally telemetry artifact files)
- `GET /api/runtime-logs?limit=N&level=<LEVEL>&contains=<text>&since=<ISO>&until=<ISO>` — read in-memory backend/runtime logs with optional level/text/time filters
- `GET /api/runtime-logs/correlate?session_id=<id>&limit=N&level=<LEVEL>&contains=<text>` — correlate runtime logs to a frontend telemetry session time window
- `POST /api/runtime-logs/reset` — clear in-memory runtime log buffer
- `GET /api/ollama` — availability info + autonomy planner flag + last-check diagnostics (`last_check_at`, `last_check_source`, `last_http_status`, `last_error`, `configured_model`, `active_model`)
- `GET /api/ollama/models` — list installed Ollama models plus current selection (`configured_model`, `active_model`, `source`)
- `POST /api/ollama/model` — set runtime Ollama model override (must be installed locally), persisted for next backend restart
- `DELETE /api/ollama/model` — clear runtime Ollama model override and revert to configured model
- `POST /api/ollama/probe` — execute a real non-streaming generate probe (`prompt`, `timeout_s`, `allow_fallback`) and return structured result (`ok`, `model`, `elapsed_ms`, `error`, `response_preview`, `response_chars`, `used_fallback`)
- `GET /api/autonomy/planner` — current autonomy planner mode + supported modes + Ollama requirement/availability
- `POST /api/autonomy/planner` — set autonomy planner mode at runtime (`deterministic`, `auto`, `ollama_required`), persisted for next backend restart
- `DELETE /api/autonomy/planner` — clear runtime planner override and revert to configured default mode
- `POST /api/summarize` — optional summary
- `POST /api/tasks` — create task objective
- `POST /api/tasks/{task_id}/plan` — attach explicit plan steps
- `POST /api/tasks/{task_id}/run` — execute planned steps
- `POST /api/tasks/{task_id}/approve` — approve blocked irreversible step
- `POST /api/tasks/{task_id}/pause` — pause task
- `POST /api/tasks/{task_id}/resume` — resume task
- `POST /api/tasks/{task_id}/cancel` — cancel task
- `POST /api/autonomy/runs` — start autonomous run (planner/executor/verifier loop)
- `GET /api/autonomy/runs` — list autonomous runs
- `GET /api/autonomy/runs/{run_id}` — get run state/log
- `POST /api/autonomy/runs/{run_id}/approve` — approve next irreversible step
- `POST /api/autonomy/runs/{run_id}/cancel` — cancel autonomous run
- `POST /api/readiness/gate` — one-shot gate: executor preflight + autonomy objective execution + pass/fail report (`cleanup_on_exit` defaults true to avoid orphan runs)
- `POST /api/readiness/matrix` — run multiple readiness-gate objectives and return aggregate pass/fail summary
- WebSocket ingest: `/ingest`
- WebSocket UI: `/ws`
  - Snapshot payload includes `state`, `events`, and `autonomy_run` (latest run if any).

## Dev UX
Use `.env.example` to configure settings.

### Makefile targets
```bash
make backend-dev
make backend-test
make ui-test
make ui-artifacts
make ui-sessions
make ui-gate
make collector-build
make skills-validate
make skills-score SKILL_CASES=evals/skills/<skill>/cases.json SKILL_RESULTS=<results.json>
make skills-score-all SKILL_RESULTS_ROOT=evals/results/skills
```
Batch scoring expects fixtures at `evals/results/skills/<skill>/results.json`.

## Real UI Testing + Logs
Use Playwright to validate the real browser journey and capture artifacts.

### One-time setup
```bash
cd /home/axw/projects/DesktopAI/ui-tests
npm install
npx playwright install chromium
```

### Run smoke journey
```bash
cd /home/axw/projects/DesktopAI
make ui-test
```

### Watch the real browser journey (headed)
```bash
cd /home/axw/projects/DesktopAI
make ui-test-headed
```

### Watch browser journey while seeing live backend logs
Run backend in terminal A:
```bash
cd /home/axw/projects/DesktopAI
source .venv/bin/activate
make backend-dev
```

Run UI tests in terminal B (reuses running backend, does not spawn an internal test server):
```bash
cd /home/axw/projects/DesktopAI
make ui-test-live
```

Smoke coverage now includes:
- page boot + live websocket connection
- autonomy run start flow
- real `/api/events` ingestion reflected in the UI
- telemetry emission for streamed events (`event_stream_received`)
- irreversible approval flow (`waiting_approval -> completed`) telemetry
- cancel flow (`waiting_approval -> cancelled`) telemetry
- journey console session selection + rendered telemetry events in UI
- readiness status panel (consolidated check summary)
- Ollama status diagnostics panel (`last_error`/status/source surfaced in UI)
- Ollama model controls (list installed models + apply/reset runtime override)
- Ollama probe control (`Probe Model`) with real generate pass/fail result in UI
- planner mode selector (live runtime update via API)
- runtime readiness panel executor preflight interaction
- readiness gate trigger from UI with rendered completion status
- readiness matrix trigger from UI with rendered pass/fail breakdown
- runtime log panel with refresh, level/text filters, session correlation, and clear action
- correlated runtime-log view stays pinned across polling until manual refresh/clear

Readiness summary now includes:
- required check totals (`required_total`, `required_passed`, `required_failed`)
- optional warning count (`warning_count`)
- optional `ollama_available` signal (warning-only; does not fail required readiness)
- optional Ollama model selection state (`ollama_model_source`, `ollama_configured_model`, `ollama_active_model`)
- optional Ollama diagnostics (`ollama_last_check_at`, `ollama_last_check_source`, `ollama_last_http_status`, `ollama_last_error`)
- `autonomy_planner_mode` (`deterministic`, `auto`, or `ollama_required`)
- `autonomy_planner_source` (`config_default` or `runtime_override`)

Artifacts are written to:
- `artifacts/ui/playwright/report/index.html` (HTML report)
- `artifacts/ui/playwright/test-results/` (trace, screenshot, video)
- `artifacts/ui/telemetry/<session-id>.jsonl` (human-visible UI journey log)
- `/api/ui-telemetry` and `/api/ui-telemetry/sessions` fall back to artifact files when in-memory telemetry is cleared.

Backend settings:
- `UI_TELEMETRY_ARTIFACT_DIR` (default `artifacts/ui/telemetry`)
- `UI_TELEMETRY_MAX_EVENTS` (default `5000`)
- `RUNTIME_LOG_MAX_ENTRIES` (default `2000`)
- `AUTONOMY_PLANNER_MODE` (default `deterministic`)
- `ACTION_EXECUTOR_MODE` (`auto`, `windows`, `simulated`)
- `ACTION_EXECUTOR_TIMEOUT_S` (default `20`)
- `ACTION_EXECUTOR_POWERSHELL` (default `powershell.exe`)
- `ACTION_EXECUTOR_DEFAULT_COMPOSE_TEXT` (default `Draft generated by DesktopAI.`)
- `ACTION_EXECUTOR_RETRY_COUNT` (default `2`)
- `ACTION_EXECUTOR_RETRY_DELAY_MS` (default `150`)

Action execution modes:
- `auto`: use real Windows PowerShell executor only on Windows hosts with PowerShell available; otherwise simulated.
- `windows`: force Windows PowerShell executor (task steps fail on non-Windows hosts or when PowerShell is unavailable).
- `simulated`: deterministic backend-only execution (for test/dev fallback).
Task action execution retries transient failures up to `ACTION_EXECUTOR_RETRY_COUNT`; unsupported-action errors fail fast without retries.

Inspect live-ish telemetry while iterating:
```bash
curl -s "http://localhost:8000/api/ui-telemetry?limit=50" | jq
```

Run one-shot readiness gate:
```bash
curl -s "http://localhost:8000/api/readiness/gate" \
  -H "Content-Type: application/json" \
  -d '{"objective":"Open outlook, draft reply, then send email","auto_approve_irreversible":true,"timeout_s":30}' | jq
```
Response includes `cleanup` metadata (`attempted`, `cancelled`, `error`) for gate-run cleanup behavior.

Run readiness matrix:
```bash
curl -s "http://localhost:8000/api/readiness/matrix" \
  -H "Content-Type: application/json" \
  -d '{"objectives":["Observe desktop and verify outcome","Open outlook, draft reply, then send email"],"auto_approve_irreversible":true,"timeout_s":30}' | jq
```

In the browser console, use `window.__desktopaiTelemetrySessionId` to fetch one session:
```bash
curl -s "http://localhost:8000/api/ui-telemetry?session_id=<SESSION_ID>&limit=200" | jq
```

Quick artifact summary:
```bash
make ui-artifacts
```

List telemetry sessions from the live backend:
```bash
make ui-sessions
```

Telemetry gate (fails if required telemetry kinds are missing from latest gate journey):
```bash
make ui-gate
```
Required kinds are configured in `ui-tests/telemetry-gate.json`.
CI also runs this gate via `.github/workflows/ui-gate.yml`.
The gate targets the explicit session recorded by the gate journey at `artifacts/ui/telemetry/latest-gate-session.txt`, so test ordering does not create false negatives.
`make ui-gate` clears this session pointer before each run to prevent stale-pass scenarios.

### Agent TDD loop (repo default)
- Keep a short test-case list and execute one behavior slice at a time.
- Red: write/update a test and prove it fails for the expected reason.
- Green: implement the smallest change to pass.
- Refactor immediately while keeping tests green.
- Run checks in order: targeted tests first, then full suite + lint/type checks.
- Add at least one negative/edge test for each new behavior.
- Update docs/contracts only for user-visible or API-visible changes.
- For exploratory tasks, do a short spike/spec first and then return to strict TDD.

### Optional pre-commit hook
```bash
pip install pre-commit
pre-commit install
```

## Notes
- The collector emits **foreground**, **idle**, and **active** events.
- UIA snapshots are optional and throttled; they capture only focused element name/control type and short text excerpt.
- The backend keeps a **memory cache** for fast UI updates and persists to SQLite.
- No keystrokes, screenshots, or cloud calls in the core path.
