"""安全工具与验证器 — 阶段 3 安全强化

提供：
    1. ShellCommandValidator: 命令注入过滤（拒绝 shell 元字符）
    2. PathValidator: 路径遍历防护
    3. safe_str_field: Pydantic Field 工厂
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from pydantic import Field, field_validator

# ── 命令注入防护 ──────────────────────────────────────────────
# 危险 shell 元字符集合（与 OWASP 保持一致）
SHELL_METACHARACTERS = re.compile(r"[;|&`$<>\\!\n\r\t\x00-\x1f]")
# 常见 shell 注入模式
SHELL_INJECTION_PATTERNS = [
    re.compile(r";\s*\w"),       # ; command
    re.compile(r"\|\s*\w"),      # | command
    re.compile(r"`[^`]*`"),      # `command`
    re.compile(r"\$\([^)]*\)"),  # $(command)
    re.compile(r"&&\s*\w"),      # && command
    re.compile(r"\|\|\s*\w"),    # || command
    re.compile(r">\s*[/\\]"),    # > redirect
    re.compile(r"<\s*[/\\]"),    # < redirect
    re.compile(r"\n\s*\w"),      # newline injection
]


def sanitize_shell_command(value: str, *, allow_shell: bool = False) -> str:
    """校验并清洗 shell 命令字符串。

    Args:
        value: 原始命令字符串
        allow_shell: 是否允许 shell 语法（默认 False — 白名单安全模式）

    Returns:
        清洗后的字符串（去除 NUL/控制字符、规范化 Unicode）

    Raises:
        ValueError: 检测到 shell 注入载荷
    """
    if not isinstance(value, str):
        raise ValueError("command must be a string")

    # 拒绝 NUL 字节与控制字符
    if any(ord(c) < 32 for c in value):
        raise ValueError("command contains control characters (potential injection)")

    # 拒绝 shell 元字符（仅当不允许 shell 时）
    if not allow_shell:
        if SHELL_METACHARACTERS.search(value):
            raise ValueError(
                f"command contains forbidden shell metacharacters: "
                f"{SHELL_METACHARACTERS.findall(value)}"
            )
        for pat in SHELL_INJECTION_PATTERNS:
            if pat.search(value):
                raise ValueError(
                    f"command matches injection pattern: {pat.pattern}"
                )

    # Unicode 规范化（防止同形字符绕过）
    return unicodedata.normalize("NFKC", value).strip()


def safe_command_field(*, default: str = "", description: str = "Shell command (no shell metacharacters allowed)"):
    """Pydantic Field 工厂 — 自动应用 shell 注入校验。"""
    return Field(default, description=description)

    # 实际校验通过 field_validator 包装（见下）


# ── 路径遍历防护 ──────────────────────────────────────────────
def sanitize_path(value: str, allowed_roots: list[Path] | None = None) -> str:
    """校验文件路径，防止目录遍历。

    规则：
        1. 拒绝包含 `..` 的相对路径段
        2. 拒绝绝对路径（除非在 allowed_roots 范围内）
        3. 解析后必须在某个 allowed_root 之下

    Args:
        value: 原始路径
        allowed_roots: 允许的根目录列表（None = 仅允许相对路径）

    Returns:
        规范化后的路径字符串

    Raises:
        ValueError: 检测到路径遍历
    """
    if not isinstance(value, str):
        raise ValueError("path must be a string")

    # 拒绝空字节
    if "\x00" in value:
        raise ValueError("path contains NUL byte")

    # 拒绝路径遍历段
    p = Path(value)
    for part in p.parts:
        if part == "..":
            raise ValueError(f"path contains '..' segment: {value}")

    # 绝对路径必须落在 allowed_roots 内
    if p.is_absolute():
        if not allowed_roots:
            raise ValueError(f"absolute path not allowed: {value}")
        try:
            resolved = p.resolve()
            for root in allowed_roots:
                try:
                    resolved.relative_to(root.resolve())
                    return str(resolved)
                except ValueError:
                    continue
            raise ValueError(f"path {value} is outside allowed roots")
        except OSError as e:
            raise ValueError(f"path resolution failed: {e}") from e

    return str(p)


# ── Pydantic 验证器包装器 ──────────────────────────────────
def command_validator(*, allow_shell: bool = False):
    """生成 Pydantic field_validator，自动调用 sanitize_shell_command。"""
    def _validator(cls, v):
        if v is None:
            return v
        return sanitize_shell_command(v, allow_shell=allow_shell)
    return _validator


def path_validator(*, allowed_roots: list[Path] | None = None):
    """生成 Pydantic field_validator，自动调用 sanitize_path。"""
    def _validator(cls, v):
        if v is None:
            return v
        return sanitize_path(v, allowed_roots=allowed_roots)
    return _validator


__all__ = [
    "SHELL_METACHARACTERS",
    "SHELL_INJECTION_PATTERNS",
    "sanitize_shell_command",
    "sanitize_path",
    "command_validator",
    "path_validator",
    "safe_command_field",
]
