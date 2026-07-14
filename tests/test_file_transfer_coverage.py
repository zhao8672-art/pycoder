"""覆盖率测试: pycoder/server/routers/file_transfer.py

目标: 行覆盖率 >= 80%
覆盖端点:
    POST /api/file-transfer/upload
    POST /api/file-transfer/upload/batch
    GET  /api/file-transfer/download/{file_path}
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers import file_transfer


@pytest.fixture
def workspace(tmp_path):
    """临时工作区目录"""
    return tmp_path


@pytest.fixture
def client(workspace, monkeypatch):
    """创建仅包含 file_transfer 路由的 FastAPI 应用，工作区指向 tmp_path"""
    monkeypatch.setattr(
        "pycoder.server.routers.file_transfer.get_workspace_root",
        lambda: workspace,
    )
    app = FastAPI()
    app.include_router(file_transfer.router)
    with TestClient(app) as c:
        yield c


class TestUploadFile:
    """POST /api/file-transfer/upload"""

    def test_upload_success(self, client, workspace):
        """上传单个文件成功"""
        resp = client.post(
            "/api/file-transfer/upload",
            files={"file": ("test.txt", b"hello world", "text/plain")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["filename"] == "test.txt"
        assert data["size"] == 11
        assert (workspace / "test.txt").read_text() == "hello world"

    def test_upload_with_target_dir(self, client, workspace):
        """上传到指定子目录"""
        resp = client.post(
            "/api/file-transfer/upload",
            files={"file": ("doc.md", b"# Title", "text/markdown")},
            data={"target_dir": "subdir"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "doc.md"
        assert data["path"].startswith("subdir/")
        assert (workspace / "subdir" / "doc.md").read_text() == "# Title"

    def test_upload_path_traversal_rejected(self, client, workspace):
        """target_dir 路径穿越被拒绝"""
        resp = client.post(
            "/api/file-transfer/upload",
            files={"file": ("evil.txt", b"x", "text/plain")},
            data={"target_dir": "../../etc"},
        )
        assert resp.status_code == 400
        assert "路径穿越" in resp.json()["detail"]

    def test_upload_filename_traversal_sanitized(self, client, workspace):
        """filename 中的路径穿越被 basename 过滤"""
        resp = client.post(
            "/api/file-transfer/upload",
            files={"file": ("../../evil.txt", b"data", "text/plain")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "evil.txt"
        assert (workspace / "evil.txt").read_text() == "data"


class TestUploadBatch:
    """POST /api/file-transfer/upload/batch"""

    def test_batch_upload_success(self, client, workspace):
        """批量上传多个文件"""
        resp = client.post(
            "/api/file-transfer/upload/batch",
            files=[
                ("files", ("a.txt", b"aaa", "text/plain")),
                ("files", ("b.txt", b"bbb", "text/plain")),
            ],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["count"] == 2
        assert len(data["files"]) == 2
        assert (workspace / "a.txt").read_text() == "aaa"
        assert (workspace / "b.txt").read_text() == "bbb"

    def test_batch_upload_with_target_dir(self, client, workspace):
        """批量上传到指定目录"""
        resp = client.post(
            "/api/file-transfer/upload/batch",
            files=[("files", ("x.py", b"pass", "text/x-python"))],
            data={"target_dir": "project/src"},
        )
        assert resp.status_code == 200
        assert (workspace / "project" / "src" / "x.py").read_text() == "pass"

    def test_batch_upload_path_traversal(self, client, workspace):
        """批量上传路径穿越被拒绝"""
        resp = client.post(
            "/api/file-transfer/upload/batch",
            files=[("files", ("x.txt", b"x", "text/plain"))],
            data={"target_dir": "../escape"},
        )
        assert resp.status_code == 400
        assert "路径穿越" in resp.json()["detail"]


class TestDownloadFile:
    """GET /api/file-transfer/download/{file_path}"""

    def test_download_success(self, client, workspace):
        """下载已存在文件"""
        (workspace / "download.txt").write_bytes(b"file content")
        resp = client.get("/api/file-transfer/download/download.txt")
        assert resp.status_code == 200
        assert resp.content == b"file content"

    def test_download_path_traversal_rejected(self, client, workspace):
        """下载路径穿越被拒绝 — 使用工作区外的绝对路径"""
        # 使用 workspace.parent 作为工作区外的绝对路径
        escape_path = str(workspace.parent.resolve()).replace("\\", "/")
        resp = client.get(f"/api/file-transfer/download/{escape_path}")
        assert resp.status_code == 400
        assert "路径穿越" in resp.json()["detail"]

    def test_download_missing_file(self, client, workspace):
        """下载不存在的文件 → 404"""
        resp = client.get("/api/file-transfer/download/nonexistent.txt")
        assert resp.status_code == 404
        assert "文件不存在" in resp.json()["detail"]

    def test_download_directory_rejected(self, client, workspace):
        """下载目录 → 400"""
        (workspace / "mydir").mkdir()
        resp = client.get("/api/file-transfer/download/mydir")
        assert resp.status_code == 400
        assert "不能下载目录" in resp.json()["detail"]

    def test_download_nested_file(self, client, workspace):
        """下载嵌套路径中的文件"""
        nested = workspace / "a" / "b" / "c.txt"
        nested.parent.mkdir(parents=True)
        nested.write_bytes(b"nested data")
        resp = client.get("/api/file-transfer/download/a/b/c.txt")
        assert resp.status_code == 200
        assert resp.content == b"nested data"
