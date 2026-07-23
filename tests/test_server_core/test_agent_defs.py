from __future__ import annotations

import json
import os
import sys
import time
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════
# 5. agent_definitions.py 测试
# ═══════════════════════════════════════════════════════════════


class TestAgentRole:
    """AgentRole 数据类测试"""

    def test_agent_role_defaults(self):
        """AgentRole 应有合理的默认值"""
        from pycoder.server.services.agent_definitions import AgentRole

        role = AgentRole(
            id="test",
            name="测试角色",
            description="测试用",
            system_prompt="你是测试角色",
            tools=["read_file"],
        )
        assert role.id == "test"
        assert role.model == "deepseek-chat"
        assert role.model_tier == "standard"
        assert role.parallel is False
        assert role.max_retries == 3
        assert role.timeout == 120
        assert role.max_concurrent == 1
        assert role.skills == []
        assert role.forbid_actions == []
        assert role.heartbeat_interval == 0


class TestAgentTask:
    """AgentTask 数据类测试"""

    def test_agent_task_defaults(self):
        """AgentTask 应有合理的默认值"""
        from pycoder.server.services.agent_definitions import AgentTask

        task = AgentTask(
            id="task-1",
            title="测试任务",
            description="任务描述",
            assigned_role="developer",
        )
        assert task.id == "task-1"
        assert task.status == "pending"
        assert task.depends_on == []
        assert task.deliverables == []
        assert task.retries == 0
        assert task.max_retries == 3


class TestAgentMessage:
    """AgentMessage 数据类测试"""

    def test_agent_message_defaults(self):
        """AgentMessage 应有合理的默认值"""
        from pycoder.server.services.agent_definitions import AgentMessage

        msg = AgentMessage(
            from_agent="pm",
            to_agent="developer",
            msg_type="task",
            content="请实现用户认证",
        )
        assert msg.from_agent == "pm"
        assert msg.to_agent == "developer"
        assert msg.msg_type == "task"
        assert msg.attachments == []
        assert msg.context == {}


class TestAgentRoles:
    """预定义 Agent 角色测试"""

    def test_all_roles_defined(self):
        """所有 7 种角色应已定义"""
        from pycoder.server.services.agent_definitions import AGENT_ROLES

        expected_roles = ["pm", "architect", "developer", "qa", "documenter", "fixer", "devops"]
        for role_id in expected_roles:
            assert role_id in AGENT_ROLES
            assert AGENT_ROLES[role_id].id == role_id

    def test_pm_role_properties(self):
        """PM 角色应有正确的属性"""
        from pycoder.server.services.agent_definitions import AGENT_ROLES

        pm = AGENT_ROLES["pm"]
        assert pm.model_tier == "standard"
        assert pm.max_concurrent == 1
        assert pm.heartbeat_interval == 1800
        assert "taskflow" in pm.skills
        assert not pm.parallel

    def test_architect_role_properties(self):
        """架构师角色应有 premium 模型"""
        from pycoder.server.services.agent_definitions import AGENT_ROLES

        architect = AGENT_ROLES["architect"]
        assert architect.model_tier == "premium"
        assert architect.model == "deepseek-reasoner"

    def test_developer_role_properties(self):
        """开发者角色应支持并行"""
        from pycoder.server.services.agent_definitions import AGENT_ROLES

        developer = AGENT_ROLES["developer"]
        assert developer.parallel is True
        assert developer.max_concurrent == 3

    def test_qa_role_properties(self):
        """QA 角色应有正确的禁止操作"""
        from pycoder.server.services.agent_definitions import AGENT_ROLES

        qa = AGENT_ROLES["qa"]
        assert "code_write" in qa.forbid_actions
        assert "deploy" in qa.forbid_actions

    def test_fixer_role_properties(self):
        """Fixer 角色应有 patch 技能"""
        from pycoder.server.services.agent_definitions import AGENT_ROLES

        fixer = AGENT_ROLES["fixer"]
        assert "patch" in fixer.skills
        assert "fix" in fixer.skills

    def test_devops_role_properties(self):
        """DevOps 角色应有空 forbid_actions"""
        from pycoder.server.services.agent_definitions import AGENT_ROLES

        devops = AGENT_ROLES["devops"]
        assert devops.forbid_actions == []


class TestModelTiers:
    """模型分层测试"""

    def test_model_tiers_have_expected_keys(self):
        """MODEL_TIERS 应包含所有分层"""
        from pycoder.server.services.agent_definitions import MODEL_TIERS

        expected = ["premium", "standard", "economy", "vision", "local"]
        for tier in expected:
            assert tier in MODEL_TIERS

    def test_get_model_for_tier_known(self):
        """已知分层应返回正确的模型"""
        from pycoder.server.services.agent_definitions import get_model_for_tier

        assert get_model_for_tier("premium") == "deepseek-reasoner"
        assert get_model_for_tier("standard") == "deepseek-chat"

    def test_get_model_for_tier_unknown(self):
        """未知分层应返回默认模型"""
        from pycoder.server.services.agent_definitions import get_model_for_tier

        assert get_model_for_tier("nonexistent") == "deepseek-chat"

    def test_get_model_for_tier_local_empty(self):
        """local 分层（无模型）应返回默认模型"""
        from pycoder.server.services.agent_definitions import get_model_for_tier

        assert get_model_for_tier("local") == "deepseek-chat"


class TestRoleTier:
    """角色分层查询测试"""

    def test_get_role_tier_known(self):
        """已知角色应返回正确的分层"""
        from pycoder.server.services.agent_definitions import get_role_tier

        assert get_role_tier("architect") == "premium"
        assert get_role_tier("pm") == "standard"
        assert get_role_tier("documenter") == "economy"

    def test_get_role_tier_unknown(self):
        """未知角色应返回 standard"""
        from pycoder.server.services.agent_definitions import get_role_tier

        assert get_role_tier("nonexistent") == "standard"


class TestConcurrencyLimits:
    """并发限制测试"""

    def test_concurrency_limits_have_expected_keys(self):
        """CONCURRENCY_LIMITS 应包含所有限制键"""
        from pycoder.server.services.agent_definitions import CONCURRENCY_LIMITS

        expected = ["global", "dev_team", "qa_team", "devops_team", "single_agent"]
        for key in expected:
            assert key in CONCURRENCY_LIMITS

    def test_get_concurrency_limit_known(self):
        """已知类别应返回正确限制"""
        from pycoder.server.services.agent_definitions import get_concurrency_limit

        assert get_concurrency_limit("global") == 10
        assert get_concurrency_limit("dev_team") == 6

    def test_get_concurrency_limit_unknown(self):
        """未知类别应返回默认值 10"""
        from pycoder.server.services.agent_definitions import get_concurrency_limit

        assert get_concurrency_limit("unknown") == 10


class TestRoleConcurrency:
    """角色并发数测试"""

    def test_get_role_concurrency_known(self):
        """已知角色应返回正确的并发数"""
        from pycoder.server.services.agent_definitions import get_role_concurrency

        assert get_role_concurrency("developer") == 3
        assert get_role_concurrency("pm") == 1

    def test_get_role_concurrency_unknown(self):
        """未知角色应返回 1"""
        from pycoder.server.services.agent_definitions import get_role_concurrency

        assert get_role_concurrency("unknown") == 1


class TestGlobalConstants:
    """全局常量测试"""

    def test_max_retries(self):
        """MAX_RETRIES 应为 2"""
        from pycoder.server.services.agent_definitions import MAX_RETRIES

        assert MAX_RETRIES == 2

    def test_task_timeout(self):
        """TASK_TIMEOUT 应为 1200"""
        from pycoder.server.services.agent_definitions import TASK_TIMEOUT

        assert TASK_TIMEOUT == 1200


class TestGetRole:
    """get_role 工厂函数测试"""

    def test_get_role_exists(self):
        """存在的角色应返回正确的 AgentRole"""
        from pycoder.server.services.agent_definitions import get_role

        role = get_role("pm")
        assert role is not None
        assert role.id == "pm"

    def test_get_role_not_exists(self):
        """不存在的角色应返回 None"""
        from pycoder.server.services.agent_definitions import get_role

        role = get_role("superhero")
        assert role is None


class TestCreateTask:
    """create_task 工厂函数测试"""

    def test_create_task_basic(self):
        """基本创建任务应正确设置字段"""
        from pycoder.server.services.agent_definitions import create_task

        task = create_task(
            title="测试任务",
            description="任务描述",
            assigned_role="developer",
        )
        assert task.title == "测试任务"
        assert task.assigned_role == "developer"
        assert task.status == "pending"
        assert task.id.startswith("task-")
        assert task.created_at > 0

    def test_create_task_with_dependencies(self):
        """带依赖的任务创建"""
        from pycoder.server.services.agent_definitions import create_task

        task = create_task(
            title="任务2",
            description="依赖任务1",
            assigned_role="qa",
            depends_on=["task-1"],
            deliverables=["report.md"],
        )
        assert task.depends_on == ["task-1"]
        assert task.deliverables == ["report.md"]


# ═══════════════════════════════════════════════════════════════
# 6. agent_parser.py 测试
# ═══════════════════════════════════════════════════════════════


class TestParsedResponse:
    """ParsedResponse 数据类测试"""

    def test_parsed_response_defaults(self):
        """ParsedResponse 应有合理的默认值"""
        from pycoder.server.services.agent_parser import ParsedResponse

        pr = ParsedResponse(
            raw="test",
            tool_calls=[],
            file_blocks=[],
            completion=False,
            summary="",
            errors=[],
        )
        assert pr.raw == "test"
        assert pr.tool_calls == []
        assert pr.completion is False


class TestDetectCompletion:
    """完成信号检测测试"""

    def test_detect_completion_chinese_done(self):
        """中文"完成"应检测为完成信号"""
        from pycoder.server.services.agent_parser import _detect_completion

        is_comp, summary = _detect_completion("完成！所有任务已完成。")
        assert is_comp is True

    def test_detect_completion_done(self):
        """英文"done"应检测为完成信号"""
        from pycoder.server.services.agent_parser import _detect_completion

        is_comp, summary = _detect_completion("done.")
        assert is_comp is True

    def test_detect_completion_finished(self):
        """英文"finished"应检测为完成信号"""
        from pycoder.server.services.agent_parser import _detect_completion

        is_comp, summary = _detect_completion("finished!")
        assert is_comp is True

    def test_detect_completion_summary(self):
        """"总结:"应检测为完成信号"""
        from pycoder.server.services.agent_parser import _detect_completion

        is_comp, summary = _detect_completion("总结：本次开发了用户认证模块...")
        assert is_comp is True

    def test_detect_completion_emoji(self):
        """"✅"开头应检测为完成信号"""
        from pycoder.server.services.agent_parser import _detect_completion

        is_comp, summary = _detect_completion("✅ 所有任务已完成")
        assert is_comp is True

    def test_detect_not_completion(self):
        """普通文本不应检测为完成信号"""
        from pycoder.server.services.agent_parser import _detect_completion

        is_comp, summary = _detect_completion("请读取文件 config.yaml")
        assert is_comp is False


class TestParseResponse:
    """统一解析器测试"""

    def test_parse_empty_text(self):
        """空文本应返回空结果"""
        from pycoder.server.services.agent_parser import parse_response

        result = parse_response("")
        assert result.completion is False
        assert result.tool_calls == []
        assert result.file_blocks == []

    def test_parse_completion_signal(self):
        """完成信号应正确识别"""
        from pycoder.server.services.agent_parser import parse_response

        result = parse_response("完成！所有任务已完成。")
        assert result.completion is True
        assert len(result.summary) > 0

    def test_parse_tool_calls_json(self):
        """JSON tool_calls 格式应正确解析"""
        from pycoder.server.services.agent_parser import parse_response

        text = '```json\n{"tool_calls": [{"name": "read_file", "params": {"path": "test.py"}}]}\n```'
        result = parse_response(text)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "read_file"
        assert result.tool_calls[0]["params"] == {"path": "test.py"}

    def test_parse_tool_calls_bare_json(self):
        """裸 JSON tool_calls 应正确解析"""
        from pycoder.server.services.agent_parser import parse_response

        text = '{"tool_calls": [{"name": "write_file", "params": {"path": "test.py", "content": "hello"}}]}'
        result = parse_response(text)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "write_file"

    def test_parse_single_tool_format(self):
        """单工具 JSON 格式应正确解析"""
        from pycoder.server.services.agent_parser import parse_response

        text = '{"name": "read_file", "params": {"path": "config.yaml"}}'
        result = parse_response(text)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "read_file"

    def test_parse_react_format(self):
        """ReAct 格式应正确解析"""
        from pycoder.server.services.agent_parser import parse_response

        text = '{"thought": "需要读文件", "action": "read_file", "action_input": {"path": "test.py"}}'
        result = parse_response(text)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "read_file"
        assert result.tool_calls[0]["_react_thought"] == "需要读文件"

    def test_parse_react_finish_not_tool_call(self):
        """ReAct FINISH 动作不应被解析为工具调用"""
        from pycoder.server.services.agent_parser import parse_response

        text = '{"thought": "完成", "action": "FINISH", "action_input": {}}'
        result = parse_response(text)
        assert result.tool_calls == []

    def test_parse_file_blocks(self):
        """FILE: 代码块应正确解析"""
        from pycoder.server.services.agent_parser import parse_response

        text = "```FILE:test.py\nprint('hello')\n```"
        result = parse_response(text)
        assert len(result.file_blocks) >= 1
        assert any(b["path"] == "test.py" for b in result.file_blocks)
        assert any("print('hello')" in b["content"] for b in result.file_blocks)

    def test_parse_inline_code_blocks(self):
        """内联代码块应正确解析"""
        from pycoder.server.services.agent_parser import parse_response

        text = "```python:test.py\nprint('hello')\n```"
        result = parse_response(text)
        # 内联代码块在没有 tool_calls 时被解析
        assert len(result.file_blocks) >= 1

    def test_parse_response_combines_all(self):
        """混合内容应同时解析工具调用和文件块"""
        from pycoder.server.services.agent_parser import parse_response

        text = (
            '{"tool_calls": [{"name": "read_file", "params": {"path": "a.py"}}]}\n'
            "```FILE:b.py\ncontent\n```"
        )
        result = parse_response(text)
        assert len(result.tool_calls) >= 1
        assert len(result.file_blocks) >= 1


class TestParseJsonBlock:
    """JSON 代码块解析测试"""

    def test_parse_tool_calls_array(self):
        """tool_calls 数组格式"""
        from pycoder.server.services.agent_parser import _parse_json_block

        block = json.dumps({
            "tool_calls": [
                {"name": "read_file", "params": {}},
                {"name": "write_file", "params": {}},
            ]
        })
        result = _parse_json_block(block)
        assert len(result) == 2

    def test_parse_single_tool_in_block(self):
        """单个工具格式"""
        from pycoder.server.services.agent_parser import _parse_json_block

        block = json.dumps({"name": "read_file", "params": {"path": "test.py"}})
        result = _parse_json_block(block)
        assert len(result) == 1
        assert result[0]["name"] == "read_file"

    def test_parse_direct_array(self):
        """直接工具数组格式"""
        from pycoder.server.services.agent_parser import _parse_json_block

        block = json.dumps([
            {"name": "read_file", "params": {"path": "a.py"}},
            {"name": "write_file", "params": {"path": "b.py", "content": "c"}},
        ])
        result = _parse_json_block(block)
        assert len(result) == 2

    def test_parse_invalid_json(self):
        """无效 JSON 应返回空列表"""
        from pycoder.server.services.agent_parser import _parse_json_block

        result = _parse_json_block("not json")
        assert result == []


class TestParseBareJson:
    """裸 JSON 解析测试"""

    def test_parse_with_prefix_suffix(self):
        """带前后缀的裸 JSON 应正确解析"""
        from pycoder.server.services.agent_parser import _parse_bare_json

        text = 'prefix text {"name": "read_file", "params": {"path": "test.py"}} suffix'
        result = _parse_bare_json(text)
        assert len(result) == 1
        assert result[0]["name"] == "read_file"

    def test_no_braces(self):
        """无花括号应返回空列表"""
        from pycoder.server.services.agent_parser import _parse_bare_json

        result = _parse_bare_json("no braces")
        assert result == []


class TestExtractFileBlocks:
    """FILE 代码块提取测试"""

    def test_extract_single_file_block(self):
        """单个 FILE 块应正确提取"""
        from pycoder.server.services.agent_parser import _extract_file_blocks

        text = "```FILE:src/app.py\nprint('hello')\n```"
        blocks = _extract_file_blocks(text)
        assert len(blocks) == 1
        assert blocks[0]["path"] == "src/app.py"
        assert blocks[0]["source"] == "file-block"

    def test_extract_multiple_file_blocks(self):
        """多个 FILE 块应全部提取"""
        from pycoder.server.services.agent_parser import _extract_file_blocks

        text = (
            "```FILE:a.py\ncontent a\n```\n"
            "```FILE:b.py\ncontent b\n```"
        )
        blocks = _extract_file_blocks(text)
        assert len(blocks) == 2

    def test_extract_no_file_blocks(self):
        """无 FILE 块应返回空列表"""
        from pycoder.server.services.agent_parser import _extract_file_blocks

        blocks = _extract_file_blocks("plain text")
        assert blocks == []


class TestIsToolNameValid:
    """工具名称验证测试"""

    def test_known_tool_valid(self):
        """已知工具名应验证通过"""
        from pycoder.server.services.agent_parser import is_tool_name_valid

        assert is_tool_name_valid("read_file") is True
        assert is_tool_name_valid("write_file") is True
        assert is_tool_name_valid("run_command") is True

    def test_unknown_tool_invalid(self):
        """未知工具名应验证失败"""
        from pycoder.server.services.agent_parser import is_tool_name_valid

        assert is_tool_name_valid("unknown_tool") is False

    def test_pycoder_prefix_valid(self):
        """pycoder. 前缀的工具名应验证通过"""
        from pycoder.server.services.agent_parser import is_tool_name_valid

        assert is_tool_name_valid("pycoder.custom_tool") is True

    def test_underscore_prefix_valid(self):
        """_ 前缀的工具名应验证通过"""
        from pycoder.server.services.agent_parser import is_tool_name_valid

        assert is_tool_name_valid("_internal_tool") is True


class TestValidateToolCall:
    """工具调用校验测试"""

    def test_valid_tool_call(self):
        """有效的工具调用应校验通过"""
        from pycoder.server.services.agent_parser import validate_tool_call

        valid, msg = validate_tool_call({"name": "read_file", "params": {"path": "test.py"}})
        assert valid is True
        assert msg == ""

    def test_missing_name(self):
        """缺少名称应校验失败"""
        from pycoder.server.services.agent_parser import validate_tool_call

        valid, msg = validate_tool_call({"params": {}})
        assert valid is False
        assert "名称为空" in msg

    def test_params_not_dict(self):
        """参数非字典应校验失败"""
        from pycoder.server.services.agent_parser import validate_tool_call

        valid, msg = validate_tool_call({"name": "read_file", "params": "not a dict"})
        assert valid is False
        assert "参数必须是对象" in msg


