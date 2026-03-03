"""
VOICE — Provider Chain
========================

Fallback chain: try primary → fallbacks → local → error.

The chain is the voice's immune system. If the primary provider
goes down, the chain automatically falls through to the next
available provider. No human intervention needed.

Events emitted:
    voice.provider.switched — when fallback occurs
    voice.provider.exhausted — when all providers fail
    voice.chat.complete — after successful completion
"""

from __future__ import annotations

import logging
import time
from typing import AsyncIterator, Optional, Any

from .provider import ChatProvider, ChatMessage, ChatResponse, StreamChunk

logger = logging.getLogger("singularity.voice.chain")


class ProviderChain:
    """Ordered chain of LLM providers with automatic fallback.
    
    Usage:
        chain = ProviderChain([copilot, ollama])
        response = await chain.chat(messages, tools=tools)
    
    The chain tries providers in order. If one fails, it moves
    to the next. Circuit-breaker logic (in ChatProvider) marks
    providers as unavailable after 3 consecutive failures.
    """
    
    def __init__(self, providers: list[ChatProvider], bus: Any = None):
        self.providers = providers
        self.bus = bus
        self._active_provider: Optional[ChatProvider] = None
    
    @property
    def active(self) -> Optional[ChatProvider]:
        """The currently active (last successful) provider."""
        return self._active_provider
    
    @property
    def available_providers(self) -> list[ChatProvider]:
        """Providers currently marked as available."""
        return [p for p in self.providers if p.available]
    
    async def initialize(self) -> None:
        """Initialize all providers."""
        for provider in self.providers:
            try:
                await provider.initialize()
                logger.info(f"Initialized provider: {provider}")
            except Exception as e:
                logger.warning(f"Failed to initialize {provider.name}: {e}")
    
    async def shutdown(self) -> None:
        """Shutdown all providers."""
        for provider in self.providers:
            try:
                await provider.shutdown()
            except Exception:
                pass
    
    async def chat(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        **kwargs,
    ) -> ChatResponse:
        """Chat with automatic fallback through the provider chain.
        
        Tries each available provider in order. If all fail,
        raises the last exception.
        """
        last_error: Optional[Exception] = None
        
        for provider in self.providers:
            if not provider.available:
                logger.debug(f"Skipping unavailable provider: {provider.name}")
                continue
            
            try:
                t0 = time.perf_counter()
                response = await provider.chat(
                    messages, tools=tools, temperature=temperature,
                    max_tokens=max_tokens, **kwargs
                )
                latency = (time.perf_counter() - t0) * 1000
                
                # Track active provider + emit event if it changed
                if self._active_provider != provider:
                    old_name = self._active_provider.name if self._active_provider else "none"
                    self._active_provider = provider
                    
                    if self.bus and old_name != "none":
                        await self.bus.emit_nowait("voice.provider.switched", {
                            "from": old_name,
                            "to": provider.name,
                            "reason": "fallback",
                        }, source="voice")
                    
                    logger.info(f"Active provider: {provider.name}")
                else:
                    self._active_provider = provider
                
                # Emit completion event
                if self.bus:
                    await self.bus.emit_nowait("voice.chat.complete", {
                        "provider": provider.name,
                        "model": response.model,
                        "latency_ms": round(latency),
                        "input_tokens": response.usage.get("input_tokens", 0),
                        "output_tokens": response.usage.get("output_tokens", 0),
                        "tool_calls": len(response.tool_calls),
                        "finish_reason": response.finish_reason,
                    }, source="voice")
                
                return response
                
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Provider {provider.name} failed: {e}. "
                    f"Trying next..."
                )
                continue
        
        # All providers exhausted
        if self.bus:
            await self.bus.emit_nowait("voice.provider.exhausted", {
                "providers_tried": [p.name for p in self.providers],
                "error": str(last_error),
            }, source="voice")
        
        raise RuntimeError(
            f"All providers exhausted. Last error: {last_error}"
        )
    
    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """Stream with fallback. Only falls back before first chunk."""
        last_error: Optional[Exception] = None
        
        for provider in self.providers:
            if not provider.available:
                continue
            
            try:
                async for chunk in provider.chat_stream(
                    messages, tools=tools, temperature=temperature,
                    max_tokens=max_tokens, **kwargs
                ):
                    yield chunk
                
                self._active_provider = provider
                return
                
            except Exception as e:
                last_error = e
                logger.warning(f"Stream provider {provider.name} failed: {e}")
                continue
        
        raise RuntimeError(f"All stream providers exhausted. Last: {last_error}")
    
    async def health_check(self) -> dict[str, bool]:
        """Check health of all providers."""
        results = {}
        for provider in self.providers:
            try:
                results[provider.name] = await provider.health()
            except Exception:
                results[provider.name] = False
        return results
    
    def status(self) -> dict:
        """Get chain status summary."""
        return {
            "active": self._active_provider.name if self._active_provider else None,
            "providers": [
                {
                    "name": p.name,
                    "model": p.model,
                    "available": p.available,
                    "failures": p._consecutive_failures,
                }
                for p in self.providers
            ],
        }
