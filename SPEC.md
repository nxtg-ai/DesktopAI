# DesktopAI Perception Agent – SPEC (Local‑First, Windows + WSL2)

## Scope
Build a lightweight, event‑driven desktop perception stack that runs locally, is offline‑capable, and provides real‑time context to a local UI. The MVP focuses on Windows foreground window changes and a WSL2 backend that maintains state and broadcasts updates to a browser UI.

## Goals (MVP)
- **Local‑first / offline:** No cloud dependency for core functionality.
- **Low latency:** Capture foreground window changes and deliver to UI within ~100ms on typical hardware.
- **Cross‑boundary:** Windows collector (native) → WSL2 backend (FastAPI) → local web UI.
- **Simple, real:** Minimal but production‑shaped implementation with logs, tests, and docs.

## Non‑Goals (MVP)
- Full UI Automation tree scraping
- Global input hooks (keyboard/mouse)
- LLM escalation to cloud APIs
- Long‑term storage or search
- Privilege escalation / admin‑only windows

## Functional Requirements
1. **Windows collector**
   - Detect foreground window changes via WinEventHook.
   - For each change, capture:
     - `hwnd` (window handle)
     - `title` (window title text)
     - `process_exe` (full path)
     - `pid`
     - `timestamp` (RFC3339 UTC)
   - Send JSON events to backend over WebSocket (preferred) or HTTP.

2. **Backend (WSL2, FastAPI)**
   - Receive events via HTTP POST and WebSocket ingest.
   - Maintain current active window state + in‑memory event log.
   - Provide REST endpoints for state/events + WebSocket for live updates.
   - Serve a minimal single‑page UI.

3. **Web UI**
   - Show current active window state.
   - Show recent events (rolling list).
   - Live updates via WebSocket.

4. **Optional Local LLM (Ollama)**
   - Detect local Ollama and expose `/api/summarize` for a short context summary.
   - If unavailable, the endpoint returns a clear error (no hard dependency).

5. **Dev UX**
   - Makefile and/or scripts for build/run/test.
   - `.env.example` for config.
   - Logging and basic tests.

## Architecture Summary
- **Collector (Windows, Rust):** Uses `SetWinEventHook` for `EVENT_SYSTEM_FOREGROUND` and Win32 APIs for process metadata.
- **Backend (WSL2, Python):** FastAPI app with in‑memory state, WebSocket broadcast, static UI.
- **UI (Browser):** Single static HTML/JS/CSS served by backend.

## Data Model (MVP)
Event payload:
```json
{
  "type": "foreground",
  "hwnd": "0x00012345",
  "title": "README.md - Visual Studio Code",
  "process_exe": "C:\\Program Files\\Microsoft VS Code\\Code.exe",
  "pid": 12345,
  "timestamp": "2026-01-31T19:22:10.123Z",
  "source": "collector"
}
```

## Performance Targets (MVP)
- **Event delivery:** < 100ms from OS event to backend state update (typical).
- **CPU:** ~0% idle, low single‑digit % under typical switching.
- **Memory:** Backend < 150MB, Collector < 50MB RSS (baseline).

## Security & Privacy (MVP)
- Local‑only services (bind to localhost by default).
- No keystroke capture or screenshotting.
- Event log in memory only (no persistent storage).
- Configurable log levels; avoid logging raw event contents at INFO by default.

## Future Extensions
- UI Automation for richer context
- Input/idle detection
- On‑device SLM classification
- Persistent event store + search
- MCP‑compatible tool API
