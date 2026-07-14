"""
Code Search API — 基于 ripgrep 的高性能搜索（含 Python fallback）
"""

from __future__ import annotations

import fnmatch
import logging
import os
import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search")

WORKSPACE_ROOT: Path = Path(
    os.environ.get(
        "PYCODER_WORKSPACE",
        str(Path(__file__).resolve().parents[3]),  # pycode/ (project root)
    )
).resolve()

# 检测 ripgrep 是否可用
_RG_PATH: str | None = shutil.which("rg")

IGNORE_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".env",
    ".idea",
    ".vscode",
    ".DS_Store",
    "dist",
    "build",
    ".egg-info",
    ".mypy_cache",
    ".pytest_cache",
}

IGNORE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".dylib",
    ".exe",
    ".zip",
    ".tar",
    ".gz",
    ".lock",
}


# ── 搜索引擎 ─────────────────────────────────────────────


def _search_with_rg(
    query: str,
    root: Path,
    limit: int = 50,
    file_type: str | None = None,
    regex: bool = False,
    case_sensitive: bool = False,
    whole_word: bool = False,
) -> list[dict]:
    """使用 ripgrep 搜索（高性能）"""
    cmd = [_RG_PATH, "--line-number", "--no-heading", "--color=never", "--max-count", str(limit)]
    if not regex:
        cmd.append("--fixed-strings")
    if not case_sensitive:
        cmd.append("--ignore-case")
    if whole_word:
        cmd.append("--word-regexp")
    if file_type:
        cmd.extend(["--glob", f"**/*{file_type}"])
    # 排除目录
    for d in IGNORE_DIRS:
        cmd.extend(["--glob", f"!{d}/**"])
    cmd.append(query)
    cmd.append(str(root))

    try:
        import re

        # ripgrep 输出格式: file_path:line_num:match_text
        # 用正则解析以正确处理:
        #   1. Windows 盘符 (C:) — split(":",2) 会错误切分
        #   2. match_text 末尾可能含 ":" (如 Python "def f():")
        # 关键: line_num 段必须是纯数字，正则贪婪匹配让 path 尽可能长
        line_re = re.compile(r"^(.+):(\d+):(.*)$")
        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=15
        )
        lines = result.stdout.strip().split("\n")
        results = []
        for line in lines:
            if not line or len(results) >= limit:
                break
            m = line_re.match(line)
            if not m:
                # 行格式不符合 file:line:match → 跳过
                continue
            file_path, line_num, match_text = m.group(1), m.group(2), m.group(3)
            results.append(
                {
                    "file": str(Path(file_path).relative_to(root)),
                    "line": int(line_num),
                    "match": match_text.strip()[:200],
                }
            )
        return results
    except (subprocess.SubprocessError, OSError, ValueError) as e:
        logger.debug("rg_search_failed error=%s", e)
        return []


def _search_python(
    query: str,
    root: Path,
    limit: int = 50,
    file_type: str | None = None,
) -> list[dict]:
    """Python fallback 逐行扫描"""
    results = []
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in IGNORE_EXTENSIONS:
                continue
            if file_type and ext != file_type.lower():
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if query.lower() in line.lower():
                            results.append(
                                {
                                    "file": str(Path(fpath).relative_to(root)),
                                    "line": i,
                                    "match": line.strip()[:200],
                                }
                            )
                            if len(results) >= limit:
                                return results
            except (OSError, UnicodeDecodeError, PermissionError) as e:
                logger.debug("file_read_failed error=%s", e)
    return results


def _search_files(pattern: str, root: Path, limit: int = 50) -> list[str]:
    """按文件名 glob 模式搜索"""
    matches = []
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fname in filenames:
            if fnmatch.fnmatch(fname, pattern):
                matches.append(str(Path(dirpath, fname).relative_to(root)))
                if len(matches) >= limit:
                    return matches
    return matches


# ── 请求模型 ─────────────────────────────────────────────


class SearchRequest(BaseModel):
    query: str
    path: str | None = None
    limit: int = 20
    file_type: str | None = None
    regex: bool = False
    case_sensitive: bool = False
    whole_word: bool = False


# ── API 端点 ─────────────────────────────────────────────


@router.post("/query")
async def search_code(req: SearchRequest):
    """全文搜索（POST，支持正则/大小写/全词匹配）"""
    if not req.query:
        raise HTTPException(400, "Query is required")
    root = Path(req.path) if req.path else WORKSPACE_ROOT

    results = (
        _search_with_rg(
            req.query,
            root,
            req.limit,
            req.file_type,
            req.regex,
            req.case_sensitive,
            req.whole_word,
        )
        if _RG_PATH
        else _search_python(req.query, root, req.limit, req.file_type)
    )

    return {
        "results": results,
        "count": len(results),
        "engine": "ripgrep" if _RG_PATH else "python",
    }


@router.get("")
async def search_code_get(
    query: str = Query(..., description="搜索关键词"),
    path: str | None = None,
    limit: int = Query(20, ge=1, le=200),
    file_type: str | None = None,
):
    """全文搜索（GET 版本，简易搜索）"""
    root = Path(path) if path else WORKSPACE_ROOT
    rg = _RG_PATH is not None
    results = (
        _search_with_rg(query, root, limit, file_type)
        if rg
        else _search_python(query, root, limit, file_type)
    )
    return {"results": results, "count": len(results), "engine": "ripgrep" if rg else "python"}


@router.get("/files")
async def search_files_by_pattern(
    pattern: str = Query(..., description="文件名 glob 模式, 如 *.py"),
    path: str | None = None,
    limit: int = Query(50, ge=1, le=500),
):
    """按文件名搜索"""
    root = Path(path) if path else WORKSPACE_ROOT
    matches = _search_files(pattern, root, limit)
    return {"results": matches, "count": len(matches)}
