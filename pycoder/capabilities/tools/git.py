"""Git 工具 — git_status, git_log, git_diff_branch, resolve_conflict"""

from __future__ import annotations

import re
import subprocess as sp
from pathlib import Path
from typing import Any

from pycoder.bus.protocol import CapabilityDefinition, ExecutionMode, SideEffect
from pycoder.capabilities.permissions import TOOL_PERMISSIONS
from pycoder.capabilities.degradation import wrap_handler


def register(registry: Any) -> None:
    _reg(registry, "tools.git.status", "Git 状态",
         "获取 Git 仓库状态概览（分支、变更文件等）",
         {"path": {"type": "string", "default": "."}}, [], _git_status)

    _reg(registry, "tools.git.log", "Git 历史",
         "查看 Git 提交历史和分支图",
         {"limit": {"type": "number", "default": 20}}, [], _git_log)

    _reg(registry, "tools.git.diff_branch", "分支对比",
         "对比两个 Git 分支的差异",
         {"branch1": {"type": "string"}, "branch2": {"type": "string", "default": "HEAD"}},
         ["branch1"], _git_diff_branch)

    _reg(registry, "tools.git.resolve_conflict", "冲突解决",
         "分析 Git 合并冲突文件，自动解决简单冲突",
         {"file": {"type": "string"}}, ["file"], _resolve_conflict)


def _reg(registry, cid, name, desc, schema, required, handler):
    registry.register(
        CapabilityDefinition(
            id=cid, name=name, description=desc,
            permission=TOOL_PERMISSIONS.get(cid),
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            schema={"type": "object", "properties": schema, "required": required},
            tags=[cid.rsplit(".", 1)[-1], name],
        ),
        handler=wrap_handler(handler),
    )


async def _git_status(params: dict, context: dict) -> dict:
    cwd = Path(params.get("path", "."))
    try:
        repo = __import__("git").Repo(cwd)
        branch = repo.active_branch.name if repo.active_branch else None
        status = repo.git.status("--porcelain")
        lines = [line.strip() for line in status.split("\n") if line.strip()]
        return {"success": True, "branch": branch,
                "changed_files": len(lines), "changes": lines[:50],
                "is_dirty": bool(lines)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _git_log(params: dict, context: dict) -> dict:
    limit = params.get("limit", 20)
    try:
        r = sp.run(["git", "log", f"-{limit}", "--oneline", "--decorate"],
                   capture_output=True, text=True, timeout=10)
        lines = [line.strip() for line in r.stdout.split("\n") if line.strip()]
        return {"success": True, "commits": lines, "count": len(lines)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _git_diff_branch(params: dict, context: dict) -> dict:
    b1, b2 = params["branch1"], params.get("branch2", "HEAD")
    try:
        r = sp.run(["git", "diff", "--name-only", f"{b1}..{b2}"],
                   capture_output=True, text=True, timeout=15)
        files = [line.strip() for line in r.stdout.split("\n") if line.strip()]
        return {"success": True, "branch1": b1, "branch2": b2,
                "changed_files": len(files), "files": files[:30]}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _resolve_conflict(params: dict, context: dict) -> dict:
    target = Path(params["file"])
    if not target.exists():
        return {"success": False, "error": f"文件不存在: {params['file']}"}
    content = target.read_text(encoding="utf-8")
    conflicts = re.findall(r"^<<<<<<< ", content, re.MULTILINE)
    if not conflicts:
        return {"success": True, "conflict_count": 0}
    return {"success": True, "conflict_count": len(conflicts),
            "note": "请手动解决冲突标记，此工具仅做检测"}
