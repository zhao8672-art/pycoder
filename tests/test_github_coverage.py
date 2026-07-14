"""覆盖率测试: pycoder/server/routers/github.py

目标: 行覆盖率 >= 80%
覆盖端点:
    POST   /api/github/auth
    GET    /api/github/auth/status
    DELETE /api/github/auth
    POST   /api/github/clone
    POST   /api/github/create-repo
    POST   /api/github/publish
    GET    /api/github/repos
    GET    /api/github/repo/{owner}/{repo}
    GET    /api/github/pulls/{owner}/{repo}
    GET    /api/github/pulls/{owner}/{repo}/{number}
    POST   /api/github/pulls/{owner}/{repo}
    POST   /api/github/pulls/{owner}/{repo}/{number}/merge
    GET    /api/github/issues/{owner}/{repo}
    POST   /api/github/issues/{owner}/{repo}
    辅助函数: _load_token, _save_token, _clear_token, _gh_headers
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers import github


@pytest.fixture
def client():
    """创建仅包含 github 路由的 FastAPI 应用"""
    app = FastAPI()
    app.include_router(github.router)
    with TestClient(app) as c:
        yield c


def _make_mock_response(status_code=200, json_data=None, text=""):
    """构造 mock httpx.Response"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


def _make_mock_async_client(get_resp=None, post_resp=None, put_resp=None):
    """构造 mock httpx.AsyncClient

    使用 AsyncMock 确保 async context manager 正常工作。
    """
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    if get_resp is not None:
        client.get = AsyncMock(return_value=get_resp)
    if post_resp is not None:
        client.post = AsyncMock(return_value=post_resp)
    if put_resp is not None:
        client.put = AsyncMock(return_value=put_resp)
    return client


@pytest.fixture
def with_token(monkeypatch):
    """设置有效 token"""
    monkeypatch.setattr(github, "_load_token", lambda: "ghp_test_token")
    return "ghp_test_token"


@pytest.fixture
def no_token(monkeypatch):
    """无 token"""
    monkeypatch.setattr(github, "_load_token", lambda: "")


# ══════════════════════════════════════════════════════════
# 辅助函数测试
# ══════════════════════════════════════════════════════════


class TestHelpers:
    """辅助函数测试"""

    def test_gh_headers_with_token(self):
        """_gh_headers 带指定 token"""
        h = github._gh_headers("ghp_xxx")
        assert h["Authorization"] == "Bearer ghp_xxx"
        assert h["Accept"] == "application/vnd.github.v3+json"
        assert "User-Agent" in h

    def test_gh_headers_without_token(self, monkeypatch):
        """_gh_headers 无 token"""
        monkeypatch.setattr(github, "_load_token", lambda: "")
        h = github._gh_headers()
        assert "Authorization" not in h

    def test_load_token_from_env(self, monkeypatch):
        """从环境变量读取 token"""
        monkeypatch.setattr(github, "GITHUB_CONFIG", MagicMock(exists=lambda: False))
        monkeypatch.setenv("GITHUB_TOKEN", "env_token")
        monkeypatch.delenv("GH_TOKEN", raising=False)
        assert github._load_token() == "env_token"

    def test_load_token_from_gh_env(self, monkeypatch):
        """从 GH_TOKEN 读取 token"""
        monkeypatch.setattr(github, "GITHUB_CONFIG", MagicMock(exists=lambda: False))
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GH_TOKEN", "gh_env_token")
        assert github._load_token() == "gh_env_token"

    def test_load_token_from_file(self, monkeypatch, tmp_path):
        """从配置文件读取 token"""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"token": "file_token", "user": {}}))
        monkeypatch.setattr(github, "GITHUB_CONFIG", config_file)
        assert github._load_token() == "file_token"

    def test_load_token_file_corrupt(self, monkeypatch, tmp_path):
        """配置文件损坏"""
        config_file = tmp_path / "config.json"
        config_file.write_text("not json")
        monkeypatch.setattr(github, "GITHUB_CONFIG", config_file)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        assert github._load_token() == ""

    def test_save_token(self, monkeypatch, tmp_path):
        """保存 token"""
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(github, "GITHUB_CONFIG", config_file)
        github._save_token("new_token", {"login": "user1"})
        data = json.loads(config_file.read_text())
        assert data["token"] == "new_token"
        assert data["user"]["login"] == "user1"

    def test_clear_token_exists(self, monkeypatch, tmp_path):
        """清除 token (文件存在)"""
        config_file = tmp_path / "config.json"
        config_file.write_text("{}")
        monkeypatch.setattr(github, "GITHUB_CONFIG", config_file)
        github._clear_token()
        assert not config_file.exists()

    def test_clear_token_not_exists(self, monkeypatch, tmp_path):
        """清除 token (文件不存在)"""
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(github, "GITHUB_CONFIG", config_file)
        github._clear_token()  # 不应抛异常


# ══════════════════════════════════════════════════════════
# P0: 认证
# ══════════════════════════════════════════════════════════


class TestAuth:
    """POST /api/github/auth, GET /api/github/auth/status, DELETE /api/github/auth"""

    def test_auth_no_token(self, client):
        """缺少 token → 400"""
        resp = client.post("/api/github/auth", json={})
        assert resp.status_code == 400

    def test_auth_success(self, client, monkeypatch):
        """认证成功"""
        mock_resp = _make_mock_response(200, {
            "login": "testuser", "name": "Test", "avatar_url": "http://..."
        })
        mock_client = _make_mock_async_client(get_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))
        monkeypatch.setattr(github, "_save_token", MagicMock())

        resp = client.post("/api/github/auth", json={"token": "ghp_valid"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["user"] == "testuser"

    def test_auth_invalid_token(self, client, monkeypatch):
        """无效 token → 401"""
        mock_resp = _make_mock_response(401)
        mock_client = _make_mock_async_client(get_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/auth", json={"token": "ghp_bad"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "Invalid token"

    def test_auth_api_error(self, client, monkeypatch):
        """GitHub API 错误 (其他状态码)"""
        mock_resp = _make_mock_response(500)
        mock_client = _make_mock_async_client(get_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/auth", json={"token": "ghp_x"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "500" in data["error"]

    def test_auth_network_error(self, client, monkeypatch):
        """网络异常"""
        mock_client = _make_mock_async_client()
        mock_client.get = AsyncMock(side_effect=ConnectionError("network"))
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/auth", json={"token": "ghp_x"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "network" in data["error"]

    def test_auth_status_no_token(self, client, no_token):
        """认证状态：无 token"""
        resp = client.get("/api/github/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False

    def test_auth_status_authenticated(self, client, monkeypatch, with_token):
        """认证状态：已认证"""
        mock_resp = _make_mock_response(200, {"login": "testuser"})
        mock_client = _make_mock_async_client(get_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True

    def test_auth_status_not_authenticated(self, client, monkeypatch, with_token):
        """认证状态：token 无效"""
        mock_resp = _make_mock_response(401)
        mock_client = _make_mock_async_client(get_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False

    def test_auth_status_network_error(self, client, monkeypatch, with_token):
        """认证状态：网络错误"""
        mock_client = _make_mock_async_client()
        mock_client.get = AsyncMock(side_effect=httpx_error())
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False
        assert data["error"] == "network_error"

    def test_auth_clear(self, client, monkeypatch):
        """清除认证"""
        clear_mock = MagicMock()
        monkeypatch.setattr(github, "_clear_token", clear_mock)

        resp = client.delete("/api/github/auth")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        clear_mock.assert_called_once()


def httpx_error():
    """返回 httpx.HTTPError 实例"""
    import httpx
    return httpx.ConnectError("connection failed")


# ══════════════════════════════════════════════════════════
# P0: Clone
# ══════════════════════════════════════════════════════════


class TestClone:
    """POST /api/github/clone"""

    def test_clone_no_url(self, client):
        """缺少 url → 400"""
        resp = client.post("/api/github/clone", json={})
        assert resp.status_code == 400

    def test_clone_success(self, client, monkeypatch):
        """克隆成功"""
        result_mock = MagicMock(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(github.subprocess, "run", MagicMock(return_value=result_mock))

        resp = client.post("/api/github/clone", json={"url": "https://github.com/user/repo.git"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["repo_name"] == "repo"

    def test_clone_failure(self, client, monkeypatch):
        """克隆失败"""
        result_mock = MagicMock(returncode=1, stderr="error")
        monkeypatch.setattr(github.subprocess, "run", MagicMock(return_value=result_mock))

        resp = client.post("/api/github/clone", json={"url": "user/repo"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "error"

    def test_clone_timeout(self, client, monkeypatch):
        """克隆超时"""
        import subprocess as sp
        monkeypatch.setattr(
            github.subprocess, "run",
            MagicMock(side_effect=sp.TimeoutExpired(cmd="git", timeout=120)),
        )

        resp = client.post("/api/github/clone", json={"url": "user/repo"})
        assert resp.status_code == 200
        data = resp.json()
        assert "timeout" in data["error"].lower()

    def test_clone_exception(self, client, monkeypatch):
        """克隆异常"""
        monkeypatch.setattr(
            github.subprocess, "run",
            MagicMock(side_effect=RuntimeError("unexpected")),
        )

        resp = client.post("/api/github/clone", json={"url": "user/repo"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    def test_clone_short_url_expansion(self, client, monkeypatch):
        """短 URL 展开 (user/repo)"""
        result_mock = MagicMock(returncode=0)
        run_mock = MagicMock(return_value=result_mock)
        monkeypatch.setattr(github.subprocess, "run", run_mock)

        resp = client.post("/api/github/clone", json={"url": "user/repo"})
        assert resp.status_code == 200
        args = run_mock.call_args[0][0]
        assert "https://github.com/user/repo.git" in args[2]

    def test_clone_with_target_dir(self, client, monkeypatch):
        """指定目标目录"""
        result_mock = MagicMock(returncode=0)
        run_mock = MagicMock(return_value=result_mock)
        monkeypatch.setattr(github.subprocess, "run", run_mock)

        resp = client.post("/api/github/clone", json={
            "url": "https://github.com/user/repo.git",
            "target_dir": "/tmp/custom",
        })
        assert resp.status_code == 200
        args = run_mock.call_args[0][0]
        assert args[3] == "/tmp/custom"


# ══════════════════════════════════════════════════════════
# P0: Create Repo
# ══════════════════════════════════════════════════════════


class TestCreateRepo:
    """POST /api/github/create-repo"""

    def test_create_repo_no_token(self, client, no_token):
        """无 token → 401"""
        resp = client.post("/api/github/create-repo", json={"name": "test"})
        assert resp.status_code == 401

    def test_create_repo_no_name(self, client, with_token):
        """无 name → 400"""
        resp = client.post("/api/github/create-repo", json={})
        assert resp.status_code == 400

    def test_create_repo_success(self, client, monkeypatch, with_token):
        """创建成功"""
        mock_resp = _make_mock_response(201, {
            "html_url": "https://github.com/user/test",
            "clone_url": "https://github.com/user/test.git",
            "name": "test",
            "full_name": "user/test",
        })
        mock_client = _make_mock_async_client(post_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/create-repo", json={
            "name": "test", "description": "desc", "private": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["url"] == "https://github.com/user/test"

    def test_create_repo_already_exists(self, client, monkeypatch, with_token):
        """仓库已存在 (422)"""
        mock_resp = _make_mock_response(422)
        mock_client = _make_mock_async_client(post_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/create-repo", json={"name": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "already exist" in data["error"]

    def test_create_repo_api_error(self, client, monkeypatch, with_token):
        """API 错误"""
        mock_resp = _make_mock_response(500, text="server error")
        mock_client = _make_mock_async_client(post_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/create-repo", json={"name": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    def test_create_repo_network_error(self, client, monkeypatch, with_token):
        """网络错误"""
        mock_client = _make_mock_async_client()
        mock_client.post = AsyncMock(side_effect=ConnectionError("network"))
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/create-repo", json={"name": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False


# ══════════════════════════════════════════════════════════
# P0: Publish
# ══════════════════════════════════════════════════════════


class TestPublish:
    """POST /api/github/publish"""

    def test_publish_no_token(self, client, no_token):
        """无 token → 401"""
        resp = client.post("/api/github/publish", json={"repo_name": "test"})
        assert resp.status_code == 401

    def test_publish_success(self, client, monkeypatch, with_token, tmp_path):
        """发布成功"""
        monkeypatch.setattr(github, "WORKSPACE_ROOT", tmp_path)
        mock_resp = _make_mock_response(201, {
            "clone_url": "https://github.com/user/test.git",
            "html_url": "https://github.com/user/test",
            "full_name": "user/test",
        })
        mock_client = _make_mock_async_client(post_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))
        # git init 不存在 .git 目录
        run_mock = MagicMock(return_value=MagicMock(returncode=0, stderr=""))
        monkeypatch.setattr(github.subprocess, "run", run_mock)

        resp = client.post("/api/github/publish", json={"repo_name": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["repo_name"] == "test"

    def test_publish_repo_exists(self, client, monkeypatch, with_token, tmp_path):
        """仓库已存在 (422)"""
        monkeypatch.setattr(github, "WORKSPACE_ROOT", tmp_path)
        mock_resp = _make_mock_response(422)
        mock_client = _make_mock_async_client(post_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/publish", json={"repo_name": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "exists" in data["error"]

    def test_publish_api_error(self, client, monkeypatch, with_token, tmp_path):
        """API 错误"""
        monkeypatch.setattr(github, "WORKSPACE_ROOT", tmp_path)
        mock_resp = _make_mock_response(500)
        mock_client = _make_mock_async_client(post_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/publish", json={"repo_name": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    def test_publish_with_org(self, client, monkeypatch, with_token, tmp_path):
        """发布到组织"""
        monkeypatch.setattr(github, "WORKSPACE_ROOT", tmp_path)
        mock_resp = _make_mock_response(201, {
            "clone_url": "https://github.com/org/test.git",
            "html_url": "https://github.com/org/test",
            "full_name": "org/test",
        })
        mock_client = _make_mock_async_client(post_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))
        run_mock = MagicMock(return_value=MagicMock(returncode=0, stderr=""))
        monkeypatch.setattr(github.subprocess, "run", run_mock)

        resp = client.post("/api/github/publish", json={
            "repo_name": "test", "org": "myorg",
        })
        assert resp.status_code == 200
        # 验证 API URL 包含 org
        post_call = mock_client.post.call_args
        assert "orgs/myorg/repos" in str(post_call[0][0])

    def test_publish_no_repo_name(self, client, monkeypatch, with_token, tmp_path):
        """无 repo_name → 使用工作区名"""
        monkeypatch.setattr(github, "WORKSPACE_ROOT", tmp_path)
        mock_resp = _make_mock_response(201, {
            "clone_url": "https://github.com/user/x.git",
            "html_url": "https://github.com/user/x",
            "full_name": "user/x",
        })
        mock_client = _make_mock_async_client(post_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))
        run_mock = MagicMock(return_value=MagicMock(returncode=0, stderr=""))
        monkeypatch.setattr(github.subprocess, "run", run_mock)

        resp = client.post("/api/github/publish", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["repo_name"] == tmp_path.name

    def test_publish_push_failure(self, client, monkeypatch, with_token, tmp_path):
        """push 失败但仓库已创建"""
        monkeypatch.setattr(github, "WORKSPACE_ROOT", tmp_path)
        mock_resp = _make_mock_response(201, {
            "clone_url": "https://github.com/user/test.git",
            "html_url": "https://github.com/user/test",
            "full_name": "user/test",
        })
        mock_client = _make_mock_async_client(post_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))
        # git remote add 成功, checkout 成功, push 失败
        push_fail = MagicMock(returncode=1, stderr="push error")
        run_mock = MagicMock(return_value=push_fail)
        monkeypatch.setattr(github.subprocess, "run", run_mock)

        resp = client.post("/api/github/publish", json={"repo_name": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "warning" in data

    def test_publish_api_exception(self, client, monkeypatch, with_token, tmp_path):
        """GitHub API 异常"""
        monkeypatch.setattr(github, "WORKSPACE_ROOT", tmp_path)
        mock_client = _make_mock_async_client()
        mock_client.post = AsyncMock(side_effect=RuntimeError("api crash"))
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/publish", json={"repo_name": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "api crash" in data["error"]


# ══════════════════════════════════════════════════════════
# P1: Repos
# ══════════════════════════════════════════════════════════


class TestRepos:
    """GET /api/github/repos, GET /api/github/repo/{owner}/{repo}"""

    def test_list_repos_no_token(self, client, no_token):
        """无 token → 401"""
        resp = client.get("/api/github/repos")
        assert resp.status_code == 401

    def test_list_repos_success(self, client, monkeypatch, with_token):
        """列表成功"""
        mock_resp = _make_mock_response(200, [
            {
                "id": 1, "name": "repo1", "full_name": "user/repo1",
                "description": "desc", "private": False,
                "html_url": "https://github.com/user/repo1",
                "clone_url": "https://github.com/user/repo1.git",
                "language": "Python", "stargazers_count": 10,
                "forks_count": 2, "open_issues_count": 1,
                "updated_at": "2024-01-01", "default_branch": "main",
            },
        ])
        mock_client = _make_mock_async_client(get_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/repos")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["repos"]) == 1
        assert data["repos"][0]["name"] == "repo1"

    def test_list_repos_api_error(self, client, monkeypatch, with_token):
        """API 错误"""
        mock_resp = _make_mock_response(403)
        mock_client = _make_mock_async_client(get_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/repos")
        assert resp.status_code == 200
        data = resp.json()
        assert data["repos"] == []
        assert "error" in data

    def test_list_repos_exception(self, client, monkeypatch, with_token):
        """异常"""
        mock_client = _make_mock_async_client()
        mock_client.get = AsyncMock(side_effect=RuntimeError("boom"))
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/repos")
        assert resp.status_code == 200
        data = resp.json()
        assert data["repos"] == []

    def test_repo_detail_success(self, client, monkeypatch):
        """仓库详情成功"""
        mock_resp = _make_mock_response(200, {
            "full_name": "user/repo", "description": "desc",
            "private": False, "html_url": "https://github.com/user/repo",
            "language": "Python", "stargazers_count": 5,
            "forks_count": 1, "open_issues_count": 0,
            "default_branch": "main", "updated_at": "2024-01-01",
        })
        mock_client = _make_mock_async_client(get_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/repo/user/repo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["repo"]["full_name"] == "user/repo"

    def test_repo_detail_api_error(self, client, monkeypatch):
        """仓库详情 API 错误"""
        mock_resp = _make_mock_response(404)
        mock_client = _make_mock_async_client(get_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/repo/user/repo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    def test_repo_detail_exception(self, client, monkeypatch):
        """仓库详情异常"""
        mock_client = _make_mock_async_client()
        mock_client.get = AsyncMock(side_effect=RuntimeError("err"))
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/repo/user/repo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False


# ══════════════════════════════════════════════════════════
# P1: Pull Requests
# ══════════════════════════════════════════════════════════


class TestPulls:
    """PR 相关端点"""

    def test_list_prs_success(self, client, monkeypatch):
        """PR 列表成功"""
        mock_resp = _make_mock_response(200, [
            {
                "number": 1, "title": "PR 1", "state": "open",
                "user": {"login": "user1"}, "created_at": "2024-01-01",
                "html_url": "https://github.com/user/repo/pull/1",
                "head": {"ref": "feature"}, "base": {"ref": "main"},
                "mergeable": True, "draft": False,
            },
        ])
        mock_client = _make_mock_async_client(get_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/pulls/user/repo")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["pulls"]) == 1
        assert data["pulls"][0]["number"] == 1

    def test_list_prs_api_error(self, client, monkeypatch):
        """PR 列表 API 错误"""
        mock_resp = _make_mock_response(403)
        mock_client = _make_mock_async_client(get_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/pulls/user/repo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pulls"] == []

    def test_list_prs_exception(self, client, monkeypatch):
        """PR 列表异常"""
        mock_client = _make_mock_async_client()
        mock_client.get = AsyncMock(side_effect=RuntimeError("err"))
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/pulls/user/repo")
        assert resp.status_code == 200
        assert resp.json()["pulls"] == []

    def test_pr_detail_success(self, client, monkeypatch):
        """PR 详情成功"""
        mock_resp = _make_mock_response(200, {
            "number": 1, "title": "PR 1", "body": "body",
            "state": "open", "user": {"login": "user1"},
            "created_at": "2024-01-01",
            "html_url": "https://github.com/user/repo/pull/1",
            "head": {"ref": "feature", "repo": {"full_name": "user/repo"}},
            "base": {"ref": "main", "repo": {"full_name": "user/repo"}},
            "mergeable": True, "merged": False,
            "commits": 1, "changed_files": 2,
            "additions": 10, "deletions": 5,
        })
        mock_client = _make_mock_async_client(get_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/pulls/user/repo/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["pull"]["number"] == 1

    def test_pr_detail_no_repo(self, client, monkeypatch):
        """PR 详情 head.repo 为 None"""
        mock_resp = _make_mock_response(200, {
            "number": 1, "title": "PR", "body": "",
            "state": "open", "user": {"login": "u"},
            "created_at": "", "html_url": "",
            "head": {"ref": "f", "repo": None},
            "base": {"ref": "m", "repo": None},
        })
        mock_client = _make_mock_async_client(get_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/pulls/user/repo/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_pr_detail_api_error(self, client, monkeypatch):
        """PR 详情 API 错误"""
        mock_resp = _make_mock_response(404)
        mock_client = _make_mock_async_client(get_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/pulls/user/repo/999")
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_pr_detail_exception(self, client, monkeypatch):
        """PR 详情异常"""
        mock_client = _make_mock_async_client()
        mock_client.get = AsyncMock(side_effect=RuntimeError("e"))
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/pulls/user/repo/1")
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_create_pr_no_token(self, client, no_token):
        """创建 PR 无 token → 401"""
        resp = client.post("/api/github/pulls/user/repo", json={"title": "T", "head": "f"})
        assert resp.status_code == 401

    def test_create_pr_missing_fields(self, client, with_token):
        """创建 PR 缺少 title/head → 400"""
        resp = client.post("/api/github/pulls/user/repo", json={"title": "", "head": ""})
        assert resp.status_code == 400

    def test_create_pr_success(self, client, monkeypatch, with_token):
        """创建 PR 成功"""
        mock_resp = _make_mock_response(201, {
            "number": 42, "html_url": "https://github.com/user/repo/pull/42",
        })
        mock_client = _make_mock_async_client(post_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/pulls/user/repo", json={
            "title": "New PR", "head": "feature", "base": "main",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["number"] == 42

    def test_create_pr_api_error(self, client, monkeypatch, with_token):
        """创建 PR API 错误"""
        mock_resp = _make_mock_response(422, text="bad")
        mock_client = _make_mock_async_client(post_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/pulls/user/repo", json={
            "title": "T", "head": "f",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_create_pr_exception(self, client, monkeypatch, with_token):
        """创建 PR 异常"""
        mock_client = _make_mock_async_client()
        mock_client.post = AsyncMock(side_effect=RuntimeError("e"))
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/pulls/user/repo", json={
            "title": "T", "head": "f",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_merge_pr_no_token(self, client, no_token):
        """合并 PR 无 token → 401"""
        resp = client.post("/api/github/pulls/user/repo/1/merge", json={})
        assert resp.status_code == 401

    def test_merge_pr_success(self, client, monkeypatch, with_token):
        """合并 PR 成功"""
        mock_resp = _make_mock_response(200, {"merged": True})
        mock_client = _make_mock_async_client(put_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/pulls/user/repo/1/merge", json={
            "merge_method": "squash",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["merged"] is True

    def test_merge_pr_api_error(self, client, monkeypatch, with_token):
        """合并 PR API 错误"""
        mock_resp = _make_mock_response(409, text="conflict")
        mock_client = _make_mock_async_client(put_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/pulls/user/repo/1/merge", json={})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_merge_pr_exception(self, client, monkeypatch, with_token):
        """合并 PR 异常"""
        mock_client = _make_mock_async_client()
        mock_client.put = AsyncMock(side_effect=RuntimeError("e"))
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/pulls/user/repo/1/merge", json={})
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ══════════════════════════════════════════════════════════
# P2: Issues
# ══════════════════════════════════════════════════════════


class TestIssues:
    """Issue 相关端点"""

    def test_list_issues_success(self, client, monkeypatch):
        """Issue 列表成功"""
        mock_resp = _make_mock_response(200, [
            {
                "number": 1, "title": "Bug", "state": "open",
                "user": {"login": "user1"}, "created_at": "2024-01-01",
                "html_url": "https://github.com/user/repo/issues/1",
                "comments": 3,
                "labels": [{"name": "bug", "color": "ff0000"}],
            },
            # 带 pull_request 的应该被过滤
            {
                "number": 2, "title": "PR", "state": "open",
                "user": {"login": "u2"}, "created_at": "",
                "html_url": "", "comments": 0, "labels": [],
                "pull_request": {"url": "..."},
            },
        ])
        mock_client = _make_mock_async_client(get_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/issues/user/repo")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["issues"]) == 1
        assert data["issues"][0]["number"] == 1

    def test_list_issues_with_labels(self, client, monkeypatch):
        """带 labels 参数"""
        mock_resp = _make_mock_response(200, [])
        mock_client = _make_mock_async_client(get_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/issues/user/repo", params={
            "labels": "bug,enhancement", "state": "closed",
        })
        assert resp.status_code == 200
        get_call = mock_client.get.call_args
        assert get_call.kwargs["params"]["labels"] == "bug,enhancement"

    def test_list_issues_api_error(self, client, monkeypatch):
        """Issue 列表 API 错误"""
        mock_resp = _make_mock_response(403)
        mock_client = _make_mock_async_client(get_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/issues/user/repo")
        assert resp.status_code == 200
        assert resp.json()["issues"] == []

    def test_list_issues_exception(self, client, monkeypatch):
        """Issue 列表异常"""
        mock_client = _make_mock_async_client()
        mock_client.get = AsyncMock(side_effect=RuntimeError("e"))
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.get("/api/github/issues/user/repo")
        assert resp.status_code == 200
        assert resp.json()["issues"] == []

    def test_create_issue_no_token(self, client, no_token):
        """创建 Issue 无 token → 401"""
        resp = client.post("/api/github/issues/user/repo", json={"title": "T"})
        assert resp.status_code == 401

    def test_create_issue_no_title(self, client, with_token):
        """创建 Issue 无 title → 400"""
        resp = client.post("/api/github/issues/user/repo", json={"title": ""})
        assert resp.status_code == 400

    def test_create_issue_success(self, client, monkeypatch, with_token):
        """创建 Issue 成功"""
        mock_resp = _make_mock_response(201, {
            "number": 5, "html_url": "https://github.com/user/repo/issues/5",
        })
        mock_client = _make_mock_async_client(post_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/issues/user/repo", json={
            "title": "Bug report", "body": "desc", "labels": ["bug"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["number"] == 5

    def test_create_issue_api_error(self, client, monkeypatch, with_token):
        """创建 Issue API 错误"""
        mock_resp = _make_mock_response(403, text="forbidden")
        mock_client = _make_mock_async_client(post_resp=mock_resp)
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/issues/user/repo", json={"title": "T"})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_create_issue_exception(self, client, monkeypatch, with_token):
        """创建 Issue 异常"""
        mock_client = _make_mock_async_client()
        mock_client.post = AsyncMock(side_effect=RuntimeError("e"))
        monkeypatch.setattr(github.httpx, "AsyncClient", MagicMock(return_value=mock_client))

        resp = client.post("/api/github/issues/user/repo", json={"title": "T"})
        assert resp.status_code == 200
        assert resp.json()["success"] is False
