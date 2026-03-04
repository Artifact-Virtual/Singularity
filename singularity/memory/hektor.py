"""
MEMORY — HEKTOR Search Engine
================================

BM25 keyword search over Singularity's workspace.
Lightweight, self-contained, no external daemon.

Indexes .core/ identity files + workspace text files.
Provides fast full-text search for the agent's memory.

Architecture:
    - BM25 in-process (no daemon, no socket)
    - Indexes on boot, re-indexes on demand
    - Priority boost for .core/ and memory files
    - Results include source path + content preview

No ONNX, no vectors — just BM25 keyword search.
Fast enough for an agent that needs to search before acting.
"""

from __future__ import annotations

import logging
import math
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

logger = logging.getLogger("singularity.memory.hektor")

# ── Index config ──────────────────────────────────────────────

TEXT_EXTENSIONS = {
    '.md', '.txt', '.py', '.json', '.yml', '.yaml', '.sh', '.js', '.ts',
    '.toml', '.cfg', '.ini', '.sql', '.csv', '.html', '.css',
}

SKIP_DIRS = {
    '.git', 'node_modules', '__pycache__', '.venv', 'venv',
    'dist', 'build', '.cache', '.npm', '.tmp', '.eggs',
    '.core-archive',  # archived agent states
}

SKIP_FILES = {
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
}

MAX_FILE_SIZE = 256 * 1024  # 256KB

# Priority boost multiplier for important files
PRIORITY_PATHS = {
    '.core/': 2.0,
    'memory/': 1.8,
    'SOUL.md': 2.0,
    'IDENTITY.md': 2.0,
    'AGENTS.md': 1.8,
    'TOOLS.md': 1.5,
    'USER.md': 1.5,
}


# ── BM25 Engine ──────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer, lowercased."""
    return re.findall(r'[a-z0-9_]+', text.lower())


class BM25Index:
    """Okapi BM25 index — in-process, no external dependencies."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: list[dict] = []       # [{path, content, tokens, priority}]
        self.doc_count = 0
        self.avgdl = 0.0
        self.df: dict[str, int] = defaultdict(int)  # document frequency
        self.tf: list[Counter] = []       # term frequency per doc

    def add(self, path: str, content: str, priority: float = 1.0) -> None:
        tokens = _tokenize(content)
        tf = Counter(tokens)
        doc_id = len(self.docs)

        self.docs.append({
            "path": path,
            "content": content[:2000],  # store preview only
            "token_count": len(tokens),
            "priority": priority,
        })
        self.tf.append(tf)

        for term in set(tokens):
            self.df[term] += 1

        self.doc_count += 1

    def finalize(self) -> None:
        """Compute average document length (call after all adds)."""
        if self.doc_count > 0:
            total = sum(d["token_count"] for d in self.docs)
            self.avgdl = total / self.doc_count

    def search(self, query: str, k: int = 5) -> list[dict]:
        """Search the index. Returns top-k results with scores."""
        query_tokens = _tokenize(query)
        if not query_tokens or self.doc_count == 0:
            return []

        scores = []
        for doc_id in range(self.doc_count):
            score = self._score_doc(doc_id, query_tokens)
            if score > 0:
                # Apply priority boost
                score *= self.docs[doc_id]["priority"]
                scores.append((doc_id, score))

        scores.sort(key=lambda x: -x[1])
        results = []
        for doc_id, score in scores[:k]:
            doc = self.docs[doc_id]
            # Extract relevant snippet
            snippet = self._extract_snippet(doc["content"], query_tokens)
            results.append({
                "path": doc["path"],
                "score": round(score, 4),
                "snippet": snippet,
            })
        return results

    def _score_doc(self, doc_id: int, query_tokens: list[str]) -> float:
        """BM25 score for a single document."""
        tf = self.tf[doc_id]
        dl = self.docs[doc_id]["token_count"]
        score = 0.0

        for term in query_tokens:
            if term not in self.df:
                continue
            n = self.df[term]
            idf = math.log((self.doc_count - n + 0.5) / (n + 0.5) + 1.0)
            term_tf = tf.get(term, 0)
            numerator = term_tf * (self.k1 + 1)
            denominator = term_tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            score += idf * numerator / denominator

        return score

    def _extract_snippet(self, content: str, query_tokens: list[str], window: int = 200) -> str:
        """Extract the most relevant snippet around query terms."""
        content_lower = content.lower()
        best_pos = 0
        best_count = 0

        # Find the position with the most query term hits in a window
        for i in range(0, len(content_lower), 50):
            chunk = content_lower[i:i + window]
            count = sum(1 for t in query_tokens if t in chunk)
            if count > best_count:
                best_count = count
                best_pos = i

        start = max(0, best_pos - 20)
        end = min(len(content), start + window)
        snippet = content[start:end].strip()

        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."

        return snippet


# ── HEKTOR Memory ────────────────────────────────────────────

class HektorMemory:
    """HEKTOR search engine for Singularity.

    Lightweight BM25 index over the agent's workspace.
    Indexes on boot, searchable immediately.
    """

    def __init__(self, workspace: str | Path, index_dir: str | Path | None = None,
                 bus: Any = None):
        self.workspace = Path(workspace)
        self.index_dir = Path(index_dir) if index_dir else self.workspace / ".core" / "memory" / "hektor"
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.bus = bus
        self._index = BM25Index()
        self._indexed = False
        self._file_count = 0

    def _should_index(self, path: Path) -> bool:
        if path.name in SKIP_FILES:
            return False
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            return False
        if any(skip in path.parts for skip in SKIP_DIRS):
            return False
        try:
            st = path.stat()
            if st.st_size > MAX_FILE_SIZE or st.st_size == 0:
                return False
        except OSError:
            return False
        return True

    def _get_priority(self, rel_path: str) -> float:
        """Get priority boost for a file path."""
        for pattern, boost in PRIORITY_PATHS.items():
            if pattern in rel_path:
                return boost
        return 1.0

    async def index(self, paths: list[str | Path] | None = None) -> int:
        """Index files. If paths not specified, indexes targeted directories.

        Default scope:
        - .core/ (agent identity, memory)
        - singularity/ (codebase)
        - memory/ (daily notes)
        - Key root files (SOUL.md, USER.md, AGENTS.md, etc.)

        Returns number of files indexed.
        """
        t0 = time.monotonic()
        self._index = BM25Index()

        if paths:
            scan_roots = [Path(p) for p in paths]
        else:
            # Targeted scope — fast enough for boot (~1-3s)
            sg_root = self.workspace / "singularity"
            scan_roots = [
                sg_root / ".core",                    # agent identity
                self.workspace / "memory",            # daily notes
                self.workspace / "executives",        # C-Suite workspace
            ]
            # Add key root files
            for fname in ["SOUL.md", "USER.md", "AGENTS.md", "TOOLS.md",
                          "IDENTITY.md", "HEARTBEAT.md", "WORKFLOW_AUTO.md"]:
                fpath = self.workspace / fname
                if fpath.exists():
                    scan_roots.append(fpath)

        count = 0
        for root in scan_roots:
            if root.is_file():
                files = [root]
            elif root.is_dir():
                files = []
                for dirpath, dirnames, filenames in os.walk(root):
                    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                    for fname in filenames:
                        fpath = Path(dirpath) / fname
                        if self._should_index(fpath):
                            files.append(fpath)
            else:
                continue

            for fpath in files:
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    rel = str(fpath.relative_to(self.workspace))
                    priority = self._get_priority(rel)
                    self._index.add(rel, content, priority)
                    count += 1
                except Exception as e:
                    logger.debug("Skip %s: %s", fpath, e)

        self._index.finalize()
        self._indexed = True
        self._file_count = count
        elapsed = time.monotonic() - t0

        logger.info("HEKTOR indexed %d files in %.1fs", count, elapsed)

        if self.bus:
            await self.bus.emit("memory.hektor.indexed", {
                "file_count": count,
                "elapsed_seconds": round(elapsed, 2),
                "term_count": len(self._index.df),
            }, source="memory.hektor")

        return count

    async def search(self, query: str, k: int = 5) -> list[dict]:
        """Search the index. Auto-indexes if not yet done."""
        if not self._indexed:
            await self.index()

        results = self._index.search(query, k=k)

        if self.bus:
            await self.bus.emit("memory.hektor.searched", {
                "query": query,
                "results": len(results),
            }, source="memory.hektor")

        return results

    @property
    def stats(self) -> dict:
        return {
            "indexed": self._indexed,
            "file_count": self._file_count,
            "term_count": len(self._index.df) if self._indexed else 0,
            "doc_count": self._index.doc_count,
        }
