"""
CSUITE — Native Executive Team (v2)
=======================================

Self-scaling executive system. Roles are data, not code.
Singularity proposes roles based on workspace audit results.

Architecture:
    Coordinator receives dispatch → routes to executive(s) → 
    executives run their own AgentLoop with scoped tools/permissions →
    results flow back through the bus → Coordinator aggregates

Subsystems:
    - roles.py       — Role definitions, registry, templates (industry-agnostic)
    - executive.py   — Executive agent class (wraps AgentLoop with role/permissions)
    - coordinator.py — Dispatch logic (task routing, aggregation, escalation)
    - dispatch.py    — Dispatch interface
    - reports.py     — Report aggregation, formatting, delivery
"""

from .roles import Role, RoleType, RoleRegistry, ToolScope, EscalationPolicy, match_roles
from .executive import Executive
from .coordinator import Coordinator
from .dispatch import Dispatcher, load_webhooks, load_deployment

__all__ = [
    "Role", "RoleType", "RoleRegistry", "ToolScope", "EscalationPolicy",
    "match_roles",
    "Executive",
    "Coordinator",
    "Dispatcher",
    "load_webhooks",
    "load_deployment",
]
