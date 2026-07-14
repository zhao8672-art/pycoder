"""P3-3 测试：确保所有 pycoder/ 文件无裸 ``except Exception:`` 静默吞错

扩展 P1-3 的检查范围：从 4 个关键文件扩展到所有 pycoder/ 下的 .py 文件。

不允许的模式（静默吞错）：
- ``except Exception:`` 后跟 ``pass``
- ``except Exception:`` 后跟 ``continue``
- ``except Exception:`` 后跟 ``return``

允许的边界兜底：
- ``except Exception as e:`` + ``logger.xxx(...)``（明确记录日志）
- ``except Exception as e:`` + ``return {...}``（API 边界层返回错误给客户端）
- WebSocket / API 顶层 catch-all（但必须 send error 给客户端）
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


PYCODER_ROOT = Path(__file__).resolve().parents[2] / "pycoder"


# 匹配 ``except Exception:`` (不带 as e) 后跟 pass/continue/return
# 注意：不匹配 ``except Exception as e:``（带 as e 的允许）
BARE_EXCEPT_SILENT_PATTERN = re.compile(
    r'except\s+Exception\s*:\s*\n\s*(?:pass|continue|return\b)',
    re.MULTILINE,
)

# 匹配 ``except Exception as e:`` 后跟 ``pass``（带 as e 但仍静默吞错）
EXCEPT_AS_E_PASS_PATTERN = re.compile(
    r'except\s+Exception\s+as\s+\w+\s*:\s*\n\s*pass',
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
    files = []
    for p in sorted(PYCODER_ROOT.rglob("*.py")):
        if any(part in _EXCLUDED_DIRS for part in p.parts):
            continue
        files.append(p)
    return files


ALL_PYCODER_FILES = _collect_python_files()


def _file_id(path: Path) -> str:
    """生成可读的测试 ID"""
    try:
        return str(path.relative_to(PYCODER_ROOT.parent))
    except ValueError:
        return str(path)


@pytest.mark.parametrize(
    "file_path",
    ALL_PYCODER_FILES,
    ids=[_file_id(f) for f in ALL_PYCODER_FILES],
)
def test_no_bare_except_silent_in_all_pycoder_files(file_path):
    """P3-3: 所有 pycoder/ 文件不应有 ``except Exception:`` 后跟 pass/continue/return

    ``except Exception:`` (不带 ``as e``) 后跟静默操作是禁止的。
    应替换为：
    1. 具体异常类型 + logger（首选）
    2. ``except Exception as e:`` + logger（边界兜底）
    """
    content = file_path.read_text(encoding="utf-8")
    matches = BARE_EXCEPT_SILENT_PATTERN.findall(content)

    assert not matches, (
        f"{file_path.name} 中仍存在 {len(matches)} 处 "
        f"``except Exception:`` 后跟 pass/continue/return\n"
        f"应替换为具体异常类型 + logger，或 ``except Exception as e:`` + logger"
    )


@pytest.mark.parametrize(
    "file_path",
    ALL_PYCODER_FILES,
    ids=[_file_id(f) for f in ALL_PYCODER_FILES],
)
def test_no_except_as_e_pass_in_all_pycoder_files(file_path):
    """P3-3: 不应有 ``except Exception as e: pass``（捕获了 e 却不用）"""
    content = file_path.read_text(encoding="utf-8")
    matches = EXCEPT_AS_E_PASS_PATTERN.findall(content)

    assert not matches, (
        f"{file_path.name} 中仍存在 {len(matches)} 处 "
        f"``except Exception as e: pass``\n"
        f"捕获了 e 却不用，应至少加 logger.warning/debug"
    )


def test_p3_3_fix_count_summary():
    """P3-3 完成后，全项目裸 except Exception 应为 0"""
    total_violations = 0
    violating_files = []

    for f in ALL_PYCODER_FILES:
        content = f.read_text(encoding="utf-8")
        silent = len(BARE_EXCEPT_SILENT_PATTERN.findall(content))
        as_pass = len(EXCEPT_AS_E_PASS_PATTERN.findall(content))
        total = silent + as_pass
        if total > 0:
            violating_files.append((f.name, silent, as_pass))
            total_violations += total

    assert total_violations == 0, (
        f"P3-3 未完成：{len(violating_files)} 个文件中仍有 {total_violations} 处违规\n"
        + "\n".join(
            f"  {name}: {s} silent + {p} as-pass"
            for name, s, p in violating_files
        )
    )
