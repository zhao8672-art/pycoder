"""P2-1: 自动补丁生成 REST API

端点:
- POST /api/patch/generate        - 从文件变更生成补丁
- POST /api/patch/preview         - 预览补丁（dry-run）
- POST /api/patch/apply           - 应用补丁
- POST /api/patch/rollback        - 回滚
- GET  /api/patch/list            - 列出已保存的补丁
- GET  /api/patch/{patch_id}      - 获取补丁详情
- POST /api/patch/{patch_id}/commit   - 提交补丁
- POST /api/patch/{patch_id}/pr       - 生成 PR 草稿
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pycoder.python.auto_patch import (
    FileChange,
    GitIntegration,
    Patch,
    PatchApplier,
    PatchGenerator,
    create_and_apply_patch,
    generate_pr_draft,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/patch", tags=["patch"])


# ── Pydantic 模型 ──────────────────────────────────────


class FileChangeModel(BaseModel):
    file_path: str
    old_content: str = ""
    new_content: str = ""
    operation: str = Field(default="modify", pattern="^(modify|create|delete)$")
    description: str = ""


class GenerateRequest(BaseModel):
    title: str
    description: str = ""
    changes: list[FileChangeModel]
    author: str = "pycoder-bot"
    project_root: str | None = None


class GenerateResponse(BaseModel):
    id: str
    title: str
    status: str
    files: int
    diff: str
    patch_file: str
    add_lines: int = 0
    del_lines: int = 0


class ApplyRequest(BaseModel):
    patch_id: str
    dry_run: bool = False
    project_root: str | None = None


class ApplyResponse(BaseModel):
    success: bool
    applied: list[str]
    errors: list[str]
    backup: str | None = None
    dry_run: bool


class RollbackRequest(BaseModel):
    backup_id: str
    project_root: str | None = None


class CommitRequest(BaseModel):
    patch_id: str
    create_branch: bool = True
    push: bool = False
    project_root: str | None = None


class CommitResponse(BaseModel):
    success: bool
    status: str
    branch: str = ""
    commit_sha: str = ""
    pr_draft: dict | None = None


# ── 端点 ──────────────────────────────────────────────


def _get_generator(project_root: str | None) -> PatchGenerator:
    root = Path(project_root) if project_root else None
    return PatchGenerator(project_root=root)


def _get_applier(project_root: str | None) -> PatchApplier:
    root = Path(project_root) if project_root else None
    return PatchApplier(project_root=root)


@router.post("/generate", response_model=GenerateResponse)
async def generate_patch(req: GenerateRequest) -> GenerateResponse:
    """生成补丁（不应用）"""
    if not req.changes:
        raise HTTPException(status_code=400, detail="至少需要一个文件变更")

    gen = _get_generator(req.project_root)
    changes = [
        FileChange(
            file_path=c.file_path,
            old_content=c.old_content,
            new_content=c.new_content,
            operation=c.operation,
            description=c.description,
        )
        for c in req.changes
    ]
    patch = gen.generate(
        title=req.title,
        description=req.description,
        changes=changes,
        author=req.author,
    )
    gen.save_to_file(patch)

    # 统计
    add_lines = sum(
        1 for line in patch.diff.split("\n") if line.startswith("+") and not line.startswith("+++")
    )
    del_lines = sum(
        1 for line in patch.diff.split("\n") if line.startswith("-") and not line.startswith("---")
    )

    return GenerateResponse(
        id=patch.id,
        title=patch.title,
        status="draft",
        files=len(changes),
        diff=patch.diff,
        patch_file=patch.patch_file,
        add_lines=add_lines,
        del_lines=del_lines,
    )


@router.post("/preview", response_model=ApplyResponse)
async def preview_patch(req: ApplyRequest) -> ApplyResponse:
    """预览补丁（dry-run，不实际写入）"""
    gen = _get_generator(req.project_root)
    patch_file = gen._patches_dir / f"{req.patch_id}.patch"
    if not patch_file.exists():
        raise HTTPException(status_code=404, detail=f"补丁不存在: {req.patch_id}")

    patch = gen.load_from_file(patch_file)
    applier = _get_applier(req.project_root)
    result = applier.apply(patch, dry_run=True)
    return ApplyResponse(
        success=result["success"],
        applied=result["applied"],
        errors=result["errors"],
        backup=result["backup"],
        dry_run=True,
    )


@router.post("/apply", response_model=ApplyResponse)
async def apply_patch(req: ApplyRequest) -> ApplyResponse:
    """应用补丁"""
    gen = _get_generator(req.project_root)
    patch_file = gen._patches_dir / f"{req.patch_id}.patch"
    if not patch_file.exists():
        raise HTTPException(status_code=404, detail=f"补丁不存在: {req.patch_id}")

    patch = gen.load_from_file(patch_file)
    applier = _get_applier(req.project_root)
    result = applier.apply(patch, dry_run=req.dry_run)
    return ApplyResponse(
        success=result["success"],
        applied=result["applied"],
        errors=result["errors"],
        backup=result["backup"],
        dry_run=req.dry_run,
    )


@router.post("/rollback")
async def rollback_patch(req: RollbackRequest) -> dict:
    """从备份回滚"""
    applier = _get_applier(req.project_root)
    return applier.rollback(req.backup_id)


@router.get("/list")
async def list_patches() -> dict:
    """列出已保存的补丁"""
    gen = _get_generator(None)
    patches = gen.list_patches()
    return {
        "patches": patches,
        "count": len(patches),
    }


@router.get("/{patch_id}")
async def get_patch(patch_id: str) -> dict:
    """获取补丁详情"""
    gen = _get_generator(None)
    patch_file = gen._patches_dir / f"{patch_id}.patch"
    if not patch_file.exists():
        raise HTTPException(status_code=404, detail=f"补丁不存在: {patch_id}")
    patch = gen.load_from_file(patch_file)
    return {
        "id": patch.id,
        "title": patch.title,
        "description": patch.description,
        "author": patch.author,
        "diff": patch.diff,
        "patch_file": patch.patch_file,
        "created_at": patch.created_at,
    }


@router.post("/{patch_id}/commit", response_model=CommitResponse)
async def commit_patch(patch_id: str, req: CommitRequest) -> CommitResponse:
    """提交补丁为 Git commit"""
    gen = _get_generator(req.project_root)
    patch_file = gen._patches_dir / f"{patch_id}.patch"
    if not patch_file.exists():
        raise HTTPException(status_code=404, detail=f"补丁不存在: {patch_id}")

    patch = gen.load_from_file(patch_file)
    git = GitIntegration(repo_root=Path(req.project_root) if req.project_root else None)

    if not git.is_repo():
        return CommitResponse(success=False, status="not_a_git_repo")

    branch_name = ""
    if req.create_branch:
        branch_name = f"pycoder/{patch_id}"
        try:
            git.create_branch(branch_name, base=git.get_current_branch())
            patch.branch = branch_name
        except RuntimeError as e:
            logger.warning("branch_create_failed error=%s", e)
            return CommitResponse(success=False, status="branch_failed", branch="")

    if git.has_changes():
        try:
            sha = git.commit(f"{patch.title}\n\n{patch.description}\n\nAuto-generated by pycoder")
            patch.commit_sha = sha
            patch.status = "committed"
        except RuntimeError as e:
            logger.error("commit_failed error=%s", e)
            return CommitResponse(success=False, status="commit_failed", branch=branch_name)

    pr_draft_dict: dict | None = None
    if req.push and branch_name:
        push_result = git.push(branch_name)
        if push_result["success"]:
            pr_draft = generate_pr_draft(patch, base=git.get_current_branch())
            pr_draft_dict = {
                "title": pr_draft.title,
                "body": pr_draft.body,
                "head": pr_draft.head,
                "base": pr_draft.base,
                "labels": pr_draft.labels,
            }
            patch.status = "pr_drafted"

    return CommitResponse(
        success=True,
        status=patch.status,
        branch=branch_name,
        commit_sha=patch.commit_sha,
        pr_draft=pr_draft_dict,
    )


@router.post("/{patch_id}/pr")
async def generate_pr(patch_id: str) -> dict:
    """生成 PR 草稿（不推送）"""
    gen = _get_generator(None)
    patch_file = gen._patches_dir / f"{patch_id}.patch"
    if not patch_file.exists():
        raise HTTPException(status_code=404, detail=f"补丁不存在: {patch_id}")
    patch = gen.load_from_file(patch_file)
    pr = generate_pr_draft(patch, base="master")
    return {
        "title": pr.title,
        "body": pr.body,
        "head": pr.head,
        "base": pr.base,
        "labels": pr.labels,
        "reviewers": pr.reviewers,
    }
