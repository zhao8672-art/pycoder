"""
DAG 调度器单元测试

测试 DAGScheduler、DAGNode、DAGExecutor 的核心功能：
- DAG 构建（添加节点、依赖边、循环检测）
- 拓扑排序与并行分组
- 异步执行（顺序、并行、混合模式）
- 进度回调与状态追踪
- 失败节点阻断依赖节点
- ASCII 可视化
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from pycoder.brain.dag_scheduler import (
    DAGScheduler,
    DAGNode,
    DAGExecutor,
    NodeStatus,
    ExecutorConfig,
)


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────


def _make_node(node_id: str, name: str = "", **kwargs: Any) -> DAGNode:
    """快速创建 DAGNode 的辅助函数"""
    return DAGNode(id=node_id, name=name or node_id, **kwargs)


def _make_executor(
    handlers: dict[str, Any] | None = None,
    max_concurrency: int = 10,
) -> DAGExecutor:
    """快速创建 DAGExecutor 并注册处理器"""
    executor = DAGExecutor(config=ExecutorConfig(max_concurrency=max_concurrency))
    if handlers:
        for name, handler in handlers.items():
            executor.register_handler(name, handler)
    return executor


# ──────────────────────────────────────────────
# 测试：DAG 构建
# ──────────────────────────────────────────────


class TestDAGBuild:
    """DAG 构建相关测试"""

    def test_create_dag(self) -> None:
        """创建 DAG 实例"""
        dag = DAGScheduler(name="test_dag")
        assert dag.name == "test_dag"
        assert dag.get_all_nodes() == []
        assert dag.get_progress()["total"] == 0

    def test_add_node(self) -> None:
        """添加节点到 DAG"""
        dag = DAGScheduler()
        node = _make_node("A", "任务A")
        dag.add_node(node)
        assert dag.get_node("A") is node
        assert len(dag.get_all_nodes()) == 1

    def test_add_node_with_dependencies(self) -> None:
        """添加带依赖边的节点"""
        dag = DAGScheduler()
        dag.add_node(_make_node("A", "编译"))
        dag.add_node(_make_node("B", "测试"))
        dag.add_edge("A", "B")  # B 依赖 A

        node_b = dag.get_node("B")
        assert node_b is not None
        assert "A" in node_b.dependencies

        # 验证拓扑排序
        order = dag.topological_sort()
        assert order == ["A", "B"]

    def test_add_duplicate_node(self) -> None:
        """添加重复节点 ID 应抛出异常"""
        dag = DAGScheduler()
        dag.add_node(_make_node("A", "任务A"))
        with pytest.raises(ValueError, match="节点 ID 重复"):
            dag.add_node(_make_node("A", "重复任务"))

    def test_add_edge_cycle_detection(self) -> None:
        """添加边产生环时应抛出异常并回滚"""
        dag = DAGScheduler()
        dag.add_node(_make_node("A"))
        dag.add_node(_make_node("B"))
        dag.add_node(_make_node("C"))

        dag.add_edge("A", "B")
        dag.add_edge("B", "C")

        with pytest.raises(ValueError, match="会产生环"):
            dag.add_edge("C", "A")  # 产生环 A→B→C→A

        # 验证回滚：C 的依赖应保持原样（只有 B）
        node_c = dag.get_node("C")
        assert node_c is not None
        assert node_c.dependencies == ["B"]

    def test_add_edge_node_not_found(self) -> None:
        """添加边时节点不存在应抛出异常"""
        dag = DAGScheduler()
        dag.add_node(_make_node("A"))
        with pytest.raises(ValueError, match="前置节点不存在"):
            dag.add_edge("X", "A")
        with pytest.raises(ValueError, match="后置节点不存在"):
            dag.add_edge("A", "Y")


# ──────────────────────────────────────────────
# 测试：拓扑排序与并行分组
# ──────────────────────────────────────────────


class TestTopologyAndGroups:
    """拓扑排序与并行分组测试"""

    def test_topological_sort_linear(self) -> None:
        """线性 DAG 拓扑排序: A→B→C→D"""
        dag = DAGScheduler()
        for nid in ["A", "B", "C", "D"]:
            dag.add_node(_make_node(nid))
        dag.add_edge("A", "B")
        dag.add_edge("B", "C")
        dag.add_edge("C", "D")
        assert dag.topological_sort() == ["A", "B", "C", "D"]

    def test_parallel_groups_linear(self) -> None:
        """线性 DAG 并行分组: 每层一个节点"""
        dag = DAGScheduler()
        for nid in ["A", "B", "C"]:
            dag.add_node(_make_node(nid))
        dag.add_edge("A", "B")
        dag.add_edge("B", "C")
        groups = dag.get_parallel_groups()
        assert groups == [["A"], ["B"], ["C"]]

    def test_parallel_groups_independent(self) -> None:
        """独立节点并行分组: 所有节点在同一层"""
        dag = DAGScheduler()
        for nid in ["A", "B", "C"]:
            dag.add_node(_make_node(nid))
        groups = dag.get_parallel_groups()
        assert groups == [["A", "B", "C"]]

    def test_parallel_groups_mixed(self) -> None:
        """混合 DAG 并行分组: A→(B, C)→D"""
        dag = DAGScheduler()
        for nid in ["A", "B", "C", "D"]:
            dag.add_node(_make_node(nid))
        dag.add_edge("A", "B")
        dag.add_edge("A", "C")
        dag.add_edge("B", "D")
        dag.add_edge("C", "D")
        groups = dag.get_parallel_groups()
        assert groups == [["A"], ["B", "C"], ["D"]]

    def test_parallel_groups_complex(self) -> None:
        """复杂 DAG 并行分组: A→(B, C)→D, 同时 E→F"""
        dag = DAGScheduler()
        for nid in ["A", "B", "C", "D", "E", "F"]:
            dag.add_node(_make_node(nid))
        dag.add_edge("A", "B")
        dag.add_edge("A", "C")
        dag.add_edge("B", "D")
        dag.add_edge("C", "D")
        dag.add_edge("E", "F")
        groups = dag.get_parallel_groups()
        # 第一层: A, E (独立); 第二层: B, C, F; 第三层: D
        assert groups == [["A", "E"], ["B", "C", "F"], ["D"]]


# ──────────────────────────────────────────────
# 测试：DAG 执行
# ──────────────────────────────────────────────


class TestDAGExecution:
    """DAG 异步执行测试"""

    @pytest.mark.asyncio
    async def test_execute_sequential(self) -> None:
        """顺序执行: A→B→C"""
        dag = DAGScheduler(name="sequential")
        for nid in ["A", "B", "C"]:
            dag.add_node(_make_node(nid))

        dag.add_edge("A", "B")
        dag.add_edge("B", "C")

        # 记录执行顺序
        exec_order: list[str] = []

        async def handler_a(node: DAGNode) -> str:
            exec_order.append("A")
            return "a_result"

        async def handler_b(node: DAGNode) -> str:
            exec_order.append("B")
            return "b_result"

        async def handler_c(node: DAGNode) -> str:
            exec_order.append("C")
            return "c_result"

        executor = _make_executor(
            {"A": handler_a, "B": handler_b, "C": handler_c}
        )
        results = await dag.execute_dag(executor)

        assert exec_order == ["A", "B", "C"]
        assert results["A"] == "a_result"
        assert results["B"] == "b_result"
        assert results["C"] == "c_result"

        # 验证节点状态
        assert dag.get_node("A").status == NodeStatus.DONE
        assert dag.get_node("B").status == NodeStatus.DONE
        assert dag.get_node("C").status == NodeStatus.DONE

    @pytest.mark.asyncio
    async def test_execute_parallel(self) -> None:
        """并行执行: A, B, C 独立节点"""
        dag = DAGScheduler(name="parallel")
        for nid in ["A", "B", "C"]:
            dag.add_node(_make_node(nid))

        # 使用事件追踪并行执行
        started: set[str] = set()
        completed: list[str] = []
        lock = asyncio.Lock()

        async def make_handler(nid: str):
            async def handler(node: DAGNode) -> str:
                async with lock:
                    started.add(nid)
                # 短暂延迟确保其他节点也能开始
                await asyncio.sleep(0.05)
                async with lock:
                    completed.append(nid)
                return f"{nid}_result"

            return handler

        executor = _make_executor(
            {
                "A": await make_handler("A"),
                "B": await make_handler("B"),
                "C": await make_handler("C"),
            },
            max_concurrency=10,
        )
        results = await dag.execute_dag(executor)

        assert len(results) == 3
        assert results["A"] == "A_result"
        assert results["B"] == "B_result"
        assert results["C"] == "C_result"

        # 并行组只有一层，所有节点应在同一组
        groups = dag.get_parallel_groups()
        assert len(groups) == 1
        assert set(groups[0]) == {"A", "B", "C"}

    @pytest.mark.asyncio
    async def test_execute_mixed(self) -> None:
        """混合执行: A→(B, C)→D"""
        dag = DAGScheduler(name="mixed")
        for nid in ["A", "B", "C", "D"]:
            dag.add_node(_make_node(nid))
        dag.add_edge("A", "B")
        dag.add_edge("A", "C")
        dag.add_edge("B", "D")
        dag.add_edge("C", "D")

        exec_order: list[str] = []

        async def make_handler(nid: str):
            async def handler(node: DAGNode) -> str:
                exec_order.append(nid)
                return f"{nid}_result"

            return handler

        executor = _make_executor(
            {
                "A": await make_handler("A"),
                "B": await make_handler("B"),
                "C": await make_handler("C"),
                "D": await make_handler("D"),
            }
        )
        results = await dag.execute_dag(executor)

        assert len(results) == 4
        # A 必须先于 B, C
        assert exec_order.index("A") < exec_order.index("B")
        assert exec_order.index("A") < exec_order.index("C")
        # B, C 必须先于 D
        assert exec_order.index("B") < exec_order.index("D")
        assert exec_order.index("C") < exec_order.index("D")

    @pytest.mark.asyncio
    async def test_execute_empty(self) -> None:
        """执行空 DAG"""
        dag = DAGScheduler(name="empty")
        executor = DAGExecutor()
        results = await dag.execute_dag(executor)
        assert results == {}

    @pytest.mark.asyncio
    async def test_execute_with_callback(self) -> None:
        """执行时使用进度回调"""
        dag = DAGScheduler(name="callback_test")
        dag.add_node(_make_node("A", "任务A"))
        dag.add_node(_make_node("B", "任务B"))
        dag.add_edge("A", "B")

        callback_calls: list[tuple[str, NodeStatus]] = []

        def on_progress(node_id: str, status: NodeStatus, info: dict[str, Any]) -> None:
            callback_calls.append((node_id, status))

        async def handler_a(node: DAGNode) -> str:
            return "a"

        async def handler_b(node: DAGNode) -> str:
            return "b"

        executor = _make_executor({"A": handler_a, "B": handler_b})
        await dag.execute_dag(executor, on_progress=on_progress)

        # 验证回调被调用（每个节点至少 RUNNING 和 DONE 各一次）
        statuses_a = [s for nid, s in callback_calls if nid == "A"]
        statuses_b = [s for nid, s in callback_calls if nid == "B"]
        assert NodeStatus.RUNNING in statuses_a
        assert NodeStatus.DONE in statuses_a
        assert NodeStatus.RUNNING in statuses_b
        assert NodeStatus.DONE in statuses_b

    @pytest.mark.asyncio
    async def test_failed_node_blocks_dependents(self) -> None:
        """失败节点阻断依赖它的后续节点"""
        dag = DAGScheduler(name="fail_test")
        dag.add_node(_make_node("A", "正常任务"))
        dag.add_node(_make_node("B", "失败任务"))
        dag.add_node(_make_node("C", "依赖B的任务"))
        dag.add_edge("A", "B")
        dag.add_edge("B", "C")

        async def handler_a(node: DAGNode) -> str:
            return "ok"

        async def handler_b(node: DAGNode) -> str:
            raise RuntimeError("B 执行失败")

        async def handler_c(node: DAGNode) -> str:
            return "should_not_run"

        executor = _make_executor(
            {"A": handler_a, "B": handler_b, "C": handler_c}
        )
        _ = await dag.execute_dag(executor)

        # A 应成功
        assert dag.get_node("A").status == NodeStatus.DONE
        # B 应失败
        assert dag.get_node("B").status == NodeStatus.FAILED
        assert "B 执行失败" in (dag.get_node("B").error or "")
        # C 应被跳过（依赖 B 失败）
        assert dag.get_node("C").status == NodeStatus.SKIPPED
        assert "依赖节点 B 执行失败" in (dag.get_node("C").error or "")

    @pytest.mark.asyncio
    async def test_execute_by_node_id_handler(self) -> None:
        """处理器按节点 ID 匹配（fallback 逻辑）"""
        dag = DAGScheduler()
        dag.add_node(_make_node("X", "custom_name"))

        async def handler_x(node: DAGNode) -> str:
            return "x_result"

        # 只注册 ID 为 "X" 的处理器，节点 name 为 "custom_name"
        executor = _make_executor({"X": handler_x})
        results = await dag.execute_dag(executor)
        assert results["X"] == "x_result"


# ──────────────────────────────────────────────
# 测试：状态查询与可视化
# ──────────────────────────────────────────────


class TestStatusAndVisualize:
    """状态查询与可视化测试"""

    def test_get_progress_empty(self) -> None:
        """空 DAG 进度查询"""
        dag = DAGScheduler(name="empty")
        progress = dag.get_progress()
        assert progress["name"] == "empty"
        assert progress["total"] == 0
        assert progress["progress_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_get_progress_after_execution(self) -> None:
        """执行后查询进度"""
        dag = DAGScheduler(name="progress_test")
        for nid in ["A", "B", "C"]:
            dag.add_node(_make_node(nid))

        async def handler(node: DAGNode) -> str:
            return f"{node.id}_result"

        executor = _make_executor(
            {"A": handler, "B": handler, "C": handler}
        )
        await dag.execute_dag(executor)

        progress = dag.get_progress()
        assert progress["total"] == 3
        assert progress["done"] == 3
        assert progress["failed"] == 0
        assert progress["progress_pct"] == 100.0
        assert progress["elapsed"] >= 0  # 执行极快时可能为 0.0

    def test_visualize_empty(self) -> None:
        """空 DAG 可视化"""
        dag = DAGScheduler()
        viz = dag.visualize()
        assert "(空 DAG)" in viz

    def test_visualize_with_nodes(self) -> None:
        """带节点的 DAG 可视化"""
        dag = DAGScheduler(name="viz_test")
        dag.add_node(_make_node("A", "编译", description="编译源代码"))
        dag.add_node(_make_node("B", "测试", description="运行测试"))
        dag.add_edge("A", "B")

        viz = dag.visualize()
        assert "viz_test" in viz
        assert "A" in viz
        assert "B" in viz
        assert "编译" in viz
        assert "测试" in viz
        assert "层级" in viz

    @pytest.mark.asyncio
    async def test_visualize_with_status(self) -> None:
        """执行后可视化包含状态图标"""
        dag = DAGScheduler(name="status_viz")
        dag.add_node(_make_node("A", "成功任务"))
        dag.add_node(_make_node("B", "失败任务"))

        async def handler_a(node: DAGNode) -> str:
            return "ok"

        async def handler_b(node: DAGNode) -> str:
            raise RuntimeError("失败")

        executor = _make_executor({"A": handler_a, "B": handler_b})
        await dag.execute_dag(executor)

        viz = dag.visualize()
        # 成功节点显示 ●，失败节点显示 ✗
        assert "●" in viz
        assert "✗" in viz


# ──────────────────────────────────────────────
# 测试：DAGNode 与 DAGExecutor
# ──────────────────────────────────────────────


class TestDAGNode:
    """DAGNode 数据类测试"""

    def test_node_defaults(self) -> None:
        """节点默认值"""
        node = DAGNode(id="1", name="测试")
        assert node.id == "1"
        assert node.name == "测试"
        assert node.description == ""
        assert node.status == NodeStatus.PENDING
        assert node.priority == 0
        assert node.dependencies == []
        assert node.max_retries == 0
        assert node.timeout is None

    def test_node_reset(self) -> None:
        """节点重置"""
        node = DAGNode(id="1", name="测试", result="done", error="err")
        node.status = NodeStatus.DONE
        node.actual_duration = 5.0
        node.reset()
        assert node.status == NodeStatus.PENDING
        assert node.result is None
        assert node.error is None
        assert node.actual_duration == 0.0


class TestDAGExecutorConfig:
    """ExecutorConfig 测试"""

    def test_default_config(self) -> None:
        """默认配置"""
        config = ExecutorConfig()
        assert config.max_concurrency == 5
        assert config.default_timeout == 60.0
        assert config.max_retries == 2
        assert config.retry_delay == 1.0

    def test_custom_config(self) -> None:
        """自定义配置"""
        config = ExecutorConfig(max_concurrency=3, default_timeout=30.0)
        assert config.max_concurrency == 3
        assert config.default_timeout == 30.0


class TestDAGExecutorHandlers:
    """DAGExecutor 处理器注册测试"""

    def test_register_handler(self) -> None:
        """注册处理器"""
        executor = DAGExecutor()

        async def my_handler(node: DAGNode) -> str:
            return "result"

        executor.register_handler("test", my_handler)
        assert "test" in executor._handlers

    def test_execute_parallel_empty(self) -> None:
        """并行执行空节点列表"""
        executor = DAGExecutor()
        # 同步调用 execute_parallel 需要事件循环
        async def _run():
            return await executor.execute_parallel([])

        results = asyncio.run(_run())
        assert results == {}