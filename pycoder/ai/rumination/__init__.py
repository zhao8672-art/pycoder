"""
RuminationEngine — 对标 Codex 工程推理 / 智谱沉思式 Rumination 的独立反思引擎

五步反思管线:
  pre_execute()   → 工具调用前评估风险、预判结果
  mid_execute()   → 每轮工具后对比预期 vs 实际
  post_execute()  → 最终回复前全局一致性检查
  backtrack()     → 检测严重偏离时回溯关键节点
  score()         → 给每轮反思打分，评估 Agent 质量

用法:
    from pycoder.ai.rumination import RuminationEngine
    re = RuminationEngine()
    result = await re.mid_execute(tool="read_file", expected="内容", actual="...", round=1)
    if result.deviation_score > 0.5:
        messages.append({"role": "system", "content": result.correction_msg})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuminationResult:
    """单次反思结果"""
    round_num: int = 0
    tool_name: str = ""
    deviation_score: float = 0.0  # 0=完全一致, 1=严重偏离
    correction_msg: str = ""
    should_continue: bool = True
    risk_level: str = "low"  # low/medium/high
    recommendations: list[str] = field(default_factory=list)


class RuminationEngine:
    """独立反思引擎 — 可追踪、可评分、可干预"""

    def __init__(self):
        self._history: list[RuminationResult] = []
        self._total_score: float = 0.0
        self._round_count: int = 0

    async def pre_execute(self, tool_name: str, params: dict) -> RuminationResult:
        """事前推演：评估工具调用风险"""
        result = RuminationResult(tool_name=tool_name, round_num=self._round_count)

        # 危险操作检测
        dangerous_tools = {
            "shell_exec", "run_command", "write_file", "delete_file",
            "git_push", "git_commit", "install_package",
        }
        if tool_name in dangerous_tools:
            result.risk_level = "medium"
            result.recommendations.append(
                f"⚠️ 危险操作 {tool_name}，请确认参数正确"
            )
            if "rm" in str(params) or "delete" in str(params).lower():
                result.risk_level = "high"
                result.recommendations.append(
                    "🔴 检测到删除操作，请再次确认这是预期行为"
                )

        self._history.append(result)
        return result

    async def mid_execute(
        self,
        tool_name: str,
        expected: str = "",
        actual: str = "",
        round_num: int = 0,
    ) -> RuminationResult:
        """事中反思：对比预期 vs 实际"""
        result = RuminationResult(
            round_num=round_num,
            tool_name=tool_name,
        )
        self._round_count = round_num

        # 检测空结果
        if not actual or actual.strip() in ("", "{}", "[]", "null"):
            result.deviation_score = 0.6
            result.correction_msg = (
                f"🔍 反思: {tool_name} 返回空结果。请检查：\n"
                "1. 工具参数是否正确？\n"
                "2. 目标资源是否存在？\n"
                "3. 是否需要切换工具？"
            )
            result.recommendations.append("工具返回空结果，可能需要切换策略")

        # 检测错误结果
        error_keywords = ("error", "Error", "失败", "denied", "refused", "timeout", "not found")
        if any(kw in actual[:500] for kw in error_keywords):
            result.deviation_score = 0.7
            result.correction_msg = (
                f"🔍 反思: {tool_name} 返回错误。请：\n"
                "1. 分析错误原因\n"
                "2. 尝试修正后重试（最多3次）\n"
                "3. 如无法修复，告知用户并建议替代方案"
            )
            result.recommendations.append("检测到错误，需要修正后重试")

        # 检测偏离：如果预期和实际差距很大
        if expected and actual and len(expected) > 20 and len(actual) > 20:
            # 简单的长度差异检测
            len_ratio = abs(len(actual) - len(expected)) / max(len(expected), 1)
            if len_ratio > 5:  # 5倍以上差异
                result.deviation_score = 0.4
                result.recommendations.append(
                    f"结果长度与预期差异 {len_ratio:.0f}x，请核实"
                )

        self._history.append(result)
        return result

    async def post_execute(self, final_content: str) -> RuminationResult:
        """事后纠偏：最终回复前全局一致性检查"""
        result = RuminationResult(round_num=self._round_count)

        checks = []

        # 检查1：是否包含工具调用痕迹
        if "🔧" in final_content and "📋" not in final_content:
            checks.append("工具执行后缺少结果展示")
            result.deviation_score += 0.1

        # 检查2：是否有未完成的 JSON
        if final_content.count("{") != final_content.count("}"):
            checks.append("JSON 括号不匹配，可能存在未完成的工具调用")
            result.deviation_score += 0.15

        # 检查3：是否过于简短（<50字符且有工具调用）
        if len(final_content) < 50 and "🔧" in final_content:
            checks.append("回复过于简短，可能工具执行未完成")
            result.deviation_score += 0.2

        # 检查4：反思质量评估
        if self._round_count > 3 and self._total_score < 0.2:
            checks.append("多轮反思评分偏低，Agent 可能陷入循环")
            result.deviation_score += 0.3

        if checks:
            result.correction_msg = (
                "🔍 最终检查发现问题：\n" +
                "\n".join(f"  - {c}" for c in checks) +
                "\n请修正后再输出最终回复。"
            )

        self._history.append(result)
        return result

    async def backtrack(self) -> RuminationResult:
        """检测到严重偏离时建议回溯到哪个关键节点"""
        result = RuminationResult(round_num=self._round_count)

        if not self._history:
            return result

        # 找最后一个 deviation_score < 0.3 的步骤
        safe_points = [
            (i, h) for i, h in enumerate(self._history) if h.deviation_score < 0.3
        ]
        if safe_points:
            last_safe = safe_points[-1]
            result.should_continue = False
            result.correction_msg = (
                f"🔍 回溯建议: 回到第 {last_safe[0] + 1} 步 "
                f"({last_safe[1].tool_name}) 重新开始。\n"
                "从该步骤起的所有操作可能需要回滚。"
            )

        return result

    def score(self) -> dict:
        """反思质量评分"""
        if not self._history:
            return {"total": 0, "avg_deviation": 0, "rounds": 0, "status": "no_data"}

        avg_deviation = sum(h.deviation_score for h in self._history) / len(
            self._history
        )
        self._total_score = max(0, 1 - avg_deviation)

        status = "excellent" if self._total_score > 0.8 else (
            "good" if self._total_score > 0.6 else (
                "fair" if self._total_score > 0.4 else "poor"
            )
        )

        return {
            "total": round(self._total_score, 2),
            "avg_deviation": round(avg_deviation, 2),
            "rounds": len(self._history),
            "status": status,
            "high_risk_count": sum(
                1 for h in self._history if h.risk_level == "high"
            ),
        }

    def reset(self):
        """重置引擎状态"""
        self._history.clear()
        self._total_score = 0.0
        self._round_count = 0


# 全局单例
_instance: RuminationEngine | None = None


def get_rumination_engine() -> RuminationEngine:
    global _instance
    if _instance is None:
        _instance = RuminationEngine()
    return _instance
