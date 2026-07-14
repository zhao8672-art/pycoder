"""P1-4 测试：Clean Architecture 核心接口与适配器

验证：
- ports 模块定义的 Protocol 可被 isinstance 检查
- adapters 模块的实现满足 Protocol 契约
- LocalFileSystem 强制路径校验，防止目录遍历
- SubprocessSandbox 实际执行沙箱代码
- BridgeLLMProvider 适配 ChatBridge
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


# ══════════════════════════════════════════════════════════
# Protocol 契约验证
# ══════════════════════════════════════════════════════════


class TestPortContracts:
    def test_llm_provider_is_protocol(self):
        from pycoder.core.ports.llm_provider import LLMProvider
        # runtime_checkable Protocol 应支持 isinstance
        assert hasattr(LLMProvider, "_is_protocol")

    def test_code_sandbox_is_protocol(self):
        from pycoder.core.ports.code_sandbox import CodeSandbox
        assert hasattr(CodeSandbox, "_is_protocol")

    def test_file_system_is_protocol(self):
        from pycoder.core.ports.file_system import FileSystem
        assert hasattr(FileSystem, "_is_protocol")

    def test_llm_response_dataclass(self):
        from pycoder.core.ports.llm_provider import LLMResponse
        resp = LLMResponse(content="hello", model="test")
        assert resp.content == "hello"
        assert resp.model == "test"
        assert resp.usage == {}

    def test_code_execution_result_dataclass(self):
        from pycoder.core.ports.code_sandbox import CodeExecutionResult
        result = CodeExecutionResult(success=True, stdout="ok")
        assert result.success is True
        assert result.stdout == "ok"


# ══════════════════════════════════════════════════════════
# LocalFileSystem 适配器测试
# ══════════════════════════════════════════════════════════


class TestLocalFileSystem:
    def test_implements_filesystem_protocol(self, tmp_path):
        from pycoder.adapters.local_file_system import LocalFileSystem
        from pycoder.core.ports.file_system import FileSystem
        fs = LocalFileSystem(workspace=tmp_path)
        # runtime_checkable Protocol 应能通过 isinstance
        assert isinstance(fs, FileSystem)

    def test_write_and_read_text(self, tmp_path):
        from pycoder.adapters.local_file_system import LocalFileSystem
        fs = LocalFileSystem(workspace=tmp_path)
        fs.write_text("test.txt", "hello world")
        assert fs.read_text("test.txt") == "hello world"

    def test_exists(self, tmp_path):
        from pycoder.adapters.local_file_system import LocalFileSystem
        fs = LocalFileSystem(workspace=tmp_path)
        assert fs.exists("test.txt") is False
        fs.write_text("test.txt", "x")
        assert fs.exists("test.txt") is True

    def test_list_files(self, tmp_path):
        from pycoder.adapters.local_file_system import LocalFileSystem
        fs = LocalFileSystem(workspace=tmp_path)
        fs.write_text("a.py", "x")
        fs.write_text("b.py", "x")
        files = fs.list_files(".", "*.py")
        names = [f.name for f in files]
        assert "a.py" in names
        assert "b.py" in names

    def test_safe_path_rejects_traversal(self, tmp_path):
        """目录遍历攻击应被拒绝"""
        from pycoder.adapters.local_file_system import LocalFileSystem
        fs = LocalFileSystem(workspace=tmp_path)
        with pytest.raises(ValueError, match="路径逃逸"):
            fs.safe_path("../../etc/passwd")

    def test_safe_path_rejects_absolute_outside(self, tmp_path):
        """绝对路径指向工作区外应被拒绝"""
        from pycoder.adapters.local_file_system import LocalFileSystem
        fs = LocalFileSystem(workspace=tmp_path)
        with pytest.raises(ValueError, match="路径逃逸"):
            fs.safe_path("/etc/passwd")

    def test_safe_path_allows_subdirectory(self, tmp_path):
        """工作区内子目录应允许"""
        from pycoder.adapters.local_file_system import LocalFileSystem
        fs = LocalFileSystem(workspace=tmp_path)
        target = fs.safe_path("src/app/main.py")
        assert str(target).startswith(str(tmp_path))

    def test_write_to_subdirectory_creates_parents(self, tmp_path):
        from pycoder.adapters.local_file_system import LocalFileSystem
        fs = LocalFileSystem(workspace=tmp_path)
        fs.write_text("src/app/main.py", "print('hi')")
        assert fs.exists("src/app/main.py")
        assert fs.read_text("src/app/main.py") == "print('hi')"


# ══════════════════════════════════════════════════════════
# SubprocessSandbox 适配器测试
# ══════════════════════════════════════════════════════════


class TestSubprocessSandbox:
    def test_implements_code_sandbox_protocol(self):
        from pycoder.adapters.subprocess_sandbox import SubprocessSandbox
        from pycoder.core.ports.code_sandbox import CodeSandbox
        sandbox = SubprocessSandbox()
        assert isinstance(sandbox, CodeSandbox)

    @pytest.mark.asyncio
    async def test_execute_safe_code(self):
        from pycoder.adapters.subprocess_sandbox import SubprocessSandbox
        sandbox = SubprocessSandbox()
        result = await sandbox.execute("print(1 + 1)")
        assert result.success is True
        assert "2" in result.stdout

    @pytest.mark.asyncio
    async def test_execute_dangerous_code_blocked(self):
        """危险模块应被沙箱拦截"""
        from pycoder.adapters.subprocess_sandbox import SubprocessSandbox
        sandbox = SubprocessSandbox()
        result = await sandbox.execute("import os\nos.listdir('/')")
        assert result.success is False
        assert "BannedImport" in result.error_type

    @pytest.mark.asyncio
    async def test_timeout_enforced(self):
        from pycoder.adapters.subprocess_sandbox import SubprocessSandbox
        sandbox = SubprocessSandbox()
        result = await sandbox.execute("while True:\n    pass", timeout=2)
        assert result.success is False
        assert "TimeoutError" in result.error_type

    @pytest.mark.asyncio
    async def test_max_timeout_cap(self):
        """超时上限不应超过 _sandbox_config.max_timeout"""
        from pycoder.adapters.subprocess_sandbox import SubprocessSandbox
        sandbox = SubprocessSandbox(max_timeout=5)
        # 传入 1000 秒，应被限制为 5 秒
        # 不实际执行（避免等待），仅验证配置
        assert sandbox._max_timeout == 5


# ══════════════════════════════════════════════════════════
# BridgeLLMProvider 适配器测试
# ══════════════════════════════════════════════════════════


class TestBridgeLLMProvider:
    def test_implements_llm_provider_protocol(self):
        from pycoder.adapters.bridge_llm_provider import BridgeLLMProvider
        from pycoder.core.ports.llm_provider import LLMProvider
        bridge = MagicMock()
        bridge.config = MagicMock()
        provider = BridgeLLMProvider(bridge)
        assert isinstance(provider, LLMProvider)

    def test_configure_delegates_to_bridge(self):
        from pycoder.adapters.bridge_llm_provider import BridgeLLMProvider
        bridge = MagicMock()
        bridge.config = MagicMock()
        provider = BridgeLLMProvider(bridge)
        provider.configure(model="gpt-4", system_prompt="x", max_tokens=100)
        # model 走 bridge.configure()，system_prompt/max_tokens 直接设 bridge.config
        bridge.configure.assert_called_once_with(model="gpt-4")
        assert bridge.config.system_prompt == "x"
        assert bridge.config.max_tokens == 100

    @pytest.mark.asyncio
    async def test_generate_collects_tokens(self):
        from pycoder.adapters.bridge_llm_provider import BridgeLLMProvider
        from pycoder.core.ports.llm_provider import LLMEvent

        bridge = MagicMock()
        bridge.config = MagicMock()

        async def fake_stream(_prompt):
            yield MagicMock(event_type="token", content="Hello")
            yield MagicMock(event_type="token", content=" world")
            yield MagicMock(event_type="done", content="Hello world", usage={"tokens": 10})
        bridge.chat_stream = fake_stream

        provider = BridgeLLMProvider(bridge)
        response = await provider.generate("test")
        assert response.content == "Hello world"
        assert response.usage == {"tokens": 10}

    @pytest.mark.asyncio
    async def test_stream_yields_llm_events(self):
        from pycoder.adapters.bridge_llm_provider import BridgeLLMProvider
        from pycoder.core.ports.llm_provider import LLMEvent

        bridge = MagicMock()
        bridge.config = MagicMock()

        async def fake_stream(_prompt):
            yield MagicMock(event_type="token", content="Hi")
            yield MagicMock(event_type="done", content="Hi", usage={})
        bridge.chat_stream = fake_stream

        provider = BridgeLLMProvider(bridge)
        events = [e async for e in provider.stream("test")]
        assert len(events) == 2
        assert events[0].event_type == "token"
        assert events[0].content == "Hi"
        assert events[1].event_type == "done"


# ══════════════════════════════════════════════════════════
# 依赖方向验证（core 不应依赖 adapters）
# ══════════════════════════════════════════════════════════


class TestDependencyDirection:
    def test_core_does_not_import_adapters(self):
        """core 包不应依赖 adapters 包"""
        import pycoder.core
        import pycoder.core.ports
        import inspect
        # 检查 core 模块的源码不引用 adapters
        for mod in [pycoder.core, pycoder.core.ports]:
            source = inspect.getsource(mod)
            assert "from pycoder.adapters" not in source, (
                f"{mod.__name__} 不应依赖 pycoder.adapters"
            )
            assert "import pycoder.adapters" not in source

    def test_adapters_import_core(self):
        """adapters 包应依赖 core 包"""
        import pycoder.adapters
        import inspect
        source = inspect.getsource(pycoder.adapters)
        # __init__.py 应导入 adapters 模块（间接依赖 core）
        assert "BridgeLLMProvider" in source or "from pycoder.adapters" in source

    def test_adapters_no_module_level_server_import(self):
        """H3: adapters 不应在模块级导入 server（反向依赖）

        检查 adapter 模块源码：server 导入只能出现在 TYPE_CHECKING 块或
        函数体内（惰性导入），不能出现在模块顶层。
        """
        import ast
        import importlib
        from pathlib import Path

        adapter_files = [
            "pycoder/adapters/bridge_llm_provider.py",
            "pycoder/adapters/subprocess_sandbox.py",
        ]
        base = Path(__file__).resolve().parents[2]

        for rel in adapter_files:
            fpath = base / rel
            if not fpath.exists():
                continue
            source = fpath.read_text(encoding="utf-8")
            tree = ast.parse(source)
            # 遍历模块顶层语句
            for node in tree.body:
                # 顶层 import 语句
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert not alias.name.startswith("pycoder.server"), (
                            f"{rel}: 顶层 import pycoder.server.{alias.name} 违反依赖方向"
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith("pycoder.server"):
                        # 允许在 if TYPE_CHECKING: 块内
                        # TYPE_CHECKING 块是 ast.If(test=ast.Name(id="TYPE_CHECKING"))
                        pass  # 已被 if TYPE_CHECKING 保护，AST 层不报错
            # 额外检查：源码中不在 TYPE_CHECKING 块的顶层 server import
            # 简化检查：确保 server import 出现次数 == TYPE_CHECKING 块内次数
            # 这里用正则做粗粒度检查
            import re
            # 匹配顶层的 from pycoder.server import（不在函数/类/if 内）
            # 简化：检查 import 不在 try/except 或函数内
            lines = source.splitlines()
            in_type_checking = False
            indent_of_tc = 0
            for line in lines:
                stripped = line.lstrip()
                indent = len(line) - len(stripped)
                if "if TYPE_CHECKING" in stripped:
                    in_type_checking = True
                    indent_of_tc = indent
                    continue
                if in_type_checking and indent <= indent_of_tc and stripped:
                    in_type_checking = False
                if "from pycoder.server" in stripped or "import pycoder.server" in stripped:
                    # 必须在 TYPE_CHECKING 块内或函数体内（惰性）
                    if not in_type_checking and indent == 0:
                        raise AssertionError(
                            f"{rel}: 模块顶层不应 import pycoder.server（H3 反向依赖）"
                        )

    def test_subprocess_sandbox_dependency_injection(self):
        """H3: SubprocessSandbox 支持 run_fn 依赖注入"""
        from pycoder.adapters.subprocess_sandbox import SubprocessSandbox

        # 注入 mock run_fn — 不应触发 server 导入
        calls = []

        def mock_run(code: str, timeout: int):
            calls.append((code, timeout))
            # 返回一个类 ExecutionResult 的 mock
            class _R:
                success = True
                stdout = "ok"
                stderr = ""
                error_type = ""
                error_message = ""
                traceback = ""
                execution_time = 0.1
            return _R()

        sandbox = SubprocessSandbox(
            run_fn=mock_run, max_timeout_fn=lambda: 600,
        )
        import asyncio
        result = asyncio.run(sandbox.execute("print('hi')", timeout=5))
        assert result.success is True
        assert result.stdout == "ok"
        assert len(calls) == 1
        assert calls[0][0] == "print('hi')"
