"""
NERVE — Communication Subsystem
==================================

Channel adapters, message routing, formatting.
The nervous system that connects Aria to the outside world.

Components:
    types       — Message types, envelopes, capabilities, health tracking
    adapter     — Abstract adapter base with rate limiting & reconnection
    formatter   — Platform-aware markdown formatting & message splitting
    router      — Inbound routing, policy enforcement, session management
    discord     — Discord adapter (discord.py)
"""

from .types import (
    AdapterHealth,
    AdapterState,
    BusEnvelope,
    ChannelCapabilities,
    ChannelPolicy,
    ChannelSource,
    ChatType,
    EnvelopeMetadata,
    FormattingDialect,
    HealthTracker,
    InboundPayload,
    MediaPayload,
    MessagePriority,
    OutboundMessage,
    PayloadType,
    RateLimitConfig,
    ReactionPayload,
    SendResult,
)

from .adapter import BaseAdapter, TokenBucketLimiter
from .formatter import format_for_channel, split_on_boundaries
from .router import InboundRouter

__all__ = [
    # Types
    "AdapterHealth",
    "AdapterState",
    "BusEnvelope",
    "ChannelCapabilities",
    "ChannelPolicy",
    "ChannelSource",
    "ChatType",
    "EnvelopeMetadata",
    "FormattingDialect",
    "HealthTracker",
    "InboundPayload",
    "MediaPayload",
    "MessagePriority",
    "OutboundMessage",
    "PayloadType",
    "RateLimitConfig",
    "ReactionPayload",
    "SendResult",
    # Adapter
    "BaseAdapter",
    "TokenBucketLimiter",
    # Formatter
    "format_for_channel",
    "split_on_boundaries",
    # Router
    "InboundRouter",
]
