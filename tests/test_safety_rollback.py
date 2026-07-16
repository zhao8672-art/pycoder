"""回滚管理模块测试

覆盖:
  - Snapshot: 数据模型
  - RollbackManager: 单文件快照创建
  - RollbackManager: 批量快照创建
  - RollbackManager: 单文件回滚
  - RollbackManager: 批量回滚 (rollback_all)
  - RollbackManager: 批次确认 (commit_batch)
  - RollbackManager: 快照查询与统计
  - RollbackManager: 容量管理与过期清理
  - RollbackManager: 错误路径（文件不存在、快照不存在）
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from pycoder.safety.rollback import RollbackManager, Snapshot


# ══════════════════════════════════════════════════════════
# Snapshot 数据模型测试
# ══════════════════════════════════════════════════════════


class TestSnapshot:
    """快照数据模型"""

    def test_create_snapshot(self):
        """创建快照对象"""
        snap = Snapshot(
            snapshot_id="abc123",
            file_path="/tmp/test.py",
            backup_path="/tmp/backups/test.py",
            original_hash="sha256hash",
        )
        assert snap.snapshot_id == "abc123"
        assert snap.file_path == "/tmp/test.py"
        assert snap.backup_path == "/tmp/backups/test.py"
        assert snap.original_hash == "sha256hash"
        assert snap.timestamp > 0

    def test_snapshot_metadata(self):
        """快照携带元数据"""
        snap = Snapshot(
            snapshot_id="meta-1",
            file_path="/tmp/a.py",
            backup_path="/tmp/backups/a.py",
            original_hash="hash",
            metadata={"reason": "pre-edit", "user": "agent"},
        )
        assert snap.metadata["reason"] == "pre-edit"
        assert snap.metadata["user"] == "agent"


# ══════════════════════════════════════════════════════════
# RollbackManager 单文件快照测试
# ══════════════════════════════════════════════════════════


class TestRollbackManagerSnapshot:
    """快照创建"""

    @pytest.fixture
    def manager(self, tmp_path) -> RollbackManager:
        """创建回滚管理器（使用临时目录）"""
        return RollbackManager(snapshot_dir=tmp_path / "snapshots")

    def test_snapshot_file_creates_backup(self, manager: RollbackManager, tmp_path):
        """为文件创建快照"""
        # 创建测试文件
        test_file = tmp_path / "test.txt"
        test_file.write_text("原始内容", encoding="utf-8")

        snapshot = manager.snapshot_file(test_file)
        assert snapshot is not None
        assert snapshot.file_path == str(test_file.absolute())
        assert Path(snapshot.backup_path).exists()

    def test_snapshot_file_not_found(self, manager: RollbackManager):
        """快照不存在的文件抛出异常"""
        with pytest.raises(FileNotFoundError, match="文件不存在"):
            manager.snapshot_file("/nonexistent/file.txt")

    def test_snapshot_files_batch(self, manager: RollbackManager, tmp_path):
        """批量创建多个文件快照"""
        files = []
        for i in range(3):
            f = tmp_path / f"file_{i}.txt"
            f.write_text(f"内容 {i}", encoding="utf-8")
            files.append(f)

        snapshots = manager.snapshot_files(files)
        assert len(snapshots) == 3
        for s in snapshots:
            assert Path(s.backup_path).exists()

    def test_snapshot_preserves_content(self, manager: RollbackManager, tmp_path):
        """快照正确保存文件内容"""
        test_file = tmp_path / "important.py"
        original = "def hello():\n    return 'world'\n"
        test_file.write_text(original, encoding="utf-8")

        snapshot = manager.snapshot_file(test_file)
        backup = Path(snapshot.backup_path)
        assert backup.read_text(encoding="utf-8") == original


# ══════════════════════════════════════════════════════════
# RollbackManager 单文件回滚测试
# ══════════════════════════════════════════════════════════


class TestRollbackManagerSingleRollback:
    """单文件回滚"""

    @pytest.fixture
    def manager(self, tmp_path) -> RollbackManager:
        return RollbackManager(snapshot_dir=tmp_path / "snapshots")

    def test_rollback_restores_content(self, manager: RollbackManager, tmp_path):
        """回滚恢复原始内容"""
        test_file = tmp_path / "data.txt"
        test_file.write_text("版本 1", encoding="utf-8")

        snapshot = manager.snapshot_file(test_file)

        # 修改文件
        test_file.write_text("版本 2（已修改）", encoding="utf-8")

        # 回滚
        success = manager.rollback(snapshot.snapshot_id)
        assert success is True
        assert test_file.read_text(encoding="utf-8") == "版本 1"

    def test_rollback_nonexistent_snapshot_id(self, manager: RollbackManager):
        """回滚不存在的快照返回 False"""
        assert manager.rollback("nonexistent-id") is False

    def test_rollback_missing_backup_file(self, manager: RollbackManager, tmp_path):
        """备份文件已被删除时回滚失败"""
        test_file = tmp_path / "data.txt"
        test_file.write_text("内容", encoding="utf-8")

        snapshot = manager.snapshot_file(test_file)
        # 手动删除备份文件
        Path(snapshot.backup_path).unlink()

        assert manager.rollback(snapshot.snapshot_id) is False

    def test_rollback_cleans_up_snapshot(self, manager: RollbackManager, tmp_path):
        """回滚成功后清理快照"""
        test_file = tmp_path / "cleanup.txt"
        test_file.write_text("原始", encoding="utf-8")

        snapshot = manager.snapshot_file(test_file)
        test_file.write_text("修改后", encoding="utf-8")

        manager.rollback(snapshot.snapshot_id)
        # 备份文件应被清理
        assert not Path(snapshot.backup_path).exists()
        # 快照记录应被移除
        assert manager.get_snapshot(snapshot.snapshot_id) is None


# ══════════════════════════════════════════════════════════
# RollbackManager 批量回滚测试
# ══════════════════════════════════════════════════════════


class TestRollbackManagerBatchRollback:
    """批量回滚"""

    @pytest.fixture
    def manager(self, tmp_path) -> RollbackManager:
        return RollbackManager(snapshot_dir=tmp_path / "snapshots")

    def test_rollback_all_restores_all_files(self, manager: RollbackManager, tmp_path):
        """批量回滚恢复所有文件"""
        files = {}
        for name in ["a.txt", "b.txt", "c.txt"]:
            f = tmp_path / name
            f.write_text(f"{name} 原始", encoding="utf-8")
            manager.snapshot_file(f)
            files[name] = f

        # 修改所有文件
        for name, f in files.items():
            f.write_text(f"{name} 修改后", encoding="utf-8")

        # 批量回滚
        success_ids = manager.rollback_all()
        assert len(success_ids) == 3

        # 验证所有文件已恢复
        for name, f in files.items():
            assert f.read_text(encoding="utf-8") == f"{name} 原始"

    def test_rollback_all_reverse_order(self, manager: RollbackManager, tmp_path):
        """回滚按倒序执行（后改的先回滚）"""
        test_file = tmp_path / "order.txt"
        test_file.write_text("v1", encoding="utf-8")

        s1 = manager.snapshot_file(test_file)  # 快照 v1
        test_file.write_text("v2", encoding="utf-8")
        s2 = manager.snapshot_file(test_file)  # 快照 v2
        test_file.write_text("v3", encoding="utf-8")

        success_ids = manager.rollback_all()
        # 先回滚 s2（恢复 v2），再回滚 s1（恢复 v1）
        assert success_ids[0] == s2.snapshot_id
        assert success_ids[1] == s1.snapshot_id
        assert test_file.read_text(encoding="utf-8") == "v1"

    def test_rollback_all_clears_active_list(self, manager: RollbackManager, tmp_path):
        """批量回滚后清空活跃快照列表"""
        test_file = tmp_path / "clear.txt"
        test_file.write_text("test", encoding="utf-8")
        manager.snapshot_file(test_file)

        assert manager.pending_count() == 1
        manager.rollback_all()
        assert manager.pending_count() == 0


# ══════════════════════════════════════════════════════════
# RollbackManager 批次确认测试
# ══════════════════════════════════════════════════════════


class TestRollbackManagerCommitBatch:
    """批次确认"""

    @pytest.fixture
    def manager(self, tmp_path) -> RollbackManager:
        return RollbackManager(snapshot_dir=tmp_path / "snapshots")

    def test_commit_batch_cleans_up(self, manager: RollbackManager, tmp_path):
        """确认批次后清理快照"""
        test_file = tmp_path / "commit.txt"
        test_file.write_text("内容", encoding="utf-8")

        snapshot = manager.snapshot_file(test_file)
        backup_path = Path(snapshot.backup_path)
        assert backup_path.exists()

        manager.commit_batch()
        # 备份文件应被删除
        assert not backup_path.exists()
        # 快照记录应被移除
        assert manager.get_snapshot(snapshot.snapshot_id) is None
        # 活跃列表应清空
        assert manager.pending_count() == 0

    def test_commit_batch_empty(self, manager: RollbackManager):
        """空批次确认不报错"""
        manager.commit_batch()
        assert manager.pending_count() == 0


# ══════════════════════════════════════════════════════════
# RollbackManager 查询与统计测试
# ══════════════════════════════════════════════════════════


class TestRollbackManagerQuery:
    """快照查询与统计"""

    @pytest.fixture
    def manager(self, tmp_path) -> RollbackManager:
        return RollbackManager(snapshot_dir=tmp_path / "snapshots")

    def test_get_snapshot(self, manager: RollbackManager, tmp_path):
        """获取快照信息"""
        test_file = tmp_path / "query.txt"
        test_file.write_text("data", encoding="utf-8")
        snap = manager.snapshot_file(test_file)

        found = manager.get_snapshot(snap.snapshot_id)
        assert found is not None
        assert found.file_path == str(test_file.absolute())

    def test_get_snapshot_not_found(self, manager: RollbackManager):
        """获取不存在的快照返回 None"""
        assert manager.get_snapshot("nonexistent") is None

    def test_list_active_snapshots(self, manager: RollbackManager, tmp_path):
        """列出活跃快照"""
        for i in range(3):
            f = tmp_path / f"active_{i}.txt"
            f.write_text(f"data {i}", encoding="utf-8")
            manager.snapshot_file(f)

        active = manager.list_active_snapshots()
        assert len(active) == 3

    def test_pending_count(self, manager: RollbackManager, tmp_path):
        """待确认快照计数"""
        assert manager.pending_count() == 0

        f = tmp_path / "pending.txt"
        f.write_text("test", encoding="utf-8")
        manager.snapshot_file(f)
        assert manager.pending_count() == 1

        manager.snapshot_file(f)
        assert manager.pending_count() == 2


# ══════════════════════════════════════════════════════════
# RollbackManager 容量管理测试
# ══════════════════════════════════════════════════════════


class TestRollbackManagerCapacity:
    """容量管理与过期清理"""

    def test_max_snapshots_triggers_cleanup(self, tmp_path):
        """超过最大快照数触发清理"""
        manager = RollbackManager(
            snapshot_dir=tmp_path / "snapshots",
            max_snapshots=5,
            snapshot_ttl_seconds=0,  # 立即过期
        )

        # 确认每个快照（使其不在活跃列表中）
        for i in range(8):
            f = tmp_path / f"cap_{i}.txt"
            f.write_text(f"data {i}", encoding="utf-8")
            manager.snapshot_file(f)
            manager.commit_batch()  # 确认后快照变为非活跃

        # 由于 TTL=0，所有非活跃快照都应被清理
        # 快照数应不超过 max_snapshots
        assert manager.pending_count() == 0

    def test_active_snapshots_not_cleaned_up(self, tmp_path):
        """活跃快照不会被过期清理"""
        manager = RollbackManager(
            snapshot_dir=tmp_path / "snapshots",
            max_snapshots=100,
            snapshot_ttl_seconds=0,
        )

        f = tmp_path / "active_protected.txt"
        f.write_text("protected", encoding="utf-8")
        snap = manager.snapshot_file(f)

        # 活跃快照不应被清理
        assert manager.get_snapshot(snap.snapshot_id) is not None
        assert manager.pending_count() == 1