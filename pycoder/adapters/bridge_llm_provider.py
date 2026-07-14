"""P1-4: BridgeLLMProvider — 包装 ChatBridge 实现 LLMProvider 端口

将现有的 ChatBridge 适配为符合 LLMProvider Protocol 的实现。

H3: ChatBridge 类型仅用于类型注解（TYPE_CHECKING），运行时不直接 import server，
消除 adapter → server 的模块级反向依赖。ChatBridge 实例由调用方注入。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from pycoder.core.ports.llm_provider import (
    LLMEvent,
    LLMResponse,
)

if TYPE_CHECKING:
    # H3: 仅类型检查时导入 ChatBridge，运行时由调用方注入实例
    from pycoder.server.chat_bridge import ChatBridge


class BridgeLLMProvider:
    """LLMProvider 适配器 — 包装 ChatBridge

    用法：
        bridge = ChatBridge()
        provider = BridgeLLMProvider(bridge)
        response = await provider.generate("Hello")
    """

    def __init__(self, bridge: ChatBridge) -> None:
        self._bridge = bridge

    def add_message(self, role: str, content: str) -> None:
        """添加消息到对话上下文（委托给内部 ChatBridge）"""
        self._bridge.add_message(role, content)

    def configure(self, **kwargs) -> None:
        """配置 ChatBridge（model / api_key / max_tokens / system_prompt 等）"""
        bridge_kwargs = {}
        for k in (
            "model",
            "api_key",
            "api_base",
            "temperature",
            "reasoning_effort",
            "enable_thinking",
            "enable_cache",
        ):
            if k in kwargs:
                bridge_kwargs[k] = kwargs[k]
        if bridge_kwargs:
            self._bridge.configure(**bridge_kwargs)
        if "system_prompt" in kwargs:
            self._bridge.config.system_prompt = kwargs["system_prompt"]
        if "max_tokens" in kwargs:
            self._bridge.config.max_tokens = kwargs["max_tokens"]

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """同步生成完整响应（收集所有 token）"""
        if system_prompt:
            self._bridge.config.system_prompt = system_prompt
        self._bridge.config.max_tokens = max_tokens

        content = ""
        usage: dict = {}
        async for event in self._bridge.chat_stream(prompt):
            if event.event_type == "token":
                content += event.content
            elif event.event_type == "done":
                content = event.content or content
                usage = event.usage or {}
                break

        return LLMResponse(
            content=content,
            usage=usage,
            model=getattr(self._bridge.config, "model", ""),
        )

    async def stream(
        self,
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
    ) -> AsyncIterator[LLMEvent]:
        """流式生成响应事件"""
        if system_prompt:
            self._bridge.config.system_prompt = system_prompt
        self._bridge.config.max_tokens = max_tokens

        async for event in self._bridge.chat_stream(prompt):
            yield LLMEvent(
                event_type=event.event_type,
                content=event.content,
                usage=getattr(event, "usage", {}),
            )
