"""P1-1: 审查与质量守卫 — QA 代码审查与修复循环

从 team_orchestrator.py 抽取的职责：
- review_code 函数（调用 LLM 审查代码）
- 阶段 3 的 review loop（最多 3 轮：审查 → 修复 → 再审查）
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pycoder.server.chat_bridge import ChatBridge  # noqa: F401

from pycoder.server.log import log


@dataclass
class ReviewResult:
    """单次代码审查结果"""

    task_id: str
    passed: bool
    score: int
    issues: list[dict] = field(default_factory=list)
    summary: str = ""


# 修复执行器：接受 task_id 与 review feedback，返回修复后的代码
FixExecutor = Callable[[str, str], Awaitable[str]]


REVIEW_SYSTEM_PROMPT = """你是 PyCoder 代码审查 Agent。

请审查以下代码，输出 JSON 格式的审查结果:
{{"passed":true,"issues":[{{"severity":"high","description":"问题描述","suggestion":"修复建议"}}],"score":85,"summary":"审查总结"}}

评分规则: 满分100，high扣15分/个，medium扣8分/个，low扣3分/个
"""


class ReviewOrchestrator:
    """审查循环编排 — 多轮审查 + 修复，直到通过或达到上限"""

    # 自适应审查轮次配置
    MIN_ROUNDS = 2  # 简单代码至少 2 轮（审查 + 确认）
    MAX_ROUNDS = 6  # 复杂代码最多 6 轮
    # 代码复杂度阈值（行数）
    COMPLEXITY_LOW = 200  # <200 行：简单
    COMPLEXITY_HIGH = 1000  # >1000 行：复杂

    def estimate_review_rounds(self, results: dict[str, str]) -> int:
        """根据代码复杂度估算审查轮次

        因素:
        - 代码总行数（越长越复杂）
        - 文件数量（越多越复杂）
        - 默认 3 轮，简单 2 轮，复杂 4-6 轮
        """
        total_lines = sum(code.count("\n") + 1 for code in results.values())
        file_count = len(results)

        # 基础轮次：按总行数
        if total_lines < self.COMPLEXITY_LOW:
            rounds = self.MIN_ROUNDS
        elif total_lines > self.COMPLEXITY_HIGH:
            rounds = 5
        elif total_lines > self.COMPLEXITY_HIGH * 2:
            rounds = self.MAX_ROUNDS
        else:
            rounds = 3

        # 多文件加成（每 3 个文件 +1 轮，上限 MAX_ROUNDS）
        if file_count > 1:
            rounds += min(2, file_count // 3)

        return min(self.MAX_ROUNDS, max(self.MIN_ROUNDS, rounds))

    async def review_code(
        self,
        bridge: ChatBridge,
        code: str,
        task_id: str = "",
    ) -> ReviewResult:
        """QA Agent 审查代码 — 异常返回有意义的失败结果

        Args:
            bridge: 已配置 model 的 ChatBridge 实例
            code: 待审查的代码字符串
            task_id: 关联的任务 ID（用于结果追踪）

        Returns:
            ReviewResult — 始终返回有效结果，不抛异常
        """
        bridge.configure(model="deepseek-chat")
        bridge.config.system_prompt = REVIEW_SYSTEM_PROMPT
        bridge.config.max_tokens = 4096

        result = ""
        async for event in bridge.chat_stream(f"请审查以下代码:\n\n```\n{code[:8000]}\n```"):
            if event.event_type == "token":
                result += event.content

        try:
            cleaned = result.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
                cleaned = cleaned.rsplit("```", 1)[0]
            parsed = json.loads(cleaned)
            return ReviewResult(
                task_id=task_id,
                passed=bool(parsed.get("passed", False)),
                score=int(parsed.get("score", 0)),
                issues=parsed.get("issues", []),
                summary=parsed.get("summary", ""),
            )
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            # 解析失败 — 返回有意义的失败结果，不静默通过
            log.warning("review_parse_failed", task_id=task_id, error=str(e))
            return ReviewResult(
                task_id=task_id,
                passed=False,
                score=0,
                issues=[
                    {
                        "severity": "high",
                        "description": f"审查解析失败: {str(e)[:100]}",
                        "suggestion": "请检查 LLM 输出格式",
                    }
                ],
                summary=f"审查异常: {e}",
            )

    async def run_review_loop(
        self,
        bridge: ChatBridge,
        results: dict[str, str],
        fix_executor: FixExecutor,
        max_rounds: int | None = None,
    ) -> tuple[list[dict], int]:
        """运行审查 + 修复循环

        Args:
            bridge: 已配置的 ChatBridge 实例
            results: task_id → code 的映射（会被原地更新）
            fix_executor: 修复函数（task_id, feedback）→ 新代码
            max_rounds: 最大审查轮次；None 时根据代码复杂度自适应

        Returns:
            (all_issues, rounds_used) — 所有累积的问题与实际使用的轮次
        """
        # 自适应轮次：max_rounds=None 时根据代码复杂度估算
        if max_rounds is None:
            max_rounds = self.estimate_review_rounds(results)
            log.info("review_rounds_adaptive", max_rounds=max_rounds, files=len(results))

        all_issues: list[dict] = []
        round_num = 0

        while round_num < max_rounds:
            round_num += 1
            round_issues: list[dict] = []
            need_fix = False

            for task_id, code in results.items():
                review = await self.review_code(bridge, code, task_id)
                for issue in review.issues:
                    issue["task_id"] = task_id
                round_issues.extend(review.issues)
                if not review.passed or review.score < 60:
                    need_fix = True

            all_issues.extend(round_issues)

            if not need_fix:
                break

            # 修复有问题的代码
            feedback = self._build_feedback(round_issues, round_num)
            for task_id in {i["task_id"] for i in round_issues}:
                if task_id in results:
                    fixed = await fix_executor(task_id, feedback)
                    if fixed:
                        results[task_id] = fixed

        return all_issues, round_num

    async def run_review_until_pass(
        self,
        bridge: ChatBridge,
        results: dict[str, str],
        fix_executor: FixExecutor,
        max_rounds: int | None = None,
    ) -> tuple[list[dict], int, bool]:
        """运行审查+修复循环，并返回最终是否通过

        在 ``run_review_loop`` 之上额外返回 ``final_passed``：
        - 循环因 `need_fix=False` 提前 break（轮次 < 上限）→ 通过
        - 循环跑满上限仍有问题 → 未通过

        Returns:
            (all_issues, rounds_used, final_passed)
        """
        if max_rounds is None:
            max_rounds = self.estimate_review_rounds(results)
        all_issues, rounds_used = await self.run_review_loop(
            bridge,
            results,
            fix_executor,
            max_rounds,
        )
        final_passed = rounds_used < max_rounds
        return all_issues, rounds_used, final_passed

    def _build_feedback(self, issues: list[dict], round_num: int) -> str:
        """构建审查反馈字符串"""
        feedback = f"\n## QA 审查反馈 — 第 {round_num} 轮\n\n"
        for iss in issues:
            feedback += (
                f"- [{iss.get('severity', '?')}] "
                f"{iss.get('description', '')}\n"
                f"  建议: {iss.get('suggestion', '')}\n"
            )
        return feedback


# ── 向后兼容入口（已废弃）──────────────────────────────────
# 注意：必须放在 ReviewOrchestrator 类定义之后，
# 因为函数体内引用了该类。


async def review_code(bridge: ChatBridge, code: str, task_id: str = "") -> ReviewResult:
    """QA Agent 审查代码 — 异常返回有意义的失败结果

    .. deprecated:: P1-1
        请改用 ``ReviewOrchestrator().review_code(...)`` 实例方法。
        本模块级函数保留作为向后兼容入口。
    """
    return await ReviewOrchestrator().review_code(bridge, code, task_id)
