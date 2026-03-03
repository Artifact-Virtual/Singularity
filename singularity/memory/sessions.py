"""
MEMORY — Session Store
========================

Asyncio-native session storage for conversation history.

Architecture:
    SQLite + WAL mode for concurrent reads.
    Each channel gets its own session (keyed by channel_id).
    Messages stored as JSON with token counts for compaction.

This replaces Plug's sessions/store.py with event bus integration
and better error recovery (Plug's store could corrupt on crash).
"""

from __future__ import annotations

import aiosqlite
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("singularity.memory.sessions")


@dataclass
class Message:
    """A conversation message (unified format across all subsystems)."""
    role: str                   # system, user, assistant, tool
    content: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None     # tool name (for tool results)
    
    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d
    
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Message:
        return cls(
            role=d["role"],
            content=d.get("content"),
            tool_calls=d.get("tool_calls"),
            tool_call_id=d.get("tool_call_id"),
            name=d.get("name"),
        )
    
    def __repr__(self) -> str:
        content_preview = (self.content or "")[:60]
        tc = f", {len(self.tool_calls)} tool_calls" if self.tool_calls else ""
        return f"Message(role={self.role}, content='{content_preview}'{tc})"


class SessionStore:
    """Async SQLite session store with WAL mode.
    
    Stores conversation messages per channel with:
    - Token counting for compaction
    - Atomic operations (no partial writes)
    - WAL mode for concurrent read access
    - Automatic schema migration
    """
    
    def __init__(self, db_path: str | Path, bus: Any = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.bus = bus
        self._db: aiosqlite.Connection | None = None
    
    async def open(self) -> None:
        """Open the database connection."""
        self._db = await aiosqlite.connect(str(self.db_path))
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        
        # Create tables
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                tool_calls TEXT,
                tool_call_id TEXT,
                name TEXT,
                token_count INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            )
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_channel 
            ON messages(channel_id, id)
        """)
        
        # Session metadata
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                channel_id TEXT PRIMARY KEY,
                total_tokens INTEGER DEFAULT 0,
                message_count INTEGER DEFAULT 0,
                last_active REAL,
                created_at REAL
            )
        """)
        
        await self._db.commit()
        logger.info("SessionStore opened: %s", self.db_path)
    
    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("SessionStore closed")
    
    async def add_message(self, channel_id: str, message: Message, 
                          token_count: int = 0) -> int:
        """Store a message in a session. Returns the message ID."""
        if not self._db:
            raise RuntimeError("SessionStore not opened")
        
        now = time.time()
        
        cursor = await self._db.execute(
            """INSERT INTO messages 
               (channel_id, role, content, tool_calls, tool_call_id, name, token_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                channel_id,
                message.role,
                message.content,
                json.dumps(message.tool_calls) if message.tool_calls else None,
                message.tool_call_id,
                message.name,
                token_count,
                now,
            ),
        )
        
        # Update session metadata (upsert)
        await self._db.execute(
            """INSERT INTO sessions (channel_id, total_tokens, message_count, last_active, created_at)
               VALUES (?, ?, 1, ?, ?)
               ON CONFLICT(channel_id) DO UPDATE SET
                   total_tokens = total_tokens + ?,
                   message_count = message_count + 1,
                   last_active = ?""",
            (channel_id, token_count, now, now, token_count, now),
        )
        
        await self._db.commit()
        msg_id = cursor.lastrowid
        
        if self.bus:
            await self.bus.emit_nowait("memory.session.message_added", {
                "channel_id": channel_id,
                "role": message.role,
                "tokens": token_count,
                "msg_id": msg_id,
            }, source="memory.sessions")
        
        return msg_id
    
    async def get_messages(self, channel_id: str, limit: int = 0) -> list[Message]:
        """Retrieve all messages for a session."""
        if not self._db:
            raise RuntimeError("SessionStore not opened")
        
        query = """SELECT role, content, tool_calls, tool_call_id, name 
                   FROM messages WHERE channel_id = ? ORDER BY id"""
        params: tuple = (channel_id,)
        
        if limit > 0:
            query += " LIMIT ?"
            params = (channel_id, limit)
        
        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        
        messages = []
        for row in rows:
            role, content, tool_calls_json, tool_call_id, name = row
            messages.append(Message(
                role=role,
                content=content,
                tool_calls=json.loads(tool_calls_json) if tool_calls_json else None,
                tool_call_id=tool_call_id,
                name=name,
            ))
        
        return messages
    
    async def get_token_count(self, channel_id: str) -> int:
        """Get total token count for a session."""
        if not self._db:
            return 0
        
        cursor = await self._db.execute(
            "SELECT total_tokens FROM sessions WHERE channel_id = ?",
            (channel_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0
    
    async def clear_messages(self, channel_id: str) -> int:
        """Clear all messages for a session. Returns count deleted."""
        if not self._db:
            return 0
        
        cursor = await self._db.execute(
            "DELETE FROM messages WHERE channel_id = ?",
            (channel_id,),
        )
        await self._db.execute(
            "DELETE FROM sessions WHERE channel_id = ?",
            (channel_id,),
        )
        await self._db.commit()
        
        deleted = cursor.rowcount
        if deleted and self.bus:
            await self.bus.emit_nowait("memory.session.cleared", {
                "channel_id": channel_id,
                "deleted": deleted,
            }, source="memory.sessions")
        
        return deleted
    
    async def replace_messages(self, channel_id: str, messages: list[Message],
                               token_counts: list[int] | None = None) -> None:
        """Replace all messages in a session (used by compaction)."""
        if not self._db:
            raise RuntimeError("SessionStore not opened")
        
        now = time.time()
        counts = token_counts or [0] * len(messages)
        
        await self._db.execute(
            "DELETE FROM messages WHERE channel_id = ?",
            (channel_id,),
        )
        
        total_tokens = 0
        for msg, tc in zip(messages, counts):
            await self._db.execute(
                """INSERT INTO messages 
                   (channel_id, role, content, tool_calls, tool_call_id, name, token_count, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    channel_id, msg.role, msg.content,
                    json.dumps(msg.tool_calls) if msg.tool_calls else None,
                    msg.tool_call_id, msg.name, tc, now,
                ),
            )
            total_tokens += tc
        
        await self._db.execute(
            """INSERT INTO sessions (channel_id, total_tokens, message_count, last_active, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(channel_id) DO UPDATE SET
                   total_tokens = ?,
                   message_count = ?,
                   last_active = ?""",
            (channel_id, total_tokens, len(messages), now, now,
             total_tokens, len(messages), now),
        )
        
        await self._db.commit()
        
        if self.bus:
            await self.bus.emit_nowait("memory.session.replaced", {
                "channel_id": channel_id,
                "message_count": len(messages),
                "total_tokens": total_tokens,
            }, source="memory.sessions")
    
    async def list_sessions(self) -> list[dict[str, Any]]:
        """List all active sessions with metadata."""
        if not self._db:
            return []
        
        cursor = await self._db.execute(
            """SELECT channel_id, total_tokens, message_count, last_active 
               FROM sessions ORDER BY last_active DESC"""
        )
        rows = await cursor.fetchall()
        
        return [
            {
                "channel_id": r[0],
                "total_tokens": r[1],
                "message_count": r[2],
                "last_active": r[3],
            }
            for r in rows
        ]
