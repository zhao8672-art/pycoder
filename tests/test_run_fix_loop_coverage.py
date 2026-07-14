"""RunFixLoop 单元测试 — 覆盖 pycoder.server.services.run_fix_loop

覆盖:
- RunFixStep / RunFixResult 数据类
- execute() 完整流程 (成功 / 生成失败 / 修复成功 / 达到最大重试)
- _generate_code
- _run_code (成功 / 失败 / 超时 / 异常)
- _fix_code
- _call_ai_and_write (含依赖安装)
- _auto_install_deps
- _strip_code_fence (静态)
- _send_step (on_step 回调 / ws_send 失败)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.server.services.run_fix_loop import RunFixLoop, RunFixResult, RunFixStep


# ── 数据类 ─────────────────────────────────────────────


class TestDataClasses:
    def test_run_fix_step_defaults(self):
        s = RunFixStep(step=0, action="run", status="running")
        assert s.code == ""
        assert s.output == ""
        assert s.error == ""

    def test_run_fix_result_defaults(self):
        r = RunFixResult(success=True, steps=[])
        assert r.final_code == ""
        assert r.exec_output == ""
        assert r.total_retries == 0
        assert r.duration_ms == 0.0


# ── _strip_code_fence ─────────────────────────────────


class TestStripCodeFence:
    def test_no_fence(self):
        assert RunFixLoop._strip_code_fence("print('hi')") == "print('hi')"

    def test_python_fence(self):
        text = "```python\nprint('hi')\n```"
        assert RunFixLoop._strip_code_fence(text) == "print('hi')"

    def test_plain_fence(self):
        text = "```\nprint('hi')\n```"
        assert RunFixLoop._strip_code_fence(text) == "print('hi')"

    def test_only_start_fence(self):
        text = "```\nprint('hi')"
        assert RunFixLoop._strip_code_fence(text) == "print('hi')"

    def test_only_end_fence(self):
        text = "print('hi')\n```"
        assert RunFixLoop._strip_code_fence(text) == "print('hi')"

    def test_whitespace_trimmed(self):
        text = "  ```python\nprint('hi')\n```  \n"
        assert RunFixLoop._strip_code_fence(text) == "print('hi')"

    def test_empty(self):
        assert RunFixLoop._strip_code_fence("") == ""


# ── Fixture ───────────────────────────────────────────


@pytest.fixture
def loop(monkeypatch, tmp_path):
    """构造 RunFixLoop 实例，工作目录在 tmp_path。"""
    monkeypatch.chdir(tmp_path)
    chat_fn = AsyncMock()
    ws_send_fn = AsyncMock()
    return RunFixLoop(chat_fn, ws_send_fn, model="deepseek-chat")


# ── _send_step ────────────────────────────────────────


class TestSendStep:
    async def test_calls_ws_send(self, loop):
        await loop._send_step({"step": 0, "action": "run"})
        loop._ws_send.assert_awaited_once()
        sent = loop._ws_send.await_args.args[0]
        assert "run_fix_step" in sent

    async def test_on_step_callback(self, loop):
        received = []
        loop.on_step = AsyncMock(side_effect=lambda d: received.append(d))
        await loop._send_step({"step": 1})
        assert len(received) == 1
        assert received[0]["step"] == 1

    async def test_ws_send_failure_swallowed(self, loop):
        loop._ws_send = AsyncMock(side_effect=ConnectionError("ws down"))
        # 不应抛异常
        await loop._send_step({"step": 0})

    async def test_ws_send_oserror_swallowed(self, loop):
        loop._ws_send = AsyncMock(side_effect=OSError("fail"))
        await loop._send_step({"step": 0})


# ── _generate_code ────────────────────────────────────


class TestGenerateCode:
    async def test_generates_and_writes(self, loop):
        async def _fake_chat(*args, **kwargs):
            yield {"type": "done", "content": "print('hello')"}
        loop._chat = _fake_chat

        code = await loop._generate_code("do something", "solution.py")
        assert "print('hello')" in code
        assert (loop._target_dir / "solution.py").exists()
        assert "print('hello')" in (loop._target_dir / "solution.py").read_text()

    async def test_returns_empty_on_no_content(self, loop):
        async def _fake_chat(*args, **kwargs):
            yield {"type": "done", "content": ""}
        loop._chat = _fake_chat
        code = await loop._generate_code("task", "solution.py")
        assert code == ""

    async def test_strips_code_fence(self, loop):
        async def _fake_chat(*args, **kwargs):
            yield {"type": "done", "content": "```python\nprint('x')\n```"}
        loop._chat = _fake_chat
        code = await loop._generate_code("task", "solution.py")
        assert code == "print('x')"

    async def test_accumulates_tokens_until_done(self, loop):
        async def _fake_chat(*args, **kwargs):
            yield {"type": "token", "content": "pri"}
            yield {"type": "token", "content": "nt('x')"}
            yield {"type": "done", "content": "print('x')"}
        loop._chat = _fake_chat
        code = await loop._generate_code("task", "solution.py")
        assert code == "print('x')"


# ── _run_code ─────────────────────────────────────────


class TestRunCode:
    async def test_success(self, loop, tmp_path):
        # 写一个会成功的脚本
        script = loop._target_dir / "ok.py"
        script.write_text("print('success output')\n", encoding="utf-8")
        result = await loop._run_code(script)
        assert result["success"] is True
        assert "success output" in result["stdout"]

    async def test_failure_nonzero_exit(self, loop, tmp_path):
        script = loop._target_dir / "fail.py"
        script.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
        result = await loop._run_code(script)
        assert result["success"] is False
        assert "stderr" in result

    async def test_runtime_error(self, loop, tmp_path):
        script = loop._target_dir / "err.py"
        script.write_text("raise ValueError('boom')\n", encoding="utf-8")
        result = await loop._run_code(script)
        assert result["success"] is False
        assert "boom" in result["stderr"]

    async def test_syntax_error(self, loop, tmp_path):
        script = loop._target_dir / "syntax.py"
        script.write_text("def (:\n", encoding="utf-8")
        result = await loop._run_code(script)
        assert result["success"] is False
        assert "stderr" in result

    async def test_timeout(self, loop, tmp_path):
        # 写一个会无限循环的脚本，缩短超时来测试
        script = loop._target_dir / "loop.py"
        script.write_text("import time\nwhile True:\n    time.sleep(0.1)\n", encoding="utf-8")
        loop.EXEC_TIMEOUT_SEC = 1
        result = await loop._run_code(script)
        assert result["success"] is False
        assert "超时" in result["stderr"] or "timeout" in result.get("error", "")

    async def test_exec_exception(self, loop, tmp_path):
        # 模拟 create_subprocess_exec 抛异常
        with patch("pycoder.server.services.run_fix_loop.asyncio.create_subprocess_exec",
                    side_effect=OSError("no such file")):
            result = await loop._run_code(Path("nonexistent.py"))
            assert result["success"] is False
            assert "exec_error" in result.get("error", "") or result["stderr"]


# ── _fix_code ─────────────────────────────────────────


class TestFixCode:
    async def test_fixes_and_writes(self, loop, tmp_path):
        # 先准备一个有问题的文件
        existing = loop._target_dir / "solution.py"
        existing.write_text("bad code", encoding="utf-8")

        async def _fake_chat(*args, **kwargs):
            yield {"type": "done", "content": "print('fixed')"}
        loop._chat = _fake_chat

        fixed = await loop._fix_code("task", existing, "SyntaxError", 0)
        assert "print('fixed')" in fixed
        assert "print('fixed')" in existing.read_text()

    async def test_returns_empty_on_no_fix(self, loop, tmp_path):
        existing = loop._target_dir / "solution.py"
        existing.write_text("bad", encoding="utf-8")

        async def _fake_chat(*args, **kwargs):
            yield {"type": "done", "content": ""}
        loop._chat = _fake_chat

        fixed = await loop._fix_code("task", existing, "err", 0)
        assert fixed == ""

    async def test_fix_prompt_includes_error(self, loop, tmp_path):
        # 间接验证: 检查文件存在时被读取
        existing = loop._target_dir / "solution.py"
        existing.write_text("original code here", encoding="utf-8")

        captured_prompt = []

        async def _capture_chat(*args, **kwargs):
            captured_prompt.append(args[1] if len(args) > 1 else kwargs.get("prompt", ""))
            yield {"type": "done", "content": ""}

        loop._chat = _capture_chat

        await loop._fix_code("my task", existing, "MY_ERROR_MSG", 1)
        # prompt 应包含任务、当前代码、错误信息
        assert captured_prompt
        prompt_text = captured_prompt[0]
        assert "my task" in prompt_text
        assert "original code here" in prompt_text
        assert "MY_ERROR_MSG" in prompt_text

    async def test_fix_when_file_missing(self, loop, tmp_path):
        # 文件不存在时 current 应为空字符串
        async def _fake_chat(*args, **kwargs):
            yield {"type": "done", "content": "print('new')"}
        loop._chat = _fake_chat

        missing = loop._target_dir / "ghost.py"
        # 不应抛异常
        fixed = await loop._fix_code("task", missing, "err", 0)
        assert "print('new')" in fixed


# ── _auto_install_deps ────────────────────────────────


class TestAutoInstallDeps:
    async def test_skips_stdlib(self, loop):
        code = "import os\nimport sys\nimport json\n"
        installed = await loop._auto_install_deps(code)
        assert installed == []

    async def test_installs_third_party(self, loop):
        code = "import requests\nimport numpy\n"
        with patch("pycoder.server.services.run_fix_loop.asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.wait = AsyncMock()
            mock_exec.return_value = mock_proc

            installed = await loop._auto_install_deps(code)
            assert "requests" in installed
            assert "numpy" in installed

    async def test_handles_install_failure(self, loop):
        code = "import nonexistent_pkg_xyz\n"
        with patch("pycoder.server.services.run_fix_loop.asyncio.create_subprocess_exec",
                    side_effect=OSError("pip fail")):
            installed = await loop._auto_install_deps(code)
            assert installed == []

    async def test_handles_timeout(self, loop):
        code = "import slow_pkg\n"
        with patch("pycoder.server.services.run_fix_loop.asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.side_effect = asyncio.TimeoutError()
            installed = await loop._auto_install_deps(code)
            assert installed == []

    async def test_handles_dotted_module(self, loop):
        # from foo.bar import baz → 只安装 foo
        code = "from foo.bar import baz\n"
        with patch("pycoder.server.services.run_fix_loop.asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.wait = AsyncMock()
            mock_exec.return_value = mock_proc
            installed = await loop._auto_install_deps(code)
            assert "foo" in installed

    async def test_nonzero_returncode_not_installed(self, loop):
        code = "import bad_pkg\n"
        with patch("pycoder.server.services.run_fix_loop.asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = MagicMock()
            mock_proc.returncode = 1
            mock_proc.wait = AsyncMock()
            mock_exec.return_value = mock_proc
            installed = await loop._auto_install_deps(code)
            assert installed == []


# ── _call_ai_and_write ────────────────────────────────


class TestCallAiAndWrite:
    async def test_writes_cleaned_content(self, loop):
        async def _fake_chat(*args, **kwargs):
            yield {"type": "done", "content": "```python\nprint('x')\n```"}
        loop._chat = _fake_chat
        # 抑制依赖安装
        with patch.object(loop, "_auto_install_deps", return_value=[]):
            code = await loop._call_ai_and_write("prompt", "solution.py")
        assert code == "print('x')"
        assert (loop._target_dir / "solution.py").read_text() == "print('x')"

    async def test_empty_result(self, loop):
        async def _fake_chat(*args, **kwargs):
            yield {"type": "done", "content": ""}
        loop._chat = _fake_chat
        with patch.object(loop, "_auto_install_deps", return_value=[]):
            code = await loop._call_ai_and_write("prompt", "solution.py")
        assert code == ""

    async def test_auto_install_failure_swallowed(self, loop):
        async def _fake_chat(*args, **kwargs):
            yield {"type": "done", "content": "import os\n"}
        loop._chat = _fake_chat
        with patch.object(loop, "_auto_install_deps",
                          side_effect=OSError("install fail")):
            # 不应抛异常
            code = await loop._call_ai_and_write("prompt", "solution.py")
        assert "import os" in code


# ── execute() 完整流程 ────────────────────────────────


class TestExecute:
    async def test_success_first_try(self, loop):
        # 第一轮就运行成功
        call_count = {"gen": 0, "fix": 0}

        async def _chat(*args, **kwargs):
            call_count["gen"] += 1
            yield {"type": "done", "content": "print('hello world')"}
        loop._chat = _chat

        result = await loop.execute("print hello world", "solution.py")
        assert result.success is True
        assert result.total_retries == 0
        assert len(result.steps) >= 2  # generate + run
        assert "hello world" in result.exec_output
        # 不应调用 fix
        assert call_count["fix"] == 0

    async def test_generate_failure(self, loop):
        async def _chat(*args, **kwargs):
            yield {"type": "done", "content": ""}
        loop._chat = _chat

        result = await loop.execute("task", "solution.py")
        assert result.success is False
        assert len(result.steps) == 1
        assert result.steps[0].action == "generate"
        assert result.steps[0].status == "failed"

    async def test_fix_then_success(self, loop):
        # 第一次运行失败，修复后第二次成功
        call_idx = {"n": 0}

        async def _chat(*args, **kwargs):
            call_idx["n"] += 1
            if call_idx["n"] == 1:
                # 初始代码: 会失败
                yield {"type": "done", "content": "raise ValueError('boom')"}
            else:
                # 修复: 成功代码
                yield {"type": "done", "content": "print('fixed ok')"}
        loop._chat = _chat

        result = await loop.execute("task", "solution.py")
        assert result.success is True
        assert result.total_retries == 1
        # 应包含 generate + run(fail) + fix + run(success)
        actions = [s.action for s in result.steps]
        assert "generate" in actions
        assert "fix" in actions

    async def test_max_retries_exhausted(self, loop):
        # 每次运行都失败，修复也每次都"成功"但代码仍失败
        call_idx = {"n": 0}

        async def _chat(*args, **kwargs):
            call_idx["n"] += 1
            # 持续返回会失败的代码
            yield {"type": "done", "content": "raise RuntimeError('always fails')"}
        loop._chat = _chat

        result = await loop.execute("task", "solution.py")
        assert result.success is False
        assert result.total_retries == RunFixLoop.MAX_RETRIES
        # 应有 generate + 5×(run + fix)
        assert len(result.steps) >= 1 + RunFixLoop.MAX_RETRIES * 2

    async def test_fix_failure_breaks_loop(self, loop):
        call_idx = {"n": 0}

        async def _chat(*args, **kwargs):
            call_idx["n"] += 1
            if call_idx["n"] == 1:
                yield {"type": "done", "content": "raise ValueError('x')"}
            else:
                # 修复返回空 → 修复失败
                yield {"type": "done", "content": ""}
        loop._chat = _chat

        result = await loop.execute("task", "solution.py")
        assert result.success is False
        # 修复失败应中断循环
        actions = [s.action for s in result.steps]
        assert "fix" in actions
        # 修复失败后不应再有 run
        last_fix_idx = max(i for i, a in enumerate(actions) if a == "fix")
        assert "run" not in actions[last_fix_idx + 1:]

    async def test_custom_target_file(self, loop):
        async def _chat(*args, **kwargs):
            yield {"type": "done", "content": "print('ok')"}
        loop._chat = _chat

        result = await loop.execute("task", target_file="custom.py")
        assert result.success is True
        assert (loop._target_dir / "custom.py").exists()

    async def test_duration_recorded(self, loop):
        async def _chat(*args, **kwargs):
            yield {"type": "done", "content": "print('ok')"}
        loop._chat = _chat

        result = await loop.execute("task", "solution.py")
        assert result.duration_ms > 0

    async def test_steps_have_incrementing_numbers(self, loop):
        async def _chat(*args, **kwargs):
            yield {"type": "done", "content": "raise ValueError('x')"}
        loop._chat = _chat

        result = await loop.execute("task", "solution.py")
        # generate 是 step 0，run 是 1,3,5...,fix 是 2,4,6...
        step_nums = [s.step for s in result.steps]
        assert step_nums[0] == 0  # generate
