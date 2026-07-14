"""
版本快照管理器 — 对标 Codex 轻量化 diff-only 快照

特性:
  - 每轮 Agent 写入前自动创建 diff-only 快照
  - 轻量化存储：仅存差异片段 (FileDiff)，不完整复制全量源码
  - 支持 snapshot_id 定位和精确回滚
  - 最大保留 MAX_SNAPSHOTS 个快照，超出自动清理旧快照
  - 快照存储在 workspace/.pycoder_snapshots/ 目录下
"""

from __future__ import annotations

import difflib
import gzip
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════

MAX_SNAPSHOTS = 10  # 最大快照数量
SNAPSHOT_DIR_NAME = ".pycoder_snapshots"


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class FileDiff:
    """单文件差异"""

    path: str  # 相对路径
    original: str = ""  # 原始内容（新格式从 diff_lines 重建）
    modified: str = ""  # 修改后内容（新格式从 diff_lines 重建）
    diff_lines: list[str] = field(default_factory=list)  # unified diff 行

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "diff_lines": self.diff_lines,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FileDiff:
        """从字典重建 FileDiff，兼容新旧格式"""
        obj = cls(
            path=data["path"],
            diff_lines=data.get("diff_lines", []),
        )
        # 旧格式：直接使用 original/modified
        if "original" in data and "modified" in data:
            obj.original = data["original"]
            obj.modified = data["modified"]
        # 新格式：仅存 diff_lines，通过解析 unified diff 重建
        elif obj.diff_lines:
            orig_parts: list[str] = []
            mod_parts: list[str] = []
            for line in obj.diff_lines:
                if line.startswith("--- ") or line.startswith("+++ ") or line.startswith("@@"):
                    continue
                if line.startswith("\\"):  # \\ No newline at end of file
                    continue
                if line.startswith("-"):
                    orig_parts.append(line[1:] + "\n")
                elif line.startswith("+"):
                    mod_parts.append(line[1:] + "\n")
                elif line.startswith(" ") or line == "":
                    content = line[1:] + "\n"
                    orig_parts.append(content)
                    mod_parts.append(content)
                else:
                    orig_parts.append(line + "\n")
                    mod_parts.append(line + "\n")
            obj.original = "".join(orig_parts)
            obj.modified = "".join(mod_parts)
        return obj


@dataclass
class RollbackResult:
    """回滚操作结果"""

    success: bool
    snapshot_id: str
    files_restored: list[str] = field(default_factory=list)
    files_failed: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class VersionSnapshot:
    """版本快照"""

    id: str
    parent_id: str | None  # 父快照，支持链式回滚
    created_at: float
    label: str  # 如 "编码完成 v1"
    files: list[FileDiff]  # 变动的文件差异
    pipeline_step: str = ""  # 关联的流水线步骤
    agent_role: str = ""  # 触发快照的 Agent 角色

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "created_at": self.created_at,
            "label": self.label,
            "pipeline_step": self.pipeline_step,
            "agent_role": self.agent_role,
            "file_count": len(self.files),
            "files": [f.to_dict() for f in self.files],
        }


# ══════════════════════════════════════════════════════════
# 快照管理器
# ══════════════════════════════════════════════════════════


class SnapshotManager:
    """快照管理器 — 创建/回滚/查询快照"""

    def __init__(self, workspace: str | Path):
        self._workspace = Path(workspace).resolve()
        self._snapshot_dir = self._workspace / SNAPSHOT_DIR_NAME
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)

    # ── 公共 API ────────────────────────────────────────

    async def create_snapshot(
        self,
        label: str,
        pipeline_step: str = "",
        agent_role: str = "",
        parent_id: str | None = None,
    ) -> VersionSnapshot:
        """创建当前工作区快照（diff-only）"""
        snapshot_id = f"snap-{uuid.uuid4().hex[:8]}"
        diffs: list[FileDiff] = []

        # 收集差异
        tracked_files = self._collect_tracked_files()
        for file_path in tracked_files:
            current_content = self._read_file(file_path)
            if current_content is None:
                continue
            # 读缓存中的上一版本内容（如果存在）作为 diff 基准
            last_content = self._get_last_version(file_path, parent_id)
            if last_content is not None and last_content == current_content:
                continue  # 无变化跳过
            diff_lines = list(
                difflib.unified_diff(
                    (last_content or "").splitlines(keepends=True),
                    current_content.splitlines(keepends=True),
                    fromfile=file_path,
                    tofile=file_path,
                    n=3,
                )
            )
            diffs.append(
                FileDiff(
                    path=file_path,
                    original=last_content or "",
                    modified=current_content,
                    diff_lines=[ln.rstrip("\n") for ln in diff_lines],
                )
            )

        snapshot = VersionSnapshot(
            id=snapshot_id,
            parent_id=parent_id,
            created_at=time.time(),
            label=label,
            files=diffs,
            pipeline_step=pipeline_step,
            agent_role=agent_role,
        )

        # 持久化快照
        self._save_snapshot(snapshot)
        self._cleanup_old()

        return snapshot

    async def rollback(
        self,
        snapshot_id: str,
        restore_targets: list[str] | None = None,
    ) -> RollbackResult:
        """回滚到指定快照版本"""
        snapshot = self._load_snapshot(snapshot_id)
        if snapshot is None:
            return RollbackResult(
                success=False,
                snapshot_id=snapshot_id,
                message=f"快照不存在: {snapshot_id}",
            )

        restored: list[str] = []
        failed: list[str] = []

        for fd in snapshot.files:
            # 若指定了恢复目标文件，仅恢复匹配的
            if restore_targets and fd.path not in restore_targets:
                continue
            target = (self._workspace / fd.path).resolve()
            if not target.is_relative_to(self._workspace):
                failed.append(fd.path)
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(fd.original, encoding="utf-8")
                restored.append(fd.path)
            except OSError as e:
                failed.append(f"{fd.path} ({e})")

        success = len(failed) == 0
        return RollbackResult(
            success=success,
            snapshot_id=snapshot_id,
            files_restored=restored,
            files_failed=failed,
            message=(
                f"快照 {snapshot_id} 回滚完成"
                f"（{len(restored)} 个文件恢复"
                + (f"，{len(failed)} 个文件失败" if failed else "")
                + "）"
            ),
        )

    def list_snapshots(self, limit: int = 20) -> list[VersionSnapshot]:
        """列出最近快照"""
        snapshots = []
        snap_dir = self._snapshot_dir
        if not snap_dir.exists():
            return snapshots

        files = sorted(
            list(snap_dir.glob("snap_*.json")) + list(snap_dir.glob("snap_*.json.gz")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for f in files[:limit]:
            try:
                raw = f.read_bytes()
                if f.suffix == ".gz":
                    raw = gzip.decompress(raw)
                data = json.loads(raw.decode("utf-8"))
                # 移除 to_dict 中额外字段，这些不是 dataclass 字段
                data.pop("file_count", None)
                data["files"] = [FileDiff.from_dict(fd) for fd in data.get("files", [])]
                snapshots.append(VersionSnapshot(**data))
            except Exception as e:
                logger.debug("load_snapshot_failed: %s", e)
                continue
        return snapshots

    def get_snapshot(self, snapshot_id: str) -> VersionSnapshot | None:
        """获取单个快照"""
        return self._load_snapshot(snapshot_id)

    def get_diff(self, from_id: str, to_id: str) -> list[dict]:
        """获取两个快照间的差异摘要"""
        from_snap = self._load_snapshot(from_id)
        to_snap = self._load_snapshot(to_id)
        if not from_snap or not to_snap:
            return []

        from_files = {fd.path: fd for fd in from_snap.files}
        to_files = {fd.path: fd for fd in to_snap.files}

        diffs = []
        all_paths = set(from_files.keys()) | set(to_files.keys())
        for path in sorted(all_paths):
            if path not in from_files:
                diffs.append({"path": path, "change": "added"})
            elif path not in to_files:
                diffs.append({"path": path, "change": "removed"})
            elif from_files[path].original != to_files[path].original:
                diffs.append({"path": path, "change": "modified"})
        return diffs

    # ── 内部方法 ────────────────────────────────────────

    def _collect_tracked_files(self) -> list[str]:
        """收集工作区中被追踪的源码文件"""
        tracked: list[str] = []
        for ext in (
            ".py",
            ".js",
            ".ts",
            ".jsx",
            ".tsx",
            ".json",
            ".yaml",
            ".yml",
            ".md",
            ".html",
            ".css",
            ".rs",
            ".go",
            ".java",
            ".kt",
            ".swift",
            ".c",
            ".cpp",
            ".h",
        ):
            for f in self._workspace.rglob(f"*{ext}"):
                rel = f.relative_to(self._workspace).as_posix()
                # 跳过快照目录和 .git 等
                if (
                    rel.startswith(".pycoder_")
                    or rel.startswith(".git")
                    or rel.startswith("node_modules")
                    or rel.startswith("__pycache__")
                    or rel.startswith(".venv")
                ):
                    continue
                tracked.append(rel)
        return sorted(tracked)

    def _read_file(self, rel_path: str) -> str | None:
        """读取文件内容"""
        target = self._workspace / rel_path
        if target.exists() and target.is_file():
            try:
                return target.read_text(encoding="utf-8")
            except Exception as e:
                logger.debug("read_file_failed: %s", e)
                return None
        return None

    def _get_last_version(self, file_path: str, parent_id: str | None) -> str | None:
        """从父快照中获取文件的上一个版本内容"""
        if parent_id is None:
            return None
        parent = self._load_snapshot(parent_id)
        if parent is None:
            return None
        for fd in parent.files:
            if fd.path == file_path:
                return fd.modified
        # 递归向上查找
        return self._get_last_version(file_path, parent.parent_id)

    def _save_snapshot(self, snapshot: VersionSnapshot):
        """快照持久化到磁盘（gzip 压缩 JSON）"""
        raw = json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2).encode("utf-8")
        compressed = gzip.compress(raw)
        snap_file = self._snapshot_dir / f"snap_{snapshot.id}.json.gz"
        snap_file.write_bytes(compressed)

    def _load_snapshot(self, snapshot_id: str) -> VersionSnapshot | None:
        """从磁盘加载快照（兼容 .json.gz 和旧 .json）"""
        snap_file = self._snapshot_dir / f"snap_{snapshot_id}.json.gz"
        if not snap_file.exists():
            snap_file = self._snapshot_dir / f"snap_{snapshot_id}.json"
        if not snap_file.exists():
            return None
        try:
            raw = snap_file.read_bytes()
            if snap_file.suffix == ".gz":
                raw = gzip.decompress(raw)
            data = json.loads(raw.decode("utf-8"))
            data.pop("file_count", None)  # to_dict 输出中的额外字段
            data["files"] = [FileDiff.from_dict(fd) for fd in data.get("files", [])]
            return VersionSnapshot(**data)
        except Exception as e:
            logger.debug("parse_snapshot_failed: %s", e)
            return None

    def _cleanup_old(self):
        """超出 MAX_SNAPSHOTS 时清理旧快照（兼容 .json 和 .json.gz）"""
        files = sorted(
            [*self._snapshot_dir.glob("snap_*.json"), *self._snapshot_dir.glob("snap_*.json.gz")],
            key=lambda p: p.stat().st_mtime,
        )
        while len(files) > MAX_SNAPSHOTS:
            oldest = files.pop(0)
            try:
                oldest.unlink()
            except OSError:
                pass


# ══════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════

_default_snapshot_manager: SnapshotManager | None = None


def get_snapshot_manager(workspace: str | Path | None = None) -> SnapshotManager:
    """获取全局快照管理器实例"""
    global _default_snapshot_manager
    if _default_snapshot_manager is None:
        w = workspace or os.getcwd()
        _default_snapshot_manager = SnapshotManager(w)
    return _default_snapshot_manager
