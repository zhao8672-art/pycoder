"""
对 pycoder/server 工具模块的综合单元测试。

覆盖模块:
  1. server/skills_checker.py     — 技能可用性检测
  2. server/services/tool_schema.py — 工具调用 JSON Schema 校验
  3. server/skills_report.py      — 技能市场月报生成器
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════
# 1. server/skills_checker.py 测试
# ═══════════════════════════════════════════════════════════════


class TestCheckSkillUsability:
    """check_skill_usability 函数测试"""

    def test_skill_with_api_key_in_description(self):
        """技能描述中包含 api_key 模式"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "my-skill",
            "description": "This skill requires an api_key for OpenAI",
            "tags": ["ai", "text"],
            "url": "https://example.com",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "api_key" in result["api_services"]
        assert result["usable_offline"] is False

    def test_skill_without_api_key(self):
        """纯离线技能，不含任何外部 API 模式"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "hello-world",
            "description": "A simple hello world skill",
            "tags": ["utility", "basic"],
            "url": "https://example.com",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is False
        assert result["api_services"] == []
        assert result["usable_offline"] is True

    def test_skill_with_openai_pattern(self):
        """技能名称中包含 openai 模式"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "openai-chat",
            "description": "Chat with OpenAI models",
            "tags": ["ai"],
            "url": "https://platform.openai.com",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "openai" in result["api_services"]

    def test_skill_with_token_pattern(self):
        """技能描述中包含 token 模式"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "auth-service",
            "description": "Authenticate using bearer token",
            "tags": ["auth"],
            "url": "https://auth.example.com",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "token" in result["api_services"]

    def test_skill_with_bearer_pattern(self):
        """技能描述中包含 bearer 模式"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "api-gateway",
            "description": "Uses bearer authorization",
            "tags": ["api"],
            "url": "",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "bearer" in result["api_services"]

    def test_skill_with_secret_in_tags(self):
        """技能 tags 中包含 secret 模式"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "vault",
            "description": "Manage secrets",
            "tags": ["secret", "security"],
            "url": "https://vault.example.com",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "secret" in result["api_services"]

    def test_skill_with_authorization_in_name(self):
        """技能名称中包含 authorization 模式"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "authorization-helper",
            "description": "Helper for auth",
            "tags": [],
            "url": "",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "authorization" in result["api_services"]

    def test_skill_with_huggingface_in_url(self):
        """技能 URL 中包含 huggingface 模式"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "hf-model",
            "description": "Run models",
            "tags": ["ml"],
            "url": "https://huggingface.co/models",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "huggingface" in result["api_services"]

    def test_skill_with_stripe_pattern(self):
        """技能中包含 stripe 模式"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "payment",
            "description": "Process payments via Stripe",
            "tags": ["payment"],
            "url": "https://stripe.com",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "stripe" in result["api_services"]

    def test_skill_with_twilio_pattern(self):
        """技能中包含 twilio 模式"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "sms-sender",
            "description": "Send SMS using Twilio",
            "tags": ["sms"],
            "url": "",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "twilio" in result["api_services"]

    def test_skill_with_sendgrid_pattern(self):
        """技能中包含 sendgrid 模式"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "emailer",
            "description": "Send emails via SendGrid",
            "tags": ["email"],
            "url": "",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "sendgrid" in result["api_services"]

    def test_skill_with_aws_prefix(self):
        """技能中包含 aws_ 模式"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "s3-uploader",
            "description": "Upload files to AWS S3",
            "tags": ["aws_", "cloud"],
            "url": "",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "aws_" in result["api_services"]

    def test_skill_with_gcp_prefix(self):
        """技能中包含 gcp_ 模式"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "gcp-storage",
            "description": "Store files on GCP",
            "tags": ["gcp_", "cloud"],
            "url": "",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "gcp_" in result["api_services"]

    def test_skill_with_azure_prefix(self):
        """技能中包含 azure_ 模式"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "azure-func",
            "description": "Deploy to Azure Functions",
            "tags": ["azure_", "cloud"],
            "url": "",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "azure_" in result["api_services"]

    def test_skill_with_muapi_pattern(self):
        """技能中包含 muapi 模式"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "muapi-client",
            "description": "Client for muapi",
            "tags": [],
            "url": "https://muapi.io",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "muapi" in result["api_services"]

    def test_skill_with_chinese_api_keyword(self):
        """技能描述中包含中文关键词"需要密钥"（纯中文无大小写问题）"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "translator",
            "description": "需要密钥才能使用翻译服务",
            "tags": ["translate"],
            "url": "",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "需要密钥" in result["api_services"]

    def test_skill_with_chinese_secret_keyword(self):
        """技能描述中包含中文关键词"需要密钥" """
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "encryptor",
            "description": "此技能需要密钥才能正常工作",
            "tags": ["security"],
            "url": "",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "需要密钥" in result["api_services"]

    def test_skill_with_requires_keyword(self):
        """技能描述中包含 requires 关键词"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "advanced-tool",
            "description": "This tool requires an external service",
            "tags": ["tool"],
            "url": "",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "requires" in result["api_services"]

    def test_skill_with_api_key_in_name(self):
        """技能名称中包含 api_key 关键词"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "api_key_manager",
            "description": "Manage API keys",
            "tags": [],
            "url": "",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        # api_key 匹配 EXTERNAL_API_PATTERNS 也匹配 EXTERNAL_API_KEYWORDS
        assert "api_key" in result["api_services"]

    def test_skill_multiple_patterns(self):
        """技能匹配多个模式时，api_services 应包含所有匹配项"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "openai-proxy",
            "description": "需要密钥，使用 bearer token 认证，requires 外部服务",
            "tags": ["secret"],
            "url": "https://huggingface.co",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "openai" in result["api_services"]
        assert "bearer" in result["api_services"]
        assert "token" in result["api_services"]
        assert "secret" in result["api_services"]
        assert "huggingface" in result["api_services"]
        assert "需要密钥" in result["api_services"]
        assert "requires" in result["api_services"]
        assert result["usable_offline"] is False
        # api_services 应该已排序
        assert result["api_services"] == sorted(result["api_services"])

    def test_skill_empty_dict(self):
        """空技能字典"""
        from pycoder.server.skills_checker import check_skill_usability

        skill: dict = {}
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is False
        assert result["api_services"] == []
        assert result["usable_offline"] is True

    def test_skill_none_values(self):
        """技能字段值为 None"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": None,
            "description": None,
            "tags": None,
            "url": None,
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is False
        assert result["api_services"] == []
        assert result["usable_offline"] is True

    def test_skill_with_only_api_keyword_in_tags_not_matched(self):
        """api_key 关键词只在 tags 中（小写），但 EXTERNAL_API_KEYWORDS
        仅检查 description 和 name，所以 tags 中的 api_key 不会触发
        EXTERNAL_API_KEYWORDS 匹配。但 EXTERNAL_API_PATTERNS 会检查
        all_text（含 tags），所以 api_key 仍会被匹配到。"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "my-tool",
            "description": "A simple tool",
            "tags": ["api_key"],
            "url": "",
        }
        result = check_skill_usability(skill)
        # api_key 在 EXTERNAL_API_PATTERNS 中，会通过 all_text 匹配到
        assert result["needs_external_api"] is True

    def test_skill_case_insensitive(self):
        """模式匹配不区分大小写"""
        from pycoder.server.skills_checker import check_skill_usability

        skill = {
            "name": "OpenAI-Client",
            "description": "Uses Bearer Token for Auth",
            "tags": ["Stripe"],
            "url": "https://HuggingFace.co",
        }
        result = check_skill_usability(skill)
        assert result["needs_external_api"] is True
        assert "openai" in result["api_services"]
        assert "bearer" in result["api_services"]
        assert "token" in result["api_services"]
        assert "stripe" in result["api_services"]
        assert "huggingface" in result["api_services"]


class TestBatchCheckSkills:
    """batch_check_skills 函数测试"""

    def test_batch_with_mixed_skills(self):
        """批量检测混合技能（有 API 和无 API）"""
        from pycoder.server.skills_checker import batch_check_skills

        skills = [
            {
                "name": "offline-skill",
                "description": "A simple offline tool",
                "tags": ["utility"],
                "url": "",
            },
            {
                "name": "openai-skill",
                "description": "Requires OpenAI API key",
                "tags": ["ai"],
                "url": "",
            },
            {
                "name": "another-offline",
                "description": "Another simple tool",
                "tags": [],
                "url": "",
            },
        ]
        result = batch_check_skills(skills)

        assert len(result) == 3
        assert result[0]["needs_external_api"] is False
        assert result[0]["usable_offline"] is True
        assert result[0]["api_services"] == []

        assert result[1]["needs_external_api"] is True
        assert result[1]["usable_offline"] is False
        assert "openai" in result[1]["api_services"]

        assert result[2]["needs_external_api"] is False
        assert result[2]["usable_offline"] is True
        assert result[2]["api_services"] == []

    def test_batch_empty_list(self):
        """批量检测空列表"""
        from pycoder.server.skills_checker import batch_check_skills

        result = batch_check_skills([])
        assert result == []

    def test_batch_all_offline(self):
        """批量检测全部离线技能"""
        from pycoder.server.skills_checker import batch_check_skills

        skills = [
            {"name": "tool-a", "description": "Simple tool A", "tags": [], "url": ""},
            {"name": "tool-b", "description": "Simple tool B", "tags": [], "url": ""},
        ]
        result = batch_check_skills(skills)

        for skill in result:
            assert skill["needs_external_api"] is False
            assert skill["usable_offline"] is True
            assert skill["api_services"] == []

    def test_batch_all_api(self):
        """批量检测全部需要 API 的技能"""
        from pycoder.server.skills_checker import batch_check_skills

        skills = [
            {"name": "openai-tool", "description": "OpenAI API", "tags": [], "url": ""},
            {"name": "stripe-tool", "description": "Stripe payment", "tags": [], "url": ""},
        ]
        result = batch_check_skills(skills)

        for skill in result:
            assert skill["needs_external_api"] is True
            assert skill["usable_offline"] is False
            assert len(skill["api_services"]) > 0

    def test_batch_preserves_original_fields(self):
        """批量检测不修改原始字段"""
        from pycoder.server.skills_checker import batch_check_skills

        skills = [
            {
                "name": "my-skill",
                "description": "A skill",
                "tags": ["tag1"],
                "url": "https://example.com",
                "extra_field": "keep-me",
            },
        ]
        result = batch_check_skills(skills)

        assert result[0]["name"] == "my-skill"
        assert result[0]["description"] == "A skill"
        assert result[0]["tags"] == ["tag1"]
        assert result[0]["url"] == "https://example.com"
        assert result[0]["extra_field"] == "keep-me"


# ═══════════════════════════════════════════════════════════════
# 2. server/services/tool_schema.py 测试
# ═══════════════════════════════════════════════════════════════


class TestValidateToolCalls:
    """validate_tool_calls 函数测试"""

    def test_valid_single_tool_call(self):
        """有效的单个工具调用"""
        from pycoder.server.services.tool_schema import validate_tool_calls

        data = {
            "tool_calls": [
                {"name": "read_file", "params": {"path": "/tmp/test.txt"}},
            ],
        }
        result = validate_tool_calls(data)
        assert len(result) == 1
        assert result[0]["name"] == "read_file"
        assert result[0]["params"] == {"path": "/tmp/test.txt"}

    def test_valid_multiple_tool_calls(self):
        """有效的多个工具调用"""
        from pycoder.server.services.tool_schema import validate_tool_calls

        data = {
            "tool_calls": [
                {"name": "read_file", "params": {"path": "/tmp/a.txt"}},
                {"name": "write_file", "params": {"path": "/tmp/b.txt", "content": "hello"}},
                {"name": "search", "params": {"query": "test"}},
            ],
        }
        result = validate_tool_calls(data)
        assert len(result) == 3
        assert result[0]["name"] == "read_file"
        assert result[1]["name"] == "write_file"
        assert result[2]["name"] == "search"

    def test_valid_with_thought(self):
        """有效响应包含 thought 字段"""
        from pycoder.server.services.tool_schema import validate_tool_calls

        data = {
            "tool_calls": [
                {"name": "read_file", "params": {"path": "/tmp/test.txt"}},
            ],
            "thought": "I need to read the file first",
        }
        result = validate_tool_calls(data)
        assert len(result) == 1
        assert result[0]["name"] == "read_file"

    def test_valid_empty_params(self):
        """有效的工具调用，params 为空字典"""
        from pycoder.server.services.tool_schema import validate_tool_calls

        data = {
            "tool_calls": [
                {"name": "list_files", "params": {}},
            ],
        }
        result = validate_tool_calls(data)
        assert len(result) == 1
        assert result[0]["name"] == "list_files"
        assert result[0]["params"] == {}

    def test_valid_empty_tool_calls_array(self):
        """tool_calls 为空数组"""
        from pycoder.server.services.tool_schema import validate_tool_calls

        data = {"tool_calls": []}
        result = validate_tool_calls(data)
        assert result == []

    def test_invalid_missing_tool_calls(self):
        """缺少 tool_calls 字段"""
        from pycoder.server.services.tool_schema import validate_tool_calls

        data = {"thought": "no tools here"}
        with pytest.raises(ValueError, match="工具调用格式校验失败"):
            validate_tool_calls(data)

    def test_invalid_tool_calls_not_array(self):
        """tool_calls 不是数组"""
        from pycoder.server.services.tool_schema import validate_tool_calls

        data = {"tool_calls": "not_an_array"}
        with pytest.raises(ValueError, match="工具调用格式校验失败"):
            validate_tool_calls(data)

    def test_invalid_missing_name(self):
        """工具调用缺少 name 字段"""
        from pycoder.server.services.tool_schema import validate_tool_calls

        data = {
            "tool_calls": [
                {"params": {"path": "/tmp/test.txt"}},
            ],
        }
        with pytest.raises(ValueError, match="工具调用格式校验失败"):
            validate_tool_calls(data)

    def test_invalid_missing_params(self):
        """工具调用缺少 params 字段"""
        from pycoder.server.services.tool_schema import validate_tool_calls

        data = {
            "tool_calls": [
                {"name": "read_file"},
            ],
        }
        with pytest.raises(ValueError, match="工具调用格式校验失败"):
            validate_tool_calls(data)

    def test_invalid_empty_name(self):
        """工具调用 name 为空字符串"""
        from pycoder.server.services.tool_schema import validate_tool_calls

        data = {
            "tool_calls": [
                {"name": "", "params": {"path": "/tmp/test.txt"}},
            ],
        }
        with pytest.raises(ValueError, match="工具调用格式校验失败"):
            validate_tool_calls(data)

    def test_invalid_extra_fields(self):
        """工具调用包含额外字段（additionalProperties: False）"""
        from pycoder.server.services.tool_schema import validate_tool_calls

        data = {
            "tool_calls": [
                {"name": "read_file", "params": {"path": "/tmp/test.txt"}, "extra": "field"},
            ],
        }
        with pytest.raises(ValueError, match="工具调用格式校验失败"):
            validate_tool_calls(data)

    def test_invalid_extra_top_level_field(self):
        """顶层响应包含额外字段"""
        from pycoder.server.services.tool_schema import validate_tool_calls

        data = {
            "tool_calls": [
                {"name": "read_file", "params": {"path": "/tmp/test.txt"}},
            ],
            "unexpected": "value",
        }
        with pytest.raises(ValueError, match="工具调用格式校验失败"):
            validate_tool_calls(data)

    def test_invalid_name_not_string(self):
        """工具调用 name 不是字符串"""
        from pycoder.server.services.tool_schema import validate_tool_calls

        data = {
            "tool_calls": [
                {"name": 123, "params": {"path": "/tmp/test.txt"}},
            ],
        }
        with pytest.raises(ValueError, match="工具调用格式校验失败"):
            validate_tool_calls(data)

    def test_invalid_params_not_object(self):
        """工具调用 params 不是对象"""
        from pycoder.server.services.tool_schema import validate_tool_calls

        data = {
            "tool_calls": [
                {"name": "read_file", "params": "not_an_object"},
            ],
        }
        with pytest.raises(ValueError, match="工具调用格式校验失败"):
            validate_tool_calls(data)

    def test_invalid_second_call_in_array(self):
        """数组中第二个工具调用无效时，错误消息应包含该工具名"""
        from pycoder.server.services.tool_schema import validate_tool_calls

        data = {
            "tool_calls": [
                {"name": "valid_call", "params": {"x": 1}},
                {"name": "", "params": {"x": 2}},  # 空名称
            ],
        }
        with pytest.raises(ValueError, match="工具调用"):
            validate_tool_calls(data)


class TestBuildToolCallsJson:
    """build_tool_calls_json 函数测试"""

    def test_build_simple(self):
        """构建简单的工具调用 JSON"""
        from pycoder.server.services.tool_schema import build_tool_calls_json

        result = build_tool_calls_json("read_file", {"path": "/tmp/test.txt"})
        assert result == {"name": "read_file", "params": {"path": "/tmp/test.txt"}}

    def test_build_with_empty_params(self):
        """构建带空 params 的工具调用 JSON"""
        from pycoder.server.services.tool_schema import build_tool_calls_json

        result = build_tool_calls_json("list_files", {})
        assert result == {"name": "list_files", "params": {}}

    def test_build_with_complex_params(self):
        """构建带复杂嵌套 params 的工具调用 JSON"""
        from pycoder.server.services.tool_schema import build_tool_calls_json

        params = {
            "path": "/tmp/test.txt",
            "options": {
                "encoding": "utf-8",
                "max_lines": 100,
            },
            "tags": ["important", "urgent"],
        }
        result = build_tool_calls_json("write_file", params)
        assert result["name"] == "write_file"
        assert result["params"] == params


class TestBuildToolCallsResponse:
    """build_tool_calls_response 函数测试"""

    def test_build_with_thought(self):
        """构建带 thought 的完整响应"""
        from pycoder.server.services.tool_schema import build_tool_calls_response

        calls = [
            {"name": "read_file", "params": {"path": "/tmp/test.txt"}},
        ]
        result = build_tool_calls_response(calls, thought="Reading the file")
        assert result == {
            "thought": "Reading the file",
            "tool_calls": [
                {"name": "read_file", "params": {"path": "/tmp/test.txt"}},
            ],
        }

    def test_build_without_thought(self):
        """构建不带 thought 的响应（默认空字符串）"""
        from pycoder.server.services.tool_schema import build_tool_calls_response

        calls = [
            {"name": "search", "params": {"query": "test"}},
        ]
        result = build_tool_calls_response(calls)
        assert result == {
            "thought": "",
            "tool_calls": [
                {"name": "search", "params": {"query": "test"}},
            ],
        }

    def test_build_with_multiple_calls(self):
        """构建多个工具调用的响应"""
        from pycoder.server.services.tool_schema import build_tool_calls_response

        calls = [
            {"name": "read_file", "params": {"path": "/tmp/a.txt"}},
            {"name": "read_file", "params": {"path": "/tmp/b.txt"}},
        ]
        result = build_tool_calls_response(calls, thought="Reading multiple files")
        assert len(result["tool_calls"]) == 2
        assert result["thought"] == "Reading multiple files"

    def test_build_with_empty_calls(self):
        """构建空工具调用列表的响应"""
        from pycoder.server.services.tool_schema import build_tool_calls_response

        result = build_tool_calls_response([], thought="No tools needed")
        assert result == {"thought": "No tools needed", "tool_calls": []}


# ═══════════════════════════════════════════════════════════════
# 3. server/skills_report.py 测试
# ═══════════════════════════════════════════════════════════════


class TestSkillsReportGeneratorInit:
    """SkillsReportGenerator.__init__ 测试"""

    def test_init_default_path(self):
        """默认路径初始化"""
        from pycoder.server.skills_report import SkillsReportGenerator

        gen = SkillsReportGenerator()
        assert gen._report_dir == Path.home() / ".pycoder" / "reports"
        assert gen._report_dir.exists()

    def test_init_custom_path(self):
        """自定义路径初始化"""
        from pycoder.server.skills_report import SkillsReportGenerator

        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = Path(tmpdir) / "custom_reports"
            gen = SkillsReportGenerator(report_dir=custom_path)
            assert gen._report_dir == custom_path
            assert gen._report_dir.exists()

    def test_init_custom_string_path(self):
        """自定义字符串路径初始化"""
        from pycoder.server.skills_report import SkillsReportGenerator

        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = str(Path(tmpdir) / "str_reports")
            gen = SkillsReportGenerator(report_dir=custom_path)
            assert gen._report_dir == Path(custom_path)
            assert gen._report_dir.exists()


class TestGenerateMarkdown:
    """generate_markdown 方法测试"""

    def test_full_report(self):
        """生成包含所有数据的完整报告"""
        from pycoder.server.skills_report import SkillsReportGenerator

        gen = SkillsReportGenerator()

        lifecycle_stats = {
            "AI/ML": [
                {"stage": "emerging", "count": 5},
                {"stage": "growing", "count": 3},
                {"stage": "stable", "count": 10},
            ],
            "Web": [
                {"stage": "stable", "count": 20},
                {"stage": "declining", "count": 2},
            ],
        }
        trending = [
            {"skill_name": "FastAPI", "category": "Web", "stars_28d": 500, "momentum": 0.15},
            {"skill_name": "LangChain", "category": "AI/ML", "stars_28d": 800, "momentum": 0.25},
        ]
        emerging = [
            {"skill_name": "Mojo", "category": "Languages", "stars_28d": 1200, "growth_rate_28d": 0.80},
            {"skill_name": "CrewAI", "category": "AI/ML", "stars_28d": 600, "growth_rate_28d": 0.55},
        ]
        so_trends = [
            {
                "technology": "Python",
                "adoption_2024": 45.0,
                "adoption_2025": 48.5,
                "growth_rate": 0.078,
                "stage": "growing",
            },
            {
                "technology": "Rust",
                "adoption_2024": 12.0,
                "adoption_2025": 15.0,
                "growth_rate": 0.25,
                "stage": "emerging",
            },
            {
                "technology": "PHP",
                "adoption_2024": 20.0,
                "adoption_2025": 18.0,
                "growth_rate": -0.10,
                "stage": "declining",
            },
        ]
        so_stats = {"technologies": 3, "rising": 2, "declining": 1}

        md = gen.generate_markdown(
            lifecycle_stats=lifecycle_stats,
            trending=trending,
            emerging=emerging,
            so_trends=so_trends,
            so_stats=so_stats,
        )

        # 验证报告结构
        assert "PyCoder 技能市场月报" in md
        assert "核心指标" in md
        assert "新兴技能 TOP 10" in md
        assert "趋势上升 TOP 10" in md
        assert "Stack Overflow 热点变迁" in md
        assert "分析摘要" in md

        # 验证具体数据
        assert "Stack Overflow 技术追踪" in md
        assert "3 项" in md
        assert "上升技术" in md
        assert "2 项" in md
        assert "下降技术" in md
        assert "1 项" in md

        # 生命周期统计
        assert "AI/ML" in md
        assert "emerging: 5" in md
        assert "growing: 3" in md
        assert "stable: 10" in md

        # 新兴技能
        assert "Mojo" in md
        assert "CrewAI" in md
        assert "80.0%" in md
        assert "55.0%" in md

        # 趋势技能
        assert "FastAPI" in md
        assert "LangChain" in md
        assert "+15.00%" in md
        assert "+25.00%" in md

        # SO 趋势
        assert "Python" in md
        assert "Rust" in md
        assert "PHP" in md
        assert "48.5%" in md
        assert "+7.8%" in md
        assert "+25.0%" in md
        assert "-10.0%" in md

        # 分析摘要
        assert "最热新兴技能" in md
        assert "快速上升" in md
        assert "持续下降" in md

    def test_empty_data(self):
        """生成空数据报告"""
        from pycoder.server.skills_report import SkillsReportGenerator

        gen = SkillsReportGenerator()

        md = gen.generate_markdown(
            lifecycle_stats={},
            trending=[],
            emerging=[],
            so_trends=[],
            so_stats={},
        )

        assert "PyCoder 技能市场月报" in md
        assert "核心指标" in md
        assert "新兴技能 TOP 10" in md
        assert "趋势上升 TOP 10" in md
        # 没有 SO 数据时不应有 SO 相关章节
        assert "Stack Overflow 热点变迁" not in md
        assert "分析摘要" in md
        # 没有 emerging 和 so_trends 时不应有摘要内容
        assert "最热新兴技能" not in md
        assert "快速上升" not in md
        assert "持续下降" not in md

    def test_only_so_trends(self):
        """仅包含 SO 趋势数据"""
        from pycoder.server.skills_report import SkillsReportGenerator

        gen = SkillsReportGenerator()

        so_trends = [
            {
                "technology": "TypeScript",
                "adoption_2024": 35.0,
                "adoption_2025": 40.0,
                "growth_rate": 0.143,
                "stage": "growing",
            },
        ]
        so_stats = {"technologies": 1, "rising": 1, "declining": 0}

        md = gen.generate_markdown(
            lifecycle_stats={},
            trending=[],
            emerging=[],
            so_trends=so_trends,
            so_stats=so_stats,
        )

        assert "Stack Overflow 热点变迁" in md
        assert "TypeScript" in md
        assert "35.0%" in md
        assert "40.0%" in md
        assert "+14.3%" in md
        # 有上升趋势，摘要中应有快速上升
        assert "快速上升" in md
        assert "TypeScript" in md

    def test_so_trends_with_declining_only(self):
        """仅包含下降趋势的 SO 数据"""
        from pycoder.server.skills_report import SkillsReportGenerator

        gen = SkillsReportGenerator()

        so_trends = [
            {
                "technology": "jQuery",
                "adoption_2024": 30.0,
                "adoption_2025": 25.0,
                "growth_rate": -0.167,
                "stage": "declining",
            },
        ]
        so_stats = {"technologies": 1, "rising": 0, "declining": 1}

        md = gen.generate_markdown(
            lifecycle_stats={},
            trending=[],
            emerging=[],
            so_trends=so_trends,
            so_stats=so_stats,
        )

        assert "持续下降" in md
        assert "jQuery" in md
        assert "快速上升" not in md  # 没有上升的

    def test_emerging_fallback_name_field(self):
        """emerging 技能使用 name 字段而非 skill_name"""
        from pycoder.server.skills_report import SkillsReportGenerator

        gen = SkillsReportGenerator()

        emerging = [
            {"name": "FallbackSkill", "category": "Tools", "stars_28d": 100, "growth_rate_28d": 0.30},
        ]

        md = gen.generate_markdown(
            lifecycle_stats={},
            trending=[],
            emerging=emerging,
            so_trends=[],
            so_stats={},
        )

        assert "FallbackSkill" in md
        assert "30.0%" in md

    def test_trending_fallback_name_field(self):
        """trending 技能使用 name 字段而非 skill_name"""
        from pycoder.server.skills_report import SkillsReportGenerator

        gen = SkillsReportGenerator()

        trending = [
            {"name": "TrendFallback", "category": "Web", "stars_28d": 200, "momentum": 0.10},
        ]

        md = gen.generate_markdown(
            lifecycle_stats={},
            trending=trending,
            emerging=[],
            so_trends=[],
            so_stats={},
        )

        assert "TrendFallback" in md
        assert "+10.00%" in md

    def test_so_trends_limited_to_15(self):
        """SO 趋势数据只显示前 15 条"""
        from pycoder.server.skills_report import SkillsReportGenerator

        gen = SkillsReportGenerator()

        so_trends = []
        for i in range(20):
            so_trends.append({
                "technology": f"Tech{i}",
                "adoption_2024": 10.0,
                "adoption_2025": 12.0,
                "growth_rate": 0.20,
                "stage": "growing",
            })

        md = gen.generate_markdown(
            lifecycle_stats={},
            trending=[],
            emerging=[],
            so_trends=so_trends,
            so_stats={"technologies": 20, "rising": 20, "declining": 0},
        )

        # 前 15 条应该出现
        assert "Tech0" in md
        assert "Tech14" in md
        # 第 16 条不应该出现
        assert "Tech15" not in md

    def test_emerging_limited_to_10(self):
        """新兴技能只显示前 10 条"""
        from pycoder.server.skills_report import SkillsReportGenerator

        gen = SkillsReportGenerator()

        emerging = []
        for i in range(15):
            emerging.append({
                "skill_name": f"Skill{i}",
                "category": "Cat",
                "stars_28d": 100 * i,
                "growth_rate_28d": 0.10 * i,
            })

        md = gen.generate_markdown(
            lifecycle_stats={},
            trending=[],
            emerging=emerging,
            so_trends=[],
            so_stats={},
        )

        assert "Skill0" in md
        assert "Skill9" in md
        assert "Skill10" not in md

    def test_report_contains_generation_time(self):
        """报告包含生成时间"""
        from pycoder.server.skills_report import SkillsReportGenerator

        gen = SkillsReportGenerator()

        md = gen.generate_markdown({}, [], [], [], {})
        assert "生成时间" in md
        assert "PyCoder 技能市场自动生成" in md


class TestSaveReport:
    """save_report 方法测试"""

    def test_save_report_with_custom_name(self):
        """保存报告，使用自定义文件名"""
        from pycoder.server.skills_report import SkillsReportGenerator

        with tempfile.TemporaryDirectory() as tmpdir:
            gen = SkillsReportGenerator(report_dir=tmpdir)
            content = "# Test Report\n\nHello World"
            path = gen.save_report(content, name="test-report")

            assert path.endswith(".md")
            saved_file = Path(path)
            assert saved_file.exists()
            assert saved_file.read_text(encoding="utf-8") == content

    def test_save_report_without_name(self):
        """保存报告，不提供文件名（使用默认名称）"""
        from pycoder.server.skills_report import SkillsReportGenerator

        with tempfile.TemporaryDirectory() as tmpdir:
            gen = SkillsReportGenerator(report_dir=tmpdir)
            content = "# Auto Report"
            path = gen.save_report(content)

            assert path.endswith(".md")
            saved_file = Path(path)
            assert saved_file.exists()
            assert saved_file.read_text(encoding="utf-8") == content

    def test_save_report_overwrites_existing(self):
        """保存报告时覆盖已存在的文件"""
        from pycoder.server.skills_report import SkillsReportGenerator

        with tempfile.TemporaryDirectory() as tmpdir:
            gen = SkillsReportGenerator(report_dir=tmpdir)

            content1 = "# First Report"
            path1 = gen.save_report(content1, name="overwrite-test")
            assert Path(path1).read_text(encoding="utf-8") == content1

            content2 = "# Second Report"
            path2 = gen.save_report(content2, name="overwrite-test")
            assert path2 == path1
            assert Path(path2).read_text(encoding="utf-8") == content2


class TestGenerateSkillsReport:
    """generate_skills_report 便捷函数测试"""

    def test_generate_skills_report_with_mocks(self):
        """使用 mock 对象测试完整流程"""
        from pycoder.server.skills_report import generate_skills_report

        mock_engine = MagicMock()
        mock_engine.import_so_survey = MagicMock()
        mock_engine.get_lifecycle_by_category = MagicMock(return_value={
            "AI/ML": [{"stage": "emerging", "count": 3}],
        })
        mock_engine.get_so_trends = MagicMock(return_value=[
            {"technology": "Python", "adoption_2024": 45.0, "adoption_2025": 48.0,
             "growth_rate": 0.067, "stage": "growing"},
        ])

        with tempfile.TemporaryDirectory() as tmpdir:
            from pycoder.server.skills_report import SkillsReportGenerator
            mock_gen = SkillsReportGenerator(report_dir=tmpdir)

            result = generate_skills_report(engine=mock_engine, report_generator=mock_gen)

            assert result["success"] is True
            assert "report_path" in result
            assert result["so_technologies"] == 1
            assert "report_size" in result
            assert result["report_size"] > 0

            # 验证文件已保存
            assert Path(result["report_path"]).exists()

            # 验证 engine 方法被调用
            mock_engine.import_so_survey.assert_called_once()
            mock_engine.get_lifecycle_by_category.assert_called_once()
            mock_engine.get_so_trends.assert_called_once()

    def test_generate_skills_report_handles_db_error(self):
        """数据库错误时优雅降级"""
        from pycoder.server.skills_report import generate_skills_report

        mock_engine = MagicMock()
        mock_engine.import_so_survey = MagicMock()
        mock_engine.get_lifecycle_by_category = MagicMock(return_value={})
        mock_engine.get_so_trends = MagicMock(return_value=[])
        # 模拟数据库连接失败
        mock_engine._db_path = "/nonexistent/path.db"

        with tempfile.TemporaryDirectory() as tmpdir:
            from pycoder.server.skills_report import SkillsReportGenerator
            mock_gen = SkillsReportGenerator(report_dir=tmpdir)

            result = generate_skills_report(engine=mock_engine, report_generator=mock_gen)

            assert result["success"] is True
            assert result["emerging_count"] == 0
            assert result["trending_count"] == 0