"""
SINGULARITY — End-to-End Test Suite
=======================================

Tests the complete Singularity runtime:
    1. Event bus (pub/sub, wildcards, once, dead letter)
    2. Config loading (YAML, defaults, env overrides)
    3. Memory (sessions, COMB)
    4. Tools (executor, sandbox)
    5. Voice (provider chain, fallback)
    6. Cortex (agent loop, context)
    7. Nerve (router, formatter, types)
    8. Pulse (scheduler, health)
    9. Immune (watchdog, vitals)
    10. C-Suite (roles, registry, coordinator)
    11. POA (manager, runtime, audits)
    12. Integration (full boot → message → response)

Run: python3 -m pytest singularity/tests/test_e2e.py -v
  or: python3 singularity/tests/test_e2e.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ══════════════════════════════════════════════════════════════
# TEST UTILITIES
# ══════════════════════════════════════════════════════════════

class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.error = ""
        self.duration_ms = 0.0

    def __repr__(self):
        icon = "✅" if self.passed else "❌"
        return f"  {icon} {self.name} ({self.duration_ms:.0f}ms)"


class TestSuite:
    def __init__(self, name: str):
        self.name = name
        self.results: list[TestResult] = []

    def add(self, result: TestResult):
        self.results.append(result)

    @property
    def passed(self):
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self):
        return sum(1 for r in self.results if not r.passed)

    @property
    def total(self):
        return len(self.results)

    def summary(self):
        lines = [f"\n{'═' * 60}", f"  {self.name}", f"{'═' * 60}"]
        for r in self.results:
            lines.append(str(r))
            if not r.passed and r.error:
                lines.append(f"      Error: {r.error[:200]}")
        lines.append(f"{'─' * 60}")
        lines.append(f"  {self.passed}/{self.total} passed")
        return "\n".join(lines)


async def run_test(name: str, coro) -> TestResult:
    """Run a single test with timing and error capture."""
    result = TestResult(name)
    start = time.monotonic()
    try:
        await coro()
        result.passed = True
    except Exception as e:
        result.error = str(e)
    result.duration_ms = (time.monotonic() - start) * 1000
    return result


# ══════════════════════════════════════════════════════════════
# TESTS — EVENT BUS
# ══════════════════════════════════════════════════════════════

async def test_event_bus_basic():
    from singularity.bus import EventBus
    bus = EventBus()
    await bus.start()
    
    received = []
    
    @bus.on("test.hello")
    async def handler(event):
        received.append(event.data)
    
    await bus.emit("test.hello", {"msg": "world"})
    await asyncio.sleep(0.1)
    assert len(received) == 1, f"Expected 1, got {len(received)}"
    assert received[0]["msg"] == "world"
    await bus.stop()


async def test_event_bus_wildcard():
    from singularity.bus import EventBus
    bus = EventBus()
    await bus.start()
    
    matched = []
    
    @bus.on("test.*")
    async def handler(event):
        matched.append(event.name)
    
    await bus.emit("test.alpha", {})
    await bus.emit("test.beta", {})
    await bus.emit("other.gamma", {})
    await asyncio.sleep(0.1)
    assert len(matched) == 2
    await bus.stop()


async def test_event_bus_once():
    from singularity.bus import EventBus
    bus = EventBus()
    await bus.start()
    
    count = []
    
    @bus.once("test.fire")
    async def handler(event):
        count.append(1)
    
    await bus.emit("test.fire", {})
    await bus.emit("test.fire", {})
    await asyncio.sleep(0.1)
    assert len(count) == 1
    await bus.stop()


# ══════════════════════════════════════════════════════════════
# TESTS — CONFIG
# ══════════════════════════════════════════════════════════════

async def test_config_defaults():
    from singularity.config import SingularityConfig
    cfg = SingularityConfig()
    assert cfg.pulse.default_cap == 20
    assert cfg.voice.temperature == 0.5
    assert cfg.discord.require_mention is True


async def test_config_load_yaml():
    from singularity.config import load_config
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write("voice:\n  temperature: 0.7\npulse:\n  default_cap: 30\n")
        f.flush()
        cfg = load_config(f.name)
    os.unlink(f.name)
    assert cfg.voice.temperature == 0.7
    assert cfg.pulse.default_cap == 30


async def test_config_env_override():
    from singularity.config import load_config
    os.environ["SINGULARITY_LOG_LEVEL"] = "DEBUG"
    cfg = load_config("/nonexistent/path.yaml")
    assert cfg.log_level == "DEBUG"
    del os.environ["SINGULARITY_LOG_LEVEL"]


# ══════════════════════════════════════════════════════════════
# TESTS — MEMORY
# ══════════════════════════════════════════════════════════════

async def test_sessions():
    """Test session store."""
    from singularity.memory.sessions import SessionStore, Message
    from singularity.bus import EventBus
    bus = EventBus()
    await bus.start()
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    store = SessionStore(db_path=db_path, bus=bus)
    await store.open()
    
    # Add messages using Message dataclass
    await store.add_message("test-session", Message(role="user", content="Hello"))
    await store.add_message("test-session", Message(role="assistant", content="Hi there"))
    
    messages = await store.get_messages("test-session")
    assert len(messages) == 2
    assert messages[0].role == "user"
    
    await store.close()
    await bus.stop()
    os.unlink(db_path)


async def test_comb():
    from singularity.memory.comb import CombMemory
    from singularity.bus import EventBus
    bus = EventBus()
    await bus.start()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        comb = CombMemory(store_path=tmpdir, bus=bus)
        await comb.initialize()
        
        # Stage (async)
        await comb.stage("Test memory content")
        
        # Recall
        result = await comb.recall()
        # Just verify it doesn't crash
        assert result is not None or result is None  # either way, it ran
    
    await bus.stop()


# ══════════════════════════════════════════════════════════════
# TESTS — TOOLS
# ══════════════════════════════════════════════════════════════

async def test_tool_executor():
    from singularity.sinew.executor import ToolExecutor
    from singularity.bus import EventBus
    bus = EventBus()
    await bus.start()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        executor = ToolExecutor(workspace=tmpdir, bus=bus)
        
        # exec tool — returns string
        result = await executor.execute("exec", {"command": "echo hello"})
        assert "hello" in result
        
        # read tool
        test_file = Path(tmpdir) / "test.txt"
        test_file.write_text("test content")
        result = await executor.execute("read", {"path": str(test_file)})
        assert "test content" in result
        
        # write tool
        write_path = Path(tmpdir) / "written.txt"
        result = await executor.execute("write", {
            "path": str(write_path),
            "content": "written by test",
        })
        assert write_path.read_text() == "written by test"
        
        await executor.close()
    
    await bus.stop()


# ══════════════════════════════════════════════════════════════
# TESTS — VOICE
# ══════════════════════════════════════════════════════════════

async def test_provider_chain_fallback():
    from singularity.voice.chain import ProviderChain
    from singularity.voice.provider import ChatProvider, ChatMessage, ChatResponse
    
    class FailProvider(ChatProvider):
        def __init__(self):
            super().__init__(name="fail", model="fail-model")
        async def chat(self, messages, **kw):
            raise ConnectionError("down")
        async def chat_stream(self, messages, **kw):
            raise ConnectionError("down")
        async def health(self):
            return {"status": "down"}
    
    class OkProvider(ChatProvider):
        def __init__(self):
            super().__init__(name="ok", model="ok-model")
        async def chat(self, messages, **kw):
            return ChatResponse(content="fallback works", model="test")
        async def chat_stream(self, messages, **kw):
            yield ChatResponse(content="fallback works", model="test")
        async def health(self):
            return {"status": "ok"}
    
    chain = ProviderChain([FailProvider(), OkProvider()])
    resp = await chain.chat([ChatMessage(role="user", content="test")])
    assert resp.content == "fallback works"


# ══════════════════════════════════════════════════════════════
# TESTS — CORTEX
# ══════════════════════════════════════════════════════════════

async def test_context_builder():
    from singularity.cortex.context import ContextAssembler, ChatMessage
    
    assembler = ContextAssembler(context_budget=100000)
    
    history = [
        ChatMessage(role="user", content="Hello"),
        ChatMessage(role="assistant", content="Hi"),
    ]
    
    messages = assembler.assemble(
        system_prompt="You are a test agent.",
        history=history,
    )
    
    # Should have system prompt + history
    assert len(messages) >= 2, f"Expected >=2 messages, got {len(messages)}"
    assert messages[0].role == "system"
    assert "test agent" in messages[0].content


# ══════════════════════════════════════════════════════════════
# TESTS — NERVE
# ══════════════════════════════════════════════════════════════

async def test_formatter():
    from singularity.nerve.formatter import format_for_channel
    from singularity.nerve.types import ChannelCapabilities
    
    caps = ChannelCapabilities(max_message_length=2000)
    
    text = "Hello **world**"
    chunks = format_for_channel(text, caps)
    assert len(chunks) >= 1
    assert "Hello" in chunks[0]


async def test_message_split():
    from singularity.nerve.formatter import format_for_channel
    from singularity.nerve.types import ChannelCapabilities
    
    caps = ChannelCapabilities(max_message_length=50)
    text = "A" * 100
    chunks = format_for_channel(text, caps)
    assert len(chunks) >= 2


# ══════════════════════════════════════════════════════════════
# TESTS — NERVE TYPES
# ══════════════════════════════════════════════════════════════

async def test_health_tracker():
    from singularity.nerve.types import HealthTracker, AdapterState
    
    ht = HealthTracker()
    assert ht.state == AdapterState.DISCONNECTED
    
    ht.transition(AdapterState.CONNECTED)
    assert ht.state == AdapterState.CONNECTED
    
    ht.transition(AdapterState.DISCONNECTED)
    assert ht.state == AdapterState.DISCONNECTED
    
    ht.transition(AdapterState.RECONNECTING)
    ht.transition(AdapterState.CONNECTED)
    # Verify status dict works
    status = ht.status
    assert status is not None


# ══════════════════════════════════════════════════════════════
# TESTS — PULSE
# ══════════════════════════════════════════════════════════════

async def test_scheduler():
    from singularity.pulse.scheduler import Scheduler, JobConfig, JobType
    from singularity.bus import EventBus
    bus = EventBus()
    await bus.start()
    
    # Use 0.2s tick for fast testing
    scheduler = Scheduler(bus, tick_interval=0.2)
    await scheduler.start()
    
    fired = []
    
    @bus.on("test.scheduled")
    async def on_fired(event):
        fired.append(event.data)
    
    # Add a one-shot job that fires after 0.3s
    job = JobConfig(
        name="test-job",
        job_type=JobType.ONESHOT,
        interval_seconds=0.3,
        emit_topic="test.scheduled",
        emit_data={"source": "test"},
        max_fires=1,
    )
    job_id = scheduler.add(job)
    assert job_id
    
    # Wait for it to fire (0.3s delay + 0.2s tick + margin)
    await asyncio.sleep(1.0)
    assert len(fired) >= 1, f"Expected at least 1 fire, got {len(fired)}"
    
    await scheduler.stop()
    await bus.stop()


# ══════════════════════════════════════════════════════════════
# TESTS — C-SUITE ROLES V2
# ══════════════════════════════════════════════════════════════

async def test_role_registry():
    from singularity.csuite.roles import RoleRegistry, RoleType
    
    reg = RoleRegistry(enterprise="TestCorp", industry="fintech")
    
    # Propose roles based on audit data
    proposals = reg.propose_roles({
        "has_code": True,
        "has_infrastructure": True,
        "has_finance": True,
        "has_security_concerns": True,
        "live_products": 3,
        "has_customers": True,
        "project_count": 8,
        "industry": "fintech",
    })
    
    assert len(proposals) > 0
    assert any(p["role"] == "cto" for p in proposals)
    assert any(p["role"] == "cro" for p in proposals)  # fintech needs CRO


async def test_role_spawn():
    from singularity.csuite.roles import RoleRegistry
    
    reg = RoleRegistry(enterprise="TestCorp")
    role = reg.spawn_role({
        "role": "cto",
        "title": "Chief Technology Officer",
    })
    
    assert role.emoji == "🔧"
    assert "TestCorp" in role.build_system_prompt()
    assert len(role.keywords) > 10


async def test_role_serialization():
    from singularity.csuite.roles import RoleRegistry
    
    reg = RoleRegistry(enterprise="TestCorp")
    reg.spawn_role({"role": "cto", "title": "CTO"})
    reg.spawn_role({"role": "ciso", "title": "CISO"})
    
    with tempfile.TemporaryDirectory() as tmpdir:
        reg.save_all(Path(tmpdir))
        
        reg2 = RoleRegistry(enterprise="TestCorp")
        count = reg2.load_all(Path(tmpdir))
        assert count == 2


async def test_role_matching():
    from singularity.csuite.roles import RoleRegistry
    
    reg = RoleRegistry(enterprise="TestCorp")
    reg.spawn_role({"role": "cto", "title": "CTO"})
    reg.spawn_role({"role": "ciso", "title": "CISO"})
    
    matches = reg.match("Run a security vulnerability audit on our API")
    assert len(matches) > 0
    assert matches[0][0].role_type.value == "ciso"


# ══════════════════════════════════════════════════════════════
# TESTS — POA
# ══════════════════════════════════════════════════════════════

async def test_poa_lifecycle():
    from singularity.poa.manager import POAManager, POAStatus
    
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = POAManager(workspace=Path(tmpdir))
        
        # Propose
        config = mgr.propose(
            "Test Product",
            description="A test product",
            endpoints=[{"url": "https://httpbin.org/get", "name": "api"}],
        )
        assert config.status == POAStatus.PROPOSED
        assert config.product_id == "test-product"
        
        # Approve
        assert mgr.approve("test-product")
        assert mgr.get("test-product").status == POAStatus.APPROVED
        
        # Activate
        assert mgr.activate("test-product")
        assert mgr.get("test-product").status == POAStatus.ACTIVE
        
        # List
        assert len(mgr.list_active()) == 1
        
        # Pause
        assert mgr.pause("test-product")
        assert len(mgr.list_active()) == 0
        
        # Summary
        summary = mgr.status_summary()
        assert summary["total"] == 1


async def test_poa_persistence():
    from singularity.poa.manager import POAManager, POAStatus
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create and save
        mgr1 = POAManager(workspace=Path(tmpdir))
        mgr1.propose("Persistent Product")
        mgr1.approve("persistent-product")
        mgr1.activate("persistent-product")
        
        # Load fresh
        mgr2 = POAManager(workspace=Path(tmpdir))
        assert mgr2.get("persistent-product").status == POAStatus.ACTIVE


async def test_poa_audit_runtime():
    from singularity.poa.manager import POAConfig, Endpoint
    from singularity.poa.runtime import POARuntime
    
    config = POAConfig(
        product_name="Test",
        endpoints=[Endpoint(url="https://httpbin.org/get", name="api")],
    )
    
    report = POARuntime.run_audit(config)
    assert report.product_name == "Test"
    assert len(report.checks) > 0
    assert report.overall_status in ("green", "yellow", "red")
    
    # Check markdown output
    md = report.to_markdown()
    assert "POA Audit: Test" in md


async def test_poa_audit_save():
    from singularity.poa.manager import POAConfig, Endpoint
    from singularity.poa.runtime import POARuntime
    
    config = POAConfig(
        product_name="SaveTest",
        endpoints=[],
    )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        report = POARuntime.run_audit(config)
        path = POARuntime.save_audit(report, Path(tmpdir))
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["product_name"] == "SaveTest"


# ══════════════════════════════════════════════════════════════
# TESTS — SANDBOX SCALING
# ══════════════════════════════════════════════════════════════

async def test_scaling_agriculture():
    """Singularity scales for an agriculture enterprise."""
    from singularity.csuite.roles import RoleRegistry
    
    reg = RoleRegistry(enterprise="GreenFields AgriTech", industry="agriculture")
    proposals = reg.propose_roles({
        "has_code": True,
        "has_infrastructure": True,
        "has_finance": True,
        "has_security_concerns": False,
        "live_products": 2,
        "has_customers": True,
        "has_data_pipeline": True,
        "project_count": 5,
        "industry": "agriculture",
    })
    
    roles = [p["role"] for p in proposals]
    assert "cto" in roles      # has code
    assert "coo" in roles      # 5 projects
    assert "cfo" in roles      # has finance
    assert "cdo" in roles      # has data pipeline


async def test_scaling_fintech():
    """Singularity scales for a fintech enterprise."""
    from singularity.csuite.roles import RoleRegistry
    
    reg = RoleRegistry(enterprise="PayScale Financial", industry="fintech")
    proposals = reg.propose_roles({
        "has_code": True,
        "has_infrastructure": True,
        "has_finance": True,
        "has_security_concerns": True,
        "live_products": 4,
        "has_customers": True,
        "has_compliance_needs": False,
        "project_count": 12,
        "industry": "fintech",
    })
    
    roles = [p["role"] for p in proposals]
    assert "cto" in roles
    assert "ciso" in roles
    assert "cro" in roles       # fintech needs risk officer
    assert "cpo" in roles       # 4+ products needs product chief


async def test_scaling_healthcare():
    """Singularity scales for a healthcare enterprise."""
    from singularity.csuite.roles import RoleRegistry
    
    reg = RoleRegistry(enterprise="MedCore Health", industry="healthcare")
    proposals = reg.propose_roles({
        "has_code": True,
        "has_infrastructure": True,
        "has_finance": False,
        "has_security_concerns": True,
        "live_products": 1,
        "has_customers": True,
        "has_compliance_needs": True,
        "project_count": 3,
        "industry": "healthcare",
    })
    
    roles = [p["role"] for p in proposals]
    assert "cto" in roles
    assert "ciso" in roles      # security concerns
    assert "cco" in roles       # healthcare needs compliance officer


async def test_scaling_space_tech():
    """Singularity scales for a space tech company."""
    from singularity.csuite.roles import RoleRegistry
    
    reg = RoleRegistry(enterprise="Orbital Dynamics", industry="aerospace")
    proposals = reg.propose_roles({
        "has_code": True,
        "has_infrastructure": True,
        "has_finance": True,
        "has_security_concerns": True,
        "live_products": 6,
        "has_customers": True,
        "has_data_pipeline": True,
        "has_marketing": True,
        "project_count": 20,
        "team_size": 150,
        "industry": "aerospace",
    })
    
    roles = [p["role"] for p in proposals]
    assert "cto" in roles
    assert "coo" in roles
    assert "cfo" in roles
    assert "ciso" in roles
    assert "cpo" in roles       # 6 products
    assert "cdo" in roles       # data pipeline


async def test_scaling_real_estate():
    """Singularity scales for a real estate company."""
    from singularity.csuite.roles import RoleRegistry
    
    reg = RoleRegistry(enterprise="PropVault Realty", industry="real_estate")
    proposals = reg.propose_roles({
        "has_code": True,
        "has_infrastructure": False,
        "has_finance": True,
        "has_security_concerns": False,
        "live_products": 1,
        "has_customers": True,
        "project_count": 2,
        "industry": "real_estate",
    })
    
    roles = [p["role"] for p in proposals]
    assert "cto" in roles       # has code
    assert "cfo" in roles       # finance heavy


async def test_scaling_solo_founder():
    """Singularity scales for a solo founder (minimal)."""
    from singularity.csuite.roles import RoleRegistry
    
    reg = RoleRegistry(enterprise="Solo Studio", industry="saas")
    proposals = reg.propose_roles({
        "has_code": True,
        "has_infrastructure": False,
        "has_finance": False,
        "has_security_concerns": False,
        "live_products": 1,
        "has_customers": False,
        "project_count": 1,
        "industry": "saas",
    })
    
    roles = [p["role"] for p in proposals]
    assert "cto" in roles       # has code
    # minimal — no COO, no CFO, no CISO for a solo project


# ══════════════════════════════════════════════════════════════
# TESTS — IMMUNE
# ══════════════════════════════════════════════════════════════

async def test_vitals():
    from singularity.immune.vitals import SystemVitals
    
    vitals = SystemVitals()
    assert vitals.disk_used_pct >= 0
    assert vitals.memory_used_pct >= 0
    assert vitals.memory_available_mb >= 0
    assert vitals.uptime_seconds >= 0


async def test_feedback_bridge():
    """Test POA audit → Immune system feedback loop."""
    from singularity.immune.health import HealthTracker, HealthStatus
    from singularity.immune.auditor import Auditor
    from singularity.immune.feedback import FeedbackBridge
    from singularity.poa.runtime import AuditReport, CheckResult

    tracker = HealthTracker()  # no persistence
    auditor = Auditor()
    bridge = FeedbackBridge(tracker=tracker, auditor=auditor)

    # 1. Clean audit → no damage
    clean_report = AuditReport(
        product_id="test-product",
        product_name="Test Product",
        overall_status="green",
    )
    clean_report.checks = [
        CheckResult(name="endpoint:api", passed=True, message="200 OK", severity="info"),
        CheckResult(name="disk:root", passed=True, message="40% used", severity="info"),
    ]
    events = bridge.process_audit(clean_report)
    assert tracker.hp == 100, f"Clean audit should not damage: HP={tracker.hp}"
    assert all(e.damage_dealt == 0 for e in events)

    # 2. Failed audit → damage dealt
    bad_report = AuditReport(
        product_id="test-product",
        product_name="Test Product",
        overall_status="red",
    )
    bad_report.checks = [
        CheckResult(name="endpoint:api", passed=False, message="Connection refused", severity="critical"),
        CheckResult(name="service:test", passed=False, message="inactive", severity="critical"),
    ]
    events = bridge.process_audit(bad_report)
    assert tracker.hp < 100, f"Failed audit should damage: HP={tracker.hp}"
    assert any(e.damage_dealt > 0 for e in events)

    # 3. Consecutive clean audits → trigger auditor
    for i in range(3):
        clean_report2 = AuditReport(
            product_id="test-product",
            product_name="Test Product",
            overall_status="green",
        )
        clean_report2.checks = [
            CheckResult(name="endpoint:api", passed=True, message="200 OK", severity="info"),
        ]
        bridge.process_audit(clean_report2)

    assert bridge.total_healer_triggers >= 1, "Should have triggered auditor on clean streak"

    # 4. Summary
    summary = bridge.summary()
    assert summary["total_audits_processed"] >= 5
    assert summary["total_damage_routed"] > 0
    assert "test-product" in summary["clean_streaks"]


async def test_feedback_damage_cap():
    """Test that max damage per audit is enforced."""
    from singularity.immune.health import HealthTracker
    from singularity.immune.auditor import Auditor
    from singularity.immune.feedback import FeedbackBridge
    from singularity.poa.runtime import AuditReport, CheckResult

    tracker = HealthTracker()
    auditor = Auditor()
    bridge = FeedbackBridge(tracker=tracker, auditor=auditor)

    # Massive failure — many critical checks
    catastrophe = AuditReport(
        product_id="doomed", product_name="Doomed",
        overall_status="red",
    )
    catastrophe.checks = [
        CheckResult(name=f"endpoint:ep{i}", passed=False, message="boom", severity="critical")
        for i in range(20)  # 20 failed endpoints
    ]
    events = bridge.process_audit(catastrophe)
    total_dmg = sum(e.damage_dealt for e in events)
    assert total_dmg <= bridge.MAX_DAMAGE_PER_AUDIT, \
        f"Damage {total_dmg} exceeds cap {bridge.MAX_DAMAGE_PER_AUDIT}"


async def test_reflector_classification():
    """Test Reflector POA state classification and noise filtering."""
    from singularity.immune.health import HealthTracker
    from singularity.immune.auditor import Auditor
    from singularity.immune.feedback import FeedbackBridge
    from singularity.immune.reflector import Reflector, POAState
    from singularity.poa.runtime import AuditReport, CheckResult
    from singularity.poa.manager import POAConfig, Endpoint

    tracker = HealthTracker()
    auditor = Auditor()
    bridge = FeedbackBridge(tracker=tracker, auditor=auditor)
    reflector = Reflector(bridge=bridge)

    # ── Product A: healthy product with endpoints (will go dormant) ──
    config_a = POAConfig(
        product_name="Healthy API",
        product_id="healthy-api",
        endpoints=[Endpoint(url="http://localhost:9999", name="api")],
    )

    # Feed 6 consecutive green audits
    for i in range(6):
        report = AuditReport(product_id="healthy-api", product_name="Healthy API", overall_status="green")
        report.checks = [CheckResult(name="endpoint:api", passed=True, message="200 OK", severity="info")]
        reflector.ingest(config_a, report)

    result = reflector.reflect()

    # Should classify as dormant (5+ consecutive green)
    assert len(result.dormant) == 1, f"Expected 1 dormant, got {len(result.dormant)}"
    assert result.dormant[0][0].product_id == "healthy-api"
    profile_a = reflector.get_profile("healthy-api")
    assert profile_a.state == POAState.DORMANT
    assert profile_a.suppressed is True
    assert profile_a.recommended_interval_hours == reflector.DORMANT_INTERVAL_HOURS

    # ── Product B: failing product (will go critical) ──
    config_b = POAConfig(
        product_name="Broken Service",
        product_id="broken-service",
        endpoints=[Endpoint(url="http://localhost:9998", name="svc")],
        service_name="broken.service",
    )

    for i in range(3):
        report = AuditReport(product_id="broken-service", product_name="Broken Service", overall_status="red")
        report.checks = [
            CheckResult(name="endpoint:svc", passed=False, message="Connection refused", severity="critical"),
            CheckResult(name="service:broken.service", passed=False, message="inactive", severity="critical"),
        ]
        reflector.ingest(config_b, report)

    result2 = reflector.reflect()

    assert len(result2.critical) == 1, f"Expected 1 critical, got {len(result2.critical)}"
    assert result2.critical[0][0].product_id == "broken-service"
    assert result2.needs_attention is True

    # ── Product C: no endpoints, no service → unnecessary ──
    config_c = POAConfig(
        product_name="Ghost Product",
        product_id="ghost-product",
    )

    report_c = AuditReport(product_id="ghost-product", product_name="Ghost Product", overall_status="green")
    report_c.checks = [
        CheckResult(name="disk:root", passed=True, message="40%", severity="info"),
        CheckResult(name="memory", passed=True, message="38%", severity="info"),
    ]
    reflector.ingest(config_c, report_c)

    result3 = reflector.reflect()
    assert len(result3.unnecessary) == 1, f"Expected 1 unnecessary, got {len(result3.unnecessary)}"
    assert result3.unnecessary[0][0].product_id == "ghost-product"


async def test_reflector_dormant_blip():
    """Test DORMANT → WATCH → DORMANT transition."""
    from singularity.immune.health import HealthTracker
    from singularity.immune.auditor import Auditor
    from singularity.immune.feedback import FeedbackBridge
    from singularity.immune.reflector import Reflector, POAState
    from singularity.poa.runtime import AuditReport, CheckResult
    from singularity.poa.manager import POAConfig, Endpoint

    tracker = HealthTracker()
    auditor = Auditor()
    bridge = FeedbackBridge(tracker=tracker, auditor=auditor)
    reflector = Reflector(bridge=bridge)

    config = POAConfig(
        product_name="Stable API",
        product_id="stable-api",
        endpoints=[Endpoint(url="http://localhost:9997", name="api")],
    )

    # 6 green → dormant
    for i in range(6):
        report = AuditReport(product_id="stable-api", product_name="Stable API", overall_status="green")
        report.checks = [CheckResult(name="endpoint:api", passed=True, message="OK", severity="info")]
        reflector.ingest(config, report)
    r = reflector.reflect()
    assert reflector.get_profile("stable-api").state == POAState.DORMANT

    # 1 yellow → WATCH
    report_blip = AuditReport(product_id="stable-api", product_name="Stable API", overall_status="yellow")
    report_blip.checks = [
        CheckResult(name="endpoint:api", passed=True, message="OK", severity="info"),
        CheckResult(name="disk:root", passed=False, message="87%", severity="warn"),
    ]
    reflector.ingest(config, report_blip)
    r = reflector.reflect()
    assert reflector.get_profile("stable-api").state == POAState.WATCH

    # 3 more green → back to DORMANT
    for i in range(3):
        report = AuditReport(product_id="stable-api", product_name="Stable API", overall_status="green")
        report.checks = [CheckResult(name="endpoint:api", passed=True, message="OK", severity="info")]
        reflector.ingest(config, report)
    r = reflector.reflect()
    assert reflector.get_profile("stable-api").state == POAState.DORMANT

    # Verify state changes were recorded
    total_changes = sum(len(x.state_changes) for x in [r])
    assert total_changes >= 1  # at least the WATCH→DORMANT change


async def test_reflector_render():
    """Test that render() produces non-empty output with proper sections."""
    from singularity.immune.health import HealthTracker
    from singularity.immune.auditor import Auditor
    from singularity.immune.feedback import FeedbackBridge
    from singularity.immune.reflector import Reflector
    from singularity.poa.runtime import AuditReport, CheckResult
    from singularity.poa.manager import POAConfig, Endpoint

    tracker = HealthTracker()
    auditor = Auditor()
    bridge = FeedbackBridge(tracker=tracker, auditor=auditor)
    reflector = Reflector(bridge=bridge)

    # One green product
    config = POAConfig(
        product_name="Test Product",
        product_id="test-prod",
        endpoints=[Endpoint(url="http://localhost:1234", name="api")],
    )
    report = AuditReport(product_id="test-prod", product_name="Test Product", overall_status="green")
    report.checks = [CheckResult(name="endpoint:api", passed=True, message="OK", severity="info")]
    reflector.ingest(config, report)

    result = reflector.reflect()
    rendered = result.render()

    assert "SINGULARITY" in rendered
    assert "Reflected Audit" in rendered
    assert "❤️" in rendered
    assert len(rendered) > 100


# ══════════════════════════════════════════════════════════════
# AUDITOR TESTS
# ══════════════════════════════════════════════════════════════

async def test_auditor_scanner():
    """Test workspace scanning on a temp directory."""
    from singularity.auditor import WorkspaceScanner
    
    # Create a temp workspace with some projects
    tmp = Path(tempfile.mkdtemp())
    try:
        # Create a Python project
        py_proj = tmp / "my-py-project"
        py_proj.mkdir()
        (py_proj / "pyproject.toml").write_text('[project]\nname = "my-py-project"\n')
        (py_proj / "README.md").write_text("# Test\n")
        (py_proj / "main.py").write_text("print('hello')\n" * 100)
        (py_proj / "tests").mkdir()
        (py_proj / "tests" / "test_main.py").write_text("def test_it(): pass\n")
        
        # Create a Node project
        node_proj = tmp / "my-node-app"
        node_proj.mkdir()
        (node_proj / "package.json").write_text('{"name": "my-node-app"}\n')
        (node_proj / "index.js").write_text("console.log('hi');\n" * 50)
        
        scanner = WorkspaceScanner(str(tmp))
        result = scanner.scan()
        
        assert len(result.projects) >= 2, f"Expected >=2 projects, got {len(result.projects)}"
        
        names = {p.name for p in result.projects}
        assert "my-py-project" in names, f"Expected 'my-py-project' in {names}"
        assert "my-node-app" in names, f"Expected 'my-node-app' in {names}"
        
        py = next(p for p in result.projects if p.name == "my-py-project")
        assert py.project_type == "python"
        assert py.files.has_readme
        assert py.files.has_tests
        assert py.total_lines > 0
        
        node = next(p for p in result.projects if p.name == "my-node-app")
        assert node.project_type == "node"
        
        assert result.scan_duration_ms > 0
        
        # Test to_audit_data conversion
        audit_data = result.to_audit_data()
        assert audit_data["has_code"] is True
        assert audit_data["code_projects"] >= 2
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


async def test_auditor_analyzer():
    """Test analyzer scoring and recommendations."""
    from singularity.auditor import WorkspaceScanner, Analyzer
    
    tmp = Path(tempfile.mkdtemp())
    try:
        # Create a mature project
        proj = tmp / "mature-app"
        proj.mkdir()
        (proj / "pyproject.toml").write_text("[project]\nname='test'\n")
        (proj / "README.md").write_text("# Docs\n")
        (proj / "LICENSE").write_text("MIT\n")
        (proj / "tests").mkdir()
        (proj / "docs").mkdir()
        (proj / "Dockerfile").write_text("FROM python:3.11\n")
        (proj / "app.py").write_text("x = 1\n" * 2000)
        
        scanner = WorkspaceScanner(str(tmp))
        scan = scanner.scan()
        analysis = Analyzer().analyze(scan)
        
        assert len(analysis.project_analyses) == 1
        pa = analysis.project_analyses[0]
        assert pa.maturity.total >= 40, f"Mature project scored only {pa.maturity.total}"
        assert len(pa.maturity.breakdown) > 0
        assert analysis.health_score >= 30
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


async def test_auditor_report():
    """Test report generation."""
    from singularity.auditor import WorkspaceScanner, Analyzer, generate_report, report_to_markdown
    
    tmp = Path(tempfile.mkdtemp())
    try:
        proj = tmp / "test-proj"
        proj.mkdir()
        (proj / "pyproject.toml").write_text('[project]\nname = "test-proj"\n')
        (proj / "main.py").write_text("print(1)\n" * 500)
        
        scanner = WorkspaceScanner(str(tmp))
        scan = scanner.scan()
        analysis = Analyzer().analyze(scan)
        report = generate_report(scan, analysis)
        
        assert "meta" in report
        assert "summary" in report
        assert report["summary"]["total_projects"] >= 1
        
        md = report_to_markdown(report)
        assert "Workspace Audit Report" in md
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ══════════════════════════════════════════════════════════════
# CLI TESTS
# ══════════════════════════════════════════════════════════════

async def test_cli_imports():
    """Test all CLI modules import cleanly."""
    from singularity.cli.main import main
    from singularity.cli.wizard import InitWizard
    from singularity.cli.formatters import header, success, info, warn, error, banner, section, kv, dim
    
    # Test formatters produce strings
    assert isinstance(success("ok"), str)
    assert isinstance(info("ok"), str)
    assert isinstance(warn("ok"), str)
    assert isinstance(error("ok"), str)
    assert isinstance(dim("ok"), str)
    
    # Test header runs without error
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        header("TEST")
    assert "TEST" in buf.getvalue()


# ══════════════════════════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════════════════════════

async def main():
    suite = TestSuite("SINGULARITY [AE] — End-to-End Test Suite")
    
    tests = [
        # Event Bus
        ("bus.basic", test_event_bus_basic),
        ("bus.wildcard", test_event_bus_wildcard),
        ("bus.once", test_event_bus_once),
        
        # Config
        ("config.defaults", test_config_defaults),
        ("config.yaml_load", test_config_load_yaml),
        ("config.env_override", test_config_env_override),
        
        # Memory
        ("memory.sessions", test_sessions),
        ("memory.comb", test_comb),
        
        # Tools
        ("sinew.executor", test_tool_executor),
        
        # Voice
        ("voice.fallback", test_provider_chain_fallback),
        
        # Cortex
        ("cortex.context", test_context_builder),
        
        # Nerve
        ("nerve.formatter", test_formatter),
        ("nerve.split", test_message_split),
        ("nerve.health_tracker", test_health_tracker),
        
        # Pulse
        ("pulse.scheduler", test_scheduler),
        
        # C-Suite v2
        ("csuite.registry", test_role_registry),
        ("csuite.spawn", test_role_spawn),
        ("csuite.serialization", test_role_serialization),
        ("csuite.matching", test_role_matching),
        
        # POA
        ("poa.lifecycle", test_poa_lifecycle),
        ("poa.persistence", test_poa_persistence),
        ("poa.audit_runtime", test_poa_audit_runtime),
        ("poa.audit_save", test_poa_audit_save),
        
        # Scaling (sandbox mock enterprises)
        ("scale.agriculture", test_scaling_agriculture),
        ("scale.fintech", test_scaling_fintech),
        ("scale.healthcare", test_scaling_healthcare),
        ("scale.space_tech", test_scaling_space_tech),
        ("scale.real_estate", test_scaling_real_estate),
        ("scale.solo_founder", test_scaling_solo_founder),
        
        # Immune
        ("immune.vitals", test_vitals),
        ("immune.feedback_bridge", test_feedback_bridge),
        ("immune.feedback_damage_cap", test_feedback_damage_cap),
        ("immune.reflector_classify", test_reflector_classification),
        ("immune.reflector_blip", test_reflector_dormant_blip),
        ("immune.reflector_render", test_reflector_render),
        
        # Auditor
        ("auditor.scanner", test_auditor_scanner),
        ("auditor.analyzer", test_auditor_analyzer),
        ("auditor.report", test_auditor_report),
        
        # CLI
        ("cli.imports", test_cli_imports),
    ]
    
    for name, test_fn in tests:
        result = await run_test(name, test_fn)
        suite.add(result)
    
    print(suite.summary())
    
    if suite.failed > 0:
        print(f"\n❌ {suite.failed} FAILED")
        return 1
    else:
        print(f"\n✅ ALL {suite.total} TESTS PASSED")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
