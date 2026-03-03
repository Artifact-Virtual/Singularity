"""
IMMUNE — Reflector (Self-Review Before User)
=================================================

The mirror. Before any audit result reaches a human, Singularity
looks at itself first.

Flow:
    POA audits (raw) → Reflector → refined output + POA state changes → User

What the Reflector does:
    1. Collects all audit reports (from audit-all)
    2. Analyzes PATTERNS across products (not just individual checks)
    3. Classifies each POA's operational state:
        - ACTIVE:   genuinely needs monitoring (failures, flapping, customers)
        - DORMANT:  healthy for N consecutive audits → reduce frequency, suppress output
        - WATCH:    was dormant but showed a blip → temporarily elevated monitoring
        - CRITICAL: actively failing, needs attention NOW
        - UNNECESSARY: no endpoints, no service, no customers → suggest removal
    4. Adjusts audit frequency recommendations
    5. Generates a REFINED report (signal, not noise)
    6. Returns only what matters to the human

Design:
    The Reflector is NOT the immune system. It doesn't deal damage or heal.
    It sits ABOVE the feedback bridge — it curates the bridge's output.
    Think of it as the prefrontal cortex: it receives sensory data,
    filters noise, and decides what deserves conscious attention.

    Feedback Bridge  = nervous system (routes signals)
    Reflector        = prefrontal cortex (curates awareness)
    Auditor          = immune response (heals)
    HealthTracker    = body (takes damage)

Ali (Day 19):
    "When the first audit is created, it should go back to singularity
     once before coming to the User. It should tighten it."
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .feedback import FeedbackBridge, FeedbackEvent
from ..poa.runtime import AuditReport
from ..poa.manager import POAConfig, POAManager, POAStatus

logger = logging.getLogger("singularity.immune.reflector")


class POAState(str, Enum):
    """Operational state of a POA (as determined by Reflector)."""
    ACTIVE = "active"           # Needs real monitoring
    DORMANT = "dormant"         # Healthy, boring — suppress noise
    WATCH = "watch"             # Was dormant, blipped — elevated temporarily
    CRITICAL = "critical"       # Actively failing
    UNNECESSARY = "unnecessary" # No real purpose — suggest removal


@dataclass
class POAProfile:
    """Reflector's accumulated understanding of a single POA."""
    product_id: str
    product_name: str
    state: POAState = POAState.ACTIVE

    # Tracking
    total_audits: int = 0
    consecutive_green: int = 0
    consecutive_red: int = 0
    total_failures: int = 0
    total_damage_caused: int = 0

    # Timing
    last_audit_time: float = 0.0
    last_failure_time: float = 0.0
    last_state_change: float = 0.0

    # Config assessment
    has_endpoints: bool = False
    has_service: bool = False
    has_customers: bool = False       # future: customer count > 0
    endpoint_count: int = 0

    # Frequency recommendation
    recommended_interval_hours: float = 4.0   # default: every 4h
    suppressed: bool = False                  # if True, don't show in output

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "state": self.state.value,
            "total_audits": self.total_audits,
            "consecutive_green": self.consecutive_green,
            "consecutive_red": self.consecutive_red,
            "total_failures": self.total_failures,
            "total_damage_caused": self.total_damage_caused,
            "recommended_interval_hours": self.recommended_interval_hours,
            "suppressed": self.suppressed,
            "has_endpoints": self.has_endpoints,
            "has_service": self.has_service,
            "endpoint_count": self.endpoint_count,
        }


@dataclass
class ReflectionResult:
    """Output of a Reflector pass — the curated view for the human."""
    timestamp: float = field(default_factory=time.time)

    # The filtered output
    critical: list[tuple[POAProfile, AuditReport]] = field(default_factory=list)
    active: list[tuple[POAProfile, AuditReport]] = field(default_factory=list)
    watch: list[tuple[POAProfile, AuditReport]] = field(default_factory=list)
    dormant: list[tuple[POAProfile, AuditReport]] = field(default_factory=list)
    unnecessary: list[tuple[POAProfile, AuditReport]] = field(default_factory=list)

    # State changes that happened during this reflection
    state_changes: list[dict[str, str]] = field(default_factory=list)

    # Immune summary
    hp_before: int = 100
    hp_after: int = 100
    total_damage: int = 0
    total_healed: int = 0

    # Recommendations
    recommendations: list[str] = field(default_factory=list)

    @property
    def needs_attention(self) -> bool:
        """Does anything need human attention?"""
        return bool(self.critical or self.state_changes or self.recommendations)

    @property
    def all_quiet(self) -> bool:
        """Is everything boring and healthy?"""
        return not self.critical and not self.watch and not self.state_changes

    def render(self) -> str:
        """Render the refined report for human consumption."""
        lines = []
        lines.append("┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓")
        lines.append("┃ SINGULARITY [AE] — Reflected Audit              ┃")
        lines.append("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛")
        lines.append("")

        # State changes first — these are the INTERESTING events
        if self.state_changes:
            lines.append("  ⚡ State Changes:")
            for sc in self.state_changes:
                lines.append(f"    {sc['product']}:  {sc['from']} → {sc['to']}  ({sc['reason']})")
            lines.append("")

        # Critical — always show
        if self.critical:
            lines.append("  🔴 CRITICAL (needs attention):")
            for profile, report in self.critical:
                failed_checks = [c for c in report.checks if not c.passed]
                lines.append(f"    {profile.product_name}: {report.passed}/{len(report.checks)} passed")
                for c in failed_checks[:3]:
                    lines.append(f"      ✗ {c.name}: {c.message}")
                if len(failed_checks) > 3:
                    lines.append(f"      ... +{len(failed_checks) - 3} more failures")
            lines.append("")

        # Watch — show but brief
        if self.watch:
            lines.append("  👁️ WATCH (elevated monitoring):")
            for profile, report in self.watch:
                lines.append(f"    {profile.product_name}: {report.passed}/{len(report.checks)} passed "
                             f"(clean streak: {profile.consecutive_green})")
            lines.append("")

        # Active — show summary only
        if self.active:
            lines.append("  🟢 ACTIVE:")
            for profile, report in self.active:
                lines.append(f"    {profile.product_name}: {report.passed}/{len(report.checks)} passed")
            lines.append("")

        # Dormant — one line summary
        if self.dormant:
            names = [p.product_name for p, _ in self.dormant]
            lines.append(f"  💤 DORMANT ({len(self.dormant)}): {', '.join(names)}")
            lines.append("")

        # Unnecessary — suggest removal
        if self.unnecessary:
            lines.append("  ❓ UNNECESSARY (consider removing):")
            for profile, report in self.unnecessary:
                lines.append(f"    {profile.product_name}: "
                             f"no endpoints, no service — does this need a POA?")
            lines.append("")

        # Immune status
        lines.append(f"  ❤️ HP: {self.hp_after}/100")
        if self.total_damage:
            lines.append(f"  💥 Damage: -{self.total_damage}")
        if self.total_healed:
            lines.append(f"  💚 Healed: +{self.total_healed}")

        # Recommendations
        if self.recommendations:
            lines.append("")
            lines.append("  📋 Recommendations:")
            for r in self.recommendations:
                lines.append(f"    • {r}")

        return "\n".join(lines)


class Reflector:
    """
    Self-review layer. Receives raw audit results and produces a
    curated, refined view for human consumption.

    The Reflector:
    1. Maintains a profile for each POA (accumulated over time)
    2. Classifies POAs into operational states
    3. Adjusts monitoring frequency recommendations
    4. Filters noise (dormant products don't need screen time)
    5. Highlights signal (state changes, critical failures, patterns)

    Usage:
        reflector = Reflector(bridge=bridge)

        # Collect audits
        for config in active_poas:
            report = POARuntime.run_audit(config)
            reflector.ingest(config, report)

        # Reflect — this is where the magic happens
        result = reflector.reflect()

        # Show the refined view
        print(result.render())
    """

    # Thresholds
    DORMANT_AFTER_GREEN = 5     # consecutive green audits → dormant
    WATCH_AFTER_BLIP = 3        # green audits needed to go from WATCH → DORMANT
    CRITICAL_AFTER_RED = 2      # consecutive red audits → CRITICAL

    # Frequency adjustment
    DORMANT_INTERVAL_HOURS = 12.0    # dormant POAs: audit every 12h
    ACTIVE_INTERVAL_HOURS = 4.0      # active POAs: every 4h
    CRITICAL_INTERVAL_HOURS = 1.0    # critical POAs: every hour
    WATCH_INTERVAL_HOURS = 2.0       # watch POAs: every 2h

    def __init__(self, bridge: FeedbackBridge):
        self.bridge = bridge
        self.profiles: dict[str, POAProfile] = {}
        self._pending_reports: list[tuple[POAConfig, AuditReport]] = []
        self._pending_events: list[list[FeedbackEvent]] = []
        self.total_reflections: int = 0

    def ingest(self, config: POAConfig, report: AuditReport) -> list[FeedbackEvent]:
        """
        Ingest a single audit report.

        Routes it through the FeedbackBridge (immune damage/healing),
        then stores it for the reflect() pass.

        Returns the feedback events (for logging).
        """
        # Route through feedback bridge first — immune system feels the damage
        events = self.bridge.process_audit(report)

        # Ensure we have a profile
        pid = config.product_id
        if pid not in self.profiles:
            self.profiles[pid] = POAProfile(
                product_id=pid,
                product_name=config.product_name,
                has_endpoints=len(config.endpoints) > 0,
                has_service=bool(config.service_name),
                endpoint_count=len(config.endpoints),
            )

        # Update profile stats
        profile = self.profiles[pid]
        profile.total_audits += 1
        profile.last_audit_time = time.time()

        if report.overall_status == "green":
            profile.consecutive_green += 1
            profile.consecutive_red = 0
        else:
            profile.consecutive_red += 1
            profile.consecutive_green = 0
            profile.total_failures += 1
            profile.last_failure_time = time.time()

        dmg = sum(e.damage_dealt for e in events)
        profile.total_damage_caused += dmg

        # Store for reflect()
        self._pending_reports.append((config, report))
        self._pending_events.append(events)

        return events

    def reflect(self) -> ReflectionResult:
        """
        The moment of truth. Analyze all ingested audits, classify
        POAs, filter noise, produce a curated report.

        Call this AFTER ingesting all audit reports for this cycle.
        """
        self.total_reflections += 1
        now = time.time()

        result = ReflectionResult(
            hp_before=self.bridge.tracker.hp,
        )

        # ── Phase 1: Classify each POA ──
        # Only use the LATEST report per product (earlier ones were already
        # processed by the bridge during ingest)
        latest_reports: dict[str, tuple[POAConfig, AuditReport]] = {}
        for config, report in self._pending_reports:
            latest_reports[config.product_id] = (config, report)

        for pid, (config, report) in latest_reports.items():
            profile = self.profiles[pid]
            old_state = profile.state

            # Determine new state
            new_state = self._classify(profile, config, report)

            # Record state change
            if new_state != old_state:
                reason = self._change_reason(profile, old_state, new_state)
                profile.state = new_state
                profile.last_state_change = now
                result.state_changes.append({
                    "product": profile.product_name,
                    "product_id": pid,
                    "from": old_state.value,
                    "to": new_state.value,
                    "reason": reason,
                })
                logger.info(f"🪞 {profile.product_name}: {old_state.value} → {new_state.value} ({reason})")

            # Adjust frequency
            profile.recommended_interval_hours = self._recommended_interval(new_state)
            profile.suppressed = (new_state == POAState.DORMANT)

            # Bucket for output
            bucket = {
                POAState.CRITICAL: result.critical,
                POAState.ACTIVE: result.active,
                POAState.WATCH: result.watch,
                POAState.DORMANT: result.dormant,
                POAState.UNNECESSARY: result.unnecessary,
            }[new_state]
            bucket.append((profile, report))

        # ── Phase 2: Cross-product pattern analysis ──
        result.recommendations = self._analyze_patterns(result)

        # ── Phase 3: Immune summary ──
        result.hp_after = self.bridge.tracker.hp
        result.total_damage = max(0, result.hp_before - result.hp_after)

        # Trigger auditor heal after reflection if health is low
        if result.hp_after < 100 and not result.critical:
            # No active crises — safe to attempt heal
            self.bridge.force_audit()
            healed = self.bridge.tracker.hp - result.hp_after
            if healed > 0:
                result.total_healed = healed
                result.hp_after = self.bridge.tracker.hp

        # Clear pending
        self._pending_reports.clear()
        self._pending_events.clear()

        return result

    def _classify(
        self, profile: POAProfile, config: POAConfig, report: AuditReport
    ) -> POAState:
        """Classify a POA's operational state based on accumulated data."""

        # ── UNNECESSARY: no real monitoring surface ──
        if not profile.has_endpoints and not profile.has_service:
            # No endpoints AND no service = what are we even monitoring?
            # Unless it has disk/memory checks from shared infra
            meaningful_checks = [
                c for c in report.checks
                if not c.name.startswith("disk:") and not c.name.startswith("memory")
            ]
            if not meaningful_checks:
                return POAState.UNNECESSARY

        # ── CRITICAL: actively failing ──
        if profile.consecutive_red >= self.CRITICAL_AFTER_RED:
            return POAState.CRITICAL
        if report.overall_status == "red" and report.criticals > 0:
            return POAState.CRITICAL

        # ── WATCH: was dormant or watch, just had a blip ──
        if profile.state in (POAState.DORMANT, POAState.WATCH):
            if report.overall_status != "green":
                return POAState.WATCH
            # Still green — check if we can return to dormant
            if profile.state == POAState.WATCH:
                if profile.consecutive_green >= self.WATCH_AFTER_BLIP:
                    return POAState.DORMANT
                return POAState.WATCH

        # ── DORMANT: consistently healthy ──
        if profile.consecutive_green >= self.DORMANT_AFTER_GREEN:
            return POAState.DORMANT

        # ── ACTIVE: default ──
        return POAState.ACTIVE

    def _change_reason(
        self, profile: POAProfile, old: POAState, new: POAState
    ) -> str:
        """Human-readable reason for a state transition."""
        if new == POAState.DORMANT:
            return f"{profile.consecutive_green} consecutive clean audits"
        if new == POAState.CRITICAL:
            return f"{profile.consecutive_red} consecutive failures"
        if new == POAState.WATCH:
            return "failure detected after stable period"
        if new == POAState.UNNECESSARY:
            return "no endpoints or service to monitor"
        if new == POAState.ACTIVE and old == POAState.DORMANT:
            return "woke from dormancy — new failure pattern"
        if new == POAState.ACTIVE and old == POAState.CRITICAL:
            return "recovering — green audit after crisis"
        return "state reassessment"

    def _recommended_interval(self, state: POAState) -> float:
        """Recommended audit interval in hours."""
        return {
            POAState.CRITICAL: self.CRITICAL_INTERVAL_HOURS,
            POAState.WATCH: self.WATCH_INTERVAL_HOURS,
            POAState.ACTIVE: self.ACTIVE_INTERVAL_HOURS,
            POAState.DORMANT: self.DORMANT_INTERVAL_HOURS,
            POAState.UNNECESSARY: 24.0,  # once a day if they insist on keeping it
        }[state]

    def _analyze_patterns(self, result: ReflectionResult) -> list[str]:
        """Cross-product pattern analysis → recommendations."""
        recs = []

        # Pattern: too many critical POAs at once → systemic issue
        if len(result.critical) >= 3:
            recs.append(
                f"🚨 {len(result.critical)} products critical simultaneously — "
                f"likely systemic (network? DNS? host?), not individual product issues"
            )

        # Pattern: all dormant → nothing interesting happening
        total = (len(result.critical) + len(result.active) +
                 len(result.watch) + len(result.dormant) + len(result.unnecessary))
        if total > 0 and len(result.dormant) == total:
            recs.append(
                "💤 All products dormant — consider reducing audit frequency globally"
            )

        # Pattern: unnecessary POAs → suggest cleanup
        if result.unnecessary:
            names = [p.product_name for p, _ in result.unnecessary]
            recs.append(
                f"🧹 {len(result.unnecessary)} POA(s) have no monitoring surface: "
                f"{', '.join(names)}. Consider retiring or adding endpoints."
            )

        # Pattern: high damage in this cycle
        if result.total_damage > 30:
            recs.append(
                f"💥 Heavy damage this cycle ({result.total_damage} HP). "
                f"Investigate root cause before next audit."
            )

        # Pattern: product flapping (was dormant, now watch/critical, repeatedly)
        for pid, profile in self.profiles.items():
            if profile.total_audits > 10 and profile.total_failures > 3:
                fail_rate = profile.total_failures / profile.total_audits
                if fail_rate > 0.2:
                    recs.append(
                        f"⚡ {profile.product_name} has {fail_rate:.0%} failure rate "
                        f"over {profile.total_audits} audits — may need architectural fix"
                    )

        return recs

    def get_profile(self, product_id: str) -> Optional[POAProfile]:
        """Get the Reflector's profile for a product."""
        return self.profiles.get(product_id)

    def summary(self) -> dict[str, Any]:
        """Full Reflector state summary."""
        by_state = {}
        for state in POAState:
            products = [p.product_id for p in self.profiles.values() if p.state == state]
            if products:
                by_state[state.value] = products

        return {
            "total_reflections": self.total_reflections,
            "profiles": {pid: p.to_dict() for pid, p in self.profiles.items()},
            "by_state": by_state,
            "bridge_summary": self.bridge.summary(),
        }
