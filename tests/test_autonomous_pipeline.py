"""AutonomousPipeline 集成测试"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pycoder.server.services.autonomous_pipeline import (
    AutonomousPipeline,
    PipelineRun,
    PipelineStatus,
    StepResult,
    StepStatus,
    _infer_project_name,
    _execute_agent_tool,
    _parse_tool_calls,
    ALLOWED_COMMANDS,
)


class TestProjectNameInference:
    """项目名推断测试"""

    def test_chinese_keywords(self):
        assert "user-system" == _infer_project_name("做一个用户管理系统")
        assert "blog-system" == _infer_project_name("写一个博客系统")
        assert "library-system" == _infer_project_name("图书管理系统")

    def test_fallback(self):
        name = _infer_project_name("xyz unknown project")
        assert isinstance(name, str) and len(name) > 0


class TestToolExecution:
    """工具执行测试"""

    @pytest.fixture
    def temp_ws(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "test.py").write_text("print('hello')", encoding="utf-8")
            (ws / "sub").mkdir()
            (ws / "sub" / "nested.py").write_text("x = 1", encoding="utf-8")
            yield ws

    @pytest.mark.asyncio
    async def test_list_files(self, temp_ws):
        r = await _execute_agent_tool("list_files", {"path": "."}, temp_ws)
        assert "test.py" in r
        assert "sub" in r

    @pytest.mark.asyncio
    async def test_read_file(self, temp_ws):
        r = await _execute_agent_tool("read_file", {"path": "test.py"}, temp_ws)
        assert "hello" in r

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, temp_ws):
        r = await _execute_agent_tool("read_file", {"path": "nope.py"}, temp_ws)
        assert "文件不存在" in r

    @pytest.mark.asyncio
    async def test_write_file(self, temp_ws):
        r = await _execute_agent_tool(
            "write_file",
            {"path": "new.py", "content": "x = 42"},
            temp_ws,
        )
        assert "已写入" in r
        assert (temp_ws / "new.py").exists()

    @pytest.mark.asyncio
    async def test_write_file_path_traversal(self, temp_ws):
        """路径越界应被拒绝"""
        r = await _execute_agent_tool(
            "write_file",
            {"path": "../outside.py", "content": "bad"},
            temp_ws,
        )
        assert "路径越界" in r

    @pytest.mark.asyncio
    async def test_search_code(self, temp_ws):
        r = await _execute_agent_tool(
            "search_code", {"query": "hello"}, temp_ws,
        )
        assert "test.py" in r

    def test_command_whitelist(self):
        """验证白名单包含开发常用命令"""
        assert "pytest" in ALLOWED_COMMANDS
        assert "uvicorn" in ALLOWED_COMMANDS
        assert "docker" in ALLOWED_COMMANDS
        assert "pip" in ALLOWED_COMMANDS
        assert "ruff" in ALLOWED_COMMANDS


class TestToolCallParsing:
    """工具调用 JSON 解析测试"""

    def test_json_block(self):
        text = '```json\n{"tool_calls": [{"name": "read_file", "params": {"path": "x.py"}}]}\n```'
        calls = _parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "read_file"

    def test_plain_json(self):
        text = '{"tool_calls": [{"name": "list_files", "params": {}}]}'
        calls = _parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "list_files"

    def test_xml_format_no_longer_supported(self):
        """P1-2: XML 标签格式不再被解析，应返回空列表

        如需向后兼容旧 LLM 输出，请显式调用 parse_tool_calls_legacy_xml。
        """
        text = '<tool name="write_file"><parameter name="path">a.py</parameter><parameter name="content">c</parameter></tool>'
        calls = _parse_tool_calls(text)
        assert calls == [], "XML 格式应不再被 parse_tool_calls 解析"

    def test_no_tools(self):
        calls = _parse_tool_calls("这是一段普通文本")
        assert calls == []


class TestPipelineRun:
    """流水线数据模型测试"""

    def test_pipeline_run_creation(self):
        run = PipelineRun(request="测试任务")
        assert run.status == PipelineStatus.PENDING
        assert len(run.id) > 0
        assert run.progress == 0

    def test_pipeline_run_to_dict(self):
        run = PipelineRun(request="测试")
        d = run.to_dict()
        assert "id" in d
        assert d["status"] == "pending"
        assert d["request"] == "测试"

    def test_step_result_duration(self):
        step = StepResult(name="test", status=StepStatus.OK)
        assert step.duration_ms == 0.0
        step.started_at = 1000.0
        step.completed_at = 2000.0
        assert step.duration_ms == 1000000.0


class TestAutonomousPipeline:
    """AutonomousPipeline 类测试"""

    def test_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = AutonomousPipeline(workspace_root=tmp)
            assert p.workspace == Path(tmp).resolve()

    def test_list_runs_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = AutonomousPipeline(workspace_root=tmp)
            assert p.list_runs() == []

    def test_cancel_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = AutonomousPipeline(workspace_root=tmp)
            assert p.cancel_run("nonexistent") is False
