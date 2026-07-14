"""
反馈闭环 — 收集隐式/显式反馈，自动调整系统参数

核心机制:
  1. 隐式反馈: 自动从执行结果推断质量（测试通过/失败、回滚率）
  2. 显式反馈: 用户评分（👍/👎）、验收结果
  3. 自适应阈值: 质量门禁阈值、重试次数随历史表现动态调整
  4. 模型路由优化: 根据历史成功率自动选择最佳模型

用法:
  from .feedback_loop import FeedbackLoop
  fl = FeedbackLoop()
  fl.collect(task_id="T-001", outcome="success", quality=92)
  adjusted = fl.adjust_quality_threshold()
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


FEEDBACK_DIR = Path(
    os.environ.get(
        "PYCODER_FEEDBACK_DIR",
        str(Path.home() / ".pycoder" / "learning" / "feedback"),
    )
)

# 默认阈值
DEFAULT_QUALITY_THRESHOLD = 85.0
DEFAULT_MIN_SCORE = 80.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_COVERAGE_THRESHOLD = 85.0


@dataclass
class FeedbackSignal:
    """单次反馈信号"""

    task_id: str = ""
    signal_type: str = ""  # implicit | explicit
    outcome: str = ""  # success | failure | partial
    quality_score: float = 0.0
    test_passed: bool = False
    test_coverage: float = 0.0
    user_rating: int = 0  # -1(👎) / 0(无) / 1(👍)
    retry_count: int = 0
    tokens_used: int = 0
    duration_ms: float = 0.0
    agent_role: str = ""
    model_used: str = ""
    error_type: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class AdaptiveConfig:
    """自适应配置"""

    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD
    min_score: float = DEFAULT_MIN_SCORE
    max_retries: int = DEFAULT_MAX_RETRIES
    coverage_threshold: float = DEFAULT_COVERAGE_THRESHOLD
    # 模型偏好
    preferred_models: dict[str, str] = field(default_factory=dict)
    # 更新历史
    adjustment_history: list[dict] = field(default_factory=list)
    last_adjusted: float = 0.0


class FeedbackLoop:
    """反馈闭环 — 收集反馈并自适应调整"""

    def __init__(self):
        FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
        self._signals: list[FeedbackSignal] = []
        self._config_path = FEEDBACK_DIR / "adaptive_config.json"
        self._signals_path = FEEDBACK_DIR / "signals.jsonl"
        self._config = self._load_config()
        # P2-3: 加载历史信号，使重启后仍保留反馈历史
        self._load_signals()

    # ─── 反馈收集 ───

    def collect(
        self,
        task_id: str = "",
        outcome: str = "",
        quality_score: float = 0.0,
        test_passed: bool = False,
        test_coverage: float = 0.0,
        user_rating: int = 0,
        retry_count: int = 0,
        tokens_used: int = 0,
        duration_ms: float = 0.0,
        agent_role: str = "",
        model_used: str = "",
        error_type: str = "",
    ) -> None:
        """收集反馈信号"""
        signal = FeedbackSignal(
            task_id=task_id,
            signal_type="explicit" if user_rating != 0 else "implicit",
            outcome=outcome,
            quality_score=quality_score,
            test_passed=test_passed,
            test_coverage=test_coverage,
            user_rating=user_rating,
            retry_count=retry_count,
            tokens_used=tokens_used,
            duration_ms=duration_ms,
            agent_role=agent_role,
            model_used=model_used,
            error_type=error_type,
        )
        self._signals.append(signal)

        # 只保留最近 500 条
        if len(self._signals) > 500:
            self._signals = self._signals[-500:]
            self._save_signals()  # P2-3: 截断时全量重写，避免文件无限增长

        # P2-3: 追加写入单条信号到 JSONL（O(1) 开销）
        self._append_signal(signal)

        # 定期触发自适应调整
        if len(self._signals) % 50 == 0:
            self._adjust()

    def collect_from_execution_report(self, report) -> None:
        """从 ExecutionReport 收集隐式反馈"""
        outcome = report.status
        if outcome == "success" and report.errors:
            outcome = "partial"

        # Bug #2: report.to_dict() 没有 avg_quality 键
        report_dict = report.to_dict()
        # 用 files_changed 数量估质量标准
        quality_estimate = 100.0
        if report.errors:
            quality_estimate -= min(len(report.errors) * 10, 50)
        if report.retry_events:
            quality_estimate -= min(len(report.retry_events) * 5, 30)
        quality_score = float(report_dict.get("avg_quality", quality_estimate))

        self.collect(
            task_id=report.task_id,
            outcome=outcome,
            quality_score=quality_score,
            test_passed=report.status == "success",
            retry_count=len(report.retry_events),
            tokens_used=report.total_tokens,
            duration_ms=report.duration_seconds * 1000,
            agent_role="team",
        )

    # ─── 自适应调整 ───

    def _adjust(self) -> AdaptiveConfig:
        """根据历史反馈自适应调整参数"""
        if len(self._signals) < 20:
            return self._config

        recent = self._signals[-100:]

        # 1. 质量门禁阈值调整
        success_signals = [s for s in recent if s.outcome == "success"]
        success_rate = len(success_signals) / len(recent)

        if success_rate > 0.9:
            self._config.quality_threshold = min(
                95,
                self._config.quality_threshold + 1,
            )
        elif success_rate < 0.5:
            self._config.quality_threshold = max(
                70,
                self._config.quality_threshold - 2,
            )

        # 2. 重试次数调整
        avg_retries = sum(s.retry_count for s in recent) / len(recent)
        if avg_retries > 2:
            self._config.max_retries = min(5, self._config.max_retries + 1)
        elif avg_retries < 0.5 and self._config.max_retries > 1:
            self._config.max_retries -= 1

        # 3. 模型偏好更新
        role_model_stats: dict[str, dict[str, list[bool]]] = {}
        for s in recent:
            key = s.agent_role or "default"
            model = s.model_used or "unknown"
            role_model_stats.setdefault(key, {}).setdefault(model, []).append(
                s.outcome == "success"
            )

        for role, models in role_model_stats.items():
            best_model = ""
            best_rate = 0.0
            for model, outcomes in models.items():
                rate = sum(outcomes) / max(len(outcomes), 1)
                if rate > best_rate:
                    best_rate = rate
                    best_model = model
            if best_model:
                self._config.preferred_models[role] = best_model

        # 记录调整历史
        self._config.adjustment_history.append(
            {
                "timestamp": time.time(),
                "sample_size": len(recent),
                "success_rate": round(success_rate, 3),
                "quality_threshold": self._config.quality_threshold,
                "max_retries": self._config.max_retries,
            }
        )
        if len(self._config.adjustment_history) > 20:
            self._config.adjustment_history = self._config.adjustment_history[-20:]
        self._config.last_adjusted = time.time()
        self._save_config()
        self._save_signals()  # P2-3: 持久化截断后的信号
        return self._config

    def force_adjust(self) -> AdaptiveConfig:
        """强制触发自适应调整"""
        return self._adjust()

    # ─── 查询 ───

    def get_adaptive_config(self) -> AdaptiveConfig:
        """获取当前自适应配置"""
        return self._config

    def get_recent_feedback(self, limit: int = 20) -> list[dict]:
        """获取最近的反馈"""
        return [
            {
                "task_id": s.task_id,
                "outcome": s.outcome,
                "quality": s.quality_score,
                "test_passed": s.test_passed,
                "user_rating": s.user_rating,
                "retries": s.retry_count,
                "role": s.agent_role,
                "model": s.model_used,
                "timestamp": s.timestamp,
            }
            for s in self._signals[-limit:]
        ]

    def get_stats(self) -> dict:
        """获取反馈统计

        Bug 修复：空信号时也返回与有信号时同构的字典（含 adaptive_config），
        避免 generate_learning_report_markdown 等下游消费者 KeyError。
        """
        # adaptive_config 在两种分支都返回，避免下游 KeyError
        adaptive_config = {
            "quality_threshold": self._config.quality_threshold,
            "max_retries": self._config.max_retries,
            "coverage_threshold": self._config.coverage_threshold,
            "last_adjusted": self._config.last_adjusted,
        }

        if not self._signals:
            # 与下方分支保持键名一致（统一用 total_signals / recent_success_rate）
            return {
                "total_signals": 0,
                "recent_total": 0,
                "recent_success_rate": 0.0,
                "explicit_feedback_rate": 0.0,
                "avg_quality_score": 0.0,
                "adaptive_config": adaptive_config,
                # 兼容旧代码的简短键
                "total": 0,
                "success_rate": 0,
            }

        recent = self._signals[-100:]
        success = sum(1 for s in recent if s.outcome == "success")
        explicit = sum(1 for s in recent if s.signal_type == "explicit")
        avg_quality = sum(s.quality_score for s in recent if s.quality_score > 0) / max(
            sum(1 for s in recent if s.quality_score > 0),
            1,
        )
        rate = success / len(recent)

        return {
            "total_signals": len(self._signals),
            "recent_total": len(recent),
            "recent_success_rate": rate,
            "explicit_feedback_rate": explicit / len(recent),
            "avg_quality_score": round(avg_quality, 1),
            "adaptive_config": adaptive_config,
            # 兼容旧代码的简短键
            "total": len(self._signals),
            "success_rate": rate,
        }

    # ─── 持久化 ───

    def _load_signals(self) -> None:
        """P2-3: 从 JSONL 文件加载历史信号回填 _signals

        只加载最近 500 条，使重启后反馈历史与统计仍可用。
        """
        if not self._signals_path.exists():
            return
        try:
            lines = self._signals_path.read_text(encoding="utf-8").splitlines()
            for line in lines[-500:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    self._signals.append(
                        FeedbackSignal(
                            task_id=data.get("task_id", ""),
                            signal_type=data.get("signal_type", ""),
                            outcome=data.get("outcome", ""),
                            quality_score=data.get("quality_score", 0.0),
                            test_passed=data.get("test_passed", False),
                            test_coverage=data.get("test_coverage", 0.0),
                            user_rating=data.get("user_rating", 0),
                            retry_count=data.get("retry_count", 0),
                            tokens_used=data.get("tokens_used", 0),
                            duration_ms=data.get("duration_ms", 0.0),
                            agent_role=data.get("agent_role", ""),
                            model_used=data.get("model_used", ""),
                            error_type=data.get("error_type", ""),
                            timestamp=data.get("timestamp", 0.0),
                        )
                    )
                except (json.JSONDecodeError, TypeError):
                    continue
        except OSError:
            return

    def _save_signals(self) -> None:
        """P2-3: 全量重写 signals.jsonl（截断后与内存保持一致）"""
        try:
            lines = [json.dumps(self._signal_to_dict(s), ensure_ascii=False) for s in self._signals]
            self._signals_path.write_text(
                "\n".join(lines) + ("\n" if lines else ""),
                encoding="utf-8",
            )
        except OSError:
            pass  # 持久化失败不应影响主流程

    def _append_signal(self, signal: FeedbackSignal) -> None:
        """P2-3: 追加写入单条信号（O(1) 开销，避免每次全量重写）"""
        try:
            line = json.dumps(self._signal_to_dict(signal), ensure_ascii=False)
            with self._signals_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    @staticmethod
    def _signal_to_dict(s: FeedbackSignal) -> dict:
        """将 FeedbackSignal 序列化为可 JSON 化的字典"""
        return {
            "task_id": s.task_id,
            "signal_type": s.signal_type,
            "outcome": s.outcome,
            "quality_score": s.quality_score,
            "test_passed": s.test_passed,
            "test_coverage": s.test_coverage,
            "user_rating": s.user_rating,
            "retry_count": s.retry_count,
            "tokens_used": s.tokens_used,
            "duration_ms": s.duration_ms,
            "agent_role": s.agent_role,
            "model_used": s.model_used,
            "error_type": s.error_type,
            "timestamp": s.timestamp,
        }

    def _load_config(self) -> AdaptiveConfig:
        """加载自适应配置"""
        if self._config_path.exists():
            try:
                data = json.loads(self._config_path.read_text(encoding="utf-8"))
                return AdaptiveConfig(
                    quality_threshold=data.get("quality_threshold", DEFAULT_QUALITY_THRESHOLD),
                    min_score=data.get("min_score", DEFAULT_MIN_SCORE),
                    max_retries=data.get("max_retries", DEFAULT_MAX_RETRIES),
                    coverage_threshold=data.get("coverage_threshold", DEFAULT_COVERAGE_THRESHOLD),
                    preferred_models=data.get("preferred_models", {}),
                    adjustment_history=data.get("adjustment_history", []),
                    last_adjusted=data.get("last_adjusted", 0.0),
                )
            except (json.JSONDecodeError, OSError, TypeError, KeyError) as e:
                logger.warning("adaptive_config_load_failed error=%s", e)
        return AdaptiveConfig()

    def _save_config(self) -> None:
        """保存自适应配置"""
        self._config_path.write_text(
            json.dumps(
                {
                    "quality_threshold": self._config.quality_threshold,
                    "min_score": self._config.min_score,
                    "max_retries": self._config.max_retries,
                    "coverage_threshold": self._config.coverage_threshold,
                    "preferred_models": self._config.preferred_models,
                    "adjustment_history": self._config.adjustment_history,
                    "last_adjusted": self._config.last_adjusted,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


# 全局单例
_loop: FeedbackLoop | None = None


def get_feedback_loop() -> FeedbackLoop:
    global _loop
    if _loop is None:
        _loop = FeedbackLoop()
    return _loop


__all__ = [
    "FeedbackLoop",
    "FeedbackSignal",
    "AdaptiveConfig",
    "get_feedback_loop",
    "FEEDBACK_DIR",
]
