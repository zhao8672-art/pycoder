"""
跨工作区 API 路由单元测试 — 覆盖 workspace_api.py 所有端点

测试范围:
  - POST /api/workspaces/register                    — 注册新工作区
  - DELETE /api/workspaces/{workspace_id}            — 注销工作区
  - GET  /api/workspaces/list                        — 列出所有工作区
  - GET  /api/workspaces/{workspace_id}              — 获取工作区详情
  - GET  /api/workspaces/{workspace_id}/files/{path} — 跨工作区读取文件
  - PUT  /api/workspaces/{workspace_id}/share-policy — 设置共享策略
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pycoder.workspace.workspace_registry import ShareLevel, WorkspaceEntry, WorkspaceRegistry


# ── 辅助函数 ──────────────────────────────────────────────


def _make_workspace_entry(
    ws_id: str = "ws-001",
    path: str = "/home/project-a",
    name: str = "项目A",
    share_level: ShareLevel = ShareLevel.NONE,
    allowed: list[str] | None = None,
    shared_paths: list[str] | None = None,
) -> WorkspaceEntry:
    """创建测试用 WorkspaceEntry"""
    return WorkspaceEntry(
        id=ws_id,
        path=path,
        name=name,
        share_level=share_level,
        allowed_workspaces=allowed or [],
        shared_paths=shared_paths or [],
    )


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def clean_registry() -> WorkspaceRegistry:
    """创建干净的工作区注册表（内存中，不持久化）"""
    import tempfile
    from pathlib import Path

    # 使用临时文件避免污染真实数据
    tmp_dir = Path(tempfile.mkdtemp(prefix="ws_test_"))
    registry = WorkspaceRegistry(storage_path=tmp_dir / "ws_registry.json")
    # 清空所有条目
    for ws_id in list(registry._entries.keys()):
        registry.unregister(ws_id)
    return registry


@pytest.fixture
def client_with_registry(clean_registry: WorkspaceRegistry) -> TestClient:
    """注入干净 WorkspaceRegistry 的 TestClient"""
    from pycoder.server.routers import workspace_api

    # 保存原始状态
    orig_registry = workspace_api._registry
    orig_sandbox = workspace_api._sandbox

    workspace_api._registry = clean_registry
    from pycoder.workspace.share_sandbox import ShareSandbox

    workspace_api._sandbox = ShareSandbox(clean_registry)

    from pycoder.server.app import app

    with TestClient(app) as c:
        yield c

    workspace_api._registry = orig_registry
    workspace_api._sandbox = orig_sandbox


# ── POST /api/workspaces/register 测试 ────────────────────


class TestRegisterWorkspace:
    """注册工作区端点"""

    def test_register_success(self, client_with_registry: TestClient) -> None:
        """测试成功注册工作区"""
        resp = client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-001",
                "path": "/home/project-a",
                "name": "项目A",
                "share_level": "read",
                "allowed_workspaces": ["ws-002"],
                "shared_paths": ["src/"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["workspace_id"] == "ws-001"

    def test_register_minimal(self, client_with_registry: TestClient) -> None:
        """测试最小参数注册"""
        resp = client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-min",
                "path": "/tmp/test",
                "name": "最小项目",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["workspace_id"] == "ws-min"

    def test_register_default_share_level(self, client_with_registry: TestClient) -> None:
        """测试默认共享级别"""
        resp = client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-default",
                "path": "/tmp/default",
                "name": "默认级别",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_register_missing_id(self, client_with_registry: TestClient) -> None:
        """测试缺少 id 返回 400"""
        resp = client_with_registry.post(
            "/api/workspaces/register",
            json={
                "path": "/tmp/test",
                "name": "无ID",
            },
        )
        assert resp.status_code == 400
        assert "缺少必填参数" in resp.json()["detail"]

    def test_register_missing_path(self, client_with_registry: TestClient) -> None:
        """测试缺少 path 返回 400"""
        resp = client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-nopath",
                "name": "无路径",
            },
        )
        assert resp.status_code == 400

    def test_register_missing_name(self, client_with_registry: TestClient) -> None:
        """测试缺少 name 返回 400"""
        resp = client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-noname",
                "path": "/tmp/test",
            },
        )
        assert resp.status_code == 400

    def test_register_invalid_share_level(self, client_with_registry: TestClient) -> None:
        """测试无效共享级别返回 400"""
        resp = client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-bad",
                "path": "/tmp/test",
                "name": "无效级别",
                "share_level": "super_admin",
            },
        )
        assert resp.status_code == 400
        assert "无效的共享级别" in resp.json()["detail"]

    def test_register_with_all_options(self, client_with_registry: TestClient) -> None:
        """测试完整参数注册"""
        resp = client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-full",
                "path": "/home/project-full",
                "name": "完整项目",
                "share_level": "rw",
                "allowed_workspaces": ["ws-a", "ws-b", "ws-c"],
                "shared_paths": ["src/", "docs/", "config/"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["workspace_id"] == "ws-full"


# ── DELETE /api/workspaces/{workspace_id} 测试 ────────────


class TestUnregisterWorkspace:
    """注销工作区端点"""

    def test_unregister_success(self, client_with_registry: TestClient) -> None:
        """测试成功注销工作区"""
        # 先注册
        client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-del",
                "path": "/tmp/delete",
                "name": "待删除",
            },
        )
        # 再注销
        resp = client_with_registry.delete("/api/workspaces/ws-del")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_unregister_not_found(self, client_with_registry: TestClient) -> None:
        """测试注销不存在的工作区返回 404"""
        resp = client_with_registry.delete("/api/workspaces/ws-nope")
        assert resp.status_code == 404
        assert "工作区不存在" in resp.json()["detail"]

    def test_unregister_and_verify(self, client_with_registry: TestClient) -> None:
        """测试注销后无法再获取"""
        # 注册
        client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-verify",
                "path": "/tmp/verify",
                "name": "验证删除",
            },
        )
        # 注销
        resp = client_with_registry.delete("/api/workspaces/ws-verify")
        assert resp.status_code == 200

        # 验证已删除
        resp = client_with_registry.get("/api/workspaces/ws-verify")
        assert resp.status_code == 404


# ── GET /api/workspaces/list 测试 ─────────────────────────


class TestListWorkspaces:
    """列出工作区端点"""

    def test_list_empty(self, client_with_registry: TestClient) -> None:
        """测试空列表"""
        resp = client_with_registry.get("/api/workspaces/list")
        assert resp.status_code == 200
        data = resp.json()
        assert "workspaces" in data
        assert data["workspaces"] == []

    def test_list_with_entries(self, client_with_registry: TestClient) -> None:
        """测试列出已注册工作区"""
        # 注册多个工作区
        entries = [
            {"id": "ws-1", "path": "/tmp/ws1", "name": "项目1", "share_level": "read"},
            {"id": "ws-2", "path": "/tmp/ws2", "name": "项目2", "share_level": "none"},
            {"id": "ws-3", "path": "/tmp/ws3", "name": "项目3", "share_level": "rw"},
        ]
        for entry in entries:
            client_with_registry.post("/api/workspaces/register", json=entry)

        resp = client_with_registry.get("/api/workspaces/list")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["workspaces"]) == 3
        ids = {ws["id"] for ws in data["workspaces"]}
        assert ids == {"ws-1", "ws-2", "ws-3"}

        # 验证每个工作区包含必要字段
        for ws in data["workspaces"]:
            assert "id" in ws
            assert "name" in ws
            assert "path" in ws
            assert "share_level" in ws
            assert "allowed_workspaces" in ws
            assert "shared_paths" in ws


# ── GET /api/workspaces/{workspace_id} 测试 ───────────────


class TestGetWorkspace:
    """获取工作区详情端点"""

    def test_get_workspace_success(self, client_with_registry: TestClient) -> None:
        """测试成功获取工作区详情"""
        client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-detail",
                "path": "/tmp/detail",
                "name": "详情项目",
                "share_level": "read",
                "allowed_workspaces": ["ws-other"],
                "shared_paths": ["src/"],
            },
        )

        resp = client_with_registry.get("/api/workspaces/ws-detail")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "ws-detail"
        assert data["name"] == "详情项目"
        assert data["path"] == "/tmp/detail"
        assert data["share_level"] == "read"
        assert data["allowed_workspaces"] == ["ws-other"]
        assert data["shared_paths"] == ["src/"]

    def test_get_workspace_not_found(self, client_with_registry: TestClient) -> None:
        """测试获取不存在的工作区返回 404"""
        resp = client_with_registry.get("/api/workspaces/ws-nobody")
        assert resp.status_code == 404
        assert "工作区不存在" in resp.json()["detail"]


# ── GET /api/workspaces/{workspace_id}/files/{file_path} ──


class TestReadSharedFile:
    """跨工作区读取文件端点"""

    def test_read_file_success(self, client_with_registry: TestClient) -> None:
        """测试成功读取共享文件"""
        import tempfile
        from pathlib import Path

        # 创建临时文件
        tmp = Path(tempfile.mkdtemp(prefix="ws_share_test_"))
        src_dir = tmp / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        test_file = src_dir / "main.py"
        test_file.write_text("print('hello')", encoding="utf-8")

        # 注册源工作区（开启共享）
        client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-source",
                "path": str(tmp),
                "name": "源项目",
                "share_level": "read",
                "allowed_workspaces": ["ws-caller"],
                "shared_paths": ["src/"],
            },
        )

        resp = client_with_registry.get(
            "/api/workspaces/ws-source/files/src/main.py?caller_ws=ws-caller"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "print('hello')"
        assert data["workspace_id"] == "ws-source"
        assert data["file_path"] == "src/main.py"

        # 清理
        import shutil

        shutil.rmtree(str(tmp), ignore_errors=True)

    def test_read_file_no_permission(self, client_with_registry: TestClient) -> None:
        """测试无权限读取返回 403"""
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="ws_perm_test_"))
        (tmp / "src").mkdir(parents=True, exist_ok=True)
        (tmp / "src" / "secret.py").write_text("secret", encoding="utf-8")

        # 注册工作区（不共享给 ws-caller）
        client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-private",
                "path": str(tmp),
                "name": "私有项目",
                "share_level": "read",  # 开启共享但未授权调用方
                "allowed_workspaces": ["ws-other"],  # 仅授权 ws-other
                "shared_paths": ["src/"],
            },
        )

        resp = client_with_registry.get(
            "/api/workspaces/ws-private/files/src/secret.py?caller_ws=ws-caller"
        )
        assert resp.status_code == 403

        import shutil

        shutil.rmtree(str(tmp), ignore_errors=True)

    def test_read_file_share_none(self, client_with_registry: TestClient) -> None:
        """测试未开启共享返回 403"""
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="ws_noshare_"))
        (tmp / "data.txt").write_text("data", encoding="utf-8")

        # 注册工作区（不开启共享）
        client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-closed",
                "path": str(tmp),
                "name": "封闭项目",
                "share_level": "none",
            },
        )

        resp = client_with_registry.get(
            "/api/workspaces/ws-closed/files/data.txt?caller_ws=ws-caller"
        )
        assert resp.status_code == 403

        import shutil

        shutil.rmtree(str(tmp), ignore_errors=True)

    def test_read_file_not_found(self, client_with_registry: TestClient) -> None:
        """测试文件不存在返回 404"""
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="ws_nofile_"))
        (tmp / "src").mkdir(parents=True, exist_ok=True)

        client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-nofile",
                "path": str(tmp),
                "name": "空项目",
                "share_level": "read",
                "allowed_workspaces": ["ws-caller"],
                "shared_paths": ["src/"],
            },
        )

        resp = client_with_registry.get(
            "/api/workspaces/ws-nofile/files/src/nonexistent.py?caller_ws=ws-caller"
        )
        assert resp.status_code == 404

        import shutil

        shutil.rmtree(str(tmp), ignore_errors=True)


# ── PUT /api/workspaces/{workspace_id}/share-policy 测试 ──


class TestSetSharePolicy:
    """设置共享策略端点"""

    def test_set_share_policy_success(self, client_with_registry: TestClient) -> None:
        """测试成功设置共享策略"""
        # 先注册
        client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-policy",
                "path": "/tmp/policy",
                "name": "策略项目",
            },
        )

        # 设置策略
        resp = client_with_registry.put(
            "/api/workspaces/ws-policy/share-policy",
            json={
                "share_level": "read",
                "allowed_workspaces": ["ws-a", "ws-b"],
                "shared_paths": ["src/", "lib/"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

        # 验证策略已更新
        resp = client_with_registry.get("/api/workspaces/ws-policy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["share_level"] == "read"
        assert data["allowed_workspaces"] == ["ws-a", "ws-b"]
        assert data["shared_paths"] == ["src/", "lib/"]

    def test_set_share_policy_workspace_not_found(self, client_with_registry: TestClient) -> None:
        """测试设置不存在工作区策略返回 404"""
        resp = client_with_registry.put(
            "/api/workspaces/ws-nonexistent/share-policy",
            json={
                "share_level": "read",
                "allowed_workspaces": [],
                "shared_paths": [],
            },
        )
        assert resp.status_code == 404
        assert "工作区不存在" in resp.json()["detail"]

    def test_set_share_policy_invalid_level(self, client_with_registry: TestClient) -> None:
        """测试无效共享级别返回 400"""
        client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-badlevel",
                "path": "/tmp/badlevel",
                "name": "坏级别",
            },
        )

        resp = client_with_registry.put(
            "/api/workspaces/ws-badlevel/share-policy",
            json={
                "share_level": "admin",
                "allowed_workspaces": [],
                "shared_paths": [],
            },
        )
        assert resp.status_code == 400
        assert "无效的共享级别" in resp.json()["detail"]

    def test_set_share_policy_partial_update(self, client_with_registry: TestClient) -> None:
        """测试部分更新策略"""
        client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-partial",
                "path": "/tmp/partial",
                "name": "部分更新",
                "share_level": "read",
                "allowed_workspaces": ["ws-old"],
                "shared_paths": ["old/"],
            },
        )

        # 只更新 shared_paths
        resp = client_with_registry.put(
            "/api/workspaces/ws-partial/share-policy",
            json={
                "shared_paths": ["new/"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

        # 验证 shared_paths 已更新，其他不变
        resp = client_with_registry.get("/api/workspaces/ws-partial")
        assert resp.status_code == 200
        data = resp.json()
        assert data["shared_paths"] == ["new/"]
        assert data["share_level"] == "read"  # 未变

    def test_set_share_policy_rw_level(self, client_with_registry: TestClient) -> None:
        """测试设置读写共享级别"""
        client_with_registry.post(
            "/api/workspaces/register",
            json={
                "id": "ws-rw",
                "path": "/tmp/rw",
                "name": "读写项目",
            },
        )

        resp = client_with_registry.put(
            "/api/workspaces/ws-rw/share-policy",
            json={
                "share_level": "rw",
                "allowed_workspaces": ["ws-other"],
                "shared_paths": ["src/"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

        # 验证
        resp = client_with_registry.get("/api/workspaces/ws-rw")
        assert resp.status_code == 200
        data = resp.json()
        assert data["share_level"] == "rw"