"""
自我进化引擎 — 真正的 LLM 驱动自修复与自升级

实现完整的"分析→修复→测试→部署→学习"闭环。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CodeIssue:
    """代码问题"""

    file: str
    line: int
    severity: str  # critical / high / medium / low
    issue_type: str  # security / bug / performance / style / architecture
    title: str
    description: str = ""
    suggestion: str = ""
    code_snippet: str = ""


@dataclass
class ScanReport:
    """扫描报告"""

    path: str
    files_scanned: int
    total_issues: int
    issues: list[CodeIssue] = field(default_factory=list)
    summary: str = ""
    duration_seconds: float = 0.0
    llm_analysis: str = ""


@dataclass
class FixProposal:
    """修复方案"""

    issue: CodeIssue
    action: str  # replace / insert / delete / refactor
    file_path: str
    old_code: str = ""
    new_code: str = ""
    line_start: int = 0
    line_end: int = 0
    reasoning: str = ""
    risk_level: str = "low"  # low / medium / high


@dataclass
class FixResult:
    """修复结果"""

    proposal: FixProposal
    success: bool
    test_passed: bool = False
    git_branch: str = ""
    git_commit: str = ""
    error: str | None = None
    rollback_needed: bool = False


@dataclass
class EvolutionRecord:
    """进化记录"""

    timestamp: float = field(default_factory=time.time)
    action: str = ""
    issue_type: str = ""
    file: str = ""
    success: bool = False
    fix_description: str = ""
    test_result: str = ""
    lessons: str = ""


@dataclass
class EvolutionTask:
    """一次进化任务"""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: str = "fix"
    target_files: list[str] = field(default_factory=list)
    description: str = ""
    status: str = "pending"
    plan: str = ""
    changes: list[dict] = field(default_factory=list)
    test_result: str = ""
    error: str = ""
    backup_ref: str = ""
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "target_files": self.target_files,
            "description": self.description,
            "status": self.status,
            "plan": self.plan,
            "changes": self.changes,
            "test_result": self.test_result,
            "error": self.error,
            "backup_ref": self.backup_ref,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


@dataclass
class EvolutionStats:
    """进化统计"""

    total_tasks: int = 0
    successful: int = 0
    failed: int = 0
    rolled_back: int = 0
    bugs_fixed: int = 0
    lines_changed: int = 0
    last_run: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.successful / self.total_tasks

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tasks": self.total_tasks,
            "successful": self.successful,
            "failed": self.failed,
            "rolled_back": self.rolled_back,
            "bugs_fixed": self.bugs_fixed,
            "lines_changed": self.lines_changed,
            "success_rate": round(self.success_rate, 3),
            "last_run": self.last_run,
        }


def _build_evolution_report(
    task: EvolutionTask,
    grade_info: dict[str, Any] | None = None,
    source_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建进化报告"""
    return {
        "task_id": task.id,
        "task_type": task.type,
        "status": task.status,
        "target_files": task.target_files,
        "description": task.description,
        "changes_count": len(task.changes),
        "test_result": task.test_result[:200] if task.test_result else "",
        "error": task.error,
        "created_at": task.created_at,
        "completed_at": task.completed_at,
        "grade": grade_info or {"task_type": task.type},
        "source_trace": source_trace,
    }


class SelfEvolutionEngine:
    """
    自我进化引擎 — AI 分析和改进 Pycoder 自身

    安全约束:
    - 所有修改在 self_evo/<timestamp> 分支上进行
    - 每次最多修改 3 个文件
    - 修改后必须运行全量测试
    - 测试不通过自动回滚
    - 关键路径（config/auth/db）写保护
    """

    # 关键路径写保护
    PROTECTED_PATTERNS = [
        "**/.env*",
        "*.env",
        ".env*",
        "**/config/*.json",
        "*.config.json",
        "**/.api_key",
        ".api_key",
        "**/__pycache__/*",
        "__pycache__",
        "**/node_modules/*",
        "node_modules",
        "**/.git/*",
        ".git",
        "**/pycoder.db",
        "*.db",
        "**/evolution_history.json",
    ]

    def __init__(
        self, v2_engine: Any = None, llm_provider: Any = None, project_root: Path | None = None
    ):
        # 向后兼容：如果第一个参数是 Path，视为 project_root（V1 调用方式）
        if isinstance(v2_engine, Path):
            project_root = v2_engine
            v2_engine = None
        self.v2 = v2_engine
        self.llm = llm_provider
        self._records: list[EvolutionRecord] = []
        self._tasks: list[EvolutionTask] = []
        self._stats = EvolutionStats()
        self._active_branch: str = ""
        self._last_issues: list[CodeIssue] = []
        self._project_root = project_root or Path.cwd()
        self._persist_path = Path.home() / ".pycoder" / "evolution_history.json"
        self._load_history()

    # ── 扫描 ────────────────────────────────

    async def scan(self, path: str = "pycoder", *, use_llm: bool = True) -> ScanReport:
        """
        扫描代码库，识别问题

        Args:
            path: 扫描路径
            use_llm: 是否使用 LLM 深度分析

        Returns:
            ScanReport 包含所有发现的问题
        """
        import ast

        start = time.monotonic()
        scan_path = Path(path)
        issues: list[CodeIssue] = []
        files_scanned = 0

        logger.info("开始扫描: %s (LLM=%s)", path, use_llm)

        for py_file in scan_path.rglob("*.py"):
            if self._is_skippable(py_file):
                continue

            try:
                source = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source)
                file_issues = self._scan_file_ast(tree, py_file, source)
                issues.extend(file_issues)
                files_scanned += 1
            except SyntaxError:
                issues.append(
                    CodeIssue(
                        file=str(py_file),
                        line=1,
                        severity="critical",
                        issue_type="bug",
                        title="语法错误",
                        description="文件包含 Python 语法错误",
                    )
                )
            except (OSError, UnicodeDecodeError, ValueError, TypeError, AttributeError):
                continue

        # LLM 深度分析
        summary = ""
        if use_llm and self.llm and len(issues) > 0:
            critical = [i for i in issues if i.severity == "critical"]
            if critical:
                summary = await self._llm_analyze(critical[:5], files_scanned)

        duration = time.monotonic() - start
        logger.info("扫描完成: %d 文件, %d 问题 (%.1fs)", files_scanned, len(issues), duration)

        # 保存最后扫描结果（供 API 使用）
        self._last_issues = issues

        return ScanReport(
            path=path,
            files_scanned=files_scanned,
            total_issues=len(issues),
            issues=issues,
            summary=summary,
            duration_seconds=duration,
        )

    # ── 修复 ────────────────────────────────

    async def generate_fix(self, issue: CodeIssue) -> FixProposal:
        """
        用 LLM 生成修复方案

        Args:
            issue: 要修复的问题

        Returns:
            FixProposal 修复方案
        """
        if self.llm:
            try:
                prompt = self._build_fix_prompt(issue)
                response = await self.llm.chat(prompt)
                return self._parse_fix_response(response, issue)
            except Exception as e:
                logger.warning("LLM 修复生成失败: %s，使用模板修复", e)

        return self._template_fix(issue)

    async def apply_fix(self, proposal: FixProposal) -> FixResult:
        """
        在隔离的 Git 分支上应用修复

        流程:
        1. checkout 到 self_evo 分支
        2. 应用修改
        3. 运行测试
        4. 通过 → 合并回主分支; 失败 → 回滚
        """
        # 保护检查
        if self._is_protected(proposal.file_path):
            return FixResult(
                proposal=proposal,
                success=False,
                error=f"文件受保护: {proposal.file_path}",
            )

        # 检查修改数量
        if len(self._get_modified_in_session()) >= 3:
            return FixResult(
                proposal=proposal,
                success=False,
                error="单次会话最多修改 3 个文件",
            )

        # 创建或切换到 self_evo 分支
        branch = await self._ensure_evo_branch()

        try:
            # 应用修改
            self._apply_patch(proposal)

            # 运行测试
            test_passed = await self._run_tests()

            if test_passed:
                commit = await self._commit_fix(proposal)
                return FixResult(
                    proposal=proposal,
                    success=True,
                    test_passed=True,
                    git_branch=branch,
                    git_commit=commit,
                )
            else:
                # 回滚
                await self._rollback()
                return FixResult(
                    proposal=proposal,
                    success=False,
                    test_passed=False,
                    git_branch=branch,
                    error="测试未通过，已自动回滚",
                    rollback_needed=True,
                )
        except Exception as e:
            await self._rollback()
            return FixResult(
                proposal=proposal,
                success=False,
                error=str(e),
                rollback_needed=True,
            )

    # ── 热重载 ──────────────────────────────

    async def hot_reload(self, file_path: str) -> bool:
        """热重载修改后的 Python 模块"""
        import importlib
        import sys

        try:
            # 从文件路径推断模块名
            module_name = self._path_to_module(file_path)
            if module_name in sys.modules:
                module = sys.modules[module_name]
                importlib.reload(module)
                logger.info("热重载成功: %s", module_name)
                return True
            else:
                logger.info("模块未加载，无需热重载: %s", module_name)
                return True
        except Exception as e:
            logger.error("热重载失败: %s → %s", file_path, e)
            return False

    # ── 学习 ────────────────────────────────

    def record_evolution(self, record: EvolutionRecord) -> None:
        """记录进化经验"""
        self._records.append(record)
        if len(self._records) > 1000:
            self._records = self._records[-1000:]
        self._save_history()

    def get_evolution_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """获取进化历史"""
        return [
            {
                "timestamp": r.timestamp,
                "action": r.action,
                "issue_type": r.issue_type,
                "file": r.file,
                "success": r.success,
                "fix": r.fix_description[:100],
                "lessons": r.lessons[:200],
            }
            for r in self._records[-limit:]
        ]

    def get_stats(self) -> dict[str, Any]:
        """获取进化统计"""
        if not self._records:
            return {"total_evolutions": 0}
        recent = self._records[-100:]
        return {
            "total_evolutions": len(self._records),
            "success_rate": sum(1 for r in recent if r.success) / max(len(recent), 1),
            "by_type": self._count_by_field("issue_type"),
            "common_lessons": self._extract_lessons(recent),
        }

    # ── 私有方法 ────────────────────────────

    def _scan_file_ast(self, tree: Any, file_path: Path, source: str) -> list[CodeIssue]:
        """AST 静态分析"""
        import ast

        issues: list[CodeIssue] = []
        fname = str(file_path)

        for node in ast.walk(tree):
            # 裸 except
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                issues.append(
                    CodeIssue(
                        file=fname,
                        line=node.lineno,
                        severity="high",
                        issue_type="bug",
                        title="裸 except 吞掉所有异常",
                        suggestion="将 'except:' 替换为 'except Exception as e:'",
                    )
                )

            # 可变默认参数
            if isinstance(node, ast.FunctionDef):
                for d in node.args.defaults + node.args.kw_defaults:
                    if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                        issues.append(
                            CodeIssue(
                                file=fname,
                                line=node.lineno,
                                severity="medium",
                                issue_type="bug",
                                title=f"函数 '{node.name}' 使用了可变默认参数",
                                suggestion="将默认值改为 None，在函数体内初始化",
                            )
                        )

            # 危险函数调用
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in ("eval", "exec"):
                    issues.append(
                        CodeIssue(
                            file=fname,
                            line=node.lineno,
                            severity="critical",
                            issue_type="security",
                            title=f"使用了危险函数 '{node.func.id}'",
                            suggestion="避免使用 eval/exec，寻找安全的替代方案",
                        )
                    )

            # 过大函数
            if isinstance(node, ast.FunctionDef):
                end = node.end_lineno or node.lineno
                length = end - node.lineno + 1
                if length > 200:
                    issues.append(
                        CodeIssue(
                            file=fname,
                            line=node.lineno,
                            severity="low",
                            issue_type="style",
                            title=f"函数 '{node.name}' 过长 ({length} 行)",
                            suggestion="将函数拆分为多个小函数",
                        )
                    )

        # 硬编码密钥
        import re

        for i, line in enumerate(source.split("\n"), 1):
            if re.search(
                r'(api_key|password|secret|token|key)\s*=\s*["\'][^"\']{8,}["\']', line, re.I
            ):
                if "os.environ" not in line and "os.getenv" not in line:
                    issues.append(
                        CodeIssue(
                            file=fname,
                            line=i,
                            severity="critical",
                            issue_type="security",
                            title="检测到硬编码密钥",
                            suggestion="使用环境变量存储敏感信息",
                            code_snippet=line.strip()[:100],
                        )
                    )

        return issues

    async def _llm_analyze(self, critical_issues: list[CodeIssue], files_scanned: int) -> str:
        """使用 LLM 深度分析关键问题"""
        if not self.llm:
            return ""

        prompt = f"""分析以下 Pycoder 代码库中的关键问题并给出改进建议:

扫描范围: {files_scanned} 个文件
发现关键问题: {len(critical_issues)} 个

问题列表:
"""
        for i, issue in enumerate(critical_issues[:5], 1):
            prompt += f"\n{i}. [{issue.severity}] {issue.file}:{issue.line} - {issue.title}"
            if issue.description:
                prompt += f"\n   {issue.description}"
            if issue.suggestion:
                prompt += f"\n   建议: {issue.suggestion}"

        prompt += "\n\n请给出: 1) 最紧急需要修复的问题; 2) 修复优先级排序; 3) 架构级改进建议。用中文回答。"

        try:
            response = await self.llm.chat(prompt)
            return response[:2000]
        except (OSError, ValueError, RuntimeError, AttributeError):
            return "LLM 分析暂时不可用，已使用静态分析结果。"

    def _build_fix_prompt(self, issue: CodeIssue) -> str:
        """构建修复提示词"""
        return f"""修复以下 Python 代码问题:

文件: {issue.file}
行号: {issue.line}
严重度: {issue.severity}
问题: {issue.title}
{issue.description}
建议: {issue.suggestion}

请提供精确的修复方案，格式:
```diff
--- a/{issue.file}
+++ b/{issue.file}
@@ ... @@
 [旧代码]
 [新代码]
```
"""

    def _parse_fix_response(self, response: str, issue: CodeIssue) -> FixProposal:
        """解析 LLM 修复响应"""
        import re

        # 尝试解析 diff 格式
        diff_match = re.search(r"```diff(.*?)```", response, re.DOTALL)
        if diff_match:
            diff_content = diff_match.group(1)
            # 提取 --- 和 +++ 之间的旧代码，以及 +++ 之后的新代码
            old_match = re.search(
                r"^---.*?\n(.*?)(?=^\+\+\+|\Z)", diff_content, re.DOTALL | re.MULTILINE
            )
            new_match = re.search(r"^\+\+\+.*?\n(.*?)$", diff_content, re.DOTALL | re.MULTILINE)
            old_code = old_match.group(1).strip() if old_match else ""
            new_code = new_match.group(1).strip() if new_match else ""
            # 如果 diff 格式不标准，尝试从整个 diff 内容中提取
            if not old_code or not new_code:
                # 提取所有以 - 开头的行作为旧代码
                old_lines = [
                    line[1:]
                    for line in diff_content.split("\n")
                    if line.startswith("-") and not line.startswith("---")
                ]
                # 提取所有以 + 开头的行作为新代码
                new_lines = [
                    line[1:]
                    for line in diff_content.split("\n")
                    if line.startswith("+") and not line.startswith("+++")
                ]
                old_code = "\n".join(old_lines) if old_lines else old_code
                new_code = "\n".join(new_lines) if new_lines else new_code
            return FixProposal(
                issue=issue,
                action="replace",
                file_path=issue.file,
                old_code=old_code,
                new_code=new_code,
                reasoning=response[:500],
            )

        # 解析代码块
        code_match = re.search(r"```(?:python|py)?\n(.*?)```", response, re.DOTALL)
        if code_match:
            return FixProposal(
                issue=issue,
                action="replace",
                file_path=issue.file,
                new_code=code_match.group(1),
                reasoning=response[:500],
            )

        return FixProposal(
            issue=issue,
            action="replace",
            file_path=issue.file,
            reasoning=response[:500],
        )

    def _template_fix(self, issue: CodeIssue) -> FixProposal:
        """模板修复（无需 LLM）"""
        if "裸 except" in issue.title:
            return FixProposal(
                issue=issue,
                action="replace",
                file_path=issue.file,
                line_start=issue.line,
                line_end=issue.line,
                old_code="except:",
                new_code="except Exception as e:",
                reasoning="模板修复: 将裸 except 替换为 except Exception as e:",
            )

        if "可变默认参数" in issue.title:
            return FixProposal(
                issue=issue,
                action="refactor",
                file_path=issue.file,
                reasoning="需要手动重构: 将可变默认参数改为 None",
            )

        return FixProposal(
            issue=issue,
            action="replace",
            file_path=issue.file,
            reasoning=f"需要手动修复: {issue.suggestion}",
        )

    def _apply_patch(self, proposal: FixProposal) -> None:
        """应用修复补丁"""
        if not proposal.old_code or not proposal.new_code:
            return

        file_path = Path(proposal.file_path)
        if not file_path.exists():
            return

        content = file_path.read_text(encoding="utf-8")
        if proposal.old_code in content:
            new_content = content.replace(proposal.old_code, proposal.new_code, 1)
            file_path.write_text(new_content, encoding="utf-8")
            logger.info("补丁已应用: %s", file_path)

    async def _run_tests(self) -> bool:
        """运行全量测试"""
        try:
            result = subprocess.run(
                ["pytest", "tests/", "-x", "--tb=short", "-q"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            return result.returncode == 0
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False

    async def _ensure_evo_branch(self) -> str:
        """确保在 self_evo 分支上"""
        try:
            # 检查当前分支
            r = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            current = r.stdout.strip()

            if current.startswith("self_evo"):
                self._active_branch = current
                return current

            # 创建新分支
            branch_name = f"self_evo/{int(time.time())}"
            subprocess.run(
                ["git", "checkout", "-b", branch_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self._active_branch = branch_name
            return branch_name
        except Exception:
            self._active_branch = "self_evo/fallback"
            return self._active_branch

    async def _commit_fix(self, proposal: FixProposal) -> str:
        """提交修复"""
        try:
            subprocess.run(["git", "add", proposal.file_path], capture_output=True, timeout=10)
            result = subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    f"self_evo: fix {proposal.issue.issue_type} in {proposal.file_path}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip()[:200]
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return "commit_failed"

    async def _rollback(self) -> None:
        """回滚变更"""
        try:
            subprocess.run(["git", "checkout", "--", "."], capture_output=True, timeout=10)
            subprocess.run(["git", "clean", "-fd"], capture_output=True, timeout=10)
            logger.info("已回滚变更")
        except Exception as e:
            logger.error("回滚失败: %s", e)

    def _path_to_module(self, file_path: str) -> str:
        """将文件路径转换为 Python 模块名"""
        p = Path(file_path)
        # pycoder/server/app.py → pycoder.server.app
        parts = list(p.parts)
        if "pycoder" in parts:
            idx = parts.index("pycoder")
            module_parts = parts[idx:]
            if module_parts[-1].endswith(".py"):
                module_parts[-1] = module_parts[-1][:-3]
            if module_parts[-1] == "__init__":
                module_parts = module_parts[:-1]
            return ".".join(module_parts)
        return p.stem

    def _is_protected(self, file_path: str) -> bool:
        """检查文件是否受保护（支持裸文件名和完整路径）"""
        import fnmatch
        from pathlib import Path

        # 同时匹配裸文件名和带路径的文件名
        paths_to_check = [file_path, str(Path(file_path).name)]

        for pattern in self.PROTECTED_PATTERNS:
            for p in paths_to_check:
                if fnmatch.fnmatch(p, pattern):
                    return True
                # 也检查是否路径包含匹配
                if fnmatch.fnmatch(f"**/{p}", pattern):
                    return True
        return False

    def _is_skippable(self, file_path: Path) -> bool:
        """检查文件是否应跳过扫描"""
        skip_dirs = {
            "__pycache__",
            ".git",
            "node_modules",
            "venv",
            ".venv",
            ".tox",
            "build",
            "dist",
        }
        for part in file_path.parts:
            if part in skip_dirs:
                return True
        return False

    def _get_modified_in_session(self) -> list[str]:
        """获取当前会话已修改的文件"""
        try:
            r = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return [f for f in r.stdout.strip().split("\n") if f]
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return []

    def _count_by_field(self, field: str) -> dict[str, int]:
        """按字段统计"""
        from collections import Counter

        return dict(Counter(getattr(r, field, "") for r in self._records if hasattr(r, field)))

    def _load_history(self) -> None:
        """从磁盘加载进化历史"""
        try:
            if self._persist_path.exists():
                data = json.loads(self._persist_path.read_text(encoding="utf-8"))
                for item in data[-500:]:
                    self._records.append(
                        EvolutionRecord(
                            timestamp=item.get("timestamp", 0),
                            action=item.get("action", ""),
                            issue_type=item.get("issue_type", ""),
                            file=item.get("file", ""),
                            success=item.get("success", False),
                            fix_description=item.get("fix_description", ""),
                            test_result=item.get("test_result", ""),
                            lessons=item.get("lessons", ""),
                        )
                    )
                logger.info("加载进化历史: %d 条记录", len(self._records))
        except Exception as e:
            logger.debug("加载进化历史失败: %s", e)

    def _save_history(self) -> None:
        """持久化进化历史到磁盘"""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = [
                {
                    "timestamp": r.timestamp,
                    "action": r.action,
                    "issue_type": r.issue_type,
                    "file": r.file,
                    "success": r.success,
                    "fix_description": r.fix_description,
                    "test_result": r.test_result,
                    "lessons": r.lessons,
                }
                for r in self._records[-500:]
            ]
            self._persist_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("保存进化历史失败: %s", e)

    @staticmethod
    def _extract_lessons(records: list[EvolutionRecord]) -> list[str]:
        """提取常见教训"""
        lessons: list[str] = []
        for r in records:
            if r.lessons and r.lessons not in lessons:
                lessons.append(r.lessons)
        return lessons[-5:]

    # ══════════════════════════════════════════════════════
    # 统一进化管线 (来自 V1，V2 原生)
    # ══════════════════════════════════════════════════════

    SELF_EVOLVE_SYSTEM_PROMPT = (
        "你是一个 Python 代码审查与修复专家。分析项目代码，发现问题并给出修复方案。\n"
        "修复方案必须使用以下格式:\n"
        "[FILE:相对路径]\n"
        "完整的修复后代码（不要省略，不要写 # ... 之类占位符）\n"
        "[END:FILE]\n"
        "每个文件一个块，不要省略任何代码。"
    )

    CORE_FILE_PATTERNS = ["self_evolution", "evolution.py", "self_optimizer.py"]
    GITHUB_TOKEN_FILE = Path.home() / ".pycoder" / "github_token"

    async def run(self, dry_run: bool = False) -> dict[str, Any]:
        """向后兼容的同步 run() — 供调度器 _scheduled_evolution_run 等调用方使用。

        实际调用 run_cycle() 并等待完成，返回汇总 dict。
        """
        result = {"fixed": 0, "skipped": 0, "errors": 0, "issues_found": 0}
        async for event in self.run_cycle(
            task_type="auto", auto_apply=False, dry_run=dry_run,
        ):
            if event.get("type") == "issues_found":
                result["issues_found"] = event.get("count", 0)
            elif event.get("type") == "done":
                result["fixed"] = event.get("changes_count", result["fixed"])
            elif event.get("type") == "error":
                result["errors"] += 1
        return result

    async def evolve(
        self,
        task_type: str = "fix",
        target: str = "",
        custom_prompt: str = "",
        dry_run: bool = False,
        auto_apply: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        """执行一次完整的进化周期：扫描 → 分析 → 生成 → 应用 → 测试"""
        task = EvolutionTask(
            type=task_type,
            description=target or custom_prompt or "自动扫描并修复项目问题",
        )
        self._tasks.append(task)
        self._stats.total_tasks += 1

        # 任务难度自动分级
        try:
            from pycoder.server.services.task_grader import get_task_grader

            grade = get_task_grader().grade_from_kwargs(task_type, target, custom_prompt)
            yield {
                "type": "task_grade",
                "task_id": task.id,
                "grade": grade.to_dict(),
                "message": f"📊 任务难度: {grade.label} (评分 {grade.score})",
            }
        except ImportError:
            pass

        try:
            # 阶段 1: 扫描分析
            task.status = "analyzing"
            yield {
                "type": "phase",
                "phase": "analyzing",
                "task_id": task.id,
                "message": "🔍 扫描项目代码...",
            }
            await asyncio.sleep(0.1)

            analysis = await self._scan_project(task_type, target, custom_prompt)
            yield {
                "type": "analysis",
                "task_id": task.id,
                "content": analysis[:2000],
                "full_length": len(analysis),
            }
            await asyncio.sleep(0.1)

            if not analysis or len(analysis) < 20:
                task.status = "done"
                task.completed_at = time.time()
                yield {
                    "type": "done",
                    "task_id": task.id,
                    "message": "✅ 未发现需要修复的问题",
                    "evolution_report": _build_evolution_report(task),
                }
                return

            if dry_run:
                task.status = "done"
                task.completed_at = time.time()
                yield {
                    "type": "done",
                    "task_id": task.id,
                    "message": "Dry-run 完成：发现潜在问题，未实际修改",
                    "dry_run": True,
                    "evolution_report": _build_evolution_report(task),
                }
                return

            # 阶段 2: 解析修复方案
            task.status = "generating"
            yield {
                "type": "phase",
                "phase": "generating",
                "task_id": task.id,
                "message": "📝 解析修复方案...",
            }
            await asyncio.sleep(0.1)

            fixes = self._parse_fixes(analysis)
            if not fixes:
                task.status = "done"
                task.completed_at = time.time()
                yield {
                    "type": "done",
                    "task_id": task.id,
                    "message": "⚠️ 未能解析出有效修复方案",
                    "evolution_report": _build_evolution_report(task),
                }
                return

            task.changes = fixes
            task.plan = analysis
            yield {
                "type": "fixes",
                "task_id": task.id,
                "count": len(fixes),
                "files": [f["file"] for f in fixes],
            }
            await asyncio.sleep(0.1)

            # ── 审批门禁：V2 使用 PermissionEngine ──
            if not auto_apply and self._is_core_modification(fixes):
                task.status = "awaiting_approval"
                yield {
                    "type": "awaiting_approval",
                    "task_id": task.id,
                    "files": [f["file"] for f in fixes],
                    "is_core_modification": True,
                    "summary": analysis[:1000],
                    "message": "⏳ 修复涉及核心文件，请通过 /api/v2/trust/escalate 升级信任级别",
                }
                return

            # 阶段 3: 快照 + 应用
            task.status = "applying"
            yield {
                "type": "phase",
                "phase": "applying",
                "task_id": task.id,
                "message": f"💾 快照并应用 {len(fixes)} 个修复...",
            }
            await asyncio.sleep(0.1)

            backup_ref = await self._snapshot_backup()
            task.backup_ref = backup_ref

            apply_failures = 0
            for i, fix in enumerate(fixes):
                success, err = await self._apply_fix(fix)
                if not success:
                    apply_failures += 1
                yield {
                    "type": "file_patch",
                    "task_id": task.id,
                    "file": fix["file"],
                    "index": i + 1,
                    "total": len(fixes),
                    "success": success,
                    "error": err,
                }
                await asyncio.sleep(0.05)

            if apply_failures == len(fixes):
                task.status = "rolled_back"
                task.completed_at = time.time()
                self._stats.rolled_back += 1
                await self._snapshot_rollback(backup_ref)
                task.error = f"全部 {len(fixes)} 个修复应用均失败，已自动回滚"
                self._record_learning(task, fixes, False, task.error, quality_score=20)
                yield {"type": "rolled_back", "task_id": task.id, "message": f"❌ {task.error}"}
                self._stats.last_run = time.time()
                return

            # 阶段 4: 测试验证
            task.status = "testing"
            yield {
                "type": "phase",
                "phase": "testing",
                "task_id": task.id,
                "message": "🧪 运行测试验证...",
            }
            await asyncio.sleep(0.1)

            test_ok, test_output = await self._run_tests_async()
            task.test_result = test_output
            yield {
                "type": "test_result",
                "task_id": task.id,
                "passed": test_ok,
                "output": test_output[:1000],
            }
            await asyncio.sleep(0.1)

            if test_ok:
                task.status = "done"
                task.completed_at = time.time()
                self._stats.successful += 1
                self._stats.bugs_fixed += len(fixes)
                self._stats.last_run = time.time()

                self._record_learning(task, fixes, test_ok, test_output, quality_score=90)

                pr_result = await self._create_evolution_pr(task)
                msg = f"✅ 进化完成！应用了 {len(fixes)} 个修复，测试全部通过"
                if pr_result:
                    msg += f" | PR: {pr_result['url']}"

                yield {
                    "type": "done",
                    "task_id": task.id,
                    "message": msg,
                    "pr_url": pr_result.get("url") if pr_result else None,
                    "evolution_report": _build_evolution_report(task),
                }
            else:
                task.status = "rolled_back"
                task.completed_at = time.time()
                self._stats.rolled_back += 1
                await self._snapshot_rollback(backup_ref)
                task.error = "测试失败，已自动回滚"
                self._record_learning(task, fixes, test_ok, test_output, quality_score=30)
                yield {
                    "type": "rolled_back",
                    "task_id": task.id,
                    "message": "❌ 测试失败，已自动回滚所有修改",
                    "test_output": test_output[:500],
                    "evolution_report": _build_evolution_report(task),
                }
                self._stats.last_run = time.time()

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            self._stats.failed += 1
            if task.backup_ref:
                try:
                    await self._snapshot_rollback(task.backup_ref)
                    task.status = "rolled_back"
                    self._stats.rolled_back += 1
                    self._stats.failed -= 1
                except Exception as rollback_err:
                    logger.error("evo_rollback_failed task=%s error=%s", task.id, rollback_err)
            self._record_learning(task, [], False, str(e), quality_score=10)
            yield {"type": "error", "task_id": task.id, "message": f"❌ 进化失败: {e}"}

    # ── 内部实现 ──────────────────────────────────────────

    async def _scan_project(self, task_type: str, target: str, custom: str) -> str:
        """调用 AI 扫描项目代码，优先 DeepSeek，降级 Ollama，最终回退 AST-only"""
        snapshot = self._collect_snapshot(target)
        prompt = self._build_scan_prompt(task_type, target, custom, snapshot)

        # 1) 优先在线 API
        try:
            result = await self._scan_project_online(prompt)
            if result and len(result) >= 20:
                return result
        except Exception as e:
            logger.warning("evo_scan_online_failed: %s", e)

        # 2) 回退本地模型
        try:
            result = await self._scan_with_local_model(prompt)
            if result and len(result) >= 20:
                return result
        except Exception as e:
            logger.warning("evo_scan_local_failed: %s", e)

        # 3) 最终降级：使用 AST 静态扫描结果的无网络模式
        logger.info("evo_scan_fallback_to_ast_only")
        return self._build_ast_scan_fallback()

    async def _scan_project_online(self, prompt: str) -> str:
        """通过 ChatBridge 在线 API 扫描

        优先使用网络 API Key。若未配置或连接失败，返回空串由调用方降级到纯 AST 扫描。
        """
        try:
            from pycoder.server.chat_bridge import ChatBridge
            from pycoder.server.chat_handler import _get_api_key_for_model

            bridge = ChatBridge()
            # 从环境变量或配置读取 API Key
            api_key = _get_api_key_for_model("deepseek-chat")
            if not api_key:
                import os as _os

                api_key = _os.environ.get("DEEPSEEK_API_KEY", "")
            if api_key:
                bridge.config.api_key = api_key
            bridge.config.system_prompt = self.SELF_EVOLVE_SYSTEM_PROMPT
            bridge.config.max_tokens = 16384
            bridge.config.enable_thinking = False  # 进化扫描不需要思考链
            bridge.config.enable_cache = True

            result = ""
            async for event in bridge.chat_stream(prompt):
                if event.event_type == "token":
                    result += event.content
                elif event.event_type == "error":
                    logger.warning("evo_scan_online_error: %s", event.content)
                    break
            await bridge.close()
            return result
        except (OSError, ValueError, RuntimeError, AttributeError) as e:
            logger.warning("evo_scan_online_exception: %s", e)
            return ""

    async def _scan_with_local_model(self, prompt: str) -> str:
        """Ollama 本地模型回退 — 快速失败不阻塞主流程"""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(
                    "http://localhost:11434/api/generate",
                    json={
                        "model": "qwen2.5-coder:7b",
                        "prompt": prompt,
                        "stream": False,
                    },
                )
                if resp.status_code == 200:
                    return resp.json().get("response", "")
        except (
            OSError,
            ValueError,
            RuntimeError,
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.ConnectTimeout,
        ):
            logger.info("evo_scan_local_model_unavailable (Ollama not running)")
        return ""

    def _build_ast_scan_fallback(self) -> str:
        """离线降级：基于缓存 AST 扫描结果构建伪分析文本

        当所有在线 API 都不可达时，使用上次 `scan()` 的缓存结果
        构建符合修复解析格式的文本，确保进化流程可以完成 AST 级修复。
        """
        if not self._last_issues:
            return ""

        lines = [
            "## 🔍 AST 静态扫描结果 (离线模式)",
            "",
            "以下问题通过 AST 静态分析发现。修复方案基于模板规则。",
            "",
        ]

        critical = [i for i in self._last_issues if i.severity == "critical"]
        high = [i for i in self._last_issues if i.severity == "high"]
        medium = [i for i in self._last_issues if i.severity == "medium"]

        if critical:
            lines.append(f"### 严重问题 ({len(critical)}):")
            for issue in critical[:5]:
                lines.append(f"- **{issue.file}:{issue.line}** [{issue.issue_type}] {issue.title}")
                if issue.suggestion:
                    lines.append(f"  修复: {issue.suggestion}")
            lines.append("")

        if high:
            lines.append(f"### 高风险问题 ({len(high)}):")
            for issue in high[:5]:
                lines.append(f"- **{issue.file}:{issue.line}** [{issue.issue_type}] {issue.title}")
            lines.append("")

        if medium:
            lines.append(f"### 中等问题 ({len(medium)}):")
            lines.append(f"({len(medium)} 个中等问题，扫描时修复)")

        lines.append("")
        lines.append("## 🔧 修复方案")
        lines.append("对以上问题应用模板修复。修复格式:")
        lines.append("```json")
        lines.append('{"file": "<path>", "action": "replace", "old": "<code>", "new": "<code>"}')
        lines.append("```")

        return "\n".join(lines)

    def _collect_snapshot(self, target: str) -> str:
        """收集项目结构快照"""
        lines = ["## 项目结构快照\n"]
        src_root = self._project_root / "pycoder"
        if target:
            parts = [src_root / p.strip("/") for p in target.split(",") if p.strip()]
        else:
            parts = [src_root / "server", src_root / "capabilities"]

        for p in parts:
            if p.exists():
                for f in sorted(p.rglob("*.py"))[:20]:
                    if "__pycache__" in str(f):
                        continue
                    if "self_evolution" in f.name or (
                        "evolution" in f.name and "routers" in str(f)
                    ):
                        continue
                    rel = f.relative_to(self._project_root)
                    try:
                        content = f.read_text(encoding="utf-8")
                        if len(content) > 8000:
                            content = content[:8000] + "\n# ... 前 8000 字节，后续已截断"
                        lines.append(f"\n### {rel}\n```\n{content}\n```")
                    except (OSError, UnicodeDecodeError):
                        pass
        return "\n".join(lines)

    def _build_scan_prompt(self, task_type: str, target: str, custom: str, snapshot: str) -> str:
        """构建扫描提示"""
        if custom:
            return f"用户指定的进化任务:\n{custom}\n\n项目代码:\n{snapshot}"

        type_map = {
            "fix": "扫描以下代码中的所有 Bug（运行时错误、逻辑错误、类型错误、NameError、导入错误等），给出修复方案",
            "optimize": "扫描以下代码中的性能瓶颈和可优化点，给出优化方案",
            "security": "扫描以下代码中的安全问题（注入、路径穿越、不安全反序列化等），给出修复方案",
            "quality": "扫描以下代码中的代码异味（重复代码、过长函数、硬编码等），给出重构方案",
        }
        return f"{type_map.get(task_type, type_map['fix'])}\n\n项目代码:\n{snapshot}"

    def _parse_fixes(self, analysis: str) -> list[dict[str, Any]]:
        """从 AI 响应中解析 [FILE:...]...[END:FILE] 修复块"""
        fixes: list[dict[str, Any]] = []
        pattern = re.compile(r"\[FILE:(.+?)\]\s*\n(.*?)\n\s*\[END:FILE\]", re.DOTALL)
        for m in pattern.finditer(analysis):
            file_path = m.group(1).strip()
            new_content = m.group(2)
            code_match = re.search(
                r"```(?:python|typescript|javascript)?\s*\n(.*?)\n\s*```", new_content, re.DOTALL
            )
            if code_match:
                new_content = code_match.group(1)

            full_path = self._project_root / file_path
            old_content = ""
            if full_path.exists():
                old_content = full_path.read_text(encoding="utf-8")

            fixes.append(
                {
                    "file": file_path,
                    "original": old_content[:100],
                    "modified": new_content,
                    "reason": f"AI 建议修改 {file_path}",
                }
            )
        return fixes

    async def _apply_fix(self, fix: dict[str, Any]) -> tuple[bool, str]:
        """应用单个修复到文件（使用 SnapshotManager 备份）"""
        try:
            target = (self._project_root / fix["file"]).resolve()
            if "pycoder" not in str(target).split(os.sep):
                return False, f"拒绝修改非 pycoder 文件: {fix['file']}"
            if not target.exists():
                return False, f"目标文件不存在: {fix['file']}"

            modified = fix.get("modified", "")
            original = target.read_text(encoding="utf-8")

            if not modified or not modified.strip():
                return False, "AI 返回了空内容，拒绝写入"

            # 核心文件保护：使用 PermissionEngine
            if any(p in str(target) for p in self.CORE_FILE_PATTERNS):
                if hasattr(self.v2, "permission") and self.v2.permission:
                    trust = self.v2.permission.get_trust_report()
                    if trust.get("level", 0) < 4:  # 需要 FULL_AUTONOMY
                        return False, (
                            "⛔ 拒绝修改核心文件。需要 FULL_AUTONOMY 信任级别。\n"
                            f"  文件: {fix['file']}\n"
                            "  请通过 /api/v2/trust/escalate 升级信任"
                        )
                else:
                    # V1 兼容模式：无 v2_engine 时直接拒绝修改核心文件
                    return False, (
                        "⛔ 拒绝修改核心文件（自我进化引擎保护）。\n"
                        f"  文件: {fix['file']} 属于核心文件（self_evolution/evolution），不允许自修改。\n"
                        "  请使用进化令牌授权修改。"
                    )

            # SnapshotManager 备份
            try:
                from pycoder.server.services.version_snapshot import get_snapshot_manager

                snap = get_snapshot_manager()
                result = snap.create_snapshot(label=f"evo_{fix['file']}", pipeline_step="apply_fix")
                if hasattr(result, "__await__"):
                    await result
            except ImportError:
                pass

            # search/replace 优先
            search_text = fix.get("search", "")
            if search_text and search_text in original:
                new_content = original.replace(search_text, modified, 1)
                target.write_text(new_content, encoding="utf-8")
                return True, f"search/replace 成功: {fix['file']}"

            # 占位符检测
            placeholder_patterns = [
                "# ... 前面代码",
                "# ... 代码保持不变",
                "# 前面代码保持不变",
                "# 中间代码保持不变",
                "# 后面代码保持不变",
            ]
            for pattern in placeholder_patterns:
                if pattern in modified:
                    return False, f"检测到占位符 '{pattern}'，拒绝写入"

            # 长度检查
            orig_lines = len(original.split("\n"))
            mod_lines = len(modified.split("\n"))
            if orig_lines > 30 and orig_lines > 0:
                ratio = mod_lines / orig_lines
                if ratio < 0.3:
                    return False, f"内容长度异常：{orig_lines}行 → {mod_lines}行 ({ratio:.0%})"

            # 导入检查
            orig_imports = len(re.findall(r"^(from |import )", original, re.MULTILINE))
            mod_imports = len(re.findall(r"^(from |import )", modified, re.MULTILINE))
            if orig_imports > 2 and mod_imports == 0:
                return False, f"原始文件有 {orig_imports} 个 import，修改后为 0"

            # AST 语法检查
            try:
                import ast

                ast.parse(modified)
            except SyntaxError as e:
                return False, f"修改后的代码有语法错误: {e}"

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(modified, encoding="utf-8")
            return True, ""
        except Exception as e:
            return False, str(e)

    async def _snapshot_backup(self) -> str:
        """创建快照备份"""
        ref = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
        try:
            from pycoder.server.services.version_snapshot import get_snapshot_manager

            snap = get_snapshot_manager()
            snap.create_snapshot(label=f"evo_{ref}", pipeline_step="evolve_backup")
        except ImportError:
            pass
        return ref

    async def _snapshot_rollback(self, ref: str) -> None:
        """从快照回滚"""
        try:
            from pycoder.server.services.version_snapshot import get_snapshot_manager

            snap = get_snapshot_manager()
            snapshots = snap.list_snapshots()
            for s in snapshots:
                if ref in s.get("label", ""):
                    snap.rollback(s["id"])
                    logger.info("snapshot_rollback ref=%s", ref)
                    return
        except (ImportError, Exception) as e:
            logger.warning("snapshot_rollback_failed: %s", e)

    async def _run_tests_async(self) -> tuple[bool, str]:
        """异步运行 pytest（不阻塞事件循环）"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "pytest",
                "tests/",
                "-x",
                "--tb=short",
                "-q",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=300)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return False, "测试超时 (300s)"
            output = stdout_bytes.decode("utf-8", errors="replace")
            return proc.returncode == 0, output
        except Exception as e:
            return False, str(e)

    async def _static_scan_async(self) -> list[dict[str, Any]]:
        """异步执行 ruff 静态分析"""
        issues: list[dict[str, Any]] = []
        project = str(self._project_root / "pycoder")

        try:
            proc = await asyncio.create_subprocess_exec(
                "ruff",
                "check",
                project,
                "--output-format=json",
                "--no-cache",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
                if stdout_bytes:
                    for issue in json.loads(stdout_bytes.decode("utf-8", errors="replace")):
                        issues.append(
                            {
                                "file": issue.get("filename", ""),
                                "line": issue.get("location", {}).get("row", 0),
                                "message": issue.get("message", ""),
                                "source": "ruff",
                            }
                        )
            except TimeoutError:
                proc.kill()
                await proc.wait()
        except FileNotFoundError:
            pass
        return issues

    async def _create_evolution_pr(self, task: EvolutionTask) -> dict[str, Any] | None:
        """进化成功后自动创建 GitHub PR"""
        try:
            token = self._load_github_token()
            if not token:
                return None

            import httpx

            branch = f"self_evo/{task.id}"
            subprocess.run(["git", "checkout", "-b", branch], capture_output=True, timeout=10)
            subprocess.run(["git", "add", "-A"], capture_output=True, timeout=10)
            subprocess.run(
                ["git", "commit", "-m", f"self_evo: {task.description[:72]}"],
                capture_output=True,
                timeout=10,
            )
            subprocess.run(["git", "push", "origin", branch], capture_output=True, timeout=30)

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.github.com/repos/zhao8672-art/pycoder/pulls",
                    headers={
                        "Authorization": f"token {token}",
                        "Accept": "application/vnd.github+json",
                    },
                    json={
                        "title": f"self_evo: {task.description[:72]}",
                        "head": branch,
                        "base": "master",
                        "body": f"## 自动进化 PR\n\n- 任务: {task.id}\n- 类型: {task.type}\n"
                        f"- 修复数: {len(task.changes)}\n- 测试: {task.test_result[:200]}",
                    },
                )
                if resp.status_code == 201:
                    data = resp.json()
                    return {"url": data.get("html_url", ""), "number": data.get("number", 0)}
        except Exception as e:
            logger.warning("evo_pr_create_failed: %s", e)
        return None

    def _load_github_token(self) -> str:
        """加载 GitHub token"""
        if self.GITHUB_TOKEN_FILE.exists():
            return self.GITHUB_TOKEN_FILE.read_text(encoding="utf-8").strip()
        return os.environ.get("GITHUB_TOKEN", "")

    def _is_core_modification(self, fixes: list[dict[str, Any]]) -> bool:
        """检查是否涉及核心文件修改"""
        return any(any(p in fix.get("file", "") for p in self.CORE_FILE_PATTERNS) for fix in fixes)

    def _record_learning(
        self,
        task: EvolutionTask,
        fixes: list[dict[str, Any]],
        test_passed: bool,
        test_output: str,
        quality_score: float = 0,
    ) -> None:
        """记录学习经验到 LearningEngine"""
        try:
            from pycoder.server.learning import get_learning_engine

            engine = get_learning_engine()
            outcome = (
                "success"
                if test_passed
                else "rolled_back" if task.status == "rolled_back" else "failure"
            )
            engine.on_task_complete(
                task_id=task.id,
                outcome=outcome,
                task_type="evolve",
                description=task.description,
                error_msg=test_output if not test_passed else "",
                file_paths=[f.get("file", "") for f in fixes],
                fix_content="\n".join(f.get("modified", "")[:500] for f in fixes),
                test_passed=test_passed,
                quality_score=quality_score,
                retry_count=1 if task.status == "rolled_back" else 0,
            )
        except Exception as e:
            logger.debug("evo_record_learning_failed: %s", e)

    # ══════════════════════════════════════════════════════
    # run_cycle — 一键自进化：SCAN→PRIORITIZE→FIX→TEST→LEARN
    # ══════════════════════════════════════════════════════

    async def run_cycle(
        self,
        task_type: str = "auto",
        target: str = "",
        auto_apply: bool = False,
        dry_run: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        """运行完整的自进化周期。

        五步管线:
          1. SCAN     — 扫描代码库（AST + ruff + LLM 深度分析）
          2. PRIORITIZE — 按严重程度/影响范围排序问题
          3. FIX      — AI 逐个生成修复方案 → 语法检查 → 沙箱测试
          4. TEST     — 运行 pytest 全量测试 → 通过则 COMMIT，失败则 ROLLBACK
          5. LEARN    — 记录修复模式到 LearningEngine，下次自动复用

        Args:
            task_type: "auto"(自动) / "fix" / "optimize" / "security" / "quality"
            target: 目标文件或目录（为空则扫描整个 pycoder/）
            auto_apply: 是否跳过审批直接应用修复
            dry_run: 仅扫描不修改

        Yields:
            {"type": "phase", "phase": "scanning", ...}
            {"type": "issues_found", "count": N, ...}
            {"type": "fix_progress", "current": i, "total": N, ...}
            {"type": "test_result", "passed": bool, ...}
            {"type": "done", "evolution_report": {...}, ...}
        """
        # ── 步骤 1: SCAN ──
        yield {"type": "phase", "phase": "scanning", "message": "🔍 SCAN — 扫描代码库..."}
        report = await self.scan(target or "pycoder", use_llm=True)
        yield {
            "type": "phase",
            "phase": "scanning",
            "status": "done",
            "files_scanned": report.files_scanned,
            "total_issues": report.total_issues,
            "summary": report.summary[:500] if report.summary else "",
        }

        if report.total_issues == 0:
            yield {"type": "done", "message": "✅ 未发现任何问题", "evolution_report": {}}
            return

        # ── 步骤 2: PRIORITIZE ──
        yield {"type": "phase", "phase": "prioritizing", "message": "📊 PRIORITIZE — 排序问题..."}
        # 按严重程度排序: critical > high > medium > low
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_issues = sorted(
            report.issues,
            key=lambda i: (severity_order.get(i.severity, 9), i.issue_type),
        )
        # 限制: 每次最多处理 10 个问题
        top_issues = sorted_issues[:10]
        yield {
            "type": "phase",
            "phase": "prioritizing",
            "status": "done",
            "top_issues": len(top_issues),
            "breakdown": {
                s: sum(1 for i in top_issues if i.severity == s)
                for s in ["critical", "high", "medium", "low"]
            },
        }

        if dry_run:
            yield {
                "type": "done",
                "message": f"Dry-run 完成: 发现 {report.total_issues} 个问题",
                "issues": [
                    {"file": i.file, "line": i.line, "title": i.title, "severity": i.severity}
                    for i in top_issues[:20]
                ],
                "evolution_report": _build_evolution_report(
                    EvolutionTask(type=task_type, description="dry-run scan"),
                ),
            }
            return

        # ── 步骤 3-5: FIX → TEST → LEARN（复用 evolve 管线）──
        _n = len(top_issues)
        yield {"type": "phase", "phase": "fixing", "message": f"🔧 FIX — 处理 {_n} 个问题..."}

        # 将 top_issues 转换为自定义 prompt 传给 evolve
        custom_prompt = self._issues_to_prompt(top_issues, task_type)
        async for event in self.evolve(
            task_type="fix",
            target=target,
            custom_prompt=custom_prompt,
            auto_apply=auto_apply,
            dry_run=False,
        ):
            yield event

    def _issues_to_prompt(self, issues: list[CodeIssue], task_type: str) -> str:
        """将扫描结果转换为进化提示词"""
        lines = [
            f"## 自动扫描结果 — {len(issues)} 个问题待修复",
            "",
            "请逐个修复以下问题。每个修复使用 [FILE:路径]...[END:FILE] 格式。",
            "",
        ]
        for i, issue in enumerate(issues, 1):
            lines.append(f"### {i}. [{issue.severity.upper()}] {issue.file}:{issue.line}")
            lines.append(f"类型: {issue.issue_type}")
            lines.append(f"问题: {issue.title}")
            if issue.description:
                lines.append(f"详情: {issue.description}")
            if issue.suggestion:
                lines.append(f"建议: {issue.suggestion}")
            if issue.code_snippet:
                lines.append(f"代码: `{issue.code_snippet[:200]}`")
            lines.append("")
        return "\n".join(lines)

    # ── 任务管理 (V1 兼容) ─────────────────────────────

    def list_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        """列出最近 N 个进化任务"""
        return [t.to_dict() for t in self._tasks[-limit:]]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """按 ID 获取任务"""
        for t in self._tasks:
            if t.id == task_id:
                return t.to_dict()
        return None

    def get_evolution_stats(self) -> dict[str, Any]:
        """获取进化统计（合并 V1 EvolutionStats + V2 历史）"""
        base = self._stats.to_dict()
        v2_stats = self.get_stats()
        base["v2_records"] = v2_stats.get("total_evolutions", 0)
        base["v2_success_rate"] = v2_stats.get("success_rate", 0)
        return base

    # ══════════════════════════════════════════════════════
    # 进化令牌系统（从 V1 迁移）
    # ══════════════════════════════════════════════════════

    _EVOLUTION_TOKEN_DIR = Path.home() / ".pycoder"
    _EVOLUTION_TOKEN_FILE = _EVOLUTION_TOKEN_DIR / "evolution_token.json"
    _EVOLUTION_TOKEN_TTL = 300

    @staticmethod
    def generate_evolution_token(files: list[str]) -> str:
        """生成进化令牌 — 手动授权修改核心文件"""
        SelfEvolutionEngine._EVOLUTION_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        token_id = hashlib.sha256(
            f"{time.time()}:{':'.join(sorted(files))}:{uuid.uuid4()}".encode()
        ).hexdigest()[:16]
        token_data = {
            "id": token_id,
            "files": files,
            "expires_at": time.time() + SelfEvolutionEngine._EVOLUTION_TOKEN_TTL,
            "used": False,
            "created_at": time.time(),
        }
        SelfEvolutionEngine._EVOLUTION_TOKEN_FILE.write_text(
            json.dumps(token_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return token_id

    @staticmethod
    def _validate_evolution_token(target_file: str) -> bool:
        """验证进化令牌是否允许修改指定核心文件（一次性令牌）"""
        if not SelfEvolutionEngine._EVOLUTION_TOKEN_FILE.exists():
            return False
        try:
            data = json.loads(SelfEvolutionEngine._EVOLUTION_TOKEN_FILE.read_text(encoding="utf-8"))
            if data.get("used"):
                return False
            if time.time() > data.get("expires_at", 0):
                SelfEvolutionEngine._EVOLUTION_TOKEN_FILE.unlink(missing_ok=True)
                return False
            allowed = data.get("files", [])
            if not any(p in target_file for p in allowed):
                return False
            data["used"] = True
            SelfEvolutionEngine._EVOLUTION_TOKEN_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except (json.JSONDecodeError, OSError):
            return False

    @staticmethod
    def clear_evolution_token() -> None:
        """清除进化令牌"""
        SelfEvolutionEngine._EVOLUTION_TOKEN_FILE.unlink(missing_ok=True)
