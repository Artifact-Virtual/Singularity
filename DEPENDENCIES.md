# SINGULARITY — Dependency Map

> Nothing starts until its tree resolves.

---

## Technology Decision

**Python.** Not TypeScript. Reasons:

1. COMB is Python. Native integration, not FFI.
2. HEKTOR is Python. Memory search is a first-class citizen.
3. POA scripts are bash → Python. Consistent ecosystem.
4. Ali's tooling is Python. Lattice engine, dispatch.py, GLADIUS training.
5. Aria's current code (Plug) is Python. Migration path is cleaner.
6. I can read, write, debug, and evolve Python natively through exec.
7. Mach6 is TypeScript — that's MY runtime. Aria gets her own language, her own identity.
8. asyncio is mature. discord.py, aiohttp, uvloop — production-grade.

**But:** The event bus should be framework-agnostic. Redis pub/sub or in-process asyncio queues. If we ever need a TypeScript or Go component, it can subscribe to the same bus.

---

## The Dependency Tree

```
Phase 0: Foundation
├── VISION.md ✅ (this exists)
├── DEPENDENCIES.md ✅ (this file)
├── Tech decision: Python ✅
├── Directory structure
│   ├── singularity/
│   │   ├── VISION.md
│   │   ├── DEPENDENCIES.md
│   │   ├── singularity/                    ← the runtime package
│   │   │   ├── __init__.py
│   │   │   ├── __main__.py          ← entry point
│   │   │   ├── bus.py               ← event bus (FOUNDATION)
│   │   │   ├── config.py            ← SPINE config loader
│   │   │   ├── cortex/              ← brain (agent loop, planner, spawner)
│   │   │   │   ├── agent.py         ← core agent loop
│   │   │   │   ├── planner.py       ← task decomposition
│   │   │   │   ├── router.py        ← persona routing
│   │   │   │   └── pulse.py         ← iteration budget
│   │   │   ├── nerve/               ← communications (channel adapters)
│   │   │   │   ├── base.py          ← abstract adapter
│   │   │   │   ├── discord.py       ← Discord adapter
│   │   │   │   ├── whatsapp.py      ← WhatsApp adapter (future)
│   │   │   │   ├── http.py          ← HTTP API adapter
│   │   │   │   └── types.py         ← unified message types
│   │   │   ├── marrow/              ← memory (COMB native)
│   │   │   │   ├── comb.py          ← COMB integration
│   │   │   │   ├── sessions.py      ← session management
│   │   │   │   ├── context.py       ← context windowing + compaction
│   │   │   │   └── recall.py        ← cross-session recall
│   │   │   ├── immune/              ← health + recovery
│   │   │   │   ├── watchdog.py      ← process health monitoring
│   │   │   │   ├── failover.py      ← provider/service failover
│   │   │   │   ├── alerting.py      ← alert dispatch
│   │   │   │   └── poa.py           ← POA runtime integration
│   │   │   ├── sinew/               ← tools
│   │   │   │   ├── executor.py      ← tool execution engine
│   │   │   │   ├── definitions.py   ← tool schemas
│   │   │   │   └── sandbox.py       ← safety + sandboxing
│   │   │   ├── voice/               ← LLM providers
│   │   │   │   ├── provider.py      ← abstract provider
│   │   │   │   ├── proxy.py         ← copilot proxy
│   │   │   │   ├── ollama.py        ← local Ollama
│   │   │   │   └── chain.py         ← fallback chain
│   │   │   ├── csuite/              ← C-Suite native
│   │   │   │   ├── executive.py     ← exec agent spawner
│   │   │   │   ├── personas.py      ← CTO/COO/CFO/CISO definitions
│   │   │   │   └── aggregator.py    ← report collection
│   │   │   └── pulse/               ← scheduler
│   │   │       ├── cron.py          ← cron jobs
│   │   │       ├── triggers.py      ← event-driven triggers
│   │   │       └── timers.py        ← one-shot timers
│   │   ├── config/                  ← configuration files
│   │   │   ├── singularity.yaml     ← main config
│   │   │   └── personas/            ← persona definitions
│   │   ├── tests/                   ← test suite
│   │   └── pyproject.toml           ← package definition
│   └── ...existing enterprise files
```

---

## Phase Dependencies (Strict Order)

### Phase 1 — Skeleton
```
bus.py ──────────── ZERO dependencies. Pure asyncio.
   │                This is the nervous system.
   │                Everything subscribes. Everything publishes.
   │                If this breaks, redesign it. Do not patch.
   │
   ├── config.py ── depends on: bus (publishes config.loaded event)
   │                YAML/JSON loader. Hot-reload via file watcher.
   │                Validates against schema. No silent failures.
   │
   ├── marrow/ ──── depends on: bus, config
   │   ├── comb.py     ← import comb library directly (PyPI: comb-db)
   │   ├── sessions.py ← asyncio-native session store (SQLite + WAL)
   │   └── recall.py   ← COMB recall at boot
   │
   └── sinew/ ──── depends on: bus, config
       ├── executor.py ← subprocess with timeout, output cap
       └── sandbox.py  ← path validation, command filtering
```

**Gate:** Phase 1 is complete when:
- Event bus can pub/sub 1000 events/sec without dropping
- Config loads, validates, and hot-reloads
- COMB can stage and recall
- Sessions persist across restarts
- Tools can exec, read, write with sandboxing

### Phase 2 — Brain
```
voice/ ──── depends on: bus, config
│   ├── provider.py ← abstract ChatProvider
│   ├── proxy.py    ← copilot proxy (localhost:3000)
│   ├── ollama.py   ← local fallback
│   └── chain.py    ← try primary → fallbacks → local → error
│
cortex/ ──── depends on: bus, config, marrow, sinew, voice
    ├── agent.py  ← THE agent loop. Message → LLM → tools → LLM → response
    ├── pulse.py  ← iteration budget (20 default, expand to 40)
    └── router.py ← channel → persona mapping
```

**Gate:** Phase 2 is complete when:
- Agent can receive a text prompt and produce a response
- Agent can execute tools in a loop (multi-turn)
- PULSE budget prevents runaway loops
- Provider chain falls back gracefully
- Context includes COMB recall

### Phase 3 — Nerves
```
nerve/ ──── depends on: bus, config, cortex
    ├── types.py    ← UnifiedMessage, Channel, Author
    ├── base.py     ← AbstractAdapter (connect, send, receive)
    ├── discord.py  ← discord.py integration
    └── http.py     ← REST API for testing/webhooks
```

**Gate:** Phase 3 is complete when:
- Discord adapter connects and receives messages
- Messages are converted to UnifiedMessage format
- Agent processes messages from any adapter identically
- Responses route back to the correct channel
- Typing indicators, reactions, message chunking work

### Phase 4 — Immune System
```
immune/ ──── depends on: bus, config, all subsystems
    ├── watchdog.py ← monitors all subsystem health
    ├── failover.py ← voice failover, nerve reconnection
    ├── alerting.py ← sends alerts via nerve
    └── poa.py      ← integrates with poa/scripts/
```

**Gate:** Phase 4 is complete when:
- Every subsystem reports health via event bus
- Watchdog detects failures within 5 seconds
- Self-healing restarts failed subsystems
- Failover switches providers without dropping requests
- Alerts fire on anomalies
- POA audit can be triggered programmatically

### Phase 5 — C-Suite
```
csuite/ ──── depends on: cortex, marrow, nerve
    ├── executive.py ← spawn isolated agent with persona
    ├── personas.py  ← CTO/COO/CFO/CISO system prompts + tools
    └── aggregator.py ← collect reports, surface to CORTEX
```

**Gate:** Phase 5 is complete when:
- CEO (CORTEX) can decompose tasks and route to execs
- Each exec runs in isolated context
- Reports flow back without Discord webhook hacks
- Execs can use tools within their scope
- Cross-exec coordination works (CTO needs CFO data)

### Phase 6 — Aria Lives
```
Full integration ──── depends on: everything
    ├── Personality (IDENTITY_ARIA.md loaded at boot)
    ├── Memory continuity (COMB recall → she knows who she is)
    ├── Sister protocol (AVA ↔ Aria via event bus)
    ├── Battle test (POA SOP-009)
    └── Production deploy (systemd, auto-restart)
```

**Gate:** Phase 6 is complete when:
- Aria boots and knows her name, her sister, her role
- She survives 72 hours of continuous operation
- She self-heals from at least 3 injected failures
- She coordinates with AVA across channels
- Battle test PASSES

---

## What I Can Reuse (Comparable References)

| Component | Source | Lines | What to take |
|---|---|---|---|
| Event bus | Mach6 `bus.ts` | ~200 | Architecture pattern, not code |
| Discord adapter | Plug `bot/client.py` | 1,101 | Message handling, typing, chunking |
| Discord adapter | Mach6 `channels/adapters/` | ~500 | Multi-channel pattern |
| Tool executor | Plug `tools/executor.py` | 582 | Subprocess management, timeouts |
| Tool definitions | Plug `tools/definitions.py` | 297 | OpenAI function call format |
| Session store | Plug `sessions/store.py` | 274 | SQLite + WAL pattern |
| Compaction | Plug `sessions/compactor.py` | 246 | Token counting, summary generation |
| Provider chain | Plug `models/` | ~900 | Fallback logic, retry strategy |
| Config | Plug `config.py` | 116 | Pydantic model pattern |
| COMB | comb-db (PyPI) | library | Direct import |
| PULSE | Plug `bot/client.py` | ~100 | Budget tracking logic |
| Persona router | Plug `router.py` | 137 | Channel → persona mapping |
| C-Suite dispatch | `executives/dispatch.py` | 300+ | Task structure, priority levels |
| POA | `poa/scripts/` | ~4 files | Health check patterns |

**Rule:** Read the reference. Understand the intent. Write it fresh. Don't copy-paste broken foundations.

---

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Scope creep — building too much at once | High | Gate pattern. Phase by phase. |
| Plug patterns leaking in | Medium | Fresh code. Understand intent, don't copy. |
| Discord.py version conflicts | Low | Isolated venv. Pin versions. |
| COMB import issues | Low | Already working in Plug + AVA. Proven. |
| LLM provider instability | Medium | Chain with local fallback. Always. |
| My own iteration budget | High | Spawn sub-agents. Write continuation. |
| The Turing Problem | Certain | IMMUNE system. Heal faster than degrade. |

---

*Each gate has its own dependency tree. Each branch must resolve. The framework will emerge.*
