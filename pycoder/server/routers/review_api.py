"""F5 代码审查 API — diff 审查 / 一键修复 / PR 自动审查

Endpoints:
    POST /api/review/run  — 审查 diff 文本或文件列表，返回结构化 ReviewResult
    POST /api/review/fix  — 为单条 issue 生成修复补丁
    POST /api/review/pr   — 拉取 GitHub PR diff 自动审查，可选回评

复用:
    - pycoder.server.services.review_orchestrator  审查编排
    - pycoder.server.routers.github._load_token/_gh_headers  GitHub 认证
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pycoder.server.services.review_orchestrator import (
    MAX_REVIEW_FILES,
    ReviewIssue,
    ReviewOrchestrator,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/review")

WORKSPACE_ROOT: Path = Path(
    os.environ.get(
        "PYCODER_WORKSPACE",
        str(Path(__file__).resolve().parents[3]),
    )
).resolve()


# ══════════════════════════════════════════════════════════
# 请求/响应模型
# ══════════════════════════════════════════════════════════


class FileInput(BaseModel):
    """待审查文件"""

    path: str = Field(..., description="文件路径")
    content: str = Field("", description="文件内容（或变更片段）")


class ReviewRunRequest(BaseModel):
    """POST /api/review/run 请求体"""

    diff: str = Field("", description="unified diff 文本（与 files 二选一）")
    files: list[FileInput] = Field(default_factory=list, description="文件列表")
    max_files: int = Field(MAX_REVIEW_FILES, ge=1, le=50, description="单次最多审查文件数")
    include_static: bool = Field(True, description="是否运行静态扫描")
    include_llm: bool = Field(True, description="是否调用 LLM 分析")
    scan_dependencies: bool = Field(False, description="是否附带依赖 CVE 扫描")


class IssueInput(BaseModel):
    """POST /api/review/fix 请求体中的 issue"""

    file_path: str
    line_start: int = 1
    line_end: int = 1
    severity: str = "info"
    category: str = "best-practice"
    message: str = ""
    suggestion: str = ""
    fix_patch: str = ""


class ReviewFixRequest(BaseModel):
    """POST /api/review/fix 请求体"""

    issue: IssueInput = Field(..., description="待修复的审查意见")


class ReviewPrRequest(BaseModel):
    """POST /api/review/pr 请求体"""

    owner: str = Field(..., description="仓库所有者")
    repo: str = Field(..., description="仓库名")
    pr_number: int = Field(..., ge=1, description="PR 编号")
    max_files: int = Field(MAX_REVIEW_FILES, ge=1, le=50)
    auto_comment: bool = Field(False, description="是否将审查结果回评到 PR")


# ══════════════════════════════════════════════════════════
# 编排器工厂（测试可 monkeypatch 替换）
# ══════════════════════════════════════════════════════════


def _make_orchestrator(scan_dependencies: bool = False) -> ReviewOrchestrator:
    """创建审查编排器实例."""
    return ReviewOrchestrator(
        scan_dependencies=scan_dependencies,
        project_root=WORKSPACE_ROOT if scan_dependencies else None,
    )


# ══════════════════════════════════════════════════════════
# POST /api/review/run — 审查 diff 或文件列表
# ══════════════════════════════════════════════════════════


@router.post("/run")
async def review_run(req: ReviewRunRequest) -> dict[str, Any]:
    """执行代码审查，返回结构化 ReviewResult."""
    if not req.diff and not req.files:
        raise HTTPException(400, "diff 或 files 至少提供一个")

    orchestrator = _make_orchestrator(scan_dependencies=req.scan_dependencies)
    if req.diff:
        result = await orchestrator.review_diff(
            req.diff,
            max_files=req.max_files,
            include_static=req.include_static,
            include_llm=req.include_llm,
        )
    else:
        result = await orchestrator.review_files(
            [f.model_dump() for f in req.files],
            max_files=req.max_files,
            include_static=req.include_static,
            include_llm=req.include_llm,
        )
    return {"success": True, "result": result.to_dict()}


# ══════════════════════════════════════════════════════════
# POST /api/review/fix — 生成修复补丁
# ══════════════════════════════════════════════════════════


@router.post("/fix")
async def review_fix(req: ReviewFixRequest) -> dict[str, Any]:
    """为单条 issue 生成 unified diff 修复补丁."""
    issue = ReviewIssue(**req.issue.model_dump())
    orchestrator = _make_orchestrator()
    patch = await orchestrator.generate_fix(issue)

    # 生成应用预览（从补丁中提取变更行统计）
    added = sum(
        1 for ln in patch.splitlines() if ln.startswith("+") and not ln.startswith("+++")
    )
    removed = sum(
        1 for ln in patch.splitlines() if ln.startswith("-") and not ln.startswith("---")
    )
    return {
        "success": bool(patch),
        "patch": patch,
        "applied_preview": {
            "file_path": issue.file_path,
            "added": added,
            "removed": removed,
            "changed": bool(patch),
        },
    }


# ══════════════════════════════════════════════════════════
# POST /api/review/pr — 拉取 GitHub PR diff 自动审查
# ══════════════════════════════════════════════════════════


def _format_review_comment(result_dict: dict[str, Any]) -> str:
    """将 ReviewResult 格式化为 Markdown PR 评论."""
    lines = [
        "## 🤖 PyCoder 自动代码审查",
        "",
        f"**总体评分**: {result_dict['overall_score']}/100",
        "",
        f"{result_dict['summary']}",
        "",
    ]
    for issue in result_dict.get("issues", [])[:20]:  # 评论最多展示 20 条
        icon = {
            "critical": "🔴",
            "error": "🟠",
            "warning": "🟡",
            "info": "🔵",
        }.get(issue["severity"], "⚪")
        lines.append(
            f"- {icon} **[{issue['severity']}/{issue['category']}]** "
            f"`{issue['file_path']}:{issue['line_start']}` — {issue['message']}"
        )
        if issue.get("suggestion"):
            lines.append(f"  - 💡 {issue['suggestion']}")
    if len(result_dict.get("issues", [])) > 20:
        lines.append(f"- … 其余 {len(result_dict['issues']) - 20} 条从略")
    return "\n".join(lines)


@router.post("/pr")
async def review_pr(req: ReviewPrRequest) -> dict[str, Any]:
    """拉取 PR diff → 自动审查 → 可选回评到 PR."""
    from pycoder.server.routers.github import _gh_headers, _load_token

    token = _load_token()
    if not token:
        raise HTTPException(401, "未配置 GitHub Token，请先在 GitHub 面板认证")

    # 1. 拉取 PR diff
    headers = _gh_headers(token)
    headers["Accept"] = "application/vnd.github.v3.diff"
    diff_url = f"https://api.github.com/repos/{req.owner}/{req.repo}/pulls/{req.pr_number}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(diff_url, headers=headers, timeout=30)
            if resp.status_code != 200:
                raise HTTPException(
                    resp.status_code, f"拉取 PR diff 失败: GitHub API {resp.status_code}"
                )
            diff_text = resp.text
    except httpx.HTTPError as e:
        raise HTTPException(502, f"GitHub 网络错误: {e}") from e

    if not diff_text.strip():
        return {"success": True, "result": None, "message": "PR 无 diff 内容"}

    # 2. 编排审查
    orchestrator = _make_orchestrator()
    result = await orchestrator.review_diff(diff_text, max_files=req.max_files)
    result_dict = result.to_dict()

    # 3. 可选回评
    comment_url = ""
    if req.auto_comment:
        comment_body = _format_review_comment(result_dict)
        issue_url = (
            f"https://api.github.com/repos/{req.owner}/{req.repo}"
            f"/issues/{req.pr_number}/comments"
        )
        try:
            async with httpx.AsyncClient() as client:
                c_resp = await client.post(
                    issue_url,
                    json={"body": comment_body},
                    headers=_gh_headers(token),
                    timeout=15,
                )
                if c_resp.status_code == 201:
                    comment_url = c_resp.json().get("html_url", "")
                else:
                    logger.warning("pr_comment_failed status=%d", c_resp.status_code)
        except httpx.HTTPError as e:
            logger.warning("pr_comment_network_error error=%s", e)

    return {
        "success": True,
        "result": result_dict,
        "comment_posted": bool(comment_url),
        "comment_url": comment_url,
    }


__all__ = ["router"]
