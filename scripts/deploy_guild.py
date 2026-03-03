#!/usr/bin/env python3
"""
Deploy Singularity channel infrastructure to a Discord guild.

Uses REST API directly (no gateway) to avoid conflicting with
the running Mach6 bot that holds the gateway session.

Usage:
    python3 scripts/deploy_guild.py <guild_id> [--public]
    python3 scripts/deploy_guild.py all [--public]
"""

import json
import ssl
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# ── Load env ──
ENV_FILE = Path("/home/adam/workspace/enterprise/.env")
BOT_TOKEN = None
for line in ENV_FILE.read_text().splitlines():
    if line.startswith("DISCORD_BOT_TOKEN="):
        BOT_TOKEN = line.split("=", 1)[1].strip().strip("'\"")
        break

if not BOT_TOKEN:
    print("❌ DISCORD_BOT_TOKEN not found in .env")
    sys.exit(1)

API = "https://discord.com/api/v10"
HEADERS = {
    "Authorization": f"Bot {BOT_TOKEN}",
    "Content-Type": "application/json",
    "User-Agent": "Singularity-Deployer/1.0",
}
CTX = ssl.create_default_context()

CATEGORY_NAME = "SINGULARITY"

# C-Suite executive roles
EXEC_ROLES = [
    ("cto", "🔧", "Chief Technology Officer", "Engineering, infrastructure, architecture"),
    ("coo", "⚙️", "Chief Operating Officer", "Operations, workflows, HR, compliance"),
    ("cfo", "💰", "Chief Financial Officer", "Finance, budgets, revenue, reporting"),
    ("ciso", "🛡️", "Chief Information Security Officer", "Security, GRC, risk management"),
]

OPS_CHANNELS = [
    ("bridge", "🌉 System heartbeats, status updates, health checks"),
    ("dispatch", "📡 Task dispatch and executive coordination"),
]


def api_call(method: str, endpoint: str, data: dict = None) -> dict:
    """Make a Discord REST API call."""
    url = f"{API}{endpoint}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=HEADERS, method=method)

    try:
        resp = urllib.request.urlopen(req, context=CTX, timeout=15)
        if resp.status == 204:
            return {"success": True}
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        try:
            error_json = json.loads(error_body)
        except Exception:
            error_json = {"message": error_body}
        return {"error": True, "status": e.code, "detail": error_json}


def deploy_guild(guild_id: str, private: bool = True) -> dict:
    """Deploy Singularity channels to a guild."""

    print(f"\n{'='*60}")
    print(f"  SINGULARITY [AE] — Deploying to {guild_id}")
    print(f"{'='*60}\n")

    # 1. Get guild info
    guild = api_call("GET", f"/guilds/{guild_id}")
    if guild.get("error"):
        print(f"❌ Cannot access guild: {guild}")
        return guild

    guild_name = guild["name"]
    print(f"🏰 Guild: {guild_name} ({guild_id})")

    # 2. Get bot info
    me = api_call("GET", "/users/@me")
    bot_id = me["id"]
    print(f"🤖 Bot: {me['username']}#{me.get('discriminator', '0')} ({bot_id})")

    # 3. Fetch existing channels
    channels = api_call("GET", f"/guilds/{guild_id}/channels")
    if isinstance(channels, dict) and channels.get("error"):
        print(f"❌ Cannot fetch channels: {channels}")
        return channels

    # 4. Check for existing SINGULARITY category
    existing_cat = None
    for ch in channels:
        if ch.get("type") == 4 and ch.get("name") == CATEGORY_NAME:
            existing_cat = ch
            break

    result = {
        "guild_id": guild_id,
        "guild_name": guild_name,
        "channels": {},
        "category_id": None,
        "created": [],
        "existing": [],
        "errors": [],
        "timestamp": time.time(),
    }

    if existing_cat:
        print(f"📂 Category '{CATEGORY_NAME}' already exists (id: {existing_cat['id']})")
        result["category_id"] = existing_cat["id"]
        cat_id = existing_cat["id"]
    else:
        # Create category
        overwrites = []
        if private:
            # Get @everyone role ID (same as guild ID)
            everyone_role_id = guild_id
            overwrites = [
                {
                    "id": everyone_role_id,
                    "type": 0,  # role
                    "deny": str(1 << 10),  # VIEW_CHANNEL
                    "allow": "0",
                },
                {
                    "id": bot_id,
                    "type": 1,  # member
                    "allow": str(
                        (1 << 10) |  # VIEW_CHANNEL
                        (1 << 11) |  # SEND_MESSAGES
                        (1 << 4)  |  # MANAGE_CHANNELS
                        (1 << 13) |  # MANAGE_MESSAGES
                        (1 << 16) |  # READ_MESSAGE_HISTORY
                        (1 << 15) |  # ATTACH_FILES
                        (1 << 14)    # EMBED_LINKS
                    ),
                    "deny": "0",
                },
            ]

        cat_data = api_call("POST", f"/guilds/{guild_id}/channels", {
            "name": CATEGORY_NAME,
            "type": 4,  # GUILD_CATEGORY
            "permission_overwrites": overwrites,
            "reason": "Singularity [AE] — Autonomous Enterprise deployment",
        })

        if cat_data.get("error"):
            print(f"❌ Failed to create category: {cat_data}")
            result["errors"].append(f"Category creation failed: {cat_data}")
            return result

        cat_id = cat_data["id"]
        result["category_id"] = cat_id
        result["created"].append(f"category:{CATEGORY_NAME}")
        print(f"✅ Created category: {CATEGORY_NAME} ({cat_id})")

    # 5. Create ops channels
    for name, topic in OPS_CHANNELS:
        ch_id = _create_or_find_channel(guild_id, cat_id, name, topic, channels, result)
        if ch_id:
            result["channels"][name] = ch_id

    # 6. Create exec channels
    for role_id, emoji, title, domain in EXEC_ROLES:
        topic = f"{emoji} {title} — {domain}"
        ch_id = _create_or_find_channel(guild_id, cat_id, role_id, topic, channels, result)
        if ch_id:
            result["channels"][role_id] = ch_id

    # 7. Send welcome message to #bridge
    bridge_id = result["channels"].get("bridge")
    if bridge_id and f"channel:bridge" in [c for c in result["created"]]:
        _send_welcome(bridge_id, guild_name, result)

    # 8. Add guild owner to channel permissions (so Ali can see them)
    owner_id = guild.get("owner_id")
    if owner_id and private:
        _add_owner_access(cat_id, owner_id, result)

    # 9. Persist
    deploy_dir = Path("/home/adam/workspace/enterprise/singularity/.singularity/deployments")
    deploy_dir.mkdir(parents=True, exist_ok=True)
    result["success"] = len(result["errors"]) == 0
    (deploy_dir / f"{guild_id}.json").write_text(json.dumps(result, indent=2))
    print(f"\n💾 Saved deployment: .singularity/deployments/{guild_id}.json")

    # Summary
    print(f"\n{'─'*60}")
    print(f"  Created: {len(result['created'])} | Existing: {len(result['existing'])} | Errors: {len(result['errors'])}")
    if result["success"]:
        print(f"  ✅ Deployment successful!")
    else:
        print(f"  ❌ Deployment had errors: {result['errors']}")
    print(f"{'─'*60}\n")

    return result


def _create_or_find_channel(guild_id, cat_id, name, topic, existing_channels, result):
    """Create a channel or find existing one under the category."""
    # Check if exists under our category
    for ch in existing_channels:
        if ch.get("name") == name and str(ch.get("parent_id")) == str(cat_id):
            print(f"  📌 #{name} already exists ({ch['id']})")
            result["existing"].append(f"channel:{name}")
            return ch["id"]

    # Create
    time.sleep(0.5)  # Rate limit safety
    ch_data = api_call("POST", f"/guilds/{guild_id}/channels", {
        "name": name,
        "type": 0,  # TEXT
        "parent_id": cat_id,
        "topic": topic,
        "reason": f"Singularity [AE] — {name} channel",
    })

    if ch_data.get("error"):
        print(f"  ❌ Failed #{name}: {ch_data}")
        result["errors"].append(f"Channel {name}: {ch_data}")
        return None

    print(f"  ✅ Created #{name} ({ch_data['id']})")
    result["created"].append(f"channel:{name}")
    return ch_data["id"]


def _add_owner_access(category_id, owner_id, result):
    """Add channel permission override for guild owner to see private channels."""
    time.sleep(0.3)
    resp = api_call("PUT", f"/channels/{category_id}/permissions/{owner_id}", {
        "type": 1,  # member
        "allow": str(
            (1 << 10) |  # VIEW_CHANNEL
            (1 << 11) |  # SEND_MESSAGES
            (1 << 16) |  # READ_MESSAGE_HISTORY
            (1 << 15) |  # ATTACH_FILES
            (1 << 14) |  # EMBED_LINKS
            (1 << 13)    # MANAGE_MESSAGES
        ),
        "deny": "0",
    })
    if resp.get("error"):
        print(f"  ⚠️  Could not add owner override: {resp}")
    else:
        print(f"  🔑 Added owner ({owner_id}) access to category")


def _send_welcome(bridge_id, guild_name, result):
    """Send welcome message to #bridge."""
    exec_list = "\n".join(
        f"  • <#{result['channels'][rid]}> — {title}"
        for rid, emoji, title, domain in EXEC_ROLES
        if rid in result["channels"]
    )
    ops_list = "\n".join(
        f"  • <#{result['channels'][name]}> — {topic}"
        for name, topic in OPS_CHANNELS
        if name in result["channels"]
    )

    welcome = (
        "```\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃  SINGULARITY [AE] — All Systems Go              ┃\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
        "```\n"
        f"Deployed to **{guild_name}** ⚡\n\n"
        f"**Operations:**\n{ops_list}\n\n"
        f"**Executive Team:**\n{exec_list}\n\n"
        "All seats taken. All channels live. Ready for dispatch."
    )

    time.sleep(0.3)
    resp = api_call("POST", f"/channels/{bridge_id}/messages", {"content": welcome})
    if resp.get("error"):
        print(f"  ⚠️  Welcome message failed: {resp}")
    else:
        print(f"  💬 Welcome message sent to #bridge")


if __name__ == "__main__":
    args = sys.argv[1:]
    public = "--public" in args
    args = [a for a in args if not a.startswith("--")]

    if not args:
        print("Usage: python3 scripts/deploy_guild.py <guild_id|all> [--public]")
        sys.exit(1)

    target = args[0]
    private = not public

    if target == "all":
        # Deploy to all guilds the bot is in
        guilds = api_call("GET", "/users/@me/guilds")
        if isinstance(guilds, dict) and guilds.get("error"):
            print(f"❌ Cannot fetch guilds: {guilds}")
            sys.exit(1)
        print(f"Found {len(guilds)} guilds")
        for g in guilds:
            deploy_guild(g["id"], private=private)
    else:
        deploy_guild(target, private=private)
