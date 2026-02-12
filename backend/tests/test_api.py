import asyncio
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")
os.environ.setdefault("CLASSIFIER_USE_OLLAMA", "0")
os.environ.setdefault("CLASSIFIER_DEFAULT", "docs")
os.environ.setdefault("UI_TELEMETRY_ARTIFACT_DIR", "/tmp/desktopai-ui-telemetry-test")

from app.main import (
    _restore_runtime_ollama_model,
    _restore_runtime_planner_mode,
    app,
    autonomy,
    db,
    logger,
    ollama,
    planner,
    runtime_logs,
    settings,
    store,
    tasks,
)

client = TestClient(app)


def _reset_runtime():
    asyncio.run(store.reset())
    asyncio.run(db.clear())
    asyncio.run(tasks.reset())
    asyncio.run(autonomy.reset())
    ollama.reset_active_model()
    planner.set_mode(settings.autonomy_planner_mode)
    runtime_logs.clear()
    shutil.rmtree("/tmp/desktopai-ui-telemetry-test", ignore_errors=True)


def _wait_for_run_status(run_id: str, expected: set[str], timeout_s: float = 1.5):
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        resp = client.get(f"/api/autonomy/runs/{run_id}")
        assert resp.status_code == 200
        run = resp.json()["run"]
        last = run["status"]
        if last in expected:
            return run
        time.sleep(0.03)
    raise AssertionError(f"run {run_id} did not reach {expected}, last status={last}")


def test_post_event_updates_state():
    _reset_runtime()
    payload = {
        "type": "foreground",
        "hwnd": "0xABC",
        "title": "Test App",
        "process_exe": "C:\\Program Files\\Test\\Test.exe",
        "pid": 4242,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "test",
    }
    resp = client.post("/api/events", json=payload)
    assert resp.status_code == 200

    state = client.get("/api/state").json()
    assert state["current"]["title"] == "Test App"
    assert state["idle"] is False
    assert state["current"]["category"] == "docs"

    events = client.get("/api/events?limit=1").json()
    assert len(events["events"]) == 1


def test_selftest_endpoint_reports_sqlite_probe():
    _reset_runtime()
    resp = client.get("/api/selftest")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["checks"]["db_path_writable"]["ok"] is True
    assert payload["checks"]["sqlite_probe"]["ok"] is True
    assert "SQLite probe" in " ".join(payload.get("notes", []))


def test_executor_status_endpoint():
    _reset_runtime()
    resp = client.get("/api/executor")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("mode")
    assert "available" in payload


def test_executor_preflight_endpoint():
    _reset_runtime()
    resp = client.get("/api/executor/preflight")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("mode")
    assert isinstance(payload.get("ok"), bool)
    assert isinstance(payload.get("checks"), list)
    assert payload["checks"]


def test_readiness_status_endpoint_returns_summary():
    _reset_runtime()
    resp = client.get("/api/readiness/status")
    assert resp.status_code == 200
    payload = resp.json()
    assert isinstance(payload.get("ok"), bool)
    assert isinstance(payload.get("checks"), list)
    assert payload["checks"]
    assert isinstance(payload.get("summary"), dict)
    assert "executor_mode" in payload["summary"]
    assert payload["summary"]["autonomy_planner_mode"] in {
        "deterministic",
        "auto",
        "ollama_required",
    }
    assert payload["summary"]["autonomy_planner_source"] in {"config_default", "runtime_override"}
    assert "collector_connected" in payload["summary"]
    assert "required_total" in payload["summary"]
    assert "required_failed" in payload["summary"]
    assert "warning_count" in payload["summary"]
    assert "ollama_available" in payload["summary"]
    check_names = {item["name"] for item in payload["checks"]}
    assert "ollama_available" in check_names


def test_readiness_status_reports_required_failures(monkeypatch):
    _reset_runtime()

    async def _preflight_failed():
        return {
            "mode": "windows-powershell",
            "ok": False,
            "checks": [
                {
                    "name": "windows_host",
                    "ok": False,
                    "detail": "Non-Windows host detected.",
                }
            ],
            "message": "Windows preflight failed: non-Windows host.",
        }

    monkeypatch.setattr(tasks, "executor_preflight", _preflight_failed)
    resp = client.get("/api/readiness/status")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["summary"]["required_failed"] >= 1


def test_readiness_status_ollama_unavailable_is_warning(monkeypatch):
    _reset_runtime()

    async def _ollama_unavailable():
        return False

    diagnostics = {
        "available": False,
        "last_check_at": "2026-01-01T00:00:00+00:00",
        "last_check_source": "tags",
        "last_http_status": 503,
        "last_error": "GET /api/tags returned status 503",
        "ttl_seconds": 30,
    }

    monkeypatch.setattr("app.main.ollama.available", _ollama_unavailable)
    monkeypatch.setattr("app.main.ollama.diagnostics", lambda: diagnostics)
    resp = client.get("/api/readiness/status")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["summary"]["ollama_available"] is False
    assert payload["summary"]["ollama_last_error"] == diagnostics["last_error"]
    assert payload["summary"]["ollama_last_http_status"] == diagnostics["last_http_status"]
    assert payload["summary"]["ollama_last_check_source"] == diagnostics["last_check_source"]
    assert payload["summary"]["ollama_last_check_at"] == diagnostics["last_check_at"]
    check = next(item for item in payload["checks"] if item["name"] == "ollama_available")
    assert check["required"] is False
    assert check["ok"] is False
    assert "503" in check["detail"]
    assert payload["summary"]["warning_count"] >= 1


def test_readiness_status_ollama_unavailable_can_be_required(monkeypatch):
    _reset_runtime()
    original_mode = planner.mode

    async def _ollama_unavailable():
        return False

    monkeypatch.setattr("app.main.ollama.available", _ollama_unavailable)
    try:
        planner.set_mode("ollama_required")
        resp = client.get("/api/readiness/status")
        assert resp.status_code == 200
        payload = resp.json()
        check = next(item for item in payload["checks"] if item["name"] == "ollama_available")
        assert check["required"] is True
        assert check["ok"] is False
        assert payload["ok"] is False
        assert payload["summary"]["required_failed"] >= 1
    finally:
        planner.set_mode(original_mode)


def test_ollama_status_includes_planner_flag():
    _reset_runtime()
    resp = client.get("/api/ollama")
    assert resp.status_code == 200
    payload = resp.json()
    assert "available" in payload
    assert "url" in payload
    assert "model" in payload
    assert payload.get("autonomy_planner_mode") in {"deterministic", "auto", "ollama_required"}
    assert payload.get("autonomy_planner_source") in {"config_default", "runtime_override"}
    assert isinstance(payload.get("autonomy_planner_use_ollama"), bool)
    assert "last_check_at" in payload
    assert "last_check_source" in payload
    assert "last_http_status" in payload
    assert "last_error" in payload
    assert isinstance(payload.get("ttl_seconds"), int)
    assert "configured_model" in payload
    assert "active_model" in payload
    assert payload["model"] == payload["active_model"]
    assert payload.get("ollama_model_source") in {"config_default", "runtime_override"}


def test_ollama_models_endpoint_returns_model_list(monkeypatch):
    _reset_runtime()

    async def _models():
        return ["mistral:latest", "mistral:instruct"]

    monkeypatch.setattr("app.main.ollama.list_models", _models, raising=False)
    resp = client.get("/api/ollama/models")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["models"] == ["mistral:latest", "mistral:instruct"]
    assert payload["configured_model"]
    assert payload["active_model"]
    assert payload["source"] in {"config_default", "runtime_override"}


def test_ollama_model_override_roundtrip():
    _reset_runtime()
    override = "mistral:latest"

    async def _models():
        return ["mistral:latest", "mistral:instruct"]

    from app import main as app_main
    original_list_models = getattr(app_main.ollama, "list_models", None)
    setattr(app_main.ollama, "list_models", _models)

    try:
        set_resp = client.post("/api/ollama/model", json={"model": override})
        assert set_resp.status_code == 200
        payload = set_resp.json()
        assert payload["active_model"] == override
        assert payload["model"] == override
        assert payload["ollama_model_source"] == "runtime_override"

        persisted = asyncio.run(db.get_runtime_setting("ollama_model"))
        assert persisted == override

        cleared = client.delete("/api/ollama/model")
        assert cleared.status_code == 200
        cleared_payload = cleared.json()
        assert cleared_payload["active_model"] == settings.ollama_model
        assert cleared_payload["ollama_model_source"] == "config_default"
        persisted_after = asyncio.run(db.get_runtime_setting("ollama_model"))
        assert persisted_after is None
    finally:
        if original_list_models is not None:
            setattr(app_main.ollama, "list_models", original_list_models)


def test_ollama_model_override_rejects_uninstalled_model(monkeypatch):
    _reset_runtime()

    async def _models():
        return ["mistral:latest"]

    monkeypatch.setattr("app.main.ollama.list_models", _models, raising=False)
    resp = client.post("/api/ollama/model", json={"model": "not-installed:latest"})
    assert resp.status_code == 404
    assert "not installed" in resp.json().get("detail", "").lower()


def test_ollama_model_override_can_be_restored_from_runtime_setting():
    _reset_runtime()
    override = "mistral:latest"
    original_model = ollama.model

    from app import main as app_main

    async def _models():
        return ["mistral:latest", "mistral:instruct"]

    original_list_models = getattr(app_main.ollama, "list_models", None)
    setattr(app_main.ollama, "list_models", _models)
    try:
        set_resp = client.post("/api/ollama/model", json={"model": override})
        assert set_resp.status_code == 200
        ollama.reset_active_model()
        assert ollama.model == settings.ollama_model

        asyncio.run(_restore_runtime_ollama_model())
        assert ollama.model == override
    finally:
        ollama.set_active_model(original_model)
        if original_list_models is not None:
            setattr(app_main.ollama, "list_models", original_list_models)


def test_ollama_probe_endpoint_returns_probe_payload(monkeypatch):
    _reset_runtime()

    async def _probe(*, prompt: str, timeout_s: float, allow_fallback: bool):
        assert "OK" in prompt
        assert timeout_s == 5.0
        assert allow_fallback is False
        return {
            "ok": True,
            "model": "mistral:latest",
            "elapsed_ms": 12,
            "error": None,
            "response_preview": "OK",
            "response_chars": 2,
            "used_fallback": False,
        }

    monkeypatch.setattr("app.main.ollama.probe", _probe, raising=False)
    resp = client.post(
        "/api/ollama/probe",
        json={"prompt": "Respond with exactly: OK", "timeout_s": 5.0, "allow_fallback": False},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["probe"]["ok"] is True
    assert payload["probe"]["model"] == "mistral:latest"
    assert payload["probe"]["response_preview"] == "OK"
    assert payload["probe"]["used_fallback"] is False
    assert payload["active_model"]
    assert payload["configured_model"]


def test_ollama_probe_endpoint_reports_failure(monkeypatch):
    _reset_runtime()

    async def _probe(*, prompt: str, timeout_s: float, allow_fallback: bool):
        return {
            "ok": False,
            "model": "missing:model",
            "elapsed_ms": 25,
            "error": "POST /api/generate returned status 404",
            "response_preview": "",
            "response_chars": 0,
            "used_fallback": False,
        }

    monkeypatch.setattr("app.main.ollama.probe", _probe, raising=False)
    resp = client.post("/api/ollama/probe", json={"prompt": "ping"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["probe"]["ok"] is False
    assert "404" in (payload["probe"]["error"] or "")
    assert payload["probe"]["used_fallback"] is False


def test_autonomy_planner_status_endpoint_reports_mode_and_supported_values():
    _reset_runtime()
    resp = client.get("/api/autonomy/planner")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["mode"] in {"deterministic", "auto", "ollama_required"}
    assert set(payload["supported_modes"]) == {"deterministic", "auto", "ollama_required"}
    assert isinstance(payload.get("ollama_available"), bool)
    assert payload["source"] in {"config_default", "runtime_override"}
    assert payload["configured_default_mode"] in {"deterministic", "auto", "ollama_required"}


def test_autonomy_planner_mode_endpoint_updates_runtime_mode():
    _reset_runtime()
    original_mode = planner.mode
    try:
        set_auto = client.post("/api/autonomy/planner", json={"mode": "auto"})
        assert set_auto.status_code == 200
        assert set_auto.json()["mode"] == "auto"
        assert set_auto.json()["source"] == "runtime_override"
        persisted = asyncio.run(db.get_runtime_setting("autonomy_planner_mode"))
        assert persisted == "auto"

        readiness = client.get("/api/readiness/status")
        assert readiness.status_code == 200
        assert readiness.json()["summary"]["autonomy_planner_mode"] == "auto"

        set_deterministic = client.post("/api/autonomy/planner", json={"mode": "deterministic"})
        assert set_deterministic.status_code == 200
        assert set_deterministic.json()["mode"] == "deterministic"
    finally:
        planner.set_mode(original_mode)


def test_autonomy_planner_mode_endpoint_rejects_invalid_mode():
    _reset_runtime()
    resp = client.post("/api/autonomy/planner", json={"mode": "invalid-mode"})
    assert resp.status_code == 422


def test_autonomy_planner_mode_delete_clears_runtime_override():
    _reset_runtime()
    client.post("/api/autonomy/planner", json={"mode": "auto"})
    persisted = asyncio.run(db.get_runtime_setting("autonomy_planner_mode"))
    assert persisted == "auto"

    cleared = client.delete("/api/autonomy/planner")
    assert cleared.status_code == 200
    payload = cleared.json()
    assert payload["mode"] == settings.autonomy_planner_mode
    assert payload["source"] == "config_default"

    persisted_after = asyncio.run(db.get_runtime_setting("autonomy_planner_mode"))
    assert persisted_after is None


def test_autonomy_planner_mode_can_be_restored_from_runtime_setting():
    _reset_runtime()
    original_mode = planner.mode
    try:
        set_required = client.post("/api/autonomy/planner", json={"mode": "ollama_required"})
        assert set_required.status_code == 200
        planner.set_mode("deterministic")
        assert planner.mode == "deterministic"

        asyncio.run(_restore_runtime_planner_mode())
        assert planner.mode == "ollama_required"
    finally:
        planner.set_mode(original_mode)


def test_runtime_logs_endpoint_includes_recent_backend_message():
    _reset_runtime()
    token = f"runtime-log-{int(time.time() * 1000)}"
    logger.warning("runtime-log-probe %s", token)

    resp = client.get(f"/api/runtime-logs?limit=50&contains={token}")
    assert resp.status_code == 200
    payload = resp.json()
    logs = payload["logs"]
    assert logs
    assert any(token in item["message"] for item in logs)


def test_runtime_logs_endpoint_supports_level_filter_and_reset():
    _reset_runtime()
    warn_token = f"runtime-warn-{int(time.time() * 1000)}"
    error_token = f"runtime-error-{int(time.time() * 1000)}"
    logger.warning("runtime-log-probe %s", warn_token)
    logger.error("runtime-log-probe %s", error_token)

    warn_resp = client.get("/api/runtime-logs?limit=50&level=WARNING")
    assert warn_resp.status_code == 200
    warn_logs = warn_resp.json()["logs"]
    assert warn_logs
    assert all(item["level"] == "WARNING" for item in warn_logs)
    assert any(warn_token in item["message"] for item in warn_logs)
    assert all(error_token not in item["message"] for item in warn_logs)

    cleared = client.post("/api/runtime-logs/reset")
    assert cleared.status_code == 200
    assert cleared.json()["cleared"] >= 1

    after = client.get("/api/runtime-logs?limit=10")
    assert after.status_code == 200
    assert after.json()["logs"] == []


def test_runtime_logs_endpoint_rejects_invalid_time_filters():
    _reset_runtime()
    resp = client.get("/api/runtime-logs?since=not-a-time")
    assert resp.status_code == 400
    assert "invalid since timestamp" in resp.json()["detail"]


def test_runtime_logs_correlate_by_ui_telemetry_session():
    _reset_runtime()
    session_id = f"session-correlate-{int(time.time() * 1000)}"
    base = datetime.now(timezone.utc)
    posted = client.post(
        "/api/ui-telemetry",
        json={
            "events": [
                {
                    "session_id": session_id,
                    "kind": "ui_boot",
                    "message": "boot",
                    "timestamp": (base - timedelta(seconds=1)).isoformat(),
                },
                {
                    "session_id": session_id,
                    "kind": "ws_open",
                    "message": "open",
                    "timestamp": (base + timedelta(seconds=1)).isoformat(),
                },
            ]
        },
    )
    assert posted.status_code == 200

    token = f"runtime-correlation-{int(time.time() * 1000)}"
    logger.warning("runtime-log-probe %s", token)

    resp = client.get(f"/api/runtime-logs/correlate?session_id={session_id}&limit=100")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["session_id"] == session_id
    assert payload["event_count"] == 2
    assert payload["window"] is not None
    assert payload["logs"]
    assert any(token in item["message"] for item in payload["logs"])


def test_runtime_logs_correlate_empty_session_returns_no_window():
    _reset_runtime()
    session_id = f"session-empty-{int(time.time() * 1000)}"
    resp = client.get(f"/api/runtime-logs/correlate?session_id={session_id}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["session_id"] == session_id
    assert payload["event_count"] == 0
    assert payload["window"] is None
    assert payload["logs"] == []


def test_ws_snapshot_serializes_datetimes():
    _reset_runtime()
    payload = {
        "type": "foreground",
        "hwnd": "0xDEF",
        "title": "WS Test App",
        "process_exe": "C:\\Program Files\\Test\\WsTest.exe",
        "pid": 5252,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "test",
    }
    resp = client.post("/api/events", json=payload)
    assert resp.status_code == 200

    with client.websocket_connect("/ws") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert snapshot["state"]["current"]["title"] == "WS Test App"
        assert isinstance(snapshot["state"]["current"]["timestamp"], str)
        assert isinstance(snapshot["events"][0]["timestamp"], str)


def test_autonomy_run_completes_without_approval():
    _reset_runtime()
    resp = client.post(
        "/api/autonomy/runs",
        json={"objective": "Observe desktop and verify outcome", "max_iterations": 16},
    )
    assert resp.status_code == 200
    run = resp.json()["run"]
    assert run["status"] in {"running", "completed"}
    assert run["planner_mode"] in {"deterministic", "auto", "ollama_required"}

    run = _wait_for_run_status(run["run_id"], {"completed"})
    assert run["iteration"] >= 1
    assert run["finished_at"] is not None


def test_autonomy_run_returns_503_when_ollama_planner_required_unavailable(monkeypatch):
    _reset_runtime()

    async def _raise_required(_request):
        raise RuntimeError("ollama planner required but Ollama is unavailable")

    monkeypatch.setattr(autonomy, "start", _raise_required)
    resp = client.post(
        "/api/autonomy/runs",
        json={"objective": "Observe desktop and verify outcome", "max_iterations": 8},
    )
    assert resp.status_code == 503
    payload = resp.json()
    assert "ollama planner required" in payload.get("detail", "").lower()


def test_autonomy_run_waits_for_approval_then_completes():
    _reset_runtime()
    resp = client.post(
        "/api/autonomy/runs",
        json={
            "objective": "Open outlook, draft reply, then send email",
            "max_iterations": 24,
            "auto_approve_irreversible": False,
        },
    )
    assert resp.status_code == 200
    run = resp.json()["run"]

    run = _wait_for_run_status(run["run_id"], {"waiting_approval"})
    token = run["approval_token"]
    assert token

    approve = client.post(
        f"/api/autonomy/runs/{run['run_id']}/approve",
        json={"approval_token": token},
    )
    assert approve.status_code == 200

    done = _wait_for_run_status(run["run_id"], {"completed"})
    assert done["approval_token"] is None
    assert done["finished_at"] is not None


def test_autonomy_run_records_current_planner_mode():
    _reset_runtime()
    original_mode = planner.mode
    try:
        planner.set_mode("auto")
        resp = client.post(
            "/api/autonomy/runs",
            json={"objective": "Observe desktop and verify outcome", "max_iterations": 8},
        )
        assert resp.status_code == 200
        run = resp.json()["run"]
        assert run["planner_mode"] == "auto"
    finally:
        planner.set_mode(original_mode)


def test_autonomy_run_auto_approve_completes_irreversible_flow():
    _reset_runtime()
    resp = client.post(
        "/api/autonomy/runs",
        json={
            "objective": "Open outlook, draft reply, then send email",
            "max_iterations": 24,
            "auto_approve_irreversible": True,
        },
    )
    assert resp.status_code == 200
    run = resp.json()["run"]

    done = _wait_for_run_status(run["run_id"], {"completed"})
    assert done["status"] == "completed"
    assert done["approval_token"] is None
    assert done["last_error"] is None


def test_autonomy_run_cancel_while_waiting_approval():
    _reset_runtime()
    resp = client.post(
        "/api/autonomy/runs",
        json={"objective": "Submit payment and send confirmation", "max_iterations": 24},
    )
    assert resp.status_code == 200
    run = resp.json()["run"]
    run = _wait_for_run_status(run["run_id"], {"waiting_approval"})

    cancel = client.post(f"/api/autonomy/runs/{run['run_id']}/cancel")
    assert cancel.status_code == 200
    payload = cancel.json()["run"]
    assert payload["status"] == "cancelled"


def test_readiness_gate_auto_approve_completes():
    _reset_runtime()
    resp = client.post(
        "/api/readiness/gate",
        json={
            "objective": "Open outlook, draft reply, then send email",
            "timeout_s": 10,
            "auto_approve_irreversible": True,
            "require_preflight_ok": True,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["reason"] == "completed"
    assert payload["preflight"]["ok"] is True
    assert payload["run"]["status"] == "completed"
    assert payload["elapsed_ms"] >= 0
    assert payload["timeline"]


def test_readiness_gate_requires_manual_approval_when_disabled():
    _reset_runtime()
    resp = client.post(
        "/api/readiness/gate",
        json={
            "objective": "Open outlook, draft reply, then send email",
            "timeout_s": 10,
            "auto_approve_irreversible": False,
            "require_preflight_ok": True,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["reason"] == "approval_required"
    assert payload["preflight"]["ok"] is True
    assert payload["cleanup"]["attempted"] is True
    assert payload["cleanup"]["cancelled"] is True
    assert payload["run"]["status"] == "cancelled"


def test_readiness_gate_can_keep_waiting_run_when_cleanup_disabled():
    _reset_runtime()
    resp = client.post(
        "/api/readiness/gate",
        json={
            "objective": "Open outlook, draft reply, then send email",
            "timeout_s": 10,
            "auto_approve_irreversible": False,
            "require_preflight_ok": True,
            "cleanup_on_exit": False,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["reason"] == "approval_required"
    assert payload["cleanup"]["attempted"] is False
    assert payload["cleanup"]["cancelled"] is False
    assert payload["run"]["status"] == "waiting_approval"


def test_readiness_gate_returns_preflight_failed(monkeypatch):
    _reset_runtime()

    async def _preflight_failed():
        return {
            "mode": "windows-powershell",
            "ok": False,
            "checks": [
                {
                    "name": "windows_host",
                    "ok": False,
                    "detail": "Non-Windows host detected.",
                }
            ],
            "message": "Windows preflight failed: non-Windows host.",
        }

    monkeypatch.setattr(tasks, "executor_preflight", _preflight_failed)
    resp = client.post(
        "/api/readiness/gate",
        json={
            "objective": "Open outlook, draft reply, then send email",
            "timeout_s": 10,
            "auto_approve_irreversible": True,
            "require_preflight_ok": True,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["reason"] == "preflight_failed"
    assert payload["run"] is None
    assert payload["preflight"]["ok"] is False


def test_readiness_matrix_runs_multiple_cases():
    _reset_runtime()
    resp = client.post(
        "/api/readiness/matrix",
        json={
            "objectives": [
                "Observe desktop and verify outcome",
                "Open outlook, draft reply, then send email",
            ],
            "timeout_s": 10,
            "auto_approve_irreversible": True,
            "require_preflight_ok": True,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 2
    assert payload["passed"] == 2
    assert payload["failed"] == 0
    assert payload["ok"] is True
    assert len(payload["results"]) == 2
    assert all(item["report"]["ok"] is True for item in payload["results"])


def test_readiness_matrix_stop_on_failure():
    _reset_runtime()
    resp = client.post(
        "/api/readiness/matrix",
        json={
            "objectives": [
                "Open outlook, draft reply, then send email",
                "Observe desktop and verify outcome",
            ],
            "timeout_s": 10,
            "auto_approve_irreversible": False,
            "require_preflight_ok": True,
            "stop_on_failure": True,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["total"] == 1
    assert payload["passed"] == 0
    assert payload["failed"] == 1
    assert len(payload["results"]) == 1
    assert payload["results"][0]["report"]["reason"] == "approval_required"


def test_autonomy_run_broadcasts_ws_updates(monkeypatch):
    _reset_runtime()
    broadcasts = []

    async def _capture(payload):
        broadcasts.append(payload)

    monkeypatch.setattr("app.main.hub.broadcast_json", _capture)

    resp = client.post(
        "/api/autonomy/runs",
        json={"objective": "Observe desktop and verify outcome", "max_iterations": 8},
    )
    assert resp.status_code == 200
    run_id = resp.json()["run"]["run_id"]

    _wait_for_run_status(run_id, {"completed"})

    deadline = time.time() + 0.5
    while time.time() < deadline:
        autonomy_updates = [item for item in broadcasts if item.get("type") == "autonomy_run"]
        if any(item.get("run", {}).get("status") == "completed" for item in autonomy_updates):
            break
        time.sleep(0.02)
    autonomy_updates = [item for item in broadcasts if item.get("type") == "autonomy_run"]
    assert autonomy_updates
    assert any(item.get("run", {}).get("run_id") == run_id for item in autonomy_updates)
    assert any(item.get("run", {}).get("status") == "completed" for item in autonomy_updates)


def test_ws_snapshot_includes_latest_autonomy_run():
    _reset_runtime()
    resp = client.post(
        "/api/autonomy/runs",
        json={"objective": "Observe desktop and verify outcome", "max_iterations": 8},
    )
    assert resp.status_code == 200
    run_id = resp.json()["run"]["run_id"]
    _wait_for_run_status(run_id, {"completed"})

    with client.websocket_connect("/ws") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert snapshot["autonomy_run"] is not None
        assert snapshot["autonomy_run"]["run_id"] == run_id


def test_autonomy_runs_are_persisted_to_db():
    _reset_runtime()
    resp = client.post(
        "/api/autonomy/runs",
        json={"objective": "Observe desktop and verify outcome", "max_iterations": 8},
    )
    assert resp.status_code == 200
    run_id = resp.json()["run"]["run_id"]
    _wait_for_run_status(run_id, {"completed"})

    persisted = []
    deadline = time.time() + 1.0
    while time.time() < deadline:
        persisted = asyncio.run(db.list_autonomy_runs(limit=10))
        matched = next((item for item in persisted if item.run_id == run_id), None)
        if matched and matched.status == "completed":
            break
        time.sleep(0.03)
    assert persisted
    matched = next((item for item in persisted if item.run_id == run_id), None)
    assert matched is not None
    assert matched.status == "completed"


def test_hydrated_inflight_run_is_failed_after_restart():
    _reset_runtime()
    resp = client.post(
        "/api/autonomy/runs",
        json={
            "objective": "Open outlook, draft reply, then send email",
            "max_iterations": 12,
            "auto_approve_irreversible": False,
        },
    )
    assert resp.status_code == 200
    run_id = resp.json()["run"]["run_id"]
    _wait_for_run_status(run_id, {"waiting_approval"})

    persisted = asyncio.run(db.list_autonomy_runs(limit=10))
    assert persisted

    asyncio.run(autonomy.reset())
    asyncio.run(tasks.reset())
    asyncio.run(autonomy.hydrate_runs(persisted))

    restored = client.get(f"/api/autonomy/runs/{run_id}")
    assert restored.status_code == 200
    run = restored.json()["run"]
    assert run["status"] == "failed"
    assert "restored after restart" in (run["last_error"] or "")

    persisted_after = asyncio.run(db.list_autonomy_runs(limit=10))
    restored_after = next((item for item in persisted_after if item.run_id == run_id), None)
    assert restored_after is not None
    assert restored_after.status == "failed"


def test_task_records_are_persisted_and_hydrated():
    _reset_runtime()
    created = client.post("/api/tasks", json={"objective": "Draft and review plan"})
    assert created.status_code == 200
    task_id = created.json()["task"]["task_id"]

    planned = client.post(
        f"/api/tasks/{task_id}/plan",
        json={
            "steps": [
                {
                    "action": {
                        "action": "observe_desktop",
                        "description": "Capture context",
                    },
                    "preconditions": ["runtime connected"],
                    "postconditions": ["context captured"],
                }
            ]
        },
    )
    assert planned.status_code == 200
    assert planned.json()["task"]["status"] == "planned"

    persisted = []
    deadline = time.time() + 1.0
    while time.time() < deadline:
        persisted = asyncio.run(db.list_task_records(limit=10))
        if any(item.task_id == task_id for item in persisted):
            break
        time.sleep(0.03)
    assert persisted
    assert any(item.task_id == task_id for item in persisted)

    asyncio.run(tasks.reset())
    asyncio.run(tasks.hydrate_tasks(persisted))

    hydrated = client.get(f"/api/tasks/{task_id}")
    assert hydrated.status_code == 200
    task = hydrated.json()["task"]
    assert task["task_id"] == task_id
    assert task["status"] == "planned"
    assert len(task["steps"]) == 1


def test_ui_telemetry_ingest_and_list():
    _reset_runtime()
    payload = {
        "events": [
            {
                "session_id": "session-a",
                "kind": "ui_loaded",
                "message": "ui loaded",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": {"path": "/"},
            }
        ]
    }
    posted = client.post("/api/ui-telemetry", json=payload)
    assert posted.status_code == 200
    body = posted.json()
    assert body["accepted"] == 1
    artifact_path = Path(body["artifact_file"])
    assert artifact_path.exists()

    listed = client.get("/api/ui-telemetry?session_id=session-a&limit=5")
    assert listed.status_code == 200
    events = listed.json()["events"]
    assert len(events) == 1
    assert events[0]["session_id"] == "session-a"
    assert events[0]["kind"] == "ui_loaded"
    assert isinstance(events[0]["timestamp"], str)


def test_ui_telemetry_requires_session_id():
    _reset_runtime()
    resp = client.post(
        "/api/ui-telemetry",
        json={
            "events": [
                {
                    "kind": "ws_open",
                    "message": "missing session id",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ]
        },
    )
    assert resp.status_code == 422


def test_ui_telemetry_reset_clears_session_buffer():
    _reset_runtime()
    posted = client.post(
        "/api/ui-telemetry",
        json={
            "events": [
                {
                    "session_id": "session-reset",
                    "kind": "snapshot_received",
                    "message": "got snapshot",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ]
        },
    )
    assert posted.status_code == 200

    reset = client.post("/api/ui-telemetry/reset")
    assert reset.status_code == 200
    assert reset.json()["cleared"] >= 1

    listed = client.get("/api/ui-telemetry?session_id=session-reset")
    assert listed.status_code == 200
    assert listed.json()["events"] == []


def test_ui_telemetry_sessions_lists_recent_session_stats():
    _reset_runtime()
    now = datetime.now(timezone.utc)
    posted = client.post(
        "/api/ui-telemetry",
        json={
            "events": [
                {
                    "session_id": "session-one",
                    "kind": "ui_boot",
                    "message": "boot",
                    "timestamp": now.isoformat(),
                },
                {
                    "session_id": "session-two",
                    "kind": "ws_open",
                    "message": "open",
                    "timestamp": (now.replace(microsecond=0)).isoformat(),
                },
                {
                    "session_id": "session-one",
                    "kind": "snapshot_fetched",
                    "message": "snapshot",
                    "timestamp": (now.replace(microsecond=0)).isoformat(),
                },
            ]
        },
    )
    assert posted.status_code == 200

    listed = client.get("/api/ui-telemetry/sessions?limit=5")
    assert listed.status_code == 200
    sessions = listed.json()["sessions"]
    assert len(sessions) == 2
    assert sessions[0]["session_id"] == "session-one"
    assert sessions[0]["event_count"] == 2
    assert sessions[0]["first_timestamp"] is not None
    assert sessions[0]["last_timestamp"] is not None
    assert sessions[0]["artifact_file"].endswith("session-one.jsonl")
    assert sessions[1]["session_id"] == "session-two"
    assert sessions[1]["event_count"] == 1


def test_ui_telemetry_sessions_limit():
    _reset_runtime()
    posted = client.post(
        "/api/ui-telemetry",
        json={
            "events": [
                {
                    "session_id": "a",
                    "kind": "ui_boot",
                    "message": "a",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                {
                    "session_id": "b",
                    "kind": "ui_boot",
                    "message": "b",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            ]
        },
    )
    assert posted.status_code == 200

    listed = client.get("/api/ui-telemetry/sessions?limit=1")
    assert listed.status_code == 200
    sessions = listed.json()["sessions"]
    assert len(sessions) == 1


def test_ui_telemetry_list_falls_back_to_artifacts_when_memory_cleared():
    _reset_runtime()
    session_id = "session-artifact-fallback"
    posted = client.post(
        "/api/ui-telemetry",
        json={
            "events": [
                {
                    "session_id": session_id,
                    "kind": "ui_boot",
                    "message": "boot",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ]
        },
    )
    assert posted.status_code == 200
    artifact_path = Path(posted.json()["artifact_file"])
    assert artifact_path.exists()

    reset = client.post("/api/ui-telemetry/reset?clear_artifacts=false")
    assert reset.status_code == 200
    assert reset.json()["cleared"] >= 1

    listed = client.get(f"/api/ui-telemetry?session_id={session_id}&limit=10")
    assert listed.status_code == 200
    events = listed.json()["events"]
    assert len(events) == 1
    assert events[0]["session_id"] == session_id
    assert events[0]["kind"] == "ui_boot"


def test_ui_telemetry_sessions_include_artifact_only_sessions():
    _reset_runtime()
    session_id = "session-artifact-only"
    posted = client.post(
        "/api/ui-telemetry",
        json={
            "events": [
                {
                    "session_id": session_id,
                    "kind": "ws_open",
                    "message": "connected",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ]
        },
    )
    assert posted.status_code == 200
    assert Path(posted.json()["artifact_file"]).exists()

    reset = client.post("/api/ui-telemetry/reset?clear_artifacts=false")
    assert reset.status_code == 200

    sessions = client.get("/api/ui-telemetry/sessions?limit=10")
    assert sessions.status_code == 200
    payload = sessions.json()["sessions"]
    assert any(item["session_id"] == session_id for item in payload)


def test_cancel_all_autonomy_runs():
    _reset_runtime()
    # Start two runs
    resp1 = client.post(
        "/api/autonomy/runs",
        json={"objective": "Task A", "max_iterations": 24},
    )
    assert resp1.status_code == 200
    resp2 = client.post(
        "/api/autonomy/runs",
        json={"objective": "Task B", "max_iterations": 24},
    )
    assert resp2.status_code == 200

    # Wait for both to reach waiting_approval (deterministic planner generates
    # irreversible steps that need approval)
    _wait_for_run_status(resp1.json()["run"]["run_id"], {"waiting_approval", "running", "completed"})
    _wait_for_run_status(resp2.json()["run"]["run_id"], {"waiting_approval", "running", "completed"})

    # Cancel all
    cancel_resp = client.post("/api/autonomy/cancel-all")
    assert cancel_resp.status_code == 200
    data = cancel_resp.json()
    assert isinstance(data["cancelled"], int)
    assert isinstance(data["runs"], list)
