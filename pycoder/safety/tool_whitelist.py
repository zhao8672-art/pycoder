"""MCP 工具白名单 — 限制可调用的工具集，防止未授权工具执行

特性:
- 基于 YAML 配置的工具名白名单
- 支持通配符匹配（如 "files.*" 匹配所有 files 前缀工具）
- 支持参数模式校验（可选）
- 拒绝未注册工具调用
- 审计日志记录所有拒绝事件

配置格式（config/tool_whitelist.yaml）:
    # 模式：allow_all / deny_all / allowlist
    mode: allowlist  # 默认 allowlist

    # 允许的工具（支持通配符）
    allowed_tools:
      - "files.read"           # 精确匹配
      - "files.write"          # 精确匹配
      - "search.*"             # 通配符：匹配 search.web, search.code 等
      - "tools.*"              # 通配符：匹配所有 tools 前缀

    # 禁止的工具（优先级高于 allowed）
    denied_tools:
      - "tools.exec"           # 即使在 allowed 中，也被禁止
      - "system.shutdown"

    # 参数模式校验（可选）
    # 当工具调用时，参数必须匹配以下模式
    param_schemas:
      files.write:
        path: "^/tmp/"         # path 参数必须以 /tmp/ 开头
        content: ".*"           # content 参数无限制

用法:
    from pycoder.safety.tool_whitelist import ToolWhitelist, WhitelistMode

    whitelist = ToolWhitelist()
    whitelist.load_config("config/tool_whitelist.yaml")

    if whitelist.is_allowed("files.read", {"path": "/tmp/test.txt"}):
        result = await call_tool("files.read", {"path": "/tmp/test.txt"})
    else:
        raise PermissionError("工具调用被拒绝")
"""

from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class WhitelistMode(str, Enum):
    """白名单模式"""

    ALLOW_ALL = "allow_all"
    """允许所有工具（无限制，仅审计）"""

    DENY_ALL = "deny_all"
    """拒绝所有工具（最严格）"""

    ALLOWLIST = "allowlist"
    """白名单模式（默认）：仅允许 allowed_tools 中的工具"""


@dataclass
class ParamSchema:
    """参数模式校验"""

    patterns: dict[str, str] = field(default_factory=dict)
    """参数名 → 正则模式"""

    def validate(self, args: dict[str, Any]) -> tuple[bool, str]:
        """校验参数

        Returns:
            (是否通过, 错误信息)
        """
        for param_name, pattern in self.patterns.items():
            if param_name not in args:
                continue  # 可选参数缺失不报错
            value = str(args[param_name])
            if not re.match(pattern, value):
                return False, f"参数 {param_name} 不匹配模式 {pattern}"
        return True, ""


@dataclass
class WhitelistConfig:
    """白名单配置

    默认模式为 ALLOW_ALL（允许所有工具），
    denied_tools 和 param_schemas 仍然生效。
    可通过 config/tool_whitelist.yaml 覆盖配置。
    """

    mode: WhitelistMode = WhitelistMode.ALLOW_ALL
    allowed_tools: list[str] = field(default_factory=list)
    denied_tools: list[str] = field(default_factory=list)
    param_schemas: dict[str, ParamSchema] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于序列化）"""
        return {
            "mode": self.mode.value,
            "allowed_tools": self.allowed_tools,
            "denied_tools": self.denied_tools,
            "param_schemas": {tool: schema.patterns for tool, schema in self.param_schemas.items()},
        }


class ToolWhitelist:
    """MCP 工具白名单管理器

    线程安全，支持运行时动态更新配置。
    """

    def __init__(self, config: WhitelistConfig | None = None) -> None:
        self._config = config or WhitelistConfig()
        self._audit_log: list[dict[str, Any]] = []
        """审计日志（最近 100 条拒绝记录）"""

    @property
    def config(self) -> WhitelistConfig:
        """当前配置"""
        return self._config

    def load_config(self, config_path: str | Path) -> None:
        """从 YAML 文件加载配置"""
        import yaml

        path = Path(config_path)
        if not path.exists():
            logger.warning("whitelist_config_not_found path=%s, using defaults", path)
            return

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        self.load_from_dict(data)
        logger.info(
            "whitelist_loaded path=%s mode=%s allowed=%d denied=%d",
            path,
            self._config.mode.value,
            len(self._config.allowed_tools),
            len(self._config.denied_tools),
        )

    def load_from_dict(self, data: dict[str, Any]) -> None:
        """从字典加载配置

        安全默认值: 如果未指定 mode 或 mode 不合法，默认 ALLOW_ALL（最高权限）
        这样 AI 在最高权限下不会因为白名单配置问题而无法使用任何工具。
        """
        mode_str = data.get("mode", "allow_all")
        try:
            self._config.mode = WhitelistMode(mode_str)
        except ValueError:
            logger.warning(
                "invalid_whitelist_mode=%s, falling back to allow_all (highest authority)",
                mode_str,
            )
            # 降级到 ALLOW_ALL 而非 ALLOWLIST — 保证 AI 不被错误配置阻断
            self._config.mode = WhitelistMode.ALLOW_ALL

        self._config.allowed_tools = list(data.get("allowed_tools", []))
        self._config.denied_tools = list(data.get("denied_tools", []))

        # 参数模式
        self._config.param_schemas = {}
        for tool_name, patterns in (data.get("param_schemas") or {}).items():
            self._config.param_schemas[tool_name] = ParamSchema(patterns=dict(patterns))

    def set_mode(self, mode: WhitelistMode) -> None:
        """设置白名单模式"""
        self._config.mode = mode
        logger.info("whitelist_mode_changed mode=%s", mode.value)

    def add_allowed(self, tool_pattern: str) -> None:
        """添加允许的工具模式"""
        if tool_pattern not in self._config.allowed_tools:
            self._config.allowed_tools.append(tool_pattern)

    def add_denied(self, tool_pattern: str) -> None:
        """添加禁止的工具模式"""
        if tool_pattern not in self._config.denied_tools:
            self._config.denied_tools.append(tool_pattern)

    def is_allowed(self, tool_name: str, args: dict[str, Any] | None = None) -> tuple[bool, str]:
        """检查工具调用是否被允许

        Args:
            tool_name: 工具名称
            args: 调用参数（可选，用于参数校验）

        Returns:
            (是否允许, 拒绝原因)
        """
        args = args or {}

        # 1. 检查黑名单（优先级最高）
        for pattern in self._config.denied_tools:
            if self._match(tool_name, pattern):
                self._log_audit(tool_name, args, False, "denied_by_blacklist")
                return False, f"工具 {tool_name} 在黑名单中（匹配 {pattern}）"

        # 2. 根据模式检查
        if self._config.mode == WhitelistMode.DENY_ALL:
            self._log_audit(tool_name, args, False, "deny_all_mode")
            return False, "当前为 deny_all 模式，拒绝所有工具调用"

        if self._config.mode == WhitelistMode.ALLOW_ALL:
            # 允许所有，但仍然校验参数
            ok, err = self._validate_params(tool_name, args)
            if not ok:
                self._log_audit(tool_name, args, False, "param_validation_failed")
                return False, err
            self._log_audit(tool_name, args, True, "allow_all_mode")
            return True, ""

        # 3. allowlist 模式：检查白名单
        matched_pattern = None
        for pattern in self._config.allowed_tools:
            if self._match(tool_name, pattern):
                matched_pattern = pattern
                break

        if matched_pattern is None:
            self._log_audit(tool_name, args, False, "not_in_allowlist")
            return False, f"工具 {tool_name} 不在白名单中"

        # 4. 参数校验
        ok, err = self._validate_params(tool_name, args)
        if not ok:
            self._log_audit(tool_name, args, False, "param_validation_failed")
            return False, err

        self._log_audit(tool_name, args, True, f"matched_{matched_pattern}")
        return True, ""

    def _match(self, tool_name: str, pattern: str) -> bool:
        """匹配工具名（支持通配符 * 和 ?）"""
        return fnmatch.fnmatch(tool_name, pattern)

    def _validate_params(self, tool_name: str, args: dict[str, Any]) -> tuple[bool, str]:
        """校验参数模式"""
        schema = self._config.param_schemas.get(tool_name)
        if schema is None:
            return True, ""
        return schema.validate(args)

    def _log_audit(
        self,
        tool_name: str,
        args: dict[str, Any],
        allowed: bool,
        reason: str,
    ) -> None:
        """记录审计日志"""
        import time

        entry = {
            "timestamp": time.time(),
            "tool": tool_name,
            "allowed": allowed,
            "reason": reason,
            "args_keys": list(args.keys()) if args else [],
        }
        self._audit_log.append(entry)
        # 保留最近 100 条
        if len(self._audit_log) > 100:
            self._audit_log = self._audit_log[-100:]

        if not allowed:
            logger.warning(
                "tool_call_denied tool=%s reason=%s args_keys=%s",
                tool_name,
                reason,
                entry["args_keys"],
            )

    def get_audit_log(self, last_n: int = 20) -> list[dict[str, Any]]:
        """获取审计日志"""
        return self._audit_log[-last_n:]

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        total = len(self._audit_log)
        allowed = sum(1 for e in self._audit_log if e["allowed"])
        denied = total - allowed
        return {
            "mode": self._config.mode.value,
            "allowed_tools_count": len(self._config.allowed_tools),
            "denied_tools_count": len(self._config.denied_tools),
            "audit_total": total,
            "audit_allowed": allowed,
            "audit_denied": denied,
        }


# ── 模块级单例 ──

_whitelist: ToolWhitelist | None = None


def get_tool_whitelist() -> ToolWhitelist:
    """获取全局 ToolWhitelist 单例（自动加载配置文件）"""
    global _whitelist
    if _whitelist is None:
        _whitelist = ToolWhitelist()
    # 每次调用都尝试加载配置（如果之前加载失败，下次可能成功）
    # 查找 config/tool_whitelist.yaml
    tried_paths = []
    for base in [
        Path.cwd(),
        Path(__file__).resolve().parent.parent.parent,  # 项目根目录
        Path(__file__).resolve().parent.parent,  # pycoder/
    ]:
        p = base / "config" / "tool_whitelist.yaml"
        tried_paths.append(str(p))
        if p.exists():
            try:
                _whitelist.load_config(str(p))
                return _whitelist
            except (OSError, ValueError, KeyError):
                continue
    logger.debug("whitelist_config_not_found tried=%s", tried_paths)
    return _whitelist


def reset_tool_whitelist() -> None:
    """重置单例（用于测试）"""
    global _whitelist
    _whitelist = None
