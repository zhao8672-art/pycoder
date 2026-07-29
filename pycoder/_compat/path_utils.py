"""跨平台路径统一工具 — 统一使用 pathlib.Path 处理路径。

提供:
- `to_unix_path(p)`: 将路径转换为 POSIX 风格（/ 分隔符）
- `to_windows_path(p)`: 将路径转换为 Windows 风格（\\ 分隔符）
- `to_native_path(p)`: 将路径转换为当前平台风格
- `normalize_path(p)`: 标准化路径（去除多余分隔符、解析相对路径）
- `is_subpath(parent, child)`: 检查 child 是否在 parent 子树中
- `safe_join(base, *parts)`: 安全路径拼接（防止路径穿越）
- `find_os_path_calls(code)`: 扫描代码中所有 os.path 调用，返回替换建议

v0.7.0: 统一路径处理，消除 os.path 硬编码。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath


def detect_platform() -> str:
    """检测当前平台."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def to_unix_path(p: str | Path) -> str:
    """将路径转换为 POSIX 风格（/ 分隔符）."""
    return PurePosixPath(Path(p)).as_posix()


def to_windows_path(p: str | Path) -> str:
    """将路径转换为 Windows 风格（\\ 分隔符）."""
    return str(PureWindowsPath(Path(p)))


def to_native_path(p: str | Path) -> str:
    """将路径转换为当前平台风格."""
    return str(Path(p))


def normalize_path(p: str | Path) -> str:
    """标准化路径: 解析 . 和 .., 去除多余分隔符."""
    return str(Path(p).resolve())


def is_subpath(parent: str | Path, child: str | Path) -> bool:
    """检查 child 是否在 parent 子树中（安全路径检查）.

    Args:
        parent: 父目录路径
        child: 子路径

    Returns:
        True 如果 child 在 parent 目录树下
    """
    try:
        parent_resolved = Path(parent).resolve()
        child_resolved = Path(child).resolve()
        return child_resolved.is_relative_to(parent_resolved)
    except (ValueError, OSError):
        return False


def safe_join(base: str | Path, *parts: str) -> Path:
    """安全路径拼接 — 防止路径穿越攻击.

    如果拼接结果不在 base 子树中，抛出 ValueError。

    Args:
        base: 基础目录
        *parts: 要拼接的路径组件

    Returns:
        拼接后的 Path 对象

    Raises:
        ValueError: 检测到路径穿越
    """
    base_path = Path(base).resolve()
    result = base_path.joinpath(*parts).resolve()
    if not result.is_relative_to(base_path):
        raise ValueError(f"路径穿越检测: {result} 不在 {base_path} 内")
    return result


# ── os.path 调用检测与替换建议 ──

# os.path 调用 → pathlib 等价物映射
_OS_PATH_MIGRATION_MAP: dict[str, str] = {
    "os.path.abspath(p)": "Path(p).resolve()",
    "os.path.basename(p)": "Path(p).name",
    "os.path.dirname(p)": "Path(p).parent",
    "os.path.exists(p)": "Path(p).exists()",
    "os.path.isfile(p)": "Path(p).is_file()",
    "os.path.isdir(p)": "Path(p).is_dir()",
    "os.path.join(a, b)": "Path(a) / b",
    "os.path.splitext(p)": "Path(p).suffix",
    "os.path.getsize(p)": "Path(p).stat().st_size",
    "os.path.getmtime(p)": "Path(p).stat().st_mtime",
    "os.path.getctime(p)": "Path(p).stat().st_ctime",
    "os.path.split(p)": "(Path(p).parent, Path(p).name)",
    "os.path.relpath(p, start)": 'Path(p).relative_to(start)',
    "os.path.isabs(p)": "Path(p).is_absolute()",
    "os.path.commonpath(paths)": "Path(paths[0]).parent  # 需递归查找",
    "os.path.expanduser(p)": "Path(p).expanduser()",
    "os.path.realpath(p)": "Path(p).resolve()",
    "os.path.samefile(a, b)": "Path(a).resolve() == Path(b).resolve()",
}

# os.path 调用检测正则
_OS_PATH_RE = re.compile(
    r'(os\.path\.\w+)\s*\(([^)]*)\)',
)


def find_os_path_calls(code: str) -> list[dict[str, str]]:
    """扫描代码中所有 os.path 调用，返回替换建议.

    Args:
        code: Python 源代码

    Returns:
        建议列表，每项包含 call, line, suggestion
    """
    suggestions: list[dict[str, str]] = []
    lines = code.split("\n")
    for i, line in enumerate(lines, 1):
        for m in _OS_PATH_RE.finditer(line):
            call = m.group(1)
            # 查找迁移建议
            suggestion = ""
            for pattern, replacement in _OS_PATH_MIGRATION_MAP.items():
                if pattern.startswith(call + "("):
                    suggestion = f"→ {replacement}  # 使用 pathlib"
                    break
            if not suggestion:
                suggestion = f"→ 考虑使用 pathlib.Path 替代 {call}"
            suggestions.append({
                "call": call,
                "line": str(i),
                "suggestion": suggestion,
            })
    return suggestions


def count_os_path_usage(root_dir: str | Path) -> dict[str, int]:
    """统计项目中 os.path 调用的分布情况.

    Args:
        root_dir: 项目根目录

    Returns:
        {文件路径: os.path 调用次数}
    """
    result: dict[str, int] = {}
    root = Path(root_dir)
    for py_file in root.rglob("*.py"):
        # 跳过 __pycache__ 和测试
        if "__pycache__" in str(py_file) or ".pyc" in str(py_file):
            continue
        try:
            code = py_file.read_text(encoding="utf-8", errors="replace")
            count = len(_OS_PATH_RE.findall(code))
            if count > 0:
                result[str(py_file.relative_to(root))] = count
        except (OSError, UnicodeDecodeError):
            pass
    return dict(sorted(result.items(), key=lambda x: -x[1]))


__all__ = [
    "count_os_path_usage",
    "detect_platform",
    "find_os_path_calls",
    "is_subpath",
    "normalize_path",
    "safe_join",
    "to_native_path",
    "to_unix_path",
    "to_windows_path",
]
