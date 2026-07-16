"""
LLM 深度分析器 — Layer 3 NLU

仅在歧义高于阈值时触发，使用 LLM 进行深度理解:
  - Chain-of-Thought 推理
  - 结构化 JSON 输出
  - 详细意图分解与上下文提取

为减少 Token 消耗，仅在 Layer 1+2 置信度不足时调用。
"""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)


DEEP_ANALYSIS_PROMPT = """\
你是一个专业的意图分析助手。分析以下用户的问题，输出 JSON 格式的分析结果。

用户输入: {text}

请按以下 JSON 格式输出:
```json
{{
    "core_intent": "用户的核心意图（一句话概括）",
    "task_category": "chat|hermes|agent",
    "entities": {{
        "primary_entity": "主要实体/对象",
        "secondary_entities": ["次要实体列表"],
        "tech_stack": ["相关技术栈"],
        "file_paths": ["涉及的文件路径"]
    }},
    "ambiguity_clarification": "如果有歧义，说明需要澄清什么",
    "required_context": ["需要用户补充的信息"],
    "sub_intents": ["子任务列表"],
    "urgency": "low|normal|high|critical",
    "estimated_complexity": "trivial|simple|medium|complex|epic",
    "confidence": "0-1之间的浮点数",
    "requires_code_change": true/false,
    "risks": ["潜在风险列表"]
}}
```
"""


class DeepAnalyzer:
    """Layer 3: LLM 深度 NLU 分析

    仅在必要时候调用（歧义高或规则无法分类）。
    """

    def __init__(self) -> None:
        self._chat_bridge: object = None

    async def analyze(self, text: str, context: dict | None = None) -> dict:
        """LLM 深度分析"""
        start = time.time()

        result = {
            "core_intent": text,
            "task_category": "chat",
            "entities": {},
            "ambiguation_notes": "",
            "required_context": [],
            "sub_intents": [],
            "urgency": "normal",
            "complexity": "medium",
            "confidence": 0.0,
            "requires_code_change": False,
            "risks": [],
            "processing_time_ms": 0,
        }

        llm_result = await self._call_llm(text)
        if llm_result:
            result.update(llm_result)

        result["processing_time_ms"] = round((time.time() - start) * 1000, 1)
        return result

    async def _call_llm(self, text: str) -> dict | None:
        """调用 LLM 分析"""
        try:
            from pycoder.server.chat_bridge import ChatBridge

            bridge = ChatBridge()
            bridge.configure(model="deepseek-chat", temperature=0.1, max_tokens=1024)

            prompt = DEEP_ANALYSIS_PROMPT.format(text=text)
            response = await bridge.chat(prompt, max_tokens=1024)

            # 解析 JSON
            return self._parse_json_response(response)
        except Exception as exc:
            logger.warning("LLM 深度分析失败: %s", exc)
            return None

    def _parse_json_response(self, response: str) -> dict | None:
        """从 LLM 回复中解析 JSON"""
        # 找 ```json ... ``` 块
        import re
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
        if match:
            json_str = match.group(1).strip()
        else:
            # 直接尝试解析
            json_str = response.strip()

        # 找 { }
        brace_start = json_str.find("{")
        brace_end = json_str.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            json_str = json_str[brace_start:brace_end + 1]

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("LLM 返回非 JSON 格式: %.200s", response)
            return None

    def _get_bridge(self) -> object:
        """获取 ChatBridge 实例（延迟加载）"""
        return self._chat_bridge
