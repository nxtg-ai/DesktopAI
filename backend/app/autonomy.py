from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Optional
from uuid import uuid4

from .orchestrator import TaskOrchestrator
from .planner import AutonomyPlanner, DeterministicAutonomyPlanner
from .schemas import (
    AgentLogEntry,
    AutonomyApproveRequest,
    AutonomyRunRecord,
    AutonomyStartRequest,
    TaskApproveRequest,
    TaskPlanRequest,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AutonomousRunner:
    """Background task runner that simulates multi-agent autonomous execution."""

    def __init__(
        self,
        orchestrator: TaskOrchestrator,
        on_run_update: Optional[Callable[[AutonomyRunRecord], Awaitable[None]]] = None,
        planner: Optional[AutonomyPlanner] = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._on_run_update = on_run_update
        self._planner = planner or DeterministicAutonomyPlanner()
        self._runs: Dict[str, AutonomyRunRecord] = {}
        self._order: List[str] = []
        self._workers: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def reset(self) -> None:
        async with self._lock:
            for worker in self._workers.values():
                worker.cancel()
            self._workers.clear()
            self._runs.clear()
            self._order.clear()

    async def shutdown(self) -> None:
        repaired: List[AutonomyRunRecord] = []
        async with self._lock:
            for worker in self._workers.values():
                worker.cancel()
            self._workers.clear()

            now = _utcnow()
            for run in self._runs.values():
                if run.status not in {"running", "waiting_approval"}:
                    continue
                run.status = "failed"
                run.last_error = "run interrupted by backend shutdown; restart objective to continue"
                run.approval_token = None
                run.finished_at = now
                run.updated_at = now
                self._append_log(run, "verifier", "Run stopped during backend shutdown.")
                repaired.append(self._clone_run(run))

        for run in repaired:
            await self._notify_update(run)

    async def hydrate_runs(self, runs: List[AutonomyRunRecord]) -> None:
        normalized: List[AutonomyRunRecord] = []
        repaired: List[AutonomyRunRecord] = []
        for run in sorted(runs, key=lambda item: item.started_at):
            snapshot = self._clone_run(run)
            if snapshot.status in {"running", "waiting_approval"}:
                snapshot.status = "failed"
                snapshot.last_error = "run restored after restart; restart objective to continue"
                snapshot.approval_token = None
                snapshot.finished_at = _utcnow()
                snapshot.updated_at = snapshot.finished_at
                self._append_log(snapshot, "verifier", "Run restored as failed after process restart.")
                repaired.append(snapshot)
            normalized.append(snapshot)

        async with self._lock:
            for worker in self._workers.values():
                worker.cancel()
            self._runs = {run.run_id: run for run in normalized}
            self._order = [run.run_id for run in normalized]
            self._workers.clear()

        for run in repaired:
            await self._notify_update(run)

    async def start(self, request: AutonomyStartRequest) -> AutonomyRunRecord:
        task = await self._orchestrator.create_task(request.objective)
        plan_steps = await self._planner.build_plan(request.objective)
        plan = TaskPlanRequest(steps=plan_steps)
        await self._orchestrator.set_plan(task.task_id, plan)
        planner_mode = str(getattr(self._planner, "mode", "deterministic") or "deterministic")

        now = _utcnow()
        run = AutonomyRunRecord(
            run_id=str(uuid4()),
            task_id=task.task_id,
            objective=request.objective,
            planner_mode=planner_mode,
            status="running",
            iteration=0,
            max_iterations=request.max_iterations,
            parallel_agents=request.parallel_agents,
            auto_approve_irreversible=request.auto_approve_irreversible,
            approval_token=None,
            last_error=None,
            started_at=now,
            updated_at=now,
            finished_at=None,
            agent_log=[],
        )
        self._append_log(run, "planner", "Objective accepted and plan drafted.")
        self._append_log(run, "executor", "Execution loop initialized.")
        self._append_log(run, "verifier", "Safety and postcondition checks armed.")

        async with self._lock:
            self._runs[run.run_id] = run
            self._order.append(run.run_id)
            worker = asyncio.create_task(self._worker_loop(run.run_id))
            self._workers[run.run_id] = worker

        await self._notify_update(run)
        return run

    async def list_runs(self, limit: int = 50) -> List[AutonomyRunRecord]:
        async with self._lock:
            if limit <= 0:
                return []
            ids = self._order[-limit:]
            return [self._clone_run(self._runs[run_id]) for run_id in reversed(ids)]

    async def get_run(self, run_id: str) -> Optional[AutonomyRunRecord]:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            return self._clone_run(run)

    async def _get_run_ref(self, run_id: str) -> Optional[AutonomyRunRecord]:
        async with self._lock:
            return self._runs.get(run_id)

    async def approve(self, run_id: str, request: AutonomyApproveRequest) -> AutonomyRunRecord:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise KeyError(f"run not found: {run_id}")
            if run.status != "waiting_approval":
                raise ValueError(f"run is not waiting approval (status={run.status})")
            if not run.approval_token or request.approval_token != run.approval_token:
                raise PermissionError("invalid approval token")
            task_id = run.task_id

        task = await self._orchestrator.approve(
            task_id, TaskApproveRequest(approval_token=request.approval_token)
        )

        snapshot: Optional[AutonomyRunRecord] = None
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise KeyError(f"run not found: {run_id}")
            run.approval_token = None
            run.updated_at = _utcnow()

            if task.status == "completed":
                run.status = "completed"
                run.finished_at = _utcnow()
                run.updated_at = run.finished_at
                self._append_log(run, "verifier", "Approval accepted, run completed.")
                snapshot = self._clone_run(run)
            elif task.status == "waiting_approval":
                run.status = "waiting_approval"
                run.approval_token = task.approval_token
                self._append_log(run, "verifier", "Additional approval required.")
                snapshot = self._clone_run(run)
            else:
                run.status = "running"
                self._append_log(run, "verifier", "Approval accepted, resuming execution.")

                worker = self._workers.get(run_id)
                if worker is None or worker.done():
                    self._workers[run_id] = asyncio.create_task(self._worker_loop(run_id))
                snapshot = self._clone_run(run)

        if snapshot is None:
            raise RuntimeError("approve update snapshot missing")
        await self._notify_update(snapshot)
        return snapshot

    async def cancel(self, run_id: str) -> AutonomyRunRecord:
        snapshot: Optional[AutonomyRunRecord] = None
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise KeyError(f"run not found: {run_id}")
            if run.status in {"completed", "failed", "cancelled"}:
                raise ValueError(f"cannot cancel run with status {run.status}")
            run.status = "cancelled"
            run.finished_at = _utcnow()
            run.updated_at = run.finished_at
            self._append_log(run, "executor", "Run cancelled by operator.")
            worker = self._workers.get(run_id)
            if worker and not worker.done():
                worker.cancel()
            snapshot = self._clone_run(run)

        try:
            await self._orchestrator.cancel_task(run.task_id)
        except Exception:
            pass
        if snapshot is None:
            raise RuntimeError("cancel update snapshot missing")
        await self._notify_update(snapshot)
        return snapshot

    async def _worker_loop(self, run_id: str) -> None:
        try:
            while True:
                run = await self.get_run(run_id)
                if run is None:
                    return
                if run.status in {"completed", "failed", "cancelled"}:
                    return
                if run.status == "waiting_approval":
                    return
                if run.iteration >= run.max_iterations:
                    await self._fail_run(run_id, "maximum iteration budget reached")
                    return

                await self._run_cycle(run_id)

                run_after = await self.get_run(run_id)
                if run_after is None:
                    return
                if run_after.status in {"completed", "failed", "cancelled", "waiting_approval"}:
                    return

                # Yield control for responsive UI updates while keeping momentum.
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            await self._fail_run(run_id, f"autonomy loop crashed: {exc}")

    async def _run_cycle(self, run_id: str) -> None:
        run = await self._get_run_ref(run_id)
        if run is None:
            return

        run.iteration += 1
        run.updated_at = _utcnow()
        self._append_log(run, "planner", f"Iteration {run.iteration}: evaluate next action set.")

        try:
            task = await self._orchestrator.run_task(run.task_id)
        except Exception as exc:
            await self._fail_run(run_id, str(exc))
            return

        self._append_log(run, "executor", "Applied current task plan to runtime.")

        if task.status == "waiting_approval":
            if run.auto_approve_irreversible and task.approval_token:
                self._append_log(
                    run,
                    "verifier",
                    "Irreversible step auto-approved by configuration.",
                )
                approved = await self._orchestrator.approve(
                    run.task_id, TaskApproveRequest(approval_token=task.approval_token)
                )
                run.updated_at = _utcnow()
                run.approval_token = None
                if approved.status == "completed":
                    run.status = "completed"
                    run.finished_at = run.updated_at
                    self._append_log(run, "verifier", "Auto-approval completed run.")
                elif approved.status == "waiting_approval":
                    run.status = "waiting_approval"
                    run.approval_token = approved.approval_token
                    self._append_log(run, "verifier", "Additional approval still required.")
                else:
                    run.status = "running"
                    self._append_log(run, "verifier", "Auto-approval applied, continuing run.")
                await self._notify_update(run)
                return

            run.status = "waiting_approval"
            run.approval_token = task.approval_token
            run.updated_at = _utcnow()
            self._append_log(
                run,
                "verifier",
                "Irreversible step blocked pending operator approval.",
            )
            await self._notify_update(run)
            return

        if task.status == "completed":
            run.status = "completed"
            run.approval_token = None
            run.finished_at = _utcnow()
            run.updated_at = run.finished_at
            self._append_log(run, "verifier", "All postconditions satisfied. Run completed.")
            await self._notify_update(run)
            return

        if task.status in {"failed", "cancelled"}:
            await self._fail_run(run_id, f"task ended with status {task.status}")
            return

        await self._notify_update(run)

    async def _fail_run(self, run_id: str, reason: str) -> None:
        snapshot: Optional[AutonomyRunRecord] = None
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            run.status = "failed"
            run.last_error = reason
            run.finished_at = _utcnow()
            run.updated_at = run.finished_at
            self._append_log(run, "verifier", f"Run failed: {reason}")
            snapshot = self._clone_run(run)
        if snapshot is not None:
            await self._notify_update(snapshot)

    def _append_log(self, run: AutonomyRunRecord, agent: str, message: str) -> None:
        run.agent_log.append(
            AgentLogEntry(
                timestamp=_utcnow(),
                agent=agent,
                message=message,
            )
        )
        # Keep log bounded for fast state transport.
        if len(run.agent_log) > 200:
            run.agent_log = run.agent_log[-200:]

    async def _notify_update(self, run: AutonomyRunRecord) -> None:
        if self._on_run_update is None:
            return
        snapshot = self._clone_run(run)
        try:
            await self._on_run_update(snapshot)
        except Exception:
            # Broadcast failures should not break run control flow.
            return

    def _clone_run(self, run: AutonomyRunRecord) -> AutonomyRunRecord:
        if hasattr(run, "model_copy"):
            return run.model_copy(deep=True)
        return run.copy(deep=True)


class VisionAutonomousRunner:
    """Wraps VisionAgent as an autonomy run with status tracking and agent_log."""

    def __init__(
        self,
        vision_agent,
        on_run_update: Optional[Callable[[AutonomyRunRecord], Awaitable[None]]] = None,
    ) -> None:
        self._agent = vision_agent
        self._on_run_update = on_run_update
        self._runs: Dict[str, AutonomyRunRecord] = {}
        self._order: List[str] = []
        self._workers: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def start(self, request: AutonomyStartRequest) -> AutonomyRunRecord:
        now = _utcnow()
        run = AutonomyRunRecord(
            run_id=str(uuid4()),
            task_id="",
            objective=request.objective,
            planner_mode="vision",
            status="running",
            iteration=0,
            max_iterations=request.max_iterations,
            parallel_agents=1,
            auto_approve_irreversible=request.auto_approve_irreversible,
            started_at=now,
            updated_at=now,
            agent_log=[],
        )
        self._append_log(run, "vision-agent", "Vision agent started.")

        async with self._lock:
            self._runs[run.run_id] = run
            self._order.append(run.run_id)
            worker = asyncio.create_task(self._run_agent(run.run_id, request.objective))
            self._workers[run.run_id] = worker

        await self._notify_update(run)
        return self._clone_run(run)

    async def _run_agent(self, run_id: str, objective: str) -> None:
        try:
            def on_step(step):
                asyncio.get_event_loop().call_soon_threadsafe(
                    lambda: None  # We update synchronously below
                )

            run = self._runs.get(run_id)
            if run is None:
                return

            steps = await self._agent.run(objective, on_step=self._make_step_callback(run_id))

            async with self._lock:
                run = self._runs.get(run_id)
                if run is None:
                    return
                run.iteration = len(steps)
                if steps and steps[-1].action.action == "done":
                    run.status = "completed"
                    run.finished_at = _utcnow()
                    self._append_log(run, "vision-agent", f"Completed: {steps[-1].action.reasoning}")
                else:
                    run.status = "failed"
                    run.last_error = "max iterations reached without completing"
                    run.finished_at = _utcnow()
                    self._append_log(run, "vision-agent", "Max iterations reached.")
                run.updated_at = _utcnow()

            await self._notify_update(run)

        except asyncio.CancelledError:
            async with self._lock:
                run = self._runs.get(run_id)
                if run:
                    run.status = "cancelled"
                    run.finished_at = _utcnow()
                    run.updated_at = run.finished_at
            return
        except Exception as exc:
            async with self._lock:
                run = self._runs.get(run_id)
                if run:
                    run.status = "failed"
                    run.last_error = str(exc)
                    run.finished_at = _utcnow()
                    run.updated_at = run.finished_at
                    self._append_log(run, "vision-agent", f"Error: {exc}")
            if run:
                await self._notify_update(run)

    def _make_step_callback(self, run_id: str):
        def on_step(step):
            run = self._runs.get(run_id)
            if run is None:
                return
            run.iteration += 1
            run.updated_at = _utcnow()
            msg = f"Step {run.iteration}: {step.action.action}"
            if step.action.reasoning:
                msg += f" — {step.action.reasoning}"
            if step.error:
                msg += f" [error: {step.error}]"
            self._append_log(run, "vision-agent", msg)
        return on_step

    async def get_run(self, run_id: str) -> Optional[AutonomyRunRecord]:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            return self._clone_run(run)

    async def cancel(self, run_id: str) -> AutonomyRunRecord:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise KeyError(f"run not found: {run_id}")
            if run.status in {"completed", "failed", "cancelled"}:
                raise ValueError(f"cannot cancel run with status {run.status}")
            run.status = "cancelled"
            run.finished_at = _utcnow()
            run.updated_at = run.finished_at
            self._append_log(run, "vision-agent", "Cancelled by operator.")
            worker = self._workers.get(run_id)
            if worker and not worker.done():
                worker.cancel()
            snapshot = self._clone_run(run)
        await self._notify_update(snapshot)
        return snapshot

    async def list_runs(self, limit: int = 50) -> List[AutonomyRunRecord]:
        async with self._lock:
            if limit <= 0:
                return []
            ids = self._order[-limit:]
            return [self._clone_run(self._runs[rid]) for rid in reversed(ids)]

    def _append_log(self, run: AutonomyRunRecord, agent: str, message: str) -> None:
        run.agent_log.append(
            AgentLogEntry(timestamp=_utcnow(), agent=agent, message=message)
        )
        if len(run.agent_log) > 200:
            run.agent_log = run.agent_log[-200:]

    async def _notify_update(self, run) -> None:
        if self._on_run_update is None:
            return
        snapshot = self._clone_run(run) if hasattr(run, "model_copy") or hasattr(run, "copy") else run
        try:
            await self._on_run_update(snapshot)
        except Exception:
            return

    def _clone_run(self, run: AutonomyRunRecord) -> AutonomyRunRecord:
        if hasattr(run, "model_copy"):
            return run.model_copy(deep=True)
        return run.copy(deep=True)
