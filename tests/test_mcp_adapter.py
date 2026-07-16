"""
MCP 协议适配器单元测试 — 覆盖 MCPProtocolAdapter 核心功能

测试范围:
  - MCPProtocolAdapter 初始化
  - tools/list 端点
  - tools/call 端点
  - resources/list 和 resources/read
  - prompts/list 和 prompts/get
  - 服务器能力协商
  - 错误处理（未知工具、无效参数）
  - JSON-RPC 消息格式验证
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.bus.mcp_adapter import (
    MCP_PROTOCOL_VERSION,
    MCP_SERVER_NAME,
    MCP_SERVER_VERSION,
    MCPProtocolAdapter,
    _capability_to_mcp_tool,
    _mcp_name_to_capability_id,
    get_mcp_adapter,
    register_capabilities,
)
from pycoder.bus.protocol import (
    CapabilityCategory,
    CapabilityDefinition,
    CapabilityResult,
    ExecutionMode,
    SideEffect,
    TrustLevel,
)


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def mock_registry() -> MagicMock:
    """创建 mock 能力注册表"""
    registry = MagicMock()
    registry.list_all.return_value = _sample_capabilities()
    registry.exists.return_value = False
    registry.call = AsyncMock()
    return registry


@pytest.fixture
def adapter(mock_registry: MagicMock) -> MCPProtocolAdapter:
    """创建使用 mock 注册表的 MCP 适配器"""
    return MCPProtocolAdapter(registry=mock_registry)


@pytest.fixture
def adapter_no_registry() -> MCPProtocolAdapter:
    """创建无注册表的 MCP 适配器"""
    return MCPProtocolAdapter()


def _sample_capabilities() -> list[CapabilityDefinition]:
    """创建示例能力定义列表"""
    return [
        CapabilityDefinition(
            id="editor.code.read",
            name="读取代码",
            description="读取源代码文件",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_READ],
            tags=["editor", "read"],
        ),
        CapabilityDefinition(
            id="editor.code.write",
            name="写入代码",
            description="写入源代码文件",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_WRITE],
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            tags=["editor", "write"],
        ),
        CapabilityDefinition(
            id="system.shell.exec",
            name="执行 Shell",
            description="执行 Shell 命令",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.PROJECT_WRITE,
            execution=ExecutionMode.ASYNC,
            side_effects=[SideEffect.PROCESS],
            tags=["system", "shell"],
        ),
        CapabilityDefinition(
            id="old.deprecated.tool",
            name="废弃工具",
            description="已废弃的工具",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            deprecated=True,
            tags=["deprecated"],
        ),
    ]


# ── 工具格式转换测试 ─────────────────────────────────────


class TestCapabilityToMCPTool:
    """能力定义到 MCP 工具格式转换测试"""

    def test_basic_conversion(self) -> None:
        """测试基本转换"""
        cap = CapabilityDefinition(
            id="editor.code.read",
            name="读取代码",
            description="读取源代码文件",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_READ],
            tags=["editor"],
        )
        tool = _capability_to_mcp_tool(cap)
        assert tool["name"] == "editor_code_read"
        assert tool["description"] == "读取源代码文件"
        assert "inputSchema" in tool
        assert "annotations" in tool
        assert tool["annotations"]["category"] == "editor"
        assert tool["annotations"]["permission"] == "READ_ONLY"
        assert tool["annotations"]["execution"] == "sync"
        assert tool["annotations"]["side_effects"] == ["file_read"]
        assert tool["annotations"]["deprecated"] is False

    def test_conversion_with_schema(self) -> None:
        """测试带 schema 的转换"""
        cap = CapabilityDefinition(
            id="editor.code.write",
            name="写入代码",
            description="写入源代码文件",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_WRITE],
            schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
        tool = _capability_to_mcp_tool(cap)
        assert "path" in tool["inputSchema"]["properties"]
        assert "path" in tool["inputSchema"]["required"]

    def test_conversion_without_schema_uses_default(self) -> None:
        """测试无 schema 时使用默认空 schema"""
        cap = CapabilityDefinition(
            id="test.tool",
            name="测试",
            description="测试工具",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
        )
        tool = _capability_to_mcp_tool(cap)
        assert tool["inputSchema"] == {"type": "object", "properties": {}}

    def test_conversion_deprecated(self) -> None:
        """测试废弃能力标记"""
        cap = CapabilityDefinition(
            id="old.tool",
            name="旧工具",
            description="旧工具",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            deprecated=True,
        )
        tool = _capability_to_mcp_tool(cap)
        assert tool["annotations"]["deprecated"] is True


class TestMCPNameConversion:
    """MCP 工具名与能力 ID 互转测试"""

    def test_capability_to_mcp_name(self) -> None:
        """测试能力 ID 转 MCP 工具名"""
        cap = CapabilityDefinition(
            id="editor.code.read",
            name="读取",
            description="读取",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
        )
        tool = _capability_to_mcp_tool(cap)
        assert tool["name"] == "editor_code_read"

    def test_mcp_name_to_capability_id(self) -> None:
        """测试 MCP 工具名转能力 ID"""
        assert _mcp_name_to_capability_id("editor_code_read") == "editor.code.read"
        assert _mcp_name_to_capability_id("system_shell_exec") == "system.shell.exec"

    def test_roundtrip(self) -> None:
        """测试往返转换"""
        original = "editor.code.read"
        cap = CapabilityDefinition(
            id=original,
            name="x",
            description="x",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
        )
        mcp_name = _capability_to_mcp_tool(cap)["name"]
        restored = _mcp_name_to_capability_id(mcp_name)
        assert restored == original


# ── MCPProtocolAdapter 初始化测试 ────────────────────────


class TestMCPProtocolAdapterInit:
    """MCP 适配器初始化测试"""

    def test_init_with_registry(self, mock_registry: MagicMock) -> None:
        """测试带注册表初始化"""
        adapter = MCPProtocolAdapter(registry=mock_registry)
        assert adapter._registry is mock_registry
        assert adapter._initialized is False

    def test_init_without_registry(self) -> None:
        """测试无注册表初始化"""
        adapter = MCPProtocolAdapter()
        assert adapter._registry is None
        assert adapter._initialized is False

    def test_server_info(self, adapter: MCPProtocolAdapter) -> None:
        """测试服务器信息"""
        info = adapter.server_info
        assert info["name"] == MCP_SERVER_NAME
        assert info["version"] == MCP_SERVER_VERSION
        assert info["protocolVersion"] == MCP_PROTOCOL_VERSION

    def test_registry_property_lazy_load(self) -> None:
        """测试注册表延迟加载"""
        adapter = MCPProtocolAdapter()
        assert adapter.registry is None


# ── 初始化测试 ───────────────────────────────────────────


class TestInitialize:
    """MCP 适配器初始化测试"""

    @pytest.mark.asyncio
    async def test_initialize(self, adapter: MCPProtocolAdapter) -> None:
        """测试首次初始化"""
        info = await adapter.initialize()
        assert adapter._initialized is True
        assert info == adapter.server_info

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, adapter: MCPProtocolAdapter) -> None:
        """测试重复初始化是幂等的"""
        await adapter.initialize()
        await adapter.initialize()
        assert adapter._initialized is True

    @pytest.mark.asyncio
    async def test_initialize_registers_builtins(self, adapter: MCPProtocolAdapter) -> None:
        """测试初始化注册内置资源和提示词"""
        await adapter.initialize()
        assert len(adapter._resources) >= 3
        assert len(adapter._prompts) >= 5
        assert "pycoder://capabilities" in adapter._resources
        assert "code_review" in adapter._prompts


# ── tools/list 测试 ──────────────────────────────────────


class TestListTools:
    """tools/list 端点测试"""

    @pytest.mark.asyncio
    async def test_list_tools(self, adapter: MCPProtocolAdapter) -> None:
        """测试列出工具"""
        tools = await adapter.list_tools()
        assert len(tools) == 3  # 4 个能力中 1 个已废弃
        assert all("name" in t for t in tools)
        assert all("description" in t for t in tools)
        assert all("inputSchema" in t for t in tools)

    @pytest.mark.asyncio
    async def test_list_tools_filters_deprecated(self, adapter: MCPProtocolAdapter) -> None:
        """测试废弃工具被过滤"""
        tools = await adapter.list_tools()
        names = [t["name"] for t in tools]
        assert "old_deprecated_tool" not in names

    @pytest.mark.asyncio
    async def test_list_tools_no_registry(self, adapter_no_registry: MCPProtocolAdapter) -> None:
        """测试无注册表时返回空列表"""
        tools = await adapter_no_registry.list_tools()
        assert tools == []

    @pytest.mark.asyncio
    async def test_list_tools_format(self, adapter: MCPProtocolAdapter) -> None:
        """测试工具格式符合 MCP 规范"""
        tools = await adapter.list_tools()
        for tool in tools:
            assert isinstance(tool["name"], str)
            assert "_" in tool["name"]
            assert isinstance(tool["description"], str)
            assert isinstance(tool["inputSchema"], dict)
            assert isinstance(tool["annotations"], dict)


# ── tools/call 测试 ──────────────────────────────────────


class TestCallTool:
    """tools/call 端点测试"""

    @pytest.mark.asyncio
    async def test_call_tool_success(
        self, adapter: MCPProtocolAdapter, mock_registry: MagicMock
    ) -> None:
        """测试成功调用工具"""
        mock_registry.exists.return_value = True
        mock_registry.call.return_value = CapabilityResult(
            trace_id="trace-001",
            capability_id="editor.code.read",
            success=True,
            data={"content": "print('hello')"},
            duration_ms=15.0,
        )

        result = await adapter.call_tool("editor_code_read", {"path": "main.py"})
        assert result["isError"] is False
        assert "trace_id" in result["_meta"]

    @pytest.mark.asyncio
    async def test_call_tool_not_found(
        self, adapter: MCPProtocolAdapter, mock_registry: MagicMock
    ) -> None:
        """测试调用不存在的工具"""
        mock_registry.exists.return_value = False

        result = await adapter.call_tool("unknown_tool", {})
        assert result["isError"] is True
        assert "未找到" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_call_tool_no_registry(self, adapter_no_registry: MCPProtocolAdapter) -> None:
        """测试无注册表时调用工具"""
        result = await adapter_no_registry.call_tool("any_tool", {})
        assert result["isError"] is True
        assert "未初始化" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_call_tool_with_none_arguments(
        self, adapter: MCPProtocolAdapter, mock_registry: MagicMock
    ) -> None:
        """测试不传参数调用工具"""
        mock_registry.exists.return_value = True
        mock_registry.call.return_value = CapabilityResult(
            trace_id="trace-002",
            capability_id="editor.code.read",
            success=True,
            data="result text",
            duration_ms=5.0,
        )

        result = await adapter.call_tool("editor_code_read")
        assert result["isError"] is False

    @pytest.mark.asyncio
    async def test_call_tool_capability_failure(
        self, adapter: MCPProtocolAdapter, mock_registry: MagicMock
    ) -> None:
        """测试能力执行失败"""
        mock_registry.exists.return_value = True
        mock_registry.call.return_value = CapabilityResult(
            trace_id="trace-003",
            capability_id="editor.code.write",
            success=False,
            error="权限不足",
            duration_ms=2.0,
        )

        result = await adapter.call_tool("editor_code_write", {"path": "/etc/hosts"})
        assert result["isError"] is True
        assert "权限不足" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_call_tool_exception(
        self, adapter: MCPProtocolAdapter, mock_registry: MagicMock
    ) -> None:
        """测试工具调用抛出异常"""
        mock_registry.exists.return_value = True
        mock_registry.call.side_effect = RuntimeError("内部错误")

        result = await adapter.call_tool("editor_code_read", {})
        assert result["isError"] is True
        assert "内部错误" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_call_tool_result_data_string(
        self, adapter: MCPProtocolAdapter, mock_registry: MagicMock
    ) -> None:
        """测试返回字符串类型的 data"""
        mock_registry.exists.return_value = True
        mock_registry.call.return_value = CapabilityResult(
            trace_id="trace-004",
            capability_id="editor.code.read",
            success=True,
            data="plain text result",
            duration_ms=10.0,
        )

        result = await adapter.call_tool("editor_code_read")
        assert result["isError"] is False
        assert result["content"][0]["text"] == "plain text result"

    @pytest.mark.asyncio
    async def test_call_tool_result_data_none(
        self, adapter: MCPProtocolAdapter, mock_registry: MagicMock
    ) -> None:
        """测试返回 None 类型的 data"""
        mock_registry.exists.return_value = True
        mock_registry.call.return_value = CapabilityResult(
            trace_id="trace-005",
            capability_id="editor.code.read",
            success=True,
            data=None,
            duration_ms=5.0,
        )

        result = await adapter.call_tool("editor_code_read")
        assert result["isError"] is False
        assert "执行成功" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_call_tool_tries_alternative_ids(
        self, adapter: MCPProtocolAdapter, mock_registry: MagicMock
    ) -> None:
        """测试尝试多种 ID 格式"""
        mock_registry.exists.side_effect = [False, True, False]
        mock_registry.call.return_value = CapabilityResult(
            trace_id="trace-006",
            capability_id="tools.editor.code.read",
            success=True,
            data="found via alternative",
            duration_ms=10.0,
        )

        result = await adapter.call_tool("editor_code_read")
        assert result["isError"] is False
        assert "found via alternative" in result["content"][0]["text"]


# ── resources/list 测试 ──────────────────────────────────


class TestListResources:
    """resources/list 端点测试"""

    @pytest.mark.asyncio
    async def test_list_resources(self, adapter: MCPProtocolAdapter) -> None:
        """测试列出资源"""
        await adapter.initialize()
        resources = await adapter.list_resources()
        assert len(resources) == 3
        uris = [r["uri"] for r in resources]
        assert "pycoder://capabilities" in uris
        assert "pycoder://server/info" in uris
        assert "pycoder://workspace/status" in uris

    @pytest.mark.asyncio
    async def test_list_resources_auto_initializes(self, adapter: MCPProtocolAdapter) -> None:
        """测试自动初始化"""
        assert adapter._initialized is False
        resources = await adapter.list_resources()
        assert adapter._initialized is True
        assert len(resources) == 3

    @pytest.mark.asyncio
    async def test_list_resources_format(self, adapter: MCPProtocolAdapter) -> None:
        """测试资源格式"""
        await adapter.initialize()
        resources = await adapter.list_resources()
        for res in resources:
            assert "uri" in res
            assert "name" in res
            assert "description" in res
            assert "mimeType" in res


# ── resources/read 测试 ──────────────────────────────────


class TestReadResource:
    """resources/read 端点测试"""

    @pytest.mark.asyncio
    async def test_read_capabilities_resource(self, adapter: MCPProtocolAdapter) -> None:
        """测试读取能力清单资源"""
        await adapter.initialize()
        result = await adapter.read_resource("pycoder://capabilities")
        assert "contents" in result
        assert len(result["contents"]) == 1
        content = result["contents"][0]
        assert content["uri"] == "pycoder://capabilities"
        assert content["mimeType"] == "application/json"
        data = json.loads(content["text"])
        assert "server" in data
        assert "total_tools" in data
        assert "tools" in data

    @pytest.mark.asyncio
    async def test_read_server_info_resource(self, adapter: MCPProtocolAdapter) -> None:
        """测试读取服务器信息资源"""
        await adapter.initialize()
        result = await adapter.read_resource("pycoder://server/info")
        assert "contents" in result
        content = result["contents"][0]
        data = json.loads(content["text"])
        assert data["name"] == MCP_SERVER_NAME
        assert "python_version" in data
        assert "platform" in data

    @pytest.mark.asyncio
    async def test_read_workspace_status_resource(self, adapter: MCPProtocolAdapter) -> None:
        """测试读取工作区状态资源"""
        await adapter.initialize()
        result = await adapter.read_resource("pycoder://workspace/status")
        assert "contents" in result
        content = result["contents"][0]
        data = json.loads(content["text"])
        assert "workspace" in data
        assert "exists" in data
        assert "python_files" in data
        assert "git" in data

    @pytest.mark.asyncio
    async def test_read_resource_not_found(self, adapter: MCPProtocolAdapter) -> None:
        """测试读取不存在的资源"""
        await adapter.initialize()
        result = await adapter.read_resource("pycoder://nonexistent")
        assert result["isError"] is True
        assert "未找到" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_read_resource_auto_initializes(self, adapter: MCPProtocolAdapter) -> None:
        """测试读取资源时自动初始化"""
        result = await adapter.read_resource("pycoder://server/info")
        assert "contents" in result


# ── prompts/list 测试 ────────────────────────────────────


class TestListPrompts:
    """prompts/list 端点测试"""

    @pytest.mark.asyncio
    async def test_list_prompts(self, adapter: MCPProtocolAdapter) -> None:
        """测试列出提示词"""
        await adapter.initialize()
        prompts = await adapter.list_prompts()
        assert len(prompts) == 5
        names = [p["name"] for p in prompts]
        assert "code_review" in names
        assert "refactor" in names
        assert "generate_tests" in names
        assert "explain_code" in names
        assert "debug" in names

    @pytest.mark.asyncio
    async def test_list_prompts_auto_initializes(self, adapter: MCPProtocolAdapter) -> None:
        """测试自动初始化"""
        prompts = await adapter.list_prompts()
        assert len(prompts) == 5

    @pytest.mark.asyncio
    async def test_list_prompts_format(self, adapter: MCPProtocolAdapter) -> None:
        """测试提示词格式"""
        await adapter.initialize()
        prompts = await adapter.list_prompts()
        for prompt in prompts:
            assert "name" in prompt
            assert "description" in prompt
            assert "arguments" in prompt
            assert isinstance(prompt["arguments"], list)


# ── prompts/get 测试 ─────────────────────────────────────


class TestGetPrompt:
    """prompts/get 端点测试"""

    @pytest.mark.asyncio
    async def test_get_prompt_code_review(self, adapter: MCPProtocolAdapter) -> None:
        """测试获取代码审查提示词"""
        await adapter.initialize()
        result = await adapter.get_prompt("code_review", {
            "code": "def foo():\n    pass",
            "language": "python",
        })
        assert "messages" in result
        assert len(result["messages"]) == 1
        msg = result["messages"][0]
        assert msg["role"] == "user"
        assert "def foo()" in msg["content"]["text"]
        assert "python" in msg["content"]["text"]

    @pytest.mark.asyncio
    async def test_get_prompt_refactor(self, adapter: MCPProtocolAdapter) -> None:
        """测试获取重构提示词"""
        await adapter.initialize()
        result = await adapter.get_prompt("refactor", {
            "code": "x = 1",
            "language": "python",
            "goal": "提取函数",
        })
        assert "提取函数" in result["messages"][0]["content"]["text"]

    @pytest.mark.asyncio
    async def test_get_prompt_generate_tests(self, adapter: MCPProtocolAdapter) -> None:
        """测试获取测试生成提示词"""
        await adapter.initialize()
        result = await adapter.get_prompt("generate_tests", {
            "code": "def add(a, b): return a + b",
            "language": "python",
            "framework": "pytest",
        })
        assert "pytest" in result["messages"][0]["content"]["text"]

    @pytest.mark.asyncio
    async def test_get_prompt_explain_code(self, adapter: MCPProtocolAdapter) -> None:
        """测试获取代码解释提示词"""
        await adapter.initialize()
        result = await adapter.get_prompt("explain_code", {
            "code": "print('hello')",
            "language": "python",
        })
        assert "解释" in result["messages"][0]["content"]["text"]

    @pytest.mark.asyncio
    async def test_get_prompt_debug(self, adapter: MCPProtocolAdapter) -> None:
        """测试获取调试提示词"""
        await adapter.initialize()
        result = await adapter.get_prompt("debug", {
            "code": "1/0",
            "language": "python",
            "error_message": "ZeroDivisionError",
        })
        assert "ZeroDivisionError" in result["messages"][0]["content"]["text"]

    @pytest.mark.asyncio
    async def test_get_prompt_not_found(self, adapter: MCPProtocolAdapter) -> None:
        """测试获取不存在的提示词"""
        await adapter.initialize()
        result = await adapter.get_prompt("nonexistent_prompt", {})
        assert result["isError"] is True
        assert "未找到" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_get_prompt_without_args(self, adapter: MCPProtocolAdapter) -> None:
        """测试不传参数获取提示词"""
        await adapter.initialize()
        result = await adapter.get_prompt("code_review")
        assert "messages" in result
        assert len(result["messages"]) == 1

    @pytest.mark.asyncio
    async def test_get_prompt_auto_initializes(self, adapter: MCPProtocolAdapter) -> None:
        """测试获取提示词时自动初始化"""
        result = await adapter.get_prompt("code_review", {"code": "test"})
        assert "messages" in result


# ── 服务器能力协商 ────────────────────────────────────────


class TestServerCapabilityNegotiation:
    """服务器能力协商测试"""

    @pytest.mark.asyncio
    async def test_server_info_after_init(self, adapter: MCPProtocolAdapter) -> None:
        """测试初始化后的服务器信息"""
        info = await adapter.initialize()
        assert info["name"] == "pycoder"
        assert info["version"] == "2.0.0"
        assert info["protocolVersion"] == "2024-11-05"

    @pytest.mark.asyncio
    async def test_full_capability_negotiation(self, adapter: MCPProtocolAdapter) -> None:
        """测试完整的 MCP 能力协商流程"""
        await adapter.initialize()

        server_info = adapter.server_info
        assert server_info["protocolVersion"] == MCP_PROTOCOL_VERSION

        tools = await adapter.list_tools()
        assert len(tools) >= 0

        resources = await adapter.list_resources()
        assert len(resources) == 3

        prompts = await adapter.list_prompts()
        assert len(prompts) == 5


# ── 错误处理测试 ─────────────────────────────────────────


class TestErrorHandling:
    """错误处理测试"""

    def test_error_response_format(self) -> None:
        """测试错误响应格式"""
        response = MCPProtocolAdapter._error_response("测试错误")
        assert response["isError"] is True
        assert len(response["content"]) == 1
        assert response["content"][0]["type"] == "text"
        assert response["content"][0]["text"] == "测试错误"

    @pytest.mark.asyncio
    async def test_unknown_tool_error(self, adapter: MCPProtocolAdapter) -> None:
        """测试未知工具错误"""
        result = await adapter.call_tool("completely_unknown_tool_xyz")
        assert result["isError"] is True

    @pytest.mark.asyncio
    async def test_invalid_resource_uri(self, adapter: MCPProtocolAdapter) -> None:
        """测试无效资源 URI"""
        await adapter.initialize()
        result = await adapter.read_resource("invalid://uri")
        assert result["isError"] is True

    @pytest.mark.asyncio
    async def test_invalid_prompt_name(self, adapter: MCPProtocolAdapter) -> None:
        """测试无效提示词名称"""
        await adapter.initialize()
        result = await adapter.get_prompt("不存在的提示词")
        assert result["isError"] is True


# ── JSON-RPC 消息格式验证 ────────────────────────────────


class TestJSONRPCMessageFormat:
    """JSON-RPC 消息格式验证"""

    @pytest.mark.asyncio
    async def test_tool_list_format(self, adapter: MCPProtocolAdapter) -> None:
        """测试工具列表的 JSON-RPC 格式"""
        tools = await adapter.list_tools()
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool
            assert isinstance(tool["inputSchema"], dict)
            assert "type" in tool["inputSchema"]
            assert tool["inputSchema"]["type"] == "object"

    @pytest.mark.asyncio
    async def test_tool_call_response_format(self, adapter: MCPProtocolAdapter) -> None:
        """测试工具调用响应的 JSON-RPC 格式"""
        result = await adapter.call_tool("unknown_tool")
        assert "content" in result
        assert "isError" in result
        assert isinstance(result["content"], list)
        for item in result["content"]:
            assert "type" in item
            assert item["type"] == "text"
            assert "text" in item

    @pytest.mark.asyncio
    async def test_resource_list_format(self, adapter: MCPProtocolAdapter) -> None:
        """测试资源列表的 JSON-RPC 格式"""
        await adapter.initialize()
        resources = await adapter.list_resources()
        for res in resources:
            assert "uri" in res
            assert res["uri"].startswith("pycoder://")
            assert "name" in res
            assert "mimeType" in res

    @pytest.mark.asyncio
    async def test_resource_read_format(self, adapter: MCPProtocolAdapter) -> None:
        """测试资源读取的 JSON-RPC 格式"""
        await adapter.initialize()
        result = await adapter.read_resource("pycoder://server/info")
        assert "contents" in result
        for item in result["contents"]:
            assert "uri" in item
            assert "mimeType" in item
            assert "text" in item

    @pytest.mark.asyncio
    async def test_prompt_list_format(self, adapter: MCPProtocolAdapter) -> None:
        """测试提示词列表的 JSON-RPC 格式"""
        await adapter.initialize()
        prompts = await adapter.list_prompts()
        for prompt in prompts:
            assert "name" in prompt
            assert "description" in prompt
            assert "arguments" in prompt
            for arg in prompt["arguments"]:
                assert "name" in arg
                assert "description" in arg
                assert "required" in arg

    @pytest.mark.asyncio
    async def test_prompt_get_format(self, adapter: MCPProtocolAdapter) -> None:
        """测试提示词获取的 JSON-RPC 格式"""
        await adapter.initialize()
        result = await adapter.get_prompt("code_review", {"code": "test"})
        assert "messages" in result
        for msg in result["messages"]:
            assert "role" in msg
            assert "content" in msg
            assert msg["content"]["type"] == "text"

    @pytest.mark.asyncio
    async def test_error_response_format(self, adapter: MCPProtocolAdapter) -> None:
        """测试错误响应的 JSON-RPC 格式"""
        response = MCPProtocolAdapter._error_response("发生错误")
        assert "content" in response
        assert "isError" in response
        assert response["isError"] is True
        assert len(response["content"]) == 1
        assert response["content"][0]["type"] == "text"


# ── 资源管理测试 ─────────────────────────────────────────


class TestResourceManagement:
    """资源管理测试"""

    @pytest.mark.asyncio
    async def test_register_resource(self, adapter: MCPProtocolAdapter) -> None:
        """测试注册自定义资源"""
        await adapter.initialize()
        adapter.register_resource(
            uri="pycoder://custom/resource",
            name="自定义资源",
            description="这是一个自定义资源",
            mime_type="text/plain",
        )
        resources = await adapter.list_resources()
        uris = [r["uri"] for r in resources]
        assert "pycoder://custom/resource" in uris

    @pytest.mark.asyncio
    async def test_unregister_resource(self, adapter: MCPProtocolAdapter) -> None:
        """测试注销资源"""
        await adapter.initialize()
        adapter.register_resource(
            uri="pycoder://temp/resource",
            name="临时资源",
            description="临时",
        )
        assert adapter.unregister_resource("pycoder://temp/resource") is True

        resources = await adapter.list_resources()
        uris = [r["uri"] for r in resources]
        assert "pycoder://temp/resource" not in uris

    def test_unregister_nonexistent_resource(self, adapter: MCPProtocolAdapter) -> None:
        """测试注销不存在的资源"""
        assert adapter.unregister_resource("pycoder://does/not/exist") is False


# ── 提示词管理测试 ───────────────────────────────────────


class TestPromptManagement:
    """提示词管理测试"""

    @pytest.mark.asyncio
    async def test_register_prompt(self, adapter: MCPProtocolAdapter) -> None:
        """测试注册自定义提示词"""
        await adapter.initialize()
        adapter.register_prompt(
            name="custom_prompt",
            description="自定义提示词",
            arguments=[
                {"name": "input", "description": "输入内容", "required": True},
            ],
        )
        prompts = await adapter.list_prompts()
        names = [p["name"] for p in prompts]
        assert "custom_prompt" in names

    @pytest.mark.asyncio
    async def test_unregister_prompt(self, adapter: MCPProtocolAdapter) -> None:
        """测试注销提示词"""
        await adapter.initialize()
        adapter.register_prompt(name="temp_prompt", description="临时")
        assert adapter.unregister_prompt("temp_prompt") is True

        prompts = await adapter.list_prompts()
        names = [p["name"] for p in prompts]
        assert "temp_prompt" not in names

    def test_unregister_nonexistent_prompt(self, adapter: MCPProtocolAdapter) -> None:
        """测试注销不存在的提示词"""
        assert adapter.unregister_prompt("does_not_exist") is False


# ── 全局实例测试 ─────────────────────────────────────────


class TestGlobalAdapter:
    """全局适配器实例测试"""

    def test_get_mcp_adapter_singleton(self) -> None:
        """测试全局适配器是单例"""
        a1 = get_mcp_adapter()
        a2 = get_mcp_adapter()
        assert a1 is a2

    def test_get_mcp_adapter_creates_instance(self) -> None:
        """测试首次调用创建实例"""
        import pycoder.bus.mcp_adapter as mod

        mod._mcp_adapter = None
        adapter = get_mcp_adapter()
        assert isinstance(adapter, MCPProtocolAdapter)