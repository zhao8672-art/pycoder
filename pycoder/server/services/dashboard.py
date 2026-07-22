"""P1-3: 项目仪表盘 — 聚合项目全景数据

为前端提供单端点获取项目综合仪表盘:
- 项目基本信息 (文件数/代码行数/最近修改)
- 依赖概览 (总数/已安装/漏洞)
- 后台任务状态 (活跃/总数/最近执行)
- 引用图统计 (符号数/引用数/Top 入口)
- 健康度评分 (综合 0-100)
- 最近活动 (会话/文件变更)

设计:
- 单文件聚合,避免前端多次请求
- 所有数据源懒加载,失败降级为 None 不影响整体响应
- 提供 /api/dashboard/full 单端点,前端可一次拉取
"""
from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProjectInfo:
    """项目基本信息"""

    name: str = ""
    root: str = ""
    file_count: int = 0
    python_count: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    last_modified: float = 0.0
    git_branch: str = ""
    git_status: str = ""


@dataclass
class DependencyOverview:
    """依赖概览"""

    total: int = 0
    installed: int = 0
    outdated: int = 0
    missing: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    frameworks: list[str] = field(default_factory=list)
    key_packages: list[str] = field(default_factory=list)
    vulnerabilities: dict[str, int] = field(default_factory=dict)  # severity -> count


@dataclass
class TaskOverview:
    """任务调度概览"""

    total: int = 0
    enabled: int = 0
    by_trigger: dict[str, int] = field(default_factory=dict)
    last_executions: list[dict] = field(default_factory=list)
    recent_errors: int = 0


@dataclass
class GraphOverview:
    """引用图概览"""

    total_symbols: int = 0
    total_references: int = 0
    files: int = 0
    top_called: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class HealthScore:
    """健康度评分"""

    overall: int = 100  # 0-100
    grade: str = "A"  # A/B/C/D/F
    factors: list[dict] = field(default_factory=list)


@dataclass
class DashboardSnapshot:
    """仪表盘完整快照"""

    generated_at: float
    project: ProjectInfo
    dependencies: DependencyOverview
    tasks: TaskOverview
    graph: GraphOverview
    health: HealthScore
    runtime: dict[str, Any] = field(default_factory=dict)
    recent_files: list[dict] = field(default_factory=list)


class DashboardBuilder:
    """仪表盘构建器 — 聚合多源数据"""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path.cwd()

    def build(self, *, include_graph: bool = True) -> DashboardSnapshot:
        """构建完整仪表盘快照"""
        project = self._collect_project_info()
        deps = self._collect_dependencies()
        tasks = self._collect_tasks()
        graph = self._collect_graph() if include_graph else GraphOverview()
        health = self._compute_health(project, deps, tasks)
        runtime = self._collect_runtime()
        recent = self._collect_recent_files()

        return DashboardSnapshot(
            generated_at=time.time(),
            project=project,
            dependencies=deps,
            tasks=tasks,
            graph=graph,
            health=health,
            runtime=runtime,
            recent_files=recent,
        )

    # ── 数据采集 ─────────────────────────────────────

    def _collect_project_info(self) -> ProjectInfo:
        info = ProjectInfo()
        info.name = self.project_root.name
        info.root = str(self.project_root)

        # 排除目录
        exclude = {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            "node_modules",
            "dist",
            "build",
            ".pytest_cache",
            ".mypy_cache",
        }

        py_files: list[Path] = []
        all_files = 0
        for root, dirs, files in os.walk(self.project_root):
            # 过滤目录
            dirs[:] = [d for d in dirs if d not in exclude]
            for f in files:
                all_files += 1
                p = Path(root) / f
                if p.suffix == ".py":
                    py_files.append(p)
                # 跟踪最近修改
                try:
                    mtime = p.stat().st_mtime
                    if mtime > info.last_modified:
                        info.last_modified = mtime
                except OSError:
                    pass

        info.file_count = all_files
        info.python_count = len(py_files)

        # 代码行数统计（采样前 200 个 .py 文件以加速）
        total_code = 0
        total_comment = 0
        total_blank = 0
        for p in py_files[:200]:
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                for line in content.split("\n"):
                    s = line.strip()
                    if not s:
                        total_blank += 1
                    elif s.startswith("#"):
                        total_comment += 1
                    else:
                        total_code += 1
            except OSError:
                pass

        # 估算剩余文件 (如果还有)
        if len(py_files) > 200:
            scale = len(py_files) / 200
            total_code = int(total_code * scale)
            total_comment = int(total_comment * scale)
            total_blank = int(total_blank * scale)

        info.code_lines = total_code
        info.comment_lines = total_comment
        info.blank_lines = total_blank

        # Git 信息
        info.git_branch = self._git_branch()
        info.git_status = self._git_status_summary()

        return info

    def _git_branch(self) -> str:
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0:
                return r.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
        return ""

    def _git_status_summary(self) -> str:
        try:
            r = subprocess.run(
                ["git", "status", "--short"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0:
                lines = [l for l in r.stdout.split("\n") if l.strip()]
                return f"{len(lines)} 个变更"
        except (OSError, subprocess.TimeoutExpired):
            pass
        return ""

    def _collect_dependencies(self) -> DependencyOverview:
        overview = DependencyOverview()
        try:
            from pycoder.python.dep_analyzer import DepAnalyzer

            analyzer = DepAnalyzer(project_root=self.project_root)
            result = analyzer.analyze()
            overview.total = result.total_deps
            overview.installed = sum(1 for d in result.production_deps if d.installed)
            overview.missing = overview.total - overview.installed
            overview.frameworks = result.frameworks
            overview.key_packages = result.key_packages
            overview.by_type = {
                "production": len(result.production_deps),
                "dev": len(result.dev_deps),
            }
        except Exception as e:
            logger.debug("dashboard_deps_collect_failed error=%s", e)

        # 漏洞统计
        try:
            from pycoder.python.security_scanner import DependencySecurityScanner

            scanner = DependencySecurityScanner(project_root=self.project_root)
            scan = scanner.scan()
            overview.vulnerabilities = scan.by_severity
        except Exception as e:
            logger.debug("dashboard_security_collect_failed error=%s", e)

        return overview

    def _collect_tasks(self) -> TaskOverview:
        overview = TaskOverview()
        try:
            from pycoder.server.scheduler import get_scheduler

            sched = get_scheduler()
            tasks = sched.list_tasks()
            overview.total = len(tasks)
            overview.enabled = sum(1 for t in tasks if t.get("enabled"))
            for t in tasks:
                trig = t.get("trigger", "unknown")
                overview.by_trigger[trig] = overview.by_trigger.get(trig, 0) + 1
            # 最近执行
            sorted_tasks = sorted(tasks, key=lambda x: x.get("last_run", 0), reverse=True)
            for t in sorted_tasks[:5]:
                if t.get("last_run", 0) > 0:
                    overview.last_executions.append(
                        {
                            "id": t.get("id"),
                            "name": t.get("name"),
                            "last_run": t.get("last_run"),
                            "last_result": (t.get("last_result") or "")[:100],
                            "last_error": (t.get("last_error") or "")[:100],
                        }
                    )
            overview.recent_errors = sum(1 for t in tasks if t.get("last_error"))
        except Exception as e:
            logger.debug("dashboard_tasks_collect_failed error=%s", e)
        return overview

    def _collect_graph(self) -> GraphOverview:
        overview = GraphOverview()
        try:
            from pycoder.python.impact_analyzer import ImpactAnalyzer

            analyzer = ImpactAnalyzer(workspace=self.project_root)
            analyzer.build()
            stats = analyzer.stats()
            overview.total_symbols = stats["total_symbols"]
            overview.total_references = stats["total_references"]
            overview.files = stats["files"]
            # Top 被调用符号
            from collections import defaultdict

            call_count: dict[tuple[str, str], int] = defaultdict(int)
            for ref in analyzer._references:
                if ref.callee_qualname:
                    call_count[(ref.caller_file, ref.callee_qualname)] += 1
            top = sorted(call_count.items(), key=lambda x: -x[1])[:5]
            overview.top_called = [(q, c) for (_f, q), c in top]
        except Exception as e:
            logger.debug("dashboard_graph_collect_failed error=%s", e)
        return overview

    def _collect_runtime(self) -> dict[str, Any]:
        return {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "cwd": str(Path.cwd()),
            "pid": os.getpid(),
            "uptime_hint": "n/a",
        }

    def _collect_recent_files(self, limit: int = 5) -> list[dict]:
        """最近修改的 Python 文件"""
        py_files: list[tuple[float, Path]] = []
        for p in self.project_root.rglob("*.py"):
            if any(seg in p.parts for seg in [".venv", "venv", "__pycache__", ".git"]):
                continue
            try:
                py_files.append((p.stat().st_mtime, p))
            except OSError:
                pass
        py_files.sort(reverse=True)
        results = []
        for mtime, p in py_files[:limit]:
            try:
                rel = p.relative_to(self.project_root).as_posix()
                results.append(
                    {
                        "file": rel,
                        "modified": mtime,
                        "size": p.stat().st_size,
                    }
                )
            except (OSError, ValueError):
                pass
        return results

    def _compute_health(
        self,
        project: ProjectInfo,
        deps: DependencyOverview,
        tasks: TaskOverview,
    ) -> HealthScore:
        """计算健康度评分"""
        factors: list[dict] = []
        score = 100

        # 因素 1: Git 工作区干净
        if project.git_status and "0 个变更" not in project.git_status:
            factors.append(
                {
                    "name": "Git 工作区",
                    "status": "warn",
                    "detail": project.git_status,
                }
            )
            score -= 5
        else:
            factors.append({"name": "Git 工作区", "status": "ok", "detail": "干净"})

        # 因素 2: 依赖完整
        if deps.missing > 0:
            factors.append(
                {
                    "name": "依赖完整",
                    "status": "warn",
                    "detail": f"{deps.missing} 个依赖未安装",
                }
            )
            score -= min(15, deps.missing * 3)
        else:
            factors.append({"name": "依赖完整", "status": "ok", "detail": "全部安装"})

        # 因素 3: 漏洞
        critical = deps.vulnerabilities.get("CRITICAL", 0)
        high = deps.vulnerabilities.get("HIGH", 0)
        if critical > 0:
            factors.append(
                {
                    "name": "安全漏洞",
                    "status": "critical",
                    "detail": f"{critical} 个严重漏洞",
                }
            )
            score -= critical * 10
        elif high > 0:
            factors.append(
                {
                    "name": "安全漏洞",
                    "status": "warn",
                    "detail": f"{high} 个高危漏洞",
                }
            )
            score -= high * 3
        else:
            factors.append({"name": "安全漏洞", "status": "ok", "detail": "无已知漏洞"})

        # 因素 4: 任务执行错误
        if tasks.recent_errors > 0:
            factors.append(
                {
                    "name": "后台任务",
                    "status": "warn",
                    "detail": f"{tasks.recent_errors} 个任务最近出错",
                }
            )
            score -= min(10, tasks.recent_errors * 2)
        else:
            factors.append(
                {"name": "后台任务", "status": "ok", "detail": "运行正常"}
            )

        # 因素 5: 代码体量
        if project.code_lines < 100:
            factors.append(
                {"name": "代码体量", "status": "info", "detail": "项目较小"}
            )
        elif project.code_lines > 100000:
            factors.append(
                {"name": "代码体量", "status": "info", "detail": f"{project.code_lines} 行"}
            )
        else:
            factors.append(
                {"name": "代码体量", "status": "ok", "detail": f"{project.code_lines} 行"}
            )

        # 等级评定
        score = max(0, min(100, score))
        if score >= 90:
            grade = "A"
        elif score >= 80:
            grade = "B"
        elif score >= 70:
            grade = "C"
        elif score >= 60:
            grade = "D"
        else:
            grade = "F"

        return HealthScore(overall=score, grade=grade, factors=factors)


def dashboard_to_dict(snap: DashboardSnapshot) -> dict:
    """快照转字典（用于 JSON 序列化）"""
    return {
        "generated_at": snap.generated_at,
        "generated_at_human": time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(snap.generated_at)
        ),
        "project": asdict(snap.project),
        "dependencies": asdict(snap.dependencies),
        "tasks": asdict(snap.tasks),
        "graph": asdict(snap.graph),
        "health": asdict(snap.health),
        "runtime": snap.runtime,
        "recent_files": snap.recent_files,
    }
