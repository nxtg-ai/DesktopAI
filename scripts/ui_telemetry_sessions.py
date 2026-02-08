#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from urllib import error, parse, request


def main() -> int:
    parser = argparse.ArgumentParser(description="List DesktopAI UI telemetry sessions from backend API")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Backend base URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum sessions to fetch (default: 10)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON payload",
    )
    args = parser.parse_args()

    query = parse.urlencode({"limit": max(1, args.limit)})
    url = f"{args.base_url.rstrip('/')}/api/ui-telemetry/sessions?{query}"
    try:
        with request.urlopen(url, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except error.URLError as exc:
        print(f"request failed: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"invalid json: {exc}", file=sys.stderr)
        return 3

    sessions = payload.get("sessions") or []
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    if not sessions:
        print("No telemetry sessions.")
        return 0

    print(f"Telemetry sessions ({len(sessions)}):")
    for item in sessions:
        session_id = item.get("session_id", "")
        count = item.get("event_count", 0)
        first_ts = item.get("first_timestamp", "")
        last_ts = item.get("last_timestamp", "")
        artifact = item.get("artifact_file", "")
        print(f"- {session_id} | events={count} | first={first_ts} | last={last_ts}")
        print(f"  artifact: {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
