# Singularity — Social Presence Manager
# Sustained typing indicators + Discord activity states.
#
# Shows what Singularity is actually doing during a turn:
# thinking, reading, writing, searching, executing, etc.
#
# Ported and adapted from Mach6 presence.py (AVA/Aria architecture)
# by Aria Shakil — 2026-03-06

import asyncio
import logging
from typing import Callable, Optional, Any

logger = logging.getLogger("singularity.nerve.presence")

# ── Activity Definitions ────────────────────────────────────────────────────

TOOL_ACTIVITY: dict[str, str] = {
    "read":            "📖 Reading files...",
    "write":           "✍️ Writing...",
    "edit":            "✏️ Editing...",
    "exec":            "⚡ Executing...",
    "process_start":   "🚀 Launching process...",
    "process_poll":    "📊 Checking process...",
    "process_kill":    "🛑 Stopping process...",
    "process_list":    "📋 Listing processes...",
    "web_fetch":       "🌐 Browsing the web...",
    "memory_search":   "🧠 Searching memory...",
    "comb_recall":     "🧠 Recalling...",
    "comb_stage":      "💾 Staging memory...",
    "message":         "💬 Sending message...",
    "tts":             "🔊 Generating speech...",
    "spawn":           "🧬 Spawning sub-agent...",
    "subagent_status": "🔍 Checking sub-agent...",
    "image":           "👁️ Analyzing image...",
}

THINKING_ACTIVITY = "🤔 Thinking..."
IDLE_ACTIVITY = "⚡ Singularity Online"

# Discord refresh every 8s (indicator lasts ~10s)
DISCORD_REFRESH_MS = 8.0
# Safety: max typing duration — 5 minutes
MAX_TYPING_SECONDS = 5 * 60


# ── Presence Manager ────────────────────────────────────────────────────────

class PresenceManager:
    """
    Manages sustained typing indicators and Discord activity states
    for Singularity. Mirrors the Mach6 presenceManager pattern.
    """

    def __init__(self) -> None:
        self._typing_tasks: dict[str, asyncio.Task] = {}  # key → task
        self._typing_fn: Optional[Callable] = None         # adapter.typing()
        self._discord_client: Optional[Any] = None          # discord.py Client
        self._current_activity: str = IDLE_ACTIVITY
        self._activity_task: Optional[asyncio.Task] = None
        self._active_chat_id: Optional[str] = None

    def register_adapter(self, typing_fn: Callable) -> None:
        """Register the Discord adapter's typing function."""
        self._typing_fn = typing_fn

    def register_discord_client(self, client: Any) -> None:
        """Register the discord.py Client for rich presence updates."""
        self._discord_client = client

    def start_typing(self, chat_id: str) -> None:
        """Start sustained typing for a chat. Refreshes every ~8s."""
        key = chat_id
        if key in self._typing_tasks and not self._typing_tasks[key].done():
            return  # already running

        self._active_chat_id = chat_id
        self._set_activity(THINKING_ACTIVITY)

        async def _sustain():
            try:
                start = asyncio.get_event_loop().time()
                while True:
                    if self._typing_fn:
                        try:
                            await self._typing_fn(chat_id)
                        except Exception as e:
                            logger.debug(f"Suppressed: {e}")
                    elapsed = asyncio.get_event_loop().time() - start
                    if elapsed > MAX_TYPING_SECONDS:
                        logger.warning("[presence] Typing timeout for %s", chat_id)
                        break
                    await asyncio.sleep(DISCORD_REFRESH_MS)
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(_sustain())
        self._typing_tasks[key] = task

    def stop_typing(self, chat_id: str) -> None:
        """Stop typing indicator for a chat."""
        key = chat_id
        task = self._typing_tasks.pop(key, None)
        if task and not task.done():
            task.cancel()

        if not self._typing_tasks:
            self._set_activity(IDLE_ACTIVITY)
            self._active_chat_id = None

    def tool_start(self, tool_name: str) -> None:
        """Called when a tool starts — update Discord activity."""
        activity = TOOL_ACTIVITY.get(tool_name, THINKING_ACTIVITY)
        self._set_activity(activity)

        # Cancel any pending "back to thinking" timer
        if self._activity_task and not self._activity_task.done():
            self._activity_task.cancel()
            self._activity_task = None

    def tool_end(self, _tool_name: str) -> None:
        """Called when a tool ends — return to thinking after brief delay."""
        if self._activity_task and not self._activity_task.done():
            self._activity_task.cancel()

        async def _back_to_thinking():
            await asyncio.sleep(0.3)
            if self._typing_tasks:  # still in active turn
                self._set_activity(THINKING_ACTIVITY)

        self._activity_task = asyncio.create_task(_back_to_thinking())

    def llm_streaming(self) -> None:
        """Called while the LLM is streaming — show thinking."""
        if self._activity_task and not self._activity_task.done():
            self._activity_task.cancel()
        self._set_activity(THINKING_ACTIVITY)

    def stop_all(self) -> None:
        """Stop everything — called on shutdown."""
        for task in self._typing_tasks.values():
            if not task.done():
                task.cancel()
        self._typing_tasks.clear()

        if self._activity_task and not self._activity_task.done():
            self._activity_task.cancel()
        self._activity_task = None

        self._set_activity(IDLE_ACTIVITY)
        self._active_chat_id = None

    def stats(self) -> dict:
        return {
            "active_chats": list(self._typing_tasks.keys()),
            "current_activity": self._current_activity,
            "discord_client": self._discord_client is not None,
        }

    # ── Internal ──────────────────────────────────────────────────────

    def _set_activity(self, activity: str) -> None:
        if self._current_activity == activity:
            return
        self._current_activity = activity

        if self._discord_client:
            try:
                import discord as discord_lib
                self._discord_client.loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(
                        self._discord_client.change_presence(
                            activity=discord_lib.CustomActivity(name=activity)
                        )
                    )
                )
            except Exception:
                # Try the async way directly
                try:
                    import discord as discord_lib
                    asyncio.ensure_future(
                        self._discord_client.change_presence(
                            activity=discord_lib.CustomActivity(name=activity)
                        )
                    )
                except Exception as e:
                    logger.debug("[presence] activity update suppressed: %s", e)


# Singleton
presence_manager = PresenceManager()
