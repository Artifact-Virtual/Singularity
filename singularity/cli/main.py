"""
SINGULARITY [AE] — CLI Entry Point
======================================

Usage:
    singularity init [--workspace PATH] [--industry TYPE]
    singularity audit [--workspace PATH] [--full]
    singularity status [--json]
    singularity spawn-exec ROLE [--approve]
    singularity poa create|list|audit PRODUCT [--approve]
    singularity scale-report
    singularity health
    singularity test
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    parser = argparse.ArgumentParser(
        prog="singularity",
        description="Singularity [AE] — Autonomous Enterprise Runtime",
        epilog="Not a chatbot. An operating system.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── init ──
    p_init = sub.add_parser("init", help="Initialize workspace (interactive wizard)")
    p_init.add_argument("--workspace", "-w", default=".", help="Workspace path")
    p_init.add_argument("--industry", "-i", default="", help="Industry type")
    p_init.add_argument("--name", "-n", default="", help="Enterprise name")
    p_init.add_argument("--non-interactive", action="store_true", help="Skip prompts")

    # ── audit ──
    p_audit = sub.add_parser("audit", help="Audit workspace")
    p_audit.add_argument("--workspace", "-w", default=".", help="Workspace path")
    p_audit.add_argument("--full", action="store_true", help="Full rescan")
    p_audit.add_argument("--output", "-o", help="Output file")

    # ── status ──
    p_status = sub.add_parser("status", help="Show runtime status")
    p_status.add_argument("--json", action="store_true", help="JSON output")

    # ── spawn-exec ──
    p_exec = sub.add_parser("spawn-exec", help="Propose/create an executive agent")
    p_exec.add_argument("role", help="Role type (cto, coo, cfo, ciso, cro, cpo, ...)")
    p_exec.add_argument("--approve", action="store_true", help="Auto-approve creation")
    p_exec.add_argument("--enterprise", default="", help="Enterprise name")

    # ── poa ──
    p_poa = sub.add_parser("poa", help="Product Owner Agent management")
    poa_sub = p_poa.add_subparsers(dest="poa_command", required=True)
    
    p_poa_create = poa_sub.add_parser("create", help="Create a new POA")
    p_poa_create.add_argument("product", help="Product name")
    p_poa_create.add_argument("--endpoint", action="append", default=[], help="Endpoint URL")
    p_poa_create.add_argument("--service", default="", help="Systemd service name")
    p_poa_create.add_argument("--approve", action="store_true", help="Auto-approve")
    
    p_poa_list = poa_sub.add_parser("list", help="List all POAs")
    
    p_poa_audit = poa_sub.add_parser("audit", help="Run POA audit")
    p_poa_audit.add_argument("product", help="Product ID")

    # ── scale-report ──
    p_scale = sub.add_parser("scale-report", help="Scaling analysis")
    p_scale.add_argument("--workspace", "-w", default=".", help="Workspace path")
    p_scale.add_argument("--industry", default="", help="Industry type")

    # ── health ──
    p_health = sub.add_parser("health", help="Subsystem health check")
    p_health.add_argument("--verbose", "-v", action="store_true")

    # ── changeset ──
    p_cs = sub.add_parser("changeset", help="Changeset management (sandbox review)")
    cs_sub = p_cs.add_subparsers(dest="cs_command", required=True)
    
    p_cs_list = cs_sub.add_parser("list", help="List pending/recent changesets")
    p_cs_list.add_argument("--all", action="store_true", help="Include applied/rejected")
    p_cs_list.add_argument("--workspace", "-w", default=".", help="Workspace path")
    
    p_cs_show = cs_sub.add_parser("show", help="Show changeset details")
    p_cs_show.add_argument("id", help="Changeset ID")
    p_cs_show.add_argument("--workspace", "-w", default=".", help="Workspace path")
    
    p_cs_approve = cs_sub.add_parser("approve", help="Approve and apply a changeset")
    p_cs_approve.add_argument("id", help="Changeset ID")
    p_cs_approve.add_argument("--only", nargs="*", help="Only approve specific mutation IDs")
    p_cs_approve.add_argument("--workspace", "-w", default=".", help="Workspace path")
    
    p_cs_reject = cs_sub.add_parser("reject", help="Reject a changeset")
    p_cs_reject.add_argument("id", help="Changeset ID")
    p_cs_reject.add_argument("--workspace", "-w", default=".", help="Workspace path")
    
    p_cs_rollback = cs_sub.add_parser("rollback", help="Rollback an applied changeset")
    p_cs_rollback.add_argument("id", help="Changeset ID")
    p_cs_rollback.add_argument("--workspace", "-w", default=".", help="Workspace path")

    # ── test ──
    sub.add_parser("test", help="Run end-to-end test suite")

    args = parser.parse_args()

    try:
        if args.command == "init":
            cmd_init(args)
        elif args.command == "audit":
            cmd_audit(args)
        elif args.command == "status":
            cmd_status(args)
        elif args.command == "spawn-exec":
            cmd_spawn_exec(args)
        elif args.command == "poa":
            cmd_poa(args)
        elif args.command == "scale-report":
            cmd_scale_report(args)
        elif args.command == "health":
            cmd_health(args)
        elif args.command == "changeset":
            cmd_changeset(args)
        elif args.command == "test":
            cmd_test(args)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)


# ══════════════════════════════════════════════════════════════
# COMMANDS
# ══════════════════════════════════════════════════════════════

def cmd_init(args):
    """Initialize Singularity for a workspace."""
    from .formatters import (
        header, banner, section, success, error, warn, info, dim,
        kv, fmt, Table, StatusBox, bold, human_bytes,
    )
    from singularity.auditor import (
        WorkspaceScanner, WorkspaceAnalyzer, generate_report, save_report,
    )
    from singularity.poa.manager import POAManager
    from singularity.csuite.roles import RoleRegistry

    workspace = os.path.abspath(args.workspace)
    enterprise_name = args.name or os.path.basename(workspace).replace("-", " ").replace("_", " ").title()
    industry = args.industry or "tech"

    if not args.non_interactive:
        # Interactive wizard
        from .wizard import InitWizard
        wizard = InitWizard()
        if not wizard.run():
            sys.exit(1)
        return

    # ── Non-interactive: scan → analyze → propose → write ──

    print()
    print(banner([
        "SINGULARITY [AE]",
        "Autonomous Enterprise — First Boot",
        "",
        f"  Workspace:  {workspace}",
        f"  Enterprise: {enterprise_name}",
        f"  Industry:   {industry}",
    ]))
    print()

    # ── Phase 1: Create workspace structure ──
    print(section("Phase 1 — Workspace Setup"))
    print()

    sg_dir = os.path.join(workspace, ".singularity")
    dirs = ["poas", "audits", "roles", "logs", "comb", "sessions"]
    for d in dirs:
        os.makedirs(os.path.join(sg_dir, d), exist_ok=True)
    print(f"  {success(f'.singularity/ created ({len(dirs)} subdirs)')}")

    # Write workspace marker
    import time as _time
    marker_path = os.path.join(sg_dir, "workspace.json")
    marker = {
        "enterprise": enterprise_name,
        "industry": industry,
        "created": _time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "workspace": workspace,
        "version": "0.1.0",
    }
    with open(marker_path, "w") as f:
        json.dump(marker, f, indent=2)
    print(f"  {success('Workspace marker written')}")
    print()

    # ── Phase 2: Full workspace scan ──
    print(section("Phase 2 — Workspace Scan"))
    print()

    scanner = WorkspaceScanner(workspace)
    result = scanner.scan()

    print(f"  {info(f'Scanned in {result.scan_duration_ms:.0f}ms')}")
    print(f"  {kv('Projects', result.to_dict()['total_projects'])}")
    print(f"  {kv('Files', f'{result.total_files:,}')}")
    print(f"  {kv('Lines of code', f'{result.total_loc:,}')}")
    print(f"  {kv('.env files', len(result.env_files))}")
    print()

    # ── Phase 3: Analysis ──
    print(section("Phase 3 — Analysis"))
    print()

    analyzer = WorkspaceAnalyzer(result.projects, result.workspace)
    analysis = analyzer.analyze()

    # Health
    health = analysis.health_score
    health_icon = "🟢" if health >= 70 else "🟡" if health >= 40 else "🔴"
    print(f"  {kv('Health Score', f'{health_icon} {health}/100')}")
    print(f"  {kv('Total Projects', analysis.total_projects)}")
    print(f"  {kv('Total LOC', f'{analysis.total_lines:,}')}")
    print()

    # Top projects table
    sorted_projects = sorted(
        analysis.project_analyses,
        key=lambda p: p.project.total_lines,
        reverse=True,
    )

    if sorted_projects:
        t = Table(["Project", "LOC", "Grade", "Score"], align=["l", "r", "c", "r"])
        for pa in sorted_projects[:15]:
            grade_colors = {"A": fmt.BR_GREEN, "B": fmt.BR_GREEN, "C": fmt.BR_YELLOW, "D": fmt.BR_YELLOW}
            grade_c = grade_colors.get(pa.maturity.grade, fmt.BR_RED)
            t.add([
                pa.project.name[:40],
                f"{pa.project.total_lines:,}",
                f"{grade_c}{pa.maturity.grade}{fmt.RESET}",
                f"{pa.maturity.total}/100",
            ])
        if len(sorted_projects) > 15:
            t.add([dim(f"... +{len(sorted_projects) - 15} more"), "", "", ""])
        print(t.render())
        print()

    # Language summary
    if analysis.language_summary:
        t = Table(["Language", "LOC", "Share"], align=["l", "r", "r"])
        total_loc = sum(analysis.language_summary.values()) or 1
        for lang, loc in sorted(analysis.language_summary.items(), key=lambda x: -x[1])[:10]:
            pct = loc / total_loc * 100
            t.add([lang, f"{loc:,}", f"{pct:.1f}%"])
        print(t.render())
        print()

    # ── Phase 4: Proposals ──
    print(section("Phase 4 — Proposals"))
    print()

    # Executive proposals
    if analysis.exec_recommendations:
        print(f"  {bold('Executive Agents Proposed:')}")
        print()
        t = Table(["Role", "Priority", "Justification"], align=["l", "c", "l"])
        for r in analysis.exec_recommendations:
            priority_colors = {
                "critical": f"{fmt.BR_RED}CRITICAL{fmt.RESET}",
                "high": f"{fmt.BR_YELLOW}HIGH{fmt.RESET}",
                "medium": f"{fmt.BR_GREEN}MEDIUM{fmt.RESET}",
                "low": f"{fmt.DIM}LOW{fmt.RESET}",
            }
            t.add([
                f"{bold(r.role.upper())}",
                priority_colors.get(r.priority, r.priority),
                r.justification[:65],
            ])
        print(t.render())
        print()

        # Save proposed roles
        roles_dir = Path(sg_dir) / "roles"
        roles_dir.mkdir(parents=True, exist_ok=True)
        for r in analysis.exec_recommendations:
            role_data = {
                "role": r.role,
                "priority": r.priority,
                "justification": r.justification,
                "status": "proposed",
                "proposed_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            with open(roles_dir / f"{r.role}.json", "w") as f:
                json.dump(role_data, f, indent=2)
        print(f"  {success(f'{len(analysis.exec_recommendations)} executive roles proposed → .singularity/roles/')}")

    # POA proposals
    if analysis.poa_recommendations:
        print()
        print(f"  {bold(f'Product Owner Agents Proposed ({len(analysis.poa_recommendations)}):')}")
        print()

        # Group by priority: live services first, then published packages
        live_poas = [r for r in analysis.poa_recommendations if "Live service" in r.justification]
        pkg_poas = [r for r in analysis.poa_recommendations if "Live service" not in r.justification]

        if live_poas:
            t = Table(["Product (Live)", "Justification"], align=["l", "l"])
            for r in live_poas[:10]:
                t.add([r.product_name[:35], r.justification[:55]])
            if len(live_poas) > 10:
                t.add([dim(f"... +{len(live_poas) - 10} more"), ""])
            print(t.render())
            print()

        if pkg_poas:
            t = Table(["Product (Published)", "Justification"], align=["l", "l"])
            for r in pkg_poas[:10]:
                t.add([r.product_name[:35], r.justification[:55]])
            if len(pkg_poas) > 10:
                t.add([dim(f"... +{len(pkg_poas) - 10} more"), ""])
            print(t.render())
            print()

        # Save POA proposals to manager
        mgr = POAManager(Path(sg_dir))
        for r in analysis.poa_recommendations:
            mgr.propose(product_name=r.product_name, description=r.justification)
        print(f"  {success(f'{len(analysis.poa_recommendations)} POAs proposed → .singularity/poas/')}")

    # ── Phase 5: Risks & Gaps ──
    print()
    print(section("Phase 5 — Risks & Gaps"))
    print()

    # Global risks
    if analysis.global_risks:
        for r in analysis.global_risks:
            icon = {"critical": fmt.BR_RED, "high": fmt.BR_YELLOW, "medium": fmt.BR_CYAN}.get(r.severity, fmt.DIM)
            print(f"  {icon}●{fmt.RESET} [{r.severity.upper()}] {r.description}")
        print()

    # Aggregate project gaps
    all_gaps = []
    for pa in analysis.project_analyses:
        for g in pa.gaps:
            all_gaps.append((pa.project.name, g))

    critical_gaps = [g for g in all_gaps if g[1].severity == "critical"]
    high_gaps = [g for g in all_gaps if g[1].severity == "high"]
    medium_gaps = [g for g in all_gaps if g[1].severity == "medium"]

    print(f"  {kv('Total gaps', len(all_gaps))}")
    if critical_gaps:
        print(f"  {kv('Critical', f'{fmt.BR_RED}{len(critical_gaps)}{fmt.RESET}')}")
    if high_gaps:
        print(f"  {kv('High', f'{fmt.BR_YELLOW}{len(high_gaps)}{fmt.RESET}')}")
    if medium_gaps:
        print(f"  {kv('Medium', f'{fmt.BR_CYAN}{len(medium_gaps)}{fmt.RESET}')}")
    print()

    if critical_gaps:
        print(f"  {bold('Critical gaps (top 10):')}")
        for name, g in critical_gaps[:10]:
            print(f"    {fmt.BR_RED}✗{fmt.RESET} {name}: {g.description}")
        if len(critical_gaps) > 10:
            print(f"    {dim(f'... +{len(critical_gaps) - 10} more')}")
        print()

    # ── Phase 6: Save reports ──
    print(section("Phase 6 — Reports"))
    print()

    report = generate_report(result, analysis)
    json_path, md_path = save_report(report, os.path.join(sg_dir, "audits"))
    print(f"  {success(f'JSON: {json_path}')}")
    print(f"  {success(f'Markdown: {md_path}')}")
    print()

    # ── Summary ──
    print(banner([
        "Init Complete ⚡",
        "",
        f"  Health:       {health_icon} {health}/100",
        f"  Projects:     {analysis.total_projects}",
        f"  LOC:          {analysis.total_lines:,}",
        f"  Executives:   {len(analysis.exec_recommendations)} proposed",
        f"  POAs:         {len(analysis.poa_recommendations)} proposed",
        f"  Gaps:         {len(all_gaps)} ({len(critical_gaps)} critical)",
        "",
        "  Next steps:",
        "    singularity status          — View current state",
        "    singularity spawn-exec ROLE — Approve an executive",
        "    singularity poa list        — View proposed POAs",
        "    singularity audit           — Re-run full audit",
    ], color=fmt.BR_GREEN))
    print()


def cmd_audit(args):
    """Audit workspace — full rescan and analysis."""
    from .formatters import (
        header, section, success, info, warn, kv, fmt, Table, bold, dim,
    )
    from singularity.auditor import (
        WorkspaceScanner, WorkspaceAnalyzer, generate_report, save_report,
    )

    header("SINGULARITY [AE] — Workspace Audit")

    workspace = os.path.abspath(args.workspace)
    sg_dir = os.path.join(workspace, ".singularity")
    audit_dir = args.output or os.path.join(sg_dir, "audits")

    # Scan
    print(f"  {info(f'Scanning {workspace} ...')}")
    scanner = WorkspaceScanner(workspace)
    result = scanner.scan()

    print(f"  {info(f'Scanned in {result.scan_duration_ms:.0f}ms')}")
    print(f"  {kv('Projects', result.to_dict()['total_projects'])}")
    print(f"  {kv('Files', f'{result.total_files:,}')}")
    print(f"  {kv('LOC', f'{result.total_loc:,}')}")
    print()

    # Analyze
    analyzer = WorkspaceAnalyzer(result.projects, result.workspace)
    analysis = analyzer.analyze()

    health = analysis.health_score
    health_icon = "🟢" if health >= 70 else "🟡" if health >= 40 else "🔴"
    print(f"  {kv('Health', f'{health_icon} {health}/100')}")
    print()

    # Top projects
    sorted_projects = sorted(
        analysis.project_analyses,
        key=lambda p: p.project.total_lines,
        reverse=True,
    )
    if sorted_projects:
        t = Table(["Project", "LOC", "Grade", "Score"], align=["l", "r", "c", "r"])
        for pa in sorted_projects[:20]:
            grade_colors = {"A": fmt.BR_GREEN, "B": fmt.BR_GREEN, "C": fmt.BR_YELLOW, "D": fmt.BR_YELLOW}
            grade_c = grade_colors.get(pa.maturity.grade, fmt.BR_RED)
            t.add([
                pa.project.name[:40],
                f"{pa.project.total_lines:,}",
                f"{grade_c}{pa.maturity.grade}{fmt.RESET}",
                f"{pa.maturity.total}/100",
            ])
        if len(sorted_projects) > 20:
            t.add([dim(f"... +{len(sorted_projects) - 20} more"), "", "", ""])
        print(t.render())
        print()

    # Executive proposals
    if analysis.exec_recommendations:
        print(f"  {bold('Executive Proposals:')}")
        for r in analysis.exec_recommendations:
            icon = {"critical": "🔴", "high": "🟡", "medium": "🟢", "low": "⚪"}.get(r.priority, "⚪")
            print(f"    {icon} {r.role.upper():6s} — {r.justification}")
        print()

    # POA proposals
    if analysis.poa_recommendations:
        print(f"  {bold(f'POA Proposals: {len(analysis.poa_recommendations)}')}")
        for r in analysis.poa_recommendations[:10]:
            print(f"    📦 {r.product_name:35s} — {r.justification[:55]}")
        if len(analysis.poa_recommendations) > 10:
            print(f"    {dim(f'... +{len(analysis.poa_recommendations) - 10} more')}")
        print()

    # Risks
    if analysis.global_risks:
        print(f"  {bold('Risks:')}")
        for r in analysis.global_risks:
            icon = {"critical": "🔴", "high": "🟡", "medium": "🟢"}.get(r.severity, "⚪")
            print(f"    {icon} {r.description}")
        print()

    # Gaps summary
    all_gaps = []
    for pa in analysis.project_analyses:
        for g in pa.gaps:
            all_gaps.append((pa.project.name, g))
    critical = sum(1 for _, g in all_gaps if g.severity == "critical")
    high = sum(1 for _, g in all_gaps if g.severity == "high")
    print(f"  {kv('Gaps', f'{len(all_gaps)} total ({critical} critical, {high} high)')}")
    print()

    # Save
    report = generate_report(result, analysis)
    os.makedirs(audit_dir, exist_ok=True)
    json_path, md_path = save_report(report, audit_dir)
    print(f"  {success(f'Report saved: {json_path}')}")


def cmd_status(args):
    """Show runtime status."""
    from .formatters import header, info
    header("SINGULARITY [AE] — Status")
    
    # Check if .singularity exists
    sg_dir = Path(".singularity")
    if not sg_dir.exists():
        print("❌ Not initialized. Run 'singularity init' first.")
        sys.exit(1)
    
    # Check for POAs
    from singularity.poa.manager import POAManager
    mgr = POAManager(sg_dir)
    poas = mgr.list_all()
    
    # Check for roles
    roles_dir = sg_dir / "roles"
    role_files = list(roles_dir.glob("*.json")) if roles_dir.exists() else []
    
    # Check for audits
    audit_dir = sg_dir / "audits"
    audits = sorted(audit_dir.glob("*.json"), reverse=True) if audit_dir.exists() else []
    
    if args.json:
        data = {
            "initialized": True,
            "poas": [p.to_dict() for p in poas],
            "roles": len(role_files),
            "audits": len(audits),
            "last_audit": str(audits[0]) if audits else None,
        }
        print(json.dumps(data, indent=2))
    else:
        info(f"POAs: {len(poas)} ({len(mgr.list_active())} active)")
        for p in poas:
            icon = {"active": "🟢", "proposed": "📋", "paused": "⏸️"}.get(p.status.value, "⚪")
            print(f"  {icon} {p.product_name} [{p.status.value}]")
        
        info(f"Executive roles: {len(role_files)}")
        for f in role_files:
            print(f"  📁 {f.stem}")
        
        info(f"Audits: {len(audits)}")
        if audits:
            print(f"  Latest: {audits[0].name}")


def cmd_spawn_exec(args):
    """Propose/create an executive agent."""
    from .formatters import header, info, success, warn
    from singularity.csuite.roles import RoleRegistry, RoleType
    
    header("SINGULARITY [AE] — Executive Proposal")
    
    enterprise = args.enterprise or "Enterprise"
    reg = RoleRegistry(enterprise=enterprise)
    
    role_name = args.role.lower()
    
    # Build proposal
    proposal = {
        "role": role_name,
        "title": f"Chief {role_name[1:].upper() if len(role_name) > 1 else role_name.upper()} Officer",
    }
    
    info(f"Proposed role: {role_name.upper()}")
    role = reg.spawn_role(proposal)
    
    print(f"\n  📋 Title:    {role.title}")
    print(f"  {role.emoji} Emoji:    {role.emoji}")
    print(f"  📝 Domain:   {role.domain}")
    print(f"  🔧 Tools:    {', '.join(role.tools.allowed_tools)}")
    print(f"  🔍 Keywords: {len(role.keywords)} routing keywords")
    print(f"  📊 Audit:    {len(role.audit.checks)} check types")
    
    if args.approve:
        # Save role to .singularity/roles/
        roles_dir = Path(".singularity/roles")
        roles_dir.mkdir(parents=True, exist_ok=True)
        role.save(roles_dir / f"{role_name}.json")
        success(f"Executive {role_name.upper()} created and saved.")
    else:
        warn("Not approved. Run with --approve to create.")


def cmd_poa(args):
    """POA management commands."""
    from .formatters import header, info, success, warn
    
    sg_dir = Path(".singularity")
    if not sg_dir.exists():
        print("❌ Not initialized. Run 'singularity init' first.")
        sys.exit(1)
    
    from singularity.poa.manager import POAManager, Endpoint
    from singularity.poa.runtime import POARuntime
    
    mgr = POAManager(sg_dir)
    
    if args.poa_command == "list":
        header("SINGULARITY [AE] — POA List")
        poas = mgr.list_all()
        if not poas:
            info("No POAs configured.")
        for p in poas:
            icon = {"active": "🟢", "proposed": "📋", "paused": "⏸️"}.get(p.status.value, "⚪")
            print(f"  {icon} {p.product_name} ({p.product_id}) [{p.status.value}]")
            for ep in p.endpoints:
                print(f"      → {ep.url}")
        
    elif args.poa_command == "create":
        header("SINGULARITY [AE] — POA Creation")
        endpoints = [{"url": u, "name": u.split("/")[-1]} for u in args.endpoint]
        
        config = mgr.propose(
            product_name=args.product,
            endpoints=endpoints,
            service_name=args.service,
        )
        
        info(f"Proposed POA: {config.product_name}")
        print(f"  ID: {config.product_id}")
        print(f"  Endpoints: {len(config.endpoints)}")
        for ep in config.endpoints:
            print(f"    → {ep.url}")
        if config.service_name:
            print(f"  Service: {config.service_name}")
        
        if args.approve:
            mgr.approve(config.product_id)
            mgr.activate(config.product_id)
            
            # Run first audit
            report = POARuntime.run_audit(config)
            POARuntime.save_audit(report, sg_dir / "poas")
            
            icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(report.overall_status, "⚪")
            success(f"POA created and activated. First audit: {icon} {report.overall_status.upper()}")
        else:
            warn("Not approved. Run with --approve to create.")
    
    elif args.poa_command == "audit":
        header("SINGULARITY [AE] — POA Audit")
        config = mgr.get(args.product)
        if not config:
            print(f"❌ POA not found: {args.product}")
            sys.exit(1)
        
        report = POARuntime.run_audit(config)
        POARuntime.save_audit(report, sg_dir / "poas")
        
        print(report.to_markdown())


def cmd_scale_report(args):
    """Show scaling analysis."""
    from .formatters import header, info
    from singularity.csuite.roles import RoleRegistry
    
    header("SINGULARITY [AE] — Scale Report")
    workspace = os.path.abspath(args.workspace)
    
    # Quick workspace scan
    audit_data = _quick_scan(workspace)
    
    reg = RoleRegistry(enterprise="Enterprise", industry=args.industry)
    proposals = reg.propose_roles(audit_data)
    
    info(f"Workspace: {workspace}")
    info(f"Projects: {audit_data.get('project_count', 0)}")
    info(f"Live products: {audit_data.get('live_products', 0)}")
    info(f"Industry: {args.industry or 'general'}")
    
    print(f"\n  Recommended executives ({len(proposals)}):")
    for p in proposals:
        priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(p["priority"], "⚪")
        print(f"    {priority_icon} {p['title']} — {p['justification']}")
    
    if not proposals:
        print("    ✅ Current executive roster is sufficient.")


def cmd_health(args):
    """Health check."""
    from .formatters import header, kv, fmt
    from singularity.immune.vitals import collect_vitals
    
    header("SINGULARITY [AE] — Health")
    
    v = collect_vitals()
    
    disk_color = fmt.BR_RED if v.disk_used_pct > 93 else fmt.BR_YELLOW if v.disk_used_pct > 85 else fmt.BR_GREEN
    mem_color = fmt.BR_RED if v.memory_used_pct > 90 else fmt.BR_YELLOW if v.memory_used_pct > 80 else fmt.BR_GREEN
    load_color = fmt.BR_RED if v.load_average_1m > 4 else fmt.BR_YELLOW if v.load_average_1m > 2 else fmt.BR_GREEN
    
    print(kv("Disk", f"{disk_color}{v.disk_used_pct:.1f}%{fmt.RESET} used ({v.disk_free_gb:.1f}GB free)"))
    print(kv("Memory", f"{mem_color}{v.memory_used_pct:.1f}%{fmt.RESET} used ({v.memory_available_mb:.0f}MB available)"))
    print(kv("Load", f"{load_color}{v.load_average_1m:.2f}{fmt.RESET}"))
    print(kv("Uptime", f"{v.uptime_seconds / 3600:.1f}h"))
    
    degraded = v.disk_used_pct > 93 or v.memory_used_pct > 90
    if degraded:
        print(f"\n  ⚠️ DEGRADED — resource pressure detected")
        sys.exit(1)
    else:
        print(f"\n  🟢 HEALTHY")
        sys.exit(0)


def cmd_test(args):
    """Run end-to-end tests."""
    test_file = PROJECT_ROOT / "tests" / "test_e2e.py"
    os.execvp(sys.executable, [sys.executable, str(test_file)])


def cmd_changeset(args):
    """Changeset management — sandbox review and approval."""
    from .formatters import header, kv, fmt, success, error, warn, info, Table
    from singularity.sinew.changeset import ChangesetManager, MutationStatus
    
    workspace = os.path.abspath(getattr(args, 'workspace', '.'))
    manager = ChangesetManager(workspace)
    
    if args.cs_command == "list":
        header("SINGULARITY [AE] — Changesets")
        
        # Show pending (in-memory)
        pending = manager.list_pending()
        if pending:
            print(f"\n  {fmt.BOLD}Pending ({len(pending)}):{fmt.RESET}")
            for cs in pending:
                risk = cs._risk_breakdown()
                risk_str = ""
                if risk["critical"]: risk_str += f" {fmt.BR_RED}{risk['critical']} critical{fmt.RESET}"
                if risk["high"]: risk_str += f" {fmt.BR_YELLOW}{risk['high']} high{fmt.RESET}"
                mut_count = len(cs.mutations)
                print(f"    📋 {cs.id}  [{cs.agent_role}]  {mut_count} changes{risk_str}")
                print(f"       {fmt.DIM}{cs.task[:70]}{fmt.RESET}")
        else:
            print(f"\n  {fmt.DIM}No pending changesets.{fmt.RESET}")
        
        # Show recent records from disk
        if getattr(args, 'all', False):
            records = manager.list_records(limit=20)
            if records:
                print(f"\n  {fmt.BOLD}Recent ({len(records)}):{fmt.RESET}")
                for r in records:
                    status_icon = {
                        "applied": "✅", "rejected": "❌", 
                        "rolled_back": "⏪", "failed": "💥",
                    }.get(r.get("status", ""), "❓")
                    print(f"    {status_icon} {r['id']}  [{r.get('agent_role', '?')}]  {r.get('status', '?')}  {r.get('mutation_count', 0)} changes")
        print()
    
    elif args.cs_command == "show":
        header("SINGULARITY [AE] — Changeset Details")
        
        cs = manager.get_changeset(args.id)
        if cs:
            print(f"\n{cs.summary()}")
            print()
            # Show full diffs for each mutation
            for i, m in enumerate(cs.mutations, 1):
                risk_color = {"critical": fmt.BR_RED, "high": fmt.BR_YELLOW, "medium": fmt.BR_CYAN, "low": fmt.BR_GREEN}.get(m.risk, "")
                print(f"  ═══ Mutation {i}/{len(cs.mutations)} [{m.id}] ═══")
                print(f"  Type: {m.type.value}  Risk: {risk_color}{m.risk.upper()}{fmt.RESET}")
                
                if m.type.value == "write":
                    print(f"  Path: {m.path}")
                    print(f"  Size: {len(m.content)} bytes")
                    preview = m.content[:500]
                    if preview:
                        print(f"  Preview:")
                        for line in preview.split('\n')[:15]:
                            print(f"    {fmt.BR_GREEN}+ {line}{fmt.RESET}")
                        if len(m.content) > 500:
                            print(f"    {fmt.DIM}... ({len(m.content) - 500} more bytes){fmt.RESET}")
                
                elif m.type.value == "edit":
                    print(f"  Path: {m.path}")
                    print(f"  Remove:")
                    for line in m.old_text.split('\n')[:10]:
                        print(f"    {fmt.BR_RED}- {line}{fmt.RESET}")
                    print(f"  Add:")
                    for line in m.new_text.split('\n')[:10]:
                        print(f"    {fmt.BR_GREEN}+ {line}{fmt.RESET}")
                
                elif m.type.value == "exec":
                    print(f"  Command: {m.command}")
                
                print()
        else:
            # Try disk
            loaded = manager._load_record(args.id)
            if loaded:
                print(f"\n  (Loaded from disk — completed changeset)")
                data = json.loads((manager.changeset_dir / f"{args.id}.json").read_text())
                print(f"  Status: {data.get('status', '?')}")
                print(f"  Agent:  {data.get('agent_role', '?')}")
                print(f"  Task:   {data.get('task', '?')}")
                print(f"  Changes: {data.get('mutation_count', 0)}")
                for m in data.get("mutations", []):
                    print(f"    {m.get('status', '?')} {m.get('type', '?')} {m.get('path', m.get('command', ''))[:60]}")
            else:
                error(f"Changeset {args.id} not found")
        print()
    
    elif args.cs_command == "approve":
        header("SINGULARITY [AE] — Approve Changeset")
        
        cs = manager.get_changeset(args.id)
        if not cs:
            error(f"Changeset {args.id} not found (must be pending in current session)")
            sys.exit(1)
        
        # Show summary first
        print(f"\n{cs.summary()}")
        
        approved_ids = set(args.only) if args.only else None
        
        if approved_ids:
            print(f"\n  Approving {len(approved_ids)} of {len(cs.mutations)} mutations...")
        else:
            print(f"\n  Approving ALL {len(cs.mutations)} mutations...")
        
        # Confirm
        try:
            answer = input(f"\n  Apply changes? [y/N] ")
            if answer.lower() not in ("y", "yes"):
                print("  Aborted.")
                sys.exit(0)
        except (EOFError, KeyboardInterrupt):
            print("\n  Aborted.")
            sys.exit(0)
        
        result = asyncio.run(manager.apply(args.id, approved_ids))
        
        if result.get("success"):
            success(f"Applied {result.get('applied', 0)} mutations")
            if result.get("failed"):
                warn(f"Failed: {result['failed']}")
        else:
            error(f"Apply failed: {result.get('error', 'unknown')}")
            if result.get("rolled_back"):
                warn("Workspace has been rolled back to pre-changeset state")
            sys.exit(1)
        print()
    
    elif args.cs_command == "reject":
        header("SINGULARITY [AE] — Reject Changeset")
        
        cs = manager.get_changeset(args.id)
        if not cs:
            error(f"Changeset {args.id} not found")
            sys.exit(1)
        
        result = asyncio.run(manager.reject(args.id))
        if result.get("success"):
            success(f"Rejected {result.get('rejected', 0)} mutations")
        else:
            error(f"Reject failed: {result.get('error', 'unknown')}")
        print()
    
    elif args.cs_command == "rollback":
        header("SINGULARITY [AE] — Rollback Changeset")
        
        cs = manager.get_changeset(args.id) 
        if not cs:
            error(f"Changeset {args.id} not found")
            sys.exit(1)
        
        if not cs.git_stash_ref:
            error("No git snapshot available — cannot rollback")
            sys.exit(1)
        
        try:
            answer = input(f"  Rollback changeset {args.id}? This will revert {len(cs.mutations)} mutations. [y/N] ")
            if answer.lower() not in ("y", "yes"):
                print("  Aborted.")
                sys.exit(0)
        except (EOFError, KeyboardInterrupt):
            print("\n  Aborted.")
            sys.exit(0)
        
        result = asyncio.run(manager.rollback(args.id))
        if result.get("success"):
            success("Workspace rolled back successfully")
        else:
            error(f"Rollback failed: {result.get('error', 'unknown')}")
        print()


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def _run_audit(workspace: str, enterprise: str = "", industry: str = "", output_path: str = None):
    """Run workspace audit and print results."""
    from .formatters import info, success, warn
    
    audit_data = _quick_scan(workspace)
    
    info(f"Scanned: {workspace}")
    info(f"Projects: {audit_data.get('project_count', 0)}")
    info(f"Code projects: {audit_data.get('code_projects', 0)}")
    info(f"Live products: {audit_data.get('live_products', 0)}")
    
    if audit_data.get("has_security_concerns"):
        warn("Security concerns detected (exposed .env files)")
    
    # Save audit
    from datetime import datetime, timezone
    import json as _json
    
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    audit_dir = os.path.join(workspace, ".singularity", "audits")
    os.makedirs(audit_dir, exist_ok=True)
    
    out_path = output_path or os.path.join(audit_dir, f"{ts}.json")
    with open(out_path, "w") as f:
        _json.dump(audit_data, f, indent=2)
    
    success(f"Audit saved: {out_path}")
    
    # Propose roles
    from singularity.csuite.roles import RoleRegistry
    reg = RoleRegistry(enterprise=enterprise, industry=industry)
    proposals = reg.propose_roles(audit_data)
    
    if proposals:
        info(f"\nRecommended executives ({len(proposals)}):")
        for p in proposals:
            print(f"  → {p['title']} ({p['priority']}): {p['justification']}")


def _quick_scan(workspace: str) -> dict:
    """Quick workspace scan for scaling analysis."""
    workspace = Path(workspace)
    
    # Scan for project indicators
    project_count = 0
    code_projects = 0
    has_code = False
    has_infra = False
    has_finance = False
    has_security = False
    has_data = False
    has_marketing = False
    has_compliance = False
    live_products = 0
    env_files = []
    
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".singularity", ".cache"}
    
    for entry in workspace.iterdir():
        if entry.name.startswith(".") and entry.name not in (".env",):
            if entry.name == ".env":
                env_files.append(str(entry))
            continue
        if entry.name in skip_dirs:
            continue
        if not entry.is_dir():
            if entry.name == ".env":
                env_files.append(str(entry))
                has_security = True
            continue
        
        # Check if it's a project
        is_project = False
        for marker in ["pyproject.toml", "setup.py", "package.json", "Cargo.toml", "go.mod", "Makefile", "Dockerfile"]:
            if (entry / marker).exists():
                is_project = True
                code_projects += 1
                has_code = True
                break
        
        if is_project or (entry / "README.md").exists():
            project_count += 1
        
        # Check for infrastructure indicators
        if any((entry / f).exists() for f in [".github", ".gitlab-ci.yml", "Dockerfile", "docker-compose.yml"]):
            has_infra = True
        
        # Check for finance indicators
        dir_name = entry.name.lower()
        if any(kw in dir_name for kw in ["finance", "billing", "payment", "pricing", "revenue"]):
            has_finance = True
        
        # Check for data pipeline indicators
        if any(kw in dir_name for kw in ["data", "pipeline", "etl", "analytics", "ml"]):
            has_data = True
        
        # Check for marketing indicators
        if any(kw in dir_name for kw in ["marketing", "social", "brand", "content"]):
            has_marketing = True
        
        # Check for live service indicators (systemd, pm2, etc.)
        if (entry / "systemd").exists() or (entry / ".service").exists():
            live_products += 1
    
    # Check .env exposure
    if env_files:
        has_security = True
    
    # Check for running services related to this workspace
    try:
        import subprocess
        result = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--state=active", "--no-legend"],
            capture_output=True, text=True, timeout=5,
        )
        # Count services that might be related (very rough heuristic)
        for line in result.stdout.strip().split("\n"):
            if any(kw in line.lower() for kw in ["api", "app", "web", "gateway", "cloud"]):
                live_products += 1
    except Exception:
        pass
    
    return {
        "workspace": str(workspace),
        "project_count": project_count,
        "code_projects": code_projects,
        "has_code": has_code,
        "has_infrastructure": has_infra,
        "has_finance": has_finance,
        "has_security_concerns": has_security,
        "has_data_pipeline": has_data,
        "has_marketing": has_marketing,
        "has_compliance_needs": has_compliance,
        "has_customers": live_products > 0,
        "live_products": live_products,
        "env_files": env_files,
    }


if __name__ == "__main__":
    main()
