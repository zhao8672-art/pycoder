"""覆盖率测试: pycoder/server/routers/visualize.py

目标: 行覆盖率 >= 80%

覆盖内容:
    工具函数:
        _scan_structure — 递归扫描目录树（含权限错误、深度限制、空目录、
                          各种文件类型 python/doc/config/web/file、IGNORE 过滤）
        _analyze_imports — Import / ImportFrom / star import / 异常路径
        _analyze_calls   — FunctionDef / AsyncFunctionDef / Call(Name) / Call(Attribute)
    端点:
        GET  /structure — 正常 / 不存在 / 空 / 异常
        GET  /imports   — 正常 / 不存在 / 异常
        POST /calls     — 无 path / 文件不存在 / 非 .py / 正常 / 异常

测试策略:
    - 用 tmp_path 创建临时项目结构
    - monkeypatch 模块级 WORKSPACE_ROOT 到 tmp_path，使 relative_to 正常工作
    - 直接调用辅助函数 + TestClient 调用端点
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers import visualize as viz


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def app_client():
    """创建仅包含 visualize 路由的 FastAPI 应用"""
    app = FastAPI()
    app.include_router(viz.router)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch):
    """创建临时工作区并 monkeypatch WORKSPACE_ROOT"""
    monkeypatch.setattr(viz, "WORKSPACE_ROOT", tmp_path)
    return tmp_path


# ══════════════════════════════════════════════════════════
# 1. _scan_structure 工具函数
# ══════════════════════════════════════════════════════════


class TestScanStructure:
    def test_normal_structure(self, workspace):
        """正常目录树 — 含子目录与多种文件类型"""
        (workspace / "src").mkdir()
        (workspace / "src" / "app.py").write_text("# code\n", encoding="utf-8")
        (workspace / "src" / "data.json").write_text("{}", encoding="utf-8")
        (workspace / "readme.md").write_text("# R\n", encoding="utf-8")
        (workspace / "style.css").write_text("body{}\n", encoding="utf-8")
        (workspace / "config.yaml").write_text("k: v\n", encoding="utf-8")

        node = viz._scan_structure(workspace, max_depth=3)
        assert node is not None
        assert node.type == "dir"
        # 应有 src 目录与若干文件
        child_names = [c.name for c in node.children]
        assert "src" in child_names
        assert "readme.md" in child_names

    def test_file_type_classification(self, workspace):
        """各类文件应被正确分类为 python/doc/config/web"""
        (workspace / "a.py").write_text("", encoding="utf-8")
        (workspace / "b.md").write_text("", encoding="utf-8")
        (workspace / "c.txt").write_text("", encoding="utf-8")
        (workspace / "d.json").write_text("", encoding="utf-8")
        (workspace / "e.yaml").write_text("", encoding="utf-8")
        (workspace / "f.html").write_text("", encoding="utf-8")
        (workspace / "g.ts").write_text("", encoding="utf-8")
        (workspace / "h.bin").write_text("x", encoding="utf-8")  # 默认 file

        node = viz._scan_structure(workspace, max_depth=1)
        types = {c.name: c.type for c in node.children}
        assert types["a.py"] == "python"
        assert types["b.md"] == "doc"
        assert types["c.txt"] == "doc"
        assert types["d.json"] == "config"
        assert types["e.yaml"] == "config"
        assert types["f.html"] == "web"
        assert types["g.ts"] == "web"
        assert types["h.bin"] == "file"

    def test_ignore_dirs_and_exts(self, workspace):
        """IGNORE_DIRS / IGNORE_EXTS / 隐藏文件应被跳过"""
        (workspace / ".git").mkdir()
        (workspace / ".git" / "config").write_text("", encoding="utf-8")
        (workspace / "__pycache__").mkdir()
        (workspace / ".hidden").write_text("", encoding="utf-8")
        (workspace / "keep.py").write_text("", encoding="utf-8")
        (workspace / "skip.pyc").write_text("", encoding="utf-8")

        node = viz._scan_structure(workspace, max_depth=2)
        names = [c.name for c in node.children]
        assert "keep.py" in names
        assert ".git" not in names
        assert "__pycache__" not in names
        assert ".hidden" not in names
        assert "skip.pyc" not in names

    def test_depth_limit(self, workspace):
        """超过 max_depth 应返回 None"""
        # 在 workspace 顶层放一个文件，避免顶层被判为空目录
        (workspace / "top.py").write_text("", encoding="utf-8")
        deep = workspace
        for _ in range(5):
            deep = deep / "deep"
            deep.mkdir()
        (deep / "leaf.py").write_text("", encoding="utf-8")

        node = viz._scan_structure(workspace, max_depth=2)
        assert node is not None
        # 深层目录不应被扫描到
        all_names = []
        stack = [node]
        while stack:
            n = stack.pop()
            all_names.append(n.name)
            stack.extend(n.children)
        assert "leaf.py" not in all_names

    def test_empty_dir_returns_none(self, workspace):
        """空目录（无子项）应返回 None"""
        empty = workspace / "empty"
        empty.mkdir()
        node = viz._scan_structure(empty, max_depth=3)
        assert node is None

    def test_permission_error_returns_none(self, workspace, monkeypatch):
        """iterdir 抛 PermissionError 应返回 None"""
        def raise_perm(_path):
            raise PermissionError("denied")
        monkeypatch.setattr(Path, "iterdir", raise_perm)

        node = viz._scan_structure(workspace, max_depth=3)
        assert node is None

    def test_os_error_returns_none(self, workspace, monkeypatch):
        """iterdir 抛 OSError 应返回 None"""
        def raise_os(_path):
            raise OSError("io err")
        monkeypatch.setattr(Path, "iterdir", raise_os)

        node = viz._scan_structure(workspace, max_depth=3)
        assert node is None


# ══════════════════════════════════════════════════════════
# 2. _analyze_imports 工具函数
# ══════════════════════════════════════════════════════════


class TestAnalyzeImports:
    def test_plain_imports(self, workspace):
        """ast.Import 应产生边"""
        f = workspace / "mod.py"
        f.write_text(
            "import os\nimport sys, json\n",
            encoding="utf-8",
        )
        edges = viz._analyze_imports(f)
        tos = {e.to_module for e in edges}
        assert "os" in tos
        assert "sys" in tos
        assert "json" in tos
        # from_module 应为 "mod"
        for e in edges:
            assert e.from_module == "mod"

    def test_import_from(self, workspace):
        """ast.ImportFrom 应产生 module.name 边"""
        f = workspace / "pkg" / "util.py"
        f.parent.mkdir()
        f.write_text(
            "from os.path import join, dirname\n",
            encoding="utf-8",
        )
        edges = viz._analyze_imports(f)
        tos = {e.to_module for e in edges}
        assert "os.path.join" in tos
        assert "os.path.dirname" in tos

    def test_star_import(self, workspace):
        """星号导入 is_star=True"""
        f = workspace / "star.py"
        f.write_text(
            "from os import *\n",
            encoding="utf-8",
        )
        edges = viz._analyze_imports(f)
        assert len(edges) == 1
        assert edges[0].is_star is True
        assert edges[0].to_module == "os"

    def test_import_from_no_module(self, workspace):
        """ImportFrom 无 module 字段（相对导入 .x）应跳过"""
        f = workspace / "rel.py"
        f.write_text(
            "from . import sibling\n",
            encoding="utf-8",
        )
        edges = viz._analyze_imports(f)
        # node.module is None → 不产生边
        assert edges == []

    def test_syntax_error_returns_empty(self, workspace):
        f = workspace / "bad.py"
        f.write_text("def broken(:\n", encoding="utf-8")
        assert viz._analyze_imports(f) == []

    def test_unicode_error_returns_empty(self, workspace):
        f = workspace / "uni.py"
        f.write_bytes(b"\xff\xfe\x00invalid")
        assert viz._analyze_imports(f) == []

    def test_os_error_returns_empty(self, workspace, monkeypatch):
        f = workspace / "ioerr.py"
        f.write_text("import os\n", encoding="utf-8")

        def raise_os(_self, *a, **kw):
            raise OSError("io")
        monkeypatch.setattr(Path, "read_text", raise_os)

        assert viz._analyze_imports(f) == []

    def test_nested_module_path(self, workspace):
        """嵌套目录应转换为点分模块名"""
        f = workspace / "a" / "b" / "c.py"
        f.parent.mkdir(parents=True)
        f.write_text("import json\n", encoding="utf-8")
        edges = viz._analyze_imports(f)
        assert edges[0].from_module == "a.b.c"


# ══════════════════════════════════════════════════════════
# 3. _analyze_calls 工具函数
# ══════════════════════════════════════════════════════════


class TestAnalyzeCalls:
    def test_function_def_with_calls(self, workspace):
        f = workspace / "calls.py"
        f.write_text(
            "def foo():\n"
            "    print('hi')\n"
            "    bar.baz()\n"
            "\n"
            "async def af():\n"
            "    await qux()\n",
            encoding="utf-8",
        )
        funcs = viz._analyze_calls(f)
        names = {fn.name for fn in funcs}
        assert "foo" in names
        assert "af" in names
        foo = next(fn for fn in funcs if fn.name == "foo")
        # print (Name) + bar.baz (Attribute → 'baz')
        assert "print" in foo.calls
        assert "baz" in foo.calls
        af = next(fn for fn in funcs if fn.name == "af")
        assert "qux" in af.calls

    def test_no_functions(self, workspace):
        f = workspace / "nofunc.py"
        f.write_text("x = 1\ny = 2\n", encoding="utf-8")
        assert viz._analyze_calls(f) == []

    def test_syntax_error_returns_empty(self, workspace):
        f = workspace / "bad.py"
        f.write_text("def broken(:\n", encoding="utf-8")
        assert viz._analyze_calls(f) == []

    def test_unicode_error_returns_empty(self, workspace):
        f = workspace / "uni.py"
        f.write_bytes(b"\xff\xfe\x00bad")
        assert viz._analyze_calls(f) == []

    def test_os_error_returns_empty(self, workspace, monkeypatch):
        f = workspace / "ioerr.py"
        f.write_text("def f():\n    pass\n", encoding="utf-8")

        def raise_os(_self, *a, **kw):
            raise OSError("io")
        monkeypatch.setattr(Path, "read_text", raise_os)

        assert viz._analyze_calls(f) == []

    def test_call_with_subscript_func(self, workspace):
        """func 不是 Name/Attribute 时不应加入 calls"""
        f = workspace / "sub.py"
        f.write_text(
            "def f():\n"
            "    d['k']()\n",  # Subscript 调用
            encoding="utf-8",
        )
        funcs = viz._analyze_calls(f)
        assert len(funcs) == 1
        assert funcs[0].calls == []


# ══════════════════════════════════════════════════════════
# 4. GET /structure 端点
# ══════════════════════════════════════════════════════════


class TestStructureEndpoint:
    def test_default_workspace(self, app_client, workspace):
        """无 path 时使用 WORKSPACE_ROOT"""
        (workspace / "a.py").write_text("", encoding="utf-8")
        (workspace / "tests").mkdir()
        (workspace / "tests" / "test_x.py").write_text("", encoding="utf-8")

        resp = app_client.get("/structure")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["stats"]["total_dirs"] >= 1
        assert data["stats"]["python_files"] >= 1
        assert data["stats"]["test_files"] >= 1
        assert data["root"] == str(workspace)

    def test_custom_path(self, app_client, workspace):
        """指定 path 参数"""
        sub = workspace / "proj"
        sub.mkdir()
        (sub / "main.py").write_text("", encoding="utf-8")
        (sub / "config.toml").write_text("", encoding="utf-8")

        resp = app_client.get("/structure", params={"path": str(sub)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["stats"]["config_files"] >= 1

    def test_path_not_exists(self, app_client):
        """路径不存在 — 返回 success=False"""
        resp = app_client.get(
            "/structure", params={"path": "/nonexistent/path/xyz"}
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_empty_structure(self, app_client, workspace):
        """空目录树 — _scan_structure 返回 None → success=False"""
        empty = workspace / "empty"
        empty.mkdir()
        resp = app_client.get("/structure", params={"path": str(empty)})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_max_depth_param(self, app_client, workspace):
        (workspace / "a.py").write_text("", encoding="utf-8")
        resp = app_client.get("/structure", params={"max_depth": 2})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_exception_returns_false(self, app_client, workspace, monkeypatch):
        """端点内异常应返回 success=False"""
        def boom(_root, _depth=3, _cur=0):
            raise RuntimeError("boom")
        monkeypatch.setattr(viz, "_scan_structure", boom)

        resp = app_client.get("/structure")
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ══════════════════════════════════════════════════════════
# 5. GET /imports 端点
# ══════════════════════════════════════════════════════════


class TestImportsEndpoint:
    def test_default_workspace(self, app_client, workspace):
        (workspace / "m1.py").write_text(
            "import os\nfrom json import loads\n",
            encoding="utf-8",
        )
        (workspace / "m2.py").write_text(
            "from os import *\n",
            encoding="utf-8",
        )
        resp = app_client.get("/imports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["stats"]["total_edges"] >= 3
        assert data["stats"]["star_imports"] >= 1
        # modules 应包含 m1 / m2
        assert "m1" in data["modules"]
        assert "m2" in data["modules"]

    def test_ignores_cache_dirs(self, app_client, workspace):
        """__pycache__ 内的 .py 应被忽略"""
        cache = workspace / "__pycache__"
        cache.mkdir()
        (cache / "cached.py").write_text("import os\n", encoding="utf-8")
        (workspace / "real.py").write_text("import sys\n", encoding="utf-8")

        resp = app_client.get("/imports")
        data = resp.json()
        modules = data["modules"]
        assert "real" in modules
        assert "__pycache__.cached" not in modules

    def test_path_not_exists(self, app_client):
        resp = app_client.get("/imports", params={"path": "/no/such/path"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["edges"] == []
        assert data["modules"] == []

    def test_exception_returns_false(self, app_client, workspace, monkeypatch):
        def boom(_root):
            raise RuntimeError("scan boom")
        monkeypatch.setattr(viz, "_analyze_imports", boom)
        # rglob 会调用 _analyze_imports → 抛异常被外层 try/except 捕获
        (workspace / "x.py").write_text("import os\n", encoding="utf-8")
        resp = app_client.get("/imports")
        assert resp.status_code == 200
        # 外层 except 捕获异常 → success=False
        assert resp.json()["success"] is False


# ══════════════════════════════════════════════════════════
# 6. POST /calls 端点
# ══════════════════════════════════════════════════════════


class TestCallsEndpoint:
    def test_no_path(self, app_client):
        resp = app_client.post("/calls")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["functions"] == []

    def test_file_not_exists(self, app_client):
        resp = app_client.post("/calls", params={"path": "/no/such.py"})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_not_python_file(self, app_client, workspace):
        f = workspace / "data.txt"
        f.write_text("not python", encoding="utf-8")
        resp = app_client.post("/calls", params={"path": str(f)})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_normal(self, app_client, workspace):
        f = workspace / "code.py"
        f.write_text(
            "def add(a, b):\n"
            "    return a + b\n"
            "\n"
            "async def afetch():\n"
            "    return fetch('url')\n",
            encoding="utf-8",
        )
        resp = app_client.post("/calls", params={"path": str(f)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["stats"]["total_functions"] == 2
        names = {fn["name"] for fn in data["functions"]}
        assert "add" in names
        assert "afetch" in names
        assert data["stats"]["total_calls"] >= 1

    def test_exception_returns_false(self, app_client, workspace, monkeypatch):
        def boom(_f):
            raise RuntimeError("boom")
        monkeypatch.setattr(viz, "_analyze_calls", boom)
        f = workspace / "code.py"
        f.write_text("def f():\n    pass\n", encoding="utf-8")
        resp = app_client.post("/calls", params={"path": str(f)})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_empty_functions_stats(self, app_client, workspace):
        """无函数定义时 stats 各项应为 0"""
        f = workspace / "empty.py"
        f.write_text("x = 1\n", encoding="utf-8")
        resp = app_client.post("/calls", params={"path": str(f)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["stats"]["total_functions"] == 0
        assert data["stats"]["max_calls"] == 0
        assert data["stats"]["avg_calls"] == 0
