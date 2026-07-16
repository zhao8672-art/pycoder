"""
迭代代码生成器 — ITERATIVE 策略

适用场景: 复杂算法、多步骤实现 (> 50 行)
特点: 生成→验证→反馈→优化，最多 3 轮迭代

流程:
  Round 1: 生成初始代码
  Round 2: 代码审查 + 问题修复
  Round 3: 最终优化 + 测试验证
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


ITERATION_PROMPTS = {
    "generate": """\
根据以下要求生成{language}代码。

要求: {instruction}

{constraints_text}
{context_text}

请输出完整的实现代码，包含适当的注释和错误处理。
""",

    "review": """\
审查以下 {language} 代码的质量:

```{language}
{code}
```

原始需求: {instruction}

请指出:
1. 逻辑错误
2. 边界情况处理
3. 性能问题
4. 代码风格问题
5. 安全风险

输出问题列表（按严重程度排序）。
""",

    "improve": """\
基于以下审查意见改进代码:

```{language}
{code}
```

审查意见: {review}

原始需求: {instruction}

请输出改进后的完整代码。
""",
}


class IterativeGenerator:
    """迭代代码生成器 — 多轮优化"""

    MAX_ITERATIONS = 3

    def __init__(self) -> None:
        self._bridge: object = None

    async def generate(self, request: CodeGenerationRequest) -> CodeGenerationResult:
        """迭代生成代码"""
        start = time.time()
        all_tokens = {}
        full_history = []

        constraints_text = ""
        if request.constraints:
            constraints_text = "\n".join(f"- {c}" for c in request.constraints)

        context_text = ""
        if request.context:
            context_text = f"\n上下文代码:\n```\n{request.context}\n```"

        lang = request.language or "python"
        current_code = ""
        final_code = ""
        passes = True

        for iteration in range(self.MAX_ITERATIONS):
            iteration_start = time.time()

            if iteration == 0:
                # Round 1: 生成
                prompt = ITERATION_PROMPTS["generate"].format(
                    language=lang,
                    instruction=request.prompt,
                    constraints_text=constraints_text,
                    context_text=context_text,
                )
                response = await self._call_llm(prompt, request.max_tokens, request.temperature)
                current_code = self._extract_code(response)

            elif iteration == 1:
                # Round 2: 审查
                if not current_code.strip():
                    continue
                prompt = ITERATION_PROMPTS["review"].format(
                    language=lang,
                    code=current_code,
                    instruction=request.prompt,
                )
                review = await self._call_llm(prompt, 1024, 0.3)

                # 检查是否有严重问题
                if "无问题" in review or "没有发现" in review or len(review) < 50:
                    final_code = current_code
                    passes = True
                    break

                # Round 2.5: 修复
                prompt = ITERATION_PROMPTS["improve"].format(
                    language=lang,
                    code=current_code,
                    review=review,
                    instruction=request.prompt,
                )
                response = await self._call_llm(prompt, request.max_tokens, 0.3)
                current_code = self._extract_code(response)

            elif iteration == 2:
                # Round 3: 最终优化
                prompt = f"""优化以下 {lang} 代码的健壮性和性能:

```{lang}
{current_code}
```

请添加:
- 输入验证
- 边界条件处理
- 错误处理
- 性能优化（如适用）

输出优化后的完整代码。"""
                response = await self._call_llm(prompt, request.max_tokens, 0.2)
                current_code = self._extract_code(response)

            full_history.append({
                "iteration": iteration,
                "code": current_code,
                "duration_ms": round((time.time() - iteration_start) * 1000, 1),
            })

        final_code = current_code if current_code.strip() else final_code
        if not final_code.strip():
            final_code = current_code

        duration = (time.time() - start) * 1000

        return CodeGenerationResult(
            code=final_code,
            language=lang,
            strategy_used=CodeGenStrategy.ITERATIVE,
            token_usage=all_tokens,
            generation_time_ms=round(duration, 1),
            passes_tests=passes,
            alternatives=[h["code"] for h in full_history[:-1] if h["code"] != final_code],
            confidence=0.85 if passes else 0.6,
        )

    async def _call_llm(
        self, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        """调用 LLM"""
        try:
            from pycoder.server.chat_bridge import ChatBridge

            bridge = ChatBridge()
            bridge.configure(
                model="deepseek-chat",
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return await bridge.chat(prompt, max_tokens=max_tokens)
        except Exception as exc:
            logger.error("LLM 调用失败: %s", exc)
            return f"# 生成失败: {exc}"

    def _extract_code(self, response: str) -> str:
        """提取代码块"""
        match = re.search(r"```(?:\w+)?\s*\n(.*?)```", response, re.DOTALL)
        if match:
            return match.group(1).strip()
        return response.strip()
