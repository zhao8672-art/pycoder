"""
权限策略引擎 - 对Shell/文件/网络操作分级控制

三个等级:
  - allow  : 静默允许
  - ask    : 每次询问用户
  - deny   : 直接拒绝

用法:
    policy = get_permission_policy()
    if policy.check_shell("rm -rf /"):
        # 执行
    else:
        # 拒绝
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class PermissionLevel(Enum):
    ALWAYS_ALLOW = "allow"
    ASK = "ask"
    ASK_REASON = "ask_reason"  # 新增: 询问并说明原因
    DENY = "deny"


@dataclass
class PermissionPolicy:
    """权限策略数据模型"""

    shell: PermissionLevel = PermissionLevel.ASK
    file_write: PermissionLevel = PermissionLevel.ASK
    file_read: PermissionLevel = PermissionLevel.ALWAYS_ALLOW
    network: PermissionLevel = PermissionLevel.ASK
    clipboard: PermissionLevel = PermissionLevel.ASK

    allowed_paths: list[str] = field(default_factory=lambda: ["pycoder/", "tests/", ".skills/"])
    allow_temp: bool = True  # 允许临时文件写入
    max_file_size: int = 10 * 1024 * 1024  # 最大写入文件大小 10MB
    safe_commands: list[str] = field(
        default_factory=lambda: ["git", "pip", "python", "npm", "npx", "node"],
    )

    def to_dict(self) -> dict:
        return {
            "shell": self.shell.value,
            "file_write": self.file_write.value,
            "file_read": self.file_read.value,
            "network": self.network.value,
            "clipboard": self.clipboard.value,
            "allowed_paths": self.allowed_paths,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PermissionPolicy:
        kwargs = {}
        for key in ("shell", "file_write", "file_read", "network", "clipboard"):
            val = data.get(key, "ask")
            try:
                kwargs[key] = PermissionLevel(val)
            except ValueError:
                kwargs[key] = PermissionLevel.ASK
        kwargs["allowed_paths"] = data.get("allowed_paths", ["pycoder/", "tests/", ".skills/"])
        return cls(**kwargs)

    def check_shell(self, command: str) -> tuple[bool, str]:
        return self._check(self.shell, f"shell: {command[:80]}")

    def check_file_write(self, path: str) -> tuple[bool, str]:
        if self._is_in_allowed(path):
            return True, ""
        return self._check(self.file_write, f"write: {path}")

    def check_file_read(self, path: str) -> tuple[bool, str]:
        if self._is_in_allowed(path):
            return True, ""
        return self._check(self.file_read, f"read: {path}")

    def check_network(self, url: str) -> tuple[bool, str]:
        return self._check(self.network, f"network: {url[:80]}")

    def _check(self, level: PermissionLevel, desc: str) -> tuple[bool, str]:
        if level == PermissionLevel.ALWAYS_ALLOW:
            return True, ""
        if level == PermissionLevel.DENY:
            return False, f"已拒绝: {desc}"
        if level == PermissionLevel.ASK_REASON:
            return False, f"ASK_REASON:{desc}"
        return False, f"ASK:{desc}"

    def check_shell_safe(self, command: str) -> tuple[bool, str]:
        """安全命令自动放行"""
        cmd_name = command.strip().split()[0] if command.strip() else ""
        if cmd_name in self.safe_commands:
            return True, ""
        return self.check_shell(command)

    def check_file_size(self, size: int) -> tuple[bool, str]:
        if size > self.max_file_size:
            return False, f"文件大小 {size} 超过限制 {self.max_file_size}"
        return True, ""

    def _is_in_allowed(self, path: str) -> bool:
        p = Path(path).as_posix()
        if self.allow_temp and ("/tmp/" in p or "/Temp/" in p):
            return True
        return any(p.startswith(a) for a in self.allowed_paths)


_POLICY_FILE = Path.home() / ".pycoder" / "permission_policy.json"
_policy: PermissionPolicy | None = None


def _ensure_dir():
    _POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_policy() -> PermissionPolicy:
    try:
        if _POLICY_FILE.exists():
            data = json.loads(_POLICY_FILE.read_text(encoding="utf-8"))
            return PermissionPolicy.from_dict(data)
    except Exception as e:
        logger.warning("policy_load_failed", error=str(e))
    return PermissionPolicy()


def _save_policy(policy: PermissionPolicy):
    _ensure_dir()
    _POLICY_FILE.write_text(
        json.dumps(policy.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_permission_policy() -> PermissionPolicy:
    global _policy
    if _policy is None:
        _policy = _load_policy()
    return _policy


def update_permission_policy(updates: dict) -> PermissionPolicy:
    global _policy
    current = get_permission_policy()
    for key in ("shell", "file_write", "file_read", "network", "clipboard"):
        if key in updates:
            try:
                setattr(current, key, PermissionLevel(updates[key]))
            except ValueError:
                pass
    if "allowed_paths" in updates:
        current.allowed_paths = updates["allowed_paths"]
    _policy = current
    _save_policy(current)
    return current
