"""覆盖率测试: pycoder/server/routers/git.py

目标: 行覆盖率 >= 80%

覆盖所有端点（Pydantic 模型已重构）:
    GET  /api/git/status                    GET  /api/git/log
    POST /api/git/commit                    POST /api/git/commit/generate-message
    GET  /api/git/branches                  POST /api/git/branch/create
    POST /api/git/branch/switch             POST /api/git/branch/merge
    POST /api/git/push                      POST /api/git/pull
    POST /api/git/stash                     GET  /api/git/diff
    GET  /api/git/blame                     POST /api/git/stage
    POST /api/git/unstage                   POST /api/git/discard
    POST /api/git/stash/detail              POST /api/git/stash/apply
    POST /api/git/branch/delete             GET  /api/git/file-history
    GET  /api/git/compare                   GET  /api/git/tags
    POST /api/git/tag/create                POST /api/git/tag/delete
    POST /api/git/fetch                     POST /api/git/reset
    POST /api/git/revert                    POST /api/git/cherry-pick
    POST /api/git/rebase                    GET  /api/git/remotes
    POST /api/git/remote/add                POST /api/git/remote/remove
    GET  /api/git/conflicts                 POST /api/git/resolve-conflict
    POST /api/git/ignore                    POST /api/git/init
    GET  /api/git/init                      _generate_commit_message

测试策略:
    - 注入 sys.modules["git"] 为 MagicMock，使 `from git import Repo` 在函数内成功
    - mock pycoder.server.routers.git._ws 返回 tmp_path
    - 用 TestClient 调用端点；Pydantic 模型用 JSON body 发送
    - _run_git 内部用 asyncio.to_thread — mock 的同步方法可直接被 to_thread 调用
"""
from __future__ import annotations

import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers import git as git_mod


# ══════════════════════════════════════════════════════════
# Fake git 模块 — 模拟 GitPython
# ══════════════════════════════════════════════════════════


class FakeDiffItem:
    """模拟 git diff item"""

    def __init__(self, a_path="f.py", change_type="M"):
        self.a_path = a_path
        self.change_type = change_type


class FakeCommit:
    """模拟 git Commit"""

    def __init__(self, hexsha="abc1234", message="feat: init\n", author_name="Dev"):
        self.hexsha = hexsha
        self.message = message
        self.author = MagicMock(name=author_name)
        self.author.name = author_name
        self.committed_datetime = datetime(2025, 1, 1)
        self.stats = MagicMock()
        self.stats.files = {"f.py": {}}


class FakeBranch:
    def __init__(self, name, is_active=False):
        self.name = name
        self._is_active = is_active

    def checkout(self):
        return None

    def tracking_branch(self):
        if self._is_active:
            tb = MagicMock()
            tb.name = "origin/main"
            return tb
        return None


class _NamedContainer:
    """支持迭代与字符串索引的容器（模拟 GitPython 的 HeadList/RemoteList）"""

    def __init__(self, items):
        self._items = list(items)
        self._by_name = {it.name: it for it in self._items}

    def __iter__(self):
        return iter(self._items)

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._by_name[key]
        return self._items[key]

    def __len__(self):
        return len(self._items)


class FakeIndex:
    def __init__(self):
        self.diff = self._diff
        self.unmerged_blobs = self._unmerged_blobs
        self.add = MagicMock(return_value=None)

    def _diff(self, ref=None):
        if ref == "HEAD":
            return [FakeDiffItem("staged.py", "M")]
        return [FakeDiffItem("unstaged.py", "M")]

    def _unmerged_blobs(self):
        return {}

    def commit(self, msg, author=None, committer=None):
        return FakeCommit(hexsha="commit123", message=msg)


class FakeRemote:
    def __init__(self, name="origin", url="git@github.com:x/y.git"):
        self.name = name
        self.url = url
        self.urls = [url]
        self.fetch = MagicMock(return_value=[])


class FakeGitCmd:
    """模拟 repo.git（push/pull/merge/stash/diff/blame 等）"""

    def __init__(self):
        self.push = MagicMock(return_value="pushed")
        self.pull = MagicMock(return_value="pulled")
        self.merge = MagicMock(return_value="merged")
        self.stash = MagicMock(return_value="stash@{0}: WIP")
        self.diff = MagicMock(return_value="diff content")
        self.blame = MagicMock(return_value="line1\nline2")
        self.checkout = MagicMock(return_value="")
        self.revert = MagicMock(return_value="reverted")
        self.cherry_pick = MagicMock(return_value="picked")
        self.rebase = MagicMock(return_value="rebased")
        self.status = MagicMock(return_value="UU conflict.py")


class FakeRepo:
    """模拟 git.Repo"""

    def __init__(self, path="."):
        self.working_tree_dir = path
        self.active_branch = FakeBranch("main", is_active=True)
        self.branches = _NamedContainer(
            [FakeBranch("main", is_active=True), FakeBranch("dev")]
        )
        self.index = FakeIndex()
        self.remotes = _NamedContainer([FakeRemote()])
        self.untracked_files = ["new.py"]
        self.git = FakeGitCmd()
        self.head = MagicMock()
        self.head.reset = MagicMock(return_value=None)

    @classmethod
    def init(cls, path="."):
        return cls(path)

    def create_head(self, name):
        return FakeBranch(name)

    def delete_head(self, name, force=False):
        return None

    def create_tag(self, name, message=None):
        tag = MagicMock()
        tag.name = name
        tag.commit = FakeCommit(hexsha="tag1234")
        tag.tag = MagicMock()
        tag.tag.message = message or ""
        return tag

    def delete_tag(self, name):
        return None

    def create_remote(self, name, url):
        return FakeRemote(name, url)

    def delete_remote(self, remote):
        return None

    def iter_commits(self, max_count=None, paths=None):
        yield FakeCommit()
        yield FakeCommit(hexsha="def5678", message="fix: bug\n")

    @property
    def tags(self):
        t = MagicMock()
        t.name = "v1.0"
        t.commit = FakeCommit(hexsha="tag1234")
        t.tag = MagicMock()
        t.tag.message = "release v1.0"
        return [t]


def _install_fake_git(monkeypatch):
    """注入 fake git 模块到 sys.modules"""
    fake_git = types.ModuleType("git")
    fake_git.Repo = FakeRepo
    fake_git.Actor = MagicMock(return_value=MagicMock(name="actor"))
    fake_git.TagReference = MagicMock
    monkeypatch.setitem(sys.modules, "git", fake_git)
    return fake_git


def _remove_git_module(monkeypatch):
    """移除 git 模块以模拟 ImportError — 设为 None 使 `from git import X` 失败"""
    monkeypatch.setitem(sys.modules, "git", None)


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def fake_git(monkeypatch):
    """注入 fake git 模块"""
    return _install_fake_git(monkeypatch)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch):
    """mock _ws() 返回 tmp_path"""
    monkeypatch.setattr(git_mod, "_ws", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def client(fake_git, workspace):
    """创建仅包含 git 路由的 FastAPI 应用"""
    app = FastAPI()
    app.include_router(git_mod.router)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def no_git_client(workspace, monkeypatch):
    """git 模块不可用（ImportError）"""
    _remove_git_module(monkeypatch)
    app = FastAPI()
    app.include_router(git_mod.router)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ══════════════════════════════════════════════════════════
# 1. status / log
# ══════════════════════════════════════════════════════════


class TestStatusLog:
    def test_status_success(self, client):
        resp = client.get("/api/git/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_git_repo"] is True
        assert data["branch"] == "main"
        assert data["has_remote"] is True
        assert data["staged_count"] >= 1
        assert data["unstaged_count"] >= 1

    def test_status_with_path(self, client, tmp_path):
        resp = client.get("/api/git/status", params={"path": str(tmp_path)})
        assert resp.status_code == 200
        assert resp.json()["is_git_repo"] is True

    def test_status_tracking_branch_lookup(self, client, monkeypatch):
        """active_branch.tracking_branch() 抛 ValueError 应进入 except"""
        # 通过 patch FakeRepo 的实例行为测试
        orig_init = FakeRepo.__init__

        def patched_init(self, path="."):
            orig_init(self, path)
            # 让 tracking_branch 抛 TypeError
            bad_branch = MagicMock()
            bad_branch.name = "main"
            bad_branch.tracking_branch.side_effect = TypeError("no tracking")
            self.active_branch = bad_branch

        monkeypatch.setattr(FakeRepo, "__init__", patched_init)
        resp = client.get("/api/git/status")
        assert resp.status_code == 200
        # 仍应正常返回（ahead/behind=0）
        assert resp.json()["ahead"] == 0

    def test_status_import_error(self, no_git_client):
        resp = no_git_client.get("/api/git/status")
        assert resp.status_code == 500

    def test_status_generic_exception(self, client, monkeypatch):
        """Repo() 抛一般异常 → 返回 is_git_repo=False"""
        def boom(path):
            raise RuntimeError("not a repo")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.get("/api/git/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_git_repo"] is False
        assert "error" in data

    def test_log_success(self, client):
        resp = client.get("/api/git/log")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["commits"]) >= 1

    def test_log_with_limit(self, client):
        resp = client.get("/api/git/log", params={"limit": 1})
        assert resp.status_code == 200

    def test_log_import_error(self, no_git_client):
        resp = no_git_client.get("/api/git/log")
        assert resp.status_code == 500

    def test_log_generic_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.get("/api/git/log")
        assert resp.status_code == 200
        assert resp.json()["commits"] == []


# ══════════════════════════════════════════════════════════
# 2. commit / generate-message
# ══════════════════════════════════════════════════════════


class TestCommit:
    def test_commit_with_files(self, client):
        resp = client.post(
            "/api/git/commit",
            json={"files": ["a.py"], "message": "test msg"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["message"] == "test msg"

    def test_commit_no_files_uses_add_all(self, client):
        resp = client.post("/api/git/commit", json={"message": "auto"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["files_count"] == -1

    def test_commit_auto_message(self, client):
        """无 message 时调用 _generate_commit_message"""
        resp = client.post("/api/git/commit", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "AI-assisted" in data["message"]

    def test_commit_with_author(self, client):
        resp = client.post(
            "/api/git/commit",
            json={"message": "x", "author": "Custom Author"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_commit_import_error(self, no_git_client):
        resp = no_git_client.post("/api/git/commit", json={"message": "x"})
        assert resp.status_code == 500

    def test_commit_generic_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("commit fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/commit", json={"message": "x"})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_generate_message_success(self, client):
        resp = client.post("/api/git/commit/generate-message")
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        assert "AI-assisted" in data["message"]

    def test_generate_message_import_error(self, no_git_client):
        resp = no_git_client.post("/api/git/commit/generate-message")
        assert resp.status_code == 500

    def test_generate_message_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/commit/generate-message")
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "chore: update"
        assert "error" in data


# ══════════════════════════════════════════════════════════
# 3. _generate_commit_message — 类型推断
# ══════════════════════════════════════════════════════════


class TestGenerateCommitMessageType:
    """验证 _generate_commit_message 的类型推断逻辑"""

    def _make_repo(self, files_diff=None, untracked=None):
        repo = MagicMock()
        repo.index.diff.return_value = files_diff or []
        repo.untracked_files = untracked or []
        return repo

    def test_test_type(self):
        diff = [FakeDiffItem("test_x.py", "M")]
        repo = self._make_repo(files_diff=diff)
        msg = git_mod._generate_commit_message(repo)
        assert msg.startswith("test:")

    def test_docs_type(self):
        diff = [FakeDiffItem("README.md", "M")]
        repo = self._make_repo(files_diff=diff)
        msg = git_mod._generate_commit_message(repo)
        assert msg.startswith("docs:")

    def test_fix_type(self):
        diff = [FakeDiffItem("bugfix.py", "A")]
        repo = self._make_repo(files_diff=diff)
        msg = git_mod._generate_commit_message(repo)
        assert msg.startswith("fix:")

    def test_refactor_type(self):
        diff = [FakeDiffItem("refactor_module.py", "M")]
        repo = self._make_repo(files_diff=diff)
        msg = git_mod._generate_commit_message(repo)
        assert msg.startswith("refactor:")

    def test_feat_type_default(self):
        diff = [FakeDiffItem("feature.py", "A")]
        repo = self._make_repo(files_diff=diff)
        msg = git_mod._generate_commit_message(repo)
        assert msg.startswith("feat:")

    def test_more_than_10_files(self):
        diff = [FakeDiffItem(f"f{i}.py", "M") for i in range(15)]
        repo = self._make_repo(files_diff=diff)
        msg = git_mod._generate_commit_message(repo)
        assert "and 5 more files" in msg

    def test_untracked_included(self):
        repo = self._make_repo(untracked=["new.py"])
        msg = git_mod._generate_commit_message(repo)
        assert "A new.py" in msg


# ══════════════════════════════════════════════════════════
# 4. branch 操作
# ══════════════════════════════════════════════════════════


class TestBranchOps:
    def test_list_branches(self, client):
        resp = client.get("/api/git/branches")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] == "main"
        names = [b["name"] for b in data["branches"]]
        assert "main" in names

    def test_list_branches_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.get("/api/git/branches")
        assert resp.status_code == 200
        data = resp.json()
        assert data["branches"] == []
        assert "error" in data

    def test_create_branch(self, client):
        resp = client.post("/api/git/branch/create", json={"name": "feature"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["branch"] == "feature"

    def test_create_branch_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/branch/create", json={"name": "x"})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_switch_branch(self, client):
        resp = client.post("/api/git/branch/switch", json={"name": "dev"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_switch_branch_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/branch/switch", json={"name": "x"})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_merge_branch_success(self, client):
        resp = client.post(
            "/api/git/branch/merge", json={"source_branch": "dev"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_merge_branch_conflict(self, client, monkeypatch):
        """merge 抛含 CONFLICT 的异常 → has_conflicts=True"""
        def merge_side_effect(*a, **kw):
            raise RuntimeError("CONFLICT in merge")
        # patch 已存在的实例方法 — 通过覆盖 FakeGitCmd.merge
        original_init = FakeRepo.__init__

        def patched_init(self, path="."):
            original_init(self, path)
            self.git.merge = merge_side_effect

        monkeypatch.setattr(FakeRepo, "__init__", patched_init)
        resp = client.post(
            "/api/git/branch/merge", json={"source_branch": "dev"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["has_conflicts"] is True

    def test_merge_branch_generic_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post(
            "/api/git/branch/merge", json={"source_branch": "dev"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["has_conflicts"] is False


# ══════════════════════════════════════════════════════════
# 5. push / pull / fetch
# ══════════════════════════════════════════════════════════


class TestRemoteOps:
    def test_push_default(self, client):
        resp = client.post("/api/git/push", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_push_with_branch(self, client):
        resp = client.post(
            "/api/git/push", json={"remote": "origin", "branch": "main"}
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_push_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/push", json={})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_pull_default(self, client):
        resp = client.post("/api/git/pull", json={})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_pull_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/pull", json={})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_fetch_success(self, client):
        resp = client.post("/api/git/fetch", json={"remote": "origin"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "fetched" in data

    def test_fetch_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/fetch", json={})
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ══════════════════════════════════════════════════════════
# 6. stash 操作
# ══════════════════════════════════════════════════════════


class TestStashOps:
    def test_stash_push(self, client):
        resp = client.post("/api/git/stash", json={"action": "push", "message": "wip"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_stash_pop(self, client):
        resp = client.post("/api/git/stash", json={"action": "pop"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_stash_list(self, client):
        resp = client.post("/api/git/stash", json={"action": "list"})
        assert resp.status_code == 200
        data = resp.json()
        assert "stashes" in data
        assert len(data["stashes"]) >= 1

    def test_stash_drop(self, client):
        resp = client.post("/api/git/stash", json={"action": "drop", "index": 0})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_stash_unknown_action(self, client):
        resp = client.post("/api/git/stash", json={"action": "unknown"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "Unknown action" in data["error"]

    def test_stash_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/stash", json={"action": "push"})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_stash_detail(self, client):
        resp = client.post("/api/git/stash/detail", json={"index": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "diff" in data

    def test_stash_detail_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/stash/detail", json={"index": 0})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_stash_apply(self, client):
        resp = client.post("/api/git/stash/apply", json={"index": 0})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_stash_apply_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/stash/apply", json={"index": 0})
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ══════════════════════════════════════════════════════════
# 7. diff / blame
# ══════════════════════════════════════════════════════════


class TestDiffBlame:
    def test_diff_default(self, client):
        resp = client.get("/api/git/diff")
        assert resp.status_code == 200
        data = resp.json()
        assert data["diff"] == "diff content"

    def test_diff_staged(self, client):
        resp = client.get("/api/git/diff", params={"staged": True})
        assert resp.status_code == 200
        assert resp.json()["diff"] == "diff content"

    def test_diff_with_file(self, client):
        resp = client.get("/api/git/diff", params={"file": "a.py", "staged": True})
        assert resp.status_code == 200

    def test_diff_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.get("/api/git/diff")
        assert resp.status_code == 200
        data = resp.json()
        assert data["diff"] == ""
        assert "error" in data

    def test_blame_no_file(self, client):
        """file 参数为空应返回 400"""
        resp = client.get("/api/git/blame", params={"file": ""})
        assert resp.status_code == 400

    def test_blame_success(self, client):
        resp = client.get("/api/git/blame", params={"file": "a.py"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["file"] == "a.py"
        assert len(data["blame"]) >= 1

    def test_blame_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.get("/api/git/blame", params={"file": "a.py"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["blame"] == []
        assert "error" in data


# ══════════════════════════════════════════════════════════
# 8. stage / unstage / discard
# ══════════════════════════════════════════════════════════


class TestStageUnstage:
    def test_stage_files(self, client):
        resp = client.post("/api/git/stage", json={"files": ["a.py"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["staged"] == ["a.py"]

    def test_stage_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/stage", json={"files": ["a.py"]})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_unstage_files(self, client):
        resp = client.post("/api/git/unstage", json={"files": ["a.py"]})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_unstage_all(self, client):
        resp = client.post("/api/git/unstage", json={"all": True})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_unstage_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/unstage", json={"files": ["a.py"]})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_discard_files(self, client):
        resp = client.post("/api/git/discard", json={"files": ["a.py", "b.py"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["discarded"] == ["a.py", "b.py"]

    def test_discard_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/discard", json={"files": ["a.py"]})
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ══════════════════════════════════════════════════════════
# 9. branch delete / file-history / compare
# ══════════════════════════════════════════════════════════


class TestBranchDeleteHistoryCompare:
    def test_delete_branch_success(self, client):
        resp = client.post(
            "/api/git/branch/delete", json={"name": "dev", "force": False}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["deleted"] == "dev"

    def test_delete_branch_no_name(self, client):
        resp = client.post("/api/git/branch/delete", json={"name": "", "force": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "name is required" in data["error"]

    def test_delete_active_branch(self, client):
        """删除当前活跃分支应失败"""
        resp = client.post(
            "/api/git/branch/delete", json={"name": "main", "force": False}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "active branch" in data["error"]

    def test_delete_branch_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post(
            "/api/git/branch/delete", json={"name": "dev"}
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_file_history(self, client):
        resp = client.get("/api/git/file-history", params={"file": "a.py"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["file"] == "a.py"
        assert len(data["commits"]) >= 1

    def test_file_history_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.get("/api/git/file-history", params={"file": "a.py"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["commits"] == []
        assert "error" in data

    def test_compare_commits(self, client):
        resp = client.get(
            "/api/git/compare", params={"base": "main", "head": "dev"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["base"] == "main"
        assert data["head"] == "dev"
        assert data["diff"] == "diff content"

    def test_compare_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.get(
            "/api/git/compare", params={"base": "a", "head": "b"}
        )
        assert resp.status_code == 200
        assert "error" in resp.json()


# ══════════════════════════════════════════════════════════
# 10. tags
# ══════════════════════════════════════════════════════════


class TestTags:
    def test_list_tags(self, client):
        resp = client.get("/api/git/tags")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tags"]) >= 1
        assert data["tags"][0]["name"] == "v1.0"

    def test_list_tags_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.get("/api/git/tags")
        assert resp.status_code == 200
        assert resp.json()["tags"] == []
        assert "error" in resp.json()

    def test_create_tag_with_message(self, client):
        resp = client.post(
            "/api/git/tag/create",
            json={"name": "v2.0", "message": "release", "commit": "abc"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["tag"] == "v2.0"

    def test_create_tag_no_message(self, client):
        resp = client.post(
            "/api/git/tag/create", json={"name": "v3.0"}
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_create_tag_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/tag/create", json={"name": "v"})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_delete_tag(self, client):
        resp = client.post("/api/git/tag/delete", json={"name": "v1.0"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_delete_tag_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/tag/delete", json={"name": "v"})
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ══════════════════════════════════════════════════════════
# 11. reset / revert / cherry-pick / rebase
# ══════════════════════════════════════════════════════════


class TestResetRevertEtc:
    def test_reset_soft(self, client):
        resp = client.post(
            "/api/git/reset", json={"mode": "soft", "commit": "HEAD~1"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["mode"] == "soft"

    def test_reset_mixed(self, client):
        resp = client.post(
            "/api/git/reset", json={"mode": "mixed", "commit": "HEAD~1"}
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_reset_hard(self, client):
        resp = client.post(
            "/api/git/reset", json={"mode": "hard", "commit": "HEAD~1"}
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_reset_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/reset", json={"mode": "hard"})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_revert_success(self, client):
        resp = client.post("/api/git/revert", json={"commit": "abc123"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_revert_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/revert", json={"commit": "abc"})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_cherry_pick_success(self, client):
        resp = client.post("/api/git/cherry-pick", json={"commit": "abc123"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_cherry_pick_conflict(self, client, monkeypatch):
        """cherry-pick 抛含 CONFLICT 的异常 → has_conflicts=True"""
        original_init = FakeRepo.__init__

        def patched_init(self, path="."):
            original_init(self, path)
            self.git.cherry_pick = lambda *a, **kw: (_ for _ in ()).throw(
                RuntimeError("CONFLICT (content)")
            )

        monkeypatch.setattr(FakeRepo, "__init__", patched_init)
        resp = client.post("/api/git/cherry-pick", json={"commit": "abc"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["has_conflicts"] is True

    def test_cherry_pick_generic_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/cherry-pick", json={"commit": "abc"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["has_conflicts"] is False

    def test_rebase_success(self, client):
        resp = client.post("/api/git/rebase", json={"branch": "main"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_rebase_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post("/api/git/rebase", json={"branch": "main"})
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ══════════════════════════════════════════════════════════
# 12. remotes
# ══════════════════════════════════════════════════════════


class TestRemotes:
    def test_list_remotes(self, client):
        resp = client.get("/api/git/remotes")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["remotes"]) >= 1
        assert data["remotes"][0]["name"] == "origin"

    def test_list_remotes_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.get("/api/git/remotes")
        assert resp.status_code == 200
        assert resp.json()["remotes"] == []
        assert "error" in resp.json()

    def test_add_remote(self, client):
        resp = client.post(
            "/api/git/remote/add",
            json={"name": "upstream", "url": "git@github.com:u/r.git"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_add_remote_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post(
            "/api/git/remote/add", json={"name": "u", "url": "x"}
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_remove_remote(self, client):
        resp = client.post(
            "/api/git/remote/remove", json={"name": "origin"}
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_remove_remote_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post(
            "/api/git/remote/remove", json={"name": "origin"}
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ══════════════════════════════════════════════════════════
# 13. conflicts / resolve-conflict
# ══════════════════════════════════════════════════════════


class TestConflicts:
    def test_list_conflicts_empty(self, client):
        """无冲突时返回空列表"""
        resp = client.get("/api/git/conflicts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["conflicted"] == []

    def test_list_conflicts_with_unmerged(self, client, monkeypatch):
        """有 unmerged_blobs 时返回冲突信息"""
        original_init = FakeRepo.__init__

        def patched_init(self, path="."):
            original_init(self, path)
            # 模拟冲突文件
            blob_ours = (1, MagicMock())
            blob_ours[1].data_stream.read.return_value = b"our content"
            blob_theirs = (2, MagicMock())
            blob_theirs[1].data_stream.read.return_value = b"their content"
            self.index.unmerged_blobs = MagicMock(
                return_value={"conflict.py": (blob_ours, blob_theirs)}
            )

        monkeypatch.setattr(FakeRepo, "__init__", patched_init)
        resp = client.get("/api/git/conflicts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["conflicted"]) == 1
        assert data["conflicted"][0]["path"] == "conflict.py"
        assert data["conflicted"][0]["ours"] == "our content"
        assert data["conflicted"][0]["theirs"] == "their content"

    def test_list_conflicts_fallback_to_status(self, client, monkeypatch):
        """unmerged_blobs 抛异常 → 回退到 git status --porcelain"""
        original_init = FakeRepo.__init__

        def patched_init(self, path="."):
            original_init(self, path)
            self.index.unmerged_blobs = MagicMock(
                side_effect=RuntimeError("no merge")
            )

        monkeypatch.setattr(FakeRepo, "__init__", patched_init)
        resp = client.get("/api/git/conflicts")
        assert resp.status_code == 200
        data = resp.json()
        # status 返回 "UU conflict.py" → 应解析出 conflict.py
        assert len(data["conflicted"]) >= 1

    def test_list_conflicts_fallback_fails(self, client, monkeypatch):
        """unmerged_blobs 与 git status 都失败 → 返回空列表"""
        original_init = FakeRepo.__init__

        def patched_init(self, path="."):
            original_init(self, path)
            self.index.unmerged_blobs = MagicMock(
                side_effect=RuntimeError("no merge")
            )
            self.git.status = MagicMock(
                side_effect=OSError("io error")
            )

        monkeypatch.setattr(FakeRepo, "__init__", patched_init)
        resp = client.get("/api/git/conflicts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["conflicted"] == []

    def test_resolve_conflict(self, client):
        resp = client.post(
            "/api/git/resolve-conflict",
            json={"file": "a.py", "resolution": "ours"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["resolution"] == "ours"

    def test_resolve_conflict_exception(self, client, monkeypatch):
        def boom(path):
            raise RuntimeError("fail")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.post(
            "/api/git/resolve-conflict",
            json={"file": "a.py", "resolution": "theirs"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ══════════════════════════════════════════════════════════
# 14. ignore / init
# ══════════════════════════════════════════════════════════


class TestIgnoreInit:
    def test_ignore_new_pattern(self, client, workspace):
        resp = client.post(
            "/api/git/ignore", json={"pattern": "*.log"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["pattern"] == "*.log"
        # 文件应被写入
        gitignore = workspace / ".gitignore"
        assert gitignore.exists()
        assert "*.log" in gitignore.read_text(encoding="utf-8")

    def test_ignore_empty_pattern(self, client):
        resp = client.post("/api/git/ignore", json={"pattern": ""})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "pattern is required" in data["error"]

    def test_ignore_existing_pattern(self, client, workspace):
        """pattern 已存在时应返回 note"""
        gitignore = workspace / ".gitignore"
        gitignore.write_text("*.log\n", encoding="utf-8")
        resp = client.post("/api/git/ignore", json={"pattern": "*.log"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["note"] == "pattern already exists"

    def test_ignore_existing_gitignore(self, client, workspace):
        """已有 .gitignore 文件时追加"""
        gitignore = workspace / ".gitignore"
        gitignore.write_text("existing\n", encoding="utf-8")
        resp = client.post("/api/git/ignore", json={"pattern": "*.tmp"})
        assert resp.status_code == 200
        content = gitignore.read_text(encoding="utf-8")
        assert "existing" in content
        assert "*.tmp" in content

    def test_ignore_exception(self, client, workspace, monkeypatch):
        """写文件失败时返回 success=False"""
        def boom(_self, *a, **kw):
            raise OSError("io")
        monkeypatch.setattr(Path, "write_text", boom)
        resp = client.post("/api/git/ignore", json={"pattern": "*.log"})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_init_already_git_repo(self, client, workspace):
        """已是 git 仓库时应返回 note"""
        (workspace / ".git").mkdir()
        resp = client.post("/api/git/init", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["note"] == "already a git repository"

    def test_init_new_repo(self, client, workspace, monkeypatch):
        """新仓库初始化"""
        # workspace 没有 .git 目录
        resp = client.post("/api/git/init", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_init_with_path(self, client, workspace, monkeypatch):
        """指定 path 参数"""
        target = workspace / "newrepo"
        target.mkdir()
        resp = client.post("/api/git/init", json={"path": str(target)})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_init_exception(self, client, workspace, monkeypatch):
        def init_boom(path):
            raise RuntimeError("init fail")
        # patch Repo.init — 通过 fake_git 模块
        fake_git = sys.modules["git"]
        monkeypatch.setattr(fake_git.Repo, "init", init_boom)
        resp = client.post("/api/git/init", json={})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_init_import_error(self, no_git_client):
        """git_init 缺少 except ImportError 处理器（与其他端点不一致）— 
        ImportError 被 except Exception 捕获，返回 200 + success=False"""
        resp = no_git_client.post("/api/git/init", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "git" in data["error"].lower()

    def test_init_check_success(self, client):
        resp = client.get("/api/git/init")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_git"] is True
        assert "path" in data

    def test_init_check_import_error(self, no_git_client):
        resp = no_git_client.get("/api/git/init")
        assert resp.status_code == 200
        assert resp.json()["is_git"] is False

    def test_init_check_oserror(self, client, monkeypatch):
        def boom(_self, path):
            raise OSError("not a repo")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.get("/api/git/init")
        assert resp.status_code == 200
        assert resp.json()["is_git"] is False

    def test_init_check_value_error(self, client, monkeypatch):
        def boom(_self, path):
            raise ValueError("bad repo")
        monkeypatch.setattr(FakeRepo, "__init__", boom)
        resp = client.get("/api/git/init")
        assert resp.status_code == 200
        assert resp.json()["is_git"] is False


# ══════════════════════════════════════════════════════════
# 15. _run_git 辅助函数
# ══════════════════════════════════════════════════════════


class TestRunGitHelper:
    @pytest.mark.asyncio
    async def test_run_git_delegates(self):
        """_run_git 应将同步函数委托到线程执行"""
        from pycoder.server.routers.git import _run_git

        calls = []

        def sync_fn(a, b, c=0):
            calls.append((a, b, c))
            return "ok"

        result = await _run_git(sync_fn, 1, 2, c=3)
        assert result == "ok"
        assert calls == [(1, 2, 3)]
