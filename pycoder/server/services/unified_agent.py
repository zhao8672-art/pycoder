"""
统一 Agent 执行引擎 — 集三种模式优点于一体

入口函数:
  - agent_chat_stream() — 兼容原 AgentOrchestrator 签名
  - UnifiedAgentEngine.chat_stream() — 统一入口，自动策略选择
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path

from pycoder.core.di import registry
from pycoder.core.ports.llm_provider import LLMProvider
from pycoder.server.log import log
from pycoder.server.services.agent_loop import UnifiedAgentLoop
from pycoder.server.services.agent_strategies import (
    AgentStrategy,
    auto_select_strategy,
    get_strategy,
    resolve_iterations_for_grade,
)
from pycoder.server.services.task_grader import get_task_grader

logger = logging.getLogger(__name__)

WORKSPACE = Path(
    __import__("os").environ.get(
        "PYCODER_WORKSPACE",
        str(Path(__file__).resolve().parents[3]),
    )
)


class UnifiedAgentEngine:
    """
    统一 Agent 执行引擎

    具备三种模式的所有优点:
      - 读并行/写串行 (AgentOrchestrator)
      - 多角色DAG并行 + QA审查 + FILE代码块 (TeamCoordinator)
      - 全自主流水线 + 内联代码块 + 完成信号 (AutonomousPipeline)
      - 反思机制每3步 (ReActLoop)
    """

    def __init__(
        self,
        workspace: Path = WORKSPACE,
    ):
        self.workspace = workspace

    async def chat_stream(
        self,
        message: str,
        model: str = "auto",
        system_prompt: str | None = None,
        api_key: str | None = None,
        strategy: str = "auto",
        context: str = "",
    ) -> AsyncIterator[dict]:
        """
        统一 Agent 执行入口

        Args:
            message: 用户任务描述
            model: LLM 模型名称
            system_prompt: 自定义系统提示词（覆盖默认）
            api_key: API 密钥
            strategy: 执行策略 (auto/simple/team)
            context: 额外上下文

        Yields:
            {"type": "status"|"tool_result"|"agent_result"|"error", ...}
        """
        if not api_key:
            yield {"type": "error", "message": "No API Key configured"}
            return

        # 创建 ChatBridge
        llm = registry.resolve(LLMProvider)
        llm.configure(model=model, api_key=api_key, system_prompt=system_prompt or "")

        # 自动选择策略（如果策略为 auto）
        if strategy == "auto":
            try:
                selected = await auto_select_strategy(message, llm.stream)
                strategy = selected
                log.info("unified_agent_strategy_selected strategy=%s", strategy)
            except Exception as e:
                logger.debug("strategy_auto_select_failed error=%s", e)
                strategy = "auto"

        # 获取策略配置
        strat_config = get_strategy(strategy)
        if system_prompt:
            strat_config = AgentStrategy(
                name=strat_config.name,
                description=strat_config.description,
                max_iterations=strat_config.max_iterations,
                tool_timeout=strat_config.tool_timeout,
                max_concurrent_tools=strat_config.max_concurrent_tools,
                enable_rumination=strat_config.enable_rumination,
                enable_snapshots=strat_config.enable_snapshots,
                enable_qa_review=strat_config.enable_qa_review,
                system_prompt=system_prompt,
                roles=strat_config.roles,
            )

        # ── 难度分级 → 动态迭代预算 ──
        # 让高复杂任务有足够步数自主跑到交付，而非被固定上限截断。
        task_grade = None
        try:
            task_grade = get_task_grader().grade(message)
            if strat_config.enable_qa_review or strategy == "auto":
                budget = resolve_iterations_for_grade(
                    task_grade.level,
                    strat_config.max_iterations,
                )
                if budget != strat_config.max_iterations:
                    strat_config = AgentStrategy(
                        name=strat_config.name,
                        description=strat_config.description,
                        max_iterations=budget,
                        tool_timeout=strat_config.tool_timeout,
                        max_concurrent_tools=strat_config.max_concurrent_tools,
                        enable_rumination=strat_config.enable_rumination,
                        enable_snapshots=strat_config.enable_snapshots,
                        enable_qa_review=strat_config.enable_qa_review,
                        system_prompt=strat_config.system_prompt,
                        roles=strat_config.roles,
                    )
        except Exception as e:
            logger.debug("task_grade_failed error=%s", e)

        yield {
            "type": "strategy",
            "strategy": strategy,
            "config": strat_config.name,
            "max_iterations": strat_config.max_iterations,
            "grade": task_grade.to_dict() if task_grade else None,
        }

        # 创建统一循环并执行
        loop = UnifiedAgentLoop(strat_config, self.workspace)

        async for event in loop.chat_stream(message, llm, context):
            yield event


# ══════════════════════════════════════════════════════════
# 兼容入口 — 替代原 agent_orchestrator.agent_chat_stream
# ══════════════════════════════════════════════════════════


async def agent_chat_stream(
    message: str,
    model: str = "auto",
    system_prompt: str | None = None,
    api_key: str | None = None,
    context: str = "",
) -> AsyncIterator[dict]:
    """兼容原 AgentOrchestrator 的入口签名（默认使用 simple 策略）"""
    engine = UnifiedAgentEngine()
    async for event in engine.chat_stream(
        message=message,
        model=model,
        system_prompt=system_prompt,
        api_key=api_key,
        strategy="auto",
        context=context,
    ):
        yield event
