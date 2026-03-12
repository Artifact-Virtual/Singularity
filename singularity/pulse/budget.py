"""
PULSE — Iteration Budget Manager
===================================

Tracks iteration usage per agent session. Provides:
- Configurable default + max budgets
- Auto-expansion when complex tasks are detected
- Threshold warnings (⚠️ 10 remaining, 🔶 5 remaining, 🔴 2 remaining)
- Budget events on the bus for other subsystems to react

Design: Each agent loop session has its own budget instance.
The budget emits events that CORTEX listens to for graceful wind-down.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..bus import EventBus


# ── Budget State ──────────────────────────────────────────────

import logging
logger = logging.getLogger("singularity.pulse.budget")

class BudgetState(str, Enum):
    """Current budget health."""
    HEALTHY = "healthy"       # Plenty of iterations left
    WARNING = "warning"       # ≤10 remaining
    CRITICAL = "critical"     # ≤5 remaining
    EMERGENCY = "emergency"   # ≤2 remaining
    EXHAUSTED = "exhausted"   # 0 remaining


@dataclass
class BudgetSnapshot:
    """Point-in-time budget status."""
    used: int
    limit: int
    remaining: int
    state: BudgetState
    expanded: bool
    expand_count: int
    elapsed_seconds: float


@dataclass
class BudgetConfig:
    """Budget configuration."""
    default_limit: int = 20
    max_limit: int = 100
    auto_expand: bool = True
    auto_expand_threshold: int = 18   # Expand when used >= this
    warn_at: int = 10                 # Warning threshold (remaining)
    critical_at: int = 5              # Critical threshold (remaining)
    emergency_at: int = 2             # Emergency threshold (remaining)


# ── Iteration Budget ─────────────────────────────────────────

class IterationBudget:
    """
    Tracks iteration usage for an agent session.
    
    Usage:
        budget = IterationBudget(session_id="abc-123")
        
        while budget.can_continue():
            # do work
            budget.tick()
            
        snapshot = budget.snapshot()
    """
    
    def __init__(
        self,
        session_id: str,
        config: BudgetConfig | None = None,
        bus: EventBus | None = None,
    ):
        self.session_id = session_id
        self.config = config or BudgetConfig()
        self.bus = bus
        
        self._limit = self.config.default_limit
        self._used = 0
        self._expanded = False
        self._expand_count = 0
        self._start_time = time.monotonic()
        self._last_state = BudgetState.HEALTHY
        self._state_transitions: list[tuple[float, BudgetState]] = []
    
    # ── Core API ──────────────────────────────────────────────
    
    @property
    def remaining(self) -> int:
        return max(0, self._limit - self._used)
    
    @property
    def used(self) -> int:
        return self._used
    
    @property
    def limit(self) -> int:
        return self._limit
    
    @property
    def state(self) -> BudgetState:
        remaining = self.remaining
        if remaining == 0:
            return BudgetState.EXHAUSTED
        if remaining <= self.config.emergency_at:
            return BudgetState.EMERGENCY
        if remaining <= self.config.critical_at:
            return BudgetState.CRITICAL
        if remaining <= self.config.warn_at:
            return BudgetState.WARNING
        return BudgetState.HEALTHY
    
    def can_continue(self) -> bool:
        """Check if we can do another iteration."""
        return self.remaining > 0
    
    def tick(self, cost: int = 1) -> BudgetSnapshot:
        """
        Record an iteration. Returns snapshot after tick.
        May trigger auto-expansion and state change events.
        """
        self._used += cost
        
        # Auto-expand check
        if (
            self.config.auto_expand
            and not self._expanded
            and self._used >= self.config.auto_expand_threshold
            and self._limit < self.config.max_limit
        ):
            self._expand()
        
        # State transition check
        new_state = self.state
        if new_state != self._last_state:
            self._state_transitions.append((time.monotonic() - self._start_time, new_state))
            self._emit_state_change(self._last_state, new_state)
            self._last_state = new_state
        
        return self.snapshot()
    
    def expand(self, new_limit: int | None = None) -> bool:
        """
        Manually expand the budget. Returns True if expanded.
        Respects max_limit.
        """
        target = new_limit or self.config.max_limit
        target = min(target, self.config.max_limit)
        
        if target <= self._limit:
            return False
        
        self._limit = target
        self._expanded = True
        self._expand_count += 1
        self._emit("pulse.budget.expanded", {
            "session_id": self.session_id,
            "new_limit": self._limit,
            "reason": "manual",
        })
        return True
    
    def snapshot(self) -> BudgetSnapshot:
        """Get current budget status."""
        return BudgetSnapshot(
            used=self._used,
            limit=self._limit,
            remaining=self.remaining,
            state=self.state,
            expanded=self._expanded,
            expand_count=self._expand_count,
            elapsed_seconds=time.monotonic() - self._start_time,
        )
    
    def force_exhaust(self) -> None:
        """Force exhaust the budget (e.g., on fatal error)."""
        self._used = self._limit
        new_state = self.state
        if new_state != self._last_state:
            self._emit_state_change(self._last_state, new_state)
            self._last_state = new_state
    
    # ── Internal ──────────────────────────────────────────────
    
    def _expand(self) -> None:
        """Auto-expand due to complex task detection."""
        old_limit = self._limit
        self._limit = self.config.max_limit
        self._expanded = True
        self._expand_count += 1
        self._emit("pulse.budget.expanded", {
            "session_id": self.session_id,
            "old_limit": old_limit,
            "new_limit": self._limit,
            "reason": "auto_expand",
            "trigger_iteration": self._used,
        })
    
    def _emit_state_change(self, old: BudgetState, new: BudgetState) -> None:
        """Emit state change event."""
        self._emit("pulse.budget.state_changed", {
            "session_id": self.session_id,
            "old_state": old.value,
            "new_state": new.value,
            "remaining": self.remaining,
            "used": self._used,
            "limit": self._limit,
        })
    
    def _emit(self, topic: str, data: dict) -> None:
        """Fire-and-forget event on bus (if available)."""
        if self.bus:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.bus.emit(topic, data))
            except RuntimeError as e:
                logger.debug(f"Suppressed RuntimeError: {e}")
    
    def __repr__(self) -> str:
        return (
            f"IterationBudget(session={self.session_id!r}, "
            f"used={self._used}/{self._limit}, "
            f"state={self.state.value})"
        )
