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
    autonomy_promoter,
    db,
    hub,
    planner,
    tasks,
    vision_runner,
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


@router.get("/api/autonomy/promotion")
async def get_autonomy_promotion_status() -> dict:
    """Return current autonomy promotion state and recommendation."""
    recent_runs = await db.recent_autonomy_outcomes(limit=20)
    result = autonomy_promoter.recommend(recent_runs)
    result["auto_promote_enabled"] = settings.autonomy_auto_promote
    return result


@router.post("/api/autonomy/runs")
async def start_autonomy_run(request: AutonomyStartRequest) -> dict:
    """Start a new autonomous task execution run."""
    # Auto-promote if enabled and no explicit level override
    if settings.autonomy_auto_promote and request.autonomy_level == "supervised":
        recent_runs = await db.recent_autonomy_outcomes(limit=20)
        recommendation = autonomy_promoter.recommend(recent_runs)
        promoted_level = recommendation["recommended_level"]
        if promoted_level != "supervised":
            request = request.model_copy(
                update={"autonomy_level": promoted_level}
            )
    try:
        run = await autonomy.start(request)
    except Exception as exc:
        raise _autonomy_http_error(exc)
    return {"run": _dump(run)}


@router.get("/api/autonomy/planner")
async def get_autonomy_planner() -> dict:
    """Return current autonomy planner mode and Ollama status."""
    return await _planner_status_payload()


@router.post("/api/autonomy/planner")
async def set_autonomy_planner(request: AutonomyPlannerModeRequest) -> dict:
    """Set the autonomy planner mode at runtime."""
    planner.set_mode(request.mode)
    await db.set_runtime_setting(RUNTIME_SETTING_PLANNER_MODE, planner.mode)
    _deps.planner_mode_source = PLANNER_SOURCE_RUNTIME_OVERRIDE
    return await _planner_status_payload()


@router.delete("/api/autonomy/planner")
async def clear_autonomy_planner_override() -> dict:
    """Reset the planner mode to the config default."""
    await db.delete_runtime_setting(RUNTIME_SETTING_PLANNER_MODE)
    planner.set_mode(settings.autonomy_planner_mode)
    _deps.planner_mode_source = PLANNER_SOURCE_CONFIG_DEFAULT
    return await _planner_status_payload()


@router.get("/api/autonomy/runs")
async def list_autonomy_runs(limit: int = 50) -> dict:
    """List recent autonomy runs ordered by update time."""
    orchestrator_runs = await autonomy.list_runs(limit=limit)
    vision_runs = await vision_runner.list_runs(limit=limit)
    all_runs = orchestrator_runs + vision_runs
    all_runs.sort(key=lambda r: r.updated_at, reverse=True)
    return {"runs": [_dump(run) for run in all_runs[:limit]]}


@router.get("/api/autonomy/runs/{run_id}")
async def get_autonomy_run(run_id: str) -> dict:
    """Get a single autonomy run by ID."""
    run = await autonomy.get_run(run_id)
    if run is None:
        run = await vision_runner.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return {"run": _dump(run)}


@router.post("/api/autonomy/runs/{run_id}/approve")
async def approve_autonomy_run(run_id: str, request: AutonomyApproveRequest) -> dict:
    """Approve an irreversible action in a waiting autonomy run."""
    try:
        run = await autonomy.approve(run_id, request)
    except Exception as exc:
        raise _autonomy_http_error(exc)
    return {"run": _dump(run)}


@router.post("/api/autonomy/runs/{run_id}/cancel")
async def cancel_autonomy_run(run_id: str) -> dict:
    """Cancel an in-progress autonomy run."""
    # Try orchestrator-based runner first, then vision runner
    try:
        run = await autonomy.cancel(run_id)
        return {"run": _dump(run)}
    except KeyError:
        pass
    try:
        run = await vision_runner.cancel(run_id)
    except Exception as exc:
        raise _autonomy_http_error(exc)
    return {"run": _dump(run)}


@router.post("/api/autonomy/cancel-all")
async def cancel_all_autonomy_runs() -> dict:
    """Cancel ALL in-progress autonomy and vision runs (kill switch)."""
    cancelled = []
    # Cancel orchestrator runs
    for run in await autonomy.list_runs(limit=100):
        if run.status in {"running", "waiting_approval"}:
            try:
                result = await autonomy.cancel(run.run_id)
                cancelled.append(_dump(result))
            except Exception:
                pass
    # Cancel vision runs
    for run in await vision_runner.list_runs(limit=100):
        if run.status in {"running", "waiting_approval"}:
            try:
                result = await vision_runner.cancel(run.run_id)
                cancelled.append(_dump(result))
            except Exception:
                pass
    if hub is not None:
        try:
            await hub.broadcast_json({"type": "kill_confirmed", "cancelled": len(cancelled)})
        except Exception:
            pass
    return {"cancelled": len(cancelled), "runs": cancelled}


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
    """Execute a single readiness gate check with timeout and polling."""
    return await _execute_readiness_gate(request)


@router.post("/api/readiness/matrix")
async def run_readiness_matrix(request: ReadinessMatrixRequest) -> dict:
    """Run multiple readiness gates across a list of objectives."""
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
