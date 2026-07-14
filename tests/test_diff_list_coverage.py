"""覆盖率测试: pycoder/server/routers/diff_list.py

目标: 行覆盖率 >= 80%
覆盖端点: GET /api/diff-list/list
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers import diff_list


@pytest.fixture
def client():
    """创建仅包含 diff_list 路由的 FastAPI 应用"""
    app = FastAPI()
    app.include_router(diff_list.router)
    with TestClient(app) as c:
        yield c


def _make_mock_blob(content: str):
    """构造 mock git blob，data_stream.read() 返回 bytes"""
    blob = MagicMock()
    blob.data_stream.read.return_value = content.encode("utf-8")
    return blob


def _make_diff_item(change_type, a_path="old.txt", b_path="new.txt",
                    a_content="", b_content=""):
    """构造 mock diff item"""
    item = MagicMock()
    item.change_type = change_type
    item.a_path = a_path
    item.b_path = b_path
    item.a_blob = _make_mock_blob(a_content) if a_content else None
    item.b_blob = _make_mock_blob(b_content) if b_content else None
    return item


def _make_mock_repo(diff_items=None):
    """构造 mock git.Repo"""
    repo = MagicMock()
    repo.index.diff.return_value = diff_items or []
    repo.head.commit = MagicMock()
    return repo


class TestListDiffs:
    """GET /api/diff-list/list"""

    def test_empty_diffs(self, client, monkeypatch):
        """无 diff 返回空列表"""
        mock_repo = _make_mock_repo([])
        mock_git_module = MagicMock()
        mock_git_module.Repo.return_value = mock_repo
        monkeypatch.setitem(sys.modules, "git", mock_git_module)

        resp = client.get("/api/diff-list/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["diffs"] == []

    def test_unstaged_added(self, client, monkeypatch):
        """未暂存的添加文件 (change_type A)"""
        item = _make_diff_item(
            change_type="A", b_path="new_file.py", b_content="line1\nline2\n"
        )
        mock_repo = _make_mock_repo([item])
        mock_git_module = MagicMock()
        mock_git_module.Repo.return_value = mock_repo
        monkeypatch.setitem(sys.modules, "git", mock_git_module)

        resp = client.get("/api/diff-list/list")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["diffs"]) == 1
        assert data["diffs"][0]["file"] == "new_file.py"
        assert data["diffs"][0]["status"] == "added"
        assert len(data["diffs"][0]["lines"]) == 2

    def test_unstaged_deleted(self, client, monkeypatch):
        """未暂存的删除文件 (change_type D)"""
        item = _make_diff_item(
            change_type="D", a_path="deleted.py", a_content="old line\n"
        )
        mock_repo = _make_mock_repo([item])
        mock_git_module = MagicMock()
        mock_git_module.Repo.return_value = mock_repo
        monkeypatch.setitem(sys.modules, "git", mock_git_module)

        resp = client.get("/api/diff-list/list")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["diffs"]) == 1
        assert data["diffs"][0]["file"] == "deleted.py"
        assert data["diffs"][0]["status"] == "deleted"

    def test_unstaged_modified(self, client, monkeypatch):
        """未暂存的修改文件 (change_type M)"""
        item = _make_diff_item(
            change_type="M",
            a_path="modified.py",
            b_path="modified.py",
            a_content="old line\nunchanged\n",
            b_content="new line\nunchanged\n",
        )
        mock_repo = _make_mock_repo([item])
        mock_git_module = MagicMock()
        mock_git_module.Repo.return_value = mock_repo
        monkeypatch.setitem(sys.modules, "git", mock_git_module)

        resp = client.get("/api/diff-list/list")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["diffs"]) == 1
        assert data["diffs"][0]["status"] == "modified"
        lines = data["diffs"][0]["lines"]
        types_in_diff = {l["type"] for l in lines}
        assert "add" in types_in_diff or "del" in types_in_diff

    def test_modified_with_none_blobs(self, client, monkeypatch):
        """修改文件但 a_blob/b_blob 为 None"""
        item = MagicMock()
        item.change_type = "M"
        item.a_path = "x.py"
        item.b_path = "x.py"
        item.a_blob = None
        item.b_blob = None
        mock_repo = _make_mock_repo([item])
        mock_git_module = MagicMock()
        mock_git_module.Repo.return_value = mock_repo
        monkeypatch.setitem(sys.modules, "git", mock_git_module)

        resp = client.get("/api/diff-list/list")
        assert resp.status_code == 200
        data = resp.json()
        # a_blob=None, b_blob=None → 比较空字符串
        assert len(data["diffs"]) == 1

    def test_staged_diffs(self, client, monkeypatch):
        """暂存的 diff (staged=True)"""
        item = _make_diff_item(
            change_type="A", b_path="staged_file.py", b_content="staged content\n"
        )
        mock_repo = _make_mock_repo([item])
        mock_git_module = MagicMock()
        mock_git_module.Repo.return_value = mock_repo
        monkeypatch.setitem(sys.modules, "git", mock_git_module)

        resp = client.get("/api/diff-list/list", params={"staged": True})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["diffs"]) == 1
        # 验证 staged=True 时调用 diff(repo.head.commit)
        mock_repo.index.diff.assert_called_once_with(mock_repo.head.commit)

    def test_unstaged_uses_none(self, client, monkeypatch):
        """unstaged=False 时调用 diff(None)"""
        mock_repo = _make_mock_repo([])
        mock_git_module = MagicMock()
        mock_git_module.Repo.return_value = mock_repo
        monkeypatch.setitem(sys.modules, "git", mock_git_module)

        client.get("/api/diff-list/list")
        mock_repo.index.diff.assert_called_once_with(None)

    def test_with_custom_path(self, client, monkeypatch, tmp_path):
        """指定 path 参数"""
        mock_repo = _make_mock_repo([])
        mock_git_module = MagicMock()
        mock_git_module.Repo.return_value = mock_repo
        monkeypatch.setitem(sys.modules, "git", mock_git_module)

        resp = client.get("/api/diff-list/list", params={"path": str(tmp_path)})
        assert resp.status_code == 200
        mock_git_module.Repo.assert_called_once_with(str(tmp_path))

    def test_unknown_change_type(self, client, monkeypatch):
        """未知 change_type → 不加入 diff 列表"""
        item = MagicMock()
        item.change_type = "R"  # Rename
        item.a_path = "old.py"
        item.b_path = "new.py"
        mock_repo = _make_mock_repo([item])
        mock_git_module = MagicMock()
        mock_git_module.Repo.return_value = mock_repo
        monkeypatch.setitem(sys.modules, "git", mock_git_module)

        resp = client.get("/api/diff-list/list")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["diffs"]) == 0

    def test_item_processing_exception(self, client, monkeypatch):
        """diff item 处理异常 → 跳过该 item"""
        item = MagicMock()
        item.change_type = "A"
        item.b_path = "bad.py"
        item.b_blob.data_stream.read.side_effect = AttributeError("read failed")
        mock_repo = _make_mock_repo([item])
        mock_git_module = MagicMock()
        mock_git_module.Repo.return_value = mock_repo
        monkeypatch.setitem(sys.modules, "git", mock_git_module)

        resp = client.get("/api/diff-list/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["diffs"] == []

    def test_unicode_decode_error_in_blob(self, client, monkeypatch):
        """blob 内容解码异常"""
        item = MagicMock()
        item.change_type = "A"
        item.b_path = "binary.py"
        blob = MagicMock()
        blob.data_stream.read.return_value = b"\xff\xfe\x00"
        item.b_blob = blob
        # decode("utf-8", errors="ignore") 不会抛 UnicodeDecodeError
        # 但 AttributeError 可以模拟
        item.b_blob.data_stream.read.side_effect = UnicodeDecodeError("utf-8", b"", 0, 1, "")
        mock_repo = _make_mock_repo([item])
        mock_git_module = MagicMock()
        mock_git_module.Repo.return_value = mock_repo
        monkeypatch.setitem(sys.modules, "git", mock_git_module)

        resp = client.get("/api/diff-list/list")
        assert resp.status_code == 200

    def test_git_not_installed(self, client, monkeypatch):
        """GitPython 未安装 → 500"""
        monkeypatch.setitem(sys.modules, "git", None)

        resp = client.get("/api/diff-list/list")
        assert resp.status_code == 500
        assert "GitPython not installed" in resp.json()["detail"]

    def test_generic_exception(self, client, monkeypatch):
        """通用异常 → 返回空 diffs"""
        mock_git_module = MagicMock()
        mock_git_module.Repo.side_effect = RuntimeError("git error")
        monkeypatch.setitem(sys.modules, "git", mock_git_module)

        resp = client.get("/api/diff-list/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["diffs"] == []

    def test_multiple_items_mixed(self, client, monkeypatch):
        """混合多种 change_type"""
        item_a = _make_diff_item("A", b_path="added.py", b_content="new\n")
        item_d = _make_diff_item("D", a_path="removed.py", a_content="old\n")
        item_m = _make_diff_item(
            "M", a_path="mod.py", b_path="mod.py",
            a_content="x=1\n", b_content="x=2\n",
        )
        mock_repo = _make_mock_repo([item_a, item_d, item_m])
        mock_git_module = MagicMock()
        mock_git_module.Repo.return_value = mock_repo
        monkeypatch.setitem(sys.modules, "git", mock_git_module)

        resp = client.get("/api/diff-list/list")
        assert resp.status_code == 200
        data = resp.json()
        statuses = {d["status"] for d in data["diffs"]}
        assert "added" in statuses
        assert "deleted" in statuses
        assert "modified" in statuses
