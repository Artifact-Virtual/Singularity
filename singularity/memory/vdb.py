"""
MEMORY — Native Vector Database (VDB)
========================================

Purpose-built persistent memory for Singularity agents.
Zero external dependencies. Pure Python. File-backed.
"So light it doesn't even exist."

Architecture:
    BM25 keyword index + TF-IDF sparse vectors + cosine similarity
    Hybrid search (BM25 score * 0.4 + TF-IDF score * 0.6)
    JSONL storage — append-only, compact on demand
    Lazy load on first query, evicted after idle timeout (5 min)

What gets indexed:
    - Discord conversations (user <-> agent turns)
    - WhatsApp conversations
    - COMB staged memories
    - Identity files (.core/SOUL.md, IDENTITY.md, etc.)
    - Any text the agent wants to remember

What does NOT get indexed:
    - Tool calls/results (noise)
    - System prompts (already in context)
    - Binary/image content

Port of Symbiote's VDB (/opt/ava/mach6/src/memory/vdb.ts).
Same tokenizer, same scoring, same persistence format.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("singularity.memory.vdb")

# ── Types ────────────────────────────────────────────────────────────────


@dataclass
class VDBDocument:
    """A document to be indexed in the VDB."""
    id: str
    text: str
    source: str        # "whatsapp", "discord", "comb", "identity", "manual"
    role: str          # "user", "assistant", "context"
    timestamp: float   # epoch ms (or seconds — we normalize)
    session_id: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class StoredDocument(VDBDocument):
    """A document stored in the VDB with pre-computed index data."""
    terms: list = field(default_factory=list)    # pre-tokenized for BM25
    tfidf: dict = field(default_factory=dict)    # sparse TF-IDF: {term_idx: value}


@dataclass
class SearchResult:
    """A search result from the VDB."""
    id: str
    text: str
    source: str
    role: str
    timestamp: float
    score: float
    session_id: str = ""


@dataclass
class VDBStats:
    """Statistics about the VDB."""
    document_count: int
    term_count: int
    disk_bytes: int
    last_indexed: float
    sources: dict = field(default_factory=dict)


# ── Tokenizer (lightweight, no deps) ─────────────────────────────────────

STOP_WORDS = frozenset([
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'shall', 'can', 'to', 'of', 'in', 'for',
    'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through', 'during',
    'before', 'after', 'above', 'below', 'between', 'and', 'but', 'or',
    'not', 'no', 'nor', 'so', 'yet', 'both', 'either', 'neither', 'each',
    'every', 'all', 'any', 'few', 'more', 'most', 'other', 'some', 'such',
    'than', 'too', 'very', 'just', 'also', 'now', 'then', 'here', 'there',
    'when', 'where', 'why', 'how', 'what', 'which', 'who', 'whom', 'this',
    'that', 'these', 'those', 'it', 'its', 'i', 'me', 'my', 'we', 'our',
    'you', 'your', 'he', 'him', 'his', 'she', 'her', 'they', 'them', 'their',
    'if', 'up', 'out', 'about', 'over', 'down', 'only', 'own', 'same',
])


def tokenize(text: str) -> list[str]:
    """Tokenize text for indexing. Matches TypeScript VDB exactly."""
    import re
    cleaned = re.sub(r'[^a-z0-9\s\-_.@]', ' ', text.lower())
    return [t for t in cleaned.split() if len(t) > 1 and t not in STOP_WORDS]


def _make_doc_id(text: str, timestamp: float) -> str:
    """Generate a document ID from content hash."""
    raw = f"{timestamp}:{text[:200]}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _content_hash(text: str) -> str:
    """Content hash for deduplication."""
    return hashlib.md5(text.encode()).hexdigest()


# ── VDB Engine ───────────────────────────────────────────────────────────


class VectorDB:
    """Embedded vector database with BM25 + TF-IDF hybrid search.
    
    Zero external dependencies. Pure Python. File-backed JSONL.
    Lazy loads on first query, evicts after idle timeout.
    """

    def __init__(self, base_dir: str, idle_timeout_ms: int = 5 * 60 * 1000, bus: Any = None):
        self._dir = os.path.join(base_dir, '.vdb')
        self._docs_file = os.path.join(self._dir, 'documents.jsonl')
        self._index_file = os.path.join(self._dir, 'index.json')
        self._idle_timeout = idle_timeout_ms
        self._bus = bus

        # In-memory state (lazy-loaded)
        self._docs: dict[str, StoredDocument] | None = None
        self._bm25_postings: dict[str, dict[str, int]] | None = None  # term -> {docId -> tf}
        self._bm25_doc_lengths: dict[str, int] | None = None
        self._bm25_avg_dl: float = 0.0
        self._bm25_N: int = 0
        self._global_terms: dict[str, int] | None = None  # term -> index
        self._dirty: bool = False
        self._last_access: float = 0.0
        self._seen_hashes: set[str] = set()

        os.makedirs(self._dir, exist_ok=True)

    def index(self, doc: dict | VDBDocument) -> bool:
        """Index a document. Deduplicates by content hash.
        
        Accepts either a VDBDocument or a dict with keys:
        id, text, source, role, timestamp, session_id (optional), metadata (optional)
        """
        self._ensure_loaded()

        # Normalize input
        if isinstance(doc, dict):
            text = doc.get('text', '')
            timestamp = doc.get('timestamp', time.time() * 1000)
            doc_id = doc.get('id', '') or _make_doc_id(text, timestamp)
            source = doc.get('source', 'manual')
            role = doc.get('role', 'context')
            session_id = doc.get('session_id', doc.get('sessionId', ''))
            metadata = doc.get('metadata', {})
        else:
            text = doc.text
            timestamp = doc.timestamp
            doc_id = doc.id or _make_doc_id(text, timestamp)
            source = doc.source
            role = doc.role
            session_id = doc.session_id
            metadata = doc.metadata

        # Content-hash deduplication
        content_h = _content_hash(text)
        if content_h in self._seen_hashes:
            return False
        self._seen_hashes.add(content_h)

        # ID deduplication
        if doc_id in self._docs:
            return False

        # Tokenize
        terms = tokenize(text)
        if not terms:
            return False

        # Register new terms in global vocabulary
        for term in terms:
            if term not in self._global_terms:
                self._global_terms[term] = len(self._global_terms)

        # Compute term frequencies
        tf: dict[str, int] = {}
        for t in terms:
            tf[t] = tf.get(t, 0) + 1

        # Compute TF vector (sparse, keyed by global term index)
        tfidf: dict[int, float] = {}
        for term, count in tf.items():
            term_idx = self._global_terms[term]
            tfidf[term_idx] = count / len(terms)

        # Create stored document
        stored = StoredDocument(
            id=doc_id, text=text, source=source, role=role,
            timestamp=timestamp, session_id=session_id,
            metadata=metadata, terms=terms, tfidf=tfidf,
        )
        self._docs[doc_id] = stored

        # Update BM25 index
        self._bm25_N += 1
        self._bm25_doc_lengths[doc_id] = len(terms)
        for term, count in tf.items():
            if term not in self._bm25_postings:
                self._bm25_postings[term] = {}
            self._bm25_postings[term][doc_id] = count

        # Recalculate avgDl
        total_len = sum(self._bm25_doc_lengths.values())
        self._bm25_avg_dl = total_len / self._bm25_N if self._bm25_N > 0 else 0

        self._dirty = True
        self._last_access = time.time() * 1000
        self._append_doc(stored)
        return True

    def index_batch(self, docs: list[dict | VDBDocument]) -> int:
        """Batch index documents. Returns count of new documents added."""
        added = 0
        for doc in docs:
            if self.index(doc):
                added += 1
        if self._dirty:
            self._save_index()
        return added

    def search(
        self, query: str, k: int = 5,
        source: str | None = None, role: str | None = None,
        min_timestamp: float | None = None,
    ) -> list[SearchResult]:
        """Hybrid search: BM25 * 0.4 + TF-IDF cosine * 0.6, with recency boost."""
        self._ensure_loaded()
        self._last_access = time.time() * 1000

        query_terms = tokenize(query)
        if not query_terms:
            return []

        bm25_scores = self._bm25_search(query_terms)
        tfidf_scores = self._tfidf_search(query_terms)

        # Combine scores
        all_ids = set(bm25_scores.keys()) | set(tfidf_scores.keys())
        bm25_max = max(bm25_scores.values()) if bm25_scores else 1e-10
        tfidf_max = max(tfidf_scores.values()) if tfidf_scores else 1e-10
        if bm25_max < 1e-10:
            bm25_max = 1e-10
        if tfidf_max < 1e-10:
            tfidf_max = 1e-10

        combined: dict[str, float] = {}
        now_ms = time.time() * 1000

        for doc_id in all_ids:
            doc = self._docs.get(doc_id)
            if not doc:
                continue
            if source and doc.source != source:
                continue
            if role and doc.role != role:
                continue
            if min_timestamp and doc.timestamp < min_timestamp:
                continue

            score = (
                (bm25_scores.get(doc_id, 0) / bm25_max) * 0.4
                + (tfidf_scores.get(doc_id, 0) / tfidf_max) * 0.6
            )

            # Recency boost
            age_ms = now_ms - doc.timestamp
            if age_ms < 24 * 60 * 60 * 1000:
                score *= 1.10
            elif age_ms < 7 * 24 * 60 * 60 * 1000:
                score *= 1.05

            combined[doc_id] = score

        # Sort and return top-k
        sorted_results = sorted(combined.items(), key=lambda x: x[1], reverse=True)[:k]

        results = []
        for doc_id, score in sorted_results:
            doc = self._docs[doc_id]
            results.append(SearchResult(
                id=doc.id, text=doc.text, source=doc.source,
                role=doc.role, timestamp=doc.timestamp,
                score=score, session_id=doc.session_id,
            ))
        return results

    def stats(self) -> VDBStats:
        """Get VDB statistics."""
        self._ensure_loaded()

        sources: dict[str, int] = {}
        last_indexed = 0.0
        for doc in self._docs.values():
            sources[doc.source] = sources.get(doc.source, 0) + 1
            if doc.timestamp > last_indexed:
                last_indexed = doc.timestamp

        disk_bytes = 0
        try:
            if os.path.exists(self._docs_file):
                disk_bytes += os.path.getsize(self._docs_file)
            if os.path.exists(self._index_file):
                disk_bytes += os.path.getsize(self._index_file)
        except Exception as e:
            logger.debug(f"Suppressed: {e}")

        return VDBStats(
            document_count=len(self._docs),
            term_count=len(self._global_terms),
            disk_bytes=disk_bytes,
            last_indexed=last_indexed,
            sources=sources,
        )

    def evict(self) -> None:
        """Evict from memory. Data stays on disk."""
        if self._dirty:
            self._save_index()
        self._docs = None
        self._bm25_postings = None
        self._bm25_doc_lengths = None
        self._global_terms = None
        self._seen_hashes.clear()
        logger.debug("VDB evicted from memory")

    def check_idle(self) -> bool:
        """Check idle and evict if needed. Returns True if evicted."""
        if (
            self._docs is not None
            and self._last_access > 0
            and (time.time() * 1000 - self._last_access) > self._idle_timeout
        ):
            self.evict()
            return True
        return False

    def compact(self) -> int:
        """Compact JSONL — remove dupes, rewrite clean. Returns bytes saved."""
        self._ensure_loaded()

        before = 0
        try:
            if os.path.exists(self._docs_file):
                before = os.path.getsize(self._docs_file)
        except Exception as e:
            logger.debug(f"Suppressed: {e}")

        lines = []
        for doc in self._docs.values():
            lines.append(json.dumps(self._doc_to_dict(doc)))

        tmp = self._docs_file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        os.replace(tmp, self._docs_file)

        self._save_index()

        after = os.path.getsize(self._docs_file)
        saved = before - after
        logger.info(f"VDB compacted: {before} -> {after} bytes (saved {saved})")
        return saved

    # ── BM25 ─────────────────────────────────────────────────────────────

    def _bm25_search(self, query_terms: list[str], k1: float = 1.5, b: float = 0.75) -> dict[str, float]:
        """BM25 scoring for query terms."""
        scores: dict[str, float] = {}
        N = self._bm25_N
        avg_dl = self._bm25_avg_dl

        for term in query_terms:
            postings = self._bm25_postings.get(term)
            if not postings:
                continue
            df = len(postings)
            idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
            for doc_id, tf in postings.items():
                dl = self._bm25_doc_lengths.get(doc_id, 0)
                tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl)) if avg_dl > 0 else 0
                scores[doc_id] = scores.get(doc_id, 0) + idf * tf_norm

        return scores

    # ── TF-IDF Cosine ────────────────────────────────────────────────────

    def _tfidf_search(self, query_terms: list[str]) -> dict[str, float]:
        """TF-IDF cosine similarity search."""
        scores: dict[str, float] = {}

        # Build query TF
        query_tf: dict[str, int] = {}
        for t in query_terms:
            query_tf[t] = query_tf.get(t, 0) + 1

        # Build query vector
        query_vec: dict[int, float] = {}
        for term, count in query_tf.items():
            idx = self._global_terms.get(term)
            if idx is None:
                continue
            tf = count / len(query_terms)
            df = len(self._bm25_postings.get(term, {}))
            idf = math.log(self._bm25_N / df) if df > 0 else 0
            query_vec[idx] = tf * idf

        if not query_vec:
            return scores

        # Query magnitude
        query_mag = math.sqrt(sum(v * v for v in query_vec.values()))
        if query_mag == 0:
            return scores

        # Score each document
        for doc_id, doc in self._docs.items():
            dot = 0.0
            doc_mag = 0.0
            for term_idx, val in doc.tfidf.items():
                if val == 0:
                    continue
                doc_mag += val * val
                qv = query_vec.get(term_idx)
                if qv:
                    dot += val * qv
            doc_mag = math.sqrt(doc_mag)
            if doc_mag == 0 or dot == 0:
                continue
            scores[doc_id] = dot / (query_mag * doc_mag)

        return scores

    # ── Persistence ──────────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        """Lazy-load documents from disk into memory."""
        if self._docs is not None:
            return

        self._docs = {}
        self._global_terms = {}
        self._bm25_postings = {}
        self._bm25_doc_lengths = {}
        self._bm25_avg_dl = 0.0
        self._bm25_N = 0

        if os.path.exists(self._docs_file):
            with open(self._docs_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                        doc = self._dict_to_doc(raw)
                        self._docs[doc.id] = doc

                        # Content hash for dedup
                        self._seen_hashes.add(_content_hash(doc.text))

                        # Register terms
                        for term in doc.terms:
                            if term not in self._global_terms:
                                self._global_terms[term] = len(self._global_terms)

                        # BM25 index
                        self._bm25_N += 1
                        self._bm25_doc_lengths[doc.id] = len(doc.terms)
                        tf: dict[str, int] = {}
                        for t in doc.terms:
                            tf[t] = tf.get(t, 0) + 1
                        for term, count in tf.items():
                            if term not in self._bm25_postings:
                                self._bm25_postings[term] = {}
                            self._bm25_postings[term][doc.id] = count

                    except (json.JSONDecodeError, KeyError, TypeError):
                        continue  # skip corrupt lines

            if self._bm25_N > 0:
                total = sum(self._bm25_doc_lengths.values())
                self._bm25_avg_dl = total / self._bm25_N

        self._last_access = time.time() * 1000
        logger.info(f"VDB loaded: {self._bm25_N} docs, {len(self._global_terms)} terms")

    def _append_doc(self, doc: StoredDocument) -> None:
        """Append a document to the JSONL file."""
        line = json.dumps(self._doc_to_dict(doc))
        with open(self._docs_file, 'a', encoding='utf-8') as f:
            f.write(line + '\n')

    def _save_index(self) -> None:
        """Save index metadata."""
        meta = {
            'documentCount': len(self._docs) if self._docs else 0,
            'termCount': len(self._global_terms) if self._global_terms else 0,
            'lastSaved': time.time() * 1000,
        }
        with open(self._index_file, 'w', encoding='utf-8') as f:
            json.dump(meta, f)
        self._dirty = False

    @staticmethod
    def _doc_to_dict(doc: StoredDocument) -> dict:
        """Serialize a StoredDocument for JSONL persistence."""
        # Store tfidf as a dict of {str(term_idx): value} for JSON compat
        tfidf_serialized = {str(k): v for k, v in doc.tfidf.items() if v}
        d: dict[str, Any] = {
            'id': doc.id,
            'text': doc.text,
            'source': doc.source,
            'role': doc.role,
            'timestamp': doc.timestamp,
            'terms': doc.terms,
            'tfidf': tfidf_serialized,
        }
        if doc.session_id:
            d['sessionId'] = doc.session_id
        if doc.metadata:
            d['metadata'] = doc.metadata
        return d

    @staticmethod
    def _dict_to_doc(raw: dict) -> StoredDocument:
        """Deserialize a dict from JSONL into a StoredDocument."""
        # Parse tfidf — can be dict with string keys or sparse array
        raw_tfidf = raw.get('tfidf', {})
        if isinstance(raw_tfidf, dict):
            tfidf = {int(k): v for k, v in raw_tfidf.items() if v}
        elif isinstance(raw_tfidf, list):
            # Sparse array format (from TypeScript VDB)
            tfidf = {i: v for i, v in enumerate(raw_tfidf) if v}
        else:
            tfidf = {}

        return StoredDocument(
            id=raw['id'],
            text=raw['text'],
            source=raw.get('source', 'manual'),
            role=raw.get('role', 'context'),
            timestamp=raw.get('timestamp', 0),
            session_id=raw.get('sessionId', raw.get('session_id', '')),
            metadata=raw.get('metadata', {}),
            terms=raw.get('terms', []),
            tfidf=tfidf,
        )


# ── Session Ingester (for Singularity's SQLite sessions) ──────────────────


def extract_from_session_db(
    db_path: str,
    channel_id: str | None = None,
) -> list[dict]:
    """Extract indexable documents from Singularity's SQLite session store.
    
    Reads directly from the sessions DB. Filters out tool calls/results
    and very short messages (< 15 chars).
    """
    import sqlite3

    docs = []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        if channel_id:
            cursor.execute(
                """SELECT channel_id, role, content, created_at 
                   FROM messages 
                   WHERE channel_id = ? AND role IN ('user', 'assistant')
                   AND content IS NOT NULL AND LENGTH(content) > 15
                   AND tool_calls IS NULL AND tool_call_id IS NULL
                   ORDER BY id""",
                (channel_id,),
            )
        else:
            cursor.execute(
                """SELECT channel_id, role, content, created_at 
                   FROM messages 
                   WHERE role IN ('user', 'assistant')
                   AND content IS NOT NULL AND LENGTH(content) > 15
                   AND tool_calls IS NULL AND tool_call_id IS NULL
                   ORDER BY id"""
            )

        for row in cursor.fetchall():
            ch_id, role, content, created_at = row
            content = content.strip()
            if len(content) < 15:
                continue
            # Skip BLINK/system messages
            if 'BLINK APPROACHING' in content or 'BLINK COMPLETE' in content:
                continue
            # Truncate very long messages
            text = content[:2000] if len(content) > 2000 else content
            # Determine source from channel_id pattern
            source = 'discord'
            if 'whatsapp' in ch_id.lower():
                source = 'whatsapp'
            elif 'http' in ch_id.lower() or 'webchat' in ch_id.lower():
                source = 'webchat'

            timestamp_ms = created_at * 1000 if created_at < 1e12 else created_at

            docs.append({
                'id': _make_doc_id(text, timestamp_ms),
                'text': text,
                'source': source,
                'role': role,
                'timestamp': timestamp_ms,
                'session_id': ch_id,
            })

        conn.close()
    except Exception as e:
        logger.error(f"Failed to extract from session DB: {e}")

    return docs


def ingest_sessions(db: VectorDB, sessions_db_path: str) -> dict:
    """Ingest all sessions from Singularity's SQLite session store into VDB.
    
    Returns: {"processed": int, "indexed": int}
    """
    docs = extract_from_session_db(sessions_db_path)
    indexed = db.index_batch(docs)
    logger.info(f"Session ingestion: processed {len(docs)}, indexed {indexed}")
    return {"processed": len(docs), "indexed": indexed}


def ingest_identity_files(db: VectorDB, core_dir: str) -> int:
    """Index identity files from .core/ directory.
    
    Reads SOUL.md, IDENTITY.md, AGENTS.md, USER.md and indexes
    them as source="identity" documents.
    """
    identity_files = ['SOUL.md', 'IDENTITY.md', 'AGENTS.md', 'USER.md']
    indexed = 0
    now_ms = time.time() * 1000

    for fname in identity_files:
        fpath = os.path.join(core_dir, fname)
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                text = f.read()
            if not text.strip():
                continue

            # Split large files into chunks of ~1500 chars for better search granularity
            chunks = _chunk_text(text, max_chunk=1500)
            for i, chunk in enumerate(chunks):
                doc = {
                    'id': _make_doc_id(chunk, now_ms + i),
                    'text': chunk,
                    'source': 'identity',
                    'role': 'context',
                    'timestamp': now_ms + i,
                    'metadata': {'file': fname, 'chunk': str(i)},
                }
                if db.index(doc):
                    indexed += 1
        except Exception as e:
            logger.error(f"Failed to index identity file {fname}: {e}")

    if indexed > 0:
        db._save_index()
        logger.info(f"Identity ingestion: indexed {indexed} chunks from {len(identity_files)} files")
    return indexed


def ingest_memory_files(db: VectorDB, memory_dir: str) -> int:
    """Index memory files (daily notes, long-term memory).
    
    Reads markdown files from the memory directory and indexes them.
    """
    indexed = 0
    now_ms = time.time() * 1000

    if not os.path.isdir(memory_dir):
        return 0

    for fname in os.listdir(memory_dir):
        if not fname.endswith('.md'):
            continue
        fpath = os.path.join(memory_dir, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                text = f.read()
            if not text.strip() or len(text) < 20:
                continue

            chunks = _chunk_text(text, max_chunk=1500)
            for i, chunk in enumerate(chunks):
                doc = {
                    'id': _make_doc_id(chunk, now_ms + i),
                    'text': chunk,
                    'source': 'memory',
                    'role': 'context',
                    'timestamp': now_ms + i,
                    'metadata': {'file': fname, 'chunk': str(i)},
                }
                if db.index(doc):
                    indexed += 1
        except Exception as e:
            logger.error(f"Failed to index memory file {fname}: {e}")

    if indexed > 0:
        db._save_index()
    return indexed


def _chunk_text(text: str, max_chunk: int = 1500) -> list[str]:
    """Split text into chunks at paragraph boundaries."""
    if len(text) <= max_chunk:
        return [text]

    chunks = []
    paragraphs = text.split('\n\n')
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 > max_chunk and current:
            chunks.append(current.strip())
            current = para
        else:
            current = current + '\n\n' + para if current else para

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text[:max_chunk]]
