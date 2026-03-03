"""CORTEX — Brain subsystem (engine + agent loop + context assembly + blink)."""

from .agent import AgentLoop, AgentConfig, TurnResult
from .blink import BlinkController, BlinkConfig, BlinkState, BlinkPhase
from .context import ContextAssembler, build_system_prompt
from .engine import CortexEngine, CortexConfig

__all__ = [
    "CortexEngine", "CortexConfig",
    "AgentLoop", "AgentConfig", "TurnResult",
    "BlinkController", "BlinkConfig", "BlinkState", "BlinkPhase",
    "ContextAssembler", "build_system_prompt",
]
