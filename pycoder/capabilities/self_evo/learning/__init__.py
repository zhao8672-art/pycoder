"""
PyCoder 自我学习进化引擎 — 统一入口

整合以下子系统实现完整的学习闭环:
  ┌───────────────────────────────────────────────────────┐
  │                 LearningEngine                        │
  ├───────────────────────────────────────────────────────┤
  │  KnowledgeBase    — 错误模式库 + 修复历史 + 项目知识   │
  │  ExperienceBuffer — 经验回放 + 优先级采样              │
  │  MetricsTracker   — 进化统计 + 质量趋势 + 学习事件     │
  │  PatternExtractor — 修复模式挖掘 + 热点分析 + Prompt优化│
  │  FeedbackLoop     — 反馈收集 + 自适应阈值 + 模型路由   │
  └───────────────────────────────────────────────────────┘

学习闭环:
  执行任务 → 记录经验 → 提取模式 → 收集反馈 → 调整参数 → 优化执行

用法:
  from pycoder.server.learning import LearningEngine

  engine = LearningEngine()

  # 任务完成后
  engine.on_task_complete(task_id="T-001", outcome="success",
                          error="NameError: 'x' not defined",
                          fix="import x", quality=90)

  # 生成学习报告
  report = engine.generate_learning_report()

  # 为下一个任务获取优化建议
  advice = engine.get_task_advice(task_description="修复API错误")
"""

from __future__ import annotations

import time

from .experience_buffer import (
    ExperienceBuffer,
    TaskExperience,
    compute_reward,
    get_experience_buffer,
)
from .feedback_applier import (
    FeedbackApplier,
    get_feedback_applier,
    reset_feedback_applier,
)
from .feedback_loop import (
    AdaptiveConfig,
    FeedbackLoop,
    FeedbackSignal,
    get_feedback_loop,
)
from .knowledge_base import (
    KnowledgeBase,
    classify_error,
    get_knowledge_base,
    normalize_error_signature,
)
from .metrics_tracker import (
    MetricsTracker,
    get_metrics_tracker,
)
from .pattern_extractor import FixPattern, PatternExtractor

# 新增模块
from .refactoring_engine import (
    CodeMetrics,
    RefactorResult,
    RefactorSuggestion,
    RefactoringEngine,
    get_refactoring_engine,
)
from .policy_manager import (
    PolicyChange,
    PolicyManager,
    SystemPolicy,
    get_policy_manager,
)
from .meta_cognition import (
    CapabilityMaturity,
    MetaCognition,
    SelfAssessment,
    SystemHealth,
    get_meta_cognition,
)
from .integration import (
    EvolutionIntegration,
    IntegrationStatus,
    get_evolution_integration,
)

# Bug #8: PatternExtractor 也做单例
_pattern_extractor_instance: PatternExtractor | None = None


def get_pattern_extractor() -> PatternExtractor:
    global _pattern_extractor_instance
    if _pattern_extractor_instance is None:
        _pattern_extractor_instance = PatternExtractor()
    return _pattern_extractor_instance


def _format_top_errors(top_errors: list) -> str:
    """格式化高频错误列表为表格单元格内容"""
    if top_errors:
        return ", ".join(f"{e}({c})" for e, c in top_errors[:3])
    return "无数据"


class LearningEngine:
    """自我学习进化引擎 — 统一入口"""

    def __init__(self):
        self.kb: KnowledgeBase = get_knowledge_base()
        self.buffer: ExperienceBuffer = get_experience_buffer()
        self.metrics: MetricsTracker = get_metrics_tracker()
        self.patterns: PatternExtractor = get_pattern_extractor()  # Bug #8
        self.feedback: FeedbackLoop = get_feedback_loop()

        # Bug #15: 防重复记录 — 最近 20 个 task_id
        self._recent_task_ids: set[str] = set()
        self._max_recent_tasks: int = 20

        # 模式提取间隔（秒）
        self._pattern_interval: float = 3600  # 1小时
        self._last_pattern_extraction: float = 0.0

    # ══════════════════════════════════════════════════════
    # 主要接口：任务完成时调用
    # ══════════════════════════════════════════════════════

    def on_task_complete(
        self,
        task_id: str = "",
        outcome: str = "success",
        task_type: str = "fix",
        description: str = "",
        error_msg: str = "",
        file_paths: list[str] | None = None,
        fix_content: str = "",
        test_passed: bool = False,
        quality_score: float = 0.0,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        duration_ms: float = 0.0,
        retry_count: int = 0,
        agent_role: str = "",
        model_used: str = "",
        test_coverage: float = 0.0,
    ) -> dict:
        """
        任务完成时调用 — 自动触发完整学习流程

        返回: {"recorded": ..., "patterns_found": ..., "feedback": ...}
        """
        # Bug #15: 防重复 — 同一 task_id 在短时间(60s)内只记录一次
        if task_id:
            now = time.time()
            if task_id in self._recent_task_ids:
                return {"dedup": True, "message": f"已处理过 {task_id}"}
            self._recent_task_ids.add(task_id)
            # 控制集合大小
            if len(self._recent_task_ids) > self._max_recent_tasks:
                self._recent_task_ids = set(list(self._recent_task_ids)[-self._max_recent_tasks :])

        file_paths = file_paths or []
        result: dict = {}

        # 1. 记录到知识库
        if error_msg:
            error_sig = normalize_error_signature(error_msg)
            self.kb.record_error_pattern(
                error_msg,
                fix_content,
                file_path=file_paths[0] if file_paths else "",
                success=(outcome == "success"),
            )
            self.kb.record_fix(
                task_id=task_id,
                error_msg=error_msg,
                file_path=file_paths[0] if file_paths else "",
                fix_content=fix_content,
                outcome=outcome,
                test_result="passed" if test_passed else "failed",
                quality_score=quality_score,
                tokens_used=tokens_used,
                duration_ms=duration_ms,
                agent_role=agent_role,
            )
            result["error_pattern"] = error_sig

        # 2. 记录到经验缓冲区
        exp = TaskExperience(
            task_type=task_type,
            description=description,
            error_signature=normalize_error_signature(error_msg) if error_msg else "",
            error_message=error_msg,
            file_paths=file_paths,
            fix_content=fix_content,
            agent_role=agent_role,
            model_used=model_used,
            outcome=outcome,
            test_passed=test_passed,
            quality_score=quality_score,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            retry_count=retry_count,
        )
        exp_id = self.buffer.store(exp)
        result["experience_id"] = exp_id

        # 3. 记录到指标追踪器
        self.metrics.record_evolution(
            task_id=task_id,
            operation=task_type,
            outcome=outcome,
            test_passed=test_passed,
            quality_score=quality_score,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
            duration_seconds=duration_ms / 1000.0,
            rollback_count=1 if outcome == "rolled_back" else 0,
        )

        # 4. 收集反馈
        self.feedback.collect(
            task_id=task_id,
            outcome=outcome,
            quality_score=quality_score,
            test_passed=test_passed,
            test_coverage=test_coverage,
            retry_count=retry_count,
            tokens_used=tokens_used,
            duration_ms=duration_ms,
            agent_role=agent_role,
            model_used=model_used,
            error_type=classify_error(error_msg) if error_msg else "",
        )
        result["feedback_config"] = {
            "quality_threshold": self.feedback.get_adaptive_config().quality_threshold,
        }

        # 5. 定期提取模式
        now = time.time()
        if now - self._last_pattern_extraction > self._pattern_interval:
            patterns = self.patterns.extract_fix_patterns(
                knowledge_base=self.kb,
                experience_buffer=self.buffer,
            )
            self._last_pattern_extraction = now
            result["patterns_extracted"] = len(patterns)

        return result

    def on_quality_scan(
        self,
        lint_score: float = 100,
        security_score: float = 100,
        complexity_score: float = 100,
        test_coverage: float = 0,
        total_score: float = 100,
        file_count: int = 0,
        issue_count: int = 0,
    ) -> None:
        """质量扫描完成时记录快照"""
        self.metrics.record_quality_snapshot(
            lint_score=lint_score,
            security_score=security_score,
            complexity_score=complexity_score,
            test_coverage=test_coverage,
            total_score=total_score,
            file_count=file_count,
            issue_count=issue_count,
        )

    def on_pipeline_complete(
        self,
        pipeline_result: dict,
    ) -> dict:
        """流水线完成后调用"""
        return self.on_task_complete(
            task_id=pipeline_result.get("run_id", ""),
            outcome=pipeline_result.get("status", "success"),
            task_type="pipeline",
            description=pipeline_result.get("request", ""),
            quality_score=pipeline_result.get("quality_score", 0),
            tokens_used=pipeline_result.get("tokens_used", 0),
            agent_role="team",
            retry_count=pipeline_result.get("review_rounds", 0),
        )

    # ══════════════════════════════════════════════════════
    # 查询接口
    # ══════════════════════════════════════════════════════

    def get_task_advice(self, task_description: str = "", error_msg: str = "") -> dict:
        """获取任务优化建议

        返回: {
            "suggested_fix": ...,
            "hotspots_to_check": [...],
            "risk_warnings": [...],
            "suggested_model": ...,
            "quality_threshold": ...,
        }
        """
        advice: dict = {
            "suggested_fix": None,
            "hotspots_to_check": [],
            "risk_warnings": [],
            "suggested_model": "deepseek-chat",
            "quality_threshold": 85.0,
        }

        # 1. 查询知识库推荐修复
        if error_msg:
            pattern = self.kb.suggest_fix(error_msg)
            if pattern:
                advice["suggested_fix"] = {
                    "error_type": pattern.error_type,
                    "fix_template": pattern.fix_template,
                    "confidence": round(pattern.confidence, 2),
                    "based_on": pattern.success_count + pattern.fail_count,
                }

        # 2. 获取热点信息（哪些文件容易出错）
        hotspots = self.patterns.get_hotspots(
            knowledge_base=self.kb,
            experience_buffer=self.buffer,
            top_n=5,
        )
        advice["hotspots_to_check"] = [
            {
                "file": h.file_path,
                "error_count": h.error_count,
                "risk_score": round(h.risk_score, 0),
            }
            for h in hotspots
        ]

        # 3. 获取自适应配置
        config = self.feedback.get_adaptive_config()
        advice["quality_threshold"] = config.quality_threshold
        advice["max_retries"] = config.max_retries
        advice["suggested_model"] = config.preferred_models.get(
            "developer",
            "deepseek-chat",
        )

        # 4. 风险警告
        feedback_stats = self.feedback.get_stats()
        if feedback_stats.get("recent_success_rate", 1) < 0.5:
            advice["risk_warnings"].append(
                f"近期任务成功率较低 ({feedback_stats['recent_success_rate']:.0%})，"
                "建议先做最小验证"
            )

        # 查询近期高频错误
        top_errors = self.kb.get_top_errors(limit=5)
        for ep in top_errors:
            if ep.fail_count > ep.success_count:
                advice["risk_warnings"].append(
                    f"注意: {ep.error_type} 修复成功率仅 {ep.success_rate:.0%}"
                )

        return advice

    def generate_learning_report(self) -> dict:
        """生成综合学习报告"""
        # 知识库统计
        kb_stats = self.kb.get_stats()

        # 经验缓冲区统计
        buf_stats = self.buffer.get_stats(window_hours=168)

        # 进化统计
        evo_stats = self.metrics.get_evolution_stats(days=30)

        # 反馈统计
        fb_stats = self.feedback.get_stats()

        # 模式统计
        pattern_stats = self.patterns.get_pattern_stats()

        # 热点
        hotspots = self.patterns.get_hotspots(
            knowledge_base=self.kb,
            experience_buffer=self.buffer,
            top_n=10,
        )

        # 质量趋势
        quality_trends = self.metrics.get_quality_trends(days=14)

        return {
            "generated_at": time.time(),
            "knowledge_base": kb_stats,
            "experience_buffer": {
                "total_experiences": buf_stats.total,
                "recent_success_rate": round(buf_stats.recent_success_rate, 3),
                "avg_reward": round(buf_stats.avg_reward, 3),
                "avg_quality": round(buf_stats.avg_quality, 1),
                "top_errors": buf_stats.top_error_types[:5],
            },
            "evolution": evo_stats,
            "feedback": fb_stats,
            "patterns": pattern_stats,
            "hotspots": [
                {
                    "file": h.file_path,
                    "errors": h.error_count,
                    "risk": round(h.risk_score, 0),
                }
                for h in hotspots
            ],
            "quality_trends": quality_trends[-7:],  # 最近7天
        }

    def generate_learning_report_markdown(self) -> str:
        """生成 Markdown 格式学习报告"""
        r = self.generate_learning_report()

        kb = r["knowledge_base"]
        buf = r["experience_buffer"]
        evo = r["evolution"]
        fb = r["feedback"]

        lines = [
            "# 🧠 PyCoder 学习进化报告",
            "",
            f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 📊 知识库",
            "| 指标 | 值 |",
            "|------|------|",
            f"| 错误模式 | {kb['error_patterns']} |",
            f"| 总修复次数 | {kb['total_fixes']} |",
            f"| 成功修复 | {kb['successful_fixes']} |",
            f"| 修复成功率 | {kb['fix_success_rate']:.1%} |",
            f"| 累计Token | {kb['total_tokens_spent']:,} |",
            f"| 平均质量分 | {kb['avg_quality_score']:.0f} |",
            "",
            "## 🧪 经验缓冲区",
            "| 指标 | 值 |",
            "|------|------|",
            f"| 总经验数 | {buf['total_experiences']} |",
            f"| 近期成功率 | {buf['recent_success_rate']:.1%} |",
            f"| 平均奖励 | {buf['avg_reward']:.2f} |",
            f"| 平均质量 | {buf['avg_quality']:.0f} |",
            "| 高频错误 | " + _format_top_errors(buf["top_errors"]) + " |",
        ]

        lines.extend(
            [
                "",
                "## 📈 进化统计（30天）",
                "| 指标 | 值 |",
                "|------|------|",
                f"| 进化次数 | {evo['total_evolutions']} |",
                f"| 成功率 | {evo['success_rate']:.1%} |",
                f"| 修改行数 | {evo['total_lines_changed']} |",
                f"| 修复Bug数 | {evo['total_bugs_fixed']} |",
                f"| Token消耗 | {evo['total_tokens']:,} |",
                f"| 成本 | ${evo['total_cost_usd']:.2f} |",
                f"| 回滚次数 | {evo['rollbacks']} |",
                "",
                "## 🔧 自适应配置",
                "| 参数 | 值 |",
                "|------|------|",
                f"| 质量门禁阈值 | {fb['adaptive_config']['quality_threshold']:.0f} |",
                f"| 最大重试次数 | {fb['adaptive_config']['max_retries']} |",
                f"| 最近成功率 | {fb['recent_success_rate']:.1%} |",
            ]
        )

        # 热点
        if r["hotspots"]:
            lines.extend(
                [
                    "",
                    "## 🔥 Bug 热点",
                ]
            )
            for h in r["hotspots"]:
                lines.append(f"- `{h['file']}`: {h['errors']}次 (风险 {h['risk']:.0f})")

        lines.extend(
            [
                "",
                "---",
                "*自动生成于 PyCoder LearningEngine*",
            ]
        )

        return "\n".join(lines)


# 全局单例
_engine: LearningEngine | None = None


def get_learning_engine() -> LearningEngine:
    global _engine
    if _engine is None:
        _engine = LearningEngine()
    return _engine


__all__ = [
    "LearningEngine",
    "get_learning_engine",
    "KnowledgeBase",
    "ExperienceBuffer",
    "MetricsTracker",
    "PatternExtractor",
    "FeedbackLoop",
    "FeedbackApplier",
    "RefactoringEngine",
    "RefactorSuggestion",
    "RefactorResult",
    "CodeMetrics",
    "PolicyManager",
    "SystemPolicy",
    "PolicyChange",
    "MetaCognition",
    "SelfAssessment",
    "SystemHealth",
    "CapabilityMaturity",
    "get_feedback_applier",
    "get_knowledge_base",
    "get_experience_buffer",
    "get_metrics_tracker",
    "get_feedback_loop",
    "get_pattern_extractor",
    "get_refactoring_engine",
    "get_policy_manager",
    "get_meta_cognition",
    "get_evolution_integration",
    "EvolutionIntegration",
    "IntegrationStatus",
    "TaskExperience",
    "FixPattern",
    "FeedbackSignal",
    "AdaptiveConfig",
    "normalize_error_signature",
    "classify_error",
    "compute_reward",
    "reset_feedback_applier",
]
