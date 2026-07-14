"""workspace 模块测试"""
from __future__ import annotations

import pytest
from pycoder.workspace.workspace_registry import WorkspaceRegistry, WorkspaceEntry, ShareLevel
from pycoder.workspace.share_sandbox import ShareSandbox


class TestWorkspaceRegistry:
    @pytest.fixture
    def registry(self, tmp_path):
        storage = tmp_path / "workspace_registry.json"
        return WorkspaceRegistry(storage_path=storage)

    def test_register_and_get(self, registry):
        entry = WorkspaceEntry(id="ws1", path="/home/project-a", name="项目A")
        registry.register(entry)
        result = registry.get("ws1")
        assert result is not None
        assert result.name == "项目A"

    def test_unregister(self, registry):
        registry.register(WorkspaceEntry(id="ws1", path="/tmp/ws1", name="测试"))
        registry.unregister("ws1")
        assert registry.get("ws1") is None

    def test_list_all(self, registry):
        registry.register(WorkspaceEntry(id="ws1", path="/tmp/a", name="A"))
        registry.register(WorkspaceEntry(id="ws2", path="/tmp/b", name="B"))
        assert len(registry.list_all()) == 2

    def test_list_accessible(self, registry):
        registry.register(WorkspaceEntry(
            id="ws1", path="/tmp/a", name="A",
            share_level=ShareLevel.READ,
            allowed_workspaces=["ws2"],
        ))
        registry.register(WorkspaceEntry(id="ws2", path="/tmp/b", name="B"))
        accessible = registry.list_accessible("ws2")
        assert len(accessible) == 1
        assert accessible[0].id == "ws1"

    def test_set_share_policy(self, registry):
        registry.register(WorkspaceEntry(id="ws1", path="/tmp/a", name="A"))
        registry.set_share_policy(
            "ws1", ShareLevel.READ, ["ws2"], ["src/"]
        )
        entry = registry.get("ws1")
        assert entry is not None
        assert entry.share_level == ShareLevel.READ
        assert "ws2" in entry.allowed_workspaces
        assert "src/" in entry.shared_paths

    def test_set_share_policy_nonexistent(self, registry):
        with pytest.raises(KeyError):
            registry.set_share_policy("nonexistent", ShareLevel.READ, [], [])

    def test_persistence(self, tmp_path):
        storage = tmp_path / "reg.json"
        r1 = WorkspaceRegistry(storage_path=storage)
        r1.register(WorkspaceEntry(id="ws1", path="/tmp/a", name="A"))
        r2 = WorkspaceRegistry(storage_path=storage)
        assert r2.get("ws1") is not None
        assert r2.get("ws1").name == "A"


class TestShareSandbox:
    @pytest.fixture
    def sandbox(self, tmp_path):
        reg = WorkspaceRegistry(storage_path=tmp_path / "reg.json")
        ws_a = tmp_path / "ws_a"
        ws_b = tmp_path / "ws_b"
        ws_a.mkdir()
        ws_b.mkdir()
        (ws_a / "src").mkdir()
        (ws_a / "src" / "main.py").write_text("print('hello from A')")
        (ws_b / "README.md").write_text("# Project B")

        reg.register(WorkspaceEntry(
            id="ws_a", path=str(ws_a), name="项目A",
            share_level=ShareLevel.READ,
            allowed_workspaces=["ws_b"],
        ))
        reg.register(WorkspaceEntry(
            id="ws_b", path=str(ws_b), name="项目B",
            share_level=ShareLevel.READ_WRITE,
            allowed_workspaces=["ws_a"],
        ))
        return ShareSandbox(reg)

    def test_read_file_with_permission(self, sandbox):
        content = sandbox.read_file("ws_b", "ws_a", "src/main.py")
        assert "hello from A" in content

    def test_read_file_no_permission(self, sandbox, tmp_path):
        sandbox._registry.register(WorkspaceEntry(
            id="ws_c", path=str(tmp_path / "ws_c"), name="C",
        ))
        with pytest.raises(PermissionError):
            sandbox.read_file("ws_c", "ws_a", "src/main.py")

    def test_read_file_not_registered(self, sandbox):
        with pytest.raises(PermissionError):
            sandbox.read_file("ws_unknown", "ws_a", "test.py")

    def test_read_file_not_found(self, sandbox):
        with pytest.raises(FileNotFoundError):
            sandbox.read_file("ws_b", "ws_a", "nonexistent.py")

    def test_write_file_with_permission(self, sandbox):
        sandbox.write_file("ws_a", "ws_b", "output.txt", "hello from A")
        merged = sandbox.commit_changes("ws_b")
        assert "output.txt" in merged

    def test_write_file_no_rw_permission(self, sandbox):
        with pytest.raises(PermissionError):
            sandbox.write_file("ws_b", "ws_a", "test.py", "bad")

    def test_rollback_changes(self, sandbox):
        sandbox.write_file("ws_a", "ws_b", "temp.txt", "temp")
        sandbox.rollback_changes("ws_b")
        merged = sandbox.commit_changes("ws_b")
        assert "temp.txt" not in merged

    def test_path_whitelist_block(self, tmp_path):
        reg = WorkspaceRegistry(storage_path=tmp_path / "reg.json")
        ws_a = tmp_path / "ws_a"
        ws_a.mkdir()
        (ws_a / "src").mkdir()
        (ws_a / "src" / "public.py").write_text("public")
        (ws_a / "secret").mkdir()
        (ws_a / "secret" / "key.txt").write_text("secret")

        reg.register(WorkspaceEntry(
            id="ws_a", path=str(ws_a), name="A",
            share_level=ShareLevel.READ,
            allowed_workspaces=["ws_b"],
            shared_paths=["src/"],
        ))
        reg.register(WorkspaceEntry(id="ws_b", path=str(tmp_path / "ws_b"), name="B"))
        sandbox = ShareSandbox(reg)

        # 允许访问 src/
        content = sandbox.read_file("ws_b", "ws_a", "src/public.py")
        assert content == "public"

        # 拒绝访问 secret/
        with pytest.raises(PermissionError):
            sandbox.read_file("ws_b", "ws_a", "secret/key.txt")