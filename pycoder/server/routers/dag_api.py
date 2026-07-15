"""
DAG 调度器 API 路由

端点:
    POST /api/dag/create          — 创建新 DAG
    POST /api/dag/{dag_id}/nodes   — 添加节点到 DAG
    POST /api/dag/{dag_id}/execute — 执行 DAG
    GET  /api/dag/{dag_id}/status  — 获取 DAG 执行状态
    GET  /api/dag/{dag_id}/visualize — 获取 ASCII 可视化
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from pycoder.brain.dag_scheduler import (
    DAGExecutor,
    DAGNode,
    DAGScheduler,
    ExecutorConfig,
    NodeStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dag", tags=["dag"])

# ──────────────────────────────────────────────
# 模块级 DAG 注册表
# ──────────────────────────────────────────────

_dag_registry: dict[str, DAGScheduler] = {}


def _get_dag(dag_id: str) -> DAGScheduler:
    """获取 DAG 实例，不存在时抛出 404"""
    dag = _dag_registry.get(dag_id)
    if dag is None:
        raise HTTPException(status_code=404, detail=f"DAG 不存在: {dag_id}")
    return dag


# ──────────────────────────────────────────────
# 请求模型
# ──────────────────────────────────────────────


class CreateDAGRequest(BaseModel):
    """创建 DAG 请求"""

    name: str = Field(..., description="DAG 名称", min_length=1, max_length=128)
    description: str = Field(default="", description="DAG 描述")


class CreateDAGResponse(BaseModel):
    """创建 DAG 响应"""

    dag_id: str = Field(..., description="DAG 唯一标识")
    name: str = Field(..., description="DAG 名称")
    description: str = Field(default="", description="DAG 描述")


class AddNodeRequest(BaseModel):
    """添加节点请求"""

    name: str = Field(..., description="节点名称", min_length=1, max_length=128)
    description: str = Field(default="", description="节点描述")
    dependencies: list[str] = Field(default_factory=list, description="依赖的节点 ID 列表")
    priority: int = Field(default=0, description="优先级（数值越小优先级越高）")
    estimated_duration: float = Field(default=0.0, description="预估耗时（秒）")
    timeout: float | None = Field(default=None, description="超时时间（秒）")
    max_retries: int = Field(default=0, description="最大重试次数")
    metadata: dict[str, Any] = Field(default_factory=dict, description="额外元数据")


class AddNodeResponse(BaseModel):
    """添加节点响应"""

    node_id: str = Field(..., description="节点 ID")
    dag_id: str = Field(..., description="所属 DAG ID")
    name: str = Field(..., description="节点名称")
    dependencies: list[str] = Field(default_factory=list, description="依赖的节点 ID 列表")


class ExecuteDAGResponse(BaseModel):
    """执行 DAG 响应"""

    dag_id: str = Field(..., description="DAG ID")
    success: bool = Field(..., description="是否全部执行成功")
    total_nodes: int = Field(default=0, description="总节点数")
    completed: int = Field(default=0, description="已完成节点数")
    failed: int = Field(default=0, description="失败节点数")
    duration_seconds: float = Field(default=0.0, description="总耗时（秒）")
    results: dict[str, Any] = Field(default_factory=dict, description="各节点执行结果")


class DAGStatusResponse(BaseModel):
    """DAG 状态响应"""

    dag_id: str = Field(..., description="DAG ID")
    name: str = Field(..., description="DAG 名称")
    total: int = Field(default=0, description="总节点数")
    pending: int = Field(default=0, description="等待中")
    running: int = Field(default=0, description="执行中")
    done: int = Field(default=0, description="已完成")
    failed: int = Field(default=0, description="已失败")
    skipped: int = Field(default=0, description="已跳过")
    progress_pct: float = Field(default=0.0, description="进度百分比")
    elapsed: float = Field(default=0.0, description="已耗时（秒）")
    estimated_remaining: float = Field(default=0.0, description="预估剩余时间（秒）")
    nodes: list[dict[str, Any]] = Field(default_factory=list, description="节点详情列表")


class VisualizeResponse(BaseModel):
    """可视化响应"""

    dag_id: str = Field(..., description="DAG ID")
    visualization: str = Field(..., description="ASCII 可视化文本")


# ──────────────────────────────────────────────
# 端点实现
# ──────────────────────────────────────────────


@router.post("/create", response_model=CreateDAGResponse)
async def create_dag(req: CreateDAGRequest) -> CreateDAGResponse:
    """
    创建新的 DAG 调度器实例

    生成唯一的 dag_id 并初始化 DAGScheduler，
    返回 dag_id 供后续添加节点和执行使用。
    """
    dag_id = str(uuid.uuid4())[:8]
    scheduler = DAGScheduler(name=req.name)
    _dag_registry[dag_id] = scheduler
    logger.info("DAG 已创建: id=%s name=%s", dag_id, req.name)

    return CreateDAGResponse(
        dag_id=dag_id,
        name=req.name,
        description=req.description,
    )


@router.post("/{dag_id}/nodes", response_model=AddNodeResponse)
async def add_node_to_dag(dag_id: str, req: AddNodeRequest) -> AddNodeResponse:
    """
    向 DAG 中添加任务节点

    创建 DAGNode 并添加到指定 DAG 中。
    如果提供了 dependencies 列表，会自动建立依赖边。
    """
    dag = _get_dag(dag_id)

    node_id = str(uuid.uuid4())[:8]
    node = DAGNode(
        id=node_id,
        name=req.name,
        description=req.description,
        priority=req.priority,
        estimated_duration=req.estimated_duration,
        timeout=req.timeout,
        max_retries=req.max_retries,
        metadata=req.metadata,
    )

    dag.add_node(node)
    logger.info("节点已添加: dag=%s node=%s name=%s", dag_id, node_id, req.name)

    # 建立依赖边
    for dep_id in req.dependencies:
        try:
            dag.add_edge(from_id=dep_id, to_id=node_id)
        except ValueError as e:
            # 回滚：移除已添加的节点
            dag._nodes.pop(node_id, None)
            raise HTTPException(status_code=400, detail=f"依赖边无效: {e}") from e

    return AddNodeResponse(
        node_id=node_id,
        dag_id=dag_id,
        name=req.name,
        dependencies=req.dependencies,
    )


@router.post("/{dag_id}/execute", response_model=ExecuteDAGResponse)
async def execute_dag(dag_id: str) -> ExecuteDAGResponse:
    """
    执行 DAG 中的所有任务

    按并行分组逐层执行 DAG 节点。每个节点由一个默认处理器执行，
    该处理器会模拟一个异步任务（实际行为由节点 name 决定）。
    执行前会重置所有节点状态。
    """
    dag = _get_dag(dag_id)

    if len(dag._nodes) == 0:
        raise HTTPException(status_code=400, detail="DAG 中没有节点，请先添加节点")

    # 重置节点状态
    dag.reset()

    # 创建执行器并注册默认处理器
    executor = DAGExecutor(config=ExecutorConfig(max_concurrency=5))

    # 为每个节点注册默认处理器
    for node in dag.get_all_nodes():

        async def _make_handler(n: DAGNode) -> Any:
            """默认处理器：模拟任务执行"""
            # 模拟执行耗时
            if n.estimated_duration > 0:
                await asyncio.sleep(min(n.estimated_duration, 5.0))
            return {
                "node_id": n.id,
                "node_name": n.name,
                "status": "completed",
                "metadata": n.metadata,
            }

        executor.register_handler(node.name, _make_handler)

    try:
        results = await dag.execute_dag(executor=executor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"DAG 执行失败: {e}") from e

    # 统计结果
    total = len(dag._nodes)
    done_count = sum(
        1 for n in dag._nodes.values() if n.status == NodeStatus.DONE
    )
    failed_count = sum(
        1 for n in dag._nodes.values() if n.status == NodeStatus.FAILED
    )
    duration = dag._total_duration

    logger.info(
        "DAG 执行完成: dag=%s 成功=%d 失败=%d 耗时=%.2fs",
        dag_id,
        done_count,
        failed_count,
        duration,
    )

    return ExecuteDAGResponse(
        dag_id=dag_id,
        success=(failed_count == 0),
        total_nodes=total,
        completed=done_count,
        failed=failed_count,
        duration_seconds=round(duration, 2),
        results={k: v for k, v in results.items() if v is not None},
    )


@router.get("/{dag_id}/status", response_model=DAGStatusResponse)
async def get_dag_status(dag_id: str) -> DAGStatusResponse:
    """
    获取 DAG 执行状态和进度

    返回各节点状态统计、进度百分比、耗时估算和节点详情。
    """
    dag = _get_dag(dag_id)
    progress = dag.get_progress()

    # 构建节点详情
    nodes_detail: list[dict[str, Any]] = []
    for node in dag.get_all_nodes():
        nodes_detail.append({
            "id": node.id,
            "name": node.name,
            "description": node.description,
            "status": node.status.value,
            "priority": node.priority,
            "dependencies": node.dependencies,
            "actual_duration": round(node.actual_duration, 2),
            "error": node.error,
        })

    return DAGStatusResponse(
        dag_id=dag_id,
        name=progress["name"],
        total=progress["total"],
        pending=progress["pending"],
        running=progress["running"],
        done=progress["done"],
        failed=progress["failed"],
        skipped=progress["skipped"],
        progress_pct=progress["progress_pct"],
        elapsed=progress["elapsed"],
        estimated_remaining=progress["estimated_remaining"],
        nodes=nodes_detail,
    )


@router.get("/{dag_id}/visualize", response_model=VisualizeResponse)
async def visualize_dag(dag_id: str) -> VisualizeResponse:
    """
    获取 DAG 的 ASCII 拓扑结构可视化

    展示 DAG 的层级结构、节点状态、依赖关系和耗时信息。
    """
    dag = _get_dag(dag_id)
    visualization = dag.visualize()

    return VisualizeResponse(
        dag_id=dag_id,
        visualization=visualization,
    )