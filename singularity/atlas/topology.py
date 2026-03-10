"""
ATLAS — Topology Graph (Data Models)
======================================

Core data structures for the enterprise topology.
Every discovered service, agent, or component becomes a Module.
Connections between them become Edges.
"""

from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("singularity.atlas.topology")


# ── Enums ────────────────────────────────────────────────────

class ModuleType(str, Enum):
    AGENT = "agent"                    # Singularity, AVA, Aria, Scarlet
    GATEWAY = "gateway"                # Mach6 Gateway, Copilot Proxy
    SERVICE = "service"                # COMB Cloud, Mach6 Cloud, ERP, GDI
    DAEMON = "daemon"                  # Cthulu, HEKTOR, Sentinel
    INFRASTRUCTURE = "infrastructure"  # Nginx, Cloudflared, PostgreSQL, Redis, Ollama
    SUPPORT = "support"                # PULSE, NEXUS, Event Bus
    UNKNOWN = "unknown"


class ModuleStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"     # Up but issues (high RAM, slow response, log bloat)
    DOWN = "down"             # Process dead or health failing
    STALE = "stale"           # Not seen for 3+ cycles
    GONE = "gone"             # Not seen for 10+ cycles — removed from active graph
    UNKNOWN = "unknown"


class EdgeType(str, Enum):
    DEPENDS_ON = "depends_on"          # Hard dependency (ERP → PostgreSQL)
    PROXIES_TO = "proxies_to"          # Nginx → backend, Cloudflare → nginx
    FEEDS_DATA = "feeds_data"          # MT5 → Cthulu webhook
    SHARES_RESOURCE = "shares_resource"  # Multiple services → Copilot Proxy
    MONITORS = "monitors"              # Sentinel → everything


class IssueSeverity(str, Enum):
    CRITICAL = "critical"  # Service down, cascading failure
    HIGH = "high"          # Security exposure, resource exhaustion imminent
    MEDIUM = "medium"      # Performance degradation, config drift
    LOW = "low"            # Hygiene — log rotation, stale git
    INFO = "info"          # Informational — new module found, topology change


class IssueCategory(str, Enum):
    HEALTH = "health"
    PERFORMANCE = "performance"
    SECURITY = "security"
    CONFIGURATION = "configuration"
    FRESHNESS = "freshness"
    CAPACITY = "capacity"


# ── Data Models ──────────────────────────────────────────────

@dataclass
class ProcessInfo:
    pid: int = 0
    command: str = ""
    user: str = ""
    start_time: str = ""
    rss_mb: float = 0.0
    cpu_pct: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PortInfo:
    port: int = 0
    proto: str = "tcp"
    binding: str = "0.0.0.0"
    pid: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ServiceInfo:
    unit_name: str = ""
    enabled: bool = False
    active: bool = False
    sub_state: str = ""  # "running", "dead", "failed"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HealthResult:
    url: str = ""
    status_code: int = 0
    latency_ms: float = 0.0
    healthy: bool = False
    error: str = ""
    checked_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Issue:
    id: str = ""
    severity: IssueSeverity = IssueSeverity.INFO
    category: IssueCategory = IssueCategory.HEALTH
    module_id: str = ""
    title: str = ""
    detail: str = ""
    auto_fixable: bool = False
    auto_fixed: bool = False
    fix_action: str = ""
    created_at: str = ""
    resolved_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        d["category"] = self.category.value
        return d


@dataclass
class Module:
    """A discovered enterprise module — service, agent, daemon, etc."""
    id: str = ""
    name: str = ""
    type: ModuleType = ModuleType.UNKNOWN
    machine: str = "dragonfly"
    process: ProcessInfo = field(default_factory=ProcessInfo)
    ports: list[PortInfo] = field(default_factory=list)
    service: ServiceInfo = field(default_factory=ServiceInfo)
    config_path: str = ""
    public_urls: list[str] = field(default_factory=list)
    health_endpoint: str = ""
    health_result: HealthResult = field(default_factory=HealthResult)
    resources: dict = field(default_factory=dict)  # rss_mb, cpu_pct, disk_mb, etc.
    dependencies: list[str] = field(default_factory=list)
    status: ModuleStatus = ModuleStatus.UNKNOWN
    last_seen: str = ""
    issues: list[Issue] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)  # arbitrary extra info
    _miss_count: int = field(default=0, repr=False)

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "machine": self.machine,
            "process": self.process.to_dict(),
            "ports": [p.to_dict() for p in self.ports],
            "service": self.service.to_dict(),
            "config_path": self.config_path,
            "public_urls": self.public_urls,
            "health_endpoint": self.health_endpoint,
            "health_result": self.health_result.to_dict(),
            "resources": self.resources,
            "dependencies": self.dependencies,
            "status": self.status.value,
            "last_seen": self.last_seen,
            "issues": [i.to_dict() for i in self.issues],
            "metadata": self.metadata,
        }
        return d


@dataclass
class Edge:
    """A connection between two modules."""
    source: str = ""
    target: str = ""
    type: EdgeType = EdgeType.DEPENDS_ON
    port: int = 0
    label: str = ""
    verified: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = self.type.value
        return d


class TopologyGraph:
    """
    The enterprise topology — all known modules and their connections.
    Single source of truth for 'what exists, where, and how it connects.'
    """

    def __init__(self):
        self.modules: dict[str, Module] = {}
        self.edges: list[Edge] = []
        self._state_path: Path | None = None

    def set_state_path(self, path: Path) -> None:
        """Set persistence path for topology state."""
        self._state_path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def upsert_module(self, module: Module) -> tuple[str, bool]:
        """
        Insert or update a module. Returns (module_id, is_new).
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        module.last_seen = now
        module._miss_count = 0

        existing = self.modules.get(module.id)
        is_new = existing is None

        if existing:
            # Merge: update dynamic fields, keep stable ones
            existing.process = module.process
            existing.ports = module.ports
            existing.service = module.service
            existing.resources = module.resources
            existing.status = module.status  # Reset status (revives gone/stale modules)
            existing.last_seen = now
            existing._miss_count = 0
            if module.health_result.checked_at:
                existing.health_result = module.health_result
            if module.public_urls:
                existing.public_urls = module.public_urls
            if module.config_path:
                existing.config_path = module.config_path
            if module.dependencies:
                existing.dependencies = module.dependencies
            if module.metadata:
                existing.metadata.update(module.metadata)
        else:
            self.modules[module.id] = module

        return module.id, is_new

    def mark_missed(self, module_id: str) -> ModuleStatus | None:
        """Called when a module wasn't found in a discovery cycle."""
        mod = self.modules.get(module_id)
        if not mod:
            return None
        mod._miss_count += 1
        if mod._miss_count >= 10:
            mod.status = ModuleStatus.GONE
        elif mod._miss_count >= 3:
            mod.status = ModuleStatus.STALE
        return mod.status

    def add_edge(self, edge: Edge) -> None:
        """Add a dependency edge (deduplicates)."""
        for e in self.edges:
            if e.source == edge.source and e.target == edge.target and e.type == edge.type:
                e.verified = edge.verified
                e.port = edge.port or e.port
                return
        self.edges.append(edge)

    def get_module(self, module_id: str) -> Module | None:
        return self.modules.get(module_id)

    def get_active_modules(self) -> list[Module]:
        """All modules that are not GONE."""
        return [m for m in self.modules.values() if m.status != ModuleStatus.GONE]

    def get_dependents(self, module_id: str) -> list[str]:
        """Who depends on this module?"""
        return [e.source for e in self.edges if e.target == module_id]

    def get_dependencies(self, module_id: str) -> list[str]:
        """What does this module depend on?"""
        return [e.target for e in self.edges if e.source == module_id]

    def summary(self) -> dict:
        """Quick topology summary."""
        by_status = {}
        by_type = {}
        by_machine = {}
        for m in self.modules.values():
            if m.status == ModuleStatus.GONE:
                continue
            by_status[m.status.value] = by_status.get(m.status.value, 0) + 1
            by_type[m.type.value] = by_type.get(m.type.value, 0) + 1
            by_machine[m.machine] = by_machine.get(m.machine, 0) + 1

        return {
            "total_modules": len(self.get_active_modules()),
            "total_edges": len(self.edges),
            "by_status": by_status,
            "by_type": by_type,
            "by_machine": by_machine,
        }

    def save(self) -> None:
        """Persist topology state to disk."""
        if not self._state_path:
            return
        try:
            state = {
                "modules": {k: v.to_dict() for k, v in self.modules.items()},
                "edges": [e.to_dict() for e in self.edges],
                "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2, default=str))
            tmp.rename(self._state_path)
        except Exception as e:
            logger.debug(f"Suppressed topology save error: {e}")

    def load(self) -> bool:
        """Load topology state from disk."""
        if not self._state_path or not self._state_path.exists():
            return False
        try:
            data = json.loads(self._state_path.read_text())
            # Reconstruct modules
            for mid, mdata in data.get("modules", {}).items():
                mod = Module(
                    id=mdata.get("id", mid),
                    name=mdata.get("name", mid),
                    type=ModuleType(mdata.get("type", "unknown")),
                    machine=mdata.get("machine", "dragonfly"),
                    config_path=mdata.get("config_path", ""),
                    public_urls=mdata.get("public_urls", []),
                    health_endpoint=mdata.get("health_endpoint", ""),
                    dependencies=mdata.get("dependencies", []),
                    status=ModuleStatus(mdata.get("status", "unknown")),
                    last_seen=mdata.get("last_seen", ""),
                    metadata=mdata.get("metadata", {}),
                )
                self.modules[mid] = mod
            # Reconstruct edges
            for edata in data.get("edges", []):
                edge = Edge(
                    source=edata.get("source", ""),
                    target=edata.get("target", ""),
                    type=EdgeType(edata.get("type", "depends_on")),
                    port=edata.get("port", 0),
                    label=edata.get("label", ""),
                    verified=edata.get("verified", False),
                )
                self.edges.append(edge)
            logger.info(f"ATLAS: Loaded topology — {len(self.modules)} modules, {len(self.edges)} edges")
            return True
        except Exception as e:
            logger.debug(f"Suppressed topology load error: {e}")
            return False
