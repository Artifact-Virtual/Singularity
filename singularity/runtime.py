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
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from .bus import EventBus
from .config import SingularityConfig, load_config
from .nerve.presence import presence_manager

import re

logger = logging.getLogger("singularity.runtime")

# C-Suite constants (shared by _boot_csuite and _extract_exec_roles)
_CSUITE_NAMES = frozenset({"cto", "coo", "cfo", "ciso", "cro", "cpo", "cmo", "cdo", "cco"})
_CSUITE__CSUITE_TITLE_MAP = {
    "cto": "Chief Technology Officer",
    "coo": "Chief Operating Officer",
    "cfo": "Chief Financial Officer",
    "ciso": "Chief Information Security Officer",
    "cro": "Chief Risk Officer",
    "cpo": "Chief Product Officer",
    "cmo": "Chief Marketing Officer",
    "cdo": "Chief Data Officer",
    "cco": "Chief Compliance Officer",
}


def _ensure_mention(text: str, sender_id: str | None, channel_type: str = "discord") -> str:
    """Ensure the response contains an @mention of the sender (Discord only).
    
    LOOP PREVENTION: If text contains @end or @drop, strip ALL mentions to break cross-bot loops.
    Otherwise, if no mention exists, prepend sender mention.
    This is a structural enforcement — the LLM can't forget it.
    """
    if channel_type != "discord" or not sender_id:
        return text
    
    # CHECK FOR LOOP BREAKERS — strip mentions to drop conversation
    if "@end" in text.lower() or "@drop" in text.lower():
        # Strip ALL @mentions to break cross-bot loops
        text = re.sub(r'<@!?\d+>', '', text).strip()
        # Clean up any resulting double spaces
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    mention = f"<@{sender_id}>"
    # Check if already mentioned anywhere in the text
    if mention in text:
        return text
    # Also accept <@!id> format (nickname mention)
    if f"<@!{sender_id}>" in text:
        return text
    return f"{mention} {text}"


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
        self.hektor = None       # MEMORY HEKTOR (search)
        self.tools = None        # SINEW executor
        self.voice = None        # VOICE provider chain
        self.cortex = None       # CORTEX engine
        self.scheduler = None    # PULSE scheduler
        self.health = None       # PULSE health monitor
        self.watchdog = None     # IMMUNE watchdog
        self.router = None       # NERVE router
        self.adapters = {}       # NERVE channel adapters
        self.coordinator = None  # CSUITE coordinator
        self.dispatcher = None   # CSUITE dispatch interface
        self.deployer = None     # NERVE guild deployer
        self.nexus = None        # NEXUS self-optimization engine
        self._nexus_daemon = None  # NEXUS evolution daemon (subagent)
        self.atlas = None        # ATLAS board manager
        
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
        
        # Phase 0: Validate .core/ exists and is clean
        logger.info("[0/12] Validating agent core...")
        self._validate_core()
        
        # Phase 1: Event Bus
        logger.info("[1/12] Starting event bus...")
        await self.bus.start()
        
        # Phase 2: Memory (MEMORY)
        logger.info("[2/12] Initializing memory (MEMORY)...")
        await self._boot_memory()
        
        # Phase 3: Tools (SINEW)
        logger.info("[3/12] Initializing tools (SINEW)...")
        await self._boot_sinew()
        
        # Phase 4: Voice (VOICE)
        logger.info("[4/12] Initializing voice (VOICE)...")
        await self._boot_voice()
        
        # Phase 5: Brain (CORTEX)
        logger.info("[5/12] Initializing brain (CORTEX)...")
        await self._boot_cortex()
        
        # Phase 6: C-Suite (CSUITE) — requires VOICE + SINEW
        logger.info("[6/12] Initializing C-Suite (CSUITE)...")
        await self._boot_csuite()
        
        # Phase 7: Self-Optimization (NEXUS)
        logger.info("[7/12] Initializing self-optimization (NEXUS)...")
        await self._boot_nexus()
        
        # Phase 8: Scheduler (PULSE)
        logger.info("[8/12] Initializing scheduler (PULSE)...")
        await self._boot_pulse()
        
        # Phase 8.5: POA Monitoring (requires PULSE)
        logger.info("[8.5/12] Initializing POA monitoring...")
        await self._boot_poa_monitoring()

        # Phase 8.6: NEXUS Evolution Daemon (requires NEXUS + PULSE)
        logger.info("[8.6/12] Starting NEXUS evolution daemon...")
        await self._boot_nexus_daemon()

        # Phase 8.7: ATLAS Board Manager (requires PULSE + bus)
        logger.info("[8.7/12] Starting ATLAS board manager...")
        await self._boot_atlas()

        # Phase 9: Health + Immune
        logger.info("[9/12] Initializing health monitoring (IMMUNE)...")
        await self._boot_immune()
        
        # Phase 10: Channel routing (NERVE router)
        logger.info("[10/12] Initializing message routing (NERVE)...")
        await self._boot_nerve_router()
        
        # Phase 11: Guild deployer (NERVE deployer)
        logger.info("[11/12] Preparing guild deployer (NERVE)...")
        self._boot_deployer()
        
        # Phase 12: Channel adapters (NERVE)
        logger.info("[12/12] Connecting channels (NERVE)...")
        await self._boot_nerve_adapters()
        
        # Wire cross-subsystem events
        await self._wire_events()
        
        elapsed = time.monotonic() - self._boot_time
        logger.info(f"Boot complete in {elapsed:.1f}s")
        logger.info("Singularity is alive. ⚡")
        
        await self.bus.emit("runtime.booted", {
            "boot_time_seconds": elapsed,
            "adapters": list(self.adapters.keys()),
            "csuite_executives": list(self.coordinator.executives.keys()) if self.coordinator else [],
        })
    
    # ── Core Validation ──────────────────────────────────────────
    
    def _validate_core(self) -> None:
        """Validate that .core/ exists and contains a clean agent install.
        
        If .core/ doesn't exist, the runtime still boots with root-level
        identity files (backward compatible). But if .core/ exists, it
        must have install.json proving it was created by fresh_install.py.
        
        This prevents corrupted state from bleeding into the runtime.
        """
        workspace = self.config.tools.workspace
        core_dir = Path(workspace) / "singularity" / ".core"
        
        if not core_dir.exists():
            logger.warning(
                "  .core/ not found — using root-level identity files. "
                "Run 'python3 -m singularity install' to create a clean agent."
            )
            return
        
        # Verify install.json exists (proof of clean install)
        install_json = core_dir / "install.json"
        if not install_json.exists():
            logger.warning(
                "  .core/ exists but has no install.json — "
                "this may be legacy state. Consider running 'install' to get a clean slate."
            )
            return
        
        try:
            record = json.loads(install_json.read_text())
            agent_name = record.get("agent_name", "Unknown")
            agent_emoji = record.get("agent_emoji", "?")
            installed_at = record.get("installed_at", "?")
            clean = record.get("clean_slate", False)
            
            logger.info(f"  {agent_emoji} Agent: {agent_name}")
            logger.info(f"  Installed: {installed_at}")
            if clean:
                logger.info("  ✅ Clean slate verified")
            else:
                logger.warning("  ⚠️  Not a clean slate install")
        except Exception as e:
            logger.warning(f"  .core/install.json unreadable: {e}")
        
        # Verify identity files exist
        for fname in ["SOUL.md", "IDENTITY.md", "AGENTS.md"]:
            fpath = core_dir / fname
            if not fpath.exists():
                logger.warning(f"  Missing: .core/{fname}")
    
    # ── Individual Boot Phases ────────────────────────────────
    
    async def _boot_memory(self) -> None:
        """Initialize memory subsystem (COMB + HEKTOR + Sessions)."""
        from .memory.sessions import SessionStore
        from .memory.comb import CombMemory
        from .memory.hektor import HektorMemory
        
        sg_root = os.path.join(self.workspace, "singularity")
        core_memory = os.path.join(sg_root, ".core", "memory")
        
        # Sessions DB — runtime data, lives in .singularity/
        sessions_db = os.path.join(self.workspace, ".singularity", "sessions.db")
        os.makedirs(os.path.dirname(sessions_db), exist_ok=True)
        self.sessions = SessionStore(db_path=sessions_db, bus=self.bus)
        await self.sessions.open()
        
        # COMB — persistent memory, lives in .core/memory/comb/
        comb_path = os.path.join(core_memory, "comb")
        self.comb = CombMemory(store_path=comb_path, bus=self.bus)
        await self.comb.initialize()
        logger.info(f"  COMB store: {comb_path}")
        
        # Recall on boot if configured
        if self.config.memory.recall_on_boot:
            recall_content = await self.comb.recall()
            if recall_content:
                logger.info(f"  COMB recall: {len(recall_content)} chars")
            else:
                logger.info("  COMB recall: empty (first boot or no staged content)")
        
        # HEKTOR — BM25 search over workspace files
        hektor_path = os.path.join(core_memory, "hektor")
        self.hektor = HektorMemory(
            workspace=self.workspace,
            index_dir=hektor_path,
            bus=self.bus,
        )
        file_count = await self.hektor.index()
        logger.info(f"  HEKTOR indexed: {file_count} files")
        
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
        
        # Wire COMB into executor (memory booted in Phase 2, before SINEW)
        if self.comb:
            self.tools.set_comb(self.comb)
    
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
            persona_name="singularity",
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
        
        # Identity files to load into system prompt (config-driven)
        workspace = self.config.tools.workspace
        identity_files = []
        for fname in self.config.identity_files:
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
            comb=self.comb,
        )
        await self.cortex.boot()
        logger.info(f"  CORTEX ready (model: {vc.primary_model})")
    
    async def _boot_csuite(self) -> None:
        """Initialize C-Suite executives and coordinator."""
        from .csuite.roles import (
            RoleRegistry, RoleType, Role, ToolScope,
            EscalationPolicy, AuditScope, _ROLE_DEFAULTS,
            build_executive_prompt,
        )
        from .csuite.executive import Executive
        from .csuite.coordinator import Coordinator
        from .csuite.dispatch import Dispatcher
        from .voice.chain import ProviderChain
        from .voice.proxy import CopilotProxyProvider
        from .voice.ollama import OllamaProvider
        
        if not self.config.csuite.enabled:
            logger.info("  CSUITE disabled in config")
            return
        
        # Build exec-tier provider chain (lighter model for executives)
        vc = self.config.voice
        exec_model = self.config.csuite.executive_model
        exec_providers = []
        
        exec_proxy = CopilotProxyProvider(
            endpoint=vc.proxy.base_url,
            model=exec_model,
        )
        exec_providers.append(exec_proxy)
        
        if vc.ollama.enabled:
            exec_ollama = OllamaProvider(
                endpoint=vc.ollama.base_url,
                model=vc.ollama.models[0] if vc.ollama.models else "llama3.2",
            )
            exec_providers.append(exec_ollama)
        
        exec_voice = ProviderChain(exec_providers)
        logger.info(f"  CSUITE exec-tier voice ready (model: {exec_model}, {len(exec_providers)} providers)")
        
        # Build role registry from config personas
        enterprise = "Artifact Virtual"
        registry = RoleRegistry(enterprise=enterprise)
        
        # Collect exec persona configs (from both personas and csuite.personas)
        exec_personas = []
        seen = set()
        for persona in self.config.personas:
            role_id = persona.name.lower()
            if role_id in _CSUITE_NAMES and role_id not in seen:
                exec_personas.append(persona)
                seen.add(role_id)
        for persona in self.config.csuite.personas:
            role_id = persona.name.lower()
            if role_id in _CSUITE_NAMES and role_id not in seen:
                exec_personas.append(persona)
                seen.add(role_id)
        
        if not exec_personas:
            logger.info("  CSUITE: no executive personas in config")
            return
        
        # Create executives
        executives: dict[RoleType, Executive] = {}
        
        for persona in exec_personas:
            role_id = persona.name.lower()
            role_type = RoleType.from_str(role_id)
            defaults = _ROLE_DEFAULTS.get(role_id, _ROLE_DEFAULTS.get("custom", {}))
            
            # Build the role
            _CSUITE__CSUITE_TITLE_MAP = {
                "cto": "Chief Technology Officer",
                "coo": "Chief Operating Officer",
                "cfo": "Chief Financial Officer",
                "ciso": "Chief Information Security Officer",
                "cro": "Chief Risk Officer",
                "cpo": "Chief Product Officer",
                "cmo": "Chief Marketing Officer",
                "cdo": "Chief Data Officer",
                "cco": "Chief Compliance Officer",
            }
            title = _CSUITE__CSUITE_TITLE_MAP.get(role_id, f"Chief {role_id.upper()} Officer")
            
            role = Role(
                role_type=role_type,
                title=title,
                emoji=defaults.get("emoji", "👤"),
                domain=defaults.get("domain", ""),
                keywords=defaults.get("keywords", []),
                tools=ToolScope(
                    read_paths=defaults.get("read_paths", []),
                    write_paths=defaults.get("write_paths", []),
                    forbidden_paths=defaults.get("forbidden_paths", [".ava-private/"]),
                    can_exec=defaults.get("can_exec", True),
                    can_network=defaults.get("can_network", False),
                    allowed_tools=defaults.get("allowed_tools", ["read", "write", "edit", "exec"]),
                ),
                escalation=EscalationPolicy(
                    timeout_seconds=defaults.get("timeout", 300),
                ),
                audit=AuditScope(
                    checks=defaults.get("audit_checks", []),
                ),
                system_prompt=build_executive_prompt(
                    role_type=role_id,
                    title=title,
                    emoji=defaults.get("emoji", "👤"),
                    domain=defaults.get("domain", ""),
                    enterprise=enterprise,
                ),
                enterprise=enterprise,
            )
            registry.register(role)
            
            # Determine workspace for this executive
            exec_workspace = Path(persona.workspace) if persona.workspace else (
                Path(self.workspace) / "executives" / role_id
            )
            
            # Create the executive (uses exec-tier voice, not coordinator's Opus)
            executive = Executive(
                role=role,
                bus=self.bus,
                provider_chain=exec_voice,
                tool_executor=self.tools,
                workspace=exec_workspace,
            )
            executives[role_type] = executive
        
        # Create coordinator
        csuite_workspace = Path(self.workspace) / ".singularity" / "csuite"
        self.coordinator = Coordinator(
            bus=self.bus,
            executives=executives,
            workspace=csuite_workspace,
        )
        await self.coordinator.start()
        
        # Create dispatcher
        self.dispatcher = Dispatcher(self.coordinator)
        
        # Make dispatcher available as a tool
        if self.tools:
            self.tools.set_csuite_dispatcher(self.dispatcher)
        
        exec_names = [rt.value.upper() for rt in executives.keys()]
        logger.info(f"  CSUITE ready ({len(executives)} executives: {', '.join(exec_names)})")
    
    def _boot_deployer(self) -> None:
        """Prepare the guild deployer with exec roles from config."""
        from .nerve.deployer import GuildDeployer
        
        exec_roles = self._extract_exec_roles()
        dc = self.config.discord
        
        if exec_roles:
            sg_dir = Path(self.workspace) / ".singularity"
            self.deployer = GuildDeployer(
                exec_roles=exec_roles,
                private=True,
                event_callback=self._deployer_event_callback,
                sg_dir=sg_dir,
                authorized_user_ids=dc.authorized_users if dc else [],
            )
            logger.info(f"  DEPLOYER ready ({len(exec_roles)} exec roles)")
        else:
            logger.info("  DEPLOYER skipped (no exec roles in config)")
    
    async def _deployer_event_callback(self, event: str, data: dict) -> None:
        """Forward deployer events to the bus."""
        await self.bus.emit(f"deployer.{event}", data)
    
    async def _boot_nexus(self) -> None:
        """Initialize the NEXUS self-optimization engine."""
        try:
            from .nexus.engine import NexusEngine
            
            source_root = Path(__file__).resolve().parent  # singularity/singularity/
            workspace = source_root.parent                  # singularity/
            
            self.nexus = NexusEngine(
                source_root=str(source_root),
                workspace=str(workspace),
                bus=self.bus,
            )
            await self.nexus.start()
            
            # Make nexus available to tool executor
            if self.tools:
                self.tools.set_nexus(self.nexus)
            
            logger.info("  NEXUS self-optimization engine ready")
        except Exception as e:
            logger.warning(f"  NEXUS failed to initialize: {e}")
            self.nexus = None
    
    async def _boot_nexus_daemon(self) -> None:
        """Start the NEXUS self-evolution daemon (requires NEXUS + PULSE)."""
        if not self.nexus:
            logger.warning("  NEXUS daemon skipped — engine not available")
            return
        try:
            from .nexus.daemon import EvolutionDaemon

            self._nexus_daemon = EvolutionDaemon(
                engine=self.nexus,
                bus=self.bus,
                scheduler=self.scheduler,
                interval_seconds=6 * 3600,  # Every 6 hours
            )
            await self._nexus_daemon.start()

            # Wire cycle reports to #governance Discord channel
            GOVERNANCE_CHANNEL = "1327890703250096168"

            async def on_nexus_cycle_done(event):
                """Forward NEXUS evolution reports to #governance for visibility."""
                try:
                    if not (self.tools and self.tools._discord_adapter):
                        return

                    data = event.data if hasattr(event, 'data') else event
                    if not isinstance(data, dict):
                        return

                    applied = data.get("applied", 0)
                    found = data.get("found", 0)
                    validated = data.get("validated", 0)
                    failed = data.get("failed", 0)
                    duration = data.get("duration", 0)
                    is_clean = data.get("clean", False)
                    error = data.get("error")
                    details = data.get("details", [])

                    # Build report
                    lines = ["**NEXUS Self-Evolution Report**", ""]

                    if error:
                        lines.append(f"Status: FAILED")
                        lines.append(f"Error: `{error}`")
                    elif is_clean:
                        lines.append(f"Status: CLEAN — no targets found")
                        lines.append(f"Duration: {duration:.1f}s")
                        lines.append("")
                        lines.append("Codebase is fully evolved. No silent exceptions or bare excepts remaining.")
                    else:
                        lines.append(f"Status: **{applied} evolutions applied**")
                        lines.append(f"Duration: {duration:.1f}s")
                        lines.append("")

                        # Analysis section
                        lines.append("**Analysis**")
                        lines.append(f"Scanned targets: {found}")
                        lines.append(f"Validated (AST-safe): {validated}")
                        if failed:
                            lines.append(f"Failed to apply: {failed}")
                        lines.append("")

                        # Implementation section
                        if details:
                            lines.append("**Implementation**")
                            for d in details[:10]:  # Cap at 10 for Discord length
                                fname = d.get("file", "?").split("/")[-1]
                                line_num = d.get("line", "?")
                                cat = d.get("category", "?")
                                desc = d.get("description", "")
                                lines.append(f"`{fname}:{line_num}` [{cat}] {desc}")

                                orig = d.get("original", "")
                                evolved = d.get("evolved", "")
                                if orig and evolved:
                                    lines.append(f"```diff")
                                    for ol in orig.splitlines()[:2]:
                                        lines.append(f"- {ol}")
                                    for el in evolved.splitlines()[:2]:
                                        lines.append(f"+ {el}")
                                    lines.append("```")
                            if len(details) > 10:
                                lines.append(f"... and {len(details) - 10} more changes")

                    report_msg = "\n".join(lines)

                    # Truncate if too long for Discord (2000 char limit)
                    if len(report_msg) > 1900:
                        report_msg = report_msg[:1900] + "\n... (truncated)"

                    from .nerve.types import OutboundMessage
                    await self.tools._discord_adapter.send(
                        GOVERNANCE_CHANNEL, OutboundMessage(content=report_msg)
                    )
                    logger.debug("[NEXUS-DAEMON] Report sent to #governance")

                except Exception as e:
                    logger.error(f"Failed to forward NEXUS report to Discord: {e}")

            self.bus.on("nexus.daemon.cycle.done", on_nexus_cycle_done)

            logger.info("  NEXUS evolution daemon started (6h cycle, reports → #governance)")
        except Exception as e:
            logger.warning(f"  NEXUS daemon failed to start: {e}")
            self._nexus_daemon = None

    async def _boot_atlas(self) -> None:
        """Start the ATLAS Board Manager — enterprise topology monitoring."""
        try:
            from .atlas.manager import Atlas
            from .pulse.scheduler import JobConfig, JobType

            state_dir = Path(self.config.tools.workspace) / ".singularity" / "atlas"
            self.atlas = Atlas(state_dir=state_dir, bus=self.bus)

            # Register PULSE jobs
            if self.scheduler:
                # Discovery + Coach cycle every 5 minutes
                self.scheduler.add(JobConfig(
                    id="atlas-cycle",
                    name="ATLAS Board Cycle",
                    job_type=JobType.INTERVAL,
                    interval_seconds=300,  # 5 minutes
                    emit_topic="atlas.cycle.trigger",
                ))

                # Board report every 6 hours
                self.scheduler.add(JobConfig(
                    id="atlas-board-report",
                    name="ATLAS Board Report",
                    job_type=JobType.INTERVAL,
                    interval_seconds=6 * 3600,  # 6 hours
                    emit_topic="atlas.board.trigger",
                ))

            # Wire cycle trigger
            @self.bus.on("atlas.cycle.trigger")
            async def on_atlas_cycle(event):
                try:
                    await self.atlas.run_cycle()
                except Exception as e:
                    logger.error(f"ATLAS cycle error: {e}")

            # Wire board report trigger → Discord #dispatch
            DISPATCH_CHANNEL = "1478716096667189292"

            @self.bus.on("atlas.board.trigger")
            async def on_atlas_board(event):
                try:
                    # Run a cycle first to get fresh data
                    await self.atlas.run_cycle()
                    report = self.atlas.get_board_report()

                    if self.tools and self.tools._discord_adapter:
                        from .nerve.types import OutboundMessage
                        await self.tools._discord_adapter.send(
                            DISPATCH_CHANNEL, OutboundMessage(content=report)
                        )
                        logger.debug("ATLAS board report sent to #dispatch")
                except Exception as e:
                    logger.error(f"ATLAS board report error: {e}")

            # Wire alerts → Discord #dispatch
            @self.bus.on("atlas.alert")
            async def on_atlas_alert(event):
                try:
                    if not (self.tools and self.tools._discord_adapter):
                        return
                    data = event.data if hasattr(event, 'data') else event
                    if not isinstance(data, dict):
                        return

                    count = data.get("count", 0)
                    issues = data.get("issues", [])

                    lines = [f"**ATLAS Alert — {count} issue{'s' if count != 1 else ''} detected**", ""]
                    for issue in issues[:10]:
                        sev = issue.get("severity", "?").upper()
                        title = issue.get("title", "?")
                        mod = issue.get("module", "?")
                        lines.append(f"[{sev}] {title} ({mod})")

                    from .nerve.types import OutboundMessage
                    msg = "\n".join(lines)
                    if len(msg) > 1900:
                        msg = msg[:1900] + "\n... (truncated)"
                    await self.tools._discord_adapter.send(
                        DISPATCH_CHANNEL, OutboundMessage(content=msg)
                    )
                except Exception as e:
                    logger.debug(f"Suppressed ATLAS alert forwarding: {e}")

            # Wire module discovery notifications
            @self.bus.on("atlas.module.discovered")
            async def on_atlas_discovered(event):
                try:
                    if not (self.tools and self.tools._discord_adapter):
                        return
                    data = event.data if hasattr(event, 'data') else event
                    if not isinstance(data, dict):
                        return

                    mod_id = data.get("module_id", "?")
                    mod_type = data.get("type", "?")
                    machine = data.get("machine", "?")

                    from .nerve.types import OutboundMessage
                    await self.tools._discord_adapter.send(
                        DISPATCH_CHANNEL,
                        OutboundMessage(content=f"**ATLAS: New module discovered** — `{mod_id}` ({mod_type}) on {machine}")
                    )
                except Exception as e:
                    logger.debug(f"Suppressed ATLAS discovery notification: {e}")

            # Wire tool executor
            if self.tools:
                self.tools.set_atlas(self.atlas)

            # Run initial scan after 15s delay (let other systems stabilize)
            async def _initial_atlas_scan():
                await asyncio.sleep(15)
                try:
                    result = await self.atlas.run_cycle()
                    mods = result.get("modules_found", 0)
                    issues = result.get("issues", 0)
                    logger.info(f"  ATLAS initial scan: {mods} modules, {issues} issues")
                except Exception as e:
                    logger.error(f"ATLAS initial scan failed: {e}")

            asyncio.ensure_future(_initial_atlas_scan())
            logger.info("  ATLAS board manager started (5min cycle, 6h reports → #dispatch)")

        except Exception as e:
            logger.warning(f"  ATLAS failed to start: {e}")
            self.atlas = None

    async def _boot_pulse(self) -> None:
        """Initialize scheduler."""
        from .pulse.scheduler import Scheduler, JobConfig, JobType
        from .pulse.health import HealthMonitor
        
        self.scheduler = Scheduler(self.bus)
        await self.scheduler.start()
        
        self.health = HealthMonitor(self.bus)
        
        # Register default health checks
        self._register_health_checks()
        
        await self.health.start(check_interval=self.config.immune.check_interval)
        logger.info("  PULSE ready (scheduler + health monitor)")
    
    async def _boot_poa_monitoring(self) -> None:
        """Register all active POAs as PULSE scheduler jobs."""
        from .poa.manager import POAManager
        from .poa.runtime import POARuntime
        from .pulse.scheduler import JobConfig, JobType
        
        # Check both local and enterprise workspaces for POAs
        # Local first — it has the active configs
        poa_dirs = []
        local_poa = Path(self.config.tools.workspace) / ".singularity" / "poas"
        enterprise_poa = Path("/home/adam/workspace/enterprise/.singularity/poas")
        
        if local_poa.exists():
            poa_dirs.append(local_poa.parent)
        if enterprise_poa.exists() and enterprise_poa != local_poa:
            poa_dirs.append(enterprise_poa.parent)
        
        if not poa_dirs:
            logger.info("  POA: No POA directories found, skipping")
            return
        
        total_poas = 0
        total_jobs = 0
        primary_manager = None
        
        for workspace in poa_dirs:
            manager = POAManager(workspace)
            if primary_manager is None:
                primary_manager = manager
            active = manager.list_active()
            total_poas += len(active)
            
            for config in active:
                interval = self._parse_cron_interval(config.audit_schedule)
                
                job = JobConfig(
                    id=f"poa-audit-{config.product_id}",
                    name=f"POA Audit: {config.product_name}",
                    job_type=JobType.INTERVAL,
                    interval_seconds=interval,
                    emit_topic="poa.audit.trigger",
                    emit_data={
                        "product_id": config.product_id,
                        "product_name": config.product_name,
                        "workspace": str(workspace),
                    },
                )
                self.scheduler.add(job)
                total_jobs += 1
        
        # Wire the audit trigger handler (once, outside the loop)
        @self.bus.on("poa.audit.trigger")
        async def on_poa_audit(event):
                """Execute POA audit when PULSE fires the job."""
                product_id = event.data.get("product_id")
                ws = Path(event.data.get("workspace", ""))
                
                try:
                    mgr = POAManager(ws)
                    cfg = mgr.get(product_id)
                    if not cfg:
                        logger.warning(f"POA audit: product {product_id} not found")
                        return
                    
                    report = POARuntime.run_audit(cfg)
                    POARuntime.save_audit(report, ws / "poas")
                    
                    # Emit result for escalation / alerting
                    await self.bus.emit("poa.audit.complete", {
                        "product_id": product_id,
                        "status": report.overall_status,
                        "passed": report.passed,
                        "failed": report.failed,
                        "criticals": report.criticals,
                        "duration_ms": report.duration_ms,
                    })
                    
                    # If RED, emit alert
                    if report.overall_status == "red":
                        await self.bus.emit("poa.alert", {
                            "product_id": product_id,
                            "product_name": cfg.product_name,
                            "status": "red",
                            "criticals": report.criticals,
                            "failed_checks": [
                                c.to_dict() for c in report.checks if not c.passed
                            ],
                        })
                        logger.warning(f"POA ALERT: {cfg.product_name} is RED ({report.criticals} critical)")
                    elif report.overall_status == "yellow":
                        await self.bus.emit("poa.alert", {
                            "product_id": product_id,
                            "product_name": cfg.product_name,
                            "status": "yellow",
                            "criticals": 0,
                            "failed_checks": [
                                c.to_dict() for c in report.checks if not c.passed
                            ],
                        })
                        logger.info(f"POA WARNING: {cfg.product_name} is YELLOW ({report.failed} failed)")
                    else:
                        logger.info(f"POA audit: {cfg.product_name} → {report.overall_status.upper()}")
                        
                except Exception as e:
                    logger.error(f"POA audit failed for {product_id}: {e}")
        
        # Wire POA alert → Discord escalation
        @self.bus.on("poa.alert")
        async def on_poa_alert(event):
            """Forward POA RED/YELLOW alerts to Discord for immediate visibility."""
            try:
                product_name = event.data.get("product_name", "unknown")
                product_id = event.data.get("product_id", "")
                status = event.data.get("status", "red")
                criticals = event.data.get("criticals", 0)
                failed_checks = event.data.get("failed_checks", [])

                icon = "🔴" if status == "red" else "🟡"
                severity_word = "CRITICAL" if status == "red" else "WARNING"

                lines = [
                    f"{icon} **POA {severity_word}: {product_name}** — {len(failed_checks)} failure(s)",
                    "",
                ]
                for check in failed_checks[:5]:
                    sev_icon = "🔴" if check.get("severity") == "critical" else "⚠️"
                    lines.append(f"  {sev_icon} **{check.get('name', '?')}**: {check.get('message', '')}")
                if len(failed_checks) > 5:
                    lines.append(f"  ... and {len(failed_checks) - 5} more failures")

                alert_msg = "\n".join(lines)

                # Send to #dispatch channel for visibility
                if self.tools and self.tools._discord_adapter:
                    from .nerve.types import OutboundMessage
                    dispatch_channel = "1478716096667189292"
                    await self.tools._discord_adapter.send(
                        dispatch_channel, OutboundMessage(content=alert_msg)
                    )
                    logger.info(f"POA alert for {product_name} forwarded to Discord")
            except Exception as e:
                logger.error(f"Failed to forward POA alert to Discord: {e}")

        # Also run first audit immediately for all active POAs
        if total_poas > 0:
            asyncio.create_task(self._run_initial_poa_audits(poa_dirs))
        
        # Wire POA manager to executor for tool access
        if primary_manager and self.tools:
            self.tools.set_poa_manager(primary_manager)
        
        logger.info(f"  POA ready ({total_poas} products, {total_jobs} audit jobs scheduled)")
    
    async def _run_initial_poa_audits(self, poa_dirs: list[Path]) -> None:
        """Run first round of POA audits immediately after boot."""
        from .poa.manager import POAManager
        from .poa.runtime import POARuntime
        
        await asyncio.sleep(5)  # Let boot finish first
        
        green = yellow = red = 0
        for workspace in poa_dirs:
            manager = POAManager(workspace)
            for config in manager.list_active():
                try:
                    report = POARuntime.run_audit(config)
                    POARuntime.save_audit(report, workspace / "poas")
                    if report.overall_status == "green":
                        green += 1
                    elif report.overall_status == "yellow":
                        yellow += 1
                    else:
                        red += 1
                except Exception as e:
                    logger.error(f"Initial POA audit failed for {config.product_name}: {e}")
                    red += 1
        
        logger.info(f"POA initial sweep: 🟢{green} 🟡{yellow} 🔴{red}")
        await self.bus.emit("poa.initial_sweep.complete", {
            "green": green, "yellow": yellow, "red": red,
        })
    
    @staticmethod
    def _parse_cron_interval(cron_expr: str) -> float:
        """Parse simplified cron expression to seconds. Default: 4 hours."""
        try:
            parts = cron_expr.split()
            if len(parts) >= 2:
                hour_part = parts[1]
                if hour_part.startswith("*/"):
                    return int(hour_part[2:]) * 3600
            return 4 * 3600  # Default: every 4 hours
        except Exception:
            return 4 * 3600
    
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
            # Day 21 — Mention-Only Protocol: one rule for all bots.
            # Process message only if it @mentions this bot's ID (or is a DM).
            policies["discord"] = ChannelPolicy(
                dm_policy=dc.dm_policy,
                group_policy="mention-only",  # kept for compat, router uses @mention check
                owner_ids=dc.authorized_users,
                allowed_senders=dc.dm_allowlist,
                self_id=dc.bot_user_id,
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
                    envelope.metadata.platform_message_id if envelope.metadata else envelope.id,
                )
            adapter.on_message(on_message)
            
            try:
                connect_config = {
                    "token": dc.token,
                    "bot_id": dc.bot_user_id,
                    "sibling_bot_ids": dc.sister_bot_ids,
                    "guild_ids": dc.guild_ids,
                    "alert_channels": self.config.immune.alert_channels,
                    "authorized_users": dc.authorized_users,
                }
                
                # Wire deployer if available (from _boot_deployer phase)
                if self.deployer:
                    connect_config["auto_deploy"] = True
                    connect_config["deployer"] = self.deployer
                
                await adapter.connect(connect_config)
                self.adapters["discord"] = adapter
                # Wire adapter to SINEW for discord_send/react tools
                if self.tools:
                    self.tools.set_discord_adapter(adapter)
                # ── Register with presence manager ──
                presence_manager.register_adapter(adapter.typing)
                if adapter.client:
                    presence_manager.register_discord_client(adapter.client)
                logger.info(f"  Discord adapter connected (deployer: {'yes' if self.deployer else 'no'})")
            except Exception as e:
                logger.error(f"  Discord adapter failed: {e}")
        else:
            logger.info("  Discord adapter skipped (no token)")
        
        # ── HTTP API Adapter ────────────────────────────────────────
        await self._boot_http_api()
    
    async def _boot_http_api(self) -> None:
        """Boot the HTTP API adapter for web/ERP integration."""
        api_key = os.environ.get("SINGULARITY_API_KEY", "")
        if not api_key:
            logger.info("  HTTP API skipped (no SINGULARITY_API_KEY)")
            return
        
        try:
            from .nerve.http_api import HttpApiAdapter
            
            http_adapter = HttpApiAdapter(
                port=8450,
                host="0.0.0.0",
                api_key=api_key,
                allowed_origins=["*"],
            )
            
            # Wire cortex processor directly
            if self.cortex:
                http_adapter.set_processor(self.cortex.process)
            
            await http_adapter.connect({})
            self.adapters["http"] = http_adapter
            logger.info("  HTTP API adapter ready (port 8450)")
        except Exception as e:
            logger.error(f"  HTTP API adapter failed: {e}")
    
    def _extract_exec_roles(self) -> list[tuple[str, str, str, str]]:
        """
        Extract exec roles from config personas for the GuildDeployer.
        
        Returns list of (role_id, emoji, title, domain) tuples.
        Maps persona names (CTO, COO, CFO, CISO, etc.) to role definitions.
        Uses explicit emoji/title/domain from config if set, otherwise
        falls back to _ROLE_DEFAULTS registry in csuite.roles.
        """
        from .csuite.roles import _ROLE_DEFAULTS
        
        # Standard C-Suite role names that should be deployed as channels
        
        _CSUITE_TITLE_MAP = {
            "cto": "Chief Technology Officer",
            "coo": "Chief Operating Officer",
            "cfo": "Chief Financial Officer",
            "ciso": "Chief Information Security Officer",
            "cro": "Chief Risk Officer",
            "cpo": "Chief Product Officer",
            "cmo": "Chief Marketing Officer",
            "cdo": "Chief Data Officer",
            "cco": "Chief Compliance Officer",
        }
        
        seen = set()
        exec_roles = []
        
        for persona in self.config.personas:
            role_id = persona.name.lower()
            if role_id in _CSUITE_NAMES and role_id not in seen:
                defaults = _ROLE_DEFAULTS.get(role_id, _ROLE_DEFAULTS.get("custom", {}))
                # Prefer explicit config values, fallback to role defaults
                emoji = persona.emoji or defaults.get("emoji", "👤")
                title = persona.title or _CSUITE_TITLE_MAP.get(role_id, f"Chief {role_id.upper()} Officer")
                domain = persona.domain or defaults.get("domain", "")
                exec_roles.append((role_id, emoji, title, domain))
                seen.add(role_id)
                logger.debug(f"  Exec role from config: {emoji} {title}")
        
        # Also check csuite.personas if any exist there
        for persona in self.config.csuite.personas:
            role_id = persona.name.lower()
            if role_id in _CSUITE_NAMES and role_id not in seen:
                defaults = _ROLE_DEFAULTS.get(role_id, _ROLE_DEFAULTS.get("custom", {}))
                emoji = persona.emoji or defaults.get("emoji", "👤")
                title = persona.title or _CSUITE_TITLE_MAP.get(role_id, f"Chief {role_id.upper()} Officer")
                domain = persona.domain or defaults.get("domain", "")
                exec_roles.append((role_id, emoji, title, domain))
                seen.add(role_id)
        
        return exec_roles
    
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
            from .immune.vitals import collect_vitals
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
        
        # Routed messages → CORTEX processing (NON-BLOCKING)
        # 
        # Architecture:
        #   - Different sessions run CONCURRENTLY (via asyncio.create_task)
        #   - Same-session messages SERIALIZE (via per-session asyncio.Lock)
        #   - Bus handler returns IMMEDIATELY (never blocks other events)
        #
        # This means: #dispatch, #cto, #bridge etc. all process in parallel.
        # But two rapid messages in #dispatch queue properly, preserving order.
        _session_locks: dict[str, asyncio.Lock] = {}
        _active_tasks: set[asyncio.Task] = set()

        async def _process_cortex(envelope) -> None:
            """Process a single routed message through cortex. Runs as independent task."""
            session_id = envelope.session_id or envelope.source.chat_id or "default"
            chat_id = envelope.source.chat_id

            # Per-session lock: same session serializes, different sessions parallel
            if session_id not in _session_locks:
                _session_locks[session_id] = asyncio.Lock()
            
            async with _session_locks[session_id]:
                # Start typing inside the lock — only when we're actually processing
                presence_manager.start_typing(chat_id)
                
                try:
                    result = await self.cortex.process(
                        session_id=session_id,
                        message=envelope.payload.text or "",
                        source=envelope.source,
                        sender_name=getattr(envelope.source, 'sender_name', ''),
                    )

                    # Send response back through the channel
                    if result and result.response:
                        sender_id = getattr(envelope.source, 'sender_id', None)
                        channel_type = envelope.source.channel_type or "discord"

                        # Stop typing — we're about to send
                        presence_manager.stop_typing(chat_id)

                        # Enforce @mention — structural, not prompt-dependent
                        response_text = _ensure_mention(
                            result.response, sender_id, channel_type
                        )

                        logger.info(
                            f"Sending response to {chat_id}: "
                            f"{len(response_text)} chars"
                        )

                        # Route to correct adapter by type
                        adapter = self.adapters.get(channel_type)
                        if adapter:
                            from .nerve.types import OutboundMessage
                            from .nerve.formatter import format_for_channel

                            chunks = format_for_channel(
                                response_text,
                                adapter.capabilities,
                            )
                            for chunk in chunks:
                                send_result = await adapter.send(chat_id, OutboundMessage(content=chunk))
                                logger.info(f"Send result: {send_result}")
                    else:
                        presence_manager.stop_typing(chat_id)
                        logger.warning(
                            f"No response from cortex for session {session_id[:12]}... "
                            f"(result={result is not None}, "
                            f"response={repr(result.response[:100]) if result and result.response else 'empty'})"
                        )

                except Exception as e:
                    presence_manager.stop_typing(chat_id)
                    logger.error(f"CORTEX processing error in {session_id[:12]}...: {e}")

        @self.bus.on("nerve.routed")
        async def on_routed(event):
            envelope = event.data.get("envelope")
            if not envelope:
                return
            
            if not self.cortex:
                return
            
            # Fire-and-forget: spawn a task so the bus handler returns immediately.
            # Different sessions process concurrently. Same-session messages
            # serialize via per-session lock (preserving message order).
            task = asyncio.create_task(
                _process_cortex(envelope),
                name=f"cortex:{(envelope.source.chat_id or 'unknown')[:16]}",
            )
            _active_tasks.add(task)
            task.add_done_callback(_active_tasks.discard)
        
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
        
        # ── Presence: tool lifecycle → Discord activity states ──────
        @self.bus.on("cortex.tool.executing")
        async def on_tool_start(event):
            tool_name = event.data.get("tool", "")
            presence_manager.tool_start(tool_name)
        
        @self.bus.on("cortex.tool.done")
        async def on_tool_done(event):
            tool_name = event.data.get("tool", "")
            presence_manager.tool_end(tool_name)
        
        @self.bus.on("cortex.llm.response")
        async def on_llm_response(event):
            presence_manager.llm_streaming()
        
                # C-Suite task completion → log and optionally report to channels
        @self.bus.on("csuite.task.completed")
        async def on_csuite_completed(event):
            data = event.data
            role = data.get("role", "?")
            status = data.get("status", "?")
            duration = data.get("duration_seconds", 0)
            logger.info(f"C-Suite task completed: {role} → {status} ({duration:.1f}s)")
        
        # C-Suite escalation → alert channel
        @self.bus.on("csuite.escalation.to_ava")
        async def on_csuite_escalation(event):
            data = event.data
            role = data.get("from", "?")
            reason = data.get("reason", "?")
            task_id = data.get("task_id", "?")
            msg = f"⚠️ C-Suite Escalation: {role.upper()} — {reason} (task {task_id})"
            logger.warning(msg)
            
            # Send alert to bridge channel
            alert_channels = self.config.immune.alert_channels
            if alert_channels and "discord" in self.adapters:
                from .nerve.types import OutboundMessage
                try:
                    await self.adapters["discord"].send(
                        alert_channels[0],
                        OutboundMessage(content=msg),
                    )
                except Exception as e:
                    logger.error(f"Escalation alert delivery failed: {e}")
        
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
        
        # Start dispatch inbox watcher (for external CLI dispatch)
        if self.dispatcher:
            asyncio.create_task(self._poll_dispatch_inbox())
        
        # Start ExfilGuard event relay watcher
        asyncio.create_task(self._poll_exfilguard_events())
        
        # Wait for shutdown signal
        await self._shutdown_event.wait()
        
        logger.info("Shutdown complete.")
    
    async def _poll_dispatch_inbox(self) -> None:
        """
        Poll .singularity/csuite/inbox/ for dispatch request files.
        External tools (AVA CLI, cron, etc.) drop JSON files here.
        Singularity picks them up, dispatches, writes results.
        """
        inbox = Path(self.workspace) / ".singularity" / "csuite" / "inbox"
        results_dir = Path(self.workspace) / ".singularity" / "csuite" / "results"
        inbox.mkdir(parents=True, exist_ok=True)
        results_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("Dispatch inbox watcher started")
        
        while self._running:
            try:
                # Check for request files
                for request_file in sorted(inbox.glob("*.json")):
                    try:
                        request = json.loads(request_file.read_text())
                        request_id = request_file.stem
                        
                        target = request.get("target", "auto")
                        # Accept both "description" and "task" field names
                        description = request.get("description", "") or request.get("task", "")
                        priority = request.get("priority", "normal")
                        max_iterations = request.get("max_iterations", 8)
                        
                        if not description:
                            logger.warning(f"Inbox: empty description in {request_file.name}, skipping")
                            request_file.unlink()
                            continue
                        
                        logger.info(f"Inbox: dispatching {request_id} → {target} (priority: {priority})")
                        
                        # Remove request file immediately (claimed)
                        request_file.unlink()
                        
                        # Dispatch
                        if target == "all":
                            result = await self.dispatcher.dispatch_all(
                                description=description, priority=priority,
                                max_iterations=max_iterations,
                            )
                        elif target == "auto":
                            result = await self.dispatcher.dispatch(
                                description=description, priority=priority,
                                max_iterations=max_iterations,
                            )
                        else:
                            result = await self.dispatcher.dispatch_to(
                                target=target, description=description, priority=priority,
                                max_iterations=max_iterations,
                            )
                        
                        # Write result
                        result_data = {
                            "request_id": request_id,
                            "dispatch_id": result.dispatch_id,
                            "all_succeeded": result.all_succeeded,
                            "duration": round(result.duration, 2),
                            "tasks": [
                                {
                                    "role": t.role,
                                    "status": t.status,
                                    "response": t.response,
                                    "iterations_used": t.iterations_used,
                                    "duration_seconds": round(t.duration_seconds, 2),
                                }
                                for t in result.tasks
                            ],
                        }
                        result_file = results_dir / f"{request_id}.json"
                        result_file.write_text(json.dumps(result_data, indent=2))
                        logger.info(f"Inbox: {request_id} complete → {result_file.name}")
                        
                    except Exception as e:
                        logger.error(f"Inbox: error processing {request_file.name}: {e}")
                        # Move bad files out
                        try:
                            request_file.rename(request_file.with_suffix(".error"))
                        except Exception:
                            request_file.unlink(missing_ok=True)
                
            except Exception as e:
                logger.error(f"Inbox watcher error: {e}")
            
            await asyncio.sleep(2)  # Poll every 2 seconds
    
    async def _poll_exfilguard_events(self) -> None:
        """
        Poll ExfilGuard event directory for Discord-bound alerts.
        ExfilGuard writes JSON event files → we read + forward to Discord → delete.
        """
        event_dir = Path(self.workspace) / ".singularity" / "events" / "exfilguard"
        event_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("ExfilGuard event relay started")
        
        while self._running:
            try:
                for event_file in sorted(event_dir.glob("*.json")):
                    try:
                        event = json.loads(event_file.read_text())
                        event_type = event.get("event", "")
                        
                        if event_type == "discord.send":
                            channel_id = event.get("channel_id")
                            message = event.get("message", "")
                            
                            if channel_id and message and self.adapters.get("discord"):
                                from .nerve.models import OutboundMessage
                                adapter = self.adapters["discord"]
                                await adapter.send_message(
                                    channel_id,
                                    OutboundMessage(content=message)
                                )
                                logger.info(f"ExfilGuard alert forwarded to Discord #{channel_id}")
                        
                        elif event_type == "security.alert":
                            # Emit on internal bus for other subsystems
                            severity = event.get("severity", "INFO")
                            await self.bus.emit("security.exfilguard", event)
                            
                            # Also forward CRITICAL/HIGH to Discord #dispatch
                            if severity in ("CRITICAL", "HIGH") and self.adapters.get("discord"):
                                from .nerve.models import OutboundMessage
                                payload = event.get("payload", {})
                                msg = (
                                    f"**[{severity}] ExfilGuard Security Alert**\n"
                                    f"```\n"
                                    f"Type: {payload.get('type', '?')}\n"
                                    f"IP:   {payload.get('ip', '?')}\n"
                                    f"rDNS: {payload.get('rdns', '?')}\n"
                                    f"```"
                                )
                                adapter = self.adapters["discord"]
                                # Forward to dispatch + security channels
                                for ch_id in ("1478716096667189292", "1328051692167762034"):
                                    await adapter.send_message(
                                        ch_id,
                                        OutboundMessage(content=msg)
                                    )
                        
                        # Processed — delete
                        event_file.unlink()
                        
                    except json.JSONDecodeError:
                        logger.warning(f"ExfilGuard: invalid JSON in {event_file.name}")
                        event_file.unlink()
                    except Exception as e:
                        logger.debug(f"ExfilGuard event relay error on {event_file.name}: {e}")
                        # Don't delete — may be transient
                        
            except Exception as e:
                logger.error(f"ExfilGuard event watcher error: {e}")
            
            await asyncio.sleep(5)  # Poll every 5 seconds
    
    async def shutdown(self) -> None:
        """Gracefully shut down all subsystems."""
        if not self._running:
            return
        self._running = False
        
        logger.info("Shutting down...")
        
        # Stop presence manager first (clean up typing indicators)
        presence_manager.stop_all()
        
        # Stop in reverse order
        for name, adapter in self.adapters.items():
            try:
                await adapter.disconnect()
                logger.info(f"  Adapter {name} disconnected")
            except Exception as e:
                logger.error(f"  Adapter {name} disconnect error: {e}")
        
        if self.coordinator:
            await self.coordinator.stop()
        
        if self.watchdog:
            await self.watchdog.stop()
        
        if self._nexus_daemon:
            await self._nexus_daemon.stop()

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
