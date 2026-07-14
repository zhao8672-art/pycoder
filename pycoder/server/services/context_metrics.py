"""
ContextMetrics — 上下文保持效果评估模块

职责：
    1. 量化上下文连续性得分
    2. 追踪上下文引用命中/未命中
    3. 收集用户反馈并持续优化策略

指标说明：
    - continuity_score: 0-100 上下文连续性评分（越高越好）
    - anchor_hit_rate: 引用历史决策的成功率
    - drift_rate: 任务偏离率（越低越好）
    - context_relevance: 上下文与当前问题的相关性

用法:
    metrics = ContextMetrics()
    metrics.record_anchor_hit()     # 每轮上下文引用成功
    metrics.record_anchor_miss()    # 引用失败
    metrics.record_drift_check(report)  # 偏离检测结果
    metrics.get_report()            # 获取评估报告
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class MetricsSnapshot:
    """指标快照"""
    continuity_score: int = 0        # 0-100
    anchor_hit_rate: float = 0.0     # 0-1
    drift_rate: float = 0.0          # 0-1
    context_relevance: float = 0.0   # 0-1
    total_anchors: int = 0
    total_anchors_hit: int = 0
    total_drift_checks: int = 0
    total_drift_detected: int = 0
    avg_response_time_ms: int = 0
    session_duration_s: int = 0
    notes: list[str] = field(default_factory=list)


class ContextMetrics:
    """上下文保持效果评估器"""

    def __init__(self):
        self._anchor_hits: int = 0
        self._anchor_misses: int = 0
        self._drift_checks: int = 0
        self._drift_detected: int = 0
        self._context_injections: int = 0
        self._response_times: list[int] = []
        self._session_start: float = 0.0
        self._notes: list[str] = []
        self._user_feedback: list[dict] = []  # {type, rating, comment, timestamp}
        self._ab_experiments: dict[str, dict] = {}  # experiment_id → metrics

    def start_session(self) -> None:
        self._session_start = time.monotonic()

    # ══════════════════════════════════════════════════════
    # 锚点命中追踪
    # ══════════════════════════════════════════════════════

    def record_anchor_hit(self) -> None:
        """上下文锚点引用成功（LLM 正确引用了历史决策）"""
        self._anchor_hits += 1

    def record_anchor_miss(self) -> None:
        """上下文锚点引用失败（LLM 忽略了或重复了已有决策）"""
        self._anchor_misses += 1

    # ══════════════════════════════════════════════════════

    def record_drift_check(self, is_drifting: bool) -> None:
        self._drift_checks += 1
        if is_drifting:
            self._drift_detected += 1

    def record_context_injection(self) -> None:
        self._context_injections += 1

    def record_response_time(self, ms: int) -> None:
        self._response_times.append(ms)

    def add_note(self, note: str) -> None:
        self._notes.append(f"[{time.strftime('%H:%M:%S')}] {note[:200]}")

    # ══════════════════════════════════════════════════════
    # 用户反馈
    # ══════════════════════════════════════════════════════

    def collect_feedback(self, feedback_type: str, rating: int, comment: str = "") -> None:
        """收集用户反馈

        Args:
            feedback_type: "context_relevance" / "task_tracking" / "drift_accuracy"
            rating: 1-5 评分
            comment: 自由文本意见
        """
        self._user_feedback.append({
            "type": feedback_type,
            "rating": rating,
            "comment": comment,
            "timestamp": time.time(),
        })

    # ══════════════════════════════════════════════════════
    # A/B 测试
    # ══════════════════════════════════════════════════════

    def start_experiment(self, experiment_id: str, variant: str) -> None:
        self._ab_experiments[experiment_id] = {
            "variant": variant,
            "started_at": time.time(),
            "anchors_hit": 0,
            "anchors_miss": 0,
        }

    def record_experiment_hit(self, experiment_id: str) -> None:
        if experiment_id in self._ab_experiments:
            self._ab_experiments[experiment_id]["anchors_hit"] += 1

    def get_experiment_result(self, experiment_id: str) -> dict:
        exp = self._ab_experiments.get(experiment_id, {})
        total = exp.get("anchors_hit", 0) + exp.get("anchors_miss", 0)
        return {
            "variant": exp.get("variant", "unknown"),
            "hit_rate": exp.get("anchors_hit", 0) / max(total, 1),
        }

    # ══════════════════════════════════════════════════════
    # 综合评估报告
    # ══════════════════════════════════════════════════════

    def get_snapshot(self) -> MetricsSnapshot:
        """获取当前指标快照"""
        total_anchors = self._anchor_hits + self._anchor_misses
        snapshot = MetricsSnapshot(
            total_anchors=total_anchors,
            total_anchors_hit=self._anchor_hits,
            anchor_hit_rate=(
                self._anchor_hits / max(total_anchors, 1)
            ),
            total_drift_checks=self._drift_checks,
            total_drift_detected=self._drift_detected,
            drift_rate=(
                self._drift_detected / max(self._drift_checks, 1)
            ),
            context_relevance=self._calc_relevance(),
            avg_response_time_ms=(
                int(sum(self._response_times) / max(len(self._response_times), 1))
                if self._response_times else 0
            ),
            session_duration_s=(
                int(time.monotonic() - self._session_start)
                if self._session_start > 0 else 0
            ),
            continuity_score=self._calc_continuity(),
            notes=list(self._notes[-5:]),
        )
        return snapshot

    def _calc_relevance(self) -> float:
        """计算上下文相关性（基于注入次数与总轮次的比例）"""
        if self._context_injections == 0:
            return 0.5  # 无数据
        return min(self._context_injections / max(self._anchor_hits + self._anchor_misses, 1), 1.0)

    def _calc_continuity(self) -> int:
        """综合计算连续性评分 0-100（直接使用 self 字段，避免递归）"""
        total_anchors = self._anchor_hits + self._anchor_misses
        anchor_hit_rate = self._anchor_hits / max(total_anchors, 1)
        drift_rate = self._drift_detected / max(self._drift_checks, 1)
        relevance = (
            self._context_injections / max(total_anchors, 1)
            if self._context_injections > 0 else 0.5
        )

        # 锚点命中率贡献 40%
        anchor_score = anchor_hit_rate * 40
        # 偏离率贡献 30%（反向）
        drift_score = max(0, (1.0 - drift_rate) * 30)
        # 上下文相关性贡献 20%
        relevance_score = min(relevance, 1.0) * 20
        # 用户反馈贡献 10%
        feedback_avg = 3.0  # 默认中等
        if self._user_feedback:
            feedback_avg = sum(f["rating"] for f in self._user_feedback) / len(self._user_feedback)
        feedback_score = (feedback_avg / 5.0) * 10

        return min(int(anchor_score + drift_score + relevance_score + feedback_score), 100)

    def get_report(self) -> str:
        """生成人类可读的评估报告"""
        s = self.get_snapshot()
        lines = [
            "## 📊 上下文保持效果评估",
            "| 指标 | 值 |",
            "|------|-----|",
            f"| 连续性评分 | {s.continuity_score}/100 |",
            f"| 锚点命中率 | {s.anchor_hit_rate:.0%} ({s.total_anchors_hit}/{s.total_anchors}) |",
            f"| 偏离率 | {s.drift_rate:.0%} ({s.total_drift_detected}/{s.total_drift_checks}) |",
            f"| 上下文相关性 | {s.context_relevance:.0%} |",
            f"| 平均响应时间 | {s.avg_response_time_ms}ms |",
            f"| 会话持续时间 | {s.session_duration_s}s |",
        ]
        if s.notes:
            lines.append("\n### 备注")
            for n in s.notes:
                lines.append(f"- {n}")
        return "\n".join(lines)
