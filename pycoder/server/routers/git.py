"""
Git Status API

H7: 异步路由内同步 git 操作用 asyncio.to_thread 包装避免阻塞事件循环；
所有 dict 入参改为 Pydantic BaseModel 进行校验。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pycoder.server.routers.files import get_workspace_root as _ws

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/git")


# ══════════════════════════════════════════════════════════
# H7: Pydantic 请求模型（替代原 req: dict）
# ══════════════════════════════════════════════════════════


class RemoteBranchRequest(BaseModel):
    """推送/拉取请求 — 含远程名与分支名"""

    remote: str = "origin"
    branch: str | None = None


class StashRequest(BaseModel):
    """暂存操作 {action: push|pop|list|drop, message?, index?}"""

    action: str = "push"
    message: str = "WIP"
    index: int = 0


class FilesRequest(BaseModel):
    """文件列表请求 — 暂存/取消暂存/放弃"""

    files: list[str] = Field(default_factory=list)
    all: bool = False  # unstage_files 专用


class StashIndexRequest(BaseModel):
    """stash 索引请求"""

    index: int = 0


class BranchNameRequest(BaseModel):
    """分支名请求 — 删除分支/标签"""

    name: str
    force: bool = False


class MergeRequest(BaseModel):
    """合并分支"""

    source_branch: str


class CommitHashRequest(BaseModel):
    """提交哈希请求 — revert/cherry-pick"""

    commit: str


class RebaseRequest(BaseModel):
    """变基请求"""

    branch: str


class RemoteAddRequest(BaseModel):
    """添加远程"""

    name: str
    url: str


class RemoteNameRequest(BaseModel):
    """远程名请求 — 删除远程"""

    name: str


class ConflictResolveRequest(BaseModel):
    """冲突解决请求"""

    file: str
    resolution: str  # "ours" | "theirs"


class GitignoreRequest(BaseModel):
    """.gitignore 添加请求"""

    pattern: str


class GitInitRequest(BaseModel):
    """初始化仓库请求"""

    path: str | None = None


class FetchRequest(BaseModel):
    """fetch 请求"""

    remote: str = "origin"


async def _run_git(fn, *args, **kwargs):
    """H7: 将同步 git 操作包装到线程中执行，避免阻塞事件循环"""
    return await asyncio.to_thread(fn, *args, **kwargs)


# Git 状态查询
@router.get("/status")
async def get_git_status(path: str | None = None):
    """Get Git status for a repository — 返回 staged/unstaged/untracked + has_remote"""
    repo_path = Path(path) if path else _ws()

    try:
        from git import Repo

        repo = Repo(str(repo_path))

        branch = repo.active_branch.name if repo.active_branch else None
        ahead, behind = 0, 0

        try:
            tracking = repo.active_branch.tracking_branch()
            if tracking:
                commits = list(repo.iter_commits(f"{tracking.name}..{branch}"))
                ahead = len(commits)
                commits = list(repo.iter_commits(f"{branch}..{tracking.name}"))
                behind = len(commits)
        except (ValueError, TypeError) as e:
            logger.debug("tracking_branch_lookup_failed error=%s", e)

        # has_remote: 检查是否有远程仓库
        has_remote = len(repo.remotes) > 0

        # staged 变更
        staged_files = []
        for item in repo.index.diff("HEAD"):
            staged_files.append(
                {
                    "path": item.a_path,
                    "status": (
                        "M"
                        if item.change_type == "M"
                        else (
                            "A"
                            if item.change_type == "A"
                            else "D" if item.change_type == "D" else str(item.change_type)
                        )
                    ),
                    "staged": True,
                }
            )

        # unstaged 变更
        unstaged_files = []
        for item in repo.index.diff(None):
            unstaged_files.append(
                {
                    "path": item.a_path,
                    "status": (
                        "M"
                        if item.change_type == "M"
                        else "D" if item.change_type == "D" else str(item.change_type)
                    ),
                    "staged": False,
                }
            )

        # untracked
        for item in repo.untracked_files:
            unstaged_files.append(
                {
                    "path": item,
                    "status": "?",
                    "staged": False,
                }
            )

        changed_files = staged_files + unstaged_files

        return {
            "branch": branch,
            "ahead": ahead,
            "behind": behind,
            "files": changed_files,
            "staged_count": len(staged_files),
            "unstaged_count": len(unstaged_files),
            "has_remote": has_remote,
            "is_git_repo": True,
        }

    except ImportError:
        raise HTTPException(500, "GitPython not installed") from None
    except Exception as e:
        return {
            "branch": None,
            "ahead": 0,
            "behind": 0,
            "files": [],
            "staged_count": 0,
            "unstaged_count": 0,
            "has_remote": False,
            "is_git_repo": False,
            "error": str(e),
        }


@router.get("/log")
async def get_git_log(limit: int = 10, path: str | None = None):
    """Get recent Git commits"""
    repo_path = Path(path) if path else _ws()

    try:
        from git import Repo

        repo = Repo(str(repo_path))

        commits = []
        for commit in repo.iter_commits(max_count=limit):
            commits.append(
                {
                    "hash": commit.hexsha,
                    "message": commit.message.strip(),
                    "author": commit.author.name,
                    "date": commit.committed_datetime.isoformat(),
                }
            )

        return {"commits": commits}

    except ImportError:
        raise HTTPException(500, "GitPython not installed") from None
    except Exception as e:
        logger.warning("git_log_failed error=%s", e)
        return {"commits": []}


# ══════════════════════════════════════════════════════════
# Git Commit API
# ══════════════════════════════════════════════════════════


class CommitRequest(BaseModel):
    """Git commit 请求"""

    files: list[str] = Field(default_factory=list)
    message: str | None = None
    author: str | None = None


@router.post("/commit")
async def git_commit(req: CommitRequest):
    """自动 Git commit — add + commit"""
    try:
        from git import Actor, Repo

        repo = Repo(str(_ws()))

        # git add
        if req.files:
            for f in req.files:
                repo.index.add([f])
        else:
            repo.index.add("*")

        # 生成或使用 commit message
        if req.message:
            msg = req.message
        else:
            msg = _generate_commit_message(repo)

        # git commit
        author = Actor(req.author or "PyCoder AI", "ai@pycoder.ai")
        commit = repo.index.commit(msg, author=author, committer=author)

        return {
            "success": True,
            "hash": commit.hexsha,
            "message": msg,
            "files_count": len(req.files) if req.files else -1,
        }
    except ImportError:
        raise HTTPException(500, "GitPython not installed") from None
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/commit/generate-message")
async def generate_commit_message():
    """AI 生成 conventional commit message"""
    try:
        from git import Repo

        repo = Repo(str(_ws()))
        return {"message": _generate_commit_message(repo)}
    except ImportError:
        raise HTTPException(500, "GitPython not installed") from None
    except Exception as e:
        return {"message": "chore: update", "error": str(e)}


def _generate_commit_message(repo) -> str:
    """基于 git diff 生成 conventional commit message"""
    diff_summary = []
    for item in repo.index.diff(None):
        diff_summary.append(f"{item.change_type} {item.a_path}")
    for item in repo.untracked_files:
        diff_summary.append(f"A {item}")

    summary_text = "\n".join(diff_summary[:10])
    if len(diff_summary) > 10:
        summary_text += f"\n... and {len(diff_summary) - 10} more files"

    # 推断类型
    all_files = " ".join(diff_summary).lower()
    if "test" in all_files:
        commit_type = "test"
    elif ".md" in all_files or ".rst" in all_files:
        commit_type = "docs"
    elif "fix" in all_files or "bug" in all_files:
        commit_type = "fix"
    elif "refactor" in all_files:
        commit_type = "refactor"
    else:
        commit_type = "feat"

    return f"{commit_type}: AI-assisted changes\n\n{summary_text}"


# ══════════════════════════════════════════════════════════
# Branch Operations
# ══════════════════════════════════════════════════════════


@router.get("/branches")
async def list_branches(path: str | None = None):
    """列出所有分支"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        branches = []
        for b in repo.branches:
            branches.append(
                {
                    "name": b.name,
                    "is_active": b.name == repo.active_branch.name,
                }
            )
        return {
            "branches": branches,
            "active": repo.active_branch.name if repo.active_branch else None,
        }
    except Exception as e:
        return {"branches": [], "active": None, "error": str(e)}


class BranchCreateRequest(BaseModel):
    name: str


@router.post("/branch/create")
async def create_branch(req: BranchCreateRequest, path: str | None = None):
    """创建新分支"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        repo.create_head(req.name)
        return {"success": True, "branch": req.name}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/branch/switch")
async def switch_branch(req: BranchCreateRequest, path: str | None = None):
    """切换分支"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        branch = repo.branches[req.name]
        branch.checkout()
        return {"success": True, "branch": req.name}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/branch/merge")
async def merge_branch(req: MergeRequest, path: str | None = None):
    """合并分支 {source_branch} 到当前分支"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        source = req.source_branch
        # H7: 合并可能涉及网络/重 IO，用 to_thread 包装
        result = await _run_git(repo.git.merge, source)
        return {"success": True, "output": result}
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "has_conflicts": "CONFLICT" in str(e),
        }


# ══════════════════════════════════════════════════════════
# Remote Operations
# ══════════════════════════════════════════════════════════


@router.post("/push")
async def git_push(req: RemoteBranchRequest = RemoteBranchRequest(), path: str | None = None):
    """推送到远程"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        remote_name = req.remote
        branch_name = req.branch or repo.active_branch.name
        # H7: 网络操作用 to_thread 避免阻塞事件循环
        result = await _run_git(repo.git.push, remote_name, branch_name)
        return {"success": True, "output": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/pull")
async def git_pull(req: RemoteBranchRequest = RemoteBranchRequest(), path: str | None = None):
    """从远程拉取"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        remote_name = req.remote
        # H7: 网络操作用 to_thread
        result = await _run_git(repo.git.pull, remote_name)
        return {"success": True, "output": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════
# Stash & Diff Detail
# ══════════════════════════════════════════════════════════


@router.post("/stash")
async def git_stash(req: StashRequest = StashRequest(), path: str | None = None):
    """暂存操作 {action: 'push'|'pop'|'list'|'drop'}"""
    action = req.action
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        if action == "push":
            # H7: stash push 可能涉及文件 IO，用 to_thread 包装
            await _run_git(repo.git.stash, "push", "-m", req.message)
            return {"success": True}
        elif action == "pop":
            await _run_git(repo.git.stash, "pop")
            return {"success": True}
        elif action == "list":
            raw = await _run_git(repo.git.stash, "list")
            stashes = [s.strip() for s in raw.split("\n") if s.strip()]
            return {"stashes": stashes}
        elif action == "drop":
            await _run_git(repo.git.stash, "drop", str(req.index))
            return {"success": True}
        return {"success": False, "error": f"Unknown action: {action}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/diff")
async def git_diff_detail(
    file: str = "",
    staged: bool = False,
    path: str | None = None,
):
    """获取文件或整个工作区的 diff"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        if staged:
            diff_text = repo.git.diff("--cached", file) if file else repo.git.diff("--cached")
        else:
            diff_text = repo.git.diff(file) if file else repo.git.diff()
        return {"diff": diff_text, "file": file}
    except Exception as e:
        return {"diff": "", "file": file, "error": str(e)}


@router.get("/blame")
async def git_blame(
    file: str,
    path: str | None = None,
):
    """逐行溯源"""
    if not file:
        raise HTTPException(400, "file is required")
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        blame_output = repo.git.blame(file, "--date=short")
        lines = blame_output.split("\n")
        return {"blame": lines, "file": file, "total_lines": len(lines)}
    except Exception as e:
        return {"blame": [], "file": file, "error": str(e)}


# ══════════════════════════════════════════════════════════
# Phase 1 (P0): Stage / Unstage / Discard
# ══════════════════════════════════════════════════════════


@router.post("/stage")
async def stage_files(req: FilesRequest, path: str | None = None):
    """暂存指定文件: {files: ["path1", "path2"]}"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        # H7: index.add 涉及文件 IO，用 to_thread 包装
        await _run_git(repo.index.add, req.files)
        return {"success": True, "staged": req.files}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/unstage")
async def unstage_files(req: FilesRequest, path: str | None = None):
    """取消暂存: {files: ["path1"], all: true 取消全部}"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        if req.all:
            # H7: reset 操作用 to_thread 包装
            await _run_git(repo.head.reset, "HEAD", index=True)
        else:
            await _run_git(repo.head.reset, commit="HEAD", index=True, paths=req.files)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/discard")
async def discard_changes(req: FilesRequest, path: str | None = None):
    """放弃文件变更: {files: ["path1"]}"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        for f in req.files:
            # H7: checkout 涉及文件 IO，用 to_thread 包装
            await _run_git(repo.git.checkout, "--", f)
        return {"success": True, "discarded": req.files}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════
# Phase 2 (P1): Stash Detail / Branch Delete / File History / Compare
# ══════════════════════════════════════════════════════════


@router.post("/stash/detail")
async def stash_detail(req: StashIndexRequest, path: str | None = None):
    """查看特定 stash 的 diff {index: 0}"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        index = req.index
        # H7: stash show 涉及文件 IO，用 to_thread 包装
        diff = await _run_git(repo.git.stash, "show", "-p", f"stash@{{{index}}}")
        msg = await _run_git(repo.git.stash, "show", f"stash@{{{index}}}")
        lines = [line.strip() for line in msg.split("\n") if line.strip()]
        return {
            "success": True,
            "index": index,
            "diff": diff,
            "summary": lines[0] if lines else "",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/stash/apply")
async def stash_apply(req: StashIndexRequest, path: str | None = None):
    """应用 stash 但不删除: {index: 0}"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        index = req.index
        # H7: stash apply 涉及文件 IO，用 to_thread 包装
        await _run_git(repo.git.stash, "apply", f"stash@{{{index}}}")
        return {"success": True, "index": index}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/branch/delete")
async def delete_branch(req: BranchNameRequest, path: str | None = None):
    """删除分支: {name, force?}"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        name = req.name
        if not name:
            return {"success": False, "error": "name is required"}
        if name == repo.active_branch.name:
            return {"success": False, "error": "Cannot delete active branch"}
        # H7: delete_head 涉及文件 IO，用 to_thread 包装
        await _run_git(repo.delete_head, name, force=req.force)
        return {"success": True, "deleted": name}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/file-history")
async def file_history(file: str, limit: int = 20, path: str | None = None):
    """查看单个文件的提交历史"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        commits = list(repo.iter_commits(paths=file, max_count=limit))
        return {
            "file": file,
            "commits": [
                {
                    "hash": c.hexsha[:8],
                    "message": c.message.strip(),
                    "author": str(c.author),
                    "date": c.committed_datetime.isoformat(),
                    "stats": c.stats.files.get(file, {}),
                }
                for c in commits
            ],
        }
    except Exception as e:
        return {"file": file, "commits": [], "error": str(e)}


@router.get("/compare")
async def compare_commits(base: str, head: str, path: str | None = None):
    """对比两个提交/分支的 diff"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        diff = repo.git.diff(f"{base}..{head}")
        return {"base": base, "head": head, "diff": diff}
    except Exception as e:
        return {"base": base, "head": head, "error": str(e)}


# ══════════════════════════════════════════════════════════
# Phase 3 (P2): Tags / Fetch / Reset / Revert / Cherry-pick / Rebase / Remote / Conflicts / .gitignore
# ══════════════════════════════════════════════════════════


@router.get("/tags")
async def list_tags(path: str | None = None):
    """列出所有标签"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        tags = []
        for t in repo.tags:
            tags.append(
                {
                    "name": t.name,
                    "commit": t.commit.hexsha[:8],
                    "message": t.tag.message.strip() if t.tag else "",
                    "date": t.commit.committed_datetime.isoformat(),
                }
            )
        return {"tags": tags}
    except Exception as e:
        return {"tags": [], "error": str(e)}


class TagCreateRequest(BaseModel):
    name: str
    message: str = ""
    commit: str = ""


@router.post("/tag/create")
async def create_tag(req: TagCreateRequest, path: str | None = None):
    """创建标签 {name, message?, commit?}"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        if req.message:
            repo.create_tag(req.name, message=req.message)
        else:
            repo.create_tag(req.name)
        return {"success": True, "tag": req.name}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/tag/delete")
async def delete_tag(req: BranchNameRequest, path: str | None = None):
    """删除标签 {name}"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        # H7: delete_tag 涉及引用操作，用 to_thread 包装
        await _run_git(repo.delete_tag, req.name)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/fetch")
async def fetch_remote(req: FetchRequest = FetchRequest(), path: str | None = None):
    """从远程拉取但不合并"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        remote_name = req.remote
        # H7: 网络操作用 to_thread 避免阻塞事件循环
        fetch_info = await _run_git(repo.remotes[remote_name].fetch)
        return {
            "success": True,
            "fetched": [str(f) for f in fetch_info],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


class ResetRequest(BaseModel):
    mode: str = "mixed"  # soft | mixed | hard
    commit: str = "HEAD~1"


@router.post("/reset")
async def git_reset(req: ResetRequest, path: str | None = None):
    """重置 HEAD {mode: soft|mixed|hard, commit: 'HEAD~1'}"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        index = req.mode != "soft"
        working_tree = req.mode == "hard"
        repo.head.reset(req.commit, index=index, working_tree=working_tree)
        return {"success": True, "commit": req.commit, "mode": req.mode}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/revert")
async def git_revert(req: CommitHashRequest, path: str | None = None):
    """撤销提交 {commit: 'abc1234'}"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        # H7: revert 涉及提交操作，用 to_thread 包装
        await _run_git(repo.git.revert, req.commit, no_edit=True)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/cherry-pick")
async def git_cherry_pick(req: CommitHashRequest, path: str | None = None):
    """摘取提交 {commit: 'abc1234'}"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        # H7: cherry-pick 涉及提交操作，用 to_thread 包装
        await _run_git(repo.git.cherry_pick, req.commit)
        return {"success": True}
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "has_conflicts": "CONFLICT" in str(e),
        }


@router.post("/rebase")
async def git_rebase(req: RebaseRequest, path: str | None = None):
    """变基 {branch: 'main'}"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        # H7: rebase 涉及提交操作，用 to_thread 包装
        await _run_git(repo.git.rebase, req.branch)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/remotes")
async def list_remotes(path: str | None = None):
    """列出所有远程仓库"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        remotes = []
        for r in repo.remotes:
            remotes.append(
                {
                    "name": r.name,
                    "url": r.url,
                    "fetch_urls": list(r.urls),
                    "push_urls": list(r.urls),
                }
            )
        return {"remotes": remotes}
    except Exception as e:
        return {"remotes": [], "error": str(e)}


@router.post("/remote/add")
async def add_remote(req: RemoteAddRequest, path: str | None = None):
    """添加远程 {name, url}"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        # H7: create_remote 涉及配置写入，用 to_thread 包装
        await _run_git(repo.create_remote, req.name, url=req.url)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/remote/remove")
async def remove_remote(req: RemoteNameRequest, path: str | None = None):
    """删除远程 {name}"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        remote = repo.remotes[req.name]
        # H7: delete_remote 涉及配置写入，用 to_thread 包装
        await _run_git(repo.delete_remote, remote)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/conflicts")
async def list_conflicts(path: str | None = None):
    """检测并列出合并冲突文件"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        conflicted = []
        for path, stages in repo.index.unmerged_blobs().items():
            ours = [b for b in stages if b[0] == 1]
            theirs = [b for b in stages if b[0] == 2]
            conflicted.append(
                {
                    "path": path,
                    "ours": ours[0][1].data_stream.read().decode() if ours else "",
                    "theirs": theirs[0][1].data_stream.read().decode() if theirs else "",
                }
            )
        return {"conflicted": conflicted}
    except Exception:
        try:
            from git import Repo

            repo = Repo(str(repo_path))
            raw = repo.git.status("--porcelain")
            conflicted_files = [
                line[3:].strip() for line in raw.split("\n") if line.startswith("UU")
            ]
            return {"conflicted": [{"path": f} for f in conflicted_files]}
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("conflict_fallback_failed error=%s", e)
            return {"conflicted": []}


@router.post("/resolve-conflict")
async def resolve_conflict(req: ConflictResolveRequest, path: str | None = None):
    """解决合并冲突 {file, resolution: "ours"|"theirs"}"""
    repo_path = Path(path) if path else _ws()
    try:
        from git import Repo

        repo = Repo(str(repo_path))
        file = req.file
        resolution = req.resolution
        # H7: checkout 与 index.add 涉及文件 IO，用 to_thread 包装
        await _run_git(repo.git.checkout, f"--{resolution}", file)
        await _run_git(repo.index.add, [file])
        return {"success": True, "file": file, "resolution": resolution}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/ignore")
async def add_to_gitignore(req: GitignoreRequest, path: str | None = None):
    """添加到 .gitignore {pattern: '*.log'}"""
    repo_path = Path(path) if path else _ws()
    try:
        gitignore = repo_path / ".gitignore"
        pattern = req.pattern
        if not pattern:
            return {"success": False, "error": "pattern is required"}
        existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        if pattern in existing:
            return {"success": True, "note": "pattern already exists"}
        gitignore.write_text(existing + f"\n{pattern}\n", encoding="utf-8")
        return {"success": True, "pattern": pattern}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════
# GitHub Integration: git init
# ══════════════════════════════════════════════════════════


@router.post("/init")
async def git_init(req: GitInitRequest = GitInitRequest()):
    """初始化新 Git 仓库: {path?} 默认当前工作区"""
    repo_path = _ws()
    if req.path:
        repo_path = Path(req.path)
    try:
        from git import Repo

        if (repo_path / ".git").exists():
            return {"success": True, "path": str(repo_path), "note": "already a git repository"}
        # H7: Repo.init 涉及文件系统操作，用 to_thread 包装
        repo = await _run_git(Repo.init, str(repo_path))
        return {"success": True, "path": str(repo.working_tree_dir)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/init")
async def git_init_check():
    """检查工作区是否是 git 仓库"""
    try:
        from git import Repo

        repo = Repo(str(_ws()))
        return {"is_git": True, "path": str(repo.working_tree_dir)}
    except (ImportError, OSError, ValueError) as e:
        logger.debug("git_init_check_failed error=%s", e)
        return {"is_git": False}
