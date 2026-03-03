"""
CSUITE — Coordinator (Singularity's Brain for C-Suite)
===================================================

The Coordinator IS the dispatch logic, native to Singularity.

It handles:
    1. Task routing — match tasks to executives by keyword/domain
    2. Multi-executive dispatch — fan-out tasks that span domains
    3. Aggregation — collect results from parallel executive runs
    4. Escalation — handle failures, timeouts, blocked tasks
    5. Standing orders — periodic tasks that auto-dispatch
    6. Task queue — buffer tasks when executives are busy

The Coordinator doesn't have its own AgentLoop — it's pure orchestration logic.
It lives on the event bus, listens for dispatch requests, and routes them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from .roles import Role, RoleType, match_roles
from .executive import Executive, Task, TaskResult, TaskStatus

if TYPE_CHECKING:
    from ..bus import EventBus

logger = logging.getLogger("singularity.csuite.coordinator")


@dataclass
class DispatchResult:
    """Result of a coordinated dispatch (may span multiple executives)."""
    dispatch_id: str
    tasks: list[TaskResult] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    escalations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None

    @property
    def all_succeeded(self) -> bool:
        return all(t.status == TaskStatus.COMPLETE for t in self.tasks)

    @property
    def duration(self) -> float:
        if self.completed_at:
            return self.completed_at - self.started_at
        return time.time() - self.started_at

    def summary(self) -> str:
        """Human-readable summary of dispatch results."""
        lines = [f"📋 Dispatch {self.dispatch_id} — {len(self.tasks)} task(s), {self.duration:.1f}s"]
        for t in self.tasks:
            icon = "✅" if t.status == TaskStatus.COMPLETE else "❌" if t.status == TaskStatus.FAILED else "⏱️"
            lines.append(f"  {icon} {t.role.value.upper()}: {t.status.value} ({t.iterations_used} iters, {t.duration_seconds:.1f}s)")
        if self.escalations:
            lines.append(f"  ⚠️ {len(self.escalations)} escalation(s)")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dispatch_id": self.dispatch_id,
            "tasks": [t.to_dict() for t in self.tasks],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "escalations": self.escalations,
            "all_succeeded": self.all_succeeded,
            "duration": round(self.duration, 2),
        }


@dataclass
class StandingOrder:
    """A recurring task that auto-dispatches."""
    order_id: str
    target: RoleType | str        # "all", or specific role
    description: str
    priority: str = "normal"
    interval_seconds: int = 3600  # default: hourly
    last_run: float = 0.0
    enabled: bool = True


class Coordinator:
    """
    Singularity's dispatch engine.
    
    Routes tasks, manages executives, aggregates results.
    Runs on the event bus — no direct channel dependencies.
    """

    def __init__(
        self,
        bus: EventBus,
        executives: dict[RoleType, Executive],
        workspace: Path,
    ):
        self.bus = bus
        self.executives = executives
        self.workspace = workspace
        self._dispatch_history: list[DispatchResult] = []
        self._task_queue: asyncio.Queue[tuple[Task, RoleType]] = asyncio.Queue(maxsize=100)
        self._standing_orders: list[StandingOrder] = []
        self._running = False

        # Wire up bus listeners
        async def _on_dispatch(event):
            await self._handle_dispatch_event(event.data)
        async def _on_escalation(event):
            await self._handle_escalation(event.data)
        self.bus.subscribe("csuite.dispatch", _on_dispatch)
        self.bus.subscribe("csuite.escalation", _on_escalation)

        # Ensure workspace
        self.workspace.mkdir(parents=True, exist_ok=True)
        (self.workspace / "dispatches").mkdir(exist_ok=True)

        logger.info(f"⚡ Coordinator initialized — {len(executives)} executives registered")

    async def start(self) -> None:
        """Start the coordinator's background loops."""
        self._running = True
        asyncio.create_task(self._queue_processor())
        asyncio.create_task(self._standing_order_loop())
        logger.info("⚡ Coordinator started")

    async def stop(self) -> None:
        """Stop the coordinator."""
        self._running = False
        logger.info("⚡ Coordinator stopped")

    # ── Public API ──

    async def dispatch(
        self,
        description: str,
        target: str | RoleType = "auto",
        priority: str = "normal",
        deadline: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
        max_iterations: int = 25,
        requester: str = "singularity",
    ) -> DispatchResult:
        """
        Dispatch a task to one or more executives.
        
        target options:
            - "auto"    — match task to best executive(s) by keywords
            - "all"     — dispatch to all executives
            - "cto"     — dispatch to specific executive
            - RoleType  — dispatch to specific executive
        """
        dispatch_id = str(uuid.uuid4())[:8]
        result = DispatchResult(dispatch_id=dispatch_id)

        # Log dispatch
        logger.info(f"⚡ Dispatch {dispatch_id}: target={target}, priority={priority}")
        await self.bus.emit("csuite.dispatch.started", {
            "dispatch_id": dispatch_id,
            "target": str(target),
            "description": description[:200],
            "priority": priority,
        })

        # Resolve targets
        targets = self._resolve_targets(description, target)

        if not targets:
            logger.warning(f"Dispatch {dispatch_id}: no matching executives for task")
            result.completed_at = time.time()
            return result

        # Create tasks
        tasks = []
        for role_type in targets:
            task = Task(
                description=description,
                priority=priority,
                deadline=deadline,
                requester=requester,
                context=context or {},
                max_iterations=max_iterations,
            )
            tasks.append((task, role_type))

        # Execute in parallel
        if len(tasks) == 1:
            # Single executive — run directly
            task, role_type = tasks[0]
            exec_result = await self._run_task(task, role_type)
            result.tasks.append(exec_result)
        else:
            # Multiple executives — fan out
            coros = [self._run_task(t, rt) for t, rt in tasks]
            exec_results = await asyncio.gather(*coros, return_exceptions=True)
            for er in exec_results:
                if isinstance(er, Exception):
                    logger.error(f"Executive task failed: {er}")
                    result.escalations.append({"error": str(er)})
                else:
                    result.tasks.append(er)

        result.completed_at = time.time()

        # Persist dispatch record
        await self._save_dispatch(result)

        # Emit completion
        await self.bus.emit("csuite.dispatch.completed", result.to_dict())

        self._dispatch_history.append(result)
        logger.info(result.summary())

        return result

    def add_standing_order(self, order: StandingOrder) -> None:
        """Register a standing order for periodic execution."""
        self._standing_orders.append(order)
        logger.info(f"Standing order added: {order.order_id} → {order.target} every {order.interval_seconds}s")

    def get_executive(self, role: RoleType | str) -> Optional[Executive]:
        """Get an executive by role."""
        if isinstance(role, str):
            try:
                role = RoleType(role.lower())
            except ValueError:
                return None
        return self.executives.get(role)

    def status_snapshot(self) -> dict[str, Any]:
        """Full C-Suite status snapshot."""
        return {
            "running": self._running,
            "executives": {
                rt.value: exec.status_snapshot()
                for rt, exec in self.executives.items()
            },
            "queue_size": self._task_queue.qsize(),
            "dispatches_total": len(self._dispatch_history),
            "standing_orders": len(self._standing_orders),
            "standing_orders_enabled": len([o for o in self._standing_orders if o.enabled]),
        }

    # ── Internal ──

    def _resolve_targets(self, description: str, target: str | RoleType) -> list[RoleType]:
        """Resolve dispatch target to list of RoleTypes."""
        if isinstance(target, RoleType):
            return [target]

        target_str = str(target).lower()

        if target_str == "all":
            return list(self.executives.keys())

        if target_str == "auto":
            # Match by keywords
            matches = match_roles(description, threshold=0.05)
            if matches:
                # Take top match, or top 2 if scores are close
                best = matches[0]
                targets = [best[0].role_type]
                if len(matches) > 1 and matches[1][1] >= best[1] * 0.7:
                    targets.append(matches[1][0].role_type)
                return targets
            # Default to CTO if no match
            logger.warning("Auto-routing found no keyword match, defaulting to CTO")
            return [RoleType.CTO]

        # Direct name
        try:
            return [RoleType(target_str)]
        except ValueError:
            logger.error(f"Unknown target: {target_str}")
            return []

    async def _run_task(self, task: Task, role_type: RoleType) -> TaskResult:
        """Run a task on a specific executive."""
        executive = self.executives.get(role_type)
        if not executive:
            return TaskResult(
                task_id=task.task_id,
                role=role_type,
                status=TaskStatus.FAILED,
                error=f"No executive registered for {role_type.value}",
            )

        # If executive is busy, queue the task
        if executive.is_busy:
            logger.info(f"{executive.name} is busy, queuing task {task.task_id}")
            await self._task_queue.put((task, role_type))
            return TaskResult(
                task_id=task.task_id,
                role=role_type,
                status=TaskStatus.PENDING,
                response="Task queued — executive is busy",
            )

        # Apply timeout from escalation rules
        timeout = executive.role.escalation.timeout_seconds
        try:
            return await asyncio.wait_for(
                executive.execute(task),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(f"{executive.name} timed out on task {task.task_id} after {timeout}s")
            return TaskResult(
                task_id=task.task_id,
                role=role_type,
                status=TaskStatus.TIMEOUT,
                error=f"Task timed out after {timeout}s",
                duration_seconds=timeout,
            )

    async def _queue_processor(self) -> None:
        """Background loop to process queued tasks."""
        while self._running:
            try:
                task, role_type = await asyncio.wait_for(
                    self._task_queue.get(),
                    timeout=5.0,
                )
                executive = self.executives.get(role_type)
                if executive and not executive.is_busy:
                    result = await self._run_task(task, role_type)
                    await self.bus.emit("csuite.queued.completed", result.to_dict())
                else:
                    # Re-queue
                    await self._task_queue.put((task, role_type))
                    await asyncio.sleep(2)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Queue processor error: {e}")
                await asyncio.sleep(1)

    async def _standing_order_loop(self) -> None:
        """Background loop to fire standing orders on schedule."""
        while self._running:
            now = time.time()
            for order in self._standing_orders:
                if not order.enabled:
                    continue
                if now - order.last_run >= order.interval_seconds:
                    order.last_run = now
                    logger.info(f"⚡ Standing order firing: {order.order_id}")
                    try:
                        await self.dispatch(
                            description=order.description,
                            target=order.target if isinstance(order.target, str) else order.target,
                            priority=order.priority,
                            requester="standing-order",
                        )
                    except Exception as e:
                        logger.error(f"Standing order {order.order_id} failed: {e}")
            await asyncio.sleep(30)  # check every 30s

    async def _handle_dispatch_event(self, event: dict[str, Any]) -> None:
        """Handle dispatch events from the bus (allows external dispatch via bus)."""
        description = event.get("description", "")
        target = event.get("target", "auto")
        priority = event.get("priority", "normal")
        if description:
            await self.dispatch(
                description=description,
                target=target,
                priority=priority,
                requester=event.get("requester", "bus"),
            )

    async def _handle_escalation(self, event: dict[str, Any]) -> None:
        """Handle escalation events from executives."""
        role = event.get("role", "unknown")
        reason = event.get("reason", "unknown")
        task_id = event.get("task_id", "?")
        description = event.get("description", "")

        logger.warning(f"⚠️ ESCALATION from {role}: {reason} — task {task_id}")

        # Emit to AVA for handling
        await self.bus.emit("csuite.escalation.to_ava", {
            "from": role,
            "reason": reason,
            "task_id": task_id,
            "description": description,
            "timestamp": time.time(),
        })

    async def _save_dispatch(self, result: DispatchResult) -> None:
        """Persist dispatch result."""
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        path = self.workspace / "dispatches" / f"{ts}-{result.dispatch_id}.json"
        try:
            path.write_text(json.dumps(result.to_dict(), indent=2))
        except Exception as e:
            logger.error(f"Failed to save dispatch: {e}")
