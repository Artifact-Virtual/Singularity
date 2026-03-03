"""
SINEW — Sandboxed Executor
===============================

A ToolExecutor wrapper that intercepts all mutations and records
them in a Changeset instead of applying them to the filesystem.

Read operations (read, web_fetch) pass through normally.
Write operations (write, edit, exec) are captured as proposals.

Usage:
    manager = ChangesetManager(workspace="/path/to/workspace")
    cs = manager.new_changeset(agent_role="cto", task="Refactor auth module")
    
    executor = SandboxedExecutor(
        workspace="/path/to/workspace",
        changeset=cs,
        bus=event_bus,
    )
    
    # Agent runs normally — reads work, writes are captured
    result = await executor.execute("write", {"path": "/tmp/test.py", "content": "..."})
    # result = "📋 Proposed: WRITE /tmp/test.py (42 bytes) [changeset abc123]"
    
    # After agent finishes:
    print(cs.summary())  # Review the proposed changes
    
    # Apply with user approval:
    await manager.apply(cs.id)  # applies all
    await manager.apply(cs.id, approved_ids={"mut1", "mut3"})  # selective
    
    # Or reject:
    await manager.reject(cs.id)
    
    # Or rollback after apply:
    await manager.rollback(cs.id)
"""

from __future__ import annotations

import logging
from typing import Any

from .executor import ToolExecutor
from .changeset import Changeset, MutationType

logger = logging.getLogger("singularity.sinew.sandbox_exec")

# Tools that are read-only and can pass through without capture
PASSTHROUGH_TOOLS = {
    "read",
    "web_fetch",
    "memory_search",
    "comb_recall",
}

# Tools that mutate state and must be captured
MUTATION_TOOLS = {
    "write",
    "edit",
    "exec",
}


class SandboxedExecutor(ToolExecutor):
    """Tool executor that captures mutations in a changeset instead of applying them.
    
    Inherits from ToolExecutor so all tool methods are available.
    Overrides the mutation tools to capture instead of execute.
    Read-only tools pass through to the parent implementation.
    """
    
    def __init__(self, workspace: str, changeset: Changeset, 
                 bus: Any = None, allow_read_exec: bool = True,
                 exec_timeout: int = 30, max_output: int = 50_000):
        super().__init__(workspace, bus, exec_timeout, max_output)
        self.changeset = changeset
        self.allow_read_exec = allow_read_exec  # allow read-only exec cmds to pass through
    
    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute or capture a tool call.
        
        Read-only tools pass through. Mutation tools are captured.
        """
        if tool_name in PASSTHROUGH_TOOLS:
            return await super().execute(tool_name, arguments)
        
        if tool_name == "exec" and self.allow_read_exec:
            # Check if this is a read-only command
            command = arguments.get("command", "")
            if self._is_read_only_exec(command):
                return await super().execute(tool_name, arguments)
        
        # Capture mutation
        if tool_name in MUTATION_TOOLS:
            return await self._capture_mutation(tool_name, arguments)
        
        # Unknown tools — capture as exec for safety
        return await self._capture_mutation(tool_name, arguments)
    
    async def _capture_mutation(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Capture a mutation in the changeset instead of executing it."""
        
        if tool_name == "write":
            path = arguments.get("path", "")
            content = arguments.get("content", "")
            m = self.changeset.add_write(path, content)
            return f"📋 Proposed: {m.diff_summary()} [{m.risk.upper()} risk] → changeset {self.changeset.id}"
        
        elif tool_name == "edit":
            path = arguments.get("path", "")
            old_text = arguments.get("oldText", "")
            new_text = arguments.get("newText", "")
            m = self.changeset.add_edit(path, old_text, new_text)
            return f"📋 Proposed: {m.diff_summary()} [{m.risk.upper()} risk] → changeset {self.changeset.id}"
        
        elif tool_name == "exec":
            command = arguments.get("command", "")
            m = self.changeset.add_exec(command)
            return f"📋 Proposed: {m.diff_summary()} [{m.risk.upper()} risk] → changeset {self.changeset.id}"
        
        else:
            # Generic capture
            m = self.changeset.add_exec(
                f"[{tool_name}] {str(arguments)[:200]}",
                description=f"Unknown tool call: {tool_name}"
            )
            return f"📋 Proposed: {m.diff_summary()} [{m.risk.upper()} risk] → changeset {self.changeset.id}"
    
    def _is_read_only_exec(self, command: str) -> bool:
        """Determine if an exec command is read-only (safe to pass through)."""
        cmd = command.strip().lower()
        
        # Explicitly safe read-only commands
        safe_prefixes = [
            "ls", "cat ", "head ", "tail ", "grep ", "find ", "wc ",
            "du ", "df ", "stat ", "file ", "type ",
            "git log", "git status", "git diff", "git show", 
            "git branch", "git tag", "git remote",
            "echo ", "date", "uptime", "whoami", "pwd", "hostname",
            "env", "printenv", "which ", "whereis ",
            "python3 -c \"import", "python3 -c 'import",  # import checks
            "curl -s", "wget -q",  # read-only fetches
            "dig ", "nslookup ", "ping -c",
            "systemctl status", "journalctl",
            "ps ", "top -bn1", "free ", "vmstat",
        ]
        
        return any(cmd.startswith(p) for p in safe_prefixes)
