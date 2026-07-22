"""修复 __fix_bare_except.py 错误插入的 _logger 行

将 `_logger = _logging.getLogger(...)` 从 `from __future__` 之前移动到 `from __future__` 之后
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(r"c:\Users\Administrator\Desktop\pycode\pycoder")

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


def fix_logger_position(rel_path: str) -> str:
    """将 _logger 移到 from __future__ 之后"""
    full_path = ROOT / rel_path
    if not full_path.exists():
        return f"[skip] not found: {rel_path}"

    content = full_path.read_text(encoding="utf-8")
    original = content

    # 匹配 _logger 行
    logger_line_pattern = re.compile(
        r"^_logger\s*=\s*_?logging\.getLogger\([^)]+\)\s*\n",
        re.MULTILINE,
    )

    logger_match = logger_line_pattern.search(content)
    if not logger_match:
        return f"[ok] no misplaced logger in {rel_path}"

    logger_line = logger_match.group(0)

    # 移除原位置的 logger 行
    content_without_logger = content.replace(logger_line, "", 1)

    # 在 from __future__ import annotations 之后插入 logger 行
    future_pattern = re.compile(
        r"^(from __future__ import annotations\s*\n)",
        re.MULTILINE,
    )
    future_match = future_pattern.search(content_without_logger)
    if not future_match:
        return f"[error] no __future__ in {rel_path}"

    # 在 future 行后插入 logger 行
    insert_pos = future_match.end()
    new_content = (
        content_without_logger[:insert_pos]
        + "\n"
        + logger_line
        + content_without_logger[insert_pos:]
    )

    # 如果有重复的 logger = logging.getLogger(__name__)，删除它（保留我们的 _logger）
    # 但只有当原文件已有 logger = 时才删除
    duplicate_pattern = re.compile(
        r"^logger\s*=\s*logging\.getLogger\(__name__\)\s*\n",
        re.MULTILINE,
    )
    # 保留 logger（向下兼容），不删除

    if new_content != original:
        full_path.write_text(new_content, encoding="utf-8")
        return f"[fixed] {rel_path}"
    return f"[unchanged] {rel_path}"


if __name__ == "__main__":
    for rel in VIOLATING_FILES:
        msg = fix_logger_position(rel)
        print(msg)
    print("=== Done ===")
