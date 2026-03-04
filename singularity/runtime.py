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
        
        if not self.config.csuite.enabled:
            logger.info("  CSUITE disabled in config")
            return
        
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
            
            # Create the executive
            executive = Executive(
                role=role,
                bus=self.bus,
                provider_chain=self.voice,
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
        
        # Check both enterprise and local workspaces for POAs
        poa_dirs = []
        enterprise_poa = Path("/home/adam/workspace/enterprise/.singularity/poas")
        local_poa = Path(self.config.tools.workspace) / ".singularity" / "poas"
        
        if enterprise_poa.exists():
            poa_dirs.append(enterprise_poa.parent)
        if local_poa.exists() and local_poa != enterprise_poa:
            poa_dirs.append(local_poa.parent)
        
        if not poa_dirs:
            logger.info("  POA: No POA directories found, skipping")
            return
        
        total_poas = 0
        total_jobs = 0
        
        for workspace in poa_dirs:
            manager = POAManager(workspace)
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
                    else:
                        logger.info(f"POA audit: {cfg.product_name} → {report.overall_status.upper()}")
                        
                except Exception as e:
                    logger.error(f"POA audit failed for {product_id}: {e}")
        
        # Also run first audit immediately for all active POAs
        if total_poas > 0:
            asyncio.create_task(self._run_initial_poa_audits(poa_dirs))
        
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
                logger.info(f"  Discord adapter connected (deployer: {'yes' if self.deployer else 'no'})")
            except Exception as e:
                logger.error(f"  Discord adapter failed: {e}")
        else:
            logger.info("  Discord adapter skipped (no token)")
    
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
        
        # Routed messages → CORTEX processing
        @self.bus.on("nerve.routed")
        async def on_routed(event):
            envelope = event.data.get("envelope")
            if not envelope:
                return
            
            session_id = envelope.session_id or envelope.source.chat_id or "default"
            
            # Send typing indicator so the user knows we're processing
            adapter_type = envelope.source.channel_type or "discord"
            adapter = self.adapters.get(adapter_type)
            if adapter:
                try:
                    await adapter.typing(envelope.source.chat_id)
                except Exception as e:
                    logger.debug(f"Suppressed: {e}")
            
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
                        sender_id = getattr(envelope.source, 'sender_id', None)
                        channel_type = envelope.source.channel_type or "discord"
                        
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
                        logger.warning(
                            f"No response from cortex for session {session_id[:12]}... "
                            f"(result={result is not None}, "
                            f"response={repr(result.response[:100]) if result and result.response else 'empty'})"
                        )
                
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
                        description = request.get("description", "")
                        priority = request.get("priority", "normal")
                        
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
                            )
                        elif target == "auto":
                            result = await self.dispatcher.dispatch(
                                description=description, priority=priority,
                            )
                        else:
                            result = await self.dispatcher.dispatch_to(
                                target=target, description=description, priority=priority,
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
        
        if self.coordinator:
            await self.coordinator.stop()
        
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
