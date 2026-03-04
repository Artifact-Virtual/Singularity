"""
POA — Double-Audit Setup Flow
=================================

The setup pipeline for bootstrapping Product Owner Agents.

Flow:
    1. BROAD AUDIT — Full workspace scan. Everything. No assumptions.
    2. REVIEW — Singularity reviews the broad audit, classifies products,
       determines what actually needs a POA vs what's dead/archived/trivial.
       Generates tightened, focused POA proposals with real configs.
    3. FOCUSED AUDIT — Runs health checks ONLY on the tightened set.
       Validates endpoints, SSL, services. Proves each POA is viable.
    4. USER APPROVAL — Presents the focused results to the human.
       They approve, reject, or modify before POAs go live.

This replaces the old single-pass init that proposed POAs for everything.

Usage:
    flow = SetupFlow(workspace="/path/to/workspace")
    
    # Phase 1: Broad scan
    broad = flow.broad_audit()
    
    # Phase 2: Review & tighten
    focused = flow.review(broad)
    
    # Phase 3: Focused audit (health checks on real products only)
    results = flow.focused_audit(focused)
    
    # Phase 4: Present for approval
    report = flow.present(results)
    
    # Phase 5: Activate approved POAs
    flow.activate(approved_ids)
    
    # Or run everything:
    report = flow.run()  # returns SetupReport
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from singularity.auditor import (
    WorkspaceScanner,
    WorkspaceAnalyzer,
    WorkspaceAnalysis,
    ProjectAnalysis,
    ScanResult,
    POARecommendation,
    generate_report,
    save_report,
)
from .manager import POAManager, POAConfig, POAStatus, Endpoint
from .runtime import POARuntime, AuditReport

logger = logging.getLogger("singularity.poa.setup")


# ── Classification Rules ──────────────────────────────────────

# Products that are clearly NOT worth a POA
SKIP_PATTERNS = {
    # Archived / dead
    "archived", "deprecated", "old", "legacy", "backup", "bak",
    # Test / scratch
    "test", "scratch", "tmp", "temp", "sandbox",
    # Configs / dotfiles (not products)
    ".git", ".vscode", ".idea",
}

# Indicators that something IS a real product
LIVE_INDICATORS = [
    "is_live",              # Scanner detected running service
    "has_endpoints",        # Has URL endpoints to monitor
    "has_service",          # Has systemd service
    "has_deployment",       # Has deployment config
    "published_package",    # Published to PyPI/npm/etc.
    "has_users",            # Has user-facing interface
]


@dataclass
class ProductClassification:
    """Classification of a scanned project for POA purposes."""
    project_name: str
    project_path: str
    total_lines: int = 0
    
    # Classification
    is_product: bool = False       # Worthy of a POA
    is_live: bool = False          # Currently running/deployed
    is_published: bool = False     # Published package
    is_archived: bool = False      # Dead/deprecated
    is_trivial: bool = False       # Too small to matter
    
    # Evidence
    reasons: list[str] = field(default_factory=list)
    
    # If is_product, proposed POA config
    proposed_config: Optional[dict] = None
    
    # Maturity from analysis
    maturity_score: int = 0
    maturity_grade: str = "F"
    
    # Priority for POA assignment
    priority: str = "low"          # critical, high, medium, low
    
    def to_dict(self) -> dict:
        d = {
            "project_name": self.project_name,
            "project_path": self.project_path,
            "total_lines": self.total_lines,
            "is_product": self.is_product,
            "is_live": self.is_live,
            "is_published": self.is_published,
            "is_archived": self.is_archived,
            "is_trivial": self.is_trivial,
            "reasons": self.reasons,
            "maturity_score": self.maturity_score,
            "maturity_grade": self.maturity_grade,
            "priority": self.priority,
        }
        if self.proposed_config:
            d["proposed_config"] = self.proposed_config
        return d


@dataclass
class BroadAuditResult:
    """Result of Phase 1: Broad Audit."""
    scan: ScanResult
    analysis: WorkspaceAnalysis
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class ReviewResult:
    """Result of Phase 2: Review & Tighten."""
    classifications: list[ProductClassification] = field(default_factory=list)
    products: list[ProductClassification] = field(default_factory=list)  # Only is_product=True
    skipped: list[ProductClassification] = field(default_factory=list)   # Filtered out
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    @property
    def product_count(self) -> int:
        return len(self.products)
    
    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


@dataclass
class FocusedAuditResult:
    """Result of Phase 3: Focused Audit."""
    audits: list[tuple[ProductClassification, AuditReport]] = field(default_factory=list)
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    @property
    def green_count(self) -> int:
        return sum(1 for _, r in self.audits if r.overall_status == "green")
    
    @property
    def yellow_count(self) -> int:
        return sum(1 for _, r in self.audits if r.overall_status == "yellow")
    
    @property
    def red_count(self) -> int:
        return sum(1 for _, r in self.audits if r.overall_status == "red")


@dataclass
class SetupReport:
    """Complete setup flow report — presented to user for approval."""
    workspace: str
    broad_summary: dict = field(default_factory=dict)
    review_summary: dict = field(default_factory=dict)
    focused_results: list[dict] = field(default_factory=list)
    proposed_poas: list[dict] = field(default_factory=list)
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> dict:
        return {
            "workspace": self.workspace,
            "timestamp": self.timestamp,
            "broad_summary": self.broad_summary,
            "review_summary": self.review_summary,
            "focused_results": self.focused_results,
            "proposed_poas": self.proposed_poas,
        }
    
    def to_markdown(self) -> str:
        lines = [
            "# POA Setup Report — Double Audit",
            f"**Workspace:** {self.workspace}",
            f"**Time:** {self.timestamp}",
            "",
        ]
        
        # Broad summary
        bs = self.broad_summary
        lines.append("## Phase 1: Broad Audit")
        lines.append(f"- Projects scanned: **{bs.get('total_projects', '?')}**")
        lines.append(f"- Total LOC: **{bs.get('total_lines', '?'):,}**")
        lines.append(f"- Health score: **{bs.get('health_score', '?')}/100**")
        lines.append("")
        
        # Review summary
        rs = self.review_summary
        lines.append("## Phase 2: Review & Tighten")
        lines.append(f"- Products identified: **{rs.get('product_count', '?')}**")
        lines.append(f"- Skipped (trivial/archived/not products): **{rs.get('skipped_count', '?')}**")
        lines.append("")
        
        if rs.get("skipped_reasons"):
            lines.append("### Filtered Out")
            for name, reason in rs["skipped_reasons"][:10]:
                lines.append(f"- ~~{name}~~ — {reason}")
            lines.append("")
        
        # Focused results
        lines.append("## Phase 3: Focused Audit")
        for fr in self.focused_results:
            icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(fr.get("status", ""), "⚪")
            lines.append(f"- {icon} **{fr['name']}** — {fr.get('checks_passed', 0)}/{fr.get('checks_total', 0)} checks, {fr.get('duration_ms', 0):.0f}ms")
        lines.append("")
        
        # Proposed POAs
        lines.append("## Phase 4: Proposed POAs (Awaiting Approval)")
        lines.append("")
        lines.append("| # | Product | Priority | Status | Endpoints | Service |")
        lines.append("|---|---------|----------|--------|-----------|---------|")
        for i, poa in enumerate(self.proposed_poas, 1):
            ep_count = len(poa.get("endpoints", []))
            svc = poa.get("service_name", "—")
            status = poa.get("audit_status", "—")
            icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(status, "⚪")
            lines.append(f"| {i} | {poa['product_name']} | {poa['priority']} | {icon} {status} | {ep_count} | {svc} |")
        lines.append("")
        
        lines.append("---")
        lines.append("*Approve POAs to activate monitoring. Reject to skip.*")
        
        return "\n".join(lines)


class SetupFlow:
    """
    Double-audit POA setup pipeline.
    
    Designed to be called from:
    - CLI: `singularity poa setup` (interactive)
    - Runtime: Singularity boot sequence (programmatic)
    - API: HTTP endpoint (automated)
    """
    
    def __init__(self, workspace: str, singularity_dir: Optional[str] = None):
        self.workspace = os.path.abspath(workspace)
        self.sg_dir = Path(singularity_dir or os.path.join(self.workspace, ".singularity"))
        self.sg_dir.mkdir(parents=True, exist_ok=True)
        self.poa_manager = POAManager(self.sg_dir)
        
    # ── Phase 1: Broad Audit ──────────────────────────────────
    
    def broad_audit(self) -> BroadAuditResult:
        """
        Phase 1: Full workspace scan. No filtering. Everything.
        Returns raw scan + analysis.
        """
        logger.info(f"Phase 1: Broad audit — scanning {self.workspace}")
        
        scanner = WorkspaceScanner(self.workspace)
        scan = scanner.scan()
        
        analyzer = WorkspaceAnalyzer(scan.projects, scan.workspace)
        analysis = analyzer.analyze()
        
        # Save broad audit
        audit_dir = self.sg_dir / "audits" / "setup"
        audit_dir.mkdir(parents=True, exist_ok=True)
        
        report_dict = generate_report(scan, analysis)
        save_report(report_dict, str(audit_dir / "broad"))
        
        logger.info(
            f"Phase 1 complete: {analysis.total_projects} projects, "
            f"{analysis.total_lines:,} LOC, health {analysis.health_score}/100"
        )
        
        return BroadAuditResult(scan=scan, analysis=analysis)
    
    # ── Phase 2: Review & Tighten ─────────────────────────────
    
    def review(self, broad: BroadAuditResult) -> ReviewResult:
        """
        Phase 2: Review the broad audit. Classify each project.
        Determine what's actually a product vs noise.
        Generate tightened POA proposals with real configs.
        """
        logger.info("Phase 2: Review — classifying projects")
        
        result = ReviewResult()
        
        for pa in broad.analysis.project_analyses:
            classification = self._classify_project(pa, broad)
            result.classifications.append(classification)
            
            if classification.is_product:
                result.products.append(classification)
            else:
                result.skipped.append(classification)
        
        # Sort products by priority
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        result.products.sort(key=lambda c: priority_order.get(c.priority, 99))
        
        # Save review
        review_dir = self.sg_dir / "audits" / "setup" / "review"
        review_dir.mkdir(parents=True, exist_ok=True)
        
        review_data = {
            "timestamp": result.timestamp,
            "product_count": result.product_count,
            "skipped_count": result.skipped_count,
            "products": [c.to_dict() for c in result.products],
            "skipped": [c.to_dict() for c in result.skipped],
        }
        (review_dir / "latest.json").write_text(json.dumps(review_data, indent=2))
        
        logger.info(
            f"Phase 2 complete: {result.product_count} products identified, "
            f"{result.skipped_count} filtered out"
        )
        
        return result
    
    def _classify_project(
        self, pa: ProjectAnalysis, broad: BroadAuditResult
    ) -> ProductClassification:
        """Classify a single project — is it POA-worthy?"""
        p = pa.project
        c = ProductClassification(
            project_name=p.name,
            project_path=p.relative_path or p.path,
            total_lines=p.total_lines,
            maturity_score=pa.maturity.total,
            maturity_grade=pa.maturity.grade,
        )
        
        # ── Check skip patterns ──
        name_lower = p.name.lower()
        for pattern in SKIP_PATTERNS:
            if pattern in name_lower:
                c.is_archived = True
                c.reasons.append(f"Name matches skip pattern: '{pattern}'")
                return c
        
        # ── Check if trivial ──
        if p.total_lines < 50:
            c.is_trivial = True
            c.reasons.append(f"Too small ({p.total_lines} LOC)")
            return c
        
        # ── Check if it's a live product ──
        if p.is_live:
            c.is_live = True
            c.is_product = True
            c.priority = "critical"
            c.reasons.append("Detected as live service")
        
        # ── Check for deployment indicators ──
        if p.cicd.docker or p.cicd.docker_compose:
            c.reasons.append("Has Docker deployment")
            if not c.is_product:
                c.is_product = True
                c.priority = "high"
        
        # ── Check for published package ──
        if p.version and p.total_lines > 200:
            c.is_published = True
            c.reasons.append(f"Published package (v{p.version})")
            if not c.is_product:
                c.is_product = True
                c.priority = "high"
        
        # ── Check for systemd service ──
        # Look for .service files or known service names
        project_path = Path(p.path)
        service_files = list(project_path.glob("*.service")) + list(project_path.glob("**/*.service"))
        if service_files:
            c.reasons.append(f"Has systemd service file(s)")
            if not c.is_product:
                c.is_product = True
                c.priority = "high"
        
        # ── Check for entry points (API servers, CLI tools) ──
        if p.entry_points:
            api_entries = [e for e in p.entry_points if any(
                kw in e.lower() for kw in ["server", "api", "app", "main", "cli"]
            )]
            if api_entries:
                c.reasons.append(f"Has entry points: {', '.join(api_entries[:3])}")
                if not c.is_product:
                    c.is_product = True
                    c.priority = "medium"
        
        # ── Check for substantial codebase without other indicators ──
        if not c.is_product and p.total_lines > 2000 and pa.maturity.total >= 40:
            c.is_product = True
            c.priority = "medium"
            c.reasons.append(f"Substantial codebase ({p.total_lines:,} LOC, grade {pa.maturity.grade})")
        
        # ── If still not a product, mark as trivial/not-product ──
        if not c.is_product:
            if p.total_lines < 200:
                c.is_trivial = True
                c.reasons.append(f"Small project ({p.total_lines} LOC), no live/deployment indicators")
            else:
                c.reasons.append("No live/deployment/publish indicators detected")
        
        # ── Build proposed POA config if it's a product ──
        if c.is_product:
            c.proposed_config = self._build_poa_config(p, pa, c)
        
        return c
    
    def _build_poa_config(
        self, p: Any, pa: ProjectAnalysis, c: ProductClassification
    ) -> dict:
        """Build a proposed POA config dict for a product."""
        config = {
            "product_name": p.name,
            "product_id": p.name.lower().replace(" ", "-").replace("_", "-"),
            "description": c.reasons[0] if c.reasons else f"Product: {p.name}",
            "endpoints": [],
            "service_name": "",
            "log_journal_unit": "",
            "support_email": "",
            "auto_restart": False,
        }
        
        # Try to detect endpoints
        # Look for common port patterns in project files
        project_path = Path(p.path)
        for config_file in ["package.json", "pyproject.toml", "docker-compose.yml", 
                           "docker-compose.yaml", ".env.example", "config.yaml"]:
            fpath = project_path / config_file
            if fpath.exists():
                try:
                    content = fpath.read_text(errors="replace")[:5000]
                    # Look for port numbers
                    import re
                    ports = re.findall(r'(?:port|PORT)\s*[:=]\s*(\d{4,5})', content)
                    for port in ports[:3]:
                        config["endpoints"].append({
                            "url": f"http://localhost:{port}",
                            "name": f"{p.name}:{port}",
                        })
                except Exception:
                    pass
        
        # Try to detect systemd service name
        service_files = list(project_path.glob("*.service"))
        if service_files:
            config["service_name"] = service_files[0].stem
        
        # If the project name matches a known service pattern
        known_services = {
            "mach6": "mach6-gateway",
            "singularity": "singularity",
            "nginx": "nginx",
        }
        for pattern, service in known_services.items():
            if pattern in p.name.lower():
                if not config["service_name"]:
                    config["service_name"] = service
        
        return config
    
    # ── Phase 3: Focused Audit ────────────────────────────────
    
    def focused_audit(self, review: ReviewResult) -> FocusedAuditResult:
        """
        Phase 3: Run real health checks ONLY on identified products.
        Validates endpoints, SSL, services, disk, memory.
        """
        logger.info(f"Phase 3: Focused audit — {review.product_count} products")
        
        result = FocusedAuditResult()
        
        for classification in review.products:
            if not classification.proposed_config:
                continue
            
            # Build a POAConfig from the proposed config
            cfg = classification.proposed_config
            endpoints = [
                Endpoint.from_dict(e) for e in cfg.get("endpoints", [])
            ]
            
            poa_config = POAConfig(
                product_name=cfg["product_name"],
                product_id=cfg.get("product_id", cfg["product_name"].lower()),
                description=cfg.get("description", ""),
                endpoints=endpoints,
                service_name=cfg.get("service_name", ""),
                log_journal_unit=cfg.get("log_journal_unit", ""),
            )
            
            # Run the audit
            audit_report = POARuntime.run_audit(poa_config)
            
            # Save individual audit
            POARuntime.save_audit(audit_report, self.sg_dir / "poas")
            
            result.audits.append((classification, audit_report))
            
            status_icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(
                audit_report.overall_status, "⚪"
            )
            logger.info(
                f"  {status_icon} {cfg['product_name']}: "
                f"{audit_report.passed}/{len(audit_report.checks)} checks passed"
            )
        
        # Save focused audit summary
        focused_dir = self.sg_dir / "audits" / "setup" / "focused"
        focused_dir.mkdir(parents=True, exist_ok=True)
        
        focused_data = {
            "timestamp": result.timestamp,
            "total_products": len(result.audits),
            "green": result.green_count,
            "yellow": result.yellow_count,
            "red": result.red_count,
            "results": [
                {
                    "product": c.project_name,
                    "status": r.overall_status,
                    "checks_passed": r.passed,
                    "checks_total": len(r.checks),
                    "duration_ms": r.duration_ms,
                }
                for c, r in result.audits
            ],
        }
        (focused_dir / "latest.json").write_text(json.dumps(focused_data, indent=2))
        
        logger.info(
            f"Phase 3 complete: {result.green_count} green, "
            f"{result.yellow_count} yellow, {result.red_count} red"
        )
        
        return result
    
    # ── Phase 4: Present for Approval ─────────────────────────
    
    def present(
        self, 
        broad: BroadAuditResult, 
        review: ReviewResult, 
        focused: FocusedAuditResult
    ) -> SetupReport:
        """
        Phase 4: Build the final report for user approval.
        """
        report = SetupReport(workspace=self.workspace)
        
        # Broad summary
        report.broad_summary = {
            "total_projects": broad.analysis.total_projects,
            "total_lines": broad.analysis.total_lines,
            "total_files": broad.analysis.total_files,
            "health_score": broad.analysis.health_score,
            "language_summary": dict(
                sorted(broad.analysis.language_summary.items(), key=lambda x: -x[1])[:10]
            ),
        }
        
        # Review summary
        report.review_summary = {
            "product_count": review.product_count,
            "skipped_count": review.skipped_count,
            "skipped_reasons": [
                (c.project_name, "; ".join(c.reasons[:2]))
                for c in review.skipped[:15]
            ],
        }
        
        # Focused results
        audit_map = {}
        for classification, audit in focused.audits:
            report.focused_results.append({
                "name": classification.project_name,
                "status": audit.overall_status,
                "checks_passed": audit.passed,
                "checks_total": len(audit.checks),
                "duration_ms": audit.duration_ms,
            })
            audit_map[classification.project_name] = audit
        
        # Proposed POAs (merge classification + audit results)
        for classification in review.products:
            if not classification.proposed_config:
                continue
            
            cfg = classification.proposed_config
            audit = audit_map.get(classification.project_name)
            
            poa_data = {
                "product_name": cfg["product_name"],
                "product_id": cfg.get("product_id", ""),
                "priority": classification.priority,
                "reasons": classification.reasons,
                "total_lines": classification.total_lines,
                "maturity_grade": classification.maturity_grade,
                "endpoints": cfg.get("endpoints", []),
                "service_name": cfg.get("service_name", ""),
                "audit_status": audit.overall_status if audit else "unknown",
            }
            report.proposed_poas.append(poa_data)
        
        # Save full report
        setup_dir = self.sg_dir / "audits" / "setup"
        setup_dir.mkdir(parents=True, exist_ok=True)
        
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        report_json = setup_dir / f"report-{ts}.json"
        report_md = setup_dir / f"report-{ts}.md"
        
        report_json.write_text(json.dumps(report.to_dict(), indent=2))
        report_md.write_text(report.to_markdown())
        
        # Also save as latest
        (setup_dir / "report-latest.json").write_text(json.dumps(report.to_dict(), indent=2))
        (setup_dir / "report-latest.md").write_text(report.to_markdown())
        
        logger.info(f"Phase 4: Setup report generated — {len(report.proposed_poas)} POAs proposed")
        
        return report
    
    # ── Phase 5: Activate ─────────────────────────────────────
    
    def activate(
        self, 
        approved_ids: list[str],
        review: ReviewResult,
    ) -> list[POAConfig]:
        """
        Phase 5: Activate approved POAs.
        Creates them in POAManager, transitions to ACTIVE.
        Returns list of activated POA configs.
        """
        activated = []
        
        # Build lookup from review
        product_map = {c.proposed_config["product_id"]: c 
                       for c in review.products 
                       if c.proposed_config}
        
        for product_id in approved_ids:
            classification = product_map.get(product_id)
            if not classification or not classification.proposed_config:
                logger.warning(f"Product {product_id} not found in review — skipping")
                continue
            
            cfg = classification.proposed_config
            
            # Propose → Approve → Activate
            poa_config = self.poa_manager.propose(
                product_name=cfg["product_name"],
                description=cfg.get("description", ""),
                endpoints=cfg.get("endpoints", []),
                service_name=cfg.get("service_name", ""),
                support_email=cfg.get("support_email", ""),
            )
            
            self.poa_manager.approve(poa_config.product_id)
            self.poa_manager.activate(poa_config.product_id)
            
            activated.append(poa_config)
            logger.info(f"POA activated: {poa_config.product_name} ({poa_config.product_id})")
        
        return activated
    
    def reject(self, rejected_ids: list[str]) -> int:
        """Mark POAs as rejected (don't create them)."""
        count = 0
        for product_id in rejected_ids:
            existing = self.poa_manager.get(product_id)
            if existing and existing.status == POAStatus.PROPOSED:
                self.poa_manager.retire(product_id)
                count += 1
        return count
    
    # ── Full Pipeline ─────────────────────────────────────────
    
    def run(self) -> SetupReport:
        """
        Run the complete double-audit pipeline.
        Returns the setup report for user approval.
        (Doesn't activate — that's a separate step after approval.)
        """
        logger.info("=" * 60)
        logger.info("POA SETUP — Double Audit Flow")
        logger.info("=" * 60)
        
        start = time.monotonic()
        
        # Phase 1
        broad = self.broad_audit()
        
        # Phase 2
        review = self.review(broad)
        
        # Phase 3
        focused = self.focused_audit(review)
        
        # Phase 4
        report = self.present(broad, review, focused)
        
        elapsed = time.monotonic() - start
        logger.info(f"Setup flow complete in {elapsed:.1f}s")
        
        return report
    
    # ── Introspection ─────────────────────────────────────────
    
    def status(self) -> dict:
        """Get current POA status — how many active, proposed, etc."""
        return self.poa_manager.status_summary()
    
    def list_active(self) -> list[POAConfig]:
        """List currently active POAs."""
        return self.poa_manager.list_active()
    
    def kill(self, product_id: str) -> bool:
        """Kill (retire) a POA."""
        return self.poa_manager.retire(product_id)
    
    def pause(self, product_id: str) -> bool:
        """Pause a POA."""
        return self.poa_manager.pause(product_id)
    
    def reactivate(self, product_id: str) -> bool:
        """Reactivate a paused POA."""
        return self.poa_manager.activate(product_id)
