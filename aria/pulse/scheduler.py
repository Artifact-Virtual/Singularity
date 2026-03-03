"""
PULSE — Scheduler (Cron + Timers + Triggers)
===============================================

Manages:
- Periodic tasks (cron-like intervals)
- One-shot timers
- Event-driven triggers (react to bus events)

All jobs emit events on the bus when they fire.
No direct function calls — everything goes through events.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from ..bus import EventBus

logger = logging.getLogger("singularity.pulse.scheduler")


# ── Job Types ─────────────────────────────────────────────────

class JobType(str, Enum):
    INTERVAL = "interval"    # Repeating at fixed intervals
    ONESHOT = "oneshot"      # Fire once after delay
    EVENT = "event"          # Fire when a bus event matches


class JobState(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    FIRED = "fired"          # For oneshots
    CANCELLED = "cancelled"
    ERRORED = "errored"


@dataclass
class JobConfig:
    """Configuration for a scheduled job."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    job_type: JobType = JobType.INTERVAL
    
    # For INTERVAL and ONESHOT
    interval_seconds: float = 0
    
    # For EVENT
    event_pattern: str = ""       # Bus event topic to watch
    
    # What happens when the job fires
    emit_topic: str = ""          # Event to emit on fire
    emit_data: dict = field(default_factory=dict)
    
    # Scheduling constraints
    max_fires: int = 0            # 0 = unlimited (for intervals)
    active_hours: tuple[int, int] | None = None  # (start_hour, end_hour) UTC


@dataclass
class JobStatus:
    """Runtime status of a job."""
    config: JobConfig
    state: JobState = JobState.PENDING
    fire_count: int = 0
    last_fired: float | None = None
    next_fire: float | None = None
    errors: int = 0
    last_error: str | None = None


# ── Scheduler ─────────────────────────────────────────────────

class Scheduler:
    """
    Event-driven scheduler. All outputs go through the bus.
    
    Usage:
        scheduler = Scheduler(bus)
        await scheduler.start()
        
        # Add a heartbeat every 30 minutes
        scheduler.add(JobConfig(
            name="heartbeat",
            job_type=JobType.INTERVAL,
            interval_seconds=1800,
            emit_topic="pulse.heartbeat",
        ))
        
        # One-shot timer
        scheduler.add(JobConfig(
            name="reminder",
            job_type=JobType.ONESHOT,
            interval_seconds=300,
            emit_topic="pulse.reminder",
            emit_data={"message": "Check email"},
        ))
        
        # Event trigger: when disk warning fires, increase check freq
        scheduler.add(JobConfig(
            name="disk-react",
            job_type=JobType.EVENT,
            event_pattern="immune.disk.warning",
            emit_topic="pulse.accelerate_checks",
        ))
    """
    
    def __init__(self, bus: EventBus, tick_interval: float = 1.0):
        self.bus = bus
        self._jobs: dict[str, JobStatus] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False
        self._tick_task: asyncio.Task | None = None
        self._tick_interval = tick_interval
    
    # ── Lifecycle ─────────────────────────────────────────────
    
    async def start(self) -> None:
        """Start the scheduler tick loop."""
        if self._running:
            return
        self._running = True
        self._tick_task = asyncio.create_task(self._tick_loop())
        logger.info("Scheduler started")
        await self.bus.emit("pulse.scheduler.started", {})
    
    async def stop(self) -> None:
        """Stop the scheduler and cancel all running jobs."""
        self._running = False
        
        # Cancel all job tasks
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
        
        # Cancel tick loop
        if self._tick_task:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
            self._tick_task = None
        
        logger.info("Scheduler stopped")
    
    # ── Job Management ────────────────────────────────────────
    
    def add(self, config: JobConfig) -> str:
        """
        Add a job. Returns job ID.
        The job starts automatically on the next tick.
        """
        if config.id in self._jobs:
            logger.warning(f"Job {config.id} already exists, replacing")
            self.remove(config.id)
        
        status = JobStatus(config=config, state=JobState.PENDING)
        
        # Calculate first fire time
        if config.job_type in (JobType.INTERVAL, JobType.ONESHOT):
            status.next_fire = time.monotonic() + config.interval_seconds
        
        self._jobs[config.id] = status
        
        # If event-driven, subscribe to the bus
        if config.job_type == JobType.EVENT and config.event_pattern:
            self._subscribe_event_job(config)
        
        status.state = JobState.ACTIVE
        logger.debug(f"Job added: {config.name or config.id} ({config.job_type.value})")
        return config.id
    
    def remove(self, job_id: str) -> bool:
        """Remove a job by ID."""
        if job_id not in self._jobs:
            return False
        
        self._jobs[job_id].state = JobState.CANCELLED
        
        if job_id in self._tasks:
            self._tasks[job_id].cancel()
            del self._tasks[job_id]
        
        del self._jobs[job_id]
        return True
    
    def get_status(self, job_id: str) -> JobStatus | None:
        """Get job status."""
        return self._jobs.get(job_id)
    
    def list_jobs(self) -> list[JobStatus]:
        """List all jobs with their status."""
        return list(self._jobs.values())
    
    # ── Internal ──────────────────────────────────────────────
    
    async def _tick_loop(self) -> None:
        """Main scheduler loop. Checks every second."""
        try:
            while self._running:
                now = time.monotonic()
                
                for job_id, status in list(self._jobs.items()):
                    if status.state != JobState.ACTIVE:
                        continue
                    
                    if status.config.job_type == JobType.EVENT:
                        continue  # Event jobs are subscription-based
                    
                    if status.next_fire and now >= status.next_fire:
                        await self._fire_job(status)
                
                await asyncio.sleep(self._tick_interval)
        except asyncio.CancelledError:
            pass
    
    async def _fire_job(self, status: JobStatus) -> None:
        """Fire a job — emit its event on the bus."""
        config = status.config
        
        # Check active hours
        if config.active_hours:
            import datetime
            current_hour = datetime.datetime.now().hour
            start, end = config.active_hours
            if start <= end:
                if not (start <= current_hour < end):
                    # Outside active hours — reschedule
                    if config.job_type == JobType.INTERVAL:
                        status.next_fire = time.monotonic() + config.interval_seconds
                    return
            else:
                # Wraps midnight (e.g., 22-6)
                if end <= current_hour < start:
                    if config.job_type == JobType.INTERVAL:
                        status.next_fire = time.monotonic() + config.interval_seconds
                    return
        
        try:
            emit_data = {
                **config.emit_data,
                "job_id": config.id,
                "job_name": config.name,
                "fire_count": status.fire_count + 1,
            }
            
            if config.emit_topic:
                await self.bus.emit(config.emit_topic, emit_data)
            
            status.fire_count += 1
            status.last_fired = time.monotonic()
            
            logger.debug(f"Job fired: {config.name or config.id} (#{status.fire_count})")
            
        except Exception as e:
            status.errors += 1
            status.last_error = str(e)
            logger.error(f"Job {config.name or config.id} error: {e}")
        
        # Reschedule or complete
        if config.job_type == JobType.ONESHOT:
            status.state = JobState.FIRED
        elif config.job_type == JobType.INTERVAL:
            if config.max_fires > 0 and status.fire_count >= config.max_fires:
                status.state = JobState.FIRED
            else:
                status.next_fire = time.monotonic() + config.interval_seconds
    
    def _subscribe_event_job(self, config: JobConfig) -> None:
        """Subscribe to a bus event for an event-driven job."""
        async def handler(event):
            status = self._jobs.get(config.id)
            if not status or status.state != JobState.ACTIVE:
                return
            await self._fire_job(status)
        
        # Register on bus
        self.bus.on(config.event_pattern)(handler)
