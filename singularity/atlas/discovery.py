"""
ATLAS — Discovery Engine
===========================

Auto-discovers all enterprise modules by scanning:
  - systemd services (user + system)
  - listening ports (ss -tlnp)
  - nginx configs (sites-enabled → backend mapping)
  - cloudflare tunnel config (public hostnames)
  - process table (resource usage)
  - remote machines (SSH probe to Victus)
  - known filesystem paths

No manual registration. If it exists, ATLAS finds it.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .topology import (
    Module, ModuleType, ModuleStatus, ProcessInfo, PortInfo,
    ServiceInfo, HealthResult, Edge, EdgeType, TopologyGraph,
)

logger = logging.getLogger("singularity.atlas.discovery")

# ── Known Module Registry ────────────────────────────────────
# Hints for classification — maps patterns to module types and metadata.
# Discovery still finds things NOT in this list (classified as UNKNOWN).

KNOWN_MODULES: dict[str, dict[str, Any]] = {
    # Agents
    "singularity": {
        "type": ModuleType.AGENT,
        "service": "singularity",
        "ports": [8450],
        "health": None,
        "deps": ["copilot-proxy", "discord-api", "hektor-daemon", "postgresql"],
    },
    "mach6-gateway": {
        "type": ModuleType.AGENT,
        "service": "mach6-gateway",
        "ports": [3006, 3009],
        "health": None,
        "config": "/opt/ava/mach6.json",
        "deps": ["copilot-proxy", "discord-api", "hektor-daemon"],
        "aliases": ["ava", "mach6"],
    },
    "aria": {
        "type": ModuleType.AGENT,
        "service": "aria",
        "ports": [3007, 3010],
        "health": None,
        "config": "/opt/aria/mach6.json",
        "deps": ["copilot-proxy", "discord-api"],
        "aliases": ["aria-gateway"],
    },
    "scarlet": {
        "type": ModuleType.AGENT,
        "machine": "victus",
        "ports": [3006, 3009],
        "config": "C:\\Users\\noufe\\ai-workspace\\mach6.json",
        "deps": ["copilot-proxy"],
    },
    # Gateways
    "copilot-proxy": {
        "type": ModuleType.GATEWAY,
        "service": "copilot-proxy",
        "ports": [3000],
        "deps": [],
    },
    # Services
    "comb-cloud": {
        "type": ModuleType.SERVICE,
        "service": "comb-cloud",
        "ports": [8420],
        "health": "http://localhost:8420/health",
        "public_urls": ["comb.artifactvirtual.com", "comb-api.artifactvirtual.com"],
        "deps": [],
    },
    "mach6-cloud": {
        "type": ModuleType.SERVICE,
        "service": "mach6-cloud",
        "ports": [8430],
        "health": "http://localhost:8430/health",
        "public_urls": ["mach6.artifactvirtual.com", "mach6-api.artifactvirtual.com"],
        "deps": [],
    },
    "artifact-erp": {
        "type": ModuleType.SERVICE,
        "service": "artifact-erp",
        "ports": [3100],
        "health": "http://localhost:3100/health",
        "public_urls": ["erp.artifactvirtual.com"],
        "deps": ["postgresql", "singularity"],
    },
    "gdi-backend": {
        "type": ModuleType.SERVICE,
        "service": "gdi-backend",
        "ports": [8600],
        "health": "http://localhost:8600/health",
        "public_urls": ["gdi.artifactvirtual.com"],
        "deps": ["postgresql"],
        "aliases": ["gdi"],
    },
    "artifact-social": {
        "type": ModuleType.SERVICE,
        "service": "artifact-social",
        "ports": [3200],
        "public_urls": ["social.artifactvirtual.com"],
        "deps": [],
    },
    # Daemons
    "cthulu-daemon": {
        "type": ModuleType.DAEMON,
        "service": "cthulu-daemon",
        "ports": [9002],
        "health": "http://localhost:9002/health",
        "deps": [],
    },
    "hektor-daemon": {
        "type": ModuleType.DAEMON,
        "service": "hektor-daemon",
        "ports": [20241],
        "deps": [],
    },
    "sentinel": {
        "type": ModuleType.DAEMON,
        "service": "sentinel",
        "deps": [],
        "aliases": ["exfil-guard"],
    },
    # Infrastructure
    "nginx": {
        "type": ModuleType.INFRASTRUCTURE,
        "ports": [80],
        "deps": [],
    },
    "cloudflared": {
        "type": ModuleType.INFRASTRUCTURE,
        "service": "cloudflared",
        "deps": ["nginx"],
    },
    "postgresql": {
        "type": ModuleType.INFRASTRUCTURE,
        "ports": [5432],
        "deps": [],
    },
    "ollama": {
        "type": ModuleType.INFRASTRUCTURE,
        "ports": [11434],
        "health": "http://localhost:11434/",
        "deps": [],
    },
    "redis": {
        "type": ModuleType.INFRASTRUCTURE,
        "ports": [6379],
        "deps": [],
        "aliases": ["redis-server"],
    },
}

# Classify unknown services by pattern
SERVICE_PATTERNS: list[tuple[str, ModuleType]] = [
    (r"mach6|gateway|daemon\.js", ModuleType.GATEWAY),
    (r"singularity|aria|scarlet|ava", ModuleType.AGENT),
    (r"sentinel|exfil|openant", ModuleType.DAEMON),
    (r"nginx|cloudflare|postgres|redis|ollama|surreal", ModuleType.INFRASTRUCTURE),
    (r"erp|gdi|comb|social|cloud", ModuleType.SERVICE),
]


class DiscoveryEngine:
    """
    Scans the enterprise to discover all running modules.
    Returns a list of Module objects for the TopologyGraph.
    """

    def __init__(self, victus_host: str = "victus"):
        self.victus_host = victus_host
        self._victus_reachable: bool = False

    async def run_full_scan(self) -> tuple[list[Module], list[Edge]]:
        """Execute a complete discovery scan. Returns (modules, edges)."""
        logger.info("ATLAS Discovery: starting full scan...")
        start = datetime.datetime.now(datetime.timezone.utc)

        modules: dict[str, Module] = {}
        edges: list[Edge] = []

        # Run independent scans concurrently
        systemd_mods, port_mods, proc_mods = await asyncio.gather(
            self._scan_systemd(),
            self._scan_ports(),
            self._scan_processes(),
            return_exceptions=True,
        )

        # Merge results (port/proc enrich systemd modules)
        if isinstance(systemd_mods, list):
            for m in systemd_mods:
                modules[m.id] = m
        else:
            logger.debug(f"Suppressed systemd scan error: {systemd_mods}")

        if isinstance(port_mods, list):
            for m in port_mods:
                if m.id in modules:
                    # Enrich existing module with port info
                    modules[m.id].ports = m.ports
                    if m.process.pid:
                        modules[m.id].process = m.process
                else:
                    modules[m.id] = m
        else:
            logger.debug(f"Suppressed port scan error: {port_mods}")

        if isinstance(proc_mods, list):
            for m in proc_mods:
                if m.id in modules:
                    # Enrich with resource data
                    modules[m.id].resources = m.resources
                    if m.process.pid and not modules[m.id].process.pid:
                        modules[m.id].process = m.process
                else:
                    modules[m.id] = m
        else:
            logger.debug(f"Suppressed process scan error: {proc_mods}")

        # Sequential scans (depend on filesystem)
        try:
            nginx_edges = await self._scan_nginx()
            edges.extend(nginx_edges)
        except Exception as e:
            logger.debug(f"Suppressed nginx scan error: {e}")

        try:
            tunnel_mods = await self._scan_cloudflare_tunnel()
            for m in tunnel_mods:
                if m.id in modules:
                    modules[m.id].public_urls = m.public_urls
                else:
                    modules[m.id] = m
        except Exception as e:
            logger.debug(f"Suppressed tunnel scan error: {e}")

        # Enrich with known module metadata
        self._enrich_known_modules(modules, edges)

        # Check Victus (SSH probe)
        try:
            victus_mods = await self._scan_victus()
            for m in victus_mods:
                modules[m.id] = m
        except Exception as e:
            logger.debug(f"Suppressed Victus scan: {e}")

        # Health checks for modules with endpoints
        await self._check_health(list(modules.values()))

        # Compute status for each module
        for mod in modules.values():
            mod.status = self._compute_status(mod)

        elapsed = (datetime.datetime.now(datetime.timezone.utc) - start).total_seconds()
        logger.info(f"ATLAS Discovery: found {len(modules)} modules, {len(edges)} edges in {elapsed:.1f}s")

        return list(modules.values()), edges

    # ── Scanners ─────────────────────────────────────────────

    async def _scan_systemd(self) -> list[Module]:
        """Scan systemd for all active services (user + system)."""
        modules = []

        for scope in ["--user", "--system"]:
            try:
                cmd = f"systemctl {scope} list-units --type=service --state=active --no-pager --plain --no-legend"
                result = await self._run(cmd)
                for line in result.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    unit = parts[0].replace(".service", "")

                    # Skip noise
                    if any(skip in unit for skip in [
                        "dbus", "gpg-agent", "systemd-", "ssh-agent",
                        "pulseaudio", "pipewire", "xdg-", "at-spi",
                        "gnome-", "gvfs-", "evolution-", "tracker-",
                        "snap.", "plymouth", "ModemManager",
                        "NetworkManager", "accounts-daemon",
                        "colord", "fwupd", "pkttyagent",
                        "polkit", "rtkit", "udisks", "upower",
                        "wpa_supplicant", "avahi", "cups",
                        "thermald", "bolt", "switcheroo",
                        # OS/desktop noise
                        "console-setup", "containerd", "cron",
                        "dconf", "docker", "filter-chain",
                        "getty@", "haveged", "ifupdown",
                        "irqbalance", "keyboard-setup", "kmod-",
                        "lightdm", "mpris-proxy", "networking",
                        "obex", "pcscd", "rpc-statd",
                        "smartmontools", "tlp", "unattended-upgrades",
                        "user-runtime-dir@", "user@",
                        "wireplumber", "xfce4-", "mosquitto",
                        "bunker-chat", "tesseract",
                    ]):
                        continue

                    mod_id = self._normalize_id(unit)
                    svc_info = await self._get_service_info(unit, scope)

                    # Use known name if available, otherwise raw unit name
                    display_name = KNOWN_MODULES.get(mod_id, {}).get("service", unit) if mod_id in KNOWN_MODULES else unit

                    mod = Module(
                        id=mod_id,
                        name=display_name,
                        type=self._classify_unit(mod_id),
                        machine="dragonfly",
                        service=svc_info,
                    )
                    modules.append(mod)
            except Exception as e:
                logger.debug(f"Suppressed systemd {scope} scan error: {e}")

        return modules

    async def _scan_ports(self) -> list[Module]:
        """Scan listening TCP ports."""
        modules = []
        try:
            result = await self._run("ss -tlnp 2>/dev/null")
            for line in result.strip().split("\n"):
                if "LISTEN" not in line:
                    continue
                # Parse: LISTEN  0  128  0.0.0.0:3006  0.0.0.0:*  users:(("node",pid=123,fd=4))
                parts = line.split()
                if len(parts) < 5:
                    continue

                local = parts[3]
                # Extract port
                port_match = re.search(r":(\d+)$", local)
                if not port_match:
                    continue
                port = int(port_match.group(1))
                binding = local.rsplit(":", 1)[0]

                # Extract PID and process name
                pid = 0
                pname = ""
                pid_match = re.search(r'pid=(\d+)', line)
                name_match = re.search(r'\("([^"]+)"', line)
                if pid_match:
                    pid = int(pid_match.group(1))
                if name_match:
                    pname = name_match.group(1)

                # Map port to known module
                mod_id = self._port_to_module_id(port, pname)
                if not mod_id:
                    # Skip unknown ports — they're noise (ephemeral, OS, etc.)
                    continue

                mod = Module(
                    id=mod_id,
                    name=pname or f"port-{port}",
                    machine="dragonfly",
                    ports=[PortInfo(port=port, binding=binding, pid=pid)],
                    process=ProcessInfo(pid=pid, command=pname),
                )
                modules.append(mod)
        except Exception as e:
            logger.debug(f"Suppressed port scan error: {e}")

        return modules

    async def _scan_processes(self) -> list[Module]:
        """Scan process table for resource usage of known services."""
        modules = []
        try:
            # Get top memory consumers
            result = await self._run(
                "ps aux --sort=-%mem | head -30"
            )
            for line in result.strip().split("\n")[1:]:  # Skip header
                parts = line.split(None, 10)
                if len(parts) < 11:
                    continue
                user, pid_s, cpu, mem = parts[0], parts[1], parts[2], parts[3]
                rss_s = parts[5]  # RSS in KB
                cmd = parts[10]

                try:
                    pid = int(pid_s)
                    rss_mb = int(rss_s) / 1024
                    cpu_pct = float(cpu)
                except (ValueError, IndexError) as e:
                    logger.debug(f"Suppressed (ValueError, IndexError): {e}")
                    continue

                # Only track processes using >50MB
                if rss_mb < 50:
                    continue

                mod_id = self._cmd_to_module_id(cmd)
                if not mod_id:
                    continue

                mod = Module(
                    id=mod_id,
                    name=mod_id,
                    machine="dragonfly",
                    process=ProcessInfo(
                        pid=pid,
                        command=cmd[:200],
                        user=user,
                        rss_mb=round(rss_mb, 1),
                        cpu_pct=cpu_pct,
                    ),
                    resources={
                        "rss_mb": round(rss_mb, 1),
                        "cpu_pct": cpu_pct,
                    },
                )
                modules.append(mod)
        except Exception as e:
            logger.debug(f"Suppressed process scan error: {e}")

        return modules

    async def _scan_nginx(self) -> list[Edge]:
        """Parse nginx configs to find proxy mappings."""
        edges = []
        nginx_dir = Path("/etc/nginx/sites-enabled")
        if not nginx_dir.exists():
            return edges

        try:
            for conf_file in nginx_dir.iterdir():
                if conf_file.is_symlink() or conf_file.is_file():
                    content = conf_file.read_text()
                    # Find server_name and proxy_pass pairs
                    server_names = re.findall(r"server_name\s+([^;]+);", content)
                    proxy_passes = re.findall(r"proxy_pass\s+http://(?:localhost|127\.0\.0\.1):(\d+)", content)
                    listen_ports = re.findall(r"listen\s+(\d+)", content)

                    for proxy_port in proxy_passes:
                        port = int(proxy_port)
                        target = self._port_to_module_id(port)
                        if target:
                            edge = Edge(
                                source="nginx",
                                target=target,
                                type=EdgeType.PROXIES_TO,
                                port=port,
                                label=", ".join(server_names).strip(),
                                verified=True,
                            )
                            edges.append(edge)
        except Exception as e:
            logger.debug(f"Suppressed nginx scan error: {e}")

        return edges

    async def _scan_cloudflare_tunnel(self) -> list[Module]:
        """Parse cloudflare tunnel config for public hostname mappings."""
        modules = []
        tunnel_config = Path.home() / ".cloudflared" / "config.yml"
        if not tunnel_config.exists():
            return modules

        try:
            content = tunnel_config.read_text()
            # Find hostname → service mappings
            # Format: - hostname: xxx.artifactvirtual.com
            #           service: http://localhost:PORT
            hostnames = re.findall(r"hostname:\s*(\S+)", content)
            services = re.findall(r"service:\s*http://localhost:(\d+)", content)

            for hostname, port_str in zip(hostnames, services):
                port = int(port_str)
                mod_id = self._port_to_module_id(port)
                if mod_id:
                    mod = Module(
                        id=mod_id,
                        name=mod_id,
                        public_urls=[hostname],
                    )
                    modules.append(mod)
        except Exception as e:
            logger.debug(f"Suppressed tunnel scan error: {e}")

        return modules

    async def _scan_victus(self) -> list[Module]:
        """SSH probe to Victus for Scarlet + MT5 status."""
        modules = []
        try:
            # Quick connectivity check (2s timeout)
            result = await self._run(
                f"ssh -o ConnectTimeout=2 -o BatchMode=yes {self.victus_host} "
                "'powershell -Command \"Get-Process node -ErrorAction SilentlyContinue | "
                "Select-Object Id,WorkingSet64,CPU | ConvertTo-Json\"'",
                timeout=5,
            )

            if result.strip():
                self._victus_reachable = True
                # Parse node processes on Victus
                try:
                    procs = json.loads(result)
                    if isinstance(procs, dict):
                        procs = [procs]
                    for proc in procs:
                        pid = proc.get("Id", 0)
                        rss_mb = round(proc.get("WorkingSet64", 0) / 1024 / 1024, 1)
                        mod = Module(
                            id="scarlet",
                            name="Scarlet (Victus)",
                            type=ModuleType.AGENT,
                            machine="victus",
                            process=ProcessInfo(
                                pid=pid,
                                command="node daemon.js",
                                rss_mb=rss_mb,
                            ),
                            ports=[PortInfo(port=3006), PortInfo(port=3009)],
                            config_path="C:\\Users\\noufe\\ai-workspace\\mach6.json",
                            resources={"rss_mb": rss_mb},
                        )
                        modules.append(mod)
                        break  # Only first node process = Scarlet
                except json.JSONDecodeError as e:
                    logger.debug(f"Suppressed json.JSONDecodeError: {e}")

            # Check MT5
            mt5_result = await self._run(
                f"ssh -o ConnectTimeout=2 -o BatchMode=yes {self.victus_host} "
                "'powershell -Command \"Get-Process terminal64 -ErrorAction SilentlyContinue | "
                "Select-Object Id | ConvertTo-Json\"'",
                timeout=5,
            )
            if mt5_result.strip() and "null" not in mt5_result.lower():
                modules.append(Module(
                    id="mt5-terminal",
                    name="MetaTrader 5 (Victus)",
                    type=ModuleType.INFRASTRUCTURE,
                    machine="victus",
                    metadata={"role": "tick-source-for-cthulu"},
                ))
        except Exception as e:
            self._victus_reachable = False
            logger.debug(f"Suppressed Victus scan: {e}")

        return modules

    async def _check_health(self, modules: list[Module]) -> None:
        """Run health checks on modules that have health endpoints."""
        import aiohttp

        checks = []
        for mod in modules:
            endpoint = mod.health_endpoint
            if not endpoint:
                # Check known modules
                known = KNOWN_MODULES.get(mod.id, {})
                endpoint = known.get("health")
            if not endpoint:
                continue

            checks.append((mod, endpoint))

        if not checks:
            return

        timeout = aiohttp.ClientTimeout(total=5)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                tasks = [self._health_check(session, mod, url) for mod, url in checks]
                await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.debug(f"Suppressed health check session error: {e}")

    async def _health_check(self, session: Any, mod: Module, url: str) -> None:
        """Single health check for a module."""
        import time as _time
        start = _time.monotonic()
        try:
            async with session.get(url) as resp:
                latency = (_time.monotonic() - start) * 1000
                mod.health_endpoint = url
                mod.health_result = HealthResult(
                    url=url,
                    status_code=resp.status,
                    latency_ms=round(latency, 1),
                    healthy=200 <= resp.status < 400,
                    checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                )
        except Exception as e:
            latency = (_time.monotonic() - start) * 1000
            mod.health_result = HealthResult(
                url=url,
                status_code=0,
                latency_ms=round(latency, 1),
                healthy=False,
                error=str(e)[:200],
                checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )

    # ── Helpers ───────────────────────────────────────────────

    def _enrich_known_modules(self, modules: dict[str, Module], edges: list[Edge]) -> None:
        """Enrich discovered modules with known metadata and add dependency edges."""
        for mod_id, known in KNOWN_MODULES.items():
            if mod_id in modules:
                mod = modules[mod_id]
                if mod.type == ModuleType.UNKNOWN:
                    mod.type = known.get("type", ModuleType.UNKNOWN)
                if not mod.health_endpoint and known.get("health"):
                    mod.health_endpoint = known["health"]
                if not mod.public_urls and known.get("public_urls"):
                    mod.public_urls = known["public_urls"]
                if not mod.config_path and known.get("config"):
                    mod.config_path = known["config"]
                if not mod.dependencies:
                    mod.dependencies = known.get("deps", [])

                # Add dependency edges
                for dep in known.get("deps", []):
                    edges.append(Edge(
                        source=mod_id,
                        target=dep,
                        type=EdgeType.DEPENDS_ON,
                        verified=(dep in modules),
                    ))

    def _normalize_id(self, unit_name: str) -> str:
        """Normalize a systemd unit name to a module ID."""
        # Check known module aliases and service names
        for mod_id, known in KNOWN_MODULES.items():
            if unit_name == mod_id or unit_name == known.get("service"):
                return mod_id
            for alias in known.get("aliases", []):
                if unit_name == alias:
                    return mod_id
        # Fuzzy match — check if unit contains a known module id
        for mod_id in KNOWN_MODULES:
            if mod_id in unit_name or unit_name in mod_id:
                return mod_id
        return unit_name

    def _classify_unit(self, unit_name: str) -> ModuleType:
        """Classify a systemd unit by name pattern."""
        known = KNOWN_MODULES.get(unit_name)
        if known:
            return known.get("type", ModuleType.UNKNOWN)

        for pattern, mod_type in SERVICE_PATTERNS:
            if re.search(pattern, unit_name, re.IGNORECASE):
                return mod_type

        return ModuleType.UNKNOWN

    def _port_to_module_id(self, port: int, pname: str = "") -> str | None:
        """Map a port number to a known module ID."""
        # Nginx proxy ports → attribute to nginx (not separate modules)
        NGINX_PROXY_PORTS = {8700, 8701, 8750, 8760, 8761}
        if port in NGINX_PROXY_PORTS:
            return "nginx"

        # Singularity HTTP API
        if port == 8450:
            return "singularity"

        for mod_id, known in KNOWN_MODULES.items():
            if port in known.get("ports", []):
                return mod_id
        # Fallback: try process name
        if pname:
            for mod_id, known in KNOWN_MODULES.items():
                for alias in [mod_id] + known.get("aliases", []):
                    if alias in pname.lower():
                        return mod_id
        return None

    def _cmd_to_module_id(self, cmd: str) -> str | None:
        """Map a process command line to a module ID."""
        cmd_lower = cmd.lower()
        for mod_id, known in KNOWN_MODULES.items():
            # Check config paths
            config = known.get("config", "")
            if config and config.lower() in cmd_lower:
                return mod_id
            # Check service name
            svc = known.get("service", "")
            if svc and svc in cmd_lower:
                return mod_id
            # Check aliases
            for alias in known.get("aliases", []):
                if alias in cmd_lower:
                    return mod_id
            # Check the module ID itself
            if mod_id in cmd_lower:
                return mod_id

        # Heuristic matches
        if "hektor" in cmd_lower or "ava_memory" in cmd_lower:
            return "hektor-daemon"
        if "cthulu" in cmd_lower or "main_multi" in cmd_lower:
            return "cthulu-daemon"
        if "copilot" in cmd_lower and "proxy" in cmd_lower:
            return "copilot-proxy"
        if "singularity" in cmd_lower and "runtime" in cmd_lower:
            return "singularity"
        if "/opt/ava/" in cmd_lower or "mach6.json" in cmd_lower:
            return "mach6-gateway"
        if "/opt/aria/" in cmd_lower or "aria" in cmd_lower:
            return "aria"
        if "artifact-erp" in cmd_lower or "artifact_erp" in cmd_lower or "business_erp" in cmd_lower:
            return "artifact-erp"
        if "http_api" in cmd_lower and "singularity" in cmd_lower:
            return "singularity"
        if "sentinel" in cmd_lower or "exfil" in cmd_lower:
            return "sentinel"
        if "ollama" in cmd_lower:
            return "ollama"
        if "postgres" in cmd_lower:
            return "postgresql"
        if "nginx" in cmd_lower:
            return "nginx"
        if "cloudflared" in cmd_lower:
            return "cloudflared"
        if "redis" in cmd_lower:
            return "redis"
        if "artifact.social" in cmd_lower or "artifact-social" in cmd_lower:
            return "artifact-social"

        return None

    async def _get_service_info(self, unit: str, scope: str) -> ServiceInfo:
        """Get detailed service info from systemctl."""
        try:
            result = await self._run(
                f"systemctl {scope} show {unit}.service "
                f"--property=ActiveState,SubState,UnitFileState --no-pager 2>/dev/null"
            )
            props = {}
            for line in result.strip().split("\n"):
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k] = v

            return ServiceInfo(
                unit_name=f"{unit}.service",
                active=props.get("ActiveState") == "active",
                enabled=props.get("UnitFileState") in ("enabled", "enabled-runtime"),
                sub_state=props.get("SubState", ""),
            )
        except Exception:
            return ServiceInfo(unit_name=f"{unit}.service")

    @staticmethod
    async def _run(cmd: str, timeout: int = 10) -> str:
        """Run a shell command asynchronously."""
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return stdout.decode(errors="replace")
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
            return ""
        except Exception as e:
            logger.debug(f"Suppressed command error ({cmd[:50]}): {e}")
            return ""

    def _compute_status(self, mod: Module) -> ModuleStatus:
        """Compute overall module status from available signals."""
        signals = []

        # Service state
        if mod.service.unit_name:
            if mod.service.active:
                signals.append("svc_up")
            else:
                signals.append("svc_down")

        # Health endpoint
        if mod.health_result.checked_at:
            if mod.health_result.healthy:
                signals.append("health_ok")
            else:
                signals.append("health_fail")

        # Process
        if mod.process.pid:
            signals.append("proc_alive")

        # Evaluate
        if "svc_down" in signals or "health_fail" in signals:
            if "proc_alive" in signals:
                return ModuleStatus.DEGRADED
            return ModuleStatus.DOWN
        if "svc_up" in signals or "health_ok" in signals or "proc_alive" in signals:
            return ModuleStatus.HEALTHY
        return ModuleStatus.UNKNOWN

    async def collect_host_resources(self) -> dict[str, dict]:
        """Collect host-level resource metrics for all machines."""
        hosts: dict[str, dict] = {}

        # --- Dragonfly (local) ---
        try:
            mem = await self._run("free -m | awk '/Mem:/{print $2,$3,$7} /Swap:/{print $2,$3}'")
            lines = mem.strip().split("\n")
            if len(lines) >= 2:
                mem_parts = lines[0].split()
                swap_parts = lines[1].split()
                total_mb = int(mem_parts[0]) if mem_parts else 0
                used_mb = int(mem_parts[1]) if len(mem_parts) > 1 else 0
                avail_mb = int(mem_parts[2]) if len(mem_parts) > 2 else 0
                swap_total = int(swap_parts[0]) if swap_parts else 0
                swap_used = int(swap_parts[1]) if len(swap_parts) > 1 else 0
            else:
                total_mb = used_mb = avail_mb = swap_total = swap_used = 0

            load = await self._run("cat /proc/loadavg")
            load_1 = float(load.split()[0]) if load else 0.0

            disk = await self._run("df -BG / | awk 'NR==2{print $2,$3,$4,$5}'")
            disk_parts = disk.strip().split() if disk else []
            disk_total = disk_parts[0].rstrip("G") if disk_parts else "0"
            disk_used = disk_parts[1].rstrip("G") if len(disk_parts) > 1 else "0"
            disk_pct = disk_parts[3].rstrip("%") if len(disk_parts) > 3 else "0"

            hosts["dragonfly"] = {
                "ram_total_mb": total_mb,
                "ram_used_mb": used_mb,
                "ram_avail_mb": avail_mb,
                "ram_pct": round((used_mb / total_mb * 100), 1) if total_mb else 0,
                "swap_total_mb": swap_total,
                "swap_used_mb": swap_used,
                "swap_pct": round((swap_used / swap_total * 100), 1) if swap_total else 0,
                "load_1m": load_1,
                "disk_total_gb": int(disk_total) if disk_total.isdigit() else 0,
                "disk_used_gb": int(disk_used) if disk_used.isdigit() else 0,
                "disk_pct": int(disk_pct) if disk_pct.isdigit() else 0,
            }
        except Exception as e:
            logger.debug(f"Suppressed dragonfly resource collection: {e}")

        # --- Victus (SSH) ---
        try:
            out = await self._run(f"ssh -o ConnectTimeout=3 {self._victus_host} 'wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /value' 2>/dev/null", timeout=5)
            if "TotalVisibleMemorySize" in out:
                vals = {}
                for line in out.strip().split("\n"):
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        vals[k.strip()] = v.strip()
                total_kb = int(vals.get("TotalVisibleMemorySize", "0"))
                free_kb = int(vals.get("FreePhysicalMemory", "0"))
                total_mb = total_kb // 1024
                free_mb = free_kb // 1024
                used_mb = total_mb - free_mb
                hosts["victus"] = {
                    "ram_total_mb": total_mb,
                    "ram_used_mb": used_mb,
                    "ram_avail_mb": free_mb,
                    "ram_pct": round((used_mb / total_mb * 100), 1) if total_mb else 0,
                }
        except Exception as e:
            logger.debug(f"Suppressed victus resource collection: {e}")

        return hosts
