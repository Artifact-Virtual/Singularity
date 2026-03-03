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
        
        from .sandbox import validate_path
        violation = validate_path(path)
        if violation:
            return f"Blocked: {violation}"
        
        try:
            p = Path(path)
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
        
        from .sandbox import validate_path
        violation = validate_path(path)
        if violation:
            return f"Blocked: {violation}"
        
        try:
            p = Path(path)
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
        
        from .sandbox import validate_path
        violation = validate_path(path)
        if violation:
            return f"Blocked: {violation}"
        
        try:
            p = Path(path)
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
