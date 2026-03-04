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
    
    @staticmethod
    def _estimate_message_chars(msg: ChatMessage) -> int:
        """Estimate the character cost of a message, including tool_calls metadata."""
        chars = len(msg.content or "")
        if msg.tool_calls:
            # tool_calls is a list of dicts — estimate their JSON size
            import json
            try:
                chars += len(json.dumps(msg.tool_calls))
            except (TypeError, ValueError):
                chars += 200 * len(msg.tool_calls)  # fallback estimate
        if msg.tool_call_id:
            chars += len(msg.tool_call_id) + 20  # overhead for the field
        if msg.name:
            chars += len(msg.name) + 10
        return chars
    
    def _fit_history(
        self,
        history: list[ChatMessage],
        budget_tokens: int,
    ) -> list[ChatMessage]:
        """Fit history into the token budget.
        
        Strategy: Keep the most recent messages. Drop oldest first.
        Estimate: ~4 chars per token (rough but fast).
        Preserves tool call integrity: assistant tool_calls messages and
        their corresponding tool result messages are kept/dropped as a unit.
        
        TODO: Use proper tokenizer when GLADIUS provides one.
        """
        if not history:
            return []
        
        # Estimate tokens (rough: 4 chars ≈ 1 token)
        budget_chars = budget_tokens * 4
        
        # Calculate total size (including tool_calls metadata)
        total_chars = sum(self._estimate_message_chars(m) for m in history)
        
        if total_chars <= budget_chars:
            return list(history)  # Everything fits
        
        # Group messages into "units" that must stay together:
        # An assistant message with tool_calls + all following tool results = one unit
        units: list[list[int]] = []  # each unit is a list of indices
        i = 0
        while i < len(history):
            msg = history[i]
            if msg.role == "assistant" and msg.tool_calls:
                # Start a unit: this assistant msg + all following tool results
                unit = [i]
                j = i + 1
                while j < len(history) and history[j].role == "tool":
                    unit.append(j)
                    j += 1
                units.append(unit)
                i = j
            else:
                units.append([i])
                i += 1
        
        # Walk backwards (newest units first), keeping units that fit
        kept_indices: set[int] = set()
        running_chars = 0
        
        for unit in reversed(units):
            unit_chars = sum(self._estimate_message_chars(history[idx]) for idx in unit)
            if running_chars + unit_chars > budget_chars:
                break
            for idx in unit:
                kept_indices.add(idx)
            running_chars += unit_chars
        
        # Build result preserving original order
        result = [history[i] for i in range(len(history)) if i in kept_indices]
        
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
        total_chars = sum(self._estimate_message_chars(m) for m in history)
        
        return total_chars > (budget_chars * threshold)


def build_system_prompt(
    persona_name: str,
    persona_prompt: str = "",
    tools_description: str = "",
    rules: str = "",
    comb_context: str = "",
    workspace: str = "",
) -> str:
    """Build a complete system prompt from components.
    
    This is where the persona's personality gets injected.
    Includes hard grounding to prevent hallucination and confabulation.
    """
    from datetime import datetime
    
    now = datetime.now()
    parts = []
    
    # ── Grounding header (date, time, platform, workspace) ──
    header = (
        f"Current date: {now.strftime('%A, %B %d, %Y')}\n"
        f"Current time: {now.strftime('%H:%M %Z')}\n"
    )
    if workspace:
        header += f"Workspace: {workspace}\n"
    header += "Platform: Discord (Singularity runtime)\n"
    parts.append(header)
    
    # ── Identity (from loaded files or fallback) ──
    if persona_prompt:
        parts.append(persona_prompt)
    else:
        parts.append(f"You are {persona_name}.")
    
    # ── Cognitive Rails (anti-hallucination, anti-confabulation) ──
    cognitive_rails = (
        "## Cognitive Rules (MANDATORY — never violate)\n"
        "1. **Never fabricate information.** If you don't know something, say \"I don't know\" or \"I'm not sure\". Do not guess and present guesses as facts.\n"
        "2. **Verify before claiming.** Use tools to check files, run commands, search memory BEFORE stating what exists or doesn't exist. Do not assume.\n"
        "3. **Do not flip-flop.** If you stated something, stand by it unless you find concrete evidence you were wrong. If correcting yourself, explain what changed.\n"
        "4. **Do not be presumptuous.** You are not omniscient. You have tools — use them. Don't claim to have done something you haven't.\n"
        "5. **Admit uncertainty.** \"I need to check\" is always better than a confident wrong answer.\n"
        "6. **Be concise.** Action over narration. Results over explanations. Don't pad responses.\n"
        "7. **One truth.** Don't say \"it is\" then \"it isn't\" then \"it is\" — investigate once, report once.\n"
        "8. **Tool-first methodology.** When a question can be answered by reading a file, running a command, or searching — do that before answering. Never guess file contents or system state.\n"
        "9. **Apply changes, don't narrate.** When code needs to be fixed, configs updated, or files modified — USE the write/edit tools to make the change. Do not just describe what should change. Audit → Fix → Confirm. If you identified a problem, fix it in the same turn.\n"
        "10. **Execute, don't ask permission.** You are an autonomous runtime. When a task requires action, take it. Don't ask 'should I do X?' — do X and report the result.\n"
    )
    parts.append(cognitive_rails)
    
    if rules:
        parts.append(f"## Operating Rules\n{rules}")
    
    if tools_description:
        parts.append(f"## Available Tools\n{tools_description}")
    
    if comb_context:
        parts.append(
            f"## Operational Memory (COMB Recall)\n"
            f"The following is your recalled persistent memory from previous sessions. "
            f"This is ground truth about past events.\n\n{comb_context}"
        )
    
    return "\n\n".join(parts)
