"""
NEXUS — Self-Evolution Daemon (Subagent)
============================================

Lightweight autonomous subagent that runs continuous self-evolution cycles.

Architecture:
    - Registers as a PULSE interval job (default: every 6 hours)
    - Listens for bus events to trigger on-demand cycles
    - Runs evolution in dry-run first, validates, then applies
    - Reports results to Discord via bus events
    - Crash-isolated: all operations wrapped in try/except with logging
    - Never touches nexus/ files (evolution engine already enforces this)

Bus events:
    LISTENS:
        nexus.daemon.trigger      — Manual trigger (from tool or Discord)
        nexus.evolution.requested — From any subsystem requesting evolution
    EMITS:
        nexus.daemon.started      — Daemon booted
        nexus.daemon.cycle.start  — Cycle beginning
        nexus.daemon.cycle.done   — Cycle complete with results
        nexus.daemon.error        — Non-fatal error during cycle
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..bus import EventBus
    from ..pulse.scheduler import Scheduler
    from .engine import NexusEngine

logger = logging.getLogger("singularity.nexus.daemon")


@dataclass
class EvolutionDetail:
    """Detail of a single applied evolution for reporting."""
    file: str
    line: int
    category: str
    description: str
    original_snippet: str = ""
    evolved_snippet: str = ""


@dataclass
class CycleResult:
    """Result of one daemon evolution cycle."""
    timestamp: float
    duration: float
    dry_run_found: int = 0
    dry_run_validated: int = 0
    applied: int = 0
    failed: int = 0
    skipped_no_targets: bool = False
    error: str | None = None
    details: list[EvolutionDetail] = field(default_factory=list)

    def summary(self) -> str:
        if self.error:
            return f"❌ Evolution cycle failed: {self.error}"
        if self.skipped_no_targets:
            return f"✅ Clean — no evolution targets found ({self.duration:.1f}s)"
        return (
            f"🧬 Evolution cycle complete ({self.duration:.1f}s)\n"
            f"  Found: {self.dry_run_found} | "
            f"Validated: {self.dry_run_validated} | "
            f"Applied: {self.applied} | "
            f"Failed: {self.failed}"
        )


class EvolutionDaemon:
    """
    Autonomous subagent for continuous self-evolution.
    
    Crash-safe design:
    - Every public method is wrapped in try/except
    - State is minimal (just cycle history)
    - No shared mutable state with other subsystems
    - If the engine or hotswap fails, the daemon logs and continues
    """

    PULSE_JOB_ID = "nexus-evolution-daemon"
    DEFAULT_INTERVAL = 6 * 3600  # 6 hours
    MAX_EVOLUTIONS_PER_CYCLE = 25  # Conservative per cycle
    MAX_HISTORY = 50

    def __init__(
        self,
        engine: NexusEngine,
        bus: EventBus,
        scheduler: Scheduler | None = None,
        interval_seconds: int = DEFAULT_INTERVAL,
    ):
        self.engine = engine
        self.bus = bus
        self.scheduler = scheduler
        self.interval = interval_seconds
        self._running = False
        self._cycle_count = 0
        self._history: list[CycleResult] = []
        self._lock = asyncio.Lock()  # Prevent concurrent cycles

    async def start(self) -> None:
        """Boot the daemon. Register with PULSE and event bus."""
        try:
            self._running = True

            # Subscribe to manual trigger events
            if self.bus:
                self.bus.subscribe("nexus.daemon.trigger", self._on_trigger)
                self.bus.subscribe("nexus.evolution.requested", self._on_trigger)

            # Register PULSE job for periodic evolution
            if self.scheduler:
                from ..pulse.scheduler import JobConfig, JobType

                job = JobConfig(
                    id=self.PULSE_JOB_ID,
                    name="NEXUS Self-Evolution",
                    job_type=JobType.INTERVAL,
                    interval_seconds=self.interval,
                    emit_topic="nexus.daemon.trigger",
                    emit_data={"source": "pulse"},
                )
                self.scheduler.add(job)
                logger.info(
                    f"[NEXUS-DAEMON] Registered PULSE job: "
                    f"every {self.interval // 3600}h"
                )

            # Run initial cycle after short delay (let everything boot)
            asyncio.create_task(self._delayed_initial_cycle())

            await self._emit("nexus.daemon.started", {
                "interval_hours": self.interval / 3600,
                "max_per_cycle": self.MAX_EVOLUTIONS_PER_CYCLE,
            })

            logger.info("[NEXUS-DAEMON] Self-evolution daemon started")

        except Exception as e:
            logger.error(f"[NEXUS-DAEMON] Failed to start: {e}", exc_info=True)

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self.scheduler:
            try:
                self.scheduler.remove(self.PULSE_JOB_ID)
            except Exception:
                pass
        logger.info("[NEXUS-DAEMON] Stopped")

    async def run_cycle(self, source: str = "manual") -> CycleResult:
        """
        Execute one evolution cycle.
        
        Strategy:
        1. Dry-run scan to find targets
        2. If targets found, run live evolution (capped at MAX_EVOLUTIONS_PER_CYCLE)
        3. Report results
        
        Thread-safe via asyncio lock — concurrent triggers are queued.
        """
        if not self._running:
            return CycleResult(
                timestamp=time.time(),
                duration=0,
                error="Daemon not running",
            )

        # Prevent concurrent cycles
        if self._lock.locked():
            logger.info("[NEXUS-DAEMON] Cycle already in progress, skipping")
            return CycleResult(
                timestamp=time.time(),
                duration=0,
                error="Cycle already in progress",
            )

        async with self._lock:
            return await self._execute_cycle(source)

    async def _execute_cycle(self, source: str) -> CycleResult:
        """Inner cycle execution (runs under lock)."""
        t0 = time.perf_counter()
        self._cycle_count += 1
        cycle_num = self._cycle_count

        logger.info(f"[NEXUS-DAEMON] Cycle #{cycle_num} starting (source: {source})")
        await self._emit("nexus.daemon.cycle.start", {
            "cycle": cycle_num,
            "source": source,
        })

        result = CycleResult(timestamp=time.time(), duration=0)

        try:
            # Phase 1: Dry run — discover what's available
            dry_report = await self.engine.evolution.evolve(
                dry_run=True,
                max_evolutions=self.MAX_EVOLUTIONS_PER_CYCLE,
            )

            result.dry_run_found = dry_report.evolutions_found
            result.dry_run_validated = dry_report.evolutions_validated

            if dry_report.evolutions_validated == 0:
                result.skipped_no_targets = True
                result.duration = time.perf_counter() - t0
                logger.info(
                    f"[NEXUS-DAEMON] Cycle #{cycle_num} complete — "
                    f"no valid targets ({result.duration:.1f}s)"
                )
                self._record(result)
                await self._emit("nexus.daemon.cycle.done", self._result_dict(result))
                return result

            # Phase 2: Live evolution — apply validated changes
            live_report = await self.engine.evolution.evolve(
                dry_run=False,
                max_evolutions=self.MAX_EVOLUTIONS_PER_CYCLE,
            )

            result.applied = live_report.evolutions_applied
            result.failed = live_report.evolutions_failed
            result.duration = time.perf_counter() - t0

            # Capture details for reporting
            for evo in live_report.details:
                if evo.applied or evo.error:
                    # Trim snippets to first 3 lines max for readability
                    orig = "\n".join(evo.original_code.strip().splitlines()[:3])
                    evolved = "\n".join(evo.evolved_code.strip().splitlines()[:3])
                    result.details.append(EvolutionDetail(
                        file=evo.target_file,
                        line=evo.line,
                        category=evo.category,
                        description=evo.description,
                        original_snippet=orig,
                        evolved_snippet=evolved,
                    ))

            logger.info(
                f"[NEXUS-DAEMON] Cycle #{cycle_num} complete — "
                f"{result.applied} applied, {result.failed} failed "
                f"({result.duration:.1f}s)"
            )

        except Exception as e:
            result.error = str(e)
            result.duration = time.perf_counter() - t0
            logger.error(
                f"[NEXUS-DAEMON] Cycle #{cycle_num} crashed: {e}",
                exc_info=True,
            )
            await self._emit("nexus.daemon.error", {
                "cycle": cycle_num,
                "error": str(e),
            })

        self._record(result)
        await self._emit("nexus.daemon.cycle.done", self._result_dict(result))
        return result

    # ── Event Handlers ────────────────────────────────────────

    async def _on_trigger(self, data: dict | None = None) -> None:
        """Handle trigger events from bus."""
        try:
            source = "bus"
            if data and isinstance(data, dict):
                source = data.get("source", "bus")
            await self.run_cycle(source=source)
        except Exception as e:
            logger.error(f"[NEXUS-DAEMON] Trigger handler error: {e}", exc_info=True)

    async def _delayed_initial_cycle(self) -> None:
        """Run first cycle after boot delay."""
        try:
            await asyncio.sleep(30)  # Let everything settle
            if self._running:
                logger.info("[NEXUS-DAEMON] Running initial boot cycle...")
                await self.run_cycle(source="boot")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[NEXUS-DAEMON] Initial cycle error: {e}", exc_info=True)

    # ── Internal Helpers ──────────────────────────────────────

    def _record(self, result: CycleResult) -> None:
        """Record cycle result in history (bounded)."""
        self._history.append(result)
        if len(self._history) > self.MAX_HISTORY:
            self._history = self._history[-self.MAX_HISTORY:]

    def _result_dict(self, result: CycleResult) -> dict:
        """Convert result to dict for bus emission."""
        return {
            "timestamp": result.timestamp,
            "duration": result.duration,
            "found": result.dry_run_found,
            "validated": result.dry_run_validated,
            "applied": result.applied,
            "failed": result.failed,
            "clean": result.skipped_no_targets,
            "error": result.error,
            "details": [
                {
                    "file": d.file,
                    "line": d.line,
                    "category": d.category,
                    "description": d.description,
                    "original": d.original_snippet,
                    "evolved": d.evolved_snippet,
                }
                for d in result.details
            ],
        }

    async def _emit(self, topic: str, data: dict) -> None:
        """Emit bus event safely."""
        try:
            if self.bus:
                await self.bus.emit(topic, data, source="nexus-daemon")
        except Exception as e:
            logger.debug(f"[NEXUS-DAEMON] Bus emit failed for {topic}: {e}")

    # ── Status API ────────────────────────────────────────────

    def status(self) -> dict:
        """Get daemon status for tools/reporting."""
        last = self._history[-1] if self._history else None
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "interval_hours": self.interval / 3600,
            "last_cycle": {
                "timestamp": last.timestamp if last else None,
                "applied": last.applied if last else 0,
                "clean": last.skipped_no_targets if last else True,
                "error": last.error if last else None,
            } if last else None,
            "total_applied": sum(r.applied for r in self._history),
            "total_failed": sum(r.failed for r in self._history),
            "total_clean_cycles": sum(
                1 for r in self._history if r.skipped_no_targets
            ),
        }
