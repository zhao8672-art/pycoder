"""gh_permissions 数据模型和异常定义。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


# ── 数据模型 ──────────────────────────────────────────────


@dataclass
class PermissionResult:
    """权限检查结果。

    Attributes:
        ok: 是否全部检查通过
        authenticated: gh CLI 是否已认证
        token_valid: token 是否有效 (API 调用成功)
        username: 当前认证的用户名 (token 无效时为 None)
        current_scopes: 当前 token 拥有的 scope 列表
        required_scopes: 本次检查要求的 scope 列表
        missing_scopes: 缺失的 scope 列表
        error: 错误信息 (检查失败时填充)
        refreshed: 是否执行过 scope 刷新
        refresh_attempts: 刷新尝试次数
        elapsed: 检查耗时秒数
    """

    ok: bool = False
    authenticated: bool = False
    token_valid: bool = False
    username: str | None = None
    current_scopes: list[str] = field(default_factory=list)
    required_scopes: list[str] = field(default_factory=list)
    missing_scopes: list[str] = field(default_factory=list)
    error: str | None = None
    refreshed: bool = False
    refresh_attempts: int = 0
    elapsed: float = 0.0

    def to_dict(self) -> dict:
        """转为字典 (用于 JSON 输出)。"""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """转为 JSON 字符串。"""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
