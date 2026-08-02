"""跨平台 Shell 命令翻译器 — 解决 Windows/Linux/Mac 命令差异。

提供：
- `ShellTranslator`: 命令白名单 + 平台映射表
- `translate_command(cmd, source='auto', target='auto')`: 将命令翻译为目标平台
- `detect_platform()`: 自动检测当前平台
- `COMMAND_MAP`: 内置 30+ 常用命令映射
- `OPERATOR_MAP`: shell 操作符跨平台翻译（&&, ||, |, >, <）

使用场景：
1. AI 输出 Linux 命令 → 自动翻译为 Windows 等价命令
2. 用户在 Windows 输入 Linux 命令 → 自动翻译为 Windows
3. 反向亦然
4. 跨平台 shell 脚本移植（处理 && / || / 管道 / 重定向）
"""

from __future__ import annotations

import re
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


# ── shell 操作符翻译（解决 Windows PowerShell 5.x 不支持 && 的问题） ──
# 关键差异：
#   - Linux/Mac bash：  cmd1 && cmd2   cmd1 || cmd2
#   - PowerShell 7+：   支持 && / ||
#   - PowerShell 5.x：  不支持 && / ||  (Windows 默认 shell)
#   - Windows cmd：     不支持 && / ||
# 翻译策略：源 Linux → 目标 Windows 时
#   && →  " ; if ($?) { "        — $? 对 cmdlet/别名/外部 exe 都有效
#   || →  " ; if (-not $?) { "
#   FIX: 之前用 $LASTEXITCODE -eq 0，但 $LASTEXITCODE 只对外部 exe 有效，
#        对 PowerShell 别名（如 dir=Get-ChildItem）不设置，导致条件永远为假。
#        $? 是通用成功标志，对所有命令类型都有效。
#   反向：源 Windows → 目标 Linux 时直接还原
OPERATOR_MAP: dict[str, dict[str, str]] = {
    "&&": {
        "windows": " ; if ($?) { ",
        "linux": " && ",
        "mac": " && ",
    },
    "||": {
        "windows": " ; if (-not $?) { ",
        "linux": " || ",
        "mac": " || ",
    },
    "|": {"windows": " | ", "linux": " | ", "mac": " | "},
    ">": {"windows": " > ", "linux": " > ", "mac": " > "},
    ">>": {"windows": " >> ", "linux": " >> ", "mac": " >> "},
    "<": {"windows": " < ", "linux": " < ", "mac": " < "},
    ";": {"windows": " ; ", "linux": " ; ", "mac": " ; "},
}


# ── 简单命令名映射表（不包含参数）────────────────────────
# 复杂映射（需要参数变换）放在 SPECIAL_RULES 中
# 当前覆盖: 50+ 常用命令（v0.7.0 扩展）
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
    "find": {
        "windows": 'powershell -Command "Get-ChildItem -Recurse -Filter"',
        "linux": "find",
        "mac": "find",
    },
    "locate": {
        "windows": 'powershell -Command "Get-ChildItem -Recurse -Name"',
        "linux": "locate",
        "mac": "mdfind",
    },
    # 文件操作
    "cp": {"windows": "copy", "linux": "cp", "mac": "cp"},
    "mv": {"windows": "move", "linux": "mv", "mac": "mv"},
    "rm": {"windows": "del", "linux": "rm", "mac": "rm"},
    "rmdir": {"windows": "rmdir", "linux": "rmdir", "mac": "rmdir"},
    "mkdir": {"windows": "mkdir", "linux": "mkdir", "mac": "mkdir"},
    "pwd": {"windows": "cd", "linux": "pwd", "mac": "pwd"},
    "touch": {
        "windows": 'powershell -Command "New-Item -ItemType File"',
        "linux": "touch",
        "mac": "touch",
    },
    "chmod": {
        "windows": 'powershell -Command "icacls"',
        "linux": "chmod",
        "mac": "chmod",
    },
    "chown": {
        "windows": 'powershell -Command "icacls /setowner"',
        "linux": "chown",
        "mac": "chown",
    },
    "ln": {
        "windows": "mklink",
        "linux": "ln",
        "mac": "ln",
    },
    "stat": {
        "windows": 'powershell -Command "Get-Item"',
        "linux": "stat",
        "mac": "stat",
    },
    "file": {
        "windows": 'powershell -Command "(Get-Item $FILE).Extension"',
        "linux": "file",
        "mac": "file",
    },
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
    "sleep": {
        "windows": "timeout",
        "linux": "sleep",
        "mac": "sleep",
    },
    "history": {
        "windows": "doskey /history",
        "linux": "history",
        "mac": "history",
    },
    # 网络
    "ifconfig": {"windows": "ipconfig", "linux": "ifconfig", "mac": "ifconfig"},
    "ip": {"windows": "ipconfig", "linux": "ip", "mac": "ifconfig"},
    "wget": {"windows": "curl -O", "linux": "wget", "mac": "curl -O"},
    "curl": {"windows": "curl", "linux": "curl", "mac": "curl"},
    "ping": {"windows": "ping", "linux": "ping", "mac": "ping"},
    "netstat": {"windows": "netstat", "linux": "netstat", "mac": "netstat"},
    "nslookup": {"windows": "nslookup", "linux": "nslookup", "mac": "nslookup"},
    "ssh": {"windows": "ssh", "linux": "ssh", "mac": "ssh"},
    "scp": {"windows": "scp", "linux": "scp", "mac": "scp"},
    # 文本处理
    "head": {
        "windows": 'powershell -Command "Get-Content $FILE -Head 10"',
        "linux": "head",
        "mac": "head",
    },
    "tail": {
        "windows": 'powershell -Command "Get-Content $FILE -Tail 10"',
        "linux": "tail",
        "mac": "tail",
    },
    "wc": {"windows": 'find /c /v ""', "linux": "wc", "mac": "wc"},
    "uniq": {
        "windows": 'powershell -Command "Get-Content $FILE | Sort-Object -Unique"',
        "linux": "uniq",
        "mac": "uniq",
    },
    "diff": {"windows": "fc", "linux": "diff", "mac": "diff"},
    "sed": {
        "windows": 'powershell -Command "(Get-Content $FILE) -replace"',
        "linux": "sed",
        "mac": "sed",
    },
    "awk": {
        "windows": 'powershell -Command "ForEach-Object"',
        "linux": "awk",
        "mac": "awk",
    },
    "sort": {
        "windows": "sort",
        "linux": "sort",
        "mac": "sort",
    },
    "cut": {
        "windows": 'powershell -Command "ForEach-Object { $_.Split() }"',
        "linux": "cut",
        "mac": "cut",
    },
    "tr": {
        "windows": 'powershell -Command "ForEach-Object { $_ -replace }"',
        "linux": "tr",
        "mac": "tr",
    },
    "tee": {
        "windows": 'powershell -Command "Tee-Object"',
        "linux": "tee",
        "mac": "tee",
    },
    "xargs": {
        "windows": 'powershell -Command "ForEach-Object { & $_ }"',
        "linux": "xargs",
        "mac": "xargs",
    },
    # 压缩
    "zip": {"windows": 'powershell -Command "Compress-Archive"', "linux": "zip", "mac": "zip"},
    "unzip": {"windows": 'powershell -Command "Expand-Archive"', "linux": "unzip", "mac": "unzip"},
    "tar": {"windows": "tar", "linux": "tar", "mac": "tar"},
    "gzip": {"windows": "tar -czf", "linux": "gzip", "mac": "gzip"},
    "gunzip": {"windows": "tar -xzf", "linux": "gunzip", "mac": "gunzip"},
    # 环境
    "export": {"windows": "set", "linux": "export", "mac": "export"},
    "env": {"windows": "set", "linux": "env", "mac": "env"},
    "source": {
        "windows": "call",
        "linux": "source",
        "mac": "source",
    },
    "echo": {"windows": "echo", "linux": "echo", "mac": "echo"},
    # 包管理 / 构建工具
    "npx": {"windows": "npx", "linux": "npx", "mac": "npx"},
    "npm": {"windows": "npm", "linux": "npm", "mac": "npm"},
    "node": {"windows": "node", "linux": "node", "mac": "node"},
    "python": {"windows": "python", "linux": "python3", "mac": "python3"},
    "python3": {"windows": "python", "linux": "python3", "mac": "python3"},
    "pip": {"windows": "pip", "linux": "pip", "mac": "pip"},
    "pip3": {"windows": "pip", "linux": "pip3", "mac": "pip3"},
    "make": {"windows": "nmake", "linux": "make", "mac": "make"},
    "systemctl": {
        "windows": "sc",
        "linux": "systemctl",
        "mac": "launchctl",
    },
    "service": {
        "windows": "sc",
        "linux": "service",
        "mac": "launchctl",
    },
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
        # 合并操作符映射 (Windows 翻译时使用)
        self._op_map = {**OPERATOR_MAP}

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

        # 同平台短路：仅当非 Windows 时直接返回。
        # Windows 上即使 source==target==windows，AI 输出的 `&&`/`||` 在
        # PowerShell 5.x 中不受支持，仍需翻译为 `if ($LASTEXITCODE)` 语法。
        if source_platform == target_platform and source_platform != "windows":
            return TranslationResult(
                original=command,
                translated=command,
                source_platform=source_platform,
                target_platform=target_platform,
                changed=False,
                mappings_applied=[],
            )

        # Windows → Windows：仅当命令含 &&/|| 时才需要规范化，否则保持不变
        if (
            source_platform == target_platform == "windows"
            and "&&" not in command
            and "||" not in command
        ):
            return TranslationResult(
                original=command,
                translated=command,
                source_platform=source_platform,
                target_platform=target_platform,
                changed=False,
                mappings_applied=[],
            )

        mappings_applied: list[str] = []

        # Step 1: 翻译 shell 操作符（&&/||/|/> 等）— 整串处理以正确配对
        translated_cmd = self._translate_operators(
            command, source_platform, target_platform, mappings_applied
        )

        # Step 2: 翻译命令名 (按 token 处理)
        tokens = self._tokenize(translated_cmd)
        translated_tokens: list[str] = []
        for token in tokens:
            translated = self._translate_token(token, source_platform, target_platform)
            if translated != token:
                cmd_name = token.split()[0] if token else ""
                if cmd_name in self._map:
                    mappings_applied.append(cmd_name)
            translated_tokens.append(translated)

        final_cmd = self._join_tokens(translated_tokens)
        changed = final_cmd != command

        return TranslationResult(
            original=command,
            translated=final_cmd,
            source_platform=source_platform,
            target_platform=target_platform,
            changed=changed,
            mappings_applied=mappings_applied,
        )

    def _translate_operators(
        self,
        command: str,
        source: str,
        target: str,
        mappings_applied: list[str],
    ) -> str:
        """翻译 shell 操作符（处理 &&/|| 的配对翻译）.

        Linux/Mac → Windows: 把 && 展开为 ; if (...) { ... }
                          必须在每个 && 分段后配对 }
        Windows → Linux/Mac: 反向展开（从 ; if (...) { ... } 还原为 &&）
        """
        if "&&" not in command and "||" not in command:
            # 没有 &&/|| — 但若 source=windows, 需把 if/else 反向还原
            if source == "windows" and target in ("linux", "mac"):
                # 直接返回, 避免 _translate_simple_operators 把 && / || 加多余空格
                return self._collapse_windows_ifs(command, target, mappings_applied)
            return self._translate_simple_operators(command, target)

        if target == "windows":
            # → Windows: && 配对展开（含 Linux→Windows 及 Windows→Windows 规范化）
            # FIX: 使用引号感知分割，避免误切引号内的 && （如 echo "a && b" && ls）
            if "&&" in command:
                parts = self._split_top_level(command, "&&")
                expanded = []
                for i, part in enumerate(parts):
                    part = part.strip()
                    if i == 0:
                        expanded.append(part)
                    else:
                        expanded.append(f"; if ($?) {{ {part} }}")
                result = " ".join(expanded)
                if "&&" in command:
                    mappings_applied.append("&&")
                # 处理 ||（在已经展开的 && 基础上再展开）
                if "||" in result:
                    result = self._expand_or(result, mappings_applied)
                return result
            elif "||" in command:
                return self._expand_or(command, mappings_applied)
        elif source == "windows":
            # Windows → Linux: 反向展开 (从 ; if (...) { ... } 还原)
            return self._collapse_windows_ifs(command, target, mappings_applied)

        return self._translate_simple_operators(command, target)

    def _expand_or(self, command: str, mappings_applied: list[str]) -> str:
        """展开 || 为 if-else 配对。"""
        # FIX: 使用引号感知分割，避免误切引号内的 ||
        parts = self._split_top_level(command, "||")
        expanded = []
        for i, part in enumerate(parts):
            part = part.strip()
            if i == 0:
                expanded.append(part)
            else:
                expanded.append(f"; if (-not $?) {{ {part} }}")
        mappings_applied.append("||")
        return " ".join(expanded)

    def _split_top_level(self, command: str, delimiter: str) -> list[str]:
        """按 delimiter 分割字符串，但忽略引号内的分隔符.

        FIX: 之前 `command.split("&&")` 会误切引号内的 &&，
        例如 `echo "a && b" && ls` 被切成 3 段而非 2 段。
        现在跟踪引号状态（单/双引号），只在引号外分割。

        Args:
            command: 待分割的命令字符串
            delimiter: 分隔符（如 "&&" 或 "||"）

        Returns:
            分割后的段列表
        """
        parts: list[str] = []
        buf: list[str] = []
        i = 0
        n = len(command)
        dlen = len(delimiter)
        in_single = False
        in_double = False
        while i < n:
            ch = command[i]
            # 引号状态切换（仅在另一类引号未开启时）
            if ch == "'" and not in_double:
                in_single = not in_single
                buf.append(ch)
                i += 1
                continue
            if ch == '"' and not in_single:
                in_double = not in_double
                buf.append(ch)
                i += 1
                continue
            # 检查分隔符（仅引号外）
            if not in_single and not in_double and command.startswith(delimiter, i):
                parts.append("".join(buf))
                buf = []
                i += dlen
                continue
            buf.append(ch)
            i += 1
        parts.append("".join(buf))
        return parts

    def _collapse_windows_ifs(self, command: str, target: str, mappings_applied: list[str]) -> str:
        """把 Windows 风格的 ; if (...) { ... } 反向还原为 && 或 ||。"""
        # 模式: ; if ($?) { CMD }  — 新格式（$? 语法）
        result = re.sub(
            r"\s*;\s*if\s*\(\$\?\)\s*\{\s*([^}]*)\s*\}",
            r" && \1 ",
            command,
        )
        if result != command:
            mappings_applied.append("&&")
            command = result
        # 模式: ; if (-not $?) { CMD }  — 新格式
        result = re.sub(
            r"\s*;\s*if\s*\(-not\s*\$\?\)\s*\{\s*([^}]*)\s*\}",
            r" || \1 ",
            command,
        )
        if result != command:
            mappings_applied.append("||")
            command = result
        # 兼容旧格式: ; if ($LASTEXITCODE -eq 0) { CMD }
        result = re.sub(
            r"\s*;\s*if\s*\(\$LASTEXITCODE\s*-eq\s*0\)\s*\{\s*([^}]*)\s*\}",
            r" && \1 ",
            command,
        )
        if result != command:
            mappings_applied.append("&&")
            command = result
        # 兼容旧格式: ; if ($LASTEXITCODE -ne 0) { CMD }
        result = re.sub(
            r"\s*;\s*if\s*\(\$LASTEXITCODE\s*-ne\s*0\)\s*\{\s*([^}]*)\s*\}",
            r" || \1 ",
            command,
        )
        if result != command:
            mappings_applied.append("||")
        return result

    def _translate_simple_operators(self, command: str, target: str) -> str:
        """翻译简单操作符（|, >, <, ;）— 两侧加空格以便 token 切分."""
        result = command
        # 长操作符优先（>> 必须在 > 之前处理）
        for op in (">>", "&&", "||", "|", ">", "<", ";"):
            replacement = self._op_map.get(op, {}).get(target, op)
            if op in result and replacement != op:
                # 在 op 两侧加空格（不替换已经在正确格式的部分）
                result = result.replace(op, replacement)
        return result

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
