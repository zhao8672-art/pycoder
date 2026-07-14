"""覆盖率测试: pycoder/server/routers/format_api.py

目标: 行覆盖率 >= 80%
覆盖端点: POST /api/format
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers import format_api


@pytest.fixture
def client():
    """创建仅包含 format_api 路由的 FastAPI 应用"""
    app = FastAPI()
    app.include_router(format_api.router)
    with TestClient(app) as c:
        yield c


def _make_completed_process(returncode=0, stdout="", stderr=""):
    """构造 subprocess.run 返回的 CompletedProcess mock"""
    return MagicMock(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class TestFormatCode:
    """POST /api/format 端点测试"""

    def test_empty_code(self, client):
        """空 code 参数返回错误"""
        resp = client.post("/api/format", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "code 参数" in data["error"]

    def test_black_success(self, client):
        """black 格式化成功"""
        with patch.object(format_api.subprocess, "run") as mock_run:
            mock_run.return_value = _make_completed_process(returncode=0)
            resp = client.post("/api/format", json={"code": "x=1", "style": "black"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["style"] == "black"
        assert "formatted" in data

    def test_isort_success(self, client):
        """isort 格式化成功"""
        with patch.object(format_api.subprocess, "run") as mock_run:
            mock_run.return_value = _make_completed_process(returncode=0)
            resp = client.post("/api/format", json={"code": "import os\nimport sys", "style": "isort"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["style"] == "isort"

    def test_ruff_success(self, client):
        """ruff 格式化成功"""
        with patch.object(format_api.subprocess, "run") as mock_run:
            mock_run.return_value = _make_completed_process(returncode=0)
            resp = client.post("/api/format", json={"code": "x=1", "style": "ruff"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["style"] == "ruff"

    def test_default_style_falls_to_black(self, client):
        """未指定 style 默认使用 black"""
        with patch.object(format_api.subprocess, "run") as mock_run:
            mock_run.return_value = _make_completed_process(returncode=0)
            resp = client.post("/api/format", json={"code": "x=1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["style"] == "black"

    def test_format_failure_returns_original(self, client):
        """格式化失败 (returncode!=0) 返回原始代码 + warning"""
        with patch.object(format_api.subprocess, "run") as mock_run:
            mock_run.return_value = _make_completed_process(returncode=1, stderr="syntax error")
            resp = client.post("/api/format", json={"code": "bad code", "style": "black"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["formatted"] == "bad code"
        assert "warning" in data

    def test_file_not_found_error(self, client):
        """格式化工具未安装 (FileNotFoundError)"""
        with patch.object(format_api.subprocess, "run", side_effect=FileNotFoundError()):
            resp = client.post("/api/format", json={"code": "x=1", "style": "black"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["formatted"] == "x=1"
        assert "未安装" in data["warning"]

    def test_generic_exception(self, client):
        """通用异常处理"""
        with patch.object(format_api.subprocess, "run", side_effect=OSError("disk full")):
            resp = client.post("/api/format", json={"code": "x=1", "style": "isort"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["formatted"] == "x=1"
        assert "格式化异常" in data["warning"]

    def test_isort_failure_returns_original(self, client):
        """isort 失败返回原始代码"""
        with patch.object(format_api.subprocess, "run") as mock_run:
            mock_run.return_value = _make_completed_process(returncode=2, stderr="error")
            resp = client.post("/api/format", json={"code": "import os", "style": "isort"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["formatted"] == "import os"

    def test_ruff_failure_returns_original(self, client):
        """ruff 失败返回原始代码"""
        with patch.object(format_api.subprocess, "run") as mock_run:
            mock_run.return_value = _make_completed_process(returncode=1)
            resp = client.post("/api/format", json={"code": "x", "style": "ruff"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["formatted"] == "x"
