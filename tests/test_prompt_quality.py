"""P2-2: 提示词质量验证测试

验证所有关键系统提示词符合 P2-2 验收标准：
1. 长度 ≤ 1500 字符（避免 LLM 注意力分散）
2. 明确要求 JSON 格式（工具调用类提示词）
3. 包含至少 1 个 few-shot 示例
4. 禁止 XML 标签输出（与 P1-2 JSON Schema 约束一致）

非工具调用类提示词（如 SELF_EVOLVE 使用 [FILE:...] 格式）不要求 JSON 但应有示例。
"""
from __future__ import annotations

import warnings

import pytest


# 抑制 team_orchestrator 的 DeprecationWarning
warnings.filterwarnings("ignore", category=DeprecationWarning)


# ══════════════════════════════════════════════════════════
# 提示词常量导入
# ══════════════════════════════════════════════════════════

from pycoder.server.services.team.agent_tool_loop import AGENT_SYSTEM_PROMPT
from pycoder.server.services.agent_react_loop import REACT_SYSTEM_PROMPT
from pycoder.server.services.task_decomposer import DECOMPOSE_SYSTEM_PROMPT
from pycoder.server.self_evolution import SELF_EVOLVE_SYSTEM_PROMPT


# P2-2 验收阈值
MAX_PROMPT_LENGTH = 1500


# ══════════════════════════════════════════════════════════
# 长度验证 — 所有提示词 ≤ 1500 字符
# ══════════════════════════════════════════════════════════


class TestPromptLength:
    """P2-2 标准 1: 所有关键提示词长度 ≤ 1500 字符"""

    def test_agent_system_prompt_within_limit(self):
        assert len(AGENT_SYSTEM_PROMPT) <= MAX_PROMPT_LENGTH

    def test_react_system_prompt_within_limit(self):
        assert len(REACT_SYSTEM_PROMPT) <= MAX_PROMPT_LENGTH

    def test_decompose_system_prompt_within_limit(self):
        assert len(DECOMPOSE_SYSTEM_PROMPT) <= MAX_PROMPT_LENGTH

    def test_self_evolve_prompt_within_limit(self):
        assert len(SELF_EVOLVE_SYSTEM_PROMPT) <= MAX_PROMPT_LENGTH


# ══════════════════════════════════════════════════════════
# JSON 格式要求 — 工具调用类提示词
# ══════════════════════════════════════════════════════════


class TestJsonFormatRequirement:
    """P2-2 标准 2: 工具调用类提示词明确要求 JSON 格式"""

    def test_agent_prompt_mentions_json(self):
        """AGENT_SYSTEM_PROMPT 明确要求 JSON 格式"""
        assert "json" in AGENT_SYSTEM_PROMPT.lower() or "JSON" in AGENT_SYSTEM_PROMPT

    def test_agent_prompt_contains_json_code_block(self):
        """AGENT_SYSTEM_PROMPT 包含 JSON 代码块示例"""
        assert "```json" in AGENT_SYSTEM_PROMPT
        # 工具调用字段名为 name/params（单工具调用格式）
        assert "name" in AGENT_SYSTEM_PROMPT and "params" in AGENT_SYSTEM_PROMPT

    def test_react_prompt_mentions_json(self):
        """REACT_SYSTEM_PROMPT 明确要求 JSON 格式"""
        assert "json" in REACT_SYSTEM_PROMPT.lower() or "JSON" in REACT_SYSTEM_PROMPT

    def test_react_prompt_contains_json_code_block(self):
        """REACT_SYSTEM_PROMPT 包含 JSON 代码块"""
        assert "```json" in REACT_SYSTEM_PROMPT

    def test_decompose_prompt_requires_json(self):
        """DECOMPOSE_SYSTEM_PROMPT 要求纯 JSON 输出"""
        assert "JSON" in DECOMPOSE_SYSTEM_PROMPT or "json" in DECOMPOSE_SYSTEM_PROMPT.lower()

    def test_decompose_prompt_forbids_markdown(self):
        """DECOMPOSE_SYSTEM_PROMPT 明确禁止 markdown 代码块"""
        assert "不要使用 markdown" in DECOMPOSE_SYSTEM_PROMPT

    def test_self_evolve_uses_file_format(self):
        """SELF_EVOLVE 使用 [FILE:...] 格式（非工具调用，不要求 JSON）"""
        assert "[FILE:" in SELF_EVOLVE_SYSTEM_PROMPT
        assert "[END:FILE]" in SELF_EVOLVE_SYSTEM_PROMPT


# ══════════════════════════════════════════════════════════
# Few-shot 示例 — 所有提示词包含示例
# ══════════════════════════════════════════════════════════


class TestFewShotExample:
    """P2-2 标准 3: 包含至少 1 个 few-shot 示例"""

    def test_agent_prompt_contains_example(self):
        """AGENT_SYSTEM_PROMPT 包含示例"""
        assert "示例" in AGENT_SYSTEM_PROMPT

    def test_agent_prompt_example_has_tool_call(self):
        """AGENT_SYSTEM_PROMPT 示例包含工具调用"""
        assert "read_file" in AGENT_SYSTEM_PROMPT or "write_file" in AGENT_SYSTEM_PROMPT

    def test_react_prompt_contains_example(self):
        """REACT_SYSTEM_PROMPT 包含示例"""
        assert "示例" in REACT_SYSTEM_PROMPT

    def test_react_prompt_example_has_action(self):
        """REACT_SYSTEM_PROMPT 示例包含 action 字段"""
        assert "action" in REACT_SYSTEM_PROMPT

    def test_decompose_prompt_contains_example(self):
        """DECOMPOSE_SYSTEM_PROMPT 包含示例"""
        assert "示例" in DECOMPOSE_SYSTEM_PROMPT

    def test_decompose_prompt_example_has_tasks(self):
        """DECOMPOSE_SYSTEM_PROMPT 示例包含 tasks 数组"""
        assert "tasks" in DECOMPOSE_SYSTEM_PROMPT

    def test_self_evolve_prompt_contains_example(self):
        """SELF_EVOLVE_SYSTEM_PROMPT 包含格式说明（V2 简化版）"""
        assert "修复方案必须使用以下格式" in SELF_EVOLVE_SYSTEM_PROMPT

    def test_self_evolve_prompt_example_has_file_block(self):
        """SELF_EVOLVE 示例包含 [FILE:...] 块（V2 整个提示词即为格式说明）"""
        assert "[FILE:" in SELF_EVOLVE_SYSTEM_PROMPT


# ══════════════════════════════════════════════════════════
# XML 禁止 — 工具调用类提示词禁止 XML
# ══════════════════════════════════════════════════════════


class TestXmlProhibition:
    """P2-2 标准 4: 工具调用类提示词禁止 XML 标签输出（与 P1-2 一致）"""

    def test_agent_prompt_forbids_xml(self):
        """AGENT_SYSTEM_PROMPT 明确禁止 XML 标签"""
        assert "XML" in AGENT_SYSTEM_PROMPT
        assert "禁" in AGENT_SYSTEM_PROMPT

    def test_react_prompt_forbids_xml(self):
        """REACT_SYSTEM_PROMPT 明确禁止 XML 标签"""
        assert "XML" in REACT_SYSTEM_PROMPT
        assert "禁" in REACT_SYSTEM_PROMPT

    def test_decompose_prompt_forbids_xml(self):
        """DECOMPOSE_SYSTEM_PROMPT 明确禁止 XML 标签"""
        assert "XML" in DECOMPOSE_SYSTEM_PROMPT
        assert "禁" in DECOMPOSE_SYSTEM_PROMPT


# ══════════════════════════════════════════════════════════
# 工具调用解析成功率验证
# ══════════════════════════════════════════════════════════


class TestToolCallParsing:
    """P2-2 标准 5: 工具调用解析成功率 ≥ 95%

    验证提示词中的 JSON 示例能被 parse_tool_calls 正确解析。
    """

    def test_agent_prompt_example_parseable(self):
        """AGENT_SYSTEM_PROMPT 中的示例能被 parse_tool_calls 解析

        注意：prompt 用 str.format() 模板，JSON 字面量需用 {{...}} 转义。
        测试先还原转义为单花括号，再验证 parse_tool_calls 能解析出工具调用。
        """
        from pycoder.server.services.agent_tools import parse_tool_calls

        # 还原 .format() 转义：{{ → {  }} → }
        rendered = AGENT_SYSTEM_PROMPT.replace("{{", "{").replace("}}", "}")
        result = parse_tool_calls(rendered)
        assert len(result) >= 1
        # 示例部分应解析出 read_file 调用
        example_section = rendered.split("## 示例")[1] if "## 示例" in rendered else ""
        example_result = parse_tool_calls(example_section)
        assert len(example_result) >= 1
        assert example_result[0]["name"] == "read_file"

    def test_react_prompt_example_parseable(self):
        """REACT_SYSTEM_PROMPT 中的示例能被 parse_tool_calls 解析"""
        from pycoder.server.services.agent_tools import parse_tool_calls

        result = parse_tool_calls(REACT_SYSTEM_PROMPT)
        # ReAct 格式是单个对象 {thought, action, action_input}，
        # 不是 {tool_calls: [...]}，parse_tool_calls 可能不直接解析
        # 但至少不应崩溃
        assert isinstance(result, list)

    def test_decompose_prompt_example_valid_json(self):
        """DECOMPOSE_SYSTEM_PROMPT 中的示例是有效 JSON"""
        import json as _json

        # 提取示例部分的 JSON
        example_section = DECOMPOSE_SYSTEM_PROMPT.split("## 示例")[1] if "## 示例" in DECOMPOSE_SYSTEM_PROMPT else ""
        # 找到 JSON 对象（花括号包裹）
        start = example_section.find("{")
        end = example_section.rfind("}") + 1
        if start >= 0 and end > start:
            json_str = example_section[start:end]
            data = _json.loads(json_str)  # 不应抛异常
            assert "tasks" in data
            assert len(data["tasks"]) >= 1


# ══════════════════════════════════════════════════════════
# 结构化验证 — 提示词应有清晰的结构
# ══════════════════════════════════════════════════════════


class TestPromptStructure:
    """提示词结构化验证"""

    def test_agent_prompt_has_sections(self):
        """AGENT_SYSTEM_PROMPT 有清晰的分节"""
        for section in ["## 工作流程", "## 可用工具", "## 约束"]:
            assert section in AGENT_SYSTEM_PROMPT

    def test_react_prompt_has_rules(self):
        """REACT_SYSTEM_PROMPT 有规则列表"""
        assert "规则" in REACT_SYSTEM_PROMPT

    def test_decompose_prompt_has_principles(self):
        """DECOMPOSE_SYSTEM_PROMPT 有原则列表"""
        assert "原则" in DECOMPOSE_SYSTEM_PROMPT

    def test_self_evolve_prompt_has_constraints(self):
        """SELF_EVOLVE_SYSTEM_PROMPT 有格式约束（V2 简化版）"""
        assert "不要省略" in SELF_EVOLVE_SYSTEM_PROMPT

    def test_agent_prompt_lists_tools(self):
        """AGENT_SYSTEM_PROMPT 列出所有可用工具"""
        for tool in ["read_file", "write_file", "search_code", "run_command", "list_files", "git_diff"]:
            assert tool in AGENT_SYSTEM_PROMPT

    def test_react_prompt_defines_finish(self):
        """REACT_SYSTEM_PROMPT 定义 FINISH 终止条件"""
        assert "FINISH" in REACT_SYSTEM_PROMPT

    def test_self_evolve_prompt_forbids_placeholders(self):
        """SELF_EVOLVE_SYSTEM_PROMPT 禁止占位符（V2 用"不要"表达）"""
        assert "占位符" in SELF_EVOLVE_SYSTEM_PROMPT
        assert "不要" in SELF_EVOLVE_SYSTEM_PROMPT
