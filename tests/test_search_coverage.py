"""覆盖率测试: pycoder/server/routers/search.py

目标: 行覆盖率 >= 95%

覆盖端点:
    POST /api/search/query  — 全文搜索（空 query / 有结果 / ripgrep 引擎 / python 引擎）
    GET  /api/search        — 全文搜索 GET 版本（ripgrep / python 引擎）
    GET  /api/search/files  — 按文件名搜索

覆盖辅助函数:
    _search_with_rg  — 正常返回 / 多行解析 / 子进程异常 / 行截断
    _search_python   — 命中匹配 / file_type 过滤 / 异常分支
    _search_files    — 命中 / limit 截断

测试策略:
    - 直接调用辅助函数（绕开 API 层）
    - TestClient + monkeypatch _RG_PATH / _search_with_rg / _search_python
    - tmp_path 隔离工作区
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers import search as search_mod


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def app_client():
    """创建仅包含 search 路由的 FastAPI 应用"""
    app = FastAPI()
    app.include_router(search_mod.router)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch):
    """创建临时工作区并 monkeypatch WORKSPACE_ROOT"""
    monkeypatch.setattr(search_mod, "WORKSPACE_ROOT", tmp_path)
    return tmp_path


# ══════════════════════════════════════════════════════════
# 1. _search_with_rg 辅助函数
# ══════════════════════════════════════════════════════════


def _abs(root: Path, rel: str) -> str:
    """构造相对于 root 的绝对路径字符串（用于模拟 rg 输出）"""
    return str(root / rel)


class TestSearchWithRg:
    def test_normal_results(self, workspace):
        """ripgrep 返回标准格式 → 解析为结果列表"""
        sample_output = (
            f"{_abs(workspace, 'src/app.py')}:10:def hello():\n"
            f"{_abs(workspace, 'src/util.py')}:25:import os\n"
        )
        mock_result = MagicMock()
        mock_result.stdout = sample_output
        mock_result.returncode = 0

        with patch.object(search_mod, "_RG_PATH", "/fake/rg"), \
             patch("subprocess.run", return_value=mock_result):
            results = search_mod._search_with_rg("hello", workspace, limit=10)

        assert len(results) == 2
        assert results[0]["file"].replace("\\", "/") == "src/app.py"
        assert results[0]["line"] == 10
        assert "def hello" in results[0]["match"]

    def test_with_filters(self, workspace):
        """ripgrep 调用应传递 file_type / regex / case / whole_word 标志"""
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.returncode = 0

        with patch.object(search_mod, "_RG_PATH", "/fake/rg"), \
             patch("subprocess.run", return_value=mock_result) as mock_run:
            search_mod._search_with_rg(
                "Hello", workspace, limit=5,
                file_type=".py", regex=True,
                case_sensitive=True, whole_word=True,
            )
            cmd = mock_run.call_args[0][0]
            assert "--fixed-strings" not in cmd  # regex=True 时不加 fixed-strings
            assert "--ignore-case" not in cmd      # case_sensitive=True 时不加
            assert "--word-regexp" in cmd
            assert "--glob" in cmd

    def test_subprocess_error(self, workspace):
        """子进程异常 → 返回空列表"""
        with patch.object(search_mod, "_RG_PATH", "/fake/rg"), \
             patch("subprocess.run", side_effect=subprocess.SubprocessError("boom")):
            results = search_mod._search_with_rg("hello", workspace)
        assert results == []

    def test_oserror(self, workspace):
        """OSError → 返回空列表"""
        with patch.object(search_mod, "_RG_PATH", "/fake/rg"), \
             patch("subprocess.run", side_effect=OSError("denied")):
            results = search_mod._search_with_rg("hello", workspace)
        assert results == []

    def test_limit_truncation(self, workspace):
        """超过 limit 的结果应被截断"""
        # 生成 5 行匹配，limit=2 → 只返回 2 条
        lines = [f"{_abs(workspace, 'file.py')}:{i+1}:match{i}" for i in range(5)]
        mock_result = MagicMock()
        mock_result.stdout = "\n".join(lines) + "\n"
        mock_result.returncode = 0

        with patch.object(search_mod, "_RG_PATH", "/fake/rg"), \
             patch("subprocess.run", return_value=mock_result):
            results = search_mod._search_with_rg("match", workspace, limit=2)
        assert len(results) == 2

    def test_empty_output(self, workspace):
        """ripgrep 无输出 → 空列表"""
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.returncode = 0
        with patch.object(search_mod, "_RG_PATH", "/fake/rg"), \
             patch("subprocess.run", return_value=mock_result):
            results = search_mod._search_with_rg("nothing", workspace)
        assert results == []

    def test_malformed_line_skipped(self, workspace):
        """格式不完整的行（无 3 段分割）应被跳过"""
        # 第一行无冒号分割 → parts 长度 < 3，应被跳过
        mock_result = MagicMock()
        good_line = f"{_abs(workspace, 'file.py')}:10:match"
        mock_result.stdout = f"no_colons_here\n{good_line}\n"
        mock_result.returncode = 0
        with patch.object(search_mod, "_RG_PATH", "/fake/rg"), \
             patch("subprocess.run", return_value=mock_result):
            results = search_mod._search_with_rg("q", workspace)
        assert len(results) == 1
        assert results[0]["file"].replace("\\", "/") == "file.py"

    def test_value_error_returns_empty(self, workspace):
        """rg 输出 file_path 不在 root 下 → ValueError 被捕获，返回空列表"""
        # file_path 是绝对路径但不在 workspace 下 → relative_to 抛 ValueError
        mock_result = MagicMock()
        mock_result.stdout = "/other/root/file.py:10:match\n"
        mock_result.returncode = 0
        with patch.object(search_mod, "_RG_PATH", "/fake/rg"), \
             patch("subprocess.run", return_value=mock_result):
            results = search_mod._search_with_rg("q", workspace)
        assert results == []


# ══════════════════════════════════════════════════════════
# 2. _search_python 辅助函数
# ══════════════════════════════════════════════════════════


class TestSearchPython:
    def test_finds_match(self, workspace):
        """Python fallback 能找到匹配"""
        (workspace / "a.py").write_text("def hello():\n    pass\n", encoding="utf-8")
        (workspace / "b.txt").write_text("no match here\n", encoding="utf-8")
        results = search_mod._search_python("hello", workspace, limit=10)
        assert len(results) == 1
        assert results[0]["file"] == "a.py"
        assert results[0]["line"] == 1

    def test_file_type_filter(self, workspace):
        """file_type 过滤：只搜 .py"""
        (workspace / "a.py").write_text("foo\n", encoding="utf-8")
        (workspace / "b.txt").write_text("foo\n", encoding="utf-8")
        results = search_mod._search_python("foo", workspace, limit=10, file_type=".py")
        files = {r["file"] for r in results}
        assert "a.py" in files
        assert "b.txt" not in files

    def test_ignore_dirs(self, workspace):
        """IGNORE_DIRS 内的目录应被跳过"""
        cache = workspace / "__pycache__"
        cache.mkdir()
        (cache / "cached.py").write_text("hidden\n", encoding="utf-8")
        (workspace / "real.py").write_text("hidden\n", encoding="utf-8")
        results = search_mod._search_python("hidden", workspace, limit=10)
        files = {r["file"] for r in results}
        assert "real.py" in files
        assert "__pycache__" not in str(files)

    def test_limit_truncation(self, workspace):
        """超过 limit → 提前返回"""
        for i in range(5):
            (workspace / f"f{i}.py").write_text("query_match\n", encoding="utf-8")
        results = search_mod._search_python("query_match", workspace, limit=2)
        assert len(results) == 2

    def test_ignore_extensions(self, workspace):
        """IGNORE_EXTENSIONS 内的扩展名应被跳过"""
        (workspace / "a.pyc").write_text("query_match\n", encoding="utf-8")
        (workspace / "b.py").write_text("query_match\n", encoding="utf-8")
        results = search_mod._search_python("query_match", workspace, limit=10)
        files = {r["file"] for r in results}
        assert "b.py" in files
        assert "a.pyc" not in files

    def test_file_read_error(self, workspace, monkeypatch):
        """读取文件抛 OSError → 跳过该文件"""
        (workspace / "broken.py").write_text("query_match\n", encoding="utf-8")
        (workspace / "ok.py").write_text("query_match\n", encoding="utf-8")

        original_open = open

        def selective_open(path, *args, **kwargs):
            if "broken.py" in str(path):
                raise OSError("denied")
            return original_open(path, *args, **kwargs)
        monkeypatch.setattr("builtins.open", selective_open)

        results = search_mod._search_python("query_match", workspace, limit=10)
        files = {r["file"] for r in results}
        assert "ok.py" in files


# ══════════════════════════════════════════════════════════
# 3. _search_files 辅助函数
# ══════════════════════════════════════════════════════════


class TestSearchFiles:
    def test_matches(self, workspace):
        """glob 模式匹配文件名"""
        (workspace / "a.py").write_text("", encoding="utf-8")
        (workspace / "b.py").write_text("", encoding="utf-8")
        (workspace / "c.txt").write_text("", encoding="utf-8")
        matches = search_mod._search_files("*.py", workspace, limit=10)
        assert "a.py" in matches
        assert "b.py" in matches
        assert "c.txt" not in matches

    def test_limit_truncation(self, workspace):
        """超过 limit → 截断"""
        for i in range(5):
            (workspace / f"f{i}.py").write_text("", encoding="utf-8")
        matches = search_mod._search_files("*.py", workspace, limit=2)
        assert len(matches) == 2

    def test_ignore_dirs(self, workspace):
        """IGNORE_DIRS 中的目录应被跳过"""
        cache = workspace / "__pycache__"
        cache.mkdir()
        (cache / "cached.py").write_text("", encoding="utf-8")
        (workspace / "real.py").write_text("", encoding="utf-8")
        matches = search_mod._search_files("*.py", workspace, limit=10)
        assert "real.py" in matches
        assert all("__pycache__" not in m for m in matches)


# ══════════════════════════════════════════════════════════
# 4. POST /api/search/query 端点
# ══════════════════════════════════════════════════════════


class TestSearchCodePost:
    def test_empty_query(self, app_client):
        """空 query → 400"""
        resp = app_client.post("/api/search/query", json={"query": ""})
        assert resp.status_code == 400
        assert "Query is required" in resp.json()["detail"]

    def test_with_rg_engine(self, app_client, workspace, monkeypatch):
        """ripgrep 引擎可用时返回 ripgrep 结果"""
        fake_results = [{"file": "a.py", "line": 1, "match": "hello"}]
        monkeypatch.setattr(search_mod, "_RG_PATH", "/fake/rg")
        monkeypatch.setattr(
            search_mod, "_search_with_rg",
            lambda *a, **kw: fake_results,
        )
        resp = app_client.post("/api/search/query", json={"query": "hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["engine"] == "ripgrep"
        assert data["count"] == 1
        assert data["results"] == fake_results

    def test_with_python_engine(self, app_client, workspace, monkeypatch):
        """ripgrep 不可用时退回 Python 引擎"""
        fake_results = [{"file": "a.py", "line": 1, "match": "hello"}]
        monkeypatch.setattr(search_mod, "_RG_PATH", None)
        monkeypatch.setattr(
            search_mod, "_search_python",
            lambda *a, **kw: fake_results,
        )
        resp = app_client.post("/api/search/query", json={"query": "hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["engine"] == "python"
        assert data["count"] == 1

    def test_custom_path(self, app_client, workspace, monkeypatch, tmp_path):
        """指定 path 参数 → 使用该路径"""
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        (custom_dir / "f.py").write_text("found\n", encoding="utf-8")
        monkeypatch.setattr(search_mod, "_RG_PATH", None)

        resp = app_client.post("/api/search/query", json={
            "query": "found", "path": str(custom_dir),
        })
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1


# ══════════════════════════════════════════════════════════
# 5. GET /api/search 端点
# ══════════════════════════════════════════════════════════


class TestSearchCodeGet:
    def test_with_rg(self, app_client, workspace, monkeypatch):
        """ripgrep 引擎"""
        monkeypatch.setattr(search_mod, "_RG_PATH", "/fake/rg")
        monkeypatch.setattr(
            search_mod, "_search_with_rg",
            lambda *a, **kw: [{"file": "x.py", "line": 1, "match": "m"}],
        )
        resp = app_client.get("/api/search", params={"query": "m"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["engine"] == "ripgrep"
        assert data["count"] == 1

    def test_with_python(self, app_client, workspace, monkeypatch):
        """python 引擎"""
        monkeypatch.setattr(search_mod, "_RG_PATH", None)
        monkeypatch.setattr(
            search_mod, "_search_python",
            lambda *a, **kw: [],
        )
        resp = app_client.get("/api/search", params={"query": "m"})
        assert resp.status_code == 200
        assert resp.json()["engine"] == "python"
        assert resp.json()["count"] == 0


# ══════════════════════════════════════════════════════════
# 6. GET /api/search/files 端点
# ══════════════════════════════════════════════════════════


class TestSearchFilesEndpoint:
    def test_normal(self, app_client, workspace):
        """按文件名搜索"""
        (workspace / "alpha.py").write_text("", encoding="utf-8")
        (workspace / "beta.txt").write_text("", encoding="utf-8")
        resp = app_client.get("/api/search/files", params={"pattern": "*.py"})
        assert resp.status_code == 200
        data = resp.json()
        assert "alpha.py" in data["results"]
        assert "beta.txt" not in data["results"]
        assert data["count"] >= 1

    def test_custom_path(self, app_client, tmp_path):
        """指定 path 参数"""
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "x.md").write_text("", encoding="utf-8")
        resp = app_client.get("/api/search/files", params={
            "pattern": "*.md", "path": str(sub),
        })
        assert resp.status_code == 200
        assert resp.json()["count"] == 1
        assert "x.md" in resp.json()["results"]
