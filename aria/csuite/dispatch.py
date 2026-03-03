"""
CSUITE — Dispatch Interface
================================

Clean dispatch API that replaces the old executives/dispatch.py webhook system.

This module provides:
    - dispatch()      — send a task to the C-Suite (routes through Coordinator)
    - dispatch_all()  — fan-out to all executives
    - dispatch_to()   — target a specific executive
    - status()        — get C-Suite health snapshot
    - history()       — recent dispatch history

All dispatches go through the Coordinator (Aria).
No webhooks. No Discord. Native event bus.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from .roles import RoleType
from .coordinator import Coordinator, DispatchResult
from .executive import Task, TaskResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger("singularity.csuite.dispatch")


class Dispatcher:
    """
    High-level dispatch interface.
    
    This is the public API that AVA (or any subsystem) uses to interact
    with the C-Suite. It wraps the Coordinator with convenience methods.
    
    Usage:
        dispatcher = Dispatcher(coordinator)
        
        # Auto-route by keywords
        result = await dispatcher.dispatch("Review GLADIUS architecture for bottlenecks")
        
        # Target specific executive
        result = await dispatcher.dispatch_to("cto", "Deploy COMB v0.3.0 to PyPI")
        
        # Fan-out to all
        result = await dispatcher.dispatch_all("Prepare Q1 status reports", priority="high")
    """

    def __init__(self, coordinator: Coordinator):
        self.coordinator = coordinator
        self._dispatch_log: list[dict[str, Any]] = []

    async def dispatch(
        self,
        description: str,
        priority: str = "normal",
        deadline: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
        max_iterations: int = 25,
    ) -> DispatchResult:
        """
        Dispatch a task with auto-routing.
        The Coordinator matches the task to the best executive(s) by keywords.
        """
        result = await self.coordinator.dispatch(
            description=description,
            target="auto",
            priority=priority,
            deadline=deadline,
            context=context,
            max_iterations=max_iterations,
            requester="ava",
        )
        self._log_dispatch("auto", description, priority, result)
        return result

    async def dispatch_to(
        self,
        target: str | RoleType,
        description: str,
        priority: str = "normal",
        deadline: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
        max_iterations: int = 25,
    ) -> DispatchResult:
        """Dispatch a task to a specific executive."""
        result = await self.coordinator.dispatch(
            description=description,
            target=target,
            priority=priority,
            deadline=deadline,
            context=context,
            max_iterations=max_iterations,
            requester="ava",
        )
        self._log_dispatch(str(target), description, priority, result)
        return result

    async def dispatch_all(
        self,
        description: str,
        priority: str = "normal",
        deadline: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
        max_iterations: int = 25,
    ) -> DispatchResult:
        """Dispatch a task to all executives in parallel."""
        result = await self.coordinator.dispatch(
            description=description,
            target="all",
            priority=priority,
            deadline=deadline,
            context=context,
            max_iterations=max_iterations,
            requester="ava",
        )
        self._log_dispatch("all", description, priority, result)
        return result

    def status(self) -> dict[str, Any]:
        """Get full C-Suite status snapshot."""
        return self.coordinator.status_snapshot()

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent dispatch history."""
        return self._dispatch_log[-limit:]

    def executive_status(self, role: str | RoleType) -> Optional[dict[str, Any]]:
        """Get status of a specific executive."""
        exec = self.coordinator.get_executive(role)
        if exec:
            return exec.status_snapshot()
        return None

    def _log_dispatch(
        self,
        target: str,
        description: str,
        priority: str,
        result: DispatchResult,
    ) -> None:
        """Log dispatch for history."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target": target,
            "description": description[:200],
            "priority": priority,
            "dispatch_id": result.dispatch_id,
            "tasks": len(result.tasks),
            "all_succeeded": result.all_succeeded,
            "duration": round(result.duration, 2),
        }
        self._dispatch_log.append(entry)
        logger.info(f"Dispatch logged: {target} → {result.dispatch_id} ({priority})")
