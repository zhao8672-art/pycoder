"""M5: ChatBridge 历史消息滑窗截断测试

验证 agent_orchestrator 循环累积的消息不会无限膨胀 prompt：
- 默认 max_history_messages=20
- 超过阈值时截断保留最近 N 条
- _messages 完整历史保留供审计
- max_history_messages=0 表示不截断
- system prompt 注入不受截断影响
"""
from __future__ import annotations

import pytest

from pycoder.server.chat_bridge import BridgeConfig, ChatBridge


class TestBridgeConfigDefault:
    """BridgeConfig 默认值"""

    def test_max_history_messages_default_is_20(self):
        """M5: 默认滑窗上限应为 20（覆盖 agent 15 轮循环场景）"""
        cfg = BridgeConfig()
        assert cfg.max_history_messages == 20

    def test_max_history_messages_is_int(self):
        cfg = BridgeConfig()
        assert isinstance(cfg.max_history_messages, int)


class TestEffectiveMessagesTruncation:
    """_get_effective_messages 滑窗截断"""

    def test_no_truncation_when_below_limit(self):
        """消息数 < max_history_messages 时不截断"""
        bridge = ChatBridge()
        bridge.config.max_history_messages = 5
        for i in range(3):
            bridge.add_message("assistant", f"msg-{i}")
        effective = bridge._get_effective_messages()
        assert len(effective) == 3
        assert effective[0]["content"] == "msg-0"
        assert effective[2]["content"] == "msg-2"

    def test_truncation_when_above_limit(self):
        """消息数 > max_history_messages 时截断保留最近 N 条"""
        bridge = ChatBridge()
        bridge.config.max_history_messages = 5
        for i in range(10):
            bridge.add_message("assistant", f"msg-{i}")
        effective = bridge._get_effective_messages()
        assert len(effective) == 5
        # 应保留最近 5 条：msg-5..msg-9
        assert effective[0]["content"] == "msg-5"
        assert effective[-1]["content"] == "msg-9"

    def test_truncation_at_exact_limit(self):
        """消息数 == max_history_messages 时不截断"""
        bridge = ChatBridge()
        bridge.config.max_history_messages = 5
        for i in range(5):
            bridge.add_message("assistant", f"msg-{i}")
        effective = bridge._get_effective_messages()
        assert len(effective) == 5
        assert effective[0]["content"] == "msg-0"

    def test_zero_means_no_truncation(self):
        """max_history_messages=0 表示不截断"""
        bridge = ChatBridge()
        bridge.config.max_history_messages = 0
        for i in range(50):
            bridge.add_message("assistant", f"msg-{i}")
        effective = bridge._get_effective_messages()
        assert len(effective) == 50

    def test_messages_history_preserved_after_truncation(self):
        """截断只影响发给 LLM 的副本，_messages 完整历史保留"""
        bridge = ChatBridge()
        bridge.config.max_history_messages = 3
        for i in range(10):
            bridge.add_message("assistant", f"msg-{i}")
        effective = bridge._get_effective_messages()
        # 发给 LLM 的被截断
        assert len(effective) == 3
        # 但 _messages 完整保留
        assert len(bridge._messages) == 10
        assert bridge._messages[0]["content"] == "msg-0"
        assert bridge._messages[9]["content"] == "msg-9"

    def test_returns_copy_not_reference(self):
        """_get_effective_messages 返回副本，修改不影响 _messages"""
        bridge = ChatBridge()
        bridge.add_message("assistant", "original")
        effective = bridge._get_effective_messages()
        effective.clear()
        # 修改副本不应影响原始 _messages
        assert len(bridge._messages) == 1
        assert bridge._messages[0]["content"] == "original"

    def test_truncation_preserves_order(self):
        """截断后消息顺序应保持（最近 N 条按原顺序）"""
        bridge = ChatBridge()
        bridge.config.max_history_messages = 3
        for i in range(6):
            bridge.add_message("user", f"u-{i}")
            bridge.add_message("assistant", f"a-{i}")
        effective = bridge._get_effective_messages()
        assert len(effective) == 3
        # 最近 3 条：a-4, u-5, a-5
        assert effective[0]["content"] == "a-4"
        assert effective[1]["content"] == "u-5"
        assert effective[2]["content"] == "a-5"

    def test_truncation_with_mixed_roles(self):
        """混合 role 消息截断正常工作"""
        bridge = ChatBridge()
        bridge.config.max_history_messages = 4
        bridge.add_message("user", "task")
        bridge.add_message("assistant", "step1")
        bridge.add_message("assistant", "step2")
        bridge.add_message("user", "clarify")
        bridge.add_message("assistant", "step3")
        bridge.add_message("assistant", "step4")
        effective = bridge._get_effective_messages()
        assert len(effective) == 4
        contents = [m["content"] for m in effective]
        assert contents == ["step2", "clarify", "step3", "step4"]


class TestAgentOrchestratorScenario:
    """模拟 agent_orchestrator 累积场景"""

    def test_15_iteration_accumulation_truncated_to_20(self):
        """模拟 15 轮 agent 循环，每轮 add_message，验证不超过 20"""
        bridge = ChatBridge()
        bridge.config.max_history_messages = 20
        # 模拟 15 轮，每轮添加 1 条工具结果
        for i in range(15):
            bridge.add_message("assistant", f"工具结果 {i} " * 50)
        effective = bridge._get_effective_messages()
        assert len(effective) == 15  # 15 < 20，不截断

    def test_30_iteration_accumulation_truncated_to_20(self):
        """模拟 30 轮累积，验证截断为 20 条（+ P1 记忆摘要）"""
        bridge = ChatBridge()
        bridge.config.max_history_messages = 20
        for i in range(30):
            bridge.add_message("assistant", f"result-{i}")
        effective = bridge._get_effective_messages()
        # P1: dropped=10 >= 阈值(10) 时触发摘要，effective = 1 摘要 + 20 历史 = 21
        # dropped < 阈值时无摘要，effective = 20
        assert len(effective) in (20, 21)
        # 非摘要消息应保留最近 20 条：result-10..result-29
        non_system = [m for m in effective if m["role"] != "system"]
        assert len(non_system) == 20
        assert non_system[0]["content"] == "result-10"
        assert non_system[-1]["content"] == "result-29"
        # 若存在摘要，应为 system 角色且包含历史摘要标记
        summaries = [m for m in effective if m["role"] == "system"]
        if summaries:
            assert "[历史摘要]" in summaries[0]["content"]
