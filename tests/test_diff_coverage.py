"""覆盖率测试: pycoder/server/routers/diff.py

目标: 行覆盖率 >= 95%

覆盖端点:
    POST /api/diff             — 生成 unified diff（有差异 / 无差异 / 自定义 context）
    POST /api/diff/file        — 文件 diff（源不存在 / 读源异常 / content /
                                  target 不存在 / 读 target 异常 / 缺参数 / 正常）
    GET  /api/diff/recent      — 列出最近 diff（带 limit）
    GET  /api/diff/hunks       — 解析 hunks（多 hunk / 无 hunk）
    POST /api/diff/hunk/invert — 反转 hunk（带 - 行 / 仅 original_context）
    POST /api/diff/hunk/apply  — 应用 hunk（缺 file_path / 路径越界 /
                                  文件不存在 / accept+匹配 / accept+不匹配 /
                                  accept+纯新增 / accept+空 hunk /
                                  reject / 未知 action）

测试策略:
    - 直接调用辅助函数 + TestClient 调用端点
    - 使用 tmp_path + monkeypatch WORKSPACE_ROOT 隔离文件系统
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers import diff as diff_router_mod


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def app_client():
    """创建仅包含 diff 路由的 FastAPI 应用"""
    app = FastAPI()
    app.include_router(diff_router_mod.router)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch):
    """创建临时工作区并 monkeypatch WORKSPACE_ROOT"""
    monkeypatch.setattr(diff_router_mod, "WORKSPACE_ROOT", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_recent_diffs():
    """每个测试前清空 _recent_diffs，避免测试间状态污染"""
    diff_router_mod._recent_diffs.clear()
    yield
    diff_router_mod._recent_diffs.clear()


# ══════════════════════════════════════════════════════════
# 1. POST /api/diff — generate_diff
# ══════════════════════════════════════════════════════════


class TestGenerateDiff:
    def test_with_changes(self, app_client):
        """有差异时返回 diff 文本和统计"""
        resp = app_client.post("/api/diff", json={
            "original": "line1\nline2\n",
            "modified": "line1\nline2 modified\n",
            "context_lines": 3,
            "filename": "test.py",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["changed"] is True
        assert data["stats"]["added"] >= 1
        assert data["stats"]["removed"] >= 1
        assert "test.py" in data["diff"]

    def test_no_changes(self, app_client):
        """无差异时 changed=False"""
        resp = app_client.post("/api/diff", json={
            "original": "same\n",
            "modified": "same\n",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["changed"] is False
        assert data["stats"]["added"] == 0
        assert data["stats"]["removed"] == 0
        assert data["diff"] == ""

    def test_recent_diffs_stored(self, app_client):
        """生成 diff 后应存入 _recent_diffs"""
        app_client.post("/api/diff", json={
            "original": "a\n", "modified": "b\n",
        })
        assert len(diff_router_mod._recent_diffs) == 1
        assert diff_router_mod._recent_diffs[0]["filename"] == "file"

    def test_max_recent_cap(self, app_client):
        """超过 _MAX_RECENT 时应弹出旧记录"""
        original_max = diff_router_mod._MAX_RECENT
        try:
            diff_router_mod._MAX_RECENT = 2
            for i in range(3):
                app_client.post("/api/diff", json={
                    "original": "a\n", "modified": f"b{i}\n",
                })
            assert len(diff_router_mod._recent_diffs) == 2
        finally:
            diff_router_mod._MAX_RECENT = original_max


# ══════════════════════════════════════════════════════════
# 2. POST /api/diff/file — diff_file
# ══════════════════════════════════════════════════════════


class TestDiffFile:
    def test_source_not_found(self, app_client):
        """源文件不存在 → 404"""
        resp = app_client.post("/api/diff/file", json={
            "source_path": "/nonexistent/path/abc.txt",
            "content": "new",
        })
        assert resp.status_code == 404
        assert "Source file not found" in resp.json()["detail"]

    def test_source_read_error(self, app_client, workspace, monkeypatch):
        """读源文件抛非 FileNotFoundError 异常 → 500"""
        f = workspace / "src.txt"
        f.write_text("orig\n", encoding="utf-8")

        def boom(_self, *args, **kwargs):
            raise OSError("io err")
        monkeypatch.setattr(Path, "read_text", boom)

        resp = app_client.post("/api/diff/file", json={
            "source_path": str(f),
            "content": "new",
        })
        assert resp.status_code == 500
        assert "Error reading source file" in resp.json()["detail"]

    def test_with_content(self, app_client, workspace):
        """通过 content 字段提供新内容"""
        f = workspace / "src.txt"
        f.write_text("original line\n", encoding="utf-8")
        resp = app_client.post("/api/diff/file", json={
            "source_path": str(f),
            "content": "modified line\n",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["changed"] is True
        assert data["stats"]["added"] >= 1

    def test_target_not_found(self, app_client, workspace):
        """target_path 不存在 → 404"""
        f = workspace / "src.txt"
        f.write_text("orig\n", encoding="utf-8")
        resp = app_client.post("/api/diff/file", json={
            "source_path": str(f),
            "target_path": "/nonexistent/target.txt",
        })
        assert resp.status_code == 404
        assert "Target file not found" in resp.json()["detail"]

    def test_target_read_error(self, app_client, workspace, monkeypatch):
        """读 target 抛非 FileNotFoundError → 500"""
        src = workspace / "src.txt"
        src.write_text("orig\n", encoding="utf-8")
        tgt = workspace / "tgt.txt"
        tgt.write_text("tgt\n", encoding="utf-8")

        original_read_text = Path.read_text
        call_count = {"n": 0}

        def selective_boom(self, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                raise OSError("io err")
            return original_read_text(self, *args, **kwargs)
        monkeypatch.setattr(Path, "read_text", selective_boom)

        resp = app_client.post("/api/diff/file", json={
            "source_path": str(src),
            "target_path": str(tgt),
        })
        assert resp.status_code == 500
        assert "Error reading target file" in resp.json()["detail"]

    def test_with_target_path(self, app_client, workspace):
        """使用 target_path 比较两个文件"""
        src = workspace / "src.txt"
        src.write_text("line1\nline2\n", encoding="utf-8")
        tgt = workspace / "tgt.txt"
        tgt.write_text("line1\nLINE2\n", encoding="utf-8")
        resp = app_client.post("/api/diff/file", json={
            "source_path": str(src),
            "target_path": str(tgt),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["changed"] is True

    def test_missing_both_content_and_target(self, app_client, workspace):
        """既无 content 也无 target_path → 400"""
        f = workspace / "src.txt"
        f.write_text("orig\n", encoding="utf-8")
        resp = app_client.post("/api/diff/file", json={
            "source_path": str(f),
        })
        assert resp.status_code == 400
        assert "Either target_path or content is required" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════
# 3. GET /api/diff/recent — list_recent_diffs
# ══════════════════════════════════════════════════════════


class TestListRecentDiffs:
    def test_empty(self, app_client):
        """无最近 diff 时返回空列表"""
        resp = app_client.get("/api/diff/recent")
        assert resp.status_code == 200
        assert resp.json() == {"diffs": []}

    def test_with_limit(self, app_client):
        """limit 参数限制返回数量"""
        for i in range(3):
            app_client.post("/api/diff", json={
                "original": "a\n", "modified": f"b{i}\n",
            })
        resp = app_client.get("/api/diff/recent", params={"limit": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["diffs"]) == 2


# ══════════════════════════════════════════════════════════
# 4. GET /api/diff/hunks — parse_diff_hunks
# ══════════════════════════════════════════════════════════


class TestParseDiffHunks:
    def test_multi_hunks(self, app_client):
        """多个 @@ hunk 应被切分"""
        diff_text = (
            "--- a\n+++ b\n"
            "@@ -1,2 +1,2 @@\n"
            " context\n"
            "-old\n"
            "+new\n"
            "@@ -5,1 +5,1 @@\n"
            " ctx2\n"
            "-del\n"
            "+ins\n"
        )
        resp = app_client.get("/api/diff/hunks", params={"diff_text": diff_text})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["hunks"][0]["added"] == 1
        assert data["hunks"][0]["removed"] == 1
        assert data["hunks"][1]["added"] == 1

    def test_no_hunks(self, app_client):
        """无 @@ 标记时返回空"""
        resp = app_client.get("/api/diff/hunks", params={"diff_text": "no hunk here"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["hunks"] == []

    def test_empty_diff(self, app_client):
        """空 diff_text"""
        resp = app_client.get("/api/diff/hunks", params={"diff_text": ""})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# ══════════════════════════════════════════════════════════
# 5. POST /api/diff/hunk/invert — invert_hunk
# ══════════════════════════════════════════════════════════


class TestInvertHunk:
    def test_with_minus_lines(self, app_client):
        """hunk_lines 中有 - 行应被提取"""
        resp = app_client.post("/api/diff/hunk/invert", json={
            "hunk_lines": ["-old line\n", " context\n", "+new line\n"],
        })
        assert resp.status_code == 200
        assert resp.json()["original"] == "old line\n"

    def test_fallback_to_original_context(self, app_client):
        """无 - 行时使用 original_context"""
        resp = app_client.post("/api/diff/hunk/invert", json={
            "hunk_lines": ["+only added\n"],
            "original_context": "fallback content\n",
        })
        assert resp.status_code == 200
        assert resp.json()["original"] == "fallback content\n"

    def test_no_minus_no_context(self, app_client):
        """无 - 行也无 original_context → 返回空字符串"""
        resp = app_client.post("/api/diff/hunk/invert", json={
            "hunk_lines": ["+only added\n"],
        })
        assert resp.status_code == 200
        assert resp.json()["original"] == ""


# ══════════════════════════════════════════════════════════
# 6. POST /api/diff/hunk/apply — apply_hunk_to_file
# ══════════════════════════════════════════════════════════


class TestApplyHunk:
    def test_missing_file_path(self, app_client):
        """无 file_path → 返回 error"""
        resp = app_client.post("/api/diff/hunk/apply", json={
            "hunk_text": "+x\n", "action": "accept",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "file_path 必填" in data["error"]

    def test_path_traversal(self, app_client, workspace):
        """路径越界（不在 WORKSPACE_ROOT 内）"""
        resp = app_client.post("/api/diff/hunk/apply", json={
            "file_path": "../../../etc/passwd",
            "hunk_text": "+x\n",
            "action": "accept",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "路径越界"

    def test_file_not_exist(self, app_client, workspace):
        """文件不存在"""
        resp = app_client.post("/api/diff/hunk/apply", json={
            "file_path": "missing.py",
            "hunk_text": "+x\n",
            "action": "accept",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "文件不存在"

    def test_accept_with_match(self, app_client, workspace):
        """accept 模式，hunk 中 - 行能匹配文件内容 → 替换成功"""
        f = workspace / "target.py"
        f.write_text("def hello():\n    print('hi')\n", encoding="utf-8")
        hunk = (
            "-def hello():\n"
            "-    print('hi')\n"
            "+def goodbye():\n"
            "+    print('bye')\n"
        )
        resp = app_client.post("/api/diff/hunk/apply", json={
            "file_path": "target.py",
            "hunk_text": hunk,
            "action": "accept",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["action"] == "accepted"
        assert "goodbye" in f.read_text(encoding="utf-8")

    def test_accept_no_match(self, app_client, workspace):
        """accept 模式，- 行无法在文件中匹配 → 失败"""
        f = workspace / "target.py"
        f.write_text("totally different content\n", encoding="utf-8")
        hunk = "-nonexistent line\n+new line\n"
        resp = app_client.post("/api/diff/hunk/apply", json={
            "file_path": "target.py",
            "hunk_text": hunk,
            "action": "accept",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "无法在文件中找到匹配" in data["error"]

    def test_accept_pure_addition(self, app_client, workspace):
        """accept 模式，仅 + 行（无 - 行）→ 追加到文件末尾"""
        f = workspace / "target.py"
        f.write_text("line1\n", encoding="utf-8")
        hunk = "+line2\n+line3\n"
        resp = app_client.post("/api/diff/hunk/apply", json={
            "file_path": "target.py",
            "hunk_text": hunk,
            "action": "accept",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        content = f.read_text(encoding="utf-8")
        assert "line2" in content and "line3" in content

    def test_accept_no_valid_changes(self, app_client, workspace):
        """accept 模式，hunk 中既无 + 也无 - → 返回无有效变更行"""
        f = workspace / "target.py"
        f.write_text("line\n", encoding="utf-8")
        hunk = " context line only\n"
        resp = app_client.post("/api/diff/hunk/apply", json={
            "file_path": "target.py",
            "hunk_text": hunk,
            "action": "accept",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "无有效变更行" in data["error"]

    def test_reject_action(self, app_client, workspace):
        """reject 模式 → 直接返回 rejected"""
        f = workspace / "target.py"
        f.write_text("orig\n", encoding="utf-8")
        resp = app_client.post("/api/diff/hunk/apply", json={
            "file_path": "target.py",
            "hunk_text": "+x\n",
            "action": "reject",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["action"] == "rejected"
        # 文件未被修改
        assert f.read_text(encoding="utf-8") == "orig\n"

    def test_unknown_action(self, app_client, workspace):
        """未知 action"""
        f = workspace / "target.py"
        f.write_text("orig\n", encoding="utf-8")
        resp = app_client.post("/api/diff/hunk/apply", json={
            "file_path": "target.py",
            "hunk_text": "+x\n",
            "action": "invalid_action",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "未知操作" in data["error"]
