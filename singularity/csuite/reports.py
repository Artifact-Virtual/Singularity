"""
CSUITE — Report Aggregation & Delivery
==========================================

Takes TaskResults from executives and formats them for:
    - AVA (internal event bus)
    - Ali (WhatsApp/Discord message)
    - File persistence (markdown reports)
    - Dashboard (structured JSON)

Reports can be:
    - Individual: single executive, single task
    - Aggregate: multiple executives, coordinated dispatch
    - Standing: periodic automated reports
    - Escalation: failure/timeout alerts
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .executive import TaskResult, TaskStatus
from .coordinator import DispatchResult
from .roles import RoleType

logger = logging.getLogger("singularity.csuite.reports")


class ReportFormatter:
    """Format executive reports for different destinations."""

    @staticmethod
    def to_markdown(result: DispatchResult) -> str:
        """Format a dispatch result as markdown."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"# C-Suite Dispatch Report",
            f"**ID:** {result.dispatch_id}  ",
            f"**Time:** {now}  ",
            f"**Duration:** {result.duration:.1f}s  ",
            f"**Status:** {'✅ All Succeeded' if result.all_succeeded else '⚠️ Partial/Failed'}  ",
            "",
            "---",
            "",
        ]

        for task in result.tasks:
            icon = {
                TaskStatus.COMPLETE: "✅",
                TaskStatus.FAILED: "❌",
                TaskStatus.TIMEOUT: "⏱️",
                TaskStatus.BLOCKED: "🔒",
                TaskStatus.ESCALATED: "⚠️",
                TaskStatus.PENDING: "⏳",
            }.get(task.status, "❓")

            lines.append(f"## {icon} {task.role.value.upper()} — {task.status.value}")
            lines.append(f"*{task.iterations_used} iterations, {task.duration_seconds:.1f}s*")
            lines.append("")

            if task.response:
                lines.append(task.response)
                lines.append("")

            if task.findings:
                lines.append("### Findings")
                for f in task.findings:
                    lines.append(f"- {f}")
                lines.append("")

            if task.actions:
                lines.append("### Actions Taken")
                for a in task.actions[:10]:  # cap at 10
                    lines.append(f"- {a}")
                if len(task.actions) > 10:
                    lines.append(f"- ... and {len(task.actions) - 10} more")
                lines.append("")

            if task.files_modified:
                lines.append("### Files Modified")
                for f in task.files_modified:
                    lines.append(f"- `{f}`")
                lines.append("")

            if task.error:
                lines.append(f"### Error")
                lines.append(f"```\n{task.error}\n```")
                lines.append("")

            lines.append("---")
            lines.append("")

        if result.escalations:
            lines.append("## ⚠️ Escalations")
            for esc in result.escalations:
                lines.append(f"- {json.dumps(esc)}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def to_chat_message(result: DispatchResult) -> str:
        """Format for WhatsApp/Discord — compact, no markdown tables."""
        lines = [f"📋 *C-Suite Report* — {result.dispatch_id}"]

        for task in result.tasks:
            icon = "✅" if task.status == TaskStatus.COMPLETE else "❌" if task.status == TaskStatus.FAILED else "⏱️"
            lines.append(f"{icon} *{task.role.value.upper()}*: {task.status.value} ({task.duration_seconds:.0f}s)")

            # Include brief response (first 200 chars)
            if task.response:
                brief = task.response[:200].strip()
                if len(task.response) > 200:
                    brief += "..."
                lines.append(f"  → {brief}")

            if task.error:
                lines.append(f"  ⚠️ {task.error[:100]}")

        lines.append(f"\n⏱️ Total: {result.duration:.1f}s")
        return "\n".join(lines)

    @staticmethod
    def to_individual_message(result: TaskResult) -> str:
        """Format a single executive's result for messaging."""
        icon = "✅" if result.status == TaskStatus.COMPLETE else "❌"
        lines = [f"{icon} *{result.role.value.upper()}* — {result.status.value}"]

        if result.response:
            lines.append(result.response[:500])

        if result.error:
            lines.append(f"\n⚠️ Error: {result.error[:200]}")

        lines.append(f"\n_{result.iterations_used} iterations, {result.duration_seconds:.1f}s_")
        return "\n".join(lines)


class ReportStore:
    """Persist and retrieve reports."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.reports_dir = workspace / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def save(self, result: DispatchResult) -> Path:
        """Save a dispatch result as markdown + JSON."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        base = f"{ts}-{result.dispatch_id}"

        # Markdown
        md_path = self.reports_dir / f"{base}.md"
        md_path.write_text(ReportFormatter.to_markdown(result))

        # JSON
        json_path = self.reports_dir / f"{base}.json"
        json_path.write_text(json.dumps(result.to_dict(), indent=2))

        logger.info(f"Report saved: {md_path}")
        return md_path

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent reports as parsed JSON."""
        json_files = sorted(self.reports_dir.glob("*.json"), reverse=True)[:limit]
        reports = []
        for f in json_files:
            try:
                reports.append(json.loads(f.read_text()))
            except Exception:
                continue
        return reports

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Simple keyword search across reports."""
        query_lower = query.lower()
        results = []
        for f in sorted(self.reports_dir.glob("*.json"), reverse=True):
            try:
                text = f.read_text()
                if query_lower in text.lower():
                    results.append(json.loads(text))
                    if len(results) >= limit:
                        break
            except Exception:
                continue
        return results
