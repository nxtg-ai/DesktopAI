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

If Ollama is not available, the summary endpoint returns 503 and the UI disables the button.

## Persistence (SQLite)
The backend stores events and derived state in SQLite for durability across restarts.
- Configure the DB path with `BACKEND_DB_PATH` (default `backend/data/desktopai.db`).
- Retention controls:
  - `DB_MAX_EVENTS` limits total rows (oldest pruned).
  - `DB_RETENTION_DAYS` prunes events older than the cutoff.

## Classification
The backend assigns categories to foreground events:
`coding`, `docs`, `comms`, `web`, `terminal`, `meeting`.

By default it uses rules. To allow a local Ollama fallback, set:
`CLASSIFIER_USE_OLLAMA=1`.

## API
- `POST /api/events` — ingest event (HTTP)
- `GET /api/state` — current state
- `GET /api/events?limit=N` — recent events
- `POST /api/classify` — classify an event payload
- `GET /api/ollama` — availability info
- `POST /api/summarize` — optional summary
- WebSocket ingest: `/ingest`
- WebSocket UI: `/ws`

## Dev UX
Use `.env.example` to configure settings.

### Makefile targets
```bash
make backend-dev
make backend-test
make collector-build
```

## Notes
- The collector emits **foreground**, **idle**, and **active** events.
- UIA snapshots are optional and throttled; they capture only focused element name/control type and short text excerpt.
- The backend keeps a **memory cache** for fast UI updates and persists to SQLite.
- No keystrokes, screenshots, or cloud calls in the core path.
