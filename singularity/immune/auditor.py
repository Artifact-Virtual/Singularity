"""
IMMUNE — Auditor (External Healer)
======================================

The Auditor is the ONLY entity allowed to heal the HealthTracker.

Design principle (Ali, Day 19):
    "Only way to self heal is through an external auditor and healer.
     That checks damage and heals appropriately. This way the healer
     remains untouched and uncorrupted so healing will never apply
     a regressed state."

The Auditor is:
    - Stateless. It has no HP. It cannot be damaged.
    - Deterministic. Same damage log → same diagnosis → same prescription.
    - External. It reads the tracker but the tracker cannot read it.
    - Immutable. Its healing logic is fixed at construction. No runtime mutation.
    - Auditable. Every heal action is fingerprinted and logged.

The Auditor runs on its own schedule (via PULSE). It:
    1. Reads the HealthTracker's damage log and current state
    2. Diagnoses: what happened? how bad? is it still happening?
    3. Prescribes healing based on evidence, not self-report
    4. Applies the healing via the tracker's private _receive_healing port

The separation guarantees:
    - A corrupted system cannot heal itself back to a corrupted-but-looks-healthy state
    - Healing is always based on external verification, not internal optimism
    - The audit trail is tamper-evident (auditor fingerprint on every heal event)
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..bus import EventBus

from .health import (
    HealthTracker,
    HealthStatus,
    HealType,
    DamageType,
    HEAL_TABLE,
)
from .vitals import collect_vitals

logger = logging.getLogger("singularity.immune.auditor")


# ── Diagnosis ──

@dataclass(frozen=True)
class Diagnosis:
    """Immutable diagnosis from an audit pass."""
    timestamp: float
    hp_observed: int
    status_observed: str
    damage_since_last_audit: int         # total damage since last audit
    damage_events_since: int             # count of damage events since last audit
    damage_active: bool                  # damage still incoming? (last damage < 60s ago)
    vitals_clear: bool                   # system vitals OK?
    prescribed_heal: Optional[HealType]  # what healing, if any
    prescribed_amount: int               # how much HP to restore
    reasoning: str                       # human-readable explanation
    auditor_id: str                      # fingerprint

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "hp": self.hp_observed,
            "status": self.status_observed,
            "damage_since": self.damage_since_last_audit,
            "damage_events": self.damage_events_since,
            "damage_active": self.damage_active,
            "vitals_clear": self.vitals_clear,
            "heal_type": self.prescribed_heal.value if self.prescribed_heal else None,
            "heal_amount": self.prescribed_amount,
            "reasoning": self.reasoning,
            "auditor": self.auditor_id,
        }


# ══════════════════════════════════════════════════════════════
#  AUDITOR — The External Healer
# ══════════════════════════════════════════════════════════════

class Auditor:
    """
    External, uncorruptible healer for the HealthTracker.

    The Auditor has no mutable state of its own. It cannot be damaged.
    It examines the patient, diagnoses, and prescribes. That's it.

    The only mutable data it tracks is `last_audit_time` — when it
    last ran — so it knows which damage events are new. This is a
    cursor, not state. Even if it's lost, the Auditor gracefully
    degrades (audits all events instead of recent ones).
    """

    # Healing thresholds — when does the Auditor heal?
    DAMAGE_COOLDOWN = 60.0     # seconds since last damage before healing is considered
    CLEAN_STREAK_FOR_HEAL = 120.0   # 2 min clean → eligible for clean audit heal
    RECOVERY_THRESHOLD = 300.0      # 5 min clean → recovery heal
    RESURRECTION_COOLDOWN = 600.0   # 10 min down before resurrection attempt

    # Healing caps per audit pass
    MAX_HEAL_PER_AUDIT = 20    # never heal more than 20 HP in one pass

    def __init__(self, bus: Optional[EventBus] = None):
        self.bus = bus
        self.last_audit_time: float = 0.0
        self.audit_count: int = 0
        self.total_healed: int = 0
        self.diagnoses: list[Diagnosis] = []

        # Fingerprint — deterministic, based on class identity
        # This proves which Auditor instance performed the healing
        self._fingerprint = hashlib.sha256(
            f"Auditor::{id(self)}::{time.time()}".encode()
        ).hexdigest()[:16]

        logger.info(f"🔍 Auditor initialized — fingerprint: {self._fingerprint}")

    @property
    def auditor_id(self) -> str:
        return f"auditor:{self._fingerprint}"

    def audit(self, tracker: HealthTracker) -> Diagnosis:
        """
        Run a full audit pass on the HealthTracker.

        Steps:
        1. Read current state (HP, status, damage log)
        2. Check system vitals independently
        3. Diagnose: is healing appropriate?
        4. If yes, apply healing via tracker._receive_healing()
        5. Return the diagnosis (immutable record)

        This method is pure: same input state → same output decision.
        """
        now = time.time()
        self.audit_count += 1

        # ── Step 1: Observe the patient ──
        hp = tracker.hp
        status = tracker.status
        damage_since = self._count_damage_since(tracker)
        damage_events = self._count_damage_events_since(tracker)
        time_since_last_damage = now - tracker.last_damage_time if tracker.last_damage_time > 0 else float("inf")
        damage_active = time_since_last_damage < self.DAMAGE_COOLDOWN

        # ── Step 2: Independent vitals check ──
        vitals = collect_vitals()
        vitals_clear = (
            vitals.disk_used_pct < 90
            and vitals.memory_used_pct < 90
            and vitals.load_average_1m < 8.0
        )

        # ── Step 3: Diagnose ──
        heal_type: Optional[HealType] = None
        heal_amount: int = 0
        reasoning: str = ""

        if hp == 0:
            # Patient is DOWN
            if time_since_last_damage >= self.RESURRECTION_COOLDOWN and vitals_clear:
                heal_type = HealType.RESURRECTION
                heal_amount = 30   # don't full-restore — bring back to DEGRADED, prove stability
                reasoning = (
                    f"System has been DOWN for {time_since_last_damage:.0f}s. "
                    f"No active damage. Vitals clear. Resurrecting to DEGRADED tier (30 HP) "
                    f"— must prove stability before further healing."
                )
            else:
                reasoning = (
                    f"System DOWN. "
                    f"{'Damage still active. ' if damage_active else ''}"
                    f"{'Vitals NOT clear. ' if not vitals_clear else ''}"
                    f"Waiting for {self.RESURRECTION_COOLDOWN}s cooldown "
                    f"(currently {time_since_last_damage:.0f}s)."
                )

        elif damage_active:
            # Damage still incoming — do NOT heal during active damage
            reasoning = (
                f"Damage active ({time_since_last_damage:.0f}s ago). "
                f"Withholding healing until damage subsides. "
                f"Current: {hp} HP [{status.value}]."
            )

        elif not vitals_clear:
            # System vitals are bad — don't heal a sick body
            reasons = []
            if vitals.disk_used_pct >= 90:
                reasons.append(f"disk {vitals.disk_used_pct:.1f}%")
            if vitals.memory_used_pct >= 90:
                reasons.append(f"memory {vitals.memory_used_pct:.1f}%")
            if vitals.load_average_1m >= 8.0:
                reasons.append(f"load {vitals.load_average_1m:.1f}")
            reasoning = (
                f"Vitals NOT clear ({', '.join(reasons)}). "
                f"Healing withheld until underlying conditions resolve. "
                f"Current: {hp} HP [{status.value}]."
            )

        elif hp >= tracker.MAX_HP:
            # Full HP — nothing to heal
            reasoning = "Full HP. No healing needed."

        elif time_since_last_damage >= self.RECOVERY_THRESHOLD:
            # 5+ min clean → recovery heal (larger)
            heal_type = HealType.RECOVERY
            heal_amount = min(HEAL_TABLE[HealType.RECOVERY], self.MAX_HEAL_PER_AUDIT, tracker.MAX_HP - hp)
            reasoning = (
                f"System stable for {time_since_last_damage:.0f}s (>{self.RECOVERY_THRESHOLD}s). "
                f"Vitals clear. Prescribing recovery: +{heal_amount} HP."
            )

        elif time_since_last_damage >= self.CLEAN_STREAK_FOR_HEAL:
            # 2+ min clean → clean audit heal (smaller)
            heal_type = HealType.CLEAN_AUDIT
            heal_amount = min(HEAL_TABLE[HealType.CLEAN_AUDIT], self.MAX_HEAL_PER_AUDIT, tracker.MAX_HP - hp)
            reasoning = (
                f"Clean audit: {time_since_last_damage:.0f}s without damage (>{self.CLEAN_STREAK_FOR_HEAL}s). "
                f"Vitals clear. Prescribing clean audit heal: +{heal_amount} HP."
            )

        else:
            # Too soon — damage subsided but not enough clean time
            reasoning = (
                f"Damage subsided {time_since_last_damage:.0f}s ago. "
                f"Waiting for {self.CLEAN_STREAK_FOR_HEAL}s clean streak before healing. "
                f"Current: {hp} HP [{status.value}]."
            )

        # ── Step 4: Build immutable diagnosis ──
        diagnosis = Diagnosis(
            timestamp=now,
            hp_observed=hp,
            status_observed=status.value,
            damage_since_last_audit=damage_since,
            damage_events_since=damage_events,
            damage_active=damage_active,
            vitals_clear=vitals_clear,
            prescribed_heal=heal_type,
            prescribed_amount=heal_amount,
            reasoning=reasoning,
            auditor_id=self.auditor_id,
        )

        # ── Step 5: Apply healing if prescribed ──
        if heal_type and heal_amount > 0:
            tracker._receive_healing(
                heal_type=heal_type,
                amount=heal_amount,
                description=reasoning,
                auditor_id=self.auditor_id,
            )
            self.total_healed += heal_amount
            logger.info(f"🔍 Audit #{self.audit_count}: HEALED +{heal_amount} HP — {reasoning}")
        else:
            logger.info(f"🔍 Audit #{self.audit_count}: NO HEAL — {reasoning}")

        # Record diagnosis
        self.diagnoses.append(diagnosis)
        if len(self.diagnoses) > 100:
            self.diagnoses = self.diagnoses[-100:]

        # Emit audit event
        if self.bus:
            self._emit_async("immune.audit", diagnosis.to_dict())

        self.last_audit_time = now
        return diagnosis

    def summary(self) -> dict[str, Any]:
        """Auditor stats."""
        return {
            "auditor_id": self.auditor_id,
            "audit_count": self.audit_count,
            "total_healed": self.total_healed,
            "last_audit": self.last_audit_time,
            "recent_diagnoses": [d.to_dict() for d in self.diagnoses[-5:]],
        }

    # ── Internal ──

    def _count_damage_since(self, tracker: HealthTracker) -> int:
        """Total damage HP since last audit."""
        return sum(
            e.amount for e in tracker.event_log
            if e.event_type == "damage" and e.timestamp > self.last_audit_time
        )

    def _count_damage_events_since(self, tracker: HealthTracker) -> int:
        """Count of damage events since last audit."""
        return sum(
            1 for e in tracker.event_log
            if e.event_type == "damage" and e.timestamp > self.last_audit_time
        )

    def _emit_async(self, event_name: str, data: dict[str, Any]) -> None:
        """Fire-and-forget async bus event from sync context."""
        if not self.bus:
            return
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            loop.create_task(self.bus.emit(event_name, data))
        except RuntimeError:
            pass
