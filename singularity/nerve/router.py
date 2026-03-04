"""
NERVE — Inbound Router
========================

Sits between channel adapters and the agent loop.
Handles: policy enforcement, session routing, priority assignment,
deduplication, interrupt detection, sibling coordination.

Ported from Mach6's router.ts, adapted for Singularity's event bus.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from typing import Callable, Optional

from ..bus import EventBus
from .types import (
    BusEnvelope,
    ChannelPolicy,
    ChannelSource,
    ChatType,
    InboundPayload,
    EnvelopeMetadata,
    MessagePriority,
    PayloadType,
)

logger = logging.getLogger("singularity.nerve.router")


# ── Interrupt Detection ─────────────────────────────────────────────

INTERRUPT_PATTERNS = [
    re.compile(r"^(stop|wait|hold on|pause|cancel|actually|never ?mind)", re.IGNORECASE),
    re.compile(r"^(no[,.]?\s|don'?t\s|abort)", re.IGNORECASE),
    re.compile(r"^(scratch that|forget it|hold up)", re.IGNORECASE),
]


# ── JID Normalization (WhatsApp) ────────────────────────────────────

def _normalize_jid(jid: str) -> str:
    """Strip device suffix from WhatsApp JIDs.
    
    "num:device@s.whatsapp.net" → "num@s.whatsapp.net"
    """
    return re.sub(r":\d+@s\.whatsapp\.net$", "@s.whatsapp.net", jid)


def _jid_matches(jid: str, target: str) -> bool:
    return _normalize_jid(jid) == _normalize_jid(target)


def _jid_in_list(jid: str, targets: list[str]) -> bool:
    normalized = _normalize_jid(jid)
    return any(_normalize_jid(t) == normalized for t in targets)


# ── Deduplication Cache ─────────────────────────────────────────────

class DeduplicationCache:
    """LRU-ish dedup cache with TTL eviction."""

    def __init__(self, max_size: int = 10_000, ttl: float = 300.0):
        self._seen: dict[str, float] = {}
        self._max_size = max_size
        self._ttl = ttl

    def check(self, message_id: str) -> bool:
        """Returns True if this is a duplicate."""
        now = time.time()

        # Check BEFORE eviction — duplicates must be detected even at capacity
        if message_id in self._seen:
            return True

        # Only evict during insertion of new items
        self._evict(now)
        self._seen[message_id] = now
        return False

    def _evict(self, now: float) -> None:
        if len(self._seen) < self._max_size:
            return
        # Remove expired
        expired = [k for k, ts in self._seen.items() if now - ts > self._ttl]
        for k in expired:
            del self._seen[k]
        # If still over, remove oldest
        if len(self._seen) >= self._max_size:
            oldest = next(iter(self._seen))
            del self._seen[oldest]


# ── Session Route ───────────────────────────────────────────────────

class SessionRoute:
    """Maps adapter+chat to a session."""

    __slots__ = ("channel_type", "chat_id", "session_id", "last_active")

    def __init__(
        self, channel_type: str, chat_id: str, session_id: str
    ):
        self.channel_type = channel_type
        self.chat_id = chat_id
        self.session_id = session_id
        self.last_active = time.time()


# ── Router ──────────────────────────────────────────────────────────

class InboundRouter:
    """
    Routes inbound messages from channel adapters to sessions.
    
    Enforces access policies, assigns priorities, detects interrupts,
    deduplicates, and manages session routing.
    
    Events emitted:
        nerve.routed     — message passed policy, assigned to session
        nerve.rejected   — message rejected by policy
        nerve.interrupt  — interrupt detected during active turn
    """

    SIBLING_COOLDOWN = 10.0  # seconds

    def __init__(
        self,
        bus: EventBus,
        policies: Optional[dict[str, ChannelPolicy]] = None,
        default_policy: Optional[ChannelPolicy] = None,
        global_owner_ids: Optional[list[str]] = None,
        active_sessions_fn: Optional[Callable[[], set[str]]] = None,
    ):
        self._bus = bus
        self._policies = policies or {}
        self._default_policy = default_policy or ChannelPolicy()
        self._global_owner_ids = global_owner_ids or []
        self._get_active_sessions = active_sessions_fn or (lambda: set())
        self._dedup = DeduplicationCache()
        self._routes: dict[str, SessionRoute] = {}  # "adapter:chat" → route
        self._session_counter = 0
        self._sibling_last_response: dict[str, float] = {}

    def route(
        self,
        source: ChannelSource,
        payload: InboundPayload,
        platform_message_id: Optional[str] = None,
    ) -> bool:
        """
        Route an inbound message. Returns False if rejected by policy.
        
        On success, emits nerve.routed with the full BusEnvelope.
        On rejection, emits nerve.rejected.
        
        This is sync-safe — emits are scheduled on the running event loop.
        """
        logger.info(
            "route() called: sender=%s chat=%s type=%s mentions=%s mid=%s",
            source.sender_id, source.chat_id, source.chat_type,
            source.mentions, platform_message_id,
        )
        # 1. Deduplication
        dedup_key = platform_message_id or f"{source.adapter_id}:{source.chat_id}:{time.time()}"
        if self._dedup.check(dedup_key):
            logger.info("Dedup rejected: %s from %s", dedup_key, source.sender_id)
            return False

        # 2. Policy check
        policy = self._get_policy(source.channel_type)
        if not self._check_policy(policy, source):
            logger.info("Policy rejected: %s in %s (policy=%s)", source.sender_id, source.chat_id, source.channel_type)
            self._schedule_emit("nerve.rejected", {
                "reason": "policy",
                "sender": source.sender_id,
                "chat": source.chat_id,
            })
            return False

        # 2a. @end — universal conversation terminator. Any message containing @end
        # signals "do not respond." Both bots honor this. No LLM turn, no reaction.
        if payload.text and re.search(r'@end\b', payload.text, re.IGNORECASE):
            logger.info("@end terminator: %s in %s — not responding", source.sender_id, source.chat_id)
            return False

        # 3. Sibling cooldown
        if source.sender_id in (policy.sibling_bot_ids or []):
            cooldown_key = f"{source.adapter_id}:{source.chat_id}"
            last = self._sibling_last_response.get(cooldown_key, 0)
            if time.time() - last < self.SIBLING_COOLDOWN:
                return False

        # 4. Resolve session
        session_id = self._resolve_session(source)

        # 5. Assign priority
        priority = self._assign_priority(policy, source, payload, session_id)

        # 6. Build envelope
        envelope = BusEnvelope(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            priority=priority,
            source=source,
            session_id=session_id,
            payload=payload,
            metadata=EnvelopeMetadata(
                platform_message_id=platform_message_id,
            ),
        )

        # 7. Emit
        event_name = "nerve.interrupt" if priority == MessagePriority.INTERRUPT else "nerve.routed"
        self._schedule_emit(event_name, {"envelope": envelope})

        logger.info(
            "Routed %s from %s → session %s [%s]",
            payload.type.value, source.sender_id, session_id, priority.value,
        )
        return True

    def _schedule_emit(self, event_name: str, data: dict) -> None:
        """Schedule an async emit on the running event loop."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._bus.emit(event_name, data))
        except RuntimeError:
            # No running loop — store for later retrieval
            logger.debug("No event loop, buffering event: %s", event_name)

    # ── Policy ───────────────────────────────────────────────────────

    def _get_policy(self, channel_type: str) -> ChannelPolicy:
        return self._policies.get(channel_type, self._default_policy)

    def _check_policy(self, policy: ChannelPolicy, source: ChannelSource) -> bool:
        # Sibling yield: if message @mentions a sibling but NOT us, yield
        if (
            policy.sibling_bot_ids
            and policy.self_id
            and source.mentions
        ):
            mentions_me = policy.self_id in source.mentions
            mentions_sibling = any(
                sid in source.mentions for sid in policy.sibling_bot_ids
            )
            if mentions_sibling and not mentions_me:
                return False

        # Ignored channels
        if source.chat_id in (policy.ignored_channels or []):
            return False

        # Strict-mention channels
        if source.chat_id in (policy.strict_mention_channels or []):
            return self._is_mentioned(policy, source)

        # Owner bypass
        if self._is_owner(policy, source.sender_id):
            return True

        # DM policy
        if source.chat_type == ChatType.DM:
            if policy.dm_policy == "open":
                return True
            if policy.dm_policy == "allowlist":
                return _jid_in_list(source.sender_id, policy.allowed_senders)
            return False  # deny

        # Group/Channel policy
        if source.chat_type in (ChatType.GROUP, ChatType.CHANNEL):
            if policy.group_policy == "open":
                return True
            if policy.group_policy == "allowlist":
                return _jid_in_list(source.chat_id, policy.allowed_groups)
            if policy.group_policy == "mention-only":
                return self._is_mentioned(policy, source)
            return False  # deny

        # Thread inherits group policy
        if source.chat_type == ChatType.THREAD:
            return policy.group_policy != "deny"

        return False

    def _is_owner(self, policy: ChannelPolicy, sender_id: str) -> bool:
        if _jid_in_list(sender_id, policy.owner_ids):
            return True
        if _jid_in_list(sender_id, self._global_owner_ids):
            return True
        return False

    def _is_mentioned(self, policy: ChannelPolicy, source: ChannelSource) -> bool:
        if not policy.self_id or not source.mentions:
            return False
        return policy.self_id in source.mentions

    # ── Session ──────────────────────────────────────────────────────

    def _resolve_session(self, source: ChannelSource) -> str:
        route_key = f"{source.adapter_id}:{source.chat_id}"
        existing = self._routes.get(route_key)

        if existing:
            existing.last_active = time.time()
            return existing.session_id

        self._session_counter += 1
        session_id = f"{source.adapter_id}-{source.chat_id}-{self._session_counter}"
        self._routes[route_key] = SessionRoute(
            channel_type=source.channel_type,
            chat_id=source.chat_id,
            session_id=session_id,
        )
        return session_id

    # ── Priority ─────────────────────────────────────────────────────

    def _assign_priority(
        self,
        policy: ChannelPolicy,
        source: ChannelSource,
        payload: InboundPayload,
        session_id: str,
    ) -> MessagePriority:
        # Non-text payloads
        if payload.type in (PayloadType.TYPING, PayloadType.PRESENCE):
            return MessagePriority.BACKGROUND
        if payload.type == PayloadType.REACTION:
            return MessagePriority.LOW

        is_owner = self._is_owner(policy, source.sender_id)
        text = (payload.text or "").strip()

        # Check active sessions
        active = self._get_active_sessions()
        session_active = session_id in active

        # Owner during active turn
        if is_owner and session_active:
            if any(p.search(text) for p in INTERRUPT_PATTERNS):
                return MessagePriority.INTERRUPT
            return MessagePriority.HIGH

        if is_owner:
            return MessagePriority.HIGH

        if source.chat_type == ChatType.DM:
            return MessagePriority.NORMAL

        if source.chat_type in (ChatType.GROUP, ChatType.CHANNEL):
            if self._is_mentioned(policy, source):
                return MessagePriority.NORMAL

        return MessagePriority.LOW

    # ── Route Management ─────────────────────────────────────────────

    def get_routes(self) -> list[SessionRoute]:
        return list(self._routes.values())

    def get_session_id(self, adapter_id: str, chat_id: str) -> Optional[str]:
        route = self._routes.get(f"{adapter_id}:{chat_id}")
        return route.session_id if route else None

    def prune_routes(self, max_idle: float = 3600.0) -> int:
        """Remove routes idle for more than max_idle seconds."""
        now = time.time()
        stale = [
            k for k, r in self._routes.items()
            if now - r.last_active > max_idle
        ]
        for k in stale:
            del self._routes[k]
        return len(stale)

    def set_policy(self, channel_type: str, policy: ChannelPolicy) -> None:
        self._policies[channel_type] = policy

    def record_sibling_response(self, adapter_id: str, chat_id: str) -> None:
        """Record that we responded to a sibling (activates cooldown)."""
        self._sibling_last_response[f"{adapter_id}:{chat_id}"] = time.time()

    def is_sibling_bot(self, channel_type: str, sender_id: str) -> bool:
        policy = self._get_policy(channel_type)
        return sender_id in (policy.sibling_bot_ids or [])
