"""Task orchestration routes."""

from fastapi import APIRouter, HTTPException

from ..deps import _dump, tasks
from ..schemas import TaskApproveRequest, TaskCreateRequest, TaskPlanRequest

router = APIRouter()


def _task_http_error(exc: Exception) -> HTTPException:
    message = str(exc)
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=message)
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=message)
    return HTTPException(status_code=409, detail=message)


@router.post("/api/tasks")
async def create_task(request: TaskCreateRequest) -> dict:
    """Create a new task with a given objective."""
    task = await tasks.create_task(request.objective)
    return {"task": _dump(task)}


@router.get("/api/tasks")
async def list_tasks(limit: int = 50) -> dict:
    """List tasks ordered by most recent update."""
    items = await tasks.list_tasks(limit=limit)
    return {"tasks": [_dump(item) for item in items]}


@router.get("/api/tasks/{task_id}")
async def get_task(task_id: str) -> dict:
    """Get a single task by ID."""
    task = await tasks.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    return {"task": _dump(task)}


@router.post("/api/tasks/{task_id}/plan")
async def plan_task(task_id: str, request: TaskPlanRequest) -> dict:
    """Set the execution plan (steps) for a task."""
    try:
        task = await tasks.set_plan(task_id, request)
    except Exception as exc:
        raise _task_http_error(exc)
    return {"task": _dump(task)}


@router.post("/api/tasks/{task_id}/run")
async def run_task(task_id: str) -> dict:
    """Begin executing a planned task."""
    try:
        task = await tasks.run_task(task_id)
    except Exception as exc:
        raise _task_http_error(exc)
    return {"task": _dump(task)}


@router.post("/api/tasks/{task_id}/approve")
async def approve_task(task_id: str, request: TaskApproveRequest) -> dict:
    """Approve an irreversible action in a waiting task."""
    try:
        task = await tasks.approve(task_id, request)
    except Exception as exc:
        raise _task_http_error(exc)
    return {"task": _dump(task)}


@router.post("/api/tasks/{task_id}/pause")
async def pause_task(task_id: str) -> dict:
    """Pause a running task."""
    try:
        task = await tasks.pause_task(task_id)
    except Exception as exc:
        raise _task_http_error(exc)
    return {"task": _dump(task)}


@router.post("/api/tasks/{task_id}/resume")
async def resume_task(task_id: str) -> dict:
    """Resume a paused task."""
    try:
        task = await tasks.resume_task(task_id)
    except Exception as exc:
        raise _task_http_error(exc)
    return {"task": _dump(task)}


@router.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict:
    """Cancel a task."""
    try:
        task = await tasks.cancel_task(task_id)
    except Exception as exc:
        raise _task_http_error(exc)
    return {"task": _dump(task)}
