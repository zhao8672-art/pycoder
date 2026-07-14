"""
PyCoder 自优化引擎 — AI 修复升级自身 + 使用记录驱动进化

整合三大能力:
  1. SelfHealer    — AI 扫描自身代码 → 生成修复 → 安全应用 → 测试验证
  2. UsageAnalyzer — 分析会话历史/用户行为 → 发现高频问题/优化点
  3. PromptOptimizer — 基于历史成功率自动调优 Agent 提示词/模型路由

自优化闭环:
  使用记录 → 模式提取 → 代码修复/提示词优化 → 效果验证 → 知识沉淀

用法:
  from .self_optimizer import SelfOptimizer

  opt = SelfOptimizer()
  report = opt.auto_heal()           # 自动修复自身代码
  usage = opt.analyze_usage()        # 分析使用模式
  opt.optimize_prompts(usage)        # 基于使用记录优化提示词
"""

from __future__ import annotations

import ast
import asyncio
import logging
import re
import shutil
import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


PYCODER_ROOT = Path(__file__).resolve().parents[2]

# ≥ 400 行：核心 Agent 提示词底线（来自执行铁律）
_MIN_CORE_PROMPT_LINES = 400
_MAX_FIX_FILES_PER_RUN = 3


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class HealFix:
    """单次自修复"""

    file: str
    reason: str  # 为什么修复
    severity: str  # critical / high / medium / low
    old_code: str = ""
    new_code: str = ""
    applied: bool = False
    test_passed: bool = False


@dataclass
class HealReport:
    """自修复报告"""

    task_id: str = ""
    files_scanned: int = 0
    issues_found: int = 0
    fixes_applied: int = 0
    fixes_successful: int = 0
    test_passed: bool = False
    backup_ref: str = ""
    fixes: list[HealFix] = field(default_factory=list)
    error: str = ""
    duration_ms: float = 0.0


@dataclass
class UsageReport:
    """使用分析报告"""

    total_sessions: int = 0
    total_messages: int = 0
    user_messages: int = 0
    ai_messages: int = 0
    top_topics: list[tuple[str, int]] = field(default_factory=list)
    top_error_types: list[tuple[str, int]] = field(default_factory=list)
    avg_response_ms: float = 0.0
    model_distribution: dict[str, int] = field(default_factory=dict)
    weekly_activity: list[dict] = field(default_factory=list)
    common_issues: list[str] = field(default_factory=list)
    optimization_hints: list[str] = field(default_factory=list)


@dataclass
class PromptOptimization:
    """提示词优化结果"""

    agent_id: str = ""
    original_lines: int = 0
    optimized_lines: int = 0
    changes: list[str] = field(default_factory=list)
    expected_improvement: str = ""


# ══════════════════════════════════════════════════════════
# SelfHealer — 代码自修复引擎
# ══════════════════════════════════════════════════════════


class SelfHealer:
    """AI 驱动的 PyCoder 自身修复升级引擎"""

    def __init__(self, project_root: Path | None = None):
        self._root = project_root or PYCODER_ROOT
        self._backup_dir = self._root / ".pycoder_backups"
        # 核心文件列表（仅供日志标识，实际拦截通过进化令牌）
        self._protect_list = [
            "self_evolution.py",
            "self_optimizer.py",
        ]

    async def auto_heal(
        self,
        target_dir: str = "pycoder/server",
        focus: str = "all",
        dry_run: bool = False,
        max_files: int = _MAX_FIX_FILES_PER_RUN,
    ) -> HealReport:
        """自动扫描并修复自身代码

        流程: 静态分析 → 动态分析 → AI 生成修复 → 安全应用 → 测试验证
        """
        report = HealReport(
            task_id=f"HEAL-{int(time.time())}",
        )
        t0 = time.time()

        try:
            # ── 阶段 1: 静态代码扫描 ──
            issues = self._static_scan(target_dir)
            report.issues_found = len(issues)
            report.files_scanned = len({i.file for i in issues})

            if not issues:
                report.duration_ms = (time.time() - t0) * 1000
                return report

            # ── 阶段 2: 动态模式匹配（知识库推荐） ──
            knowledge_fixes = self._match_knowledge(issues)
            if knowledge_fixes:
                report.fixes = knowledge_fixes
                if not dry_run:
                    for fix in report.fixes:
                        success = self._apply_fix_safe(fix)
                        fix.applied = success
                        if success:
                            report.fixes_applied += 1

            # ── 阶段 3: AI 深度修复（复杂问题） ──
            complex_issues = [
                i
                for i in issues
                if i.severity in ("critical", "high")
                and not any(f.file == i.file for f in (knowledge_fixes or []))
            ]
            if complex_issues and not dry_run:
                ai_fixes = await self._ai_heal(complex_issues[:max_files])
                for fix in ai_fixes:
                    success = self._apply_fix_safe(fix)
                    fix.applied = success
                    if success:
                        report.fixes_applied += 1
                        report.fixes.append(fix)

            # ── 阶段 4: 测试验证 ──
            if report.fixes_applied > 0 and not dry_run:
                test_ok, _ = await self._run_tests()
                report.test_passed = test_ok
                for fix in report.fixes:
                    fix.test_passed = test_ok

                if not test_ok:
                    report.error = "测试失败，请检查修复结果"

            # ── 记录到学习引擎 ──
            self._record_heal_result(report)

        except Exception as e:
            report.error = str(e)

        report.duration_ms = (time.time() - t0) * 1000
        return report

    # ── 静态扫描 ──

    def _static_scan(self, target_dir: str) -> list[HealFix]:
        """内建静态代码扫描（不依赖外部工具）"""
        issues: list[HealFix] = []
        scan_root = self._root / target_dir if target_dir else self._root

        for py_file in scan_root.rglob("*.py"):
            # 跳过保护列表中的文件（决不扫描/修改自身等核心文件）
            if any(p in str(py_file) for p in self._protect_list):
                continue
            # 跳过 __pycache__
            if "__pycache__" in str(py_file):
                continue

            try:
                code = py_file.read_text(encoding="utf-8")
                lines = code.splitlines()
            except (OSError, UnicodeDecodeError) as e:
                logger.debug("scan_file_read_failed path=%s error=%s", py_file, e)
                continue

            rel = str(py_file.relative_to(self._root))

            # 1. BOM 检测
            if code.startswith("\ufeff"):
                issues.append(
                    HealFix(
                        file=rel,
                        reason="文件含 BOM 头",
                        severity="medium",
                        old_code="(BOM)",
                        new_code="UTF-8 无 BOM",
                    )
                )

            # 2. 行尾空格/混合缩进
            tabs = sum(1 for line in lines if line.startswith("\t"))
            spaces4 = sum(1 for line in lines if line.startswith("    "))
            if tabs > 0 and spaces4 > 0:
                issues.append(
                    HealFix(
                        file=rel,
                        reason="混合缩进（Tab + 空格）",
                        severity="low",
                    )
                )

            # 3. AST 语法检查
            try:
                ast.parse(code)
            except SyntaxError as e:
                issues.append(
                    HealFix(
                        file=rel,
                        reason=f"语法错误: {e.msg} (行{e.lineno})",
                        severity="critical",
                    )
                )

            # 4. 过长行
            long_lines = [(i + 1, line) for i, line in enumerate(lines) if len(line) > 120]
            if len(long_lines) > 20:
                issues.append(
                    HealFix(
                        file=rel,
                        reason=f"{len(long_lines)} 行超过 120 字符",
                        severity="low",
                    )
                )

            # 5. 硬编码密钥检测
            for i, line in enumerate(lines, 1):
                key_pattern = (
                    r"(?:api[_-]?key|apikey|secret|token|password)"
                    r'\s*[:=]\s*["\'][^"\']{8,}["\']'
                )
                if re.search(key_pattern, line, re.IGNORECASE):
                    stripped = line.strip()
                    if not stripped.startswith("#") and not stripped.startswith('"""'):
                        issues.append(
                            HealFix(
                                file=rel,
                                reason=f"硬编码密钥 (行{i})",
                                severity="high",
                            )
                        )
                        break

        return issues

    # ── 知识库匹配 ──

    def _match_knowledge(self, issues: list[HealFix]) -> list[HealFix]:
        """从知识库查询历史修复方案"""
        try:
            from .knowledge_base import get_knowledge_base

            kb = get_knowledge_base()
            fixes: list[HealFix] = []
            seen: set[str] = set()
            for issue in issues[:10]:
                if issue.file in seen:
                    continue
                pattern = kb.suggest_fix(issue.reason, min_confidence=0.5)
                if pattern and pattern.fix_template:
                    fixes.append(
                        HealFix(
                            file=issue.file,
                            reason=issue.reason,
                            severity=issue.severity,
                            new_code=pattern.fix_template[:2000],
                            old_code=issue.old_code,
                        )
                    )
                    seen.add(issue.file)
            return fixes
        except (ValueError, TypeError, KeyError, AttributeError, OSError) as e:
            logger.warning("pattern_based_heal_failed error=%s", e)
            return []

    # ── AI 深度修复 ──

    async def _ai_heal(self, issues: list[HealFix]) -> list[HealFix]:
        """调用 AI 生成精确修复"""
        try:
            from pycoder.server.chat_bridge import ChatBridge
            from pycoder.server.chat_handler import _get_api_key_for_model

            bridge = ChatBridge()
            api_key = _get_api_key_for_model("deepseek-reasoner")
            bridge.configure(model="deepseek-reasoner", api_key=api_key)
            bridge.config.max_tokens = 16384
            bridge.config.reasoning_effort = "high"

            files_text = ""
            for issue in issues:
                file_path = self._root / issue.file
                if file_path.exists():
                    code = file_path.read_text(encoding="utf-8")
                    files_text += (
                        f"\n## {issue.file}\n{issue.reason}\n" f"```python\n{code[:3000]}\n```\n"
                    )

            prompt = f"""分析以下 PyCoder 自身代码问题并给出精确修复。

{files_text}

输出格式: 对每个问题输出
[FIX:文件路径]
```python
完整的修复后代码
```
[END:FIX]"""

            bridge.config.system_prompt = (
                "你是 PyCoder 自修复专家。只输出 [FIX:path]...[END:FIX] 块。"
            )
            result = ""
            async for event in bridge.chat_stream(prompt):
                if event.event_type == "token":
                    result += event.content
                elif event.event_type == "done":
                    result = event.content or result
                    break
            await bridge.close()

            # 解析修复
            return self._parse_ai_fixes(result, issues)
        except (ValueError, TypeError, KeyError, RuntimeError, OSError) as e:
            logger.warning("ai_heal_failed error=%s", e)
            return []

    def _parse_ai_fixes(self, result: str, issues: list[HealFix]) -> list[HealFix]:
        """解析 AI 返回的 [FIX:...][END:FIX] 块"""
        fixes: list[HealFix] = []
        pattern = re.compile(r"\[FIX:(.+?)\]\n(.*?)\[END:FIX\]", re.DOTALL)
        for m in pattern.finditer(result):
            file_path = m.group(1).strip()
            new_code = m.group(2).strip()
            if new_code and len(new_code) > 20:
                # 匹配原始问题
                matched = next(
                    (i for i in issues if i.file == file_path),
                    issues[0] if issues else None,
                )
                if matched:
                    fixes.append(
                        HealFix(
                            file=file_path,
                            reason=matched.reason,
                            severity=matched.severity,
                            new_code=new_code,
                            old_code=matched.old_code,
                        )
                    )
        return fixes

    # ── 安全应用修复 ──

    def _apply_fix_safe(self, fix: HealFix) -> bool:
        """安全应用单个修复（备份+写入+语法验证）"""
        target = self._root / fix.file
        if not target.exists():
            return False
        if not fix.new_code or len(fix.new_code) < 10:
            return False
        # 占位符检测
        if re.search(r"#\s*\.{3}\s*(代码|code)", fix.new_code):
            return False

        # 核心文件令牌校验（复用 self_evolution 的令牌系统）
        is_core = any(p in str(target) for p in self._protect_list)
        if is_core:
            try:
                from pycoder.capabilities.self_evo.engine import (
                    SelfEvolutionEngine,
                )

                if not SelfEvolutionEngine._validate_evolution_token(
                    str(target),
                ):
                    logger.warning("heal_core_no_token", file=fix.file)
                    return False
            except ImportError:
                logger.warning("heal_token_check_import_failed")
                return False

        try:
            # 备份
            self._backup_dir.mkdir(exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            bak = self._backup_dir / f"{target.name}.{ts}.bak"
            shutil.copy2(target, bak)

            # 写入
            old = target.read_text(encoding="utf-8")
            target.write_text(fix.new_code, encoding="utf-8")
            fix.old_code = old[:500]

            # 语法验证
            try:
                ast.parse(fix.new_code)
                return True
            except SyntaxError:
                # 回滚
                target.write_text(old, encoding="utf-8")
                bak.unlink(missing_ok=True)
                return False
        except (OSError, ValueError) as e:
            logger.warning("apply_fix_failed error=%s", e)
            return False

    # ── 测试验证 ──

    async def _run_tests(self) -> tuple[bool, str]:
        """运行 pytest"""
        try:
            r = await asyncio.to_thread(
                subprocess.run,
                ["python", "-m", "pytest", "tests/", "-q", "--tb=short"],
                cwd=str(self._root),
                capture_output=True,
                text=True,
                timeout=60,
                encoding="utf-8",
                errors="replace",
            )
            return r.returncode == 0, (r.stdout + r.stderr)[:2000]
        except Exception as e:
            return False, str(e)

    # ── 学习记录 ──

    def _record_heal_result(self, report: HealReport) -> None:
        try:
            from . import get_learning_engine

            engine = get_learning_engine()
            for fix in report.fixes:
                engine.on_task_complete(
                    task_id=report.task_id,
                    task_type="self_heal",
                    outcome="success" if fix.applied and fix.test_passed else "failure",
                    description=f"自修复: {fix.reason}",
                    error_msg=fix.reason,
                    file_paths=[fix.file],
                    fix_content=fix.new_code[:500],
                    test_passed=fix.test_passed,
                    quality_score=90 if fix.test_passed else 30,
                )
        except (ImportError, RuntimeError, OSError, ValueError, TypeError) as e:
            logger.debug("learning_engine_record_failed error=%s", e)


# ══════════════════════════════════════════════════════════
# UsageAnalyzer — 使用记录分析器
# ══════════════════════════════════════════════════════════


class UsageAnalyzer:
    """分析 PyCoder 使用记录驱动进化优化"""

    def analyze(self, days: int = 30) -> UsageReport:
        """综合分析使用模式"""
        report = UsageReport()

        try:
            # 1. 从 session_store 分析对话
            self._analyze_sessions(report, days)

            # 2. 从 learning 知识库分析错误模式
            self._analyze_errors(report, days)

            # 3. 从 evolution 记录分析进化效果
            self._analyze_evolution(report, days)

            # 4. 生成优化建议
            self._generate_hints(report)

        except (ImportError, RuntimeError, OSError, ValueError, TypeError, KeyError) as e:
            logger.warning("usage_analysis_failed error=%s", e)

        return report

    def _analyze_sessions(self, report: UsageReport, days: int) -> None:
        """分析会话数据"""
        from pycoder.server.session_store import get_session_store

        store = get_session_store()

        sessions = store.list_sessions(limit=200)
        report.total_sessions = len(sessions)

        topic_counter: Counter = Counter()
        for sess in sessions:
            msgs = store.get_messages(sess.id)
            for msg in msgs:
                report.total_messages += 1
                if msg.role == "user":
                    report.user_messages += 1
                    # 提取话题关键词
                    for word in [
                        "错误",
                        "bug",
                        "修复",
                        "优化",
                        "功能",
                        "API",
                        "部署",
                        "数据库",
                        "前端",
                        "后端",
                        "测试",
                        "性能",
                        "安全",
                        "配置",
                        "模型",
                        "代理",
                        "error",
                        "fix",
                        "bug",
                        "deploy",
                        "test",
                    ]:
                        if word in msg.content[:200].lower():
                            topic_counter[word] += 1
                elif msg.role == "assistant":
                    report.ai_messages += 1
                # 统计模型使用
                model = msg.metadata.get("model", "") if hasattr(msg, "metadata") else ""
                if model:
                    report.model_distribution[model] = report.model_distribution.get(model, 0) + 1

        report.top_topics = topic_counter.most_common(15)

    def _analyze_errors(self, report: UsageReport, days: int) -> None:
        """分析错误模式"""
        try:
            from .knowledge_base import get_knowledge_base

            kb = get_knowledge_base()
            top_errors = kb.get_top_errors(limit=20)
            report.top_error_types = [
                (ep.error_type, ep.success_count + ep.fail_count) for ep in top_errors
            ]
            # 提取常见问题关键词
            report.common_issues = [
                ep.error_type for ep in top_errors[:10] if ep.fail_count > ep.success_count
            ]
        except (ImportError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as e:
            logger.debug("analyze_errors_failed error=%s", e)

    def _analyze_evolution(self, report: UsageReport, days: int) -> None:
        """分析进化记录"""
        try:
            from .metrics_tracker import get_metrics_tracker

            mt = get_metrics_tracker()
            stats = mt.get_evolution_stats(days=days)
            report.optimization_hints.append(
                f"最近{days}天: {stats['total_evolutions']}次进化, "
                f"成功率 {stats['success_rate']:.1%}, "
                f"修复 {stats['total_bugs_fixed']} 个bug"
            )
            daily = mt.get_daily_summary(days=min(days, 14))
            report.weekly_activity = daily
        except (ImportError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as e:
            logger.debug("analyze_evolution_failed error=%s", e)

    def _generate_hints(self, report: UsageReport) -> None:
        """生成优化建议"""
        hints = report.optimization_hints

        # 成功率相关
        if report.top_error_types:
            worst = report.top_error_types[0]
            hints.append(
                f"最高频错误: {worst[0]} ({worst[1]}次), "
                "建议优化相关 Agent 提示词或添加自动修复规则"
            )

        # 模型使用分布
        if report.model_distribution:
            total = sum(report.model_distribution.values())
            cheapest = (
                min(report.model_distribution.items(), key=lambda x: x[1])
                if report.model_distribution
                else ("?", 0)
            )
            if total > 0 and cheapest[1] / total < 0.1:
                hints.append(
                    f"模型 {cheapest[0]} 使用率仅 "
                    f"{cheapest[1] / total:.1%}, "
                    "建议增加路由到低成本模型"
                )

        # 活跃度
        if report.total_sessions < 3:
            hints.append("会话数较少，积累更多数据后可进行精准优化")

        # 会话质量
        if report.user_messages > 0 and report.ai_messages > 0:
            ratio = report.ai_messages / max(report.user_messages, 1)
            if ratio > 3:
                hints.append(f"AI/用户消息比 {ratio:.1f}, 可能响应过长, 建议精简提示词")


# ══════════════════════════════════════════════════════════
# PromptOptimizer — 提示词自动优化器
# ══════════════════════════════════════════════════════════


class PromptOptimizer:
    """基于历史成功率自动优化 Agent 提示词和模型路由"""

    def optimize_agent_prompt(self, agent_id: str) -> PromptOptimization:
        """优化指定 Agent 的提示词"""
        result = PromptOptimization(agent_id=agent_id)

        try:
            from pycoder.server.services.agent_definitions import AGENT_ROLES

            role = AGENT_ROLES.get(agent_id)
            if not role:
                return result

            original = role.system_prompt
            result.original_lines = len(original.splitlines())

            # 1. 检查提示词底线（≥ 400 行）
            if result.original_lines < _MIN_CORE_PROMPT_LINES:
                result.changes.append(
                    f"提示词仅 {result.original_lines} 行, "
                    f"建议扩充到 ≥ {_MIN_CORE_PROMPT_LINES} 行"
                )

            # 2. 检查是否缺少关键部分
            required_sections = {
                "职责": "职责" not in original and "角色" not in original,
                "输出格式": "输出格式" not in original and "格式" not in original,
                "原则": "原则" not in original and "约束" not in original,
                "执行铁律": "铁律" not in original and "备份" not in original,
            }
            for section, missing in required_sections.items():
                if missing:
                    result.changes.append(f"缺少关键部分: {section}")

            # 3. 从知识库获取该角色的成功率
            try:
                from .feedback_loop import get_feedback_loop

                fb = get_feedback_loop()
                config = fb.get_adaptive_config()
                preferred = config.preferred_models.get(agent_id)
                if preferred and preferred != role.model:
                    result.changes.append(
                        f"推荐模型 {preferred} 优于当前 {role.model}, " "建议更新 agent_definition"
                    )
            except (
                ImportError,
                RuntimeError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
            ) as e:
                logger.debug("preferred_model_lookup_failed agent=%s error=%s", agent_id, e)

            result.expected_improvement = (
                f"修复 {len(result.changes)} 个问题后, " "预计提升任务成功率 5-15%"
            )

        except (ImportError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as e:
            logger.warning("prompt_optimize_failed agent=%s error=%s", agent_id, e)

        return result

    def optimize_all_agents(self) -> list[PromptOptimization]:
        """批量优化所有 Agent"""
        results = []
        for agent_id in ["pm", "architect", "developer", "qa", "devops"]:
            results.append(self.optimize_agent_prompt(agent_id))
        return results

    def generate_optimization_report(self) -> str:
        """生成提示词优化报告"""
        results = self.optimize_all_agents()
        lines = ["# 🧠 Agent 提示词优化报告", ""]

        for r in results:
            lines.append(f"## {r.agent_id}")
            lines.append(f"- 原始行数: {r.original_lines}")
            if r.changes:
                for c in r.changes:
                    lines.append(f"  - ⚠️ {c}")
                lines.append(f"  - 📈 {r.expected_improvement}")
            else:
                lines.append("  - ✅ 无需优化")
            lines.append("")

        return "\n".join(lines)


# ══════════════════════════════════════════════════════════
# 统一入口
# ══════════════════════════════════════════════════════════


class SelfOptimizer:
    """PyCoder 自优化引擎 — 统一入口"""

    def __init__(self):
        self.healer = SelfHealer()
        self.analyzer = UsageAnalyzer()
        self.prompt_opt = PromptOptimizer()

    async def auto_heal(self, dry_run: bool = False) -> HealReport:
        """自动修复 PyCoder 自身代码"""
        return await self.healer.auto_heal(dry_run=dry_run)

    def analyze_usage(self, days: int = 30) -> UsageReport:
        """分析使用模式"""
        return self.analyzer.analyze(days=days)

    def optimize_prompts(self) -> list[PromptOptimization]:
        """优化 Agent 提示词"""
        return self.prompt_opt.optimize_all_agents()

    def full_optimization_cycle(self) -> dict:
        """完整自优化周期: 分析 → 优化 → 修复

        返回: {usage, prompts, heal}
        """
        result = {
            "usage": None,
            "prompts": [],
            "heal": None,
            "recommendations": [],
        }

        # 1. 分析使用记录
        usage = self.analyze_usage(days=30)
        result["usage"] = {
            "sessions": usage.total_sessions,
            "messages": usage.total_messages,
            "top_topics": usage.top_topics[:5],
            "top_errors": usage.top_error_types[:5],
            "hints": usage.optimization_hints,
        }

        # 2. 优化提示词
        prompts = self.optimize_prompts()
        result["prompts"] = [
            {
                "agent": p.agent_id,
                "lines": p.original_lines,
                "issues": len(p.changes),
                "changes": p.changes,
            }
            for p in prompts
            if p.changes
        ]

        # 3. 生成推荐
        recs = result["recommendations"]
        if usage.common_issues:
            recs.append(f"⚠️ 高频问题: {', '.join(usage.common_issues[:3])}")
        if len(prompts) > 0 and any(p.changes for p in prompts):
            recs.append("📝 建议优化 Agent 提示词（详见 prompts 字段）")
        if usage.top_topics:
            top = usage.top_topics[0]
            recs.append(f"🔍 最热话题 '{top[0]}' ({top[1]}次), 建议增强相关能力")
        if usage.model_distribution:
            recs.append(f"🤖 模型分布: {dict(list(usage.model_distribution.items())[:3])}")

        return result

    def generate_optimization_markdown(self) -> str:
        """生成完整自优化 Markdown 报告"""
        result = self.full_optimization_cycle()

        usage = result["usage"] or {}
        lines = [
            "# 🔧 PyCoder 自优化报告",
            f"\n生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 📊 使用分析",
            "| 指标 | 值 |",
            "|------|------|",
            f"| 总会话 | {usage.get('sessions', 0)} |",
            f"| 总消息 | {usage.get('messages', 0)} |",
        ]

        if usage.get("top_topics"):
            lines.append(
                f"| 热门话题 | {', '.join(f'{t}({c})' for t, c in usage['top_topics'][:5])} |"
            )

        top_errors = usage.get("top_errors", [])
        if top_errors:
            lines.append(f"| 高频错误 | {', '.join(f'{t}({c})' for t, c in top_errors[:5])} |")

        hints = usage.get("hints", [])
        if hints:
            lines.extend(["", "## 💡 优化建议"])
            for h in hints:
                lines.append(f"- {h}")

        prompt_results = result.get("prompts", [])
        if prompt_results:
            lines.extend(["", "## 📝 提示词优化"])
            for p in prompt_results:
                lines.append(f"- **{p['agent']}**: {p['issues']} 个问题")
                for c in p.get("changes", [])[:3]:
                    lines.append(f"  - {c}")

        recs = result.get("recommendations", [])
        if recs:
            lines.extend(["", "## 🎯 推荐操作"])
            for r in recs:
                lines.append(f"- {r}")

        lines.extend(
            [
                "",
                "---",
                "*由 PyCoder SelfOptimizer 自动生成*",
            ]
        )
        return "\n".join(lines)


# 全局单例
_optimizer: SelfOptimizer | None = None


def get_self_optimizer() -> SelfOptimizer:
    global _optimizer
    if _optimizer is None:
        _optimizer = SelfOptimizer()
    return _optimizer


__all__ = [
    "SelfOptimizer",
    "SelfHealer",
    "UsageAnalyzer",
    "PromptOptimizer",
    "HealReport",
    "HealFix",
    "UsageReport",
    "PromptOptimization",
    "get_self_optimizer",
]
