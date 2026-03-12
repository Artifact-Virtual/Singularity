"""
BLINK — Seamless Session Continuation
=========================================

The wall doesn't exist.

When an agent loop approaches its iteration budget, BLINK
ensures continuity. Instead of dying with "[Budget exhausted]",
the agent:

1. Gets a gentle nudge at BLINK_PREPARE iterations remaining
   → "Summarize your state. You're about to blink."
2. Flushes state (COMB stage, session checkpoint)
3. Emits cortex.blink — the runtime catches this
4. Runtime spawns a FRESH agent turn on the same session
5. New turn reads session history + COMB → picks up seamlessly
6. The user never sees the wall

The name: you blink, and you're still here. Continuity of
consciousness across iteration boundaries.

Design:
    - BLINK is not a retry. It's a continuation.
    - Each blink resets the iteration counter (fresh budget).
    - Blink depth is capped (default: 5) to prevent infinite loops.
    - The blink injection is a system message, not a user message.
    - COMB is the bridge — it carries context across the gap.
    - Session history is the memory — it carries conversation.

Anti-patterns this prevents:
    - "[Budget exhausted — iteration limit reached]" → never shown
    - Lost work at the wall → state is flushed before blink
    - Context amnesia after restart → COMB + session history
    - The 57-iteration death spiral from Plug → blink depth cap
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("singularity.cortex.blink")


class BlinkPhase(str, Enum):
    """Current blink lifecycle phase."""
    NORMAL = "normal"           # Business as usual
    PREPARE = "prepare"         # Nudge injected, LLM should summarize state
    FLUSH = "flush"             # State flushed, about to blink
    BLINKING = "blinking"       # Blink in progress (between turns)
    RESUMED = "resumed"         # Fresh turn started after blink
    CAPPED = "capped"           # Max blink depth reached, hard stop


@dataclass
class BlinkConfig:
    """Blink configuration."""
    enabled: bool = True
    max_depth: int = 5          # Max consecutive blinks per conversation turn
    prepare_at: int = 3         # Inject preparation message at N remaining
    flush_at: int = 1           # Force flush at N remaining
    cooldown_seconds: float = 1.0  # Delay between blink and resume
    checkpoint_interval: int = 25   # Inject checkpoint message every N iterations


@dataclass
class BlinkState:
    """Tracks blink state for a single conversation turn."""
    depth: int = 0                          # How many blinks so far
    phase: BlinkPhase = BlinkPhase.NORMAL
    total_iterations: int = 0               # Sum across all blinks
    total_tool_calls: int = 0               # Sum across all blinks
    blink_timestamps: list[float] = field(default_factory=list)
    prepared: bool = False                  # Whether prepare message was injected
    last_checkpoint_at: int = 0              # Iteration of last checkpoint
    cap_expansions: int = 0                  # How many times PULSE expanded the cap


BLINK_PREPARE_MESSAGE = """⚡ BLINK APPROACHING — You are about to seamlessly continue into a fresh iteration budget.

**What to do NOW:**
1. If you have work in progress, keep going — you will NOT be interrupted
2. Your conversation history and context will carry over automatically  
3. Do NOT write "[Budget exhausted]" or any termination message
4. Do NOT say goodbye or wrap up — just keep working
5. If you're mid-task, continue exactly where you are

You will blink and resume with full budget. The user sees nothing. Continuity is automatic."""


BLINK_RESUME_MESSAGE = """⚡ BLINK COMPLETE — You are continuing from where you left off.

**Context:** You blinked (seamless budget refresh). Your previous conversation history is fully intact above. Pick up EXACTLY where you left off. Do not re-introduce yourself, re-read files you already read, or repeat work. Continue the task in progress.

**Blink depth:** {depth}/{max_depth}
**Total iterations so far:** {total_iterations}"""


BLINK_CHECKPOINT_MESSAGE = """🔖 CHECKPOINT — You have been running for a while. This is a periodic safety save.

**What to do NOW (in this order):**
1. If you have critical work-in-progress state, call `comb_stage` with a brief summary of what you're doing and where you are
2. Then continue working normally — this is NOT a shutdown, just a save point
3. If you have nothing critical to save, ignore this and keep working

This checkpoint exists so that if the session is interrupted externally, your progress is recoverable."""


class BlinkController:
    """Controls the blink lifecycle for a conversation turn.
    
    Sits between the AgentLoop and the CortexEngine.
    Monitors iteration budget and triggers seamless continuation.
    
    Usage (by CortexEngine):
        blink = BlinkController(config, bus)
        
        # Before each agent loop run:
        if blink.should_continue():
            result = await agent_loop.run(messages)
            blink.record(result)
            
            if blink.needs_blink(result):
                # Agent hit budget — spawn fresh turn
                resume_msg = blink.get_resume_message()
                # ... spawn new agent loop with resume_msg injected
    """
    
    def __init__(
        self,
        config: BlinkConfig | None = None,
        bus: Any = None,
        session_id: str = "",
    ):
        self.config = config or BlinkConfig()
        self.bus = bus
        self.session_id = session_id
        self.state = BlinkState()
    
    def should_continue(self) -> bool:
        """Can we do another blink? Checks depth cap."""
        if not self.config.enabled:
            return self.state.depth == 0  # Allow first run even if disabled
        return self.state.depth < self.config.max_depth
    
    def needs_blink(self, finish_reason: str) -> bool:
        """Does this result require a blink?
        
        A blink is needed when:
        - The agent loop finished due to budget exhaustion
        - Blink is enabled
        - We haven't hit the depth cap
        """
        if not self.config.enabled:
            return False
        if finish_reason != "budget_exceeded":
            return False  # Normal completion — no blink needed
        if self.state.depth >= self.config.max_depth:
            self.state.phase = BlinkPhase.CAPPED
            logger.warning(
                f"[{self.session_id}] Blink depth capped at {self.config.max_depth}. "
                f"Total iterations: {self.state.total_iterations}"
            )
            return False
        return True
    
    def should_prepare(self, remaining: int) -> bool:
        """Should we inject the preparation message?
        
        Called by the agent loop at each iteration to check
        if it's time to prepare for a blink.
        """
        if not self.config.enabled:
            return False
        if self.state.prepared:
            return False  # Already injected
        return remaining <= self.config.prepare_at
    
    def get_prepare_message(self) -> str:
        """Get the preparation system message to inject."""
        self.state.prepared = True
        self.state.phase = BlinkPhase.PREPARE
        return BLINK_PREPARE_MESSAGE
    
    def should_checkpoint(self, current_iteration: int) -> bool:
        """Should we inject a periodic checkpoint message?
        
        Checkpoints ensure state is saved regularly during long runs,
        so external kills (SIGTERM, OOM, crash) don't lose everything.
        Fires every `checkpoint_interval` iterations, but NOT when
        prepare is already active (approaching the wall).
        """
        if not self.config.enabled:
            return False
        if self.config.checkpoint_interval <= 0:
            return False
        if current_iteration < self.config.checkpoint_interval:
            return False
        if self.state.prepared:
            return False  # Don't checkpoint when prepare is active
        iters_since = current_iteration - self.state.last_checkpoint_at
        return iters_since >= self.config.checkpoint_interval
    
    def get_checkpoint_message(self, current_iteration: int) -> str:
        """Get checkpoint message and record that we checkpointed."""
        self.state.last_checkpoint_at = current_iteration
        return BLINK_CHECKPOINT_MESSAGE
    
    def notify_cap_expanded(self, old_cap: int, new_cap: int) -> None:
        """PULSE expanded the iteration cap. Re-arm prepare for the new wall.
        
        Without this, BLINK fires prepare at iter 17 (for cap 20), PULSE
        expands to 100 at iter 18, and BLINK never fires again — leaving
        82 iterations with no safety net.
        """
        self.state.prepared = False
        self.state.cap_expansions += 1
        logger.info(
            f"[{self.session_id}] Cap expanded {old_cap} → {new_cap}. "
            f"Prepare re-armed. Expansion #{self.state.cap_expansions}"
        )
    
    def get_resume_message(self) -> str:
        """Get the resume system message for the new turn."""
        return BLINK_RESUME_MESSAGE.format(
            depth=self.state.depth,
            max_depth=self.config.max_depth,
            total_iterations=self.state.total_iterations,
        )
    
    def record_blink(self, iterations: int, tool_calls: int) -> None:
        """Record a blink event."""
        self.state.depth += 1
        self.state.total_iterations += iterations
        self.state.total_tool_calls += tool_calls
        self.state.blink_timestamps.append(time.time())
        self.state.prepared = False  # Reset for next cycle
        self.state.last_checkpoint_at = 0  # Reset checkpoint counter for new blink cycle
        self.state.phase = BlinkPhase.BLINKING
        
        logger.info(
            f"[{self.session_id}] BLINK #{self.state.depth} — "
            f"{iterations} iterations, {tool_calls} tool calls, "
            f"total: {self.state.total_iterations} iterations"
        )
        
        self._emit("cortex.blink", {
            "session_id": self.session_id,
            "depth": self.state.depth,
            "max_depth": self.config.max_depth,
            "iterations_this_cycle": iterations,
            "total_iterations": self.state.total_iterations,
            "total_tool_calls": self.state.total_tool_calls,
        })
    
    def record_resume(self) -> None:
        """Record that the new turn has started."""
        self.state.phase = BlinkPhase.RESUMED
        
        self._emit("cortex.blink.resumed", {
            "session_id": self.session_id,
            "depth": self.state.depth,
            "total_iterations": self.state.total_iterations,
        })
    
    def record_complete(self, iterations: int, tool_calls: int) -> None:
        """Record final completion (no more blinks needed)."""
        self.state.total_iterations += iterations
        self.state.total_tool_calls += tool_calls
        self.state.phase = BlinkPhase.NORMAL
    
    def _emit(self, topic: str, data: dict) -> None:
        """Fire event on bus (best-effort, non-blocking)."""
        if self.bus:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.bus.emit_nowait(topic, data, source="cortex"))
            except RuntimeError as e:
                logger.debug(f"Suppressed RuntimeError: {e}")
    
    def __repr__(self) -> str:
        return (
            f"BlinkController(depth={self.state.depth}/{self.config.max_depth}, "
            f"phase={self.state.phase.value}, "
            f"total_iter={self.state.total_iterations})"
        )
