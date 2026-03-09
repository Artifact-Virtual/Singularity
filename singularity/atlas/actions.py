"""
ATLAS — Actions (Auto-Remediation)
====================================

Executes safe auto-fix actions identified by the Coach Engine.
Logs all actions taken. Escalates failures.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from pathlib import Path
from typing import Any

from .topology import Issue, IssueSeverity

logger = logging.getLogger("singularity.atlas.actions")


class ActionLog:
    """Records all auto-remediation actions taken."""

    def __init__(self, log_path: Path | None = None):
        self._log_path = log_path
        self._actions: list[dict] = []
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, issue: Issue, success: bool, output: str = "") -> None:
        entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "issue_id": issue.id,
            "module": issue.module_id,
            "title": issue.title,
            "action": issue.fix_action,
            "success": success,
            "output": output[:500],
        }
        self._actions.append(entry)

        # Persist
        if self._log_path:
            try:
                with open(self._log_path, "a") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception as e:
                logger.debug(f"Suppressed action log write: {e}")

    def recent(self, n: int = 20) -> list[dict]:
        return self._actions[-n:]


class ActionExecutor:
    """
    Executes auto-fix actions from Coach Engine issues.

    Only executes issues marked auto_fixable=True.
    Logs everything. Reports failures for escalation.
    """

    # Actions that are ALWAYS safe to auto-execute
    SAFE_PATTERNS = [
        "systemctl --user restart",
        "systemctl restart",
        "chmod 600",
        "truncate -s 0",
    ]

    def __init__(self, log_path: Path | None = None):
        self.log = ActionLog(log_path)

    async def execute_safe_fixes(self, issues: list[Issue]) -> tuple[int, int]:
        """
        Execute all auto-fixable issues. Returns (success_count, fail_count).
        """
        fixable = [i for i in issues if i.auto_fixable and i.fix_action and not i.auto_fixed]
        if not fixable:
            return 0, 0

        success = 0
        failed = 0

        for issue in fixable:
            if not self._is_safe(issue.fix_action):
                logger.warning(f"ATLAS: Refusing unsafe action: {issue.fix_action}")
                continue

            try:
                proc = await asyncio.create_subprocess_shell(
                    issue.fix_action,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                output = (stdout.decode(errors="replace") + stderr.decode(errors="replace")).strip()

                if proc.returncode == 0:
                    issue.auto_fixed = True
                    issue.resolved_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    self.log.record(issue, True, output)
                    success += 1
                    logger.info(f"ATLAS: Auto-fixed: {issue.title} via [{issue.fix_action}]")
                else:
                    self.log.record(issue, False, output)
                    failed += 1
                    logger.warning(f"ATLAS: Auto-fix FAILED: {issue.title} → {output[:200]}")
            except asyncio.TimeoutError:
                self.log.record(issue, False, "Timeout after 30s")
                failed += 1
            except Exception as e:
                self.log.record(issue, False, str(e))
                failed += 1

        return success, failed

    def _is_safe(self, action: str) -> bool:
        """Check if an action matches safe patterns."""
        return any(action.startswith(pattern) for pattern in self.SAFE_PATTERNS)
