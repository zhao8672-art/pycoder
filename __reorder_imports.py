"""整理 import 顺序 — 把 _logger 行移到所有 import 之后"""
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


def reorganize_imports(rel_path: str) -> str:
    """收集文件中的所有 import 块，将 _logger 行放在最后"""
    full_path = ROOT / rel_path
    if not full_path.exists():
        return f"[skip] not found: {rel_path}"

    content = full_path.read_text(encoding="utf-8")
    original = content

    # 找到 _logger 行
    logger_match = re.search(
        r"^_logger\s*=\s*logging\.getLogger\([^)]+\)\s*\n",
        content,
        re.MULTILINE,
    )
    if not logger_match:
        return f"[unchanged] {rel_path}"

    logger_line = logger_match.group(0)
    content_no_logger = content.replace(logger_line, "", 1)

    # 找到 _logger 后面第一个 import 行（被错位的 import）
    # 找出第一个空行后的第一个 import
    # 简化策略：在 _logger 之前的所有 import 块已经存在，我们只是把 _logger 行重新插入到最后一个 import 后

    # 找到文件中的所有 import 语句位置
    # 找 from __future__ 后所有 import / from ... import ... 块的最后一个位置
    future_match = re.search(
        r"^from __future__ import annotations\s*\n",
        content_no_logger,
        re.MULTILINE,
    )
    if not future_match:
        return f"[error] no __future__ in {rel_path}"

    # 找 from __future__ 之后的所有 import 语句
    after_future = content_no_logger[future_match.end():]
    import_pattern = re.compile(
        r"^(?:import\s+\S+|from\s+\S+\s+import\s+.+?)\s*\n",
        re.MULTILINE,
    )
    # 找最后一个连续 import 块的结束位置
    last_import_end = 0
    for m in import_pattern.finditer(after_future):
        # 检查 m.end() 之后是否是空行/空行+其他语句
        rest = after_future[m.end():]
        # 如果紧接着是空行+非 import 或仅是空行
        if rest.startswith("\n") or rest.startswith("import ") or rest.startswith("from "):
            last_import_end = m.end()
        else:
            break

    if last_import_end == 0:
        return f"[error] no imports after __future__ in {rel_path}"

    # 插入位置：从 __future__ 结束 + 最后一个 import 结束
    insert_pos = future_match.end() + last_import_end
    new_content = (
        content_no_logger[:insert_pos]
        + "\n"
        + logger_line
        + content_no_logger[insert_pos:]
    )

    if new_content != original:
        full_path.write_text(new_content, encoding="utf-8")
        return f"[fixed] {rel_path}"
    return f"[unchanged] {rel_path}"


if __name__ == "__main__":
    for rel in VIOLATING_FILES:
        msg = reorganize_imports(rel)
        print(msg)
    print("=== Done ===")
