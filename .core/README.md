# .core/ — Singularity Operational Core
# =============================================
#
# All operational data that makes Singularity run.
# Imported from Plug + executives/ + .plug/ on Day 19 (2026-03-03).
#
# This is the RUNTIME DATA, not the SOUL.
# The runtime's personality lives in its identity/config files.
# .core/ is everything else — config, dispatch, reports, secrets, infrastructure.
#
# Directory Layout:
#
#   config/           — Runtime configuration (models, channels, personas, budgets)
#   profiles/         — Executive + personnel profiles (who does what)
#   operations/       — Operational playbooks, launch plans, degraded mode
#   reports/          — Executive report archives (CTO/COO/CFO/CISO)
#   logs/             — Dispatch logs, report feeds, mode transitions
#   standing-orders/  — Periodic executive tasks (heartbeats, audits)
#   infrastructure/   — System reference docs (what's normal, what to flag)
#   secrets/          — vault.enc + credential management
#
# Origin Map:
#   ~/.plug/config.json           → config/runtime.yaml
#   executives/plug-csuite-config → config/csuite.yaml
#   executives/dispatch.py        → (stays in aria/csuite/dispatch.py — native now)
#   executives/profiles/          → profiles/
#   executives/operations/        → operations/
#   executives/*/reports/         → reports/
#   executives/dispatch_log.jsonl → logs/
#   executives/INFRASTRUCTURE.md  → infrastructure/
#   executives/watchdog.sh        → infrastructure/
#   aria_memory/pulse-budget.json → config/pulse.yaml
#   NEW: vault.enc                → secrets/
