"""
Pycoder V2 中央编排引擎

将所有 V2 组件（总线、安全、能力、大脑、模块）连接在一起。
这是从 V1 到 V2 的桥梁 —— 保持 V1 API 兼容的同时启用 V2 架构。

使用方式:
    from pycoder.v2 import V2Engine

    engine = V2Engine()
    await engine.initialize()

    # 通过总线调用能力
    result = await engine.call("editor.code.read", {"path": "main.py"})

    # 使用 AI 大脑执行任务
    await engine.execute_task("创建一个用户认证模块")
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from pycoder.bus.registry import CapabilityRegistry
from pycoder.bus.router import IntelligentRouter
from pycoder.bus.monitor import BusMonitor
from pycoder.bus.protocol import (
    CapabilityCall,
    CapabilityDefinition,
    CapabilityEvent,
    CapabilityResult,
    TrustLevel,
)
from pycoder.bus.transformer import InputTransformer, OutputTransformer

from pycoder.safety.permission import PermissionEngine, PermissionDecision, DecisionType
from pycoder.safety.sandbox import SandboxManager
from pycoder.safety.audit import AuditTrail, AuditRecord
from pycoder.safety.rollback import RollbackManager
from pycoder.safety.circuit_breaker import CircuitBreakerRegistry

from pycoder.brain.consciousness import ConsciousnessEngine, OperatingMode, SystemEvent
from pycoder.brain.task_planner import TaskPlanner, ExecutionPlan
from pycoder.brain.agent_swarm import AgentSwarmOrchestrator, AgentTask
from pycoder.brain.memory_engine import MemoryEngine

from pycoder.modules import ModuleLoader

from pycoder.capabilities import (
    register_editor_capabilities,
    register_system_capabilities,
    register_self_evo_capabilities,
)

logger = logging.getLogger(__name__)


@dataclass
class V2EngineConfig:
    """V2 引擎配置"""
    workspace_root: str = "."
    initial_trust: TrustLevel = TrustLevel.WORKSPACE_WRITE
    enable_consciousness: bool = True     # 是否启��意识引擎（持续感知）
    enable_self_evo: bool = True          # 是否启用自进化能力
    audit_log_path: str = ""              # 审计日志路径
    snapshot_dir: str = ""                # 快照目录


class V2Engine:
    """
    V2 中央编排引擎

    这是 Pycoder V2 的单一入口，将所有子系统连接在一起:
    - 能力总线: 统一的 AI ↔ 模块通信
    - 安全体系: 权限、沙箱、审计、回滚
    - AI 大脑: 意识、规划、编排、记忆
    - 动态模块: 插件的完整生命周期
    """

    def __init__(self, config: V2EngineConfig | None = None):
        self.config = config or V2EngineConfig()

        # 能力总线
        self.registry = CapabilityRegistry()
        self.router = IntelligentRouter(self.registry)
        self.monitor = BusMonitor()
        self.input_transformer = InputTransformer()
        self.output_transformer = OutputTransformer()

        # 安全体系
        self.permission = PermissionEngine(self.config.initial_trust)
        self.sandbox = SandboxManager()
        self.audit = AuditTrail()
        self.rollback = RollbackManager()
        self.circuit_breakers = CircuitBreakerRegistry()

        # AI 大脑
        self.consciousness = ConsciousnessEngine()
        self.planner = TaskPlanner()
        self.orchestrator = AgentSwarmOrchestrator()
        self.memory = MemoryEngine()  # 自动从磁盘加载持久化记忆

        # 动态模块
        self.modules = ModuleLoader(self.registry)

        # 自我进化引擎（延迟初始化，需要 LLM provider）
        self.evolution: Any = None

        # 状态
        self._initialized = False

    async def initialize(self) -> None:
        """初始化 V2 引擎 —— 注册所有能力，启动子系统"""
        if self._initialized:
            return

        logger.info("初始化 Pycoder V2 引擎...")

        # 1. 注册所有能力到总线
        logger.info("注册编辑器能力...")
        register_editor_capabilities(self.registry)

        logger.info("注册系统能力...")
        register_system_capabilities(self.registry)

        if self.config.enable_self_evo:
            logger.info("注册自进化能力...")
            register_self_evo_capabilities(self.registry)

            # 初始化自我进化引擎
            try:
                from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine
                # 尝试注入 LLM provider
                llm = None
                try:
                    from pycoder.server.chat_bridge import ChatBridge
                    bridge = ChatBridge()
                    llm = bridge  # ChatBridge 可作为 LLM provider
                except (ImportError, AttributeError, TypeError, ValueError):
                    pass

                self.evolution = SelfEvolutionEngine(self, llm)
                logger.info("自我进化引擎已初始化 (LLM=%s)", "ready" if llm else "AST-only")
            except Exception as e:
                logger.warning("自我进化引擎初始化失败（将使用 AST 扫描模式）: %s", e)

        # 2. 记忆引擎加载持久化数据
        if self.config.enable_consciousness:
            self.consciousness.set_mode(OperatingMode.AWARE)
            logger.info(
                "意识引擎已启动: mode=%s memories=%d",
                self.consciousness.mode.value,
                len(self.memory.recall("")),
            )

        # 3. V1→V2 工具桥接：将 MCP 工具注册到能力总线
        try:
            from pycoder.server.v2_bridge import bridge_mcp_to_v2
            tool_count = bridge_mcp_to_v2(self)
            logger.info("V1→V2 工具桥接完成: %d tools", tool_count)
        except Exception as e:
            logger.warning("V1→V2 工具桥接失败: %s", e)

        self._initialized = True
        logger.info(
            "V2 引擎初始化完成 — %d 个能力已注册, 信任级别: %s",
            self.registry.count,
            self.permission.current_trust.name,
        )

    # ── 核心 API ────────────────────────────

    async def call(
        self,
        capability_id: str,
        params: dict[str, Any] | None = None,
        *,
        caller: str = "user",
        force: bool = False,
    ) -> CapabilityResult:
        """
        调用一个能力 —— 经过完整的安全检查和审计

        这是 AI 和用户调用任何编辑器功能的统一入口。

        Args:
            capability_id: 能力 ID
            params: 调用参数
            caller: 调用者标识
            force: 是否跳过权限检查（危险！）

        Returns:
            CapabilityResult
        """
        if not self._initialized:
            await self.initialize()

        params = params or {}
        call = CapabilityCall(
            capability_id=capability_id,
            params=params,
            caller=caller,
        )

        # 1. 路由
        route = self.router.route(capability_id, params)
        if route.confidence == 0:
            return CapabilityResult(
                trace_id=call.trace_id,
                capability_id=capability_id,
                success=False,
                error=route.suggestion or f"未找到能力 '{capability_id}'",
                error_code="NOT_FOUND",
            )

        # 2. 获取能力定义
        definition = self.registry.get(route.capability_id)
        if definition is None:
            return CapabilityResult(
                trace_id=call.trace_id,
                capability_id=capability_id,
                success=False,
                error=f"能力定义不存在: {route.capability_id}",
                error_code="DEFINITION_NOT_FOUND",
            )

        # 3. 熔断器检查
        breaker = self.circuit_breakers.get_or_create(route.capability_id)
        if breaker.is_open and not force:
            return CapabilityResult(
                trace_id=call.trace_id,
                capability_id=capability_id,
                success=False,
                error=f"能力 '{capability_id}' 已被熔断",
                error_code="CIRCUIT_OPEN",
            )

        # 4. 权限检查
        if not force:
            decision = self.permission.check(
                route.capability_id,
                definition.permission,
                params,
                definition.side_effects,
            )
            if not decision.allowed and not decision.requires_user_confirm:
                return CapabilityResult(
                    trace_id=call.trace_id,
                    capability_id=capability_id,
                    success=False,
                    error=decision.reason,
                    error_code="PERMISSION_DENIED",
                )
            if decision.requires_user_confirm:
                # 需要用户确认 —— 返回待确认状态
                return CapabilityResult(
                    trace_id=call.trace_id,
                    capability_id=capability_id,
                    success=False,
                    error=decision.confirm_message,
                    error_code="CONFIRMATION_REQUIRED",
                    metadata={"escalate_suggestion": decision.escalate_suggestion},
                )

        # 5. 写操作前创建快照
        if definition.rollback_support:
            await self._create_snapshot_before_write(params, definition)

        # 6. 开始追踪
        trace = self.monitor.start_trace(call, definition)

        # 7. 执行
        try:
            async with breaker:
                result = await self.registry.call(call, {
                    "caller": caller,
                    "permission_level": definition.permission.value,
                })
        except Exception as e:
            result = CapabilityResult(
                trace_id=call.trace_id,
                capability_id=capability_id,
                success=False,
                error=str(e),
                error_code=type(e).__name__,
            )

        # 8. 结束追踪
        self.monitor.end_trace(trace, result)

        # 9. 审计记录
        self.audit.log(AuditRecord(
            trace_id=call.trace_id,
            capability_id=route.capability_id,
            params_summary=self.monitor._summarize_params(params),
            permission_level=definition.permission.value,
            decision=DecisionType.AUTO_ALLOW.value,
            user_confirmed=False,
            success=result.success,
            error=result.error,
            duration_ms=result.duration_ms,
            caller=caller,
        ))

        # 10. 记录行为
        self.permission.record_behavior(
            __import__('pycoder.safety.permission', fromlist=['BehaviorRecord']).BehaviorRecord(
                capability_id=call.capability_id,
                success=result.success,
                had_side_effects=bool(definition.side_effects),
            )
        )

        return result

    async def stream(
        self,
        capability_id: str,
        params: dict[str, Any] | None = None,
        *,
        caller: str = "user",
    ) -> AsyncIterator[CapabilityEvent]:
        """流式调用能力"""
        if not self._initialized:
            await self.initialize()

        params = params or {}
        call = CapabilityCall(
            capability_id=capability_id,
            params=params,
            caller=caller,
        )

        async for event in self.registry.stream(call):
            yield event

    async def execute_task(self, intent: str) -> dict[str, Any]:
        """
        使用 AI 大脑执行一个任务

        Args:
            intent: 用户意图，如 "创建用户认证模块"

        Returns:
            执行结果汇总
        """
        if not self._initialized:
            await self.initialize()

        # 1. 规划
        plan = self.planner.plan(intent)
        logger.info("计划: %s, %d 个任务", plan.strategy.value, len(plan.tasks))

        # 2. 分配角色
        agent_tasks = AgentSwarmOrchestrator.assign_roles(plan.tasks)

        # 3. 执行
        results = await self.orchestrator.execute(agent_tasks)

        # 4. 汇总
        success_count = sum(1 for r in results if r.success)
        return {
            "intent": intent,
            "total_tasks": len(results),
            "success_count": success_count,
            "failed_count": len(results) - success_count,
            "strategy": plan.strategy.value,
            "results": [
                {
                    "task_id": r.task_id,
                    "role": r.role.value,
                    "success": r.success,
                    "error": r.error,
                }
                for r in results
            ],
        }

    # ── 管理 API ────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """获取引擎统计信息"""
        return {
            "initialized": self._initialized,
            "bus": {
                "capabilities": self.registry.stats(),
            },
            "safety": {
                "trust": self.permission.get_trust_report(),
                "breakers": self.circuit_breakers.get_all_stats(),
            },
            "monitor": self.monitor.get_stats(),
            "consciousness": self.consciousness.generate_awareness_report(),
        }

    def get_health_report(self) -> dict[str, Any]:
        """获取健康报告"""
        return {
            "bus_health": self.monitor.get_health_report(),
            "audit_report": self.audit.generate_report(),
            "pending_rollbacks": self.rollback.pending_count(),
            "active_modules": self.modules.list_loaded(),
        }

    def emergency_lockdown(self) -> None:
        """紧急锁定 —— 限制 AI 权限"""
        self.permission.emergency_lockdown()
        self.consciousness.set_mode(OperatingMode.IDLE)
        logger.critical("V2 引擎已进入紧急锁定模式")

    async def shutdown(self) -> None:
        """优雅关闭"""
        logger.info("关闭 V2 引擎...")
        await self.sandbox.cleanup_all()

    # ── 私有方法 ───────────────────────────

    async def _create_snapshot_before_write(
        self,
        params: dict[str, Any],
        definition: CapabilityDefinition,
    ) -> None:
        """写操作前创建文件快照"""
        paths = self.input_transformer.extract_paths(params)
        for path in paths:
            import os
            if os.path.exists(path) and os.path.isfile(path):
                try:
                    self.rollback.snapshot_file(path)
                except (OSError, ValueError):
                    pass
