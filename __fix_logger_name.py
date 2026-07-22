"""修复 _logger = _logging.getLogger(...) → _logger = logging.getLogger(...)"""
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


def fix_logger_name(rel_path: str) -> str:
    """将 _logger = _logging.getLogger(...) 改为 _logger = logging.getLogger(...)"""
    full_path = ROOT / rel_path
    if not full_path.exists():
        return f"[skip] not found: {rel_path}"

    content = full_path.read_text(encoding="utf-8")
    new_content = re.sub(
        r"^(_logger\s*=\s*)_logging\.getLogger",
        r"\1logging.getLogger",
        content,
        flags=re.MULTILINE,
    )
    if new_content != content:
        full_path.write_text(new_content, encoding="utf-8")
        return f"[fixed] {rel_path}"
    return f"[unchanged] {rel_path}"


if __name__ == "__main__":
    for rel in VIOLATING_FILES:
        msg = fix_logger_name(rel)
        print(msg)
    print("=== Done ===")
