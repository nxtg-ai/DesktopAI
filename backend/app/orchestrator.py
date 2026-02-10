"""Task orchestrator with step-by-step execution, approval gates, and retry logic."""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Optional, Set
from uuid import uuid4

logger = logging.getLogger(__name__)

from .action_executor import (
    ActionExecutionResult,
    SimulatedTaskActionExecutor,
    TaskActionExecutor,
)
from .schemas import (
    TaskAction,
    TaskApproveRequest,
    TaskPlanRequest,
    TaskRecord,
    TaskStep,
    TaskStepPlan,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskOrchestrator:
    """Task orchestration with pluggable action execution backend."""

    def __init__(
        self,
        on_task_update: Optional[Callable[[TaskRecord], Awaitable[None]]] = None,
        action_executor: Optional[TaskActionExecutor] = None,
        executor_retry_count: int = 1,
        executor_retry_delay_ms: int = 50,
        state_store=None,
    ) -> None:
        self._on_task_update = on_task_update
        self._action_executor = action_executor or SimulatedTaskActionExecutor()
        self._executor_retry_count = max(1, int(executor_retry_count))
        self._executor_retry_delay_ms = max(0, int(executor_retry_delay_ms))
        self._state_store = state_store
        self._tasks: Dict[str, TaskRecord] = {}
        self._task_order: List[str] = []
        self._update_jobs: Set[asyncio.Task] = set()
        self._lock = asyncio.Lock()

    def executor_status(self) -> Dict[str, object]:
        return self._action_executor.status()

    async def executor_preflight(self) -> Dict[str, object]:
        return await self._action_executor.preflight()

    async def create_task(self, objective: str) -> TaskRecord:
        async with self._lock:
            now = _utcnow()
            task = TaskRecord(
                task_id=str(uuid4()),
                objective=objective,
                status="created",
                created_at=now,
                updated_at=now,
            )
            self._tasks[task.task_id] = task
            self._task_order.append(task.task_id)
            snapshot = self._clone_task(task)
        await self._notify_update(snapshot)
        return snapshot

    async def reset(self) -> None:
        for job in list(self._update_jobs):
            job.cancel()
        self._update_jobs.clear()
        async with self._lock:
            self._tasks.clear()
            self._task_order.clear()

    async def drain_updates(self, timeout_s: Optional[float] = None) -> bool:
        jobs = [job for job in list(self._update_jobs) if not job.done()]
        if not jobs:
            return True
        if timeout_s is None:
            await asyncio.gather(*jobs, return_exceptions=True)
            return True
        done, pending = await asyncio.wait(jobs, timeout=timeout_s)
        return len(pending) == 0

    async def hydrate_tasks(self, tasks: List[TaskRecord]) -> None:
        for job in list(self._update_jobs):
            job.cancel()
        self._update_jobs.clear()
        normalized: List[TaskRecord] = []
        repaired: List[TaskRecord] = []
        for task in sorted(tasks, key=lambda item: item.created_at):
            snapshot = self._clone_task(task)
            if snapshot.status in {"running", "waiting_approval"}:
                snapshot.status = "failed"
                snapshot.approval_token = None
                snapshot.last_error = "task restored after restart; rerun task to continue"
                snapshot.updated_at = _utcnow()
                repaired.append(snapshot)
            normalized.append(snapshot)
        async with self._lock:
            self._tasks = {task.task_id: task for task in normalized}
            self._task_order = [task.task_id for task in normalized]
        for task in repaired:
            await self._notify_update(task)

    async def list_tasks(self, limit: int = 50) -> List[TaskRecord]:
        async with self._lock:
            if limit <= 0:
                return []
            ids = self._task_order[-limit:]
            return [self._clone_task(self._tasks[task_id]) for task_id in reversed(ids)]

    async def get_task(self, task_id: str) -> Optional[TaskRecord]:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            return self._clone_task(task)

    async def set_plan(self, task_id: str, request: TaskPlanRequest) -> TaskRecord:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"task not found: {task_id}")
            if task.status in {"running", "waiting_approval"}:
                raise ValueError("cannot replace plan while task is running")
            if task.status in {"completed", "cancelled"}:
                raise ValueError(f"cannot replace plan when task status is {task.status}")

            task.steps = self._compile_steps(request.steps)
            task.current_step_index = None
            task.approval_token = None
            task.last_error = None
            task.status = "planned"
            task.updated_at = _utcnow()
            snapshot = self._clone_task(task)
        await self._notify_update(snapshot)
        return snapshot

    async def run_task(self, task_id: str) -> TaskRecord:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"task not found: {task_id}")
            if task.status in {"completed", "failed", "cancelled"}:
                raise ValueError(f"cannot run task with status {task.status}")
            if not task.steps:
                raise ValueError("task has no plan steps")
        snapshot = await self._advance_task(task_id)
        await self._notify_update(snapshot)
        return snapshot

    async def approve(self, task_id: str, request: TaskApproveRequest) -> TaskRecord:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"task not found: {task_id}")
            if task.status != "waiting_approval":
                raise ValueError(f"task is not waiting approval (status={task.status})")
            if not task.approval_token or request.approval_token != task.approval_token:
                raise PermissionError("invalid approval token")

            idx = task.current_step_index
            if idx is None or idx < 0 or idx >= len(task.steps):
                raise RuntimeError("task waiting approval but has no current step")

            step = task.steps[idx]
            step.approved = True
            if step.status == "blocked":
                step.status = "pending"
            task.status = "planned"
            task.approval_token = None
            task.updated_at = _utcnow()
        snapshot = await self._advance_task(task_id)
        await self._notify_update(snapshot)
        return snapshot

    async def pause_task(self, task_id: str) -> TaskRecord:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"task not found: {task_id}")
            if task.status in {"completed", "failed", "cancelled"}:
                raise ValueError(f"cannot pause task with status {task.status}")
            task.status = "paused"
            task.updated_at = _utcnow()
            snapshot = self._clone_task(task)
        await self._notify_update(snapshot)
        return snapshot

    async def resume_task(self, task_id: str) -> TaskRecord:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"task not found: {task_id}")
            if task.status != "paused":
                raise ValueError(f"cannot resume task with status {task.status}")
        snapshot = await self._advance_task(task_id)
        await self._notify_update(snapshot)
        return snapshot

    async def cancel_task(self, task_id: str) -> TaskRecord:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"task not found: {task_id}")
            if task.status in {"completed", "failed", "cancelled"}:
                raise ValueError(f"cannot cancel task with status {task.status}")
            task.status = "cancelled"
            task.updated_at = _utcnow()
            snapshot = self._clone_task(task)
        await self._notify_update(snapshot)
        return snapshot

    def _compile_steps(self, steps: List[TaskStepPlan]) -> List[TaskStep]:
        now = _utcnow()
        compiled = []
        for idx, plan in enumerate(steps):
            compiled.append(
                TaskStep(
                    step_id=str(uuid4()),
                    index=idx,
                    action=plan.action,
                    preconditions=list(plan.preconditions),
                    postconditions=list(plan.postconditions),
                    status="pending",
                    approved=False,
                    started_at=None,
                    finished_at=None,
                    result=None,
                    error=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        return compiled

    async def _advance_task(self, task_id: str) -> TaskRecord:
        while True:
            action_snapshot: Optional[TaskAction] = None
            objective = ""
            step_index = -1

            async with self._lock:
                task = self._tasks.get(task_id)
                if task is None:
                    raise KeyError(f"task not found: {task_id}")
                if task.status in {"completed", "failed", "cancelled"}:
                    return self._clone_task(task)
                if task.status == "waiting_approval":
                    return self._clone_task(task)
                if not task.steps:
                    raise ValueError("task has no plan steps")

                task.status = "running"
                next_idx = self._next_pending_step_index(task)
                if next_idx is None:
                    task.current_step_index = None
                    task.approval_token = None
                    task.status = "completed"
                    task.updated_at = _utcnow()
                    return self._clone_task(task)

                task.current_step_index = next_idx
                step = task.steps[next_idx]
                step.updated_at = _utcnow()

                if step.action.irreversible and not step.approved:
                    step.status = "blocked"
                    task.status = "waiting_approval"
                    task.approval_token = self._new_approval_token()
                    task.updated_at = _utcnow()
                    return self._clone_task(task)

                step.status = "running"
                step.started_at = _utcnow()
                step.updated_at = step.started_at
                step_index = next_idx
                objective = task.objective
                action_snapshot = (
                    step.action.model_copy(deep=True)
                    if hasattr(step.action, "model_copy")
                    else step.action.copy(deep=True)
                )

            if action_snapshot is None:
                raise RuntimeError("internal error: missing action snapshot")

            execution = await self._execute_action(action_snapshot, objective=objective)
            finished_at = _utcnow()

            async with self._lock:
                task = self._tasks.get(task_id)
                if task is None:
                    raise KeyError(f"task not found: {task_id}")
                if step_index < 0 or step_index >= len(task.steps):
                    return self._clone_task(task)

                step = task.steps[step_index]
                if step.status not in {"running", "pending"}:
                    return self._clone_task(task)

                if not execution.ok:
                    step.status = "failed"
                    step.error = execution.error
                    step.result = execution.result
                    step.finished_at = finished_at
                    step.updated_at = finished_at
                    task.status = "failed"
                    task.last_error = execution.error or "executor failed"
                    task.approval_token = None
                    task.updated_at = finished_at
                    return self._clone_task(task)

                step.status = "succeeded"
                step.error = None
                step.result = execution.result
                step.finished_at = finished_at
                step.updated_at = finished_at
                task.updated_at = finished_at
                if task.status == "paused":
                    return self._clone_task(task)

    async def _execute_action(self, action: TaskAction, *, objective: str) -> ActionExecutionResult:
        desktop_context = None
        if self._state_store:
            try:
                event = await self._state_store.current()
                if event:
                    from .desktop_context import DesktopContext
                    desktop_context = DesktopContext.from_event(event)
            except Exception as exc:
                logger.debug("Desktop context fetch failed: %s", exc)

        last: Optional[ActionExecutionResult] = None
        for attempt in range(1, self._executor_retry_count + 1):
            try:
                execution = await self._action_executor.execute(
                    action, objective=objective, desktop_context=desktop_context
                )
            except Exception as exc:
                execution = ActionExecutionResult(
                    ok=False,
                    error=f"action executor crashed: {exc}",
                    result={
                        "executor": getattr(self._action_executor, "mode", "unknown"),
                        "action": action.action,
                        "ok": False,
                    },
                )

            last = execution
            result = dict(execution.result or {})
            result["attempts"] = attempt

            if execution.ok:
                return ActionExecutionResult(ok=True, error=None, result=result)

            if not self._should_retry_error(execution.error):
                return ActionExecutionResult(ok=False, error=execution.error, result=result)

            if attempt < self._executor_retry_count and self._executor_retry_delay_ms > 0:
                await asyncio.sleep(self._executor_retry_delay_ms / 1000.0)

        if last is None:
            return ActionExecutionResult(
                ok=False,
                error="action executor did not produce a result",
                result={
                    "executor": getattr(self._action_executor, "mode", "unknown"),
                    "action": action.action,
                    "ok": False,
                    "attempts": 0,
                },
            )
        final = dict(last.result or {})
        final["attempts"] = self._executor_retry_count
        return ActionExecutionResult(ok=False, error=last.error, result=final)

    def _should_retry_error(self, error: Optional[str]) -> bool:
        if not error:
            return True
        lowered = error.lower()
        if "unsupported action" in lowered:
            return False
        return True

    def _next_pending_step_index(self, task: TaskRecord) -> Optional[int]:
        for idx, step in enumerate(task.steps):
            if step.status in {"pending", "blocked"}:
                return idx
        return None

    def _new_approval_token(self) -> str:
        return secrets.token_urlsafe(16)

    async def _notify_update(self, task: TaskRecord) -> None:
        if self._on_task_update is None:
            return
        snapshot = self._clone_task(task)

        async def _run_update() -> None:
            try:
                await self._on_task_update(snapshot)
            except Exception as exc:
                logger.debug("Task update callback failed: %s", exc)

        job = asyncio.create_task(_run_update())
        self._update_jobs.add(job)
        job.add_done_callback(self._update_jobs.discard)

    def _clone_task(self, task: TaskRecord) -> TaskRecord:
        if hasattr(task, "model_copy"):
            return task.model_copy(deep=True)
        return task.copy(deep=True)
