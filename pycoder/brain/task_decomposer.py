"""
AI 驱动的任务分解引擎 — 自然语言 → 可并行 DAG

将用户自然语言描述的任务自动分解为有依赖关系的子任务，
自动识别可并行执行的独立任务组。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DAGNode:
    """DAG 任务节点"""
    id: str
    description: str
    deps: list[str] = field(default_factory=list)
    estimated_duration: float = 0.0
    tool: str = ""
    params: dict = field(default_factory=dict)


@dataclass
class DAGPlan:
    """DAG 执行计划"""
    nodes: list[DAGNode]
    parallel_groups: list[list[str]] = field(default_factory=list)
    estimated_speedup: float = 1.0
    estimated_total_seconds: float = 0.0
    risk_level: str = "low"


DECOMPOSE_PROMPT = """\
你是一个任务分解专家。将以下任务分解为可并行执行的子任务清单。

任务: {task}

要求:
1. 识别可以**同时进行**的独立子任务（放在同一组）
2. 识别有依赖关系的子任务（后一个依赖前一个的结果）
3. 每个子任务应足够小（5-50 行代码/1-3 分钟）

请输出 JSON 格式:
```json
{{
    "nodes": [
        {{"id": "task_1", "description": "xxx", "deps": []}},
        {{"id": "task_2", "description": "xxx", "deps": []}},
        {{"id": "task_3", "description": "xxx", "deps": ["task_1"]}}
    ]
}}
```
"""


class TaskDecomposer:
    """AI 驱动的任务分解器 — 自然语言 → DAG"""

    def __init__(self):
        self._bridge: object = None

    async def decompose(self, task: str, context: dict | None = None) -> DAGPlan:
        """将自然语言任务分解为 DAG 计划"""
        prompt = DECOMPOSE_PROMPT.format(task=task)
        response = await self._call_llm(prompt)

        # 解析 JSON
        nodes = self._parse_nodes(response)
        if not nodes:
            # 失败降级：单节点
            nodes = [DAGNode(id="task_main", description=task)]

        # 计算并行分组
        groups = self._calculate_groups(nodes)

        # 估算加速比
        serial_time = len(nodes)
        parallel_time = len(groups)
        speedup = round(serial_time / max(parallel_time, 1), 1)

        return DAGPlan(
            nodes=nodes,
            parallel_groups=groups,
            estimated_speedup=speedup,
            estimated_total_seconds=parallel_time * 30,  # 每组 30s 估算
        )

    def _parse_nodes(self, response: str) -> list[DAGNode]:
        """从 LLM 回复解析 DAG 节点"""
        # 提取 JSON
        import re
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
        json_str = match.group(1) if match else response

        brace_start = json_str.find("{")
        brace_end = json_str.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            json_str = json_str[brace_start:brace_end + 1]

        try:
            data = json.loads(json_str)
            nodes_data = data.get("nodes", [])
            return [
                DAGNode(
                    id=n.get("id", f"task_{i}"),
                    description=n.get("description", ""),
                    deps=n.get("deps", []),
                )
                for i, n in enumerate(nodes_data)
            ]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("任务分解 JSON 解析失败: %s", exc)
            return []

    def _calculate_groups(self, nodes: list[DAGNode]) -> list[list[str]]:
        """Kahn 拓扑排序 → BFS 并行分组"""
        in_degree = {n.id: len(n.deps) for n in nodes}
        adj = {n.id: [] for n in nodes}
        for n in nodes:
            for dep in n.deps:
                if dep in adj:
                    adj[dep].append(n.id)

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        groups = []
        while queue:
            groups.append(list(queue))
            next_queue = []
            for nid in queue:
                for neighbor in adj.get(nid, []):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_queue.append(neighbor)
            queue = next_queue
        return groups

    async def _call_llm(self, prompt: str) -> str:
        """调用 LLM 进行任务分解"""
        try:
            from pycoder.server.chat_bridge import ChatBridge
            bridge = ChatBridge()
            bridge.configure(model="deepseek-chat", temperature=0.2, max_tokens=2048)
            return await bridge.chat(prompt, max_tokens=2048)
        except Exception as exc:
            logger.warning("LLM 任务分解失败: %s", exc)
            return ""


# ══════════════════════════════════════════════════════════
# DAG 执行接口
# ══════════════════════════════════════════════════════════


class DAGExecutor:
    """DAG 执行器 — 将 DAGPlan 提交到 DAGScheduler 执行"""

    async def execute(self, plan: DAGPlan, executor_func: callable = None) -> dict:
        """执行 DAG 计划"""
        from pycoder.brain.dag_scheduler import DAGScheduler, DAGNode as SchedNode

        scheduler = DAGScheduler()
        node_map = {}

        # 注册节点
        for n in plan.nodes:
            sched_node = SchedNode(id=n.id, label=n.description[:50])
            scheduler.add_node(sched_node)
            node_map[n.id] = sched_node

        # 注册依赖
        for n in plan.nodes:
            for dep in n.deps:
                if dep in node_map:
                    scheduler.add_edge(dep, n.id)

        # 拓扑排序
        topo = scheduler.topological_sort()
        if not topo:
            return {"success": False, "error": "DAG 存在循环依赖"}

        # 执行每个并行组
        results = {}
        for group in plan.parallel_groups:
            import asyncio

            async def run_node(nid):
                try:
                    if executor_func:
                        result = await executor_func(
                            next((n for n in plan.nodes if n.id == nid), None)
                        )
                        results[nid] = result
                    else:
                        results[nid] = {"status": "skipped", "node_id": nid}
                except Exception as e:
                    results[nid] = {"status": "failed", "error": str(e)}

            await asyncio.gather(*[run_node(nid) for nid in group])

        return {
            "success": True,
            "total_nodes": len(plan.nodes),
            "parallel_groups": len(plan.parallel_groups),
            "speedup": plan.estimated_speedup,
            "results": results,
        }


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_decomposer: TaskDecomposer | None = None


def get_decomposer() -> TaskDecomposer:
    global _decomposer
    if _decomposer is None:
        _decomposer = TaskDecomposer()
    return _decomposer
