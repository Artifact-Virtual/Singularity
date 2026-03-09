"""
ATLAS — Board Reporter
========================

Generates enterprise-wide board reports and formats them for Discord.
Scheduled every 6 hours. Also produces on-demand status reports.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from .topology import (
    Module, ModuleType, ModuleStatus, TopologyGraph,
    Issue, IssueSeverity,
)

logger = logging.getLogger("singularity.atlas.board")


# Status icons
STATUS_ICONS = {
    ModuleStatus.HEALTHY: "✅",
    ModuleStatus.DEGRADED: "⚠️",
    ModuleStatus.DOWN: "🔴",
    ModuleStatus.STALE: "❓",
    ModuleStatus.GONE: "💀",
    ModuleStatus.UNKNOWN: "❔",
}

SEVERITY_ICONS = {
    IssueSeverity.CRITICAL: "🔴",
    IssueSeverity.HIGH: "🟠",
    IssueSeverity.MEDIUM: "🟡",
    IssueSeverity.LOW: "🔵",
    IssueSeverity.INFO: "ℹ️",
}

TYPE_LABELS = {
    ModuleType.AGENT: "Agents",
    ModuleType.GATEWAY: "Gateways",
    ModuleType.SERVICE: "Services",
    ModuleType.DAEMON: "Daemons",
    ModuleType.INFRASTRUCTURE: "Infrastructure",
    ModuleType.SUPPORT: "Support",
    ModuleType.UNKNOWN: "Other",
}


class BoardReporter:
    """Generates formatted board reports from the topology graph."""

    def __init__(self, graph: TopologyGraph):
        self.graph = graph

    def generate_board_report(
        self,
        issues: list[Issue] | None = None,
        actions_taken: int = 0,
        actions_failed: int = 0,
    ) -> str:
        """Generate the full board report for Discord."""
        now = datetime.datetime.now(datetime.timezone.utc)
        time_str = now.strftime("%Y-%m-%d %H:%M UTC")
        summary = self.graph.summary()
        active = self.graph.get_active_modules()

        lines = [
            "```",
            "══════════════════════════════════════",
            f"    ATLAS BOARD REPORT — {now.strftime('%H:%M')}",
            "══════════════════════════════════════",
        ]

        # Module counts by status
        by_status = summary.get("by_status", {})
        healthy = by_status.get("healthy", 0)
        degraded = by_status.get("degraded", 0)
        down = by_status.get("down", 0)
        total = summary.get("total_modules", 0)

        lines.append(f"  Modules: {total} tracked ({healthy} healthy, {degraded} degraded, {down} down)")

        # By machine
        by_machine = summary.get("by_machine", {})
        machine_parts = [f"{m}: {c}" for m, c in sorted(by_machine.items())]
        lines.append(f"  Machines: {len(by_machine)} ({', '.join(machine_parts)})")

        lines.append("")

        # Module listing by type
        by_type: dict[ModuleType, list[Module]] = {}
        for mod in active:
            if mod.type not in by_type:
                by_type[mod.type] = []
            by_type[mod.type].append(mod)

        # Display order
        type_order = [
            ModuleType.AGENT, ModuleType.GATEWAY, ModuleType.SERVICE,
            ModuleType.DAEMON, ModuleType.INFRASTRUCTURE,
            ModuleType.SUPPORT, ModuleType.UNKNOWN,
        ]

        for mod_type in type_order:
            mods = by_type.get(mod_type, [])
            if not mods:
                continue
            label = TYPE_LABELS.get(mod_type, mod_type.value)
            lines.append(f"  {label}:")
            for mod in sorted(mods, key=lambda m: m.name):
                icon = STATUS_ICONS.get(mod.status, "❔")
                extra = ""
                rss = mod.resources.get("rss_mb", mod.process.rss_mb)
                if rss and rss > 100:
                    extra += f" [{rss:.0f}MB]"
                if mod.machine != "dragonfly":
                    extra += f" ({mod.machine})"
                if mod.health_result.healthy:
                    extra += f" {mod.health_result.latency_ms:.0f}ms"
                lines.append(f"    {icon} {mod.name}{extra}")
            lines.append("")

        # Issues summary
        if issues:
            crit = sum(1 for i in issues if i.severity == IssueSeverity.CRITICAL)
            high = sum(1 for i in issues if i.severity == IssueSeverity.HIGH)
            med = sum(1 for i in issues if i.severity == IssueSeverity.MEDIUM)
            low = sum(1 for i in issues if i.severity in (IssueSeverity.LOW, IssueSeverity.INFO))

            lines.append("  Issues:")
            if crit:
                lines.append(f"    🔴 {crit} critical")
            if high:
                lines.append(f"    🟠 {high} high")
            if med:
                lines.append(f"    🟡 {med} medium")
            if low:
                lines.append(f"    🔵 {low} low/info")

            # List critical and high issues
            serious = [i for i in issues if i.severity in (IssueSeverity.CRITICAL, IssueSeverity.HIGH)]
            if serious:
                lines.append("")
                lines.append("  Findings:")
                for issue in serious[:10]:  # Cap at 10
                    icon = SEVERITY_ICONS.get(issue.severity, "•")
                    fixed = " [AUTO-FIXED]" if issue.auto_fixed else ""
                    lines.append(f"    {icon} {issue.title}{fixed}")
            lines.append("")

        # Auto-remediation summary
        if actions_taken or actions_failed:
            lines.append(f"  Auto-fixes: {actions_taken} applied, {actions_failed} failed")
            lines.append("")

        lines.append(f"  Report: {time_str}")
        lines.append("══════════════════════════════════════")
        lines.append("```")

        return "\n".join(lines)

    def generate_status_summary(self) -> str:
        """Generate a compact status line for quick queries."""
        summary = self.graph.summary()
        by_status = summary.get("by_status", {})
        total = summary.get("total_modules", 0)
        healthy = by_status.get("healthy", 0)
        degraded = by_status.get("degraded", 0)
        down = by_status.get("down", 0)

        if down:
            return f"ATLAS: {total} modules — {healthy} healthy, {degraded} degraded, **{down} DOWN**"
        elif degraded:
            return f"ATLAS: {total} modules — {healthy} healthy, {degraded} degraded"
        else:
            return f"ATLAS: {total} modules — all healthy"

    def generate_module_detail(self, module_id: str) -> str:
        """Generate detailed report for a single module."""
        mod = self.graph.get_module(module_id)
        if not mod:
            return f"Module '{module_id}' not found in topology."

        lines = [f"**{mod.name}** ({mod.type.value})", ""]
        lines.append(f"Status: {STATUS_ICONS.get(mod.status, '?')} {mod.status.value}")
        lines.append(f"Machine: {mod.machine}")

        if mod.process.pid:
            lines.append(f"PID: {mod.process.pid}")
            lines.append(f"Command: `{mod.process.command[:100]}`")

        if mod.service.unit_name:
            lines.append(f"Service: {mod.service.unit_name} ({'active' if mod.service.active else 'inactive'}, {'enabled' if mod.service.enabled else 'disabled'})")

        if mod.ports:
            port_str = ", ".join(f"{p.port}/{p.proto}" for p in mod.ports)
            lines.append(f"Ports: {port_str}")

        if mod.public_urls:
            lines.append(f"Public: {', '.join(mod.public_urls)}")

        if mod.health_result.checked_at:
            h = mod.health_result
            lines.append(f"Health: {'✅' if h.healthy else '❌'} {h.url} → {h.status_code} ({h.latency_ms:.0f}ms)")

        rss = mod.resources.get("rss_mb", mod.process.rss_mb)
        if rss:
            lines.append(f"RAM: {rss:.0f}MB")

        if mod.dependencies:
            lines.append(f"Dependencies: {', '.join(mod.dependencies)}")

        dependents = self.graph.get_dependents(mod.id)
        if dependents:
            lines.append(f"Depended on by: {', '.join(dependents)}")

        if mod.issues:
            lines.append("")
            lines.append("Issues:")
            for issue in mod.issues:
                icon = SEVERITY_ICONS.get(issue.severity, "•")
                lines.append(f"  {icon} {issue.title}")

        return "\n".join(lines)

    def generate_topology_view(self) -> str:
        """Generate a text-based topology map."""
        active = self.graph.get_active_modules()
        by_machine: dict[str, list[Module]] = {}
        for mod in active:
            if mod.machine not in by_machine:
                by_machine[mod.machine] = []
            by_machine[mod.machine].append(mod)

        lines = ["**Enterprise Topology**", ""]

        for machine, mods in sorted(by_machine.items()):
            lines.append(f"**{machine.upper()}**")
            for mod in sorted(mods, key=lambda m: (m.type.value, m.name)):
                icon = STATUS_ICONS.get(mod.status, "?")
                ports = ", ".join(f":{p.port}" for p in mod.ports) if mod.ports else ""
                lines.append(f"  {icon} {mod.name} [{mod.type.value}] {ports}")
            lines.append("")

        # Show edges
        if self.graph.edges:
            lines.append("**Connections:**")
            for edge in self.graph.edges[:20]:
                lines.append(f"  {edge.source} → {edge.target} ({edge.type.value})")

        return "\n".join(lines)
