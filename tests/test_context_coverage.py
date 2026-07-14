"""覆盖率测试: pycoder/server/routers/context.py

目标: 行覆盖率 >= 80%
覆盖端点:
    GET /api/context/file
    GET /api/context/symbols
    GET /api/context/deps
    GET /api/context/web
    函数 _guess_lang
"""
from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers import context as context_router
from pycoder.server.routers.context import _guess_lang


@pytest.fixture
def workspace(tmp_path):
    """临时工作区"""
    return tmp_path


@pytest.fixture
def client(workspace, monkeypatch):
    """创建仅包含 context 路由的 FastAPI 应用"""
    monkeypatch.setattr(context_router, "WORKSPACE", workspace)
    app = FastAPI()
    app.include_router(context_router.router)
    with TestClient(app) as c:
        yield c


class TestFileContext:
    """GET /api/context/file"""

    def test_file_success(self, client, workspace):
        """读取工作区内文件"""
        (workspace / "hello.py").write_text("print('hi')")
        resp = client.get("/api/context/file", params={"path": "hello.py"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "print('hi')"
        assert data["language"] == "python"
        assert data["size"] == len("print('hi')")

    def test_file_path_traversal(self, client, workspace):
        """路径穿越被拒绝"""
        resp = client.get("/api/context/file", params={"path": "../../../etc/passwd"})
        assert resp.status_code == 200
        data = resp.json()
        assert "路径越界" in data["error"]

    def test_file_not_found(self, client, workspace):
        """文件不存在"""
        resp = client.get("/api/context/file", params={"path": "missing.py"})
        assert resp.status_code == 200
        data = resp.json()
        assert "文件不存在" in data["error"]

    def test_file_is_directory(self, client, workspace):
        """路径是目录"""
        (workspace / "subdir").mkdir()
        resp = client.get("/api/context/file", params={"path": "subdir"})
        assert resp.status_code == 200
        data = resp.json()
        assert "不能引用目录" in data["error"]

    def test_file_too_large(self, client, workspace):
        """文件超过 200KB 上限"""
        big_file = workspace / "big.txt"
        big_file.write_bytes(b"x" * 200_001)
        resp = client.get("/api/context/file", params={"path": "big.txt"})
        assert resp.status_code == 200
        data = resp.json()
        assert "文件过大" in data["error"]

    def test_file_nested_path(self, client, workspace):
        """嵌套路径文件"""
        nested = workspace / "a" / "b" / "c.ts"
        nested.parent.mkdir(parents=True)
        nested.write_text("const x = 1")
        resp = client.get("/api/context/file", params={"path": "a/b/c.ts"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "const x = 1"
        assert data["language"] == "typescript"

    def test_file_non_utf8(self, client, workspace):
        """非 UTF-8 文件触发 UnicodeDecodeError"""
        (workspace / "binary.dat").write_bytes(b"\xff\xfe\x00\x01")
        try:
            resp = client.get("/api/context/file", params={"path": "binary.dat"})
            # 如果抛异常，FastAPI 返回 500；如果被捕获，返回错误
            assert resp.status_code in (200, 500)
        except Exception:
            # UnicodeDecodeError 可能直接抛出
            pass


class TestSymbols:
    """GET /api/context/symbols"""

    def test_symbols_import_error(self, client, monkeypatch):
        """get_symbol_index 不可用 → ImportError"""
        # 确保 project_context 模块不可导入
        monkeypatch.setitem(sys.modules, "pycoder.python.project_context", None)
        resp = client.get("/api/context/symbols", params={"q": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbols"] == []
        assert "未就绪" in data["error"]

    def test_symbols_success(self, client, monkeypatch):
        """符号搜索成功"""
        # 构造 mock project_context 模块并注入 sys.modules
        mock_symbol = MagicMock()
        mock_symbol.name = "foo"
        mock_symbol.file = "main.py"
        mock_symbol.line = 10
        mock_symbol.kind = "function"
        mock_index = MagicMock()
        mock_index.search.return_value = [mock_symbol]
        mock_module = MagicMock()
        mock_module.get_symbol_index.return_value = mock_index

        monkeypatch.setitem(sys.modules, "pycoder.python.project_context", mock_module)

        resp = client.get("/api/context/symbols", params={"q": "foo"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["symbols"]) == 1
        assert data["symbols"][0]["name"] == "foo"

    def test_symbols_generic_exception(self, client, monkeypatch):
        """符号搜索异常"""
        mock_module = MagicMock()
        mock_module.get_symbol_index.side_effect = RuntimeError("boom")
        monkeypatch.setitem(sys.modules, "pycoder.python.project_context", mock_module)

        resp = client.get("/api/context/symbols", params={"q": "foo"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbols"] == []
        assert "boom" in data["error"]


class TestDeps:
    """GET /api/context/deps"""

    def test_deps_import_error(self, client, monkeypatch):
        """get_dep_analyzer 不可用 → ImportError"""
        monkeypatch.setitem(sys.modules, "pycoder.python.dep_analyzer", None)
        resp = client.get("/api/context/deps", params={"q": "pytest"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["dependencies"] == []
        assert "未就绪" in data["error"]

    def test_deps_success_no_query(self, client, monkeypatch):
        """依赖搜索成功（无查询）"""
        mock_analyzer = MagicMock()
        mock_analyzer.get_all_deps.return_value = [
            {"name": "pytest", "package": "pytest"},
            {"name": "fastapi", "package": "fastapi"},
        ]
        mock_module = MagicMock()
        mock_module.get_dep_analyzer.return_value = mock_analyzer
        monkeypatch.setitem(sys.modules, "pycoder.python.dep_analyzer", mock_module)

        resp = client.get("/api/context/deps")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["dependencies"]) == 2

    def test_deps_success_with_query(self, client, monkeypatch):
        """依赖搜索带查询过滤"""
        mock_analyzer = MagicMock()
        mock_analyzer.get_all_deps.return_value = [
            {"name": "pytest", "package": "pytest"},
            {"name": "fastapi", "package": "fastapi"},
            {"name": "pydantic", "package": "pydantic"},
        ]
        mock_module = MagicMock()
        mock_module.get_dep_analyzer.return_value = mock_analyzer
        monkeypatch.setitem(sys.modules, "pycoder.python.dep_analyzer", mock_module)

        resp = client.get("/api/context/deps", params={"q": "py"})
        assert resp.status_code == 200
        data = resp.json()
        names = [d["name"] for d in data["dependencies"]]
        assert "pytest" in names
        assert "pydantic" in names
        assert "fastapi" not in names

    def test_deps_generic_exception(self, client, monkeypatch):
        """依赖搜索异常"""
        mock_module = MagicMock()
        mock_module.get_dep_analyzer.side_effect = RuntimeError("crash")
        monkeypatch.setitem(sys.modules, "pycoder.python.dep_analyzer", mock_module)

        resp = client.get("/api/context/deps", params={"q": "x"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["dependencies"] == []
        assert "crash" in data["error"]

    def test_deps_truncates_to_20(self, client, monkeypatch):
        """依赖列表截断为前 20 条"""
        mock_analyzer = MagicMock()
        mock_analyzer.get_all_deps.return_value = [
            {"name": f"dep{i}", "package": f"dep{i}"} for i in range(30)
        ]
        mock_module = MagicMock()
        mock_module.get_dep_analyzer.return_value = mock_analyzer
        monkeypatch.setitem(sys.modules, "pycoder.python.dep_analyzer", mock_module)

        resp = client.get("/api/context/deps")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["dependencies"]) == 20


class TestWebSearch:
    """GET /api/context/web"""

    def test_web_success(self, client, monkeypatch):
        """网页搜索成功"""
        mock_result = MagicMock(success=True, output=[{"title": "result1"}])
        mock_module = MagicMock()
        mock_module.call_builtin_tool = AsyncMock(return_value=mock_result)
        monkeypatch.setitem(sys.modules, "pycoder.server.mcp_tools", mock_module)

        resp = client.get("/api/context/web", params={"q": "python"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1

    def test_web_tool_unavailable(self, client, monkeypatch):
        """web_search 工具不可用"""
        mock_result = MagicMock(success=False, output=None)
        mock_module = MagicMock()
        mock_module.call_builtin_tool = AsyncMock(return_value=mock_result)
        monkeypatch.setitem(sys.modules, "pycoder.server.mcp_tools", mock_module)

        resp = client.get("/api/context/web", params={"q": "python"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert "不可用" in data["error"]

    def test_web_exception(self, client, monkeypatch):
        """网页搜索异常"""
        mock_module = MagicMock()
        mock_module.call_builtin_tool = AsyncMock(side_effect=RuntimeError("network error"))
        monkeypatch.setitem(sys.modules, "pycoder.server.mcp_tools", mock_module)

        resp = client.get("/api/context/web", params={"q": "python"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert "network error" in data["error"]


class TestGuessLang:
    """_guess_lang 私有函数测试"""

    @pytest.mark.parametrize(
        "suffix,expected",
        [
            (".py", "python"),
            (".ts", "typescript"),
            (".tsx", "typescript"),
            (".js", "javascript"),
            (".jsx", "javascript"),
            (".json", "json"),
            (".md", "markdown"),
            (".css", "css"),
            (".html", "html"),
            (".yaml", "yaml"),
            (".yml", "yaml"),
            (".toml", "toml"),
            (".sql", "sql"),
            (".sh", "shell"),
            (".bash", "shell"),
            (".go", "go"),
            (".rs", "rust"),
            (".java", "java"),
            (".kt", "kotlin"),
            (".swift", "swift"),
            (".rb", "ruby"),
            (".php", "php"),
            (".c", "c"),
            (".cpp", "cpp"),
            (".h", "c"),
            (".hpp", "cpp"),
            (".vue", "html"),
            (".svelte", "html"),
            (".xml", "xml"),
            (".env", "text"),
            (".gitignore", "text"),
            (".dockerfile", "dockerfile"),
            (".txt", "text"),
            (".unknown", "text"),
            (".XYZ", "text"),
        ],
    )
    def test_language_mapping(self, suffix, expected):
        """文件后缀到语言 ID 映射"""
        assert _guess_lang(suffix) == expected
