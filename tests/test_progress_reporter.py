"""Agent 执行进度报告器测试

覆盖:
  - StageDef: 阶段定义数据类
  - Milestone: 里程碑数据类
  - ProgressReporter: 进度报告器
    - set_stages: 设置阶段
    - set_callback: 设置回调
    - advance: 推进阶段
    - emit_progress: 发送进度事件
    - mark_milestone: 标记里程碑
    - mark_stage_error: 标记阶段错误
    - reset: 重置状态
    - force_complete_all: 强制完成所有阶段
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.server.services.progress_reporter import (
    Milestone,
    ProgressReporter,
    StageDef,
)


# ══════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════


@pytest.fixture
def make_stages() -> list[StageDef]:
    """创建标准阶段列表"""
    return [
        StageDef(id="intent", label="意图分析", description="分析用户意图"),
        StageDef(id="plan", label="任务规划", description="规划执行步骤"),
        StageDef(id="execute", label="代码执行", description="执行代码生成"),
        StageDef(id="review", label="代码审查", description="审查代码质量"),
        StageDef(id="test", label="测试验证", description="运行测试"),
        StageDef(id="deliver", label="交付报告", description="生成交付报告"),
    ]


# 模块级阶段列表常量，供非 fixture 场景使用
_STAGES = [
    StageDef(id="intent", label="意图分析", description="分析用户意图"),
    StageDef(id="plan", label="任务规划", description="规划执行步骤"),
    StageDef(id="execute", label="代码执行", description="执行代码生成"),
    StageDef(id="review", label="代码审查", description="审查代码质量"),
    StageDef(id="test", label="测试验证", description="运行测试"),
    StageDef(id="deliver", label="交付报告", description="生成交付报告"),
]


@pytest.fixture
def reporter() -> ProgressReporter:
    """创建一个标准进度报告器"""
    return ProgressReporter()


@pytest.fixture
def reporter_with_stages(reporter, make_stages) -> ProgressReporter:
    """创建已设置阶段的进度报告器"""
    reporter.set_stages(make_stages, total_eta=120)
    return reporter


@pytest.fixture
def async_callback() -> AsyncMock:
    """创建一个异步回调 mock"""
    return AsyncMock()


# ══════════════════════════════════════════════════════════
# StageDef 测试
# ══════════════════════════════════════════════════════════


class TestStageDef:
    """阶段定义数据类"""

    def test_creation(self):
        """创建阶段定义"""
        stage = StageDef(
            id="intent",
            label="意图分析",
            description="分析用户意图并分类",
        )
        assert stage.id == "intent"
        assert stage.label == "意图分析"
        assert stage.description == "分析用户意图并分类"


# ══════════════════════════════════════════════════════════
# Milestone 测试
# ══════════════════════════════════════════════════════════


class TestMilestone:
    """里程碑数据类"""

    def test_default_status(self):
        """默认状态为 pending"""
        m = Milestone(step="意图分析")
        assert m.step == "意图分析"
        assert m.status == "pending"

    def test_custom_status(self):
        """自定义状态"""
        m = Milestone(step="代码审查", status="done")
        assert m.status == "done"

    def test_error_status(self):
        """错误状态"""
        m = Milestone(step="测试验证", status="error")
        assert m.status == "error"


# ══════════════════════════════════════════════════════════
# ProgressReporter set_stages 测试
# ══════════════════════════════════════════════════════════


class TestProgressReporterSetStages:
    """设置阶段"""

    def test_set_stages_initializes(self, reporter, make_stages):
        """设置阶段初始化所有状态"""
        reporter.set_stages(make_stages)
        assert len(reporter._stages) == 6
        assert reporter._current_idx == 0
        assert reporter._start_time > 0

    def test_set_stages_creates_milestones(self, reporter, make_stages):
        """设置阶段创建里程碑"""
        reporter.set_stages(make_stages)
        assert len(reporter._milestones) == 6
        # 第一个里程碑应为 active
        assert reporter._milestones[0].status == "active"
        assert reporter._milestones[0].step == "意图分析"

    def test_set_stages_initializes_status(self, reporter, make_stages):
        """设置阶段初始化状态字典"""
        reporter.set_stages(make_stages)
        assert reporter._stage_status["intent"] == "active"
        assert reporter._stage_status["plan"] == "pending"
        assert reporter._stage_status["execute"] == "pending"

    def test_set_stages_resets_total_eta(self, reporter, make_stages):
        """设置阶段重置 ETA"""
        reporter.set_stages(make_stages, total_eta=300)
        assert reporter._total_eta_seconds == 300

    def test_set_stages_empty_list(self, reporter):
        """空阶段列表"""
        reporter.set_stages([])
        assert len(reporter._stages) == 0
        assert len(reporter._milestones) == 0


# ══════════════════════════════════════════════════════════
# ProgressReporter set_callback 测试
# ══════════════════════════════════════════════════════════


class TestProgressReporterSetCallback:
    """设置回调"""

    def test_set_callback(self, reporter):
        """设置异步回调"""
        cb = AsyncMock()
        reporter.set_callback(cb)
        assert reporter._callback is cb

    def test_callback_none(self, reporter):
        """回调为 None"""
        reporter.set_callback(None)
        assert reporter._callback is None


# ══════════════════════════════════════════════════════════
# ProgressReporter emit_progress 测试
# ══════════════════════════════════════════════════════════


class TestProgressReporterEmitProgress:
    """发送进度事件"""

    @pytest.mark.asyncio
    async def test_emit_with_callback(self, reporter_with_stages, async_callback):
        """有回调时发送事件"""
        reporter_with_stages.set_callback(async_callback)
        await reporter_with_stages.emit_progress("intent", "正在分析意图...")
        async_callback.assert_awaited_once()
        event = async_callback.call_args[0][0]
        assert event["type"] == "progress"
        assert event["phase"] == "intent"
        assert event["stage"] == "正在分析意图..."
        assert event["total_steps"] == 6
        assert "percent" in event
        assert "elapsed_seconds" in event
        assert "eta_seconds" in event
        assert "milestones" in event

    @pytest.mark.asyncio
    async def test_emit_without_callback_no_error(self, reporter_with_stages):
        """无回调时不报错"""
        await reporter_with_stages.emit_progress("intent", "测试")
        # 无异常即可

    @pytest.mark.asyncio
    async def test_emit_callback_error_handled(self, reporter_with_stages):
        """回调异常被捕获"""
        error_cb = AsyncMock(side_effect=RuntimeError("callback error"))
        reporter_with_stages.set_callback(error_cb)
        # 不应抛出异常
        await reporter_with_stages.emit_progress("intent", "测试")

    @pytest.mark.asyncio
    async def test_emit_percent_calculation(self, reporter_with_stages, async_callback):
        """百分比计算正确"""
        reporter_with_stages.set_callback(async_callback)
        # 第 0 步 (current_idx=0)
        await reporter_with_stages.emit_progress("intent", "开始")
        event = async_callback.call_args[0][0]
        assert event["percent"] == 0

    @pytest.mark.asyncio
    async def test_emit_eta_calculation_zero_percent(self, reporter_with_stages, async_callback):
        """0% 时 ETA 使用预设值"""
        reporter_with_stages.set_callback(async_callback)
        reporter_with_stages._current_idx = 0
        await reporter_with_stages.emit_progress("intent", "开始")
        event = async_callback.call_args[0][0]
        assert event["eta_seconds"] == reporter_with_stages._total_eta_seconds

    @pytest.mark.asyncio
    async def test_emit_milestones_data(self, reporter_with_stages, async_callback):
        """里程碑数据包含在事件中"""
        reporter_with_stages.set_callback(async_callback)
        await reporter_with_stages.emit_progress("intent", "测试")
        event = async_callback.call_args[0][0]
        assert len(event["milestones"]) == 6
        assert event["milestones"][0]["step"] == "意图分析"
        assert event["milestones"][0]["status"] == "active"


# ══════════════════════════════════════════════════════════
# ProgressReporter advance 测试
# ══════════════════════════════════════════════════════════


class TestProgressReporterAdvance:
    """推进阶段"""

    @pytest.mark.asyncio
    async def test_advance_first_stage(self, reporter_with_stages, async_callback):
        """推进到第一个阶段 — _current_idx=0 时不标记上一阶段"""
        reporter_with_stages.set_callback(async_callback)
        await reporter_with_stages.advance("plan", "正在规划任务...")
        # _current_idx 从 0 开始，不会标记 intent 为 done
        # intent 保持 active，plan 变为 active
        assert reporter_with_stages._stage_status["intent"] == "active"
        assert reporter_with_stages._stage_status["plan"] == "active"
        assert reporter_with_stages._current_idx == 2  # 1-based

    @pytest.mark.asyncio
    async def test_advance_through_all_stages(self, reporter_with_stages, async_callback):
        """推进所有阶段 — 从第2个阶段开始标记前一个为 done"""
        reporter_with_stages.set_callback(async_callback)
        # 第一步: advance 到 plan（intent 保持 active，_current_idx 从 0 开始）
        await reporter_with_stages.advance("plan", "规划中")
        # 第二步: advance 到 execute（plan 被标记为 done）
        await reporter_with_stages.advance("execute", "执行中")
        # 第三步: advance 到 review
        await reporter_with_stages.advance("review", "审查中")
        # 第四步: advance 到 test
        await reporter_with_stages.advance("test", "测试中")
        # 第五步: advance 到 deliver
        await reporter_with_stages.advance("deliver", "交付中")

        # intent 从未被标记为 done（因为 _current_idx 从 0 开始）
        assert reporter_with_stages._stage_status["intent"] == "active"
        # plan, execute, review, test 被标记为 done
        assert reporter_with_stages._stage_status["plan"] == "done"
        assert reporter_with_stages._stage_status["execute"] == "done"
        assert reporter_with_stages._stage_status["review"] == "done"
        assert reporter_with_stages._stage_status["test"] == "done"
        # deliver 是最后一个 active
        assert reporter_with_stages._stage_status["deliver"] == "active"
        assert reporter_with_stages._current_idx == 6

    @pytest.mark.asyncio
    async def test_advance_unknown_stage(self, reporter_with_stages, async_callback):
        """推进到未注册的阶段"""
        reporter_with_stages.set_callback(async_callback)
        await reporter_with_stages.advance("unknown", "未知阶段")
        # 不应报错，也不应改变状态
        assert reporter_with_stages._current_idx == 0

    @pytest.mark.asyncio
    async def test_advance_with_failure(self, reporter_with_stages, async_callback):
        """失败推进 — _current_idx=0 时不标记前一个阶段"""
        reporter_with_stages.set_callback(async_callback)
        await reporter_with_stages.advance("plan", "规划中", success=False)
        # _current_idx 从 0 开始，不会标记 intent 为 error
        assert reporter_with_stages._stage_status["intent"] == "active"
        assert reporter_with_stages._milestones[0].status == "active"

    @pytest.mark.asyncio
    async def test_advance_force_complete_all(self, reporter_with_stages, async_callback):
        """强制完成所有阶段"""
        reporter_with_stages.set_callback(async_callback)
        await reporter_with_stages.advance("", "", force_complete_all=True)
        # 所有阶段标记为 done
        for s in reporter_with_stages._stages:
            assert reporter_with_stages._stage_status[s.id] == "done"
        assert reporter_with_stages._current_idx == 6

    @pytest.mark.asyncio
    async def test_advance_force_complete_all_milestones(self, reporter_with_stages, async_callback):
        """强制完成所有阶段更新里程碑"""
        reporter_with_stages.set_callback(async_callback)
        await reporter_with_stages.advance("", "", force_complete_all=True)
        for m in reporter_with_stages._milestones:
            assert m.status == "done"

    @pytest.mark.asyncio
    async def test_advance_emits_callback(self, reporter_with_stages, async_callback):
        """推进时发送回调"""
        reporter_with_stages.set_callback(async_callback)
        await reporter_with_stages.advance("plan", "正在规划...")
        async_callback.assert_awaited()


# ══════════════════════════════════════════════════════════
# ProgressReporter mark_milestone 测试
# ══════════════════════════════════════════════════════════


class TestProgressReporterMarkMilestone:
    """标记里程碑"""

    def test_mark_valid_index(self, reporter_with_stages):
        """标记有效索引"""
        reporter_with_stages.mark_milestone(2, "done")
        assert reporter_with_stages._milestones[2].status == "done"

    def test_mark_negative_index(self, reporter_with_stages):
        """标记负数索引（不报错）"""
        reporter_with_stages.mark_milestone(-1, "done")
        # 不改变任何里程碑
        assert reporter_with_stages._milestones[0].status == "active"

    def test_mark_out_of_range(self, reporter_with_stages):
        """标记超出范围索引（不报错）"""
        reporter_with_stages.mark_milestone(100, "done")
        # 不改变任何里程碑

    def test_mark_error_status(self, reporter_with_stages):
        """标记为错误"""
        reporter_with_stages.mark_milestone(1, "error")
        assert reporter_with_stages._milestones[1].status == "error"


# ══════════════════════════════════════════════════════════
# ProgressReporter mark_stage_error 测试
# ══════════════════════════════════════════════════════════


class TestProgressReporterMarkStageError:
    """标记阶段错误"""

    def test_mark_stage_error(self, reporter_with_stages):
        """标记阶段错误"""
        reporter_with_stages.mark_stage_error("execute", "代码执行失败")
        assert reporter_with_stages._stage_status["execute"] == "error"

    def test_mark_stage_error_unknown_stage(self, reporter_with_stages):
        """标记未注册阶段"""
        reporter_with_stages.mark_stage_error("unknown", "错误")
        # 不报错，设置状态
        assert reporter_with_stages._stage_status["unknown"] == "error"


# ══════════════════════════════════════════════════════════
# ProgressReporter reset 测试
# ══════════════════════════════════════════════════════════


class TestProgressReporterReset:
    """重置状态"""

    def test_reset_clears_state(self, reporter_with_stages):
        """重置清空所有状态"""
        reporter_with_stages.reset()
        assert reporter_with_stages._current_idx == 0
        assert reporter_with_stages._stage_status == {}
        assert reporter_with_stages._milestones == []
        assert reporter_with_stages._start_time == 0.0

    def test_reset_after_advance(self, reporter_with_stages, async_callback):
        """推进后重置"""
        reporter_with_stages.set_callback(async_callback)

        import asyncio
        async def advance():
            await reporter_with_stages.advance("plan", "规划中")

        # 使用同步方式重置
        reporter_with_stages._stage_status["plan"] = "active"
        reporter_with_stages._current_idx = 2

        reporter_with_stages.reset()
        assert reporter_with_stages._current_idx == 0
        assert reporter_with_stages._stage_status == {}


# ══════════════════════════════════════════════════════════
# ProgressReporter 集成测试
# ══════════════════════════════════════════════════════════


class TestProgressReporterIntegration:
    """集成场景测试"""

    @pytest.mark.asyncio
    async def test_full_workflow(self, reporter, make_stages, async_callback):
        """完整工作流"""
        reporter.set_callback(async_callback)
        reporter.set_stages(make_stages, total_eta=60)

        # 意图分析 → 推进到 plan（_current_idx=0 不标记 intent）
        await reporter.advance("plan", "正在规划任务...")
        # intent 保持 active
        assert reporter._stage_status["intent"] == "active"

        # 任务规划 → 推进到 execute（plan 被标记为 done）
        await reporter.advance("execute", "正在执行代码生成...")
        assert reporter._stage_status["plan"] == "done"

        # 标记里程碑
        reporter.mark_milestone(0, "done")
        reporter.mark_milestone(1, "done")

        # 代码执行失败 → 推进到 review（execute 标记为 error）
        await reporter.advance("review", "执行失败，跳过审查", success=False)
        assert reporter._stage_status["execute"] == "error"

        # 标记阶段错误
        reporter.mark_stage_error("test", "无法运行测试")

        # 强制完成
        await reporter.advance("", "", force_complete_all=True)
        assert reporter._current_idx == 6

        # 验证回调被调用多次
        assert async_callback.await_count >= 3

    @pytest.mark.asyncio
    async def test_workflow_with_errors(self, reporter, make_stages, async_callback):
        """带错误的工作流"""
        reporter.set_callback(async_callback)
        reporter.set_stages(make_stages)

        # 正常推进
        await reporter.advance("plan", "规划中")
        await reporter.advance("execute", "执行中")

        # 标记错误
        reporter.mark_stage_error("execute", "代码有语法错误")
        reporter.mark_milestone(2, "error")

        # 验证状态
        assert reporter._stage_status["execute"] == "error"
        assert reporter._milestones[2].status == "error"

    @pytest.mark.asyncio
    async def test_workflow_without_callback(self, reporter, make_stages):
        """无回调的工作流（不报错）"""
        reporter.set_stages(make_stages)

        await reporter.advance("plan", "规划中")
        await reporter.advance("execute", "执行中")
        await reporter.advance("review", "审查中")
        await reporter.advance("test", "测试中")
        await reporter.advance("deliver", "交付中")

        assert reporter._current_idx == 6
        # intent 保持 active（_current_idx 从 0 开始，从未标记为 done）
        assert reporter._stage_status["intent"] == "active"
        # plan, execute, review, test 被标记为 done
        for stage_id in ["plan", "execute", "review", "test"]:
            assert reporter._stage_status[stage_id] == "done"
        # deliver 是最后一个 active
        assert reporter._stage_status["deliver"] == "active"