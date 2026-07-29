"""偏差检测器 — 执行过程中实时检测计划偏离（补充方案2）

三类偏差检测:
1. 跳步: 执行了依赖未满足的任务
2. 重复: 已完成任务被再次执行
3. 遗漏: 连续多轮未推进计划

动态调整:
- 子任务失败2次 → 触发 replan
- 偏差累计过多 → 注入纠正 prompt
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pycoder.brain.task_planner import (
    ExecutionPlan,
    Task,
    TaskStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class Deviation:
    """单次偏差记录"""

    kind: str  # skip / repeat / stall / dependency_violation
    task_id: str = ""
    description: str = ""
    correction: str = ""  # 纠正建议


@dataclass
class DeviationReport:
    """偏差检测报告"""

    deviations: list[Deviation] = field(default_factory=list)
    completed_task_ids: set[str] = field(default_factory=set)
    current_task_id: str = ""
    stall_rounds: int = 0  # 连续未推进轮次
    total_replans: int = 0

    @property
    def has_critical(self) -> bool:
        """是否有严重偏差"""
        return any(d.kind in ("skip", "dependency_violation") for d in self.deviations)

    @property
    def needs_replan(self) -> bool:
        """是否需要重规划"""
        return self.total_replans < 2 and any(
            d.kind == "repeat" and "失败" in d.description for d in self.deviations
        )

    def correction_prompt(self) -> str:
        """生成纠正 prompt"""
        if not self.deviations:
            return ""
        lines = ["⚠️ 检测到执行偏差，请调整:"]
        for d in self.deviations:
            lines.append(f"  - {d.description}")
            if d.correction:
                lines.append(f"    → {d.correction}")
        return "\n".join(lines)


class DeviationDetector:
    """偏差检测器 — 每轮迭代后调用，检测计划偏离"""

    def __init__(self, plan: ExecutionPlan) -> None:
        self._plan = plan
        self._report = DeviationReport()
        # 工具调用 → 任务ID 的映射（启发式）
        self._tool_task_map = self._build_tool_task_map()
        # 每个任务的失败计数
        self._fail_counts: dict[str, int] = {}
        # 上一轮的已完成数量
        self._last_completed_count = 0

    def _build_tool_task_map(self) -> dict[str, str]:
        """构建工具名称→任务ID的映射（启发式匹配）"""
        mapping: dict[str, str] = {}
        for task in self._plan.tasks:
            # 用任务描述的关键词作为映射键
            keywords = self._extract_keywords(task.description)
            for kw in keywords:
                mapping[kw] = task.task_id
        return mapping

    @staticmethod
    def _extract_keywords(desc: str) -> list[str]:
        """从任务描述提取关键词"""
        # 简单分词：取长度>2的词
        words = desc.replace("/", " ").replace(".", " ").split()
        return [w.lower() for w in words if len(w) > 2]

    def detect(
        self,
        tool_calls: list[dict[str, Any]],
        tool_results: list[dict[str, Any]],
    ) -> DeviationReport:
        """每轮迭代后检测偏差

        Args:
            tool_calls: 本轮工具调用列表 [{name, params, ...}]
            tool_results: 本轮工具执行结果 [{success, output, ...}]

        Returns:
            DeviationReport 偏差报告
        """
        self._report.deviations.clear()
        len(self._report.completed_task_ids)

        # 分析本轮工具调用对应的任务
        touched_task_ids: set[str] = set()
        for tc in tool_calls:
            task_id = self._match_tool_to_task(tc)
            if task_id:
                touched_task_ids.add(task_id)

        # 检测偏差
        for task_id in touched_task_ids:
            task = self._find_task(task_id)
            if task is None:
                continue

            # 重复检测
            if task_id in self._report.completed_task_ids:
                self._report.deviations.append(
                    Deviation(
                        kind="repeat",
                        task_id=task_id,
                        description=f"任务 {task_id}（{task.description[:30]}）已完成但被重复执行",
                        correction="跳过此任务，执行下一个未完成的任务",
                    )
                )
                continue

            # 依赖违规检测
            unmet_deps = [
                dep for dep in task.dependencies if dep not in self._report.completed_task_ids
            ]
            if unmet_deps:
                self._report.deviations.append(
                    Deviation(
                        kind="dependency_violation",
                        task_id=task_id,
                        description=(f"任务 {task_id} 依赖未完成的任务: {', '.join(unmet_deps)}"),
                        correction=f"先完成依赖任务: {', '.join(unmet_deps)}",
                    )
                )

        # 标记完成的任务
        for task_id in touched_task_ids:
            self._mark_completed(task_id)

        # 检测执行失败
        for i, result in enumerate(tool_results):
            if not result.get("success", True):
                if i < len(tool_calls):
                    task_id = self._match_tool_to_task(tool_calls[i])
                    if task_id:
                        self._fail_counts[task_id] = self._fail_counts.get(task_id, 0) + 1
                        if self._fail_counts[task_id] >= 2:
                            self._report.deviations.append(
                                Deviation(
                                    kind="repeat",
                                    task_id=task_id,
                                    description=(
                                        f"任务 {task_id} 已失败 " f"{self._fail_counts[task_id]} 次"
                                    ),
                                    correction="触发重规划，调整剩余任务",
                                )
                            )
                            self._report.total_replans += 1

        # 遗漏检测（连续未推进）
        current_completed = len(self._report.completed_task_ids)
        if current_completed == self._last_completed_count and tool_calls:
            self._report.stall_rounds += 1
            if self._report.stall_rounds >= 2:
                next_task = self._get_next_pending_task()
                if next_task:
                    self._report.deviations.append(
                        Deviation(
                            kind="stall",
                            task_id=next_task.task_id,
                            description=(f"连续 {self._report.stall_rounds} 轮未推进计划"),
                            correction=(
                                f"下一步应执行: {next_task.task_id} - "
                                f"{next_task.description[:40]}"
                            ),
                        )
                    )
        else:
            self._report.stall_rounds = 0

        self._last_completed_count = current_completed
        self._report.current_task_id = self._get_current_task_id()

        if self._report.deviations:
            logger.warning(
                "偏差检测: %d 项偏差, stall=%d, completed=%d/%d",
                len(self._report.deviations),
                self._report.stall_rounds,
                len(self._report.completed_task_ids),
                len(self._plan.tasks),
            )

        return self._report

    def _match_tool_to_task(self, tool_call: dict[str, Any]) -> str | None:
        """将工具调用匹配到任务ID"""
        tool_name = tool_call.get("name", "")
        params = tool_call.get("params", {})
        # 用工具名+参数值搜索任务关键词
        search_text = f"{tool_name} {' '.join(str(v) for v in params.values())}".lower()
        for keyword, task_id in self._tool_task_map.items():
            if keyword in search_text:
                return task_id
        return None

    def _find_task(self, task_id: str) -> Task | None:
        for t in self._plan.tasks:
            if t.task_id == task_id:
                return t
        return None

    def _mark_completed(self, task_id: str) -> None:
        task = self._find_task(task_id)
        if task and task_id not in self._report.completed_task_ids:
            self._report.completed_task_ids.add(task_id)
            task.status = TaskStatus.COMPLETED
            logger.info("任务完成: %s (%s)", task_id, task.description[:30])

    def _get_next_pending_task(self) -> Task | None:
        """获取下一个可执行的待处理任务"""
        for task in self._plan.tasks:
            if task.status != TaskStatus.PENDING:
                continue
            if all(dep in self._report.completed_task_ids for dep in task.dependencies):
                return task
        return None

    def _get_current_task_id(self) -> str:
        task = self._get_next_pending_task()
        return task.task_id if task else ""

    @property
    def progress_percent(self) -> int:
        """计划完成百分比"""
        total = len(self._plan.tasks)
        if total == 0:
            return 100
        return int(len(self._report.completed_task_ids) / total * 100)

    @property
    def is_complete(self) -> bool:
        """计划是否全部完成"""
        return self.progress_percent >= 100

    def status_dict(self) -> dict[str, Any]:
        """返回状态字典（用于进度事件）"""
        return {
            "completed": len(self._report.completed_task_ids),
            "total": len(self._plan.tasks),
            "percent": self.progress_percent,
            "stall_rounds": self._report.stall_rounds,
            "deviations": len(self._report.deviations),
            "replans": self._report.total_replans,
            "current_task": self._report.current_task_id,
        }
