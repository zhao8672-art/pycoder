"""pycoder.server.services.autonomous_pipeline 单元测试（覆盖率补充版）

测试策略:
  - 纯函数（解析器、完成信号检测、项目名推断）直接测试
  - _agent_loop 用 FakeChatBridge 注入预定义响应序列
  - 各 _step_* 方法独立测试，mock 掉 task_decomposer / QualityGuard / TestGenerator
  - 完整 run() 流程测试用 monkeypatch 替换所有外部依赖
  - subprocess / shutil 用 monkeypatch mock
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pycoder.server.services import autonomous_pipeline as ap
from pycoder.server.services.autonomous_pipeline import (
    ALLOWED_COMMANDS,
    AutonomousPipeline,
    MAX_AGENT_ITERATIONS,
    MAX_FIX_ROUNDS,
    PipelineRun,
    PipelineStatus,
    StepResult,
    StepStatus,
    _agent_loop,
    _extract_all_files,
    _infer_project_name,
    _is_completion_signal,
    _parse_code_blocks,
    _parse_files_from_response,
    _parse_tool_calls,
    _record_pipeline_learning,
    _write_extracted_files,
    get_pipeline,
)


# ══════════════════════════════════════════════════════════
# 辅助：mock registry.resolve
# ══════════════════════════════════════════════════════════

def _mock_registry_resolve(monkeypatch):
    """Mock registry.resolve 返回模拟 LLM 对象"""
    mock_llm = MagicMock()
    mock_llm.configure = MagicMock()
    mock_llm.close = AsyncMock()
    mock_llm.config = SimpleNamespace(system_prompt="", max_tokens=16384)
    mock_llm.chat_stream = AsyncMock(return_value=AsyncMock())
    mock_llm.add_message = MagicMock()
    monkeypatch.setattr(ap.registry, "resolve", lambda *args, **kwargs: mock_llm)
    return mock_llm


# ══════════════════════════════════════════════════════════
# 辅助：FakeChatBridge
# ══════════════════════════════════════════════════════════

class FakeChatEvent:
    """模拟 ChatEvent"""
    def __init__(self, event_type, content=""):
        self.event_type = event_type
        self.content = content


class FakeChatBridge:
    """模拟 ChatBridge — 按预定义序列返回响应

    每次调用 chat_stream(message) 返回列表中下一个响应（作为 done 事件）。
    """

    def __init__(self, responses=None, events_per_call=None):
        """
        Args:
            responses: list[str] - 每次调用返回的 done 内容
            events_per_call: list[list[dict]] - 更细粒度控制，每次调用返回的事件列表
                           如 [{"type": "token", "content": "x"}, {"type": "done", "content": "x"}]
        """
        self._responses = list(responses or [])
        self._events_per_call = events_per_call or []
        self._call_index = 0
        self.config = SimpleNamespace(
            system_prompt="", max_tokens=16384, enable_cache=True,
            model="test-model", api_key="test-key", temperature=0.7,
            api_base="http://test", max_history_messages=0,
            enable_thinking=False, reasoning_effort="medium",
        )
        self._messages = []
        self.added_messages = []
        self.closed = False
        self.configured_with = []

    def configure(self, model=None, api_key=None):
        if model:
            self.config.model = model
            self.configured_with.append(("model", model))
        if api_key:
            self.config.api_key = api_key

    def add_message(self, role, content):
        self.added_messages.append({"role": role, "content": content})

    async def chat_stream(self, message):
        if self._events_per_call:
            events = (self._events_per_call[self._call_index]
                      if self._call_index < len(self._events_per_call)
                      else [{"type": "done", "content": "完成"}])
        else:
            content = (self._responses[self._call_index]
                       if self._call_index < len(self._responses)
                       else "完成")
            events = [{"type": "done", "content": content}]
        self._call_index += 1

        for ev in events:
            etype = ev.get("type", "done")
            content = ev.get("content", "")
            if etype == "token":
                yield FakeChatEvent(event_type="token", content=content)
            elif etype == "done":
                yield FakeChatEvent(event_type="done", content=content)
                return
            elif etype == "error":
                yield FakeChatEvent(event_type="error", content=content)
                return

    async def close(self):
        self.closed = True


# ══════════════════════════════════════════════════════════
# 1. 纯函数测试
# ══════════════════════════════════════════════════════════

class TestParseFilesFromResponse:
    """_parse_files_from_response: FILE:...```END 格式"""

    def test_single_file(self):
        text = '```FILE:src/main.py\nprint("hello")\n```END'
        files = _parse_files_from_response(text)
        assert len(files) == 1
        assert files[0]["path"] == "src/main.py"
        assert 'print("hello")' in files[0]["content"]

    def test_multiple_files(self):
        text = (
            '```FILE:a.py\nx = 1\n```END\n'
            '```FILE:b.py\ny = 2\n```END'
        )
        files = _parse_files_from_response(text)
        assert len(files) == 2
        assert files[0]["path"] == "a.py"
        assert files[1]["path"] == "b.py"

    def test_no_files(self):
        assert _parse_files_from_response("just text") == []
        assert _parse_files_from_response("") == []


class TestParseCodeBlocks:
    """_parse_code_blocks: 多种格式"""

    def test_format1_lang_path(self):
        text = '```python:src/app.py\nx = 1\n```'
        files = _parse_code_blocks(text)
        assert len(files) == 1
        assert files[0]["path"] == "src/app.py"
        assert "x = 1" in files[0]["content"]

    def test_format2_file_header(self):
        text = '# 文件: app.py\n```python\nx = 1\n```'
        files = _parse_code_blocks(text)
        assert len(files) == 1
        assert files[0]["path"] == "app.py"

    def test_format2_file_header_english(self):
        text = '# file: app.py\n```python\nx = 1\n```'
        files = _parse_code_blocks(text)
        assert len(files) == 1

    def test_format3_write_tag(self):
        text = '[WRITE app.py]\n```python\nx = 1\n```'
        files = _parse_code_blocks(text)
        assert len(files) == 1
        assert files[0]["path"] == "app.py"

    def test_format4_create_header(self):
        text = '## 创建文件: app.py\n```python\nx = 1\n```'
        files = _parse_code_blocks(text)
        assert len(files) == 1
        assert files[0]["path"] == "app.py"

    def test_format4_generate_header(self):
        text = '### 生成: mod.py\n```python\nx = 1\n```'
        files = _parse_code_blocks(text)
        assert len(files) == 1

    def test_deduplication(self):
        """同一文件路径出现多次只保留第一次"""
        text = (
            '```python:app.py\nx = 1\n```\n'
            '# 文件: app.py\n```python\ny = 2\n```'
        )
        files = _parse_code_blocks(text)
        # 第一次格式1匹配，第二次格式2因为路径相同被跳过
        assert len(files) == 1
        assert "x = 1" in files[0]["content"]

    def test_no_code_blocks(self):
        assert _parse_code_blocks("plain text") == []


class TestExtractAllFiles:
    """_extract_all_files: 组合解析"""

    def test_combines_both_parsers(self):
        text = (
            '```FILE:a.py\nx = 1\n```END\n'
            '```python:b.py\ny = 2\n```'
        )
        files = _extract_all_files(text)
        assert len(files) == 2
        paths = {f["path"] for f in files}
        assert "a.py" in paths
        assert "b.py" in paths

    def test_deduplication(self):
        """同一路径在两种格式中都出现时去重"""
        text = (
            '```FILE:app.py\nx = 1\n```END\n'
            '```python:app.py\ny = 2\n```'
        )
        files = _extract_all_files(text)
        assert len(files) == 1

    def test_empty(self):
        assert _extract_all_files("") == []


class TestWriteExtractedFiles:
    """_write_extracted_files"""

    def test_writes_files(self, tmp_path):
        files = [
            {"path": "src/main.py", "content": "x = 1"},
            {"path": "README.md", "content": "# test"},
        ]
        written = _write_extracted_files(files, tmp_path)
        assert set(written) == {"src/main.py", "README.md"}
        assert (tmp_path / "src" / "main.py").read_text(encoding="utf-8") == "x = 1"
        assert (tmp_path / "README.md").read_text(encoding="utf-8") == "# test"

    def test_path_traversal_rejected(self, tmp_path):
        """路径穿越的文件不会被写入"""
        files = [
            {"path": "../escape.py", "content": "bad"},
            {"path": "ok.py", "content": "good"},
        ]
        written = _write_extracted_files(files, tmp_path)
        assert "ok.py" in written
        assert "../escape.py" not in written
        assert not (tmp_path.parent / "escape.py").exists()

    def test_empty_list(self, tmp_path):
        assert _write_extracted_files([], tmp_path) == []


class TestIsCompletionSignal:
    """_is_completion_signal: 完成信号检测"""

    def test_chinese_variants(self):
        assert _is_completion_signal("完成") is True
        assert _is_completion_signal("完成！") is True
        assert _is_completion_signal("总结：项目已交付") is True
        assert _is_completion_signal("所有任务已完成") is True
        assert _is_completion_signal("任务完成") is True

    def test_english_variants(self):
        assert _is_completion_signal("done") is True
        assert _is_completion_signal("Done.") is True
        assert _is_completion_signal("all tasks are complete") is True
        assert _is_completion_signal("I have finished") is True
        assert _is_completion_signal("everything is done") is True
        assert _is_completion_signal("the task is done") is True
        assert _is_completion_signal("no more tasks") is True

    def test_separator_finish(self):
        assert _is_completion_signal("--- finish ---") is True
        assert _is_completion_signal("=== 总结 ===") is True

    def test_short_signals(self):
        assert _is_completion_signal("finished") is True
        assert _is_completion_signal("all done") is True
        assert _is_completion_signal("completed") is True
        assert _is_completion_signal("complete") is True
        assert _is_completion_signal("summary") is True

    def test_no_more_semantic(self):
        assert _is_completion_signal("no more work to do") is True
        assert _is_completion_signal("nothing else here") is True

    def test_not_completion(self):
        assert _is_completion_signal("def foo(): pass") is False
        assert _is_completion_signal("```python\nx = 1\n```") is False
        assert _is_completion_signal("正在处理任务...") is False
        # 长文本包含 "no more" 但超过 200 字符不算
        assert _is_completion_signal("no more " + "x" * 250) is False

    def test_empty(self):
        assert _is_completion_signal("") is False
        assert _is_completion_signal("   ") is False


class TestInferProjectName:
    """_infer_project_name"""

    def test_keywords(self):
        assert _infer_project_name("做一个用户系统") == "user-system"
        assert _infer_project_name("图书管理系统") == "library-system"
        assert _infer_project_name("写一个博客") == "blog-system"
        assert _infer_project_name("订单处理") == "order-system"
        assert _infer_project_name("商品列表") == "product-system"
        assert _infer_project_name("股票监控") == "stock-monitor"
        assert _infer_project_name("API 服务") == "api-service"
        assert _infer_project_name("爬虫项目") == "crawler"
        assert _infer_project_name("数据管道") == "data-pipeline"
        assert _infer_project_name("聊天应用") == "chat-app"
        assert _infer_project_name("仪表盘") == "dashboard"
        assert _infer_project_name("监控系统") == "monitor"

    def test_fallback_chinese(self):
        name = _infer_project_name("一个普通的测试项目")
        assert isinstance(name, str)
        # 应取中文词
        assert name != "my-project"

    def test_fallback_default(self):
        assert _infer_project_name("xyz123") == "my-project"
        assert _infer_project_name("") == "my-project"


class TestRecordPipelineLearning:
    """_record_pipeline_learning"""

    def test_import_error_handled(self):
        """learning 模块不存在 → ImportError 被静默捕获"""
        run = PipelineRun(request="test")
        # 不应抛异常
        _record_pipeline_learning(run)

    def test_with_status_enum(self):
        run = PipelineRun(request="test", status=PipelineStatus.DONE)
        run.report = {"score": 85}
        _record_pipeline_learning(run)  # 不应抛异常

    def test_with_status_string(self):
        run = PipelineRun(request="test")
        run.status = "done"  # 字符串而非枚举
        _record_pipeline_learning(run)


# ══════════════════════════════════════════════════════════
# 2. 数据模型测试（补充）
# ══════════════════════════════════════════════════════════

class TestDataModels:
    def test_step_result_duration_zero(self):
        s = StepResult(name="x")
        assert s.duration_ms == 0.0

    def test_step_result_duration_calculated(self):
        s = StepResult(name="x", started_at=1.0, completed_at=2.5)
        assert s.duration_ms == 1500.0

    def test_pipeline_run_to_dict(self):
        run = PipelineRun(request="test request", project_name="proj")
        run.status = PipelineStatus.DONE
        run.progress = 100
        run.completed_at = time.time()
        step = StepResult(name="step1", status=StepStatus.OK, started_at=1.0, completed_at=2.0)
        step.error = "some error"
        run.steps.append(step)

        d = run.to_dict()
        assert d["status"] == "done"
        assert d["project_name"] == "proj"
        assert d["progress"] == 100
        assert len(d["steps"]) == 1
        assert d["steps"][0]["name"] == "step1"
        assert d["steps"][0]["status"] == "ok"
        assert d["steps"][0]["duration_ms"] == 1000

    def test_pipeline_run_to_dict_long_request(self):
        run = PipelineRun(request="x" * 300)
        d = run.to_dict()
        # request 应被截断到 200 字符
        assert len(d["request"]) == 200

    def test_pipeline_run_to_dict_long_error(self):
        run = PipelineRun(request="t")
        step = StepResult(name="x", error="e" * 300)
        run.steps.append(step)
        d = run.to_dict()
        assert len(d["steps"][0]["error"]) == 200

    def test_pipeline_run_default_id(self):
        run1 = PipelineRun()
        run2 = PipelineRun()
        assert run1.id != run2.id
        assert run1.id.startswith("pipeline-")

    def test_pipeline_run_cancel_flag(self):
        run = PipelineRun()
        assert run._cancel_flag is False


# ══════════════════════════════════════════════════════════
# 3. _agent_loop 测试
# ══════════════════════════════════════════════════════════

class TestAgentLoop:
    async def test_immediate_completion(self, tmp_path):
        """LLM 立即回复 '完成'"""
        bridge = FakeChatBridge(responses=["完成"])
        text, files = await _agent_loop(bridge, "task", "system prompt", tmp_path)
        assert text == "完成"
        assert files == []
        assert bridge.config.system_prompt == "system prompt"
        assert bridge.config.max_tokens == 16384
        assert bridge.config.enable_cache is True

    async def test_completion_with_code_blocks(self, tmp_path):
        """LLM 输出代码块后回复 '完成'"""
        bridge = FakeChatBridge(responses=[
            '```python:app.py\nprint("hello")\n```',
            "完成",
        ])
        text, files = await _agent_loop(bridge, "task", "sys", tmp_path)
        assert "app.py" in files
        assert (tmp_path / "app.py").exists()
        assert 'print("hello")' in (tmp_path / "app.py").read_text(encoding="utf-8")

    async def test_completion_with_file_blocks(self, tmp_path):
        """LLM 输出 FILE:...```END 块"""
        bridge = FakeChatBridge(responses=[
            '```FILE:mod.py\nx = 42\n```END',
            "完成",
        ])
        text, files = await _agent_loop(bridge, "task", "sys", tmp_path)
        assert "mod.py" in files
        assert (tmp_path / "mod.py").exists()

    async def test_error_event(self, tmp_path):
        """LLM 返回 error 事件"""
        bridge = FakeChatBridge(events_per_call=[[{"type": "error", "content": "API fail"}]])
        text, files = await _agent_loop(bridge, "task", "sys", tmp_path)
        assert "Agent 错误" in text
        assert "API fail" in text

    async def test_token_then_done(self, tmp_path):
        """LLM 输出 token 流然后 done"""
        bridge = FakeChatBridge(events_per_call=[[
            {"type": "token", "content": "完"},
            {"type": "token", "content": "成"},
            {"type": "done", "content": "完成"},
        ]])
        text, files = await _agent_loop(bridge, "task", "sys", tmp_path)
        assert text == "完成"

    async def test_tool_calls(self, tmp_path, monkeypatch):
        """LLM 输出 JSON 工具调用"""
        # Mock _execute_agent_tool
        async def fake_exec(tool_name, params, workspace):
            return f"tool result: {tool_name}"
        monkeypatch.setattr(ap, "_execute_agent_tool", fake_exec)
        # Mock _parse_tool_calls
        monkeypatch.setattr(ap, "_parse_tool_calls", lambda text: [
            {"name": "list_files", "params": {"path": "."}},
        ] if "list_files" in text else [])

        bridge = FakeChatBridge(responses=[
            '{"tool_calls": [{"name": "list_files", "params": {"path": "."}}]}',
            "完成",
        ])
        text, files = await _agent_loop(bridge, "task", "sys", tmp_path)
        # 应执行工具后继续
        assert any("list_files" in m["content"] for m in bridge.added_messages)

    async def test_write_file_tool_appends_to_files(self, tmp_path, monkeypatch):
        """write_file 工具调用会记录到 files 列表"""
        async def fake_exec(tool_name, params, workspace):
            return "written"
        monkeypatch.setattr(ap, "_execute_agent_tool", fake_exec)
        monkeypatch.setattr(ap, "_parse_tool_calls", lambda text: [
            {"name": "write_file", "params": {"path": "new.py", "content": "x"}},
        ] if "write_file" in text else [])

        bridge = FakeChatBridge(responses=[
            '{"tool_calls": [{"name": "write_file", "params": {"path": "new.py", "content": "x"}}]}',
            "完成",
        ])
        _, files = await _agent_loop(bridge, "task", "sys", tmp_path)
        assert "new.py" in files

    async def test_max_iterations(self, tmp_path):
        """LLM 一直不完成 → 达到 max_iterations"""
        # 每次返回非完成文本，无工具调用，无代码块
        bridge = FakeChatBridge(responses=["继续"] * 30)
        text, files = await _agent_loop(
            bridge, "task", "sys", tmp_path, max_iterations=3,
        )
        # 3 次后退出
        assert bridge._call_index == 3

    async def test_no_tool_no_file_continues(self, tmp_path):
        """LLM 既无工具调用也无代码块 → 继续循环"""
        bridge = FakeChatBridge(responses=[
            "just thinking about the task",
            "完成",
        ])
        text, files = await _agent_loop(bridge, "task", "sys", tmp_path)
        assert text == "完成"

    async def test_final_files_extraction(self, tmp_path):
        """最后一次响应中的代码块也会被提取"""
        bridge = FakeChatBridge(responses=[
            '```python:final.py\nx = 1\n```',
        ])
        # 第一次响应就匹配完成信号？不，它不匹配
        # 但 _is_completion_signal 对 "```python:final.py\nx = 1\n```" 返回 False
        # 所以会进入 tool_calls / files 分支，写入文件后继续
        # 第二次返回 "完成"
        bridge._responses.append("完成")
        _, files = await _agent_loop(bridge, "task", "sys", tmp_path)
        assert "final.py" in files


# ══════════════════════════════════════════════════════════
# 4. _step_decompose 测试
# ══════════════════════════════════════════════════════════

class TestStepDecompose:
    async def test_no_api_key_uses_fallback(self, tmp_path, monkeypatch):
        """无 API key → 使用 _fallback_decomposition"""
        # 关键：构造时 api_key="" 仍会通过 _get_api_key_for_model 读环境变量
        # 必须将 _get_api_key_for_model 也 patch 为空，才能走 fallback 分支
        monkeypatch.setattr(ap, "_get_api_key_for_model", lambda m: "")
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="做一个用户管理系统", work_dir=str(tmp_path))
        # _step_decompose 不推断 project_name（只有 run() 在第535行推断）
        # 手动设置以匹配真实 pipeline 流程
        run.project_name = ap._infer_project_name("做一个用户管理系统")

        step = await pipeline._step_decompose(run)
        assert step.status == StepStatus.OK
        assert step.output["task_count"] > 0
        assert step.output["project_name"] == "user-system"

    async def test_with_api_key_llm_success(self, tmp_path, monkeypatch):
        """有 API key → 使用 LLM 分解"""
        from pycoder.server.services import task_decomposer as td_mod
        from pycoder.server.services.agent_definitions import AgentTask

        fake_tasks = [
            AgentTask(id="t1", title="task1", description="d1",
                      assigned_role="developer", depends_on=[], deliverables=["a.py"]),
        ]
        async def fake_decompose(req, bridge):
            return fake_tasks
        monkeypatch.setattr(td_mod, "decompose_task", fake_decompose)
        # Mock registry.resolve 返回模拟 LLM 对象
        mock_llm = MagicMock()
        mock_llm.configure = MagicMock()
        mock_llm.close = AsyncMock()
        monkeypatch.setattr(ap.registry, "resolve", lambda *args, **kwargs: mock_llm)

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="test-key")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        step = await pipeline._step_decompose(run)
        assert step.status == StepStatus.OK
        assert step.output["task_count"] == 1
        assert step.output["tasks"][0]["title"] == "task1"

    async def test_with_api_key_llm_fails_fallback(self, tmp_path, monkeypatch):
        """LLM 分解失败 → 回退到规则分解"""
        from pycoder.server.services import task_decomposer as td_mod

        async def boom(req, bridge):
            raise RuntimeError("LLM error")
        monkeypatch.setattr(td_mod, "decompose_task", boom)
        mock_llm = MagicMock()
        mock_llm.configure = MagicMock()
        mock_llm.close = AsyncMock()
        monkeypatch.setattr(ap.registry, "resolve", lambda *args, **kwargs: mock_llm)
        

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="test-key")
        run = PipelineRun(request="做一个博客系统", work_dir=str(tmp_path))
        step = await pipeline._step_decompose(run)
        assert step.status == StepStatus.OK
        # 回退分解也会产生任务
        assert step.output["task_count"] > 0

    async def test_import_error(self, tmp_path, monkeypatch):
        """task_decomposer 模块导入失败"""
        import builtins
        orig_import = builtins.__import__
        def fake_import(name, *args, **kwargs):
            if "task_decomposer" in name:
                raise ImportError("no module")
            return orig_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", fake_import)

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        step = await pipeline._step_decompose(run)
        assert step.status == StepStatus.FAILED
        assert "no module" in step.error


# ══════════════════════════════════════════════════════════
# 5. _step_execute 测试
# ══════════════════════════════════════════════════════════

class TestStepExecute:
    @pytest.fixture(autouse=True)
    def _mock_registry(self, monkeypatch):
        """自动 mock registry.resolve 避免 DI 未注册错误"""
        _mock_registry_resolve(monkeypatch)

    async def test_no_tasks(self, tmp_path):
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="decompose", output={"tasks": []}))

        step = await pipeline._step_execute(run)
        assert step.status == StepStatus.FAILED
        assert "无任务" in step.error

    async def test_execute_with_agent_loop(self, tmp_path, monkeypatch):
        """正常执行 — mock _agent_loop 返回文件"""
        async def fake_agent_loop(bridge, task, sys_prompt, workspace, max_iterations=12):
            return "完成", ["app.py", "test_app.py"]
        monkeypatch.setattr(ap, "_agent_loop", fake_agent_loop)
        

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="key")
        run = PipelineRun(request="做一个 API 服务", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="decompose", output={
            "tasks": [
                {"id": "t1", "title": "实现 API", "description": "d",
                 "assigned_role": "developer", "depends_on": [],
                 "deliverables": ["app.py"]},
            ],
        }))

        step = await pipeline._step_execute(run)
        assert step.status == StepStatus.OK
        assert "app.py" in step.output["files_created"]
        assert step.output["tasks_completed"] == 1

    async def test_execute_multiple_tasks_with_deps(self, tmp_path, monkeypatch):
        """多任务依赖顺序执行"""
        executed_order = []
        async def fake_agent_loop(bridge, task, sys_prompt, workspace, max_iterations=12):
            executed_order.append(task)
            return "完成", [f"file_{task[:10]}.py"]
        monkeypatch.setattr(ap, "_agent_loop", fake_agent_loop)
        

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="key")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="decompose", output={
            "tasks": [
                {"id": "t1", "title": "架构", "description": "d",
                 "assigned_role": "architect", "depends_on": [],
                 "deliverables": ["arch.md"]},
                {"id": "t2", "title": "开发", "description": "d",
                 "assigned_role": "developer", "depends_on": ["t1"],
                 "deliverables": ["app.py"]},
            ],
        }))

        step = await pipeline._step_execute(run)
        assert step.status == StepStatus.OK
        assert step.output["tasks_completed"] == 2

    async def test_execute_circular_deps(self, tmp_path, monkeypatch):
        """循环依赖 — 回退执行剩余任务"""
        async def fake_agent_loop(bridge, task, sys_prompt, workspace, max_iterations=12):
            return "完成", []
        monkeypatch.setattr(ap, "_agent_loop", fake_agent_loop)
        

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="key")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="decompose", output={
            "tasks": [
                {"id": "a", "title": "A", "description": "d",
                 "assigned_role": "developer", "depends_on": ["b"],
                 "deliverables": []},
                {"id": "b", "title": "B", "description": "d",
                 "assigned_role": "developer", "depends_on": ["a"],
                 "deliverables": []},
            ],
        }))

        step = await pipeline._step_execute(run)
        assert step.status == StepStatus.OK
        # 循环依赖仍会执行（回退逻辑）
        assert step.output["tasks_completed"] == 2

    async def test_cancel_flag(self, tmp_path, monkeypatch):
        """取消标志中断执行"""
        async def fake_agent_loop(bridge, task, sys_prompt, workspace, max_iterations=12):
            return "完成", []
        monkeypatch.setattr(ap, "_agent_loop", fake_agent_loop)
        

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="key")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run._cancel_flag = True
        run.steps.append(StepResult(name="decompose", output={
            "tasks": [
                {"id": "t1", "title": "T", "description": "d",
                 "assigned_role": "developer", "depends_on": [],
                 "deliverables": []},
            ],
        }))

        step = await pipeline._step_execute(run)
        assert step.status == StepStatus.OK
        # 取消标志下不执行任务
        assert step.output["tasks_completed"] == 0


# ══════════════════════════════════════════════════════════
# 6. _step_review 测试
# ══════════════════════════════════════════════════════════

class TestStepReview:
    async def test_no_files_skipped(self, tmp_path):
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="execute", output={"files_created": []}))

        step = await pipeline._step_review(run)
        assert step.status == StepStatus.SKIPPED

    async def test_review_success(self, tmp_path, monkeypatch):
        """质量审查通过"""
        from pycoder.server.services import quality_guard as qg_mod

        fake_report = SimpleNamespace(score=85, is_pass=lambda min_score=70: True)
        fake_guard = MagicMock()
        fake_guard.check = AsyncMock(return_value=fake_report)
        monkeypatch.setattr(qg_mod, "QualityGuard", MagicMock(return_value=fake_guard))

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="execute", output={"files_created": ["app.py"]}))

        step = await pipeline._step_review(run)
        assert step.status == StepStatus.OK
        assert step.output["report"]["average_score"] == 85
        assert step.output["files_need_fix"] == []

    async def test_review_files_need_fix(self, tmp_path, monkeypatch):
        """质量审查发现需修复文件"""
        from pycoder.server.services import quality_guard as qg_mod

        good_report = SimpleNamespace(score=80, is_pass=lambda min_score=70: True)
        bad_report = SimpleNamespace(score=40, is_pass=lambda min_score=60: False)
        fake_guard = MagicMock()
        fake_guard.check = AsyncMock(side_effect=[good_report, bad_report])
        monkeypatch.setattr(qg_mod, "QualityGuard", MagicMock(return_value=fake_guard))

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="execute", output={
            "files_created": ["good.py", "bad.py"],
        }))

        step = await pipeline._step_review(run)
        assert step.status == StepStatus.OK
        assert "bad.py" in step.output["files_need_fix"]
        assert step.output["report"]["average_score"] == 60  # (80+40)/2

    async def test_review_non_py_files_skipped(self, tmp_path, monkeypatch):
        """非 .py 文件不审查"""
        from pycoder.server.services import quality_guard as qg_mod

        fake_guard = MagicMock()
        fake_guard.check = AsyncMock(return_value=SimpleNamespace(
            score=90, is_pass=lambda min_score=70: True))
        monkeypatch.setattr(qg_mod, "QualityGuard", MagicMock(return_value=fake_guard))

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="execute", output={
            "files_created": ["readme.md", "config.json"],
        }))

        step = await pipeline._step_review(run)
        assert step.status == StepStatus.OK
        # 无 .py 文件 → all_scores 为空 → avg=100
        assert step.output["report"]["average_score"] == 100

    async def test_review_exception(self, tmp_path, monkeypatch):
        from pycoder.server.services import quality_guard as qg_mod
        monkeypatch.setattr(qg_mod, "QualityGuard", MagicMock(side_effect=RuntimeError("init fail")))

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="execute", output={"files_created": ["a.py"]}))

        step = await pipeline._step_review(run)
        assert step.status == StepStatus.FAILED
        assert "init fail" in step.error


# ══════════════════════════════════════════════════════════
# 7. _step_testgen 测试
# ══════════════════════════════════════════════════════════

class TestStepTestgen:
    async def test_no_py_files_skipped(self, tmp_path):
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="review", output={"files_created": ["readme.md"]}))

        step = await pipeline._step_testgen(run)
        assert step.status == StepStatus.SKIPPED

    async def test_testgen_success(self, tmp_path, monkeypatch):
        from pycoder.server.services import test_generator as tg_mod

        fake_result = SimpleNamespace(
            success=True, test_count=5, passed=5, failed=0, coverage_percent=90,
        )
        fake_gen = MagicMock()
        fake_gen.generate.return_value = fake_result
        monkeypatch.setattr(tg_mod, "TestGenerator", MagicMock(return_value=fake_gen))

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="review", output={
            "files_created": ["app.py"],
        }))

        step = await pipeline._step_testgen(run)
        assert step.status == StepStatus.OK
        assert step.output["result"]["success"] is True
        assert step.output["result"]["total_tests"] == 5

    async def test_testgen_with_failure(self, tmp_path, monkeypatch):
        from pycoder.server.services import test_generator as tg_mod

        fake_result = SimpleNamespace(
            success=False, test_count=3, passed=1, failed=2, coverage_percent=40,
        )
        fake_gen = MagicMock()
        fake_gen.generate.return_value = fake_result
        monkeypatch.setattr(tg_mod, "TestGenerator", MagicMock(return_value=fake_gen))

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="review", output={
            "files_created": ["app.py"],
        }))

        step = await pipeline._step_testgen(run)
        assert step.status == StepStatus.OK
        assert step.output["result"]["success"] is False

    async def test_testgen_exception(self, tmp_path, monkeypatch):
        from pycoder.server.services import test_generator as tg_mod
        monkeypatch.setattr(tg_mod, "TestGenerator", MagicMock(side_effect=RuntimeError("init fail")))

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="review", output={"files_created": ["a.py"]}))

        step = await pipeline._step_testgen(run)
        assert step.status == StepStatus.FAILED
        assert "init fail" in step.error


# ══════════════════════════════════════════════════════════
# 8. _step_fixloop 测试
# ══════════════════════════════════════════════════════════

class TestStepFixloop:
    @pytest.fixture(autouse=True)
    def _mock_registry(self, monkeypatch):
        _mock_registry_resolve(monkeypatch)

    async def test_no_files_need_fix_skipped(self, tmp_path):
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="review", output={}))

        step = await pipeline._step_fixloop(run)
        assert step.status == StepStatus.SKIPPED

    async def test_fixloop_with_files(self, tmp_path, monkeypatch):
        """修复需要修复的文件"""
        # 创建需要修复的文件
        (tmp_path / "bad.py").write_text("x = 1", encoding="utf-8")
        async def fake_agent_loop(bridge, task, sys_prompt, workspace, max_iterations=8):
            return "完成", ["bad.py"]
        monkeypatch.setattr(ap, "_agent_loop", fake_agent_loop)
        

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="key")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="review", output={"files_need_fix": ["bad.py"]}))

        step = await pipeline._step_fixloop(run)
        assert step.status == StepStatus.OK
        assert step.output["files_fixed"] == 1

    async def test_fixloop_file_not_exists(self, tmp_path, monkeypatch):
        """文件不存在 → 跳过该文件"""
        async def fake_agent_loop(bridge, task, sys_prompt, workspace, max_iterations=8):
            return "完成", []
        monkeypatch.setattr(ap, "_agent_loop", fake_agent_loop)
        

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="key")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="review", output={"files_need_fix": ["ghost.py"]}))

        step = await pipeline._step_fixloop(run)
        assert step.status == StepStatus.OK
        assert step.output["files_fixed"] == 0

    async def test_fixloop_with_extra_context(self, tmp_path, monkeypatch):
        """有额外上下文但无 files_need_fix → 从 execute 步骤获取文件"""
        (tmp_path / "app.py").write_text("x = 1", encoding="utf-8")
        async def fake_agent_loop(bridge, task, sys_prompt, workspace, max_iterations=8):
            return "完成", ["app.py"]
        monkeypatch.setattr(ap, "_agent_loop", fake_agent_loop)
        

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="key")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="execute", output={"files_created": ["app.py", "readme.md"]}))
        run.steps.append(StepResult(name="accept", output={}))

        step = await pipeline._step_fixloop(run, extra_context="验收失败: 缺少测试")
        assert step.status == StepStatus.OK
        assert step.output["files_fixed"] == 1  # 只有 app.py (readme.md 非 .py)

    async def test_fixloop_cancel_flag(self, tmp_path, monkeypatch):
        async def fake_agent_loop(bridge, task, sys_prompt, workspace, max_iterations=8):
            return "完成", []
        monkeypatch.setattr(ap, "_agent_loop", fake_agent_loop)
        

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="key")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run._cancel_flag = True
        run.steps.append(StepResult(name="review", output={"files_need_fix": ["a.py", "b.py", "c.py"]}))

        step = await pipeline._step_fixloop(run)
        assert step.status == StepStatus.OK
        assert step.output["files_fixed"] == 0  # 取消标志中断

    async def test_fixloop_read_error(self, tmp_path, monkeypatch):
        """读取文件失败 → 跳过"""
        async def fake_agent_loop(bridge, task, sys_prompt, workspace, max_iterations=8):
            return "完成", []
        monkeypatch.setattr(ap, "_agent_loop", fake_agent_loop)
        
        # 让 read_text 抛异常
        original_read = Path.read_text
        def boom_read(self, *args, **kwargs):
            if self.name == "bad.py":
                raise PermissionError("denied")
            return original_read(self, *args, **kwargs)
        monkeypatch.setattr(Path, "read_text", boom_read)
        (tmp_path / "bad.py").write_text("x", encoding="utf-8")

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="key")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="review", output={"files_need_fix": ["bad.py"]}))

        step = await pipeline._step_fixloop(run)
        assert step.status == StepStatus.OK
        assert step.output["files_fixed"] == 0


# ══════════════════════════════════════════════════════════
# 9. _step_accept 测试
# ══════════════════════════════════════════════════════════

class TestStepAccept:
    @pytest.fixture(autouse=True)
    def _mock_registry(self, monkeypatch):
        _mock_registry_resolve(monkeypatch)

    async def test_no_files_failed(self, tmp_path):
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="execute", output={"files_created": []}))
        run.steps.append(StepResult(name="execute", output={"files_created": []}))

        step = await pipeline._step_accept(run)
        assert step.status == StepStatus.FAILED
        assert "无生成文件" in step.error

    async def test_accept_success(self, tmp_path):
        """文件存在且语法正确 → 验收通过"""
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="decompose", output={}))
        run.steps.append(StepResult(name="execute", output={"files_created": ["app.py"]}))

        step = await pipeline._step_accept(run)
        assert step.status == StepStatus.OK
        assert step.output["report"]["passed"] is True

    async def test_accept_file_missing(self, tmp_path):
        """文件缺失 → 验收失败"""
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="decompose", output={}))
        run.steps.append(StepResult(name="execute", output={"files_created": ["ghost.py"]}))

        step = await pipeline._step_accept(run)
        assert step.status == StepStatus.FAILED
        assert "文件缺失" in step.output["reason"]

    async def test_accept_syntax_error(self, tmp_path):
        """语法错误 → 验收失败"""
        (tmp_path / "bad.py").write_text("def (: pass\n", encoding="utf-8")
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="decompose", output={}))
        run.steps.append(StepResult(name="execute", output={"files_created": ["bad.py"]}))

        step = await pipeline._step_accept(run)
        assert step.status == StepStatus.FAILED
        assert "语法错误" in step.output["reason"]

    async def test_accept_with_llm_verification(self, tmp_path, monkeypatch):
        """有 API key → LLM 验收"""
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        # Mock ChatBridge 返回 JSON 验收结果
        bridge = FakeChatBridge(responses=['{"passed": true, "issues": [], "score": 95}'])
        monkeypatch.setattr(ap.registry, "resolve", lambda *args, **kwargs: bridge)
        

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="key")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="decompose", output={}))
        run.steps.append(StepResult(name="execute", output={"files_created": ["app.py"]}))

        step = await pipeline._step_accept(run)
        assert step.status == StepStatus.OK

    async def test_accept_llm_says_failed(self, tmp_path, monkeypatch):
        """LLM 验收不通过"""
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        bridge = FakeChatBridge(responses=['{"passed": false, "issues": ["缺少测试"], "score": 50}'])
        monkeypatch.setattr(ap.registry, "resolve", lambda *args, **kwargs: bridge)
        

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="key")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="decompose", output={}))
        run.steps.append(StepResult(name="execute", output={"files_created": ["app.py"]}))

        step = await pipeline._step_accept(run)
        assert step.status == StepStatus.FAILED
        assert "缺少测试" in step.output["reason"]

    async def test_accept_llm_invalid_json(self, tmp_path, monkeypatch):
        """LLM 返回非 JSON → 不影响验收"""
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        bridge = FakeChatBridge(responses=["这不是 JSON"])
        monkeypatch.setattr(ap.registry, "resolve", lambda *args, **kwargs: bridge)
        

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="key")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="decompose", output={}))
        run.steps.append(StepResult(name="execute", output={"files_created": ["app.py"]}))

        step = await pipeline._step_accept(run)
        # JSON 解析失败但文件存在且语法正确 → 验收通过
        assert step.status == StepStatus.OK

    async def test_accept_llm_markdown_json(self, tmp_path, monkeypatch):
        """LLM 返回 markdown 包裹的 JSON"""
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        bridge = FakeChatBridge(responses=[
            '```json\n{"passed": false, "issues": ["md issue"], "score": 40}\n```',
        ])
        monkeypatch.setattr(ap.registry, "resolve", lambda *args, **kwargs: bridge)
        

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="key")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="decompose", output={}))
        run.steps.append(StepResult(name="execute", output={"files_created": ["app.py"]}))

        step = await pipeline._step_accept(run)
        assert step.status == StepStatus.FAILED
        assert "md issue" in step.output["reason"]


# ══════════════════════════════════════════════════════════
# 10. _step_deliver 测试
# ══════════════════════════════════════════════════════════

class TestStepDeliver:
    async def test_deliver_success(self, tmp_path, monkeypatch):
        """打包交付成功"""
        (tmp_path / "app.py").write_text("x = 1", encoding="utf-8")
        # Mock shutil.which 返回 None（跳过 zip/tar）
        monkeypatch.setattr(shutil, "which", lambda cmd: None)

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", project_name="myproj", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="execute", output={"files_created": ["app.py"]}))

        step = await pipeline._step_deliver(run)
        assert step.status == StepStatus.OK
        assert step.output["package"]["files_count"] == 1
        assert step.output["package"]["project_name"] == "myproj"
        assert (tmp_path / "DELIVERY.md").exists()

    async def test_deliver_with_zip(self, tmp_path, monkeypatch):
        """有 zip 工具 → 创建 zip"""
        (tmp_path / "app.py").write_text("x = 1", encoding="utf-8")
        monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/zip" if cmd == "zip" else None)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", project_name="proj", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="execute", output={"files_created": ["app.py"]}))

        step = await pipeline._step_deliver(run)
        assert step.status == StepStatus.OK
        assert "zip_path" in step.output["package"]

    async def test_deliver_with_tar(self, tmp_path, monkeypatch):
        """无 zip 但有 tar → 创建 tar.gz"""
        (tmp_path / "app.py").write_text("x = 1", encoding="utf-8")
        monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/tar" if cmd == "tar" else None)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", project_name="proj", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="execute", output={"files_created": ["app.py"]}))

        step = await pipeline._step_deliver(run)
        assert step.status == StepStatus.OK

    async def test_deliver_subprocess_exception(self, tmp_path, monkeypatch):
        """打包 subprocess 异常 → 不影响交付"""
        (tmp_path / "app.py").write_text("x = 1", encoding="utf-8")
        monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/zip")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
            subprocess.SubprocessError("zip fail")))

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", project_name="proj", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="execute", output={"files_created": ["app.py"]}))

        step = await pipeline._step_deliver(run)
        assert step.status == StepStatus.OK
        assert "未生成" in step.output["package"]["zip_path"]

    async def test_deliver_with_readme_generation(self, tmp_path, monkeypatch):
        """有 API key 且无 README → 生成 README"""
        (tmp_path / "app.py").write_text("x = 1", encoding="utf-8")
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        # Mock _generate_readme — 注意：monkeypatch 到类上的方法会变成 unbound
        # 调用时 self 会作为第一个参数传入，因此需要接受 self
        async def fake_readme(self_, run, files):
            (tmp_path / "README.md").write_text("# Generated README", encoding="utf-8")
        monkeypatch.setattr(AutonomousPipeline, "_generate_readme", fake_readme)

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="key")
        run = PipelineRun(request="test", project_name="proj", work_dir=str(tmp_path))
        run.steps.append(StepResult(name="execute", output={"files_created": ["app.py"]}))

        step = await pipeline._step_deliver(run)
        assert step.status == StepStatus.OK
        assert (tmp_path / "README.md").exists()


# ══════════════════════════════════════════════════════════
# 11. _generate_readme / _build_delivery_md / _build_report 测试
# ══════════════════════════════════════════════════════════

class TestGenerateReadme:
    @pytest.fixture(autouse=True)
    def _mock_registry(self, monkeypatch):
        _mock_registry_resolve(monkeypatch)

    async def test_generate_readme(self, tmp_path, monkeypatch):
        bridge = FakeChatBridge(responses=["# README content\n\n## Usage"])
        monkeypatch.setattr(ap.registry, "resolve", lambda *args, **kwargs: bridge)
        

        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="key")
        run = PipelineRun(request="test project", project_name="proj", work_dir=str(tmp_path))
        await pipeline._generate_readme(run, ["app.py"])

        readme = tmp_path / "README.md"
        assert readme.exists()
        assert "README content" in readme.read_text(encoding="utf-8")
        assert bridge.closed is True


class TestBuildDeliveryMd:
    def test_build_delivery_md(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1", encoding="utf-8")
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test request", project_name="proj", work_dir=str(tmp_path))
        run.steps = [
            StepResult(name="decompose", status=StepStatus.OK, started_at=1.0, completed_at=2.0),
            StepResult(name="execute", status=StepStatus.OK, started_at=2.0, completed_at=3.0,
                       output={"files_created": ["app.py"]}),
            StepResult(name="review", status=StepStatus.OK, output={
                "report": {"average_score": 85}, "files_need_fix": [],
            }),
            StepResult(name="testgen", status=StepStatus.OK, output={
                "result": {"total_passed": 5, "total_tests": 5},
            }),
            StepResult(name="accept", status=StepStatus.OK),
        ]

        md = pipeline._build_delivery_md(run, ["app.py"])
        assert "proj" in md
        assert "app.py" in md
        assert "85" in md
        assert "5/5" in md

    def test_build_delivery_md_with_failed_step(self, tmp_path):
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", project_name="proj")
        run.steps = [
            StepResult(name="decompose", status=StepStatus.FAILED, error="some error",
                       started_at=1.0, completed_at=1.5),
        ]
        md = pipeline._build_delivery_md(run, [])
        assert "decompose" in md
        assert "some error" in md

    def test_build_delivery_md_skipped_review(self, tmp_path):
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", project_name="proj")
        run.steps = [
            StepResult(name="review", status=StepStatus.SKIPPED),
            StepResult(name="testgen", status=StepStatus.SKIPPED),
            StepResult(name="accept", status=StepStatus.OK),
        ]
        md = pipeline._build_delivery_md(run, [])
        # 跳过的步骤不输出报告
        assert "decompose" not in md or "review" in md


class TestBuildReport:
    def test_build_report(self, tmp_path):
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test request", project_name="proj")
        run.created_at = 100.0
        run.completed_at = 105.5
        run.status = PipelineStatus.DONE
        run.steps = [
            StepResult(name="execute", output={"files_created": ["a.py", "b.py"]}),
            StepResult(name="testgen", output={}),
        ]

        report = pipeline._build_report(run)
        assert report["project_name"] == "proj"
        assert report["steps_count"] == 2
        assert report["total_files"] == 2
        assert report["duration_seconds"] == 5.5
        assert report["status"] == "done"

    def test_build_report_no_completed_at(self, tmp_path):
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test")
        report = pipeline._build_report(run)
        assert report["duration_seconds"] == 0


# ══════════════════════════════════════════════════════════
# 12. 管理方法测试
# ══════════════════════════════════════════════════════════

class TestManagementMethods:
    def test_list_runs(self, tmp_path):
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run1 = PipelineRun(request="r1", work_dir=str(tmp_path))
        run1.created_at = 100.0
        run2 = PipelineRun(request="r2", work_dir=str(tmp_path))
        run2.created_at = 200.0
        pipeline._runs[run1.id] = run1
        pipeline._runs[run2.id] = run2

        runs = pipeline.list_runs()
        assert len(runs) == 2
        # 按 created_at 倒序
        assert runs[0]["request"] == "r2"
        assert runs[1]["request"] == "r1"

    def test_list_runs_limit(self, tmp_path):
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        for i in range(5):
            r = PipelineRun(request=f"r{i}", work_dir=str(tmp_path))
            r.created_at = float(i)
            pipeline._runs[r.id] = r
        runs = pipeline.list_runs(limit=2)
        assert len(runs) == 2

    def test_get_run(self, tmp_path):
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        pipeline._runs[run.id] = run

        result = pipeline.get_run(run.id)
        assert result is not None
        assert result["id"] == run.id

    def test_get_run_not_found(self, tmp_path):
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        assert pipeline.get_run("nonexistent") is None

    def test_cancel_run(self, tmp_path):
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.status = PipelineStatus.EXECUTING
        pipeline._runs[run.id] = run

        assert pipeline.cancel_run(run.id) is True
        assert run._cancel_flag is True

    def test_cancel_run_already_done(self, tmp_path):
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        run = PipelineRun(request="test", work_dir=str(tmp_path))
        run.status = PipelineStatus.DONE
        pipeline._runs[run.id] = run

        assert pipeline.cancel_run(run.id) is False
        assert run._cancel_flag is False

    def test_cancel_run_nonexistent(self, tmp_path):
        pipeline = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        assert pipeline.cancel_run("nope") is False


# ══════════════════════════════════════════════════════════
# 13. 完整 run() 流程测试
# ══════════════════════════════════════════════════════════

class TestFullRun:
    """完整流水线 run() 流程"""

    @pytest.fixture(autouse=True)
    def _setup_mocks(self, tmp_path, monkeypatch):
        """注入所有外部依赖的 mock"""
        self.tmp_path = tmp_path
        self.monkeypatch = monkeypatch

        # 1. Mock registry.resolve — 返回模拟 LLM
        _mock_registry_resolve(monkeypatch)

        # 2. Mock _agent_loop — 直接返回成功
        async def fake_agent_loop(bridge, task, sys_prompt, workspace, max_iterations=12):
            # 写一个文件到工作区以便后续步骤能找到
            (workspace / "app.py").write_text("x = 1\n", encoding="utf-8")
            return "完成", ["app.py"]
        monkeypatch.setattr(ap, "_agent_loop", fake_agent_loop)

        # 3. Mock QualityGuard
        from pycoder.server.services import quality_guard as qg_mod
        fake_guard = MagicMock()
        fake_guard.check = AsyncMock(return_value=SimpleNamespace(
            score=85, is_pass=lambda min_score=70: True))
        monkeypatch.setattr(qg_mod, "QualityGuard", MagicMock(return_value=fake_guard))

        # 4. Mock TestGenerator
        from pycoder.server.services import test_generator as tg_mod
        fake_gen = MagicMock()
        fake_gen.generate.return_value = SimpleNamespace(
            success=True, test_count=3, passed=3, failed=0, coverage_percent=90)
        monkeypatch.setattr(tg_mod, "TestGenerator", MagicMock(return_value=fake_gen))

        # 5. Mock shutil.which — 无打包工具
        monkeypatch.setattr(shutil, "which", lambda cmd: None)

    async def test_full_pipeline_success(self):
        """完整流水线成功执行"""
        pipeline = AutonomousPipeline(workspace_root=self.tmp_path, api_key="")
        events = []
        async for event in pipeline.run("做一个用户管理系统"):
            events.append(event)

        # 验证事件序列
        event_types = [e["type"] for e in events]
        assert "pipeline_start" in event_types
        assert "phase" in event_types
        assert "done" in event_types

        # 最终事件是 done
        done_event = next(e for e in events if e["type"] == "done")
        assert done_event["report"]["status"] == "done"
        assert done_event["progress"] == 100

    async def test_full_pipeline_with_run_id_resume(self):
        """用 run_id 恢复已有 run"""
        pipeline = AutonomousPipeline(workspace_root=self.tmp_path, api_key="")
        # 先创建一个 run
        run = PipelineRun(request="test", work_dir=str(self.tmp_path))
        pipeline._runs[run.id] = run

        events = []
        async for event in pipeline.run("test", run_id=run.id):
            events.append(event)

        # 应该用已有的 run
        assert any(e["type"] == "pipeline_start" for e in events)

    async def test_pipeline_decompose_failure(self, monkeypatch):
        """Step 1 失败 → 流水线终止"""
        import builtins
        orig_import = builtins.__import__
        def fake_import(name, *args, **kwargs):
            if "task_decomposer" in name:
                raise ImportError("no module")
            return orig_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", fake_import)

        pipeline = AutonomousPipeline(workspace_root=self.tmp_path, api_key="")
        events = []
        async for event in pipeline.run("test"):
            events.append(event)

        # 应有 error 事件
        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) >= 1
        assert "no module" in error_events[0]["message"]

    async def test_pipeline_acceptance_retry(self, monkeypatch):
        """验收不通过 → 自动修复循环"""
        # Mock _step_accept 第一次失败，第二次通过
        call_count = {"accept": 0}
        original_accept = AutonomousPipeline._step_accept
        async def fake_accept(self, run):
            call_count["accept"] += 1
            if call_count["accept"] == 1:
                step = StepResult(name="accept", status=StepStatus.FAILED,
                                  started_at=time.time(), completed_at=time.time())
                step.output = {"report": {"passed": False}, "reason": "验收不通过",
                               "suggestions": "需要修复"}
                return step
            step = StepResult(name="accept", status=StepStatus.OK,
                              started_at=time.time(), completed_at=time.time())
            step.output = {"report": {"passed": True}, "reason": "验收通过", "suggestions": ""}
            return step
        monkeypatch.setattr(AutonomousPipeline, "_step_accept", fake_accept)

        # Mock _step_fixloop 避免真实修复
        async def fake_fixloop(self, run, extra_context=""):
            return StepResult(name="fix", status=StepStatus.OK,
                              started_at=time.time(), completed_at=time.time(),
                              output={"rounds": 1, "files_fixed": 1})
        monkeypatch.setattr(AutonomousPipeline, "_step_fixloop", fake_fixloop)

        pipeline = AutonomousPipeline(workspace_root=self.tmp_path, api_key="")
        events = []
        async for event in pipeline.run("做一个博客系统"):
            events.append(event)

        # 应有 fix_round 事件
        fix_events = [e for e in events if e["type"] == "fix_round"]
        assert len(fix_events) >= 1
        # 最终 done
        assert any(e["type"] == "done" for e in events)

    async def test_pipeline_exception_handling(self, monkeypatch):
        """流水线异常 → error 事件"""
        async def boom_decompose(self, run):
            raise RuntimeError("unexpected crash")
        monkeypatch.setattr(AutonomousPipeline, "_step_decompose", boom_decompose)

        pipeline = AutonomousPipeline(workspace_root=self.tmp_path, api_key="")
        events = []
        async for event in pipeline.run("test"):
            events.append(event)

        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) >= 1
        assert "unexpected crash" in error_events[0]["message"]


# ══════════════════════════════════════════════════════════
# 14. get_pipeline 单例测试
# ══════════════════════════════════════════════════════════

class TestGetPipeline:
    def test_singleton(self, monkeypatch):
        monkeypatch.setattr(ap, "_pipeline", None)
        p1 = get_pipeline()
        p2 = get_pipeline()
        assert p1 is p2

    def test_singleton_already_set(self, monkeypatch):
        existing = MagicMock()
        monkeypatch.setattr(ap, "_pipeline", existing)
        assert get_pipeline() is existing


# ══════════════════════════════════════════════════════════
# 15. 常量与配置测试
# ══════════════════════════════════════════════════════════

class TestConstants:
    def test_max_iterations(self):
        assert MAX_AGENT_ITERATIONS == 20

    def test_max_fix_rounds(self):
        assert MAX_FIX_ROUNDS == 3

    def test_allowed_commands(self):
        assert "python" in ALLOWED_COMMANDS
        assert "git" in ALLOWED_COMMANDS
        assert "pytest" in ALLOWED_COMMANDS
        assert "docker" in ALLOWED_COMMANDS
        assert "pip" in ALLOWED_COMMANDS


# ══════════════════════════════════════════════════════════
# 16. AutonomousPipeline.__init__ 测试
# ══════════════════════════════════════════════════════════

class TestPipelineInit:
    def test_with_workspace_root(self, tmp_path):
        p = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        assert p.workspace == tmp_path.resolve()
        assert p._model == "deepseek-chat"

    def test_with_custom_model(self, tmp_path):
        p = AutonomousPipeline(workspace_root=tmp_path, model="gpt-4")
        assert p._model == "gpt-4"

    def test_with_api_key(self, tmp_path):
        p = AutonomousPipeline(workspace_root=tmp_path, api_key="my-key")
        assert p._api_key == "my-key"

    def test_api_key_from_model(self, tmp_path, monkeypatch):
        """无 api_key → 从 _get_api_key_for_model 获取"""
        monkeypatch.setattr(ap, "_get_api_key_for_model", lambda m: "derived-key")
        p = AutonomousPipeline(workspace_root=tmp_path, api_key=None)
        assert p._api_key == "derived-key"

    def test_default_workspace(self, monkeypatch, tmp_path):
        """无 workspace_root → 使用 _get_workspace()"""
        from pycoder.server.routers import files as files_mod
        monkeypatch.setattr(files_mod, "get_workspace_root", lambda: tmp_path)
        p = AutonomousPipeline()
        assert p.workspace == tmp_path.resolve()

    def test_workspace_property(self, tmp_path):
        p = AutonomousPipeline(workspace_root=tmp_path, api_key="")
        assert p.workspace == tmp_path.resolve()
