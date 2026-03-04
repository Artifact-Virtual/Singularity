"""
VOICE — LLM Provider Abstraction
====================================

Abstract base class for LLM providers.
Every provider implements the same interface: chat() → stream of tokens.

Design:
    - Provider is protocol, not inheritance hierarchy
    - Each provider owns its own HTTP client lifecycle
    - Streaming is the default — non-streaming is just collected stream
    - Token counting is provider-specific (different tokenizers)
    - Health checks are built in (not bolted on)
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional, Any

logger = logging.getLogger("singularity.voice.provider")


@dataclass
class ChatMessage:
    """A single message in a conversation."""
    role: str  # "system", "user", "assistant", "tool"
    content: str = ""
    name: Optional[str] = None          # tool name (when role=tool)
    tool_call_id: Optional[str] = None  # for tool results
    tool_calls: Optional[list[dict]] = None  # assistant's tool calls
    
    def to_dict(self) -> dict:
        d = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            # Ensure arguments are JSON strings (OpenAI API requirement)
            serialized = []
            for tc in self.tool_calls:
                tc_copy = {**tc}
                fn = tc_copy.get("function", {})
                if fn and not isinstance(fn.get("arguments"), str):
                    tc_copy = {**tc_copy, "function": {**fn, "arguments": json.dumps(fn["arguments"])}}
                serialized.append(tc_copy)
            d["tool_calls"] = serialized
        return d


@dataclass
class ChatResponse:
    """Response from a provider."""
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str = "stop"  # "stop", "tool_calls", "length", "error"
    usage: dict = field(default_factory=dict)  # input_tokens, output_tokens
    model: str = ""
    latency_ms: float = 0.0
    provider_name: str = ""
    
    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0
    
    @property
    def total_tokens(self) -> int:
        return self.usage.get("input_tokens", 0) + self.usage.get("output_tokens", 0)


@dataclass
class StreamChunk:
    """A chunk from a streaming response."""
    delta: str = ""               # text delta
    tool_call_delta: Optional[dict] = None  # partial tool call
    finish_reason: Optional[str] = None
    usage: Optional[dict] = None  # final chunk may include usage


class ChatProvider(ABC):
    """Abstract LLM provider.
    
    Every provider must implement:
    - chat_stream() → async iterator of StreamChunks
    - health() → bool
    
    chat() is provided as a convenience (collects stream).
    """
    
    def __init__(self, name: str, model: str, **kwargs):
        self.name = name
        self.model = model
        self.available = True
        self._consecutive_failures = 0
        self._last_success: float = 0
        self._last_failure: float = 0
    
    @abstractmethod
    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a chat completion. Yields StreamChunks."""
        ...
    
    async def chat(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        **kwargs,
    ) -> ChatResponse:
        """Non-streaming chat. Collects stream into a single response."""
        t0 = time.perf_counter()
        
        content_parts = []
        tool_calls = []
        finish_reason = "stop"
        usage = {}
        
        # Accumulators for streamed tool calls
        tc_accum: dict[int, dict] = {}  # index → {id, type, function: {name, arguments_parts}}
        
        async for chunk in self.chat_stream(
            messages, tools=tools, temperature=temperature,
            max_tokens=max_tokens, **kwargs
        ):
            if chunk.delta:
                content_parts.append(chunk.delta)
            
            if chunk.tool_call_delta:
                tcd = chunk.tool_call_delta
                idx = tcd.get("index", 0)
                if idx not in tc_accum:
                    tc_accum[idx] = {
                        "id": tcd.get("id", ""),
                        "type": "function",
                        "function": {"name": "", "arguments_parts": []},
                    }
                if tcd.get("id"):
                    tc_accum[idx]["id"] = tcd["id"]
                fn = tcd.get("function", {})
                if fn.get("name"):
                    tc_accum[idx]["function"]["name"] = fn["name"]
                if fn.get("arguments"):
                    tc_accum[idx]["function"]["arguments_parts"].append(fn["arguments"])
            
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason
            if chunk.usage:
                usage = chunk.usage
        
        if tc_accum:
            tool_calls = []
            for i in sorted(tc_accum.keys()):
                tc = tc_accum[i]
                args_str = "".join(tc["function"]["arguments_parts"])
                try:
                    args_parsed = json.loads(args_str) if args_str.strip() else {}
                except json.JSONDecodeError:
                    args_parsed = args_str  # fallback to string
                tool_calls.append({
                    "id": tc["id"],
                    "type": tc["type"],
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": args_parsed,
                    },
                })
            if finish_reason == "stop":
                finish_reason = "tool_calls"
        
        latency = (time.perf_counter() - t0) * 1000
        self._consecutive_failures = 0
        self._last_success = time.time()
        
        final_content = "".join(content_parts)
        logger.info(
            f"chat() result: content={len(final_content)} chars, "
            f"tool_calls={len(tool_calls)}, finish={finish_reason}, "
            f"usage={usage}"
        )
        
        return ChatResponse(
            content=final_content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            model=self.model,
            latency_ms=latency,
            provider_name=self.name,
        )
    
    @abstractmethod
    async def health(self) -> bool:
        """Check if this provider is healthy and reachable."""
        ...
    
    async def initialize(self) -> None:
        """Initialize the provider (create HTTP clients, etc)."""
        pass
    
    async def shutdown(self) -> None:
        """Clean up resources."""
        pass
    
    def record_failure(self, error: Exception) -> None:
        """Record a failure for circuit-breaker logic."""
        self._consecutive_failures += 1
        self._last_failure = time.time()
        if self._consecutive_failures >= 3:
            self.available = False
            logger.warning(
                f"Provider {self.name} marked unavailable after "
                f"{self._consecutive_failures} consecutive failures"
            )
    
    def record_success(self) -> None:
        """Record a success — resets failure counter."""
        self._consecutive_failures = 0
        self._last_success = time.time()
        self.available = True
    
    def __repr__(self) -> str:
        status = "✅" if self.available else "❌"
        return f"<{self.name} model={self.model} {status}>"
