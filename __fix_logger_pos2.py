"""修复 _logger 行位置 — 必须位于 import logging 之后"""
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


def fix_logger_after_logging_import(rel_path: str) -> str:
    """将 _logger 行移到 import logging 之后"""
    full_path = ROOT / rel_path
    if not full_path.exists():
        return f"[skip] not found: {rel_path}"

    content = full_path.read_text(encoding="utf-8")

    # 找到 _logger 行
    logger_line_match = re.search(
        r"^_logger\s*=\s*_?logging\.getLogger\([^)]+\)\s*\n",
        content,
        re.MULTILINE,
    )
    if not logger_line_match:
        return f"[ok] no _logger line in {rel_path}"

    logger_line = logger_line_match.group(0)

    # 删除当前位置的 logger 行
    content_no_logger = content.replace(logger_line, "", 1)

    # 找 import logging 行
    logging_import_match = re.search(
        r"^(import logging(?:\s+as\s+_logging)?\s*\n)",
        content_no_logger,
        re.MULTILINE,
    )
    if not logging_import_match:
        return f"[error] no import logging in {rel_path}"

    insert_pos = logging_import_match.end()
    new_content = (
        content_no_logger[:insert_pos]
        + "\n"
        + logger_line
        + content_no_logger[insert_pos:]
    )

    if new_content != content:
        full_path.write_text(new_content, encoding="utf-8")
        return f"[fixed] {rel_path}"
    return f"[unchanged] {rel_path}"


if __name__ == "__main__":
    for rel in VIOLATING_FILES:
        msg = fix_logger_after_logging_import(rel)
        print(msg)
    print("=== Done ===")
