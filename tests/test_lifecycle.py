"""项目管理闭环系统 — 单元测试

覆盖:
- 上下文数据模型 (ProjectContext, PhaseRecord)
- 7 阶段状态机 (LifecyclePhase)
- 编排器 (ProjectLifecycleOrchestrator)
- 适配器 (7 个阶段策略)
- 能力注册 (register_capabilities)
"""

from __future__ import annotations

import asyncio

import pytest

from pycoder.lifecycle import (
    LifecyclePhase,
    PhaseArtifact,
    PhaseRecord,
    ProjectContext,
    ProjectStatus,
    create_default_phases,
    get_orchestrator,
    get_progress,
)
from pycoder.lifecycle.orchestrator import ProjectLifecycleOrchestrator


# ══════════════════════════════════════════════════════
# 上下文数据模型测试
# ══════════════════════════════════════════════════════


class TestProjectContext:
    """ProjectContext 数据模型测试"""

    def test_create_default(self):
        """默认创建应有唯一 project_id"""
        ctx1 = ProjectContext()
        ctx2 = ProjectContext()
        assert ctx1.project_id != ctx2.project_id
        assert ctx1.status == ProjectStatus.PENDING
        assert len(ctx1.project_id) == 12

    def test_add_artifact(self):
        """添加产出物应更新 artifacts 列表和阶段记录"""
        ctx = ProjectContext(request="test")
        artifact = PhaseArtifact(phase="INTAKE", name="summary", content="测试")
        ctx.add_artifact(artifact)

        assert len(ctx.artifacts) == 1
        assert ctx.phases["INTAKE"].artifacts[0] == artifact

    def test_get_phase_creates_if_missing(self):
        """get_phase 在不存在时创建默认记录"""
        ctx = ProjectContext()
        record = ctx.get_phase("TEST")
        assert record.phase == "TEST"
        assert record.status == "pending"

    def test_to_dict_serializable(self):
        """to_dict 应返回可序列化的字典"""
        ctx = ProjectContext(request="test request")
        ctx.status = ProjectStatus.RUNNING
        d = ctx.to_dict()

        assert d["status"] == "running"
        assert d["request"] == "test request"
        assert "phases" in d
        assert "project_id" in d

    def test_touch_updates_timestamp(self):
        """touch 应更新 updated_at"""
        import time

        ctx = ProjectContext()
        old_ts = ctx.updated_at
        time.sleep(0.001)
        ctx.touch()
        assert ctx.updated_at >= old_ts


class TestPhaseRecord:
    """PhaseRecord 测试"""

    def test_is_terminal(self):
        """终态判断"""
        assert PhaseRecord(phase="X", status="passed").is_terminal
        assert PhaseRecord(phase="X", status="failed").is_terminal
        assert PhaseRecord(phase="X", status="skipped").is_terminal
        assert not PhaseRecord(phase="X", status="running").is_terminal
        assert not PhaseRecord(phase="X", status="pending").is_terminal

    def test_to_dict(self):
        """序列化"""
        record = PhaseRecord(
            phase="DESIGN", status="passed", duration_ms=123.4, gate_score=85.0
        )
        d = record.to_dict()
        assert d["phase"] == "DESIGN"
        assert d["status"] == "passed"
        assert d["gate_score"] == 85.0


# ══════════════════════════════════════════════════════
# 7 阶段状态机测试
# ══════════════════════════════════════════════════════


class TestLifecyclePhase:
    """LifecyclePhase 枚举测试"""

    def test_ordered(self):
        """ordered 应返回按顺序的 7 个阶段"""
        phases = LifecyclePhase.ordered()
        assert len(phases) == 7
        assert phases[0] == LifecyclePhase.INTAKE
        assert phases[-1] == LifecyclePhase.DELIVER

    def test_next_prev(self):
        """next/prev 流转"""
        assert LifecyclePhase.INTAKE.next() == LifecyclePhase.ANALYZE
        assert LifecyclePhase.DELIVER.next() is None
        assert LifecyclePhase.INTAKE.prev() is None
        assert LifecyclePhase.DELIVER.prev() == LifecyclePhase.HEAL

    def test_label(self):
        """中文标签"""
        assert LifecyclePhase.INTAKE.label == "任务接收"
        assert LifecyclePhase.DELIVER.label == "交付管理"

    def test_description_not_empty(self):
        """所有阶段应有描述"""
        for phase in LifecyclePhase.ordered():
            assert phase.description, f"{phase.name} 缺少描述"


class TestProgressCalculation:
    """进度计算测试"""

    def test_empty_progress(self):
        """无阶段记录时进度为 0"""
        ctx = ProjectContext()
        assert get_progress(ctx) == 0.0

    def test_full_progress(self):
        """所有阶段终态时进度为 1.0"""
        ctx = ProjectContext()
        for phase in LifecyclePhase.ordered():
            ctx.phases[phase.name] = PhaseRecord(phase=phase.name, status="passed")
        assert get_progress(ctx) == 1.0

    def test_partial_progress(self):
        """部分完成进度计算"""
        ctx = ProjectContext()
        ctx.phases["INTAKE"] = PhaseRecord(phase="INTAKE", status="passed")
        ctx.phases["ANALYZE"] = PhaseRecord(phase="ANALYZE", status="passed")
        progress = get_progress(ctx)
        assert 0.2 < progress < 0.4  # 2/7 ≈ 0.286


# ══════════════════════════════════════════════════════
# 编排器测试
# ══════════════════════════════════════════════════════


class TestOrchestrator:
    """ProjectLifecycleOrchestrator 测试"""

    def test_create_project(self):
        """创建项目"""
        orch = ProjectLifecycleOrchestrator()
        ctx = orch.create_project("test request")
        assert ctx.request == "test request"
        assert ctx.status == ProjectStatus.PENDING
        assert orch.get_project(ctx.project_id) is ctx

    def test_list_projects(self):
        """列出项目"""
        orch = ProjectLifecycleOrchestrator()
        orch.create_project("req1")
        orch.create_project("req2")
        projects = orch.list_projects()
        assert len(projects) == 2

    def test_cancel_project(self):
        """取消项目"""
        orch = ProjectLifecycleOrchestrator()
        ctx = orch.create_project("test")
        assert orch.cancel_project(ctx.project_id)
        assert ctx.status == ProjectStatus.CANCELLED
        # 已终态不可再次取消
        assert not orch.cancel_project(ctx.project_id)

    def test_cancel_nonexistent(self):
        """取消不存在的项目"""
        orch = ProjectLifecycleOrchestrator()
        assert not orch.cancel_project("nonexistent")

    def test_replace_phase(self):
        """替换阶段策略"""

        class MockStrategy:
            phase = LifecyclePhase.INTAKE

            async def execute(self, ctx):
                return PhaseRecord(phase="INTAKE", status="passed")

        orch = ProjectLifecycleOrchestrator()
        orch.replace_phase(LifecyclePhase.INTAKE, MockStrategy())
        # 验证替换成功（不抛异常即可）

    def test_get_phase_progress_nonexistent(self):
        """获取不存在项目的进度"""
        orch = ProjectLifecycleOrchestrator()
        result = orch.get_phase_progress("nonexistent")
        assert "error" in result


# ══════════════════════════════════════════════════════
# 端到端闭环测试
# ══════════════════════════════════════════════════════


class TestEndToEnd:
    """端到端闭环测试"""

    @pytest.mark.asyncio
    async def test_full_lifecycle_run(self):
        """完整 7 阶段闭环运行"""
        orch = ProjectLifecycleOrchestrator()
        ctx = orch.create_project("实现用户注册API")

        events = []
        async for event in orch.run(ctx.project_id):
            events.append(event)

        # 验证事件序列
        event_types = [e["type"] for e in events]
        assert "pipeline_start" in event_types
        assert "done" in event_types

        # 验证最终状态
        final_ctx = orch.get_project(ctx.project_id)
        assert final_ctx.status == ProjectStatus.COMPLETED
        assert len(final_ctx.phases) == 7

    @pytest.mark.asyncio
    async def test_phase_events(self):
        """验证阶段事件包含必要字段"""
        orch = ProjectLifecycleOrchestrator()
        ctx = orch.create_project("test")

        phase_starts = []
        phase_dones = []
        async for event in orch.run(ctx.project_id):
            if event["type"] == "phase_start":
                phase_starts.append(event)
            elif event["type"] == "phase_done":
                phase_dones.append(event)

        assert len(phase_starts) == 7
        assert len(phase_dones) == 7

        for evt in phase_starts:
            assert "phase" in evt
            assert "label" in evt
            assert "progress" in evt

        for evt in phase_dones:
            assert "phase" in evt
            assert "status" in evt
            assert evt["status"] in ("passed", "failed", "skipped")

    @pytest.mark.asyncio
    async def test_empty_request_fails(self):
        """空需求应在 INTAKE 阶段失败"""
        orch = ProjectLifecycleOrchestrator()
        ctx = orch.create_project("")

        events = []
        async for event in orch.run(ctx.project_id):
            events.append(event)

        final_ctx = orch.get_project(ctx.project_id)
        assert final_ctx.status == ProjectStatus.FAILED

    @pytest.mark.asyncio
    async def test_resume_completed_project(self):
        """恢复已完成的项目应直接返回 done"""
        orch = ProjectLifecycleOrchestrator()
        ctx = orch.create_project("test")

        # 第一次运行
        async for _ in orch.run(ctx.project_id):
            pass

        # 恢复运行
        events = []
        async for event in orch.run(ctx.project_id, resume=True):
            events.append(event)

        assert any(e["type"] == "done" for e in events)


# ══════════════════════════════════════════════════════
# 适配器测试
# ══════════════════════════════════════════════════════


class TestAdapters:
    """阶段适配器测试"""

    def test_create_default_phases(self):
        """默认策略集合应包含 7 个阶段"""
        phases = create_default_phases()
        assert len(phases) == 7
        for phase in LifecyclePhase.ordered():
            assert phase in phases

    @pytest.mark.asyncio
    async def test_intake_adapter(self):
        """INTAKE 适配器应解析需求"""
        from pycoder.lifecycle.adapters import IntakeAdapter

        ctx = ProjectContext(request="实现一个API")
        adapter = IntakeAdapter()
        record = await adapter.execute(ctx)

        assert record.status == "passed"
        assert "project_name" in ctx.requirements

    @pytest.mark.asyncio
    async def test_intake_empty_request(self):
        """INTAKE 空需求应失败"""
        from pycoder.lifecycle.adapters import IntakeAdapter

        ctx = ProjectContext(request="")
        adapter = IntakeAdapter()
        record = await adapter.execute(ctx)

        assert record.status == "failed"
        assert "为空" in record.error


# ══════════════════════════════════════════════════════
# 单例测试
# ══════════════════════════════════════════════════════


class TestSingleton:
    """全局单例测试"""

    def test_get_orchestrator_singleton(self):
        """get_orchestrator 返回同一实例"""
        o1 = get_orchestrator()
        o2 = get_orchestrator()
        assert o1 is o2
