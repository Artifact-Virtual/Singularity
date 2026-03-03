"""
NERVE — Abstract Channel Adapter Base
========================================

Provides common infrastructure (health tracking, reconnection logic,
rate limiting) so concrete adapters only implement platform-specific I/O.

Ported from Mach6's adapter.ts.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Callable, Optional

from .types import (
    AdapterHealth,
    AdapterState,
    BusEnvelope,
    ChannelCapabilities,
    ChannelSource,
    EnvelopeMetadata,
    HealthTracker,
    InboundPayload,
    MessagePriority,
    OutboundMessage,
    SendResult,
)

logger = logging.getLogger("singularity.nerve.adapter")


# ── Token Bucket Rate Limiter ────────────────────────────────────────

class TokenBucketLimiter:
    """Rate limiter using token bucket algorithm."""

    def __init__(self, max_per_second: float, burst_size: Optional[int] = None):
        self._max_tokens = burst_size or int(max_per_second)
        self._tokens = float(self._max_tokens)
        self._refill_rate = max_per_second / 1000.0  # tokens per ms
        self._last_refill = time.monotonic() * 1000  # ms

    def check(self) -> float:
        """Returns delay in seconds before send is allowed. 0 = immediate."""
        self._refill()
        if self._tokens >= 1:
            return 0.0
        return (1.0 - self._tokens) / self._refill_rate / 1000.0

    def consume(self) -> bool:
        """Consume a token. Returns True if available."""
        self._refill()
        if self._tokens >= 1:
            self._tokens -= 1
            return True
        return False

    def _refill(self) -> None:
        now = time.monotonic() * 1000
        elapsed = now - self._last_refill
        self._tokens = min(
            float(self._max_tokens),
            self._tokens + elapsed * self._refill_rate,
        )
        self._last_refill = now


# ── Abstract Base Adapter ────────────────────────────────────────────

class BaseAdapter(ABC):
    """
    Abstract channel adapter base.
    
    Concrete adapters implement:
        - platform_connect(config)
        - platform_disconnect()
        - platform_reconnect()
        - platform_send(chat_id, message)
    
    Base provides:
        - Health tracking with valid state transitions
        - Rate limiting
        - Automatic reconnection with exponential backoff
        - Message normalization (emit → BusEnvelope)
    """

    def __init__(self, adapter_id: str):
        self._id = adapter_id
        self._health = HealthTracker()
        self._rate_limiter: Optional[TokenBucketLimiter] = None
        self._message_handler: Optional[Callable[[BusEnvelope], None]] = None
        self._health_handler: Optional[Callable[[AdapterHealth], None]] = None
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10
        self._reconnect_backoff = 1.0  # seconds
        self._running = False

    @property
    def id(self) -> str:
        return self._id

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """Channel type identifier: "discord", "whatsapp", etc."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> ChannelCapabilities:
        """What this platform supports."""
        ...

    # ── Lifecycle ────────────────────────────────────────────────────

    async def connect(self, config: dict) -> None:
        """Connect to the platform."""
        # Setup rate limiter
        rl = self.capabilities.rate_limits
        if rl.messages_per_second:
            self._rate_limiter = TokenBucketLimiter(
                rl.messages_per_second, rl.burst_size
            )

        try:
            await self.platform_connect(config)
            self._health.transition(AdapterState.CONNECTED)
            self._reconnect_attempts = 0
            self._running = True
        except Exception as exc:
            self._health.transition(
                AdapterState.DISCONNECTED, str(exc)
            )
            raise

    async def disconnect(self) -> None:
        """Graceful disconnect."""
        self._running = False
        try:
            await self.platform_disconnect()
        finally:
            self._health.transition(AdapterState.DISCONNECTED)

    async def reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        if self._health.state == AdapterState.RECONNECTING:
            return

        self._health.transition(AdapterState.DISCONNECTED)
        self._health.transition(AdapterState.RECONNECTING)

        while self._reconnect_attempts < self._max_reconnect_attempts:
            self._reconnect_attempts += 1
            delay = min(
                self._reconnect_backoff * (2 ** (self._reconnect_attempts - 1)),
                60.0,
            )

            logger.info(
                "[%s] Reconnect attempt %d/%d (delay %.1fs)",
                self._id, self._reconnect_attempts,
                self._max_reconnect_attempts, delay,
            )

            await asyncio.sleep(delay)

            try:
                await self.platform_reconnect()
                self._health.transition(AdapterState.CONNECTED)
                self._reconnect_attempts = 0
                self._running = True
                return
            except Exception as exc:
                logger.error(
                    "[%s] Reconnect attempt %d failed: %s",
                    self._id, self._reconnect_attempts, exc,
                )

        self._health.transition(
            AdapterState.DISCONNECTED,
            f"Max reconnect attempts ({self._max_reconnect_attempts}) exceeded",
        )

    def get_health(self) -> AdapterHealth:
        return self._health.status

    # ── Event Registration ───────────────────────────────────────────

    def on_message(self, handler: Callable[[BusEnvelope], None]) -> None:
        """Register handler for inbound messages."""
        self._message_handler = handler

    def on_health_change(self, handler: Callable[[AdapterHealth], None]) -> None:
        """Register handler for health state changes."""
        self._health_handler = handler
        self._health.on_change(handler)

    # ── Outbound ─────────────────────────────────────────────────────

    async def send(self, chat_id: str, message: OutboundMessage) -> SendResult:
        """Send a message with rate limiting."""
        if self._rate_limiter:
            delay = self._rate_limiter.check()
            if delay > 0:
                await asyncio.sleep(delay)
            self._rate_limiter.consume()

        try:
            return await self.platform_send(chat_id, message)
        except Exception as exc:
            if self._is_connection_error(exc):
                self._health.transition(AdapterState.DEGRADED)
            return SendResult(success=False, error=str(exc))

    # ── Helpers for Subclasses ───────────────────────────────────────

    def emit(
        self,
        source: ChannelSource,
        payload: InboundPayload,
        platform_message_id: Optional[str] = None,
    ) -> None:
        """
        Emit a normalized inbound message.
        
        Call this from platform event handlers. The message handler
        (set by the router or runtime) receives a BusEnvelope.
        """
        if not self._message_handler:
            return

        envelope = BusEnvelope(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            priority=MessagePriority.NORMAL,  # Router will reassign
            source=source,
            payload=payload,
            metadata=EnvelopeMetadata(
                platform_message_id=platform_message_id,
            ),
        )

        self._message_handler(envelope)

    def _is_connection_error(self, exc: Exception) -> bool:
        """Override in subclass for platform-specific detection."""
        return False

    # ── Abstract Platform Methods ────────────────────────────────────

    @abstractmethod
    async def platform_connect(self, config: dict) -> None:
        """Connect to the platform."""
        ...

    @abstractmethod
    async def platform_disconnect(self) -> None:
        """Disconnect from the platform."""
        ...

    @abstractmethod
    async def platform_reconnect(self) -> None:
        """Reconnect to the platform."""
        ...

    @abstractmethod
    async def platform_send(
        self, chat_id: str, message: OutboundMessage
    ) -> SendResult:
        """Send a message on the platform."""
        ...

    # ── Optional Platform Actions ────────────────────────────────────

    async def react(
        self, chat_id: str, message_id: str, emoji: str
    ) -> None:
        """React to a message. Override if platform supports it."""
        raise NotImplementedError(
            f"{self.channel_type} adapter does not support reactions"
        )

    async def edit_message(
        self, chat_id: str, message_id: str, new_content: str
    ) -> None:
        """Edit a sent message. Override if platform supports it."""
        raise NotImplementedError(
            f"{self.channel_type} adapter does not support message editing"
        )

    async def delete_message(self, chat_id: str, message_id: str) -> None:
        """Delete a message. Override if platform supports it."""
        raise NotImplementedError(
            f"{self.channel_type} adapter does not support message deletion"
        )

    async def typing(self, chat_id: str, duration_ms: int = 5000) -> None:
        """Send typing indicator. Override if platform supports it."""
        raise NotImplementedError(
            f"{self.channel_type} adapter does not support typing indicators"
        )

    async def mark_read(self, chat_id: str, message_id: str) -> None:
        """Mark a message as read. Override if platform supports it."""
        raise NotImplementedError(
            f"{self.channel_type} adapter does not support read receipts"
        )
