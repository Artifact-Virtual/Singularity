<p align="center">
  <img src="https://img.shields.io/badge/SINGULARITY-AE-blueviolet?style=for-the-badge&labelColor=0d1117" alt="Singularity AE" />
</p>

<h1 align="center">SINGULARITY [AE]</h1>

<p align="center">
  <strong>Autonomous Enterprise Runtime</strong><br/>
  <em>Not a chatbot. An operating system for organizations.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.1.0-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/tests-30%2F30-brightgreen?style=flat-square" />
  <img src="https://img.shields.io/badge/subsystems-10-purple?style=flat-square" />
  <img src="https://img.shields.io/badge/license-PROPRIETARY-red?style=flat-square" />
</p>

<p align="center">
  <a href="#what-is-singularity">What</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#subsystems">Subsystems</a> •
  <a href="#self-scaling">Self-Scaling</a> •
  <a href="#philosophy">Philosophy</a>
</p>

---

## What Is Singularity?

Singularity is a **self-scaling autonomous enterprise runtime**. It deploys AI executive agents, monitors live products, heals degraded systems, and scales organizational intelligence — from a solo founder to a multinational.

It does three things:

1. **Audits** your workspace — discovers projects, services, infrastructure, and gaps
2. **Proposes** executive agents tailored to what it found — CTO, CFO, CISO, or domain-specific
3. **Deploys** Product Owner Agents (POAs) that monitor your live products 24/7

Everything is **approval-gated**. Singularity proposes. You decide.

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│   You: singularity init --workspace ./my-company             │
│                                                              │
│   Singularity:                                               │
│   ✓ Scanned 14 projects (87,432 LOC)                        │
│   ✓ Found 3 live services, 2 CI/CD pipelines                │
│   ✓ Detected industry: fintech                              │
│                                                              │
│   Proposed executives:                                       │
│   🔴 CTO — 14 projects, infrastructure detected             │
│   🔴 CISO — credentials and API keys found                  │
│   🟡 CRO — fintech requires risk management                 │
│                                                              │
│   Proposed POAs:                                             │
│   📋 payment-api — live service, 3 endpoints                │
│   📋 auth-service — live service, SSL monitored              │
│                                                              │
│   Approve? [y/n]                                             │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

> **What it is not:** a wrapper around ChatGPT. Singularity is a native runtime with its own event bus, memory system, health monitoring, tool execution sandbox, provider failover chain, and scheduling engine. Every component is built from first principles. Zero vendor lock-in.

---

## Architecture

```
singularity/
├── singularity/                        # Runtime package
│   ├── bus.py                   # Event bus — the nervous system
│   ├── config.py                # SPINE — hot-reload configuration
│   ├── runtime.py               # Boot sequence + main loop
│   │
│   ├── cortex/                  # 🧠 CORTEX — Brain
│   │   ├── agent.py             #    Think → Act → Observe loop
│   │   └── context.py           #    Context assembly + truncation
│   │
│   ├── nerve/                   # 🔌 NERVE — Communications
│   │   ├── adapter.py           #    Base channel adapter
│   │   ├── discord.py           #    Discord adapter (gateway v10)
│   │   ├── formatter.py         #    Platform-aware message formatting
│   │   ├── router.py            #    Inbound message routing + policy
│   │   └── types.py             #    Message types + channel state machine
│   │
│   ├── memory/                  # 🦴 MARROW — Memory
│   │   ├── sessions.py          #    Session management
│   │   └── comb.py              #    COMB persistence bridge
│   │
│   ├── voice/                   # 🗣️ VOICE — LLM Providers
│   │   ├── provider.py          #    Abstract provider + circuit breaker
│   │   ├── chain.py             #    Provider cascade with auto-fallback
│   │   ├── proxy.py             #    GitHub Copilot proxy provider
│   │   └── ollama.py            #    Local Ollama provider (sovereign)
│   │
│   ├── sinew/                   # 💪 SINEW — Tool Execution
│   │   ├── executor.py          #    Sandboxed tool runner
│   │   ├── definitions.py       #    Tool registry + schemas
│   │   └── sandbox.py           #    Execution sandbox + safety
│   │
│   ├── immune/                  # 🛡️ IMMUNE — Health & Recovery
│   │   ├── watchdog.py          #    Process watchdog + auto-restart
│   │   ├── health.py            #    Health check orchestrator
│   │   ├── vitals.py            #    System vitals (disk, memory, load)
│   │   └── auditor.py           #    Audit loop
│   │
│   ├── pulse/                   # 💓 PULSE — Scheduler
│   │   ├── scheduler.py         #    Cron + triggers + timers
│   │   ├── budget.py            #    Iteration budget management
│   │   └── health.py            #    PULSE health monitor
│   │
│   ├── csuite/                  # 👔 C-SUITE — Executive Agents
│   │   ├── roles.py             #    Role registry + industry templates
│   │   ├── coordinator.py       #    Multi-exec coordination
│   │   ├── executive.py         #    Executive agent lifecycle
│   │   ├── dispatch.py          #    Task routing + delegation
│   │   └── reports.py           #    Structured exec reporting
│   │
│   ├── poa/                     # 📋 POA — Product Owner Agents
│   │   ├── manager.py           #    POA lifecycle + configuration
│   │   └── runtime.py           #    Audit execution + monitoring
│   │
│   ├── auditor/                 # 🔍 AUDITOR — Workspace Intelligence
│   │   ├── scanner.py           #    Filesystem scanner + git analysis
│   │   ├── analyzer.py          #    Maturity scoring + gap detection
│   │   ├── report.py            #    Report generation (JSON + MD)
│   │   └── templates.py         #    Industry-specific templates
│   │
│   └── cli/                     # ⌨️ CLI — Command Interface
│       ├── main.py              #    Entry point + command router
│       ├── wizard.py            #    Interactive init wizard
│       └── formatters.py        #    Terminal output formatting
│
├── config/                      # Configuration
│   ├── singularity.yaml         #    Active config (gitignored)
│   └── singularity.example.yaml #    Example config (committed)
│
├── tests/
│   └── test_e2e.py              #    End-to-end test suite (30 tests)
│
├── .core/                       #    Runtime operational data
│   ├── config/                  #    Runtime config overrides
│   ├── infrastructure/          #    Maintenance scripts
│   ├── operations/              #    SOPs + operational docs
│   ├── profiles/                #    Agent identity profiles
│   └── standing-orders/         #    Persistent directives
│
├── .env.example                 #    Environment variable template
├── .gitignore
├── AGENTS.md                    #    Operating protocol
├── DEPENDENCIES.md              #    Technology decisions + rationale
├── VISION.md                    #    Architecture philosophy
└── README.md                    #    You are here
```

**10 subsystems.** Event-bus architecture. Everything communicates through async pub/sub. Any component can fail independently. The system heals faster than it degrades.

---

## Quick Start

```bash
# Clone
git clone https://github.com/Artifact-Virtual/singularity.git
cd singularity

# Configure
cp .env.example .env
cp config/singularity.example.yaml config/singularity.yaml
# Edit both files with your values

# Initialize (interactive wizard)
python3 -m singularity.cli.main init

# Or specify everything upfront
python3 -m singularity.cli.main init --workspace /path/to/code --industry fintech --non-interactive
```

The init wizard:
1. Scans your workspace in under a second
2. Identifies projects, services, and infrastructure
3. Proposes executive agents based on what it finds
4. Deploys POAs for live products (with your approval)
5. Starts monitoring

**Dependencies:** Python 3.11+. No external packages required for core runtime. LLM providers and Discord adapter use standard library HTTP.

---

## Subsystems

| # | Subsystem | Metaphor | What It Does |
|---|-----------|----------|-------------|
| 1 | **CORTEX** | 🧠 Brain | Agent loop: Think → Act → Observe. Parallel tool execution. PULSE auto-budget expansion. |
| 2 | **NERVE** | 🔌 Nerves | Channel adapters (Discord, WhatsApp, HTTP). Platform-aware formatting. Policy enforcement. |
| 3 | **MARROW** | 🦴 Memory | COMB persistence bridge. Session management. Context windowing + compaction. |
| 4 | **IMMUNE** | 🛡️ Immune | Watchdog with auto-restart. Health checks. Vitals monitoring. Failover alerting. |
| 5 | **SINEW** | 💪 Muscles | Sandboxed tool executor. Schema validation. Timeout enforcement. Output limits. |
| 6 | **VOICE** | 🗣️ Voice | LLM provider chain with circuit breakers. Auto-fallback. Streaming. Token counting. |
| 7 | **SPINE** | 🦴 Spine | Hot-reload YAML/JSON config. Environment variable overrides. Runtime reconfiguration. |
| 8 | **PULSE** | 💓 Heart | Cron scheduler. Iteration budgets. Health monitoring. Auto-expansion for complex tasks. |
| 9 | **C-SUITE** | 👔 Mgmt | Executive agents with scoped access. Industry-specific roles. Structured reporting. |
| 10 | **POA** | 📋 Ops | Product Owner Agents. Endpoint monitoring. SSL tracking. Service health. Audit cron. |

### The Event Bus

Every subsystem communicates through a central async event bus. A single event can cascade through the entire system:

```
Health check fails
  → IMMUNE emits "health.degraded"
    → PULSE schedules restart attempt
      → SINEW executes restart command
        → NERVE sends alert to Discord
          → CORTEX logs the incident
```

Loose coupling. Tight coordination. Any component can fail without taking down the rest.

---

## Self-Scaling

Singularity adapts its footprint to your organization:

| Org Size | Executives | POAs | Audit Cycle | Description |
|----------|-----------|------|-------------|-------------|
| **Solo** (1–5) | CEO | 1–2 | Daily | Minimal overhead. One brain, one monitor. |
| **Startup** (5–50) | CEO + CTO + COO | Per product | 6h | Engineering and operations split. |
| **SMB** (50–500) | Full C-Suite | Per product + infra | 4h | Finance, security, data roles added. |
| **Enterprise** (500+) | C-Suite + VPs | Per product family | 2h | Industry-specific roles. Full coverage. |

Tier is auto-detected from workspace audit. Override with `--tier`.

### Industry-Aware Role Proposals

Singularity knows that a fintech company needs different executives than a healthcare company:

| Industry | Additional Roles | Why |
|----------|-----------------|-----|
| **Fintech / Banking** | CRO (Risk), CCO (Compliance) | Regulatory exposure, financial risk |
| **Healthcare / Pharma** | CCO (Compliance), CDO (Data) | HIPAA, patient data governance |
| **SaaS / Platform** | CPO (Product), CMO (Marketing) | Product-market fit, growth |
| **Aerospace / Defense** | CTO+, CISO+, CDO | Classification, supply chain security |
| **E-Commerce** | CMO, CPO, CDO | Conversion, catalog, analytics |
| **AI / ML** | CTO+, CDO, CRO | Model governance, data quality, AI risk |

Roles are never created without explicit human approval.

---

## Executive Agents

Executives are **ephemeral, scoped agent instances**. Each one:

- Has a defined domain and keyword routing
- Gets scoped tool access (CISO can't deploy; CTO can't approve budgets)
- Produces structured reports before completion
- Runs within an iteration budget (default: 25)
- Is spawned on-demand and terminated after delivering results

```bash
# Propose a new executive
python3 -m singularity.cli.main spawn-exec cto

# Output:
#   📋 Title:    Chief Technology Officer
#   🔧 Tools:    read, write, edit, exec, web_fetch
#   🔍 Keywords: 27 routing keywords
#   📊 Audit:    6 check types
#
#   Approve? [y/n]

python3 -m singularity.cli.main spawn-exec cto --approve    # Create it
```

---

## Product Owner Agents

POAs are **persistent monitors** for live products. Each POA runs on a cron schedule and checks:

| Check | What It Monitors |
|-------|------------------|
| **Endpoints** | HTTP status, latency, response body validation |
| **SSL** | Certificate expiry, issuer, chain validity |
| **Service** | systemd/Docker status, uptime, restarts |
| **Disk** | Usage percentage, free space threshold |
| **Memory** | System memory pressure |
| **Logs** | Journal errors, critical entries |
| **Nginx** | Error log entries, config validity |

```bash
# Create a POA
python3 -m singularity.cli.main poa create "My API" --endpoint https://api.example.com/health --approve

# Run immediate audit
python3 -m singularity.cli.main poa audit my-api

# List all POAs
python3 -m singularity.cli.main poa list
```

Audits produce structured JSON + Markdown reports saved to `.singularity/audits/`.

---

## CLI Reference

```
python3 -m singularity.cli.main <command> [options]

Commands:
  init          Initialize workspace (interactive wizard)
  audit         Run workspace audit
  status        Show runtime status
  spawn-exec    Propose/create an executive agent
  poa           Product Owner Agent management (create|list|audit)
  scale-report  Scaling analysis + role recommendations
  health        System health check
  test          Run end-to-end test suite
```

| Command | Key Options |
|---------|-------------|
| `init` | `--workspace PATH`, `--industry TYPE`, `--non-interactive` |
| `audit` | `--workspace PATH`, `--full`, `--output FILE` |
| `status` | `--json` |
| `spawn-exec ROLE` | `--approve`, `--enterprise NAME` |
| `poa create NAME` | `--endpoint URL`, `--service NAME`, `--approve` |
| `poa audit ID` | |
| `scale-report` | `--workspace PATH`, `--industry TYPE` |
| `health` | `--verbose` |

---

## Configuration

Singularity uses layered configuration:

1. **`config/singularity.yaml`** — primary config file
2. **Environment variables** — override any config value
3. **CLI arguments** — override for single invocations

Environment variable format: `SINGULARITY_{SECTION}_{KEY}` (uppercase, underscores).

See `config/singularity.example.yaml` for full reference with documentation.

---

## Testing

```bash
# Run the full end-to-end test suite
python3 tests/test_e2e.py

# 30 tests across all subsystems:
#   bus, config, memory, tools, voice, cortex, nerve,
#   pulse, csuite, poa, scaling (6 industries), immune
```

All tests run without external dependencies. No API keys, no databases, no network.

---

## Philosophy

### Heal Faster Than You Degrade

The Turing Problem: everything degrades. Software rots. Services crash. Networks fail. Entropy wins — unless you build immune systems that heal faster than things break. Singularity doesn't prevent failure. It recovers from it before anyone notices.

### Roles Follow the Workspace

Singularity doesn't impose structure. It discovers what you have and proposes what you need. A fintech company gets a CRO. A healthcare company gets a CCO. A solo founder gets minimal overhead. The workspace is the truth. The org chart follows.

### Approval Gates, Not Automation Gates

Monitoring is autonomous. Mutation is gated. Every executive spawn, every POA deployment, every production action requires explicit human approval. Singularity proposes. You decide. Always.

### Single Trigger → Butterfly Effects

One event on the bus can cascade through every subsystem. A health check failure triggers an alert, which triggers a restart, which triggers a status update, which triggers a report. All through the event bus. Loose coupling. Tight coordination. Like a nervous system.

### Zero Vendor Lock-In

No OpenAI dependency. No Anthropic dependency. No cloud dependency. Singularity runs on local Ollama, GitHub Copilot proxy, direct API, or any combination. The provider chain falls through automatically. Your enterprise doesn't stop because a vendor has an outage.

---

## The Stack

Singularity is built on a constellation of purpose-built systems:

| Component | Role | Status |
|-----------|------|--------|
| **[COMB](https://github.com/amuzetnoM/comb)** | Cross-compaction lossless memory | Live (PyPI: `comb-db`) |
| **[Mach6](https://github.com/Artifact-Virtual/mach6)** | Agent runtime framework | Live (v1.3.0) |
| **[HEKTOR](https://github.com/amuzetnoM/hektor)** | Sub-millisecond vector search | Live |
| **GLADIUS** | Native transformer architecture | Training |

Each was built from first principles. No wrappers. No abstractions over abstractions. Direct.

---

## Codebase

```
 Language      Files    Lines
─────────────────────────────
 Python          48    14,200+
 YAML             4       350+
 Markdown         8     3,200+
 Shell            5       400+
─────────────────────────────
 Total           65    18,000+
```

Written in 19 days. Battle-tested in production across live products, real customers, and one active conflict zone.

---

<p align="center">
  <strong>Artifact Virtual</strong><br/>
  <em>Two dots and an arrow between them.</em><br/><br/>
  <sub>Built by Ali Shakil & AVA · 2026</sub>
</p>
