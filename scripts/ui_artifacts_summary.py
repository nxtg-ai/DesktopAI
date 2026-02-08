#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Iterable


def _latest(paths: Iterable[Path]) -> Path | None:
    items = list(paths)
    if not items:
        return None
    return max(items, key=lambda p: p.stat().st_mtime)


def _load_events(path: Path) -> list[dict]:
    events: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _load_required_kinds(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict):
        values = payload.get("required_kinds", [])
    else:
        raise ValueError("required kinds file must be a JSON list or object")

    if not isinstance(values, list):
        raise ValueError("required_kinds must be a list")

    required = []
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("required kinds must be non-empty strings")
        required.append(item.strip())
    return required


def _latest_sessions(paths: Iterable[Path], limit: int) -> list[Path]:
    items = sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)
    if limit <= 0:
        return []
    return items[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize latest DesktopAI UI artifacts")
    parser.add_argument(
        "--artifacts-root",
        default="artifacts/ui",
        help="Root directory for UI artifacts (default: artifacts/ui)",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=8,
        help="How many last telemetry events to print (default: 8)",
    )
    parser.add_argument(
        "--session-id",
        default="",
        help="Specific telemetry session id to inspect (defaults to latest)",
    )
    parser.add_argument(
        "--session-id-file",
        default="",
        help="Text file containing telemetry session id to inspect (single line).",
    )
    parser.add_argument(
        "--require-kind",
        action="append",
        default=[],
        help="Telemetry kind that must exist in the session (repeatable)",
    )
    parser.add_argument(
        "--required-kinds-file",
        default="",
        help="JSON file containing required telemetry kinds (array or {required_kinds:[...]}).",
    )
    parser.add_argument(
        "--scan-latest-sessions",
        type=int,
        default=1,
        help="Scan up to N most-recent sessions to find one that satisfies required kinds (default: 1).",
    )
    args = parser.parse_args()

    root = Path(args.artifacts_root)
    telemetry_dir = root / "telemetry"
    playwright_root = root / "playwright"
    report_index = playwright_root / "report" / "index.html"

    print(f"Artifacts root: {root}")
    print(f"Playwright report: {report_index if report_index.exists() else 'missing'}")

    latest_trace = _latest((playwright_root / "test-results").glob("**/trace.zip")) or _latest(
        (playwright_root / "report" / "data").glob("*.zip")
    )
    latest_video = _latest((playwright_root / "test-results").glob("**/video.webm")) or _latest(
        (playwright_root / "report" / "data").glob("*.webm")
    )
    latest_shot = _latest((playwright_root / "test-results").glob("**/*.png")) or _latest(
        (playwright_root / "report" / "data").glob("*.png")
    )

    print(f"Latest trace: {latest_trace if latest_trace else 'none'}")
    print(f"Latest video: {latest_video if latest_video else 'none'}")
    print(f"Latest screenshot: {latest_shot if latest_shot else 'none'}")

    required_kinds = list(args.require_kind)
    if args.required_kinds_file:
        try:
            file_required = _load_required_kinds(Path(args.required_kinds_file))
        except FileNotFoundError:
            print(f"required kinds file not found: {args.required_kinds_file}")
            return 4
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"invalid required kinds file: {exc}")
            return 5
        for kind in file_required:
            if kind not in required_kinds:
                required_kinds.append(kind)

    requested_session_id = args.session_id.strip()
    if not requested_session_id and args.session_id_file:
        file_path = Path(args.session_id_file)
        if not file_path.exists():
            print(f"session id file not found: {args.session_id_file}")
            return 6
        requested_session_id = file_path.read_text(encoding="utf-8").strip()
        if not requested_session_id:
            print(f"session id file is empty: {args.session_id_file}")
            return 7

    latest_session = None
    session_candidates: list[Path] = []
    if telemetry_dir.exists():
        if requested_session_id:
            candidate = telemetry_dir / f"{requested_session_id}.jsonl"
            if candidate.exists():
                session_candidates = [candidate]
        else:
            scan_limit = max(1, args.scan_latest_sessions)
            session_candidates = _latest_sessions(telemetry_dir.glob("*.jsonl"), scan_limit)

    if not session_candidates:
        print("Latest telemetry session: none")
        return 0

    selected_path = session_candidates[0]
    selected_events = _load_events(selected_path)
    selected_kinds = Counter((ev.get("kind") or "unknown") for ev in selected_events)
    missing = [kind for kind in required_kinds if selected_kinds.get(kind, 0) == 0]

    # If required kinds are configured, find the first recent session that satisfies all constraints.
    if required_kinds and len(session_candidates) > 1:
        for path in session_candidates:
            events = _load_events(path)
            kinds = Counter((ev.get("kind") or "unknown") for ev in events)
            missing_here = [kind for kind in required_kinds if kinds.get(kind, 0) == 0]
            if not missing_here:
                selected_path = path
                selected_events = events
                selected_kinds = kinds
                missing = []
                break

    print(f"Selected telemetry session for gate: {selected_path}")
    print(f"Latest telemetry session: {selected_path}")
    print(f"Telemetry events: {len(selected_events)}")
    if not selected_events:
        return 0

    print("Telemetry kinds:")
    for kind, count in selected_kinds.most_common():
        print(f"- {kind}: {count}")

    tail = max(1, args.tail)
    print(f"Last {tail} events:")
    for event in selected_events[-tail:]:
        ts = event.get("timestamp") or "?"
        kind = event.get("kind") or "unknown"
        message = event.get("message") or ""
        print(f"- {ts} | {kind} | {message}")

    if missing:
        print("Missing required telemetry kinds:")
        for kind in sorted(set(missing)):
            print(f"- {kind}")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
