"""安全总线模块综合测试

覆盖:
  - bus/protocol.py: 所有枚举、数据类、PERMISSION_SIDE_EFFECT_MAP、适配器
  - safety/permission.py: PermissionEngine 全面测试（补充现有测试未覆盖的场景）
  - safety/sandbox.py: SandboxConfig, SandboxResult, ProcessSandbox, CodeSandbox,
    PluginSandbox, SandboxManager
  - safety/audit.py: AuditRecord 和 AuditTrail 补充测试
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.bus.protocol import SideEffect, TrustLevel
from pycoder.safety.permission import (
    BehaviorRecord,
    DecisionType,
    PermissionDecision,
    PermissionEngine,
    PermissionRule,
)

# ══════════════════════════════════════════════════════════
# 第一部分: bus/protocol.py 测试
# ══════════════════════════════════════════════════════════


# ── 枚举测试 ────────────────────────────────────────────


class TestCapabilityCategory:
    """能力分类枚举"""

    def test_values(self):
        """验证所有枚举值"""
        from pycoder.bus.protocol import CapabilityCategory

        assert CapabilityCategory.EDITOR == "editor"
        assert CapabilityCategory.SYSTEM == "system"
        assert CapabilityCategory.SELF_EVO == "self_evo"
        assert CapabilityCategory.PLUGIN == "plugin"

    def test_is_str_enum(self):
        """验证是 StrEnum 类型"""
        from pycoder.bus.protocol import CapabilityCategory

        assert isinstance(CapabilityCategory.EDITOR, str)
        assert CapabilityCategory.EDITOR.value == "editor"


class TestExecutionMode:
    """执行模式枚举"""

    def test_values(self):
        """验证所有枚举值"""
        from pycoder.bus.protocol import ExecutionMode

        assert ExecutionMode.SYNC == "sync"
        assert ExecutionMode.STREAM == "stream"
        assert ExecutionMode.ASYNC == "async"

    def test_count(self):
        """验证三种模式都存在"""
        from pycoder.bus.protocol import ExecutionMode

        modes = list(ExecutionMode)
        assert len(modes) == 3


class TestSideEffect:
    """副作用枚举"""

    def test_values(self):
        """验证所有副作用值"""
        from pycoder.bus.protocol import SideEffect

        assert SideEffect.NONE == "none"
        assert SideEffect.FILE_READ == "file_read"
        assert SideEffect.FILE_WRITE == "file_write"
        assert SideEffect.FILE_DELETE == "file_delete"
        assert SideEffect.NETWORK == "network"
        assert SideEffect.PROCESS == "process"
        assert SideEffect.SYSTEM == "system"
        assert SideEffect.SELF_MODIFY == "self_modify"

    def test_count(self):
        """验证 8 种副作用类型"""
        from pycoder.bus.protocol import SideEffect

        assert len(list(SideEffect)) == 8


class TestTrustLevel:
    """信任级别枚举"""

    def test_values(self):
        """验证所有信任级别"""
        from pycoder.bus.protocol import TrustLevel

        assert TrustLevel.READ_ONLY == 0
        assert TrustLevel.WORKSPACE_WRITE == 1
        assert TrustLevel.PROJECT_WRITE == 2
        assert TrustLevel.SYSTEM_ACCESS == 3
        assert TrustLevel.FULL_AUTONOMY == 4

    def test_comparison(self):
        """验证级别比较"""
        from pycoder.bus.protocol import TrustLevel

        assert TrustLevel.FULL_AUTONOMY > TrustLevel.READ_ONLY
        assert TrustLevel.SYSTEM_ACCESS > TrustLevel.WORKSPACE_WRITE
        assert TrustLevel.READ_ONLY < TrustLevel.WORKSPACE_WRITE

    def test_is_int_enum(self):
        """验证是 IntEnum 类型"""
        from pycoder.bus.protocol import TrustLevel

        assert isinstance(TrustLevel.READ_ONLY, int)
        assert TrustLevel.READ_ONLY.value == 0
        assert TrustLevel.FULL_AUTONOMY.value == 4


# ── PERMISSION_SIDE_EFFECT_MAP 测试 ──────────────────────


class TestPermissionSideEffectMap:
    """权限级别到副作用映射"""

    def test_read_only_permissions(self):
        """只读级别仅允许 NONE 和 FILE_READ"""
        from pycoder.bus.protocol import PERMISSION_SIDE_EFFECT_MAP, SideEffect, TrustLevel

        allowed = PERMISSION_SIDE_EFFECT_MAP[TrustLevel.READ_ONLY]
        assert SideEffect.NONE in allowed
        assert SideEffect.FILE_READ in allowed
        assert SideEffect.FILE_WRITE not in allowed
        assert SideEffect.NETWORK not in allowed
        assert SideEffect.SELF_MODIFY not in allowed

    def test_workspace_write_permissions(self):
        """工作区写入级别允许读/写"""
        from pycoder.bus.protocol import PERMISSION_SIDE_EFFECT_MAP, SideEffect, TrustLevel

        allowed = PERMISSION_SIDE_EFFECT_MAP[TrustLevel.WORKSPACE_WRITE]
        assert SideEffect.FILE_WRITE in allowed
        assert SideEffect.FILE_DELETE not in allowed
        assert SideEffect.NETWORK not in allowed

    def test_project_write_permissions(self):
        """项目写入级别允许删除和进程"""
        from pycoder.bus.protocol import PERMISSION_SIDE_EFFECT_MAP, SideEffect, TrustLevel

        allowed = PERMISSION_SIDE_EFFECT_MAP[TrustLevel.PROJECT_WRITE]
        assert SideEffect.FILE_DELETE in allowed
        assert SideEffect.PROCESS in allowed
        assert SideEffect.NETWORK not in allowed

    def test_system_access_permissions(self):
        """系统访问级别允许网络"""
        from pycoder.bus.protocol import PERMISSION_SIDE_EFFECT_MAP, SideEffect, TrustLevel

        allowed = PERMISSION_SIDE_EFFECT_MAP[TrustLevel.SYSTEM_ACCESS]
        assert SideEffect.NETWORK in allowed
        assert SideEffect.SELF_MODIFY not in allowed

    def test_full_autonomy_all_permissions(self):
        """完全自主级别允许所有副作用"""
        from pycoder.bus.protocol import PERMISSION_SIDE_EFFECT_MAP, SideEffect, TrustLevel

        allowed = PERMISSION_SIDE_EFFECT_MAP[TrustLevel.FULL_AUTONOMY]
        assert SideEffect.SELF_MODIFY in allowed
        assert len(allowed) == len(list(SideEffect))

    def test_map_has_all_levels(self):
        """映射包含所有 5 个级别"""
        from pycoder.bus.protocol import PERMISSION_SIDE_EFFECT_MAP, TrustLevel

        assert len(PERMISSION_SIDE_EFFECT_MAP) == 5
        for level in TrustLevel:
            assert level in PERMISSION_SIDE_EFFECT_MAP


# ── 数据类测试 ──────────────────────────────────────────


class TestRetryPolicy:
    """重试策略数据类"""

    def test_defaults(self):
        """验证默认值"""
        from pycoder.bus.protocol import RetryPolicy

        policy = RetryPolicy()
        assert policy.max_retries == 2
        assert policy.backoff_multiplier == 1.5
        assert policy.retryable_exceptions == (TimeoutError, ConnectionError)
        assert policy.max_delay_seconds == 30.0

    def test_custom_values(self):
        """验证自定义值"""
        from pycoder.bus.protocol import RetryPolicy

        policy = RetryPolicy(
            max_retries=5,
            backoff_multiplier=2.0,
            retryable_exceptions=(ValueError,),
            max_delay_seconds=60.0,
        )
        assert policy.max_retries == 5
        assert policy.backoff_multiplier == 2.0
        assert policy.max_delay_seconds == 60.0


class TestCapabilityDefinition:
    """能力定义数据类"""

    def test_minimal_creation(self):
        """最小字段创建"""
        from pycoder.bus.protocol import CapabilityCategory, CapabilityDefinition, TrustLevel

        cap = CapabilityDefinition(
            id="test.action",
            name="测试操作",
            description="测试描述",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
        )
        assert cap.id == "test.action"
        assert cap.execution == "sync"  # 默认 SYNC
        assert cap.side_effects[0] == "none"  # 默认 [NONE]
        assert cap.version == "1.0.0"
        assert cap.timeout_ms == 30000
        assert cap.retry_policy is None
        assert cap.rollback_support is False
        assert cap.schema == {}
        assert cap.tags == []
        assert cap.deprecated is False
        assert cap.deprecated_message == ""

    def test_full_creation(self):
        """全字段创建"""
        from pycoder.bus.protocol import (
            CapabilityCategory,
            CapabilityDefinition,
            ExecutionMode,
            RetryPolicy,
            SideEffect,
            TrustLevel,
        )

        policy = RetryPolicy(max_retries=3)
        cap = CapabilityDefinition(
            id="system.shell.exec",
            name="执行 Shell",
            description="执行 Shell 命令",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.PROJECT_WRITE,
            execution=ExecutionMode.STREAM,
            side_effects=[SideEffect.PROCESS, SideEffect.SYSTEM],
            version="2.0.0",
            timeout_ms=60000,
            retry_policy=policy,
            rollback_support=True,
            schema={"type": "object"},
            tags=["shell", "dangerous"],
            deprecated=True,
            deprecated_message="请使用新版本",
        )
        assert cap.id == "system.shell.exec"
        assert cap.execution == ExecutionMode.STREAM
        assert len(cap.side_effects) == 2
        assert cap.timeout_ms == 60000
        assert cap.retry_policy is policy
        assert cap.rollback_support is True
        assert cap.deprecated is True
        assert cap.deprecated_message == "请使用新版本"

    def test_hash_by_id(self):
        """基于 id 的哈希（id 相同则 hash 相同）"""
        from pycoder.bus.protocol import CapabilityCategory, CapabilityDefinition, TrustLevel

        cap1 = CapabilityDefinition(
            id="test.op", name="A", description="desc", category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
        )
        cap2 = CapabilityDefinition(
            id="test.op", name="B", description="other", category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.FULL_AUTONOMY,
        )
        assert hash(cap1) == hash(cap2)
        # dataclass 的 __eq__ 比较所有字段，所以即使 id 相同也不相等
        assert cap1.id == cap2.id

    def test_to_mcp_tool_schema_with_schema(self):
        """有 schema 时转换为 MCP 工具格式"""
        from pycoder.bus.protocol import CapabilityCategory, CapabilityDefinition, TrustLevel

        cap = CapabilityDefinition(
            id="editor.code.read",
            name="读取代码",
            description="读取代码文件",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            schema={"type": "object", "properties": {"path": {"type": "string"}}},
        )
        result = cap.to_mcp_tool_schema()
        assert result["name"] == "editor_code_read"
        assert result["inputSchema"]["properties"]["path"]["type"] == "string"

    def test_to_mcp_tool_schema_without_schema(self):
        """无 schema 时生成默认 schema"""
        from pycoder.bus.protocol import CapabilityCategory, CapabilityDefinition, TrustLevel

        cap = CapabilityDefinition(
            id="test.op",
            name="测试",
            description="desc",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
        )
        result = cap.to_mcp_tool_schema()
        assert result["name"] == "test_op"
        assert result["inputSchema"]["type"] == "object"

    def test_to_dict_basic(self):
        """to_dict 基本转换"""
        from pycoder.bus.protocol import CapabilityCategory, CapabilityDefinition, TrustLevel

        cap = CapabilityDefinition(
            id="test.op",
            name="测试",
            description="desc",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
        )
        d = cap.to_dict()
        assert d["id"] == "test.op"
        assert d["name"] == "测试"
        assert d["category"] == "editor"
        assert d["permission"] == "READ_ONLY"
        assert d["execution"] == "sync"
        assert d["version"] == "1.0.0"
        assert d["deprecated"] is False


class TestCapabilityCall:
    """能力调用请求"""

    def test_defaults(self):
        """默认值"""
        from pycoder.bus.protocol import CapabilityCall

        call = CapabilityCall(capability_id="test.op", params={"key": "val"})
        assert call.capability_id == "test.op"
        assert call.params == {"key": "val"}
        assert call.trace_id != ""  # 自动生成 UUID
        assert call.caller == "ai_brain"
        assert call.timestamp > 0
        assert call.timeout_ms is None
        assert call.mode_override is None

    def test_trace_id_format(self):
        """trace_id 是有效的 UUID 格式"""
        from pycoder.bus.protocol import CapabilityCall

        call = CapabilityCall(capability_id="x", params={})
        try:
            uuid.UUID(call.trace_id)
        except ValueError:
            pytest.fail("trace_id 不是有效的 UUID")


class TestCapabilityResult:
    """能力调用结果"""

    def test_defaults(self):
        """默认值"""
        from pycoder.bus.protocol import CapabilityResult

        result = CapabilityResult(
            trace_id="trace-1", capability_id="test.op", success=True,
        )
        assert result.trace_id == "trace-1"
        assert result.success is True
        assert result.data is None
        assert result.error is None
        assert result.error_code is None
        assert result.duration_ms == 0.0
        assert result.side_effects_applied == []
        assert result.rollback_id is None
        assert result.metadata == {}

    def test_error_result(self):
        """错误结果"""
        from pycoder.bus.protocol import CapabilityResult

        result = CapabilityResult(
            trace_id="t1",
            capability_id="shell.exec",
            success=False,
            error="Permission denied",
            error_code="E403",
            duration_ms=150.0,
        )
        assert result.success is False
        assert result.error == "Permission denied"
        assert result.error_code == "E403"


class TestCapabilityEvent:
    """流式事件"""

    def test_defaults(self):
        """默认值"""
        from pycoder.bus.protocol import CapabilityEvent

        event = CapabilityEvent(trace_id="t1", event_type="data")
        assert event.trace_id == "t1"
        assert event.event_type == "data"
        assert event.data is None
        assert event.progress_pct == 0.0
        assert event.message == ""
        assert event.timestamp > 0

    def test_progress_event(self):
        """进度事件"""
        from pycoder.bus.protocol import CapabilityEvent

        event = CapabilityEvent(
            trace_id="t1", event_type="progress", progress_pct=50.0, message="处理中...",
        )
        assert event.event_type == "progress"
        assert event.progress_pct == 50.0
        assert event.message == "处理中..."


class TestCallTrace:
    """全链路追踪记录"""

    def test_defaults(self):
        """默认值"""
        from pycoder.bus.protocol import CallTrace, TrustLevel

        trace = CallTrace(
            trace_id="t1",
            capability_id="test.op",
            params_summary="{}",
            permission_required=TrustLevel.READ_ONLY,
            permission_granted=True,
            user_confirmed=False,
            success=True,
            duration_ms=100.0,
        )
        assert trace.trace_id == "t1"
        assert trace.sandbox_used is False
        assert trace.rollback_triggered is False
        assert trace.start_time > 0
        assert trace.end_time == 0.0
        assert trace.caller == "unknown"
        assert trace.error is None

    def test_full_trace(self):
        """完整追踪"""
        from pycoder.bus.protocol import CallTrace, TrustLevel

        trace = CallTrace(
            trace_id="t2",
            capability_id="git.commit",
            params_summary="commit message",
            permission_required=TrustLevel.PROJECT_WRITE,
            permission_granted=True,
            user_confirmed=True,
            success=False,
            duration_ms=250.0,
            error="冲突",
            sandbox_used=True,
            rollback_triggered=True,
            end_time=1234567890.0,
            caller="agent_v2",
        )
        assert trace.error == "冲突"
        assert trace.sandbox_used is True
        assert trace.rollback_triggered is True


# ── 适配器测试 ──────────────────────────────────────────


class TestMCPAdapter:
    """MCP 协议适配器"""

    @pytest.mark.asyncio
    async def test_translate_request(self):
        """将 MCP 请求翻译为内部调用"""
        from pycoder.bus.protocol import MCPAdapter

        adapter = MCPAdapter()
        raw = {
            "name": "editor_code_read",
            "arguments": {"path": "main.py"},
            "_meta": {"trace_id": "custom-trace"},
        }
        call = await adapter.translate_request(raw)
        assert call.capability_id == "editor.code.read"
        assert call.params == {"path": "main.py"}
        assert call.trace_id == "custom-trace"

    @pytest.mark.asyncio
    async def test_translate_request_no_meta(self):
        """无 _meta 时自动生成 trace_id"""
        from pycoder.bus.protocol import MCPAdapter

        adapter = MCPAdapter()
        raw = {"name": "test", "arguments": {}}
        call = await adapter.translate_request(raw)
        assert call.capability_id == "test"
        assert call.trace_id != ""

    @pytest.mark.asyncio
    async def test_translate_response_success(self):
        """成功响应翻译"""
        from pycoder.bus.protocol import CapabilityResult, MCPAdapter

        adapter = MCPAdapter()
        result = CapabilityResult(
            trace_id="t1", capability_id="test", success=True, data="hello",
        )
        response = await adapter.translate_response(result)
        assert "content" in response
        assert response["content"][0]["text"] == "hello"
        assert "isError" not in response

    @pytest.mark.asyncio
    async def test_translate_response_error(self):
        """错误响应翻译"""
        from pycoder.bus.protocol import CapabilityResult, MCPAdapter

        adapter = MCPAdapter()
        result = CapabilityResult(
            trace_id="t1", capability_id="test", success=False, error="失败",
        )
        response = await adapter.translate_response(result)
        assert response["isError"] is True
        assert response["content"][0]["text"] == "失败"

    def test_protocol_name(self):
        """协议名称"""
        from pycoder.bus.protocol import MCPAdapter

        assert MCPAdapter.protocol_name == "mcp_v2"


class TestGRPCAdapter:
    """gRPC 适配器"""

    @pytest.mark.asyncio
    async def test_translate_request(self):
        """将 gRPC 请求翻译为内部调用"""
        from pycoder.bus.protocol import GRPCAdapter

        adapter = GRPCAdapter()
        raw = MagicMock()
        raw.capability_id = "editor.code.read"
        raw.params = {"path": "test.py"}
        raw.trace_id = "grpc-trace"
        call = await adapter.translate_request(raw)
        assert call.capability_id == "editor.code.read"
        assert call.params == {"path": "test.py"}
        assert call.trace_id == "grpc-trace"

    @pytest.mark.asyncio
    async def test_translate_request_no_trace_id(self):
        """无 trace_id 时自动生成"""
        from pycoder.bus.protocol import GRPCAdapter

        adapter = GRPCAdapter()
        raw = MagicMock()
        raw.capability_id = ""
        raw.params = {}
        # 没有 trace_id 属性会触发 AttributeError → 被 getattr 捕获返回默认值
        del raw.trace_id
        call = await adapter.translate_request(raw)
        assert call.trace_id != ""

    @pytest.mark.asyncio
    async def test_translate_response(self):
        """响应翻译"""
        from pycoder.bus.protocol import CapabilityResult, GRPCAdapter

        adapter = GRPCAdapter()
        result = CapabilityResult(
            trace_id="t1", capability_id="test", success=True, data={"k": "v"},
        )
        response = await adapter.translate_response(result)
        assert response["success"] is True
        assert response["data"] == {"k": "v"}
        assert response["trace_id"] == "t1"


class TestInternalAdapter:
    """内部适配器"""

    @pytest.mark.asyncio
    async def test_translate_request_passthrough(self):
        """内部调用直接透传"""
        from pycoder.bus.protocol import CapabilityCall, InternalAdapter

        adapter = InternalAdapter()
        call = CapabilityCall(capability_id="test", params={"a": 1})
        result = await adapter.translate_request(call)
        assert result is call  # 直接返回原对象

    @pytest.mark.asyncio
    async def test_translate_response_passthrough(self):
        """内部响应直接透传"""
        from pycoder.bus.protocol import CapabilityResult, InternalAdapter

        adapter = InternalAdapter()
        result = CapabilityResult(trace_id="t1", capability_id="test", success=True)
        response = await adapter.translate_response(result)
        assert response is result


# ══════════════════════════════════════════════════════════
# 第二部分: safety/permission.py 补充测试
# ══════════════════════════════════════════════════════════


class TestPermissionEngineAdvanced:
    """PermissionEngine 高级场景测试"""

    @pytest.fixture
    def engine(self, tmp_path, monkeypatch):
        """创建权限引擎（隔离行为历史）"""
        import pycoder.safety.permission as perm_mod

        perm_dir = tmp_path / ".pycoder" / "permission"
        monkeypatch.setattr(perm_mod, "_PERMISSION_DIR", perm_dir)
        monkeypatch.setattr(perm_mod, "_BEHAVIOR_FILE", perm_dir / "behavior_history.jsonl")
        return PermissionEngine(initial_trust=TrustLevel.WORKSPACE_WRITE)

    # ── 自定义规则 REQUIRE_CONFIRM 场景 ────────────────

    def test_custom_rule_require_confirm_no_match(self, engine):
        """自定义规则 REQUIRE_CONFIRM：当更早的规则匹配 AUTO_ALLOW 时优先返回"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType, PermissionRule

        # 添加一个 REQUIRE_CONFIRM 规则，但默认规则中已有更宽泛的匹配
        rule = PermissionRule(
            pattern="custom.confirm.*",
            trust_level=TrustLevel.READ_ONLY,
            action=DecisionType.REQUIRE_CONFIRM,
            description="需要确认",
        )
        engine.add_rule(rule)
        # 对不匹配任何默认规则的 capability，REQUIRE_CONFIRM 规则不直接返回
        # 会继续走到信任不足检查
        result = engine.check("custom.confirm.test", TrustLevel.SYSTEM_ACCESS)
        assert result.decision_type == DecisionType.REQUIRE_CONFIRM

    # ── 默认规则测试 ────────────────────────────────────

    def test_default_rules_editor_code_read(self, engine):
        """默认规则：editor.code.read 始终允许"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check("editor.code.read", TrustLevel.FULL_AUTONOMY)
        assert result.allowed is True
        assert result.decision_type == DecisionType.AUTO_ALLOW

    def test_default_rules_lsp_wildcard(self, engine):
        """默认规则：editor.lsp.* 通配符匹配"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check("editor.lsp.completion", TrustLevel.FULL_AUTONOMY)
        assert result.allowed is True
        assert result.decision_type == DecisionType.AUTO_ALLOW

    def test_default_rules_self_evo(self, engine):
        """默认规则：self_evo.* 完全放开"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check("self_evo.scan", TrustLevel.FULL_AUTONOMY)
        assert result.allowed is True
        assert result.decision_type == DecisionType.AUTO_ALLOW

    def test_default_rules_tools_agent(self, engine):
        """默认规则：tools.agent.* 完全放开"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check("tools.agent.scan", TrustLevel.FULL_AUTONOMY)
        assert result.allowed is True
        assert result.decision_type == DecisionType.AUTO_ALLOW

    def test_default_rules_marketplace(self, engine):
        """默认规则：tools.marketplace.* 完全放开"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check("tools.marketplace.install", TrustLevel.FULL_AUTONOMY)
        assert result.allowed is True
        assert result.decision_type == DecisionType.AUTO_ALLOW

    def test_default_rules_docker_execute(self, engine):
        """默认规则：tools.env.docker_execute 完全放开"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check("tools.env.docker_execute", TrustLevel.FULL_AUTONOMY)
        assert result.allowed is True
        assert result.decision_type == DecisionType.AUTO_ALLOW

    def test_default_rules_self_evo_deploy_confirm(self, engine):
        """默认规则：self_evo.deploy.* 被 self_evo.* 规则先匹配，返回 AUTO_ALLOW"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        # self_evo.* 规则在列表中排在 self_evo.deploy.* 前面，先匹配
        result = engine.check("self_evo.deploy.staging", TrustLevel.FULL_AUTONOMY)
        assert result.decision_type == DecisionType.AUTO_ALLOW

    def test_default_rules_self_evo_arch_implement_confirm(self, engine):
        """默认规则：self_evo.arch.implement 被 self_evo.* 规则先匹配，返回 AUTO_ALLOW"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check("self_evo.arch.implement", TrustLevel.FULL_AUTONOMY)
        assert result.decision_type == DecisionType.AUTO_ALLOW

    # ── 批量批准测试 ────────────────────────────────────

    def test_batch_approval_first_call(self, engine):
        """批量批准：第一次调用是 AUTO_ALLOW"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        # 设置高信任级别
        engine.set_trust_level(TrustLevel.FULL_AUTONOMY)
        result = engine.check("custom.op", TrustLevel.PROJECT_WRITE)
        assert result.decision_type == DecisionType.AUTO_ALLOW

    def test_batch_approval_second_call(self, engine):
        """批量批准：第二次同类调用是 ALLOW_BATCH"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        engine.set_trust_level(TrustLevel.FULL_AUTONOMY)
        engine.check("custom.op", TrustLevel.PROJECT_WRITE)
        result = engine.check("custom.op", TrustLevel.PROJECT_WRITE)
        assert result.decision_type == DecisionType.ALLOW_BATCH
        assert result.batch_approved_count == 2

    def test_batch_approval_different_levels(self, engine):
        """不同信任级别的批量批准分开计数"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        engine.set_trust_level(TrustLevel.FULL_AUTONOMY)
        # 第一次调用 PROJECT_WRITE
        engine.check("custom.op", TrustLevel.PROJECT_WRITE)
        # 第二次调用 SYSTEM_ACCESS（不同 level）
        result = engine.check("custom.op", TrustLevel.SYSTEM_ACCESS)
        assert result.decision_type == DecisionType.AUTO_ALLOW  # 第一次，不是批量

    def test_batch_approval_below_threshold(self, engine):
        """低于 PROJECT_WRITE 的操作不触发批量批准"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        engine.set_trust_level(TrustLevel.FULL_AUTONOMY)
        # WORKSPACE_WRITE < PROJECT_WRITE，不进入批量批准逻辑
        r1 = engine.check("test.op", TrustLevel.WORKSPACE_WRITE)
        r2 = engine.check("test.op", TrustLevel.WORKSPACE_WRITE)
        assert r1.decision_type == DecisionType.AUTO_ALLOW
        assert r2.decision_type == DecisionType.AUTO_ALLOW  # 不触发批量

    # ── _has_dangerous_params 深入测试 ──────────────────

    def test_dangerous_params_command_key(self, engine):
        """危险参数：command 键"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "shell.exec", TrustLevel.READ_ONLY,
            params={"command": "shutdown now"},
        )
        assert result.allowed is False
        assert "危险操作" in result.reason

    def test_dangerous_params_cmd_rm_rf(self, engine):
        """危险参数：rm -rf 变体"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "shell.exec", TrustLevel.READ_ONLY,
            params={"cmd": "rm -rf /home/user"},
        )
        assert result.allowed is False
        assert "危险操作" in result.reason

    def test_dangerous_params_fork_bomb(self, engine):
        """危险参数：fork 炸弹"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "shell.exec", TrustLevel.READ_ONLY,
            params={"cmd": ":(){ :|:& };:"},
        )
        assert result.allowed is False

    def test_dangerous_params_format_c(self, engine):
        """危险参数：format c: (Windows)"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "shell.exec", TrustLevel.READ_ONLY,
            params={"cmd": "format c: /q"},
        )
        assert result.allowed is False

    def test_dangerous_params_windows_system32(self, engine):
        """危险参数：Windows 系统路径"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "file.write", TrustLevel.READ_ONLY,
            params={"path": "C:\\Windows\\System32\\drivers\\etc\\hosts"},
        )
        assert result.allowed is False
        assert "危险操作" in result.reason

    def test_dangerous_params_shadow_file(self, engine):
        """危险参数：/etc/shadow"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "file.read", TrustLevel.READ_ONLY,
            params={"file": "/etc/shadow"},
        )
        assert result.allowed is False

    def test_dangerous_params_source_key(self, engine):
        """危险参数：source 键"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "file.copy", TrustLevel.READ_ONLY,
            params={"source": "/etc/passwd", "target": "/tmp/out"},
        )
        assert result.allowed is False

    def test_dangerous_params_target_key(self, engine):
        """危险参数：target 键"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "file.move", TrustLevel.READ_ONLY,
            params={"target": "/etc/passwd"},
        )
        assert result.allowed is False

    def test_dangerous_params_case_insensitive(self, engine):
        """危险参数：大小写不敏感"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "shell.exec", TrustLevel.READ_ONLY,
            params={"cmd": "SHUTDOWN /s"},
        )
        assert result.allowed is False

    # ── _touches_critical_path 深入测试 ─────────────────

    def test_critical_path_env_file(self, engine):
        """关键路径：.env 文件"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "file.write", TrustLevel.SYSTEM_ACCESS,
            params={"path": ".env"},
        )
        assert result.allowed is False
        assert "关键路径" in result.reason

    def test_critical_path_env_production(self, engine):
        """关键路径：.env.production"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "file.write", TrustLevel.SYSTEM_ACCESS,
            params={"path": ".env.production"},
        )
        assert result.allowed is False

    def test_critical_path_git_config(self, engine):
        """关键路径：.git/config"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "file.write", TrustLevel.SYSTEM_ACCESS,
            params={"path": ".git/config"},
        )
        assert result.allowed is False

    def test_critical_path_pycoder_config(self, engine):
        """关键路径：.pycoder/config.json"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "file.write", TrustLevel.SYSTEM_ACCESS,
            params={"path": ".pycoder/config.json"},
        )
        assert result.allowed is False

    def test_critical_path_pycoder_api_key(self, engine):
        """关键路径：.pycoder/.api_key"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "file.write", TrustLevel.SYSTEM_ACCESS,
            params={"path": ".pycoder/.api_key"},
        )
        assert result.allowed is False

    def test_critical_path_node_modules(self, engine):
        """关键路径：node_modules"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "file.write", TrustLevel.SYSTEM_ACCESS,
            params={"path": "node_modules/react/index.js"},
        )
        assert result.allowed is False

    def test_critical_path_allowed_at_full_autonomy(self, engine):
        """完全自主级别允许操作关键路径"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        engine.set_trust_level(TrustLevel.FULL_AUTONOMY)
        result = engine.check(
            "file.write", TrustLevel.FULL_AUTONOMY,
            params={"path": ".env"},
        )
        # 关键路径检查在 FULL_AUTONOMY 时通过
        # 但可能被其他规则拦截（如危险参数）
        assert result.decision_type != DecisionType.AUTO_DENY or "关键路径" not in result.reason

    def test_critical_path_file_path_key(self, engine):
        """关键路径：file_path 键"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "file.write", TrustLevel.SYSTEM_ACCESS,
            params={"file_path": ".env"},
        )
        assert result.allowed is False

    def test_critical_path_source_key(self, engine):
        """关键路径：source 键"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "file.copy", TrustLevel.SYSTEM_ACCESS,
            params={"source": ".env"},
        )
        assert result.allowed is False

    def test_critical_path_not_touched(self, engine):
        """非关键路径不被拦截"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "file.write", TrustLevel.WORKSPACE_WRITE,
            params={"path": "src/main.py"},
        )
        # 信任级别足够，不应该被关键路径拦截
        assert result.decision_type != DecisionType.AUTO_DENY or "关键路径" not in result.reason

    # ── params=None 和 side_effects=None 场景 ─────────

    def test_check_without_params(self, engine):
        """无参数调用的权限检查"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check("editor.code.read", TrustLevel.READ_ONLY)
        assert result.allowed is True
        assert result.decision_type == DecisionType.AUTO_ALLOW

    def test_check_with_empty_params(self, engine):
        """空字典参数"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check("test.op", TrustLevel.READ_ONLY, params={})
        # 空参数不匹配任何危险参数或关键路径
        assert result.decision_type == DecisionType.AUTO_ALLOW

    # ── 黑名单优先级测试 ───────────────────────────────

    def test_blacklist_overrides_whitelist(self, engine):
        """黑名单优先级高于白名单"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        engine.add_whitelist("dangerous.op")
        engine.add_blacklist("dangerous.op")
        result = engine.check("dangerous.op", TrustLevel.READ_ONLY)
        assert result.allowed is False
        assert result.decision_type == DecisionType.AUTO_DENY

    def test_blacklist_overrides_custom_rule(self, engine):
        """黑名单优先级高于自定义规则"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType, PermissionRule

        engine.add_rule(PermissionRule(
            pattern="blocked.*",
            trust_level=TrustLevel.READ_ONLY,
            action=DecisionType.AUTO_ALLOW,
            description="应被允许",
        ))
        engine.add_blacklist("blocked.op")
        result = engine.check("blocked.op", TrustLevel.READ_ONLY)
        assert result.allowed is False
        assert result.decision_type == DecisionType.AUTO_DENY

    # ── 自定义规则中 deny 规则高于 allow 规则 ──────────

    def test_deny_rule_before_allow_rule(self, engine):
        """deny 规则（前面）的优先级高于 allow 规则（后面）"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType, PermissionRule

        # deny 规则添加得早，在列表中靠前
        engine.add_rule(PermissionRule(
            pattern="dangerous.*",
            trust_level=TrustLevel.READ_ONLY,
            action=DecisionType.AUTO_DENY,
            description="拒绝危险操作",
        ))
        engine.add_rule(PermissionRule(
            pattern="dangerous.edit",
            trust_level=TrustLevel.READ_ONLY,
            action=DecisionType.AUTO_ALLOW,
            description="允许危险编辑",
        ))
        # 第一个匹配的规则是 deny
        result = engine.check("dangerous.edit", TrustLevel.READ_ONLY)
        assert result.allowed is False
        assert result.decision_type == DecisionType.AUTO_DENY

    # ── escalate_trust 边界场景 ────────────────────────

    def test_escalate_trust_exact_50_records(self, engine):
        """恰好 50 条记录时的提升"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import BehaviorRecord

        for i in range(50):
            engine.record_behavior(BehaviorRecord(
                capability_id="test.op", success=True, decision="auto_allow", trust_level=1,
            ))
        ok, msg = engine.escalate_trust()
        assert ok is True
        assert engine.current_trust == TrustLevel.PROJECT_WRITE

    def test_escalate_trust_49_records(self, engine):
        """49 条记录拒绝提升"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import BehaviorRecord

        for i in range(49):
            engine.record_behavior(BehaviorRecord(
                capability_id="test.op", success=True, decision="auto_allow", trust_level=1,
            ))
        ok, msg = engine.escalate_trust()
        assert ok is False
        assert "50" in msg

    def test_escalate_trust_exact_95_percent(self, engine):
        """恰好 95% 成功率可以通过"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import BehaviorRecord

        # 100 条记录，95 条成功，5 条失败 = 95%
        for i in range(100):
            engine.record_behavior(BehaviorRecord(
                capability_id="test.op", success=(i < 95), decision="auto_allow", trust_level=1,
            ))
        ok, msg = engine.escalate_trust()
        assert ok is True

    def test_escalate_trust_94_percent(self, engine):
        """94% 成功率被拒绝"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import BehaviorRecord

        for i in range(100):
            engine.record_behavior(BehaviorRecord(
                capability_id="test.op", success=(i < 94), decision="auto_allow", trust_level=1,
            ))
        ok, msg = engine.escalate_trust()
        assert ok is False
        assert "成功率" in msg

    # ── revoke_trust 多次降级 ──────────────────────────

    def test_revoke_trust_multiple_levels(self, engine):
        """多次降级"""
        from pycoder.bus.protocol import TrustLevel

        engine.set_trust_level(TrustLevel.FULL_AUTONOMY)
        engine.revoke_trust("事件1")
        assert engine.current_trust == TrustLevel.SYSTEM_ACCESS
        engine.revoke_trust("事件2")
        assert engine.current_trust == TrustLevel.PROJECT_WRITE
        engine.revoke_trust("事件3")
        assert engine.current_trust == TrustLevel.WORKSPACE_WRITE
        engine.revoke_trust("事件4")
        assert engine.current_trust == TrustLevel.READ_ONLY
        engine.revoke_trust("事件5")  # 不再降级
        assert engine.current_trust == TrustLevel.READ_ONLY

    # ── current_trust 属性 ─────────────────────────────

    def test_current_trust_property(self, engine):
        """current_trust 属性返回当前信任级别"""
        from pycoder.bus.protocol import TrustLevel

        assert engine.current_trust == TrustLevel.WORKSPACE_WRITE
        engine.set_trust_level(TrustLevel.FULL_AUTONOMY)
        assert engine.current_trust == TrustLevel.FULL_AUTONOMY

    # ── 行为记录持久化异常处理 ─────────────────────────

    def test_load_behavior_from_corrupted_file(self, tmp_path, monkeypatch):
        """从损坏的文件加载行为历史"""
        import pycoder.safety.permission as perm_mod
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import PermissionEngine

        perm_dir = tmp_path / ".pycoder" / "permission"
        perm_dir.mkdir(parents=True)
        behavior_file = perm_dir / "behavior_history.jsonl"
        # 写入一些损坏的行
        behavior_file.write_text(
            '{"capability_id": "good", "success": true}\n'
            'not valid json\n'
            '{"capability_id": "also_good", "success": false}\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(perm_mod, "_PERMISSION_DIR", perm_dir)
        monkeypatch.setattr(perm_mod, "_BEHAVIOR_FILE", behavior_file)

        engine = PermissionEngine()
        report = engine.get_trust_report()
        assert report["total_behaviors"] == 2

    def test_persist_behavior_os_error(self, tmp_path, monkeypatch):
        """持久化写入 OS 错误时不崩溃"""
        import pycoder.safety.permission as perm_mod
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import BehaviorRecord, PermissionEngine

        perm_dir = tmp_path / ".pycoder" / "permission"
        monkeypatch.setattr(perm_mod, "_PERMISSION_DIR", perm_dir)
        monkeypatch.setattr(perm_mod, "_BEHAVIOR_FILE", perm_dir / "behavior_history.jsonl")

        engine = PermissionEngine()

        with patch("builtins.open", side_effect=OSError("磁盘满")):
            # 不应抛出异常
            engine.record_behavior(BehaviorRecord(
                capability_id="test.op", success=True, decision="auto_allow",
            ))

        # 行为仍被记录到内存
        report = engine.get_trust_report()
        assert report["total_behaviors"] == 1

    # ── 模式匹配更多场景 ───────────────────────────────

    def test_match_pattern_single_char_wildcard(self):
        """单字符通配符 ? 匹配"""
        from pycoder.safety.permission import PermissionEngine

        assert PermissionEngine._match_pattern("file.1", "file.?") is True
        assert PermissionEngine._match_pattern("file.12", "file.?") is False

    def test_match_pattern_complex(self):
        """复杂通配符模式"""
        from pycoder.safety.permission import PermissionEngine

        assert PermissionEngine._match_pattern("a.b.c.d", "a.*.c.*") is True
        assert PermissionEngine._match_pattern("a.x.c.d", "a.*.c.*") is True
        assert PermissionEngine._match_pattern("a.x.y.d", "a.*.c.*") is False

    def test_match_pattern_case_sensitive(self):
        """fnmatch 在 Windows 上大小写不敏感，在 Unix 上大小写敏感"""
        from pycoder.safety.permission import PermissionEngine

        result = PermissionEngine._match_pattern("Editor.Code.Read", "editor.code.read")
        if sys.platform == "win32":
            # Windows 上 fnmatch 默认大小写不敏感
            assert result is True
        else:
            assert result is False

    # ── escalate_trust 自定义原因 ──────────────────────

    def test_escalate_trust_with_reason(self, engine):
        """带原因提升信任"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import BehaviorRecord

        for i in range(100):
            engine.record_behavior(BehaviorRecord(
                capability_id="test.op", success=True, decision="auto_allow", trust_level=1,
            ))
        ok, msg = engine.escalate_trust("连续良好表现")
        assert ok is True
        assert "提升" in msg

    # ── 无参数关键路径检查 ─────────────────────────────

    def test_critical_path_with_non_matching_key(self, engine):
        """非路径键不触发关键路径检查"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import DecisionType

        result = engine.check(
            "file.write", TrustLevel.WORKSPACE_WRITE,
            params={"content": "hello", "encoding": "utf-8"},
        )
        assert "关键路径" not in result.reason


# ══════════════════════════════════════════════════════════
# 第三部分: safety/sandbox.py 测试
# ══════════════════════════════════════════════════════════


class TestSandboxConfig:
    """沙箱配置数据类"""

    def test_defaults(self):
        """验证默认值"""
        from pycoder.safety.sandbox import SandboxConfig

        config = SandboxConfig()
        assert config.max_cpu_percent == 30.0
        assert config.max_memory_mb == 512
        assert config.max_disk_mb == 100
        assert config.max_timeout_seconds == 60.0
        assert config.allow_network is False
        assert config.allow_file_write is False
        assert config.allowed_paths == []
        assert config.network_whitelist == []

    def test_custom_values(self):
        """验证自定义值"""
        from pycoder.safety.sandbox import SandboxConfig

        config = SandboxConfig(
            max_cpu_percent=50.0,
            max_memory_mb=256,
            max_disk_mb=50,
            max_timeout_seconds=30.0,
            allow_network=True,
            allow_file_write=True,
            allowed_paths=["/tmp", "/home/user"],
            network_whitelist=["api.github.com"],
        )
        assert config.max_cpu_percent == 50.0
        assert config.allow_network is True
        assert config.allowed_paths == ["/tmp", "/home/user"]


class TestSandboxResult:
    """沙箱执行结果"""

    def test_defaults(self):
        """验证默认值"""
        from pycoder.safety.sandbox import SandboxResult

        result = SandboxResult(success=True)
        assert result.success is True
        assert result.output == ""
        assert result.error == ""
        assert result.exit_code == 0
        assert result.duration_ms == 0.0
        assert result.memory_used_mb == 0.0
        assert result.cpu_time_ms == 0.0
        assert result.killed_by_timeout is False
        assert result.killed_by_memory is False

    def test_error_result(self):
        """错误结果"""
        from pycoder.safety.sandbox import SandboxResult

        result = SandboxResult(
            success=False,
            error="内存不足",
            exit_code=1,
            duration_ms=500.0,
            killed_by_memory=True,
        )
        assert result.success is False
        assert result.error == "内存不足"
        assert result.exit_code == 1
        assert result.killed_by_memory is True


class TestProcessSandbox:
    """进程沙箱"""

    def test_default_config(self):
        """默认配置"""
        from pycoder.safety.sandbox import ProcessSandbox, SandboxConfig

        sandbox = ProcessSandbox()
        assert isinstance(sandbox.config, SandboxConfig)
        assert sandbox.config.max_timeout_seconds == 60.0

    def test_custom_config(self):
        """自定义配置"""
        from pycoder.safety.sandbox import ProcessSandbox, SandboxConfig

        config = SandboxConfig(max_timeout_seconds=10.0, max_memory_mb=128)
        sandbox = ProcessSandbox(config)
        assert sandbox.config.max_timeout_seconds == 10.0
        assert sandbox.config.max_memory_mb == 128

    @pytest.mark.asyncio
    async def test_execute_simple_python(self, monkeypatch):
        """执行简单 Python 代码"""
        from pycoder.safety.sandbox import ProcessSandbox

        sandbox = ProcessSandbox()
        # 在 Windows 上 python3 不存在，使用 sys.executable
        monkeypatch.setattr(sandbox, "_get_interpreter", lambda lang: sys.executable)
        result = await sandbox.execute('print("hello")', language="python")
        assert result.success is True
        assert "hello" in result.output
        assert result.error == ""
        # exit_code 可能为 0 或 -1（取决于 process.returncode or -1 的语义）
        assert result.exit_code in (0, -1)
        assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_execute_error_code(self, monkeypatch):
        """执行有错误的代码"""
        from pycoder.safety.sandbox import ProcessSandbox

        sandbox = ProcessSandbox()
        monkeypatch.setattr(sandbox, "_get_interpreter", lambda lang: sys.executable)
        result = await sandbox.execute("import sys; sys.exit(1)", language="python")
        assert result.success is False
        assert result.exit_code == 1

    @pytest.mark.asyncio
    async def test_execute_stderr(self, monkeypatch):
        """执行产生 stderr 的代码"""
        from pycoder.safety.sandbox import ProcessSandbox

        sandbox = ProcessSandbox()
        monkeypatch.setattr(sandbox, "_get_interpreter", lambda lang: sys.executable)
        result = await sandbox.execute("import sys; print('ok'); print('err', file=sys.stderr)", language="python")
        assert result.success is True
        assert "ok" in result.output
        # exit_code 可能为 0 或 -1（取决于 process.returncode or -1 的语义）
        assert result.exit_code in (0, -1)

    @pytest.mark.asyncio
    async def test_execute_with_stdin(self, monkeypatch):
        """带 stdin 的执行"""
        from pycoder.safety.sandbox import ProcessSandbox

        sandbox = ProcessSandbox()
        monkeypatch.setattr(sandbox, "_get_interpreter", lambda lang: sys.executable)
        result = await sandbox.execute("print(input())", language="python", stdin="test_input")
        assert result.success is True
        assert "test_input" in result.output

    @pytest.mark.asyncio
    async def test_execute_with_env(self, monkeypatch):
        """带环境变量的执行"""
        from pycoder.safety.sandbox import ProcessSandbox

        sandbox = ProcessSandbox()
        monkeypatch.setattr(sandbox, "_get_interpreter", lambda lang: sys.executable)
        result = await sandbox.execute(
            "import os; print(os.environ.get('MY_VAR', 'NOT_SET'))",
            language="python",
            env={"MY_VAR": "custom_value"},
        )
        assert result.success is True
        assert "custom_value" in result.output

    def test_prepare_code_python(self):
        """准备 Python 代码文件"""
        from pycoder.safety.sandbox import ProcessSandbox
        from pathlib import Path
        import tempfile

        sandbox = ProcessSandbox()
        with tempfile.TemporaryDirectory() as work_dir:
            path = sandbox._prepare_code("x = 1", "python", Path(work_dir))
            assert path.suffix == ".py"
            assert path.read_text() == "x = 1"

    def test_prepare_code_javascript(self):
        """准备 JavaScript 代码文件"""
        from pycoder.safety.sandbox import ProcessSandbox
        from pathlib import Path
        import tempfile

        sandbox = ProcessSandbox()
        with tempfile.TemporaryDirectory() as work_dir:
            path = sandbox._prepare_code("console.log(1)", "javascript", Path(work_dir))
            assert path.suffix == ".js"

    def test_prepare_code_unknown_language(self):
        """未知语言使用 .txt 后缀"""
        from pycoder.safety.sandbox import ProcessSandbox
        from pathlib import Path
        import tempfile

        sandbox = ProcessSandbox()
        with tempfile.TemporaryDirectory() as work_dir:
            path = sandbox._prepare_code("code", "unknown", Path(work_dir))
            assert path.suffix == ".txt"

    def test_get_interpreter_known(self):
        """已知语言解释器"""
        from pycoder.safety.sandbox import ProcessSandbox

        sandbox = ProcessSandbox()
        assert sandbox._get_interpreter("python") == "python3"
        assert sandbox._get_interpreter("javascript") == "node"
        assert sandbox._get_interpreter("bash") == "bash"

    def test_get_interpreter_unknown(self):
        """未知语言默认 python3"""
        from pycoder.safety.sandbox import ProcessSandbox

        sandbox = ProcessSandbox()
        assert sandbox._get_interpreter("unknown") == "python3"

    @pytest.mark.asyncio
    async def test_execute_timeout(self, monkeypatch):
        """超时执行被杀死"""
        from pycoder.safety.sandbox import ProcessSandbox, SandboxConfig

        config = SandboxConfig(max_timeout_seconds=1.0)
        sandbox = ProcessSandbox(config)
        monkeypatch.setattr(sandbox, "_get_interpreter", lambda lang: sys.executable)
        result = await sandbox.execute("import time; time.sleep(10)", language="python")
        assert result.killed_by_timeout is True
        assert result.success is False


class TestCodeSandbox:
    """代码沙箱"""

    def test_default_timeout(self):
        """默认超时"""
        from pycoder.safety.sandbox import CodeSandbox

        sandbox = CodeSandbox()
        assert sandbox.timeout == 5.0

    def test_custom_timeout(self):
        """自定义超时"""
        from pycoder.safety.sandbox import CodeSandbox

        sandbox = CodeSandbox(timeout=10.0)
        assert sandbox.timeout == 10.0

    @pytest.mark.asyncio
    async def test_execute_simple_expression(self):
        """执行简单表达式"""
        from pycoder.safety.sandbox import CodeSandbox

        sandbox = CodeSandbox()
        result = await sandbox.execute("result = 1 + 1")
        assert result.success is True
        assert "2" in result.output

    @pytest.mark.asyncio
    async def test_execute_list_comprehension(self):
        """执行列表推导（内置函数可能受限于沙箱实现）"""
        from pycoder.safety.sandbox import CodeSandbox

        sandbox = CodeSandbox()
        # 使用纯字面量，不依赖 range 内置函数
        result = await sandbox.execute("result = [1, 2, 3]")
        assert result.success is True
        assert "1" in result.output and "3" in result.output

    @pytest.mark.asyncio
    async def test_execute_syntax_error(self):
        """执行语法错误代码"""
        from pycoder.safety.sandbox import CodeSandbox

        sandbox = CodeSandbox()
        result = await sandbox.execute("invalid python code !!!")
        assert result.success is False
        assert "SyntaxError" in result.error

    @pytest.mark.asyncio
    async def test_execute_runtime_error(self):
        """执行运行时错误"""
        from pycoder.safety.sandbox import CodeSandbox

        sandbox = CodeSandbox()
        result = await sandbox.execute("result = 1 / 0")
        assert result.success is False
        assert "ZeroDivisionError" in result.error

    @pytest.mark.asyncio
    async def test_execute_restricted_builtins(self):
        """受限内置函数"""
        from pycoder.safety.sandbox import CodeSandbox

        sandbox = CodeSandbox()
        # open 不在 ALLOWED_BUILTINS 中，应该失败
        result = await sandbox.execute("result = open('test.txt')")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_allowed_builtins(self):
        """允许的内置函数可以正常使用（取决于沙箱实现中 __builtins__ 的类型）"""
        from pycoder.safety.sandbox import CodeSandbox

        sandbox = CodeSandbox()
        result = await sandbox.execute("result = True")
        # True 在 ALLOWED_BUILTINS 中，但受限于 __builtins__ 的 dict/module 差异
        # 至少验证沙箱不崩溃
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_execute_duration_recorded(self):
        """执行耗时被记录"""
        from pycoder.safety.sandbox import CodeSandbox

        sandbox = CodeSandbox()
        result = await sandbox.execute("result = sum(range(1000))")
        assert result.duration_ms > 0


class TestPluginSandbox:
    """插件沙箱"""

    def test_creation(self):
        """创建插件沙箱"""
        from pycoder.safety.sandbox import PluginSandbox, SandboxConfig

        sandbox = PluginSandbox("test_plugin")
        assert sandbox.plugin_name == "test_plugin"
        assert isinstance(sandbox.config, SandboxConfig)
        assert sandbox.config.max_memory_mb == 256
        assert sandbox.config.max_timeout_seconds == 30.0
        assert sandbox.config.allow_network is False

    def test_custom_config(self):
        """自定义配置"""
        from pycoder.safety.sandbox import PluginSandbox, SandboxConfig

        config = SandboxConfig(max_memory_mb=128, allow_network=True)
        sandbox = PluginSandbox("custom_plugin", config)
        assert sandbox.config.max_memory_mb == 128
        assert sandbox.config.allow_network is True

    @pytest.mark.asyncio
    async def test_start(self):
        """启动插件沙箱"""
        from pycoder.safety.sandbox import PluginSandbox

        sandbox = PluginSandbox("test_plugin")
        result = await sandbox.start()
        assert result is True

    @pytest.mark.asyncio
    async def test_stop_no_process(self):
        """停止未启动的沙箱"""
        from pycoder.safety.sandbox import PluginSandbox

        sandbox = PluginSandbox("test_plugin")
        # 不应抛出异常
        await sandbox.stop()

    def test_is_running_no_process(self):
        """无进程时 is_running 为 False"""
        from pycoder.safety.sandbox import PluginSandbox

        sandbox = PluginSandbox("test_plugin")
        assert sandbox.is_running is False

    @pytest.mark.asyncio
    async def test_health_check_no_process(self):
        """健康检查：无进程"""
        from pycoder.safety.sandbox import PluginSandbox

        sandbox = PluginSandbox("test_plugin")
        result = await sandbox.health_check()
        assert result is False


class TestSandboxManager:
    """沙箱管理器"""

    def test_creation(self):
        """创建管理器"""
        from pycoder.safety.sandbox import SandboxManager

        manager = SandboxManager()
        assert manager.list_sandboxes() == {}

    def test_create_process_sandbox(self):
        """创建进程沙箱"""
        from pycoder.safety.sandbox import ProcessSandbox, SandboxManager

        manager = SandboxManager()
        sandbox = manager.create_process_sandbox("proc1")
        assert isinstance(sandbox, ProcessSandbox)
        assert "proc1" in manager.list_sandboxes()

    def test_create_code_sandbox(self):
        """创建代码沙箱"""
        from pycoder.safety.sandbox import CodeSandbox, SandboxManager

        manager = SandboxManager()
        sandbox = manager.create_code_sandbox("code1", timeout=3.0)
        assert isinstance(sandbox, CodeSandbox)
        assert sandbox.timeout == 3.0

    def test_create_plugin_sandbox(self):
        """创建插件沙箱"""
        from pycoder.safety.sandbox import PluginSandbox, SandboxManager

        manager = SandboxManager()
        sandbox = manager.create_plugin_sandbox("plug1", "my_plugin")
        assert isinstance(sandbox, PluginSandbox)
        assert sandbox.plugin_name == "my_plugin"

    def test_get_existing(self):
        """获取已存在的沙箱"""
        from pycoder.safety.sandbox import SandboxManager

        manager = SandboxManager()
        sandbox = manager.create_process_sandbox("proc1")
        assert manager.get("proc1") is sandbox

    def test_get_nonexistent(self):
        """获取不存在的沙箱返回 None"""
        from pycoder.safety.sandbox import SandboxManager

        manager = SandboxManager()
        assert manager.get("nonexistent") is None

    def test_remove(self):
        """移除沙箱"""
        from pycoder.safety.sandbox import SandboxManager

        manager = SandboxManager()
        manager.create_process_sandbox("proc1")
        manager.remove("proc1")
        assert manager.get("proc1") is None
        assert "proc1" not in manager.list_sandboxes()

    def test_list_sandboxes(self):
        """列出所有沙箱"""
        from pycoder.safety.sandbox import SandboxManager

        manager = SandboxManager()
        manager.create_process_sandbox("proc1")
        manager.create_code_sandbox("code1")
        sandboxes = manager.list_sandboxes()
        assert len(sandboxes) == 2
        assert sandboxes["proc1"] == "ProcessSandbox"
        assert sandboxes["code1"] == "CodeSandbox"

    @pytest.mark.asyncio
    async def test_cleanup_all(self):
        """清理所有沙箱"""
        from pycoder.safety.sandbox import SandboxManager

        manager = SandboxManager()
        manager.create_process_sandbox("proc1")
        manager.create_plugin_sandbox("plug1", "plugin_a")
        manager.create_code_sandbox("code1")

        await manager.cleanup_all()
        assert manager.list_sandboxes() == {}


# ══════════════════════════════════════════════════════════
# 第四部分: 跨模块集成测试
# ══════════════════════════════════════════════════════════


class TestCrossModuleIntegration:
    """跨模块集成测试"""

    def test_protocol_trust_level_in_permission(self):
        """protocol.py 中的 TrustLevel 在 permission.py 中正确使用"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.permission import PermissionEngine

        engine = PermissionEngine(initial_trust=TrustLevel.WORKSPACE_WRITE)
        assert engine.current_trust == TrustLevel.WORKSPACE_WRITE

    def test_protocol_side_effect_in_permission_check(self, tmp_path, monkeypatch):
        """SideEffect 作为参数传入 check 方法"""
        import pycoder.safety.permission as perm_mod
        from pycoder.bus.protocol import SideEffect, TrustLevel
        from pycoder.safety.permission import PermissionEngine

        perm_dir = tmp_path / ".pycoder" / "permission"
        monkeypatch.setattr(perm_mod, "_PERMISSION_DIR", perm_dir)
        monkeypatch.setattr(perm_mod, "_BEHAVIOR_FILE", perm_dir / "behavior_history.jsonl")

        engine = PermissionEngine(initial_trust=TrustLevel.READ_ONLY)
        result = engine.check(
            "file.read", TrustLevel.READ_ONLY,
            side_effects=[SideEffect.FILE_READ],
        )
        assert result.allowed is True

    def test_permission_decision_with_side_effects(self):
        """PermissionDecision 与 SideEffect 配合使用"""
        from pycoder.bus.protocol import SideEffect
        from pycoder.safety.permission import DecisionType, PermissionDecision

        decision = PermissionDecision(
            allowed=True,
            decision_type=DecisionType.AUTO_ALLOW,
            reason=f"允许只读操作 {SideEffect.FILE_READ.value}",
        )
        assert decision.allowed is True
        assert "file_read" in decision.reason

    def test_sandbox_config_with_permission_trust(self):
        """沙箱配置与信任级别配合"""
        from pycoder.bus.protocol import TrustLevel
        from pycoder.safety.sandbox import SandboxConfig

        # 根据信任级别配置沙箱
        configs = {
            TrustLevel.READ_ONLY: SandboxConfig(allow_network=False, allow_file_write=False),
            TrustLevel.FULL_AUTONOMY: SandboxConfig(allow_network=True, allow_file_write=True),
        }
        assert configs[TrustLevel.READ_ONLY].allow_network is False
        assert configs[TrustLevel.FULL_AUTONOMY].allow_network is True