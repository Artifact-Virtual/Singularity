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
]
