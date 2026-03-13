"""MEMORY — Memory subsystem.

Components:
    - VDB: Native embedded vector database (BM25 + TF-IDF hybrid search)
    - COMB: Cross-session memory persistence (stage/recall)
    - Sessions: SQLite conversation storage
    - HEKTOR: BM25 search over workspace files (kept but not booted by default — VDB handles it)
"""

from .vdb import VectorDB, VDBDocument, StoredDocument, SearchResult, VDBStats
from .vdb import extract_from_session_db, ingest_sessions, ingest_identity_files, ingest_memory_files

__all__ = [
    "VectorDB",
    "VDBDocument",
    "StoredDocument",
    "SearchResult",
    "VDBStats",
    "extract_from_session_db",
    "ingest_sessions",
    "ingest_identity_files",
    "ingest_memory_files",
]
