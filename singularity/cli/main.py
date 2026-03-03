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
    from .formatters import header, success, info
    from .wizard import run_wizard

    header("SINGULARITY [AE] — Init")
    
    if args.non_interactive:
        workspace = os.path.abspath(args.workspace)
        config = {
            "workspace": workspace,
            "enterprise": args.name or os.path.basename(workspace),
            "industry": args.industry or "general",
        }
    else:
        config = run_wizard(
            workspace=args.workspace,
            industry=args.industry,
            name=args.name,
        )
    
    workspace = config["workspace"]
    
    # Create .singularity directory
    sg_dir = os.path.join(workspace, ".singularity")
    os.makedirs(os.path.join(sg_dir, "poas"), exist_ok=True)
    os.makedirs(os.path.join(sg_dir, "audits"), exist_ok=True)
    os.makedirs(os.path.join(sg_dir, "roles"), exist_ok=True)
    os.makedirs(os.path.join(sg_dir, "logs"), exist_ok=True)
    
    success(f"Workspace initialized: {workspace}")
    
    # Run first audit
    info("Running first workspace audit...")
    _run_audit(workspace, config.get("enterprise", ""), config.get("industry", ""))
    
    success("Init complete. Run 'singularity status' to check.")


def cmd_audit(args):
    """Audit workspace."""
    from .formatters import header
    header("SINGULARITY [AE] — Workspace Audit")
    workspace = os.path.abspath(args.workspace)
    _run_audit(workspace, output_path=args.output)


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
    from .formatters import header
    from singularity.immune.vitals import SystemVitals
    
    header("SINGULARITY [AE] — Health")
    
    v = SystemVitals()
    print(f"  Disk:    {v.disk_used_pct:.1f}% used ({v.disk_free_gb:.1f}GB free)")
    print(f"  Memory:  {v.memory_used_pct:.1f}% used ({v.memory_available_mb:.0f}MB available)")
    print(f"  Load:    {v.load_average_1m:.2f}")
    print(f"  Uptime:  {v.uptime_seconds / 3600:.1f}h")
    
    if v.disk_used_pct > 93 or v.memory_used_pct > 90:
        print("\n  ⚠️ DEGRADED — resource pressure detected")
        sys.exit(1)
    else:
        print("\n  🟢 HEALTHY")
        sys.exit(0)


def cmd_test(args):
    """Run end-to-end tests."""
    test_file = PROJECT_ROOT / "tests" / "test_e2e.py"
    os.execvp(sys.executable, [sys.executable, str(test_file)])


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
