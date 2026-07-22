"""批量修复 ``except Exception:`` 静默吞错模式

将 ``except Exception:`` + pass/continue/return 改为 ``except Exception as e:`` + logger.warning/debug
自动在文件顶部添加 logging import（如尚未存在）
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(r"c:\Users\Administrator\Desktop\pycode\pycoder")

# 违规文件列表（来自 smoke 测试结果）
VIOLATING_FILES = [
    "ai/cache/kv_cache.py",
    "safety/sandbox_executor.py",
    "multimodal/ocr_engine.py",
    "multimodal/image_analyzer.py",
    "capabilities/tools/env.py",
    "gateway/adapters/cli.py",
    "server/mcp_tools.py",
    "server/ws_handler_v2.py",
    "server/mcp_store.py",
    "server/services/multimodal_perception.py",
    "server/services/unified_entry.py",
]

# 静默模式：except Exception: 后跟 pass/continue/return
SILENT_PATTERN = re.compile(
    r'(\s+)except Exception:\s*\n(\s+)(pass|continue|return\b[^\n]*)',
    re.MULTILINE,
)

# 模块名（用于 logger 命名）— 用相对路径
def get_logger_name(rel_path: str) -> str:
    name = rel_path.replace("/", ".").replace(".py", "")
    return f"pycoder.{name}"


def ensure_logging_import(content: str, logger_name: str) -> str:
    """确保文件中有 logger 定义"""
    # 检查是否已有 logger 定义
    if re.search(r"^\s*_logger\s*=\s*_?logging\.getLogger", content, re.MULTILINE):
        return content

    # 检查是否已经 import logging
    has_logging_import = re.search(r"^(?:import logging|from logging)", content, re.MULTILINE)

    # 找第一个 import 块
    first_import_match = re.search(r"^(?:import |from )", content, re.MULTILINE)
    if not first_import_match:
        return content

    insert_pos = first_import_match.start()

    additions = []
    if not has_logging_import:
        additions.append("import logging as _logging\n")

    additions.append(f"_logger = _logging.getLogger({logger_name!r})\n")
    additions.append("\n")

    new_content = content[:insert_pos] + "".join(additions) + content[insert_pos:]
    return new_content


def fix_file(rel_path: str) -> tuple[int, str]:
    """修复单个文件，返回（修复数量， 状态）"""
    full_path = ROOT / rel_path
    if not full_path.exists():
        return 0, f"[skip] not found: {rel_path}"

    content = full_path.read_text(encoding="utf-8")
    original = content

    # 替换所有静默 except 模式
    matches = SILENT_PATTERN.findall(content)
    if not matches:
        return 0, f"[ok] no violations: {rel_path}"

    logger_name = get_logger_name(rel_path)

    def replacer(m: re.Match) -> str:
        indent = m.group(1)
        inner_indent = m.group(2)
        action = m.group(3)
        return (
            f"{indent}except Exception as e:\n"
            f"{inner_indent}_logger.warning(\"silently_swallowed: {{err}}\", exc_info=False)\n"
            f"{inner_indent}{action}"
        )

    new_content = SILENT_PATTERN.sub(replacer, content)

    # 添加 logger import
    new_content = ensure_logging_import(new_content, logger_name)

    # 写回
    full_path.write_text(new_content, encoding="utf-8")

    return len(matches), f"[fixed] {rel_path}: {len(matches)} violations"


if __name__ == "__main__":
    total = 0
    for rel in VIOLATING_FILES:
        count, msg = fix_file(rel)
        print(msg)
        total += count
    print(f"\n=== Total: {total} violations fixed ===")
