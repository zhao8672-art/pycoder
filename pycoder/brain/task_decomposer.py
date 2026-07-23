"""
AI 驱动的任务分解引擎 — 自然语言 → 可并行 DAG + 状态图工作流

借鉴生产级 Agent 团队方案，集成:
  - Kahn 拓扑排序 + BFS 并行分组
  - 失败分级重试（RetryPolicy）
  - 三级熔断保护（CircuitBreaker）
  - 任务快照与断点续跑（TaskSnapshot）
  - 全链路审计日志（AuditLogger）
  - 8 阶段流水线状态机
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

PYCODER_ROOT = Path(__file__).resolve().parents[2]


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


class TaskPhase(StrEnum):
    """8 阶段流水线规范"""
    # 阶段 1: 任务接入与准入校验
    INTAKE = "intake"
    # 阶段 2: 需求解析与方案标准化
    DESIGN = "design"
    # 阶段 3: 长任务原子拆解与调度规划
    DECOMPOSE = "decompose"
    # 阶段 4: 环境初始化与前置准备
    ENV_SETUP = "env_setup"
    # 阶段 5: 迭代开发 + 自测提交
    DEVELOP = "develop"
    # 阶段 6: 全量测试 + 问题闭环
    TEST = "test"
    # 阶段 7: 部署验证与交付验收
    DEPLOY = "deploy"
    # 阶段 8: 文档沉淀 + 自动复盘 + 能力迭代
    REVIEW = "review"
    # 终态
    DONE = "done"
    FAILED = "failed"


class TaskLevel(StrEnum):
    """任务分级"""
    S = "S"  # 3 天以上，高复杂度
    A = "A"  # 1-3 天，中等复杂度
    B = "B"  # 半天以内，低复杂度


class NodeStatus(StrEnum):
    """节点执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


@dataclass
class DAGNode:
    """DAG 任务节点 — 增强版（含 Agent 分配、验收标准、超时、重试）"""
    id: str
    description: str
    deps: list[str] = field(default_factory=list)
    estimated_duration: float = 0.0
    tool: str = ""
    params: dict = field(default_factory=dict)
    deliverable: str = ""          # 产出物描述
    risk: str = "low"              # 风险等级: low/medium/high/critical
    # ── 新增：Agent 分配与执行控制 ──
    owner_agent: str = ""          # 负责执行的 Agent 角色（design/dev/test/env/review）
    acceptance_criteria: str = ""  # 验收标准
    timeout_seconds: float = 300.0 # 超时时间
    retry_max: int = 3             # 最大重试次数
    status: NodeStatus = NodeStatus.PENDING  # 执行状态
    result: str = ""               # 执行结果
    error_msg: str = ""            # 错误信息
    started_at: float = 0.0
    completed_at: float = 0.0


@dataclass
class DAGPlan:
    """DAG 执行计划 — 增强版（含全局任务状态）"""
    # 全局标识
    global_task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    task_title: str = ""
    task_level: TaskLevel = TaskLevel.B
    # 流程数据
    requirement_content: str = ""
    tech_solution: str = ""
    # DAG 节点
    nodes: list[DAGNode] = field(default_factory=list)
    parallel_groups: list[list[str]] = field(default_factory=list)
    estimated_speedup: float = 1.0
    estimated_total_seconds: float = 0.0
    risk_level: str = "low"
    critical_path: list[str] = field(default_factory=list)
    # ── 新增：流水线状态 ──
    phase: TaskPhase = TaskPhase.INTAKE
    is_finish: bool = False
    last_run_node: str = "start"
    # 阶段结果
    code_commit_log: list[str] = field(default_factory=list)
    bug_list: list[dict] = field(default_factory=list)
    test_report: str = ""
    deploy_result: str = ""
    review_report: str = ""
    # 时间戳
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "global_task_id": self.global_task_id,
            "task_title": self.task_title,
            "task_level": self.task_level.value,
            "requirement_content": self.requirement_content[:500],
            "tech_solution": self.tech_solution[:500],
            "nodes": [
                {
                    "id": n.id, "description": n.description[:100],
                    "deps": n.deps, "owner_agent": n.owner_agent,
                    "status": n.status.value, "risk": n.risk,
                    "deliverable": n.deliverable[:200],
                }
                for n in self.nodes
            ],
            "parallel_groups": self.parallel_groups,
            "estimated_speedup": self.estimated_speedup,
            "phase": self.phase.value,
            "is_finish": self.is_finish,
            "last_run_node": self.last_run_node,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ══════════════════════════════════════════════════════════
# 分解提示词
# ══════════════════════════════════════════════════════════

DECOMPOSE_PROMPT = """\
你是一个任务分解专家。将以下任务分解为可并行执行的子任务清单。

任务: {task}

## 分解准则
1. **粒度适中**：每个子任务应足够小（5-50 行代码/1-3 分钟），可独立完成
2. **识别并行**：识别可以**同时进行**的独立子任务（放在同一组），最大化并行度
3. **明确依赖**：识别有依赖关系的子任务（后一个依赖前一个的结果），依赖关系必须无环（DAG 合法）
4. **标注风险**：标注每个子任务的风险等级（low/medium/high）
5. **标注产出**：标注任务之间的数据流（产出物是什么），每个 task 明确给出 deliverables
6. **单一 owner**：每个 task 有且仅有 1 个 owner 角色（design/dev/test/env/review）
7. **验收标准**：每个 task 给出明确的可验收标准
8. **超时估算**：每个 task 估算超时时间（秒）

## 输出格式
请输出 JSON 格式:
```json
{{
    "nodes": [
        {{
            "id": "task_1",
            "description": "xxx",
            "deps": [],
            "owner_agent": "dev",
            "deliverable": "产出物",
            "acceptance_criteria": "验收标准",
            "risk": "low|medium|high",
            "timeout_seconds": 300
        }},
        {{
            "id": "task_2",
            "description": "xxx",
            "deps": ["task_1"],
            "owner_agent": "test",
            "deliverable": "产出物",
            "acceptance_criteria": "验收标准",
            "risk": "low"
        }}
    ],
    "parallel_groups": [["task_1", "task_2"], ["task_3"]],
    "critical_path": ["task_1", "task_3"],
    "estimated_effort": "预估工作量",
    "risk_points": ["潜在风险点"],
    "task_level": "S|A|B"
}}
```"""


# ══════════════════════════════════════════════════════════
# TaskDecomposer — AI 驱动的任务分解器
# ══════════════════════════════════════════════════════════


class TaskDecomposer:
    """AI 驱动的任务分解器 — 自然语言 → DAG

    支持:
      - LLM 驱动的任务分解
      - 依赖拓扑自动生成
      - 并行分组计算
      - Agent 角色自动分配
    """

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
            nodes = [DAGNode(
                id="task_main",
                description=task,
                owner_agent="dev",
                acceptance_criteria="功能正常运行",
            )]

        # 计算并行分组
        groups = self._calculate_groups(nodes)

        # 估算加速比
        serial_time = len(nodes)
        parallel_time = len(groups)
        speedup = round(serial_time / max(parallel_time, 1), 1)

        # 估算风险等级
        risk_level = self._estimate_risk(nodes)

        # 计算关键路径
        critical_path = self._calculate_critical_path(nodes, groups)

        # 解析任务分级
        task_level = self._parse_task_level(response)

        return DAGPlan(
            nodes=nodes,
            parallel_groups=groups,
            estimated_speedup=speedup,
            estimated_total_seconds=parallel_time * 30,
            risk_level=risk_level,
            critical_path=critical_path,
            task_level=task_level,
            task_title=task[:80],
            requirement_content=task,
            phase=TaskPhase.DECOMPOSE,
            last_run_node="task_split_finish",
        )

    def _parse_nodes(self, response: str) -> list[DAGNode]:
        """从 LLM 回复解析 DAG 节点"""
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
                    owner_agent=n.get("owner_agent", "dev"),
                    deliverable=n.get("deliverable", ""),
                    acceptance_criteria=n.get("acceptance_criteria", ""),
                    risk=n.get("risk", "low"),
                    timeout_seconds=float(n.get("timeout_seconds", 300)),
                    retry_max=int(n.get("retry_max", 3)),
                )
                for i, n in enumerate(nodes_data)
            ]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("任务分解 JSON 解析失败: %s", exc)
            return []

    def _calculate_groups(self, nodes: list[DAGNode]) -> list[list[str]]:
        """Kahn 拓扑排序 → BFS 并行分组"""
        in_degree = {n.id: len(n.deps) for n in nodes}
        adj: dict[str, list[str]] = {n.id: [] for n in nodes}
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

    def _estimate_risk(self, nodes: list[DAGNode]) -> str:
        """估算整体风险等级"""
        risk_weights = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        if not nodes:
            return "low"
        avg = sum(risk_weights.get(n.risk, 0) for n in nodes) / len(nodes)
        if avg >= 2.5:
            return "critical"
        if avg >= 1.5:
            return "high"
        if avg >= 0.5:
            return "medium"
        return "low"

    def _calculate_critical_path(
        self, nodes: list[DAGNode], groups: list[list[str]]
    ) -> list[str]:
        """计算关键路径（最长依赖链）"""
        if not nodes:
            return []

        # 构建邻接表
        adj: dict[str, list[str]] = {n.id: [] for n in nodes}
        for n in nodes:
            for dep in n.deps:
                if dep in adj:
                    adj[dep].append(n.id)

        # 拓扑排序 + 最长路径
        in_degree = {n.id: len(n.deps) for n in nodes}
        dist: dict[str, int] = {n.id: 1 for n in nodes}
        prev: dict[str, str | None] = {n.id: None for n in nodes}

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        while queue:
            u = queue.pop(0)
            for v in adj.get(u, []):
                if dist[v] < dist[u] + 1:
                    dist[v] = dist[u] + 1
                    prev[v] = u
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    queue.append(v)

        # 回溯最长路径
        if not dist:
            return []
        end_node = max(dist, key=lambda k: dist[k])
        path = []
        current: str | None = end_node
        while current is not None:
            path.append(current)
            current = prev[current]
        path.reverse()
        return path

    def _parse_task_level(self, response: str) -> TaskLevel:
        """从 LLM 响应中解析任务分级"""
        import re

        match = re.search(r'"task_level"\s*:\s*"([SAB])"', response)
        if match:
            return TaskLevel(match.group(1))
        return TaskLevel.B

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
# DAGExecutor — 生产级 DAG 执行器（集成重试/熔断/快照/审计）
# ══════════════════════════════════════════════════════════


class DAGExecutor:
    """生产级 DAG 执行器

    集成:
      - 失败分级重试（RetryPolicy）
      - 三级熔断保护（CircuitBreaker）
      - 任务快照与断点续跑（TaskSnapshot）
      - 全链路审计日志（AuditLogger）
      - 8 阶段流水线状态机
      - Agent 角色路由
    """

    # Agent 角色 → 流水线阶段映射
    AGENT_PHASE_MAP: dict[str, TaskPhase] = {
        "design": TaskPhase.DESIGN,
        "dev": TaskPhase.DEVELOP,
        "test": TaskPhase.TEST,
        "env": TaskPhase.ENV_SETUP,
        "review": TaskPhase.REVIEW,
    }

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace or PYCODER_ROOT
        self._retry_policy = None
        self._circuit_breaker = None
        self._snapshot = None
        self._audit_logger = None

    # ══════════════════════════════════════════════════════
    # 核心执行方法
    # ══════════════════════════════════════════════════════

    async def execute(
        self,
        plan: DAGPlan,
        executor_func: Callable[[DAGNode], Awaitable[dict[str, Any]]] | None = None,
        *,
        auto_retry: bool = True,
        enable_snapshot: bool = True,
        enable_audit: bool = True,
    ) -> dict[str, Any]:
        """执行 DAG 计划，按并行组逐组执行

        Args:
            plan: DAG 执行计划
            executor_func: 节点执行函数，接收 DAGNode 返回结果字典
            auto_retry: 是否启用自动重试
            enable_snapshot: 是否启用任务快照
            enable_audit: 是否启用审计日志

        Returns:
            执行结果字典
        """
        t0 = time.time()
        plan.phase = TaskPhase.DECOMPOSE

        # 初始化集成组件
        if auto_retry:
            self._init_retry_policy()
        self._init_circuit_breaker()
        if enable_snapshot:
            self._init_snapshot()
        if enable_audit:
            self._init_audit_logger()

        # 保存初始快照
        if enable_snapshot and self._snapshot:
            self._save_plan_snapshot(plan)

        # 校验 DAG 合法性
        if not self._validate_dag(plan):
            self._audit("dag_validate", {"plan_id": plan.global_task_id}, "failed",
                        error="DAG 存在循环依赖")
            return {"success": False, "error": "DAG 存在循环依赖", "plan_id": plan.global_task_id}

        # 按并行组执行
        results: dict[str, dict[str, Any]] = {}
        total_nodes = len(plan.nodes)
        failed_nodes = 0

        for group_idx, group in enumerate(plan.parallel_groups):
            # 检查熔断器
            if self._circuit_breaker and self._circuit_breaker.is_open():
                msg = "熔断器已打开，暂停执行"
                logger.warning("circuit_open plan=%s group=%d", plan.global_task_id, group_idx)
                self._audit("circuit_breaker", {"plan_id": plan.global_task_id}, "blocked", error=msg)
                break

            # 更新阶段
            plan.phase = self._determine_phase(group, plan)

            # 并行执行组内节点
            group_results = await asyncio.gather(
                *[self._execute_node(nid, plan, executor_func, auto_retry) for nid in group],
                return_exceptions=True,
            )

            for nid, result in zip(group, group_results):
                if isinstance(result, Exception):
                    results[nid] = {"status": "failed", "error": str(result)}
                    failed_nodes += 1
                else:
                    results[nid] = result
                    if result.get("status") == "failed":
                        failed_nodes += 1

            # 保存快照
            if enable_snapshot and self._snapshot:
                self._save_plan_snapshot(plan)

            # 检查是否应该继续
            if failed_nodes > 0 and self._should_stop_on_failure(plan):
                logger.warning("stop_on_failure plan=%s failed=%d", plan.global_task_id, failed_nodes)
                break

        plan.is_finish = True
        plan.phase = TaskPhase.DONE if failed_nodes == 0 else TaskPhase.FAILED
        duration_ms = (time.time() - t0) * 1000

        # 最终审计
        self._audit("dag_execute_complete", {
            "plan_id": plan.global_task_id,
            "total_nodes": total_nodes,
            "failed": failed_nodes,
            "duration_ms": duration_ms,
        }, "success" if failed_nodes == 0 else "failed")

        return {
            "success": failed_nodes == 0,
            "plan_id": plan.global_task_id,
            "total_nodes": total_nodes,
            "failed_nodes": failed_nodes,
            "parallel_groups": len(plan.parallel_groups),
            "speedup": plan.estimated_speedup,
            "phase": plan.phase.value,
            "duration_ms": duration_ms,
            "results": results,
        }

    # ══════════════════════════════════════════════════════
    # 单节点执行（含重试）
    # ══════════════════════════════════════════════════════

    async def _execute_node(
        self,
        nid: str,
        plan: DAGPlan,
        executor_func: Callable | None,
        auto_retry: bool,
    ) -> dict[str, Any]:
        """执行单个节点，支持重试"""
        node = next((n for n in plan.nodes if n.id == nid), None)
        if not node:
            return {"status": "failed", "error": f"节点 {nid} 不存在"}

        node.status = NodeStatus.RUNNING
        node.started_at = time.time()

        self._audit("node_start", {
            "node_id": nid,
            "plan_id": plan.global_task_id,
            "owner_agent": node.owner_agent,
            "phase": plan.phase.value,
        }, "running")

        last_error = ""
        max_attempts = node.retry_max + 1 if auto_retry else 1

        for attempt in range(1, max_attempts + 1):
            try:
                if executor_func:
                    # 带超时执行
                    result = await asyncio.wait_for(
                        executor_func(node),
                        timeout=node.timeout_seconds,
                    )
                else:
                    result = {"status": "skipped", "node_id": nid}

                node.status = NodeStatus.SUCCESS
                node.result = str(result)
                node.completed_at = time.time()
                node.error_msg = ""

                self._audit("node_success", {
                    "node_id": nid,
                    "attempt": attempt,
                    "duration_ms": (node.completed_at - node.started_at) * 1000,
                }, "success")

                # 记录到熔断器
                if self._circuit_breaker:
                    self._circuit_breaker.record_success()

                return {"status": "success", "node_id": nid, "result": result, "attempt": attempt}

            except asyncio.TimeoutError:
                last_error = f"超时 ({node.timeout_seconds}s)"
                logger.warning("node_timeout node=%s attempt=%d/%d", nid, attempt, max_attempts)
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning("node_error node=%s attempt=%d/%d: %s", nid, attempt, max_attempts, e)

            # 重试延迟
            if attempt < max_attempts:
                delay = min(2 ** (attempt - 1), 30)  # 指数退避，最大 30s
                self._audit("node_retry", {
                    "node_id": nid, "attempt": attempt,
                    "delay": delay, "error": last_error,
                }, "retrying")
                await asyncio.sleep(delay)

        # 所有重试失败
        node.status = NodeStatus.FAILED
        node.error_msg = last_error
        node.completed_at = time.time()

        self._audit("node_failed", {
            "node_id": nid, "total_attempts": max_attempts,
            "error": last_error,
        }, "failed")

        # 记录到熔断器
        if self._circuit_breaker:
            self._circuit_breaker.record_failure(last_error)

        return {"status": "failed", "node_id": nid, "error": last_error, "attempts": max_attempts}

    # ══════════════════════════════════════════════════════
    # DAG 校验
    # ══════════════════════════════════════════════════════

    def _validate_dag(self, plan: DAGPlan) -> bool:
        """校验 DAG 无循环依赖"""
        node_ids = {n.id for n in plan.nodes}
        visited: set[str] = set()
        rec_stack: set[str] = set()

        adj: dict[str, list[str]] = {n.id: [] for n in plan.nodes}
        for n in plan.nodes:
            for dep in n.deps:
                if dep in adj:
                    adj[dep].append(n.id)

        def has_cycle(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            rec_stack.discard(node)
            return False

        for nid in node_ids:
            if nid not in visited:
                if has_cycle(nid):
                    return False
        return True

    # ══════════════════════════════════════════════════════
    # 阶段判定
    # ══════════════════════════════════════════════════════

    def _determine_phase(self, group: list[str], plan: DAGPlan) -> TaskPhase:
        """根据当前执行组的 Agent 角色判定阶段"""
        phases_seen: set[TaskPhase] = set()
        for nid in group:
            node = next((n for n in plan.nodes if n.id == nid), None)
            if node and node.owner_agent in self.AGENT_PHASE_MAP:
                phases_seen.add(self.AGENT_PHASE_MAP[node.owner_agent])

        # 优先级: DESIGN > ENV_SETUP > DEVELOP > TEST > DEPLOY > REVIEW
        for phase in TaskPhase:
            if phase in phases_seen:
                return phase
        return plan.phase

    def _should_stop_on_failure(self, plan: DAGPlan) -> bool:
        """判断是否应该因失败而停止"""
        # 如果关键路径上有节点失败，停止
        critical_failed = any(
            n.status == NodeStatus.FAILED and n.id in plan.critical_path
            for n in plan.nodes
        )
        if critical_failed:
            return True

        # 如果风险等级为 critical，任何失败都停止
        if plan.risk_level == "critical":
            return True

        return False

    # ══════════════════════════════════════════════════════
    # 集成组件初始化
    # ══════════════════════════════════════════════════════

    def _init_retry_policy(self) -> None:
        """初始化重试策略"""
        if self._retry_policy is None:
            try:
                from pycoder.evolution.retry_policy import RetryPolicy
                self._retry_policy = RetryPolicy(max_retries=3)
            except ImportError:
                logger.debug("RetryPolicy 不可用")

    def _init_circuit_breaker(self) -> None:
        """初始化熔断器"""
        if self._circuit_breaker is None:
            try:
                from pycoder.safety.circuit_breaker import CircuitBreakerRegistry
                self._circuit_breaker = CircuitBreakerRegistry().get("dag_executor")
            except ImportError:
                logger.debug("CircuitBreaker 不可用")

    def _init_snapshot(self) -> None:
        """初始化任务快照"""
        if self._snapshot is None:
            try:
                from pycoder.brain.task_snapshot import TaskSnapshot
                self._snapshot = TaskSnapshot(workspace=self._workspace)
            except ImportError:
                logger.debug("TaskSnapshot 不可用")

    def _init_audit_logger(self) -> None:
        """初始化审计日志"""
        if self._audit_logger is None:
            try:
                from pycoder.server.services.audit_logger import AuditLogger
                self._audit_logger = AuditLogger()
            except ImportError:
                logger.debug("AuditLogger 不可用")

    def _save_plan_snapshot(self, plan: DAGPlan) -> None:
        """保存 DAGPlan 快照"""
        try:
            if self._snapshot:
                # 将 DAGPlan 转换为 TaskState 保存
                from pycoder.brain.task_snapshot import TaskState, SubTask, TaskStatus

                state = TaskState(
                    global_task_id=plan.global_task_id,
                    task_title=plan.task_title,
                    status=plan.phase.value,
                    sub_tasks={
                        n.id: SubTask(
                            task_id=n.id,
                            task_name=n.description[:50],
                            task_type=n.owner_agent or "dev",
                            status=n.status.value,
                            depend_task_ids=n.deps,
                            accept_std=n.acceptance_criteria,
                            result=n.result,
                            error_msg=n.error_msg,
                            assigned_agent=n.owner_agent,
                        )
                        for n in plan.nodes
                    },
                    last_run_node=plan.phase.value,
                    is_finish=plan.is_finish,
                )
                self._snapshot.save(state)
        except Exception as e:
            logger.debug("snapshot_save_failed: %s", e)

    def _audit(
        self,
        tool_name: str,
        params: dict,
        result: str,
        error: str = "",
        duration_ms: float = 0,
    ) -> None:
        """记录审计日志"""
        try:
            if self._audit_logger:
                self._audit_logger.log(
                    tool_name=tool_name,
                    params=params,
                    result=result,
                    error=error,
                    duration_ms=duration_ms,
                )
        except Exception as e:
            logger.debug("audit_log_failed: %s", e)

    # ══════════════════════════════════════════════════════
    # 状态恢复
    # ══════════════════════════════════════════════════════

    async def resume(self, plan_id: str, executor_func: Callable | None = None) -> dict[str, Any]:
        """从快照恢复执行（断点续跑）"""
        try:
            from pycoder.brain.task_snapshot import TaskSnapshot
            snapshot = TaskSnapshot(workspace=self._workspace)
            state = snapshot.load(plan_id)

            if not state:
                return {"success": False, "error": f"快照不存在: {plan_id}"}

            if state.is_finish:
                return {"success": True, "message": "任务已完成", "plan_id": plan_id}

            # 重建 DAGPlan
            nodes = [
                DAGNode(
                    id=st.task_id,
                    description=st.task_name,
                    deps=st.depend_task_ids,
                    owner_agent=st.assigned_agent or st.task_type,
                    acceptance_criteria=st.accept_std,
                    status=NodeStatus(st.status) if st.status in NodeStatus._value2member_map_ else NodeStatus.PENDING,
                    result=st.result,
                    error_msg=st.error_msg,
                )
                for st in state.sub_tasks.values()
            ]

            plan = DAGPlan(
                global_task_id=state.global_task_id,
                task_title=state.task_title,
                phase=TaskPhase(state.status) if state.status in TaskPhase._value2member_map_ else TaskPhase.DECOMPOSE,
                nodes=nodes,
                parallel_groups=self._calculate_groups_from_nodes(nodes),
                last_run_node=state.last_run_node,
            )

            # 跳过已完成的节点
            pending_nodes = [n for n in plan.nodes if n.status != NodeStatus.SUCCESS]
            plan.nodes = pending_nodes
            plan.parallel_groups = self._calculate_groups_from_nodes(pending_nodes)

            return await self.execute(plan, executor_func)

        except Exception as e:
            logger.error("resume_failed plan=%s: %s", plan_id, e)
            return {"success": False, "error": str(e)}

    def _calculate_groups_from_nodes(self, nodes: list[DAGNode]) -> list[list[str]]:
        """从节点列表计算并行分组"""
        return TaskDecomposer()._calculate_groups(nodes)


# ══════════════════════════════════════════════════════════
# CoreSchedulerAgent — 中枢调度 Agent（借鉴生产级方案）
# ══════════════════════════════════════════════════════════


class CoreSchedulerAgent:
    """中枢调度 Agent — 长任务拆解 + 拓扑调度 + 闭环驱动

    负责:
      1. 接收原始任务，进行任务分级
      2. 拆解长任务为原子子任务 DAG
      3. 根据子任务类型智能分发至对应 Agent
      4. 实时监控进度、阻塞点、异常状态
      5. 驱动全流程闭环
    """

    AGENT_ROUTER: dict[str, str] = {
        "design": "design_run",
        "dev": "dev_run",
        "test": "test_run",
        "env": "env_run",
        "review": "review_run",
    }

    def __init__(self):
        self._decomposer = TaskDecomposer()
        self._executor = DAGExecutor()

    async def run_task(
        self,
        requirement: str,
        task_level: str = "B",
        executor_func: Callable | None = None,
    ) -> dict[str, Any]:
        """运行完整的长任务闭环

        Args:
            requirement: 需求描述
            task_level: 任务等级 (S/A/B)
            executor_func: 节点执行函数

        Returns:
            执行结果
        """
        # 阶段 1-2: 准入校验 + 需求解析
        plan = await self._decomposer.decompose(requirement)
        plan.task_level = TaskLevel(task_level) if task_level in TaskLevel._value2member_map_ else TaskLevel.B
        plan.phase = TaskPhase.DECOMPOSE

        logger.info(
            "task_started plan=%s title=%s level=%s nodes=%d groups=%d",
            plan.global_task_id, plan.task_title, plan.task_level.value,
            len(plan.nodes), len(plan.parallel_groups),
        )

        # 阶段 3-8: 执行 DAG
        result = await self._executor.execute(plan, executor_func)

        logger.info(
            "task_completed plan=%s success=%s duration=%s",
            plan.global_task_id, result.get("success"), result.get("duration_ms"),
        )

        return result

    def schedule_router(self, plan: DAGPlan) -> str:
        """智能路由 — 判断当前可执行的任务节点"""
        if plan.is_finish:
            return "end"

        # 筛选所有依赖完成、未执行的任务
        runnable_tasks: list[tuple[str, str]] = []
        for node in plan.nodes:
            if node.status != NodeStatus.PENDING:
                continue
            # 校验依赖是否全部完成
            deps_ok = all(
                any(n.id == d and n.status == NodeStatus.SUCCESS for n in plan.nodes)
                for d in node.deps
            )
            if deps_ok:
                runnable_tasks.append((node.owner_agent, node.id))

        if not runnable_tasks:
            # 检查是否全部完成
            all_done = all(n.status == NodeStatus.SUCCESS for n in plan.nodes)
            if all_done:
                plan.is_finish = True
                return "end"
            return "wait"

        # 返回对应执行节点
        current_type, _ = runnable_tasks[0]
        return self.AGENT_ROUTER.get(current_type, "wait")


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_decomposer: TaskDecomposer | None = None
_executor: DAGExecutor | None = None
_scheduler: CoreSchedulerAgent | None = None


def get_decomposer() -> TaskDecomposer:
    global _decomposer
    if _decomposer is None:
        _decomposer = TaskDecomposer()
    return _decomposer


def get_executor(workspace: Path | None = None) -> DAGExecutor:
    global _executor
    if _executor is None:
        _executor = DAGExecutor(workspace=workspace)
    return _executor


def get_scheduler() -> CoreSchedulerAgent:
    global _scheduler
    if _scheduler is None:
        _scheduler = CoreSchedulerAgent()
    return _scheduler


__all__ = [
    "TaskDecomposer",
    "DAGExecutor",
    "CoreSchedulerAgent",
    "DAGNode",
    "DAGPlan",
    "TaskPhase",
    "TaskLevel",
    "NodeStatus",
    "get_decomposer",
    "get_executor",
    "get_scheduler",
]