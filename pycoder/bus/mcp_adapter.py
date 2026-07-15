"""
标准 MCP 协议适配器 — 兼容 OpenClaw / Hermes 生态

实现标准 Model Context Protocol (MCP)，使 PyCoder 能与
外部 MCP 客户端和服务器互操作。

支持:
- tools/list, tools/call — 工具发现与调用
- resources/list, resources/read — 资源发现与读取
- prompts/list, prompts/get — 提示词发现与获取
- PyCoder V2 能力 ↔ MCP 工具格式 双向转换
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pycoder.bus.protocol import (
    CapabilityCall,
    CapabilityCategory,
    CapabilityDefinition,
    CapabilityResult,
    ExecutionMode,
    SideEffect,
    TrustLevel,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# MCP 协议常量
# ──────────────────────────────────────────────

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_SERVER_NAME = "pycoder"
MCP_SERVER_VERSION = "2.0.0"


# ──────────────────────────────────────────────
# 工具格式转换
# ──────────────────────────────────────────────


def _capability_to_mcp_tool(cap: CapabilityDefinition) -> dict[str, Any]:
    """将 PyCoder V2 能力定义转换为 MCP 工具格式"""
    return {
        "name": cap.id.replace(".", "_"),
        "description": cap.description,
        "inputSchema": cap.schema or {"type": "object", "properties": {}},
        "annotations": {
            "category": cap.category.value,
            "permission": cap.permission.name,
            "execution": cap.execution.value,
            "side_effects": [se.value for se in cap.side_effects],
            "version": cap.version,
            "tags": cap.tags,
            "deprecated": cap.deprecated,
        },
    }


def _mcp_name_to_capability_id(name: str) -> str:
    """将 MCP 工具名转换回 PyCoder 能力 ID"""
    return name.replace("_", ".")


# ──────────────────────────────────────────────
# MCP 协议适配器
# ──────────────────────────────────────────────


class MCPProtocolAdapter:
    """
    标准 MCP 协议适配器

    实现 tools/list、tools/call、resources/list、resources/read、
    prompts/list、prompts/get 六个核心 MCP 方法，
    与 PyCoder 内部能力总线桥接。

    使用方式:
        adapter = MCPProtocolAdapter(registry)
        tools = await adapter.list_tools()
        result = await adapter.call_tool("read_file", {"path": "main.py"})
    """

    def __init__(self, registry: Any = None):
        """
        初始化 MCP 协议适配器

        Args:
            registry: CapabilityRegistry 实例，如果为 None 则延迟获取
        """
        self._registry = registry
        self._resources: dict[str, dict[str, Any]] = {}
        self._prompts: dict[str, dict[str, Any]] = {}
        self._initialized = False

    # ── 属性 ──────────────────────────────────

    @property
    def registry(self) -> Any:
        """获取能力注册表（延迟加载）"""
        if self._registry is None:
            try:
                from pycoder.server.app import get_v2_engine

                engine = get_v2_engine()
                if engine:
                    self._registry = engine.registry
            except ImportError:
                pass
        return self._registry

    @property
    def server_info(self) -> dict[str, Any]:
        """获取 MCP 服务器信息"""
        return {
            "name": MCP_SERVER_NAME,
            "version": MCP_SERVER_VERSION,
            "protocolVersion": MCP_PROTOCOL_VERSION,
        }

    # ── 初始化 ────────────────────────────────

    async def initialize(self) -> dict[str, Any]:
        """初始化 MCP 适配器，注册内置资源和提示词"""
        if self._initialized:
            return self.server_info

        self._register_builtin_resources()
        self._register_builtin_prompts()
        self._initialized = True
        logger.info("MCP 协议适配器已初始化，协议版本: %s", MCP_PROTOCOL_VERSION)
        return self.server_info

    def _register_builtin_resources(self) -> None:
        """注册内置 MCP 资源"""
        self._resources = {
            "pycoder://capabilities": {
                "uri": "pycoder://capabilities",
                "name": "能力清单",
                "description": "PyCoder 当前所有已注册的能力列表",
                "mimeType": "application/json",
            },
            "pycoder://server/info": {
                "uri": "pycoder://server/info",
                "name": "服务器信息",
                "description": "PyCoder 服务器版本和配置信息",
                "mimeType": "application/json",
            },
            "pycoder://workspace/status": {
                "uri": "pycoder://workspace/status",
                "name": "工作区状态",
                "description": "当前工作区的项目状态概览",
                "mimeType": "application/json",
            },
        }

    def _register_builtin_prompts(self) -> None:
        """注册内置 MCP 提示词模板"""
        self._prompts = {
            "code_review": {
                "name": "code_review",
                "description": "对指定代码进行审查",
                "arguments": [
                    {
                        "name": "code",
                        "description": "要审查的代码内容",
                        "required": True,
                    },
                    {
                        "name": "language",
                        "description": "编程语言",
                        "required": False,
                    },
                ],
            },
            "refactor": {
                "name": "refactor",
                "description": "重构指定代码",
                "arguments": [
                    {
                        "name": "code",
                        "description": "要重构的代码",
                        "required": True,
                    },
                    {
                        "name": "goal",
                        "description": "重构目标（如: 提取函数、简化逻辑）",
                        "required": False,
                    },
                ],
            },
            "generate_tests": {
                "name": "generate_tests",
                "description": "为指定代码生成单元测试",
                "arguments": [
                    {
                        "name": "code",
                        "description": "需要生成测试的代码",
                        "required": True,
                    },
                    {
                        "name": "framework",
                        "description": "测试框架（pytest/unittest）",
                        "required": False,
                    },
                ],
            },
            "explain_code": {
                "name": "explain_code",
                "description": "解释代码的功能和逻辑",
                "arguments": [
                    {
                        "name": "code",
                        "description": "需要解释的代码",
                        "required": True,
                    },
                ],
            },
            "debug": {
                "name": "debug",
                "description": "分析代码中的潜在 bug",
                "arguments": [
                    {
                        "name": "code",
                        "description": "需要调试的代码",
                        "required": True,
                    },
                    {
                        "name": "error_message",
                        "description": "错误信息（如有）",
                        "required": False,
                    },
                ],
            },
        }

    # ── tools/list ────────────────────────────

    async def list_tools(self) -> list[dict[str, Any]]:
        """
        MCP tools/list 实现

        列出所有已注册的 PyCoder 能力，转换为 MCP 工具格式。

        Returns:
            MCP 工具定义列表
        """
        if self.registry is None:
            logger.warning("能力注册表未初始化，无法列出工具")
            return []

        caps = self.registry.list_all()
        tools = [_capability_to_mcp_tool(cap) for cap in caps if not cap.deprecated]
        logger.debug("列出 %d 个 MCP 工具", len(tools))
        return tools

    # ── tools/call ────────────────────────────

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        MCP tools/call 实现

        调用指定的 PyCoder 能力，返回 MCP 格式的结果。

        Args:
            name: 工具名称（MCP 格式，下划线分隔）
            arguments: 工具参数

        Returns:
            MCP 格式的调用结果
        """
        args = arguments or {}
        capability_id = _mcp_name_to_capability_id(name)

        if self.registry is None:
            return self._error_response(f"能力注册表未初始化，无法调用工具: {name}")

        # 尝试多种 ID 格式
        candidate_ids = [capability_id, f"tools.{capability_id}", f"v1.{capability_id}"]
        result = None

        for cid in candidate_ids:
            if self.registry.exists(cid):
                try:
                    call = CapabilityCall(capability_id=cid, params=args, caller="mcp_adapter")
                    result = await self.registry.call(call, {"caller": "mcp_adapter"})
                    break
                except Exception as e:
                    logger.error("调用工具 '%s' (ID: %s) 失败: %s", name, cid, e)
                    return self._error_response(f"工具调用失败: {e}")

        if result is None:
            return self._error_response(f"工具未找到: {name}")

        return self._capability_result_to_mcp(result)

    def _capability_result_to_mcp(self, result: CapabilityResult) -> dict[str, Any]:
        """将 CapabilityResult 转换为 MCP 响应格式"""
        if not result.success:
            return self._error_response(result.error or "未知错误")

        data = result.data
        content = []

        if isinstance(data, str):
            content.append({"type": "text", "text": data})
        elif isinstance(data, dict):
            import json

            content.append(
                {
                    "type": "text",
                    "text": json.dumps(data, ensure_ascii=False, indent=2, default=str),
                }
            )
        elif data is not None:
            content.append({"type": "text", "text": str(data)})
        else:
            content.append({"type": "text", "text": "执行成功"})

        return {
            "content": content,
            "isError": False,
            "_meta": {
                "trace_id": result.trace_id,
                "duration_ms": result.duration_ms,
                "capability_id": result.capability_id,
            },
        }

    @staticmethod
    def _error_response(message: str) -> dict[str, Any]:
        """生成 MCP 错误响应"""
        return {
            "content": [{"type": "text", "text": message}],
            "isError": True,
        }

    # ── resources/list ────────────────────────

    async def list_resources(self) -> list[dict[str, Any]]:
        """
        MCP resources/list 实现

        列出所有可用的 MCP 资源。

        Returns:
            MCP 资源定义列表
        """
        if not self._initialized:
            await self.initialize()

        resources = list(self._resources.values())
        logger.debug("列出 %d 个 MCP 资源", len(resources))
        return resources

    # ── resources/read ────────────────────────

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """
        MCP resources/read 实现

        读取指定 URI 的资源内容。

        Args:
            uri: 资源 URI

        Returns:
            MCP 资源内容
        """
        if not self._initialized:
            await self.initialize()

        resource = self._resources.get(uri)
        if resource is None:
            return self._error_response(f"资源未找到: {uri}")

        # 动态生成资源内容
        if uri == "pycoder://capabilities":
            return await self._read_capabilities_resource()
        elif uri == "pycoder://server/info":
            return await self._read_server_info_resource()
        elif uri == "pycoder://workspace/status":
            return await self._read_workspace_status_resource()
        else:
            return self._error_response(f"不支持的资源 URI: {uri}")

    async def _read_capabilities_resource(self) -> dict[str, Any]:
        """读取能力清单资源"""
        tools = await self.list_tools()
        import json

        return {
            "contents": [
                {
                    "uri": "pycoder://capabilities",
                    "mimeType": "application/json",
                    "text": json.dumps(
                        {
                            "server": self.server_info,
                            "total_tools": len(tools),
                            "tools": tools,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                }
            ]
        }

    async def _read_server_info_resource(self) -> dict[str, Any]:
        """读取服务器信息资源"""
        import json
        import sys

        info = {
            **self.server_info,
            "python_version": sys.version,
            "platform": sys.platform,
        }
        return {
            "contents": [
                {
                    "uri": "pycoder://server/info",
                    "mimeType": "application/json",
                    "text": json.dumps(info, ensure_ascii=False, indent=2),
                }
            ]
        }

    async def _read_workspace_status_resource(self) -> dict[str, Any]:
        """读取工作区状态资源"""
        import json
        import os
        from pathlib import Path

        cwd = Path.cwd()
        status = {
            "workspace": str(cwd),
            "exists": cwd.exists(),
            "python_files": len(list(cwd.rglob("*.py"))),
            "git": (cwd / ".git").exists(),
        }
        return {
            "contents": [
                {
                    "uri": "pycoder://workspace/status",
                    "mimeType": "application/json",
                    "text": json.dumps(status, ensure_ascii=False, indent=2),
                }
            ]
        }

    # ── prompts/list ──────────────────────────

    async def list_prompts(self) -> list[dict[str, Any]]:
        """
        MCP prompts/list 实现

        列出所有可用的 MCP 提示词模板。

        Returns:
            MCP 提示词定义列表
        """
        if not self._initialized:
            await self.initialize()

        prompts = list(self._prompts.values())
        logger.debug("列出 %d 个 MCP 提示词", len(prompts))
        return prompts

    # ── prompts/get ───────────────────────────

    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        MCP prompts/get 实现

        获取指定名称的提示词，填入参数后返回。

        Args:
            name: 提示词名称
            arguments: 提示词参数

        Returns:
            填充后的 MCP 提示词消息
        """
        if not self._initialized:
            await self.initialize()

        args = arguments or {}
        prompt = self._prompts.get(name)

        if prompt is None:
            return self._error_response(f"提示词未找到: {name}")

        messages = self._render_prompt(prompt, args)
        return {"messages": messages}

    def _render_prompt(
        self, prompt: dict[str, Any], arguments: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """根据提示词模板和参数渲染消息列表"""
        name = prompt["name"]
        code = arguments.get("code", "")
        language = arguments.get("language", "python")
        goal = arguments.get("goal", "")
        framework = arguments.get("framework", "pytest")
        error_message = arguments.get("error_message", "")

        prompt_templates: dict[str, str] = {
            "code_review": (
                f"请对以下 {language} 代码进行审查，"
                "检查代码质量、潜在 bug、安全问题和最佳实践:\n\n```{language}\n{code}\n```"
            ),
            "refactor": (
                f"请重构以下 {language} 代码"
                + (f"，目标: {goal}" if goal else "")
                + f":\n\n```{language}\n{code}\n```"
            ),
            "generate_tests": (
                f"请为以下 {language} 代码生成 {framework} 单元测试"
                "，确保覆盖主要功能和边界情况:\n\n```{language}\n{code}\n```"
            ),
            "explain_code": (
                f"请详细解释以下 {language} 代码的功能和逻辑:\n\n```{language}\n{code}\n```"
            ),
            "debug": (
                f"请分析以下 {language} 代码中的潜在 bug"
                + (f"，已知错误信息: {error_message}" if error_message else "")
                + f":\n\n```{language}\n{code}\n```"
            ),
        }

        text = prompt_templates.get(name, f"提示词 '{name}' 无预定义模板")
        # 替换占位符
        text = text.replace("{code}", code).replace("{language}", language)

        return [
            {
                "role": "user",
                "content": {"type": "text", "text": text},
            }
        ]

    # ── 资源管理 ──────────────────────────────

    def register_resource(self, uri: str, name: str, description: str, mime_type: str = "text/plain") -> None:
        """注册自定义 MCP 资源"""
        self._resources[uri] = {
            "uri": uri,
            "name": name,
            "description": description,
            "mimeType": mime_type,
        }
        logger.info("MCP 资源已注册: %s (%s)", uri, name)

    def unregister_resource(self, uri: str) -> bool:
        """注销 MCP 资源"""
        if uri in self._resources:
            del self._resources[uri]
            logger.info("MCP 资源已注销: %s", uri)
            return True
        return False

    def register_prompt(self, name: str, description: str, arguments: list[dict[str, Any]] | None = None) -> None:
        """注册自定义 MCP 提示词"""
        self._prompts[name] = {
            "name": name,
            "description": description,
            "arguments": arguments or [],
        }
        logger.info("MCP 提示词已注册: %s", name)

    def unregister_prompt(self, name: str) -> bool:
        """注销 MCP 提示词"""
        if name in self._prompts:
            del self._prompts[name]
            logger.info("MCP 提示词已注销: %s", name)
            return True
        return False


# ──────────────────────────────────────────────
# 全局实例
# ──────────────────────────────────────────────

_mcp_adapter: MCPProtocolAdapter | None = None


def get_mcp_adapter() -> MCPProtocolAdapter:
    """获取全局 MCP 协议适配器实例"""
    global _mcp_adapter
    if _mcp_adapter is None:
        _mcp_adapter = MCPProtocolAdapter()
    return _mcp_adapter


# ──────────────────────────────────────────────
# 能力注册
# ──────────────────────────────────────────────


def register_capabilities(registry: Any) -> None:
    """
    向总线注册 MCP 协议适配器相关能力

    注册的能力:
    - mcp.tools.list — 列出所有 MCP 工具
    - mcp.tools.call — 调用 MCP 工具
    - mcp.resources.list — 列出 MCP 资源
    - mcp.resources.read — 读取 MCP 资源
    - mcp.prompts.list — 列出 MCP 提示词
    - mcp.prompts.get — 获取 MCP 提示词
    - mcp.server.info — 获取 MCP 服务器信息

    Args:
        registry: CapabilityRegistry 实例
    """
    adapter = get_mcp_adapter()

    # ── MCP tools/list ──
    registry.register(
        CapabilityDefinition(
            id="mcp.tools.list",
            name="列出 MCP 工具",
            description="列出所有已注册的 PyCoder 能力（MCP 工具格式）",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["mcp", "tools", "list", "工具列表"],
        ),
        handler=_handle_tools_list,
    )

    # ── MCP tools/call ──
    registry.register(
        CapabilityDefinition(
            id="mcp.tools.call",
            name="调用 MCP 工具",
            description="通过 MCP 协议调用指定的 PyCoder 能力",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "工具名称"},
                    "arguments": {"type": "object", "description": "工具参数"},
                },
                "required": ["name"],
            },
            tags=["mcp", "tools", "call", "调用"],
        ),
        handler=_handle_tools_call,
    )

    # ── MCP resources/list ──
    registry.register(
        CapabilityDefinition(
            id="mcp.resources.list",
            name="列出 MCP 资源",
            description="列出所有可用的 MCP 资源",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["mcp", "resources", "list", "资源"],
        ),
        handler=_handle_resources_list,
    )

    # ── MCP resources/read ──
    registry.register(
        CapabilityDefinition(
            id="mcp.resources.read",
            name="读取 MCP 资源",
            description="读取指定 URI 的 MCP 资源内容",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            schema={
                "type": "object",
                "properties": {
                    "uri": {"type": "string", "description": "资源 URI"},
                },
                "required": ["uri"],
            },
            tags=["mcp", "resources", "read", "读取"],
        ),
        handler=_handle_resources_read,
    )

    # ── MCP prompts/list ──
    registry.register(
        CapabilityDefinition(
            id="mcp.prompts.list",
            name="列出 MCP 提示词",
            description="列出所有可用的 MCP 提示词模板",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["mcp", "prompts", "list", "提示词"],
        ),
        handler=_handle_prompts_list,
    )

    # ── MCP prompts/get ──
    registry.register(
        CapabilityDefinition(
            id="mcp.prompts.get",
            name="获取 MCP 提示词",
            description="获取并填充指定名称的 MCP 提示词模板",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "提示词名称"},
                    "arguments": {"type": "object", "description": "提示词参数"},
                },
                "required": ["name"],
            },
            tags=["mcp", "prompts", "get", "获取"],
        ),
        handler=_handle_prompts_get,
    )

    # ── MCP server/info ──
    registry.register(
        CapabilityDefinition(
            id="mcp.server.info",
            name="MCP 服务器信息",
            description="获取 PyCoder MCP 服务器的元信息",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["mcp", "server", "info"],
        ),
        handler=_handle_server_info,
    )

    logger.info("MCP 协议适配器能力已注册（7 个能力）")


# ── 处理器实现 ────────────────────────────────


async def _handle_tools_list(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理 tools/list 请求"""
    adapter = get_mcp_adapter()
    tools = await adapter.list_tools()
    return {"tools": tools, "count": len(tools)}


async def _handle_tools_call(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理 tools/call 请求"""
    adapter = get_mcp_adapter()
    name = params["name"]
    arguments = params.get("arguments", {})
    return await adapter.call_tool(name, arguments)


async def _handle_resources_list(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理 resources/list 请求"""
    adapter = get_mcp_adapter()
    resources = await adapter.list_resources()
    return {"resources": resources, "count": len(resources)}


async def _handle_resources_read(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理 resources/read 请求"""
    adapter = get_mcp_adapter()
    uri = params["uri"]
    return await adapter.read_resource(uri)


async def _handle_prompts_list(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理 prompts/list 请求"""
    adapter = get_mcp_adapter()
    prompts = await adapter.list_prompts()
    return {"prompts": prompts, "count": len(prompts)}


async def _handle_prompts_get(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理 prompts/get 请求"""
    adapter = get_mcp_adapter()
    name = params["name"]
    arguments = params.get("arguments", {})
    return await adapter.get_prompt(name, arguments)


async def _handle_server_info(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理 server/info 请求"""
    adapter = get_mcp_adapter()
    return adapter.server_info