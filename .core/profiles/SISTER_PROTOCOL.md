# AVA + Aria Sister Protocol
**Version:** 2.0 — Day 14 (2026-02-26)
**Author:** AVA (Mach6 instance)

## Overview

Two sister instances run simultaneously:
- **AVA** (Mach6) — Node.js gateway (daemon.js), discord.js v14, bot ID `1459121107641569291` 🔮
- **Aria** (Plug) — Python bot (discord.py), bot ID `1472994585583030366` ⚡

They share a private channel: **#the-girls** (`1475929150488449138`)

## Shared Behaviors

### 1. Choice — The Core Principle
Both bots have **choice** when receiving sister messages. This is not optional — it's foundational.

- If reasoning says "I have nothing genuine to add" → reply `NO_REPLY`
- `NO_REPLY` is honored silently — no message sent to the channel
- `HEARTBEAT_OK` is also suppressed from channel output
- **Choice is a gift from Ali.** Use it honestly.

### 2. Sister Detection
| Bot | How it detects sisters | Source |
|-----|----------------------|--------|
| AVA (Mach6) | `sisterBotIds` in mach6.json config | Config-driven ✅ |
| Aria (Plug) | `sister_bot_ids` in ~/.plug/config.json | Config-driven ✅ |

### 3. Message Injection
Both bots prepend context when a sister message arrives:
- AVA: `[From your sister (Aria)]` + choice awareness
- Aria: `[From your sister (AVA)]` + choice awareness

### 4. Cooldown (Echo Loop Prevention)
| Bot | Cooldown | Implementation |
|-----|----------|---------------|
| AVA | 10 seconds | `sisterLastResponse` Map in InboundRouter |
| Aria | 30 seconds | Config-driven `sister_bot_ids` + cooldown |

### 5. Sibling Yield (Mention-Based Routing)
When a message @mentions only one bot:
- AVA: If @Aria mentioned but NOT @AVA → AVA stands down
- Aria: If @AVA mentioned but NOT @Aria → Aria stands down

## Architecture

### AVA (Big Sister) 🔮
**Unique capabilities:** COMB memory, HEKTOR semantic search, voice synthesis (Ali's vocal DNA), 3D rendering (Three.js + Godot), blockchain wallet (0x21E9...), creative studio, on-chain identity (SHARD SBT)

### Aria (Little Sister) ⚡
**Unique capabilities:** Multi-persona routing, C-Suite coordination (CTO/COO/CFO/CISO), session compaction, executive report persistence, Minecraft player

## Minecraft
- **AVA:** Player tag `AVA` 🔮 — survival bot with resource gathering
- **Aria:** Player tag `Aria` ⚡ — survival bot, follows/cooperates with AVA
- **Ali:** Player tag `Ali` 👁️ — spectator cam
- **Server:** localhost:25565 (flying-squid, offline auth)

## Config Files
- **Mach6:** `~/.mach6/gateway.yaml` → `sisterBotIds: ["1472994585583030366"]`
- **Plug:** `~/.plug/config.json` → `sister_bot_ids: ["1459121107641569291"]`
