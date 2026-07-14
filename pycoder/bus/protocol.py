"""
协议定义 — 能力注册和调用的核心数据类型

定义了能力总线上的所有通信协议，包括：
- 能力定义的完整结构
- 调用请求/响应格式
- 执行模式和副作用分类
- 权限级别映射
"""

from __future__ import annotations

import enum
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

# ──────────────────────────────────────────────
# 枚举定义
# ──────────────────────────────────────────────


class CapabilityCategory(enum.StrEnum):
    """能力所属的功能域"""

    EDITOR = "editor"  # 编辑器能力：代码编辑、LSP、重构
    SYSTEM = "system"  # 系统能力：文件操作、Shell、Git
    SELF_EVO = "self_evo"  # 自进化能力：代码分析、自修复
    PLUGIN = "plugin"  # 动态插件能力


class ExecutionMode(enum.StrEnum):
    """能力执行的三种模式"""

    SYNC = "sync"  # 同步执行，立即返回结果
    STREAM = "stream"  # 流式执行，逐块返回
    ASYNC = "async"  # 异步执行，返回 task_id


class SideEffect(enum.StrEnum):
    """操作的副作用类型"""

    NONE = "none"  # 无副作用（只读）
    FILE_READ = "file_read"  # 读取文件
    FILE_WRITE = "file_write"  # 写入文件
    FILE_DELETE = "file_delete"  # 删除文件
    NETWORK = "network"  # 网络请求
    PROCESS = "process"  # 进程操作
    SYSTEM = "system"  # 系统级操作
    SELF_MODIFY = "self_modify"  # 修改自身代码


class TrustLevel(int, enum.Enum):
    """五级渐进信任模型"""

    READ_ONLY = 0  # 只读：文件读取、代码分析
    WORKSPACE_WRITE = 1  # 工作区写入：创建/编辑文件
    PROJECT_WRITE = 2  # 项目写入：Git、测试、Shell
    SYSTEM_ACCESS = 3  # 系统访问：包管理、网络
    FULL_AUTONOMY = 4  # 完全自主：修改自身代码、重启服务


# 权限级别到副作用类型的映射
PERMISSION_SIDE_EFFECT_MAP: dict[TrustLevel, set[SideEffect]] = {
    TrustLevel.READ_ONLY: {SideEffect.NONE, SideEffect.FILE_READ},
    TrustLevel.WORKSPACE_WRITE: {SideEffect.NONE, SideEffect.FILE_READ, SideEffect.FILE_WRITE},
    TrustLevel.PROJECT_WRITE: {
        SideEffect.NONE,
        SideEffect.FILE_READ,
        SideEffect.FILE_WRITE,
        SideEffect.FILE_DELETE,
        SideEffect.PROCESS,
    },
    TrustLevel.SYSTEM_ACCESS: {
        SideEffect.NONE,
        SideEffect.FILE_READ,
        SideEffect.FILE_WRITE,
        SideEffect.FILE_DELETE,
        SideEffect.PROCESS,
        SideEffect.NETWORK,
    },
    TrustLevel.FULL_AUTONOMY: set(SideEffect),  # 所有副作用
}


# ──────────────────────────────────────────────
# 核心数据类型
# ──────────────────────────────────────────────


@dataclass
class RetryPolicy:
    """重试策略"""

    max_retries: int = 2
    backoff_multiplier: float = 1.5
    retryable_exceptions: tuple[type[Exception], ...] = (TimeoutError, ConnectionError)
    max_delay_seconds: float = 30.0


@dataclass
class CapabilityDefinition:
    """
    能力定义 —— 每个模块向总线注册时必须提供的信息

    示例:
        CapabilityDefinition(
            id="editor.code.read",
            name="读取代码文件",
            description="读取指定路径的源代码文件内容",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_READ],
        )
    """

    id: str  # 唯一标识，使用点分隔命名: "domain.subdomain.action"
    name: str  # 人类可读的名称
    description: str  # 功能描述（供 AI 理解能力用途）
    category: CapabilityCategory  # 所属功能域
    permission: TrustLevel  # 所需的最低权限级别
    execution: ExecutionMode = ExecutionMode.SYNC  # 执行模式
    side_effects: list[SideEffect] = field(default_factory=lambda: [SideEffect.NONE])

    # 可选元数据
    version: str = "1.0.0"
    timeout_ms: int = 30000
    retry_policy: RetryPolicy | None = None
    rollback_support: bool = False  # 是否支持回滚
    schema: dict[str, Any] = field(default_factory=dict)  # JSON Schema
    tags: list[str] = field(default_factory=list)
    deprecated: bool = False
    deprecated_message: str = ""

    def __hash__(self) -> int:
        return hash(self.id)

    def to_mcp_tool_schema(self) -> dict[str, Any]:
        """转换为 MCP 工具格式"""
        return {
            "name": self.id.replace(".", "_"),
            "description": self.description,
            "inputSchema": self.schema
            or {
                "type": "object",
                "properties": {},
            },
        }

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于 JSON 序列化）"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": (
                self.category.value if hasattr(self.category, "value") else str(self.category)
            ),
            "permission": (
                self.permission.name if hasattr(self.permission, "name") else str(self.permission)
            ),
            "execution": (
                self.execution.value if hasattr(self.execution, "value") else str(self.execution)
            ),
            "tags": self.tags,
            "version": self.version,
            "deprecated": self.deprecated,
        }


@dataclass
class CapabilityCall:
    """一次能力调用的请求"""

    capability_id: str
    params: dict[str, Any]
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    caller: str = "ai_brain"
    timestamp: float = field(default_factory=time.time)
    timeout_ms: int | None = None
    mode_override: ExecutionMode | None = None


@dataclass
class CapabilityResult:
    """能力调用的结果"""

    trace_id: str
    capability_id: str
    success: bool
    data: Any = None
    error: str | None = None
    error_code: str | None = None
    duration_ms: float = 0.0
    side_effects_applied: list[SideEffect] = field(default_factory=list)
    rollback_id: str | None = None  # 如果支持回滚，提供回滚 ID
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CapabilityEvent:
    """流式执行中的单个事件"""

    trace_id: str
    event_type: str  # "data" | "progress" | "error" | "done"
    data: Any = None
    progress_pct: float = 0.0
    message: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class CallTrace:
    """全链路追踪记录"""

    trace_id: str
    capability_id: str
    params_summary: str
    permission_required: TrustLevel
    permission_granted: bool
    user_confirmed: bool
    success: bool
    duration_ms: float
    error: str | None = None
    sandbox_used: bool = False
    rollback_triggered: bool = False
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    caller: str = "unknown"


# ──────────────────────────────────────────────
# 处理器协议
# ──────────────────────────────────────────────


class CapabilityHandler(Protocol):
    """能力处理器协议 —— 每个能力实现必须符合此接口"""

    async def __call__(self, params: dict[str, Any], context: dict[str, Any]) -> Any:
        """
        同步处理：接收参数和上下文，返回结果

        Args:
            params: 能力调用的参数
            context: 执行上下文（包含 trace_id, caller, permission 等）

        Returns:
            能力执行的结果数据

        Raises:
            CapabilityError: 能力执行失败时抛出
        """
        ...


class StreamCapabilityHandler(Protocol):
    """流式能力处理器协议"""

    async def __call__(
        self, params: dict[str, Any], context: dict[str, Any]
    ) -> AsyncIterator[CapabilityEvent]:
        """流式处理：yield 事件序列"""
        ...
        yield  # type: ignore


# ──────────────────────────────────────────────
# 协议适配器接口
# ──────────────────────────────────────────────


class ProtocolAdapter(Protocol):
    """协议适配器 —— 将外部协议转换为总线内部调用"""

    async def translate_request(self, raw_request: Any) -> CapabilityCall:
        """将外部协议的请求翻译为内部 CapabilityCall"""
        ...

    async def translate_response(self, result: CapabilityResult) -> Any:
        """将内部 CapabilityResult 翻译为外部协议格式"""
        ...

    @property
    def protocol_name(self) -> str:
        """协议名称"""
        ...


# ──────────────────────────────────────────────
# 实现
# ──────────────────────────────────────────────


class MCPAdapter:
    """MCP (Model Context Protocol) v2 适配器"""

    protocol_name = "mcp_v2"

    async def translate_request(self, raw_request: dict[str, Any]) -> CapabilityCall:
        return CapabilityCall(
            capability_id=raw_request.get("name", "").replace("_", "."),
            params=raw_request.get("arguments", {}),
            trace_id=raw_request.get("_meta", {}).get("trace_id", str(uuid.uuid4())),
        )

    async def translate_response(self, result: CapabilityResult) -> dict[str, Any]:
        response: dict[str, Any] = {
            "content": [{"type": "text", "text": str(result.data) if result.data else ""}],
        }
        if not result.success:
            response["isError"] = True
            response["content"][0]["text"] = result.error or "Unknown error"
        return response


class GRPCAdapter:
    """gRPC 适配器（高性能内部通信）"""

    protocol_name = "grpc"

    async def translate_request(self, raw_request: Any) -> CapabilityCall:
        return CapabilityCall(
            capability_id=getattr(raw_request, "capability_id", ""),
            params=getattr(raw_request, "params", {}),
            trace_id=getattr(raw_request, "trace_id", str(uuid.uuid4())),
        )

    async def translate_response(self, result: CapabilityResult) -> dict[str, Any]:
        return {
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "trace_id": result.trace_id,
        }


class InternalAdapter:
    """内部模块直接调用适配器 —— 零开销"""

    protocol_name = "internal"

    async def translate_request(self, raw_request: CapabilityCall) -> CapabilityCall:
        return raw_request

    async def translate_response(self, result: CapabilityResult) -> CapabilityResult:
        return result
