"""
CthulhOps — Dedicated Cthulu Trading Operations Agent
======================================================

Autonomous monitoring, journaling, and alerting for the Cthulu
trading system. Runs as scheduled PULSE jobs inside Singularity.

Responsibilities:
- Bridge health monitoring (every 5 min)
- Position tracking + P&L journaling (every 15 min)
- Trade rationale logging (when new trades detected)
- Daily summary generation (10 PM PKT / 17:00 UTC)
- Alert escalation to Ali (on critical events)
- Self-healing: restart bridge/webhook if down

NOT responsible for:
- Code changes to Cthulu
- Strategy modifications
- K9 brain configuration
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import aiohttp

logger = logging.getLogger("singularity.csuite.cthulu_ops")

# ── Constants ────────────────────────────────────────────────────────

WEBHOOK_BASE = "http://127.0.0.1:9002"
COPILOT_URL = "http://127.0.0.1:3000/v1/chat/completions"
PKT = timezone(timedelta(hours=5))  # Asia/Karachi

# Discord webhook for alerts (heartbeat-monitor style)
DISCORD_WEBHOOK = (
    "https://discord.com/api/webhooks/1460675818245066833/"
    "RFpqNaTJfPm_76xUhvGBWbg-QQglsEm9shyLEFSd8417FlGwzQ96KekksixqAefFrG_d"
)
ALI_MENTION = "<@193011943382974466>"

# Discord channels
CHANNEL_AVA = "1475929150488449138"
CHANNEL_HEARTBEAT = "1478862319785349292"

# Note-to-self prompt — generates clean 1-2 line observations
NOTE_PROMPT = (
    "You are CthulhOps, a trading operations monitor. "
    "Given the market data below, write exactly 1-2 sentences of observation. "
    "Be specific. Note patterns, risks, or opportunities. No filler. No stories."
)

# Paths
JOURNAL_DIR = Path(__file__).resolve().parent.parent.parent / ".core" / "reports" / "cthulu"
K9_LOG = Path("/home/adam/workspace/projects/cthulu-daemon/logs/k9_brain.log")
CTHULU_TRADES_LOG = Path("/home/adam/workspace/memory/cthulu-trades.log")


# ── Helpers ──────────────────────────────────────────────────────────

def _now_pkt() -> datetime:
    """Current time in PKT."""
    return datetime.now(PKT)


def _fmt_pkt(dt: datetime | None = None) -> str:
    """Format datetime as HH:MM PKT."""
    dt = dt or _now_pkt()
    return dt.strftime("%H:%M PKT")


def _journal_path(dt: datetime | None = None) -> Path:
    """Get today's journal file path."""
    dt = dt or _now_pkt()
    return JOURNAL_DIR / f"trades-{dt.strftime('%Y-%m-%d')}.md"


def _pnl_icon(profit: float) -> str:
    return "🟢" if profit >= 0 else "🔴"


def _direction(pos_type: int) -> str:
    return "Long" if pos_type == 0 else "Short"


# ── CthulhOps Agent ─────────────────────────────────────────────────

class CthulhOps:
    """
    Cthulu Operational Agent — dedicated trading ops monitor.
    
    Runs as scheduled PULSE jobs, not a standalone process.
    Consumes webhook API at localhost:9002 for all trading data.
    """

    def __init__(self, bus=None, workspace: str = ""):
        self.bus = bus
        self.workspace = workspace or "/home/adam/workspace"
        
        # State tracking (in-memory, rebuilt on restart)
        self._last_positions: dict[int, dict] = {}  # ticket → position data
        self._last_account: dict = {}
        self._last_health_ok: bool = True
        self._last_bridge_ok: bool = True
        self._consecutive_failures: int = 0
        self._boot_time = time.monotonic()
        
        # Ensure journal directory exists
        JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
        
        logger.info("🐙 CthulhOps initialized")

    # ── HTTP Helpers ─────────────────────────────────────────────

    async def _get_json(self, path: str, timeout: float = 5.0) -> Optional[dict]:
        """GET JSON from webhook server. Returns None on failure."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{WEBHOOK_BASE}{path}",
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    logger.warning(f"Webhook {path} returned {resp.status}")
                    return None
        except Exception as e:
            logger.warning(f"Webhook {path} failed: {e}")
            return None

    # ── Health Check (every 5 min) ───────────────────────────────

    async def check_health(self) -> dict:
        """
        Full health check: webhook, K9 brain, bridge on Victus, tick freshness.
        Returns status dict for logging/alerting.
        """
        status = {
            "timestamp": _now_pkt().isoformat(),
            "webhook": False,
            "k9_brain": False,
            "bridge": False,
            "mt5": False,
            "tick_fresh": False,
            "daemon": False,
            "alerts": [],
        }

        # 1. Webhook server
        health = await self._get_json("/health")
        if health:
            status["webhook"] = True
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
            status["alerts"].append("Webhook server DOWN")
            if self._consecutive_failures >= 3:
                await self._try_restart_webhook()
                status["alerts"].append("Attempted webhook restart")

        # 2. K9 Brain process
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["pgrep", "-f", "k9.live"],
                    capture_output=True, timeout=5,
                ),
            )
            status["k9_brain"] = result.returncode == 0
            if not status["k9_brain"]:
                status["alerts"].append("K9 brain process NOT running")
        except Exception as e:
            logger.warning(f"K9 brain check failed: {e}")

        # 3. Cthulu daemon service
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["systemctl", "--user", "is-active", "cthulu-daemon.service"],
                    capture_output=True, text=True, timeout=5,
                ),
            )
            status["daemon"] = result.stdout.strip() == "active"
            if not status["daemon"]:
                status["alerts"].append("cthulu-daemon.service inactive")
        except Exception as e:
            logger.warning(f"Daemon check failed: {e}")

        # 4. Bridge + MT5 on Victus
        victus_status = await self.check_victus()
        status["bridge"] = victus_status.get("bridge", False)
        status["mt5"] = victus_status.get("mt5", False)
        if not status["bridge"]:
            status["alerts"].append("Bridge DOWN on Victus")
        if not status["mt5"]:
            status["alerts"].append("MT5 terminal DOWN on Victus (needs GUI)")

        # 5. Tick freshness (BTC as canary)
        tick = await self._get_json("/latest_tick?symbol=BTCUSD%23")
        if tick:
            tick_time = tick.get("time", 0)
            if tick_time:
                age = time.time() - float(tick_time)
                status["tick_fresh"] = age < 120  # 2 min tolerance
                if not status["tick_fresh"]:
                    status["alerts"].append(f"Stale ticks — BTCUSD# last tick {int(age)}s ago")
        else:
            status["alerts"].append("No tick data available")

        # Track state changes
        was_healthy = self._last_health_ok
        is_healthy = not status["alerts"]
        self._last_health_ok = is_healthy

        # Alert on state transitions
        if was_healthy and not is_healthy:
            await self.alert("warning", "🐙 Health degraded:\n" + "\n".join(f"• {a}" for a in status["alerts"]))
        elif not was_healthy and is_healthy:
            await self.alert("info", "🐙 All systems recovered ✅")

        # Critical alerts always escalate
        critical_alerts = [a for a in status["alerts"] if "DOWN" in a or "NOT running" in a]
        if critical_alerts and self._consecutive_failures >= 2:
            await self.alert("critical", "🚨 CTHULU CRITICAL:\n" + "\n".join(f"• {a}" for a in critical_alerts))

        return status

    # ── Victus Check ─────────────────────────────────────────────

    async def check_victus(self) -> dict:
        """Check bridge and MT5 on Victus via SSH."""
        result = {"bridge": False, "mt5": False, "error": None}

        try:
            # Check bridge (python process)
            proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=5", "victus",
                     'tasklist /FI "IMAGENAME eq python.exe" /NH'],
                    capture_output=True, text=True, timeout=10,
                ),
            )
            if proc.returncode == 0 and "python.exe" in proc.stdout:
                result["bridge"] = True
            elif proc.returncode != 0:
                # SSH failed — Victus unreachable
                result["error"] = "SSH to Victus failed"
                return result

            # Check MT5 terminal
            proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=5", "victus",
                     'tasklist /FI "IMAGENAME eq terminal64.exe" /NH'],
                    capture_output=True, text=True, timeout=10,
                ),
            )
            if proc.returncode == 0 and "terminal64.exe" in proc.stdout:
                result["mt5"] = True

        except subprocess.TimeoutExpired:
            result["error"] = "SSH timeout"
        except Exception as e:
            result["error"] = str(e)

        # Self-heal: try restarting bridge if down but MT5 is up
        if not result["bridge"] and result["mt5"] and not result.get("error"):
            await self._try_restart_bridge()

        self._last_bridge_ok = result["bridge"]
        return result

    # ── Position Check (every 15 min) ────────────────────────────

    async def check_positions(self) -> dict:
        """
        Fetch current positions and account, compare with last known state.
        Detect new trades, closed trades, significant P&L changes.
        Journals everything.
        """
        positions_data = await self._get_json("/positions")
        account_data = await self._get_json("/account")

        if not positions_data or not account_data:
            logger.warning("Could not fetch positions/account data")
            return {"error": "data_unavailable"}

        current_positions = {}
        for p in positions_data.get("positions", []):
            ticket = p.get("ticket", 0)
            if ticket:
                current_positions[ticket] = p

        # Detect new trades
        new_tickets = set(current_positions.keys()) - set(self._last_positions.keys())
        for ticket in new_tickets:
            pos = current_positions[ticket]
            await self.journal_trade(pos, "OPENED")
            logger.info(f"New trade detected: {pos.get('symbol')} {_direction(pos.get('type', 0))}")

        # Detect closed trades
        closed_tickets = set(self._last_positions.keys()) - set(current_positions.keys())
        for ticket in closed_tickets:
            pos = self._last_positions[ticket]
            await self.journal_trade(pos, "CLOSED")
            pnl = pos.get("profit", 0)
            await self.alert(
                "info",
                f"🐙 Trade closed: {pos.get('symbol')} {_direction(pos.get('type', 0))} "
                f"→ {_pnl_icon(pnl)} ${pnl:+.2f}",
            )

        # Build position summary for journal
        balance = account_data.get("balance", 0)
        equity = account_data.get("equity", 0)
        profit = account_data.get("profit", 0)
        margin_level = account_data.get("margin_level", 0)

        # Risk checks
        if balance > 0:
            drawdown_pct = (balance - equity) / balance * 100
            if drawdown_pct > 10:
                await self.alert("warning", f"⚠️ Drawdown alert: {drawdown_pct:.1f}%")
            if 0 < margin_level < 200:
                await self.alert("critical", f"🚨 MARGIN CRITICAL: {margin_level:.0f}%")
            elif 0 < margin_level < 500:
                await self.alert("warning", f"⚠️ Margin low: {margin_level:.0f}%")

        # Journal the position update
        await self._journal_position_update(account_data, current_positions)

        # Generate note-to-self observation
        note = await self._generate_note(
            f"Balance: ${balance:.2f}, Equity: ${equity:.2f}, P&L: ${profit:+.2f}, "
            f"Positions: {len(current_positions)}, "
            + ", ".join(
                f"{p.get('symbol')} {_direction(p.get('type',0))} ${p.get('profit',0):+.2f}"
                for p in current_positions.values()
            )
        )
        if note:
            path = _journal_path()
            self._append_journal(path, f"\n> 💭 {note}\n")

        # Post to Discord (clean summary, not verbose)
        discord_lines = [f"🐙 **{_fmt_pkt()}** | ${balance:.2f} | P&L: ${profit:+.2f}"]
        for p in current_positions.values():
            sym = p.get("symbol", "?")
            pnl = p.get("profit", 0)
            discord_lines.append(f"  {_pnl_icon(pnl)} {sym} {_direction(p.get('type',0))} ${pnl:+.2f}")
        if note:
            discord_lines.append(f"  💭 _{note}_")
        await self._post_discord_webhook("\n".join(discord_lines))

        # Update state
        self._last_positions = current_positions
        self._last_account = account_data

        return {
            "balance": balance,
            "equity": equity,
            "profit": profit,
            "positions": len(current_positions),
            "new_trades": len(new_tickets),
            "closed_trades": len(closed_tickets),
        }

    # ── Note-to-Self (via Copilot Proxy) ────────────────────────

    async def _generate_note(self, market_data: str) -> Optional[str]:
        """Generate a 1-2 sentence observation via copilot proxy.
        
        Clean, concise, reflective. Not a data dump — an insight.
        Returns None on failure (non-fatal).
        """
        try:
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": NOTE_PROMPT},
                    {"role": "user", "content": market_data},
                ],
                "max_tokens": 100,
                "temperature": 0.3,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    COPILOT_URL,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            note = choices[0].get("message", {}).get("content", "").strip()
                            if note and len(note) < 500:
                                return note
                    logger.debug(f"Copilot note generation returned {resp.status}")
                    return None
        except Exception as e:
            logger.debug(f"Note generation failed (non-fatal): {e}")
            return None

    # ── Journaling ───────────────────────────────────────────────

    async def journal_trade(self, trade_data: dict, event: str = "UPDATE") -> None:
        """Write a trade event to the journal file."""
        now = _now_pkt()
        path = _journal_path(now)

        symbol = trade_data.get("symbol", "?")
        direction = _direction(trade_data.get("type", 0))
        volume = trade_data.get("volume", 0)
        open_price = trade_data.get("price_open", 0)
        current_price = trade_data.get("price_current", open_price)
        profit = trade_data.get("profit", 0)
        sl = trade_data.get("sl", 0)
        tp = trade_data.get("tp", 0)

        entry = (
            f"\n## {_fmt_pkt(now)} — Trade {event}\n"
            f"- {_pnl_icon(profit)} **{symbol}** {direction} {volume} lots\n"
            f"- Open: {open_price} → Current: {current_price} → P&L: ${profit:+.2f}\n"
            f"- SL: {sl if sl > 0 else 'None'} | TP: {tp if tp > 0 else 'None'}\n"
        )

        self._append_journal(path, entry)
        logger.info(f"Journaled trade {event}: {symbol} {direction}")

    async def _journal_position_update(
        self, account: dict, positions: dict[int, dict]
    ) -> None:
        """Write periodic position snapshot to journal."""
        now = _now_pkt()
        path = _journal_path(now)

        balance = account.get("balance", 0)
        equity = account.get("equity", 0)
        profit = account.get("profit", 0)
        margin_level = account.get("margin_level", 0)

        lines = [
            f"\n## {_fmt_pkt(now)} — Position Update",
            f"Balance: ${balance:.2f} | Equity: ${equity:.2f} | "
            f"Unrealized: {_pnl_icon(profit)} ${profit:+.2f}"
            + (f" | Margin: {margin_level:.0f}%" if margin_level > 0 else ""),
        ]

        if positions:
            for ticket, p in positions.items():
                sym = p.get("symbol", "?")
                direction = _direction(p.get("type", 0))
                vol = p.get("volume", 0)
                op = p.get("price_open", 0)
                cp = p.get("price_current", 0)
                pnl = p.get("profit", 0)
                lines.append(
                    f"- {_pnl_icon(pnl)} {sym} {direction} {vol} @ {op} → {cp} "
                    f"(${pnl:+.2f})"
                )
        else:
            lines.append("- No open positions")

        # K9 signals from log (last scan line)
        k9_status = self._read_k9_last_scan()
        if k9_status:
            lines.append(f"K9: {k9_status}")

        lines.append("")
        self._append_journal(path, "\n".join(lines))

    def _append_journal(self, path: Path, content: str) -> None:
        """Append content to a journal file, creating header if new."""
        if not path.exists():
            header = (
                f"# 🐙 Cthulu Trading Journal — {_now_pkt().strftime('%Y-%m-%d')}\n"
                f"*Auto-generated by CthulhOps agent*\n"
            )
            path.write_text(header)
        with open(path, "a") as f:
            f.write(content)

    def _read_k9_last_scan(self) -> Optional[str]:
        """Read the last scan summary line from K9 brain log."""
        try:
            if not K9_LOG.exists():
                return None
            # Read last 10 lines, find the summary line (starts with #)
            result = subprocess.run(
                ["tail", "-10", str(K9_LOG)],
                capture_output=True, text=True, timeout=3,
            )
            for line in reversed(result.stdout.strip().split("\n")):
                line = line.strip()
                if line.startswith("#") and "|" in line:
                    # e.g.: # 263 [  97.1ms] $54.34 | GOLDm#: B/HOLD | BTCUSD#: D/HOLD ...
                    return line
            return None
        except Exception:
            return None

    # ── Daily Summary (10 PM PKT) ────────────────────────────────

    async def daily_summary(self) -> dict:
        """
        Generate and post daily P&L summary.
        Posts to Discord #ava channel via webhook.
        """
        account = await self._get_json("/account")
        positions_data = await self._get_json("/positions")

        if not account:
            await self.alert("warning", "🐙 Daily summary skipped — webhook not responding")
            return {"error": "no_data"}

        balance = account.get("balance", 0)
        equity = account.get("equity", 0)
        profit = account.get("profit", 0)
        margin_level = account.get("margin_level", 0)

        positions = (positions_data or {}).get("positions", [])

        lines = [
            "🐙 **Cthulu Daily Summary**",
            "",
            f"💰 Balance: ${balance:.2f}",
            f"📊 Equity: ${equity:.2f}",
            f"{_pnl_icon(profit)} P&L: ${profit:+.2f}",
        ]
        if margin_level > 0:
            lines.append(f"📐 Margin Level: {margin_level:.0f}%")

        lines.append("")

        if positions:
            lines.append(f"📋 **Open Positions ({len(positions)}):**")
            for p in positions:
                sym = p.get("symbol", "?")
                direction = _direction(p.get("type", 0)).upper()
                vol = p.get("volume", 0)
                op = p.get("price_open", 0)
                cp = p.get("price_current", 0)
                pnl = p.get("profit", 0)
                sl = p.get("sl", 0)
                tp = p.get("tp", 0)
                sl_str = f"SL:{sl:.1f}" if sl > 0 else "No SL"
                tp_str = f"TP:{tp:.1f}" if tp > 0 else "No TP"
                lines.append(
                    f"{_pnl_icon(pnl)} {sym} {direction} {vol} @ {op:.2f} → {cp:.2f} "
                    f"= ${pnl:+.2f} ({sl_str}, {tp_str})"
                )
        else:
            lines.append("No open positions.")

        # Drawdown check
        if balance > 0:
            dd = (balance - equity) / balance * 100
            if dd > 5:
                lines.extend(["", f"⚠️ Drawdown: {dd:.1f}%"])

        summary_text = "\n".join(lines)

        # Post to Discord via webhook
        await self._post_discord_webhook(summary_text)

        # Also journal it
        path = _journal_path()
        self._append_journal(path, f"\n## {_fmt_pkt()} — Daily Summary\n{summary_text}\n")

        logger.info("Daily summary posted")
        return {"balance": balance, "equity": equity, "profit": profit, "positions": len(positions)}

    # ── Alerting ─────────────────────────────────────────────────

    async def alert(self, level: str, message: str) -> None:
        """
        Post alert to Discord webhook.
        Levels: info, warning, critical
        Critical alerts tag Ali.
        """
        prefix = {
            "info": "ℹ️",
            "warning": "⚠️",
            "critical": f"🚨 {ALI_MENTION}",
        }.get(level, "")

        full_message = f"{prefix} {message}" if prefix else message

        await self._post_discord_webhook(full_message)

        # Also emit on bus for other subsystems
        if self.bus:
            await self.bus.emit("cthulu.alert", {
                "level": level,
                "message": message,
                "timestamp": _now_pkt().isoformat(),
            })

        logger.info(f"Alert [{level}]: {message[:80]}")

    async def _post_discord_webhook(self, content: str) -> bool:
        """Post a message to Discord via bus event (routed to Discord adapter)."""
        if self.bus:
            try:
                await self.bus.emit("cthulu.discord.send", {
                    "channel_id": CHANNEL_AVA,
                    "content": content[:2000],
                })
                return True
            except Exception as e:
                logger.debug(f"Bus emit for Discord failed: {e}")
        # Fallback: direct webhook (if available)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    DISCORD_WEBHOOK,
                    json={"content": content[:2000], "username": "🐙 CthulhOps"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status in (200, 204):
                        return True
                    return False
        except Exception as e:
            logger.error(f"Discord post failed: {e}")
            return False

    # ── Self-Healing ─────────────────────────────────────────────

    async def _try_restart_webhook(self) -> bool:
        """Attempt to restart the Cthulu webhook server."""
        logger.warning("Attempting webhook server restart...")
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["systemctl", "--user", "restart", "cthulu-daemon.service"],
                    capture_output=True, text=True, timeout=15,
                ),
            )
            if result.returncode == 0:
                await asyncio.sleep(3)  # Give it time to come up
                health = await self._get_json("/health")
                if health:
                    await self.alert("info", "🐙 Webhook server auto-restarted ✅")
                    return True
            logger.error(f"Webhook restart failed: {result.stderr}")
            return False
        except Exception as e:
            logger.error(f"Webhook restart exception: {e}")
            return False

    async def _try_restart_bridge(self) -> bool:
        """Attempt to restart the bridge on Victus via scheduled task."""
        logger.warning("Attempting bridge restart on Victus...")
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=5", "victus",
                     "schtasks /Run /TN CthulhuBridge"],
                    capture_output=True, text=True, timeout=15,
                ),
            )
            if result.returncode == 0:
                await asyncio.sleep(5)
                await self.alert("info", "🐙 Bridge restart attempted on Victus")
                return True
            return False
        except Exception as e:
            logger.error(f"Bridge restart failed: {e}")
            return False

    # ── Main Cycle (called by PULSE) ─────────────────────────────

    async def run_health_cycle(self) -> None:
        """Health check cycle — called every 5 minutes by PULSE."""
        try:
            status = await self.check_health()
            components = sum([
                status.get("webhook", False),
                status.get("k9_brain", False),
                status.get("bridge", False),
                status.get("daemon", False),
            ])
            logger.debug(f"Health: {components}/4 components OK")
        except Exception as e:
            logger.error(f"Health cycle error: {e}")

    async def run_position_cycle(self) -> None:
        """Position check cycle — called every 15 minutes by PULSE."""
        try:
            result = await self.check_positions()
            if "error" not in result:
                logger.debug(
                    f"Positions: {result.get('positions', 0)} open, "
                    f"balance ${result.get('balance', 0):.2f}"
                )
        except Exception as e:
            logger.error(f"Position cycle error: {e}")

    async def run_daily_summary(self) -> None:
        """Daily summary — called once at 17:00 UTC (10 PM PKT) by PULSE."""
        try:
            await self.daily_summary()
        except Exception as e:
            logger.error(f"Daily summary error: {e}")
            await self.alert("warning", f"🐙 Daily summary failed: {e}")
