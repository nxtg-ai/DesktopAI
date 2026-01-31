# Plan

## Phase 1 — MVP Foundations
**Milestone:** Core pipeline working end‑to‑end (Windows → WSL2 → UI)

Acceptance Criteria:
- Windows collector emits JSON on foreground window changes.
- Backend receives events via WS or HTTP and updates state.
- UI shows live state and recent events.
- Basic logging and smoke tests pass.

## Phase 2 — Dev UX + Resilience
**Milestone:** Developer‑friendly workflow and stability improvements

Acceptance Criteria:
- Makefile/scripts for build/run/test.
- `.env.example` and README with WSL2 + Windows build steps.
- WS reconnect + HTTP fallback verified.
- Basic unit tests for state storage and API endpoints.

## Phase 3 — Local Summary (Optional)
**Milestone:** Local summarization endpoint (Ollama)

Acceptance Criteria:
- `/api/summarize` returns a short summary when Ollama is available.
- Endpoint returns a clear, non‑fatal error when Ollama is missing.
- UI can show availability state (optional in MVP).

## Future (Post‑MVP)
- UI Automation for deeper context (controls/text).
- Input/idle detection and richer activity modeling.
- Persistent storage + search.
- MCP protocol integration.
- Configurable privacy filters (blacklist apps/paths).
