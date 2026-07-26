"""Pipeline 端口 — AutonomousPipeline 的 Protocol 抽象

将 lifecycle 层对 server.services.AutonomousPipeline 的直接依赖
替换为 Protocol 依赖，消除 D→C 违规。

演进策略（ADR-002）：
- 新代码通过依赖注入接收 PipelineProtocol 实例
- 旧代码可继续使用延迟导入（标记 @deprecated）
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PipelineProtocol(Protocol):
    """自主流水线协议 — 供 lifecycle 层依赖注入"""

    def __init__(
        self,
        workspace_root: str | None = None,
        model: str | None = None,
    ) -> None:
        """初始化流水线"""
        ...

    def run(self, user_request: str) -> AsyncIterator[dict[str, Any]]:
        """运行流水线，异步产生事件

        Args:
            user_request: 用户请求文本

        Yields:
            事件字典（type=agent_done/files_changed/error 等）
        """
        ...


# ── 工厂函数（供 lifecycle 层使用） ──────────────

_pipeline_factory: type[PipelineProtocol] | None = None


def register_pipeline_factory(factory: type[PipelineProtocol]) -> None:
    """注册 Pipeline 实现类（由 server 层在启动时调用）

    Args:
        factory: 实现 PipelineProtocol 的类
    """
    global _pipeline_factory
    _pipeline_factory = factory


def get_pipeline(
    workspace_root: str | None = None,
    model: str | None = None,
) -> PipelineProtocol:
    """获取 Pipeline 实例

    优先使用注册的工厂。若未注册则抛出 RuntimeError。

    Args:
        workspace_root: 工作区根目录
        model: 模型 ID

    Returns:
        PipelineProtocol 实例

    Raises:
        RuntimeError: 若未注册工厂（server 层应在启动时调用 register_pipeline_factory）
    """
    if _pipeline_factory is not None:
        return _pipeline_factory(workspace_root=workspace_root, model=model)

    raise RuntimeError(
        "Pipeline 工厂未注册。请在 server 启动时调用 "
        "pycoder.core.ports.pipeline.register_pipeline_factory(AutonomousPipeline)"
    )
