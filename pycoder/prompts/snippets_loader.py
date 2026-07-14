"""
代码片段系统 — 自动扫描 .snippets/ 和 ~/.pycoder/snippets/ 目录

格式: JSON 文件，key=快捷词，value=模板（支持 {variable} 占位符）
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SNIPPETS_DIRS: list[Path] = []


def _init_dirs():
    if SNIPPETS_DIRS:
        return
    dirs = [
        Path.cwd() / ".snippets",
        Path.home() / ".pycoder" / "snippets",
    ]
    SNIPPETS_DIRS.extend(dirs)


def load_snippets(language: str = "python") -> dict[str, dict]:
    """
    加载语言对应的代码片段。

    Returns:
        {"prefix": {"description": "...", "body": "..."}}
    """
    _init_dirs()
    result: dict[str, dict] = {}

    for snippets_dir in SNIPPETS_DIRS:
        json_file = snippets_dir / f"{language}.json"
        if not json_file.exists():
            continue
        try:
            content = json_file.read_text(encoding="utf-8")
            import re

            blocks = re.split(r"\n?^---$\n?", content, flags=re.MULTILINE)

            # Snippet entries: meta block then body block at alternating positions.
            # Walk blocks, pair each prefix: block with its next non-blank block.
            i = 0
            while i < len(blocks) - 1:
                meta_block = blocks[i].strip()
                if "prefix:" in meta_block:
                    # Find the next non-blank body block
                    j = i + 1
                    while j < len(blocks):
                        body_block = blocks[j].strip()
                        if (
                            body_block
                            and "prefix:" not in body_block.split("\n")[0]
                            and len(body_block) >= 10
                        ):
                            break
                        j += 1

                    if j < len(blocks):
                        body_block = blocks[j].strip()
                        meta = {}
                        for line in meta_block.split("\n"):
                            line = line.strip()
                            if line.startswith("prefix:"):
                                meta["prefix"] = line.split(":", 1)[1].strip()
                            elif line.startswith("description:"):
                                meta["description"] = line.split(":", 1)[1].strip()

                        body = body_block
                        if body.startswith("```"):
                            lines = body.split("\n")
                            body = "\n".join(lines[1:-1]) if len(lines) > 2 else body

                        if meta.get("prefix") and body:
                            result[meta["prefix"]] = {
                                "description": meta.get("description", ""),
                                "body": body,
                            }
                        i = j
                i += 1
        except Exception as e:
            # 注意：标准 logging 不接受任意 kwarg，使用 %s 格式化
            logger.warning("snippets_load_error: file=%s error=%s", json_file, e)

    return result


def get_snippet(language: str, prefix: str) -> dict | None:
    return load_snippets(language).get(prefix)


def list_snippets(language: str = "python") -> list[dict]:
    result = []
    for prefix, info in load_snippets(language).items():
        result.append(
            {
                "prefix": prefix,
                "description": info["description"],
                "body": info["body"][:100] + ("..." if len(info["body"]) > 100 else ""),
            }
        )
    return result
