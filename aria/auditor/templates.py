"""
TEMPLATES — Executive and POA Configuration Generators
========================================================
Generates configs for spawning C-Suite executives and Product Owner Agents.
"""
from __future__ import annotations
from datetime import datetime, timezone

EXEC_TEMPLATES = {
    "CTO": {"domain": "technology", "focus": ["architecture", "code quality", "CI/CD", "technical debt", "infrastructure"]},
    "COO": {"domain": "operations", "focus": ["deployment", "monitoring", "SLAs", "workflows", "coordination"]},
    "CFO": {"domain": "finance", "focus": ["costs", "revenue", "budgets", "runway", "pricing"]},
    "CISO": {"domain": "security", "focus": ["secrets", "vulnerabilities", "compliance", "incident response", "access control"]},
    "CMO": {"domain": "marketing", "focus": ["growth", "content", "social media", "landing pages", "user acquisition"]},
}

def generate_exec_config(role: str, domain: str, workspace_context: dict | None = None) -> dict:
    template = EXEC_TEMPLATES.get(role.upper(), {"domain": domain, "focus": [domain]})
    ctx = workspace_context or {}
    return {
        "role": role.upper(),
        "domain": template["domain"],
        "system_prompt": (
            f"You are the {role.upper()} ({template['domain']}) for this enterprise. "
            f"Your focus areas: {', '.join(template['focus'])}. "
            f"You receive tasks, analyze them, execute within your domain, and report results. "
            f"Be direct, actionable, and data-driven. Cite specific files and metrics."
        ),
        "tools": _tools_for_role(role.upper()),
        "report_format": {
            "sections": ["summary", "findings", "actions_taken", "recommendations", "metrics"],
            "max_length": 2000,
            "format": "markdown",
        },
        "focus_areas": template["focus"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace_projects": ctx.get("total_projects", 0),
        "workspace_loc": ctx.get("total_lines", 0),
    }

def _tools_for_role(role: str) -> list[str]:
    base = ["read", "write", "exec", "web_fetch", "memory_search"]
    role_tools = {
        "CTO": ["git_status", "run_tests", "lint", "dependency_audit"],
        "COO": ["service_status", "deploy", "monitor", "cron_manage"],
        "CFO": ["cost_report", "revenue_track", "budget_check"],
        "CISO": ["secret_scan", "vuln_scan", "access_audit", "ssl_check"],
        "CMO": ["analytics", "social_post", "seo_check", "content_publish"],
    }
    return base + role_tools.get(role, [])

def generate_poa_config(product_name: str, project_path: str, audit_data: dict | None = None) -> dict:
    ad = audit_data or {}
    return {
        "product_name": product_name,
        "project_path": project_path,
        "system_prompt": (
            f"You are the Product Owner Agent for {product_name}. "
            f"You own this product end-to-end: health monitoring, customer support tier-1, "
            f"metrics tracking, documentation upkeep, and escalation to AVA when needed. "
            f"Run audits every 4 hours. Generate weekly reports. Be proactive."
        ),
        "audit_schedule": "0 */4 * * *",
        "report_schedule": "0 18 * * 5",
        "health_checks": [
            {"name": "endpoint_health", "type": "http", "interval": 300},
            {"name": "ssl_expiry", "type": "ssl", "interval": 86400},
            {"name": "error_rate", "type": "log", "interval": 3600},
            {"name": "disk_usage", "type": "system", "interval": 3600},
        ],
        "escalation_chain": ["poa", "ava", "ali"],
        "thresholds": {
            "response_time_ms": 2000,
            "error_rate_pct": 5.0,
            "ssl_expiry_days": 14,
            "disk_usage_pct": 90,
        },
        "metrics": ["signups", "api_calls", "error_rate", "uptime", "response_time"],
        "maturity_score": ad.get("maturity", {}).get("total", 0),
        "known_gaps": [g.get("description", "") for g in ad.get("gaps", [])[:5]],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
