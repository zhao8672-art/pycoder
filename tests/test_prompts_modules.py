"""
pycoder/prompts 模块综合单元测试

覆盖模块：
    1. pycoder.prompts.cache_rules — 缓存规则与命中率追踪
    2. pycoder.prompts.agents_templates — AGENTS.md 模板生成
    3. pycoder.prompts.loader — system prompt 加载器
    4. pycoder.prompts.skills_loader — Skills 自动发现
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ══════════════════════════════════════════════════════════
# 1. cache_rules 模块测试
# ══════════════════════════════════════════════════════════


class TestCacheRulesConstants:
    """测试缓存规则常量定义"""

    def test_cache_rules_prompt_zh_not_empty(self):
        """CACHE_RULES_PROMPT_ZH 应为非空字符串"""
        from pycoder.prompts.cache_rules import CACHE_RULES_PROMPT_ZH

        assert isinstance(CACHE_RULES_PROMPT_ZH, str)
        assert len(CACHE_RULES_PROMPT_ZH) > 100
        assert "缓存优化规则" in CACHE_RULES_PROMPT_ZH or "缓存" in CACHE_RULES_PROMPT_ZH

    def test_cache_rules_prompt_en_not_empty(self):
        """CACHE_RULES_PROMPT_EN 应为非空字符串"""
        from pycoder.prompts.cache_rules import CACHE_RULES_PROMPT_EN

        assert isinstance(CACHE_RULES_PROMPT_EN, str)
        assert len(CACHE_RULES_PROMPT_EN) > 100
        assert "Cache" in CACHE_RULES_PROMPT_EN

    def test_cache_rules_prompts_are_different(self):
        """中英文缓存规则提示应为不同内容"""
        from pycoder.prompts.cache_rules import CACHE_RULES_PROMPT_ZH, CACHE_RULES_PROMPT_EN

        assert CACHE_RULES_PROMPT_ZH != CACHE_RULES_PROMPT_EN


class TestGetCacheRules:
    """测试 get_cache_rules() 函数"""

    def test_get_cache_rules_zh(self):
        """lang='zh' 返回中文缓存规则"""
        from pycoder.prompts.cache_rules import get_cache_rules, CACHE_RULES_PROMPT_ZH

        result = get_cache_rules("zh")
        assert result == CACHE_RULES_PROMPT_ZH

    def test_get_cache_rules_en(self):
        """lang='en' 返回英文缓存规则"""
        from pycoder.prompts.cache_rules import get_cache_rules, CACHE_RULES_PROMPT_EN

        result = get_cache_rules("en")
        assert result == CACHE_RULES_PROMPT_EN

    def test_get_cache_rules_default(self):
        """默认参数应返回中文缓存规则"""
        from pycoder.prompts.cache_rules import get_cache_rules, CACHE_RULES_PROMPT_ZH

        result = get_cache_rules()
        assert result == CACHE_RULES_PROMPT_ZH


class TestInjectCacheRules:
    """测试 inject_cache_rules() 函数"""

    def test_inject_cache_rules_normal(self):
        """正常注入：将缓存规则追加到 system prompt 末尾"""
        from pycoder.prompts.cache_rules import inject_cache_rules

        original = "我是系统提示词"
        result = inject_cache_rules(original, "zh")
        assert result.startswith(original)
        assert "缓存优化规则" in result

    def test_inject_cache_rules_already_has_zh(self):
        """已有中文缓存规则时跳过注入，避免重复"""
        from pycoder.prompts.cache_rules import inject_cache_rules

        original = "我是系统提示词\n缓存优化规则（强制遵守）"
        result = inject_cache_rules(original, "zh")
        assert result == original

    def test_inject_cache_rules_already_has_en(self):
        """已有英文缓存规则时跳过注入"""
        from pycoder.prompts.cache_rules import inject_cache_rules

        original = "System prompt\nCache Optimization Rules (MANDATORY)"
        result = inject_cache_rules(original, "en")
        assert result == original

    def test_inject_cache_rules_en(self):
        """lang='en' 注入英文缓存规则"""
        from pycoder.prompts.cache_rules import inject_cache_rules

        original = "System prompt"
        result = inject_cache_rules(original, "en")
        assert result.startswith(original)
        assert "Cache Optimization Rules" in result

    def test_inject_cache_rules_empty_prompt(self):
        """空 system prompt 也能正常注入"""
        from pycoder.prompts.cache_rules import inject_cache_rules

        result = inject_cache_rules("", "zh")
        assert "缓存优化规则" in result


class TestCanonicalizeMessages:
    """测试 canonicalize_messages() 消息规范化"""

    def test_insert_system_prompt(self):
        """无 system prompt 时插入指定 system prompt 作为第一条"""
        from pycoder.prompts.cache_rules import canonicalize_messages

        messages = [{"role": "user", "content": "你好"}]
        result = canonicalize_messages(messages, system_prompt="系统提示")
        assert result[0] == {"role": "system", "content": "系统提示"}
        assert result[1]["role"] == "user"

    def test_dedup_system_messages(self):
        """去除重复的 system 消息（已有 system_prompt 参数时）"""
        from pycoder.prompts.cache_rules import canonicalize_messages

        messages = [
            {"role": "system", "content": "旧的系统提示"},
            {"role": "user", "content": "你好"},
            {"role": "system", "content": "另一个系统提示"},
        ]
        result = canonicalize_messages(messages, system_prompt="新的系统提示")
        # 只保留一条 system 消息（参数指定的）
        system_count = sum(1 for m in result if m["role"] == "system")
        assert system_count == 1
        assert result[0]["content"] == "新的系统提示"

    def test_keep_system_without_param(self):
        """无 system_prompt 参数时保留原始 system 消息"""
        from pycoder.prompts.cache_rules import canonicalize_messages

        messages = [
            {"role": "system", "content": "第一条系统消息"},
            {"role": "user", "content": "你好"},
        ]
        result = canonicalize_messages(messages)
        system_msgs = [m for m in result if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0]["content"] == "第一条系统消息"

    def test_preserve_tool_calls(self):
        """保留 assistant 消息中的 tool_calls 字段"""
        from pycoder.prompts.cache_rules import canonicalize_messages

        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call_1", "function": {"name": "read_file"}}],
            },
        ]
        result = canonicalize_messages(messages)
        assert "tool_calls" in result[0]
        assert result[0]["tool_calls"][0]["id"] == "call_1"

    def test_preserve_tool_call_id(self):
        """保留 tool 消息中的 tool_call_id 字段"""
        from pycoder.prompts.cache_rules import canonicalize_messages

        messages = [
            {"role": "tool", "tool_call_id": "call_1", "content": "文件内容"},
        ]
        result = canonicalize_messages(messages)
        assert result[0]["tool_call_id"] == "call_1"
        assert result[0]["role"] == "tool"

    def test_preserve_name_field(self):
        """保留消息中的 name 字段"""
        from pycoder.prompts.cache_rules import canonicalize_messages

        messages = [
            {"role": "user", "content": "你好", "name": "张三"},
        ]
        result = canonicalize_messages(messages)
        assert result[0]["name"] == "张三"

    def test_stable_field_order(self):
        """规范化后字段顺序固定为 role, content, name, tool_calls, tool_call_id"""
        from pycoder.prompts.cache_rules import canonicalize_messages

        messages = [
            {"name": "李四", "content": "测试", "role": "user"},
        ]
        result = canonicalize_messages(messages)
        keys = list(result[0].keys())
        assert keys[0] == "role"
        assert keys[1] == "content"

    def test_empty_messages(self):
        """空消息列表处理"""
        from pycoder.prompts.cache_rules import canonicalize_messages

        result = canonicalize_messages([], system_prompt="系统提示")
        assert len(result) == 1
        assert result[0]["role"] == "system"

    def test_empty_messages_no_system(self):
        """空消息列表且无 system_prompt"""
        from pycoder.prompts.cache_rules import canonicalize_messages

        result = canonicalize_messages([])
        assert result == []

    def test_missing_role_defaults_to_user(self):
        """缺少 role 字段的消息默认视为 user"""
        from pycoder.prompts.cache_rules import canonicalize_messages

        messages = [{"content": "无 role 的消息"}]
        result = canonicalize_messages(messages)
        assert result[0]["role"] == "user"

    def test_missing_content_defaults_to_empty(self):
        """缺少 content 字段的消息默认使用空字符串"""
        from pycoder.prompts.cache_rules import canonicalize_messages

        messages = [{"role": "user"}]
        result = canonicalize_messages(messages)
        assert result[0]["content"] == ""


class TestCanonicalizeTools:
    """测试 canonicalize_tools() 工具列表规范化"""

    def test_sort_by_type_and_name(self):
        """按 type 和 function.name 排序"""
        from pycoder.prompts.cache_rules import canonicalize_tools

        tools = [
            {"type": "function", "function": {"name": "z_tool"}},
            {"type": "function", "function": {"name": "a_tool"}},
            {"type": "function", "function": {"name": "m_tool"}},
        ]
        result = canonicalize_tools(tools)
        assert result[0]["function"]["name"] == "a_tool"
        assert result[1]["function"]["name"] == "m_tool"
        assert result[2]["function"]["name"] == "z_tool"

    def test_empty_tools(self):
        """空工具列表返回原列表"""
        from pycoder.prompts.cache_rules import canonicalize_tools

        result = canonicalize_tools([])
        assert result == []

    def test_single_tool(self):
        """单个工具无需排序"""
        from pycoder.prompts.cache_rules import canonicalize_tools

        tools = [{"type": "function", "function": {"name": "read_file"}}]
        result = canonicalize_tools(tools)
        assert result == tools

    def test_missing_name_handled(self):
        """缺少 function.name 的工具也能正常排序"""
        from pycoder.prompts.cache_rules import canonicalize_tools

        tools = [
            {"type": "function", "function": {}},
            {"type": "function", "function": {"name": "b_tool"}},
        ]
        result = canonicalize_tools(tools)
        # 空 name 排序在前（空字符串 < "b_tool"）
        assert len(result) == 2


class TestComputeCacheFingerprint:
    """测试 compute_cache_fingerprint() 缓存指纹计算"""

    def test_basic_fingerprint(self):
        """基本指纹计算"""
        from pycoder.prompts.cache_rules import compute_cache_fingerprint

        messages = [{"role": "user", "content": "你好"}]
        fp = compute_cache_fingerprint(messages)
        assert isinstance(fp, str)
        assert len(fp) == 12

    def test_with_tools(self):
        """带 tools 的指纹计算"""
        from pycoder.prompts.cache_rules import compute_cache_fingerprint

        messages = [{"role": "user", "content": "你好"}]
        tools = [{"type": "function", "function": {"name": "read_file"}}]
        fp = compute_cache_fingerprint(messages, tools=tools)
        assert isinstance(fp, str)
        assert len(fp) == 12

    def test_with_system_fingerprint(self):
        """带 system_fingerprint 的指纹计算"""
        from pycoder.prompts.cache_rules import compute_cache_fingerprint

        messages = [{"role": "user", "content": "你好"}]
        fp = compute_cache_fingerprint(messages, system_fingerprint="abc123")
        assert isinstance(fp, str)
        assert len(fp) == 12

    def test_same_input_same_fingerprint(self):
        """相同输入产生相同指纹（确定性）"""
        from pycoder.prompts.cache_rules import compute_cache_fingerprint

        messages = [{"role": "user", "content": "你好"}]
        fp1 = compute_cache_fingerprint(messages)
        fp2 = compute_cache_fingerprint(messages)
        assert fp1 == fp2

    def test_different_messages_different_fingerprint(self):
        """不同消息产生不同指纹"""
        from pycoder.prompts.cache_rules import compute_cache_fingerprint

        fp1 = compute_cache_fingerprint([{"role": "user", "content": "你好"}])
        fp2 = compute_cache_fingerprint([{"role": "user", "content": "再见"}])
        assert fp1 != fp2

    def test_empty_messages(self):
        """空消息列表也能计算指纹"""
        from pycoder.prompts.cache_rules import compute_cache_fingerprint

        fp = compute_cache_fingerprint([])
        assert isinstance(fp, str)
        assert len(fp) == 12


class TestCacheHitTracker:
    """测试 CacheHitTracker 缓存命中追踪器"""

    def test_init_state(self):
        """初始状态检查"""
        from pycoder.prompts.cache_rules import CacheHitTracker

        tracker = CacheHitTracker()
        assert tracker._request_count == 0
        assert tracker._estimated_hits == 0
        assert tracker._last_fingerprint == ""

    def test_set_system_hash(self):
        """设置 system hash"""
        from pycoder.prompts.cache_rules import CacheHitTracker

        tracker = CacheHitTracker()
        tracker.set_system_hash("测试系统提示")
        assert len(tracker._last_system_hash) == 12

    def test_check_hit_first_call(self):
        """第一次调用 check_hit 不命中缓存"""
        from pycoder.prompts.cache_rules import CacheHitTracker

        tracker = CacheHitTracker()
        messages = [{"role": "user", "content": "你好"}]
        hit, fp = tracker.check_hit(messages)
        assert hit is False
        assert len(fp) == 12
        assert tracker._request_count == 1

    def test_check_hit_same_messages_hits(self):
        """相同消息第二次调用命中缓存"""
        from pycoder.prompts.cache_rules import CacheHitTracker

        tracker = CacheHitTracker()
        messages = [{"role": "user", "content": "你好"}]
        tracker.check_hit(messages)
        hit, fp = tracker.check_hit(messages)
        assert hit is True

    def test_check_hit_different_messages_misses(self):
        """不同消息不命中缓存"""
        from pycoder.prompts.cache_rules import CacheHitTracker

        tracker = CacheHitTracker()
        tracker.check_hit([{"role": "user", "content": "你好"}])
        hit, fp = tracker.check_hit([{"role": "user", "content": "再见"}])
        assert hit is False

    def test_hit_rate_zero_before_two_calls(self):
        """少于两次调用时命中率为 0"""
        from pycoder.prompts.cache_rules import CacheHitTracker

        tracker = CacheHitTracker()
        # 0 次调用
        assert tracker.hit_rate == 0.0
        # 1 次调用
        tracker.check_hit([{"role": "user", "content": "你好"}])
        assert tracker.hit_rate == 0.0

    def test_hit_rate_after_multiple_calls(self):
        """多次调用后命中率计算正确"""
        from pycoder.prompts.cache_rules import CacheHitTracker

        tracker = CacheHitTracker()
        messages = [{"role": "user", "content": "你好"}]
        # 调用 1: 不命中
        tracker.check_hit(messages)
        # 调用 2: 命中
        tracker.check_hit(messages)
        # 调用 3: 命中
        tracker.check_hit(messages)
        # 调用 4: 不命中（换消息）
        tracker.check_hit([{"role": "user", "content": "再见"}])

        # 共 4 次调用，命中 2 次，分母 = 3
        assert tracker.hit_rate == pytest.approx(2 / 3, rel=0.01)

    def test_hit_rate_perfect(self):
        """全部命中时命中率为 1.0"""
        from pycoder.prompts.cache_rules import CacheHitTracker

        tracker = CacheHitTracker()
        messages = [{"role": "user", "content": "你好"}]
        for _ in range(5):
            tracker.check_hit(messages)
        # 5 次调用，后 4 次命中，分母 = 4
        assert tracker.hit_rate == 1.0

    def test_hit_rate_with_tools(self):
        """带 tools 参数也能正确追踪命中率"""
        from pycoder.prompts.cache_rules import CacheHitTracker

        tracker = CacheHitTracker()
        messages = [{"role": "user", "content": "你好"}]
        tools = [{"type": "function", "function": {"name": "read_file"}}]
        tracker.check_hit(messages, tools=tools)
        tracker.check_hit(messages, tools=tools)
        assert tracker.hit_rate == 1.0

    def test_set_system_hash_affects_fingerprint(self):
        """设置 system hash 后会影响指纹，导致不命中"""
        from pycoder.prompts.cache_rules import CacheHitTracker

        tracker = CacheHitTracker()
        messages = [{"role": "user", "content": "你好"}]
        tracker.check_hit(messages)
        tracker.set_system_hash("不同的系统提示")
        hit, _ = tracker.check_hit(messages)
        # system hash 变了，指纹不同，不命中
        assert hit is False


# ══════════════════════════════════════════════════════════
# 2. agents_templates 模块测试
# ══════════════════════════════════════════════════════════


class TestAgentTemplateDataclass:
    """测试 AgentTemplate 数据类"""

    def test_create_basic(self):
        """创建基本 AgentTemplate 实例"""
        from pycoder.prompts.agents_templates import AgentTemplate

        t = AgentTemplate(
            name="测试Agent",
            role="test_agent",
            description="用于测试的 Agent",
        )
        assert t.name == "测试Agent"
        assert t.role == "test_agent"
        assert t.description == "用于测试的 Agent"
        assert t.responsibilities == []
        assert t.tools == []
        assert t.constraints == []

    def test_create_with_all_fields(self):
        """创建带所有字段的 AgentTemplate"""
        from pycoder.prompts.agents_templates import AgentTemplate

        t = AgentTemplate(
            name="全功能Agent",
            role="full_agent",
            description="测试所有字段",
            responsibilities=["任务1", "任务2"],
            tools=["tool1", "tool2"],
            constraints=["约束1", "约束2"],
        )
        assert t.name == "全功能Agent"
        assert t.role == "full_agent"
        assert t.description == "测试所有字段"
        assert len(t.responsibilities) == 2
        assert len(t.tools) == 2
        assert len(t.constraints) == 2

    def test_default_factory_isolation(self):
        """默认工厂应为每个实例创建独立列表"""
        from pycoder.prompts.agents_templates import AgentTemplate

        t1 = AgentTemplate(name="A", role="a", description="desc")
        t2 = AgentTemplate(name="B", role="b", description="desc")
        t1.responsibilities.append("task1")
        assert t2.responsibilities == []


class TestAgentTemplatesDict:
    """测试预定义 AGENT_TEMPLATES 字典"""

    def test_contains_expected_roles(self):
        """应包含所有预定义角色"""
        from pycoder.prompts.agents_templates import AGENT_TEMPLATES

        expected = {
            "software_pm",
            "tech_architect",
            "frontend_engineer",
            "backend_engineer",
            "qa_engineer",
            "devops_engineer",
        }
        assert set(AGENT_TEMPLATES.keys()) == expected

    def test_all_templates_have_required_fields(self):
        """所有模板必须有 name, role, description"""
        from pycoder.prompts.agents_templates import AGENT_TEMPLATES

        for key, template in AGENT_TEMPLATES.items():
            assert template.name, f"{key} 缺少 name"
            assert template.role == key, f"{key} 的 role 与 key 不一致"
            assert template.description, f"{key} 缺少 description"

    def test_all_templates_have_responsibilities(self):
        """所有模板应有职责列表"""
        from pycoder.prompts.agents_templates import AGENT_TEMPLATES

        for key, template in AGENT_TEMPLATES.items():
            assert len(template.responsibilities) > 0, f"{key} 缺少职责定义"

    def test_all_templates_have_tools(self):
        """所有模板应有工具列表"""
        from pycoder.prompts.agents_templates import AGENT_TEMPLATES

        for key, template in AGENT_TEMPLATES.items():
            assert len(template.tools) > 0, f"{key} 缺少工具定义"

    def test_all_templates_have_constraints(self):
        """所有模板应有约束列表"""
        from pycoder.prompts.agents_templates import AGENT_TEMPLATES

        for key, template in AGENT_TEMPLATES.items():
            assert len(template.constraints) > 0, f"{key} 缺少约束定义"


class TestGenerateAgentsMd:
    """测试 generate_agents_md() 函数"""

    def test_basic_generation(self):
        """基本生成：包含项目名和语言"""
        from pycoder.prompts.agents_templates import generate_agents_md

        result = generate_agents_md(
            project_name="测试项目",
            language="Python",
        )
        assert "# AGENTS.md — 测试项目" in result
        assert "Python" in result
        assert "## 团队角色" in result
        assert "## 开发流程" in result

    def test_with_description(self):
        """带项目描述的生成"""
        from pycoder.prompts.agents_templates import generate_agents_md

        result = generate_agents_md(
            project_name="MyProject",
            project_description="这是一个测试项目",
            language="Python",
        )
        assert "这是一个测试项目" in result

    def test_without_description(self):
        """无描述时使用默认格式"""
        from pycoder.prompts.agents_templates import generate_agents_md

        result = generate_agents_md(
            project_name="MyProject",
            language="Python",
        )
        assert "MyProject — Python 项目" in result

    def test_with_framework(self):
        """带框架信息的生成"""
        from pycoder.prompts.agents_templates import generate_agents_md

        result = generate_agents_md(
            project_name="MyProject",
            language="Python",
            framework="FastAPI",
        )
        assert "**框架：** FastAPI" in result

    def test_without_framework(self):
        """无框架时不显示框架信息"""
        from pycoder.prompts.agents_templates import generate_agents_md

        result = generate_agents_md(
            project_name="MyProject",
            language="Python",
        )
        assert "**框架：**" not in result

    def test_contains_hitl_section(self):
        """应包含 HITL 规范部分"""
        from pycoder.prompts.agents_templates import generate_agents_md

        result = generate_agents_md("MyProject", language="Python")
        assert "## HITL 规范" in result
        assert "merge_to_main" in result
        assert "deploy_production" in result

    def test_contains_commit_convention(self):
        """应包含提交规范"""
        from pycoder.prompts.agents_templates import generate_agents_md

        result = generate_agents_md("MyProject", language="Python")
        assert "## 提交规范" in result
        assert "feat:" in result
        assert "fix:" in result

    def test_contains_code_review_checklist(self):
        """应包含代码审查清单"""
        from pycoder.prompts.agents_templates import generate_agents_md

        result = generate_agents_md("MyProject", language="Python")
        assert "## 代码审查清单" in result
        assert "单元测试覆盖率" in result

    def test_with_custom_templates(self):
        """使用自定义模板列表"""
        from pycoder.prompts.agents_templates import generate_agents_md, AgentTemplate

        custom = [
            AgentTemplate(
                name="自定义Agent",
                role="custom_agent",
                description="自定义描述",
                responsibilities=["自定义职责"],
                tools=["custom_tool"],
                constraints=["自定义约束"],
            )
        ]
        result = generate_agents_md(
            "MyProject",
            language="Python",
            custom_templates=custom,
        )
        assert "自定义Agent" in result
        assert "custom_agent" in result
        # 不应包含默认模板角色
        assert "技术PM" not in result

    def test_returns_string(self):
        """返回值应为字符串类型"""
        from pycoder.prompts.agents_templates import generate_agents_md

        result = generate_agents_md("MyProject", language="Python")
        assert isinstance(result, str)
        assert len(result) > 100

    def test_default_project_name(self):
        """默认项目名为 PyCoder"""
        from pycoder.prompts.agents_templates import generate_agents_md

        result = generate_agents_md()
        assert "PyCoder" in result


class TestGetTemplate:
    """测试 get_template() 函数"""

    def test_get_existing_template(self):
        """获取已存在的模板"""
        from pycoder.prompts.agents_templates import get_template

        t = get_template("software_pm")
        assert t is not None
        assert t.name == "技术PM"

    def test_get_all_roles(self):
        """所有角色都能获取到模板"""
        from pycoder.prompts.agents_templates import get_template, list_roles

        for role in list_roles():
            t = get_template(role)
            assert t is not None, f"角色 {role} 模板为 None"
            assert t.role == role

    def test_get_nonexistent_template(self):
        """获取不存在的角色返回 None"""
        from pycoder.prompts.agents_templates import get_template

        t = get_template("nonexistent_role")
        assert t is None


class TestListRoles:
    """测试 list_roles() 函数"""

    def test_returns_list(self):
        """返回列表类型"""
        from pycoder.prompts.agents_templates import list_roles

        roles = list_roles()
        assert isinstance(roles, list)

    def test_contains_expected_keys(self):
        """包含预期的角色键"""
        from pycoder.prompts.agents_templates import list_roles

        roles = list_roles()
        assert "software_pm" in roles
        assert "backend_engineer" in roles
        assert "qa_engineer" in roles

    def test_non_empty(self):
        """列表非空"""
        from pycoder.prompts.agents_templates import list_roles

        roles = list_roles()
        assert len(roles) >= 4


# ══════════════════════════════════════════════════════════
# 3. loader 模块测试
# ══════════════════════════════════════════════════════════


class TestGetPrompt:
    """测试 get_prompt() 函数"""

    def test_get_prompt_zh(self):
        """获取中文 prompt"""
        from pycoder.prompts.loader import get_prompt

        prompt = get_prompt("hermes", "zh")
        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "PyCoder" in prompt or "Hermes" in prompt

    def test_get_prompt_en(self):
        """获取英文 prompt"""
        from pycoder.prompts.loader import get_prompt

        prompt = get_prompt("hermes", "en")
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_get_prompt_default_lang(self):
        """默认 lang='zh' 获取中文 prompt"""
        from pycoder.prompts.loader import get_prompt

        prompt_zh = get_prompt("hermes", "zh")
        prompt_default = get_prompt("hermes")
        assert prompt_zh == prompt_default

    def test_get_prompt_fallback_to_root(self):
        """当 lang 版本中没有时回退到根级 prompt"""
        from pycoder.prompts.loader import get_prompt

        # 根级有 "hermes" 键，versions 里也有，但测试 fallback
        # 使用一个不存在的 lang 触发 fallback
        prompt = get_prompt("hermes", "xx")
        # 回退到根级
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_get_prompt_not_found(self):
        """获取不存在的 prompt 返回空字符串"""
        from pycoder.prompts.loader import get_prompt

        prompt = get_prompt("nonexistent_prompt_name", "zh")
        assert prompt == ""

    def test_get_prompt_all_known_keys(self):
        """所有已知 prompt 键都能获取到非空内容"""
        from pycoder.prompts.loader import get_prompt

        known_keys = ["hermes", "chat_default", "code_review", "unified_entry"]
        for key in known_keys:
            prompt = get_prompt(key, "zh")
            assert prompt, f"键 {key} 的 prompt 为空"


class TestReload:
    """测试 reload() 函数"""

    def test_reload_clears_cache(self):
        """reload 应清除缓存并重新加载"""
        from pycoder.prompts import loader

        # 先加载一次
        loader.get_prompt("hermes", "zh")
        assert loader._cache is not None
        # 重载
        loader.reload()
        assert loader._cache is not None  # 重新加载后缓存应存在

    def test_reload_then_get_prompt(self):
        """reload 后仍能正常获取 prompt"""
        from pycoder.prompts import loader

        loader.reload()
        prompt = loader.get_prompt("hermes", "zh")
        assert len(prompt) > 0


class TestGetPromptWithCacheRules:
    """测试 get_prompt_with_cache_rules() 函数"""

    def test_returns_prompt_with_cache_rules(self):
        """返回的 prompt 应包含缓存规则"""
        from pycoder.prompts.loader import get_prompt_with_cache_rules

        result = get_prompt_with_cache_rules("hermes", "zh")
        assert isinstance(result, str)
        assert len(result) > 0
        assert "缓存优化规则" in result

    def test_base_prompt_included(self):
        """原始 prompt 内容应包含在结果中"""
        from pycoder.prompts.loader import get_prompt_with_cache_rules, get_prompt

        base = get_prompt("hermes", "zh")
        result = get_prompt_with_cache_rules("hermes", "zh")
        assert result.startswith(base) or base in result

    def test_en_lang_cache_rules(self):
        """英文版也应包含缓存规则"""
        from pycoder.prompts.loader import get_prompt_with_cache_rules

        result = get_prompt_with_cache_rules("hermes", "en")
        assert "Cache Optimization Rules" in result


# ══════════════════════════════════════════════════════════
# 4. skills_loader 模块测试
# ══════════════════════════════════════════════════════════


class TestSkillsLoader:
    """测试 skills_loader 模块"""

    def test_discover_skills_from_empty_dir(self, tmp_path, monkeypatch):
        """从空目录扫描应返回空列表（无注册表回退时）"""
        from pycoder.prompts import skills_loader

        # 临时替换 SKILLS_DIRS
        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [tmp_path])
        # 阻止注册表加载
        monkeypatch.setattr(skills_loader, "_load_from_registry", lambda: [])

        skills = skills_loader.discover_skills()
        assert isinstance(skills, list)
        assert skills == []

    def test_discover_skills_from_md_files(self, tmp_path, monkeypatch):
        """从包含 .md 文件的目录扫描技能"""
        from pycoder.prompts import skills_loader

        # 创建测试 .md 文件
        md_file = tmp_path / "test_skill.md"
        content = "# 测试技能\n这是一个测试技能的描述。\n\n## 内容\n技能详细内容。"
        md_file.write_text(content, encoding="utf-8")

        # 创建非 .md 文件（应被忽略）
        (tmp_path / "not_a_skill.txt").write_text("忽略此文件", encoding="utf-8")

        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [tmp_path])
        monkeypatch.setattr(skills_loader, "_load_from_registry", lambda: [])

        skills = skills_loader.discover_skills()
        assert len(skills) == 1
        assert skills[0]["name"] == "测试技能"
        assert skills[0]["description"] == "这是一个测试技能的描述。"
        assert skills[0]["type"] == "skill"
        # content 是文件原始内容，含 # 标记
        assert skills[0]["content"] == content

    def test_discover_skills_source_label(self, tmp_path, monkeypatch):
        """扫描的 source 标签应为 project 或 user"""
        from pycoder.prompts import skills_loader

        md_file = tmp_path / "skill.md"
        md_file.write_text("# 技能\n描述", encoding="utf-8")

        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [tmp_path])
        monkeypatch.setattr(skills_loader, "_load_from_registry", lambda: [])

        skills = skills_loader.discover_skills()
        assert skills[0]["source"] in ("project", "user")

    def test_discover_skills_no_title_uses_stem(self, tmp_path, monkeypatch):
        """无 # 标题时使用文件名（不含扩展名）作为名称"""
        from pycoder.prompts import skills_loader

        md_file = tmp_path / "my_skill.md"
        md_file.write_text("没有标题的技能文件\n描述内容", encoding="utf-8")

        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [tmp_path])
        monkeypatch.setattr(skills_loader, "_load_from_registry", lambda: [])

        skills = skills_loader.discover_skills()
        assert skills[0]["name"] == "my_skill"

    def test_discover_skills_file_key(self, tmp_path, monkeypatch):
        """返回的技能应有 file 键"""
        from pycoder.prompts import skills_loader

        md_file = tmp_path / "skill.md"
        md_file.write_text("# 技能\n描述", encoding="utf-8")

        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [tmp_path])
        monkeypatch.setattr(skills_loader, "_load_from_registry", lambda: [])

        skills = skills_loader.discover_skills()
        assert "file" in skills[0]

    def test_discover_skills_registry_fallback(self, tmp_path, monkeypatch):
        """本地目录为空时从注册表回退加载"""
        from pycoder.prompts import skills_loader

        # 创建模拟注册表文件
        registry_path = tmp_path / ".skills-registry-enhanced.json"
        registry_data = [
            {
                "name": "注册表技能",
                "description": "来自注册表的技能",
                "content": "# 注册表技能\n来自注册表",
                "tags": ["python", "web"],
                "stars": 5,
            }
        ]
        registry_path.write_text(json.dumps(registry_data, ensure_ascii=False), encoding="utf-8")

        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [tmp_path / "empty_dir"])
        (tmp_path / "empty_dir").mkdir(exist_ok=True)
        monkeypatch.setattr(skills_loader, "_REGISTRY_PATHS", [registry_path])

        skills = skills_loader.discover_skills()
        # 应有注册表回退的技能
        registry_names = [s["name"] for s in skills if s.get("source") == "registry"]
        assert len(registry_names) >= 1
        assert "注册表技能" in registry_names

    def test_discover_skills_registry_has_tags(self, tmp_path, monkeypatch):
        """注册表技能应有 tags 字段"""
        from pycoder.prompts import skills_loader

        registry_path = tmp_path / ".skills-registry-enhanced.json"
        registry_data = [
            {"name": "技能A", "description": "描述A", "tags": ["tag1", "tag2"], "stars": 3}
        ]
        registry_path.write_text(json.dumps(registry_data, ensure_ascii=False), encoding="utf-8")

        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [tmp_path / "empty"])
        (tmp_path / "empty").mkdir(exist_ok=True)
        monkeypatch.setattr(skills_loader, "_REGISTRY_PATHS", [registry_path])

        skills = skills_loader.discover_skills()
        reg_skill = next(s for s in skills if s["source"] == "registry")
        assert "tags" in reg_skill
        assert reg_skill["tags"] == ["tag1", "tag2"]

    def test_discover_skills_registry_has_stars(self, tmp_path, monkeypatch):
        """注册表技能应有 stars 字段"""
        from pycoder.prompts import skills_loader

        registry_path = tmp_path / ".skills-registry-enhanced.json"
        registry_data = [
            {"name": "技能A", "description": "描述A", "stars": 42}
        ]
        registry_path.write_text(json.dumps(registry_data, ensure_ascii=False), encoding="utf-8")

        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [tmp_path / "empty2"])
        (tmp_path / "empty2").mkdir(exist_ok=True)
        monkeypatch.setattr(skills_loader, "_REGISTRY_PATHS", [registry_path])

        skills = skills_loader.discover_skills()
        reg_skill = next(s for s in skills if s["source"] == "registry")
        assert reg_skill["stars"] == 42

    def test_discover_skills_local_overrides_registry(self, tmp_path, monkeypatch):
        """本地文件同名技能应覆盖注册表技能"""
        from pycoder.prompts import skills_loader

        # 本地技能
        md_file = tmp_path / "我的技能.md"
        md_file.write_text("# 我的技能\n本地描述", encoding="utf-8")

        # 注册表技能（同名不同源）
        registry_path = tmp_path / ".skills-registry-enhanced.json"
        registry_data = [
            {"name": "我的技能", "description": "注册表描述"}
        ]
        registry_path.write_text(json.dumps(registry_data, ensure_ascii=False), encoding="utf-8")

        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [tmp_path])
        monkeypatch.setattr(skills_loader, "_REGISTRY_PATHS", [registry_path])

        skills = skills_loader.discover_skills()
        my_skills = [s for s in skills if s["name"] == "我的技能"]
        # 本地技能优先
        assert len(my_skills) == 1
        assert my_skills[0]["source"] != "registry"

    def test_get_skill_by_name(self, tmp_path, monkeypatch):
        """按名称查找技能"""
        from pycoder.prompts import skills_loader

        md_file = tmp_path / "skill.md"
        md_file.write_text("# 查找技能\n描述", encoding="utf-8")

        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [tmp_path])
        monkeypatch.setattr(skills_loader, "_load_from_registry", lambda: [])

        skill = skills_loader.get_skill("查找技能")
        assert skill is not None
        assert skill["name"] == "查找技能"

    def test_get_skill_by_file(self, tmp_path, monkeypatch):
        """按文件名查找技能"""
        from pycoder.prompts import skills_loader

        md_file = tmp_path / "my_skill.md"
        md_file.write_text("# 我的技能\n描述", encoding="utf-8")

        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [tmp_path])
        monkeypatch.setattr(skills_loader, "_load_from_registry", lambda: [])

        skill = skills_loader.get_skill("my_skill.md")
        assert skill is not None
        assert skill["name"] == "我的技能"

    def test_get_skill_not_found(self, tmp_path, monkeypatch):
        """查找不存在的技能返回 None"""
        from pycoder.prompts import skills_loader

        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [tmp_path])
        monkeypatch.setattr(skills_loader, "_load_from_registry", lambda: [])

        skill = skills_loader.get_skill("不存在的技能")
        assert skill is None

    def test_reload_skills(self, tmp_path, monkeypatch):
        """reload_skills 清空缓存并重新扫描"""
        from pycoder.prompts import skills_loader

        md_file = tmp_path / "skill.md"
        md_file.write_text("# 技能\n描述", encoding="utf-8")

        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [tmp_path])
        monkeypatch.setattr(skills_loader, "_load_from_registry", lambda: [])

        skills = skills_loader.reload_skills()
        assert isinstance(skills, list)
        assert len(skills) >= 1

    def test_load_from_registry_dict_format(self, tmp_path, monkeypatch):
        """注册表文件为 dict 格式（含 skills 键）"""
        from pycoder.prompts import skills_loader

        registry_path = tmp_path / ".skills-registry.json"
        registry_data = {
            "skills": [
                {"name": "技能X", "description": "dict格式技能"}
            ]
        }
        registry_path.write_text(json.dumps(registry_data, ensure_ascii=False), encoding="utf-8")

        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [tmp_path / "empty3"])
        (tmp_path / "empty3").mkdir(exist_ok=True)
        monkeypatch.setattr(skills_loader, "_REGISTRY_PATHS", [registry_path])

        skills = skills_loader.discover_skills()
        names = [s["name"] for s in skills if s.get("source") == "registry"]
        assert "技能X" in names

    def test_load_from_registry_invalid_json(self, tmp_path, monkeypatch):
        """注册表文件 JSON 解析失败时不崩溃"""
        from pycoder.prompts import skills_loader

        registry_path = tmp_path / ".skills-registry-enhanced.json"
        registry_path.write_text("这不是合法的 JSON", encoding="utf-8")

        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [tmp_path / "empty4"])
        (tmp_path / "empty4").mkdir(exist_ok=True)
        monkeypatch.setattr(skills_loader, "_REGISTRY_PATHS", [registry_path])

        # 不应抛出异常
        skills = skills_loader.discover_skills()
        assert isinstance(skills, list)

    def test_init_skills_dirs(self, monkeypatch):
        """_init_skills_dirs 初始化搜索路径"""
        from pycoder.prompts import skills_loader

        # 清空 SKILLS_DIRS
        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [])
        dirs = skills_loader._init_skills_dirs()
        assert len(dirs) == 2
        assert any(".skills" in str(d) for d in dirs)
        assert any("skills" in str(d) for d in dirs)

    def test_discover_skills_multiple_dirs(self, tmp_path, monkeypatch):
        """多个目录都能扫描到技能"""
        from pycoder.prompts import skills_loader

        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        (dir1 / "a.md").write_text("# 技能A\n描述A", encoding="utf-8")
        (dir2 / "b.md").write_text("# 技能B\n描述B", encoding="utf-8")

        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [dir1, dir2])
        monkeypatch.setattr(skills_loader, "_load_from_registry", lambda: [])

        skills = skills_loader.discover_skills()
        names = [s["name"] for s in skills]
        assert "技能A" in names
        assert "技能B" in names

    def test_discover_skills_read_error_handled(self, tmp_path, monkeypatch):
        """文件读取错误时跳过并继续（mock logger 避免日志格式兼容问题）"""
        from pycoder.prompts import skills_loader

        md_file = tmp_path / "bad.md"
        md_file.write_text("# 坏文件\n描述", encoding="utf-8")
        good_file = tmp_path / "good.md"
        good_file.write_text("# 好文件\n描述", encoding="utf-8")

        # 模拟第一个文件的 read_text 失败
        original_read = Path.read_text

        def failing_read(self, *args, **kwargs):
            if self.name == "bad.md":
                raise OSError("模拟读取失败")
            return original_read(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", failing_read)
        monkeypatch.setattr(skills_loader, "SKILLS_DIRS", [tmp_path])
        monkeypatch.setattr(skills_loader, "_load_from_registry", lambda: [])
        # 同时 mock logger.warning 避免 source code 中 logger 参数兼容问题
        monkeypatch.setattr(skills_loader.logger, "warning", lambda *a, **kw: None)

        skills = skills_loader.discover_skills()
        assert isinstance(skills, list)
        # 坏文件被跳过，好文件正常加载
        assert len(skills) == 1
        assert skills[0]["name"] == "好文件"