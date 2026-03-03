"""
PULSE — Health Monitor
========================

System-wide health monitoring:
- Per-subsystem health checks
- Aggregate system health
- Heartbeat generation
- Self-healing triggers via bus events

Each subsystem registers a health check function.
The monitor runs checks periodically and emits events
for degraded/recovered states.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from ..bus import EventBus

logger = logging.getLogger("singularity.pulse.health")


# ── Health Status ─────────────────────────────────────────────

class HealthLevel(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class SubsystemHealth:
    """Health status of a single subsystem."""
    name: str
    level: HealthLevel = HealthLevel.UNKNOWN
    message: str = ""
    last_check: float = 0
    check_count: int = 0
    fail_count: int = 0
    consecutive_failures: int = 0
    last_healthy: float = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class SystemHealth:
    """Aggregate system health."""
    level: HealthLevel
    subsystems: dict[str, SubsystemHealth]
    uptime_seconds: float
    timestamp: float


# ── Health Check Registration ─────────────────────────────────

HealthCheckFn = Callable[[], Awaitable[tuple[HealthLevel, str]]]
"""A health check returns (level, message)."""


# ── Health Monitor ────────────────────────────────────────────

class HealthMonitor:
    """
    Monitors system health by running registered health checks.
    
    Usage:
        monitor = HealthMonitor(bus)
        
        # Register subsystem health checks
        monitor.register("voice", voice_health_check)
        monitor.register("memory", memory_health_check)
        
        await monitor.start(check_interval=30)
        
        # Get current health
        health = monitor.get_health()
    """
    
    def __init__(self, bus: EventBus):
        self.bus = bus
        self._checks: dict[str, HealthCheckFn] = {}
        self._status: dict[str, SubsystemHealth] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        self._start_time = time.monotonic()
        self._check_interval = 30.0
        self._recovery_handlers: dict[str, Callable] = {}
    
    # ── Registration ──────────────────────────────────────────
    
    def register(
        self,
        name: str,
        check_fn: HealthCheckFn,
        recovery_fn: Callable | None = None,
    ) -> None:
        """
        Register a subsystem health check.
        
        Args:
            name: Subsystem name (e.g., "voice", "memory")
            check_fn: Async function returning (HealthLevel, message)
            recovery_fn: Optional function to call on failure (self-healing)
        """
        self._checks[name] = check_fn
        self._status[name] = SubsystemHealth(name=name)
        if recovery_fn:
            self._recovery_handlers[name] = recovery_fn
        logger.debug(f"Health check registered: {name}")
    
    def unregister(self, name: str) -> None:
        """Remove a health check."""
        self._checks.pop(name, None)
        self._status.pop(name, None)
        self._recovery_handlers.pop(name, None)
    
    # ── Lifecycle ─────────────────────────────────────────────
    
    async def start(self, check_interval: float = 30.0) -> None:
        """Start periodic health monitoring."""
        if self._running:
            return
        self._running = True
        self._check_interval = check_interval
        self._start_time = time.monotonic()
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Health monitor started (interval={check_interval}s)")
    
    async def stop(self) -> None:
        """Stop health monitoring."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Health monitor stopped")
    
    # ── Queries ───────────────────────────────────────────────
    
    def get_health(self) -> SystemHealth:
        """Get aggregate system health."""
        subsystems = dict(self._status)
        
        # Determine aggregate level
        levels = [s.level for s in subsystems.values()]
        if not levels:
            aggregate = HealthLevel.UNKNOWN
        elif any(l == HealthLevel.UNHEALTHY for l in levels):
            aggregate = HealthLevel.UNHEALTHY
        elif any(l == HealthLevel.DEGRADED for l in levels):
            aggregate = HealthLevel.DEGRADED
        elif all(l == HealthLevel.HEALTHY for l in levels):
            aggregate = HealthLevel.HEALTHY
        else:
            aggregate = HealthLevel.UNKNOWN
        
        return SystemHealth(
            level=aggregate,
            subsystems=subsystems,
            uptime_seconds=time.monotonic() - self._start_time,
            timestamp=time.time(),
        )
    
    def get_subsystem(self, name: str) -> SubsystemHealth | None:
        """Get health of a specific subsystem."""
        return self._status.get(name)
    
    # ── Manual Check ──────────────────────────────────────────
    
    async def check_now(self, subsystem: str | None = None) -> SystemHealth:
        """Run health checks immediately (all or specific)."""
        if subsystem:
            if subsystem in self._checks:
                await self._run_check(subsystem)
        else:
            await self._run_all_checks()
        return self.get_health()
    
    # ── Internal ──────────────────────────────────────────────
    
    async def _monitor_loop(self) -> None:
        """Periodic health check loop."""
        try:
            while self._running:
                await self._run_all_checks()
                await asyncio.sleep(self._check_interval)
        except asyncio.CancelledError:
            pass
    
    async def _run_all_checks(self) -> None:
        """Run all registered health checks."""
        tasks = [self._run_check(name) for name in self._checks]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        # Emit aggregate health
        health = self.get_health()
        await self.bus.emit("pulse.health.report", {
            "level": health.level.value,
            "subsystems": {
                name: {
                    "level": s.level.value,
                    "message": s.message,
                    "consecutive_failures": s.consecutive_failures,
                }
                for name, s in health.subsystems.items()
            },
            "uptime": health.uptime_seconds,
        })
    
    async def _run_check(self, name: str) -> None:
        """Run a single health check."""
        check_fn = self._checks.get(name)
        if not check_fn:
            return
        
        status = self._status[name]
        old_level = status.level
        
        try:
            level, message = await asyncio.wait_for(check_fn(), timeout=10.0)
            status.level = level
            status.message = message
            status.last_check = time.time()
            status.check_count += 1
            
            if level == HealthLevel.HEALTHY:
                status.consecutive_failures = 0
                status.last_healthy = time.time()
            else:
                status.fail_count += 1
                status.consecutive_failures += 1
            
        except asyncio.TimeoutError:
            status.level = HealthLevel.UNHEALTHY
            status.message = "Health check timed out"
            status.fail_count += 1
            status.consecutive_failures += 1
            logger.warning(f"Health check timeout: {name}")
            
        except Exception as e:
            status.level = HealthLevel.UNHEALTHY
            status.message = f"Check error: {e}"
            status.fail_count += 1
            status.consecutive_failures += 1
            logger.error(f"Health check error for {name}: {e}")
        
        # State transition events
        if old_level != status.level:
            if status.level in (HealthLevel.DEGRADED, HealthLevel.UNHEALTHY):
                await self.bus.emit("pulse.health.degraded", {
                    "subsystem": name,
                    "level": status.level.value,
                    "message": status.message,
                    "consecutive_failures": status.consecutive_failures,
                })
            
            elif old_level in (HealthLevel.DEGRADED, HealthLevel.UNHEALTHY) and status.level == HealthLevel.HEALTHY:
                await self.bus.emit("pulse.health.recovered", {
                    "subsystem": name,
                    "was": old_level.value,
                })
        
        # Self-healing (independent of state transitions)
        if (
            status.consecutive_failures >= 3
            and status.consecutive_failures % 3 == 0  # Every 3 consecutive failures
            and name in self._recovery_handlers
        ):
            logger.info(f"Attempting recovery for {name} (consecutive_failures={status.consecutive_failures})")
            try:
                recovery_fn = self._recovery_handlers[name]
                if asyncio.iscoroutinefunction(recovery_fn):
                    await recovery_fn()
                else:
                    recovery_fn()
                await self.bus.emit("pulse.health.recovery_attempted", {
                    "subsystem": name,
                    "attempt": status.consecutive_failures // 3,
                })
            except Exception as e:
                logger.error(f"Recovery failed for {name}: {e}")
