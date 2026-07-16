"""
意图解析器单元测试

测试 IntentParser 和 ParsedIntent 的核心功能：
- TaskCategory 枚举
- ParsedIntent 数据类
- 规则分类（chat / hermes / agent）
- 高风险检测
- 歧义检测
- 指令美化
- 边界情况（短消息、长消息、文件路径）
- parse_intent 便捷函数
"""

from __future__ import annotations

import pytest

from pycoder.server.services.intent_parser import (
    CATEGORY_RULES,
    RISK_KEYWORDS,
    IntentParser,
    ParsedIntent,
    TaskCategory,
    parse_intent,
)


# ══════════════════════════════════════════════════════════
# 测试：TaskCategory 枚举
# ══════════════════════════════════════════════════════════


class TestTaskCategory:
    """TaskCategory 枚举测试"""

    def test_enum_values(self):
        """枚举值正确"""
        assert TaskCategory.CHAT.value == "chat"
        assert TaskCategory.HERMES.value == "hermes"
        assert TaskCategory.AGENT.value == "agent"

    def test_enum_members(self):
        """枚举成员数量"""
        members = list(TaskCategory)
        assert len(members) == 3


# ══════════════════════════════════════════════════════════
# 测试：ParsedIntent 数据类
# ══════════════════════════════════════════════════════════


class TestParsedIntent:
    """ParsedIntent 数据类测试"""

    def test_create_default(self):
        """创建默认意图"""
        intent = ParsedIntent(
            raw_input="hello",
            surface_text="hello",
            core_need="简单问答",
        )
        assert intent.raw_input == "hello"
        assert intent.surface_text == "hello"
        assert intent.core_need == "简单问答"
        assert intent.ambiguity == ""
        assert intent.task_category == TaskCategory.CHAT
        assert intent.beautified_command == ""
        assert intent.has_risk is False
        assert intent.risk_description == ""

    def test_create_full(self):
        """创建完整意图"""
        intent = ParsedIntent(
            raw_input="删除所有文件",
            surface_text="删除所有文件",
            core_need="高风险操作",
            ambiguity="操作范围不明确",
            task_category=TaskCategory.HERMES,
            beautified_command="删除所有文件。",
            has_risk=True,
            risk_description="检测到高风险操作",
        )
        assert intent.task_category == TaskCategory.HERMES
        assert intent.has_risk is True
        assert intent.ambiguity == "操作范围不明确"

    def test_surface_text_truncated(self):
        """surface_text 在 parse 中自动截断"""
        parser = IntentParser()
        long_msg = "A" * 300
        result = parser.parse(long_msg)
        assert len(result.surface_text) <= 200


# ══════════════════════════════════════════════════════════
# 测试：分类规则
# ══════════════════════════════════════════════════════════


class TestClassification:
    """意图分类测试"""

    @pytest.fixture
    def parser(self):
        """创建意图解析器"""
        return IntentParser()

    # ── CHAT 分类 ──────────────────────────────────

    def test_classify_chat_question(self, parser):
        """简单问答 → chat"""
        result = parser.parse("什么是 Python？")
        assert result.task_category == TaskCategory.CHAT

    def test_classify_chat_greeting(self, parser):
        """问候 → chat"""
        result = parser.parse("你好")
        assert result.task_category == TaskCategory.CHAT

    def test_classify_chat_help(self, parser):
        """帮助请求 → chat"""
        result = parser.parse("你能帮我做什么？")
        assert result.task_category == TaskCategory.CHAT

    def test_classify_chat_comparison(self, parser):
        """对比询问 → chat"""
        result = parser.parse("Python 和 Java 的区别是什么？")
        assert result.task_category == TaskCategory.CHAT

    def test_classify_short_message(self, parser):
        """短消息（< 8 字符）→ chat"""
        result = parser.parse("hi")
        assert result.task_category == TaskCategory.CHAT
        assert "短消息" in result.core_need

    # ── HERMES 分类 ────────────────────────────────

    def test_classify_hermes_modify(self, parser):
        """修改操作 → hermes"""
        result = parser.parse("修改 config.py 文件中的数据库配置")
        assert result.task_category == TaskCategory.HERMES

    def test_classify_hermes_install(self, parser):
        """安装操作 → hermes"""
        result = parser.parse("安装 pytest 和 pytest-asyncio")
        assert result.task_category == TaskCategory.HERMES

    def test_classify_hermes_generate(self, parser):
        """代码生成 → hermes"""
        result = parser.parse("写一个 FastAPI 路由处理函数")
        assert result.task_category == TaskCategory.HERMES

    def test_classify_hermes_check(self, parser):
        """检查/分析 → hermes"""
        result = parser.parse("检查代码中的安全漏洞并修复")
        assert result.task_category == TaskCategory.HERMES

    def test_classify_hermes_git(self, parser):
        """Git 操作 → hermes"""
        result = parser.parse("提交当前的修改并推送")
        assert result.task_category == TaskCategory.HERMES

    def test_classify_hermes_file_path(self, parser):
        """含文件路径 → hermes 加权"""
        result = parser.parse("看看 test.py 文件的内容")
        assert result.task_category == TaskCategory.HERMES

    # ── AGENT 分类 ─────────────────────────────────

    def test_classify_agent_system_dev(self, parser):
        """系统开发 → agent"""
        result = parser.parse("开发一个完整的用户权限管理系统")
        assert result.task_category == TaskCategory.AGENT

    def test_classify_agent_architecture(self, parser):
        """架构设计 → agent"""
        result = parser.parse("设计一个微服务架构并规划整体重构方案")
        assert result.task_category == TaskCategory.AGENT

    def test_classify_agent_scaffold(self, parser):
        """项目初始化 → agent"""
        result = parser.parse("从零搭建一个 FastAPI 项目框架")
        assert result.task_category == TaskCategory.AGENT

    def test_classify_agent_multi_module(self, parser):
        """多模块开发 → agent"""
        result = parser.parse("实现用户认证模块和数据库接口")
        assert result.task_category == TaskCategory.AGENT

    def test_classify_agent_complex(self, parser):
        """复杂多步骤 → agent"""
        result = parser.parse("这是一个包含多个步骤的复杂任务，需要完整流程")
        assert result.task_category == TaskCategory.AGENT

    # ── 长消息默认 ─────────────────────────────────

    def test_classify_long_message_no_match(self, parser):
        """长消息无明确操作 → hermes（需 > 100 字符以触发长消息规则）"""
        base = "需要处理一个涉及多个模块的复杂业务逻辑，各个模块之间存在数据流转，需要仔细梳理依赖关系"
        result = parser.parse(base * 3)  # 确保 > 100 字符
        assert result.task_category == TaskCategory.HERMES

    def test_classify_keyword_position_weight(self, parser):
        """关键词在开头权重更高（长度需 >= 8 以避开短消息规则）"""
        result = parser.parse("修改这个文件的内容")
        assert result.task_category == TaskCategory.HERMES


# ══════════════════════════════════════════════════════════
# 测试：风险检测
# ══════════════════════════════════════════════════════════


class TestRiskDetection:
    """高风险检测测试"""

    @pytest.fixture
    def parser(self):
        return IntentParser()

    def test_detect_rm_rf(self, parser):
        """检测 rm -rf 高风险"""
        result = parser.parse("请执行 rm -rf /tmp/test")
        assert result.has_risk is True
        assert "rm -rf" in result.risk_description

    def test_detect_format(self, parser):
        """检测格式化高风险"""
        result = parser.parse("格式化磁盘分区")
        assert result.has_risk is True

    def test_detect_system_delete(self, parser):
        """检测删除系统文件高风险"""
        result = parser.parse("删除系统核心配置文件")
        assert result.has_risk is True

    def test_no_risk_normal(self, parser):
        """正常操作无风险"""
        result = parser.parse("创建一个新的 Python 文件")
        assert result.has_risk is False
        assert result.risk_description == ""

    def test_risk_keywords_not_empty(self):
        """RISK_KEYWORDS 列表不为空"""
        assert len(RISK_KEYWORDS) > 0


# ══════════════════════════════════════════════════════════
# 测试：歧义检测
# ══════════════════════════════════════════════════════════


class TestAmbiguityDetection:
    """歧义检测测试"""

    @pytest.fixture
    def parser(self):
        return IntentParser()

    def test_detect_ambiguous_pronoun(self, parser):
        """检测模糊代词"""
        result = parser.parse("修改那个文件")
        assert "模糊代词" in result.ambiguity

    def test_detect_modify_without_target(self, parser):
        """检测修改操作无目标文件"""
        result = parser.parse("修复这个 bug")
        assert "未指定目标文件" in result.ambiguity

    def test_detect_dev_without_tech_stack(self, parser):
        """检测开发操作无技术栈"""
        result = parser.parse("创建一个 Web 项目")
        assert "未指定技术栈" in result.ambiguity

    def test_no_ambiguity_clear(self, parser):
        """明确指令无歧义"""
        result = parser.parse("修改 src/main.py 中的数据库连接配置")
        assert result.ambiguity == ""

    def test_no_ambiguity_with_tech_stack(self, parser):
        """指定技术栈无歧义"""
        result = parser.parse("用 FastAPI 和 React 创建全栈项目")
        assert "未指定技术栈" not in result.ambiguity


# ══════════════════════════════════════════════════════════
# 测试：指令美化
# ══════════════════════════════════════════════════════════


class TestBeautify:
    """指令美化测试"""

    @pytest.fixture
    def parser(self):
        return IntentParser()

    def test_beautify_hermes_adds_period(self, parser):
        """hermes 分类补充句号（长度需 >= 8 以避开短消息规则）"""
        result = parser.parse("修改配置文件内容")
        assert result.task_category == TaskCategory.HERMES
        assert result.beautified_command.endswith("。")

    def test_beautify_hermes_already_has_period(self, parser):
        """已带句号不重复添加"""
        result = parser.parse("修改配置。")
        assert result.beautified_command == "修改配置。"

    def test_beautify_agent_adds_tech_stack(self, parser):
        """agent 分类补充默认技术栈"""
        result = parser.parse("开发一个完整的后台管理系统")
        assert "默认技术栈" in result.beautified_command
        assert "Python" in result.beautified_command

    def test_beautify_agent_with_tech_stack_no_add(self, parser):
        """agent 分类已有技术栈不补充"""
        result = parser.parse("用 Go 开发一个完整的后台管理系统")
        assert "默认技术栈" not in result.beautified_command

    def test_beautify_chat_no_change(self, parser):
        """chat 分类不修改"""
        result = parser.parse("什么是 Python")
        assert result.beautified_command == "什么是 Python"


# ══════════════════════════════════════════════════════════
# 测试：parse_intent 便捷函数
# ══════════════════════════════════════════════════════════


class TestParseIntentFunction:
    """parse_intent() 便捷函数测试"""

    def test_parse_intent_returns_parsed_intent(self):
        """返回 ParsedIntent 实例"""
        result = parse_intent("你好")
        assert isinstance(result, ParsedIntent)

    def test_parse_intent_chat(self):
        """问答类消息"""
        result = parse_intent("什么是面向对象编程？")
        assert result.task_category == TaskCategory.CHAT

    def test_parse_intent_hermes(self):
        """工具操作类消息"""
        result = parse_intent("修改 app.py 中的路由配置")
        assert result.task_category == TaskCategory.HERMES

    def test_parse_intent_agent(self):
        """系统工程类消息"""
        result = parse_intent("开发一个完整的电商平台系统")
        assert result.task_category == TaskCategory.AGENT


# ══════════════════════════════════════════════════════════
# 测试：边界情况
# ══════════════════════════════════════════════════════════


class TestEdgeCases:
    """边界情况测试"""

    @pytest.fixture
    def parser(self):
        return IntentParser()

    def test_empty_message(self, parser):
        """空消息"""
        result = parser.parse("")
        assert result.task_category == TaskCategory.CHAT
        assert result.surface_text == ""

    def test_whitespace_only(self, parser):
        """纯空白消息"""
        result = parser.parse("   ")
        assert result.task_category == TaskCategory.CHAT

    def test_very_long_message(self, parser):
        """超长消息"""
        long_msg = "我需要开发一个系统 " * 50
        result = parser.parse(long_msg)
        assert result.task_category in (
            TaskCategory.HERMES,
            TaskCategory.AGENT,
        )

    def test_mixed_keywords(self, parser):
        """混合关键词 — 最高分获胜"""
        # 同时包含 "修改" (hermes) 和 "什么是" (chat)
        result = parser.parse("什么是 Python？修改一下 test.py")
        # "修改" 在前面且匹配文件路径，hermes 得分更高
        assert result.task_category == TaskCategory.HERMES

    def test_category_rules_not_empty(self):
        """CATEGORY_RULES 列表不为空"""
        assert len(CATEGORY_RULES) > 0

    def test_each_category_in_rules(self):
        """CATEGORY_RULES 包含所有类别"""
        categories = {cat for _, cat, _ in CATEGORY_RULES}
        assert TaskCategory.CHAT in categories
        assert TaskCategory.HERMES in categories
        assert TaskCategory.AGENT in categories