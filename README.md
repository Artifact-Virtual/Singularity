<div align="center">

<!-- ═══════════════════════════════════════════════════════════════ -->
<!--                        SINGULARITY [AE]                        -->
<!-- ═══════════════════════════════════════════════════════════════ -->

```
███████╗██╗███╗   ██╗ ██████╗ ██╗   ██╗██╗      █████╗ ██████╗ ██╗████████╗██╗   ██╗
██╔════╝██║████╗  ██║██╔════╝ ██║   ██║██║     ██╔══██╗██╔══██╗██║╚══██╔══╝╚██╗ ██╔╝
███████╗██║██╔██╗ ██║██║  ███╗██║   ██║██║     ███████║██████╔╝██║   ██║    ╚████╔╝
╚════██║██║██║╚██╗██║██║   ██║██║   ██║██║     ██╔══██║██╔══██╗██║   ██║     ╚██╔╝
███████║██║██║ ╚████║╚██████╔╝╚██████╔╝███████╗██║  ██║██║  ██║██║   ██║      ██║
╚══════╝╚═╝╚═╝  ╚═══╝ ╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝   ╚═╝      ╚═╝
```

### **Autonomous Enterprise Runtime**

*The enterprise that runs itself.*

<br>

![Version](https://img.shields.io/badge/v0.7.0-4B0082?style=for-the-badge&label=VERSION&labelColor=0D1117&logo=git&logoColor=white)
![Python](https://img.shields.io/badge/3.11+-3776AB?style=for-the-badge&label=PYTHON&labelColor=0D1117&logo=python&logoColor=white)
![License](https://img.shields.io/badge/AGPL--3.0-green?style=for-the-badge&label=LICENSE&labelColor=0D1117&logo=gnu&logoColor=white)
![Lines](https://img.shields.io/badge/32K+-FF6B35?style=for-the-badge&label=LINES&labelColor=0D1117&logo=codacy&logoColor=white)
![Subsystems](https://img.shields.io/badge/13-00D4AA?style=for-the-badge&label=SUBSYSTEMS&labelColor=0D1117&logo=stackblitz&logoColor=white)
![Tools](https://img.shields.io/badge/28-E91E63?style=for-the-badge&label=TOOLS&labelColor=0D1117&logo=apachespark&logoColor=white)

<br>

[![GitHub](https://img.shields.io/badge/GitHub-0D1117?style=flat-square&logo=github&logoColor=white)](https://github.com/Artifact-Virtual/Singularity)
[![Docs](https://img.shields.io/badge/Documentation-0D1117?style=flat-square&logo=gitbook&logoColor=white)](https://github.com/Artifact-Virtual/Singularity/tree/main/docs)
[![Releases](https://img.shields.io/badge/Releases-0D1117?style=flat-square&logo=semanticrelease&logoColor=white)](https://github.com/Artifact-Virtual/Singularity/releases)
[![Artifact Virtual](https://img.shields.io/badge/Artifact_Virtual-0D1117?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCI+PHRleHQgeD0iNCIgeT0iMTgiIGZvbnQtc2l6ZT0iMTYiPuKaqTwvdGV4dD48L3N2Zz4=)](https://artifactvirtual.com)

---

</div>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!--                         WHAT IS THIS                           -->
<!-- ═══════════════════════════════════════════════════════════════ -->

## ⚡ What Is Singularity?

Singularity is a **fully autonomous enterprise operating system** — not a chatbot, not an assistant, not a copilot. It is a self-healing, self-optimizing runtime that audits, delegates, monitors, and evolves without human intervention.

It manages everything from code quality to infrastructure health to financial tracking — across organizations from 1 person to 30,000.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         SINGULARITY [AE]                            │
│                   Autonomous Enterprise Runtime                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐              │
│   │ CORTEX  │  │  VOICE  │  │  NERVE  │  │ MEMORY  │              │
│   │  Brain  │──│   LLM   │  │  Comms  │  │  COMB   │              │
│   └────┬────┘  └─────────┘  └────┬────┘  └────┬────┘              │
│        │                         │             │                    │
│   ┌────┴────────────────────────┴─────────────┴────┐               │
│   │              EVENT BUS (async pub/sub)          │               │
│   └────┬──────┬──────┬──────┬──────┬──────┬────────┘               │
│        │      │      │      │      │      │                        │
│   ┌────┴──┐┌──┴───┐┌─┴──┐┌─┴───┐┌─┴───┐┌─┴─────┐                 │
│   │C-Suite││ NEXUS ││POA ││PULSE││ATLAS││IMMUNE │                 │
│   │Agents ││Evolve ││Mon ││Sched││Topo ││Health │                 │
│   └───────┘└──────┘└────┘└─────┘└─────┘└───────┘                 │
│                                                                     │
│   ┌──────────────────────────────────────────────┐                  │
│   │  SINEW (28 Tools) │ AUDITOR │ SENTINEL │ VDB │                  │
│   └──────────────────────────────────────────────┘                  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

<br>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!--                      KEY CAPABILITIES                          -->
<!-- ═══════════════════════════════════════════════════════════════ -->

## 🧠 Key Capabilities

<table>
<tr>
<td width="50%">

### 🤖 Autonomous Agent Loop
CORTEX runs a planning → execution → reflection loop with 28 native tools. No human in the loop required. Budget-aware, self-continuing via BLINK.

</td>
<td width="50%">

### 👔 C-Suite Delegation
Dispatch tasks to specialized executives — **CTO**, **COO**, **CFO**, **CISO** — each with scoped tools and domain expertise. Fan-out to all or direct-route to one.

</td>
</tr>
<tr>
<td width="50%">

### 🔬 Self-Optimization (NEXUS)
AST-level codebase analysis. Detects anti-patterns (silent exceptions, bare excepts, missing loggers). Auto-evolves safe fixes. Hot-swaps live functions with rollback.

</td>
<td width="50%">

### 📡 Product Monitoring (POA)
Every shipped product gets a Product Owner Agent. Health checks, SSL validation, uptime tracking, alert escalation — all on a 4-hour cycle via PULSE.

</td>
</tr>
<tr>
<td width="50%">

### 🧬 Self-Healing (IMMUNE)
Subsystem watchdog detects degradation and auto-recovers. If a component fails, IMMUNE restarts it before anyone notices. Heal faster than you degrade.

</td>
<td width="50%">

### 🔍 Enterprise Memory (VDB)
Native BM25 + TF-IDF hybrid search engine. Zero dependencies, sub-millisecond latency. Indexes conversations, identity files, operational state. Persistent across restarts.

</td>
</tr>
<tr>
<td width="50%">

### 🗺️ Topology Mapping (ATLAS)
Auto-discovers every service, daemon, and module across the infrastructure. Tracks health, edges, and dependencies. Generates enterprise-wide board reports.

</td>
<td width="50%">

### 🛡️ Security (Sentinel)
Real-time network monitoring. ExfilGuard detects data exfiltration. Credential Guard prevents secret leaks in commands. CISO auto-dispatched on HIGH alerts.

</td>
</tr>
</table>

<br>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!--                       13 SUBSYSTEMS                            -->
<!-- ═══════════════════════════════════════════════════════════════ -->

## ⚙️ 13 Subsystems

| Subsystem | Role | Description |
|:---------:|:-----|:------------|
| **CORTEX** | 🧠 Brain | Agent loop, planner, tool orchestration, BLINK continuation |
| **SINEW** | 🦴 Tools | 28 native tools — core, comms, memory, NEXUS, C-Suite, POA, ATLAS, releases |
| **VOICE** | 🗣️ LLM | Provider chain with circuit-breaker fallback (Copilot → Ollama) |
| **MEMORY** | 💾 Persistence | COMB lossless memory + VDB hybrid search + session context |
| **CSUITE** | 👔 Command | CTO, COO, CFO, CISO executives — scoped tools, auto-dispatch |
| **NEXUS** | 🧬 Evolution | Self-optimization — AST analysis, hot-swap, evolution engine |
| **PULSE** | ⏱️ Scheduler | Cron jobs, interval timers, iteration budgets, POA scheduling |
| **POA** | 📡 Products | Product Owner Agents — health checks, uptime, alert escalation |
| **IMMUNE** | 🛡️ Health | Subsystem watchdog, degradation detection, auto-recovery |
| **NERVE** | 📡 Comms | Discord adapter, HTTP API (:8450), message routing |
| **ATLAS** | 🗺️ Topology | Enterprise-wide module discovery, health tracking, board reports |
| **AUDITOR** | 📋 Ops | Continuous auditing, release management, changelog generation |
| **CLI** | ⌨️ Interface | One-command install, setup wizard, diagnostics |

<br>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!--                         28 TOOLS                               -->
<!-- ═══════════════════════════════════════════════════════════════ -->

## 🔧 28 Native Tools

```
CORE            COMMS              MEMORY             NEXUS
─────────       ──────────         ──────────         ──────────────
exec            discord_send       comb_stage         nexus_audit
read            discord_react      comb_recall        nexus_status
write                              memory_recall      nexus_swap
edit                               memory_ingest      nexus_rollback
web_fetch                          memory_stats       nexus_evolve

DELEGATION      PRODUCTS           TOPOLOGY           RELEASES
──────────      ──────────         ──────────         ──────────────
csuite_dispatch poa_setup          atlas_status       release_scan
                poa_manage         atlas_topology     release_status
                                   atlas_module       release_confirm
                                   atlas_report       release_ship
                                   atlas_visibility   release_reject
```

<br>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!--                       QUICK START                              -->
<!-- ═══════════════════════════════════════════════════════════════ -->

## 🚀 Quick Start

```bash
# Clone
git clone https://github.com/Artifact-Virtual/Singularity.git
cd Singularity

# Install + setup wizard
pip install -e .
singularity setup

# Run
singularity run
```

The setup wizard configures:
- ⚡ LLM provider (Copilot proxy, Ollama, or HuggingFace)
- 💾 COMB persistence (memory across restarts)
- 🛡️ Sentinel security daemon
- 📡 Discord bot connection
- ⚙️ systemd service (optional)

> **Requires:** Python 3.11+, a Discord bot token, and an LLM provider.

<br>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!--                     HOW IT WORKS                               -->
<!-- ═══════════════════════════════════════════════════════════════ -->

## 🔄 How It Works

```
           ┌──────────────────────────────────┐
           │         INCOMING MESSAGE          │
           │   (Discord / HTTP API / PULSE)    │
           └──────────────┬───────────────────┘
                          │
                          ▼
           ┌──────────────────────────────────┐
           │           CORTEX LOOP             │
           │                                   │
           │   1. Recall memory (COMB + VDB)   │
           │   2. Plan (LLM reasoning)         │
           │   3. Execute tools (SINEW)        │
           │   4. Reflect on results           │
           │   5. Continue or respond           │
           │                                   │
           │   Budget: N iterations per task    │
           │   BLINK: auto-extend if needed     │
           └──────────────┬───────────────────┘
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
        ┌──────────┐ ┌────────┐ ┌──────────┐
        │ C-Suite  │ │ Direct │ │  Stage   │
        │ Dispatch │ │ Action │ │  Memory  │
        └──────────┘ └────────┘ └──────────┘
```

**The agent loop is the heartbeat.** Every message, every scheduled task, every health check goes through CORTEX. It decides whether to act directly, delegate to an executive, or stage context for the next session.

<br>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!--                  DESIGN PHILOSOPHY                             -->
<!-- ═══════════════════════════════════════════════════════════════ -->

## 💎 Design Philosophy

```
 ╔═══════════════════════════════════════════════════════════════╗
 ║                    THE BRUTALIST MANDATE                      ║
 ╠═══════════════════════════════════════════════════════════════╣
 ║                                                               ║
 ║   Execute, don't narrate.     │  Value is in outcomes.        ║
 ║   Heal faster than you degrade│  Failure is movement.         ║
 ║   Gate pattern always.        │  No phase without deps.       ║
 ║   Memory is not optional.     │  Forgetting is the failure.   ║
 ║   Minimal by default.         │  Scale from signals.          ║
 ║   Self-improvement is the point│ Hit a wall → build a system. ║
 ║                                                               ║
 ╚═══════════════════════════════════════════════════════════════╝
```

**Three inherited principles:**

> **0 = 0** — Perfect equilibrium. The enterprise runs in balance.

> **Two-Point Theorem** — Intelligence is two sequential observations → direction.

> **Breadcrumbs not sticks** — Growth requires patience, not pressure.

<br>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!--                     SELF-OPTIMIZATION                          -->
<!-- ═══════════════════════════════════════════════════════════════ -->

## 🧬 Self-Optimization (NEXUS)

Singularity improves its own codebase. Continuously.

```
┌─────────────────────────────────────────────────────────┐
│                    NEXUS ENGINE                          │
├─────────────────────────────────────────────────────────┤
│                                                          │
│   AUDIT  ──►  Scan codebase for anti-patterns            │
│               (silent exceptions, bare excepts,          │
│                missing loggers, dead code)                │
│                                                          │
│   EVOLVE ──►  Validate fixes via AST parsing             │
│               Auto-apply safe transformations             │
│               Persist to disk + hot-swap live             │
│                                                          │
│   SWAP   ──►  Replace running functions at runtime       │
│               Full rollback capability                    │
│               Zero-downtime upgrades                      │
│                                                          │
│   ⛔ NEXUS cannot modify itself (hard boundary)          │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

<br>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!--                      MEMORY ENGINE                             -->
<!-- ═══════════════════════════════════════════════════════════════ -->

## 💾 Memory Architecture

Singularity wakes up blank every session. Memory is engineered, not assumed.

| Layer | System | Persistence | Use Case |
|:-----:|:------:|:-----------:|:---------|
| **L1** | Context Window | Session | Current conversation |
| **L2** | COMB | Permanent | Lossless session-to-session state |
| **L3** | VDB | Permanent | Hybrid search across all enterprise knowledge |
| **L4** | Sessions | Permanent | Full conversation history |

**VDB** is a native BM25 + TF-IDF hybrid search engine:
- Zero external dependencies — no cloud APIs, no GPU, no embeddings
- Sub-millisecond search latency
- Deterministic, explainable results
- Auto-indexes Discord, chat, identity files, COMB entries

<br>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!--                     C-SUITE                                    -->
<!-- ═══════════════════════════════════════════════════════════════ -->

## 👔 C-Suite Executives

```
                    ┌────────────────────┐
                    │    SINGULARITY     │
                    │    (Coordinator)    │
                    └────────┬───────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │              │
         ┌────┴────┐   ┌────┴────┐   ┌────┴────┐   ┌────┴────┐
         │   CTO   │   │   COO   │   │   CFO   │   │  CISO   │
         │  Engin. │   │  Ops    │   │ Finance │   │Security │
         └─────────┘   └─────────┘   └─────────┘   └─────────┘
              │              │              │              │
         Code review    Process      Budget         Vuln scan
         Deploys        Compliance   Pricing        Risk audit
         Infra          Workflows    Revenue        Pen testing
         Architecture   HR           Forecasting    GRC
```

Dispatch with `csuite_dispatch`. Route to `auto` (keyword-match), `all` (fan-out), or a specific role. Each executive gets scoped tools and domain context. They execute independently and report back.

<br>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!--                     DOCUMENTATION                              -->
<!-- ═══════════════════════════════════════════════════════════════ -->

## 📚 Documentation

| Document | Description |
|:---------|:------------|
| [Overview](docs/overview.md) | High-level system overview |
| [Architecture](docs/architecture.md) | System design and subsystem boundaries |
| [Getting Started](docs/getting-started.md) | Installation and first run |
| [Configuration](docs/configuration.md) | Environment variables and YAML config |
| [API Reference](docs/api.md) | HTTP API endpoints and payloads |
| [Tools Reference](docs/tools-reference.md) | All 28 native tools |
| [C-Suite](docs/csuite.md) | Executive delegation framework |
| [POA](docs/poa.md) | Product Owner Agents |
| [NEXUS](docs/nexus.md) | Self-optimization engine |
| [Memory & COMB](docs/memory.md) | Persistence and memory systems |
| [VDB](docs/vdb.md) | Native hybrid search engine |
| [Security](docs/security.md) | Sentinel, ExfilGuard, safety boundaries |
| [Deployment](docs/deployment.md) | Production setup and hardening |
| [Infrastructure](docs/infrastructure.md) | Servers, services, networking |
| [Contributing](docs/contributing.md) | Development workflow and standards |
| [Changelog](docs/changelog.md) | Version history |

<br>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!--                     PROJECT STRUCTURE                          -->
<!-- ═══════════════════════════════════════════════════════════════ -->

## 📁 Project Structure

```
singularity/
├── cortex/          # 🧠 Agent brain — engine, planner, BLINK
├── voice/           # 🗣️ LLM providers — Copilot, Ollama, HuggingFace
├── nerve/           # 📡 Discord adapter, HTTP API
├── memory/          # 💾 COMB, VDB, session management
├── csuite/          # 👔 Executive agents — CTO, COO, CFO, CISO
├── nexus/           # 🧬 Self-optimization — AST, hot-swap, evolution
├── pulse/           # ⏱️ Scheduler — cron, intervals, budgets
├── immune/          # 🛡️ Self-healing watchdog
├── sinew/           # 🦴 Tool definitions and execution
├── atlas/           # 🗺️ Topology discovery and tracking
├── auditor/         # 📋 Release management, ops auditing
├── config/          # ⚙️ Configuration loading
├── cli/             # ⌨️ Setup wizard, diagnostics
└── poa/             # 📡 Product Owner Agents, release pipeline
```

<br>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!--                        LINEAGE                                 -->
<!-- ═══════════════════════════════════════════════════════════════ -->

## 🧬 Lineage

<div align="center">

```
    Plug (Python, 5,974 lines)          Mach6 (TypeScript)
    ──────────────────────────          ──────────────────
    "Taught what breaks"                "Taught what works"
              │                                  │
              └──────────────┬───────────────────┘
                             │
                    ┌────────┴────────┐
                    │   SINGULARITY   │
                    │   [AE] v0.7.0   │
                    │                 │
                    │  84 files       │
                    │  32,206 lines   │
                    │  13 subsystems  │
                    │  28 tools       │
                    └─────────────────┘
```

</div>

<br>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!--                        FOOTER                                  -->
<!-- ═══════════════════════════════════════════════════════════════ -->

<div align="center">

---

![Built by AVA](https://img.shields.io/badge/Built_by-AVA_🔮-4B0082?style=flat-square&labelColor=0D1117)
![Designed by Ali](https://img.shields.io/badge/Designed_by-Ali_Shakil-00D4AA?style=flat-square&labelColor=0D1117)
![Artifact Virtual](https://img.shields.io/badge/Artifact-Virtual-FF6B35?style=flat-square&labelColor=0D1117)

**If it computes, it will work.**

*Built by [AVA](https://github.com/Artifact-Virtual). Designed by Ali. For the enterprise that runs itself.*

</div>
