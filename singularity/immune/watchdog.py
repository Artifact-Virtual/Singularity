"""
IMMUNE — Self-Healing & Recovery
===================================

Lightweight initial immune system:
- Subsystem watchdog (restarts crashed components)
- Failover coordination (voice provider switching)
- System vitals monitoring (disk, memory, CPU)
- Alert routing (notify admin on critical issues)

Full POA integration comes later.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from ..bus import EventBus

logger = logging.getLogger("singularity.immune")


# ── System Vitals ─────────────────────────────────────────────

@dataclass
class SystemVitals:
    """Point-in-time system resource snapshot."""
    disk_used_pct: float = 0.0
    disk_free_gb: float = 0.0
    memory_used_pct: float = 0.0
    memory_available_mb: float = 0.0
    load_average_1m: float = 0.0
    uptime_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)


def collect_vitals() -> SystemVitals:
    """Collect current system resource stats."""
    vitals = SystemVitals()
    
    try:
        # Disk (home partition)
        stat = os.statvfs(os.path.expanduser("~"))
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bavail * stat.f_frsize
        if total > 0:
            vitals.disk_used_pct = (1 - free / total) * 100
            vitals.disk_free_gb = free / (1024**3)
    except Exception:
        pass
    
    try:
        # Memory
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip().split()[0]
                    meminfo[key] = int(val)  # kB
            
            total = meminfo.get("MemTotal", 1)
            available = meminfo.get("MemAvailable", 0)
            vitals.memory_used_pct = (1 - available / total) * 100
            vitals.memory_available_mb = available / 1024
    except Exception:
        pass
    
    try:
        # Load average
        vitals.load_average_1m = os.getloadavg()[0]
    except Exception:
        pass
    
    try:
        # Uptime
        with open("/proc/uptime") as f:
            vitals.uptime_seconds = float(f.read().split()[0])
    except Exception:
        pass
    
    vitals.timestamp = time.time()
    return vitals


# ── Watchdog ──────────────────────────────────────────────────

class Watchdog:
    """
    Monitors subsystem health events and coordinates recovery.
    
    Listens to bus events from the health monitor and:
    1. Tracks degraded subsystems
    2. Coordinates failover (e.g., voice provider switching)
    3. Sends alerts on critical issues
    4. Monitors system vitals
    """
    
    def __init__(
        self,
        bus: EventBus,
        alert_chat_id: str | None = None,
        alert_channel: str = "discord",
        vitals_interval: float = 300.0,    # Check vitals every 5 min
        disk_warn_pct: float = 90.0,
        memory_warn_pct: float = 90.0,
    ):
        self.bus = bus
        self.alert_chat_id = alert_chat_id
        self.alert_channel = alert_channel
        self.vitals_interval = vitals_interval
        self.disk_warn_pct = disk_warn_pct
        self.memory_warn_pct = memory_warn_pct
        
        self._running = False
        self._vitals_task: asyncio.Task | None = None
        self._last_vitals: SystemVitals | None = None
        self._alert_count = 0
        self._recovery_log: list[dict] = []
    
    async def start(self) -> None:
        """Start watchdog monitoring."""
        if self._running:
            return
        self._running = True
        
        # Subscribe to health events
        self.bus.on("pulse.health.degraded")(self._on_degraded)
        self.bus.on("pulse.health.recovered")(self._on_recovered)
        self.bus.on("pulse.health.recovery_attempted")(self._on_recovery_attempted)
        
        # Start vitals monitoring
        self._vitals_task = asyncio.create_task(self._vitals_loop())
        
        logger.info("Watchdog started")
        await self.bus.emit("immune.watchdog.started", {})
    
    async def stop(self) -> None:
        """Stop watchdog."""
        self._running = False
        if self._vitals_task:
            self._vitals_task.cancel()
            try:
                await self._vitals_task
            except asyncio.CancelledError:
                pass
        logger.info("Watchdog stopped")
    
    def get_vitals(self) -> SystemVitals:
        """Get last collected vitals."""
        return self._last_vitals or collect_vitals()
    
    def get_recovery_log(self) -> list[dict]:
        """Get recovery attempt history."""
        return list(self._recovery_log)
    
    # ── Event Handlers ────────────────────────────────────────
    
    async def _on_degraded(self, event) -> None:
        """Handle subsystem degradation."""
        data = event.data
        subsystem = data.get("subsystem", "unknown")
        level = data.get("level", "unknown")
        message = data.get("message", "")
        consecutive = data.get("consecutive_failures", 0)
        
        logger.warning(f"Subsystem degraded: {subsystem} ({level}) - {message}")
        
        # Voice provider failover
        if subsystem == "voice":
            await self.bus.emit("immune.failover.voice", {
                "reason": message,
                "action": "switch_provider",
            })
        
        # Alert on first degradation
        if consecutive <= 1:
            await self._alert(
                f"⚠️ {subsystem} degraded: {message}",
                level="warning",
            )
    
    async def _on_recovered(self, event) -> None:
        """Handle subsystem recovery."""
        data = event.data
        subsystem = data.get("subsystem", "unknown")
        was = data.get("was", "unknown")
        
        logger.info(f"Subsystem recovered: {subsystem} (was {was})")
        await self._alert(
            f"✅ {subsystem} recovered (was {was})",
            level="info",
        )
    
    async def _on_recovery_attempted(self, event) -> None:
        """Log recovery attempts."""
        data = event.data
        self._recovery_log.append({
            "subsystem": data.get("subsystem"),
            "attempt": data.get("attempt"),
            "timestamp": time.time(),
        })
        # Keep last 50 entries
        if len(self._recovery_log) > 50:
            self._recovery_log = self._recovery_log[-50:]
    
    # ── Vitals Monitoring ─────────────────────────────────────
    
    async def _vitals_loop(self) -> None:
        """Periodic system vitals check."""
        try:
            while self._running:
                vitals = collect_vitals()
                self._last_vitals = vitals
                
                # Emit vitals event
                await self.bus.emit("immune.vitals", {
                    "disk_used_pct": round(vitals.disk_used_pct, 1),
                    "disk_free_gb": round(vitals.disk_free_gb, 1),
                    "memory_used_pct": round(vitals.memory_used_pct, 1),
                    "memory_available_mb": round(vitals.memory_available_mb, 0),
                    "load_1m": round(vitals.load_average_1m, 2),
                })
                
                # Check thresholds
                if vitals.disk_used_pct > self.disk_warn_pct:
                    await self._alert(
                        f"🔴 Disk usage critical: {vitals.disk_used_pct:.1f}% "
                        f"({vitals.disk_free_gb:.1f} GB free)",
                        level="critical",
                    )
                    await self.bus.emit("immune.disk.warning", {
                        "used_pct": vitals.disk_used_pct,
                        "free_gb": vitals.disk_free_gb,
                    })
                
                if vitals.memory_used_pct > self.memory_warn_pct:
                    await self._alert(
                        f"🔴 Memory usage critical: {vitals.memory_used_pct:.1f}% "
                        f"({vitals.memory_available_mb:.0f} MB available)",
                        level="critical",
                    )
                
                await asyncio.sleep(self.vitals_interval)
        except asyncio.CancelledError:
            pass
    
    # ── Alerting ──────────────────────────────────────────────
    
    async def _alert(self, message: str, level: str = "info") -> None:
        """Send alert via bus event (for NERVE to pick up and deliver)."""
        self._alert_count += 1
        await self.bus.emit("immune.alert", {
            "message": message,
            "level": level,
            "chat_id": self.alert_chat_id,
            "channel": self.alert_channel,
            "alert_number": self._alert_count,
        })
