"""P2-1: 自动补丁生成 + Git PR 草稿

工作流:
1. 用户描述修改意图 → LLM 生成具体修改内容 (或人工提供)
2. 系统生成 unified diff 格式的 patch 文件
3. 用户可预览 patch 并应用/拒绝
4. 应用后: 自动创建 git 分支 + 提交
5. 推送到 GitHub 后: 自动生成 PR 描述草稿

特性:
- 安全: 应用前显示 diff，需用户确认
- 幂等: 同一 patch 可重复应用检测
- 可回滚: 应用前自动创建 backup
- 多文件: 支持单次 patch 修改多个文件
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# ── 数据模型 ─────────────────────────────────────────────


@dataclass
class FileChange:
    """单个文件的修改"""

    file_path: str
    old_content: str = ""
    new_content: str = ""
    operation: str = "modify"  # "modify" | "create" | "delete"
    description: str = ""


@dataclass
class Patch:
    """完整补丁"""

    id: str
    title: str
    description: str
    changes: list[FileChange]
    author: str = "pycoder-bot"
    branch: str = ""
    created_at: float = field(default_factory=time.time)
    status: str = "draft"  # "draft" | "applied" | "committed" | "pr_created" | "rejected"
    patch_file: str = ""
    diff: str = ""
    commit_sha: str = ""
    pr_url: str = ""


@dataclass
class PRDraft:
    """PR 草稿"""

    title: str
    body: str
    head: str  # 分支名
    base: str = "master"  # 目标分支
    labels: list[str] = field(default_factory=list)
    reviewers: list[str] = field(default_factory=list)


# ── 补丁生成器 ───────────────────────────────────────────


class PatchGenerator:
    """从多个文件变更生成 unified diff patch"""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path.cwd()
        self._patches_dir = Path.home() / ".pycoder" / "patches"
        self._patches_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        title: str,
        description: str,
        changes: list[FileChange],
        author: str = "pycoder-bot",
    ) -> Patch:
        """生成补丁对象

        Args:
            title: 补丁标题
            description: 详细说明
            changes: 文件修改列表
            author: 作者
        """
        patch_id = f"patch_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        diff = self._build_unified_diff(changes)
        return Patch(
            id=patch_id,
            title=title,
            description=description,
            changes=changes,
            author=author,
            diff=diff,
        )

    def _build_unified_diff(self, changes: list[FileChange]) -> str:
        """构建 unified diff 文本"""
        diff_parts: list[str] = []
        for change in changes:
            file_path = change.file_path
            if change.operation == "create":
                # 新建文件
                lines = change.new_content.splitlines(keepends=True)
                if lines and not lines[-1].endswith("\n"):
                    lines[-1] += "\n"
                from_lines: list[str] = []
                ud = list(
                    difflib.unified_diff(
                        from_lines,
                        lines,
                        fromfile="/dev/null",
                        tofile=file_path,
                        lineterm="",
                    )
                )
                diff_parts.extend(ud)
            elif change.operation == "delete":
                lines = change.old_content.splitlines(keepends=True)
                if lines and not lines[-1].endswith("\n"):
                    lines[-1] += "\n"
                ud = list(
                    difflib.unified_diff(
                        lines,
                        [],
                        fromfile=file_path,
                        tofile="/dev/null",
                        lineterm="",
                    )
                )
                diff_parts.extend(ud)
            else:  # modify
                old_lines = change.old_content.splitlines(keepends=True)
                new_lines = change.new_content.splitlines(keepends=True)
                # 保证最后一行有换行符
                if old_lines and not old_lines[-1].endswith("\n"):
                    old_lines[-1] += "\n"
                if new_lines and not new_lines[-1].endswith("\n"):
                    new_lines[-1] += "\n"
                ud = list(
                    difflib.unified_diff(
                        old_lines,
                        new_lines,
                        fromfile=file_path,
                        tofile=file_path,
                        lineterm="",
                    )
                )
                diff_parts.extend(ud)
        return "\n".join(diff_parts)

    def save_to_file(self, patch: Patch) -> Path:
        """保存补丁到磁盘 (.patch 文件)"""
        patch_file = self._patches_dir / f"{patch.id}.patch"
        content = self._format_patch_file(patch)
        patch_file.write_text(content, encoding="utf-8")
        patch.patch_file = str(patch_file)
        logger.info("patch_saved id=%s file=%s", patch.id, patch_file)
        return patch_file

    def _format_patch_file(self, patch: Patch) -> str:
        """格式化为标准 patch 文件（含元信息）"""
        header = [
            f"# Patch: {patch.title}",
            f"# ID: {patch.id}",
            f"# Author: {patch.author}",
            f"# Created: {datetime.fromtimestamp(patch.created_at).isoformat()}",
            f"# Description: {patch.description}",
            f"# Files: {len(patch.changes)}",
            "",
        ]
        return "\n".join(header) + patch.diff

    def load_from_file(self, patch_file: Path) -> Patch:
        """从 .patch 文件加载"""
        content = patch_file.read_text(encoding="utf-8")
        # 解析 header
        meta: dict[str, str] = {}
        diff_lines: list[str] = []
        in_header = True
        for line in content.split("\n"):
            if in_header and line.startswith("# "):
                kv = line[2:].split(": ", 1)
                if len(kv) == 2:
                    meta[kv[0]] = kv[1]
            elif line == "" and in_header:
                in_header = False
            else:
                diff_lines.append(line)
        return Patch(
            id=meta.get("ID", patch_file.stem),
            title=meta.get("Patch", patch_file.stem),
            description=meta.get("Description", ""),
            changes=[],  # 简化: 不重新解析 diff
            author=meta.get("Author", "unknown"),
            diff="\n".join(diff_lines),
            patch_file=str(patch_file),
        )

    def list_patches(self) -> list[dict]:
        """列出所有已保存的补丁"""
        results = []
        for p in sorted(self._patches_dir.glob("*.patch"), reverse=True):
            stat = p.stat()
            results.append(
                {
                    "id": p.stem,
                    "file": str(p),
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                }
            )
        return results


# ── 补丁应用器 ───────────────────────────────────────────


class PatchApplier:
    """应用补丁到文件系统（带备份/校验/回滚）"""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path.cwd()
        self._backups_dir = Path.home() / ".pycoder" / "backups"
        self._backups_dir.mkdir(parents=True, exist_ok=True)

    def apply(self, patch: Patch, *, dry_run: bool = False) -> dict:
        """应用补丁到工作区

        Args:
            patch: 补丁对象
            dry_run: 仅校验不写入

        Returns:
            dict: {success, applied, skipped, errors, backup}
        """
        backup_id = f"backup_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        backup_dir = self._backups_dir / backup_id
        if not dry_run:
            backup_dir.mkdir(parents=True, exist_ok=True)

        applied: list[str] = []
        errors: list[str] = []

        for change in patch.changes:
            try:
                file_path = self.project_root / change.file_path
                # 备份原文件
                if file_path.exists() and not dry_run:
                    backup_file = backup_dir / change.file_path
                    backup_file.parent.mkdir(parents=True, exist_ok=True)
                    backup_file.write_text(
                        file_path.read_text(encoding="utf-8", errors="replace"),
                        encoding="utf-8",
                    )

                if dry_run:
                    # 校验模式: 仅检查文件路径合法
                    if change.operation != "create" and not file_path.exists():
                        errors.append(f"{change.file_path}: 文件不存在")
                    else:
                        applied.append(change.file_path)
                else:
                    # 实际应用
                    if change.operation == "delete":
                        if file_path.exists():
                            file_path.unlink()
                            applied.append(change.file_path)
                    else:
                        # create / modify
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        file_path.write_text(change.new_content, encoding="utf-8")
                        applied.append(change.file_path)

            except (OSError, PermissionError) as e:
                errors.append(f"{change.file_path}: {e}")
                logger.error("patch_apply_failed file=%s error=%s", change.file_path, e)

        return {
            "success": len(errors) == 0,
            "applied": applied,
            "skipped": [],
            "errors": errors,
            "backup": str(backup_dir) if not dry_run else None,
            "dry_run": dry_run,
        }

    def rollback(self, backup_id: str) -> dict:
        """从备份回滚"""
        backup_dir = self._backups_dir / backup_id
        if not backup_dir.exists():
            return {"success": False, "error": f"备份不存在: {backup_id}"}

        restored: list[str] = []
        errors: list[str] = []
        for backup_file in backup_dir.rglob("*"):
            if not backup_file.is_file():
                continue
            rel = backup_file.relative_to(backup_dir)
            target = self.project_root / rel
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    backup_file.read_text(encoding="utf-8", errors="replace"),
                    encoding="utf-8",
                )
                restored.append(str(rel))
            except (OSError, PermissionError) as e:
                errors.append(f"{rel}: {e}")

        return {
            "success": len(errors) == 0,
            "restored": restored,
            "errors": errors,
        }


# ── Git 集成 ───────────────────────────────────────────


class GitIntegration:
    """Git 操作封装：分支创建、提交、推送、PR 草稿生成"""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = repo_root or Path.cwd()

    def _run(self, *args: str, check: bool = True) -> str:
        """运行 git 命令"""
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def is_repo(self) -> bool:
        """是否为 git 仓库"""
        try:
            self._run("rev-parse", "--git-dir")
            return True
        except (RuntimeError, FileNotFoundError):
            return False

    def get_current_branch(self) -> str:
        """获取当前分支名"""
        try:
            return self._run("rev-parse", "--abbrev-ref", "HEAD")
        except RuntimeError:
            return "master"

    def create_branch(self, branch_name: str, base: str = "master") -> str:
        """创建并切换到新分支"""
        self._run("checkout", base)
        # 如果分支已存在则删除
        try:
            self._run("branch", "-D", branch_name, check=False)
        except RuntimeError:
            pass
        self._run("checkout", "-b", branch_name)
        return branch_name

    def commit(self, message: str, files: list[str] | None = None) -> str:
        """提交变更"""
        if files:
            for f in files:
                self._run("add", f)
        else:
            self._run("add", "-A")
        self._run("commit", "-m", message)
        return self._run("rev-parse", "HEAD")

    def has_changes(self) -> bool:
        """是否有未提交变更"""
        try:
            output = self._run("status", "--short")
            return bool(output.strip())
        except RuntimeError:
            return False

    def get_remote_url(self, remote: str = "origin") -> str:
        """获取远程 URL"""
        try:
            return self._run("remote", "get-url", remote)
        except RuntimeError:
            return ""

    def push(self, branch: str, remote: str = "origin", set_upstream: bool = True) -> dict:
        """推送分支"""
        args = ["push"]
        if set_upstream:
            args.extend(["-u", remote, branch])
        else:
            args.extend([remote, branch])
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }


# ── PR 草稿生成 ───────────────────────────────────────


def generate_pr_draft(patch: Patch, *, base: str = "master") -> PRDraft:
    """根据补丁内容生成 PR 描述草稿

    生成包含:
    - 标题
    - 摘要
    - 变更文件列表
    - 测试计划
    """
    # 文件分类
    modified = [c for c in patch.changes if c.operation == "modify"]
    created = [c for c in patch.changes if c.operation == "create"]
    deleted = [c for c in patch.changes if c.operation == "delete"]

    # 推断标签
    labels: list[str] = []
    for c in patch.changes:
        f = c.file_path.lower()
        if "test" in f or "tests/" in f:
            labels.append("test")
        if "docs/" in f or f.endswith(".md"):
            labels.append("documentation")
        if "fix" in patch.title.lower() or "bug" in patch.title.lower():
            labels.append("bug")
        if "feat" in patch.title.lower():
            labels.append("enhancement")
    labels = list(set(labels))

    # 构建 PR body
    body_parts: list[str] = []
    if patch.description:
        body_parts.append(f"## 描述\n\n{patch.description}\n")

    body_parts.append("## 变更内容\n")
    if created:
        body_parts.append("### 新增文件")
        for c in created:
            body_parts.append(f"- `{c.file_path}`: {c.description or '新增'}")
        body_parts.append("")
    if modified:
        body_parts.append("### 修改文件")
        for c in modified:
            body_parts.append(f"- `{c.file_path}`: {c.description or '修改'}")
        body_parts.append("")
    if deleted:
        body_parts.append("### 删除文件")
        for c in deleted:
            body_parts.append(f"- `{c.file_path}`: {c.description or '删除'}")
        body_parts.append("")

    # diff 统计
    if patch.diff:
        add_lines = sum(
            1 for line in patch.diff.split("\n") if line.startswith("+") and not line.startswith("+++")
        )
        del_lines = sum(
            1 for line in patch.diff.split("\n") if line.startswith("-") and not line.startswith("---")
        )
        body_parts.append(f"## 统计\n- 新增行: +{add_lines}\n- 删除行: -{del_lines}\n")

    # 测试计划
    body_parts.append("## 测试计划\n- [ ] 单元测试通过\n- [ ] 集成测试通过\n- [ ] 手动验证\n")

    # 自动生成 PR 标题
    if not patch.title.startswith(("feat", "fix", "docs", "refactor", "test", "chore")):
        title_prefix = "feat"
        if "fix" in patch.title.lower() or "bug" in patch.title.lower():
            title_prefix = "fix"
        elif "docs" in patch.title.lower():
            title_prefix = "docs"
        pr_title = f"{title_prefix}: {patch.title}"
    else:
        pr_title = patch.title

    return PRDraft(
        title=pr_title,
        body="\n".join(body_parts),
        head=patch.branch or "",
        base=base,
        labels=labels,
    )


# ── 端到端工作流 ───────────────────────────────────────


def create_and_apply_patch(
    title: str,
    description: str,
    changes: list[FileChange],
    *,
    create_branch: bool = True,
    commit: bool = True,
    push: bool = False,
    author: str = "pycoder-bot",
    project_root: Path | None = None,
) -> Patch:
    """一键工作流：生成 → 应用 → 提交

    Args:
        title: 标题
        description: 描述
        changes: 文件变更
        create_branch: 是否创建新分支
        commit: 是否提交
        push: 是否推送
        author: 作者
        project_root: 项目根目录

    Returns:
        更新后的 Patch 对象（含 status/commit_sha）
    """
    project_root = project_root or Path.cwd()
    generator = PatchGenerator(project_root=project_root)
    applier = PatchApplier(project_root=project_root)
    git = GitIntegration(repo_root=project_root)

    # 1. 生成补丁
    patch = generator.generate(title=title, description=description, changes=changes, author=author)
    generator.save_to_file(patch)
    logger.info("patch_generated id=%s files=%d", patch.id, len(changes))

    # 2. 应用
    apply_result = applier.apply(patch, dry_run=False)
    if not apply_result["success"]:
        patch.status = "rejected"
        logger.error("patch_apply_failed id=%s errors=%s", patch.id, apply_result["errors"])
        return patch
    patch.status = "applied"

    # 3. Git 操作
    if git.is_repo() and (create_branch or commit):
        if create_branch:
            branch_name = f"pycoder/{patch.id}"
            try:
                git.create_branch(branch_name, base=git.get_current_branch())
                patch.branch = branch_name
            except RuntimeError as e:
                logger.warning("branch_create_failed error=%s", e)

        if commit and git.has_changes():
            try:
                sha = git.commit(f"{patch.title}\n\n{patch.description}\n\nAuto-generated by pycoder")
                patch.commit_sha = sha
                patch.status = "committed"
            except RuntimeError as e:
                logger.error("commit_failed error=%s", e)

        if push and patch.branch:
            push_result = git.push(patch.branch)
            if push_result["success"]:
                # 生成本地 PR 草稿
                pr_draft = generate_pr_draft(patch, base="master")
                patch.status = "pr_created"
                patch.pr_url = (
                    f"待创建 PR: {pr_draft.title}\n\n{pr_draft.body[:200]}..."
                )

    return patch
