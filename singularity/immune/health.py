"""
IMMUNE — Health Tracker (Patient)
====================================

The health tracker takes damage. It CANNOT heal itself.

Design principle (Ali, Day 19):
    "Recovery is no points. Only way to self heal is through an external
     auditor and healer. That checks damage and heals appropriately.
     This way the healer remains untouched and uncorrupted so healing
     will never apply a regressed state."

The tracker is the patient. It records wounds. It reports status.
It does NOT prescribe medicine. That's the Auditor's job.

Core concepts:
    - HP (Health Points): 0-100, represents overall system health
    - Damage events: crashes, timeouts, failures reduce HP
    - Status effects: conditions that modify behavior based on HP tier
    - Shield: temporary damage resistance from consecutive clean periods
    - NO self-healing. NO passive regen. NO auto-heal from bus events.

Damage Table:
    - Subsystem crash:       -20 HP
    - Task timeout:          -5 HP
    - LLM provider failure:  -10 HP
    - Rate limit hit:        -3 HP
    - Disk critical (>90%):  -15 HP
    - Memory critical:       -15 HP
    - Exec command failure:  -2 HP
    - Auth failure:          -1 HP

Status Tiers:
    - HEALTHY (HP >= 80):     Normal operation. Shield eligible.
    - STRESSED (HP 50-79):    Increased monitoring frequency. Alerts.
    - DEGRADED (HP 20-49):    Reduced task load. Fallback providers. Loud alerts.
    - CRITICAL (HP 1-19):     Emergency mode. Only essential operations. Escalate to Ali.
    - DOWN (HP 0):            System is non-functional. All-hands alert.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..bus import EventBus

logger = logging.getLogger("singularity.immune")


# ── Enums ──

class HealthStatus(str, Enum):
    HEALTHY = "healthy"       # HP >= 80
    STRESSED = "stressed"     # HP 50-79
    DEGRADED = "degraded"     # HP 20-49
    CRITICAL = "critical"     # HP 1-19
    DOWN = "down"             # HP 0


class DamageType(str, Enum):
    CRASH = "crash"                   # -20
    TIMEOUT = "timeout"               # -5
    PROVIDER_FAILURE = "provider"     # -10
    RATE_LIMIT = "rate_limit"         # -3
    DISK_CRITICAL = "disk"            # -15
    MEMORY_CRITICAL = "memory"        # -15
    EXEC_FAILURE = "exec"             # -2
    AUTH_FAILURE = "auth"             # -1


class HealType(str, Enum):
    """Healing types — ONLY the Auditor may use these."""
    RECOVERY = "recovery"             # +15 — sustained health observed
    CLEAN_AUDIT = "clean_audit"       # +5  — auditor verified all clear
    TASK_COMPLETE = "task_complete"    # +2  — verified task success
    STANDING_OK = "standing_ok"       # +1  — minor positive signal
    RESURRECTION = "resurrection"     # full restore from DOWN


# ── Tables ──

DAMAGE_TABLE: dict[DamageType, int] = {
    DamageType.CRASH: 20,
    DamageType.TIMEOUT: 5,
    DamageType.PROVIDER_FAILURE: 10,
    DamageType.RATE_LIMIT: 3,
    DamageType.DISK_CRITICAL: 15,
    DamageType.MEMORY_CRITICAL: 15,
    DamageType.EXEC_FAILURE: 2,
    DamageType.AUTH_FAILURE: 1,
}

HEAL_TABLE: dict[HealType, int] = {
    HealType.RECOVERY: 15,
    HealType.CLEAN_AUDIT: 5,
    HealType.TASK_COMPLETE: 2,
    HealType.STANDING_OK: 1,
    HealType.RESURRECTION: 100,    # full restore
}


# ── Data Structures ──

@dataclass
class HealthEvent:
    """A single health event (damage or healing)."""
    event_type: str             # "damage" or "heal"
    source: str                 # DamageType or HealType value
    amount: int                 # positive number (damage dealt or health restored)
    hp_before: int
    hp_after: int
    shield_absorbed: int = 0    # damage absorbed by shield
    description: str = ""
    auditor_id: str = ""        # empty for damage, auditor fingerprint for heals
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.event_type,
            "source": self.source,
            "amount": self.amount,
            "hp_before": self.hp_before,
            "hp_after": self.hp_after,
            "shield_absorbed": self.shield_absorbed,
            "description": self.description,
            "auditor_id": self.auditor_id,
            "timestamp": self.timestamp,
        }


@dataclass
class StatusEffect:
    """An active status effect."""
    name: str
    description: str
    applied_at: float = field(default_factory=time.time)
    duration: Optional[float] = None   # None = permanent until condition clears
    modifiers: dict[str, Any] = field(default_factory=dict)

    @property
    def expired(self) -> bool:
        if self.duration is None:
            return False
        return time.time() > self.applied_at + self.duration


# ══════════════════════════════════════════════════════════════
#  HEALTH TRACKER — The Patient
# ══════════════════════════════════════════════════════════════

class HealthTracker:
    """
    The patient. Takes damage. Reports status. CANNOT heal itself.

    Only the Auditor (external, uncorrupted) may call `_receive_healing()`.
    The `heal()` method is gone. There is no self-medication.
    """

    MAX_HP = 100
    SHIELD_THRESHOLD = 1800    # 30 min without damage → shield activates
    SHIELD_ABSORB_PCT = 0.3   # shield absorbs 30% of incoming damage
    SHIELD_HP_MAX = 20         # shield pool

    def __init__(
        self,
        bus: Optional[EventBus] = None,
        state_path: Optional[Path] = None,
    ):
        self.bus = bus
        self.state_path = state_path

        # Core state
        self.hp: int = self.MAX_HP
        self.shield_active: bool = False
        self.shield_hp: int = 0
        self.last_damage_time: float = 0.0
        self.status: HealthStatus = HealthStatus.HEALTHY

        # History (bounded — prevent memory leaks)
        self._event_log_max = 200
        self.event_log: list[HealthEvent] = []
        self.status_effects: list[StatusEffect] = []
        self._status_transition_max = 50
        self._status_transition_log: list[tuple[HealthStatus, HealthStatus, float]] = []

        # Stats
        self.total_damage_taken: int = 0
        self.total_healing_received: int = 0   # only from Auditor
        self.total_shield_absorbed: int = 0
        self.deaths: int = 0
        self.uptime_start: float = time.time()

        # Load persisted state
        if self.state_path and self.state_path.exists():
            self._load_state()

        # Wire bus for auto-damage (NOT auto-heal)
        if self.bus:
            self._wire_bus()

        logger.info(f"❤️ Health Tracker initialized — HP: {self.hp}/{self.MAX_HP} [{self.status.value}]")

    # ── Public API: Damage Only ──

    def take_damage(self, damage_type: DamageType, description: str = "") -> HealthEvent:
        """Apply damage. Anyone can hurt the system."""
        raw_amount = DAMAGE_TABLE.get(damage_type, 5)
        hp_before = self.hp

        # Shield absorption
        shield_absorbed = 0
        if self.shield_active and self.shield_hp > 0:
            shield_absorbed = min(int(raw_amount * self.SHIELD_ABSORB_PCT), self.shield_hp)
            self.shield_hp -= shield_absorbed
            self.total_shield_absorbed += shield_absorbed
            if self.shield_hp <= 0:
                self.shield_active = False
                self.shield_hp = 0
                logger.info("🛡️ Shield broken!")

        actual_damage = raw_amount - shield_absorbed
        self.hp = max(0, self.hp - actual_damage)
        self.last_damage_time = time.time()
        self.total_damage_taken += actual_damage

        event = HealthEvent(
            event_type="damage",
            source=damage_type.value,
            amount=raw_amount,
            hp_before=hp_before,
            hp_after=self.hp,
            shield_absorbed=shield_absorbed,
            description=description,
        )
        self.event_log.append(event)
        if len(self.event_log) > self._event_log_max:
            self.event_log = self.event_log[-self._event_log_max:]
        self._update_status()

        # Check death
        if self.hp == 0 and hp_before > 0:
            self.deaths += 1
            logger.critical(f"💀 SYSTEM DOWN! HP: 0 — death #{self.deaths}")

        # Log
        shield_str = f" (🛡️ absorbed {shield_absorbed})" if shield_absorbed else ""
        logger.warning(
            f"💥 -{actual_damage} HP [{damage_type.value}]{shield_str}: "
            f"{self.hp}/{self.MAX_HP} [{self.status.value}] — {description}"
        )

        # Emit to bus
        self._emit_async("immune.damage", event.to_dict())
        self._persist_state()
        return event

    def tick(self) -> None:
        """
        Called periodically. Handles:
        - Shield activation (earned through surviving without damage)
        - Status effect expiry
        - NO healing. NO regen. That's the Auditor's domain.
        """
        now = time.time()

        # Shield: activates after clean streak (defensive, not healing)
        if not self.shield_active and self.last_damage_time > 0:
            if (now - self.last_damage_time) >= self.SHIELD_THRESHOLD:
                self.shield_active = True
                self.shield_hp = self.SHIELD_HP_MAX
                logger.info("🛡️ Shield activated! (30 min clean streak)")
                self._emit_async("immune.shield.activated", {
                    "hp": self.hp, "shield_hp": self.shield_hp,
                })

        # Expire status effects
        self.status_effects = [e for e in self.status_effects if not e.expired]

    # ── Read-Only Accessors ──

    def snapshot(self) -> dict[str, Any]:
        """Current health state — read-only."""
        return {
            "hp": self.hp,
            "max_hp": self.MAX_HP,
            "hp_pct": round(self.hp / self.MAX_HP * 100, 1),
            "status": self.status.value,
            "shield_active": self.shield_active,
            "shield_hp": self.shield_hp,
            "deaths": self.deaths,
            "total_damage": self.total_damage_taken,
            "total_healing": self.total_healing_received,
            "total_shield_absorbed": self.total_shield_absorbed,
            "uptime_seconds": round(time.time() - self.uptime_start, 0),
            "last_damage_ago": round(time.time() - self.last_damage_time, 0) if self.last_damage_time else None,
            "status_effects": [
                {"name": e.name, "description": e.description}
                for e in self.status_effects
            ],
            "recent_events": [e.to_dict() for e in self.event_log[-10:]],
            "bar": self.render_bar(),
        }

    @property
    def damage_log_since(self) -> list[HealthEvent]:
        """All damage events — for the Auditor to inspect."""
        return [e for e in self.event_log if e.event_type == "damage"]

    @property
    def heal_log(self) -> list[HealthEvent]:
        """All healing events — audit trail of Auditor actions."""
        return [e for e in self.event_log if e.event_type == "heal"]

    def render_bar(self) -> str:
        """Render ASCII health bar."""
        filled = int(self.hp / self.MAX_HP * 20)
        empty = 20 - filled

        if self.hp >= 80:
            char = "█"
        elif self.hp >= 50:
            char = "▓"
        elif self.hp >= 20:
            char = "▒"
        else:
            char = "░"

        bar = char * filled + "·" * empty
        shield = " 🛡️" if self.shield_active else ""
        return f"[{bar}] {self.hp}/{self.MAX_HP}{shield}"

    # ── Healing Port (Auditor-Only) ──

    def _receive_healing(
        self,
        heal_type: HealType,
        amount: int,
        description: str,
        auditor_id: str,
    ) -> HealthEvent:
        """
        Apply healing. This method is PRIVATE — only the Auditor calls it.

        The Auditor provides:
        - What type of healing
        - How much HP to restore (Auditor decides, not the tracker)
        - Description of diagnosis
        - Its own fingerprint (audit trail)

        The tracker cannot call this on itself. It has no reference to
        its own _receive_healing in its public API.
        """
        hp_before = self.hp
        self.hp = min(self.MAX_HP, self.hp + amount)
        self.total_healing_received += amount

        event = HealthEvent(
            event_type="heal",
            source=heal_type.value,
            amount=amount,
            hp_before=hp_before,
            hp_after=self.hp,
            description=description,
            auditor_id=auditor_id,
        )
        self.event_log.append(event)
        if len(self.event_log) > self._event_log_max:
            self.event_log = self.event_log[-self._event_log_max:]

        self._update_status()

        logger.info(
            f"💚 +{amount} HP [{heal_type.value}] by {auditor_id}: "
            f"{self.hp}/{self.MAX_HP} [{self.status.value}] — {description}"
        )

        self._emit_async("immune.heal", event.to_dict())
        self._persist_state()
        return event

    # ── Internal ──

    def _emit_async(self, event_name: str, data: dict[str, Any]) -> None:
        """Fire-and-forget async bus event from sync context."""
        if not self.bus:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.bus.emit(event_name, data))
        except RuntimeError as e:
            logger.debug(f"Suppressed RuntimeError: {e}")

    def _update_status(self) -> None:
        """Update health status based on current HP."""
        old_status = self.status

        if self.hp >= 80:
            self.status = HealthStatus.HEALTHY
        elif self.hp >= 50:
            self.status = HealthStatus.STRESSED
        elif self.hp >= 20:
            self.status = HealthStatus.DEGRADED
        elif self.hp > 0:
            self.status = HealthStatus.CRITICAL
        else:
            self.status = HealthStatus.DOWN

        if old_status != self.status:
            self._status_transition_log.append((old_status, self.status, time.time()))
            if len(self._status_transition_log) > self._status_transition_max:
                self._status_transition_log = self._status_transition_log[-self._status_transition_max:]
            logger.info(f"🔄 Status: {old_status.value} → {self.status.value}")
            self._apply_status_effects()
            self._emit_async("immune.status_change", {
                "old": old_status.value,
                "new": self.status.value,
                "hp": self.hp,
                "bar": self.render_bar(),
            })

    def _apply_status_effects(self) -> None:
        """Apply status effects based on current health tier."""
        self.status_effects = [
            e for e in self.status_effects
            if not e.name.startswith("auto_")
        ]

        if self.status == HealthStatus.STRESSED:
            self.status_effects.append(StatusEffect(
                name="auto_stressed",
                description="Increased monitoring. Watchdog checks every 30s.",
                modifiers={"monitor_interval": 30},
            ))
        elif self.status == HealthStatus.DEGRADED:
            self.status_effects.append(StatusEffect(
                name="auto_degraded",
                description="Reduced load. Max concurrent tasks halved. Fallback providers preferred.",
                modifiers={"max_concurrent": 0.5, "prefer_fallback": True},
            ))
        elif self.status == HealthStatus.CRITICAL:
            self.status_effects.append(StatusEffect(
                name="auto_critical",
                description="Emergency mode. Essential operations only. Alert Ali.",
                modifiers={"essential_only": True, "alert_ali": True},
            ))

    def _wire_bus(self) -> None:
        """Wire bus for automatic DAMAGE only. No auto-heal."""
        if not self.bus:
            return

        async def on_provider_failed(event):
            self.take_damage(DamageType.PROVIDER_FAILURE,
                f"LLM provider failed: {event.data.get('provider', '?')}")

        async def on_task_failed(event):
            self.take_damage(DamageType.TIMEOUT,
                f"Task failed: {event.data.get('task_id', '?')}")

        async def on_adapter_crashed(event):
            self.take_damage(DamageType.CRASH,
                f"Adapter crashed: {event.data.get('adapter', '?')}")

        self.bus.subscribe("voice.provider.failed", on_provider_failed)
        self.bus.subscribe("csuite.task.failed", on_task_failed)
        self.bus.subscribe("nerve.adapter.crashed", on_adapter_crashed)

    def _persist_state(self) -> None:
        """Save state to disk."""
        if not self.state_path:
            return
        try:
            state = {
                "hp": self.hp,
                "shield_active": self.shield_active,
                "shield_hp": self.shield_hp,
                "last_damage_time": self.last_damage_time,
                "total_damage_taken": self.total_damage_taken,
                "total_healing_received": self.total_healing_received,
                "total_shield_absorbed": self.total_shield_absorbed,
                "deaths": self.deaths,
                "uptime_start": self.uptime_start,
                "status": self.status.value,
            }
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(state, indent=2))
        except Exception as e:
            logger.debug(f"State persist error: {e}")

    def _load_state(self) -> None:
        """Load state from disk."""
        try:
            data = json.loads(self.state_path.read_text())
            self.hp = data.get("hp", self.MAX_HP)
            self.shield_active = data.get("shield_active", False)
            self.shield_hp = data.get("shield_hp", 0)
            self.last_damage_time = data.get("last_damage_time", 0)
            self.total_damage_taken = data.get("total_damage_taken", 0)
            self.total_healing_received = data.get("total_healing_received", 0)
            self.total_shield_absorbed = data.get("total_shield_absorbed", 0)
            self.deaths = data.get("deaths", 0)
            self.uptime_start = data.get("uptime_start", time.time())
            self._update_status()
            logger.info(f"❤️ State loaded — HP: {self.hp}/{self.MAX_HP} [{self.status.value}]")
        except Exception as e:
            logger.warning(f"Failed to load state: {e}, starting fresh")
