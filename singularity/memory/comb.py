"""
MEMORY — COMB Native Memory
==============================

COMB isn't a library call bolted onto Singularity.
COMB is her bloodstream. Every interaction persists.
Every context window has history. She remembers.

Architecture:
    CombMemory — wrapper around comb-db (PyPI: comb-db)
        - stage(content) → store for next session
        - recall() → retrieve staged content
        - search(query) → semantic/BM25 hybrid search
    
    This integrates with the event bus:
        - memory.comb.staged → when something is staged
        - memory.comb.recalled → at boot when recall completes
        - memory.comb.searched → when a search query runs

Design:
    The previous runtime (Plug) had a standalone flush.py script for memory.
    Singularity has COMB as a native subsystem — imported, initialized,
    and wired into the event bus at boot. No shell-outs. No subprocess.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("singularity.memory.comb")


class CombMemory:
    """Native COMB integration for persistent cross-session memory.
    
    Wraps comb-db library for:
    - Stage/recall (lossless session-to-session carryforward)
    - Search (if HEKTOR is available)
    - Direct store operations
    """
    
    def __init__(self, store_path: str | Path, bus: Any = None):
        self.store_path = Path(store_path)
        self.store_path.mkdir(parents=True, exist_ok=True)
        self.bus = bus
        self._comb = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize COMB store. Must be called before use."""
        try:
            from comb import CombStore
            self._comb = CombStore(str(self.store_path))
            self._initialized = True
            logger.info("COMB memory initialized at %s", self.store_path)
        except ImportError:
            # Fallback: file-based staging without comb-db
            logger.warning("comb-db not installed, using file-based fallback")
            self._initialized = True
        
        if self.bus:
            await self.bus.emit("memory.comb.initialized", {
                "store_path": str(self.store_path),
                "native": self._comb is not None,
            }, source="memory.comb")
    
    async def stage(self, content: str) -> bool:
        """Stage content for next session recall.
        
        This is the core of memory persistence.
        What you stage survives restarts.
        """
        if not self._initialized:
            logger.error("COMB not initialized — call initialize() first")
            return False
        
        try:
            if self._comb:
                self._comb.stage(content)
            else:
                # File-based fallback
                stage_file = self.store_path / "staged.jsonl"
                entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "content": content,
                }
                with open(stage_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
            
            logger.info("Staged %d chars into COMB", len(content))
            
            # Trigger HEKTOR vectorization so staged content becomes searchable
            self._trigger_hektor_ingest(content)
            
            if self.bus:
                await self.bus.emit("memory.comb.staged", {
                    "chars": len(content),
                    "preview": content[:100],
                }, source="memory.comb")
            
            return True
            
        except Exception as e:
            logger.error("COMB stage failed: %s", e)
            return False
    
    def _trigger_hektor_ingest(self, staged_text: str):
        """Queue staged content for HEKTOR vectorization.
        
        Writes to comb-pending.jsonl and signals the HEKTOR daemon
        to process it. The content becomes BM25 + vector searchable.
        """
        import socket as sock_mod
        
        # Find the workspace root (parent of store_path's parent)
        workspace = self.store_path.parent
        # Walk up until we find a workspace-like directory
        for candidate in [workspace, workspace.parent, workspace.parent.parent]:
            if (candidate / ".ava-memory").exists():
                workspace = candidate
                break
        
        pending_path = workspace / ".ava-memory" / "comb-pending.jsonl"
        
        try:
            entry = {
                "text": staged_text,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "singularity-comb-stage",
            }
            
            with open(pending_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
            
            logger.info("Queued for HEKTOR vectorization (%d chars)", len(staged_text))
            
            # Signal daemon to process queue
            sock_path = workspace / ".ava-memory" / "ava_daemon.sock"
            if sock_path.exists():
                try:
                    s = sock_mod.socket(sock_mod.AF_UNIX, sock_mod.SOCK_STREAM)
                    s.settimeout(2)
                    s.connect(str(sock_path))
                    s.sendall(b'{"cmd": "reload"}\n')
                    s.close()
                except Exception:
                    pass  # Daemon not running — entries stay queued
                    
        except Exception as e:
            logger.warning("HEKTOR queue failed (non-fatal): %s", e)
    
    async def recall(self) -> str:
        """Recall staged content from previous session.
        
        This is what makes Singularity wake up knowing who she is.
        """
        if not self._initialized:
            logger.error("COMB not initialized")
            return ""
        
        try:
            content = ""
            if self._comb:
                content = self._comb.recall()
            else:
                # File-based fallback
                stage_file = self.store_path / "staged.jsonl"
                if stage_file.exists():
                    lines = stage_file.read_text(encoding="utf-8").strip().split("\n")
                    entries = [json.loads(line) for line in lines if line.strip()]
                    content = "\n".join(e["content"] for e in entries)
            
            if content:
                logger.info("COMB recall: %d chars", len(content))
            else:
                logger.info("COMB recall: empty (first boot or no staged content)")
            
            if self.bus:
                await self.bus.emit("memory.comb.recalled", {
                    "chars": len(content),
                    "has_content": bool(content),
                }, source="memory.comb")
            
            return content
            
        except Exception as e:
            logger.error("COMB recall failed: %s", e)
            return ""
    
    async def search(self, query: str, k: int = 5, mode: str = "hybrid") -> list[dict]:
        """Search COMB/HEKTOR for relevant memories.
        
        Returns list of {content, score, source} dicts.
        """
        # This delegates to HEKTOR if available
        results = []
        try:
            if self._comb and hasattr(self._comb, 'search'):
                raw = self._comb.search(query, k=k, mode=mode)
                results = raw if isinstance(raw, list) else []
            else:
                logger.debug("COMB search not available (no native comb-db or search method)")
        except Exception as e:
            logger.error("COMB search failed: %s", e)
        
        if self.bus:
            await self.bus.emit("memory.comb.searched", {
                "query": query,
                "results": len(results),
                "mode": mode,
            }, source="memory.comb")
        
        return results
