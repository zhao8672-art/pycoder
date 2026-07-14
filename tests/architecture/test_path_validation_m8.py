"""M8 测试：确保路径校验使用 is_relative_to() 而非字符串前缀匹配

字符串前缀匹配 ``str(target).startswith(str(root))`` 可被兄弟目录逃逸绕过：
- root = ``/home/user/app``
- target = ``/home/user/app-secret/evil``（resolve 后）
- ``startswith`` 会错误地返回 True

正确做法是使用 ``Path.is_relative_to()``（Python 3.9+）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


PYCODER_ROOT = Path(__file__).resolve().parents[2] / "pycoder"


# 匹配 ``.startswith(str(...root...))`` 的路径校验模式
# 这是不安全的字符串前缀匹配
PREFIX_MATCH_PATTERN = re.compile(
    r'\.startswith\(\s*str\(\s*\w+\s*\)\s*\)',
    re.MULTILINE,
)


_EXCLUDED_DIRS = frozenset({
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".git",
    "site-packages",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
})


def _collect_python_files() -> list[Path]:
    """收集所有 pycoder/ 下的 .py 文件（排除第三方依赖与缓存目录）"""
    if not PYCODER_ROOT.exists():
        return []
    return sorted(
        p for p in PYCODER_ROOT.rglob("*.py")
        if not any(part in _EXCLUDED_DIRS for part in p.parts)
    )


ALL_PYCODER_FILES = _collect_python_files()


def _file_id(path: Path) -> str:
    try:
        return str(path.relative_to(PYCODER_ROOT.parent))
    except ValueError:
        return str(path)


@pytest.mark.parametrize(
    "file_path",
    ALL_PYCODER_FILES,
    ids=[_file_id(f) for f in ALL_PYCODER_FILES],
)
def test_no_string_prefix_path_validation(file_path):
    """M8: 不应使用 ``str(target).startswith(str(root))`` 做路径校验

    应使用 ``Path.is_relative_to()`` 替代。
    """
    content = file_path.read_text(encoding="utf-8")
    matches = PREFIX_MATCH_PATTERN.findall(content)

    # 过滤掉非路径校验的 startswith 使用（如字符串处理）
    # 只关注 ``str(...).startswith(str(...))`` 模式
    path_validation_matches = re.findall(
        r'str\(\s*\w+\s*\)\.startswith\(\s*str\(\s*\w+\s*\)\s*\)',
        content,
    )

    assert not path_validation_matches, (
        f"{file_path.name} 中仍存在 {len(path_validation_matches)} 处 "
        f"字符串前缀匹配路径校验\n"
        f"应替换为 ``Path.is_relative_to()``\n"
        f"匹配: {path_validation_matches}"
    )


def test_is_relative_to_usage_exists():
    """M8: 项目中应存在 is_relative_to 的使用"""
    count = 0
    for f in ALL_PYCODER_FILES:
        content = f.read_text(encoding="utf-8")
        count += content.count("is_relative_to(")
    assert count >= 10, (
        f"项目中 is_relative_to 使用次数仅 {count} 次，"
        f"应至少 10 次（M8 修复后）"
    )
