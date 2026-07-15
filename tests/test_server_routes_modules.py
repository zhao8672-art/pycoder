"""
对 pycoder/server 路由层模块的综合单元测试。

覆盖模块:
  1. chat_bridge.py            — ChatBridge AI 聊天桥接
  2. ws_handler_v2.py           — V2 WebSocket 处理器
  3. routers/git.py             — Git API 路由
  4. routers/skills_api_v2.py   — Skills API v2 路由
  5. routers/skills_marketplace_api.py — 技能市场 API 路由
  6. routers/extensions.py      — 扩展 API 路由
  7. routers/dag_api.py         — DAG API 路由
  8. routers/v2/__init__.py     — V2 路由
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════
# 1. chat_bridge.py 测试
# ═══════════════════════════════════════════════════════════════


class TestChatEvent:
    """ChatEvent 数据类测试"""

    def test_create_default_event(self):
        """创建默认 ChatEvent"""
        from pycoder.server.chat_bridge import ChatEvent

        ev = ChatEvent(event_type="done")
        assert ev.event_type == "done"
        assert ev.content == ""
        assert ev.usage == {}

    def test_create_token_event(self):
        """创建 token 类型事件"""
        from pycoder.server.chat_bridge import ChatEvent

        ev = ChatEvent(event_type="token", content="Hello", usage={"prompt_tokens": 10})
        assert ev.event_type == "token"
        assert ev.content == "Hello"
        assert ev.usage == {"prompt_tokens": 10}

    def test_create_error_event(self):
        """创建 error 类型事件"""
        from pycoder.server.chat_bridge import ChatEvent

        ev = ChatEvent(event_type="error", content="API 请求失败")
        assert ev.event_type == "error"
        assert ev.content == "API 请求失败"

    def test_create_reasoning_event(self):
        """创建 reasoning 类型事件"""
        from pycoder.server.chat_bridge import ChatEvent

        ev = ChatEvent(event_type="reasoning", content="思考中...")
        assert ev.event_type == "reasoning"
        assert ev.content == "思考中..."


class TestBridgeConfig:
    """BridgeConfig 数据类测试"""

    def test_default_config(self):
        """默认配置值检查"""
        from pycoder.server.chat_bridge import BridgeConfig

        cfg = BridgeConfig()
        assert cfg.model == "deepseek-chat"
        assert cfg.api_key == ""
        assert cfg.api_base == "https://api.deepseek.com"
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 8192
        assert cfg.reasoning_effort == "medium"
        assert cfg.enable_thinking is True
        assert cfg.enable_cache is True
        assert cfg.max_history_messages == 20

    def test_custom_config(self):
        """自定义配置值检查"""
        from pycoder.server.chat_bridge import BridgeConfig

        cfg = BridgeConfig(
            model="gpt-4o-mini",
            api_key="sk-123",
            api_base="https://api.openai.com/v1",
            temperature=0.3,
            max_tokens=4096,
            max_history_messages=10,
        )
        assert cfg.model == "gpt-4o-mini"
        assert cfg.api_key == "sk-123"
        assert cfg.max_tokens == 4096
        assert cfg.max_history_messages == 10


class TestDetectProvider:
    """_detect_provider 函数测试"""

    def test_deepseek_model(self):
        """检测 deepseek 模型"""
        from pycoder.server.chat_bridge import _detect_provider

        assert _detect_provider("deepseek-chat") == "deepseek"
        assert _detect_provider("deepseek-reasoner") == "deepseek"

    def test_qwen_model(self):
        """检测 qwen 模型"""
        from pycoder.server.chat_bridge import _detect_provider

        assert _detect_provider("qwen-coder-plus") == "qwen"
        assert _detect_provider("qwen-max") == "qwen"

    def test_glm_model(self):
        """检测 glm 模型"""
        from pycoder.server.chat_bridge import _detect_provider

        assert _detect_provider("glm-4-flash") == "glm"

    def test_openai_model(self):
        """检测 openai 模型"""
        from pycoder.server.chat_bridge import _detect_provider

        assert _detect_provider("gpt-4o") == "openai"
        assert _detect_provider("o1-mini") == "openai"

    def test_nvidia_model(self):
        """检测 nvidia 模型"""
        from pycoder.server.chat_bridge import _detect_provider

        assert _detect_provider("z-llama") == "nvidia"
        assert _detect_provider("nvidia-nemotron") == "nvidia"

    def test_unknown_model_defaults_to_deepseek(self):
        """未知模型默认返回 deepseek"""
        from pycoder.server.chat_bridge import _detect_provider

        assert _detect_provider("unknown-model") == "deepseek"
        assert _detect_provider("") == "deepseek"


class TestProviderApiBases:
    """PROVIDER_API_BASES 常量测试"""

    def test_all_providers_have_bases(self):
        """所有已知 provider 都有 API base"""
        from pycoder.server.chat_bridge import PROVIDER_API_BASES

        assert "deepseek" in PROVIDER_API_BASES
        assert "qwen" in PROVIDER_API_BASES
        assert "glm" in PROVIDER_API_BASES
        assert "openai" in PROVIDER_API_BASES
        assert "nvidia" in PROVIDER_API_BASES

    def test_deepseek_base(self):
        """DeepSeek API base"""
        from pycoder.server.chat_bridge import PROVIDER_API_BASES

        assert PROVIDER_API_BASES["deepseek"] == "https://api.deepseek.com"

    def test_openai_base(self):
        """OpenAI API base"""
        from pycoder.server.chat_bridge import PROVIDER_API_BASES

        assert PROVIDER_API_BASES["openai"] == "https://api.openai.com/v1"


class TestEstimateTokens:
    """estimate_tokens 函数测试"""

    def test_empty_text_returns_zero(self):
        """空文本返回 0"""
        from pycoder.server.chat_bridge import estimate_tokens

        assert estimate_tokens("") == 0

    def test_english_text(self):
        """英文文本估算"""
        from pycoder.server.chat_bridge import estimate_tokens

        tokens = estimate_tokens("Hello World")
        assert tokens > 0
        assert isinstance(tokens, int)

    def test_chinese_text(self):
        """中文文本估算"""
        from pycoder.server.chat_bridge import estimate_tokens

        tokens = estimate_tokens("你好世界")
        assert tokens > 0
        assert isinstance(tokens, int)

    def test_mixed_text(self):
        """中英文混合文本估算"""
        from pycoder.server.chat_bridge import estimate_tokens

        tokens = estimate_tokens("Hello 你好 World")
        assert tokens > 0
        assert isinstance(tokens, int)


class TestModelRouting:
    """MODEL_ROUTING 常量测试"""

    def test_deepseek_routing(self):
        """DeepSeek 路由配置"""
        from pycoder.server.chat_bridge import MODEL_ROUTING

        assert MODEL_ROUTING["deepseek"]["model"] == "deepseek-chat"
        assert MODEL_ROUTING["deepseek"]["provider"] == "deepseek"

    def test_deepseek_reasoner_routing(self):
        """DeepSeek Reasoner 路由配置"""
        from pycoder.server.chat_bridge import MODEL_ROUTING

        assert MODEL_ROUTING["deepseek-reasoner"]["model"] == "deepseek-reasoner"

    def test_qwen_routing(self):
        """Qwen 路由配置"""
        from pycoder.server.chat_bridge import MODEL_ROUTING

        assert MODEL_ROUTING["qwen"]["model"] == "qwen-coder-plus"

    def test_glm_routing(self):
        """GLM 路由配置"""
        from pycoder.server.chat_bridge import MODEL_ROUTING

        assert MODEL_ROUTING["glm"]["model"] == "glm-4-flash"


class TestResolveModelEndpoint:
    """_resolve_model_endpoint 函数测试"""

    def test_known_model_returns_route(self):
        """已知模型返回路由配置"""
        from pycoder.server.chat_bridge import _resolve_model_endpoint

        base, model = _resolve_model_endpoint("deepseek")
        assert base == "https://api.deepseek.com"
        assert model == "deepseek-chat"

    def test_prefix_match(self):
        """前缀匹配"""
        from pycoder.server.chat_bridge import _resolve_model_endpoint

        base, model = _resolve_model_endpoint("deepseek-v3")
        assert base == "https://api.deepseek.com"
        assert model == "deepseek-v3"

    def test_qwen_prefix_match(self):
        """Qwen 前缀匹配"""
        from pycoder.server.chat_bridge import _resolve_model_endpoint

        base, model = _resolve_model_endpoint("qwen-max-2025")
        assert "qwen" in base.lower() or "dashscope" in base.lower()

    def test_unknown_model_falls_back_to_deepseek(self):
        """未知模型回退到 DeepSeek"""
        from pycoder.server.chat_bridge import _resolve_model_endpoint

        base, model = _resolve_model_endpoint("unknown-xyz")
        assert "deepseek" in base.lower()
        assert model == "unknown-xyz"


class TestGetContextAnchor:
    """_get_context_anchor 函数测试"""

    def test_returns_empty_when_no_orchestrator(self):
        """无 orchestrator 时返回空串"""
        from pycoder.server.chat_bridge import _get_context_anchor

        result = _get_context_anchor()
        assert result == ""

    def test_returns_empty_on_import_error(self):
        """导入失败时返回空串（不抛异常）"""
        with patch(
            "pycoder.server.services.context_orchestrator.get_orchestrator",
            side_effect=ImportError,
        ):
            from pycoder.server.chat_bridge import _get_context_anchor

            result = _get_context_anchor()
            assert result == ""


class TestChatBridge:
    """ChatBridge 类测试"""

    def test_init_creates_config_and_messages(self):
        """初始化创建配置和消息列表"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        assert bridge.config is not None
        assert bridge.config.model == "deepseek-chat"
        assert bridge._messages == []

    def test_configure_updates_model(self):
        """configure 更新模型"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        bridge.configure(model="gpt-4o-mini")
        assert bridge.config.model == "gpt-4o-mini"

    def test_configure_updates_api_key(self):
        """configure 更新 API Key"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        bridge.configure(api_key="sk-test")
        assert bridge.config.api_key == "sk-test"

    def test_configure_updates_system_prompt(self):
        """configure 更新系统提示词"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        bridge.configure(system_prompt="你是助手")
        assert bridge.config.system_prompt == "你是助手"

    def test_configure_updates_max_tokens(self):
        """configure 更新最大 token 数"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        bridge.configure(max_tokens=4096)
        assert bridge.config.max_tokens == 4096

    def test_configure_none_params_do_not_change(self):
        """configure 传入 None 不改变原有值"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        original = bridge.config.model
        bridge.configure(model=None)
        assert bridge.config.model == original

    def test_configure_auto_detects_provider(self):
        """configure 自动检测 provider 并设置 api_base"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        bridge.configure(model="qwen-coder-plus")
        assert "dashscope" in bridge.config.api_base or "qwen" in bridge.config.api_base.lower()

    def test_add_message_adds_to_list(self):
        """add_message 添加消息到列表"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        bridge.add_message("user", "Hello")
        assert len(bridge._messages) == 1
        assert bridge._messages[0] == {"role": "user", "content": "Hello"}

    def test_add_multiple_messages(self):
        """多次添加消息"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        bridge.add_message("user", "Q1")
        bridge.add_message("assistant", "A1")
        bridge.add_message("user", "Q2")
        assert len(bridge._messages) == 3

    def test_get_effective_messages_no_truncation(self):
        """消息数未超限时不截断"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        bridge.config.max_history_messages = 10
        for i in range(5):
            bridge.add_message("user", f"msg{i}")
        messages = bridge._get_effective_messages()
        assert len(messages) >= 5

    def test_get_effective_messages_with_truncation(self):
        """消息数超限时截断并压缩"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        bridge.config.max_history_messages = 3
        for i in range(10):
            bridge.add_message("user", f"msg{i}")
        messages = bridge._get_effective_messages()
        # 截断后至少保留最近 3 条
        assert len(messages) <= 6  # 3 保留 + 最多 1 压缩摘要 + 可能 1 上下文锚点

    def test_get_effective_messages_max_zero_means_no_truncation(self):
        """max_history_messages=0 不截断"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        bridge.config.max_history_messages = 0
        for i in range(20):
            bridge.add_message("user", f"msg{i}")
        messages = bridge._get_effective_messages()
        assert len(messages) >= 20

    def test_check_token_budget_returns_int(self):
        """_check_token_budget 返回整数"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        messages = [{"role": "user", "content": "Hello World"}]
        result = bridge._check_token_budget(messages)
        assert isinstance(result, int)
        assert result > 0

    def test_check_token_budget_large_warns(self):
        """超大消息列表触发预警"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        messages = [{"role": "user", "content": "x" * 200000}]
        result = bridge._check_token_budget(messages)
        assert result > 60000

    def test_compress_old_messages_empty_returns_empty(self):
        """空消息列表压缩返回空"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        result = bridge._compress_old_messages([])
        assert result == ""

    def test_enable_agent_mode(self):
        """enable_agent_mode 不抛异常"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        bridge.enable_agent_mode()
        # 不抛异常即通过

    def test_disable_agent_mode(self):
        """disable_agent_mode 不抛异常"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        bridge.disable_agent_mode()
        # 不抛异常即通过

    def test_build_capabilities_block_returns_string(self):
        """_build_capabilities_block 返回字符串"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        result = bridge._build_capabilities_block()
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_close_clears_messages(self):
        """close 清理消息列表"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        bridge.add_message("user", "test")
        await bridge.close()
        assert bridge._messages == []

    @pytest.mark.asyncio
    async def test_chat_returns_string(self):
        """chat 方法返回字符串"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        bridge.config.api_key = "test-key"
        with patch.object(
            ChatBridge, "_get_client", new_callable=AsyncMock
        ) as mock_client:
            mock_client.return_value.post = AsyncMock(
                return_value=MagicMock(
                    status_code=200,
                    json=lambda: {"choices": [{"message": {"content": "response"}}]},
                )
            )
            result = await bridge.chat("Hello")
            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_chat_returns_empty_on_error(self):
        """chat 网络错误时返回空串"""
        from pycoder.server.chat_bridge import ChatBridge

        bridge = ChatBridge()
        bridge.config.api_key = "test-key"
        with patch.object(
            ChatBridge, "_get_client", new_callable=AsyncMock
        ) as mock_client:
            mock_client.return_value.post = AsyncMock(
                side_effect=OSError("Connection failed")
            )
            result = await bridge.chat("Hello")
            assert result == ""


# ═══════════════════════════════════════════════════════════════
# 2. routers/git.py 测试
# ═══════════════════════════════════════════════════════════════


class TestGitPydanticModels:
    """Git 路由 Pydantic 模型测试"""

    def test_remote_branch_request_defaults(self):
        """RemoteBranchRequest 默认值"""
        from pycoder.server.routers.git import RemoteBranchRequest

        req = RemoteBranchRequest()
        assert req.remote == "origin"
        assert req.branch is None

    def test_remote_branch_request_custom(self):
        """RemoteBranchRequest 自定义值"""
        from pycoder.server.routers.git import RemoteBranchRequest

        req = RemoteBranchRequest(remote="upstream", branch="main")
        assert req.remote == "upstream"
        assert req.branch == "main"

    def test_stash_request_defaults(self):
        """StashRequest 默认值"""
        from pycoder.server.routers.git import StashRequest

        req = StashRequest()
        assert req.action == "push"
        assert req.message == "WIP"
        assert req.index == 0

    def test_files_request_defaults(self):
        """FilesRequest 默认值"""
        from pycoder.server.routers.git import FilesRequest

        req = FilesRequest()
        assert req.files == []
        assert req.all is False

    def test_files_request_with_files(self):
        """FilesRequest 带文件列表"""
        from pycoder.server.routers.git import FilesRequest

        req = FilesRequest(files=["a.py", "b.py"])
        assert req.files == ["a.py", "b.py"]

    def test_branch_name_request(self):
        """BranchNameRequest 模型"""
        from pycoder.server.routers.git import BranchNameRequest

        req = BranchNameRequest(name="feature-x", force=True)
        assert req.name == "feature-x"
        assert req.force is True

    def test_merge_request(self):
        """MergeRequest 模型"""
        from pycoder.server.routers.git import MergeRequest

        req = MergeRequest(source_branch="develop")
        assert req.source_branch == "develop"

    def test_commit_hash_request(self):
        """CommitHashRequest 模型"""
        from pycoder.server.routers.git import CommitHashRequest

        req = CommitHashRequest(commit="abc1234")
        assert req.commit == "abc1234"

    def test_rebase_request(self):
        """RebaseRequest 模型"""
        from pycoder.server.routers.git import RebaseRequest

        req = RebaseRequest(branch="main")
        assert req.branch == "main"

    def test_remote_add_request(self):
        """RemoteAddRequest 模型"""
        from pycoder.server.routers.git import RemoteAddRequest

        req = RemoteAddRequest(name="origin", url="https://github.com/user/repo.git")
        assert req.name == "origin"
        assert req.url == "https://github.com/user/repo.git"

    def test_remote_name_request(self):
        """RemoteNameRequest 模型"""
        from pycoder.server.routers.git import RemoteNameRequest

        req = RemoteNameRequest(name="upstream")
        assert req.name == "upstream"

    def test_conflict_resolve_request(self):
        """ConflictResolveRequest 模型"""
        from pycoder.server.routers.git import ConflictResolveRequest

        req = ConflictResolveRequest(file="src/main.py", resolution="ours")
        assert req.file == "src/main.py"
        assert req.resolution == "ours"

    def test_gitignore_request(self):
        """GitignoreRequest 模型"""
        from pycoder.server.routers.git import GitignoreRequest

        req = GitignoreRequest(pattern="*.log")
        assert req.pattern == "*.log"

    def test_git_init_request(self):
        """GitInitRequest 模型"""
        from pycoder.server.routers.git import GitInitRequest

        req = GitInitRequest(path="/tmp/project")
        assert req.path == "/tmp/project"

    def test_fetch_request(self):
        """FetchRequest 模型"""
        from pycoder.server.routers.git import FetchRequest

        req = FetchRequest(remote="origin")
        assert req.remote == "origin"

    def test_commit_request(self):
        """CommitRequest 模型"""
        from pycoder.server.routers.git import CommitRequest

        req = CommitRequest(files=["a.py"], message="feat: new feature", author="Dev")
        assert req.files == ["a.py"]
        assert req.message == "feat: new feature"
        assert req.author == "Dev"

    def test_reset_request(self):
        """ResetRequest 模型"""
        from pycoder.server.routers.git import ResetRequest

        req = ResetRequest(mode="hard", commit="HEAD~2")
        assert req.mode == "hard"
        assert req.commit == "HEAD~2"


class TestGitRouter:
    """Git 路由端点测试"""

    def test_router_exists(self):
        """路由对象存在"""
        from pycoder.server.routers.git import router

        assert router is not None

    def test_router_prefix(self):
        """路由前缀正确"""
        from pycoder.server.routers.git import router

        assert router.prefix == "/api/git"


# ═══════════════════════════════════════════════════════════════
# 3. routers/skills_api_v2.py 测试
# ═══════════════════════════════════════════════════════════════


class TestSkillsApiV2PydanticModels:
    """Skills API v2 Pydantic 模型测试"""

    def test_skill_search_request_defaults(self):
        """SkillSearchRequest 默认值"""
        from pycoder.server.routers.skills_api_v2 import SkillSearchRequest

        req = SkillSearchRequest()
        assert req.query == ""
        assert req.category == ""
        assert req.tags == []
        assert req.sort_by == "quality"
        assert req.limit == 20
        assert req.offset == 0

    def test_skill_search_request_custom(self):
        """SkillSearchRequest 自定义值"""
        from pycoder.server.routers.skills_api_v2 import SkillSearchRequest

        req = SkillSearchRequest(
            query="test", category="code", tags=["unit"], sort_by="stars", limit=10, offset=5
        )
        assert req.query == "test"
        assert req.category == "code"
        assert req.tags == ["unit"]
        assert req.sort_by == "stars"
        assert req.limit == 10
        assert req.offset == 5

    def test_skill_rate_request(self):
        """SkillRateRequest 模型"""
        from pycoder.server.routers.skills_api_v2 import SkillRateRequest

        req = SkillRateRequest(rating=4, review="Good!")
        assert req.rating == 4
        assert req.review == "Good!"

    def test_skill_rate_request_rating_range(self):
        """SkillRateRequest rating 范围 1-5"""
        from pycoder.server.routers.skills_api_v2 import SkillRateRequest

        # ge=1, le=5
        req = SkillRateRequest(rating=1)
        assert req.rating == 1
        req = SkillRateRequest(rating=5)
        assert req.rating == 5

    def test_skill_search_response(self):
        """SkillSearchResponse 模型"""
        from pycoder.server.routers.skills_api_v2 import SkillSearchResponse

        resp = SkillSearchResponse(
            success=True, query="test", total=10, results=[], sort_by="quality", offset=0, limit=20
        )
        assert resp.success is True
        assert resp.total == 10

    def test_skill_detail_response(self):
        """SkillDetailResponse 模型"""
        from pycoder.server.routers.skills_api_v2 import SkillDetailResponse

        resp = SkillDetailResponse(success=True, skill={"id": "test"})
        assert resp.success is True
        assert resp.skill == {"id": "test"}

    def test_skill_rate_response(self):
        """SkillRateResponse 模型"""
        from pycoder.server.routers.skills_api_v2 import SkillRateResponse

        resp = SkillRateResponse(
            success=True, skill_id="test", rating=5, review="Great", message="OK"
        )
        assert resp.success is True
        assert resp.skill_id == "test"

    def test_skill_stats_response(self):
        """SkillStatsResponse 模型"""
        from pycoder.server.routers.skills_api_v2 import SkillStatsResponse

        resp = SkillStatsResponse(success=True, stats={"total": 100})
        assert resp.success is True
        assert resp.stats == {"total": 100}


class TestSkillsApiV2Router:
    """Skills API v2 路由测试"""

    def test_router_exists(self):
        """路由对象存在"""
        from pycoder.server.routers.skills_api_v2 import router

        assert router is not None

    def test_router_prefix(self):
        """路由前缀正确"""
        from pycoder.server.routers.skills_api_v2 import router

        assert router.prefix == "/api/skills/v2"


# ═══════════════════════════════════════════════════════════════
# 4. routers/skills_marketplace_api.py 测试
# ═══════════════════════════════════════════════════════════════


class TestSkillsMarketplaceApiModels:
    """Skills Marketplace API Pydantic 模型测试"""

    def test_skill_install_request(self):
        """SkillInstallRequest 模型"""
        from pycoder.server.routers.skills_marketplace_api import SkillInstallRequest

        req = SkillInstallRequest(skill_id="code-review")
        assert req.skill_id == "code-review"

    def test_skill_rate_request(self):
        """SkillRateRequest 模型"""
        from pycoder.server.routers.skills_marketplace_api import SkillRateRequest

        req = SkillRateRequest(skill_id="test", rating=4)
        assert req.skill_id == "test"
        assert req.rating == 4

    def test_skill_list_response(self):
        """SkillListResponse 模型"""
        from pycoder.server.routers.skills_marketplace_api import SkillListResponse

        resp = SkillListResponse(success=True, skills=[], total=0)
        assert resp.success is True
        assert resp.total == 0

    def test_skill_search_response(self):
        """SkillSearchResponse 模型"""
        from pycoder.server.routers.skills_marketplace_api import SkillSearchResponse

        resp = SkillSearchResponse(success=True, query="test", skills=[], total=0)
        assert resp.success is True
        assert resp.query == "test"

    def test_skill_action_response(self):
        """SkillActionResponse 模型"""
        from pycoder.server.routers.skills_marketplace_api import SkillActionResponse

        resp = SkillActionResponse(success=True, skill_id="test", action="install", message="OK")
        assert resp.success is True
        assert resp.action == "install"

    def test_skill_install_result_response(self):
        """SkillInstallResultResponse 模型"""
        from pycoder.server.routers.skills_marketplace_api import SkillInstallResultResponse

        resp = SkillInstallResultResponse(
            success=True, skill_id="test", name="Test Skill", installed_at="2024-01-01", action="install"
        )
        assert resp.success is True
        assert resp.name == "Test Skill"

    def test_skill_stats_response(self):
        """SkillStatsResponse 模型"""
        from pycoder.server.routers.skills_marketplace_api import SkillStatsResponse

        resp = SkillStatsResponse(success=True, stats={"total": 50})
        assert resp.success is True


class TestSkillsMarketplaceRouter:
    """Skills Marketplace 路由测试"""

    def test_router_exists(self):
        """路由对象存在"""
        from pycoder.server.routers.skills_marketplace_api import router

        assert router is not None

    def test_router_prefix(self):
        """路由前缀正确"""
        from pycoder.server.routers.skills_marketplace_api import router

        assert router.prefix == "/api/skills"


# ═══════════════════════════════════════════════════════════════
# 5. routers/extensions.py 测试
# ═══════════════════════════════════════════════════════════════


class TestExtensionsRouter:
    """Extensions 路由测试"""

    def test_router_exists(self):
        """路由对象存在"""
        from pycoder.server.routers.extensions import router

        assert router is not None

    def test_router_prefix(self):
        """路由前缀正确"""
        from pycoder.server.routers.extensions import router

        assert router.prefix == "/api/extensions"


# ═══════════════════════════════════════════════════════════════
# 6. routers/dag_api.py 测试
# ═══════════════════════════════════════════════════════════════


class TestDAGApiPydanticModels:
    """DAG API Pydantic 模型测试"""

    def test_create_dag_request(self):
        """CreateDAGRequest 模型"""
        from pycoder.server.routers.dag_api import CreateDAGRequest

        req = CreateDAGRequest(name="test-dag", description="测试 DAG")
        assert req.name == "test-dag"
        assert req.description == "测试 DAG"

    def test_create_dag_response(self):
        """CreateDAGResponse 模型"""
        from pycoder.server.routers.dag_api import CreateDAGResponse

        resp = CreateDAGResponse(dag_id="abc123", name="test-dag", description="desc")
        assert resp.dag_id == "abc123"
        assert resp.name == "test-dag"

    def test_add_node_request(self):
        """AddNodeRequest 模型"""
        from pycoder.server.routers.dag_api import AddNodeRequest

        req = AddNodeRequest(
            name="node1",
            description="node desc",
            dependencies=["dep1"],
            priority=1,
            estimated_duration=5.0,
            timeout=30.0,
            max_retries=3,
            metadata={"key": "value"},
        )
        assert req.name == "node1"
        assert req.dependencies == ["dep1"]
        assert req.priority == 1
        assert req.estimated_duration == 5.0
        assert req.timeout == 30.0
        assert req.max_retries == 3
        assert req.metadata == {"key": "value"}

    def test_add_node_response(self):
        """AddNodeResponse 模型"""
        from pycoder.server.routers.dag_api import AddNodeResponse

        resp = AddNodeResponse(
            node_id="n1", dag_id="d1", name="node1", dependencies=["dep1"]
        )
        assert resp.node_id == "n1"
        assert resp.dag_id == "d1"

    def test_execute_dag_response(self):
        """ExecuteDAGResponse 模型"""
        from pycoder.server.routers.dag_api import ExecuteDAGResponse

        resp = ExecuteDAGResponse(
            dag_id="d1",
            success=True,
            total_nodes=5,
            completed=5,
            failed=0,
            duration_seconds=10.0,
            results={"n1": "ok"},
        )
        assert resp.success is True
        assert resp.total_nodes == 5
        assert resp.completed == 5

    def test_dag_status_response(self):
        """DAGStatusResponse 模型"""
        from pycoder.server.routers.dag_api import DAGStatusResponse

        resp = DAGStatusResponse(
            dag_id="d1",
            name="test",
            total=10,
            pending=5,
            running=2,
            done=3,
            failed=0,
            skipped=0,
            progress_pct=30.0,
            elapsed=5.0,
            estimated_remaining=10.0,
            nodes=[],
        )
        assert resp.dag_id == "d1"
        assert resp.total == 10
        assert resp.progress_pct == 30.0

    def test_visualize_response(self):
        """VisualizeResponse 模型"""
        from pycoder.server.routers.dag_api import VisualizeResponse

        resp = VisualizeResponse(dag_id="d1", visualization="A -> B -> C")
        assert resp.dag_id == "d1"
        assert resp.visualization == "A -> B -> C"


class TestDAGApiRouter:
    """DAG API 路由测试"""

    def test_router_exists(self):
        """路由对象存在"""
        from pycoder.server.routers.dag_api import router

        assert router is not None

    def test_router_prefix(self):
        """路由前缀正确"""
        from pycoder.server.routers.dag_api import router

        assert router.prefix == "/api/dag"

    def test_get_dag_raises_404_for_unknown(self):
        """_get_dag 对未知 DAG 抛出 404"""
        from pycoder.server.routers.dag_api import _get_dag

        with pytest.raises(Exception) as exc_info:
            _get_dag("nonexistent-dag-id")
        assert exc_info.value.status_code == 404


# ═══════════════════════════════════════════════════════════════
# 7. routers/v2/__init__.py 测试
# ═══════════════════════════════════════════════════════════════


class TestV2RouterModels:
    """V2 路由 Pydantic 模型测试"""

    def test_scan_request_defaults(self):
        """ScanRequest 默认值"""
        from pycoder.server.routers.v2 import ScanRequest

        req = ScanRequest()
        assert req.path == "pycoder"
        assert req.use_llm is True

    def test_scan_request_custom(self):
        """ScanRequest 自定义值"""
        from pycoder.server.routers.v2 import ScanRequest

        req = ScanRequest(path="src", use_llm=False)
        assert req.path == "src"
        assert req.use_llm is False

    def test_fix_request(self):
        """FixRequest 模型"""
        from pycoder.server.routers.v2 import FixRequest

        req = FixRequest(
            file="test.py",
            line=10,
            severity="high",
            issue_type="bug",
            title="Null pointer",
            description="Detailed desc",
            suggestion="Add null check",
        )
        assert req.file == "test.py"
        assert req.line == 10
        assert req.severity == "high"
        assert req.issue_type == "bug"
        assert req.title == "Null pointer"

    def test_apply_request(self):
        """ApplyRequest 模型"""
        from pycoder.server.routers.v2 import ApplyRequest

        req = ApplyRequest(issue_index=0, confirm=True)
        assert req.issue_index == 0
        assert req.confirm is True

    def test_escalate_request(self):
        """EscalateRequest 模型"""
        from pycoder.server.routers.v2 import EscalateRequest

        req = EscalateRequest(reason="需要写入文件")
        assert req.reason == "需要写入文件"


class TestV2Router:
    """V2 路由测试"""

    def test_router_exists(self):
        """路由对象存在"""
        from pycoder.server.routers.v2 import router

        assert router is not None

    def test_router_prefix(self):
        """路由前缀正确"""
        from pycoder.server.routers.v2 import router

        assert router.prefix == "/api/v2"

    def test_count_severity_empty(self):
        """_count_severity 空列表返回空字典"""
        from pycoder.server.routers.v2 import _count_severity

        result = _count_severity([])
        assert result == {}

    def test_count_severity_with_issues(self):
        """_count_severity 统计各严重度"""
        from collections import namedtuple

        from pycoder.server.routers.v2 import _count_severity

        Issue = namedtuple("Issue", ["severity"])
        issues = [
            Issue(severity="high"),
            Issue(severity="high"),
            Issue(severity="low"),
            Issue(severity="medium"),
        ]
        result = _count_severity(issues)
        assert result["high"] == 2
        assert result["low"] == 1
        assert result["medium"] == 1


# ═══════════════════════════════════════════════════════════════
# 8. ws_handler_v2.py 测试
# ═══════════════════════════════════════════════════════════════


class TestWsHandlerV2:
    """V2 WebSocket 处理器测试"""

    @pytest.mark.asyncio
    async def test_handle_mcp_v2_list(self):
        """_handle_mcp_v2 处理 mcp_list"""
        from unittest.mock import AsyncMock, MagicMock

        from pycoder.server.ws_handler_v2 import _handle_mcp_v2

        ws = AsyncMock()
        v2 = MagicMock()
        v2.registry.count = 5

        with patch("pycoder.server.mcp_tools.list_builtin_tools", return_value=[]):
            with patch(
                "pycoder.server.mcp_tools.get_mcp_client_manager",
                return_value=MagicMock(connected_servers=[], list_remote_tools=AsyncMock(return_value=[])),
            ):
                await _handle_mcp_v2("mcp_list", {}, ws, v2)
                ws.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_mcp_v2_call_no_tool(self):
        """_handle_mcp_v2 mcp_call 无工具名返回错误"""
        from unittest.mock import AsyncMock, MagicMock

        from pycoder.server.ws_handler_v2 import _handle_mcp_v2

        ws = AsyncMock()
        v2 = MagicMock()
        await _handle_mcp_v2("mcp_call", {"tool": "", "args": {}}, ws, v2)
        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "error"

    @pytest.mark.asyncio
    async def test_handle_mcp_v2_connect_no_name(self):
        """_handle_mcp_v2 mcp_connect 无名称返回错误"""
        from unittest.mock import AsyncMock, MagicMock

        from pycoder.server.ws_handler_v2 import _handle_mcp_v2

        ws = AsyncMock()
        v2 = MagicMock()
        await _handle_mcp_v2("mcp_connect", {"name": "", "command": ""}, ws, v2)
        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "error"

    @pytest.mark.asyncio
    async def test_handle_mcp_v2_disconnect_no_name(self):
        """_handle_mcp_v2 mcp_disconnect 无名称返回错误"""
        from unittest.mock import AsyncMock, MagicMock

        from pycoder.server.ws_handler_v2 import _handle_mcp_v2

        ws = AsyncMock()
        v2 = MagicMock()
        await _handle_mcp_v2("mcp_disconnect", {"name": ""}, ws, v2)
        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "error"

    @pytest.mark.asyncio
    async def test_handle_inline_edit_no_code(self):
        """_handle_inline_edit 无代码返回错误"""
        from unittest.mock import AsyncMock

        from pycoder.server.ws_handler_v2 import _handle_inline_edit

        ws = AsyncMock()
        await _handle_inline_edit({"code": "", "instruction": ""}, ws)
        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "error"