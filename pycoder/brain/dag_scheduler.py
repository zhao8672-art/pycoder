"""
DAG 并行任务调度器 — Codex 风格的 DAG 并行任务执行引擎

将任务建模为有向无环图（DAG），自动识别可并行执行的独立任务组，
使用 asyncio 并发执行，支持拓扑排序、循环检测、进度追踪和 ASCII 可视化。

核心流程:
1. 构建 DAG → 添加节点和依赖边
2. 拓扑排序 → 验证无环性
3. 并行分组 → BFS 识别同级独立任务
4. 分组执行 → 逐组并行执行，组内并发受 Semaphore 控制
5. 进度追踪 → 实时回调执行状态
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from pycoder.bus.protocol import (
    CapabilityCategory,
    CapabilityDefinition,
    ExecutionMode,
    SideEffect,
    TrustLevel,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 枚举定义
# ──────────────────────────────────────────────


class NodeStatus(enum.StrEnum):
    """DAG 节点状态"""

    PENDING = "pending"  # 等待执行
    RUNNING = "running"  # 正在执行
    DONE = "done"  # 执行完成
    FAILED = "failed"  # 执行失败
    SKIPPED = "skipped"  # 因依赖失败而跳过


# ──────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────


@dataclass
class DAGNode:
    """
    DAG 任务节点

    表示 DAG 中的一个可执行任务单元。
    支持依赖关系、优先级、耗时估算和状态追踪。

    Attributes:
        id: 节点唯一标识
        name: 人类可读的任务名称
        description: 任务详细描述
        status: 当前执行状态
        priority: 优先级（数值越小优先级越高）
        estimated_duration: 预估耗时（秒）
        actual_duration: 实际耗时（秒），执行完成后填充
        result: 执行结果数据
        error: 错误信息（失败时填充）
        dependencies: 依赖的节点 ID 列表
        max_retries: 最大重试次数
        timeout: 超时时间（秒），None 表示无限制
        metadata: 额外元数据
    """

    id: str
    name: str
    description: str = ""
    status: NodeStatus = NodeStatus.PENDING
    priority: int = 0
    estimated_duration: float = 0.0
    actual_duration: float = 0.0
    result: Any = None
    error: str | None = None
    dependencies: list[str] = field(default_factory=list)
    max_retries: int = 0
    timeout: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def reset(self) -> None:
        """重置节点状态，用于重新执行"""
        self.status = NodeStatus.PENDING
        self.result = None
        self.error = None
        self.actual_duration = 0.0


# ──────────────────────────────────────────────
# DAG 调度器
# ──────────────────────────────────────────────


class DAGScheduler:
    """
    DAG 并行任务调度器

    将任务建模为有向无环图（DAG），支持：
    - 拓扑排序（Kahn 算法）
    - 并行分组（BFS 层级分组）
    - 循环检测（添加边时自动检测）
    - 进度追踪
    - ASCII 可视化
    """

    def __init__(self, name: str = "default") -> None:
        self.name = name
        self._nodes: dict[str, DAGNode] = {}
        self._adj: dict[str, list[str]] = defaultdict(list)  # 邻接表: from_id → [to_id, ...]
        self._in_degree: dict[str, int] = defaultdict(int)  # 入度
        self._total_duration: float = 0.0
        self._start_time: float = 0.0
        self._end_time: float = 0.0

    # ── 构建方法 ──

    def add_node(self, node: DAGNode) -> None:
        """
        添加任务节点

        Args:
            node: DAGNode 实例

        Raises:
            ValueError: 节点 ID 重复
        """
        if node.id in self._nodes:
            raise ValueError(f"节点 ID 重复: {node.id}")
        self._nodes[node.id] = node
        # 初始化入度（确保在邻接表中存在）
        if node.id not in self._in_degree:
            self._in_degree[node.id] = 0
        logger.debug("添加节点: %s (%s)", node.id, node.name)

    def add_edge(self, from_id: str, to_id: str) -> None:
        """
        添加依赖边: from_id → to_id（to_id 依赖 from_id）

        Args:
            from_id: 前置节点 ID
            to_id: 后置节点 ID

        Raises:
            ValueError: 节点不存在或添加边后产生环
        """
        if from_id not in self._nodes:
            raise ValueError(f"前置节点不存在: {from_id}")
        if to_id not in self._nodes:
            raise ValueError(f"后置节点不存在: {to_id}")

        # 添加边
        self._adj[from_id].append(to_id)
        self._in_degree[to_id] += 1

        # 初始化 from_id 的入度（如果尚未存在）
        if from_id not in self._in_degree:
            self._in_degree[from_id] = 0

        # 循环检测
        if self._has_cycle():
            # 回滚
            self._adj[from_id].remove(to_id)
            self._in_degree[to_id] -= 1
            raise ValueError(f"添加边 {from_id} → {to_id} 会产生环，操作已回滚")

        # 更新节点的依赖列表
        self._nodes[to_id].dependencies.append(from_id)
        logger.debug("添加边: %s → %s", from_id, to_id)

    def _has_cycle(self) -> bool:
        """检测 DAG 中是否存在环（Kahn 算法变体）"""
        in_deg = dict(self._in_degree)
        queue: deque[str] = deque()
        visited = 0

        for node_id in self._nodes:
            if in_deg.get(node_id, 0) == 0:
                queue.append(node_id)

        while queue:
            node_id = queue.popleft()
            visited += 1
            for neighbor in self._adj.get(node_id, []):
                in_deg[neighbor] -= 1
                if in_deg[neighbor] == 0:
                    queue.append(neighbor)

        return visited != len(self._nodes)

    # ── 拓扑排序 ──

    def topological_sort(self) -> list[str]:
        """
        Kahn 算法拓扑排序

        Returns:
            按拓扑序排列的节点 ID 列表

        Raises:
            ValueError: DAG 中存在环
        """
        if self._has_cycle():
            raise ValueError("DAG 中存在环，无法进行拓扑排序")

        in_deg = dict(self._in_degree)
        queue: deque[str] = deque()
        result: list[str] = []

        # 找到所有入度为 0 的节点
        for node_id in self._nodes:
            if in_deg.get(node_id, 0) == 0:
                queue.append(node_id)

        while queue:
            # 按优先级排序（数值越小优先级越高）
            queue = deque(sorted(queue, key=lambda nid: self._nodes[nid].priority))
            node_id = queue.popleft()
            result.append(node_id)

            for neighbor in self._adj.get(node_id, []):
                in_deg[neighbor] -= 1
                if in_deg[neighbor] == 0:
                    queue.append(neighbor)

        return result

    # ── 并行分组 ──

    def get_parallel_groups(self) -> list[list[str]]:
        """
        BFS 层级分组：将拓扑排序后的节点按层级分组，
        同一层级内的节点互不依赖，可并行执行。

        Returns:
            按层级排列的节点 ID 分组列表，每组可并行执行
        """
        if self._has_cycle():
            raise ValueError("DAG 中存在环，无法进行并行分组")

        in_deg = dict(self._in_degree)
        current_level: list[str] = []
        groups: list[list[str]] = []

        # 找到所有入度为 0 的节点作为第一层
        for node_id in self._nodes:
            if in_deg.get(node_id, 0) == 0:
                current_level.append(node_id)

        while current_level:
            # 按优先级排序
            current_level.sort(key=lambda nid: self._nodes[nid].priority)
            groups.append(list(current_level))

            next_level: list[str] = []
            for node_id in current_level:
                for neighbor in self._adj.get(node_id, []):
                    in_deg[neighbor] -= 1
                    if in_deg[neighbor] == 0:
                        next_level.append(neighbor)

            current_level = next_level

        return groups

    # ── 执行 ──

    async def execute_dag(
        self,
        executor: DAGExecutor,
        on_progress: Callable[[str, NodeStatus, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """
        执行整个 DAG：按并行分组逐层执行

        Args:
            executor: DAGExecutor 实例，负责实际的任务执行
            on_progress: 进度回调函数 (node_id, status, info) -> None

        Returns:
            {node_id: result} 字典

        Raises:
            RuntimeError: 执行过程中有节点失败
        """
        groups = self.get_parallel_groups()
        self._start_time = time.time()
        results: dict[str, Any] = {}
        has_failure = False

        logger.info(
            "开始执行 DAG [%s]: %d 个节点, %d 个并行组",
            self.name,
            len(self._nodes),
            len(groups),
        )

        for group_idx, group in enumerate(groups):
            logger.info("执行第 %d/%d 组: %d 个任务", group_idx + 1, len(groups), len(group))
            group_results = await self._execute_group(
                group=group,
                executor=executor,
                on_progress=on_progress,
            )

            # 合并结果
            for node_id, node_result in group_results.items():
                results[node_id] = node_result
                node = self._nodes[node_id]
                if node.status == NodeStatus.FAILED:
                    has_failure = True
                    # 标记所有依赖此节点的后续节点为 SKIPPED
                    self._skip_dependents(node_id)

            if has_failure:
                logger.warning("第 %d 组有节点失败，跳过后续组", group_idx + 1)
                break

        self._end_time = time.time()
        self._total_duration = self._end_time - self._start_time

        status = "失败" if has_failure else "成功"
        logger.info(
            "DAG [%s] 执行%s: 耗时 %.2fs, %d 个节点",
            self.name,
            status,
            self._total_duration,
            len(self._nodes),
        )

        return results

    async def _execute_group(
        self,
        group: list[str],
        executor: DAGExecutor,
        on_progress: Callable[[str, NodeStatus, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """
        执行一组并行任务

        Args:
            group: 当前组节点 ID 列表
            executor: DAGExecutor 实例
            on_progress: 进度回调

        Returns:
            {node_id: result} 字典
        """
        nodes = [self._nodes[nid] for nid in group]

        for node in nodes:
            node.status = NodeStatus.RUNNING
            if on_progress:
                on_progress(node.id, NodeStatus.RUNNING, {"name": node.name})

        # 并发执行
        group_results = await executor.execute_parallel(
            nodes=nodes,
            on_node_done=lambda node, result, error: self._on_node_done(
                node, result, error, on_progress
            ),
        )

        return group_results

    def _on_node_done(
        self,
        node: DAGNode,
        result: Any,
        error: str | None,
        on_progress: Callable | None,
    ) -> None:
        """节点执行完成回调"""
        if error:
            node.status = NodeStatus.FAILED
            node.error = error
            if on_progress:
                on_progress(node.id, NodeStatus.FAILED, {"name": node.name, "error": error})
        else:
            node.status = NodeStatus.DONE
            node.result = result
            if on_progress:
                on_progress(
                    node.id,
                    NodeStatus.DONE,
                    {"name": node.name, "result": str(result)[:200]},
                )

    def _skip_dependents(self, failed_node_id: str) -> None:
        """标记所有依赖失败节点的后续节点为 SKIPPED"""
        queue: deque[str] = deque([failed_node_id])
        visited: set[str] = set()

        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            for neighbor in self._adj.get(current, []):
                if neighbor not in visited:
                    node = self._nodes[neighbor]
                    if node.status == NodeStatus.PENDING:
                        node.status = NodeStatus.SKIPPED
                        node.error = f"依赖节点 {failed_node_id} 执行失败"
                        logger.debug("跳过节点 %s（依赖 %s 失败）", neighbor, failed_node_id)
                    queue.append(neighbor)

    # ── 进度查询 ──

    def get_progress(self) -> dict[str, Any]:
        """
        获取执行进度

        Returns:
            进度信息字典，包含各状态节点数、百分比、耗时等
        """
        total = len(self._nodes)
        if total == 0:
            return {
                "name": self.name,
                "total": 0,
                "pending": 0,
                "running": 0,
                "done": 0,
                "failed": 0,
                "skipped": 0,
                "progress_pct": 0.0,
                "elapsed": 0.0,
                "estimated_remaining": 0.0,
            }

        status_counts = {
            "pending": 0,
            "running": 0,
            "done": 0,
            "failed": 0,
            "skipped": 0,
        }

        for node in self._nodes.values():
            status_counts[node.status.value] += 1

        completed = status_counts["done"] + status_counts["failed"] + status_counts["skipped"]
        progress_pct = (completed / total) * 100

        elapsed = time.time() - self._start_time if self._start_time > 0 else 0.0
        estimated_remaining = 0.0
        if completed > 0 and elapsed > 0:
            estimated_remaining = (elapsed / completed) * (total - completed)

        return {
            "name": self.name,
            "total": total,
            **status_counts,
            "progress_pct": round(progress_pct, 1),
            "elapsed": round(elapsed, 2),
            "estimated_remaining": round(estimated_remaining, 2),
        }

    # ── 可视化 ──

    def visualize(self) -> str:
        """
        生成 ASCII DAG 可视化

        Returns:
            多行字符串，展示 DAG 的拓扑结构
        """
        if not self._nodes:
            return "(空 DAG)"

        groups = self.get_parallel_groups()
        lines: list[str] = []
        lines.append(f"DAG: {self.name} ({len(self._nodes)} 节点, {len(groups)} 层级)")
        lines.append("=" * 60)

        status_icon = {
            NodeStatus.PENDING: "○",
            NodeStatus.RUNNING: "◌",
            NodeStatus.DONE: "●",
            NodeStatus.FAILED: "✗",
            NodeStatus.SKIPPED: "⊘",
        }

        for level_idx, group in enumerate(groups):
            lines.append(f"\n层级 {level_idx + 1}:")

            for node_id in group:
                node = self._nodes[node_id]
                icon = status_icon.get(node.status, "?")
                deps_str = ""
                if node.dependencies:
                    deps_str = f" ← [{', '.join(node.dependencies)}]"
                duration_str = ""
                if node.actual_duration > 0:
                    duration_str = f" ({node.actual_duration:.1f}s)"
                elif node.estimated_duration > 0:
                    duration_str = f" (~{node.estimated_duration:.1f}s)"

                lines.append(
                    f"  {icon} [{node.id}] {node.name}{duration_str}{deps_str}"
                )

                if node.error:
                    lines.append(f"      ⚠ {node.error}")

        lines.append(f"\n{'=' * 60}")
        return "\n".join(lines)

    # ── 辅助方法 ──

    def get_node(self, node_id: str) -> DAGNode | None:
        """获取节点"""
        return self._nodes.get(node_id)

    def get_all_nodes(self) -> list[DAGNode]:
        """获取所有节点"""
        return list(self._nodes.values())

    def reset(self) -> None:
        """重置所有节点状态"""
        for node in self._nodes.values():
            node.reset()
        self._total_duration = 0.0
        self._start_time = 0.0
        self._end_time = 0.0


# ──────────────────────────────────────────────
# DAG 执行器
# ──────────────────────────────────────────────


@dataclass
class ExecutorConfig:
    """执行器配置"""

    max_concurrency: int = 5  # 最大并发数（Semaphore 限制）
    default_timeout: float | None = 60.0  # 默认超时（秒）
    max_retries: int = 2  # 默认最大重试次数
    retry_delay: float = 1.0  # 重试间隔（秒）


class DAGExecutor:
    """
    DAG 并行执行器

    使用 asyncio.gather + Semaphore 实现并发控制，
    支持超时、重试和进度回调。

    Usage:
        executor = DAGExecutor(config=ExecutorConfig(max_concurrency=3))
        executor.register_handler("build", my_build_func)
        results = await executor.execute_parallel(nodes)
    """

    def __init__(self, config: ExecutorConfig | None = None) -> None:
        self.config = config or ExecutorConfig()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrency)
        self._handlers: dict[str, Callable[..., Coroutine[Any, Any, Any]]] = {}

    def register_handler(
        self, name: str, handler: Callable[..., Coroutine[Any, Any, Any]]
    ) -> None:
        """
        注册任务处理器

        Args:
            name: 处理器名称（与节点 name 匹配）
            handler: 异步处理函数，签名为 async def handler(node: DAGNode) -> Any
        """
        self._handlers[name] = handler
        logger.debug("注册处理器: %s", name)

    async def execute_parallel(
        self,
        nodes: list[DAGNode],
        on_node_done: Callable[[DAGNode, Any, str | None], None] | None = None,
    ) -> dict[str, Any]:
        """
        并行执行一组节点

        Args:
            nodes: 待执行的节点列表
            on_node_done: 单个节点完成回调 (node, result, error) -> None

        Returns:
            {node_id: result} 字典
        """
        if not nodes:
            return {}

        tasks = []
        for node in nodes:
            task = self._execute_single(node, on_node_done)
            tasks.append(task)

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        # 组装结果
        results: dict[str, Any] = {}
        for node, result in zip(nodes, results_list):
            if isinstance(result, Exception):
                results[node.id] = None
            else:
                results[node.id] = result

        return results

    async def _execute_single(
        self,
        node: DAGNode,
        on_node_done: Callable[[DAGNode, Any, str | None], None] | None,
    ) -> Any:
        """
        执行单个节点（含重试和超时）

        Args:
            node: 待执行节点
            on_node_done: 完成回调

        Returns:
            执行结果
        """
        max_retries = node.max_retries if node.max_retries > 0 else self.config.max_retries
        timeout = node.timeout if node.timeout is not None else self.config.default_timeout
        last_error: str | None = None

        for attempt in range(max_retries + 1):
            try:
                async with self._semaphore:
                    logger.debug(
                        "执行节点 %s (%s), 第 %d/%d 次",
                        node.id,
                        node.name,
                        attempt + 1,
                        max_retries + 1,
                    )

                    start = time.time()

                    if timeout:
                        result = await asyncio.wait_for(
                            self._run_handler(node), timeout=timeout
                        )
                    else:
                        result = await self._run_handler(node)

                    elapsed = time.time() - start
                    node.actual_duration = elapsed

                    if on_node_done:
                        on_node_done(node, result, None)

                    return result

            except asyncio.TimeoutError:
                last_error = f"超时 ({timeout}s)"
                logger.warning("节点 %s 超时: %s", node.id, last_error)
                if attempt < max_retries:
                    await asyncio.sleep(self.config.retry_delay)

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "节点 %s 执行失败 (第 %d 次): %s",
                    node.id,
                    attempt + 1,
                    last_error,
                )
                if attempt < max_retries:
                    await asyncio.sleep(self.config.retry_delay)

        # 所有重试均失败
        node.actual_duration = 0.0
        if on_node_done:
            on_node_done(node, None, last_error)

        return None

    async def _run_handler(self, node: DAGNode) -> Any:
        """
        执行节点对应的处理器

        Args:
            node: 待执行节点

        Returns:
            处理器返回结果

        Raises:
            ValueError: 未找到匹配的处理器
        """
        handler = self._handlers.get(node.name)
        if handler is None:
            # 尝试按节点 ID 查找
            handler = self._handlers.get(node.id)
        if handler is None:
            raise ValueError(f"未找到节点 {node.id} ({node.name}) 的处理器")

        return await handler(node)


# ──────────────────────────────────────────────
# 能力注册
# ──────────────────────────────────────────────


def register_capabilities(registry: Any) -> None:
    """向能力总线注册 DAG 调度器的所有能力"""
    from pycoder.bus.protocol import (
        CapabilityCategory,
        CapabilityDefinition,
        ExecutionMode,
        SideEffect,
        TrustLevel,
    )

    capabilities = [
        CapabilityDefinition(
            id="dag.create",
            name="创建 DAG",
            description="创建一个新的有向无环图（DAG），用于组织并行任务",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["dag", "scheduler", "parallel"],
        ),
        CapabilityDefinition(
            id="dag.add_node",
            name="添加 DAG 节点",
            description="向 DAG 中添加任务节点，支持依赖关系配置",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["dag", "node", "task"],
        ),
        CapabilityDefinition(
            id="dag.execute",
            name="执行 DAG",
            description="按并行分组执行 DAG 中的所有任务",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.PROJECT_WRITE,
            execution=ExecutionMode.ASYNC,
            side_effects=[SideEffect.PROCESS, SideEffect.FILE_WRITE],
            timeout_ms=600000,
            tags=["dag", "execute", "parallel"],
        ),
        CapabilityDefinition(
            id="dag.status",
            name="DAG 执行状态",
            description="查询 DAG 的执行进度和状态信息",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["dag", "status", "progress"],
        ),
        CapabilityDefinition(
            id="dag.visualize",
            name="DAG 可视化",
            description="生成 DAG 的 ASCII 拓扑结构可视化",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["dag", "visualize", "debug"],
        ),
    ]

    for cap in capabilities:
        registry.register(cap)

    logger.info("DAG 调度器能力已注册: %d 个能力", len(capabilities))