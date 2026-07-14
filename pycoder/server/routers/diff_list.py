"""
Diff List API - List git diffs for files
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diff-list")

WORKSPACE_ROOT: Path = Path(
    os.environ.get(
        "PYCODER_WORKSPACE",
        str(Path(__file__).resolve().parents[3]),  # pycode/ (project root)
    )
).resolve()


@router.get("/list")
async def list_diffs(staged: bool = False, path: str | None = None):
    """List file diffs from Git"""
    repo_path = Path(path) if path else WORKSPACE_ROOT

    try:
        import difflib

        from git import Repo

        repo = Repo(str(repo_path))

        diffs = []

        if staged:
            diff_items = repo.index.diff(repo.head.commit)
        else:
            diff_items = repo.index.diff(None)

        for item in diff_items:
            try:
                if item.change_type == "A":
                    content = item.b_blob.data_stream.read().decode("utf-8", errors="ignore")
                    lines = [
                        {"type": "add", "line_no": i, "content": line}
                        for i, line in enumerate(content.splitlines(), 1)
                    ]
                    diffs.append(
                        {
                            "file": item.b_path,
                            "status": "added",
                            "lines": lines,
                        }
                    )
                elif item.change_type == "D":
                    content = item.a_blob.data_stream.read().decode("utf-8", errors="ignore")
                    lines = [
                        {"type": "del", "line_no": i, "content": line}
                        for i, line in enumerate(content.splitlines(), 1)
                    ]
                    diffs.append(
                        {
                            "file": item.a_path,
                            "status": "deleted",
                            "lines": lines,
                        }
                    )
                elif item.change_type == "M":
                    original = (
                        item.a_blob.data_stream.read().decode("utf-8", errors="ignore")
                        if item.a_blob
                        else ""
                    )
                    modified = (
                        item.b_blob.data_stream.read().decode("utf-8", errors="ignore")
                        if item.b_blob
                        else ""
                    )

                    original_lines = original.splitlines(keepends=True)
                    modified_lines = modified.splitlines(keepends=True)

                    diff_lines = []
                    for line in difflib.unified_diff(
                        original_lines,
                        modified_lines,
                        fromfile=item.a_path,
                        tofile=item.b_path,
                        n=3,
                    ):
                        if line.startswith("@@"):
                            continue
                        elif line.startswith("+") and not line.startswith("+++"):
                            diff_lines.append({"type": "add", "content": line[1:]})
                        elif line.startswith("-") and not line.startswith("---"):
                            diff_lines.append({"type": "del", "content": line[1:]})
                        else:
                            diff_lines.append({"type": "context", "content": line})

                    diffs.append(
                        {
                            "file": item.b_path,
                            "status": "modified",
                            "lines": diff_lines,
                        }
                    )
            except (OSError, UnicodeDecodeError, AttributeError, KeyError) as e:
                logger.debug("diff_item_failed error=%s", e)
                continue

        return {"diffs": diffs}

    except ImportError:
        raise HTTPException(500, "GitPython not installed") from None
    except Exception as e:
        logger.warning("list_diffs_failed error=%s", e)
        return {"diffs": []}
