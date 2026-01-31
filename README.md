# DesktopAI MVP

Local‑first desktop context pipeline:
- **Windows collector (Rust):** foreground window changes
- **WSL2 backend (FastAPI):** state + event log + Web UI
- **Web UI:** live state and recent events

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
./desktopai-collector.exe
```

> Note: Windows → WSL2 `localhost` forwarding is typically enabled. If it isn't, set `BACKEND_WS_URL` and `BACKEND_HTTP_URL` to the WSL2 VM IP (from `wsl hostname -I`).

## Ollama (optional)
If Ollama is running locally, the backend will expose `/api/summarize`.
- Default URL: `http://localhost:11434`
- Configure via `OLLAMA_URL` and `OLLAMA_MODEL`.

If Ollama is not available, the summary endpoint returns 503 and the UI disables the button.

## API (MVP)
- `POST /api/events` — ingest event (HTTP)
- `GET /api/state` — current state
- `GET /api/events?limit=N` — recent events
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
- The MVP only captures **foreground window changes**.
- The event log is **in memory** only.
- No keystrokes, screenshots, or cloud calls in the core path.
