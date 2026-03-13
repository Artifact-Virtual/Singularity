"""
VOICE — HuggingFace Inference Provider
=========================================

OpenAI-compatible provider for HuggingFace Inference API (router).
Supports all models on router.huggingface.co.

Usage:
    provider = HuggingFaceProvider(
        model="Qwen/Qwen3.5-27B",
        api_key="hf_...",
    )
    async for chunk in provider.chat_stream(messages):
        print(chunk.delta)
"""

from __future__ import annotations

import json
import logging
import os
from typing import AsyncIterator, Optional

import aiohttp

from .provider import ChatProvider, ChatMessage, StreamChunk

logger = logging.getLogger("singularity.voice.huggingface")

HF_ROUTER_URL = "https://router.huggingface.co/v1"


class HuggingFaceProvider(ChatProvider):
    """HuggingFace Inference API provider (OpenAI-compatible).
    
    Uses router.huggingface.co which supports 120+ models including
    Qwen3.5, DeepSeek, Llama 4, Gemma, etc.
    """

    def __init__(
        self,
        model: str = "Qwen/Qwen3.5-27B",
        api_key: str = "",
        base_url: str = HF_ROUTER_URL,
        **kwargs,
    ):
        super().__init__(name="huggingface", model=model, **kwargs)
        self._api_key = api_key or os.environ.get("HF_TOKEN_AVA", "") or os.environ.get("HF_TOKEN_ALI", "") or os.environ.get("HF_TOKEN", "")
        self._base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    async def initialize(self) -> None:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=300)
            )

    async def shutdown(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _build_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 16384,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """Stream chat completion from HuggingFace."""
        await self.initialize()

        body: dict = {
            "model": self.model,
            "stream": True,
            "messages": [m.to_dict() for m in messages],
        }
        if max_tokens:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if tools:
            body["tools"] = tools

        endpoint = f"{self._base_url}/chat/completions"

        try:
            async with self._session.post(
                endpoint, json=body, headers=self._build_headers()
            ) as resp:
                if resp.status == 402:
                    # Credits depleted — let chain fall through
                    text = await resp.text()
                    raise RuntimeError(f"HF credits depleted: {text}")

                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"HF API error {resp.status}: {text}")

                buffer = ""
                async for raw_bytes in resp.content.iter_any():
                    buffer += raw_bytes.decode("utf-8", errors="replace")
                    lines = buffer.split("\n")
                    buffer = lines[-1]

                    for line in lines[:-1]:
                        if not line.startswith("data: "):
                            continue
                        data = line[6:].strip()
                        if data == "[DONE]":
                            return

                        try:
                            parsed = json.loads(data)
                        except Exception as e:
                            logger.debug(f"Suppressed: {e}")
                            continue

                        # Usage
                        usage = parsed.get("usage")
                        if usage and usage.get("total_tokens"):
                            yield StreamChunk(
                                usage={
                                    "input_tokens": usage.get("prompt_tokens", 0),
                                    "output_tokens": usage.get("completion_tokens", 0),
                                }
                            )

                        choices = parsed.get("choices")
                        if not choices:
                            continue

                        choice = choices[0]
                        delta = choice.get("delta")
                        if delta:
                            content = delta.get("content")
                            if content:
                                yield StreamChunk(delta=content)

                            tc_list = delta.get("tool_calls")
                            if tc_list:
                                for tc in tc_list:
                                    fn = tc.get("function", {})
                                    yield StreamChunk(tool_call_delta={
                                        "index": tc.get("index", 0),
                                        "id": tc.get("id", ""),
                                        "function": {
                                            "name": fn.get("name", ""),
                                            "arguments": fn.get("arguments", ""),
                                        },
                                    })

                        finish = choice.get("finish_reason")
                        if finish:
                            yield StreamChunk(finish_reason=finish)

            self.record_success()

        except Exception as e:
            self.record_failure(e)
            raise

    async def health(self) -> bool:
        """Check if HF API is reachable."""
        try:
            await self.initialize()
            async with self._session.get(
                f"{self._base_url}/models",
                headers=self._build_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200
        except Exception:
            return False
