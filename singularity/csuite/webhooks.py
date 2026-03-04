"""
CSUITE — Webhook Reporter
==============================

Posts C-Suite dispatch results to Discord channels via webhooks.

Each executive has a dedicated channel:
    #cto   — CTO full reports
    #coo   — COO full reports
    #cfo   — CFO full reports
    #ciso  — CISO full reports
    #dispatch — Summary of all dispatches

Webhook URLs are loaded from the deployment state file:
    .singularity/deployments/<guild_id>.json

These channels are read-only for humans — only webhooks post there.
This ensures clean, auditable executive output without noise.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiohttp

from .executive import TaskResult, TaskStatus

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .coordinator import DispatchResult

logger = logging.getLogger("singularity.csuite.webhooks")

# Role → webhook display config
ROLE_CONFIG = {
    "cto": {"name": "CTO", "emoji": "🔧", "color": 0x3498DB},   # Blue
    "coo": {"name": "COO", "emoji": "📋", "color": 0x2ECC71},   # Green
    "cfo": {"name": "CFO", "emoji": "💰", "color": 0xF1C40F},   # Gold
    "ciso": {"name": "CISO", "emoji": "🔒", "color": 0xE74C3C}, # Red
}


class WebhookReporter:
    """
    Posts C-Suite results to Discord via webhooks.
    
    Loads webhook URLs on init from the deployment state file.
    After each dispatch, posts:
        - Full report to the executive's dedicated channel
        - Summary to #dispatch
    """

    def __init__(self, sg_dir: str | Path | None = None):
        self._webhooks: dict[str, str] = {}  # channel_name → webhook_url
        self._loaded = False
        self._sg_dir = Path(sg_dir) if sg_dir else None

    async def initialize(self, sg_dir: str | Path | None = None) -> bool:
        """Load webhook URLs from deployment state."""
        if sg_dir:
            self._sg_dir = Path(sg_dir)
        
        if not self._sg_dir:
            # Try default locations
            candidates = [
                Path.home() / "workspace" / "singularity" / ".singularity",
                Path.home() / "workspace" / ".singularity",
            ]
            for c in candidates:
                if (c / "deployments").exists():
                    self._sg_dir = c
                    break
        
        if not self._sg_dir:
            logger.warning("No .singularity directory found — webhooks disabled")
            return False

        deploy_dir = self._sg_dir / "deployments"
        if not deploy_dir.exists():
            logger.warning(f"No deployments directory at {deploy_dir}")
            return False

        # Load all deployment files, take the first with webhooks
        for f in sorted(deploy_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                wh = data.get("webhooks", {})
                if wh:
                    self._webhooks.update(wh)
                    logger.info(f"⚡ Loaded {len(wh)} webhook URLs from {f.name}")
            except Exception as e:
                logger.error(f"Failed to load webhooks from {f}: {e}")

        self._loaded = bool(self._webhooks)
        if self._loaded:
            logger.info(f"⚡ Webhook reporter ready — {len(self._webhooks)} hooks: {list(self._webhooks.keys())}")
        else:
            logger.warning("No webhook URLs found in deployment files")
        
        return self._loaded

    @property
    def is_ready(self) -> bool:
        return self._loaded and bool(self._webhooks)

    async def report_dispatch(self, result: DispatchResult, task_description: str) -> None:
        """
        Post a complete dispatch result to Discord.
        
        - Each executive's result → their dedicated channel (full report)
        - Summary → #dispatch channel
        """
        if not self.is_ready:
            logger.debug("Webhook reporter not ready — skipping")
            return

        # Post individual results to each executive's channel
        for task in result.tasks:
            await self._post_executive_report(task, result.dispatch_id, task_description)

        # Post summary to #dispatch
        await self._post_dispatch_summary(result, task_description)

    def _safe_field(self, value: str, max_len: int = 1024) -> str:
        """Ensure a field value is non-empty and within Discord limits."""
        if not value or not value.strip():
            return "—"
        text = value.strip()[:max_len]
        if len(value.strip()) > max_len:
            text = text[:max_len - 15] + "\n… (truncated)"
        return text

    async def _post_executive_report(
        self,
        task: TaskResult,
        dispatch_id: str,
        task_description: str,
    ) -> None:
        """Post a full report to an executive's dedicated channel."""
        role_name = task.role.value.lower()
        webhook_url = self._webhooks.get(role_name)
        if not webhook_url:
            logger.debug(f"No webhook for role '{role_name}' — skipping")
            return

        config = ROLE_CONFIG.get(role_name, {"name": role_name.upper(), "emoji": "📌", "color": 0x95A5A6})
        status_icon = "✅" if task.status == TaskStatus.COMPLETE else "❌" if task.status == TaskStatus.FAILED else "⏱️"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # Build Discord embed fields (all values must be non-empty)
        fields = [
            {
                "name": "📝 Task",
                "value": self._safe_field(task_description),
                "inline": False,
            },
            {
                "name": "📊 Status",
                "value": f"`{task.status.value}` — {task.iterations_used} iterations, {task.duration_seconds:.1f}s",
                "inline": True,
            },
        ]

        # Add response — use description if response is too long for embed
        if task.response:
            fields.append({
                "name": "📄 Report",
                "value": self._safe_field(task.response),
                "inline": False,
            })

        # Add findings
        if task.findings:
            findings_text = "\n".join(f"• {f}" for f in task.findings[:10])
            if len(task.findings) > 10:
                findings_text += f"\n… and {len(task.findings) - 10} more"
            fields.append({
                "name": "🔍 Findings",
                "value": self._safe_field(findings_text),
                "inline": False,
            })

        # Add actions
        if task.actions:
            actions_text = "\n".join(f"• {a}" for a in task.actions[:8])
            if len(task.actions) > 8:
                actions_text += f"\n… and {len(task.actions) - 8} more"
            fields.append({
                "name": "⚡ Actions",
                "value": self._safe_field(actions_text),
                "inline": False,
            })

        # Add files modified
        if task.files_modified:
            files_text = "\n".join(f"`{f}`" for f in task.files_modified[:5])
            if len(task.files_modified) > 5:
                files_text += f"\n… and {len(task.files_modified) - 5} more"
            fields.append({
                "name": "📁 Files Modified",
                "value": self._safe_field(files_text),
                "inline": False,
            })

        # Add error
        if task.error:
            fields.append({
                "name": "⚠️ Error",
                "value": self._safe_field(f"```\n{task.error[:900]}\n```"),
                "inline": False,
            })

        # Enforce Discord total embed limit (6000 chars)
        total = 0
        capped_fields = []
        for f in fields:
            field_len = len(f["name"]) + len(f["value"])
            if total + field_len > 5500:
                break
            capped_fields.append(f)
            total += field_len

        embed = {
            "title": f"{status_icon} {config['name']} — Dispatch {dispatch_id[:8]}",
            "color": config["color"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fields": capped_fields,
            "footer": {
                "text": f"Singularity C-Suite • {now}",
            },
        }

        payload = {
            "username": f"Singularity {config['name']}",
            "embeds": [embed],
        }

        await self._send_webhook(webhook_url, payload, f"#{role_name}")

    async def _post_dispatch_summary(self, result: DispatchResult, task_description: str) -> None:
        """Post a summary embed to #dispatch."""
        webhook_url = self._webhooks.get("dispatch")
        if not webhook_url:
            logger.debug("No webhook for #dispatch — skipping")
            return

        overall_icon = "✅" if result.all_succeeded else "⚠️"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # Build task summary lines
        task_lines = []
        for t in result.tasks:
            config = ROLE_CONFIG.get(t.role.value.lower(), {"emoji": "📌"})
            icon = "✅" if t.status == TaskStatus.COMPLETE else "❌" if t.status == TaskStatus.FAILED else "⏱️"
            one_line = (t.response or "")[:100].replace("\n", " ").strip() if t.response else (t.error or "")[:100] if t.error else "—"
            if not one_line:
                one_line = "—"
            if len(one_line) > 100:
                one_line = one_line[:97] + "..."
            task_lines.append(f"{icon} **{t.role.value.upper()}**: {t.status.value} ({t.duration_seconds:.1f}s) — {one_line}")

        description = "\n".join(task_lines) or "—"

        embed = {
            "title": f"{overall_icon} Dispatch {result.dispatch_id[:8]} — {len(result.tasks)} task(s)",
            "color": 0x2ECC71 if result.all_succeeded else 0xE74C3C,
            "description": self._safe_field(description, 4000),
            "fields": [
                {
                    "name": "📝 Task",
                    "value": self._safe_field(task_description, 512),
                    "inline": False,
                },
                {
                    "name": "⏱️ Duration",
                    "value": f"{result.duration:.1f}s",
                    "inline": True,
                },
                {
                    "name": "📊 Result",
                    "value": f"{len([t for t in result.tasks if t.status == TaskStatus.COMPLETE])}/{len(result.tasks)} succeeded",
                    "inline": True,
                },
            ],
            "footer": {
                "text": f"Singularity Dispatch • {now}",
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if result.escalations:
            embed["fields"].append({
                "name": "⚠️ Escalations",
                "value": str(len(result.escalations)),
                "inline": True,
            })

        payload = {
            "username": "Singularity Dispatch",
            "embeds": [embed],
        }

        await self._send_webhook(webhook_url, payload, "#dispatch")

    async def _send_webhook(self, url: str, payload: dict, channel_label: str) -> bool:
        """POST a webhook payload to Discord."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status in (200, 204):
                        logger.info(f"✅ Webhook posted to {channel_label}")
                        return True
                    else:
                        body = await resp.text()
                        logger.error(f"❌ Webhook {channel_label} failed: HTTP {resp.status} — {body[:200]}")
                        return False
        except Exception as e:
            logger.error(f"❌ Webhook {channel_label} error: {e}")
            return False
