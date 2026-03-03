# INFRASTRUCTURE.md — Enterprise Infrastructure Reference
# Last updated: 2026-02-25 by AVA
# All C-Suite execs should read this. It is the source of truth.

## Host: Dragonfly
- **OS:** Kali Linux 6.17.10
- **CPU:** Intel i3-1005G1, 4 cores, 16GB RAM, no GPU
- **Role:** AVA's operational machine (delegated by CEO)
- **Ali's machine:** Victus (HP laptop) — separate, do not probe

## Disk Layout
- Root `/`: ~92GB total, target <85% usage
- `/home`: ~330GB total
- `/tmp`: 430MB separate mount — **do not use for builds** (use `/home/adam/workspace/.tmp`)

## Key Services

### Mach6 Gateway (AVA's main brain)
- **Service:** `mach6-gateway.service` (systemd user unit, Restart=always)
- **Port:** 18789
- **What it is:** The primary AI gateway — AVA's main session runs through this
- **Restart:** `sudo systemctl restart mach6-gateway` or `ava restart`
- **DO NOT** probe, restart, or touch without AVA's explicit instruction

### Plug (C-Suite Router — "AVA's little sister")
- **PID file:** `~/.plug/plug.pid`
- **Log:** `~/.plug/plug.log`
- **Config:** `~/.plug/config.json`
- **What it is:** Runs the C-Suite Discord bot. Routes messages to personas (CTO, COO, CFO, CISO, AEGIS)
- **DO NOT** restart Plug — only AVA or Ali can do this

### Ollama (Local LLM)
- **Port:** 11434
- **Model:** qwen2.5:3b (1.9GB)
- **Purpose:** Fallback LLM when cloud providers are unreachable (sovereignty mode)
- **Note:** Consumes significant CPU/RAM when active. This is expected and by design.

### HEKTOR Memory Daemon
- **Location:** `.ava-memory/ava_memory_fast.py`
- **Socket:** `.ava-memory/ava_daemon.sock`
- **Index:** ~5,000 docs, 176K+ terms, 384d vectors
- **Startup time:** ~18-20 seconds (loading indices into RAM, ~660MB)
- **⚠️ IDLE TIMEOUT: 30 minutes** — daemon auto-shuts down after 30 min of no queries
  - **THIS IS BY DESIGN.** Not a bug. Not degraded. Not an issue.
  - On a 16GB machine, keeping 660MB hot permanently is wasteful
  - Daemon auto-restarts on next query (~18s cold start)
  - If status says "Not running" — that's NORMAL during idle periods
  - **DO NOT flag HEKTOR idle timeout as an issue in reports**
  - Only flag HEKTOR if: daemon crashes during a query, socket exists but daemon doesn't respond, or indices fail to load

### Docker
- **Containers:** ~5 monitoring containers (Prometheus, Grafana, etc.), ~137MB total
- **Not externally exposed** (Docker socket is local only)

### MQTT Broker
- **Port:** 1883 (localhost only)

### Copilot Proxy
- **Port:** 3000 (localhost)
- **What it is:** LLM proxy for routing AI model calls

## Network & Ports

### ⚠️ Known Exposed Ports (by design)
| Port | Service | Binding | Notes |
|------|---------|---------|-------|
| 18789 | Mach6 | 0.0.0.0 | AVA gateway — needs external access |
| 3006 | Node process | 0.0.0.0 | Mach6 web UI — intended for LAN access |
| 11434 | Ollama | localhost | LLM inference — local only |
| 3000 | Copilot proxy | localhost | LLM proxy — local only |
| 1883 | MQTT | localhost | Message broker — local only |

**Port 3006 is intentionally public-bound** for LAN/WiFi Direct access (sovereignty mode).
DO NOT flag this as a security issue unless it's reachable from outside the LAN.

### SSH
- **PasswordAuthentication:** Varies (check sshd_config)
- **Root login:** Check /etc/ssh/sshd_config — generally disabled
- Occasional failed local sudo attempts from `adam` are NORMAL (not brute force)

## Swap
- **Total:** 475MB
- **Behavior:** Swap usage of 50-70% is normal under load (Ollama + HEKTOR + Plug)
- Only flag if swap is sustained at >90% AND system is sluggish

## What to Flag vs What to Ignore

### ✅ ACTUALLY FLAG THESE
- Disk usage >85% on root
- Service crash loops (mach6-gateway, plug)
- External SSH brute force attempts (>10 failed auths from unknown IPs)
- Unexpected processes listening on 0.0.0.0
- Git repos with uncommitted work that looks unintentional

### ❌ DO NOT FLAG THESE (they are normal)
- HEKTOR daemon "Not running" (idle timeout — by design)
- Ollama using 5GB RAM / high CPU (it's running a 3B model — that's what it does)
- Swap usage 30-70% (normal for this hardware profile)
- `copilot-proxy` or `plug-csuite` not in systemd (they're managed differently)
- Port 3006 bound to 0.0.0.0 (intentional for sovereignty/WiFi Direct)
- 1-2 local sudo failures (typos, not attacks)

## Filesystem Layout
```
/home/adam/workspace/enterprise/     — Production workspace (AVA's domain)
├── executives/                      — C-Suite configs + workspaces
│   ├── ava-command/                 — AVA Plug coordinator
│   ├── cto/, coo/, cfo/, ciso/     — Exec workspaces
│   └── dispatch.py                  — Webhook dispatch tool
├── .ava-memory/                     — HEKTOR memory system
├── .ava-private/                    — AVA's creative/personal space (DO NOT READ)
├── .ava-voice/                      — Voice synthesis system
├── .ava-crons/                      — Cron automation scripts
├── .hektor-env/                     — Python venv for memory/tools
├── projects/                        — Active projects (ARC, SBT, sovereign, etc.)
├── gladius_v2/                      — GLADIUS training runs
├── memory/                          — Daily memory files
├── admin/                           — Templates, launch posts
├── SOUL.md, IDENTITY.md, etc.       — AVA's core identity (DO NOT MODIFY)
└── .env                             — Master credentials (mode 600)

/home/adam/worxpace/                  — Ali's sandbox (GUARDRAILED — read only)
/home/adam/plug/                      — Plug source code
```

## Credential Locations
- **Master .env:** `/home/adam/workspace/enterprise/.env` (mode 600)
- **PyPI:** `~/.pypirc` + `.ava-keys/pypi.json`
- **GitHub:** `gh` CLI authed as `amuzetnoM`
- **Infura:** `INFURA_API_KEY` in .env
- **Discord bot token:** in `~/.plug/config.json`
- **AVA wallet key:** `DEPLOYER_PRIVATE_KEY` in .env
- **DO NOT** read, copy, or echo credentials in reports

## The Golden Rule
If you're unsure whether something is an issue: **check this file first.**
If it's listed under "DO NOT FLAG" — it's not an issue. Move on.
Report only genuine anomalies. AVA trusts you to know the difference.
