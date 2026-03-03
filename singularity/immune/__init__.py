"""
IMMUNE — Health & Recovery
===================================

Architecture (Ali, Day 19): Patient / Auditor separation.

The patient (HealthTracker) takes damage. It CANNOT heal itself.
The healer (Auditor) is external, stateless, uncorruptible.
Only the Auditor may restore HP, after diagnosing the damage log
and verifying system vitals independently.

The feedback bridge (Day 19) wires POA audit results into the immune
system — translating external observations into damage events and
triggering Auditor runs on clean streaks. The nervous system.

The reflector (Day 19) sits above the feedback bridge — curates
awareness before anything reaches a human. Classifies POAs into
operational states (active, dormant, watch, critical, unnecessary),
adjusts monitoring frequency, filters noise, highlights signal.

Subsystems:
- health.py:    HealthTracker — the patient (damage only, no self-heal)
- auditor.py:   Auditor — external healer (diagnose → prescribe → heal)
- feedback.py:  FeedbackBridge — POA → HealthTracker → Auditor wiring
- reflector.py: Reflector — self-review layer (curate before human sees)
- watchdog.py:  Subsystem monitoring, vitals collection, alerting
"""

from .health import (
    HealthTracker,
    HealthStatus,
    DamageType,
    HealType,
    HealthEvent,
    StatusEffect,
    DAMAGE_TABLE,
    HEAL_TABLE,
)
from .auditor import Auditor, Diagnosis
from .feedback import FeedbackBridge, FeedbackEvent
from .reflector import Reflector, ReflectionResult, POAState, POAProfile
from .watchdog import Watchdog, SystemVitals, collect_vitals

__all__ = [
    # Patient
    "HealthTracker",
    "HealthStatus",
    "DamageType",
    "HealType",
    "HealthEvent",
    "StatusEffect",
    "DAMAGE_TABLE",
    "HEAL_TABLE",
    # Healer
    "Auditor",
    "Diagnosis",
    # Nervous System
    "FeedbackBridge",
    "FeedbackEvent",
    # Prefrontal Cortex
    "Reflector",
    "ReflectionResult",
    "POAState",
    "POAProfile",
    # Monitoring
    "Watchdog",
    "SystemVitals",
    "collect_vitals",
]
