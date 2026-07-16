"""
单次代码生成器 — SINGLE_PASS 策略

适用场景: 简单函数、工具方法、配置代码 (< 50 行)
特点: 一次 LLM 调用，快速返回
"""

from __future__ import annotations

import logging
import time

from pycoder.ai.interface.types import (
    CodeGenerationRequest,
    CodeGenerationResult,
    CodeGenStrategy,
)

logger = logging.getLogger(__name__)

# 生成提示词模板
SINGLE_PASS_PROMPT = """\
你是一个代码生成助手。根据以下要求生成代码。

{instruction}

要求:
{constraints_text}

语言: {language}
{context_text}

请只输出代码，用 ``` 包裹。
"""


class SinglePassGenerator:
    """单次代码生成器 — 一次 LLM 调用完成"""

    def __init__(self) -> None:
        self._bridge: object = None

    async def generate(self, request: CodeGenerationRequest) -> CodeGenerationResult:
        """单次生成代码"""
        start = time.time()

        constraints_text = ""
        if request.constraints:
            constraints_text = "\n".join(f"- {c}" for c in request.constraints)

        context_text = ""
        if request.context:
            context_text = f"\n上下文代码:\n```\n{request.context}\n```"

        prompt = SINGLE_PASS_PROMPT.format(
            instruction=request.prompt,
            constraints_text=constraints_text,
            language=request.language or "python",
            context_text=context_text,
        )

        llm_code, usage = await self._call_llm(
            prompt, request.max_tokens, request.temperature
        )

        duration = (time.time() - start) * 1000

        return CodeGenerationResult(
            code=llm_code,
            language=request.language or "python",
            strategy_used=CodeGenStrategy.SINGLE_PASS,
            token_usage=usage or {},
            generation_time_ms=round(duration, 1),
            passes_tests=True,
            confidence=0.8,
        )

    async def _call_llm(
        self, prompt: str, max_tokens: int, temperature: float
    ) -> tuple[str, dict]:
        """调用 LLM"""
        try:
            from pycoder.server.chat_bridge import ChatBridge

            bridge = ChatBridge()
            bridge.configure(
                model="deepseek-chat",
                temperature=temperature,
                max_tokens=max_tokens,
            )
            response = await bridge.chat(prompt, max_tokens=max_tokens)
            code = self._extract_code(response)
            return code, {}
        except Exception as exc:
            logger.error("LLM 调用失败: %s", exc)
            return f"# 生成失败: {exc}", {}

    def _extract_code(self, response: str) -> str:
        """从 LLM 回复中提取代码块"""
        import re
        match = re.search(r"```(?:\w+)?\s*\n(.*?)```", response, re.DOTALL)
        if match:
            return match.group(1).strip()
        return response.strip()

    async def complete(self, prefix: str, suffix: str = "", language: str = "") -> str:
        """FIM 补全（基础版）"""
        prompt = f"补全以下{language}代码:\n```\n{prefix}█{suffix}\n```\n只输出█位置的补全代码："
        code, _ = await self._call_llm(prompt, 512, 0.2)
        return code
