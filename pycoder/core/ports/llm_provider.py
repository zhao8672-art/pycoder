"""P1-4: LLMProvider 端口 — 大语言模型调用抽象接口

核心业务逻辑通过此接口调用 LLM，不依赖具体的 ChatBridge / OpenAI / Anthropic 实现。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class LLMEvent:
    """LLM 流式响应事件"""

    event_type: str  # "token" | "reasoning" | "done" | "error"
    content: str = ""
    usage: dict = field(default_factory=dict)


@dataclass
class LLMResponse:
    """LLM 完整响应"""

    content: str
    usage: dict = field(default_factory=dict)
    model: str = ""
    finish_reason: str = ""


@runtime_checkable
class LLMProvider(Protocol):
    """LLM 调用端口 — 核心业务依赖此接口

    实现示例：BridgeLLMProvider（包装 ChatBridge）

    用法：
        async def my_business_logic(llm: LLMProvider):
            response = await llm.generate("Hello")
            print(response.content)
    """

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """同步生成完整响应"""
        ...

    def stream(
        self,
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
    ) -> AsyncIterator[LLMEvent]:
        """流式生成响应事件

        Yields:
            LLMEvent — token / reasoning / done / error
        """
        ...

    def configure(self, **kwargs) -> None:
        """配置 LLM 参数（model / temperature 等）"""
        ...
