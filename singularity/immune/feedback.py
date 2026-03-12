"""
IMMUNE — Feedback Bridge (POA → HealthTracker → Auditor)
============================================================

The nervous system. Wires POA audit results into the immune system
so the organism can feel its own health and heal autonomously.

Flow:
    POA Audit → Feedback Bridge → HealthTracker (damage/observe)
    HealthTracker → Auditor (examine → diagnose → heal)
    Auditor → HealthTracker (apply healing)

The bridge translates external observations (HTTP failures, SSL expiry,
service crashes, disk warnings) into immune system events (damage types,
severity, duration).

Design principles:
    - The bridge is a TRANSLATOR, not a decision maker
    - It maps audit check failures to DamageType/amount
    - It triggers Auditor runs when enough clean audits accumulate
    - It respects the patient/auditor separation — never heals directly
    - Multiple concurrent POAs feed into ONE HealthTracker (the organism has one body)

Ali (Day 19):
    "Audit should feedback to it so it can determine wisely.
     We won't be around always."
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..bus import EventBus

from .health import HealthTracker, DamageType, HealthStatus
from .auditor import Auditor
from ..poa.runtime import AuditReport, CheckResult

logger = logging.getLogger("singularity.immune.feedback")


# ── Damage Mapping ──

# Maps POA check names/patterns to DamageType + severity multiplier
DAMAGE_MAP: dict[str, tuple[DamageType, float]] = {
    "endpoint:":      (DamageType.PROVIDER_FAILURE, 1.0),   # HTTP failures → provider failure
    "ssl:":           (DamageType.PROVIDER_FAILURE, 0.5),   # SSL issues → lower severity
    "service:":       (DamageType.CRASH, 1.0),              # service down = crash
    "disk:":          (DamageType.DISK_CRITICAL, 1.0),      # disk issues
    "memory":         (DamageType.MEMORY_CRITICAL, 1.0),    # memory issues
    "journal:":       (DamageType.EXEC_FAILURE, 0.5),       # journal errors = minor
}

# Severity multipliers for check severity field
SEVERITY_MULTIPLIER: dict[str, float] = {
    "critical": 1.0,
    "warn": 0.5,
    "info": 0.0,   # info-level failures don't deal damage
}


@dataclass
class FeedbackEvent:
    """Record of a single feedback translation."""
    timestamp: float
    product_id: str
    check_name: str
    check_passed: bool
    damage_type: Optional[str]    # DamageType value or None
    damage_dealt: int
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "product_id": self.product_id,
            "check": self.check_name,
            "passed": self.check_passed,
            "damage_type": self.damage_type,
            "damage": self.damage_dealt,
            "description": self.description,
        }


class FeedbackBridge:
    """
    Translates POA audit results into immune system events.

    The bridge:
    1. Receives AuditReport objects from POA runs
    2. Maps failed checks to HealthTracker damage
    3. Tracks consecutive clean audits per product
    4. Triggers Auditor runs on schedule
    5. Emits bus events for observability

    The bridge does NOT:
    - Heal the tracker (only Auditor can)
    - Make policy decisions (only Auditor diagnoses)
    - Modify audit results (it's a translator, not an editor)
    """

    # After N consecutive clean audits, trigger Auditor
    CLEAN_AUDITS_FOR_HEAL_TRIGGER = 2

    # Maximum damage per single audit report (prevent cascade)
    MAX_DAMAGE_PER_AUDIT = 40

    def __init__(
        self,
        tracker: HealthTracker,
        auditor: Auditor,
        bus: Optional[EventBus] = None,
    ):
        self.tracker = tracker
        self.auditor = auditor
        self.bus = bus

        # Per-product tracking
        self._consecutive_clean: dict[str, int] = {}   # product_id → clean audit streak
        self._last_audit_status: dict[str, str] = {}   # product_id → last overall status

        # History
        self.events: list[FeedbackEvent] = []
        self.total_damage_routed: int = 0
        self.total_audits_processed: int = 0
        self.total_healer_triggers: int = 0

        logger.info("🔗 Feedback Bridge initialized — POA → Immune wiring active")

    def process_audit(self, report: AuditReport) -> list[FeedbackEvent]:
        """
        Process a POA audit report and translate into immune events.

        Returns list of FeedbackEvents (for logging/observability).
        """
        self.total_audits_processed += 1
        events: list[FeedbackEvent] = []
        total_damage_this_audit = 0

        # ── Process failed checks → damage ──
        for check in report.checks:
            if check.passed:
                continue

            # Map check name to damage type
            damage_type, base_multiplier = self._resolve_damage_type(check.name)
            if damage_type is None:
                continue

            # Apply severity multiplier
            sev_mult = SEVERITY_MULTIPLIER.get(check.severity, 0.5)
            if sev_mult == 0.0:
                continue   # info-level failures don't damage

            # Calculate effective damage
            from .health import DAMAGE_TABLE
            base_damage = DAMAGE_TABLE.get(damage_type, 5)
            effective_damage = max(1, int(base_damage * base_multiplier * sev_mult))

            # Cap total damage per audit
            if total_damage_this_audit + effective_damage > self.MAX_DAMAGE_PER_AUDIT:
                effective_damage = max(0, self.MAX_DAMAGE_PER_AUDIT - total_damage_this_audit)
                if effective_damage == 0:
                    break

            # Deal damage
            description = f"[{report.product_id}] {check.name}: {check.message}"
            self.tracker.take_damage(damage_type, description)
            total_damage_this_audit += effective_damage
            self.total_damage_routed += effective_damage

            event = FeedbackEvent(
                timestamp=time.time(),
                product_id=report.product_id,
                check_name=check.name,
                check_passed=False,
                damage_type=damage_type.value,
                damage_dealt=effective_damage,
                description=description,
            )
            events.append(event)

            logger.warning(
                f"🔗 POA→Immune: {report.product_id} [{check.name}] "
                f"→ {damage_type.value} (-{effective_damage} HP)"
            )

        # ── Track clean audit streaks ──
        pid = report.product_id
        if report.overall_status == "green":
            self._consecutive_clean[pid] = self._consecutive_clean.get(pid, 0) + 1

            # Trigger Auditor after enough consecutive clean audits
            if self._consecutive_clean[pid] >= self.CLEAN_AUDITS_FOR_HEAL_TRIGGER:
                self._trigger_auditor(
                    reason=f"{pid}: {self._consecutive_clean[pid]} consecutive clean audits"
                )
        else:
            # Reset streak on any non-green audit
            self._consecutive_clean[pid] = 0

        # ── Track status transitions ──
        old_status = self._last_audit_status.get(pid, "unknown")
        new_status = report.overall_status
        self._last_audit_status[pid] = new_status

        if old_status != new_status:
            logger.info(
                f"🔗 {pid} status: {old_status} → {new_status} "
                f"(tracker HP: {self.tracker.hp}/{self.tracker.MAX_HP})"
            )
            self._emit_async("immune.feedback.status_change", {
                "product_id": pid,
                "old_status": old_status,
                "new_status": new_status,
                "tracker_hp": self.tracker.hp,
                "tracker_status": self.tracker.status.value,
            })

        # ── Log all events ──
        if not events:
            events.append(FeedbackEvent(
                timestamp=time.time(),
                product_id=pid,
                check_name="*",
                check_passed=True,
                damage_type=None,
                damage_dealt=0,
                description=f"Clean audit — {report.passed}/{len(report.checks)} checks passed",
            ))

        self.events.extend(events)
        # Keep last 500 events
        if len(self.events) > 500:
            self.events = self.events[-500:]

        # Emit summary event
        self._emit_async("immune.feedback.processed", {
            "product_id": pid,
            "overall_status": new_status,
            "checks_total": len(report.checks),
            "checks_passed": report.passed,
            "checks_failed": report.failed,
            "damage_dealt": total_damage_this_audit,
            "tracker_hp": self.tracker.hp,
            "tracker_status": self.tracker.status.value,
            "clean_streak": self._consecutive_clean.get(pid, 0),
            "bar": self.tracker.render_bar(),
        })

        return events

    def _trigger_auditor(self, reason: str) -> None:
        """Trigger an Auditor examination based on feedback signals."""
        self.total_healer_triggers += 1
        logger.info(f"🔗 Triggering Auditor — reason: {reason}")

        diagnosis = self.auditor.audit(self.tracker)

        self._emit_async("immune.feedback.healer_triggered", {
            "reason": reason,
            "diagnosis": diagnosis.to_dict(),
            "trigger_number": self.total_healer_triggers,
        })

    def force_audit(self) -> None:
        """Force an immediate Auditor run (for manual/CLI use)."""
        self._trigger_auditor(reason="manual trigger")

    def summary(self) -> dict[str, Any]:
        """Feedback bridge stats."""
        return {
            "total_audits_processed": self.total_audits_processed,
            "total_damage_routed": self.total_damage_routed,
            "total_healer_triggers": self.total_healer_triggers,
            "clean_streaks": dict(self._consecutive_clean),
            "product_statuses": dict(self._last_audit_status),
            "tracker_hp": self.tracker.hp,
            "tracker_status": self.tracker.status.value,
            "tracker_bar": self.tracker.render_bar(),
            "recent_events": [e.to_dict() for e in self.events[-10:]],
        }

    def _resolve_damage_type(
        self, check_name: str
    ) -> tuple[Optional[DamageType], float]:
        """Map a check name to its DamageType and base multiplier."""
        for prefix, (dtype, mult) in DAMAGE_MAP.items():
            if check_name.startswith(prefix):
                return dtype, mult
        # Unknown check type — mild damage
        return DamageType.EXEC_FAILURE, 0.3

    def _emit_async(self, event_name: str, data: dict[str, Any]) -> None:
        """Fire-and-forget bus event."""
        if not self.bus:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.bus.emit(event_name, data))
        except RuntimeError as e:
            logger.debug(f"Suppressed RuntimeError: {e}")
