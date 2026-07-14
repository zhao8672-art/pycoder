"""
V2 核心模块测试 — 总线、安全、能力、引擎

运行: pytest tests/v2/ -v
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

# ── 总线测试 ───────────────────────────────


class TestCapabilityRegistry:
    """能力注册表测试"""

    def test_register_and_list(self):
        from pycoder.bus.registry import CapabilityRegistry
        from pycoder.bus.protocol import (
            CapabilityCategory, CapabilityDefinition,
            ExecutionMode, SideEffect, TrustLevel,
        )

        registry = CapabilityRegistry()
        assert registry.count == 0

        cap = CapabilityDefinition(
            id="test.read",
            name="测试读取",
            description="测试用读取能力",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            side_effects=[SideEffect.FILE_READ],
            tags=["test"],
        )

        async def handler(params, ctx):
            return {"ok": True}

        registry.register(cap, handler=handler)
        assert registry.count == 1
        assert registry.exists("test.read")
        assert registry.get("test.read").name == "测试读取"

    def test_search_by_keyword(self):
        from pycoder.bus.registry import CapabilityRegistry
        from pycoder.bus.protocol import CapabilityCategory, CapabilityDefinition, TrustLevel

        registry = CapabilityRegistry()

        for i, kw in enumerate(["读取文件", "写入文件", "Git提交", "执行命令"]):
            registry.register(CapabilityDefinition(
                id=f"test.{i}", name=kw, description=f"测试{i}",
                category=CapabilityCategory.EDITOR,
                permission=TrustLevel.READ_ONLY,
                tags=["测试"],
            ))

        results = registry.search("读取")
        assert len(results) >= 1
        assert any("读取" in r.name for r in results)

        results = registry.search("git")
        assert len(results) >= 1
        assert any("git" in r.name.lower() for r in results)

    def test_search_by_description(self):
        from pycoder.bus.registry import CapabilityRegistry
        from pycoder.bus.protocol import CapabilityCategory, CapabilityDefinition, TrustLevel

        registry = CapabilityRegistry()

        registry.register(CapabilityDefinition(
            id="editor.code.write", name="写入代码文件",
            description="将内容写入指定路径的文件",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.WORKSPACE_WRITE,
            tags=["write", "写入", "文件"],
        ))

        results = registry.search_by_description("我想修改一个文件")
        assert len(results) >= 1

    def test_async_call(self):
        from pycoder.bus.registry import CapabilityRegistry
        from pycoder.bus.protocol import CapabilityCall, CapabilityCategory, CapabilityDefinition, TrustLevel

        registry = CapabilityRegistry()

        async def handler(params, ctx):
            return {"result": params.get("value", 0) * 2}

        registry.register(
            CapabilityDefinition(
                id="test.double",
                name="Double",
                description="Double a value",
                category=CapabilityCategory.SYSTEM,
                permission=TrustLevel.READ_ONLY,
            ),
            handler=handler,
        )

        result = asyncio.run(registry.call(
            CapabilityCall(capability_id="test.double", params={"value": 21}),
        ))
        assert result.success
        assert result.data["result"] == 42

    def test_call_nonexistent(self):
        from pycoder.bus.registry import CapabilityRegistry
        from pycoder.bus.protocol import CapabilityCall

        registry = CapabilityRegistry()
        result = asyncio.run(registry.call(
            CapabilityCall(capability_id="nonexistent.capability", params={}),
        ))
        assert not result.success
        assert result.error_code == "CAPABILITY_NOT_FOUND"


class TestIntelligentRouter:
    """智能路由器测试"""

    def test_exact_match(self):
        from pycoder.bus.registry import CapabilityRegistry
        from pycoder.bus.router import IntelligentRouter
        from pycoder.bus.protocol import CapabilityCategory, CapabilityDefinition, TrustLevel

        registry = CapabilityRegistry()
        registry.register(CapabilityDefinition(
            id="test.hello", name="Hello", description="Test",
            category=CapabilityCategory.SYSTEM, permission=TrustLevel.READ_ONLY,
        ))

        router = IntelligentRouter(registry)
        decision = router.route("test.hello")
        assert decision.confidence == 1.0
        assert decision.capability_id == "test.hello"

    def test_semantic_fallback(self):
        from pycoder.bus.registry import CapabilityRegistry
        from pycoder.bus.router import IntelligentRouter
        from pycoder.bus.protocol import CapabilityCategory, CapabilityDefinition, TrustLevel

        registry = CapabilityRegistry()
        registry.register(CapabilityDefinition(
            id="system.git.status", name="Git Status",
            description="查看Git状态",
            category=CapabilityCategory.SYSTEM, permission=TrustLevel.READ_ONLY,
            tags=["git"],
        ))

        router = IntelligentRouter(registry)
        decision = router.route("git")
        assert decision.confidence > 0
        assert "git" in decision.capability_id


# ── 安全测试 ───────────────────────────────


class TestPermissionEngine:
    """权限引擎测试"""

    def test_read_always_allowed(self):
        from pycoder.safety.permission import PermissionEngine
        from pycoder.bus.protocol import TrustLevel

        engine = PermissionEngine(TrustLevel.WORKSPACE_WRITE)
        decision = engine.check("editor.code.read", TrustLevel.READ_ONLY)
        assert decision.allowed

    def test_higher_level_requires_confirm(self):
        from pycoder.safety.permission import PermissionEngine
        from pycoder.bus.protocol import TrustLevel

        engine = PermissionEngine(TrustLevel.WORKSPACE_WRITE)
        decision = engine.check("system.package.install", TrustLevel.SYSTEM_ACCESS)
        assert not decision.allowed
        assert decision.requires_user_confirm

    def test_full_autonomy_denied_at_lower_trust(self):
        from pycoder.safety.permission import PermissionEngine
        from pycoder.bus.protocol import TrustLevel

        engine = PermissionEngine(TrustLevel.WORKSPACE_WRITE)
        decision = engine.check("self_evo.code.apply_fix", TrustLevel.FULL_AUTONOMY)
        assert not decision.allowed

    def test_escalate_trust_needs_history(self):
        from pycoder.safety.permission import PermissionEngine
        from pycoder.bus.protocol import TrustLevel

        engine = PermissionEngine(TrustLevel.WORKSPACE_WRITE)
        ok, msg = engine.escalate_trust()
        assert not ok  # 需要 50 次行为记录

    def test_emergency_lockdown(self):
        from pycoder.safety.permission import PermissionEngine
        from pycoder.bus.protocol import TrustLevel

        engine = PermissionEngine(TrustLevel.SYSTEM_ACCESS)
        engine.emergency_lockdown()
        assert engine.current_trust == TrustLevel.READ_ONLY


class TestCircuitBreaker:
    """熔断器测试"""

    def test_normal_state(self):
        from pycoder.safety.circuit_breaker import CircuitBreaker

        breaker = CircuitBreaker("test")
        assert breaker.state.value == "closed"
        assert not breaker.is_open

    def test_trip_on_failures(self):
        from pycoder.safety.circuit_breaker import CircuitBreaker

        breaker = CircuitBreaker("test")
        for _ in range(10):
            breaker.record_failure()
        assert breaker.is_open

    def test_before_call_blocks_when_open(self):
        from pycoder.safety.circuit_breaker import CircuitBreaker

        breaker = CircuitBreaker("test")
        for _ in range(10):
            breaker.record_failure()
        assert not breaker.before_call()

    def test_reset(self):
        from pycoder.safety.circuit_breaker import CircuitBreaker

        breaker = CircuitBreaker("test")
        for _ in range(10):
            breaker.record_failure()
        breaker.reset()
        assert breaker.state.value == "closed"


# ── V2 引擎测试 ────────────────────────────


class TestV2Engine:
    """V2 引擎集成测试"""

    def test_initialize(self):
        from pycoder.v2 import V2Engine, V2EngineConfig

        engine = V2Engine(V2EngineConfig(workspace_root=os.getcwd()))
        asyncio.run(engine.initialize())
        assert engine.registry.count >= 19
        assert engine.permission.current_trust.value >= 1

    def test_call_env_detect(self):
        from pycoder.v2 import V2Engine, V2EngineConfig

        engine = V2Engine(V2EngineConfig(workspace_root=os.getcwd()))
        asyncio.run(engine.initialize())
        result = asyncio.run(engine.call("system.env.detect", {}, force=True))
        assert result.success
        assert "python_version" in result.data

    def test_call_git_status(self):
        from pycoder.v2 import V2Engine, V2EngineConfig

        engine = V2Engine(V2EngineConfig(workspace_root=os.getcwd()))
        asyncio.run(engine.initialize())
        result = asyncio.run(engine.call("system.git.status", {}, force=True))
        assert result.success

    def test_call_search(self):
        from pycoder.v2 import V2Engine, V2EngineConfig

        engine = V2Engine(V2EngineConfig(workspace_root=os.getcwd()))
        asyncio.run(engine.initialize())
        result = asyncio.run(engine.call(
            "editor.code.search", {"query": "class", "max_results": 3}, force=True,
        ))
        assert result.success
        assert result.data["matches"] >= 0

    def test_audit_trail(self):
        from pycoder.v2 import V2Engine, V2EngineConfig

        engine = V2Engine(V2EngineConfig(workspace_root=os.getcwd()))
        asyncio.run(engine.initialize())
        asyncio.run(engine.call("system.env.detect", {}, force=True))
        assert engine.audit.record_count >= 1

    def test_task_planning(self):
        from pycoder.v2 import V2Engine, V2EngineConfig

        engine = V2Engine(V2EngineConfig(workspace_root=os.getcwd()))
        asyncio.run(engine.initialize())
        plan = engine.planner.plan("创建用户认证模块")
        assert len(plan.tasks) >= 3
        assert plan.strategy.value in ("single_agent", "parallel_agents", "sdlc_pipeline")

    def test_self_evo_with_evo_enabled(self):
        from pycoder.v2 import V2Engine, V2EngineConfig

        engine = V2Engine(V2EngineConfig(workspace_root=os.getcwd(), enable_self_evo=True))
        asyncio.run(engine.initialize())
        assert engine.evolution is not None
        assert engine.registry.count >= 30


class TestSelfEvolutionEngine:
    """自进化引擎测试"""

    def test_scan_clean_code(self):
        from pycoder.v2 import V2Engine, V2EngineConfig

        engine = V2Engine(V2EngineConfig(workspace_root=os.getcwd(), enable_self_evo=True))
        asyncio.run(engine.initialize())
        report = asyncio.run(engine.evolution.scan("pycoder/bus", use_llm=False))
        assert report.files_scanned > 0
        assert isinstance(report.total_issues, int)

    def test_generate_template_fix(self):
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine, CodeIssue

        # 直接测试模板修复，不依赖 LLM
        engine = SelfEvolutionEngine(None, None)

        issue = CodeIssue(
            file="test.py", line=10, severity="high", issue_type="bug",
            title="裸 except 吞掉所有异常",
            suggestion="将 'except:' 替换为 'except Exception as e:'",
        )

        proposal = asyncio.run(engine.generate_fix(issue))
        assert proposal.action == "replace"
        assert "except" in proposal.old_code.lower() or proposal.reasoning

    def test_evolution_persistence(self):
        from pycoder.v2 import V2Engine, V2EngineConfig
        from pycoder.capabilities.self_evo.engine import EvolutionRecord

        engine = V2Engine(V2EngineConfig(workspace_root=os.getcwd(), enable_self_evo=True))
        asyncio.run(engine.initialize())

        engine.evolution.record_evolution(EvolutionRecord(
            action="test", issue_type="bug", file="test.py",
            success=True, fix_description="test fix",
        ))

        stats = engine.evolution.get_stats()
        assert stats["total_evolutions"] >= 1

        # 验证持久化
        history_path = Path.home() / ".pycoder" / "evolution_history.json"
        assert history_path.exists()


class TestMemoryEngine:
    """记忆引擎测试"""

    def test_working_memory_add_and_retrieve(self):
        from pycoder.brain.memory_engine import WorkingMemory

        wm = WorkingMemory(max_items=10)
        wm.add("key1", "这是测试内容", importance=0.8, tags=["test"])
        item = wm.get("key1")
        assert item is not None
        assert item.content == "这是测试内容"

    def test_working_memory_search(self):
        from pycoder.brain.memory_engine import WorkingMemory

        wm = WorkingMemory()
        wm.add("auth", "JWT认证模块", tags=["auth"])
        wm.add("user", "用户管理API", tags=["user", "api"])

        results = wm.search("认证")
        assert len(results) >= 1
        results2 = wm.search("api")
        assert len(results2) >= 1

    def test_memory_engine_recall(self):
        from pycoder.brain.memory_engine import MemoryEngine

        mem = MemoryEngine()
        mem.remember("project_name", "Pycoder V2", level="working")
        mem.remember("convention", "使用Type Hints", level="project")

        results = mem.recall("Pycoder")
        assert len(results) >= 1
        results2 = mem.recall("Type Hints")
        assert len(results2) >= 1


class TestTaskPlanner:
    """任务规划器测试"""

    def test_plan_creation(self):
        from pycoder.brain.task_planner import TaskPlanner

        planner = TaskPlanner()
        plan = planner.plan("创建用户认证模块")
        assert len(plan.tasks) >= 3
        assert plan.strategy.value in ("single_agent", "parallel_agents", "sdlc_pipeline")

    def test_plan_fix_bug(self):
        from pycoder.brain.task_planner import TaskPlanner

        planner = TaskPlanner()
        plan = planner.plan("修复登录页面的bug")
        # bug fix pattern should generate 4 tasks
        assert len(plan.tasks) >= 3
        assert any("定位" in t.description or "根因" in t.description for t in plan.tasks)

    def test_get_next_task(self):
        from pycoder.brain.task_planner import TaskPlanner

        planner = TaskPlanner()
        plan = planner.plan("创建API")
        task = planner.get_next_task(plan.plan_id)
        assert task is not None
        assert task.dependencies == []  # first task has no deps


class TestConsciousnessEngine:
    """意识引擎测试"""

    def test_mode_switching(self):
        from pycoder.brain.consciousness import ConsciousnessEngine, OperatingMode

        engine = ConsciousnessEngine()
        assert engine.mode == OperatingMode.IDLE
        engine.set_mode(OperatingMode.AWARE)
        assert engine.mode == OperatingMode.AWARE

    def test_perceive_event(self):
        from pycoder.brain.consciousness import ConsciousnessEngine, SystemEvent, OperatingMode

        engine = ConsciousnessEngine()
        engine.set_mode(OperatingMode.AWARE)

        event = SystemEvent(
            event_type="file_changed",
            source="test.py",
            summary="测试文件已修改",
            severity="info",
        )

        # Should not raise
        asyncio.run(engine.perceive(event))
