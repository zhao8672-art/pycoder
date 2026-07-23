"""
自我进化集成桥接 — 连接 self_evo 与 memory/plugins/observability/safety 模块

提供:
  1. MemoryIntegration  — 将进化历史持久化到 memory 模块
  2. PluginIntegration  — 通过插件系统扩展进化能力
  3. ObservabilityIntegration — 进化效果监控与评估
  4. SafetyIntegration  — 进化过程安全沙箱保护

用法:
  from pycoder.capabilities.self_evo.learning.integration import (
      EvolutionIntegration,
      get_evolution_integration,
  )
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class IntegrationStatus:
    """集成状态"""

    memory_available: bool = False
    plugins_available: bool = False
    observability_available: bool = False
    safety_available: bool = False
    last_check: float = 0.0


class EvolutionIntegration:
    """自我进化集成桥接器"""

    def __init__(self):
        self._status = self._check_availability()
        self._evolution_history: list[dict[str, Any]] = []

    # ══════════════════════════════════════════════════════
    # 可用性检查
    # ══════════════════════════════════════════════════════

    def _check_availability(self) -> IntegrationStatus:
        """检查各模块可用性"""
        status = IntegrationStatus()

        # Memory
        try:
            from pycoder.memory import SessionMemoryEngine

            status.memory_available = True
        except ImportError:
            logger.debug("Memory 模块不可用")

        # Plugins
        try:
            from pycoder.plugins import BasePlugin

            status.plugins_available = True
        except ImportError:
            logger.debug("Plugins 模块不可用")

        # Observability
        try:
            from pycoder.observability.sentry import SentryIntegration

            status.observability_available = True
        except ImportError:
            logger.debug("Observability 模块不可用")

        # Safety
        try:
            from pycoder.safety import SandboxManager

            status.safety_available = True
        except ImportError:
            logger.debug("Safety 模块不可用")

        status.last_check = time.time()
        return status

    def refresh(self) -> IntegrationStatus:
        """刷新可用性检查"""
        self._status = self._check_availability()
        return self._status

    # ══════════════════════════════════════════════════════
    # Memory 集成
    # ══════════════════════════════════════════════════════

    def persist_evolution_record(
        self,
        task_id: str,
        task_type: str,
        outcome: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """将进化记录持久化到 memory 模块"""
        if not self._status.memory_available:
            return False

        try:
            from pycoder.memory import SessionMemoryEngine

            engine = SessionMemoryEngine()
            record = {
                "task_id": task_id,
                "task_type": task_type,
                "outcome": outcome,
                "details": details or {},
                "timestamp": time.time(),
            }
            engine.save("evolution", record)
            self._evolution_history.append(record)
            return True
        except Exception as e:
            logger.warning("Memory 集成失败: %s", e)
            return False

    def retrieve_evolution_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """从 memory 检索进化历史"""
        if not self._status.memory_available:
            return self._evolution_history[-limit:]

        try:
            from pycoder.memory import SessionMemoryEngine

            engine = SessionMemoryEngine()
            return engine.query("evolution", limit=limit) or []
        except Exception as e:
            logger.warning("Memory 查询失败: %s", e)
            return self._evolution_history[-limit:]

    # ══════════════════════════════════════════════════════
    # Plugins 集成
    # ══════════════════════════════════════════════════════

    def register_evolution_plugin(self, plugin_class: type) -> bool:
        """通过插件系统注册进化能力"""
        if not self._status.plugins_available:
            return False

        try:
            from pycoder.plugins.base import PluginRegistry

            registry = PluginRegistry()
            registry.register(plugin_class)
            logger.info("已注册进化插件: %s", plugin_class.__name__)
            return True
        except Exception as e:
            logger.warning("插件注册失败: %s", e)
            return False

    def get_evolution_plugins(self) -> list[str]:
        """获取已注册的进化插件"""
        if not self._status.plugins_available:
            return []

        try:
            from pycoder.plugins.base import PluginRegistry

            registry = PluginRegistry()
            return [p.__name__ for p in registry.get_all()]
        except Exception:
            return []

    # ══════════════════════════════════════════════════════
    # Observability 集成
    # ══════════════════════════════════════════════════════

    def track_evolution_event(
        self,
        event_name: str,
        properties: dict[str, Any] | None = None,
    ) -> bool:
        """追踪进化事件到 observability 模块"""
        if not self._status.observability_available:
            return False

        try:
            from pycoder.observability.sentry import SentryIntegration

            sentry = SentryIntegration()
            sentry.capture_event(
                event_name,
                properties or {},
                tags={"module": "self_evo", "event": event_name},
            )
            return True
        except Exception as e:
            logger.warning("Observability 集成失败: %s", e)
            return False

    def measure_evolution_effectiveness(
        self,
    ) -> dict[str, Any]:
        """评估进化效果

        返回: {
            "total_evolutions": ...,
            "success_rate": ...,
            "avg_quality_improvement": ...,
            "most_effective_type": ...,
        }
        """
        history = self.retrieve_evolution_history(limit=100)
        if not history:
            return {
                "total_evolutions": 0,
                "success_rate": 0.0,
                "avg_quality_improvement": 0.0,
                "most_effective_type": "N/A",
            }

        total = len(history)
        success = sum(1 for h in history if h.get("outcome") == "success")
        types = {}
        for h in history:
            t = h.get("task_type", "unknown")
            if t not in types:
                types[t] = {"total": 0, "success": 0}
            types[t]["total"] += 1
            if h.get("outcome") == "success":
                types[t]["success"] += 1

        best_type = max(types, key=lambda t: types[t]["success"] / max(types[t]["total"], 1), default="N/A")

        return {
            "total_evolutions": total,
            "success_rate": round(success / max(total, 1) * 100, 1),
            "avg_quality_improvement": 0.0,
            "most_effective_type": best_type,
        }

    # ══════════════════════════════════════════════════════
    # Safety 集成
    # ══════════════════════════════════════════════════════

    def sandbox_evolution(self, task_id: str, operation: str) -> bool:
        """在安全沙箱中执行进化操作

        防止:
          - 无限循环
          - 系统稳定性破坏
          - 未授权的文件修改
        """
        if not self._status.safety_available:
            logger.warning("Safety 模块不可用，进化操作将在无沙箱环境中执行")
            return True  # 允许继续但记录警告

        try:
            from pycoder.safety import SandboxManager, SandboxConfig
            from pycoder.safety.circuit_breaker import CircuitBreakerRegistry

            # 检查熔断器
            breaker = CircuitBreakerRegistry().get("self_evo")
            if breaker and breaker.is_open():
                logger.error("进化熔断器已打开，阻止进化操作")
                return False

            # 创建沙箱
            config = SandboxConfig(
                max_runtime_ms=300_000,  # 5分钟
                max_file_writes=3,
                allowed_dirs=["pycoder/"],
                banned_dirs=["__pycache__", ".git", "venv", ".venv", "node_modules"],
            )
            manager = SandboxManager(config)
            manager.enter(task_id)

            return True
        except Exception as e:
            logger.warning("Safety 沙箱集成失败: %s", e)
            return True  # 降级: 允许继续

    def record_evolution_rollback(self, task_id: str, reason: str) -> None:
        """记录进化回滚"""
        try:
            from pycoder.safety.rollback import RollbackManager

            manager = RollbackManager()
            manager.create_snapshot(task_id, {"reason": reason, "timestamp": time.time()})
            logger.info("进化回滚已记录: %s", task_id)
        except Exception as e:
            logger.warning("回滚记录失败: %s", e)

    def get_integration_status(self) -> IntegrationStatus:
        """获取当前集成状态"""
        return self._status


# 全局单例
_integration: EvolutionIntegration | None = None


def get_evolution_integration() -> EvolutionIntegration:
    global _integration
    if _integration is None:
        _integration = EvolutionIntegration()
    return _integration


__all__ = [
    "EvolutionIntegration",
    "IntegrationStatus",
    "get_evolution_integration",
]