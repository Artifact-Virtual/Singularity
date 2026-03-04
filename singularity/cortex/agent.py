"""
CORTEX — The Agent Loop
==========================

The brain of Singularity. This is where thinking happens.

Loop:
    1. Assemble context (system prompt + session history + new message)
    2. Send to VOICE (LLM provider chain)  
    3. If response has tool calls → execute them (SINEW) → add results → goto 2
    4. If response is text → emit to NERVE → store in MEMORY → done
    5. Enforce iteration budget (PULSE) — never loop forever

Design decisions:
    - Agent loop is persona-agnostic. Persona is injected via system prompt.
    - Tool execution is parallel by default (like Mach6, not serial like Plug).
    - Each iteration emits events. The bus carries everything.
    - Context window management is the agent's responsibility.
    - The agent doesn't know about Discord or WhatsApp. It knows about
      messages, tools, and responses. NERVE handles the rest.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from ..voice.provider import ChatMessage, ChatResponse
from ..voice.chain import ProviderChain
from ..sinew.executor import ToolExecutor
from ..sinew.definitions import TOOL_DEFINITIONS
from .blink import BlinkController

logger = logging.getLogger("singularity.cortex.agent")


@dataclass
class AgentConfig:
    """Configuration for an agent loop instance."""
    persona_name: str = "singularity"
    system_prompt: str = ""
    max_iterations: int = 20
    expanded_iterations: int = 100  # When PULSE auto-expands
    expansion_threshold: int = 18   # Expand at this iteration count
    temperature: float = 0.7
    max_tokens: int = 8192
    parallel_tools: bool = True     # Execute tool calls in parallel


@dataclass
class TurnResult:
    """Result of a complete agent turn (message in → response out)."""
    response: str = ""
    iterations: int = 0
    tool_calls_total: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    provider: str = ""
    finish_reason: str = "stop"     # stop, budget_exceeded, error
    error: Optional[str] = None


class AgentLoop:
    """The core think → act → observe loop.
    
    One AgentLoop per conversation turn. Created fresh each time
    a message comes in, runs until the LLM produces a final response
    or the iteration budget is exhausted.
    
    If a BlinkController is attached, the loop will inject a preparation
    message near the budget boundary instead of dying. The controller
    tracks whether a blink is needed so the engine can spawn a fresh loop.
    """
    
    def __init__(
        self,
        voice: ProviderChain,
        tools: ToolExecutor,
        config: AgentConfig,
        bus: Any = None,
        blink: BlinkController | None = None,
    ):
        self.voice = voice
        self.tools = tools
        self.config = config
        self.bus = bus
        self.blink = blink
        
        self._iteration = 0
        self._max_iterations = config.max_iterations
        self._expanded = False
        self._tool_calls_total = 0
        self._total_tokens = 0
        self._turn_id = str(uuid.uuid4())[:8]
    
    async def run(self, messages: list[ChatMessage]) -> TurnResult:
        """Execute the agent loop.
        
        Args:
            messages: Full conversation history including system prompt
                     and the new user message.
        
        Returns:
            TurnResult with the final response and metadata.
        """
        t0 = time.perf_counter()
        
        try:
            while self._iteration < self._max_iterations:
                self._iteration += 1
                remaining = self._max_iterations - self._iteration
                
                # ── PULSE: Auto-expand budget if near limit ──────
                if (remaining <= (self._max_iterations - self.config.expansion_threshold)
                    and not self._expanded):
                    self._max_iterations = self.config.expanded_iterations
                    self._expanded = True
                    logger.info(
                        f"[{self._turn_id}] PULSE expanded budget to "
                        f"{self._max_iterations} iterations"
                    )
                    if self.bus:
                        await self.bus.emit_nowait("cortex.budget.expanded", {
                            "turn_id": self._turn_id,
                            "new_max": self._max_iterations,
                        }, source="cortex")
                
                # ── THINK: Send to LLM ───────────────────────────
                
                # ── BLINK: Inject preparation if approaching boundary ──
                if self.blink:
                    remaining_after = self._max_iterations - self._iteration
                    if self.blink.should_prepare(remaining_after):
                        prep_msg = self.blink.get_prepare_message()
                        messages.append(ChatMessage(
                            role="user",
                            content=prep_msg,
                        ))
                        logger.info(
                            f"[{self._turn_id}] BLINK prepare injected "
                            f"({remaining_after} iterations remaining)"
                        )
                
                if self.bus:
                    await self.bus.emit_nowait("cortex.iteration.start", {
                        "turn_id": self._turn_id,
                        "iteration": self._iteration,
                        "remaining": self._max_iterations - self._iteration,
                        "messages": len(messages),
                    }, source="cortex")
                
                response = await self.voice.chat(
                    messages,
                    tools=TOOL_DEFINITIONS,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                )
                
                self._total_tokens += response.total_tokens
                
                logger.debug(
                    f"[{self._turn_id}] Iteration {self._iteration}: "
                    f"{response.finish_reason}, "
                    f"{len(response.tool_calls)} tool calls, "
                    f"{response.total_tokens} tokens"
                )
                
                # ── No tool calls → final response ───────────────
                if not response.has_tool_calls:
                    latency = (time.perf_counter() - t0) * 1000
                    
                    if self.bus:
                        await self.bus.emit_nowait("cortex.turn.complete", {
                            "turn_id": self._turn_id,
                            "iterations": self._iteration,
                            "tool_calls": self._tool_calls_total,
                            "tokens": self._total_tokens,
                            "latency_ms": round(latency),
                            "provider": response.provider_name,
                        }, source="cortex")
                    
                    return TurnResult(
                        response=response.content,
                        iterations=self._iteration,
                        tool_calls_total=self._tool_calls_total,
                        total_tokens=self._total_tokens,
                        latency_ms=latency,
                        provider=response.provider_name,
                        finish_reason="stop",
                    )
                
                # ── ACT: Execute tool calls ──────────────────────
                # Add assistant message with tool calls to history
                messages.append(ChatMessage(
                    role="assistant",
                    content=response.content or "",
                    tool_calls=response.tool_calls,
                ))
                
                # Execute tools (parallel or serial)
                tool_results = await self._execute_tools(response.tool_calls)
                self._tool_calls_total += len(response.tool_calls)
                
                # ── OBSERVE: Add tool results to history ─────────
                for tc, result in zip(response.tool_calls, tool_results):
                    messages.append(ChatMessage(
                        role="tool",
                        content=result,
                        tool_call_id=tc["id"],
                        name=tc["function"]["name"],
                    ))
            
            # Budget exhausted — but BLINK may save us
            latency = (time.perf_counter() - t0) * 1000
            logger.warning(
                f"[{self._turn_id}] Budget exhausted at {self._iteration} iterations"
            )
            
            if self.bus:
                await self.bus.emit_nowait("cortex.budget.exhausted", {
                    "turn_id": self._turn_id,
                    "iterations": self._iteration,
                    "tool_calls": self._tool_calls_total,
                    "blink_eligible": self.blink is not None and self.blink.should_continue(),
                }, source="cortex")
            
            # If blink controller exists, don't show the wall —
            # return with budget_exceeded so the engine can blink
            return TurnResult(
                response="",  # No dead-wall message — blink handles it
                iterations=self._iteration,
                tool_calls_total=self._tool_calls_total,
                total_tokens=self._total_tokens,
                latency_ms=latency,
                provider=self.voice.active.name if self.voice.active else "unknown",
                finish_reason="budget_exceeded",
            )
            
        except Exception as e:
            latency = (time.perf_counter() - t0) * 1000
            logger.error(f"[{self._turn_id}] Agent loop error: {e}", exc_info=True)
            
            if self.bus:
                await self.bus.emit_nowait("cortex.turn.error", {
                    "turn_id": self._turn_id,
                    "error": str(e),
                    "iteration": self._iteration,
                }, source="cortex")
            
            return TurnResult(
                response="",
                iterations=self._iteration,
                tool_calls_total=self._tool_calls_total,
                total_tokens=self._total_tokens,
                latency_ms=latency,
                finish_reason="error",
                error=str(e),
            )
    
    async def _execute_tools(self, tool_calls: list[dict]) -> list[str]:
        """Execute tool calls, optionally in parallel.
        
        Each tool call: {id, type, function: {name, arguments}}
        Returns list of result strings in same order.
        """
        if not tool_calls:
            return []
        
        if self.config.parallel_tools and len(tool_calls) > 1:
            return await self._execute_parallel(tool_calls)
        else:
            return await self._execute_serial(tool_calls)
    
    async def _execute_serial(self, tool_calls: list[dict]) -> list[str]:
        """Execute tool calls one at a time."""
        results = []
        for tc in tool_calls:
            result = await self._execute_single(tc)
            results.append(result)
        return results
    
    async def _execute_parallel(self, tool_calls: list[dict]) -> list[str]:
        """Execute tool calls in parallel."""
        tasks = [self._execute_single(tc) for tc in tool_calls]
        return await asyncio.gather(*tasks)
    
    async def _execute_single(self, tool_call: dict) -> str:
        """Execute a single tool call."""
        fn = tool_call.get("function", {})
        name = fn.get("name", "")
        
        # Parse arguments
        args_raw = fn.get("arguments", "{}")
        try:
            if isinstance(args_raw, str):
                # Handle empty/whitespace arguments (e.g. comb_recall with no params)
                args_raw = args_raw.strip() if args_raw else "{}"
                if not args_raw:
                    args_raw = "{}"
                arguments = json.loads(args_raw)
            else:
                arguments = args_raw if args_raw is not None else {}
        except json.JSONDecodeError:
            return f"Error: invalid JSON arguments: {args_raw[:200]}"
        
        # Emit tool execution event
        if self.bus:
            await self.bus.emit_nowait("cortex.tool.executing", {
                "turn_id": self._turn_id,
                "tool": name,
                "iteration": self._iteration,
            }, source="cortex")
        
        # Log tool call with args summary
        args_summary = str(arguments)[:120]
        logger.info(
            f"[{self._turn_id}] Tool call: {name}({args_summary})"
        )
        
        # Execute via SINEW
        result = await self.tools.execute(name, arguments)
        
        logger.info(
            f"[{self._turn_id}] Tool {name}: "
            f"{len(result)} chars output"
        )
        
        return result
