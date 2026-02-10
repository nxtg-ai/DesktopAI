import asyncio
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")
os.environ.setdefault("CLASSIFIER_USE_OLLAMA", "0")
os.environ.setdefault("CLASSIFIER_DEFAULT", "docs")
os.environ.setdefault("UI_TELEMETRY_ARTIFACT_DIR", "/tmp/desktopai-ui-telemetry-test")

from app.auth import _rate_limiter
from app.main import autonomy, db, ollama, planner, runtime_logs, settings, store, tasks


def _run(coro):
    try:
        asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()


@pytest.fixture(autouse=True)
def reset_runtime_state():
    _run(store.reset())
    _run(db.clear())
    _run(tasks.reset())
    _run(autonomy.reset())
    ollama.reset_active_model()
    planner.set_mode(settings.autonomy_planner_mode)
    runtime_logs.clear()
    _rate_limiter._hits.clear()
    shutil.rmtree("/tmp/desktopai-ui-telemetry-test", ignore_errors=True)
