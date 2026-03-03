"""
POA — Product Owner Agent Manager
=====================================

Creates, deploys, and manages Product Owner Agents.

A POA is a persistent agent responsible for ONE product:
    - Health monitoring (endpoints, SSL, uptime)
    - Customer operations (signups, support, billing)
    - Metrics collection (API usage, error rates, latency)
    - Audit scheduling (periodic health + security checks)
    - Report generation (daily, weekly)
    - Escalation (POA → Coordinator → Admin → CEO)

POA lifecycle:
    1. PROPOSED — Singularity detected a live product needing an owner
    2. APPROVED — Human approved the proposal
    3. ACTIVE — POA is running, monitoring, reporting
    4. PAUSED — Temporarily suspended
    5. RETIRED — Product decommissioned

Each POA gets:
    - A config file (.singularity/poas/<product>.yaml)
    - A workspace directory (.singularity/poas/<product>/)
    - Scheduled audit jobs via PULSE
    - Event bus subscriptions for real-time monitoring
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("singularity.poa")


class POAStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    ACTIVE = "active"
    PAUSED = "paused"
    RETIRED = "retired"
    ERROR = "error"


@dataclass
class Endpoint:
    """A monitored endpoint."""
    url: str
    name: str = ""
    method: str = "GET"
    expected_status: int = 200
    timeout_ms: int = 5000
    check_ssl: bool = True

    def to_dict(self) -> dict:
        return {
            "url": self.url, "name": self.name or self.url,
            "method": self.method, "expected_status": self.expected_status,
            "timeout_ms": self.timeout_ms, "check_ssl": self.check_ssl,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Endpoint":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class POAConfig:
    """Complete configuration for a Product Owner Agent."""
    product_name: str
    product_id: str = ""          # slug (auto-generated if empty)
    description: str = ""
    status: POAStatus = POAStatus.PROPOSED
    
    # Monitoring
    endpoints: list[Endpoint] = field(default_factory=list)
    service_name: str = ""        # systemd service to monitor
    log_journal_unit: str = ""    # journalctl unit for log scanning
    
    # Scheduling
    audit_schedule: str = "0 */4 * * *"    # cron: health audit
    metrics_schedule: str = "0 18 * * *"   # cron: daily metrics
    report_schedule: str = "0 18 * * 5"    # cron: weekly report (Friday)
    ssl_check_schedule: str = "0 1 * * *"  # cron: daily SSL check
    
    # Thresholds
    latency_warn_ms: int = 2000
    latency_crit_ms: int = 5000
    error_rate_warn: float = 0.01
    error_rate_crit: float = 0.05
    ssl_expiry_warn_days: int = 30
    ssl_expiry_crit_days: int = 7
    disk_warn_pct: int = 85
    disk_crit_pct: int = 93
    
    # Escalation
    escalation_email: str = ""
    escalation_channel: str = ""   # Discord channel ID
    auto_restart: bool = False     # restart service on failure
    
    # Customer ops
    support_email: str = ""
    docs_url: str = ""
    pricing_tiers: list[dict] = field(default_factory=list)
    
    # Metadata
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    created_by: str = "singularity"
    version: str = "1.0.0"

    def __post_init__(self):
        if not self.product_id:
            self.product_id = self.product_name.lower().replace(" ", "-")

    def to_dict(self) -> dict:
        d = {
            "product_name": self.product_name,
            "product_id": self.product_id,
            "description": self.description,
            "status": self.status.value,
            "endpoints": [e.to_dict() for e in self.endpoints],
            "service_name": self.service_name,
            "log_journal_unit": self.log_journal_unit,
            "audit_schedule": self.audit_schedule,
            "metrics_schedule": self.metrics_schedule,
            "report_schedule": self.report_schedule,
            "ssl_check_schedule": self.ssl_check_schedule,
            "latency_warn_ms": self.latency_warn_ms,
            "latency_crit_ms": self.latency_crit_ms,
            "error_rate_warn": self.error_rate_warn,
            "error_rate_crit": self.error_rate_crit,
            "ssl_expiry_warn_days": self.ssl_expiry_warn_days,
            "ssl_expiry_crit_days": self.ssl_expiry_crit_days,
            "disk_warn_pct": self.disk_warn_pct,
            "disk_crit_pct": self.disk_crit_pct,
            "escalation_email": self.escalation_email,
            "escalation_channel": self.escalation_channel,
            "auto_restart": self.auto_restart,
            "support_email": self.support_email,
            "docs_url": self.docs_url,
            "pricing_tiers": self.pricing_tiers,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "version": self.version,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "POAConfig":
        d = dict(d)
        d["status"] = POAStatus(d.get("status", "proposed"))
        d["endpoints"] = [Endpoint.from_dict(e) for e in d.get("endpoints", [])]
        # Filter to valid fields
        valid = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in valid})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = time.time()
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path) -> "POAConfig":
        return cls.from_dict(json.loads(path.read_text()))


class POAManager:
    """
    Manages the lifecycle of all Product Owner Agents.
    
    Usage:
        manager = POAManager(workspace=Path(".singularity"))
        
        # Propose a POA
        config = manager.propose("COMB Cloud", endpoints=[...])
        
        # Approve it
        manager.approve("comb-cloud")
        
        # Activate (starts monitoring)
        manager.activate("comb-cloud")
        
        # List all POAs
        for poa in manager.list_all():
            print(poa.product_name, poa.status)
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.poa_dir = workspace / "poas"
        self.poa_dir.mkdir(parents=True, exist_ok=True)
        self._configs: dict[str, POAConfig] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Load all POA configs from disk."""
        for f in self.poa_dir.glob("*/config.json"):
            try:
                config = POAConfig.load(f)
                self._configs[config.product_id] = config
            except Exception as e:
                logger.error(f"Failed to load POA config {f}: {e}")

    def propose(
        self,
        product_name: str,
        description: str = "",
        endpoints: list[dict] = None,
        service_name: str = "",
        support_email: str = "",
        docs_url: str = "",
        **kwargs,
    ) -> POAConfig:
        """
        Propose a new POA for a product.
        Returns the config in PROPOSED state.
        """
        config = POAConfig(
            product_name=product_name,
            description=description,
            endpoints=[Endpoint.from_dict(e) for e in (endpoints or [])],
            service_name=service_name,
            support_email=support_email,
            docs_url=docs_url,
            status=POAStatus.PROPOSED,
            **{k: v for k, v in kwargs.items() if k in POAConfig.__dataclass_fields__},
        )

        # Save
        product_dir = self.poa_dir / config.product_id
        product_dir.mkdir(parents=True, exist_ok=True)
        (product_dir / "logs").mkdir(exist_ok=True)
        (product_dir / "audits").mkdir(exist_ok=True)
        (product_dir / "reports").mkdir(exist_ok=True)
        config.save(product_dir / "config.json")
        
        self._configs[config.product_id] = config
        logger.info(f"POA proposed: {config.product_name} ({config.product_id})")
        return config

    def approve(self, product_id: str) -> bool:
        """Approve a proposed POA."""
        config = self._configs.get(product_id)
        if not config:
            logger.error(f"POA not found: {product_id}")
            return False
        if config.status != POAStatus.PROPOSED:
            logger.warning(f"POA {product_id} is {config.status.value}, not proposed")
            return False
        config.status = POAStatus.APPROVED
        self._save(config)
        logger.info(f"POA approved: {config.product_name}")
        return True

    def activate(self, product_id: str) -> bool:
        """Activate an approved POA (starts monitoring)."""
        config = self._configs.get(product_id)
        if not config:
            return False
        if config.status not in (POAStatus.APPROVED, POAStatus.PAUSED):
            logger.warning(f"POA {product_id} cannot be activated from {config.status.value}")
            return False
        config.status = POAStatus.ACTIVE
        self._save(config)
        logger.info(f"POA activated: {config.product_name}")
        return True

    def pause(self, product_id: str) -> bool:
        """Pause an active POA."""
        config = self._configs.get(product_id)
        if not config or config.status != POAStatus.ACTIVE:
            return False
        config.status = POAStatus.PAUSED
        self._save(config)
        return True

    def retire(self, product_id: str) -> bool:
        """Retire a POA (product decommissioned)."""
        config = self._configs.get(product_id)
        if not config:
            return False
        config.status = POAStatus.RETIRED
        self._save(config)
        return True

    def get(self, product_id: str) -> Optional[POAConfig]:
        return self._configs.get(product_id)

    def list_all(self) -> list[POAConfig]:
        return list(self._configs.values())

    def list_active(self) -> list[POAConfig]:
        return [c for c in self._configs.values() if c.status == POAStatus.ACTIVE]

    def status_summary(self) -> dict[str, Any]:
        """Summary of all POAs by status."""
        summary = {"total": len(self._configs)}
        for status in POAStatus:
            count = sum(1 for c in self._configs.values() if c.status == status)
            if count:
                summary[status.value] = count
        return summary

    def _save(self, config: POAConfig) -> None:
        """Save a POA config to disk."""
        product_dir = self.poa_dir / config.product_id
        product_dir.mkdir(parents=True, exist_ok=True)
        config.save(product_dir / "config.json")
