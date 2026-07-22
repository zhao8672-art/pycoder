"""跨平台 Shell 命令翻译器 — 解决 Windows/Linux/Mac 命令差异。

提供：
- `ShellTranslator`: 命令白名单 + 平台映射表
- `translate_command(cmd, source='auto', target='auto')`: 将命令翻译为目标平台
- `detect_platform()`: 自动检测当前平台
- `COMMAND_MAP`: 内置 30+ 常用命令映射

使用场景：
1. AI 输出 Linux 命令 → 自动翻译为 Windows 等价命令
2. 用户在 Windows 输入 Linux 命令 → 自动翻译为 Windows
3. 反向亦然
"""
from __future__ import annotations

import re
import shutil
import sys
from dataclasses import dataclass
from typing import Literal

Platform = Literal["windows", "linux", "mac", "auto"]


def detect_platform() -> str:
    """检测当前运行平台."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


# ── 简单命令名映射表（不包含参数）────────────────────────
# 复杂映射（需要参数变换）放在 SPECIAL_RULES 中
COMMAND_MAP: dict[str, dict[str, str]] = {
    # 列表/查找
    "ls": {"windows": "dir", "linux": "ls", "mac": "ls"},
    "ll": {"windows": "dir", "linux": "ls -la", "mac": "ls -la"},
    "cat": {"windows": "type", "linux": "cat", "mac": "cat"},
    "more": {"windows": "more", "linux": "more", "mac": "more"},
    "less": {"windows": "more", "linux": "less", "mac": "less"},
    # 搜索
    "grep": {"windows": "findstr", "linux": "grep", "mac": "grep"},
    "rg": {"windows": "findstr", "linux": "rg", "mac": "rg"},
    "which": {"windows": "where", "linux": "which", "mac": "which"},
    # 文件操作
    "cp": {"windows": "copy", "linux": "cp", "mac": "cp"},
    "mv": {"windows": "move", "linux": "mv", "mac": "mv"},
    "rm": {"windows": "del", "linux": "rm", "mac": "rm"},
    "rmdir": {"windows": "rmdir", "linux": "rmdir", "mac": "rmdir"},
    "mkdir": {"windows": "mkdir", "linux": "mkdir", "mac": "mkdir"},
    "pwd": {"windows": "cd", "linux": "pwd", "mac": "pwd"},
    # 系统信息
    "ps": {"windows": "tasklist", "linux": "ps", "mac": "ps"},
    "kill": {"windows": "taskkill", "linux": "kill", "mac": "kill"},
    "top": {"windows": "tasklist", "linux": "top", "mac": "top"},
    "df": {"windows": "wmic logicaldisk get caption,size,freespace", "linux": "df", "mac": "df"},
    "du": {"windows": "dir /s", "linux": "du", "mac": "du"},
    "free": {"windows": "wmic OS get FreePhysicalMemory", "linux": "free", "mac": "vm_stat"},
    "uname": {"windows": "ver", "linux": "uname", "mac": "uname"},
    "whoami": {"windows": "whoami", "linux": "whoami", "mac": "whoami"},
    "hostname": {"windows": "hostname", "linux": "hostname", "mac": "hostname"},
    "date": {"windows": "echo %DATE%", "linux": "date", "mac": "date"},
    "clear": {"windows": "cls", "linux": "clear", "mac": "clear"},
    # 网络
    "ifconfig": {"windows": "ipconfig", "linux": "ifconfig", "mac": "ifconfig"},
    "ip": {"windows": "ipconfig", "linux": "ip", "mac": "ifconfig"},
    "wget": {"windows": "curl -O", "linux": "wget", "mac": "curl -O"},
    # 文本处理
    "head": {"windows": "powershell -Command \"Get-Content $FILE -Head 10\"", "linux": "head", "mac": "head"},
    "tail": {"windows": "powershell -Command \"Get-Content $FILE -Tail 10\"", "linux": "tail", "mac": "tail"},
    "wc": {"windows": "find /c /v \"\"", "linux": "wc", "mac": "wc"},
    "uniq": {"windows": "powershell -Command \"Get-Content $FILE | Sort-Object -Unique\"", "linux": "uniq", "mac": "uniq"},
    "diff": {"windows": "fc", "linux": "diff", "mac": "diff"},
    # 压缩
    "zip": {"windows": "powershell -Command \"Compress-Archive\"", "linux": "zip", "mac": "zip"},
    "unzip": {"windows": "powershell -Command \"Expand-Archive\"", "linux": "unzip", "mac": "unzip"},
    # 环境
    "export": {"windows": "set", "linux": "export", "mac": "export"},
}


# ── 特殊规则：需要参数变换的命令 ──────────────────────────
# 格式: 命令名 -> { target_platform: 转换函数 }
SPECIAL_RULES: dict[str, dict[str, str]] = {
    # 复杂场景可在 _apply_special_rule 中扩展
}


@dataclass
class TranslationResult:
    """命令翻译结果."""

    original: str
    translated: str
    source_platform: str
    target_platform: str
    changed: bool
    mappings_applied: list[str]


class ShellTranslator:
    """Shell 命令跨平台翻译器.

    用法:
        translator = ShellTranslator()
        result = translator.translate("ls -la", target="windows")
        print(result.translated)  # "dir"
    """

    # 命令分词正则：处理管道 / 重定向 / 引号
    _TOKEN_RE = re.compile(
        r'("[^"]*"|\'[^\']*\'|\S+)',
    )

    def __init__(self, custom_map: dict[str, dict[str, str]] | None = None) -> None:
        self._map = {**COMMAND_MAP}
        if custom_map:
            self._map.update(custom_map)

    def translate(
        self,
        command: str,
        *,
        source: Platform = "auto",
        target: Platform = "auto",
    ) -> TranslationResult:
        """翻译 shell 命令到目标平台.

        Args:
            command: 原始命令
            source: 源平台 (auto = 自动检测)
            target: 目标平台 (auto = 自动检测)

        Returns:
            TranslationResult: 翻译结果（含原始、翻译后、应用映射列表）
        """
        if not command or not command.strip():
            return TranslationResult(
                original=command,
                translated=command,
                source_platform="",
                target_platform="",
                changed=False,
                mappings_applied=[],
            )

        source_platform = detect_platform() if source == "auto" else source
        target_platform = detect_platform() if target == "auto" else target

        if source_platform == target_platform:
            return TranslationResult(
                original=command,
                translated=command,
                source_platform=source_platform,
                target_platform=target_platform,
                changed=False,
                mappings_applied=[],
            )

        tokens = self._tokenize(command)
        mappings_applied: list[str] = []
        translated_tokens: list[str] = []

        for token in tokens:
            translated = self._translate_token(token, source_platform, target_platform)
            if translated != token:
                # 记录应用了哪些映射
                cmd_name = token.split()[0] if token else ""
                if cmd_name in self._map:
                    mappings_applied.append(cmd_name)
            translated_tokens.append(translated)

        translated_cmd = self._join_tokens(translated_tokens)
        changed = translated_cmd != command

        return TranslationResult(
            original=command,
            translated=translated_cmd,
            source_platform=source_platform,
            target_platform=target_platform,
            changed=changed,
            mappings_applied=mappings_applied,
        )

    def _tokenize(self, command: str) -> list[str]:
        """分词：处理引号和空白."""
        return self._TOKEN_RE.findall(command)

    def _translate_token(self, token: str, source: str, target: str) -> str:
        """翻译单个 token（可能是带参数的命令）."""
        # 跳过空 token
        if not token:
            return token

        # 跳过纯参数（不以命令关键字开头）
        if token.startswith("-") or token.startswith("/"):
            return token

        # 跳过包含路径分隔符的 token（已是完整路径）
        if "/" in token or "\\" in token:
            # 但仍尝试翻译首段
            parts = token.split("/", 1) if "/" in token else token.rsplit("\\", 1)
            if isinstance(parts, list) and len(parts) == 2:
                first, rest = parts
                translated_first = self._lookup(first, source, target)
                if translated_first != first:
                    sep = "/" if "/" in token else "\\"
                    return f"{translated_first}{sep}{rest}"
            return token

        # 提取命令名（第一个空白分隔的部分）
        if " " in token:
            cmd_name, rest = token.split(" ", 1)
        else:
            cmd_name, rest = token, ""

        translated_cmd = self._lookup(cmd_name, source, target)
        if translated_cmd == cmd_name:
            return token  # 无映射

        if rest:
            return f"{translated_cmd} {rest}"
        return translated_cmd

    def _lookup(self, cmd_name: str, source: str, target: str) -> str:
        """查表获取目标平台的命令."""
        if cmd_name not in self._map:
            return cmd_name
        return self._map[cmd_name].get(target, cmd_name)

    def _join_tokens(self, tokens: list[str]) -> str:
        """拼接 token 列表为命令字符串."""
        if not tokens:
            return ""
        result = tokens[0]
        for t in tokens[1:]:
            if t.startswith("|"):
                result += " " + t
            elif result.endswith("|"):
                result += " " + t
            else:
                result += " " + t
        return result


# ── 全局单例 + 便捷函数 ──────────────────────────────────────
_translator: ShellTranslator | None = None


def get_translator() -> ShellTranslator:
    """获取全局翻译器单例."""
    global _translator
    if _translator is None:
        _translator = ShellTranslator()
    return _translator


def translate_command(
    command: str,
    *,
    source: Platform = "auto",
    target: Platform = "auto",
) -> TranslationResult:
    """便捷函数：翻译命令到当前平台."""
    return get_translator().translate(command, source=source, target=target)


def translate_to_current_platform(command: str, source: Platform = "auto") -> TranslationResult:
    """便捷函数：翻译命令到当前运行平台."""
    target = detect_platform()
    return translate_command(command, source=source, target=target)


def add_custom_mapping(cmd_name: str, mapping: dict[str, str]) -> None:
    """添加自定义命令映射（运行时扩展，影响所有新创建的 ShellTranslator 实例）.

    自动补全缺失的 platform 键（默认保留原命令名）。
    """
    # 补全缺失的 platform 键
    for p in ("windows", "linux", "mac"):
        if p not in mapping:
            mapping[p] = cmd_name

    # 更新模块级 COMMAND_MAP
    if cmd_name in COMMAND_MAP:
        COMMAND_MAP[cmd_name].update(mapping)
    else:
        COMMAND_MAP[cmd_name] = mapping
    # 同步更新已存在的全局单例
    if _translator is not None:
        if cmd_name in _translator._map:
            _translator._map[cmd_name].update(mapping)
        else:
            _translator._map[cmd_name] = mapping


__all__ = [
    "COMMAND_MAP",
    "Platform",
    "ShellTranslator",
    "TranslationResult",
    "add_custom_mapping",
    "detect_platform",
    "get_translator",
    "translate_command",
    "translate_to_current_platform",
]


if __name__ == "__main__":
    # 快速测试
    test_cmds = [
        "ls -la",
        "cat README.md",
        "grep -r 'TODO' src/",
        "ps aux | grep python",
        "rm -rf build/",
        "find . -name '*.py'",
        "echo $PATH",
    ]
    t = get_translator()
    current = detect_platform()
    target = "windows" if current != "windows" else "linux"

    print(f"Current platform: {current}")
    print(f"Translating to: {target}")
    print("-" * 60)
    for cmd in test_cmds:
        result = t.translate(cmd, target=target)
        marker = "*" if result.changed else " "
        print(f"{marker} {result.original}")
        print(f"  -> {result.translated}")
        if result.mappings_applied:
            print(f"     mapped: {result.mappings_applied}")
