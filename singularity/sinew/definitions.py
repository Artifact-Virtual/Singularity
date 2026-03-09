"""
SINEW — Tool Definitions
===========================

OpenAI function-calling format tool schemas.
These are passed to the LLM so it knows what tools are available.

Keep this separate from executor.py so:
1. Schemas are readable and maintainable
2. You can add a tool definition without touching execution logic
3. Testing can validate schemas independently
"""

from __future__ import annotations

from typing import Any


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "exec",
            "description": "Execute a shell command and return its output (stdout + stderr).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Timeout in seconds (default 30)",
                    },
                    "workdir": {
                        "type": "string",
                        "description": "Working directory (defaults to workspace)",
                    },
                    "background": {
                        "type": "boolean",
                        "description": "Run in background (returns PID)",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read the contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to read",
                    },
                    "offset": {
                        "type": "number",
                        "description": "Line number to start from (1-indexed)",
                    },
                    "limit": {
                        "type": "number",
                        "description": "Max lines to read",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write",
            "description": "Write content to a file. Creates parent directories automatically. USE THIS to create new files or overwrite existing ones. Do not describe file contents — write them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to write to",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit",
            "description": "Edit a file by replacing exact text. USE THIS to apply code changes, fix bugs, update configs. Do not narrate edits — execute them. Find the exact oldText in the file, replace with newText.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to edit",
                    },
                    "oldText": {
                        "type": "string",
                        "description": "Exact text to find and replace",
                    },
                    "newText": {
                        "type": "string",
                        "description": "New text to replace with",
                    },
                },
                "required": ["path", "oldText", "newText"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch content from a URL and return text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to fetch",
                    },
                    "maxChars": {
                        "type": "number",
                        "description": "Max characters to return (default 50000)",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discord_send",
            "description": "Send a message to a Discord channel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "Discord channel ID",
                    },
                    "content": {
                        "type": "string",
                        "description": "Message content",
                    },
                },
                "required": ["channel_id", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discord_react",
            "description": "React to a Discord message with an emoji.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "Discord channel ID",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Message ID to react to",
                    },
                    "emoji": {
                        "type": "string",
                        "description": "Emoji to react with",
                    },
                },
                "required": ["channel_id", "message_id", "emoji"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "comb_stage",
            "description": "Stage information in COMB for the next session. Persists across restarts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Information to stage",
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "comb_recall",
            "description": "Recall operational memory from COMB — lossless session-to-session context.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search enterprise memory using HEKTOR (BM25 + vector hybrid search).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                    "k": {
                        "type": "number",
                        "description": "Number of results (default 5)",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["bm25", "vector", "hybrid"],
                        "description": "Search mode (default: hybrid)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nexus_audit",
            "description": "Run NEXUS self-optimization audit on Singularity's own codebase. Scans for code quality issues, complexity, and improvement opportunities.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Specific file or subdirectory to scan (relative to source root). Leave empty for full scan.",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["audit", "propose", "optimize", "report"],
                        "description": "Audit mode. 'audit' = scan only. 'propose' = scan + generate proposals. 'optimize' = scan + propose + auto-apply HIGH confidence. 'report' = full report. Default: audit",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nexus_status",
            "description": "Get current NEXUS engine status including active hot-swaps, run count, and journal entries.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nexus_swap",
            "description": "Hot-swap a specific function at runtime via NEXUS. Replaces a live function with new source code, with rollback capability.",
            "parameters": {
                "type": "object",
                "properties": {
                    "module_name": {
                        "type": "string",
                        "description": "Python module name (e.g. 'singularity.cortex.agent')",
                    },
                    "function_name": {
                        "type": "string",
                        "description": "Function name to replace",
                    },
                    "new_source": {
                        "type": "string",
                        "description": "New function source code",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for the swap",
                    },
                    "class_name": {
                        "type": "string",
                        "description": "Class name if swapping a method (optional)",
                    },
                },
                "required": ["module_name", "function_name", "new_source", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nexus_rollback",
            "description": "Rollback a NEXUS hot-swap. Pass a specific swap_id to rollback one swap, or 'all' to rollback everything.",
            "parameters": {
                "type": "object",
                "properties": {
                    "swap_id": {
                        "type": "string",
                        "description": "Swap ID to rollback, or 'all' for full rollback",
                    },
                },
                "required": ["swap_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nexus_evolve",
            "description": "Run NEXUS self-evolution cycle. Scans for safe mechanical code transformations (silent exceptions, bare excepts, etc.), validates them via AST, and applies them with hot-swap + disk persistence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Specific file or subdirectory to evolve (relative to source root). Leave empty for full scan.",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, find and validate but don't apply. Default: true (safe mode)",
                    },
                    "max_evolutions": {
                        "type": "number",
                        "description": "Maximum number of evolutions to apply. Default: 50",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "csuite_dispatch",
            "description": "Dispatch a task to C-Suite executives (CTO, COO, CFO, CISO). Routes through the native Coordinator — no webhooks, direct execution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Task description for the executive(s)",
                    },
                    "target": {
                        "type": "string",
                        "description": "Target: 'auto' (keyword-match), 'all' (fan-out), or specific role: cto, coo, cfo, ciso. Default: auto",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "critical"],
                        "description": "Task priority. Default: normal",
                    },
                    "max_iterations": {
                        "type": "number",
                        "description": "Max iterations for the executive agent loop. Default: 25",
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "poa_setup",
            "description": "Run the double-audit POA setup flow on a workspace. Phase 1: broad scan. Phase 2: review & tighten (classify products vs noise). Phase 3: focused audit (health checks on real products). Phase 4: present proposals for approval. Returns JSON report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {
                        "type": "string",
                        "description": "Workspace path to scan. Default: current workspace.",
                    },
                    "auto_approve": {
                        "type": "boolean",
                        "description": "Auto-approve all green POAs. Default: false (present for review).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "poa_manage",
            "description": "Manage POA lifecycle: list, status, audit, kill, pause, resume.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "status", "audit", "kill", "pause", "resume"],
                        "description": "POA management action.",
                    },
                    "product_id": {
                        "type": "string",
                        "description": "Product ID (required for audit/kill/pause/resume).",
                    },
                },
                "required": ["action"],
            },
        },
    },
    # ── ATLAS (Board Manager) ────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "atlas_status",
            "description": "Get ATLAS board manager status — module counts, health summary, last cycle info.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "atlas_topology",
            "description": "Get the enterprise topology map — all modules, machines, and connections. Hidden modules are excluded by default.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_hidden": {
                        "type": "boolean",
                        "description": "If true, include hidden/confidential modules in the output. Default: false.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "atlas_module",
            "description": "Get detailed report for a specific module in the ATLAS topology.",
            "parameters": {
                "type": "object",
                "properties": {
                    "module_id": {
                        "type": "string",
                        "description": "Module ID (e.g. 'singularity', 'mach6-gateway', 'cthulu-daemon', 'hektor-daemon')",
                    },
                },
                "required": ["module_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "atlas_report",
            "description": "Generate and return the full ATLAS board report — enterprise-wide status across all modules. Hidden modules are excluded by default.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_hidden": {
                        "type": "boolean",
                        "description": "If true, include hidden/confidential modules in the report. Default: false.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "atlas_visibility",
            "description": "Manage ATLAS module visibility. Hide confidential modules from reports and topology, or show them again. Actions: list (show all with visibility state), hide (hide a module), show (unhide a module).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action to perform: 'list', 'hide', or 'show'.",
                        "enum": ["list", "hide", "show"],
                    },
                    "module_id": {
                        "type": "string",
                        "description": "Module ID to hide or show (required for hide/show actions).",
                    },
                },
                "required": ["action"],
            },
        },
    },
]
