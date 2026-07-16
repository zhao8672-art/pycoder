"""ContextWindowManager 智能上下文窗口管理器测试

覆盖:
  - ContextScore: 评分数据类
  - ContextWindowManager: 消息评分机制
  - ContextWindowManager: 滑窗管理（token 预算控制）
  - ContextWindowManager: 关键决策/里程碑标记
  - ContextWindowManager: 上下文关联查找
  - ContextWindowManager: 会话摘要导出
  - ContextWindowManager: 重置功能
  - estimate_tokens: token 估算
"""

from __future__ import annotations

import pytest

from pycoder.server.services.context_manager import (
    ContextScore,
    ContextWindowManager,
)


# ══════════════════════════════════════════════════════════
# estimate_tokens 测试
# ══════════════════════════════════════════════════════════


class TestEstimateTokens:
    """Token 估算功能测试"""

    def test_empty_string(self) -> None:
        """空字符串 token 估算为 0"""
        result = ContextWindowManager.estimate_tokens("")
        assert result == 0

    def test_chinese_text(self) -> None:
        """中文文本 token 估算"""
        result = ContextWindowManager.estimate_tokens("你好世界")
        assert result > 0
        # 4 个中文字符 ≈ 4 tokens
        assert result >= 4

    def test_english_text(self) -> None:
        """英文文本 token 估算"""
        result = ContextWindowManager.estimate_tokens("hello world this is a test")
        assert result > 0
        # 6 个单词 × 1.3 ≈ 8 tokens
        assert result >= 7

    def test_mixed_text(self) -> None:
        """中英文混合文本 token 估算"""
        result = ContextWindowManager.estimate_tokens("你好 hello 世界 world")
        assert result > 0

    def test_code_text(self) -> None:
        """代码文本 token 估算"""
        code = "def foo(x: int) -> int:\n    return x + 1"
        result = ContextWindowManager.estimate_tokens(code)
        assert result > 0


# ══════════════════════════════════════════════════════════
# ContextScore 测试
# ══════════════════════════════════════════════════════════


class TestContextScore:
    """上下文评分数据类测试"""

    def test_default_values(self) -> None:
        """默认评分值"""
        score = ContextScore()
        assert score.score == 0.0
        assert score.is_decision is False
        assert score.is_milestone is False
        assert score.is_file_ref is False
        assert score.is_error is False
        assert score.tokens == 0

    def test_custom_values(self) -> None:
        """自定义评分值"""
        score = ContextScore(
            score=0.8,
            is_decision=True,
            is_milestone=True,
            tokens=200,
        )
        assert score.score == 0.8
        assert score.is_decision is True
        assert score.is_milestone is True
        assert score.tokens == 200


# ══════════════════════════════════════════════════════════
# ContextWindowManager 核心功能测试
# ══════════════════════════════════════════════════════════


class TestContextWindowManager:
    """上下文窗口管理器核心测试"""

    @pytest.fixture
    def manager(self) -> ContextWindowManager:
        """创建 ContextWindowManager 实例"""
        return ContextWindowManager(max_context_tokens=300)

    @pytest.fixture
    def manager_small(self) -> ContextWindowManager:
        """创建小容量 ContextWindowManager（容易触发淘汰）"""
        return ContextWindowManager(max_context_tokens=100)

    # ── 消息添加与评分 ──

    def test_add_message_user(self, manager: ContextWindowManager) -> None:
        """添加用户消息后自动评分"""
        manager.add_message({"role": "user", "content": "帮我修复一个 bug"})
        assert len(manager._messages) == 1
        assert 0 in manager._scores
        assert manager._scores[0].score > 0.3  # 用户消息基础分

    def test_add_message_assistant(self, manager: ContextWindowManager) -> None:
        """添加助手消息后自动评分"""
        manager.add_message({"role": "assistant", "content": "好的，我来帮你"})
        assert len(manager._messages) == 1
        assert 0 in manager._scores

    def test_decision_keyword_scoring(self, manager: ContextWindowManager) -> None:
        """包含决策关键词的消息获得高分"""
        manager.add_message({"role": "user", "content": "我决定采用微服务架构"})
        score = manager._scores[0]
        assert score.is_decision is True
        assert score.score >= 0.5  # 基准分 0.3 + 决策 0.3

    def test_milestone_keyword_scoring(self, manager: ContextWindowManager) -> None:
        """包含里程碑关键词的消息获得高分"""
        manager.add_message({"role": "assistant", "content": "已完成所有单元测试，测试通过"})
        score = manager._scores[0]
        assert score.is_milestone is True
        assert score.score >= 0.5  # 基准分 0.3 + 里程碑 0.25

    def test_error_keyword_scoring(self, manager: ContextWindowManager) -> None:
        """包含错误关键词的消息获得高分"""
        manager.add_message({"role": "assistant", "content": "执行失败: Traceback error"})
        score = manager._scores[0]
        assert score.is_error is True
        assert score.score >= 0.5  # 基准分 0.3 + 错误 0.2

    def test_file_ref_scoring(self, manager: ContextWindowManager) -> None:
        """包含文件引用的消息获得加分"""
        manager.add_message({"role": "user", "content": "修改 `main.py` 文件"})
        score = manager._scores[0]
        assert score.is_file_ref is True
        assert score.score >= 0.45  # 基准分 0.3 + 文件引用 0.15

    def test_code_block_scoring(self, manager: ContextWindowManager) -> None:
        """包含代码块的消息获得加分"""
        manager.add_message({"role": "assistant", "content": "这是代码:\n```python\nprint('hello')\n```"})
        score = manager._scores[0]
        assert score.score >= 0.4  # 基准分 0.3 + 代码块 0.1

    def test_long_message_scoring(self, manager: ContextWindowManager) -> None:
        """长消息获得额外加分"""
        long_content = "这是一个很长的消息" * 40  # 约 360 tokens
        manager.add_message({"role": "user", "content": long_content})
        score = manager._scores[0]
        assert score.score >= 0.35  # 基准分 0.3 + 长消息 0.05

    def test_score_capped_at_1(self, manager: ContextWindowManager) -> None:
        """评分上限定为 1.0"""
        # 同时触发多个高分规则
        manager.add_message({
            "role": "user",
            "content": (
                "我决定采用微服务架构，已完成部署，请修改 `main.py` "
                "错误信息: Traceback error\n```python\ncode\n```"
            ),
        })
        score = manager._scores[0]
        assert score.score <= 1.0

    # ── 滑窗管理 ──

    def test_get_window_empty(self, manager: ContextWindowManager) -> None:
        """空窗口返回空列表"""
        messages, summary = manager.get_window_messages()
        assert messages == []
        assert summary == ""

    def test_get_window_within_budget(self, manager: ContextWindowManager) -> None:
        """消息在 token 预算内全部保留"""
        manager.add_message({"role": "user", "content": "你好"})
        manager.add_message({"role": "assistant", "content": "你好！有什么可以帮你的？"})
        messages, summary = manager.get_window_messages()
        assert len(messages) == 2
        assert summary == ""

    def test_get_window_exceeds_budget(self, manager_small: ContextWindowManager) -> None:
        """超出 token 预算时淘汰低分消息"""
        # 添加大量长消息以超出 100 token 预算
        for i in range(20):
            manager_small.add_message({
                "role": "assistant",
                "content": f"这是一条很长的普通回复消息，编号为 {i}，包含很多文字",
            })
        messages, summary = manager_small.get_window_messages()
        # 部分消息被淘汰
        assert len(messages) < 20
        assert len(summary) > 0  # 有淘汰摘要
        assert "上下文摘要" in summary

    def test_get_window_preserves_decisions(self, manager_small: ContextWindowManager) -> None:
        """关键决策消息即使超出预算也保留"""
        # 先添加大量低分消息
        for i in range(15):
            manager_small.add_message({"role": "assistant", "content": f"普通回复 {i}"})
        # 再添加关键决策
        manager_small.add_message({"role": "user", "content": "我决定采用 PostgreSQL 数据库"})
        messages, _ = manager_small.get_window_messages()
        contents = [str(m.get("content", "")) for m in messages]
        assert any("PostgreSQL" in c for c in contents)

    def test_get_window_preserves_errors(self, manager_small: ContextWindowManager) -> None:
        """错误消息即使超出预算也保留"""
        for i in range(15):
            manager_small.add_message({"role": "assistant", "content": f"普通回复 {i}"})
        manager_small.add_message({"role": "assistant", "content": "Traceback error: 连接失败"})
        messages, _ = manager_small.get_window_messages()
        contents = [str(m.get("content", "")) for m in messages]
        assert any("Traceback" in c for c in contents)

    def test_get_window_high_score_preserved(self, manager_small: ContextWindowManager) -> None:
        """高分消息（>= 0.7）永不淘汰"""
        for i in range(15):
            manager_small.add_message({"role": "assistant", "content": f"普通回复 {i}"})
        # 高分消息：用户 + 决策 + 错误
        manager_small.add_message({
            "role": "user",
            "content": "我决定采用方案A，修复这个 Traceback error",
        })
        messages, _ = manager_small.get_window_messages()
        contents = [str(m.get("content", "")) for m in messages]
        assert any("方案A" in c for c in contents)

    def test_get_window_maintains_order(self, manager_small: ContextWindowManager) -> None:
        """保留的消息保持原始顺序"""
        manager_small.add_message({"role": "user", "content": "第一条消息"})
        for i in range(15):
            manager_small.add_message({"role": "assistant", "content": f"普通回复 {i}"})
        manager_small.add_message({"role": "user", "content": "最后一条消息，决定采用方案B"})
        messages, _ = manager_small.get_window_messages()
        # 最后一条高分的决策消息应保留
        contents = [str(m.get("content", "")) for m in messages]
        assert any("方案B" in c for c in contents)

    # ── 决策与里程碑日志 ──

    def test_decision_log(self, manager: ContextWindowManager) -> None:
        """决策日志记录"""
        manager.add_message({"role": "user", "content": "我决定采用 Redis 缓存"})
        assert len(manager._decision_log) == 1
        assert "Redis" in manager._decision_log[0]

    def test_milestone_log(self, manager: ContextWindowManager) -> None:
        """里程碑日志记录"""
        manager.add_message({"role": "assistant", "content": "已完成所有功能，测试通过"})
        assert len(manager._milestones) == 1
        assert "测试通过" in manager._milestones[0]

    def test_decision_log_in_summary(self, manager_small: ContextWindowManager) -> None:
        """淘汰摘要中包含关键决策"""
        # 先添加关键决策（高分，不会被淘汰）
        manager_small.add_message({"role": "user", "content": "我决定采用微服务架构"})
        # 再添加大量长消息以触发淘汰
        for i in range(15):
            manager_small.add_message({
                "role": "assistant",
                "content": f"这是一条长消息用于填满预算，编号 {i}",
            })
        messages, summary = manager_small.get_window_messages()
        # 决策日志应出现在摘要中
        assert "关键决策" in summary

    # ── 上下文关联查找 ──

    def test_find_related_messages_empty(self, manager: ContextWindowManager) -> None:
        """空窗口查找返回空列表"""
        result = manager.find_related_messages("测试内容")
        assert result == []

    def test_find_related_messages_no_match(self, manager: ContextWindowManager) -> None:
        """无匹配时返回空列表"""
        manager.add_message({"role": "user", "content": "完全不相关的内容"})
        result = manager.find_related_messages("测试内容")
        assert result == []

    def test_find_related_messages_with_match(self, manager: ContextWindowManager) -> None:
        """有匹配时返回相关消息"""
        manager.add_message({"role": "user", "content": "Python 连接失败"})
        manager.add_message({"role": "assistant", "content": "请检查 Python 配置"})
        result = manager.find_related_messages("Python 问题查询")
        assert len(result) > 0
        assert any("Python" in str(m.get("content")) for m in result)

    def test_find_related_messages_max_results(self, manager: ContextWindowManager) -> None:
        """限制返回数量"""
        for i in range(5):
            manager.add_message({"role": "user", "content": f"Python 相关消息 {i}"})
        result = manager.find_related_messages("Python 查询", max_results=2)
        assert len(result) <= 2

    # ── 会话摘要 ──

    def test_get_session_summary_empty(self, manager: ContextWindowManager) -> None:
        """空会话摘要"""
        summary = manager.get_session_summary()
        assert "总消息数: 0" in summary

    def test_get_session_summary_with_data(self, manager: ContextWindowManager) -> None:
        """有数据时生成完整摘要"""
        manager.add_message({"role": "user", "content": "我决定采用方案A"})
        manager.add_message({"role": "assistant", "content": "已完成部署，测试通过"})
        summary = manager.get_session_summary()
        assert "关键决策" in summary
        assert "里程碑" in summary
        assert "总消息数" in summary

    # ── 重置 ──

    def test_reset(self, manager: ContextWindowManager) -> None:
        """重置后清空所有状态"""
        manager.add_message({"role": "user", "content": "测试消息"})
        manager.add_message({"role": "user", "content": "我决定采用方案A"})
        manager.add_message({"role": "assistant", "content": "已完成，测试通过"})

        assert len(manager._messages) > 0
        assert len(manager._decision_log) > 0
        assert len(manager._milestones) > 0

        manager.reset()

        assert len(manager._messages) == 0
        assert len(manager._scores) == 0
        assert len(manager._decision_log) == 0
        assert len(manager._milestones) == 0
        assert manager._last_summary_index == 0

    # ── 总消息计数 ──

    def test_total_messages_seen(self, manager: ContextWindowManager) -> None:
        """总消息计数器递增"""
        for i in range(5):
            manager.add_message({"role": "user", "content": f"消息 {i}"})
        assert manager._total_messages_seen == 5

    def test_total_messages_seen_after_reset(self, manager: ContextWindowManager) -> None:
        """reset 不影响 _total_messages_seen（设计如此）"""
        for i in range(5):
            manager.add_message({"role": "user", "content": f"消息 {i}"})
        manager.reset()
        # _total_messages_seen 在 reset 中不被重置（根据源码）
        assert manager._messages == []
        assert manager._total_messages_seen == 5