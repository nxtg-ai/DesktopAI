from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict

from .config import settings


def run_selftest() -> Dict[str, Any]:
    """Cheap, local-only health/self-test.

    Goal: quickly answer "is the backend + persistence basically working?".
    This does NOT test the Windows collector.
    """

    checks: Dict[str, Any] = {}

    # DB path writable
    db_path = settings.db_path
    try:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        probe = os.path.join(os.path.dirname(db_path), ".selftest-write")
        with open(probe, "w", encoding="utf-8") as f:
            f.write(datetime.now(timezone.utc).isoformat())
        os.remove(probe)
        checks["db_path_writable"] = {"ok": True, "path": db_path}
    except Exception as e:
        checks["db_path_writable"] = {"ok": False, "path": db_path, "error": str(e)}

    # Ollama reachability is tested via /api/ollama already; just surface config
    checks["ollama_config"] = {
        "ok": True,
        "url": settings.ollama_url,
        "model": settings.ollama_model,
    }

    ok = all(v.get("ok") for v in checks.values())

    return {
        "ok": ok,
        "ts": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "notes": [
            "This validates backend config + local filesystem writability.",
            "Collector connectivity must be tested separately (Windows).",
        ],
    }
