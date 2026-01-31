# Architecture

## Components
1. **Windows Collector (Rust)**
   - Subscribes to `EVENT_SYSTEM_FOREGROUND` via `SetWinEventHook`.
   - On each foreground change, queries:
     - Window title (`GetWindowTextW`)
     - PID (`GetWindowThreadProcessId`)
     - Process path (`OpenProcess` + `QueryFullProcessImageNameW`)
   - Emits JSON events over WebSocket to backend; falls back to HTTP POST.

2. **Backend API (FastAPI on WSL2)**
   - Receives events over `/ingest` (WebSocket) or `/api/events` (HTTP).
   - Stores **current state** and **event log** (in‑memory ring buffer).
   - Broadcasts updates over `/ws` to UI and other local clients.
   - Serves static SPA at `/`.
   - Optional Ollama integration for summaries.

3. **Web UI (Static)**
   - Renders current active window info.
   - Displays recent events.
   - Live updates via WebSocket.

## Interfaces
### Collector → Backend
- **WebSocket (preferred):** `ws://<host>:<port>/ingest`
  - Message: JSON event (single object per message)
- **HTTP fallback:** `POST http://<host>:<port>/api/events`
  - Body: JSON event

### Backend → UI
- **WebSocket:** `ws://<host>:<port>/ws`
  - Messages:
    - `{"type":"snapshot","state":...,"events":[...]}`
    - `{"type":"event","event":...}`
    - `{"type":"state","state":...}`
- **REST:**
  - `GET /api/state`
  - `GET /api/events?limit=N`

### Optional Summarization
- **REST:** `POST /api/summarize`
  - Uses local Ollama if available.

## Data Model
### WindowEvent
| Field | Type | Notes |
|---|---|---|
| type | string | `"foreground"` for MVP |
| hwnd | string | Hex string of HWND |
| title | string | Window title (may be empty) |
| process_exe | string | Full path to exe (best effort) |
| pid | int | Process ID |
| timestamp | string | RFC3339 UTC |
| source | string | e.g. `"collector"` |

### State
- `current`: latest `WindowEvent` or null
- `event_count`: total in ring buffer

## Sequence (Foreground Change)
1. Windows raises foreground event.
2. Collector callback queries title and process metadata.
3. Collector sends JSON event to backend over WS (fallback HTTP).
4. Backend updates in‑memory state and event log.
5. Backend broadcasts to UI WebSocket clients.
6. UI updates live view.

## Threat Model (MVP)
### Assets
- Window title / process path / PID (sensitive metadata)
- Local state and event log

### Adversaries
- Local untrusted processes on same machine
- Malicious local web pages attempting cross‑origin access

### Threats & Mitigations
- **Unauthorized access to API:**
  - Bind to `localhost` by default; no external exposure.
  - Keep API minimal; no destructive operations.
- **Data leakage via logs:**
  - Avoid logging full event payloads at INFO.
  - Provide debug level for deep inspection.
- **Cross‑origin abuse:**
  - Serve UI from same origin; optional CORS allow‑list.
- **Process inspection limits:**
  - Collector runs as normal user; cannot introspect elevated windows.
  - Document limitation; no privilege escalation in MVP.

## Reliability & Performance
- Event‑driven collection (no polling loop).
- In‑memory ring buffer to avoid disk IO.
- Backpressure via WS reconnect/fallback.

## Deployment Topology (MVP)
- **WSL2:** `uvicorn` serves backend and UI on `localhost:8000`.
- **Windows:** Collector runs natively, sends to `ws://localhost:8000/ingest`.
- WSL2 localhost forwarding allows Windows to reach backend.

