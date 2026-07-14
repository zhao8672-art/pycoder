"""
安全与权限体系

Pycoder V2 的安全子系统，包括:
- 权限引擎: 五级渐进信任模型
- 沙箱管理: 进程/WASM/插件隔离
- 审计追踪: 不可变操作日志
- 回滚管理: 自动快照与恢复
- 熔断器: 异常检测与自动降级
"""

from pycoder.safety.permission import PermissionEngine, PermissionDecision
from pycoder.safety.sandbox import SandboxManager, SandboxConfig
from pycoder.safety.audit import AuditTrail, AuditRecord
from pycoder.safety.rollback import RollbackManager, Snapshot
from pycoder.safety.circuit_breaker import CircuitBreaker, CircuitState, CircuitBreakerRegistry

__all__ = [
    "PermissionEngine",
    "PermissionDecision",
    "SandboxManager",
    "SandboxConfig",
    "AuditTrail",
    "AuditRecord",
    "RollbackManager",
    "Snapshot",
    "CircuitBreaker",
    "CircuitState",
    "CircuitBreakerRegistry",
]
