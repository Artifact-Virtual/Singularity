"""
MEMORY — COMB Native Memory
==============================

COMB isn't a library call bolted onto Singularity.
COMB is her bloodstream. Every interaction persists.
Every context window has history. She remembers.

Architecture:
    CombMemory — wrapper around comb-db (PyPI: comb-db)
        - stage(content) → store for next session + feed into VDB
        - recall() → retrieve staged content + feed into VDB
    
    This integrates with the event bus:
        - memory.comb.staged → when something is staged
        - memory.comb.recalled → at boot when recall completes

Design:
    COMB is a thin stage/recall layer feeding INTO the VDB.
    VDB handles all search. COMB handles persistence across sessions.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("singularity.memory.comb")


class CombMemory:
    """Native COMB integration for persistent cross-session memory.
    
    Wraps comb-db library for:
    - Stage/recall (lossless session-to-session carryforward)
    - Feeds staged/recalled content into VDB for searchability
    """
    
    def __init__(self, store_path: str | Path, bus: Any = None, vdb: Any = None):
        self.store_path = Path(store_path)
        self.store_path.mkdir(parents=True, exist_ok=True)
        self.bus = bus
        self._vdb = vdb
        self._comb = None
        self._initialized = False
    
    def set_vdb(self, vdb: Any) -> None:
        """Wire the VDB instance for indexing staged/recalled content."""
        self._vdb = vdb
    
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
        Also feeds content into VDB for searchability.
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
            
            # Feed into VDB for searchability
            self._index_in_vdb(content, "comb-stage")
            
            if self.bus:
                await self.bus.emit("memory.comb.staged", {
                    "chars": len(content),
                    "preview": content[:100],
                }, source="memory.comb")
            
            return True
            
        except Exception as e:
            logger.error("COMB stage failed: %s", e)
            return False
    
    def _index_in_vdb(self, text: str, tag: str = "comb") -> None:
        """Index content into VDB if available."""
        if not self._vdb:
            return
        try:
            import hashlib
            now_ms = time.time() * 1000
            doc_id = hashlib.md5(f"{now_ms}:{text[:200]}".encode()).hexdigest()[:12]
            self._vdb.index({
                'id': doc_id,
                'text': text[:2000],  # Cap for VDB
                'source': 'comb',
                'role': 'context',
                'timestamp': now_ms,
                'metadata': {'tag': tag},
            })
        except Exception as e:
            logger.debug(f"VDB indexing from COMB failed (non-fatal): {e}")
    
    async def recall(self) -> str:
        """Recall staged content from previous session.
        
        This is what makes Singularity wake up knowing who she is.
        Also feeds recalled content into VDB for searchability.
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
                # Feed recalled content into VDB
                self._index_in_vdb(content, "comb-recall")
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
        """Search using VDB (replaces HEKTOR for conversational memory).
        
        Returns list of {text, score, source, role} dicts.
        """
        if self._vdb:
            try:
                results = self._vdb.search(query, k=k)
                return [
                    {
                        "content": r.text,
                        "text": r.text,
                        "score": r.score,
                        "source": r.source,
                        "role": r.role,
                    }
                    for r in results
                ]
            except Exception as e:
                logger.error(f"VDB search failed: {e}")
        
        # Fallback to comb-db native search if available
        results = []
        try:
            if self._comb and hasattr(self._comb, 'search'):
                raw = self._comb.search(query, k=k, mode=mode)
                results = raw if isinstance(raw, list) else []
        except Exception as e:
            logger.error("COMB search failed: %s", e)
        
        if self.bus:
            await self.bus.emit("memory.comb.searched", {
                "query": query,
                "results": len(results),
                "mode": mode,
            }, source="memory.comb")
        
        return results
