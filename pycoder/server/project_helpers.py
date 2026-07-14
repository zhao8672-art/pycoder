"""Project tree, Git status, Diff preview helpers for WebSocket handler."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# ─── 桌面增强功能：项目树、文件打开、Diff 预览、Git 状态 ─────────────────


async def _get_project_tree(path: str = None, max_depth: int = 3) -> dict:
    """
    扫描项目目录结构，返回树形 JSON。
    - path: 起始路径（默认当前工作目录）
    - max_depth: 最大递归深度，防止遍历过深
    """
    if not path:
        path = os.getcwd()

    # 默认忽略目录和文件（类似 .gitignore 效果）
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
        ".openclaw",
        ".claude",
        ".cursor",
    }
    IGNORE_EXTS = {".pyc", ".pyo", ".so", ".dll", ".dylib"}

    root = Path(path).resolve()
    if not root.is_dir():
        return {"error": f"目录不存在: {path}", "name": root.name, "type": "dir", "children": []}

    def _scan(current: Path, depth: int) -> dict | None:
        """递归扫描一层"""
        if depth > max_depth:
            return {"name": current.name, "type": "dir", "truncated": True}
        try:
            entries = sorted(current.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return {"name": current.name, "type": "dir", "error": "权限拒绝"}
        children = []
        for entry in entries:
            if entry.name.startswith("."):
                if entry.is_dir() and depth > 0:
                    continue
                if entry.name in IGNORE_DIRS:
                    continue
            if entry.is_dir():
                if entry.name in IGNORE_DIRS:
                    continue
                child = _scan(entry, depth + 1)
                if child:
                    children.append(child)
            elif entry.suffix in IGNORE_EXTS:
                continue
            else:
                try:
                    stat = entry.stat()
                    children.append(
                        {
                            "name": entry.name,
                            "type": "file",
                            "path": str(entry.relative_to(root)),
                            "size": stat.st_size,
                            "modified_at": stat.st_mtime,
                        }
                    )
                except OSError:
                    continue
        return {
            "name": current.name,
            "type": "dir",
            "path": str(current.relative_to(root)) if current != root else "",
            "children": children,
        }

    tree = _scan(root, 0)
    tree["root"] = str(root)
    return tree


async def _get_git_status(project_path: str = None) -> dict:
    """
    获取当前项目 Git 状态。
    返回：分支名、未暂存变更、暂存变更、未跟踪文件、提交统计
    """
    if not project_path:
        project_path = os.getcwd()
    result = {
        "branch": "",
        "modified": [],
        "staged": [],
        "untracked": [],
        "ahead": 0,
        "behind": 0,
        "has_remote": False,
    }
    try:
        check_repo = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        if check_repo.returncode != 0:
            result["error"] = "不是 Git 仓库"
            return result

        br = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        if br.returncode == 0:
            result["branch"] = br.stdout.strip()

        mr = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        if mr.returncode == 0:
            result["modified"] = [line.strip() for line in mr.stdout.split("\n") if line.strip()]

        sr = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        if sr.returncode == 0:
            result["staged"] = [line.strip() for line in sr.stdout.split("\n") if line.strip()]

        ur = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        if ur.returncode == 0:
            result["untracked"] = [line.strip() for line in ur.stdout.split("\n") if line.strip()]

        rr = subprocess.run(
            ["git", "remote", "-v"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        result["has_remote"] = bool(rr.stdout.strip())

        if result["branch"]:
            srr = subprocess.run(
                [
                    "git",
                    "rev-list",
                    "--left-right",
                    "--count",
                    f"{result['branch']}@{{u}}...{result['branch']}",
                ],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=5,
                encoding="utf-8",
                errors="replace",
            )
            if srr.returncode == 0:
                parts = srr.stdout.strip().split()
                if len(parts) == 2:
                    result["behind"] = int(parts[0])
                    result["ahead"] = int(parts[1])
    except FileNotFoundError:
        result["error"] = "Git 未安装"
    except subprocess.TimeoutExpired:
        result["error"] = "Git 命令超时"
    except Exception as e:
        result["error"] = str(e)
    return result


async def _get_diff_preview(file_path: str = None, staged: bool = False) -> dict:
    """
    生成文件或整个项目的 diff 预览。
    - file_path: 指定文件（可选），null 时返回全部变更
    - staged: 是否显示暂存区 diff
    """
    project_path = os.getcwd()
    result = {
        "files": [],
        "total_additions": 0,
        "total_deletions": 0,
        "summary": "",
    }
    try:
        cmd = ["git", "diff"]
        if staged:
            cmd.append("--cached")
        if file_path:
            cmd.append(file_path)

        diff_r = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if diff_r.returncode != 0:
            result["error"] = diff_r.stderr.strip()
            return result

        diff_text = diff_r.stdout
        if not diff_text:
            result["summary"] = "没有变更"
            return result

        # 解析每个文件的 diff 块
        current_file = None
        for line in diff_text.split("\n"):
            if line.startswith("diff --git"):
                parts = line.split()
                if len(parts) >= 4:
                    current_file = parts[2].removeprefix("a/")
                    result["files"].append(
                        {
                            "path": current_file,
                            "additions": 0,
                            "deletions": 0,
                            "diff": [],
                        }
                    )
            elif current_file and result["files"]:
                last_file = result["files"][-1]
                last_file["diff"].append(line)
                if line.startswith("+") and not line.startswith("+++"):
                    last_file["additions"] += 1
                elif line.startswith("-") and not line.startswith("---"):
                    last_file["deletions"] += 1

        for f in result["files"]:
            result["total_additions"] += f["additions"]
            result["total_deletions"] += f["deletions"]

        fc = len(result["files"])
        result["summary"] = (
            f"{fc} 个文件变更，+{result['total_additions']}/-{result['total_deletions']}"
            if fc > 1
            else f"1 个文件变更，+{result['total_additions']}/-{result['total_deletions']}"
        )

    except FileNotFoundError:
        result["error"] = "Git 未安装"
    except subprocess.TimeoutExpired:
        result["error"] = "Diff 命令超时"
    except Exception as e:
        result["error"] = str(e)
    return result
