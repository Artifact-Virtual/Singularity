"""
CORTEX — Context Assembly
============================

Assembles the context window for each agent turn:
    1. System prompt (persona + tools + rules)
    2. Session history (from MEMORY)
    3. New message

Context window management:
    - Token budget tracking
    - History truncation (oldest first)
    - Compaction trigger (summarize old context)
    - System prompt is never truncated
"""

from __future__ import annotations

import logging
from typing import Optional

from ..voice.provider import ChatMessage

logger = logging.getLogger("singularity.cortex.context")

# Default token budgets (conservative — leaves room for response)
DEFAULT_CONTEXT_BUDGET = 180_000  # Max tokens for context
SYSTEM_PROMPT_BUDGET = 10_000     # Reserved for system prompt
RESPONSE_BUDGET = 8_192           # Reserved for response


class ContextAssembler:
    """Assemble and manage the context window.
    
    Responsibilities:
    - Build system prompt from persona definition
    - Retrieve session history from MEMORY
    - Enforce token budget (truncate if needed)
    - Signal when compaction is needed
    """
    
    def __init__(
        self,
        context_budget: int = DEFAULT_CONTEXT_BUDGET,
        response_budget: int = RESPONSE_BUDGET,
    ):
        self.context_budget = context_budget
        self.response_budget = response_budget
    
    def assemble(
        self,
        system_prompt: str,
        history: list[ChatMessage],
        new_message: Optional[ChatMessage] = None,
        max_history_tokens: Optional[int] = None,
    ) -> list[ChatMessage]:
        """Assemble the full message list for an LLM call.
        
        Args:
            system_prompt: The system prompt text
            history: Previous messages in this session
            new_message: The new incoming message (if any)
            max_history_tokens: Override max tokens for history
        
        Returns:
            List of ChatMessages ready for the LLM
        """
        messages = []
        
        # 1. System prompt (always first, never truncated)
        if system_prompt:
            messages.append(ChatMessage(role="system", content=system_prompt))
        
        # 2. History (may be truncated)
        if max_history_tokens:
            available_budget = max_history_tokens
        else:
            # Reserve space for system prompt (estimate) and response
            sys_tokens = len(system_prompt) // 4 if system_prompt else 0
            available_budget = max(
                0,
                self.context_budget - sys_tokens - self.response_budget
            )
        
        truncated_history = self._fit_history(history, available_budget)
        messages.extend(truncated_history)
        
        # 3. New message
        if new_message:
            messages.append(new_message)
        
        return messages
    
    def _fit_history(
        self,
        history: list[ChatMessage],
        budget_tokens: int,
    ) -> list[ChatMessage]:
        """Fit history into the token budget.
        
        Strategy: Keep the most recent messages. Drop oldest first.
        Estimate: ~4 chars per token (rough but fast).
        
        TODO: Use proper tokenizer when GLADIUS provides one.
        """
        if not history:
            return []
        
        # Estimate tokens (rough: 4 chars ≈ 1 token)
        budget_chars = budget_tokens * 4
        
        # Calculate total size
        total_chars = sum(len(m.content or "") for m in history)
        
        if total_chars <= budget_chars:
            return list(history)  # Everything fits
        
        # Drop oldest messages until we fit
        result = []
        running_chars = 0
        
        # Walk backwards (newest first)
        for msg in reversed(history):
            msg_chars = len(msg.content or "")
            if running_chars + msg_chars > budget_chars:
                break
            result.insert(0, msg)
            running_chars += msg_chars
        
        if len(result) < len(history):
            dropped = len(history) - len(result)
            logger.info(
                f"Context truncation: dropped {dropped} oldest messages "
                f"({total_chars - running_chars} chars)"
            )
            
            # Prepend a note about truncation
            if result and result[0].role != "system":
                note = ChatMessage(
                    role="system",
                    content=f"[Context note: {dropped} earlier messages were truncated to fit the context window.]"
                )
                result.insert(0, note)
        
        return result
    
    def needs_compaction(
        self,
        history: list[ChatMessage],
        threshold: float = 0.8,
    ) -> bool:
        """Check if history should be compacted.
        
        Returns True if history uses more than `threshold` of the budget.
        """
        if not history:
            return False
        
        budget_chars = self.context_budget * 4  # rough token-to-char
        total_chars = sum(len(m.content or "") for m in history)
        
        return total_chars > (budget_chars * threshold)


def build_system_prompt(
    persona_name: str,
    persona_prompt: str = "",
    tools_description: str = "",
    rules: str = "",
    comb_context: str = "",
) -> str:
    """Build a complete system prompt from components.
    
    This is where Aria's personality gets injected.
    """
    parts = []
    
    if persona_prompt:
        parts.append(persona_prompt)
    else:
        parts.append(f"You are {persona_name}.")
    
    if rules:
        parts.append(f"\n## Rules\n{rules}")
    
    if tools_description:
        parts.append(f"\n## Available Tools\n{tools_description}")
    
    if comb_context:
        parts.append(f"\n## Operational Memory (COMB)\n{comb_context}")
    
    return "\n\n".join(parts)
