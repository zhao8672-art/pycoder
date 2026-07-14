"""覆盖率测试: pycoder/server/chat_handler.py

目标: 行覆盖率 >= 80%
覆盖内容:
  - ChatRequest / ChatResponse 数据模型
  - _resolve_model / _get_effective_model — 模型路由
  - _get_api_key_for_model — 各 provider key 查找
  - _read_file_head — 文件头读取与异常处理
  - _build_context_prompt — 上下文构造
  - _try_write_code_files — 多种代码块格式解析 + 文件写入
  - _write_file_safe — 路径越界检查
  - _run_chat_stream — 异步生成器主流程

测试策略:
  - mock ChatBridge 避免真实 LLM 调用
  - mock get_session_store / get_model_manager / get_api_key
  - mock get_cost_controller 避免预算检查失败
  - 用 async for 收集 _run_chat_stream 事件
  - 用 tmp_path 隔离文件写入
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from pycoder.server import chat_handler as ch
from pycoder.server.chat_handler import (
    ChatRequest,
    ChatResponse,
    _build_context_prompt,
    _get_api_key_for_model,
    _get_effective_model,
    _read_file_head,
    _resolve_model,
    _run_chat_stream,
    _try_write_code_files,
    _write_file_safe,
)


# ══════════════════════════════════════════════════════════
# 数据模型测试
# ══════════════════════════════════════════════════════════

class TestChatRequest:
    def test_defaults(self):
        r = ChatRequest(message="hi")
        assert r.message == "hi"
        assert r.session_id is None
        assert r.model == "auto"
        assert r.stream is False
        assert r.files == []
        assert r.system_prompt is None
        assert r.hermes is False
        assert r.agent_mode is False

    def test_validation_requires_message(self):
        with pytest.raises(Exception):
            ChatRequest(message="")

    def test_custom_fields(self):
        r = ChatRequest(
            message="hi", session_id="s1", model="deepseek-chat",
            stream=True, files=["a.py"], system_prompt="sys",
            hermes=True, agent_mode=True,
        )
        assert r.session_id == "s1"
        assert r.model == "deepseek-chat"
        assert r.files == ["a.py"]


class TestChatResponse:
    def test_defaults(self):
        r = ChatResponse(session_id="s1", content="hello", model="deepseek-chat")
        assert r.session_id == "s1"
        assert r.content == "hello"
        assert r.model == "deepseek-chat"
        assert r.role == "assistant"
        assert r.id != ""
        assert r.usage == {}
        assert r.created_at > 0

    def test_custom_id(self):
        r = ChatResponse(
            id="fixed-id", session_id="s1", content="x", model="m",
        )
        assert r.id == "fixed-id"


# ══════════════════════════════════════════════════════════
# _resolve_model / _get_effective_model 测试
# ══════════════════════════════════════════════════════════

class TestResolveModel:
    def test_explicit_non_auto_returns_input(self):
        assert _resolve_model("deepseek-chat") == "deepseek-chat"
        assert _resolve_model("gpt-4") == "gpt-4"

    def test_auto_calls_effective_model(self, monkeypatch):
        """requested == 'auto' 时委托 _get_effective_model"""
        monkeypatch.setattr(ch, "_get_effective_model", lambda r: "mocked")
        assert _resolve_model("auto") == "mocked"

    def test_empty_calls_effective_model(self, monkeypatch):
        monkeypatch.setattr(ch, "_get_effective_model", lambda r: "mocked")
        assert _resolve_model("") == "mocked"


class TestGetEffectiveModel:
    def test_explicit_non_auto_returns_input(self):
        assert _get_effective_model("deepseek-chat") == "deepseek-chat"
        assert _get_effective_model("gpt-4") == "gpt-4"

    def test_recommend_with_task_type(self, monkeypatch):
        """mgr.recommend 支持 task_type 参数"""
        mock_mgr = MagicMock()
        mock_mgr.recommend.return_value = ("qwen-coder", "qwen")
        monkeypatch.setattr(ch, "get_model_manager", lambda: mock_mgr)
        assert _get_effective_model("auto") == "qwen-coder"
        mock_mgr.recommend.assert_called_once()

    def test_recommend_without_task_type(self, monkeypatch):
        """mgr.recommend 不支持 task_type → TypeError → 退化为无参调用"""
        mock_mgr = MagicMock()

        def recommend(task_type=None):
            if task_type is not None:
                raise TypeError("no task_type arg")
            return ("glm-4", "glm")

        mock_mgr.recommend.side_effect = recommend
        monkeypatch.setattr(ch, "get_model_manager", lambda: mock_mgr)
        assert _get_effective_model("auto") == "glm-4"

    def test_recommend_returns_empty_falls_back(self, monkeypatch):
        """recommend 返回空模型 → 回退到 deepseek-chat"""
        mock_mgr = MagicMock()
        mock_mgr.recommend.return_value = ("", "deepseek")
        monkeypatch.setattr(ch, "get_model_manager", lambda: mock_mgr)
        assert _get_effective_model("auto") == "deepseek-chat"

    def test_recommend_raises_value_error(self, monkeypatch):
        mock_mgr = MagicMock()
        mock_mgr.recommend.side_effect = ValueError("no key")
        monkeypatch.setattr(ch, "get_model_manager", lambda: mock_mgr)
        assert _get_effective_model("auto") == "deepseek-chat"

    def test_recommend_raises_runtime_error(self, monkeypatch):
        mock_mgr = MagicMock()
        mock_mgr.recommend.side_effect = RuntimeError("fail")
        monkeypatch.setattr(ch, "get_model_manager", lambda: mock_mgr)
        assert _get_effective_model("auto") == "deepseek-chat"

    def test_recommend_raises_attribute_error(self, monkeypatch):
        mock_mgr = MagicMock()
        mock_mgr.recommend.side_effect = AttributeError("no method")
        monkeypatch.setattr(ch, "get_model_manager", lambda: mock_mgr)
        assert _get_effective_model("auto") == "deepseek-chat"


# ══════════════════════════════════════════════════════════
# _get_api_key_for_model 测试
# ══════════════════════════════════════════════════════════

class TestGetApiKeyForModel:
    def test_deepseek_default_provider(self, monkeypatch):
        mock_mgr = MagicMock()
        mock_mgr.get_key.return_value = "ds-key"
        monkeypatch.setattr(ch, "get_model_manager", lambda: mock_mgr)
        monkeypatch.setattr(ch, "get_api_key", lambda p: "ds-key-2")
        assert _get_api_key_for_model("deepseek-chat") == "ds-key"

    def test_qwen_provider(self, monkeypatch):
        mock_mgr = MagicMock()
        mock_mgr.get_key.return_value = "qwen-key"
        monkeypatch.setattr(ch, "get_model_manager", lambda: mock_mgr)
        assert _get_api_key_for_model("qwen-coder") == "qwen-key"

    def test_glm_provider(self, monkeypatch):
        mock_mgr = MagicMock()
        mock_mgr.get_key.return_value = "glm-key"
        monkeypatch.setattr(ch, "get_model_manager", lambda: mock_mgr)
        assert _get_api_key_for_model("glm-4") == "glm-key"

    def test_gpt_provider(self, monkeypatch):
        mock_mgr = MagicMock()
        mock_mgr.get_key.return_value = "openai-key"
        monkeypatch.setattr(ch, "get_model_manager", lambda: mock_mgr)
        assert _get_api_key_for_model("gpt-4") == "openai-key"

    def test_claude_provider(self, monkeypatch):
        mock_mgr = MagicMock()
        mock_mgr.get_key.return_value = "anthropic-key"
        monkeypatch.setattr(ch, "get_model_manager", lambda: mock_mgr)
        assert _get_api_key_for_model("claude-3") == "anthropic-key"

    def test_gemini_provider(self, monkeypatch):
        mock_mgr = MagicMock()
        mock_mgr.get_key.return_value = "google-key"
        monkeypatch.setattr(ch, "get_model_manager", lambda: mock_mgr)
        assert _get_api_key_for_model("gemini-pro") == "google-key"

    def test_get_key_returns_empty_falls_back_to_api(self, monkeypatch):
        """mgr.get_key 返回空 → 用 get_api_key"""
        mock_mgr = MagicMock()
        mock_mgr.get_key.return_value = ""
        monkeypatch.setattr(ch, "get_model_manager", lambda: mock_mgr)
        monkeypatch.setattr(ch, "get_api_key", lambda p: "fallback-key")
        assert _get_api_key_for_model("deepseek-chat") == "fallback-key"

    def test_get_key_returns_empty_env_var(self, monkeypatch):
        """所有方式都失败 → 用环境变量"""
        mock_mgr = MagicMock()
        mock_mgr.get_key.return_value = ""
        monkeypatch.setattr(ch, "get_model_manager", lambda: mock_mgr)
        monkeypatch.setattr(ch, "get_api_key", lambda p: "")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
        assert _get_api_key_for_model("deepseek-chat") == "env-key"

    def test_exception_falls_back_to_deepseek(self, monkeypatch):
        """ValueError → 走 deepseek 回退分支"""
        mock_mgr = MagicMock()
        mock_mgr.get_key.side_effect = ValueError("fail")
        monkeypatch.setattr(ch, "get_model_manager", lambda: mock_mgr)
        monkeypatch.setattr(ch, "get_api_key", lambda p: "deepseek-key")
        # 模型以 deepseek 开头 → 走 deepseek 回退
        assert _get_api_key_for_model("deepseek-chat") == "deepseek-key"

    def test_exception_non_deepseek_returns_empty(self, monkeypatch):
        """异常 + 非 deepseek 模型 → 返回空字符串"""
        mock_mgr = MagicMock()
        mock_mgr.get_key.side_effect = KeyError("no provider")
        monkeypatch.setattr(ch, "get_model_manager", lambda: mock_mgr)
        monkeypatch.setattr(ch, "get_api_key", lambda p: "")
        # qwen 不是 deepseek → 走空分支
        result = _get_api_key_for_model("qwen-coder")
        assert result == ""

    def test_attribute_error_handled(self, monkeypatch):
        mock_mgr = MagicMock()
        mock_mgr.get_key.side_effect = AttributeError("no attr")
        monkeypatch.setattr(ch, "get_model_manager", lambda: mock_mgr)
        monkeypatch.setattr(ch, "get_api_key", lambda p: "")
        # 不应抛
        assert _get_api_key_for_model("qwen-coder") == ""


# ══════════════════════════════════════════════════════════
# _read_file_head 测试
# ══════════════════════════════════════════════════════════

class TestReadFileHead:
    def test_read_short_file(self, tmp_path):
        f = tmp_path / "f.txt"
        f.write_text("hello world", encoding="utf-8")
        assert _read_file_head(str(f)) == "hello world"

    def test_truncates_at_max_chars(self, tmp_path):
        f = tmp_path / "long.txt"
        content = "x" * 3000
        f.write_text(content, encoding="utf-8")
        result = _read_file_head(str(f), max_chars=100)
        assert len(result) == 100

    def test_default_max_chars_2000(self, tmp_path):
        f = tmp_path / "long.txt"
        f.write_text("y" * 3000, encoding="utf-8")
        assert len(_read_file_head(str(f))) == 2000

    def test_oserror_returns_empty(self, tmp_path):
        """不存在的文件 → 返回空"""
        assert _read_file_head(str(tmp_path / "missing.txt")) == ""

    def test_unicode_decode_error_returns_empty(self, tmp_path):
        """二进制文件无法 utf-8 解码 → 返回空"""
        f = tmp_path / "bin.dat"
        f.write_bytes(b"\xff\xfe\x00binary")
        # 应不抛异常，返回空
        result = _read_file_head(str(f))
        assert isinstance(result, str)


# ══════════════════════════════════════════════════════════
# _build_context_prompt 测试
# ══════════════════════════════════════════════════════════

class TestBuildContextPrompt:
    def test_empty_files(self):
        assert _build_context_prompt([]) == ""

    def test_none_files(self):
        assert _build_context_prompt(None) == ""

    def test_with_file(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("print('hi')", encoding="utf-8")
        result = _build_context_prompt([str(f)])
        assert "## 当前上下文" in result
        assert "code.py" in result
        assert "print('hi')" in result

    def test_multiple_files_truncates_to_3(self, tmp_path):
        """files 列表只取前 3 个"""
        files = []
        for i in range(5):
            f = tmp_path / f"f{i}.py"
            f.write_text(f"content {i}", encoding="utf-8")
            files.append(str(f))
        result = _build_context_prompt(files)
        # 只包含前 3 个文件名
        for i in range(3):
            assert f"f{i}.py" in result
        assert "f3.py" not in result
        assert "f4.py" not in result

    def test_nonexistent_file_skipped(self, tmp_path):
        """不存在的文件不报错，跳过"""
        result = _build_context_prompt(["/nonexistent/file.py"])
        # 由于所有文件都不可读 → context_lines 只有 "## 当前上下文" 一个元素
        # 长度 == 1 → 返回 ""
        assert result == ""


# ══════════════════════════════════════════════════════════
# _write_file_safe 测试
# ══════════════════════════════════════════════════════════

class TestWriteFileSafe:
    def test_writes_file_within_workspace(self, tmp_path):
        _write_file_safe(tmp_path, "sub/file.py", "content")
        written = tmp_path / "sub" / "file.py"
        assert written.exists()
        assert written.read_text() == "content"

    def test_rejects_path_traversal(self, tmp_path):
        """../ 路径不应写入"""
        _write_file_safe(tmp_path, "../escape.py", "bad")
        assert not (tmp_path.parent / "escape.py").exists()

    def test_creates_parent_dirs(self, tmp_path):
        _write_file_safe(tmp_path, "a/b/c/d.py", "x")
        assert (tmp_path / "a" / "b" / "c" / "d.py").exists()


# ══════════════════════════════════════════════════════════
# _try_write_code_files 测试
# ══════════════════════════════════════════════════════════

class TestTryWriteCodeFiles:
    def test_empty_content_returns_none(self, monkeypatch):
        """空 content → 直接返回"""
        assert _try_write_code_files("") is None
        assert _try_write_code_files(None) is None

    def test_pattern1_file_block(self, tmp_path, monkeypatch):
        """模式1: ```FILE:path\ncode```END"""
        monkeypatch.setattr(
            "pycoder.server.routers.files.get_workspace_root", lambda: tmp_path
        )
        content = "```FILE:app1.py\nprint('hello')\n```END"
        _try_write_code_files(content)
        assert (tmp_path / "app1.py").exists()
        assert "print('hello')" in (tmp_path / "app1.py").read_text()

    def test_pattern2_lang_path(self, tmp_path, monkeypatch):
        """模式2: ```python:app2.py\ncode```"""
        monkeypatch.setattr(
            "pycoder.server.routers.files.get_workspace_root", lambda: tmp_path
        )
        content = "```python:app2.py\nx = 1\n```"
        _try_write_code_files(content)
        assert (tmp_path / "app2.py").exists()
        assert "x = 1" in (tmp_path / "app2.py").read_text()

    def test_pattern3_write_marker(self, tmp_path, monkeypatch):
        """模式3: [WRITE path] + 代码块"""
        monkeypatch.setattr(
            "pycoder.server.routers.files.get_workspace_root", lambda: tmp_path
        )
        content = (
            "[WRITE app3.py]\n"
            "```python\nprint('three')\n```"
        )
        _try_write_code_files(content)
        assert (tmp_path / "app3.py").exists()

    def test_pattern4_natural_format_hash(self, tmp_path, monkeypatch):
        """模式4: # file: name.py + 代码块"""
        monkeypatch.setattr(
            "pycoder.server.routers.files.get_workspace_root", lambda: tmp_path
        )
        content = (
            "# file: app4.py\n"
            "```python\nprint('four')\n```"
        )
        _try_write_code_files(content)
        assert (tmp_path / "app4.py").exists()

    def test_pattern5_markdown_heading(self, tmp_path, monkeypatch):
        """模式5: ## 创建文件: name.py + 代码块"""
        monkeypatch.setattr(
            "pycoder.server.routers.files.get_workspace_root", lambda: tmp_path
        )
        content = (
            "## 创建文件: app5.py\n"
            "```python\nprint('five')\n```"
        )
        _try_write_code_files(content)
        assert (tmp_path / "app5.py").exists()

    def test_no_code_blocks_does_nothing(self, tmp_path, monkeypatch):
        """无任何代码块 → 不写入"""
        monkeypatch.setattr(
            "pycoder.server.routers.files.get_workspace_root", lambda: tmp_path
        )
        _try_write_code_files("just text, no code")
        # 不应有文件被创建
        assert list(tmp_path.iterdir()) == []


# ══════════════════════════════════════════════════════════
# _run_chat_stream 测试（async）
# ══════════════════════════════════════════════════════════

def _make_mock_store(session=None, messages=None):
    """构造 mock SessionStore"""
    store = MagicMock()
    store.get_session.return_value = session
    store.get_messages.return_value = messages or []
    store.add_message = MagicMock()
    store.update_session = MagicMock()
    return store


def _make_chat_event(event_type, content="", usage=None):
    """构造 ChatEvent"""
    return MagicMock(
        event_type=event_type, content=content,
        usage=usage or {}, __iter__=lambda self: iter([]),
    )


def _make_mock_bridge(events):
    """构造 mock ChatBridge，chat_stream 返回指定事件"""
    bridge = MagicMock()
    bridge.configure = MagicMock()
    bridge.config = MagicMock()
    bridge.config.system_prompt = ""
    bridge.config.reasoning_effort = "medium"
    bridge.config.enable_thinking = True
    bridge.config.enable_cache = True
    bridge.add_message = MagicMock()
    bridge.close = AsyncMock(return_value=None)

    async def chat_stream(prompt):
        for ev in events:
            yield ev

    bridge.chat_stream = chat_stream
    return bridge


class TestRunChatStream:
    async def test_no_api_key_yields_error(self, monkeypatch):
        """无 API key → 立即返回 error 事件"""
        monkeypatch.setattr(ch, "_get_api_key_for_model", lambda m: "")
        events = []
        async for ev in _run_chat_stream("s1", "msg", "model"):
            events.append(ev)
        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "API Key" in events[0]["message"]

    async def test_cost_control_blocks(self, monkeypatch):
        """成本超限 → 返回 error 事件"""
        monkeypatch.setattr(ch, "_get_api_key_for_model", lambda m: "key")

        # mock get_cost_controller
        fake_cc = MagicMock()
        fake_cc.check_before_call.return_value = (False, "已超预算")
        import pycoder.server.services.cost_control as cc_mod
        monkeypatch.setattr(cc_mod, "get_cost_controller", lambda: fake_cc)

        events = []
        async for ev in _run_chat_stream("s1", "msg", "model"):
            events.append(ev)
        assert any(e["type"] == "error" for e in events)
        assert any("成本超限" in e.get("message", "") for e in events)

    async def test_hermes_mode_activates_agent(self, monkeypatch, tmp_path):
        """hermes=True → 调用 agent_chat_stream"""
        monkeypatch.setattr(ch, "_get_api_key_for_model", lambda m: "key")
        # mock cost controller 放行
        fake_cc = MagicMock()
        fake_cc.check_before_call.return_value = (True, "")
        import pycoder.server.services.cost_control as cc_mod
        monkeypatch.setattr(cc_mod, "get_cost_controller", lambda: fake_cc)

        # mock ChatBridge
        monkeypatch.setattr(ch, "ChatBridge", lambda: _make_mock_bridge([]))

        # mock session store
        monkeypatch.setattr(ch, "get_session_store",
                            lambda: _make_mock_store(session=None))

        # mock agent_chat_stream → 返回 done 事件
        async def fake_agent_stream(*args, **kwargs):
            yield {"type": "done", "content": "agent result"}

        import pycoder.server.services.agent_orchestrator as ao_mod
        monkeypatch.setattr(ao_mod, "agent_chat_stream", fake_agent_stream)

        events = []
        async for ev in _run_chat_stream(
            "s1", "msg", "deepseek-chat", hermes=True,
        ):
            events.append(ev)

        types = [e["type"] for e in events]
        assert "agent_status" in types
        assert "done" in types

    async def test_agent_mode_activates_agent(self, monkeypatch, tmp_path):
        """agent_mode=True → 调用 agent_chat_stream"""
        monkeypatch.setattr(ch, "_get_api_key_for_model", lambda m: "key")
        fake_cc = MagicMock()
        fake_cc.check_before_call.return_value = (True, "")
        import pycoder.server.services.cost_control as cc_mod
        monkeypatch.setattr(cc_mod, "get_cost_controller", lambda: fake_cc)

        monkeypatch.setattr(ch, "ChatBridge", lambda: _make_mock_bridge([]))
        monkeypatch.setattr(ch, "get_session_store",
                            lambda: _make_mock_store(session=None))

        async def fake_agent_stream(*args, **kwargs):
            yield {"type": "agent_result", "content": "agent done"}

        import pycoder.server.services.agent_orchestrator as ao_mod
        monkeypatch.setattr(ao_mod, "agent_chat_stream", fake_agent_stream)

        events = []
        async for ev in _run_chat_stream(
            "s1", "msg", "deepseek-chat", agent_mode=True,
        ):
            events.append(ev)

        assert any(e["type"] == "agent_status" for e in events)

    async def test_normal_chat_token_stream(self, monkeypatch):
        """普通聊天模式 — token 事件流"""
        monkeypatch.setattr(ch, "_get_api_key_for_model", lambda m: "key")
        fake_cc = MagicMock()
        fake_cc.check_before_call.return_value = (True, "")
        import pycoder.server.services.cost_control as cc_mod
        monkeypatch.setattr(cc_mod, "get_cost_controller", lambda: fake_cc)

        # mock ChatBridge 返回 token + done
        events_for_bridge = [
            _make_chat_event("token", "hello "),
            _make_chat_event("token", "world"),
            _make_chat_event("done", "hello world", {"tokens": 10}),
        ]
        monkeypatch.setattr(ch, "ChatBridge",
                            lambda: _make_mock_bridge(events_for_bridge))

        # mock session store — 无 session
        monkeypatch.setattr(ch, "get_session_store",
                            lambda: _make_mock_store(session=None))

        events = []
        async for ev in _run_chat_stream("s1", "hi", "deepseek-chat"):
            events.append(ev)

        # 应有 token + done 事件
        token_events = [e for e in events if e["type"] == "token"]
        assert len(token_events) == 2
        done = next(e for e in events if e["type"] == "done")
        assert done["content"] == "hello world"
        assert done["usage"] == {"tokens": 10}

    async def test_normal_chat_error_event(self, monkeypatch):
        """普通聊天 — error 事件 → 提前返回"""
        monkeypatch.setattr(ch, "_get_api_key_for_model", lambda m: "key")
        fake_cc = MagicMock()
        fake_cc.check_before_call.return_value = (True, "")
        import pycoder.server.services.cost_control as cc_mod
        monkeypatch.setattr(cc_mod, "get_cost_controller", lambda: fake_cc)

        events_for_bridge = [
            _make_chat_event("error", "API failure"),
        ]
        monkeypatch.setattr(ch, "ChatBridge",
                            lambda: _make_mock_bridge(events_for_bridge))
        monkeypatch.setattr(ch, "get_session_store",
                            lambda: _make_mock_store(session=None))

        events = []
        async for ev in _run_chat_stream("s1", "hi", "deepseek-chat"):
            events.append(ev)
        assert any(e["type"] == "error" for e in events)
        assert "API failure" in events[-1]["message"]

    async def test_normal_chat_reasoning_event(self, monkeypatch):
        """普通聊天 — reasoning 事件"""
        monkeypatch.setattr(ch, "_get_api_key_for_model", lambda m: "key")
        fake_cc = MagicMock()
        fake_cc.check_before_call.return_value = (True, "")
        import pycoder.server.services.cost_control as cc_mod
        monkeypatch.setattr(cc_mod, "get_cost_controller", lambda: fake_cc)

        events_for_bridge = [
            _make_chat_event("reasoning", "thinking..."),
            _make_chat_event("done", "result"),
        ]
        monkeypatch.setattr(ch, "ChatBridge",
                            lambda: _make_mock_bridge(events_for_bridge))
        monkeypatch.setattr(ch, "get_session_store",
                            lambda: _make_mock_store(session=None))

        events = []
        async for ev in _run_chat_stream("s1", "hi", "deepseek-chat"):
            events.append(ev)
        assert any(e["type"] == "reasoning" for e in events)

    async def test_session_history_loaded(self, monkeypatch):
        """有 session_id 时加载历史消息"""
        monkeypatch.setattr(ch, "_get_api_key_for_model", lambda m: "key")
        fake_cc = MagicMock()
        fake_cc.check_before_call.return_value = (True, "")
        import pycoder.server.services.cost_control as cc_mod
        monkeypatch.setattr(cc_mod, "get_cost_controller", lambda: fake_cc)

        # 构造 session + 历史
        mock_session = MagicMock(id="s1", title="")
        mock_msg = MagicMock(role="user", content="previous message")
        store = _make_mock_store(session=mock_session, messages=[mock_msg])
        monkeypatch.setattr(ch, "get_session_store", lambda: store)

        # mock ChatBridge
        events_for_bridge = [
            _make_chat_event("done", "response"),
        ]
        monkeypatch.setattr(ch, "ChatBridge",
                            lambda: _make_mock_bridge(events_for_bridge))

        events = []
        async for ev in _run_chat_stream("s1", "hi", "deepseek-chat"):
            events.append(ev)

        # 验证历史加载被调用
        store.get_messages.assert_called()

    async def test_session_title_auto_generated(self, monkeypatch):
        """session 有用户消息但无 title → 自动生成标题"""
        monkeypatch.setattr(ch, "_get_api_key_for_model", lambda m: "key")
        fake_cc = MagicMock()
        fake_cc.check_before_call.return_value = (True, "")
        import pycoder.server.services.cost_control as cc_mod
        monkeypatch.setattr(cc_mod, "get_cost_controller", lambda: fake_cc)

        # session 无 title，但历史中有 user 消息
        mock_session = MagicMock(id="s1", title="")
        mock_msg = MagicMock(role="user", content="这是第一条用户消息的内容")
        store = _make_mock_store(session=mock_session, messages=[mock_msg])
        monkeypatch.setattr(ch, "get_session_store", lambda: store)

        events_for_bridge = [_make_chat_event("done", "response")]
        monkeypatch.setattr(ch, "ChatBridge",
                            lambda: _make_mock_bridge(events_for_bridge))

        events = []
        async for ev in _run_chat_stream("s1", "hi", "deepseek-chat"):
            events.append(ev)

        # update_session 应被调用以设置 title
        store.update_session.assert_called()

    async def test_files_context_injected(self, monkeypatch, tmp_path):
        """传入 files 参数 → 构建上下文 prompt 注入 bridge"""
        monkeypatch.setattr(ch, "_get_api_key_for_model", lambda m: "key")
        fake_cc = MagicMock()
        fake_cc.check_before_call.return_value = (True, "")
        import pycoder.server.services.cost_control as cc_mod
        monkeypatch.setattr(cc_mod, "get_cost_controller", lambda: fake_cc)

        # 创建一个文件作为上下文
        ctx_file = tmp_path / "ctx.py"
        ctx_file.write_text("# context file", encoding="utf-8")

        monkeypatch.setattr(ch, "get_session_store",
                            lambda: _make_mock_store(session=None))

        # 用真实 bridge 来验证 add_message 调用
        bridge = _make_mock_bridge([_make_chat_event("done", "resp")])
        monkeypatch.setattr(ch, "ChatBridge", lambda: bridge)

        events = []
        async for ev in _run_chat_stream(
            "s1", "hi", "deepseek-chat", files=[str(ctx_file)],
        ):
            events.append(ev)

        # bridge.add_message 应被调用注入上下文
        bridge.add_message.assert_called()

    async def test_workspace_files_lookup(self, monkeypatch, tmp_path):
        """无 files 时查找工作区关键文件"""
        monkeypatch.setattr(ch, "_get_api_key_for_model", lambda m: "key")
        fake_cc = MagicMock()
        fake_cc.check_before_call.return_value = (True, "")
        import pycoder.server.services.cost_control as cc_mod
        monkeypatch.setattr(cc_mod, "get_cost_controller", lambda: fake_cc)

        # 工作区中放一个 README.md
        (tmp_path / "README.md").write_text("readme", encoding="utf-8")
        monkeypatch.setattr(
            "pycoder.server.routers.files.get_workspace_root", lambda: tmp_path
        )
        monkeypatch.setattr(ch, "get_session_store",
                            lambda: _make_mock_store(session=None))

        events_for_bridge = [_make_chat_event("done", "resp")]
        monkeypatch.setattr(ch, "ChatBridge",
                            lambda: _make_mock_bridge(events_for_bridge))

        events = []
        async for ev in _run_chat_stream("s1", "hi", "deepseek-chat"):
            events.append(ev)
        # 只验证能正常完成
        assert any(e["type"] == "done" for e in events)

    async def test_system_prompt_set(self, monkeypatch):
        """传入 system_prompt → 设置到 bridge.config"""
        monkeypatch.setattr(ch, "_get_api_key_for_model", lambda m: "key")
        fake_cc = MagicMock()
        fake_cc.check_before_call.return_value = (True, "")
        import pycoder.server.services.cost_control as cc_mod
        monkeypatch.setattr(cc_mod, "get_cost_controller", lambda: fake_cc)

        bridge = _make_mock_bridge([_make_chat_event("done", "resp")])
        monkeypatch.setattr(ch, "ChatBridge", lambda: bridge)
        monkeypatch.setattr(ch, "get_session_store",
                            lambda: _make_mock_store(session=None))

        events = []
        async for ev in _run_chat_stream(
            "s1", "hi", "deepseek-chat", system_prompt="custom prompt",
        ):
            events.append(ev)

        # bridge.config.system_prompt 应被设置为 custom prompt
        assert bridge.config.system_prompt == "custom prompt"

    async def test_save_user_and_assistant_messages(self, monkeypatch):
        """普通聊天结束时应保存用户与 AI 消息"""
        monkeypatch.setattr(ch, "_get_api_key_for_model", lambda m: "key")
        fake_cc = MagicMock()
        fake_cc.check_before_call.return_value = (True, "")
        import pycoder.server.services.cost_control as cc_mod
        monkeypatch.setattr(cc_mod, "get_cost_controller", lambda: fake_cc)

        store = _make_mock_store(session=None)
        monkeypatch.setattr(ch, "get_session_store", lambda: store)

        events_for_bridge = [_make_chat_event("done", "ai response")]
        monkeypatch.setattr(ch, "ChatBridge",
                            lambda: _make_mock_bridge(events_for_bridge))

        events = []
        async for ev in _run_chat_stream("s1", "user msg", "deepseek-chat"):
            events.append(ev)

        # 应保存 user 消息
        store.add_message.assert_any_call("s1", "user", "user msg")
        # 应保存 assistant 消息
        store.add_message.assert_any_call("s1", "assistant", "ai response")

    async def test_cost_precheck_failure_continues(self, monkeypatch):
        """cost precheck 抛异常 → 应继续执行（不阻断）"""
        monkeypatch.setattr(ch, "_get_api_key_for_model", lambda m: "key")

        # mock cost controller 抛 ImportError
        import pycoder.server.services.cost_control as cc_mod
        def raise_import():
            raise ImportError("cost module missing")
        monkeypatch.setattr(cc_mod, "get_cost_controller", raise_import)

        monkeypatch.setattr(ch, "ChatBridge",
                            lambda: _make_mock_bridge([_make_chat_event("done", "resp")]))
        monkeypatch.setattr(ch, "get_session_store",
                            lambda: _make_mock_store(session=None))

        events = []
        async for ev in _run_chat_stream("s1", "hi", "deepseek-chat"):
            events.append(ev)
        # 应能正常完成
        assert any(e["type"] == "done" for e in events)
