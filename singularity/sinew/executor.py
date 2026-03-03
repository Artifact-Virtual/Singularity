"""
SINEW — Tool Executor
========================

Native tool execution engine for Singularity.

Handles: exec (shell commands), read (files), write (files),
         web_fetch, discord_send, discord_react, comb_stage, comb_recall,
         memory_search, and extensible custom tools.

Safety:
    - Path validation (no escaping workspace)
    - Command filtering (no destructive ops without explicit allow)
    - Timeout enforcement (no runaway processes)
    - Output capping (no memory bombs)
    - All executions logged to event bus

Design:
    Plug's tool executor was 582 lines with everything mixed together.
    Singularity separates concerns:
        - executor.py: the execution engine (this file)
        - sandbox.py: safety validation
        - definitions.py: tool schemas for LLM
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("singularity.sinew.executor")


class ToolExecutor:
    """Execute tools with safety, timeouts, and event bus integration.
    
    Each tool is a method: _tool_{name}(arguments) -> str
    Adding a new tool = adding a new method + schema in definitions.py
    """
    
    def __init__(self, workspace: str, bus: Any = None, 
                 exec_timeout: int = 30, max_output: int = 50_000):
        self.workspace = Path(workspace)
        self.bus = bus
        self.exec_timeout = exec_timeout
        self.max_output = max_output
        self._background_procs: dict[str, asyncio.subprocess.Process] = {}
        self._discord_adapter: Any = None  # Set by runtime after boot
        self._current_sender_id: str | None = None  # For @mention enforcement
    
    def set_discord_adapter(self, adapter: Any) -> None:
        """Wire the Discord adapter for discord_send/react tools."""
        self._discord_adapter = adapter
    
    def set_current_sender(self, sender_id: str | None) -> None:
        """Set the current message sender for @mention enforcement."""
        self._current_sender_id = sender_id
    
    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool by name. Returns the result as a string."""
        method_name = f"_tool_{tool_name}"
        method = getattr(self, method_name, None)
        
        if method is None:
            error = f"Unknown tool: {tool_name}"
            logger.warning(error)
            return error
        
        t0 = time.perf_counter()
        try:
            result = await method(arguments)
            latency = time.perf_counter() - t0
            
            # Cap output
            if len(result) > self.max_output:
                result = result[:self.max_output] + f"\n\n[Output truncated at {self.max_output} chars]"
            
            if self.bus:
                await self.bus.emit_nowait("sinew.tool.executed", {
                    "tool": tool_name,
                    "latency_ms": round(latency * 1000),
                    "output_chars": len(result),
                    "success": True,
                }, source="sinew")
            
            return result
            
        except Exception as e:
            latency = time.perf_counter() - t0
            error = f"Tool error ({tool_name}): {type(e).__name__}: {e}"
            logger.error(error, exc_info=True)
            
            if self.bus:
                await self.bus.emit_nowait("sinew.tool.failed", {
                    "tool": tool_name,
                    "error": str(e),
                    "latency_ms": round(latency * 1000),
                }, source="sinew")
            
            return error
    
    async def close(self) -> None:
        """Clean up background processes."""
        for pid, proc in self._background_procs.items():
            try:
                proc.terminate()
            except Exception:
                pass
        self._background_procs.clear()
    
    # ── Tool implementations ─────────────────────────────────────────
    
    async def _tool_exec(self, args: dict) -> str:
        """Execute a shell command."""
        command = args.get("command", "")
        timeout = args.get("timeout", self.exec_timeout)
        workdir = args.get("workdir", str(self.workspace))
        background = args.get("background", False)
        
        if not command:
            return "Error: no command provided"
        
        # Sandbox check
        from .sandbox import validate_command
        violation = validate_command(command)
        if violation:
            return f"Blocked: {violation}"
        
        if background:
            return await self._exec_background(command, workdir)
        
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=workdir,
                env={**os.environ, "TERM": "dumb"},
            )
            
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                return f"Error: Command timed out after {timeout}s"
            
            output = stdout.decode("utf-8", errors="replace")
            
            if proc.returncode != 0:
                output += f"\n\nExit code: {proc.returncode}"
            
            return output or "(no output)"
            
        except Exception as e:
            return f"Exec error: {e}"
    
    async def _exec_background(self, command: str, workdir: str) -> str:
        """Run a command in the background."""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=workdir,
            )
            pid = str(proc.pid)
            self._background_procs[pid] = proc
            return f"Background process started: PID {pid}"
        except Exception as e:
            return f"Background exec error: {e}"
    
    async def _tool_read(self, args: dict) -> str:
        """Read a file."""
        path = args.get("path", "")
        offset = args.get("offset", 0)
        limit = args.get("limit", 0)
        
        if not path:
            return "Error: no path provided"
        
        # Resolve relative paths against workspace (not cwd)
        p = Path(path)
        if not p.is_absolute():
            p = self.workspace / p
        
        from .sandbox import validate_path
        violation = validate_path(str(p))
        if violation:
            return f"Blocked: {violation}"
        
        try:
            if not p.exists():
                return f"File not found: {path}"
            if not p.is_file():
                return f"Not a file: {path}"
            
            text = p.read_text(encoding="utf-8", errors="replace")
            lines = text.split("\n")
            
            if offset > 0:
                lines = lines[offset - 1:]  # 1-indexed
            if limit > 0:
                lines = lines[:limit]
            
            return "\n".join(lines)
            
        except Exception as e:
            return f"Read error: {e}"
    
    async def _tool_write(self, args: dict) -> str:
        """Write content to a file."""
        path = args.get("path", "")
        content = args.get("content", "")
        
        if not path:
            return "Error: no path provided"
        
        # Resolve relative paths against workspace
        p = Path(path)
        if not p.is_absolute():
            p = self.workspace / p
        
        from .sandbox import validate_path
        violation = validate_path(str(p))
        if violation:
            return f"Blocked: {violation}"
        
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Write error: {e}"
    
    async def _tool_edit(self, args: dict) -> str:
        """Edit a file by replacing exact text."""
        path = args.get("path", "")
        old_text = args.get("oldText", "")
        new_text = args.get("newText", "")
        
        if not path or not old_text:
            return "Error: path and oldText required"
        
        # Resolve relative paths against workspace
        p = Path(path)
        if not p.is_absolute():
            p = self.workspace / p
        
        from .sandbox import validate_path
        violation = validate_path(str(p))
        if violation:
            return f"Blocked: {violation}"
        
        try:
            if not p.exists():
                return f"File not found: {path}"
            
            content = p.read_text(encoding="utf-8")
            if old_text not in content:
                return f"oldText not found in {path}"
            
            count = content.count(old_text)
            new_content = content.replace(old_text, new_text, 1)
            p.write_text(new_content, encoding="utf-8")
            
            old_lines = old_text.count("\n") + 1
            new_lines = new_text.count("\n") + 1
            return f"Edited {path}: replaced {old_lines} line(s) with {new_lines} line(s)"
            
        except Exception as e:
            return f"Edit error: {e}"
    
    async def _tool_web_fetch(self, args: dict) -> str:
        """Fetch content from a URL."""
        url = args.get("url", "")
        max_chars = args.get("maxChars", 50_000)
        
        if not url:
            return "Error: no URL provided"
        
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    text = await resp.text()
                    
                    # Strip HTML if content type suggests it
                    ct = resp.headers.get("content-type", "")
                    if "html" in ct.lower():
                        try:
                            from html.parser import HTMLParser
                            import re
                            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
                            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
                            text = re.sub(r'<[^>]+>', ' ', text)
                            text = re.sub(r'\s+', ' ', text).strip()
                        except Exception:
                            pass
                    
                    if len(text) > max_chars:
                        text = text[:max_chars] + f"\n\n[Truncated at {max_chars} chars]"
                    
                    return f"HTTP {resp.status}\n\n{text}"
                    
        except Exception as e:
            return f"Fetch error: {e}"
    
    # ── Discord tools ────────────────────────────────────────────
    
    async def _tool_discord_send(self, args: dict) -> str:
        """Send a message to a Discord channel."""
        channel_id = args.get("channel_id", "")
        content = args.get("content", "")
        
        if not channel_id or not content:
            return "Error: channel_id and content required"
        
        # ── ANTI-LOOP SYSTEM: Check for mention suppression ──
        should_suppress = self._should_suppress_mentions(content)
        if should_suppress:
            # Strip all @mentions to prevent response loops
            content = self._strip_mentions(content)
            # Replace @end with empty string
            content = content.replace("@end", "").strip()
            if not content:
                content = "(message sent without mention to prevent loop)"
        else:
            # Normal @mention enforcement — if sender is known and not already mentioned, prepend
            if self._current_sender_id and f"<@{self._current_sender_id}>" not in content and f"<@!{self._current_sender_id}>" not in content:
                # Only auto-prepend if no OTHER @mention is present (LLM may be addressing someone specific)
                import re
                if not re.search(r'<@!?\d+>', content):
                    content = f"<@{self._current_sender_id}> {content}"
        
        # Use the adapter reference if wired
        if self._discord_adapter:
            from ..nerve.types import OutboundMessage
            try:
                result = await self._discord_adapter.send(
                    channel_id, OutboundMessage(content=content)
                )
                if result.success:
                    return f"Sent to {channel_id} (msg_id: {result.message_id})"
                return f"Send failed: {result.error}"
            except Exception as e:
                return f"Discord send error: {e}"
        
        return "Error: Discord adapter not available"
    
    def _should_suppress_mentions(self, content: str) -> bool:
        """Check if we should suppress @mentions to prevent loops."""
        # Look for explicit suppression signals
        if "@end" in content.lower():
            return True
        # If content suggests loop prevention, suppress mentions
        if any(phrase in content.lower() for phrase in [
            "don't respond", "no mention", "suppress mention", "prevent loop",
            "without mention", "loop prevention", "echo prevention"
        ]):
            return True
        return False
    
    def _strip_mentions(self, content: str) -> str:
        """Remove @mentions from content."""
        import re
        # Remove Discord mentions: <@123456789> and <@!123456789>
        content = re.sub(r'<@!?\d+>', '', content)
        # Remove @username patterns
        content = re.sub(r'@\w+', '', content)
        return content.strip()
    
    async def _tool_discord_react(self, args: dict) -> str:
        """React to a Discord message with an emoji."""
        channel_id = args.get("channel_id", "")
        message_id = args.get("message_id", "")
        emoji = args.get("emoji", "")
        
        if not channel_id or not message_id or not emoji:
            return "Error: channel_id, message_id, and emoji required"
        
        if self._discord_adapter:
            try:
                await self._discord_adapter.react(channel_id, message_id, emoji)
                return f"Reacted with {emoji} on {message_id}"
            except Exception as e:
                return f"Discord react error: {e}"
        
        return "Error: Discord adapter not available"
    
    # ── COMB tools ───────────────────────────────────────────────
    
    async def _tool_comb_stage(self, args: dict) -> str:
        """Stage information in COMB for persistence."""
        content = args.get("content", "")
        if not content:
            return "Error: content required"
        
        try:
            # Primary: use the enterprise flush.py (battle-tested)
            flush_script = self.workspace / ".ava-memory" / "flush.py"
            if flush_script.exists():
                proc = await asyncio.create_subprocess_exec(
                    "python3", str(flush_script), "stage", content,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=str(self.workspace),
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
                output = stdout.decode("utf-8", errors="replace").strip()
                return output or f"Staged {len(content)} chars"
            
            # Fallback: native CombMemory
            from ..memory.comb import CombMemory
            comb_path = self.workspace / ".singularity" / "comb"
            comb = CombMemory(store_path=str(comb_path))
            await comb.initialize()
            success = await comb.stage(content)
            return f"Staged {len(content)} chars to COMB" if success else "COMB stage failed"
        except Exception as e:
            return f"COMB stage error: {e}"
    
    async def _tool_comb_recall(self, args: dict) -> str:
        """Recall operational memory from COMB."""
        try:
            # Primary: use the enterprise flush.py (battle-tested)
            flush_script = self.workspace / ".ava-memory" / "flush.py"
            if flush_script.exists():
                proc = await asyncio.create_subprocess_exec(
                    "python3", str(flush_script), "recall",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=str(self.workspace),
                    env={**os.environ, "PATH": os.environ.get("PATH", "")},
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
                output = stdout.decode("utf-8", errors="replace").strip()
                return output or "(no COMB data)"
            
            # Fallback: native CombMemory
            from ..memory.comb import CombMemory
            comb_path = self.workspace / ".singularity" / "comb"
            comb = CombMemory(store_path=str(comb_path))
            await comb.initialize()
            result = await comb.recall()
            return result or "(no COMB data)"
        except Exception as e:
            return f"COMB recall error: {e}"
    
    # ── Memory search ────────────────────────────────────────────
    
    async def _tool_memory_search(self, args: dict) -> str:
        """Search enterprise memory using HEKTOR."""
        query = args.get("query", "")
        k = args.get("k", 5)
        mode = args.get("mode", "hybrid")
        
        if not query:
            return "Error: query required"
        
        try:
            search_script = self.workspace / ".ava-memory" / "ava_memory_fast.py"
            if not search_script.exists():
                return "Error: HEKTOR memory system not found"
            
            cmd = [
                "python3", str(search_script), "search", query,
                "--mode", mode, "-k", str(int(k))
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(self.workspace),
                env={**os.environ, "PATH": os.environ.get("PATH", "")},
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode("utf-8", errors="replace").strip()
            return output or "(no results)"
        except Exception as e:
            return f"Memory search error: {e}"
