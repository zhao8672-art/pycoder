"""UnifiedEntryAgent 统一入口调度测试

覆盖:
  - TaskCategory 枚举
  - ParsedIntent / ModeResult / UnifiedResult 数据类
  - _classify_intent: 意图分类（规则 + 启发式）
  - UnifiedEntryAgent: 初始化与工厂函数
  - UnifiedEntryAgent._parse_intent: 意图解析
  - UnifiedEntryAgent._detect_ambiguity: 歧义检测
  - UnifiedEntryAgent._route_to_modes: 模式路由
  - UnifiedEntryAgent._merge_results: 结果归集
  - UnifiedEntryAgent._strip_internal_markers: 内部标记清洗
  - UnifiedEntryAgent._check_system_health: 系统健康检查
  - UnifiedEntryAgent.process: 完整处理流程（异步）
  - UnifiedEntryAgent.process_stream: 流式处理（异步）
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.server.services.unified_entry import (
    ModeResult,
    ParsedIntent,
    TaskCategory,
    UnifiedEntryAgent,
    UnifiedResult,
    _classify_intent,
    create_unified_entry,
)


# ══════════════════════════════════════════════════════════
# TaskCategory 枚举测试
# ══════════════════════════════════════════════════════════


class TestTaskCategory:
    """任务分类枚举"""

    def test_chat_value(self) -> None:
        """CHAT 枚举值"""
        assert TaskCategory.CHAT.value == "chat"

    def test_hermes_value(self) -> None:
        """HERMES 枚举值"""
        assert TaskCategory.HERMES.value == "hermes"

    def test_agent_value(self) -> None:
        """AGENT 枚举值"""
        assert TaskCategory.AGENT.value == "agent"


# ══════════════════════════════════════════════════════════
# 数据类测试
# ══════════════════════════════════════════════════════════


class TestParsedIntent:
    """意图解析结果数据类"""

    def test_default_values(self) -> None:
        """默认值"""
        intent = ParsedIntent(raw_input="测试", surface_text="测试", core_need="问答")
        assert intent.raw_input == "测试"
        assert intent.surface_text == "测试"
        assert intent.core_need == "问答"
        assert intent.ambiguity == ""
        assert intent.task_category == TaskCategory.CHAT
        assert intent.beautified_command == ""
        assert intent.sub_intents == []
        assert intent.has_risk is False
        assert intent.risk_description == ""

    def test_full_values(self) -> None:
        """完整赋值"""
        intent = ParsedIntent(
            raw_input="完整输入",
            surface_text="表层",
            core_need="核心需求",
            ambiguity="歧义说明",
            task_category=TaskCategory.AGENT,
            beautified_command="美化后",
            has_risk=True,
            risk_description="高风险",
        )
        assert intent.task_category == TaskCategory.AGENT
        assert intent.has_risk is True
        assert intent.risk_description == "高风险"


class TestModeResult:
    """单模式执行结果数据类"""

    def test_success_result(self) -> None:
        """成功结果"""
        result = ModeResult(
            mode=TaskCategory.CHAT,
            success=True,
            content="回复内容",
            duration_ms=1500,
            retries=0,
        )
        assert result.mode == TaskCategory.CHAT
        assert result.success is True
        assert result.content == "回复内容"
        assert result.error == ""
        assert result.duration_ms == 1500
        assert result.retries == 0

    def test_failure_result(self) -> None:
        """失败结果"""
        result = ModeResult(
            mode=TaskCategory.HERMES,
            success=False,
            error="连接超时",
            duration_ms=5000,
            retries=2,
        )
        assert result.success is False
        assert result.error == "连接超时"
        assert result.retries == 2


class TestUnifiedResult:
    """统一入口最终结果数据类"""

    def test_basic_result(self) -> None:
        """基本结果"""
        intent = ParsedIntent(raw_input="你好", surface_text="你好", core_need="闲聊")
        result = UnifiedResult(
            original_input="你好",
            intent=intent,
            dispatched_modes=["chat"],
            mode_results=[],
            merged_output="你好！",
            system_issues=[],
            risk_warnings=[],
        )
        assert result.original_input == "你好"
        assert result.dispatched_modes == ["chat"]
        assert result.merged_output == "你好！"

    def test_result_with_issues(self) -> None:
        """带系统问题和风险告警的结果"""
        intent = ParsedIntent(raw_input="测试", surface_text="测试", core_need="测试")
        result = UnifiedResult(
            original_input="测试",
            intent=intent,
            dispatched_modes=["agent"],
            mode_results=[],
            merged_output="结果",
            system_issues=["超时问题"],
            risk_warnings=["高风险操作"],
        )
        assert len(result.system_issues) == 1
        assert len(result.risk_warnings) == 1


# ══════════════════════════════════════════════════════════
# _classify_intent 意图分类测试
# ══════════════════════════════════════════════════════════


class TestClassifyIntent:
    """意图分类规则测试"""

    def test_short_message_defaults_to_chat(self) -> None:
        """短消息（<8 字符）默认 CHAT"""
        category, reason = _classify_intent("你好")
        assert category == TaskCategory.CHAT
        assert reason == "短消息，判断为简单问答"

    def test_chat_question(self) -> None:
        """知识问答类 → CHAT"""
        category, reason = _classify_intent("什么是 FastAPI？请解释一下")
        assert category == TaskCategory.CHAT
        assert "纯知识问答" in reason

    def test_chat_suggestion(self) -> None:
        """咨询建议类 → CHAT"""
        category, reason = _classify_intent("你觉得用 React 还是 Vue 比较好？")
        assert category == TaskCategory.CHAT

    def test_hermes_modify(self) -> None:
        """代码修改操作 → HERMES"""
        category, reason = _classify_intent("修改 main.py 文件中的登录逻辑")
        assert category == TaskCategory.HERMES
        assert "代码/文件修改" in reason

    def test_hermes_install(self) -> None:
        """工具安装操作 → HERMES"""
        category, reason = _classify_intent("安装 pytest 测试框架")
        assert category == TaskCategory.HERMES
        assert "工具/环境操作" in reason

    def test_hermes_check(self) -> None:
        """检查诊断操作 → HERMES"""
        category, reason = _classify_intent("检查 src/utils.py 中的潜在 bug 并审查代码质量")
        assert category == TaskCategory.HERMES

    def test_hermes_file_path(self) -> None:
        """包含文件路径的默认消息 → HERMES"""
        category, reason = _classify_intent("帮忙看看 src/main.py 和 config.json 的关系")
        assert category == TaskCategory.HERMES

    def test_agent_develop(self) -> None:
        """系统开发任务 → AGENT"""
        category, reason = _classify_intent("开发一个用户管理系统，包含注册登录权限管理")
        assert category == TaskCategory.AGENT
        assert "多角色协作" in reason

    def test_agent_architecture(self) -> None:
        """架构设计 → AGENT"""
        category, reason = _classify_intent("请设计整个项目的架构，规划微服务拆分方案")
        assert category == TaskCategory.AGENT

    def test_agent_multi_step(self) -> None:
        """多步骤任务 → AGENT"""
        category, reason = _classify_intent("先检查代码规范，再修复所有类型错误，然后运行测试覆盖")
        assert category == TaskCategory.AGENT

    def test_classify_long_with_many_verbs(self) -> None:
        """长消息 + 多动词 → AGENT"""
        long_action_msg = (
            "请检查项目中的所有 Python 文件代码，分析代码质量结构语句，"
            "修改不符合规范的代码写法，优化性能瓶颈问题解决，"
            "测试核心功能模块，部署到生产环境服务器，"
            "还需要审查安全漏洞，重构数据库访问层，"
            "增加单元测试覆盖，确保所有模块通过 CI/CD 流水线验证，"
            "最后还要诊断内存泄漏问题并修复所有已知缺陷和 Bug"
        )
        category, reason = _classify_intent(long_action_msg)
        assert category == TaskCategory.AGENT

    def test_long_message_defaults_to_hermes(self) -> None:
        """长消息（>100 字符）但无特殊模式 → HERMES"""
        long_msg = (
            "请帮我写一个详细的文档，说明这个项目的使用方法，"
            "包括安装步骤、配置说明、API 接口文档和常见问题解答"
        )
        category, reason = _classify_intent(long_msg)
        assert category == TaskCategory.HERMES


# ══════════════════════════════════════════════════════════
# UnifiedEntryAgent 核心测试
# ══════════════════════════════════════════════════════════


class TestUnifiedEntryAgentInit:
    """初始化与工厂函数"""

    def test_default_init(self) -> None:
        """默认初始化"""
        agent = UnifiedEntryAgent()
        assert agent.model == "deepseek-chat"
        assert agent.api_key == ""

    def test_custom_init(self) -> None:
        """自定义模型和 API Key"""
        agent = UnifiedEntryAgent(model="gpt-4", api_key="sk-custom")
        assert agent.model == "gpt-4"
        assert agent.api_key == "sk-custom"

    def test_mode_status_default(self) -> None:
        """默认所有模式状态为可用"""
        agent = UnifiedEntryAgent()
        assert agent._mode_status == {
            "chat": True,
            "hermes": True,
            "agent": True,
        }

    def test_factory_function(self) -> None:
        """工厂函数创建 Agent"""
        agent = create_unified_entry(model="gpt-4", api_key="sk-test")
        assert isinstance(agent, UnifiedEntryAgent)
        assert agent.model == "gpt-4"
        assert agent.api_key == "sk-test"


class TestParseIntent:
    """意图解析"""

    def test_parse_chat_intent(self) -> None:
        """解析闲聊意图"""
        agent = UnifiedEntryAgent()
        intent = agent._parse_intent("什么是 Python 装饰器？")
        assert intent.task_category == TaskCategory.CHAT
        assert intent.surface_text == "什么是 Python 装饰器？"
        assert "纯知识问答" in intent.core_need

    def test_parse_hermes_intent(self) -> None:
        """解析工具操作意图"""
        agent = UnifiedEntryAgent()
        intent = agent._parse_intent("修改 main.py 添加异常处理")
        assert intent.task_category == TaskCategory.HERMES

    def test_parse_agent_intent(self) -> None:
        """解析系统工程意图"""
        agent = UnifiedEntryAgent()
        intent = agent._parse_intent("开发一个完整的内容管理系统，支持用户、文章、评论")
        assert intent.task_category == TaskCategory.AGENT


class TestDetectAmbiguity:
    """歧义检测"""

    def test_no_ambiguity(self) -> None:
        """无歧义的清晰消息"""
        agent = UnifiedEntryAgent()
        result = agent._detect_ambiguity("修复 src/utils.py 中的类型错误")
        assert result == ""

    def test_vague_pronoun(self) -> None:
        """模糊代词检测"""
        agent = UnifiedEntryAgent()
        result = agent._detect_ambiguity("修改这个文件中的那个函数")
        assert "模糊代词" in result

    def test_modify_without_file(self) -> None:
        """修改操作但未指定文件"""
        agent = UnifiedEntryAgent()
        result = agent._detect_ambiguity("修改登录逻辑")
        assert "未指定具体文件" in result

    def test_develop_without_tech_stack(self) -> None:
        """开发操作但未指定技术栈"""
        agent = UnifiedEntryAgent()
        result = agent._detect_ambiguity("创建一个用户管理项目")
        assert "未指定技术栈" in result

    def test_too_short(self) -> None:
        """输入过短"""
        agent = UnifiedEntryAgent()
        result = agent._detect_ambiguity("修")
        assert "输入过短" in result

    def test_multiple_ambiguities(self) -> None:
        """多个歧义同时存在"""
        agent = UnifiedEntryAgent()
        result = agent._detect_ambiguity("修改那个")
        assert "模糊代词" in result
        assert "未指定具体文件" in result
        assert "输入过短" in result


class TestRouteToModes:
    """模式路由"""

    def test_route_chat(self) -> None:
        """CHAT 意图路由到 CHAT 模式"""
        agent = UnifiedEntryAgent()
        intent = ParsedIntent(
            raw_input="你好", surface_text="你好", core_need="闲聊",
            task_category=TaskCategory.CHAT,
        )
        tasks = agent._route_to_modes(intent)
        assert len(tasks) == 1
        assert tasks[0]["mode"] == TaskCategory.CHAT

    def test_route_hermes(self) -> None:
        """HERMES 意图路由到 Hermes 模式"""
        agent = UnifiedEntryAgent()
        intent = ParsedIntent(
            raw_input="修改文件", surface_text="修改文件", core_need="操作",
            task_category=TaskCategory.HERMES,
        )
        tasks = agent._route_to_modes(intent)
        assert len(tasks) == 1
        assert tasks[0]["mode"] == TaskCategory.HERMES

    def test_route_agent(self) -> None:
        """AGENT 意图路由到 Agent 模式"""
        agent = UnifiedEntryAgent()
        intent = ParsedIntent(
            raw_input="开发系统", surface_text="开发系统", core_need="开发",
            task_category=TaskCategory.AGENT,
        )
        tasks = agent._route_to_modes(intent)
        assert len(tasks) == 1
        assert tasks[0]["mode"] == TaskCategory.AGENT


class TestMergeResults:
    """结果归集"""

    def test_merge_successful_chat(self) -> None:
        """归集成功的 CHAT 结果"""
        agent = UnifiedEntryAgent()
        intent = ParsedIntent(
            raw_input="你好", surface_text="你好", core_need="闲聊",
            task_category=TaskCategory.CHAT,
        )
        results = [
            ModeResult(
                mode=TaskCategory.CHAT,
                success=True,
                content="你好！有什么可以帮你的？",
                duration_ms=500,
            )
        ]
        merged = agent._merge_results(intent, results)
        assert "你好！有什么可以帮你的？" in merged
        assert "chat" in merged

    def test_merge_all_failed(self) -> None:
        """所有模式失败时返回故障提示"""
        agent = UnifiedEntryAgent()
        intent = ParsedIntent(
            raw_input="测试", surface_text="测试", core_need="测试",
            task_category=TaskCategory.HERMES,
        )
        results = [
            ModeResult(
                mode=TaskCategory.HERMES,
                success=False,
                error="连接失败",
                duration_ms=3000,
                retries=2,
            )
        ]
        merged = agent._merge_results(intent, results)
        assert "所有模式执行失败" in merged

    def test_merge_strips_internal_markers(self) -> None:
        """归集时去除内部标记（标记块内容被移除）"""
        agent = UnifiedEntryAgent()
        intent = ParsedIntent(
            raw_input="测试", surface_text="测试", core_need="测试",
            task_category=TaskCategory.CHAT,
        )
        results = [
            ModeResult(
                mode=TaskCategory.CHAT,
                success=True,
                content="【原始用户输入】测试内容\n\n实际回复内容",
                duration_ms=500,
            )
        ]
        merged = agent._merge_results(intent, results)
        # 内部标记被移除
        assert "【原始用户输入】" not in merged
        # 页脚保留
        assert "chat" in merged


class TestStripInternalMarkers:
    """内部标记清洗"""

    def test_clean_content_no_markers(self) -> None:
        """无标记的内容原样返回"""
        result = UnifiedEntryAgent._strip_internal_markers("这是干净的回复内容")
        assert result == "这是干净的回复内容"

    def test_strip_chinese_markers(self) -> None:
        """去除中文【】标记（标记块被完全移除）"""
        text = "【原始用户输入】用户消息\n\n【分层意图解析】意图分析\n\n实际回复"
        result = UnifiedEntryAgent._strip_internal_markers(text)
        assert "【原始用户输入】" not in result
        assert "【分层意图解析】" not in result
        # 标记后的内容（直到下一个标记或结尾）被一并移除，结果为空
        assert result == ""

    def test_strip_english_markers(self) -> None:
        """去除英文[]标记（标记块被完全移除）"""
        text = "[原始用户输入] 用户消息\n\n实际回复"
        result = UnifiedEntryAgent._strip_internal_markers(text)
        assert "[原始用户输入]" not in result
        # 标记后的内容到结尾被一并移除，结果为空
        assert result == ""

    def test_strip_chinese_markers_with_content_between(self) -> None:
        """标记块之间的非标记内容保留"""
        text = "前置内容【原始用户输入】用户消息【完】后续内容"
        result = UnifiedEntryAgent._strip_internal_markers(text)
        assert "前置内容" in result
        assert "【原始用户输入】" not in result
        assert "后续内容" in result

    def test_strip_multiple_blank_lines(self) -> None:
        """清理多余空行"""
        text = "内容A\n\n\n\n内容B"
        result = UnifiedEntryAgent._strip_internal_markers(text)
        # 多余空行被合并为最多两个换行
        assert "\n\n\n\n" not in result


class TestCheckSystemHealth:
    """系统健康检查"""

    def test_all_success_no_issues(self) -> None:
        """全部成功时无问题"""
        agent = UnifiedEntryAgent()
        results = [
            ModeResult(
                mode=TaskCategory.CHAT,
                success=True,
                content="OK",
                duration_ms=500,
            )
        ]
        issues = agent._check_system_health(results)
        assert issues == []

    def test_failure_detected(self) -> None:
        """检测到失败模式"""
        agent = UnifiedEntryAgent()
        results = [
            ModeResult(
                mode=TaskCategory.HERMES,
                success=False,
                error="网络超时",
                duration_ms=10000,
                retries=2,
            )
        ]
        issues = agent._check_system_health(results)
        assert len(issues) == 1
        assert "hermes" in issues[0]
        assert "网络超时" in issues[0]
        assert "重试" in issues[0]

    def test_timeout_detected(self) -> None:
        """检测到超时"""
        agent = UnifiedEntryAgent()
        results = [
            ModeResult(
                mode=TaskCategory.AGENT,
                success=True,
                content="完成",
                duration_ms=150000,  # 超过 120s
            )
        ]
        issues = agent._check_system_health(results)
        assert len(issues) == 1
        assert "超时" in issues[0]


# ══════════════════════════════════════════════════════════
# 异步处理测试
# ══════════════════════════════════════════════════════════


class TestProcessAsync:
    """异步处理流程"""

    @pytest.mark.asyncio
    async def test_process_chat_message(self) -> None:
        """处理简单 CHAT 消息"""
        agent = UnifiedEntryAgent(model="test-model", api_key="sk-test")

        with patch.object(
            agent, "_execute_modes",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = [
                ModeResult(
                    mode=TaskCategory.CHAT,
                    success=True,
                    content="你好！这是回复",
                    duration_ms=300,
                )
            ]
            result = await agent.process("你好")
            assert isinstance(result, UnifiedResult)
            assert result.original_input == "你好"
            assert result.intent.task_category == TaskCategory.CHAT
            assert "chat" in result.dispatched_modes
            assert len(result.mode_results) == 1
            assert result.mode_results[0].success is True

    @pytest.mark.asyncio
    async def test_process_hermes_message(self) -> None:
        """处理 HERMES 消息"""
        agent = UnifiedEntryAgent()

        with patch.object(
            agent, "_execute_modes",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = [
                ModeResult(
                    mode=TaskCategory.HERMES,
                    success=True,
                    content="已修改 main.py",
                    duration_ms=1200,
                )
            ]
            result = await agent.process("修改 main.py 文件中的错误处理")
            assert result.intent.task_category == TaskCategory.HERMES
            assert "hermes" in result.dispatched_modes

    @pytest.mark.asyncio
    async def test_process_agent_message(self) -> None:
        """处理 AGENT 消息"""
        agent = UnifiedEntryAgent()

        with patch.object(
            agent, "_execute_modes",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = [
                ModeResult(
                    mode=TaskCategory.AGENT,
                    success=True,
                    content="系统开发完成",
                    duration_ms=5000,
                )
            ]
            result = await agent.process("开发一个完整的用户管理系统，支持注册、登录、权限管理")
            assert result.intent.task_category == TaskCategory.AGENT
            assert "agent" in result.dispatched_modes

    @pytest.mark.asyncio
    async def test_process_with_risk_warning(self) -> None:
        """处理带风险的操作"""
        agent = UnifiedEntryAgent()

        with patch.object(
            agent, "_execute_modes",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = [
                ModeResult(
                    mode=TaskCategory.HERMES,
                    success=True,
                    content="操作完成",
                    duration_ms=500,
                )
            ]
            # 使用一个会触发风险检测的消息（has_risk 在 _parse_intent 中默认 False）
            with patch.object(
                agent, "_parse_intent",
                return_value=ParsedIntent(
                    raw_input="删除所有文件",
                    surface_text="删除所有文件",
                    core_need="删除操作",
                    task_category=TaskCategory.HERMES,
                    has_risk=True,
                    risk_description="高危操作：删除所有文件",
                ),
            ):
                result = await agent.process("删除所有文件")
                assert len(result.risk_warnings) == 1
                assert "高危操作" in result.risk_warnings[0]


# ══════════════════════════════════════════════════════════
# 流式处理测试
# ══════════════════════════════════════════════════════════


class TestProcessStream:
    """流式处理"""

    @pytest.fixture
    def agent(self) -> UnifiedEntryAgent:
        """创建 Agent 实例"""
        return UnifiedEntryAgent(model="test-model", api_key="sk-test")

    @pytest.mark.asyncio
    async def test_stream_emits_intent_event(self, agent: UnifiedEntryAgent) -> None:
        """流式处理发出 intent 事件"""
        # 收集事件
        events: list[dict] = []

        with patch(
            "pycoder.server.services.context_orchestrator.get_orchestrator",
        ) as mock_orch:
            mock_orch.return_value = MagicMock()
            mock_orch.return_value.tracker.is_active = False

            with patch(
                "pycoder.server.services.progress_reporter.ProgressReporter",
            ) as mock_prog:
                mock_prog.return_value = MagicMock()
                mock_prog.return_value.set_stages = MagicMock()
                mock_prog.return_value.set_callback = MagicMock()
                mock_prog.return_value.advance = AsyncMock()

                with patch(
                    "pycoder.server.services.plugin_executor.PluginExecutor",
                ) as mock_plugin:
                    mock_plugin.return_value = MagicMock()
                    mock_plugin.return_value.set_plugin_callback = MagicMock()

                    with patch(
                        "pycoder.server.services.execution_pipeline.ExecutionPipeline",
                    ) as mock_pipe:
                        mock_pipe_instance = MagicMock()

                        async def mock_execute(*args, **kwargs):
                            yield {"type": "agent_status", "status": "started"}
                            yield {"type": "token", "content": "你好！"}
                            yield {"type": "done", "content": "你好！这是回复"}

                        mock_pipe_instance.execute = mock_execute
                        mock_pipe.return_value = mock_pipe_instance

                        with patch(
                            "pycoder.server.services.execution_pipeline.get_execution_config",
                        ):
                            with patch(
                                "pycoder.server.chat_bridge.ChatBridge",
                            ) as mock_bridge:
                                mock_bridge.return_value = MagicMock()
                                mock_bridge.return_value.configure = MagicMock()
                                mock_bridge.return_value.close = AsyncMock()

                                async for ev in agent.process_stream("你好"):
                                    events.append(ev)

        # 验证包含 intent 事件
        types = [e.get("type") for e in events]
        assert "unified_intent" in types

    @pytest.mark.asyncio
    async def test_stream_emits_done_event(self, agent: UnifiedEntryAgent) -> None:
        """流式处理发出 done 事件"""
        events: list[dict] = []

        with patch(
            "pycoder.server.services.context_orchestrator.get_orchestrator",
        ) as mock_orch:
            mock_orch.return_value = MagicMock()
            mock_orch.return_value.tracker.is_active = False

            with patch(
                "pycoder.server.services.progress_reporter.ProgressReporter",
            ) as mock_prog:
                mock_prog.return_value = MagicMock()
                mock_prog.return_value.set_stages = MagicMock()
                mock_prog.return_value.set_callback = MagicMock()
                mock_prog.return_value.advance = AsyncMock()

                with patch(
                    "pycoder.server.services.plugin_executor.PluginExecutor",
                ) as mock_plugin:
                    mock_plugin.return_value = MagicMock()
                    mock_plugin.return_value.set_plugin_callback = MagicMock()

                    with patch(
                        "pycoder.server.services.execution_pipeline.ExecutionPipeline",
                    ) as mock_pipe:
                        mock_pipe_instance = MagicMock()

                        async def mock_execute(*args, **kwargs):
                            yield {"type": "done", "content": "回复内容"}

                        mock_pipe_instance.execute = mock_execute
                        mock_pipe.return_value = mock_pipe_instance

                        with patch(
                            "pycoder.server.services.execution_pipeline.get_execution_config",
                        ):
                            with patch(
                                "pycoder.server.chat_bridge.ChatBridge",
                            ) as mock_bridge:
                                mock_bridge.return_value = MagicMock()
                                mock_bridge.return_value.configure = MagicMock()
                                mock_bridge.return_value.close = AsyncMock()

                                async for ev in agent.process_stream("你好"):
                                    events.append(ev)

        types = [e.get("type") for e in events]
        assert "done" in types
        # 找到 done 事件
        done_events = [e for e in events if e.get("type") == "done"]
        assert len(done_events) >= 1
        assert "回复内容" in done_events[0].get("content", "")

    @pytest.mark.asyncio
    async def test_stream_emits_route_event(self, agent: UnifiedEntryAgent) -> None:
        """流式处理发出路由事件"""
        events: list[dict] = []

        with patch(
            "pycoder.server.services.context_orchestrator.get_orchestrator",
        ) as mock_orch:
            mock_orch.return_value = MagicMock()
            mock_orch.return_value.tracker.is_active = False

            with patch(
                "pycoder.server.services.progress_reporter.ProgressReporter",
            ) as mock_prog:
                mock_prog.return_value = MagicMock()
                mock_prog.return_value.set_stages = MagicMock()
                mock_prog.return_value.set_callback = MagicMock()
                mock_prog.return_value.advance = AsyncMock()

                with patch(
                    "pycoder.server.services.plugin_executor.PluginExecutor",
                ) as mock_plugin:
                    mock_plugin.return_value = MagicMock()
                    mock_plugin.return_value.set_plugin_callback = MagicMock()

                    with patch(
                        "pycoder.server.services.execution_pipeline.ExecutionPipeline",
                    ) as mock_pipe:
                        mock_pipe_instance = MagicMock()

                        async def mock_execute(*args, **kwargs):
                            yield {"type": "done", "content": "完成"}

                        mock_pipe_instance.execute = mock_execute
                        mock_pipe.return_value = mock_pipe_instance

                        with patch(
                            "pycoder.server.services.execution_pipeline.get_execution_config",
                        ):
                            with patch(
                                "pycoder.server.chat_bridge.ChatBridge",
                            ) as mock_bridge:
                                mock_bridge.return_value = MagicMock()
                                mock_bridge.return_value.configure = MagicMock()
                                mock_bridge.return_value.close = AsyncMock()

                                async for ev in agent.process_stream("修改 main.py"):
                                    events.append(ev)

        types = [e.get("type") for e in events]
        assert "unified_route" in types

    @pytest.mark.asyncio
    async def test_stream_emits_beautify_event(self, agent: UnifiedEntryAgent) -> None:
        """流式处理发出 beautify 事件"""
        events: list[dict] = []

        with patch(
            "pycoder.server.services.context_orchestrator.get_orchestrator",
        ) as mock_orch:
            mock_orch.return_value = MagicMock()
            mock_orch.return_value.tracker.is_active = False

            with patch(
                "pycoder.server.services.progress_reporter.ProgressReporter",
            ) as mock_prog:
                mock_prog.return_value = MagicMock()
                mock_prog.return_value.set_stages = MagicMock()
                mock_prog.return_value.set_callback = MagicMock()
                mock_prog.return_value.advance = AsyncMock()

                with patch(
                    "pycoder.server.services.plugin_executor.PluginExecutor",
                ) as mock_plugin:
                    mock_plugin.return_value = MagicMock()
                    mock_plugin.return_value.set_plugin_callback = MagicMock()

                    with patch(
                        "pycoder.server.services.execution_pipeline.ExecutionPipeline",
                    ) as mock_pipe:
                        mock_pipe_instance = MagicMock()

                        async def mock_execute(*args, **kwargs):
                            yield {"type": "done", "content": "完成"}

                        mock_pipe_instance.execute = mock_execute
                        mock_pipe.return_value = mock_pipe_instance

                        with patch(
                            "pycoder.server.services.execution_pipeline.get_execution_config",
                        ):
                            with patch(
                                "pycoder.server.chat_bridge.ChatBridge",
                            ) as mock_bridge:
                                mock_bridge.return_value = MagicMock()
                                mock_bridge.return_value.configure = MagicMock()
                                mock_bridge.return_value.close = AsyncMock()

                                async for ev in agent.process_stream("你好"):
                                    events.append(ev)

        types = [e.get("type") for e in events]
        assert "unified_beautify" in types

    @pytest.mark.asyncio
    async def test_stream_emits_merge_event(self, agent: UnifiedEntryAgent) -> None:
        """流式处理发出 merge 事件"""
        events: list[dict] = []

        with patch(
            "pycoder.server.services.context_orchestrator.get_orchestrator",
        ) as mock_orch:
            mock_orch.return_value = MagicMock()
            mock_orch.return_value.tracker.is_active = False

            with patch(
                "pycoder.server.services.progress_reporter.ProgressReporter",
            ) as mock_prog:
                mock_prog.return_value = MagicMock()
                mock_prog.return_value.set_stages = MagicMock()
                mock_prog.return_value.set_callback = MagicMock()
                mock_prog.return_value.advance = AsyncMock()

                with patch(
                    "pycoder.server.services.plugin_executor.PluginExecutor",
                ) as mock_plugin:
                    mock_plugin.return_value = MagicMock()
                    mock_plugin.return_value.set_plugin_callback = MagicMock()

                    with patch(
                        "pycoder.server.services.execution_pipeline.ExecutionPipeline",
                    ) as mock_pipe:
                        mock_pipe_instance = MagicMock()

                        async def mock_execute(*args, **kwargs):
                            yield {"type": "done", "content": "回复内容"}

                        mock_pipe_instance.execute = mock_execute
                        mock_pipe.return_value = mock_pipe_instance

                        with patch(
                            "pycoder.server.services.execution_pipeline.get_execution_config",
                        ):
                            with patch(
                                "pycoder.server.chat_bridge.ChatBridge",
                            ) as mock_bridge:
                                mock_bridge.return_value = MagicMock()
                                mock_bridge.return_value.configure = MagicMock()
                                mock_bridge.return_value.close = AsyncMock()

                                async for ev in agent.process_stream("你好"):
                                    events.append(ev)

        types = [e.get("type") for e in events]
        assert "unified_merge" in types

    @pytest.mark.asyncio
    async def test_stream_hermes_message(self, agent: UnifiedEntryAgent) -> None:
        """流式处理 HERMES 类消息"""
        events: list[dict] = []

        with patch(
            "pycoder.server.services.context_orchestrator.get_orchestrator",
        ) as mock_orch:
            mock_orch.return_value = MagicMock()
            mock_orch.return_value.tracker.is_active = False

            with patch(
                "pycoder.server.services.progress_reporter.ProgressReporter",
            ) as mock_prog:
                mock_prog.return_value = MagicMock()
                mock_prog.return_value.set_stages = MagicMock()
                mock_prog.return_value.set_callback = MagicMock()
                mock_prog.return_value.advance = AsyncMock()

                with patch(
                    "pycoder.server.services.plugin_executor.PluginExecutor",
                ) as mock_plugin:
                    mock_plugin.return_value = MagicMock()
                    mock_plugin.return_value.set_plugin_callback = MagicMock()

                    with patch(
                        "pycoder.server.services.execution_pipeline.ExecutionPipeline",
                    ) as mock_pipe:
                        mock_pipe_instance = MagicMock()

                        async def mock_execute(*args, **kwargs):
                            yield {"type": "done", "content": "已修改文件"}

                        mock_pipe_instance.execute = mock_execute
                        mock_pipe.return_value = mock_pipe_instance

                        with patch(
                            "pycoder.server.services.execution_pipeline.get_execution_config",
                        ):
                            with patch(
                                "pycoder.server.chat_bridge.ChatBridge",
                            ) as mock_bridge:
                                mock_bridge.return_value = MagicMock()
                                mock_bridge.return_value.configure = MagicMock()
                                mock_bridge.return_value.close = AsyncMock()

                                async for ev in agent.process_stream(
                                    "修改 main.py 中的登录逻辑"
                                ):
                                    events.append(ev)

        # 应有 HERMES 分类的 intent
        intent_events = [e for e in events if e.get("type") == "unified_intent"]
        assert len(intent_events) >= 1
        assert intent_events[0].get("category") == "hermes"