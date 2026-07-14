"""工作区注册表 — 管理所有已知工作区及其共享权限

提供工作区注册/注销、ACL 权限声明、共享范围控制。
数据持久化到统一 SQLite 数据库。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ShareLevel(Enum):
    NONE = "none"
    READ = "read"
    READ_WRITE = "rw"


@dataclass
class WorkspaceEntry:
    id: str
    path: str
    name: str
    share_level: ShareLevel = ShareLevel.NONE
    allowed_workspaces: list[str] = field(default_factory=list)
    shared_paths: list[str] = field(default_factory=list)
    created_at: float = 0.0


class WorkspaceRegistry:
    """工作区注册表

    用法:
        registry = WorkspaceRegistry()
        entry = WorkspaceEntry(id="ws1", path="/home/project-a", name="项目A")
        registry.register(entry)
        accessible = registry.list_accessible("ws2")
    """

    def __init__(self, storage_path: Path | None = None):
        storage_path = storage_path or (Path.home() / ".pycoder" / "workspace_registry.json")
        self._storage = storage_path
        self._storage.parent.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, WorkspaceEntry] = {}
        self._load()

    def register(self, entry: WorkspaceEntry) -> None:
        """注册工作区"""
        entry.created_at = time.time()
        self._entries[entry.id] = entry
        self._save()

    def unregister(self, workspace_id: str) -> None:
        """注销工作区"""
        self._entries.pop(workspace_id, None)
        self._save()

    def get(self, workspace_id: str) -> WorkspaceEntry | None:
        """获取工作区信息"""
        return self._entries.get(workspace_id)

    def list_all(self) -> list[WorkspaceEntry]:
        """列出所有已注册工作区"""
        return list(self._entries.values())

    def list_accessible(self, caller_id: str) -> list[WorkspaceEntry]:
        """列出调用方可访问的工作区"""
        result = []
        for entry in self._entries.values():
            if entry.id == caller_id:
                continue
            if caller_id in entry.allowed_workspaces:
                result.append(entry)
        return result

    def set_share_policy(self, workspace_id: str, level: ShareLevel,
                         allowed: list[str], shared_paths: list[str]) -> None:
        """设置共享策略"""
        entry = self._entries.get(workspace_id)
        if not entry:
            raise KeyError(f"工作区 {workspace_id} 未注册")
        entry.share_level = level
        entry.allowed_workspaces = allowed
        entry.shared_paths = shared_paths
        self._save()

    def _load(self):
        """从磁盘加载"""
        if self._storage.exists():
            try:
                data = json.loads(self._storage.read_text(encoding="utf-8"))
                for e in data.get("workspaces", []):
                    entry = WorkspaceEntry(
                        id=e["id"],
                        path=e["path"],
                        name=e["name"],
                        share_level=ShareLevel(e.get("share_level", "none")),
                        allowed_workspaces=e.get("allowed_workspaces", []),
                        shared_paths=e.get("shared_paths", []),
                        created_at=e.get("created_at", 0.0),
                    )
                    self._entries[entry.id] = entry
            except (json.JSONDecodeError, OSError, KeyError):
                pass

    def _save(self):
        """持久化到磁盘"""
        self._storage.write_text(
            json.dumps(
                {
                    "workspaces": [
                        {
                            "id": e.id,
                            "path": e.path,
                            "name": e.name,
                            "share_level": e.share_level.value,
                            "allowed_workspaces": e.allowed_workspaces,
                            "shared_paths": e.shared_paths,
                            "created_at": e.created_at,
                        }
                        for e in self._entries.values()
                    ]
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )