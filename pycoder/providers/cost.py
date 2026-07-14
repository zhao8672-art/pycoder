from __future__ import annotations

import csv
import io
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

# ====== Cost Tracker ======
"""
Token 用量跟踪与实时计费

功能:
- 记录每次 API 调用的 token 用量
- 按模型/会话/日期汇总费用
- 实时计费显示（TUI 状态栏）
- 费用估算和预算提醒
- 使用记录导出 (JSON/CSV)

全局单例模式: get_cost_tracker() 返回唯一实例
"""


from collections import defaultdict  # noqa: E402

logger = logging.getLogger(__name__)

# ── 模型定价表 ($/M tokens) ──────────────────────────────

MODEL_PRICING = {
    # DeepSeek
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-coder": {"input": 0.41, "output": 0.83},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    # Qwen
    "qwen-coder-plus": {"input": 0.35, "output": 1.20},
    "qwen-coder-turbo": {"input": 0.15, "output": 0.60},
    "qwen-max": {"input": 0.80, "output": 2.00},
    "qwen-plus": {"input": 0.14, "output": 0.40},
    # GLM
    "glm-4": {"input": 0.10, "output": 0.10},
    "glm-4-flash": {"input": 0.10, "output": 0.10},
    "glm-4v-flash": {"input": 0.10, "output": 0.10},
    # OpenAI (参考)
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    # NVIDIA NIM
    "z-ai/glm-5.2": {"input": 2.00, "output": 5.00},
    # Anthropic (参考)
    "claude-sonnet": {"input": 3.00, "output": 15.00},
    "claude-haiku": {"input": 0.25, "output": 1.25},
}


# ── 用量记录 ─────────────────────────────────────────────


class UsageRecord:
    """单次 API 调用用量记录"""

    def __init__(
        self,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        timestamp: float = None,
    ):
        self.model = model
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens or (prompt_tokens + completion_tokens)
        self.timestamp = timestamp or time.time()

    @property
    def cost(self) -> float:
        """计算此次调用费用 ($)"""
        pricing = MODEL_PRICING.get(self.model, {"input": 0.14, "output": 0.28})
        if self.model not in MODEL_PRICING:
            logging.warning(f"[CostTracker] 未知模型 '{self.model}'，使用默认价格 $0.14/$0.28")
        input_cost = (self.prompt_tokens / 1_000_000) * pricing["input"]
        output_cost = (self.completion_tokens / 1_000_000) * pricing["output"]
        return round(input_cost + output_cost, 6)

    @property
    def datetime_str(self) -> str:
        return datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost": self.cost,
            "timestamp": self.timestamp,
            "datetime": self.datetime_str,
        }


# ── 计费跟踪器 ────────────────────────────────────────────


class CostTracker:
    """
    全局计费跟踪器（单例）。

    用法:
        tracker = get_cost_tracker()
        tracker.record("deepseek-chat", {"prompt_tokens": 100, "completion_tokens": 50})
        print(tracker.format_summary())
    """

    def __init__(self):
        self._records: list[UsageRecord] = []
        self._start_time = time.time()
        self._budget_limit: float | None = None
        self._budget_warning_threshold: float = 0.80  # 80% 时警告

    # ── 记录 ──────────────────────────────────────────────

    def record(
        self,
        model: str,
        usage: dict,
        timestamp: float = None,
    ) -> UsageRecord:
        """
        记录一次 API 调用的用量。

        Args:
            model: 模型 ID
            usage: API 返回的 usage 字段 {"prompt_tokens": N, "completion_tokens": M, "total_tokens": T}
            timestamp: 调用时间戳

        Returns:
            创建的 UsageRecord
        """
        record = UsageRecord(
            model=model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            timestamp=timestamp,
        )
        self._records.append(record)

        # 预算检查
        if self._budget_limit:
            total = self.total_cost()
            if total >= self._budget_limit:
                print(f"⚠️ 已达到预算上限 ${self._budget_limit:.2f}")
            elif total >= self._budget_limit * self._budget_warning_threshold:
                remaining = self._budget_limit - total
                print(f"⚡ 预算使用 {total/self._budget_limit*100:.0f}%，剩余 ${remaining:.2f}")

        return record

    def set_budget(self, limit_usd: float, warning_at: float = 0.80):
        """设置费用预算（美元）"""
        self._budget_limit = limit_usd
        self._budget_warning_threshold = warning_at

    # ── 查询 ──────────────────────────────────────────────

    def total_cost(self) -> float:
        """总费用"""
        return round(sum(r.cost for r in self._records), 6)

    def total_tokens(self) -> int:
        """总 token 数"""
        return sum(r.total_tokens for r in self._records)

    def total_calls(self) -> int:
        """总 API 调用次数"""
        return len(self._records)

    def cost_by_model(self) -> dict[str, float]:
        """按模型分组的费用"""
        by_model = defaultdict(float)
        for r in self._records:
            by_model[r.model] += r.cost
        return dict(by_model)

    def cost_today(self) -> float:
        """今日费用"""
        today = datetime.now().date()
        return round(
            sum(
                r.cost for r in self._records if datetime.fromtimestamp(r.timestamp).date() == today
            ),
            6,
        )

    def cost_this_session(self) -> float:
        """本次会话费用"""
        return round(sum(r.cost for r in self._records if r.timestamp >= self._start_time), 6)

    def recent_records(self, n: int = 10) -> list[UsageRecord]:
        """最近 N 条记录"""
        return self._records[-n:]

    # ── 格式化输出 ────────────────────────────────────────

    def format_summary(self) -> str:
        """状态栏一行摘要: 💰 $0.0042 | 1.2K tokens | 3 次"""
        cost = self.cost_this_session()
        tokens = self.total_tokens()
        calls = self.total_calls()

        if tokens > 1_000_000:
            token_str = f"{tokens/1_000_000:.1f}M"
        elif tokens > 1_000:
            token_str = f"{tokens/1_000:.1f}K"
        else:
            token_str = str(tokens)

        return f"${cost:.4f} | {token_str} tokens | {calls} 次"

    def format_report(self) -> str:
        """费用报告（Markdown 格式）"""
        today = self.cost_today()
        total = self.total_cost()
        calls = self.total_calls()
        tokens = self.total_tokens()

        lines = [
            "💰 费用报告",
            "",
            f"本次会话: ${self.cost_this_session():.4f}",
            f"今日累计: ${today:.4f}",
            f"总计:     ${total:.4f}",
            f"API 调用: {calls} 次",
            f"Token:    {tokens:,}",
            "",
        ]

        # 按模型明细
        by_model = self.cost_by_model()
        if by_model:
            lines.append("📊 按模型:")
            for model, cost in sorted(by_model.items(), key=lambda x: -x[1]):
                pct = (cost / total * 100) if total > 0 else 0
                lines.append(f"  {model:<20s} ${cost:.4f} ({pct:.0f}%)")

        # 预算状态
        if self._budget_limit:
            pct = total / self._budget_limit * 100
            status = "🟢" if pct < 50 else ("🟡" if pct < 80 else ("🔴" if pct < 100 else "💀"))
            lines.append(f"\n{status} 预算: ${total:.4f} / ${self._budget_limit:.2f} ({pct:.1f}%)")

        # 最近调用
        recent = self.recent_records(5)
        if recent:
            lines.append("\n🕐 最近 5 次:")
            for r in recent:
                lines.append(
                    f"  {r.datetime_str} {r.model} ${r.cost:.5f} ({r.total_tokens} tokens)"
                )

        return "\n".join(lines)

    def format_json(self) -> str:
        """导出为 JSON"""
        return json.dumps(
            {
                "summary": {
                    "total_cost": self.total_cost(),
                    "total_tokens": self.total_tokens(),
                    "total_calls": self.total_calls(),
                    "session_cost": self.cost_this_session(),
                    "today_cost": self.cost_today(),
                },
                "by_model": self.cost_by_model(),
                "records": [r.to_dict() for r in self._records],
            },
            ensure_ascii=False,
            indent=2,
        )

    # ── 持久化 ────────────────────────────────────────────

    def save(self, path: str | Path = None):
        """保存记录到文件"""
        if path is None:
            path = Path.home() / ".pycoder" / "cost_history.json"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.format_json())

    def load(self, path: str | Path = None):
        """加载历史记录"""
        if path is None:
            path = Path.home() / ".pycoder" / "cost_history.json"
        path = Path(path)
        if not path.exists():
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for r in data.get("records", []):
                self._records.append(
                    UsageRecord(
                        model=r["model"],
                        prompt_tokens=r.get("prompt_tokens", 0),
                        completion_tokens=r.get("completion_tokens", 0),
                        total_tokens=r.get(
                            "total_tokens",
                            r.get("prompt_tokens", 0) + r.get("completion_tokens", 0),
                        ),
                        timestamp=r.get("timestamp", 0),
                    )
                )
        except Exception as e:
            logger.debug("Failed to load cost history: %s", e)

    def reset_session(self):
        """重置本次会话计数"""
        self._start_time = time.time()

    def clear(self):
        """清除所有记录"""
        self._records.clear()
        self._start_time = time.time()


# ── 全局单例 ─────────────────────────────────────────────

_tracker: CostTracker | None = None


def get_cost_tracker() -> CostTracker:
    """获取全局计费跟踪器单例"""
    global _tracker
    if _tracker is None:
        _tracker = CostTracker()
        # 尝试加载历史记录
        _tracker.load()
    return _tracker


def reset_cost_tracker():
    """重置全局计费跟踪器"""
    global _tracker
    if _tracker:
        _tracker.save()
    _tracker = CostTracker()


# ── 费用估算工具 ─────────────────────────────────────────


def estimate_cost(
    model: str,
    prompt_tokens: int = 0,
    expected_output_tokens: int = 0,
) -> dict:
    """
    估算一次调用的费用。

    Args:
        model: 模型 ID
        prompt_tokens: 提示词 token 数
        expected_output_tokens: 预期输出 token 数

    Returns:
        {"model": str, "estimated_cost": float, "breakdown": dict}
    """
    pricing = MODEL_PRICING.get(model, {"input": 0.14, "output": 0.28})
    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (expected_output_tokens / 1_000_000) * pricing["output"]

    return {
        "model": model,
        "estimated_cost": round(input_cost + output_cost, 6),
        "breakdown": {
            "input_tokens": prompt_tokens,
            "input_cost": round(input_cost, 6),
            "output_tokens": expected_output_tokens,
            "output_cost": round(output_cost, 6),
            "price_per_m_input": pricing["input"],
            "price_per_m_output": pricing["output"],
        },
    }


def compare_costs(
    prompt_tokens: int = 4000,
    output_tokens: int = 1000,
    models: list[str] = None,
) -> list[dict]:
    """
    比较多个模型的预估费用。

    Returns:
        按费用升序排列的比较结果
    """
    if models is None:
        models = [
            "deepseek-chat",
            "deepseek-coder",
            "qwen-coder-plus",
            "qwen-coder-turbo",
            "glm-4",
            "glm-4-flash",
            "gpt-4o",
            "gpt-4o-mini",
        ]

    results = []
    for model in models:
        est = estimate_cost(model, prompt_tokens, output_tokens)
        results.append(est)

    return sorted(results, key=lambda x: x["estimated_cost"])


# ====== Billing ======
class TokenEstimator:
    """
    Token 消耗预估器。

    在 AI 回答前预估 token 消耗，帮助用户做出经济决策。
    """

    def __init__(self, cost_tracker: CostTracker = None):
        self.tracker = cost_tracker or get_cost_tracker()
        self._history: list[dict] = []  # 预估历史

    def estimate_call(
        self,
        model: str,
        system_prompt: str = "",
        user_message: str = "",
        conversation_history: list = None,
        expected_output_ratio: float = 0.3,  # 输出/输入比
    ) -> dict:
        """
        预估一次 API 调用的 token 消耗和费用。

        Args:
            model: 模型 ID
            system_prompt: 系统提示
            user_message: 用户消息
            conversation_history: 对话历史
            expected_output_ratio: 预期输出与输入的比率

        Returns:
            预估报告
        """
        # 简单估算：每字符 ~0.25 token
        from pycoder.server.chat_bridge import estimate_tokens

        input_tokens = estimate_tokens(system_prompt) if system_prompt else 0
        input_tokens += estimate_tokens(user_message)
        if conversation_history:
            for msg in conversation_history:
                input_tokens += estimate_tokens(str(msg.get("content", "")))

        output_tokens = int(input_tokens * expected_output_ratio)

        # 计算费用
        pricing = MODEL_PRICING.get(model, {"input": 0.14, "output": 0.28})
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        total_cost = input_cost + output_cost

        result = {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "estimated_cost": round(total_cost, 6),
            "breakdown": {
                "input_cost": round(input_cost, 6),
                "output_cost": round(output_cost, 6),
                "price_per_m_input": pricing["input"],
                "price_per_m_output": pricing["output"],
            },
        }

        self._history.append(result)
        return result

    def compare_models(
        self,
        input_tokens: int = 4000,
        output_tokens: int = 1000,
        models: list[str] = None,
    ) -> list[dict]:
        """比较多个模型的费用"""
        from pycoder.providers.cost import compare_costs

        return compare_costs(input_tokens, output_tokens, models)

    def format_estimate(self, estimate: dict) -> str:
        """格式化预估报告"""
        lines = [
            "💰 Token 预估:",
            f"  模型: {estimate['model']}",
            f"  输入: {estimate['input_tokens']:,} tokens → ${estimate['breakdown']['input_cost']:.6f}",
            f"  输出: {estimate['output_tokens']:,} tokens → ${estimate['breakdown']['output_cost']:.6f}",
            f"  总计: {estimate['total_tokens']:,} tokens → ${estimate['estimated_cost']:.6f}",
        ]
        return "\n".join(lines)

    def should_warn(self, estimate: dict, budget_limit: float = None) -> tuple[bool, str]:
        """检查是否应该发出费用警告"""
        if not budget_limit:
            return False, ""

        total_spent = self.tracker.total_cost()
        after_call = total_spent + estimate["estimated_cost"]

        if after_call >= budget_limit:
            return True, f"⚠️ 此次调用后总费用 ${after_call:.4f} 将达到预算上限 ${budget_limit:.2f}"
        if after_call >= budget_limit * 0.80:
            return True, f"⚡ 此次调用后费用将使用预算的 {after_call/budget_limit*100:.0f}%"

        return False, ""


class BudgetManager:
    """
    预算管理器 — 支持月预算、日预算和告警。
    """

    def __init__(self, cost_tracker: CostTracker = None):
        self.tracker = cost_tracker or get_cost_tracker()
        self._monthly_budget: float = 0.0
        self._daily_budget: float = 0.0
        self._warn_threshold: float = 0.80
        self._alert_threshold: float = 0.95
        self._callbacks: list[callable] = []

    def set_monthly_budget(self, usd: float):
        """设置月预算"""
        self._monthly_budget = usd
        self.tracker.set_budget(usd, self._warn_threshold)

    def set_daily_budget(self, usd: float):
        """设置日预算"""
        self._daily_budget = usd

    @property
    def monthly_budget(self) -> float:
        return self._monthly_budget

    @property
    def daily_budget(self) -> float:
        return self._daily_budget

    def check_budget(self) -> dict:
        """
        检查预算状态。

        Returns:
            {
                "monthly_used": float,
                "monthly_remaining": float,
                "monthly_pct": float,
                "daily_used": float,
                "status": "ok" | "warning" | "critical" | "exceeded",
                "message": str,
            }
        """
        monthly_used = self.tracker.total_cost()
        today_used = self.tracker.cost_today()

        result = {
            "monthly_used": monthly_used,
            "monthly_remaining": (
                max(0, self._monthly_budget - monthly_used) if self._monthly_budget else 0
            ),
            "monthly_pct": (
                (monthly_used / self._monthly_budget * 100) if self._monthly_budget else 0
            ),
            "daily_used": today_used,
            "status": "ok",
            "message": "",
        }

        # 检查日预算
        if self._daily_budget and today_used >= self._daily_budget:
            result["status"] = "exceeded"
            result["message"] = f"🔴 今日预算已用完: ${today_used:.4f} / ${self._daily_budget:.2f}"
            return result
        elif self._daily_budget and today_used >= self._daily_budget * self._alert_threshold:
            result["status"] = "critical"
            result["message"] = (
                f"⚠️ 今日预算即将用完: ${today_used:.4f} / ${self._daily_budget:.2f}"
            )
            return result

        # 检查月预算
        if self._monthly_budget:
            if monthly_used >= self._monthly_budget:
                result["status"] = "exceeded"
                result["message"] = (
                    f"🔴 月预算已用完: ${monthly_used:.4f} / ${self._monthly_budget:.2f}"
                )
            elif monthly_used >= self._monthly_budget * self._alert_threshold:
                result["status"] = "critical"
                result["message"] = (
                    f"⚠️ 月预算即将用完: ${monthly_used:.4f} / ${self._monthly_budget:.2f} ({result['monthly_pct']:.0f}%)"
                )
            elif monthly_used >= self._monthly_budget * self._warn_threshold:
                result["status"] = "warning"
                result["message"] = (
                    f"⚡ 月预算使用 {result['monthly_pct']:.0f}%，剩余 ${result['monthly_remaining']:.2f}"
                )

        return result

    def format_status(self) -> str:
        """格式化预算状态为可显示文本"""
        check = self.check_budget()
        icons = {"ok": "🟢", "warning": "🟡", "critical": "🟠", "exceeded": "🔴"}
        icon = icons.get(check["status"], "⚪")

        lines = [f"{icon} 预算状态"]
        if self._monthly_budget:
            lines.append(
                f"  月预算: ${check['monthly_used']:.4f} / ${self._monthly_budget:.2f} ({check['monthly_pct']:.0f}%)"
            )
        if self._daily_budget:
            lines.append(f"  今日: ${check['daily_used']:.4f} / ${self._daily_budget:.2f}")
        if check["message"]:
            lines.append(f"  {check['message']}")
        return "\n".join(lines)


class UsageCharts:
    """
    用量图表生成器 — 生成费用趋势数据。

    用于 TUI 中的图表展示。
    """

    def __init__(self, cost_tracker: CostTracker = None):
        self.tracker = cost_tracker or get_cost_tracker()

    def daily_costs(self, days: int = 7) -> dict:
        """获取最近 N 天的每日费用趋势"""
        now = datetime.now()
        daily = defaultdict(float)

        for record in self.tracker._records:
            record_date = datetime.fromtimestamp(record.timestamp).date()
            if (now.date() - record_date).days <= days:
                daily[record_date.isoformat()] += record.cost

        # 填充缺失日期
        result = {}
        for i in range(days - 1, -1, -1):
            d = (now - timedelta(days=i)).date().isoformat()
            result[d] = round(daily.get(d, 0), 6)

        return result

    def model_usage(self) -> dict[str, dict]:
        """按模型统计用量"""
        model_stats = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "calls": 0})

        for record in self.tracker._records:
            stats = model_stats[record.model]
            stats["tokens"] += record.total_tokens
            stats["cost"] += record.cost
            stats["calls"] += 1

        return dict(model_stats)

    def hourly_heatmap(self, days: int = 7) -> dict:
        """生成 24h × 7day 热量图数据"""
        now = datetime.now()
        heatmap = defaultdict(lambda: defaultdict(float))

        for record in self.tracker._records:
            dt = datetime.fromtimestamp(record.timestamp)
            if (now.date() - dt.date()).days <= days:
                day = dt.date().isoformat()
                hour = dt.hour
                heatmap[day][str(hour)] += record.cost

        return dict(heatmap)

    def format_trend(self, days: int = 7) -> str:
        """格式化为终端文本趋势图"""
        daily = self.daily_costs(days)
        if not daily:
            return "暂无数据"

        max_cost = max(daily.values()) if daily.values() else 0.0001

        lines = ["📈 费用趋势 (最近 7 天):", ""]
        for date, cost in daily.items():
            bar_len = int(cost / max_cost * 30) if max_cost > 0 else 0
            bar = "█" * bar_len
            lines.append(f"  {date[-5:]} {bar} ${cost:.4f}")

        return "\n".join(lines)


class ReportExporter:
    """
    费用报告导出器。
    """

    def __init__(self, cost_tracker: CostTracker = None):
        self.tracker = cost_tracker or get_cost_tracker()

    def export_json(self) -> str:
        """导出为 JSON 格式"""
        return self.tracker.format_json()

    def export_csv(self) -> str:
        """导出为 CSV 格式"""
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(
            ["datetime", "model", "prompt_tokens", "completion_tokens", "total_tokens", "cost"]
        )
        for record in self.tracker._records:
            writer.writerow(
                [
                    record.datetime_str,
                    record.model,
                    record.prompt_tokens,
                    record.completion_tokens,
                    record.total_tokens,
                    f"${record.cost:.6f}",
                ]
            )

        return output.getvalue()

    def export_markdown(self) -> str:
        """导出为 Markdown 格式"""
        lines = [
            "# PyCoder 费用报告",
            "",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 摘要",
            "",
            "| 指标 | 值 |",
            "|------|-----|",
            f"| 总费用 | ${self.tracker.total_cost():.4f} |",
            f"| 总 Token | {self.tracker.total_tokens():,} |",
            f"| 总调用 | {self.tracker.total_calls()} |",
            f"| 本次会话 | ${self.tracker.cost_this_session():.4f} |",
            f"| 今日 | ${self.tracker.cost_today():.4f} |",
            "",
            "## 按模型",
            "",
            "| 模型 | 费用 | 占比 |",
            "|------|------|------|",
        ]

        total = self.tracker.total_cost()
        for model, cost in sorted(self.tracker.cost_by_model().items(), key=lambda x: -x[1]):
            pct = (cost / total * 100) if total > 0 else 0
            lines.append(f"| {model} | ${cost:.4f} | {pct:.0f}% |")

        lines.append("")
        lines.append("## 最近 20 次调用")
        lines.append("")
        lines.append("| 时间 | 模型 | Token | 费用 |")
        lines.append("|------|------|-------|------|")

        for record in self.tracker._records[-20:]:
            lines.append(
                f"| {record.datetime_str} | {record.model} | "
                f"{record.total_tokens:,} | ${record.cost:.6f} |"
            )

        return "\n".join(lines)

    def save_report(self, format: str = "json", path: str = None):
        """保存报告到文件"""
        if format == "json":
            content = self.export_json()
            ext = ".json"
        elif format == "csv":
            content = self.export_csv()
            ext = ".csv"
        elif format == "md":
            content = self.export_markdown()
            ext = ".md"
        else:
            raise ValueError(f"不支持的格式: {format}")

        if path is None:
            path = f"pycoder_cost_report_{datetime.now().strftime('%Y%m%d')}{ext}"

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        return path


# ── 全局单例增强 ─────────────────────────────────────────

_budget_manager: BudgetManager | None = None
_token_estimator: TokenEstimator | None = None


def get_budget_manager() -> BudgetManager:
    global _budget_manager
    if _budget_manager is None:
        _budget_manager = BudgetManager()
    return _budget_manager


def get_token_estimator() -> TokenEstimator:
    global _token_estimator
    if _token_estimator is None:
        _token_estimator = TokenEstimator()
    return _token_estimator
