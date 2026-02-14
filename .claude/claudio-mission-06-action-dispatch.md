# Claudio Mission 06B: Multi-Monitor Fix + Vision Research

**Updated:** 2026-02-13
**Priority:** Multi-monitor fix is ship-blocking; research is Sprint 7 prep

---

## DONE: Direct Bridge Fast Path (completed this session)

Implemented in `backend/app/routes/agent.py` — 6 regex patterns, `_try_direct_command()`, two-tier system prompt. 6 new tests in `test_chat.py`. All 504 tests pass, lint clean.

---

## TASK 1: Multi-Monitor Screenshot Fix

### Problem
`screenshot.rs` captures the entire virtual desktop via `GetDC(HWND(0))`. With multiple monitors, the downscaled image is squished and confusing for the VLM.

### Fix
Capture only the monitor containing the foreground window:
1. Use `MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)` to get the correct monitor
2. Use `GetMonitorInfoW()` to get that monitor's rect
3. `BitBlt` only that monitor's area instead of the full virtual desktop

### File
`collector/src/screenshot.rs` — the `capture_screenshot()` function (around lines 51-63)

### Testing
- `cargo test` must stay green (72 tests, Linux-testable with `#[cfg(windows)]` gates)
- `cargo clippy --all-targets -- -D warnings` must pass
- Manual verification: connect collector on multi-monitor Windows, check that screenshot only shows one monitor

### Constraints
- Rust only — this is collector code
- Compile target: `x86_64-pc-windows-gnu`
- Keep the existing JPEG/WebP format support and configurable quality
- The `hwnd` of the foreground window is available from the event that triggers the screenshot

---

## TASK 2: Vision Stack Research (no code changes)

Research next-gen perception options to replace the current slow VLM-only approach (30-60s per VisionAgent iteration).

### What to evaluate

**Fara-7B (Microsoft)**
- 7B CUA model designed for computer use agents
- Natively predicts pixel coordinates + action sequences
- Built-in "Critical Points" safety mechanism
- Key question: Does it run in Ollama? What quantizations are available?

**YOLO + Text LLM (split perception from reasoning)**
- YOLO v8/v26 detects UI elements in <100ms (bounding boxes + labels)
- Feed structured element list to fast text LLM (2-3s decision)
- Key question: Is there a YOLO model fine-tuned for Windows UI elements?

**OmniParser (Microsoft)**
- Purpose-built screen parser for UI element extraction
- Used by Microsoft's UFO framework
- Key question: How does it compare to YOLO for speed and accuracy on Windows?

### What we already have (don't reinvent)
- UIA integration (collector captures full UIA tree)
- Trajectory memory (trajectory_store with error lessons)
- Safety gates (approval tokens, kill switch, confidence gating)
- Self-correction (retry on failure)

### Deliverable
Write findings to `.asif/vision-stack-research.md` with:
- Comparison table: speed, accuracy, Ollama compatibility, model size
- Recommended architecture (YOLO+LLM vs Fara-7B vs OmniParser+LLM)
- Migration path from current qwen2.5vl:7b approach
- Any prototype code or config needed to test the winner

---

## Notes
- Do NOT modify any Python backend code — that's the other session's territory
- The collector binary deploys to `C:\temp\desktopai\desktopai-collector.exe`
- Default vision model is `qwen2.5vl:7b` (set in `backend/app/config.py`)
