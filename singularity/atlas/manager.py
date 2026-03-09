"""
ATLAS — Board Manager (Orchestrator)
======================================

Ties all layers together:
  Discovery → Topology → Coach → Actions → Board Report

Manages the scan/evaluate/report cycle.
Registers with PULSE for periodic execution.
Emits events on the bus for alerts and topology changes.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..bus import EventBus

from .topology import TopologyGraph, Module, ModuleStatus, IssueSeverity
from .discovery import DiscoveryEngine
from .coach import CoachEngine
from .actions import ActionExecutor
from .board import BoardReporter

logger = logging.getLogger("singularity.atlas")


class Atlas:
    """
    The Board Manager.
    Discovers, maps, evaluates, and reports on the entire enterprise.
    """

    def __init__(
        self,
        state_dir: Path | None = None,
        bus: "EventBus | None" = None,
    ):
        self.bus = bus
        self._state_dir = state_dir or Path.home() / "workspace" / ".singularity" / "atlas"
        self._state_dir.mkdir(parents=True, exist_ok=True)

        # Layers
        self.graph = TopologyGraph()
        self.graph.set_state_path(self._state_dir / "topology.json")

        self.discovery = DiscoveryEngine()
        self.coach = CoachEngine(self.graph)
        self.actions = ActionExecutor(self._state_dir / "actions.jsonl")
        self.reporter = BoardReporter(self.graph)

        # State
        self._cycle_count: int = 0
        self._last_cycle: str = ""
        self._last_issues: list[Any] = []
        self._new_modules: list[str] = []
        self._gone_modules: list[str] = []
        self._running = False

        # Load previous state
        self.graph.load()

    async def run_cycle(self) -> dict:
        """
        Execute one full ATLAS cycle:
          1. Discover all modules
          2. Update topology graph
          3. Mark missed modules (stale/gone)
          4. Run coach evaluation
          5. Execute safe auto-fixes
          6. Save state
          7. Return results
        """
        if self._running:
            logger.warning("ATLAS: Cycle already in progress, skipping")
            return {"status": "skipped", "reason": "already_running"}

        self._running = True
        start = datetime.datetime.now(datetime.timezone.utc)

        try:
            # 1. Discovery
            discovered_modules, discovered_edges = await self.discovery.run_full_scan()

            # 2. Update topology
            discovered_ids = set()
            self._new_modules = []
            for mod in discovered_modules:
                mod_id, is_new = self.graph.upsert_module(mod)
                discovered_ids.add(mod_id)
                if is_new:
                    self._new_modules.append(mod_id)
                    logger.info(f"ATLAS: New module discovered — {mod_id} ({mod.type.value})")

            for edge in discovered_edges:
                self.graph.add_edge(edge)

            # 3. Mark missed modules
            self._gone_modules = []
            for mod_id in list(self.graph.modules.keys()):
                if mod_id not in discovered_ids:
                    new_status = self.graph.mark_missed(mod_id)
                    if new_status == ModuleStatus.GONE:
                        self._gone_modules.append(mod_id)
                        logger.info(f"ATLAS: Module gone — {mod_id}")

            # 4. Coach evaluation
            # Clear previous issues first
            for mod in self.graph.get_active_modules():
                mod.issues = []
            issues = await self.coach.evaluate()
            self._last_issues = issues

            # 5. Auto-fix safe issues
            fixed, failed = await self.actions.execute_safe_fixes(issues)

            # 6. Save state
            self.graph.save()

            # 7. Build result
            self._cycle_count += 1
            self._last_cycle = start.isoformat()
            elapsed = (datetime.datetime.now(datetime.timezone.utc) - start).total_seconds()

            result = {
                "status": "complete",
                "cycle": self._cycle_count,
                "elapsed_s": round(elapsed, 1),
                "modules_found": len(discovered_modules),
                "modules_new": len(self._new_modules),
                "modules_gone": len(self._gone_modules),
                "edges": len(discovered_edges),
                "issues": len(issues),
                "issues_critical": sum(1 for i in issues if i.severity == IssueSeverity.CRITICAL),
                "issues_high": sum(1 for i in issues if i.severity == IssueSeverity.HIGH),
                "auto_fixed": fixed,
                "auto_failed": failed,
                "new_modules": self._new_modules,
                "gone_modules": self._gone_modules,
            }

            # Emit events
            if self.bus:
                await self._emit_events(result, issues)

            logger.info(
                f"ATLAS: Cycle #{self._cycle_count} complete — "
                f"{result['modules_found']} modules, {result['issues']} issues, "
                f"{fixed} auto-fixed in {elapsed:.1f}s"
            )

            return result

        except Exception as e:
            logger.error(f"ATLAS: Cycle failed — {e}")
            return {"status": "error", "error": str(e)}
        finally:
            self._running = False

    async def _emit_events(self, result: dict, issues: list) -> None:
        """Emit bus events for alerts and topology changes."""
        if not self.bus:
            return

        try:
            # Cycle complete
            await self.bus.emit("atlas.cycle.complete", result)

            # New module discoveries
            for mod_id in self._new_modules:
                mod = self.graph.get_module(mod_id)
                if mod:
                    await self.bus.emit("atlas.module.discovered", {
                        "module_id": mod_id,
                        "name": mod.name,
                        "type": mod.type.value,
                        "machine": mod.machine,
                    })

            # Gone modules
            for mod_id in self._gone_modules:
                await self.bus.emit("atlas.module.gone", {"module_id": mod_id})

            # Critical/High issues → alert
            serious = [i for i in issues if i.severity in (IssueSeverity.CRITICAL, IssueSeverity.HIGH) and not i.auto_fixed]
            if serious:
                await self.bus.emit("atlas.alert", {
                    "count": len(serious),
                    "issues": [{"title": i.title, "severity": i.severity.value, "module": i.module_id} for i in serious[:10]],
                })
        except Exception as e:
            logger.debug(f"Suppressed event emission error: {e}")

    def get_board_report(self) -> str:
        """Generate the board report from current state."""
        fixed = sum(1 for i in self._last_issues if i.auto_fixed)
        failed = sum(1 for i in self._last_issues if i.auto_fixable and not i.auto_fixed)
        return self.reporter.generate_board_report(
            issues=self._last_issues,
            actions_taken=fixed,
            actions_failed=failed,
        )

    def get_status(self) -> dict:
        """Quick status for tooling."""
        summary = self.graph.summary()
        return {
            "cycle_count": self._cycle_count,
            "last_cycle": self._last_cycle,
            "running": self._running,
            "modules": summary.get("total_modules", 0),
            "by_status": summary.get("by_status", {}),
            "by_machine": summary.get("by_machine", {}),
            "issues": len(self._last_issues),
            "new_modules": self._new_modules,
            "gone_modules": self._gone_modules,
        }

    def get_module_detail(self, module_id: str) -> str:
        """Get detailed report for a specific module."""
        return self.reporter.generate_module_detail(module_id)

    def get_topology(self) -> str:
        """Get text topology map."""
        return self.reporter.generate_topology_view()
