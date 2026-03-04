"""
NERVE — Guild Auto-Deployer
================================

When the bot joins a Discord server, Singularity automatically
deploys the entire enterprise infrastructure:

    1. Creates a category: "SINGULARITY"
    2. Creates C-Suite channels (one per exec role)
    3. Creates operational channels (#bridge, #dispatch)
    4. Locks channels to bot-only visibility (optional)
    5. Persists channel map to config
    6. Emits bus events for each deployment step

Zero manual setup. User pastes a token, clicks an invite link,
and their enterprise materializes.

Ali (Day 19):
    "1 bot should be enough. It should automatically create c suite
     execs as channels like how we had them."
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("singularity.nerve.deployer")

try:
    import discord
    from discord import (
        Guild,
        TextChannel,
        CategoryChannel,
        PermissionOverwrite,
        Permissions,
    )
    HAS_DISCORD = True
except ImportError:
    HAS_DISCORD = False


# ══════════════════════════════════════════════════════════════
# DEPLOYMENT BLUEPRINT
# ══════════════════════════════════════════════════════════════

# Standard channel layout — what gets created on guild join
CATEGORY_NAME = "SINGULARITY"

# Operational channels (always created)
OPS_CHANNELS = [
    {
        "name": "bridge",
        "topic": "🌉 System heartbeats, status updates, health checks",
        "emoji": "🌉",
    },
    {
        "name": "dispatch",
        "topic": "📡 Task dispatch and executive coordination",
        "emoji": "📡",
    },
]

# Executive channels — created dynamically from the role registry
# Each exec gets their own channel: #cto, #coo, #cfo, #ciso, etc.
EXEC_CHANNEL_TOPIC_TEMPLATE = "{emoji} {title} — {domain}"


# ══════════════════════════════════════════════════════════════
# INVITE LINK GENERATOR
# ══════════════════════════════════════════════════════════════

# Permissions needed for full Singularity deployment
REQUIRED_PERMISSIONS = discord.Permissions(
    # Channel management
    manage_channels=True,
    manage_roles=True,
    manage_webhooks=True,
    view_channel=True,

    # Messaging
    send_messages=True,
    send_messages_in_threads=True,
    embed_links=True,
    attach_files=True,
    read_message_history=True,
    add_reactions=True,
    use_external_emojis=True,

    # Threads
    create_public_threads=True,
    create_private_threads=True,
    manage_threads=True,

    # Voice (future)
    connect=True,
    speak=True,

    # Admin-lite
    manage_messages=True,
    mention_everyone=False,
) if HAS_DISCORD else None


def generate_invite_link(bot_id: str) -> str:
    """
    Generate a Discord OAuth2 invite link with the exact permissions
    Singularity needs.

    Args:
        bot_id: The bot's application/client ID

    Returns:
        The full invite URL
    """
    if not HAS_DISCORD:
        # Fallback: manual permission int
        perms = 397553090640
    else:
        perms = REQUIRED_PERMISSIONS.value

    return (
        f"https://discord.com/oauth2/authorize"
        f"?client_id={bot_id}"
        f"&permissions={perms}"
        f"&scope=bot%20applications.commands"
    )


# ══════════════════════════════════════════════════════════════
# INTENT INSTRUCTIONS
# ══════════════════════════════════════════════════════════════

INTENT_INSTRUCTIONS = """
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  Discord Bot — Required Privileged Intents                 ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

  Go to: https://discord.com/developers/applications
  Select your bot → "Bot" tab → Privileged Gateway Intents

  Enable ALL THREE:
    ✅ PRESENCE INTENT
    ✅ SERVER MEMBERS INTENT
    ✅ MESSAGE CONTENT INTENT

  Without these, Singularity cannot:
  - Read messages (can't respond to commands)
  - Track member presence (can't detect who's online)
  - Manage roles (can't enforce channel permissions)

  Save changes before proceeding.
"""


# ══════════════════════════════════════════════════════════════
# DEPLOYMENT STATE
# ══════════════════════════════════════════════════════════════

@dataclass
class DeploymentResult:
    """Result of a guild deployment."""
    guild_id: str
    guild_name: str
    success: bool = False
    category_id: Optional[str] = None
    channels: dict[str, str] = field(default_factory=dict)  # name → channel_id
    webhooks: dict[str, str] = field(default_factory=dict)   # name → webhook_url
    errors: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "guild_id": self.guild_id,
            "guild_name": self.guild_name,
            "success": self.success,
            "category_id": self.category_id,
            "channels": self.channels,
            "webhooks": self.webhooks,
            "errors": self.errors,
            "timestamp": self.timestamp,
        }

    def save(self, path: Path) -> None:
        """Persist deployment result."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path) -> "DeploymentResult":
        d = json.loads(path.read_text())
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ══════════════════════════════════════════════════════════════
# DEPLOYER — The Auto-Deployment Engine
# ══════════════════════════════════════════════════════════════

class GuildDeployer:
    """
    Automatically deploys Singularity infrastructure into a Discord guild.

    On guild join:
        1. Create SINGULARITY category
        2. Create ops channels (#bridge, #dispatch)
        3. Create exec channels (#cto, #coo, etc.)
        4. Set permissions (bot can see, @everyone cannot — optional)
        5. Persist channel map
        6. Emit deployment events

    Usage:
        deployer = GuildDeployer(
            exec_roles=[("cto", "🔧", "Chief Technology Officer", "Engineering..."), ...],
            private=True,
        )
        result = await deployer.deploy(guild, bot_member)
    """

    def __init__(
        self,
        exec_roles: list[tuple[str, str, str, str]] = None,
        private: bool = True,
        event_callback: Optional[callable] = None,
        sg_dir: Optional[Path] = None,
    ):
        """
        Args:
            exec_roles: List of (role_id, emoji, title, domain) tuples
            private: If True, channels are hidden from @everyone
            event_callback: async callback(event_name, data) for bus events
            sg_dir: .singularity directory for persistence
        """
        self.exec_roles = exec_roles or []
        self.private = private
        self._event_cb = event_callback
        self._sg_dir = sg_dir
        self._deployments: dict[str, DeploymentResult] = {}

    async def _emit(self, event: str, data: dict) -> None:
        """Emit a deployment event."""
        logger.info(f"⚡ {event}: {data.get('name', data.get('channel', ''))}")
        if self._event_cb:
            try:
                await self._event_cb(event, data)
            except Exception as e:
                logger.warning(f"Event callback error: {e}")

    async def deploy(self, guild: Guild, bot_member=None) -> DeploymentResult:
        """
        Deploy full Singularity infrastructure into a guild.

        Args:
            guild: The Discord guild to deploy into
            bot_member: The bot's Member object (for permissions)

        Returns:
            DeploymentResult with all created channel IDs
        """
        result = DeploymentResult(
            guild_id=str(guild.id),
            guild_name=guild.name,
        )

        await self._emit("deploy.start", {
            "guild_id": str(guild.id),
            "name": guild.name,
            "exec_count": len(self.exec_roles),
        })

        try:
            # ── Step 1: Check for existing deployment ──
            existing_category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
            if existing_category:
                logger.info(f"Category '{CATEGORY_NAME}' already exists in {guild.name}")
                await self._emit("deploy.existing", {
                    "guild_id": str(guild.id),
                    "category_id": str(existing_category.id),
                })
                # Use existing category — don't duplicate
                category = existing_category
            else:
                # ── Step 2: Create category ──
                category = await self._create_category(guild)

            result.category_id = str(category.id)

            # ── Step 3: Create ops channels ──
            for ch_def in OPS_CHANNELS:
                channel_id = await self._create_channel(
                    guild, category, ch_def["name"], ch_def["topic"]
                )
                if channel_id:
                    result.channels[ch_def["name"]] = channel_id

            # ── Step 4: Create exec channels ──
            for role_id, emoji, title, domain in self.exec_roles:
                topic = EXEC_CHANNEL_TOPIC_TEMPLATE.format(
                    emoji=emoji, title=title, domain=domain[:80]
                )
                channel_id = await self._create_channel(
                    guild, category, role_id, topic
                )
                if channel_id:
                    result.channels[role_id] = channel_id

            # ── Step 5: Create webhooks for all channels ──
            for ch_name, ch_id in result.channels.items():
                webhook_url = await self._create_webhook(guild, ch_name, ch_id)
                if webhook_url:
                    result.webhooks[ch_name] = webhook_url

            # ── Step 6: Send welcome message to #bridge ──
            bridge_id = result.channels.get("bridge")
            if bridge_id:
                await self._send_welcome(guild, bridge_id, result)

            result.success = True

        except discord.Forbidden as e:
            err = f"Missing permissions: {e}"
            result.errors.append(err)
            logger.error(f"Deploy failed in {guild.name}: {err}")
            await self._emit("deploy.error", {"guild_id": str(guild.id), "error": err})

        except Exception as e:
            err = f"Deployment error: {e}"
            result.errors.append(err)
            logger.error(f"Deploy failed in {guild.name}: {err}", exc_info=True)
            await self._emit("deploy.error", {"guild_id": str(guild.id), "error": err})

        # ── Step 7: Persist ──
        self._deployments[str(guild.id)] = result
        if self._sg_dir:
            deploy_dir = self._sg_dir / "deployments"
            result.save(deploy_dir / f"{guild.id}.json")

        await self._emit("deploy.complete", {
            "guild_id": str(guild.id),
            "success": result.success,
            "channels_created": len(result.channels),
            "errors": result.errors,
        })

        return result

    async def _create_category(self, guild: Guild) -> CategoryChannel:
        """Create the SINGULARITY category with proper permissions."""
        overwrites = {}

        if self.private:
            # @everyone can't see, bot can see everything
            overwrites[guild.default_role] = PermissionOverwrite(
                view_channel=False,
            )
            # Bot sees everything
            if guild.me:
                overwrites[guild.me] = PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_channels=True,
                    manage_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    embed_links=True,
                )

        category = await guild.create_category(
            name=CATEGORY_NAME,
            overwrites=overwrites,
            reason="Singularity [AE] — Autonomous Enterprise deployment",
        )

        await self._emit("deploy.category", {
            "guild_id": str(guild.id),
            "category_id": str(category.id),
            "name": CATEGORY_NAME,
            "private": self.private,
        })

        return category

    async def _create_channel(
        self,
        guild: Guild,
        category: CategoryChannel,
        name: str,
        topic: str,
    ) -> Optional[str]:
        """Create a text channel under the category. Returns channel ID or None."""
        # Check if channel already exists in category
        existing = discord.utils.get(category.text_channels, name=name)
        if existing:
            logger.info(f"Channel #{name} already exists, skipping")
            await self._emit("deploy.channel.exists", {
                "guild_id": str(guild.id),
                "channel": name,
                "channel_id": str(existing.id),
            })
            return str(existing.id)

        try:
            channel = await guild.create_text_channel(
                name=name,
                category=category,
                topic=topic,
                reason=f"Singularity [AE] — {name} channel",
            )

            await self._emit("deploy.channel", {
                "guild_id": str(guild.id),
                "channel": name,
                "channel_id": str(channel.id),
                "topic": topic,
            })

            # Brief pause to avoid rate limits
            await asyncio.sleep(0.5)

            return str(channel.id)

        except Exception as e:
            logger.error(f"Failed to create #{name}: {e}")
            return None

    async def _create_webhook(
        self,
        guild: Guild,
        channel_name: str,
        channel_id: str,
    ) -> Optional[str]:
        """Create a webhook on a channel. Returns webhook URL or None.
        
        Reuses existing Singularity webhooks if found (idempotent).
        """
        webhook_name = f"Singularity — {channel_name}"
        try:
            channel = guild.get_channel(int(channel_id))
            if not channel:
                logger.warning(f"Channel {channel_id} not found for webhook creation")
                return None

            # Check for existing webhook (idempotent — don't duplicate)
            existing_webhooks = await channel.webhooks()
            for wh in existing_webhooks:
                if wh.name == webhook_name:
                    logger.info(f"Webhook already exists on #{channel_name}, reusing")
                    await self._emit("deploy.webhook.exists", {
                        "guild_id": str(guild.id),
                        "channel": channel_name,
                        "webhook_id": str(wh.id),
                    })
                    return wh.url

            # Create new webhook
            webhook = await channel.create_webhook(
                name=webhook_name,
                reason=f"Singularity [AE] — dispatch webhook for #{channel_name}",
            )

            await self._emit("deploy.webhook", {
                "guild_id": str(guild.id),
                "channel": channel_name,
                "webhook_id": str(webhook.id),
            })

            logger.info(f"Created webhook on #{channel_name}: {webhook.id}")

            # Brief pause to avoid rate limits
            await asyncio.sleep(0.3)

            return webhook.url

        except discord.Forbidden:
            logger.error(f"Missing Manage Webhooks permission for #{channel_name}")
            return None
        except Exception as e:
            logger.error(f"Failed to create webhook on #{channel_name}: {e}")
            return None

    async def _send_welcome(
        self,
        guild: Guild,
        bridge_channel_id: str,
        result: DeploymentResult,
    ) -> None:
        """Send a welcome message to #bridge after deployment."""
        try:
            channel = guild.get_channel(int(bridge_channel_id))
            if not channel:
                return

            exec_list = "\n".join(
                f"  • <#{result.channels[rid]}> — {title}"
                for rid, emoji, title, domain in self.exec_roles
                if rid in result.channels
            )

            ops_list = "\n".join(
                f"  • <#{result.channels[ch['name']]}> — {ch['topic']}"
                for ch in OPS_CHANNELS
                if ch["name"] in result.channels
            )

            welcome = (
                "```\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  SINGULARITY [AE] — All Systems Go              ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
                "```\n"
                f"Deployed to **{guild.name}** ⚡\n\n"
                f"**Operations:**\n{ops_list}\n\n"
                f"**Executive Team:**\n{exec_list}\n\n"
                "All seats taken. All channels live. Ready for dispatch."
            )

            await channel.send(welcome)

        except Exception as e:
            logger.warning(f"Failed to send welcome: {e}")

    def get_deployment(self, guild_id: str) -> Optional[DeploymentResult]:
        """Get deployment result for a guild."""
        return self._deployments.get(guild_id)

    def get_channel_map(self, guild_id: str) -> dict[str, str]:
        """Get the channel name → ID map for a guild."""
        result = self._deployments.get(guild_id)
        return result.channels if result else {}


# ══════════════════════════════════════════════════════════════
# BOT ID VALIDATOR
# ══════════════════════════════════════════════════════════════

def validate_bot_id(bot_id: str) -> Optional[str]:
    """Validate a Discord bot/application ID. Returns error or None."""
    if not bot_id:
        return "Bot ID is required"
    if not bot_id.isdigit():
        return "Bot ID must be numeric (it's a Discord snowflake)"
    if len(bot_id) < 17 or len(bot_id) > 20:
        return "Bot ID should be 17-20 digits"
    return None


def validate_bot_token(token: str) -> Optional[str]:
    """Validate a Discord bot token format. Returns error or None."""
    if not token:
        return "Bot token is required"
    # Discord bot tokens have 3 parts separated by dots
    parts = token.split(".")
    if len(parts) != 3:
        return "Invalid token format (expected 3 dot-separated parts)"
    return None
