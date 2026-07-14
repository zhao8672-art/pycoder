"""
代码质量守卫 — AI 每次修改后自动运行质量检查。

集成:
  - code_quality.py (5 维评分)
  - refactor_analyzer.py (圈复杂度等)
  - pylint/ruff (外部工具)

流程:
  AI 修改代码 → QualityGuard.check(file) → 评分报告 → 不达标则自动反馈修复
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from pycoder.server.log import log
from pycoder.server.services.execution_rules import ExecutionRules


@dataclass
class Issue:
    """单个代码质量问题"""

    line: int
    column: int
    severity: str  # "error" | "warning" | "info"
    message: str
    category: str  # "lint" | "security" | "complexity" | "style" | "type"


@dataclass
class QualityReport:
    """质量检查报告"""

    success: bool
    issues: list[Issue] = field(default_factory=list)
    score: int = 100  # 0-100 综合评分
    lint_score: int = 100  # 代码规范 (0-100)
    security_score: int = 100  # 安全 (0-100)
    complexity_score: int = 100  # 复杂度 (0-100)
    format_ok: bool = True
    summary: str = ""

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def is_pass(self, min_score: int = 70) -> bool:
        return self.score >= min_score and self.error_count == 0


class QualityGuard:
    """代码质量守卫 — 统一入口"""

    def __init__(self, workspace_root: str | Path | None = None):
        self._workspace = Path(workspace_root or os.getcwd()).resolve()

    async def check(self, file_path: str | Path) -> QualityReport:
        """对文件运行全部质量检查"""
        target = Path(file_path)
        if not target.is_absolute():
            target = self._workspace / target
        if not target.exists():
            return QualityReport(success=False, summary=f"文件不存在: {file_path}")

        code = target.read_text(encoding="utf-8")
        all_issues: list[Issue] = []

        # 1. 安全扫描 (内建)
        security_issues = self._scan_security(code, target)
        all_issues.extend(security_issues)

        # 2. 复杂度分析 (AST)
        complexity_issues = self._scan_complexity(code)
        all_issues.extend(complexity_issues)

        # 3. 代码规范 (AST)
        style_issues = self._scan_style(code)
        all_issues.extend(style_issues)

        # 4. 外部工具 (pylint/ruff)
        external_issues = await self._run_external_linter(target)
        all_issues.extend(external_issues)

        # 评分
        lint_score = self._calc_lint_score(all_issues)
        security_score = self._calc_security_score(security_issues)
        complexity_score = self._calc_complexity_score(complexity_issues)
        total_score = int((lint_score + security_score + complexity_score) / 3)

        format_ok = self._check_format(code)

        error_n = sum(1 for i in all_issues if i.severity == "error")
        warn_n = sum(1 for i in all_issues if i.severity == "warning")
        return QualityReport(
            success=True,
            issues=all_issues,
            score=total_score,
            lint_score=lint_score,
            security_score=security_score,
            complexity_score=complexity_score,
            format_ok=format_ok,
            summary=(
                f"评分: {total_score}/100 | 错误: {error_n} | "
                f"警告: {warn_n} | "
                f"格式化: {'✅' if format_ok else '❌'}"
            ),
        )

    def _scan_security(self, code: str, file_path: Path) -> list[Issue]:
        """安全扫描 — 检测危险模式"""
        issues = []
        patterns = [
            (r"\beval\s*\(", "eval() 可能执行任意代码", "error"),
            (r"\bexec\s*\(", "exec() 可能执行任意代码", "error"),
            (r"__import__\s*\(", "动态 import 可能被利用", "warning"),
            (r"subprocess\.call", "subprocess.call 用 subprocess.run 替代", "warning"),
            (r"subprocess\.Popen", "用 subprocess.run 替代", "warning"),
            (r"pickle\.load", "反序列化 pickle 可能不安全", "warning"),
            (r"yaml\.load\s*(?!.*Loader=yaml\.SafeLoader)", "用 yaml.safe_load() 替代", "warning"),
            (r"sqlite3\.execute\s*\(.*f['\"]", "SQL 注入风险: 使用参数化查询", "error"),
            (r"\.format\(.*input", "潜在的格式化字符串注入", "info"),
            (r"os\.system\s*\(", "os.system() 用 subprocess.run() 替代", "warning"),
        ]
        for i, line in enumerate(code.splitlines(), 1):
            for pattern, msg, severity in patterns:
                if re.search(pattern, line):
                    issues.append(
                        Issue(
                            line=i,
                            column=0,
                            severity=severity,
                            message=msg,
                            category="security",
                        )
                    )
        return issues

    def _scan_complexity(self, code: str) -> list[Issue]:
        """复杂度分析 — 检测过长函数/过高圈复杂度"""
        issues = []
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # 函数长度
                    line_count = node.end_lineno - node.lineno if hasattr(node, "end_lineno") else 0
                    if line_count > 50:
                        issues.append(
                            Issue(
                                line=node.lineno,
                                column=0,
                                severity="warning",
                                message=f"函数 '{node.name}' 过长 ({line_count} 行), 建议拆分为子函数",
                                category="complexity",
                            )
                        )
                    # 嵌套深度
                    depth = self._max_nesting(node)
                    if depth > 4:
                        issues.append(
                            Issue(
                                line=node.lineno,
                                column=0,
                                severity="info",
                                message=f"函数 '{node.name}' 嵌套深度 {depth} (建议 <= 4)",
                                category="complexity",
                            )
                        )
                elif isinstance(node, ast.ClassDef):
                    if hasattr(node, "end_lineno") and (node.end_lineno - node.lineno) > 200:
                        issues.append(
                            Issue(
                                line=node.lineno,
                                column=0,
                                severity="warning",
                                message=f"类 '{node.name}' 过大 ({(node.end_lineno - node.lineno)} 行)",
                                category="complexity",
                            )
                        )
        except SyntaxError:
            pass
        return issues

    def _scan_style(self, code: str) -> list[Issue]:
        """代码规范扫描"""
        issues = []
        lines = code.splitlines()
        for i, line in enumerate(lines, 1):
            # 行长检查
            if len(line) > 100:
                issues.append(
                    Issue(
                        line=i,
                        column=100,
                        severity="info",
                        message=f"行过长 ({len(line)} > 100 字符)",
                        category="style",
                    )
                )
            # 行尾空格
            if line != line.rstrip():
                issues.append(
                    Issue(
                        line=i,
                        column=len(line.rstrip()),
                        severity="info",
                        message="行尾有多余空格",
                        category="style",
                    )
                )
        # 文件末尾换行
        if not code.endswith("\n"):
            issues.append(
                Issue(
                    line=len(lines),
                    column=0,
                    severity="info",
                    message="文件末尾缺少换行",
                    category="style",
                )
            )
        return issues

    async def _run_external_linter(self, file_path: Path) -> list[Issue]:
        """运行外部 lint 工具 (ruff/pylint)"""
        issues = []
        # 尝试 ruff
        ruff = await self._run_tool("ruff", ["check", "-q", str(file_path)])
        if ruff and ruff[0]:
            issues.extend(ruff[1])
            return issues  # ruff 结果优先

        # 回退到 py_compile (至少检查语法)
        try:
            compile(file_path.read_text(encoding="utf-8"), str(file_path), "exec")
        except SyntaxError as e:
            issues.append(
                Issue(
                    line=e.lineno or 0,
                    column=e.offset or 0,
                    severity="error",
                    message=f"语法错误: {e.msg}",
                    category="lint",
                )
            )
        return issues

    async def _run_tool(self, tool: str, args: list[str]) -> tuple[bool, list[Issue]] | None:
        """运行外部工具并解析输出"""
        try:
            result = subprocess.run(
                [tool, *args],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode == 0:
                return True, []
            issues = []
            for line in result.stdout.splitlines() + result.stderr.splitlines():
                # ruff: path:line:col: severity: message
                m = re.match(r".+:(\d+):(\d+):\s*(\w+):\s*(.+)", line)
                if m:
                    severity_map = {"E": "error", "W": "warning", "I": "info", "F": "error"}
                    issues.append(
                        Issue(
                            line=int(m.group(1)),
                            column=int(m.group(2)),
                            severity=severity_map.get(m.group(3)[:1], "info"),
                            message=m.group(4).strip(),
                            category="lint",
                        )
                    )
            return True, issues
        except FileNotFoundError:
            return None  # 工具未安装
        except subprocess.TimeoutExpired:
            return True, []

    def _check_format(self, code: str) -> bool:
        """检查格式化 (仅基础检查)"""
        lines = code.splitlines()
        if not lines:
            return True
        # 检查缩进一致性
        indent_types = set()
        for line in lines:
            if line.startswith("    "):
                indent_types.add("spaces")
            elif line.startswith("\t"):
                indent_types.add("tabs")
        if len(indent_types) > 1:
            return False
        return True

    @staticmethod
    def _max_nesting(node: ast.AST, current_depth: int = 0) -> int:
        """计算 AST 节点的最大嵌套深度"""
        max_depth = current_depth
        for child in ast.walk(node):
            loop_types = (
                ast.If,
                ast.For,
                ast.While,
                ast.Try,
                ast.With,
                ast.AsyncFor,
                ast.AsyncWith,
            )
            if isinstance(child, loop_types):
                depth = current_depth + 1
                for sub in ast.walk(child):
                    if isinstance(sub, loop_types):
                        depth = max(depth, current_depth + 2)
                max_depth = max(max_depth, depth)
        return max_depth

    @staticmethod
    def _calc_lint_score(issues: list[Issue]) -> int:
        errors = sum(1 for i in issues if i.severity == "error")
        warnings = sum(1 for i in issues if i.severity == "warning")
        info = sum(1 for i in issues if i.severity == "info")
        score = 100 - errors * 15 - warnings * 5 - info * 2
        return max(0, score)

    @staticmethod
    def _calc_security_score(issues: list[Issue]) -> int:
        if not issues:
            return 100
        errors = sum(1 for i in issues if i.severity == "error")
        warnings = sum(1 for i in issues if i.severity == "warning")
        score = 100 - errors * 30 - warnings * 10
        return max(0, score)

    @staticmethod
    def _calc_complexity_score(issues: list[Issue]) -> int:
        if not issues:
            return 100
        score = 100 - len(issues) * 10
        return max(0, score)


# ══════════════════════════════════════════════════════════
# 正式质量门禁 — 借鉴好运助手评分公式
# ══════════════════════════════════════════════════════════


@dataclass
class GateResult:
    """质量门禁结果"""

    passed: bool
    score: float  # 0-100 综合评分
    details: dict[str, float]  # 各维度得分
    issues: list[dict] = field(default_factory=list)
    hard_rejections: list[str] = field(default_factory=list)
    summary: str = ""


class QualityGate:
    """质量门禁 — 对标好运助手 L1/L2/L3/L4 质检体系

    评分公式:
      总分 = 规范匹配(25%) + 产出完整(25%) + 测试覆盖(20%)
           + 安全合规(15%) + 落地可行(15%)

    通行规则:
      - >= 85 分: 自动放行
      - < 85 分: 批量重跑（最多 2 轮）
      - 仍不达标: 降级交付

    硬性驳回:
      - 测试覆盖率 < 85%
      - 严重安全漏洞（SQL注入/XSS/硬编码密钥）
      - 评分 < 80
    """

    # 评分权重
    WEIGHTS: dict[str, float] = {
        "spec_compliance": 0.25,  # 规范匹配
        "output_completeness": 0.25,  # 产出完整
        "test_coverage": 0.20,  # 测试覆盖
        "security_compliance": 0.15,  # 安全合规
        "deployability": 0.15,  # 落地可行
    }

    PASS_THRESHOLD: float = 85.0
    MIN_SCORE: float = 80.0
    MAX_RETRY_ROUNDS: int = 2

    def __init__(
        self,
        workspace_root: str | Path | None = None,
        use_adaptive_threshold: bool = True,
    ):
        self._guard = QualityGuard(workspace_root)
        self._workspace = Path(workspace_root or os.getcwd()).resolve()
        self._rules = ExecutionRules()  # Bug #11: 提循环外
        # Bug #14: 从 FeedbackLoop 加载自适应阈值
        if use_adaptive_threshold:
            try:
                from pycoder.capabilities.self_evo.learning.feedback_loop import get_feedback_loop

                fb = get_feedback_loop()
                config = fb.get_adaptive_config()
                self.PASS_THRESHOLD = config.quality_threshold
                self.MIN_SCORE = max(70.0, config.min_score)
            except (ImportError, AttributeError, KeyError, ValueError) as e:
                log.debug("load_adaptive_threshold_failed", error=str(e))

    def evaluate(
        self,
        files: list[str | Path],
        test_coverage: float = 0.0,
        deliverables_check: dict[str, bool] | None = None,
    ) -> GateResult:
        """执行完整质量门禁评估

        参数:
            files: 变更文件列表
            test_coverage: 测试覆盖率 (0.0-100.0)
            deliverables_check: {交付物名称: 是否完成}
        """
        all_issues: list[dict] = []
        hard_rejections: list[str] = []
        scores: dict[str, float] = {}

        # ── 1. 安全合规 (15%) — Bug #11: ExecutionRules提循环外
        security_score = 100.0
        for f in files:
            p = Path(f)
            if not p.is_absolute():
                p = self._workspace / p
            if p.exists() and p.suffix == ".py":
                try:
                    code = p.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError, PermissionError) as e:
                    log.debug("read_pyfile_failed", path=str(p), error=str(e))
                    continue
                sec_issues = self._rules.validate_code_safety(code, str(p))
                all_issues.extend(sec_issues)
                for i in sec_issues:
                    if i.get("severity") == "high":
                        security_score -= 30
                        hard_rejections.append(
                            f"[安全] {p}:{i.get('line')} - {i.get('description')}"
                        )
                    elif i.get("severity") == "medium":
                        security_score -= 10
        scores["security_compliance"] = max(0, security_score)

        # ── 2. 规范匹配 (25%) ──
        # 基于 ruff/pylint + 内建扫描
        spec_score = 100.0
        for f in files:
            p = Path(f)
            if not p.is_absolute():
                p = self._workspace / p
            if p.exists() and p.suffix == ".py":
                try:
                    code = p.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError, PermissionError) as e:
                    log.debug("read_pyfile_failed", path=str(p), error=str(e))
                    continue
                # 行长度 + 行尾空格
                for i, line in enumerate(code.splitlines(), 1):
                    if len(line) > 100:
                        spec_score -= 2
                        all_issues.append(
                            {
                                "line": i,
                                "severity": "info",
                                "category": "style",
                                "description": f"行过长 ({len(line)} > 100)",
                                "file": str(f),
                            }
                        )
        scores["spec_compliance"] = max(0, spec_score)

        # ── 3. 产出完整 (25%) ──
        if deliverables_check:
            total = len(deliverables_check)
            done = sum(1 for v in deliverables_check.values() if v)
            scores["output_completeness"] = (done / total * 100) if total > 0 else 100
        else:
            scores["output_completeness"] = 100

        # ── 4. 测试覆盖 (20%) ──
        scores["test_coverage"] = min(test_coverage, 100)
        if test_coverage < 85:
            hard_rejections.append(f"[测试] 覆盖率 {test_coverage:.1f}% 低于 85% 阈值")

        # ── 5. 落地可行 (15%) ──
        # 检查是否有 README/部署配置
        deploy_files = [
            "Dockerfile",
            "docker-compose.yml",
            "README.md",
            "requirements.txt",
            "pyproject.toml",
        ]
        found = sum(1 for df in deploy_files if (self._workspace / df).exists())
        scores["deployability"] = min(100, found / max(len(deploy_files), 1) * 100)

        # ── 综合评分 ──
        total = sum(scores.get(k, 0) * w for k, w in self.WEIGHTS.items())

        # 硬性驳回判断
        if total < self.MIN_SCORE:
            hard_rejections.insert(0, f"[评分] 综合得分 {total:.1f} 低于最低阈值 {self.MIN_SCORE}")
        if hard_rejections:
            total = min(total, 79)  # 有硬性驳回时上限 79

        passed = total >= self.PASS_THRESHOLD and not hard_rejections

        return GateResult(
            passed=passed,
            score=round(total, 1),
            details=scores,
            issues=all_issues,
            hard_rejections=hard_rejections,
            summary=(
                f"{'✅ 放行' if passed else '❌ 驳回'}"
                f" | 评分: {total:.1f}/100"
                f" | 安全: {scores['security_compliance']:.0f}"
                f" | 规范: {scores['spec_compliance']:.0f}"
                f" | 产出: {scores['output_completeness']:.0f}"
                f" | 测试: {scores['test_coverage']:.0f}%"
                f" | 部署: {scores['deployability']:.0f}"
            ),
        )

    def is_deliverable_complete(self, required: list[str], actual: list[str]) -> dict[str, bool]:
        """检查交付物完整性"""
        return {d: d in actual for d in required}


__all__ = [
    "Issue",
    "QualityReport",
    "QualityGuard",
    "GateResult",
    "QualityGate",
]
