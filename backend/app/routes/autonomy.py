"""Autonomy run management routes."""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

import app.deps as _deps

from ..config import settings
from ..deps import (
    PLANNER_SOURCE_CONFIG_DEFAULT,
    PLANNER_SOURCE_RUNTIME_OVERRIDE,
    RUNTIME_SETTING_PLANNER_MODE,
    _dump,
    _planner_status_payload,
    autonomy,
    db,
    planner,
    tasks,
)
from ..schemas import (
    AutonomyApproveRequest,
    AutonomyPlannerModeRequest,
    AutonomyStartRequest,
    ReadinessGateRequest,
    ReadinessMatrixRequest,
)

router = APIRouter()


def _autonomy_http_error(exc: Exception) -> HTTPException:
    message = str(exc)
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=message)
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=message)
    if "ollama planner required" in message.lower():
        return HTTPException(status_code=503, detail=message)
    return HTTPException(status_code=409, detail=message)


@router.post("/api/autonomy/runs")
async def start_autonomy_run(request: AutonomyStartRequest) -> dict:
    try:
        run = await autonomy.start(request)
    except Exception as exc:
        raise _autonomy_http_error(exc)
    return {"run": _dump(run)}


@router.get("/api/autonomy/planner")
async def get_autonomy_planner() -> dict:
    return await _planner_status_payload()


@router.post("/api/autonomy/planner")
async def set_autonomy_planner(request: AutonomyPlannerModeRequest) -> dict:
    planner.set_mode(request.mode)
    await db.set_runtime_setting(RUNTIME_SETTING_PLANNER_MODE, planner.mode)
    _deps.planner_mode_source = PLANNER_SOURCE_RUNTIME_OVERRIDE
    return await _planner_status_payload()


@router.delete("/api/autonomy/planner")
async def clear_autonomy_planner_override() -> dict:
    await db.delete_runtime_setting(RUNTIME_SETTING_PLANNER_MODE)
    planner.set_mode(settings.autonomy_planner_mode)
    _deps.planner_mode_source = PLANNER_SOURCE_CONFIG_DEFAULT
    return await _planner_status_payload()


@router.get("/api/autonomy/runs")
async def list_autonomy_runs(limit: int = 50) -> dict:
    runs = await autonomy.list_runs(limit=limit)
    return {"runs": [_dump(run) for run in runs]}


@router.get("/api/autonomy/runs/{run_id}")
async def get_autonomy_run(run_id: str) -> dict:
    run = await autonomy.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return {"run": _dump(run)}


@router.post("/api/autonomy/runs/{run_id}/approve")
async def approve_autonomy_run(run_id: str, request: AutonomyApproveRequest) -> dict:
    try:
        run = await autonomy.approve(run_id, request)
    except Exception as exc:
        raise _autonomy_http_error(exc)
    return {"run": _dump(run)}


@router.post("/api/autonomy/runs/{run_id}/cancel")
async def cancel_autonomy_run(run_id: str) -> dict:
    try:
        run = await autonomy.cancel(run_id)
    except Exception as exc:
        raise _autonomy_http_error(exc)
    return {"run": _dump(run)}


# ── Readiness gate & matrix ───────────────────────────────────────────────

async def _execute_readiness_gate(request: ReadinessGateRequest) -> dict:
    started_at = datetime.now(timezone.utc)
    preflight = await tasks.executor_preflight()
    cleanup = {"attempted": False, "cancelled": False, "error": None}

    async def _cleanup_run(run_obj):
        if run_obj is None:
            return None
        if not request.cleanup_on_exit:
            return run_obj
        if run_obj.status in {"completed", "failed", "cancelled"}:
            return run_obj
        cleanup["attempted"] = True
        try:
            cancelled = await autonomy.cancel(run_obj.run_id)
            cleanup["cancelled"] = cancelled.status == "cancelled"
            return cancelled
        except Exception as exc:
            cleanup["error"] = str(exc)
            return run_obj

    def _result(*, ok: bool, reason: str, run_obj, timeline: list[dict]) -> dict:
        finished_at = datetime.now(timezone.utc)
        return {
            "ok": ok,
            "reason": reason,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "elapsed_ms": int((finished_at - started_at).total_seconds() * 1000),
            "preflight": preflight,
            "run": _dump(run_obj) if run_obj is not None else None,
            "timeline": timeline,
            "cleanup": cleanup,
        }

    if request.require_preflight_ok and not bool(preflight.get("ok", False)):
        return _result(ok=False, reason="preflight_failed", run_obj=None, timeline=[])

    start_req = AutonomyStartRequest(
        objective=request.objective,
        max_iterations=request.max_iterations,
        parallel_agents=request.parallel_agents,
        auto_approve_irreversible=False,
    )
    run = await autonomy.start(start_req)
    timeline = [
        {
            "status": run.status,
            "iteration": run.iteration,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    ]
    last_status = run.status

    deadline = started_at.timestamp() + request.timeout_s
    poll_s = request.poll_interval_ms / 1000.0
    terminal = {"completed", "failed", "cancelled"}

    while datetime.now(timezone.utc).timestamp() < deadline:
        current = await autonomy.get_run(run.run_id)
        if current is None:
            return _result(ok=False, reason="run_not_found", run_obj=None, timeline=timeline)

        if current.status != last_status:
            last_status = current.status
            timeline.append(
                {
                    "status": current.status,
                    "iteration": current.iteration,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

        if current.status == "waiting_approval":
            if request.auto_approve_irreversible and current.approval_token:
                current = await autonomy.approve(
                    current.run_id,
                    AutonomyApproveRequest(approval_token=current.approval_token),
                )
                if current.status != last_status:
                    last_status = current.status
                    timeline.append(
                        {
                            "status": current.status,
                            "iteration": current.iteration,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                if current.status in terminal:
                    ok = current.status == "completed"
                    return _result(
                        ok=ok,
                        reason="completed" if ok else f"run_{current.status}",
                        run_obj=current,
                        timeline=timeline,
                    )
            else:
                cleaned = await _cleanup_run(current)
                return _result(
                    ok=False,
                    reason="approval_required",
                    run_obj=cleaned,
                    timeline=timeline,
                )

        if current.status in terminal:
            ok = current.status == "completed"
            return _result(
                ok=ok,
                reason="completed" if ok else f"run_{current.status}",
                run_obj=current,
                timeline=timeline,
            )

        await asyncio.sleep(poll_s)

    timeout_run = await autonomy.get_run(run.run_id)
    cleaned_timeout = await _cleanup_run(timeout_run)
    return _result(
        ok=False,
        reason="timeout",
        run_obj=cleaned_timeout,
        timeline=timeline,
    )


@router.post("/api/readiness/gate")
async def run_readiness_gate(request: ReadinessGateRequest) -> dict:
    return await _execute_readiness_gate(request)


@router.post("/api/readiness/matrix")
async def run_readiness_matrix(request: ReadinessMatrixRequest) -> dict:
    started_at = datetime.now(timezone.utc)
    results = []
    passed = 0
    failed = 0

    for objective in request.objectives:
        objective_text = (objective or "").strip()
        if not objective_text:
            continue
        gate_request = ReadinessGateRequest(
            objective=objective_text,
            timeout_s=request.timeout_s,
            poll_interval_ms=request.poll_interval_ms,
            max_iterations=request.max_iterations,
            parallel_agents=request.parallel_agents,
            auto_approve_irreversible=request.auto_approve_irreversible,
            require_preflight_ok=request.require_preflight_ok,
            cleanup_on_exit=request.cleanup_on_exit,
        )
        report = await _execute_readiness_gate(gate_request)
        ok = bool(report.get("ok", False))
        if ok:
            passed += 1
        else:
            failed += 1
        results.append({"objective": objective_text, "report": report})

        if request.stop_on_failure and not ok:
            break

    finished_at = datetime.now(timezone.utc)
    return {
        "ok": failed == 0 and len(results) > 0,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "elapsed_ms": int((finished_at - started_at).total_seconds() * 1000),
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "results": results,
    }
