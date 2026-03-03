"""
NERVE — Message & Channel Type Definitions
=============================================

Core types for the communication layer. Platform-agnostic message
representation, channel capabilities, routing policies.

Ported from Mach6's TypeScript channel types, adapted for Python/Singularity.
Zero external dependencies — only stdlib + dataclasses.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ── Enums ────────────────────────────────────────────────────────────

class MessagePriority(Enum):
    """Processing priority for inbound messages."""
    INTERRUPT = "interrupt"  # Stop current turn immediately
    HIGH = "high"            # Owner messages, direct commands
    NORMAL = "normal"        # Standard messages, DMs
    LOW = "low"              # Group mentions, reactions
    BACKGROUND = "background"  # Typing indicators, presence


class PayloadType(Enum):
    """Type of inbound message payload."""
    TEXT = "text"
    MEDIA = "media"
    REACTION = "reaction"
    EDIT = "edit"
    DELETE = "delete"
    TYPING = "typing"
    PRESENCE = "presence"
    SYSTEM = "system"


class ChatType(Enum):
    """Type of chat/conversation."""
    DM = "dm"
    GROUP = "group"
    CHANNEL = "channel"
    THREAD = "thread"


class AdapterState(Enum):
    """Health state of a channel adapter."""
    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"


class FormattingDialect(Enum):
    """Platform-native formatting dialect."""
    MARKDOWN = "markdown"      # Discord, generic
    HTML = "html"              # Telegram
    WHATSAPP = "whatsapp"      # WhatsApp-specific markdown
    SLACK_MRKDWN = "slack-mrkdwn"
    PLAIN = "plain"


# ── Inbound Types ────────────────────────────────────────────────────

@dataclass
class MediaPayload:
    """A media attachment (image, video, audio, document, sticker, voice)."""
    type: str  # image, video, audio, document, sticker, voice
    url: Optional[str] = None
    path: Optional[str] = None
    mime_type: Optional[str] = None
    filename: Optional[str] = None
    size_bytes: Optional[int] = None
    duration_ms: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    caption: Optional[str] = None


@dataclass
class ReactionPayload:
    """A reaction event."""
    emoji: str
    message_id: str
    remove: bool = False


@dataclass
class EditPayload:
    """A message edit event."""
    message_id: str
    new_text: str


@dataclass
class ChannelSource:
    """Where an inbound message came from."""
    channel_type: str         # "discord", "whatsapp", etc.
    adapter_id: str           # "discord-main", "wa-primary"
    chat_id: str              # Platform-specific chat/channel ID
    chat_type: ChatType
    sender_id: str            # Platform-specific sender ID
    sender_name: Optional[str] = None
    reply_to_id: Optional[str] = None
    thread_id: Optional[str] = None
    mentions: list[str] = field(default_factory=list)


@dataclass
class InboundPayload:
    """Normalized inbound message content."""
    type: PayloadType
    text: Optional[str] = None
    media: Optional[list[MediaPayload]] = None
    reaction: Optional[ReactionPayload] = None
    edit: Optional[EditPayload] = None
    raw: Any = None  # Platform-specific original event


@dataclass
class EnvelopeMetadata:
    """Platform-specific metadata preserved across the pipeline."""
    platform_message_id: Optional[str] = None
    guild_id: Optional[str] = None
    ephemeral: bool = False
    forwarded: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class BusEnvelope:
    """
    A normalized message envelope flowing through the system.
    
    Every inbound message — from any platform — is normalized into this
    shape before entering the processing pipeline.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    priority: MessagePriority = MessagePriority.NORMAL
    source: ChannelSource = field(default_factory=lambda: ChannelSource(
        channel_type="", adapter_id="", chat_id="",
        chat_type=ChatType.DM, sender_id=""
    ))
    session_id: Optional[str] = None
    payload: InboundPayload = field(default_factory=lambda: InboundPayload(
        type=PayloadType.TEXT
    ))
    metadata: EnvelopeMetadata = field(default_factory=EnvelopeMetadata)


# ── Outbound Types ───────────────────────────────────────────────────

@dataclass
class OutboundMessage:
    """A message to send to a platform."""
    content: str = ""
    media: Optional[list[MediaPayload]] = None
    reply_to_id: Optional[str] = None
    thread_id: Optional[str] = None
    ephemeral: bool = False
    split_strategy: str = "paginate"  # truncate, paginate, thread
    priority: str = "interactive"     # interactive, proactive, background


@dataclass
class SendResult:
    """Result of sending a message."""
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    delivered_at: Optional[float] = None


# ── Channel Capabilities ────────────────────────────────────────────

@dataclass
class RateLimitConfig:
    """Rate limit configuration for a channel."""
    messages_per_second: Optional[float] = None
    messages_per_minute: Optional[float] = None
    burst_size: Optional[int] = None


@dataclass
class ChannelCapabilities:
    """What a platform supports."""
    media: bool = True
    reactions: bool = True
    message_edit: bool = False
    message_delete: bool = True
    threads: bool = False
    embeds: bool = False
    components: bool = False
    voice_notes: bool = False
    read_receipts: bool = False
    typing_indicator: bool = True
    ephemeral: bool = False
    polls: bool = False
    formatting: FormattingDialect = FormattingDialect.MARKDOWN
    max_message_length: int = 2000
    max_media_size: int = 25 * 1024 * 1024  # 25 MB
    rate_limits: RateLimitConfig = field(default_factory=RateLimitConfig)


# ── Routing Policy ──────────────────────────────────────────────────

@dataclass
class ChannelPolicy:
    """Access control policy for a channel adapter."""
    dm_policy: str = "deny"        # open, allowlist, deny
    group_policy: str = "deny"     # open, allowlist, mention-only, deny
    owner_ids: list[str] = field(default_factory=list)
    allowed_senders: list[str] = field(default_factory=list)
    allowed_groups: list[str] = field(default_factory=list)
    self_id: Optional[str] = None
    sibling_bot_ids: list[str] = field(default_factory=list)
    require_mention: bool = False
    strict_mention_channels: list[str] = field(default_factory=list)
    ignored_channels: list[str] = field(default_factory=list)


# ── Health Tracking ─────────────────────────────────────────────────

# Valid state transitions for adapters
VALID_TRANSITIONS: dict[AdapterState, list[AdapterState]] = {
    AdapterState.CONNECTED: [AdapterState.DEGRADED, AdapterState.DISCONNECTED],
    AdapterState.DEGRADED: [AdapterState.CONNECTED, AdapterState.DISCONNECTED],
    AdapterState.DISCONNECTED: [AdapterState.RECONNECTING, AdapterState.CONNECTED],
    AdapterState.RECONNECTING: [AdapterState.CONNECTED, AdapterState.DISCONNECTED],
}


@dataclass
class AdapterHealth:
    """Health status snapshot of a channel adapter."""
    state: AdapterState = AdapterState.DISCONNECTED
    last_connected: float = 0.0
    disconnect_count: int = 0
    last_error: Optional[str] = None
    uptime_percent: float = 0.0
    latency_ms: Optional[float] = None


class HealthTracker:
    """
    Tracks adapter health with valid state transitions.
    
    Emits health change events and computes uptime percentage.
    """

    def __init__(self) -> None:
        self._state = AdapterState.DISCONNECTED
        self._last_connected = 0.0
        self._disconnect_count = 0
        self._last_error: Optional[str] = None
        self._connected_since = 0.0
        self._total_connected = 0.0
        self._tracking_since = time.time()
        self._handlers: list = []

    @property
    def state(self) -> AdapterState:
        return self._state

    @property
    def status(self) -> AdapterHealth:
        now = time.time()
        connected_s = self._total_connected
        if self._state == AdapterState.CONNECTED and self._connected_since > 0:
            connected_s += now - self._connected_since
        total_s = now - self._tracking_since
        uptime = round((connected_s / total_s) * 100, 1) if total_s > 0 else 0.0
        return AdapterHealth(
            state=self._state,
            last_connected=self._last_connected,
            disconnect_count=self._disconnect_count,
            last_error=self._last_error,
            uptime_percent=uptime,
        )

    def transition(self, to: AdapterState, error: Optional[str] = None) -> bool:
        """Attempt a state transition. Returns True if valid."""
        allowed = VALID_TRANSITIONS.get(self._state, [])
        if to not in allowed:
            return False

        now = time.time()

        # Accumulate connected time
        if self._state == AdapterState.CONNECTED and self._connected_since > 0:
            self._total_connected += now - self._connected_since
            self._connected_since = 0.0

        if to == AdapterState.CONNECTED:
            self._last_connected = now
            self._connected_since = now

        if to == AdapterState.DISCONNECTED:
            self._disconnect_count += 1
            if error:
                self._last_error = error

        self._state = to
        status = self.status
        for handler in self._handlers:
            handler(status)
        return True

    def on_change(self, handler) -> None:
        """Register a health change handler."""
        self._handlers.append(handler)
