"""
SINGULARITY Runtime — The Runtime Lives
===================================

The runtime orchestrator. Boots all subsystems, wires them
through the event bus, connects to channels, and starts
listening. This is where the system becomes alive.

Boot sequence:
1. Load config (SPINE)
2. Start event bus
3. Initialize memory (MEMORY)
4. Initialize tools (SINEW)
5. Initialize voice (VOICE provider chain)
6. Initialize brain (CORTEX agent loop)
7. Initialize scheduler (PULSE)
8. Initialize health monitoring (PULSE + IMMUNE)
9. Connect channels (NERVE adapters)
10. Start listening
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from .bus import EventBus
from .config import SingularityConfig, load_config

logger = logging.getLogger("singularity.runtime")


class Runtime:
    """
    The Singularity runtime — the autonomous enterprise nervous system.
    
    Boots all subsystems, wires the event bus, and runs
    the main event loop.
    
    Usage:
        runtime = Runtime()
        await runtime.boot()
        await runtime.run()  # Blocks until shutdown
    """
    
    def __init__(self, config_path: str | None = None):
        self.config = load_config(config_path)
        self.bus = EventBus()
        
        # Subsystem references (populated during boot)
        self.sessions = None     # MEMORY sessions
        self.comb = None         # MEMORY COMB
        self.tools = None        # SINEW executor
        self.voice = None        # VOICE provider chain
        self.cortex = None       # CORTEX engine
        self.scheduler = None    # PULSE scheduler
        self.health = None       # PULSE health monitor
        self.watchdog = None     # IMMUNE watchdog
        self.router = None       # NERVE router
        self.adapters = {}       # NERVE channel adapters
        
        self._running = False
        self._boot_time: float | None = None
        self._shutdown_event = asyncio.Event()
    
    # ── Convenience Accessors ─────────────────────────────────
    
    @property
    def workspace(self) -> str:
        return self.config.tools.workspace
    
    @property
    def discord_enabled(self) -> bool:
        return bool(self.config.discord.token)
    
    @property
    def discord_token(self) -> str:
        return self.config.discord.token
    
    # ── Boot Sequence ─────────────────────────────────────────
    
    async def boot(self) -> None:
        """
        Boot all subsystems in dependency order.
        Each phase must succeed before the next starts.
        """
        logger.info("=" * 60)
        logger.info("SINGULARITY [AE] — Boot Sequence")
        logger.info("=" * 60)
        self._boot_time = time.monotonic()
        
        # Phase 1: Event Bus
        logger.info("[1/9] Starting event bus...")
        await self.bus.start()
        
        # Phase 2: Memory (MEMORY)
        logger.info("[2/9] Initializing memory (MEMORY)...")
        await self._boot_memory()
        
        # Phase 3: Tools (SINEW)
        logger.info("[3/9] Initializing tools (SINEW)...")
        await self._boot_sinew()
        
        # Phase 4: Voice (VOICE)
        logger.info("[4/9] Initializing voice (VOICE)...")
        await self._boot_voice()
        
        # Phase 5: Brain (CORTEX)
        logger.info("[5/9] Initializing brain (CORTEX)...")
        await self._boot_cortex()
        
        # Phase 6: Scheduler (PULSE)
        logger.info("[6/9] Initializing scheduler (PULSE)...")
        await self._boot_pulse()
        
        # Phase 7: Health + Immune
        logger.info("[7/9] Initializing health monitoring (IMMUNE)...")
        await self._boot_immune()
        
        # Phase 8: Channel routing (NERVE router)
        logger.info("[8/9] Initializing message routing (NERVE)...")
        await self._boot_nerve_router()
        
        # Phase 9: Channel adapters (NERVE)
        logger.info("[9/9] Connecting channels (NERVE)...")
        await self._boot_nerve_adapters()
        
        # Wire cross-subsystem events
        await self._wire_events()
        
        elapsed = time.monotonic() - self._boot_time
        logger.info(f"Boot complete in {elapsed:.1f}s")
        logger.info("Singularity is alive. ⚡")
        
        await self.bus.emit("runtime.booted", {
            "boot_time_seconds": elapsed,
            "adapters": list(self.adapters.keys()),
        })
    
    # ── Individual Boot Phases ────────────────────────────────
    
    async def _boot_memory(self) -> None:
        """Initialize memory subsystem."""
        from .memory.sessions import SessionStore
        from .memory.comb import CombMemory
        
        sessions_db = os.path.join(self.workspace, ".singularity", "sessions.db")
        os.makedirs(os.path.dirname(sessions_db), exist_ok=True)
        self.sessions = SessionStore(db_path=sessions_db, bus=self.bus)
        comb_path = os.path.join(self.workspace, ".singularity", "comb")
        self.comb = CombMemory(store_path=comb_path, bus=self.bus)
        logger.info(f"  MEMORY ready (workspace: {self.workspace})")
    
    async def _boot_sinew(self) -> None:
        """Initialize tool execution."""
        from .sinew.executor import ToolExecutor
        
        tc = self.config.tools
        self.tools = ToolExecutor(
            workspace=tc.workspace,
            bus=self.bus,
            exec_timeout=tc.exec_timeout,
            max_output=tc.exec_max_output,
        )
        logger.info(f"  SINEW ready (workspace: {tc.workspace})")
    
    async def _boot_voice(self) -> None:
        """Initialize LLM provider chain."""
        from .voice.chain import ProviderChain
        from .voice.proxy import CopilotProxyProvider
        from .voice.ollama import OllamaProvider
        
        vc = self.config.voice
        providers = []
        
        # Copilot proxy (primary)
        proxy = CopilotProxyProvider(
            endpoint=vc.proxy.base_url,
            model=vc.primary_model,
        )
        providers.append(proxy)
        
        # Ollama (fallback)
        if vc.ollama.enabled:
            ollama = OllamaProvider(
                endpoint=vc.ollama.base_url,
                model=vc.ollama.models[0] if vc.ollama.models else "llama3.2",
            )
            providers.append(ollama)
        
        self.voice = ProviderChain(providers)
        logger.info(f"  VOICE ready ({len(providers)} providers in chain)")
    
    async def _boot_cortex(self) -> None:
        """Initialize the cortex engine."""
        from .cortex.engine import CortexEngine, CortexConfig
        from .cortex.agent import AgentConfig
        from .cortex.blink import BlinkConfig as BlinkCfg
        
        vc = self.config.voice
        pc = self.config.pulse
        bc = self.config.blink
        
        agent_config = AgentConfig(
            persona_name=self.config.persona.name if hasattr(self.config, 'persona') else "singularity",
            max_iterations=pc.default_cap,
            expanded_iterations=pc.expanded_cap,
            expansion_threshold=pc.expand_threshold,
            temperature=vc.temperature,
            max_tokens=vc.max_tokens,
        )
        
        blink_config = BlinkCfg(
            enabled=bc.enabled,
            max_depth=bc.max_depth,
            prepare_at=bc.prepare_at,
            flush_at=bc.flush_at,
            cooldown_seconds=bc.cooldown_seconds,
        )
        
        # Identity files to load into system prompt
        workspace = self.config.tools.workspace
        identity_files = []
        for fname in ["IDENTITY_ARIA.md", "SOUL_ARIA.md", "AGENTS_ARIA.md", "USER_ARIA.md"]:
            fpath = os.path.join(workspace, fname)
            if os.path.exists(fpath):
                identity_files.append(fpath)
        
        cortex_config = CortexConfig(
            persona_name=agent_config.persona_name,
            identity_files=identity_files,
            context_budget=self.config.memory.max_context_tokens,
            agent=agent_config,
            blink=blink_config,
        )
        
        self.cortex = CortexEngine(
            voice=self.voice,
            tools=self.tools,
            sessions=self.sessions,
            config=cortex_config,
            bus=self.bus,
            workspace=workspace,
        )
        await self.cortex.boot()
        logger.info(f"  CORTEX ready (model: {vc.primary_model})")
    
    async def _boot_pulse(self) -> None:
        """Initialize scheduler."""
        from .pulse.scheduler import Scheduler, JobConfig, JobType
        from .pulse.health import HealthMonitor
        
        self.scheduler = Scheduler(self.bus)
        await self.scheduler.start()
        
        self.health = HealthMonitor(self.bus)
        
        # Register default health checks
        self._register_health_checks()
        
        await self.health.start(check_interval=60.0)
        logger.info("  PULSE ready (scheduler + health monitor)")
    
    async def _boot_immune(self) -> None:
        """Initialize immune system."""
        from .immune.watchdog import Watchdog
        
        alert_channels = self.config.immune.alert_channels
        alert_chat_id = alert_channels[0] if alert_channels else None
        
        self.watchdog = Watchdog(
            bus=self.bus,
            alert_chat_id=alert_chat_id,
            alert_channel="discord",
        )
        await self.watchdog.start()
        logger.info("  IMMUNE ready (watchdog active)")
    
    async def _boot_nerve_router(self) -> None:
        """Initialize message routing."""
        from .nerve.router import InboundRouter
        from .nerve.types import ChannelPolicy
        
        dc = self.config.discord
        policies = {}
        
        if dc.token:
            policies["discord"] = ChannelPolicy(
                dm_policy=dc.dm_policy,
                group_policy="mention-only" if dc.require_mention else "open",
                owner_ids=dc.authorized_users,
                allowed_senders=dc.dm_allowlist,
                self_id=dc.bot_user_id,
                sibling_bot_ids=dc.sister_bot_ids,
                ignored_channels=[],
            )
        
        self.router = InboundRouter(
            bus=self.bus,
            policies=policies,
            global_owner_ids=dc.authorized_users,
        )
        logger.info(f"  NERVE router ready ({len(policies)} channel policies)")
    
    async def _boot_nerve_adapters(self) -> None:
        """Connect channel adapters."""
        dc = self.config.discord
        
        if dc.token:
            from .nerve.discord import DiscordAdapter
            
            adapter = DiscordAdapter(adapter_id="discord-main")
            
            # Wire adapter messages to router
            def on_message(envelope):
                self.router.route(
                    envelope.source,
                    envelope.payload,
                    envelope.id,
                )
            adapter.on_message(on_message)
            
            try:
                await adapter.connect({
                    "token": dc.token,
                    "bot_id": dc.bot_user_id,
                    "sibling_bot_ids": dc.sister_bot_ids,
                    "guild_ids": dc.guild_ids,
                })
                self.adapters["discord"] = adapter
                logger.info("  Discord adapter connected")
            except Exception as e:
                logger.error(f"  Discord adapter failed: {e}")
        else:
            logger.info("  Discord adapter skipped (no token)")
    
    # ── Health Check Registration ─────────────────────────────
    
    def _register_health_checks(self) -> None:
        """Register default health checks."""
        from .pulse.health import HealthLevel
        
        # Voice health
        async def check_voice():
            if not self.voice:
                return HealthLevel.UNKNOWN, "Voice not initialized"
            # Check if any providers in chain are available
            avail = sum(1 for p in self.voice.providers if p.available)
            total = len(self.voice.providers)
            if avail == 0:
                return HealthLevel.UNHEALTHY, "No providers available"
            if avail < total:
                return HealthLevel.DEGRADED, f"Degraded: {avail}/{total} providers"
            return HealthLevel.HEALTHY, f"All {total} providers available"
        
        # Memory health
        async def check_memory():
            if not self.sessions:
                return HealthLevel.UNKNOWN, "Sessions not initialized"
            sessions = await self.sessions.list_sessions()
            return HealthLevel.HEALTHY, f"{len(sessions)} active sessions"
        
        # System vitals
        async def check_vitals():
            from .immune.watchdog import collect_vitals
            vitals = collect_vitals()
            issues = []
            if vitals.disk_used_pct > 93:
                issues.append(f"disk {vitals.disk_used_pct:.0f}%")
            if vitals.memory_used_pct > 90:
                issues.append(f"mem {vitals.memory_used_pct:.0f}%")
            if issues:
                return HealthLevel.DEGRADED, "Resources: " + ", ".join(issues)
            return HealthLevel.HEALTHY, f"disk {vitals.disk_used_pct:.0f}%, mem {vitals.memory_used_pct:.0f}%"
        
        self.health.register("voice", check_voice)
        self.health.register("memory", check_memory)
        self.health.register("vitals", check_vitals)
    
    # ── Event Wiring ──────────────────────────────────────────
    
    async def _wire_events(self) -> None:
        """Wire cross-subsystem event handlers."""
        
        # Routed messages → CORTEX processing
        @self.bus.on("nerve.routed")
        async def on_routed(event):
            envelope = event.data.get("envelope")
            if not envelope:
                return
            
            session_id = envelope.session_id or envelope.source.chat_id or "default"
            
            # Process through cortex engine
            if self.cortex:
                try:
                    result = await self.cortex.process(
                        session_id=session_id,
                        message=envelope.payload.text or "",
                        source=envelope.source,
                        sender_name=getattr(envelope.source, 'sender_name', ''),
                    )
                    
                    # Send response back through the channel
                    if result and result.response:
                        adapter_id = envelope.source.adapter_id
                        chat_id = envelope.source.chat_id
                        
                        adapter = self.adapters.get("discord")  # TODO: route by adapter_id
                        if adapter:
                            from .nerve.types import OutboundMessage
                            from .nerve.formatter import format_for_channel
                            
                            chunks = format_for_channel(
                                result.response,
                                adapter.capabilities,
                            )
                            for chunk in chunks:
                                await adapter.send(chat_id, OutboundMessage(content=chunk))
                
                except Exception as e:
                    logger.error(f"CORTEX processing error: {e}")
        
        # Immune alerts → send to alert channel
        @self.bus.on("immune.alert")
        async def on_alert(event):
            data = event.data
            chat_id = data.get("chat_id")
            channel = data.get("channel", "discord")
            message = data.get("message", "")
            
            if chat_id and channel in self.adapters:
                from .nerve.types import OutboundMessage
                adapter = self.adapters[channel]
                try:
                    await adapter.send(chat_id, OutboundMessage(content=f"🛡️ {message}"))
                except Exception as e:
                    logger.error(f"Alert delivery failed: {e}")
        
        logger.info("Event wiring complete")
    
    # ── Run Loop ──────────────────────────────────────────────
    
    async def run(self) -> None:
        """
        Run the main event loop. Blocks until shutdown signal.
        """
        self._running = True
        
        # Handle signals
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
        
        logger.info("Runtime running. Waiting for events...")
        
        # Wait for shutdown signal
        await self._shutdown_event.wait()
        
        logger.info("Shutdown complete.")
    
    async def shutdown(self) -> None:
        """Gracefully shut down all subsystems."""
        if not self._running:
            return
        self._running = False
        
        logger.info("Shutting down...")
        
        # Stop in reverse order
        for name, adapter in self.adapters.items():
            try:
                await adapter.disconnect()
                logger.info(f"  Adapter {name} disconnected")
            except Exception as e:
                logger.error(f"  Adapter {name} disconnect error: {e}")
        
        if self.watchdog:
            await self.watchdog.stop()
        
        if self.health:
            await self.health.stop()
        
        if self.scheduler:
            await self.scheduler.stop()
        
        if self.tools:
            await self.tools.close()
        
        await self.bus.stop()
        
        logger.info("All subsystems stopped.")
        self._shutdown_event.set()
    
    @property
    def uptime(self) -> float:
        """Uptime in seconds since boot."""
        if self._boot_time is None:
            return 0
        return time.monotonic() - self._boot_time
