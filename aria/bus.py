"""
EVENT BUS — The Nervous System
================================

Zero-dependency, asyncio-native event bus.

Design principles:
    1. Publish-subscribe. Loose coupling. Any component can fail independently.
    2. Typed events. Every event has a name, payload, timestamp, source.
    3. Wildcard subscriptions. Subscribe to "health.*" to catch all health events.
    4. Priority ordering. Critical events process before informational ones.
    5. Dead letter queue. Failed handlers don't crash the bus.
    6. Metrics. Event counts, handler latency, error rates — built in.
    7. No external dependencies. Pure asyncio. Redis pub/sub is a future ADAPTER, not a requirement.

Event naming convention:
    {subsystem}.{action}[.{detail}]
    
    Examples:
        nerve.message.received
        cortex.agent.started
        cortex.tool.executed
        memory.session.saved
        immune.health.degraded
        voice.provider.switched
        csuite.task.dispatched
        csuite.report.received
        pulse.cron.fired
        config.loaded
        config.reloaded

Usage:
    bus = EventBus()
    
    # Subscribe
    @bus.on("nerve.message.received")
    async def handle_message(event: Event):
        print(event.data)
    
    # Wildcard
    @bus.on("immune.*")
    async def handle_health(event: Event):
        log_health(event)
    
    # Publish
    await bus.emit("nerve.message.received", {
        "channel": "discord",
        "author": "Ali",
        "content": "hello",
    }, source="nerve.discord")
    
    # One-shot (auto-unsubscribe after first fire)
    @bus.once("cortex.agent.ready")
    async def on_ready(event: Event):
        print("Agent is ready!")
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Awaitable, Optional
from collections import defaultdict

logger = logging.getLogger("singularity.bus")


class Priority(IntEnum):
    """Event processing priority. Lower number = higher priority."""
    CRITICAL = 0    # System failures, interrupts
    HIGH = 10       # Health alerts, failover triggers
    NORMAL = 50     # Standard operations
    LOW = 90        # Metrics, logging, non-urgent
    BACKGROUND = 100  # Cleanup, analytics


@dataclass(frozen=True, slots=True)
class Event:
    """An immutable event on the bus."""
    name: str                          # e.g., "nerve.message.received"
    data: dict[str, Any]               # payload
    source: str = ""                   # originating subsystem
    timestamp: float = field(default_factory=time.time)
    priority: Priority = Priority.NORMAL
    correlation_id: str = ""           # for tracing event chains
    
    def __repr__(self) -> str:
        data_preview = str(self.data)[:100]
        return f"Event({self.name}, src={self.source}, data={data_preview})"


# Type alias for event handlers
EventHandler = Callable[[Event], Awaitable[None]]


@dataclass
class Subscription:
    """A registered event subscription."""
    pattern: str                # event name or wildcard pattern
    handler: EventHandler       # async callback
    priority: Priority = Priority.NORMAL
    once: bool = False          # auto-unsubscribe after first fire
    source: str = ""            # who registered this (for debugging)
    _id: int = 0                # unique subscription ID
    
    def matches(self, event_name: str) -> bool:
        """Check if this subscription matches an event name."""
        if self.pattern == event_name:
            return True
        if "*" in self.pattern or "?" in self.pattern:
            return fnmatch.fnmatch(event_name, self.pattern)
        return False


class DeadLetter:
    """Record of a failed event handler execution."""
    __slots__ = ("event", "handler_name", "error", "timestamp")
    
    def __init__(self, event: Event, handler_name: str, error: Exception):
        self.event = event
        self.handler_name = handler_name
        self.error = error
        self.timestamp = time.time()
    
    def __repr__(self) -> str:
        return f"DeadLetter({self.event.name} → {self.handler_name}: {self.error})"


class BusMetrics:
    """Real-time metrics for the event bus."""
    __slots__ = (
        "events_emitted", "events_delivered", "events_failed",
        "handler_latency_sum", "handler_calls",
        "_event_counts", "_error_counts",
    )
    
    def __init__(self):
        self.events_emitted: int = 0
        self.events_delivered: int = 0
        self.events_failed: int = 0
        self.handler_latency_sum: float = 0.0
        self.handler_calls: int = 0
        self._event_counts: dict[str, int] = defaultdict(int)
        self._error_counts: dict[str, int] = defaultdict(int)
    
    def record_emit(self, event_name: str) -> None:
        self.events_emitted += 1
        self._event_counts[event_name] += 1
    
    def record_delivery(self, latency: float) -> None:
        self.events_delivered += 1
        self.handler_calls += 1
        self.handler_latency_sum += latency
    
    def record_failure(self, event_name: str) -> None:
        self.events_failed += 1
        self._error_counts[event_name] += 1
    
    @property
    def avg_latency_ms(self) -> float:
        if self.handler_calls == 0:
            return 0.0
        return (self.handler_latency_sum / self.handler_calls) * 1000
    
    def snapshot(self) -> dict[str, Any]:
        return {
            "events_emitted": self.events_emitted,
            "events_delivered": self.events_delivered,
            "events_failed": self.events_failed,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "top_events": dict(sorted(
                self._event_counts.items(),
                key=lambda x: x[1], reverse=True,
            )[:10]),
            "top_errors": dict(sorted(
                self._error_counts.items(),
                key=lambda x: x[1], reverse=True,
            )[:5]),
        }


class EventBus:
    """
    The central nervous system of Singularity.
    
    Asyncio-native publish-subscribe event bus with:
    - Pattern matching (wildcards)
    - Priority ordering
    - Dead letter queue for failed handlers
    - Built-in metrics
    - Fire-and-forget or await-all semantics
    """
    
    def __init__(self, max_dead_letters: int = 100):
        self._subscriptions: list[Subscription] = []
        self._sub_counter: int = 0
        self._dead_letters: list[DeadLetter] = []
        self._max_dead_letters = max_dead_letters
        self._metrics = BusMetrics()
        self._running = False
        self._queue: asyncio.Queue[Event] | None = None
        self._processor_task: asyncio.Task | None = None
        # Middleware: pre-emit hooks (can modify/filter events)
        self._middleware: list[Callable[[Event], Awaitable[Event | None]]] = []
    
    # ── Lifecycle ────────────────────────────────────────────────────
    
    async def start(self) -> None:
        """Start the bus processor (processes queued events)."""
        if self._running:
            return
        self._running = True
        self._queue = asyncio.Queue()
        self._processor_task = asyncio.create_task(self._process_loop())
        logger.info("EventBus started")
    
    async def stop(self) -> None:
        """Stop the bus processor gracefully."""
        self._running = False
        if self._queue:
            # Sentinel to wake up the processor
            await self._queue.put(None)  # type: ignore
        if self._processor_task:
            try:
                await asyncio.wait_for(self._processor_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._processor_task.cancel()
            self._processor_task = None
        logger.info("EventBus stopped. Metrics: %s", self._metrics.snapshot())
    
    # ── Subscribe ────────────────────────────────────────────────────
    
    def on(self, pattern: str, *, priority: Priority = Priority.NORMAL, 
           source: str = "") -> Callable[[EventHandler], EventHandler]:
        """Decorator to subscribe to events matching a pattern.
        
        Usage:
            @bus.on("nerve.message.received")
            async def handle(event: Event):
                ...
            
            @bus.on("immune.*", priority=Priority.CRITICAL)
            async def handle_health(event: Event):
                ...
        """
        def decorator(handler: EventHandler) -> EventHandler:
            self.subscribe(pattern, handler, priority=priority, source=source)
            return handler
        return decorator
    
    def once(self, pattern: str, *, priority: Priority = Priority.NORMAL,
             source: str = "") -> Callable[[EventHandler], EventHandler]:
        """Subscribe to fire once then auto-unsubscribe."""
        def decorator(handler: EventHandler) -> EventHandler:
            self.subscribe(pattern, handler, priority=priority, source=source, once=True)
            return handler
        return decorator
    
    def subscribe(self, pattern: str, handler: EventHandler, *,
                  priority: Priority = Priority.NORMAL,
                  source: str = "", once: bool = False) -> int:
        """Register a subscription. Returns subscription ID."""
        self._sub_counter += 1
        sub = Subscription(
            pattern=pattern,
            handler=handler,
            priority=priority,
            once=once,
            source=source or getattr(handler, "__qualname__", str(handler)),
            _id=self._sub_counter,
        )
        self._subscriptions.append(sub)
        # Keep sorted by priority for ordered dispatch
        self._subscriptions.sort(key=lambda s: s.priority)
        logger.debug("Subscribed [%d] %s → %s (priority=%s, once=%s)",
                     sub._id, pattern, sub.source, priority.name, once)
        return sub._id
    
    def unsubscribe(self, sub_id: int) -> bool:
        """Remove a subscription by ID."""
        before = len(self._subscriptions)
        self._subscriptions = [s for s in self._subscriptions if s._id != sub_id]
        removed = len(self._subscriptions) < before
        if removed:
            logger.debug("Unsubscribed [%d]", sub_id)
        return removed
    
    # ── Publish ──────────────────────────────────────────────────────
    
    async def emit(self, name: str, data: dict[str, Any] | None = None, *,
                   source: str = "", priority: Priority = Priority.NORMAL,
                   correlation_id: str = "") -> None:
        """Emit an event. If the bus processor is running, queues it.
        Otherwise, processes inline (for pre-start bootstrapping).
        """
        event = Event(
            name=name,
            data=data or {},
            source=source,
            priority=priority,
            correlation_id=correlation_id,
        )
        
        # Run middleware
        for mw in self._middleware:
            try:
                result = await mw(event)
                if result is None:
                    # Middleware filtered out the event
                    logger.debug("Event %s filtered by middleware", name)
                    return
                event = result
            except Exception as e:
                logger.error("Middleware error on %s: %s", name, e)
        
        self._metrics.record_emit(name)
        
        if self._running and self._queue:
            await self._queue.put(event)
        else:
            # Process inline (bus not started yet — bootstrapping)
            await self._dispatch(event)
    
    async def emit_nowait(self, name: str, data: dict[str, Any] | None = None, *,
                          source: str = "", priority: Priority = Priority.NORMAL) -> None:
        """Fire-and-forget emit. Doesn't block if queue is full."""
        event = Event(name=name, data=data or {}, source=source, priority=priority)
        self._metrics.record_emit(name)
        
        if self._running and self._queue:
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Event bus queue full, dropping: %s", name)
        else:
            await self._dispatch(event)
    
    # ── Processing ───────────────────────────────────────────────────
    
    async def _process_loop(self) -> None:
        """Main event processing loop."""
        logger.debug("Bus processor started")
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                if event is None:
                    break  # Sentinel — shutdown
                await self._dispatch(event)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Bus processor error: %s", e, exc_info=True)
        logger.debug("Bus processor stopped")
    
    async def _dispatch(self, event: Event) -> None:
        """Dispatch an event to all matching subscribers."""
        to_remove: list[int] = []
        
        for sub in self._subscriptions:
            if not sub.matches(event.name):
                continue
            
            t0 = time.perf_counter()
            try:
                await sub.handler(event)
                latency = time.perf_counter() - t0
                self._metrics.record_delivery(latency)
                
                if latency > 1.0:
                    logger.warning("Slow handler: %s took %.2fs for %s",
                                   sub.source, latency, event.name)
                
            except Exception as e:
                self._metrics.record_failure(event.name)
                logger.error("Handler %s failed on %s: %s",
                             sub.source, event.name, e, exc_info=True)
                
                # Dead letter queue
                dl = DeadLetter(event, sub.source, e)
                self._dead_letters.append(dl)
                if len(self._dead_letters) > self._max_dead_letters:
                    self._dead_letters = self._dead_letters[-self._max_dead_letters:]
            
            if sub.once:
                to_remove.append(sub._id)
        
        # Clean up one-shot subscriptions
        if to_remove:
            self._subscriptions = [
                s for s in self._subscriptions if s._id not in set(to_remove)
            ]
    
    # ── Middleware ────────────────────────────────────────────────────
    
    def use(self, middleware: Callable[[Event], Awaitable[Event | None]]) -> None:
        """Add middleware that processes events before dispatch.
        
        Middleware can:
        - Modify the event (return modified Event)
        - Filter the event (return None to drop)
        - Log, meter, trace (return event unchanged)
        """
        self._middleware.append(middleware)
    
    # ── Inspection ───────────────────────────────────────────────────
    
    @property
    def metrics(self) -> BusMetrics:
        return self._metrics
    
    @property
    def dead_letters(self) -> list[DeadLetter]:
        return list(self._dead_letters)
    
    @property
    def subscription_count(self) -> int:
        return len(self._subscriptions)
    
    def list_subscriptions(self) -> list[dict[str, Any]]:
        """List all active subscriptions (for debugging)."""
        return [
            {
                "id": s._id,
                "pattern": s.pattern,
                "source": s.source,
                "priority": s.priority.name,
                "once": s.once,
            }
            for s in self._subscriptions
        ]
    
    async def wait_for(self, pattern: str, timeout: float = 30.0) -> Event:
        """Wait for a specific event (blocking). Useful for initialization gates."""
        future: asyncio.Future[Event] = asyncio.get_event_loop().create_future()
        
        async def _resolver(event: Event) -> None:
            if not future.done():
                future.set_result(event)
        
        self.subscribe(pattern, _resolver, once=True, source=f"wait_for({pattern})")
        
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Timed out waiting for event: {pattern}")
