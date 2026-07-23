"""PyCoder 安全代码执行沙箱 - 根级入口.

完整实现位于 `pycoder.safety` 子包, 此处重导出以便根级 `import safety` 访问.
"""

from pycoder.safety import (
    # 沙箱核心
    SandboxManager,
    SandboxConfig,
    # 权限
    PermissionEngine,
    PermissionDecision,
    # 审计
    AuditTrail,
    AuditRecord,
    # 弹性
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitState,
    RollbackManager,
    Snapshot,
)

__version__ = "0.5.0"
__all__ = [
    "SandboxManager",
    "SandboxConfig",
    "PermissionEngine",
    "PermissionDecision",
    "AuditTrail",
    "AuditRecord",
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "CircuitState",
    "RollbackManager",
    "Snapshot",
    "__version__",
]
