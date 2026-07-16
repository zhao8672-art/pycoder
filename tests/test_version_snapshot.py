"""SnapshotManager 版本快照管理器测试

覆盖:
  - FileDiff: 数据模型（序列化/反序列化，新旧格式兼容）
  - RollbackResult: 回滚结果数据模型
  - VersionSnapshot: 快照数据模型
  - SnapshotManager: 快照创建
  - SnapshotManager: 快照回滚
  - SnapshotManager: 快照列表
  - SnapshotManager: 快照差异对比
  - SnapshotManager: 快照清理
  - get_snapshot_manager: 全局单例
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pycoder.server.services.version_snapshot import (
    MAX_SNAPSHOTS,
    FileDiff,
    RollbackResult,
    SnapshotManager,
    VersionSnapshot,
    get_snapshot_manager,
)


# ══════════════════════════════════════════════════════════
# FileDiff 测试
# ══════════════════════════════════════════════════════════


class TestFileDiff:
    """文件差异数据模型测试"""

    def test_default_values(self) -> None:
        """默认值"""
        fd = FileDiff(path="test.py")
        assert fd.path == "test.py"
        assert fd.original == ""
        assert fd.modified == ""
        assert fd.diff_lines == []

    def test_to_dict(self) -> None:
        """序列化为字典"""
        fd = FileDiff(
            path="main.py",
            diff_lines=["- old", "+ new", "  same"],
        )
        d = fd.to_dict()
        assert d["path"] == "main.py"
        assert d["diff_lines"] == ["- old", "+ new", "  same"]
        # 新格式不包含 original/modified
        assert "original" not in d
        assert "modified" not in d

    def test_from_dict_new_format(self) -> None:
        """从新格式字典反序列化（仅 diff_lines）"""
        data = {
            "path": "main.py",
            "diff_lines": [
                "--- main.py",
                "+++ main.py",
                "@@ -1,3 +1,3 @@",
                " unchanged",
                "-old_line",
                "+new_line",
                " unchanged2",
            ],
        }
        fd = FileDiff.from_dict(data)
        assert fd.path == "main.py"
        assert "old_line" in fd.original
        assert "new_line" in fd.modified
        assert "unchanged" in fd.original
        assert "unchanged" in fd.modified

    def test_from_dict_old_format(self) -> None:
        """从旧格式字典反序列化（直接存储 original/modified）"""
        data = {
            "path": "main.py",
            "original": "old content",
            "modified": "new content",
            "diff_lines": [],
        }
        fd = FileDiff.from_dict(data)
        assert fd.path == "main.py"
        assert fd.original == "old content"
        assert fd.modified == "new content"

    def test_from_dict_empty_diff_lines(self) -> None:
        """空 diff_lines 时 original/modified 为空"""
        data = {"path": "test.py", "diff_lines": []}
        fd = FileDiff.from_dict(data)
        assert fd.original == ""
        assert fd.modified == ""

    def test_from_dict_diff_header_lines(self) -> None:
        """diff 头行（---/+++/@@）被正确跳过"""
        data = {
            "path": "test.py",
            "diff_lines": [
                "--- test.py",
                "+++ test.py",
                "@@ -1,1 +1,1 @@",
                " unchanged",
            ],
        }
        fd = FileDiff.from_dict(data)
        assert "unchanged" in fd.original
        assert "unchanged" in fd.modified
        assert "---" not in fd.original
        assert "+++" not in fd.modified
        assert "@@" not in fd.original

    def test_from_dict_no_newline_at_eof(self) -> None:
        """处理 \\ No newline at end of file 行"""
        data = {
            "path": "test.py",
            "diff_lines": [
                "--- test.py",
                "+++ test.py",
                "@@ -1,1 +1,1 @@",
                " unchanged",
                "\\ No newline at end of file",
            ],
        }
        fd = FileDiff.from_dict(data)
        assert "unchanged" in fd.original
        assert "\\ No newline" not in fd.original


# ══════════════════════════════════════════════════════════
# RollbackResult 测试
# ══════════════════════════════════════════════════════════


class TestRollbackResult:
    """回滚结果数据模型测试"""

    def test_successful_rollback(self) -> None:
        """成功回滚"""
        result = RollbackResult(
            success=True,
            snapshot_id="snap-abc123",
            files_restored=["a.py", "b.py"],
            message="回滚成功",
        )
        assert result.success is True
        assert result.snapshot_id == "snap-abc123"
        assert result.files_restored == ["a.py", "b.py"]
        assert result.files_failed == []
        assert result.message == "回滚成功"

    def test_failed_rollback(self) -> None:
        """失败回滚"""
        result = RollbackResult(
            success=False,
            snapshot_id="snap-xyz",
            files_restored=["a.py"],
            files_failed=["b.py (Permission denied)"],
            message="部分文件回滚失败",
        )
        assert result.success is False
        assert len(result.files_restored) == 1
        assert len(result.files_failed) == 1

    def test_default_values(self) -> None:
        """默认值"""
        result = RollbackResult(success=True, snapshot_id="snap-001")
        assert result.files_restored == []
        assert result.files_failed == []
        assert result.message == ""


# ══════════════════════════════════════════════════════════
# VersionSnapshot 测试
# ══════════════════════════════════════════════════════════


class TestVersionSnapshot:
    """版本快照数据模型测试"""

    def test_to_dict(self) -> None:
        """序列化为字典"""
        fd = FileDiff(path="test.py", diff_lines=["- old", "+ new"])
        snapshot = VersionSnapshot(
            id="snap-001",
            parent_id=None,
            created_at=1234567890.0,
            label="测试快照",
            files=[fd],
            pipeline_step="llm",
            agent_role="coder",
        )
        d = snapshot.to_dict()
        assert d["id"] == "snap-001"
        assert d["parent_id"] is None
        assert d["created_at"] == 1234567890.0
        assert d["label"] == "测试快照"
        assert d["pipeline_step"] == "llm"
        assert d["agent_role"] == "coder"
        assert d["file_count"] == 1
        assert len(d["files"]) == 1

    def test_to_dict_with_parent(self) -> None:
        """带父快照的序列化"""
        snapshot = VersionSnapshot(
            id="snap-002",
            parent_id="snap-001",
            created_at=1234567891.0,
            label="子快照",
            files=[],
        )
        d = snapshot.to_dict()
        assert d["parent_id"] == "snap-001"
        assert d["file_count"] == 0


# ══════════════════════════════════════════════════════════
# SnapshotManager 测试
# ══════════════════════════════════════════════════════════


class TestSnapshotManager:
    """快照管理器核心测试"""

    @pytest.fixture
    def temp_workspace(self) -> Path:
        """创建临时工作区"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def manager(self, temp_workspace: Path) -> SnapshotManager:
        """创建 SnapshotManager 实例"""
        return SnapshotManager(temp_workspace)

    @pytest.fixture
    def manager_with_files(self, temp_workspace: Path) -> SnapshotManager:
        """创建带测试文件的 SnapshotManager"""
        # 创建测试文件
        (temp_workspace / "test.py").write_text("print('hello')", encoding="utf-8")
        (temp_workspace / "utils.py").write_text("def foo(): pass", encoding="utf-8")
        # 创建应被忽略的目录
        (temp_workspace / ".git").mkdir(exist_ok=True)
        (temp_workspace / "__pycache__").mkdir(exist_ok=True)
        return SnapshotManager(temp_workspace)

    # ── 初始化测试 ──

    def test_init_creates_snapshot_dir(self, temp_workspace: Path) -> None:
        """初始化时创建快照目录"""
        manager = SnapshotManager(temp_workspace)
        assert manager._snapshot_dir.exists()
        assert manager._snapshot_dir.name == ".pycoder_snapshots"

    def test_init_with_existing_dir(self, temp_workspace: Path) -> None:
        """已存在快照目录时正常初始化"""
        snap_dir = temp_workspace / ".pycoder_snapshots"
        snap_dir.mkdir(parents=True)
        manager = SnapshotManager(temp_workspace)
        assert manager._snapshot_dir.exists()

    # ── 快照列表测试 ──

    def test_list_snapshots_empty(self, manager: SnapshotManager) -> None:
        """空快照列表"""
        snapshots = manager.list_snapshots()
        assert snapshots == []

    @pytest.mark.asyncio
    async def test_create_and_list_snapshot(self, manager_with_files: SnapshotManager) -> None:
        """创建快照后可列出"""
        with patch.object(
            manager_with_files,
            "_collect_tracked_files",
            return_value=["test.py"],
        ):
            with patch.object(
                manager_with_files,
                "_read_file",
                return_value="print('hello world')",
            ):
                with patch.object(
                    manager_with_files,
                    "_get_last_version",
                    return_value="print('hello')",
                ):
                    snapshot = await manager_with_files.create_snapshot("测试快照")

        assert snapshot.id.startswith("snap-")
        assert snapshot.label == "测试快照"

        snapshots = manager_with_files.list_snapshots()
        assert len(snapshots) >= 1

    @pytest.mark.asyncio
    async def test_create_snapshot_with_metadata(self, manager_with_files: SnapshotManager) -> None:
        """创建带元数据的快照"""
        with patch.object(
            manager_with_files,
            "_collect_tracked_files",
            return_value=["test.py"],
        ):
            with patch.object(
                manager_with_files,
                "_read_file",
                return_value="content",
            ):
                with patch.object(
                    manager_with_files,
                    "_get_last_version",
                    return_value=None,
                ):
                    snapshot = await manager_with_files.create_snapshot(
                        label="编码完成 v1",
                        pipeline_step="llm",
                        agent_role="coder",
                        parent_id="snap-parent",
                    )

        assert snapshot.pipeline_step == "llm"
        assert snapshot.agent_role == "coder"
        assert snapshot.parent_id == "snap-parent"

    # ── 快照回滚测试 ──

    @pytest.mark.asyncio
    async def test_rollback_nonexistent_snapshot(self, manager: SnapshotManager) -> None:
        """回滚不存在的快照返回失败"""
        result = await manager.rollback("snap-nonexistent")
        assert result.success is False
        assert "不存在" in result.message

    @pytest.mark.asyncio
    async def test_rollback_success(self, manager_with_files: SnapshotManager) -> None:
        """成功回滚快照"""
        # 创建快照
        with patch.object(
            manager_with_files,
            "_collect_tracked_files",
            return_value=["test.py"],
        ):
            with patch.object(
                manager_with_files,
                "_read_file",
                return_value="new content",
            ):
                with patch.object(
                    manager_with_files,
                    "_get_last_version",
                    return_value="old content",
                ):
                    snapshot = await manager_with_files.create_snapshot("v1")

        # 回滚
        result = await manager_with_files.rollback(snapshot.id)
        assert result.success is True
        assert result.snapshot_id == snapshot.id
        assert "test.py" in result.files_restored

    @pytest.mark.asyncio
    async def test_rollback_with_restore_targets(
        self, manager_with_files: SnapshotManager
    ) -> None:
        """指定恢复目标文件回滚"""
        with patch.object(
            manager_with_files,
            "_collect_tracked_files",
            return_value=["test.py", "utils.py"],
        ):
            with patch.object(
                manager_with_files,
                "_read_file",
                return_value="new content",
            ):
                with patch.object(
                    manager_with_files,
                    "_get_last_version",
                    return_value="old content",
                ):
                    snapshot = await manager_with_files.create_snapshot("v1")

        result = await manager_with_files.rollback(
            snapshot.id, restore_targets=["test.py"]
        )
        assert result.success is True
        assert "test.py" in result.files_restored
        assert "utils.py" not in result.files_restored

    @pytest.mark.asyncio
    async def test_rollback_path_traversal_prevention(
        self, manager_with_files: SnapshotManager
    ) -> None:
        """防止路径穿越攻击"""
        # 创建包含危险路径的快照
        fd = FileDiff(
            path="../../etc/passwd",
            original="hacked",
            modified="hacked",
        )
        snapshot = VersionSnapshot(
            id="snap-danger",
            parent_id=None,
            created_at=1234567890.0,
            label="危险快照",
            files=[fd],
        )

        with patch.object(
            manager_with_files,
            "_load_snapshot",
            return_value=snapshot,
        ):
            result = await manager_with_files.rollback("snap-danger")
            assert "etc/passwd" in result.files_failed or result.files_restored == []

    # ── 快照查询测试 ──

    def test_get_snapshot_nonexistent(self, manager: SnapshotManager) -> None:
        """获取不存在的快照返回 None"""
        result = manager.get_snapshot("snap-nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_snapshot_exists(self, manager_with_files: SnapshotManager) -> None:
        """获取存在的快照"""
        with patch.object(
            manager_with_files,
            "_collect_tracked_files",
            return_value=["test.py"],
        ):
            with patch.object(
                manager_with_files,
                "_read_file",
                return_value="content",
            ):
                with patch.object(
                    manager_with_files,
                    "_get_last_version",
                    return_value=None,
                ):
                    snapshot = await manager_with_files.create_snapshot("v1")

        result = manager_with_files.get_snapshot(snapshot.id)
        assert result is not None
        assert result.id == snapshot.id
        assert result.label == "v1"

    # ── 快照差异对比测试 ──

    def test_get_diff_nonexistent_snapshots(self, manager: SnapshotManager) -> None:
        """不存在的快照差异对比返回空列表"""
        result = manager.get_diff("snap-a", "snap-b")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_diff_between_snapshots(self, manager_with_files: SnapshotManager) -> None:
        """两个快照间差异对比"""
        fd1 = FileDiff(path="a.py", original="v1", modified="v1")
        fd2 = FileDiff(path="a.py", original="v2", modified="v2")
        fd3 = FileDiff(path="b.py", original="", modified="new")

        snap1 = VersionSnapshot(
            id="snap-1",
            parent_id=None,
            created_at=1.0,
            label="v1",
            files=[fd1],
        )
        snap2 = VersionSnapshot(
            id="snap-2",
            parent_id=None,
            created_at=2.0,
            label="v2",
            files=[fd2, fd3],
        )

        with patch.object(
            manager_with_files,
            "_load_snapshot",
            side_effect=[snap1, snap2],
        ):
            diffs = manager_with_files.get_diff("snap-1", "snap-2")
            assert len(diffs) >= 1
            # modified 变化
            modified = [d for d in diffs if d["change"] == "modified"]
            assert len(modified) >= 1
            # added 文件
            added = [d for d in diffs if d["change"] == "added"]
            assert len(added) >= 1

    def test_get_diff_added_and_removed(self, manager: SnapshotManager) -> None:
        """文件新增和删除的差异对比"""
        fd1 = FileDiff(path="a.py", original="old", modified="old")
        fd2 = FileDiff(path="b.py", original="", modified="new")

        snap1 = VersionSnapshot(
            id="snap-1", parent_id=None, created_at=1.0, label="v1", files=[fd1]
        )
        snap2 = VersionSnapshot(
            id="snap-2", parent_id=None, created_at=2.0, label="v2", files=[fd2]
        )

        with patch.object(
            manager, "_load_snapshot", side_effect=[snap1, snap2]
        ):
            diffs = manager.get_diff("snap-1", "snap-2")
            changes = {d["path"]: d["change"] for d in diffs}
            assert changes.get("a.py") == "removed"
            assert changes.get("b.py") == "added"

    # ── 快照清理测试 ──

    @pytest.mark.asyncio
    async def test_cleanup_old_snapshots(self, manager_with_files: SnapshotManager) -> None:
        """超出最大数量时清理旧快照"""
        # 创建超过 MAX_SNAPSHOTS 个快照文件
        for i in range(MAX_SNAPSHOTS + 5):
            snap_file = manager_with_files._snapshot_dir / f"snap_test_{i}.json.gz"
            snap_file.write_bytes(b"dummy")

        manager_with_files._cleanup_old()

        remaining = list(manager_with_files._snapshot_dir.glob("snap_*.json.gz"))
        assert len(remaining) <= MAX_SNAPSHOTS

    # ── 文件收集测试 ──

    def test_collect_tracked_files(self, manager_with_files: SnapshotManager) -> None:
        """收集被追踪的源码文件"""
        files = manager_with_files._collect_tracked_files()
        assert "test.py" in files
        assert "utils.py" in files
        # 确保忽略目录的文件不在列表中
        for f in files:
            assert not f.startswith(".git")
            assert not f.startswith("__pycache__")
            assert not f.startswith(".pycoder_")

    def test_collect_tracked_files_ignores_patterns(
        self, temp_workspace: Path
    ) -> None:
        """验证忽略规则"""
        (temp_workspace / "node_modules").mkdir(exist_ok=True)
        (temp_workspace / "node_modules" / "lib.js").write_text("// lib")
        (temp_workspace / ".venv").mkdir(exist_ok=True)
        (temp_workspace / ".venv" / "lib.py").write_text("# lib")

        manager = SnapshotManager(temp_workspace)
        files = manager._collect_tracked_files()
        for f in files:
            assert not f.startswith("node_modules")
            assert not f.startswith(".venv")

    # ── 文件读取测试 ──

    def test_read_file_exists(self, manager_with_files: SnapshotManager) -> None:
        """读取存在的文件"""
        content = manager_with_files._read_file("test.py")
        assert content == "print('hello')"

    def test_read_file_not_exists(self, manager: SnapshotManager) -> None:
        """读取不存在的文件返回 None"""
        content = manager._read_file("nonexistent.py")
        assert content is None

    def test_read_file_directory(self, manager_with_files: SnapshotManager) -> None:
        """读取目录路径返回 None"""
        content = manager_with_files._read_file(".git")
        assert content is None

    # ── 父快照查找测试 ──

    def test_get_last_version_no_parent(self, manager: SnapshotManager) -> None:
        """无父快照时返回 None"""
        result = manager._get_last_version("test.py", None)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_last_version_from_parent(self, manager_with_files: SnapshotManager) -> None:
        """从父快照获取文件版本"""
        parent_fd = FileDiff(path="test.py", modified="parent content")
        parent_snap = VersionSnapshot(
            id="snap-parent",
            parent_id=None,
            created_at=1.0,
            label="parent",
            files=[parent_fd],
        )

        with patch.object(
            manager_with_files,
            "_load_snapshot",
            return_value=parent_snap,
        ):
            result = manager_with_files._get_last_version("test.py", "snap-parent")
            assert result == "parent content"

    @pytest.mark.asyncio
    async def test_get_last_version_recursive(self, manager_with_files: SnapshotManager) -> None:
        """递归查找父快照链"""
        grandparent_fd = FileDiff(path="test.py", modified="grandparent content")
        grandparent_snap = VersionSnapshot(
            id="snap-grandparent",
            parent_id=None,
            created_at=1.0,
            label="grandparent",
            files=[grandparent_fd],
        )
        parent_snap = VersionSnapshot(
            id="snap-parent",
            parent_id="snap-grandparent",
            created_at=2.0,
            label="parent",
            files=[],  # 父快照没有该文件
        )

        def load_side_effect(snap_id):
            if snap_id == "snap-parent":
                return parent_snap
            elif snap_id == "snap-grandparent":
                return grandparent_snap
            return None

        with patch.object(
            manager_with_files,
            "_load_snapshot",
            side_effect=load_side_effect,
        ):
            result = manager_with_files._get_last_version("test.py", "snap-parent")
            assert result == "grandparent content"

    # ── 快照保存/加载测试 ──

    @pytest.mark.asyncio
    async def test_save_and_load_snapshot(self, manager: SnapshotManager) -> None:
        """保存并加载快照验证数据完整性"""
        fd = FileDiff(path="test.py", diff_lines=["- old", "+ new", "  same"])
        snapshot = VersionSnapshot(
            id="snap-test-001",
            parent_id=None,
            created_at=1234567890.0,
            label="测试",
            files=[fd],
            pipeline_step="llm",
            agent_role="coder",
        )

        manager._save_snapshot(snapshot)
        loaded = manager._load_snapshot("snap-test-001")

        assert loaded is not None
        assert loaded.id == snapshot.id
        assert loaded.label == snapshot.label
        assert loaded.pipeline_step == "llm"
        assert len(loaded.files) == 1
        assert loaded.files[0].path == "test.py"

    def test_load_snapshot_nonexistent(self, manager: SnapshotManager) -> None:
        """加载不存在的快照返回 None"""
        result = manager._load_snapshot("snap-nonexistent")
        assert result is None

    def test_load_snapshot_corrupted(self, manager: SnapshotManager) -> None:
        """加载损坏的快照文件返回 None"""
        snap_file = manager._snapshot_dir / "snap_corrupt.json.gz"
        snap_file.write_bytes(b"not valid gzip data")
        result = manager._load_snapshot("corrupt")
        assert result is None


# ══════════════════════════════════════════════════════════
# 全局单例测试
# ══════════════════════════════════════════════════════════


class TestGetSnapshotManager:
    """全局单例测试"""

    def test_returns_snapshot_manager(self) -> None:
        """返回 SnapshotManager 实例"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 重置全局单例以便测试
            import pycoder.server.services.version_snapshot as vs
            vs._default_snapshot_manager = None

            manager = get_snapshot_manager(tmpdir)
            assert isinstance(manager, SnapshotManager)

    def test_singleton_behavior(self) -> None:
        """多次调用返回同一实例"""
        with tempfile.TemporaryDirectory() as tmpdir:
            import pycoder.server.services.version_snapshot as vs
            vs._default_snapshot_manager = None

            m1 = get_snapshot_manager(tmpdir)
            m2 = get_snapshot_manager(tmpdir)
            assert m1 is m2

    def test_uses_cwd_when_no_workspace(self) -> None:
        """无工作区时使用当前目录"""
        import pycoder.server.services.version_snapshot as vs
        vs._default_snapshot_manager = None

        with patch("os.getcwd", return_value=str(Path.cwd())):
            manager = get_snapshot_manager()
            assert isinstance(manager, SnapshotManager)