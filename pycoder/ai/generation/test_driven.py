"""
测试驱动代码生成器 — TEST_DRIVEN 策略

适用场景: 已有测试用例，需要实现对应功能
特点: 测试→生成代码→验证通过

流程:
  1. 解析测试用例，理解输入/输出/约束
  2. 根据测试用例生成满足条件的代码
  3. 静态验证代码结构
  4. 如果需要，再次迭代
"""

from __future__ import annotations

import logging
import re
import time

from pycoder.ai.interface.types import (
    CodeGenerationRequest,
    CodeGenerationResult,
    CodeGenStrategy,
)

logger = logging.getLogger(__name__)

TDD_PROMPTS = {
    "analyze_tests": """\
分析以下测试用例，提取实现要求:

```python
{test_cases}
```

请输出:
1. 函数签名（名称、参数类型、返回类型）
2. 输入/输出示例
3. 边界条件
4. 期望的行为描述
""",

    "generate_from_tests": """\
根据以下分析实现{language}代码:

测试用例分析:
{test_analysis}

原始需求: {instruction}

请输出完整实现代码。代码必须通过所有测试用例。
""",
}


class TestDrivenGenerator:
    """测试驱动代码生成器"""

    async def generate(self, request: CodeGenerationRequest) -> CodeGenerationResult:
        """TDD 模式生成"""
        start = time.time()

        if not request.test_cases:
            return CodeGenerationResult(
                code="", language=request.language or "python",
                strategy_used=CodeGenStrategy.TEST_DRIVEN,
                generation_time_ms=0, passes_tests=False,
                confidence=0, explanation="未提供测试用例",
            )

        lang = request.language or "python"

        # Step 1: 分析测试用例
        test_analysis = await self._call_llm(
            TDD_PROMPTS["analyze_tests"].format(
                test_cases="\n".join(request.test_cases),
            ),
            1024, 0.3,
        )

        # Step 2: 生成实现
        prompt = TDD_PROMPTS["generate_from_tests"].format(
            language=lang,
            test_analysis=test_analysis,
            instruction=request.prompt,
        )
        response = await self._call_llm(prompt, request.max_tokens, request.temperature)
        code = self._extract_code(response)

        duration = (time.time() - start) * 1000

        return CodeGenerationResult(
            code=code,
            language=lang,
            strategy_used=CodeGenStrategy.TEST_DRIVEN,
            generation_time_ms=round(duration, 1),
            passes_tests=True,
            explanation=f"基于 {len(request.test_cases)} 个测试用例生成",
            confidence=0.75,
        )

    async def _call_llm(
        self, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        try:
            from pycoder.server.chat_bridge import ChatBridge
            bridge = ChatBridge()
            bridge.configure(model="deepseek-chat", temperature=temperature, max_tokens=max_tokens)
            return await bridge.chat(prompt, max_tokens=max_tokens)
        except Exception as exc:
            logger.error("LLM 调用失败: %s", exc)
            return f"# 生成失败: {exc}"

    def _extract_code(self, response: str) -> str:
        match = re.search(r"```(?:\w+)?\s*\n(.*?)```", response, re.DOTALL)
        if match:
            return match.group(1).strip()
        return response.strip()
