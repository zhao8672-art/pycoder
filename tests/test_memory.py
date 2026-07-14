"""memory 模块测试 — 会话记忆引擎"""
from __future__ import annotations

import pytest

from pycoder.memory.session_memory import SessionMemoryEngine, SessionMemory


class TestSessionMemoryEngine:
    @pytest.fixture
    def engine(self, tmp_path):
        return SessionMemoryEngine(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_start_session(self, engine):
        session = await engine.start_session("test_session_1")
        assert isinstance(session, SessionMemory)
        assert session.session_id == "test_session_1"
        assert session.message_count == 0

    @pytest.mark.asyncio
    async def test_start_session_auto_id(self, engine):
        session = await engine.start_session()
        assert session.session_id.startswith("session_")

    @pytest.mark.asyncio
    async def test_record_decision(self, engine):
        await engine.start_session("test_session_2")
        await engine.record_decision("使用 SQLite 替代 JSON 文件")
        assert engine.current_session is not None
        assert "使用 SQLite 替代 JSON 文件" in engine.current_session.key_decisions

    @pytest.mark.asyncio
    async def test_record_file_activity(self, engine):
        await engine.start_session("test_session_3")
        await engine.record_file_activity("src/main.py")
        await engine.record_file_activity("src/main.py")  # 去重
        assert engine.current_session is not None
        assert engine.current_session.active_files == ["src/main.py"]

    @pytest.mark.asyncio
    async def test_set_task_progress(self, engine):
        await engine.start_session("test_session_4")
        await engine.set_task_progress("完成数据库迁移")
        assert engine.current_session is not None
        assert engine.current_session.task_progress == "完成数据库迁移"

    @pytest.mark.asyncio
    async def test_set_user_preference(self, engine):
        await engine.start_session("test_session_5")
        await engine.set_user_preference("theme", "dark")
        assert engine.current_session is not None
        assert engine.current_session.user_preferences == {"theme": "dark"}

    @pytest.mark.asyncio
    async def test_end_session_without_llm(self, engine):
        await engine.start_session("test_session_6")
        await engine.record_decision("测试决策")
        await engine.set_task_progress("测试任务")
        summary = await engine.end_session()
        assert isinstance(summary, str)
        assert len(summary) > 0
        assert engine.current_session is None

    @pytest.mark.asyncio
    async def test_end_session_persists(self, tmp_path):
        engine = SessionMemoryEngine(workspace=tmp_path)
        await engine.start_session("test_session_7")
        await engine.record_decision("持久化测试")
        await engine.end_session()

        # 验证文件已保存
        saved = tmp_path / ".pycoder" / "sessions" / "test_session_7.json"
        assert saved.exists()

    @pytest.mark.asyncio
    async def test_load_last_summary(self, tmp_path):
        engine1 = SessionMemoryEngine(workspace=tmp_path)
        await engine1.start_session("test_session_8")
        await engine1.record_decision("上次会话的决策")
        await engine1.set_task_progress("上次会话的任务")
        await engine1.end_session()

        # 新引擎启动，应该加载上次摘要
        engine2 = SessionMemoryEngine(workspace=tmp_path)
        session = await engine2.start_session("test_session_9")
        assert "上次会话" in session.summary

    @pytest.mark.asyncio
    async def test_list_sessions(self, tmp_path):
        engine = SessionMemoryEngine(workspace=tmp_path)
        await engine.start_session("s1")
        await engine.end_session()
        await engine.start_session("s2")
        await engine.end_session()

        sessions = engine.list_sessions()
        assert len(sessions) >= 2
        session_ids = [s["session_id"] for s in sessions]
        assert "s1" in session_ids
        assert "s2" in session_ids

    @pytest.mark.asyncio
    async def test_get_session(self, tmp_path):
        engine = SessionMemoryEngine(workspace=tmp_path)
        await engine.start_session("s_get")
        await engine.record_decision("获取测试")
        await engine.end_session()

        data = engine.get_session("s_get")
        assert data is not None
        assert data["session_id"] == "s_get"

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, engine):
        data = engine.get_session("nonexistent_session")
        assert data is None

    @pytest.mark.asyncio
    async def test_delete_session(self, tmp_path):
        engine = SessionMemoryEngine(workspace=tmp_path)
        await engine.start_session("s_delete")
        await engine.end_session()

        assert engine.delete_session("s_delete") is True
        assert engine.get_session("s_delete") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, engine):
        assert engine.delete_session("nonexistent") is False

    @pytest.mark.asyncio
    async def test_search_sessions(self, tmp_path):
        engine = SessionMemoryEngine(workspace=tmp_path)
        await engine.start_session("s_search1")
        await engine.record_decision("数据库优化")
        await engine.end_session()
        await engine.start_session("s_search2")
        await engine.record_decision("前端重构")
        await engine.end_session()

        results = engine.search_sessions("数据库")
        assert len(results) >= 1
        assert results[0]["session_id"] == "s_search1"

    @pytest.mark.asyncio
    async def test_search_no_match(self, tmp_path):
        engine = SessionMemoryEngine(workspace=tmp_path)
        await engine.start_session("s1")
        await engine.end_session()

        results = engine.search_sessions("不存在的关键词xyz")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_export_session(self, tmp_path):
        engine = SessionMemoryEngine(workspace=tmp_path)
        await engine.start_session("s_export")
        await engine.record_decision("导出测试")
        await engine.set_task_progress("测试导出")
        await engine.record_file_activity("test.py")
        await engine.end_session()

        markdown = engine.export_session("s_export")
        assert markdown is not None
        assert "# 会话" in markdown
        assert "导出测试" in markdown

    @pytest.mark.asyncio
    async def test_export_nonexistent(self, engine):
        markdown = engine.export_session("nonexistent")
        assert markdown is None

    @pytest.mark.asyncio
    async def test_record_token_usage(self, engine):
        await engine.start_session("test_tokens")
        engine.record_token_usage({"input": 500, "output": 200})
        assert engine.current_session is not None
        assert engine.current_session.token_usage == {"input": 500, "output": 200}

    @pytest.mark.asyncio
    async def test_empty_session_end(self, engine):
        await engine.start_session("test_empty")
        summary = await engine.end_session()
        assert isinstance(summary, str)