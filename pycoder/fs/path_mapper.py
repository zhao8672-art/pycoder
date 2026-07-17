"""
路径映射管理器 — 将用户授权路径映射为 AI 可访问的 fs:// 别名

支持:
  - 别名注册 (fs://docs → D:/Documents)
  - 路径穿越防护
  - 读写权限控制
  - 配置持久化
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_KEY = "fs_mappings"


@dataclass
class PathEntry:
    """路径映射条目"""
    alias: str
    real_path: str
    permission: str = "read"  # read / write / deny


class PathMapper:
    """路径映射管理器"""

    def __init__(self):
        self._mappings: dict[str, PathEntry] = {}
        self._load_from_config()

    def register(self, alias: str, real_path: str, permission: str = "read") -> bool:
        """注册授权路径"""
        real_path = os.path.abspath(os.path.normpath(real_path))
        if not os.path.exists(real_path):
            logger.warning("路径不存在: %s", real_path)
            return False
        if permission not in ("read", "write", "deny"):
            permission = "read"

        self._mappings[alias] = PathEntry(
            alias=alias, real_path=real_path, permission=permission,
        )
        self._save_to_config()
        logger.info("路径映射注册: %s → %s (%s)", alias, real_path, permission)
        return True

    def unregister(self, alias: str) -> bool:
        """移除路径映射"""
        if alias in self._mappings:
            del self._mappings[alias]
            self._save_to_config()
            return True
        return False

    def resolve(self, ai_path: str) -> str | None:
        """将 AI 请求路径解析为真实路径（含安全防护）

        ai_path 格式: "fs://documents/project/main.py"
                      或 "/documents/project/main.py"
        """
        if ai_path.startswith("fs://"):
            parts = ai_path[5:].split("/")
        else:
            parts = ai_path.strip("/").split("/")

        alias = parts[0] if parts else ""
        relative = "/".join(parts[1:]) if len(parts) > 1 else ""

        entry = self._mappings.get(alias)
        if not entry:
            logger.debug("路径别名未注册: %s", alias)
            return None

        if entry.permission == "deny":
            logger.warning("路径访问被拒绝: %s", alias)
            return None

        # 路径穿越防护
        real = os.path.normpath(os.path.join(entry.real_path, relative))
        if not real.startswith(os.path.normpath(entry.real_path)):
            logger.warning("路径穿越检测: %s", real)
            return None

        return real

    def can_write(self, ai_path: str) -> bool:
        """检查是否有写入权限"""
        if ai_path.startswith("fs://"):
            alias = ai_path[5:].split("/")[0]
        else:
            alias = ai_path.strip("/").split("/")[0]
        entry = self._mappings.get(alias)
        return entry is not None and entry.permission == "write"

    def list_mappings(self) -> list[dict]:
        """列出所有映射"""
        return [
            {"alias": e.alias, "path": e.real_path, "permission": e.permission}
            for e in self._mappings.values()
        ]

    def add_workspace(self, workspace_path: str) -> None:
        """自动添加工作区为默认映射"""
        alias = "workspace"
        if alias not in self._mappings:
            self.register(alias, workspace_path, "write")

    def _load_from_config(self):
        """从配置文件加载"""
        try:
            cfg = _load_pycoder_config()
            mappings = cfg.get(CONFIG_KEY, {})
            for alias, data in mappings.items():
                entry = PathEntry(
                    alias=alias,
                    real_path=data.get("path", ""),
                    permission=data.get("permission", "read"),
                )
                if os.path.exists(entry.real_path):
                    self._mappings[alias] = entry
        except Exception as exc:
            logger.debug("路径映射配置加载失败: %s", exc)

    def _save_to_config(self):
        """持久化到配置文件"""
        try:
            cfg = _load_pycoder_config()
            cfg[CONFIG_KEY] = {
                alias: {"path": e.real_path, "permission": e.permission}
                for alias, e in self._mappings.items()
            }
            _save_pycoder_config(cfg)
        except Exception as exc:
            logger.warning("路径映射持久化失败: %s", exc)


def _load_pycoder_config() -> dict:
    config_path = Path.home() / ".pycoder" / "config.json"
    if config_path.exists():
        return json.loads(config_path.read_text(encoding="utf-8"))
    return {}


def _save_pycoder_config(cfg: dict):
    config_path = Path.home() / ".pycoder" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8",
    )


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_mapper: PathMapper | None = None


def get_mapper() -> PathMapper:
    global _mapper
    if _mapper is None:
        _mapper = PathMapper()
    return _mapper
