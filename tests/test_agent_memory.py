"""P1: Agent 记忆系统测试

覆盖:
  - FactExtractor: 文件引用/决策/错误模式提取
  - MessageSummarizer: 消息压缩
  - MemoryStore: SQLite 持久化
  - AgentMemoryManager: 统一管理器
  - ChatBridge 集成: 超阈值时压缩旧消息
  - ReActLoop 集成: 注入关键事实 + 持久化
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pycoder.server.services.agent_memory import (
    AgentMemoryManager,
    Fact,
    FactExtractor,
    MemoryStore,
    MessageSummarizer,
    Summary,
)


# ══════════════════════════════════════════════════════════
# FactExtractor
# ══════════════════════════════════════════════════════════


class TestFactExtractor:
    """关键事实提取"""

    def test_extract_file_refs(self):
        ext = FactExtractor()
        msgs = [
            {"role": "user", "content": "请修改 src/main.py 和 tests/test_app.py"},
            {"role": "assistant", "content": "已修改 ./pycoder/server/app.py"},
        ]
        facts = ext.extract(msgs)
        file_facts = [f for f in facts if f.type == "file_ref"]
        paths = {f.content for f in file_facts}
        assert "src/main.py" in paths
        assert "tests/test_app.py" in paths
        # ./ 前缀被清理，但应包含 pycoder/server/app.py 子路径
        assert any("pycoder/server/app.py" in p for p in paths)

    def test_extract_decisions(self):
        ext = FactExtractor()
        msgs = [
            {"role": "assistant", "content": "我决定采用 FastAPI 重构这个模块。"},
            {"role": "assistant", "content": "选择 SQLite 作为持久化方案。"},
        ]
        facts = ext.extract(msgs)
        decisions = [f for f in facts if f.type == "decision"]
        assert len(decisions) >= 2
        assert any("FastAPI" in d.content for d in decisions)

    def test_extract_errors(self):
        ext = FactExtractor()
        msgs = [
            {"role": "tool", "content": "Error: FileNotFoundError: config.json not found"},
            {"role": "assistant", "content": "测试失败，需要修复。"},
        ]
        facts = ext.extract(msgs)
        errors = [f for f in facts if f.type == "error_pattern"]
        assert len(errors) >= 1
        assert any("FileNotFoundError" in e.content for e in errors)

    def test_dedup_facts(self):
        ext = FactExtractor()
        msgs = [
            {"role": "user", "content": "修改 main.py"},
            {"role": "assistant", "content": "已修改 main.py"},
        ]
        facts = ext.extract(msgs)
        file_facts = [f for f in facts if f.type == "file_ref"]
        # 同一路径应只保留一条
        assert len(file_facts) == 1

    def test_empty_messages(self):
        ext = FactExtractor()
        assert ext.extract([]) == []
        assert ext.extract([{"role": "user", "content": ""}]) == []


# ══════════════════════════════════════════════════════════
# MessageSummarizer
# ══════════════════════════════════════════════════════════


class TestMessageSummarizer:
    """消息摘要器"""

    def test_summarize_empty(self):
        s = MessageSummarizer()
        result = s.summarize([])
        assert result.text == ""
        assert result.original_count == 0

    def test_summarize_short_history(self):
        """少量消息仍生成摘要（包含关键事实）"""
        s = MessageSummarizer()
        msgs = [
            {"role": "user", "content": "修改 main.py"},
            {"role": "assistant", "content": "已修改"},
        ]
        result = s.summarize(msgs)
        assert "main.py" in result.text
        assert result.original_count == 2

    def test_summarize_long_history_truncates(self):
        """长消息历史会被截断到上限"""
        s = MessageSummarizer()
        msgs = []
        for i in range(20):
            msgs.append({"role": "user", "content": f"消息 {i} 涉及 file_{i}.py"})
            msgs.append({"role": "assistant", "content": f"回复 {i}" + "x" * 200})
        result = s.summarize(msgs)
        assert len(result.text) <= 1600  # _SUMMARY_MAX_LEN + 容差

    def test_summarize_includes_file_refs(self):
        s = MessageSummarizer()
        msgs = [
            {"role": "user", "content": "请修改 src/app.py 和 tests/test_app.py"},
            {"role": "assistant", "content": "已修改"},
            {"role": "user", "content": "继续修改 lib/utils.py"},
        ]
        result = s.summarize(msgs)
        assert "涉及文件" in result.text
        assert "src/app.py" in result.text


# ══════════════════════════════════════════════════════════
# MemoryStore
# ══════════════════════════════════════════════════════════


class TestMemoryStore:
    """SQLite 持久化"""

    def test_save_and_load_facts(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "memory.db")
        facts = [
            Fact(type="file_ref", content="main.py"),
            Fact(type="decision", content="采用 FastAPI"),
        ]
        saved = store.save_facts("sess-1", facts)
        assert saved >= 1
        loaded = store.load_facts("sess-1")
        assert len(loaded) >= 2

    def test_load_by_type(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "memory.db")
        facts = [
            Fact(type="file_ref", content="a.py"),
            Fact(type="decision", content="决定 X"),
        ]
        store.save_facts("sess-1", facts)
        file_facts = store.load_facts("sess-1", fact_type="file_ref")
        assert all(f.type == "file_ref" for f in file_facts)
        assert any(f.content == "a.py" for f in file_facts)

    def test_dedup_on_save(self, tmp_path):
        """相同事实重复保存应去重"""
        store = MemoryStore(db_path=tmp_path / "memory.db")
        fact = Fact(type="file_ref", content="main.py")
        store.save_facts("sess-1", [fact])
        store.save_facts("sess-1", [fact])
        loaded = store.load_facts("sess-1")
        file_facts = [f for f in loaded if f.type == "file_ref"]
        assert len(file_facts) == 1

    def test_clear_session(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "memory.db")
        store.save_facts("sess-1", [Fact(type="file_ref", content="a.py")])
        deleted = store.clear_session("sess-1")
        assert deleted >= 1
        assert store.load_facts("sess-1") == []

    def test_session_isolation(self, tmp_path):
        """不同会话的事实互不干扰"""
        store = MemoryStore(db_path=tmp_path / "memory.db")
        store.save_facts("sess-1", [Fact(type="file_ref", content="a.py")])
        store.save_facts("sess-2", [Fact(type="file_ref", content="b.py")])
        s1 = store.load_facts("sess-1")
        s2 = store.load_facts("sess-2")
        assert all(f.content == "a.py" for f in s1 if f.type == "file_ref")
        assert all(f.content == "b.py" for f in s2 if f.type == "file_ref")


# ══════════════════════════════════════════════════════════
# AgentMemoryManager
# ══════════════════════════════════════════════════════════


class TestAgentMemoryManager:
    """统一记忆管理器"""

    def test_compress_short_history_returns_empty(self, tmp_path):
        m = AgentMemoryManager(store=MemoryStore(db_path=tmp_path / "m.db"))
        # 少于阈值（_SUMMARY_THRESHOLD=10）
        msgs = [{"role": "user", "content": "hi"}]
        assert m.compress_history(msgs) == ""

    def test_compress_long_history_returns_summary(self, tmp_path):
        m = AgentMemoryManager(store=MemoryStore(db_path=tmp_path / "m.db"))
        msgs = []
        for i in range(6):
            msgs.append({"role": "user", "content": f"修改 file_{i}.py"})
            msgs.append({"role": "assistant", "content": f"已修改 file_{i}.py"})
        # 12 条消息 > 10（阈值）
        result = m.compress_history(msgs)
        assert "[历史摘要]" in result
        assert "file_" in result

    def test_persist_and_build_context(self, tmp_path):
        m = AgentMemoryManager(store=MemoryStore(db_path=tmp_path / "m.db"))
        msgs = [
            {"role": "user", "content": "修改 main.py"},
            {"role": "assistant", "content": "决定采用 FastAPI 重构"},
        ]
        m.persist_facts("sess-1", msgs)
        ctx = m.build_fact_context("sess-1")
        assert "[关键事实]" in ctx
        assert "main.py" in ctx

    def test_build_context_empty_session(self, tmp_path):
        m = AgentMemoryManager(store=MemoryStore(db_path=tmp_path / "m.db"))
        assert m.build_fact_context("nonexistent") == ""

    def test_invalidate_cache(self, tmp_path):
        m = AgentMemoryManager(store=MemoryStore(db_path=tmp_path / "m.db"))
        msgs = [{"role": "user", "content": "修改 main.py"}]
        m.persist_facts("sess-1", msgs)
        ctx1 = m.build_fact_context("sess-1")
        m.invalidate_cache("sess-1")
        ctx2 = m.build_fact_context("sess-1")
        assert ctx1 == ctx2  # 内容相同（重新加载）


# ══════════════════════════════════════════════════════════
# ChatBridge 集成
# ══════════════════════════════════════════════════════════


class TestChatBridgeMemoryIntegration:
    """ChatBridge 超阈值时压缩旧消息"""

    def test_short_history_no_compression(self):
        from pycoder.server.chat_bridge import ChatBridge
        bridge = ChatBridge()
        bridge.config.max_history_messages = 20
        for i in range(5):
            bridge.add_message("user", f"msg {i}")
        effective = bridge._get_effective_messages()
        assert len(effective) == 5
        # 不应有摘要 system 消息
        assert not any(m["role"] == "system" for m in effective)

    def test_long_history_compressed(self):
        from pycoder.server.chat_bridge import ChatBridge
        bridge = ChatBridge()
        bridge.config.max_history_messages = 5
        # 添加 15 条消息（含文件引用）
        for i in range(15):
            bridge.add_message("user", f"修改 file_{i}.py")
            bridge.add_message("assistant", f"已修改 file_{i}.py")
        effective = bridge._get_effective_messages()
        # 应有 1 条 system 摘要 + 5 条最近消息
        system_msgs = [m for m in effective if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert "[历史摘要]" in system_msgs[0]["content"]
        # 最近 5 条保留完整
        non_system = [m for m in effective if m["role"] != "system"]
        assert len(non_system) == 5


# ══════════════════════════════════════════════════════════
# ReActLoop 集成
# ══════════════════════════════════════════════════════════


class TestReActLoopMemoryIntegration:
    """ReActLoop 注入关键事实 + 持久化"""

    def test_no_session_id_skips_memory(self):
        from pycoder.server.services.agent_react_loop import ReActLoop
        loop = ReActLoop(llm=MagicMock(), tool_executor=MagicMock())
        assert loop._load_fact_context() == ""

    def test_load_fact_context_with_session(self, tmp_path, monkeypatch):
        from pycoder.server.services.agent_memory import get_memory_manager
        from pycoder.server.services.agent_react_loop import ReActLoop

        # 用临时 DB
        manager = AgentMemoryManager(store=MemoryStore(db_path=tmp_path / "m.db"))
        manager.persist_facts("sess-1", [
            {"role": "user", "content": "修改 main.py"},
        ])
        monkeypatch.setattr(
            "pycoder.server.services.agent_memory._manager_instance", manager
        )

        loop = ReActLoop(llm=MagicMock(), tool_executor=MagicMock(), session_id="sess-1")
        ctx = loop._load_fact_context()
        assert "main.py" in ctx

    def test_persist_facts_on_finish(self, tmp_path, monkeypatch):
        from pycoder.server.services.agent_react_loop import ReActStep

        manager = AgentMemoryManager(store=MemoryStore(db_path=tmp_path / "m.db"))
        monkeypatch.setattr(
            "pycoder.server.services.agent_memory._manager_instance", manager
        )

        from pycoder.server.services.agent_react_loop import ReActLoop
        loop = ReActLoop(llm=MagicMock(), tool_executor=MagicMock(), session_id="sess-1")
        steps = [
            ReActStep(
                thought="决定修改 src/app.py 采用 FastAPI",
                action="FINISH",
                action_input={},
                observation="",
                iteration=1,
            ),
        ]
        loop._persist_facts("重构 app.py", steps)

        facts = manager.store.load_facts("sess-1")
        assert len(facts) >= 1
        assert any("app.py" in f.content for f in facts)
