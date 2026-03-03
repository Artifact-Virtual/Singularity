"""
POA — Runtime (Audit & Monitoring Engine)
=============================================

Executes POA duties:
    - Health checks (endpoint latency, SSL, service status)
    - Metrics collection
    - Report generation
    - Escalation on failures

Works with PULSE scheduler for periodic execution.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import socket
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from .manager import POAConfig, POAStatus, Endpoint

logger = logging.getLogger("singularity.poa.runtime")


@dataclass
class CheckResult:
    """Result of a single health check."""
    name: str
    passed: bool
    message: str
    value: Any = None
    duration_ms: float = 0.0
    severity: str = "info"   # info, warn, critical

    def to_dict(self) -> dict:
        return {
            "name": self.name, "passed": self.passed,
            "message": self.message, "value": self.value,
            "duration_ms": round(self.duration_ms, 1),
            "severity": self.severity,
        }


@dataclass
class AuditReport:
    """Complete audit report for a product."""
    product_id: str
    product_name: str
    timestamp: str = ""
    checks: list[CheckResult] = field(default_factory=list)
    overall_status: str = "unknown"   # green, yellow, red
    duration_ms: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    @property
    def criticals(self) -> int:
        return sum(1 for c in self.checks if c.severity == "critical")

    def compute_status(self) -> str:
        if self.criticals > 0:
            self.overall_status = "red"
        elif self.failed > 0:
            self.overall_status = "yellow"
        else:
            self.overall_status = "green"
        return self.overall_status

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "timestamp": self.timestamp,
            "overall_status": self.overall_status,
            "passed": self.passed,
            "failed": self.failed,
            "criticals": self.criticals,
            "duration_ms": round(self.duration_ms, 1),
            "checks": [c.to_dict() for c in self.checks],
        }

    def to_markdown(self) -> str:
        icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(self.overall_status, "⚪")
        lines = [
            f"# POA Audit: {self.product_name}",
            f"**Status:** {icon} {self.overall_status.upper()}",
            f"**Time:** {self.timestamp}",
            f"**Checks:** {self.passed}/{len(self.checks)} passed",
            f"**Duration:** {self.duration_ms:.0f}ms",
            "",
            "| Check | Status | Detail |",
            "|-------|--------|--------|",
        ]
        for c in self.checks:
            status = "✅" if c.passed else ("🔴" if c.severity == "critical" else "⚠️")
            lines.append(f"| {c.name} | {status} | {c.message} |")
        return "\n".join(lines)


class POARuntime:
    """
    Executes POA health checks and audits.
    Stateless — takes a config and produces results.
    """

    @staticmethod
    def run_audit(config: POAConfig) -> AuditReport:
        """Run a complete health audit for a product."""
        report = AuditReport(
            product_id=config.product_id,
            product_name=config.product_name,
        )
        start = time.monotonic()

        # 1. Endpoint checks
        for ep in config.endpoints:
            result = POARuntime._check_endpoint(ep, config)
            report.checks.append(result)

        # 2. Service check
        if config.service_name:
            result = POARuntime._check_service(config.service_name)
            report.checks.append(result)

        # 3. SSL checks
        for ep in config.endpoints:
            if ep.check_ssl and ep.url.startswith("https://"):
                result = POARuntime._check_ssl(ep.url, config)
                report.checks.append(result)

        # 4. Disk check
        report.checks.append(POARuntime._check_disk(config))

        # 5. Memory check
        report.checks.append(POARuntime._check_memory())

        # 6. Journal errors (if unit specified)
        if config.log_journal_unit:
            result = POARuntime._check_journal(config.log_journal_unit)
            report.checks.append(result)

        report.duration_ms = (time.monotonic() - start) * 1000
        report.compute_status()
        return report

    @staticmethod
    def save_audit(report: AuditReport, poa_dir: Path) -> Path:
        """Save audit report to disk (both JSON and markdown)."""
        audit_dir = poa_dir / report.product_id / "audits"
        audit_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        json_path = audit_dir / f"{ts}.json"
        md_path = audit_dir / f"{ts}.md"

        json_path.write_text(json.dumps(report.to_dict(), indent=2))
        md_path.write_text(report.to_markdown())

        # Also save as latest
        (audit_dir / "latest.json").write_text(json.dumps(report.to_dict(), indent=2))
        (audit_dir / "latest.md").write_text(report.to_markdown())

        return json_path

    # ── Individual Checks ──

    @staticmethod
    def _check_endpoint(ep: Endpoint, config: POAConfig) -> CheckResult:
        """Check if an endpoint is reachable and responding."""
        start = time.monotonic()
        try:
            req = Request(ep.url, method=ep.method)
            req.add_header("User-Agent", "Singularity-POA/1.0")
            with urlopen(req, timeout=ep.timeout_ms / 1000) as resp:
                elapsed = (time.monotonic() - start) * 1000
                status = resp.status
                if status != ep.expected_status:
                    return CheckResult(
                        name=f"endpoint:{ep.name or ep.url}",
                        passed=False, severity="critical",
                        message=f"HTTP {status} (expected {ep.expected_status})",
                        value=status, duration_ms=elapsed,
                    )
                severity = "info"
                if elapsed > config.latency_crit_ms:
                    severity = "critical"
                elif elapsed > config.latency_warn_ms:
                    severity = "warn"
                return CheckResult(
                    name=f"endpoint:{ep.name or ep.url}",
                    passed=True, severity=severity,
                    message=f"HTTP {status} in {elapsed:.0f}ms",
                    value=status, duration_ms=elapsed,
                )
        except (URLError, HTTPError, OSError) as e:
            elapsed = (time.monotonic() - start) * 1000
            return CheckResult(
                name=f"endpoint:{ep.name or ep.url}",
                passed=False, severity="critical",
                message=str(e)[:200], duration_ms=elapsed,
            )

    @staticmethod
    def _check_ssl(url: str, config: POAConfig) -> CheckResult:
        """Check SSL certificate expiry."""
        try:
            from urllib.parse import urlparse
            hostname = urlparse(url).hostname
            port = urlparse(url).port or 443
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(socket.socket(), server_hostname=hostname) as s:
                s.settimeout(5)
                s.connect((hostname, port))
                cert = s.getpeercert()
                not_after = ssl.cert_time_to_seconds(cert["notAfter"])
                days_left = (not_after - time.time()) / 86400
                severity = "info"
                if days_left < config.ssl_expiry_crit_days:
                    severity = "critical"
                elif days_left < config.ssl_expiry_warn_days:
                    severity = "warn"
                return CheckResult(
                    name=f"ssl:{hostname}",
                    passed=days_left > 0,
                    severity=severity,
                    message=f"{days_left:.0f} days until expiry",
                    value=round(days_left, 1),
                )
        except Exception as e:
            return CheckResult(
                name=f"ssl:{url}", passed=False,
                severity="critical", message=str(e)[:200],
            )

    @staticmethod
    def _check_service(service_name: str) -> CheckResult:
        """Check if a systemd service is active."""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", service_name],
                capture_output=True, text=True, timeout=5,
            )
            active = result.stdout.strip() == "active"
            return CheckResult(
                name=f"service:{service_name}",
                passed=active,
                severity="info" if active else "critical",
                message=result.stdout.strip(),
            )
        except Exception as e:
            return CheckResult(
                name=f"service:{service_name}",
                passed=False, severity="critical",
                message=str(e)[:200],
            )

    @staticmethod
    def _check_disk(config: POAConfig) -> CheckResult:
        """Check disk usage."""
        try:
            st = os.statvfs("/")
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            used_pct = round((1 - free / total) * 100, 1)
            severity = "info"
            if used_pct > config.disk_crit_pct:
                severity = "critical"
            elif used_pct > config.disk_warn_pct:
                severity = "warn"
            return CheckResult(
                name="disk:root", passed=used_pct < config.disk_crit_pct,
                severity=severity,
                message=f"{used_pct}% used ({free // (1024**3)}GB free)",
                value=used_pct,
            )
        except Exception as e:
            return CheckResult(
                name="disk:root", passed=False,
                severity="warn", message=str(e)[:200],
            )

    @staticmethod
    def _check_memory() -> CheckResult:
        """Check memory usage."""
        try:
            with open("/proc/meminfo") as f:
                info = {}
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = int(parts[1].strip().split()[0])
                        info[key] = val
                total = info.get("MemTotal", 1)
                available = info.get("MemAvailable", 0)
                used_pct = round((1 - available / total) * 100, 1)
                severity = "info"
                if used_pct > 90:
                    severity = "critical"
                elif used_pct > 80:
                    severity = "warn"
                return CheckResult(
                    name="memory", passed=used_pct < 90,
                    severity=severity,
                    message=f"{used_pct}% used ({available // 1024}MB available)",
                    value=used_pct,
                )
        except Exception as e:
            return CheckResult(
                name="memory", passed=True,
                severity="info", message=str(e)[:200],
            )

    @staticmethod
    def _check_journal(unit: str) -> CheckResult:
        """Check for errors in systemd journal."""
        try:
            result = subprocess.run(
                ["journalctl", "-u", unit, "--since", "1h ago",
                 "-p", "err", "--no-pager", "-q", "--output", "short"],
                capture_output=True, text=True, timeout=10,
            )
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            error_count = len(lines)
            severity = "info"
            if error_count > 10:
                severity = "critical"
            elif error_count > 0:
                severity = "warn"
            return CheckResult(
                name=f"journal:{unit}",
                passed=error_count == 0,
                severity=severity,
                message=f"{error_count} errors in last hour",
                value=error_count,
            )
        except Exception as e:
            return CheckResult(
                name=f"journal:{unit}", passed=True,
                severity="info", message=str(e)[:200],
            )
