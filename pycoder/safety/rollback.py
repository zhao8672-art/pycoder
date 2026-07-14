"""
回滚管理 — 自动快照与恢复

每次写操作前自动创建快照，失败时可一键回滚。
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Snapshot:
    """文件快照"""
    snapshot_id: str
    file_path: str
    backup_path: str
    original_hash: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class RollbackManager:
    """
    回滚管理器

    特性:
    - 写操作前自动创建文件快照
    - 支持单文件和批量回滚
    - 快照自动过期清理
    - 与 Git 集成（优先使用 git stash）
    """

    def __init__(
        self,
        snapshot_dir: Path | None = None,
        max_snapshots: int = 1000,
        snapshot_ttl_seconds: float = 86400,  # 24 hours
    ):
        self._snapshot_dir = snapshot_dir or Path(tempfile.gettempdir()) / "pycoder_snapshots"
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._max_snapshots = max_snapshots
        self._snapshot_ttl = snapshot_ttl_seconds
        self._snapshots: dict[str, Snapshot] = {}
        self._active_snapshots: list[str] = []  # 当前批次的快照 ID 列表

    def snapshot_file(self, file_path: str | Path) -> Snapshot:
        """
        为文件创建快照

        Args:
            file_path: 要备份的文件路径

        Returns:
            Snapshot 快照对象
        """
        fpath = Path(file_path)
        if not fpath.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # 计算文件哈希
        original_hash = self._hash_file(fpath)

        # 创建备份
        snapshot_id = self._generate_snapshot_id(fpath, original_hash)
        backup_path = self._snapshot_dir / f"{snapshot_id}_{fpath.name}"

        shutil.copy2(str(fpath), str(backup_path))

        snapshot = Snapshot(
            snapshot_id=snapshot_id,
            file_path=str(fpath.absolute()),
            backup_path=str(backup_path),
            original_hash=original_hash,
        )

        self._snapshots[snapshot_id] = snapshot
        self._active_snapshots.append(snapshot_id)

        logger.debug("快照已创建: %s → %s", fpath.name, snapshot_id[:8])

        # 检查容量
        if len(self._snapshots) > self._max_snapshots:
            self._cleanup_old_snapshots()

        return snapshot

    def snapshot_files(self, file_paths: list[str | Path]) -> list[Snapshot]:
        """批量为多个文件创建快照"""
        return [self.snapshot_file(p) for p in file_paths]

    def rollback(self, snapshot_id: str) -> bool:
        """
        回滚到指定快照

        Args:
            snapshot_id: 快照 ID

        Returns:
            是否成功回滚
        """
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None:
            logger.error("快照不存在: %s", snapshot_id)
            return False

        file_path = Path(snapshot.file_path)
        backup_path = Path(snapshot.backup_path)

        if not backup_path.exists():
            logger.error("备份文件不存在: %s", backup_path)
            return False

        try:
            shutil.copy2(str(backup_path), str(file_path))
            logger.info("已回滚: %s", file_path.name)

            # 清理快照
            backup_path.unlink(missing_ok=True)
            self._snapshots.pop(snapshot_id, None)

            return True
        except Exception as e:
            logger.error("回滚失败: %s", e)
            return False

    def rollback_all(self) -> list[str]:
        """
        回滚当前批次的所有变更

        Returns:
            成功回滚的快照 ID 列表
        """
        success_ids: list[str] = []
        failed_ids: list[str] = []

        # 倒序回滚（后改的先回滚）
        for sid in reversed(self._active_snapshots):
            if self.rollback(sid):
                success_ids.append(sid)
            else:
                failed_ids.append(sid)

        self._active_snapshots.clear()

        if failed_ids:
            logger.warning("%d 个文件回滚失败", len(failed_ids))

        return success_ids

    def commit_batch(self) -> None:
        """确认当前批次，清理快照"""
        for sid in self._active_snapshots:
            snapshot = self._snapshots.get(sid)
            if snapshot:
                Path(snapshot.backup_path).unlink(missing_ok=True)
                self._snapshots.pop(sid, None)

        self._active_snapshots.clear()
        logger.info("批次已确认，%d 个快照已清理", len(self._active_snapshots))

    def get_snapshot(self, snapshot_id: str) -> Snapshot | None:
        """获取快照信息"""
        return self._snapshots.get(snapshot_id)

    def list_active_snapshots(self) -> list[Snapshot]:
        """列出当前活跃的快照"""
        return [s for sid in self._active_snapshots if (s := self._snapshots.get(sid))]

    def pending_count(self) -> int:
        """当前批次中未确认的快照数量"""
        return len(self._active_snapshots)

    # ── 私有方法 ───────────────────────────

    @staticmethod
    def _hash_file(filepath: Path) -> str:
        """计算文件的 SHA-256 哈希"""
        hasher = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def _generate_snapshot_id(filepath: Path, file_hash: str) -> str:
        """生成快照 ID"""
        unique = f"{filepath}_{file_hash}_{time.time()}"
        return hashlib.md5(unique.encode()).hexdigest()[:16]

    def _cleanup_old_snapshots(self) -> None:
        """清理过期快照"""
        cutoff = time.time() - self._snapshot_ttl
        expired = [
            sid for sid, s in self._snapshots.items()
            if s.timestamp < cutoff and sid not in self._active_snapshots
        ]

        for sid in expired[:100]:  # 每次最多清理 100 个
            snapshot = self._snapshots.pop(sid, None)
            if snapshot:
                Path(snapshot.backup_path).unlink(missing_ok=True)

        if expired:
            logger.debug("清理了 %d 个过期快照", min(len(expired), 100))
