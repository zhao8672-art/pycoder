"""
Code Diff API — generate unified diff between files/strings

Endpoints:
    POST /api/diff           — Generate diff between two text inputs
    GET  /api/diff/files     — List recent file changes/diffs

Uses Python's built-in difflib (no external deps).
"""

from __future__ import annotations

import difflib
import os
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/diff")

# In-memory store for recent diffs
_recent_diffs: list[dict] = []
_MAX_RECENT = 50

WORKSPACE_ROOT: Path = Path(
    os.environ.get(
        "PYCODER_WORKSPACE",
        str(Path(__file__).resolve().parents[3]),  # pycode/ (project root)
    )
).resolve()


class DiffRequest(BaseModel):
    """Diff generation request"""

    original: str = Field(..., description="Original text/content")
    modified: str = Field(..., description="Modified text/content")
    context_lines: int = Field(3, description="Number of context lines", ge=0, le=50)
    filename: str = Field("file", description="Filename for display")


class DiffResponse(BaseModel):
    """Diff response with unified diff"""

    diff: str
    stats: dict
    changed: bool


@router.post("")
async def generate_diff(req: DiffRequest) -> DiffResponse:
    """
    Generate a unified diff between original and modified text.

    Returns:
        { "diff": "unified diff text", "stats": { "added", "removed", "changed" }, "changed": bool }
    """
    original_lines = req.original.splitlines(keepends=True)
    modified_lines = req.modified.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            original_lines,
            modified_lines,
            fromfile=req.filename,
            tofile=req.filename,
            n=req.context_lines,
        )
    )

    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))

    diff_text = "".join(diff_lines)

    # Store recent diff
    _recent_diffs.insert(
        0,
        {
            "filename": req.filename,
            "timestamp": time.time(),
            "stats": {"added": added, "removed": removed, "changed": len(diff_lines) > 0},
        },
    )
    if len(_recent_diffs) > _MAX_RECENT:
        _recent_diffs.pop()

    return DiffResponse(
        diff=diff_text,
        stats={"added": added, "removed": removed, "changed": len(diff_lines) > 0},
        changed=len(diff_lines) > 0,
    )


class FileDiffRequest(BaseModel):
    """Diff between two file paths"""

    source_path: str = Field(..., description="Path to original file")
    target_path: str | None = Field(
        None, description="Path to modified file (if None, compare source with current content)"
    )
    content: str | None = Field(None, description="New content to diff against file content")
    context_lines: int = Field(3, ge=0, le=50)


@router.post("/file")
async def diff_file(req: FileDiffRequest):
    """Generate diff between a file and new content, or between two files"""

    def _safe_read(path: str) -> str:
        p = Path(path).resolve()
        return p.read_text(encoding="utf-8")

    try:
        source_content = _safe_read(req.source_path)
    except FileNotFoundError as e:
        raise HTTPException(404, f"Source file not found: {req.source_path}") from e
    except Exception as e:
        raise HTTPException(500, f"Error reading source file: {e}") from e

    if req.content is not None:
        modified_content = req.content
    elif req.target_path:
        try:
            modified_content = _safe_read(req.target_path)
        except FileNotFoundError as e:
            raise HTTPException(404, f"Target file not found: {req.target_path}") from e
        except Exception as e:
            raise HTTPException(500, f"Error reading target file: {e}") from e
    else:
        raise HTTPException(400, "Either target_path or content is required")

    original_lines = source_content.splitlines(keepends=True)
    modified_lines = modified_content.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            original_lines,
            modified_lines,
            fromfile=Path(req.source_path).name,
            tofile=Path(req.target_path or req.source_path).name,
            n=req.context_lines,
        )
    )

    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))

    return {
        "diff": "".join(diff_lines),
        "stats": {"added": added, "removed": removed, "changed": len(diff_lines) > 0},
        "changed": len(diff_lines) > 0,
    }


@router.get("/recent")
async def list_recent_diffs(limit: int = Query(10, ge=1, le=50)):
    """List recent diffs"""
    return {"diffs": _recent_diffs[:limit]}


# ══════════════════════════════════════════════════════════
# Hunk 级操作
# ══════════════════════════════════════════════════════════


@router.get("/hunks")
async def parse_diff_hunks(diff_text: str = Query(..., description="Unified diff text")):
    """将 unified diff 解析为独立的 hunk 列表"""
    lines = diff_text.splitlines(keepends=True)
    hunks = []
    current_hunk = None
    hunk_index = 0

    for line in lines:
        if line.startswith("@@"):
            if current_hunk:
                hunks.append(current_hunk)
            current_hunk = {
                "index": hunk_index,
                "header": line.strip(),
                "lines": [],
                "added": 0,
                "removed": 0,
            }
            hunk_index += 1
        elif current_hunk is not None:
            current_hunk["lines"].append(line)
            if line.startswith("+") and not line.startswith("+++"):
                current_hunk["added"] += 1
            elif line.startswith("-") and not line.startswith("---"):
                current_hunk["removed"] += 1

    if current_hunk:
        hunks.append(current_hunk)

    return {"hunks": hunks, "total": len(hunks)}


class HunkInvertRequest(BaseModel):
    """将 diff hunk 反转为原始代码"""

    hunk_lines: list[str] = Field(..., description="Hunk 中的差异行")
    original_context: str = Field("", description="原始上下文（可选）")


@router.post("/hunk/invert")
async def invert_hunk(req: HunkInvertRequest):
    """从 hunk 差异行中提取原始代码（- 行）"""
    original_lines = [ln[1:] for ln in req.hunk_lines if ln.startswith("-")]
    if not original_lines and req.original_context:
        original_lines = req.original_context.splitlines(keepends=True)
    return {"original": "".join(original_lines)}


@router.post("/hunk/apply")
async def apply_hunk_to_file(req: dict):
    """将单个 hunk 的修改应用到文件"""
    file_path = req.get("file_path", "")
    hunk_text = req.get("hunk_text", "")
    action = req.get("action", "accept")  # accept / reject

    if not file_path:
        return {"success": False, "error": "file_path 必填"}

    full_path = (WORKSPACE_ROOT / file_path).resolve()
    # M8: 用 is_relative_to 替代字符串前缀匹配
    if not full_path.is_relative_to(WORKSPACE_ROOT):
        return {"success": False, "error": "路径越界"}

    if not full_path.exists():
        return {"success": False, "error": "文件不存在"}

    if action == "accept":
        current = full_path.read_text(encoding="utf-8")
        # 从 hunk_text 中提取 + 行的内容（移除前导 + 号）
        # 将 hunk 中的 + 行内容作为替代文本
        added_lines = []
        original_lines_from_hunk = []
        for line in hunk_text.splitlines(keepends=True):
            if line.startswith("+") and not line.startswith("+++"):
                added_lines.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                original_lines_from_hunk.append(line[1:])

        if added_lines and original_lines_from_hunk:
            # 在原始文件中找到匹配的原始行并替换
            orig_str = "".join(original_lines_from_hunk)
            new_str = "".join(added_lines)
            if orig_str in current:
                updated = current.replace(orig_str, new_str, 1)
                full_path.write_text(updated, encoding="utf-8")
                return {"success": True, "action": "accepted", "file": file_path}
            return {"success": False, "error": "无法在文件中找到匹配的原始代码段"}
        elif added_lines and not original_lines_from_hunk:
            # 纯新增
            updated = current + "".join(added_lines)
            full_path.write_text(updated, encoding="utf-8")
            return {"success": True, "action": "accepted", "file": file_path}

        return {"success": False, "error": "hunk 中无有效变更行"}

    elif action == "reject":
        return {"success": True, "action": "rejected", "file": file_path}

    return {"success": False, "error": f"未知操作: {action}"}
