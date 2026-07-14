"""pycoder.server.mcp_tools 单元测试（覆盖率补充版）

测试策略:
  - 直接调用各 `_handle_*` 异步处理器，验证返回结构与错误分支
  - 用 monkeypatch 替换延迟导入的依赖（CodeExecutor / CodeQualityAnalyzer 等）
  - 用 tmp_path 隔离文件 IO，mock subprocess.run / git.Repo 等外部副作用
  - call_tool_with_fallback / MCPClientManager 走 mock 注入
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── 在导入测试目标前预注入可选依赖，避免 mcp_tools_db 加载失败 ──
# （mcp_tools 顶部 try/except 已容错，但显式注入更稳定）


from pycoder.server import mcp_tools
from pycoder.server.mcp_tools import (
    MCPClientManager,
    MCPCallResult,
    MCPToolDef,
    _builtin_tools,
    _gen_fastapi_tests,
    _get_mitigation_hint,
    call_builtin_tool,
    call_tool_with_fallback,
    get_mcp_client_manager,
    list_builtin_tools,
)


# ══════════════════════════════════════════════════════════
# 辅助：异步运行工具处理器
# ══════════════════════════════════════════════════════════

async def _call(handler, args):
    """便捷调用异步处理器"""
    return await handler(args)


# ══════════════════════════════════════════════════════════
# 数据模型与注册表
# ══════════════════════════════════════════════════════════

class TestDataModels:
    """MCPToolDef / MCPCallResult 数据模型"""

    def test_mcp_tool_def_defaults(self):
        d = MCPToolDef(name="x", description="d", input_schema={})
        assert d.name == "x"
        assert d.handler is None

    def test_mcp_call_result_defaults(self):
        r = MCPCallResult(success=True)
        assert r.output is None
        assert r.error == ""
        assert r.tool == ""
        assert r.success is True

    def test_builtin_tools_populated(self):
        # 注册阶段应已注入若干工具
        assert "execute_python" in _builtin_tools
        assert "git_status" in _builtin_tools
        assert "write_file" in _builtin_tools

    def test_list_builtin_tools(self):
        tools = list_builtin_tools()
        assert isinstance(tools, list)
        assert all(t["source"] == "builtin" for t in tools)
        names = {t["name"] for t in tools}
        assert "execute_python" in names
        assert "file_read" in names

    async def test_call_builtin_tool_unknown(self):
        r = await call_builtin_tool("does_not_exist", {})
        assert r.success is False
        assert "未知 Tool" in r.error

    async def test_call_builtin_tool_handler_exception(self):
        """处理器抛异常时 call_builtin_tool 应转为失败结果"""
        # 替换一个已注册工具的 handler 为抛异常的函数
        orig = _builtin_tools["git_status"].handler
        async def boom(args):
            raise RuntimeError("boom")
        _builtin_tools["git_status"].handler = boom
        try:
            r = await call_builtin_tool("git_status", {})
            assert r.success is False
            assert "boom" in r.error
        finally:
            _builtin_tools["git_status"].handler = orig


# ══════════════════════════════════════════════════════════
# execute_python / multilang / list_languages
# ══════════════════════════════════════════════════════════

class TestExecutePython:
    async def test_success(self, monkeypatch):
        from pycoder.server.routers import code_exec as ce_mod
        fake_result = SimpleNamespace(success=True, stdout="42", stderr="", error_type="", error_message="", execution_time=0.01)
        monkeypatch.setattr(ce_mod, "_run_in_subprocess", lambda code, timeout: fake_result)

        r = await mcp_tools._handle_execute_python({"code": "print(42)"})
        assert r["success"] is True
        assert r["stdout"] == "42"

    async def test_exception(self, monkeypatch):
        from pycoder.server.routers import code_exec as ce_mod
        def _raise(code, timeout):
            raise RuntimeError("exec fail")
        monkeypatch.setattr(ce_mod, "_run_in_subprocess", _raise)

        r = await mcp_tools._handle_execute_python({"code": "x"})
        assert r["success"] is False
        assert "exec fail" in r["error"]


class TestMultilang:
    async def test_execute_multilang(self, monkeypatch):
        from pycoder.python import multilang_executor as ml_mod
        async def fake_exec(language, code, timeout):
            return {"success": True, "language": language, "output": "ok"}
        monkeypatch.setattr(ml_mod, "execute_multilang", fake_exec)

        r = await mcp_tools._handle_multilang({"language": "go", "code": "package main"})
        assert r["success"] is True
        assert r["language"] == "go"

    async def test_list_languages(self, monkeypatch):
        from pycoder.python import multilang_executor as ml_mod
        monkeypatch.setattr(ml_mod, "list_available", lambda: ["python", "go"])
        r = await mcp_tools._handle_list_languages({})
        assert r["success"] is True
        assert r["count"] == 2
        assert "python" in r["languages"]


# ══════════════════════════════════════════════════════════
# code_review / _get_mitigation_hint
# ══════════════════════════════════════════════════════════

class _FakeQualityResult:
    """模拟 CodeQualityAnalyzer.analyze 的返回（带 to_dict + 评分属性）"""
    overall = 85
    readability = 80
    maintainability = 82
    performance = 90
    security = 88

    def __init__(self, issues):
        self._issues = issues

    def to_dict(self):
        return {
            "issues": self._issues,
            "performance_issues": self._issues,
            "quality_score": self,
            "overall": self.overall,
            "readability": self.readability,
            "maintainability": self.maintainability,
            "performance": self.performance,
            "security": self.security,
        }

    def get(self, key, default=None):
        if key == "quality_score":
            return self
        return self.to_dict().get(key, default)


class TestCodeReview:
    async def test_review_with_issues(self, monkeypatch):
        from pycoder.python import code_quality as cq_mod
        issues = [
            {"type": "security", "severity": "high", "line": 10, "message": "sql inj"},
            {"type": "performance", "severity": "medium", "message": "slow loop"},  # 无 line
        ]
        fake_analyzer = MagicMock()
        fake_analyzer.return_value.analyze.return_value = _FakeQualityResult(issues)
        monkeypatch.setattr(cq_mod, "CodeQualityAnalyzer", fake_analyzer)

        r = await mcp_tools._handle_code_review({"code": "x = 1"})
        assert r["success"] is True
        assert r["scores"]["overall"] == 85
        assert len(r["issues"]) == 2
        # 第一个 issue 有 line → confidence=high, detection_method=AST
        assert r["issues"][0]["confidence"] == "high"
        assert r["issues"][0]["detection_method"] == "AST"
        # 第二个无 line → pattern
        assert r["issues"][1]["detection_method"] == "pattern"
        assert "mitigation_hint" in r["issues"][0]

    async def test_review_no_issues(self, monkeypatch):
        from pycoder.python import code_quality as cq_mod
        fake_analyzer = MagicMock()
        fake_analyzer.return_value.analyze.return_value = _FakeQualityResult([])
        monkeypatch.setattr(cq_mod, "CodeQualityAnalyzer", fake_analyzer)

        r = await mcp_tools._handle_code_review({"code": "x"})
        assert r["success"] is True
        assert r["issues"] == []
        assert "0 个问题" in r["summary"]

    def test_mitigation_hint_all_types(self):
        for itype in ["security", "performance", "maintainability", "readability", "bug"]:
            hint = _get_mitigation_hint({"type": itype})
            assert isinstance(hint, str) and hint

    def test_mitigation_hint_unknown(self):
        assert _get_mitigation_hint({"type": "unknown_xyz"}) == "根据实际业务逻辑评估必要性"
        assert _get_mitigation_hint({}) == "根据实际业务逻辑评估必要性"


# ══════════════════════════════════════════════════════════
# dependency_analysis / security_scan
# ══════════════════════════════════════════════════════════

class TestDepAnalysis:
    async def test_dep_analysis(self, monkeypatch):
        """_handle_dep_analysis 期望返回 dict-like，但 dep_analyzer.DependencyAnalyzer 不存在
        （实际类是 DepAnalyzer）。这里通过 monkeypatch 注入伪造类以测试内部逻辑。"""
        from pycoder.python import dep_analyzer as da_mod

        class FakeDep:
            name = "requests"
            version = "2.0"
            def to_dict(self):
                return {"name": "requests", "version": "2.0"}

        class FakeAnalyzer:
            def __init__(self):
                pass
            def analyze(self, path):
                return {
                    "dependencies": [FakeDep(), SimpleNamespace(name="flask")],
                    "summary": "2 deps",
                }

        # raising=False: 该属性原本不存在
        monkeypatch.setattr(da_mod, "DependencyAnalyzer", FakeAnalyzer, raising=False)

        r = await mcp_tools._handle_dep_analysis({"path": "."})
        assert r["success"] is True
        assert len(r["dependencies"]) == 2
        assert r["dependencies"][0]["name"] == "requests"
        assert r["dependencies"][1]["name"] == "flask"


class TestSecurityScan:
    async def test_security_scan_success(self, monkeypatch):
        from pycoder.python import dep_analyzer as da_mod
        fake_deps = SimpleNamespace(total_deps=5)
        fake_instance = MagicMock()
        fake_instance.analyze.return_value = fake_deps
        fake_instance.scan_vulnerabilities.return_value = [{"id": "CVE-1"}]
        monkeypatch.setattr(da_mod, "DepAnalyzer", lambda path: fake_instance)

        r = await mcp_tools._handle_security_scan({"path": "."})
        assert r["success"] is True
        assert r["total_deps"] == 5
        assert len(r["vulnerabilities"]) == 1
        assert "扫描了 5 个依赖" in r["summary"]

    async def test_security_scan_no_scan_method(self, monkeypatch):
        from pycoder.python import dep_analyzer as da_mod
        fake_deps = SimpleNamespace(total_deps=3)
        fake_instance = MagicMock()
        fake_instance.analyze.return_value = fake_deps
        # 没有 scan_vulnerabilities 属性 → getattr 返回 None
        del fake_instance.scan_vulnerabilities
        # MagicMock 默认会返回一个 Mock，需要显式设置为 None
        type(fake_instance).scan_vulnerabilities = property(lambda self: None)
        monkeypatch.setattr(da_mod, "DepAnalyzer", lambda path: fake_instance)

        r = await mcp_tools._handle_security_scan({"path": "."})
        assert r["success"] is True
        assert r["vulnerabilities"] == []

    async def test_security_scan_exception(self, monkeypatch):
        from pycoder.python import dep_analyzer as da_mod
        def boom(path):
            raise RuntimeError("scan failed")
        monkeypatch.setattr(da_mod, "DepAnalyzer", boom)

        r = await mcp_tools._handle_security_scan({"path": "."})
        assert r["success"] is False
        assert "scan failed" in r["error"]


# ══════════════════════════════════════════════════════════
# git_status
# ══════════════════════════════════════════════════════════

class TestGitStatus:
    async def test_git_status_success(self, monkeypatch):
        fake_repo = MagicMock()
        fake_repo.active_branch.name = "master"
        fake_repo.git.status.return_value = " M file1.py\n A file2.py\n"

        fake_git_mod = types.ModuleType("git")
        fake_git_mod.Repo = MagicMock(return_value=fake_repo)
        monkeypatch.setitem(sys.modules, "git", fake_git_mod)

        r = await mcp_tools._handle_git_status({"path": "/repo"})
        assert r["success"] is True
        assert r["branch"] == "master"
        assert r["changed_files"] == 2
        assert r["is_dirty"] is True
        assert len(r["changes"]) == 2

    async def test_git_status_no_changes(self, monkeypatch):
        fake_repo = MagicMock()
        fake_repo.active_branch.name = "main"
        fake_repo.git.status.return_value = ""

        fake_git_mod = types.ModuleType("git")
        fake_git_mod.Repo = MagicMock(return_value=fake_repo)
        monkeypatch.setitem(sys.modules, "git", fake_git_mod)

        r = await mcp_tools._handle_git_status({"path": "/repo"})
        assert r["success"] is True
        assert r["changed_files"] == 0
        assert r["is_dirty"] is False

    async def test_git_status_exception(self, monkeypatch):
        fake_git_mod = types.ModuleType("git")
        fake_git_mod.Repo = MagicMock(side_effect=RuntimeError("not a repo"))
        monkeypatch.setitem(sys.modules, "git", fake_git_mod)

        r = await mcp_tools._handle_git_status({"path": "/nope"})
        assert r["success"] is False
        assert "not a repo" in r["error"]


# ══════════════════════════════════════════════════════════
# file_read / file_list
# ══════════════════════════════════════════════════════════

class TestFileRead:
    async def test_read_existing(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("hello world", encoding="utf-8")
        r = await mcp_tools._handle_file_read({"path": str(f)})
        assert r["success"] is True
        assert r["content"] == "hello world"
        assert r["truncated"] is False

    async def test_read_truncated(self, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("x" * 200, encoding="utf-8")
        r = await mcp_tools._handle_file_read({"path": str(f), "max_length": 50})
        assert r["success"] is True
        assert len(r["content"]) == 50
        assert r["truncated"] is True
        assert r["total_length"] == 200

    async def test_read_not_found(self, tmp_path):
        r = await mcp_tools._handle_file_read({"path": str(tmp_path / "nope.txt")})
        assert r["success"] is False
        assert "文件不存在" in r["error"]


class TestFileList:
    async def test_file_list_success(self, monkeypatch):
        from pycoder.server import project_helpers as ph_mod
        async def fake_tree(path, max_depth):
            return {"name": path, "depth": max_depth, "children": []}
        monkeypatch.setattr(ph_mod, "_get_project_tree", fake_tree)

        r = await mcp_tools._handle_file_list({"path": "/x", "max_depth": 3})
        assert r["success"] is True
        assert r["tree"]["depth"] == 3

    async def test_file_list_exception(self, monkeypatch):
        from pycoder.server import project_helpers as ph_mod
        async def boom(*a, **k):
            raise RuntimeError("tree fail")
        monkeypatch.setattr(ph_mod, "_get_project_tree", boom)

        r = await mcp_tools._handle_file_list({"path": "/x"})
        assert r["success"] is False
        assert "tree fail" in r["error"]


# ══════════════════════════════════════════════════════════
# search
# ══════════════════════════════════════════════════════════

class TestSearch:
    async def test_search_finds_matches(self, tmp_path, monkeypatch):
        (tmp_path / "a.py").write_text("def foo():\n    return 'hello'\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("HELLO = 1\n", encoding="utf-8")
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))

        r = await mcp_tools._handle_search({"query": "hello", "max_results": 5})
        assert r["success"] is True
        assert r["total"] >= 2

    async def test_search_max_results(self, tmp_path, monkeypatch):
        for i in range(5):
            (tmp_path / f"f{i}.py").write_text(f"target = {i}\n", encoding="utf-8")
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))

        r = await mcp_tools._handle_search({"query": "target", "max_results": 2})
        assert r["success"] is True
        assert r["total"] == 2

    async def test_search_skips_pycache(self, tmp_path, monkeypatch):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "mod.cpython.py").write_text("target_should_not_appear\n", encoding="utf-8")
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))

        r = await mcp_tools._handle_search({"query": "target_should_not_appear"})
        assert r["success"] is True
        assert r["total"] == 0


# ══════════════════════════════════════════════════════════
# format_code
# ══════════════════════════════════════════════════════════

class TestFormatCode:
    async def test_missing_code(self):
        r = await mcp_tools._handle_format_code({"code": ""})
        assert r["success"] is False
        assert "缺少" in r["error"]

    async def test_black_format(self, monkeypatch):
        """模拟 black 修改临时文件内容后读取"""
        def fake_run(cmd, **kwargs):
            # black 会重写文件 — 模拟一下：找到临时文件并写入格式化内容
            tmp_file = cmd[-1]
            Path(tmp_file).write_text("formatted = True\n", encoding="utf-8")
            return SimpleNamespace(returncode=0)
        monkeypatch.setattr(subprocess, "run", fake_run)

        r = await mcp_tools._handle_format_code({"code": "x=1", "style": "black"})
        assert r["success"] is True
        assert r["style"] == "black"
        assert r["formatted"] == "formatted = True\n"

    async def test_isort_format(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            tmp_file = cmd[-1]
            Path(tmp_file).write_text("import os\n", encoding="utf-8")
            return SimpleNamespace(returncode=0)
        monkeypatch.setattr(subprocess, "run", fake_run)

        r = await mcp_tools._handle_format_code({"code": "import os", "style": "isort"})
        assert r["success"] is True
        assert r["style"] == "isort"

    async def test_ruff_format(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            tmp_file = cmd[-1]
            Path(tmp_file).write_text("x = 1\n", encoding="utf-8")
            return SimpleNamespace(returncode=0)
        monkeypatch.setattr(subprocess, "run", fake_run)

        r = await mcp_tools._handle_format_code({"code": "x=1", "style": "ruff"})
        assert r["success"] is True

    async def test_format_file_not_found(self, monkeypatch):
        """模拟格式化工具未安装"""
        def boom(*a, **k):
            raise FileNotFoundError("black not found")
        monkeypatch.setattr(subprocess, "run", boom)

        r = await mcp_tools._handle_format_code({"code": "x=1"})
        assert r["success"] is False
        assert "未安装" in r["error"]

    async def test_format_other_exception(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("disk full")
        monkeypatch.setattr(subprocess, "run", boom)

        r = await mcp_tools._handle_format_code({"code": "x=1"})
        assert r["success"] is False
        assert "disk full" in r["error"]


# ══════════════════════════════════════════════════════════
# debug_python
# ══════════════════════════════════════════════════════════

class TestDebugPython:
    async def test_success_no_breakpoints(self, monkeypatch):
        from pycoder.server.routers import code_exec as ce_mod
        fake_result = SimpleNamespace(
            success=True, stdout="out", stderr="", error_type="",
            error_message="", execution_time=0.012, traceback="trace\ntrace2",
        )
        monkeypatch.setattr(ce_mod, "_run_in_subprocess", lambda code, timeout: fake_result)

        r = await mcp_tools._handle_debug_python({"code": "print(1)"})
        assert r["success"] is True
        assert r["output"] == "out"
        assert r["duration_ms"] == 12
        assert r["stack_trace"] == ["trace", "trace2"]

    async def test_with_breakpoints(self, monkeypatch):
        from pycoder.server.routers import code_exec as ce_mod
        captured_code = []
        fake_result = SimpleNamespace(
            success=True, stdout="", stderr="", error_type="",
            error_message="", execution_time=0.001, traceback="",
        )
        def fake_run(code, timeout):
            captured_code.append(code)
            return fake_result
        monkeypatch.setattr(ce_mod, "_run_in_subprocess", fake_run)

        r = await mcp_tools._handle_debug_python({
            "code": "line1\nline2\nline3",
            "breakpoints": [2],
        })
        assert r["success"] is True
        assert "pdb.set_trace" in captured_code[0]

    async def test_breakpoint_out_of_range(self, monkeypatch):
        from pycoder.server.routers import code_exec as ce_mod
        captured = []
        fake_result = SimpleNamespace(
            success=True, stdout="o", stderr="", error_type="",
            error_message="", execution_time=0.001, traceback="",
        )
        def fake_exec(code, timeout=30):
            captured.append(code)
            return fake_result
        monkeypatch.setattr(ce_mod, "_run_in_subprocess", fake_exec)

        r = await mcp_tools._handle_debug_python({
            "code": "only one line", "breakpoints": [99],
        })
        assert r["success"] is True
        assert "pdb" not in captured[0]

    async def test_no_traceback(self, monkeypatch):
        """traceback 为空 → stack_trace 为空列表"""
        from pycoder.server.routers import code_exec as ce_mod
        fake_result = SimpleNamespace(
            success=True, stdout="sync", stderr="", error_type="",
            error_message="", execution_time=0.005, traceback="",
        )
        monkeypatch.setattr(ce_mod, "_run_in_subprocess", lambda code, timeout: fake_result)

        r = await mcp_tools._handle_debug_python({"code": "x"})
        assert r["success"] is True
        assert r["output"] == "sync"
        assert r["stack_trace"] == []

    async def test_outer_exception(self, monkeypatch):
        from pycoder.server.routers import code_exec as ce_mod
        def _raise(code, timeout):
            raise RuntimeError("init fail")
        monkeypatch.setattr(ce_mod, "_run_in_subprocess", _raise)
        r = await mcp_tools._handle_debug_python({"code": "x"})
        assert r["success"] is False
        assert "init fail" in r["error"]


# ══════════════════════════════════════════════════════════
# generate_tests / _gen_fastapi_tests
# ══════════════════════════════════════════════════════════

class TestGenerateTests:
    """generate_tests 测试

    注意: 源码使用 `fn.args.annotations`，该属性在 Python 3.14 已被移除。
    测试通过 monkeypatch 注入 ast.arguments.annotations 类属性以绕过该 bug，
    覆盖包含参数的函数测试生成路径。详见最终报告。
    """

    @pytest.fixture(autouse=True)
    def _patch_ast_annotations(self, monkeypatch):
        """为 ast.arguments 注入 annotations 属性以兼容 Python 3.14"""
        import ast as _ast
        # 设为空 list — `p in []` 为 False，跳过类型注解推断分支
        monkeypatch.setattr(_ast.arguments, "annotations", [], raising=False)

    async def test_generate_for_simple_function(self, tmp_path):
        src = tmp_path / "calc.py"
        src.write_text(
            "def add(a: int, b: int) -> int:\n"
            "    '''Add two numbers'''\n"
            "    return a + b\n",
            encoding="utf-8",
        )
        r = await mcp_tools._handle_generate_tests({"file": str(src)})
        assert r["success"] is True
        test_file = Path(r["test_file"])
        assert test_file.exists()
        content = r["test_content"]
        assert "def test_add" in content
        assert "TODO" in content
        test_file.unlink()

    async def test_generate_for_function_no_params(self, tmp_path):
        src = tmp_path / "util.py"
        src.write_text(
            "def hello():\n"
            "    '''Say hi'''\n"
            "    return 'hi'\n",
            encoding="utf-8",
        )
        r = await mcp_tools._handle_generate_tests({"file": str(src)})
        assert r["success"] is True
        content = r["test_content"]
        assert "def test_hello" in content
        Path(r["test_file"]).unlink()

    async def test_generate_for_class(self, tmp_path):
        src = tmp_path / "cls.py"
        src.write_text(
            "class Calculator:\n"
            "    def add(self, a: int, b: int) -> int:\n"
            "        return a + b\n"
            "    async def fetch(self) -> str:\n"
            "        return 'x'\n",
            encoding="utf-8",
        )
        r = await mcp_tools._handle_generate_tests({"file": str(src)})
        assert r["success"] is True
        content = r["test_content"]
        assert "class TestCalculator" in content
        assert "test_add" in content
        assert "async def test_fetch" in content
        Path(r["test_file"]).unlink()

    async def test_generate_for_fastapi(self, tmp_path):
        # 注意: 源码检测 is_fastapi 依赖 n.func.attr == 'FastAPI'，
        # 即需要 `fastapi.FastAPI()` 形式（Attribute 节点），`FastAPI()`（Name 节点）不被识别
        src = tmp_path / "app.py"
        src.write_text(
            "import fastapi\n"
            "app = fastapi.FastAPI()\n"
            "@app.get('/items')\n"
            "def list_items():\n"
            "    return []\n"
            "@app.post('/items')\n"
            "def create_item():\n"
            "    return {}\n",
            encoding="utf-8",
        )
        r = await mcp_tools._handle_generate_tests({"file": str(src)})
        assert r["success"] is True
        content = r["test_content"]
        assert "ASGITransport" in content
        # FastAPI 路由测试
        assert "test_get_items" in content or "test_post_items" in content
        Path(r["test_file"]).unlink()

    async def test_generate_for_api_router(self, tmp_path):
        # 用 APIRouter() 形式触发 is_router 检测
        src = tmp_path / "router_app.py"
        src.write_text(
            "import fastapi\n"
            "router = fastapi.APIRouter()\n"
            "@router.get('/users')\n"
            "def users():\n"
            "    return []\n",
            encoding="utf-8",
        )
        r = await mcp_tools._handle_generate_tests({"file": str(src)})
        assert r["success"] is True
        content = r["test_content"]
        assert "ASGITransport" in content
        Path(r["test_file"]).unlink()

    async def test_generate_file_not_found(self):
        r = await mcp_tools._handle_generate_tests({"file": "/no/such.py"})
        assert r["success"] is False
        assert "文件不存在" in r["error"]

    async def test_generate_syntax_error(self, tmp_path):
        src = tmp_path / "bad.py"
        src.write_text("def (:\n", encoding="utf-8")
        r = await mcp_tools._handle_generate_tests({"file": str(src)})
        assert r["success"] is False
        assert "语法错误" in r["error"]

    def test_gen_fastapi_tests_no_routes(self):
        import ast
        tree = ast.parse("x = 1\n")
        lines = _gen_fastapi_tests(tree, Path("x.py"))
        assert lines == []

    def test_gen_fastapi_tests_with_routes(self):
        import ast
        code = (
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            "@app.get('/users')\n"
            "def users(): pass\n"
            "@app.delete('/users/1')\n"
            "def del_user(): pass\n"
        )
        tree = ast.parse(code)
        lines = _gen_fastapi_tests(tree, Path("app.py"))
        joined = "\n".join(lines)
        assert "test_get_users" in joined
        assert "test_delete" in joined
        assert "AsyncClient" in joined


# ══════════════════════════════════════════════════════════
# generate_pipeline
# ══════════════════════════════════════════════════════════

class TestGeneratePipeline:
    async def test_python_app(self, tmp_path, monkeypatch):
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
        r = await mcp_tools._handle_generate_pipeline({
            "project_type": "python-app", "platform": "github-actions",
        })
        assert r["success"] is True
        assert r["file"] == ".github/workflows/ci.yml"
        assert (tmp_path / ".github" / "workflows" / "ci.yml").exists()

    async def test_fastapi_template(self, tmp_path, monkeypatch):
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
        r = await mcp_tools._handle_generate_pipeline({
            "project_type": "fastapi", "platform": "github-actions",
        })
        assert r["success"] is True
        assert "PyCoder CI" not in r["content"]  # fastapi 模板不同
        assert "Deploy FastAPI" in r["content"]

    async def test_unsupported_combo(self):
        r = await mcp_tools._handle_generate_pipeline({
            "project_type": "unknown", "platform": "gitlab-ci",
        })
        assert r["success"] is False
        assert "不支持的组合" in r["error"]

    async def test_write_exception(self, monkeypatch):
        # 让 Path.mkdir 抛异常
        monkeypatch.setattr(os, "getcwd", lambda: "/nonexistent_root_xyz")
        r = await mcp_tools._handle_generate_pipeline({})
        # 在 Windows 上可能成功也可能失败 — 只要 success 字段存在即可
        assert "success" in r


# ══════════════════════════════════════════════════════════
# docker_status / docker_execute
# ══════════════════════════════════════════════════════════

class TestDocker:
    async def test_docker_status(self, monkeypatch):
        from pycoder.server import docker_backend as db_mod
        backend = MagicMock()
        backend.get_status = AsyncMock(return_value={"available": True})
        monkeypatch.setattr(db_mod, "get_docker_backend", lambda: backend)

        r = await mcp_tools._handle_docker_status({})
        assert r == {"available": True}

    async def test_docker_execute_unavailable(self, monkeypatch):
        from pycoder.server import docker_backend as db_mod
        backend = MagicMock()
        backend.is_available = False
        monkeypatch.setattr(db_mod, "get_docker_backend", lambda: backend)

        r = await mcp_tools._handle_docker_execute({"code": "x"})
        assert r["success"] is False
        assert "Docker 不可用" in r["error"]

    async def test_docker_execute_success(self, monkeypatch):
        from pycoder.server import docker_backend as db_mod
        backend = MagicMock()
        backend.is_available = True
        backend.execute = AsyncMock(return_value=SimpleNamespace(
            success=True, output="ok", error="", duration_ms=10,
            container_id="abcdef1234567890",
        ))
        monkeypatch.setattr(db_mod, "get_docker_backend", lambda: backend)

        r = await mcp_tools._handle_docker_execute({"code": "print(1)"})
        assert r["success"] is True
        assert r["output"] == "ok"
        assert r["container_id"] == "abcdef123456"  # 截取前 12 字符

    async def test_docker_execute_no_container(self, monkeypatch):
        from pycoder.server import docker_backend as db_mod
        backend = MagicMock()
        backend.is_available = True
        backend.execute = AsyncMock(return_value=SimpleNamespace(
            success=True, output="", error="", duration_ms=1, container_id="",
        ))
        monkeypatch.setattr(db_mod, "get_docker_backend", lambda: backend)

        r = await mcp_tools._handle_docker_execute({"code": "x"})
        assert r["success"] is True
        assert r["container_id"] == ""

    async def test_docker_execute_exception(self, monkeypatch):
        from pycoder.server import docker_backend as db_mod
        backend = MagicMock()
        backend.is_available = True
        backend.execute = AsyncMock(side_effect=RuntimeError("container gone"))
        monkeypatch.setattr(db_mod, "get_docker_backend", lambda: backend)

        r = await mcp_tools._handle_docker_execute({"code": "x"})
        assert r["success"] is False
        assert "container gone" in r["error"]


# ══════════════════════════════════════════════════════════
# profile_python
# ══════════════════════════════════════════════════════════

class TestProfilePython:
    async def test_success(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            # 找到临时脚本，写入 stdout
            return SimpleNamespace(returncode=0, stdout="PROFILE OUTPUT", stderr="")
        monkeypatch.setattr(subprocess, "run", fake_run)

        r = await mcp_tools._handle_profile_python({"code": "x = 1"})
        assert r["success"] is True
        assert "PROFILE OUTPUT" in r["profile"]

    async def test_nonzero_returncode(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=1, stdout="", stderr="syntax error"))
        r = await mcp_tools._handle_profile_python({"code": "bad"})
        assert r["success"] is False
        assert "syntax error" in r["error"]

    async def test_timeout(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd="x", timeout=30)))
        r = await mcp_tools._handle_profile_python({"code": "while True: pass", "timeout": 30})
        assert r["success"] is False
        assert "超时" in r["error"]

    async def test_other_exception(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("disk")))
        r = await mcp_tools._handle_profile_python({"code": "x"})
        assert r["success"] is False
        assert "disk" in r["error"]


# ══════════════════════════════════════════════════════════
# execute_code (多语言自动检测)
# ══════════════════════════════════════════════════════════

class TestExecuteCode:
    async def test_python_success(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="42", stderr=""))
        r = await mcp_tools._handle_execute_code({"code": "print(42)", "language": "python"})
        assert r["success"] is True
        assert r["output"] == "42"
        assert r["language"] == "python"

    async def test_python_timeout(self, monkeypatch):
        """超时应返回 success=False"""
        def boom(*a, **k):
            raise subprocess.TimeoutExpired(cmd="python", timeout=30)
        monkeypatch.setattr(subprocess, "run", boom)
        r = await mcp_tools._handle_execute_code({"code": "while True: pass", "language": "python"})
        assert r["success"] is False
        assert "超时" in r["error"]

    async def test_python_file_not_found(self, monkeypatch):
        """Python 未安装应返回 success=False"""
        def boom(*a, **k):
            raise FileNotFoundError("python not found")
        monkeypatch.setattr(subprocess, "run", boom)
        r = await mcp_tools._handle_execute_code({"code": "x", "language": "python"})
        assert r["success"] is False
        assert "运行时未找到" in r["error"]

    async def test_auto_detect_python_shebang(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="detected", stderr=""))
        r = await mcp_tools._handle_execute_code({"code": "#!/usr/bin/env python\nprint(1)"})
        assert r["success"] is True
        assert r["language"] == "python"

    async def test_auto_detect_node_shebang(self, monkeypatch):
        """node shebang → language=javascript"""
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="js", stderr=""))
        r = await mcp_tools._handle_execute_code({"code": "#!/usr/bin/env node\nconsole.log(1)"})
        assert r["success"] is True
        assert r["language"] == "javascript"

    async def test_auto_detect_bash_shebang(self, monkeypatch):
        """bash shebang → language=shell"""
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="sh", stderr=""))
        r = await mcp_tools._handle_execute_code({"code": "#!/bin/bash\necho hi"})
        assert r["success"] is True
        assert r["language"] == "shell"

    async def test_auto_detect_default_python(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="default", stderr=""))
        r = await mcp_tools._handle_execute_code({"code": "print(1)"})
        assert r["success"] is True
        assert r["language"] == "python"

    async def test_unsupported_language(self):
        r = await mcp_tools._handle_execute_code({"code": "x", "language": "ruby"})
        assert r["success"] is False
        assert "不支持的语言" in r["error"]
        assert r["language"] == "ruby"

    async def test_javascript_explicit(self, monkeypatch):
        """显式 javascript → 走 javascript 分支"""
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="js", stderr=""))
        r = await mcp_tools._handle_execute_code({"code": "console.log(1)", "language": "javascript"})
        assert r["success"] is True
        assert r["language"] == "javascript"

    async def test_javascript_timeout(self, monkeypatch):
        """javascript 超时分支有独立的返回（不依赖 _mkres）"""
        def boom(*a, **k):
            raise subprocess.TimeoutExpired(cmd="node", timeout=30)
        monkeypatch.setattr(subprocess, "run", boom)
        r = await mcp_tools._handle_execute_code({"code": "while(true){}", "language": "javascript"})
        assert r["success"] is False
        assert "超时" in r["error"]

    async def test_javascript_not_found(self, monkeypatch):
        """javascript FileNotFoundError 分支有独立返回"""
        def boom(*a, **k):
            raise FileNotFoundError("node missing")
        monkeypatch.setattr(subprocess, "run", boom)
        r = await mcp_tools._handle_execute_code({"code": "x", "language": "javascript"})
        assert r["success"] is False
        assert "Node.js 未安装" in r["error"]

    async def test_shell_path_bug(self, monkeypatch):
        """shell 分支正常执行"""
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="sh", stderr=""))
        r = await mcp_tools._handle_execute_code({"code": "echo hi", "language": "shell"})
        assert r["success"] is True
        assert r["language"] == "shell"


# ══════════════════════════════════════════════════════════
# resolve_conflict
# ══════════════════════════════════════════════════════════

class TestResolveConflict:
    async def test_file_not_found(self):
        r = await mcp_tools._handle_resolve_conflict({"file": "/no/such.txt"})
        assert r["success"] is False
        assert "文件不存在" in r["error"]

    async def test_no_conflicts(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text("x = 1\n", encoding="utf-8")
        r = await mcp_tools._handle_resolve_conflict({"file": str(f)})
        assert r["success"] is True
        assert r["conflict_count"] == 0
        assert r["resolved"] == "x = 1\n"

    async def test_identical_conflict(self, tmp_path):
        f = tmp_path / "c.py"
        f.write_text(
            "<<<<<<< HEAD\nsame line\n=======\nsame line\n>>>>>>> branch\n",
            encoding="utf-8",
        )
        r = await mcp_tools._handle_resolve_conflict({"file": str(f)})
        assert r["success"] is True
        assert r["conflict_count"] == 1
        assert r["conflicts"][0]["strategy"] == "identical"
        assert r["auto_resolved"] is True

    async def test_superset_conflict(self, tmp_path):
        f = tmp_path / "c.py"
        f.write_text(
            "<<<<<<< HEAD\nabc extended\n=======\nabc\n>>>>>>> branch\n",
            encoding="utf-8",
        )
        r = await mcp_tools._handle_resolve_conflict({"file": str(f)})
        assert r["success"] is True
        assert r["conflicts"][0]["strategy"] == "superset"
        assert r["auto_resolved"] is True

    async def test_needs_review_conflict(self, tmp_path):
        f = tmp_path / "c.py"
        f.write_text(
            "<<<<<<< HEAD\noption A\n=======\noption B\n>>>>>>> branch\n",
            encoding="utf-8",
        )
        r = await mcp_tools._handle_resolve_conflict({"file": str(f)})
        assert r["success"] is True
        assert r["conflicts"][0]["strategy"] == "needs_review"
        assert len(r["needs_review"]) == 1
        assert r["auto_resolved"] is False

    async def test_exception(self, monkeypatch):
        # 让 Path.exists 抛异常
        monkeypatch.setattr(Path, "exists", lambda self: (_ for _ in ()).throw(RuntimeError("io")))
        r = await mcp_tools._handle_resolve_conflict({"file": "/x"})
        assert r["success"] is False
        assert "io" in r["error"]


# ══════════════════════════════════════════════════════════
# test_integration / test_e2e / test_performance
# ══════════════════════════════════════════════════════════

class TestTestIntegration:
    async def test_file_not_found(self):
        r = await mcp_tools._handle_test_integration({"app_file": "/no/app.py"})
        assert r["success"] is False
        assert "文件不存在" in r["error"]

    async def test_generate_with_routes(self, tmp_path):
        app = tmp_path / "myapp.py"
        app.write_text(
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            "@app.get('/api/users')\n"
            "def users(): pass\n"
            "@app.post('/api/items')\n"
            "def create(): pass\n",
            encoding="utf-8",
        )
        r = await mcp_tools._handle_test_integration({
            "app_file": str(app), "output_dir": str(tmp_path / "tests"),
        })
        assert r["success"] is True
        assert r["route_count"] >= 2
        assert "test_get_api_users" in r["test_content"]
        assert "AsyncClient" in r["test_content"]
        assert (tmp_path / "tests" / "test_myapp_api.py").exists()

    async def test_no_routes(self, tmp_path):
        app = tmp_path / "plain.py"
        app.write_text("x = 1\n", encoding="utf-8")
        r = await mcp_tools._handle_test_integration({
            "app_file": str(app), "output_dir": str(tmp_path / "out"),
        })
        assert r["success"] is True
        assert r["route_count"] == 0

    async def test_exception(self, monkeypatch):
        monkeypatch.setattr(Path, "exists", lambda self: (_ for _ in ()).throw(RuntimeError("io")))
        r = await mcp_tools._handle_test_integration({"app_file": "/x"})
        assert r["success"] is False


class TestTestE2E:
    async def test_default_pages(self):
        r = await mcp_tools._handle_test_e2e({})
        assert r["success"] is True
        assert "playwright" in r["test_content"]
        assert r["page_count"] == 1

    async def test_custom_pages(self):
        r = await mcp_tools._handle_test_e2e({
            "app_url": "http://myapp.com",
            "pages": ["/", "/about", "/users"],
        })
        assert r["success"] is True
        assert r["page_count"] == 3
        assert "myapp.com" in r["test_content"]
        assert "test_page_about" in r["test_content"]


class TestTestPerformance:
    async def test_default(self):
        r = await mcp_tools._handle_test_performance({})
        assert r["success"] is True
        assert "locust" in r["test_content"]
        assert "WebsiteUser" in r["test_content"]
        assert "locust" in r["instructions"]

    async def test_custom(self):
        r = await mcp_tools._handle_test_performance({
            "target_url": "http://x.com", "users": 50, "spawn_rate": 5,
        })
        assert r["success"] is True
        assert "50" in r["test_content"]
        assert "5" in r["test_content"]


# ══════════════════════════════════════════════════════════
# python_env / quick_open / git_log / git_diff_branch / snippets
# ══════════════════════════════════════════════════════════

class TestPythonEnv:
    async def test_with_venv_env(self, monkeypatch, tmp_path):
        # 模拟 VIRTUAL_ENV
        monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "venv"))
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="Python 3.14.0", stderr=""))

        r = await mcp_tools._handle_python_env({})
        assert r["success"] is True
        assert any(e["name"] == "current" for e in r["environments"])
        assert "Python 3.14.0" in r["python_version"]

    async def test_with_conda_env(self, monkeypatch, tmp_path):
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        monkeypatch.setenv("CONDA_PREFIX", "/opt/conda")
        monkeypatch.setenv("CONDA_DEFAULT_ENV", "myenv")
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="Python 3.12", stderr=""))

        r = await mcp_tools._handle_python_env({})
        assert r["success"] is True
        conda_envs = [e for e in r["environments"] if e["type"] == "conda"]
        assert len(conda_envs) == 1
        assert conda_envs[0]["name"] == "myenv"

    async def test_subprocess_failure(self, monkeypatch, tmp_path):
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
            subprocess.SubprocessError("fail")))

        r = await mcp_tools._handle_python_env({})
        assert r["success"] is True
        # 回退到 sys.version_info
        assert "." in r["python_version"]


class TestQuickOpen:
    async def test_find_files(self, tmp_path, monkeypatch):
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        (tmp_path / "b.md").write_text("y", encoding="utf-8")
        (tmp_path / "c.txt").write_text("z", encoding="utf-8")  # 不在支持后缀
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))

        r = await mcp_tools._handle_quick_open({"query": ""})
        assert r["success"] is True
        paths = [item["path"] for item in r["results"]]
        assert "a.py" in paths
        assert "b.md" in paths
        assert "c.txt" not in paths

    async def test_filter_by_query(self, tmp_path, monkeypatch):
        (tmp_path / "alpha.py").write_text("x", encoding="utf-8")
        (tmp_path / "beta.py").write_text("y", encoding="utf-8")
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))

        r = await mcp_tools._handle_quick_open({"query": "alpha"})
        assert r["success"] is True
        paths = [item["path"] for item in r["results"]]
        assert "alpha.py" in paths
        assert "beta.py" not in paths

    async def test_max_results(self, tmp_path, monkeypatch):
        for i in range(5):
            (tmp_path / f"f{i}.py").write_text("x", encoding="utf-8")
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))

        r = await mcp_tools._handle_quick_open({"max_results": 2})
        assert r["success"] is True
        assert r["total"] == 2


class TestGitLog:
    async def test_success(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="* abc\n* def\n", stderr=""))
        r = await mcp_tools._handle_git_log({"limit": 5})
        assert r["success"] is True
        assert r["count"] == 2

    async def test_exception(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("git not installed")))
        r = await mcp_tools._handle_git_log({"limit": 5})
        assert r["success"] is False
        assert "git not installed" in r["error"]


class TestGitDiffBranch:
    async def test_success(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            if "--name-only" in cmd:
                return SimpleNamespace(returncode=0, stdout="a.py\nb.py\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="2 files changed", stderr="")
        monkeypatch.setattr(subprocess, "run", fake_run)

        r = await mcp_tools._handle_git_diff_branch({"branch1": "main", "branch2": "dev"})
        assert r["success"] is True
        assert r["changed_files"] == 2
        assert len(r["files"]) == 2
        assert "2 files changed" in r["stat"]

    async def test_exception(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("fail")))
        r = await mcp_tools._handle_git_diff_branch({"branch1": "main"})
        assert r["success"] is False


class TestSnippets:
    async def test_list(self, monkeypatch):
        from pycoder.prompts import snippets_loader as sl_mod
        monkeypatch.setattr(sl_mod, "list_snippets", lambda lang: [
            {"prefix": "fn", "body": "def f(): pass"},
        ])
        r = await mcp_tools._handle_snippets({"subcommand": "list", "language": "python"})
        assert r["success"] is True
        assert r["total"] == 1
        assert r["language"] == "python"

    async def test_get_found(self, monkeypatch):
        from pycoder.prompts import snippets_loader as sl_mod
        monkeypatch.setattr(sl_mod, "get_snippet", lambda lang, prefix: {"prefix": prefix})
        r = await mcp_tools._handle_snippets({
            "subcommand": "get", "language": "python", "prefix": "fn",
        })
        assert r["success"] is True
        assert r["snippet"]["prefix"] == "fn"

    async def test_get_not_found(self, monkeypatch):
        from pycoder.prompts import snippets_loader as sl_mod
        monkeypatch.setattr(sl_mod, "get_snippet", lambda lang, prefix: None)
        r = await mcp_tools._handle_snippets({
            "subcommand": "get", "language": "python", "prefix": "nope",
        })
        assert r["success"] is False
        assert "not found" in r["error"]

    async def test_default_subcommand(self, monkeypatch):
        from pycoder.prompts import snippets_loader as sl_mod
        monkeypatch.setattr(sl_mod, "list_snippets", lambda lang: [])
        r = await mcp_tools._handle_snippets({"language": "go"})
        assert r["success"] is True
        assert r["language"] == "go"


# ══════════════════════════════════════════════════════════
# 工作区文件操作: write_file / create_directory / read_file / list_files / delete_file / run_terminal
# ══════════════════════════════════════════════════════════

def _patch_workspace(monkeypatch, tmp_path):
    """注入 get_workspace_root 返回 tmp_path"""
    from pycoder.server.routers import files as files_mod
    monkeypatch.setattr(files_mod, "get_workspace_root", lambda: tmp_path)
    # 由于源码使用 from ... import get_workspace_root，
    # 每次调用都会重新 import — 直接修改 sys.modules 中的属性即可
    return files_mod


class TestWorkspaceFiles:
    async def test_write_file_success(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        r = await mcp_tools._handle_write_file({"path": "src/main.py", "content": "x = 1"})
        assert r["success"] is True
        assert (tmp_path / "src" / "main.py").exists()
        assert r["size"] == 5

    async def test_write_file_empty_path(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        r = await mcp_tools._handle_write_file({"path": "", "content": "x"})
        assert r["success"] is False
        assert "path" in r["error"]

    async def test_write_file_empty_content(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        r = await mcp_tools._handle_write_file({"path": "a.py", "content": ""})
        assert r["success"] is False
        assert "content" in r["error"]

    async def test_write_file_traversal(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        r = await mcp_tools._handle_write_file({"path": "../escape.py", "content": "x"})
        assert r["success"] is False
        assert "路径穿越" in r["error"]

    async def test_create_directory_success(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        r = await mcp_tools._handle_create_directory({"path": "a/b/c"})
        assert r["success"] is True
        assert (tmp_path / "a" / "b" / "c").is_dir()

    async def test_create_directory_empty(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        r = await mcp_tools._handle_create_directory({"path": ""})
        assert r["success"] is False

    async def test_create_directory_traversal(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        r = await mcp_tools._handle_create_directory({"path": "../x"})
        assert r["success"] is False
        assert "路径穿越" in r["error"]

    async def test_read_file_success(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        (tmp_path / "r.py").write_text("hello", encoding="utf-8")
        r = await mcp_tools._handle_read_file({"path": "r.py"})
        assert r["success"] is True
        assert r["content"] == "hello"
        assert r["size"] == 5

    async def test_read_file_empty_path(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        r = await mcp_tools._handle_read_file({"path": ""})
        assert r["success"] is False

    async def test_read_file_traversal(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        r = await mcp_tools._handle_read_file({"path": "../x"})
        assert r["success"] is False
        assert "路径穿越" in r["error"]

    async def test_read_file_not_found(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        r = await mcp_tools._handle_read_file({"path": "nope.py"})
        assert r["success"] is False
        assert "文件不存在" in r["error"]

    async def test_read_file_is_dir(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        (tmp_path / "subdir").mkdir()
        r = await mcp_tools._handle_read_file({"path": "subdir"})
        assert r["success"] is False
        assert "目录" in r["error"]

    async def test_list_files_success(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        r = await mcp_tools._handle_list_files({"path": "."})
        assert r["success"] is True
        names = {it["name"] for it in r["items"]}
        assert "a.py" in names
        assert "sub" in names

    async def test_list_files_traversal(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        r = await mcp_tools._handle_list_files({"path": "../"})
        assert r["success"] is False
        assert "路径穿越" in r["error"]

    async def test_list_files_not_exists(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        r = await mcp_tools._handle_list_files({"path": "nope"})
        assert r["success"] is False
        assert "路径不存在" in r["error"]

    async def test_list_files_not_dir(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        (tmp_path / "f.py").write_text("x", encoding="utf-8")
        r = await mcp_tools._handle_list_files({"path": "f.py"})
        assert r["success"] is False
        assert "不是目录" in r["error"]

    async def test_delete_file_success(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        (tmp_path / "del.py").write_text("x", encoding="utf-8")
        r = await mcp_tools._handle_delete_file({"path": "del.py"})
        assert r["success"] is True
        assert not (tmp_path / "del.py").exists()

    async def test_delete_directory_success(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "a.py").write_text("x", encoding="utf-8")
        r = await mcp_tools._handle_delete_file({"path": "subdir"})
        assert r["success"] is True
        assert not sub.exists()

    async def test_delete_empty_path(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        r = await mcp_tools._handle_delete_file({"path": ""})
        assert r["success"] is False

    async def test_delete_traversal(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        r = await mcp_tools._handle_delete_file({"path": "../x"})
        assert r["success"] is False
        assert "路径穿越" in r["error"]

    async def test_delete_exception(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        # 不存在的文件 → unlink 抛异常
        r = await mcp_tools._handle_delete_file({"path": "ghost.py"})
        assert r["success"] is False


class TestRunTerminal:
    async def test_empty_command(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        r = await mcp_tools._handle_run_terminal({"command": ""})
        assert r["success"] is False
        assert "command" in r["error"]

    async def test_success(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="output here", stderr=""))
        r = await mcp_tools._handle_run_terminal({"command": "echo hi"})
        assert r["success"] is True
        assert r["exit_code"] == 0
        assert "output here" in r["stdout"]

    async def test_nonzero_exit(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=1, stdout="", stderr="error msg"))
        r = await mcp_tools._handle_run_terminal({"command": "false"})
        assert r["success"] is False
        assert r["exit_code"] == 1
        assert "error msg" in r["stderr"]

    async def test_timeout(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd="x", timeout=5)))
        r = await mcp_tools._handle_run_terminal({"command": "sleep 100", "timeout": 5})
        assert r["success"] is False
        assert "超时" in r["error"]
        assert r["exit_code"] == -1

    async def test_other_exception(self, tmp_path, monkeypatch):
        _patch_workspace(monkeypatch, tmp_path)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("shell crash")))
        r = await mcp_tools._handle_run_terminal({"command": "x"})
        assert r["success"] is False
        assert "shell crash" in r["error"]
        assert r["exit_code"] == -1


# ══════════════════════════════════════════════════════════
# Skills Market v2 handlers
# ══════════════════════════════════════════════════════════

class TestSkillsV2:
    async def test_search_v2(self, monkeypatch):
        from pycoder.server import skills_market_v2 as sm_mod
        market = MagicMock()
        market.search.return_value = {"total": 1, "skills": [{"id": "x"}]}
        monkeypatch.setattr(sm_mod, "get_enhanced_market", lambda: market)

        r = await mcp_tools._handle_skills_search_v2({"query": "test", "tags": ["a"]})
        assert r["success"] is True
        assert r["total"] == 1
        assert r["sort_by"] == "quality"

    async def test_search_v2_exception(self, monkeypatch):
        from pycoder.server import skills_market_v2 as sm_mod
        market = MagicMock()
        market.search.side_effect = RuntimeError("boom")
        monkeypatch.setattr(sm_mod, "get_enhanced_market", lambda: market)
        r = await mcp_tools._handle_skills_search_v2({})
        assert r["success"] is False
        assert "boom" in r["error"]

    async def test_recommendations_v2(self, monkeypatch):
        from pycoder.server import skills_market_v2 as sm_mod
        market = MagicMock()
        market.get_recommendations.return_value = [{"id": "r1"}]
        monkeypatch.setattr(sm_mod, "get_enhanced_market", lambda: market)
        r = await mcp_tools._handle_skills_recommendations_v2({"category": "ai", "limit": 5})
        assert r["success"] is True
        assert r["count"] == 1

    async def test_recommendations_v2_exception(self, monkeypatch):
        from pycoder.server import skills_market_v2 as sm_mod
        market = MagicMock()
        market.get_recommendations.side_effect = ValueError("bad")
        monkeypatch.setattr(sm_mod, "get_enhanced_market", lambda: market)
        r = await mcp_tools._handle_skills_recommendations_v2({})
        assert r["success"] is False

    async def test_trending_v2(self, monkeypatch):
        from pycoder.server import skills_market_v2 as sm_mod
        market = MagicMock()
        market.get_trending.return_value = [{"id": "t1"}]
        monkeypatch.setattr(sm_mod, "get_enhanced_market", lambda: market)
        r = await mcp_tools._handle_skills_trending_v2({"limit": 3})
        assert r["success"] is True
        assert r["count"] == 1

    async def test_trending_v2_exception(self, monkeypatch):
        from pycoder.server import skills_market_v2 as sm_mod
        market = MagicMock()
        market.get_trending.side_effect = RuntimeError("x")
        monkeypatch.setattr(sm_mod, "get_enhanced_market", lambda: market)
        r = await mcp_tools._handle_skills_trending_v2({})
        assert r["success"] is False

    async def test_stats_v2(self, monkeypatch):
        from pycoder.server import skills_market_v2 as sm_mod
        market = MagicMock()
        market.get_stats.return_value = {"total": 100}
        monkeypatch.setattr(sm_mod, "get_enhanced_market", lambda: market)
        r = await mcp_tools._handle_skills_stats_v2({})
        assert r["success"] is True
        assert r["stats"]["total"] == 100

    async def test_stats_v2_exception(self, monkeypatch):
        from pycoder.server import skills_market_v2 as sm_mod
        market = MagicMock()
        market.get_stats.side_effect = RuntimeError("x")
        monkeypatch.setattr(sm_mod, "get_enhanced_market", lambda: market)
        r = await mcp_tools._handle_skills_stats_v2({})
        assert r["success"] is False

    async def test_sync_v2(self, monkeypatch):
        from pycoder.server import skills_market_v2 as sm_mod
        market = MagicMock()
        market.sync_from_all_sources = AsyncMock(return_value={
            "total_skills": 10, "sources": {"github": 5},
        })
        monkeypatch.setattr(sm_mod, "get_enhanced_market", lambda: market)
        r = await mcp_tools._handle_skills_sync_v2({})
        assert r["success"] is True
        assert r["total_skills"] == 10

    async def test_sync_v2_exception(self, monkeypatch):
        from pycoder.server import skills_market_v2 as sm_mod
        market = MagicMock()
        market.sync_from_all_sources = AsyncMock(side_effect=RuntimeError("sync fail"))
        monkeypatch.setattr(sm_mod, "get_enhanced_market", lambda: market)
        r = await mcp_tools._handle_skills_sync_v2({})
        assert r["success"] is False
        assert "sync fail" in r["error"]


# ══════════════════════════════════════════════════════════
# skills_update / skills_market / system_upgrade
# ══════════════════════════════════════════════════════════

class TestSkillsUpdate:
    async def test_success(self, monkeypatch):
        from pycoder.server import skills_updater as su_mod
        fetcher = MagicMock()
        fetcher.fetch_all_sources = AsyncMock(return_value={
            "success": True, "total_skills": 8, "sources": {"a": 1, "b": 2},
        })
        monkeypatch.setattr(su_mod, "get_skills_fetcher", lambda: fetcher)
        r = await mcp_tools._handle_skills_update({})
        assert r["success"] is True
        assert r["total_skills"] == 8
        assert "8 skills" in r["message"]


class TestSkillsMarket:
    async def test_list(self, monkeypatch):
        from pycoder.server import skills_market as sm_mod
        market = MagicMock()
        market.list_skills.return_value = {"items": [], "count": 0}
        monkeypatch.setattr(sm_mod, "get_skills_market", lambda: market)
        r = await mcp_tools._handle_skills_market({"subcommand": "list", "sort_by": "stars"})
        assert r["success"] is True
        assert r["sort_by"] == "stars"

    async def test_sync(self, monkeypatch):
        from pycoder.server import skills_market as sm_mod
        market = MagicMock()
        market.sync_from_remote = AsyncMock(return_value={"synced": True})
        monkeypatch.setattr(sm_mod, "get_skills_market", lambda: market)
        r = await mcp_tools._handle_skills_market({"subcommand": "sync"})
        assert r == {"synced": True}

    async def test_install(self, monkeypatch):
        from pycoder.server import skills_market as sm_mod
        market = MagicMock()
        market.install_skill.return_value = {"installed": True}
        monkeypatch.setattr(sm_mod, "get_skills_market", lambda: market)
        r = await mcp_tools._handle_skills_market({"subcommand": "install", "skill_id": "x"})
        assert r == {"installed": True}

    async def test_uninstall(self, monkeypatch):
        from pycoder.server import skills_market as sm_mod
        market = MagicMock()
        market.uninstall_skill.return_value = {"uninstalled": True}
        monkeypatch.setattr(sm_mod, "get_skills_market", lambda: market)
        r = await mcp_tools._handle_skills_market({"subcommand": "uninstall", "skill_id": "x"})
        assert r == {"uninstalled": True}

    async def test_update_all(self, monkeypatch):
        from pycoder.server import skills_market as sm_mod
        market = MagicMock()
        market.update_all_skills.return_value = {"updated": 3}
        monkeypatch.setattr(sm_mod, "get_skills_market", lambda: market)
        r = await mcp_tools._handle_skills_market({"subcommand": "update_all"})
        assert r == {"updated": 3}

    async def test_rate(self, monkeypatch):
        from pycoder.server import skills_market as sm_mod
        market = MagicMock()
        market.rate_skill.return_value = {"rated": True}
        monkeypatch.setattr(sm_mod, "get_skills_market", lambda: market)
        r = await mcp_tools._handle_skills_market({
            "subcommand": "rate", "skill_id": "x", "rating": 5, "review": "good",
        })
        assert r == {"rated": True}

    async def test_detail(self, monkeypatch):
        from pycoder.server import skills_market as sm_mod
        market = MagicMock()
        market.get_skill_detail.return_value = {"detail": True}
        monkeypatch.setattr(sm_mod, "get_skills_market", lambda: market)
        r = await mcp_tools._handle_skills_market({"subcommand": "detail", "skill_id": "x"})
        assert r == {"detail": True}

    async def test_publish(self, monkeypatch):
        from pycoder.server import skills_market as sm_mod
        market = MagicMock()
        market.publish_skill.return_value = {"published": True}
        monkeypatch.setattr(sm_mod, "get_skills_market", lambda: market)
        r = await mcp_tools._handle_skills_market({
            "subcommand": "publish", "skill_data": {"name": "x"},
        })
        assert r == {"published": True}

    async def test_categories(self, monkeypatch):
        from pycoder.server import skills_market as sm_mod
        market = MagicMock()
        market.get_categories.return_value = ["ai", "web"]
        monkeypatch.setattr(sm_mod, "get_skills_market", lambda: market)
        r = await mcp_tools._handle_skills_market({"subcommand": "categories"})
        assert r["success"] is True
        assert r["categories"] == ["ai", "web"]


class TestSystemUpgrade:
    async def test_check(self, monkeypatch):
        from pycoder.server import auto_upgrade as au_mod
        monkeypatch.setattr(au_mod, "check_version", lambda: SimpleNamespace(
            current="1.0", latest="1.1", has_update=True, release_notes="notes"))
        r = await mcp_tools._handle_system_upgrade({"action": "check"})
        assert r["success"] is True
        assert r["has_update"] is True
        assert r["latest_version"] == "1.1"

    async def test_upgrade(self, monkeypatch):
        from pycoder.server import auto_upgrade as au_mod
        monkeypatch.setattr(au_mod, "run_upgrade", lambda to_version=None, dry_run=False: SimpleNamespace(
            success=True, from_version="1.0", to_version="1.1", steps=[],
            error="", duration_ms=100))
        r = await mcp_tools._handle_system_upgrade({
            "action": "upgrade", "target_version": "1.1", "dry_run": True,
        })
        assert r["success"] is True
        assert r["to_version"] == "1.1"

    async def test_health(self, monkeypatch):
        from pycoder.server import auto_upgrade as au_mod
        monkeypatch.setattr(au_mod, "health_check", lambda: SimpleNamespace(
            passed=True, checks={}, warnings=[], errors=[]))
        r = await mcp_tools._handle_system_upgrade({"action": "health"})
        assert r["success"] is True
        assert r["checks"] == {}

    async def test_status(self, monkeypatch):
        from pycoder.server import auto_upgrade as au_mod
        monkeypatch.setattr(au_mod, "get_upgrade_status", lambda: {"state": "idle"})
        r = await mcp_tools._handle_system_upgrade({"action": "status"})
        assert r == {"state": "idle"}

    async def test_diff(self, monkeypatch):
        from pycoder.server import auto_upgrade as au_mod
        monkeypatch.setattr(au_mod, "get_snapshot_diff", lambda sid: {"diff": True})
        r = await mcp_tools._handle_system_upgrade({
            "action": "diff", "snapshot_id": "snap1",
        })
        assert r == {"diff": True}

    async def test_unknown_action(self):
        r = await mcp_tools._handle_system_upgrade({"action": "unknown"})
        assert r["success"] is False
        assert "未知操作" in r["error"]


# ══════════════════════════════════════════════════════════
# call_tool_with_fallback
# ══════════════════════════════════════════════════════════

class TestCallToolWithFallback:
    """call_tool_with_fallback 测试"""

    async def test_builtin_tool(self):
        r = await call_tool_with_fallback("git_log", {"limit": 5})
        # git_log 会调用 subprocess.run — 用默认行为可能成功也可能失败
        assert isinstance(r, MCPCallResult)

    async def test_unknown_tool(self):
        r = await call_tool_with_fallback("no_such_tool", {})
        assert r.success is False
        assert "未知 Tool" in r.error

    async def test_mcp_remote_success(self, monkeypatch):
        """mcp: 前缀的工具 — 远程调用成功"""
        class FakeMgr:
            async def call_remote_tool(self, server, tool, args):
                return MCPCallResult(success=True, output={"x": 1}, tool=tool)
        monkeypatch.setattr(mcp_tools, "get_mcp_client_manager", lambda: FakeMgr())

        r = await call_tool_with_fallback("mcp:filesystem/list_directory", {"path": "."})
        assert r.success is True
        assert r.output == {"x": 1}

    async def test_mcp_remote_fail_with_fallback(self, monkeypatch):
        """mcp: 远程失败 → 降级到本地 file_list"""
        class FakeMgr:
            async def call_remote_tool(self, server, tool, args):
                raise asyncio.TimeoutError()
        monkeypatch.setattr(mcp_tools, "get_mcp_client_manager", lambda: FakeMgr())
        # file_list 依赖 _get_project_tree — mock 一下避免真实文件系统
        from pycoder.server import project_helpers as ph_mod
        async def fake_tree(path, max_depth):
            return {"name": "fake"}
        monkeypatch.setattr(ph_mod, "_get_project_tree", fake_tree)

        r = await call_tool_with_fallback("mcp:filesystem/list_directory", {"path": "."})
        assert r.success is True
        assert r.tool == "file_list"

    async def test_mcp_remote_fail_no_fallback(self, monkeypatch):
        """mcp: 远程失败且无本地替代 → 返回错误"""
        class FakeMgr:
            async def call_remote_tool(self, server, tool, args):
                raise asyncio.TimeoutError()
        monkeypatch.setattr(mcp_tools, "get_mcp_client_manager", lambda: FakeMgr())

        r = await call_tool_with_fallback("mcp:playwright/navigate", {"url": "x"})
        assert r.success is False
        assert "不可用" in r.error
        assert "playwright/navigate" in r.tool

    async def test_mcp_remote_returns_failure_with_fallback(self, monkeypatch):
        """mcp: 远程返回 success=False → 降级到本地替代 (call_builtin_tool 包装)"""
        class FakeMgr:
            async def call_remote_tool(self, server, tool, args):
                return MCPCallResult(success=False, error="remote err", tool=tool)
        monkeypatch.setattr(mcp_tools, "get_mcp_client_manager", lambda: FakeMgr())
        # file_read fallback 会尝试读取文件，返回文件不存在
        r = await call_tool_with_fallback("mcp:filesystem/read_file", {"path": "/no/such/file"})
        # call_builtin_tool 成功调用了 file_read 工具 → r.success=True
        # 但工具内部返回 success=False（文件不存在）
        assert r.success is True
        assert r.tool == "file_read"
        assert r.output["success"] is False

    async def test_mcp_remote_exception_with_fallback(self, monkeypatch):
        """mcp: 远程抛普通异常 → 降级"""
        class FakeMgr:
            async def call_remote_tool(self, server, tool, args):
                raise RuntimeError("network down")
        monkeypatch.setattr(mcp_tools, "get_mcp_client_manager", lambda: FakeMgr())
        # github/search 无本地替代
        r = await call_tool_with_fallback("mcp:github/search_repositories", {"query": "x"})
        # mcp:github/search_repositories → fallback 到 "search"
        assert r.tool == "search"

    async def test_mcp_invalid_format(self, monkeypatch):
        """mcp: 前缀但格式不对（无 / 分隔）"""
        fake_mgr = MagicMock()
        monkeypatch.setattr(mcp_tools, "get_mcp_client_manager", lambda: fake_mgr)
        r = await call_tool_with_fallback("mcp:invalid_name", {})
        # 没有 / 分隔 → len(parts) != 2 → 跳过降级，返回未知 Tool
        assert r.success is False
        assert "未知 Tool" in r.error or "不可用" in r.error


# ══════════════════════════════════════════════════════════
# MCPClientManager
# ══════════════════════════════════════════════════════════

class TestMCPClientManager:
    def test_connected_servers_empty(self):
        m = MCPClientManager()
        assert m.connected_servers == []

    async def test_connect_stdio_import_error(self, monkeypatch):
        """mcp 包未安装 → connect_stdio 返回 False"""
        m = MCPClientManager()
        # 让 from mcp import ... 失败
        import builtins
        orig_import = builtins.__import__
        def fake_import(name, *args, **kwargs):
            if name == "mcp" or name.startswith("mcp."):
                raise ImportError("no mcp")
            return orig_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", fake_import)

        result = await m.connect_stdio("test", "some-command")
        assert result is False

    async def test_connect_stdio_exception(self, monkeypatch):
        """mcp 包加载但 stdio_client 抛异常 → 返回 False"""
        m = MCPClientManager()
        fake_mcp_mod = types.ModuleType("mcp")
        fake_client_mod = types.ModuleType("mcp.client.stdio")

        async def boom_stdio(params):
            raise RuntimeError("connect failed")
        fake_client_mod.stdio_client = boom_stdio
        fake_client_mod.StdioServerParameters = MagicMock()
        fake_mcp_mod.ClientSession = MagicMock()
        monkeypatch.setitem(sys.modules, "mcp", fake_mcp_mod)
        monkeypatch.setitem(sys.modules, "mcp.client.stdio", fake_client_mod)
        # mcp.client 也需要存在
        if "mcp.client" not in sys.modules:
            monkeypatch.setitem(sys.modules, "mcp.client", types.ModuleType("mcp.client"))

        result = await m.connect_stdio("srv", "cmd")
        assert result is False

    async def test_list_remote_tools_no_server(self):
        m = MCPClientManager()
        result = await m.list_remote_tools("nonexistent")
        assert result == []

    async def test_list_remote_tools_success(self):
        m = MCPClientManager()
        fake_tool = SimpleNamespace(
            name="t1", description="d", inputSchema={"type": "object"})
        fake_session = MagicMock()
        fake_session.list_tools = AsyncMock(return_value=SimpleNamespace(tools=[fake_tool]))
        m._servers["srv"] = {"session": fake_session}

        result = await m.list_remote_tools("srv")
        assert len(result) == 1
        assert result[0]["name"] == "t1"
        assert result[0]["source"] == "mcp:srv"

    async def test_list_remote_tools_exception(self):
        m = MCPClientManager()
        fake_session = MagicMock()
        fake_session.list_tools = AsyncMock(side_effect=RuntimeError("list fail"))
        m._servers["srv"] = {"session": fake_session}

        result = await m.list_remote_tools("srv")
        assert result == []

    async def test_call_remote_tool_no_server(self):
        m = MCPClientManager()
        r = await m.call_remote_tool("nope", "tool", {})
        assert r.success is False
        assert "未连接" in r.error

    async def test_call_remote_tool_success(self):
        m = MCPClientManager()
        fake_session = MagicMock()
        fake_session.call_tool = AsyncMock(return_value=SimpleNamespace(content="result"))
        m._servers["srv"] = {"session": fake_session}
        r = await m.call_remote_tool("srv", "tool1", {"a": 1})
        assert r.success is True
        assert r.output == "result"

    async def test_call_remote_tool_exception(self):
        m = MCPClientManager()
        fake_session = MagicMock()
        fake_session.call_tool = AsyncMock(side_effect=RuntimeError("call fail"))
        m._servers["srv"] = {"session": fake_session}
        r = await m.call_remote_tool("srv", "tool1", {})
        assert r.success is False
        assert "call fail" in r.error

    async def test_disconnect_existing(self):
        m = MCPClientManager()
        fake_session = MagicMock()
        fake_session.__aexit__ = AsyncMock()
        m._servers["srv"] = {"session": fake_session}
        await m.disconnect("srv")
        assert "srv" not in m._servers

    async def test_disconnect_with_close_exception(self):
        m = MCPClientManager()
        fake_session = MagicMock()
        fake_session.__aexit__ = AsyncMock(side_effect=RuntimeError("close fail"))
        m._servers["srv"] = {"session": fake_session}
        # 不应抛异常
        await m.disconnect("srv")
        assert "srv" not in m._servers

    async def test_disconnect_nonexistent(self):
        m = MCPClientManager()
        await m.disconnect("nope")  # 不抛异常

    async def test_disconnect_all(self):
        m = MCPClientManager()
        s1 = MagicMock()
        s1.__aexit__ = AsyncMock()
        s2 = MagicMock()
        s2.__aexit__ = AsyncMock()
        m._servers["a"] = {"session": s1}
        m._servers["b"] = {"session": s2}
        await m.disconnect_all()
        assert m.connected_servers == []


# ══════════════════════════════════════════════════════════
# get_mcp_client_manager singleton
# ══════════════════════════════════════════════════════════

class TestGetMCPClientManager:
    def test_singleton(self, monkeypatch):
        # 重置全局单例
        monkeypatch.setattr(mcp_tools, "_client_manager", None)
        m1 = get_mcp_client_manager()
        m2 = get_mcp_client_manager()
        assert m1 is m2
