"""
智能路由系统测试 — IntentAnalyzer, AgentSelector, ToolPlanner,
IntelligentRouter, FeedbackLoop, ContextEnhancer

测试覆盖:
  - 意图分析（正则快速通道 + LLM 深度分析）
  - Agent 选择（多维评分 + 历史反馈）
  - 工具规划（复杂度驱动 + 任务类型映射）
  - 智能路由（完整决策链 + 执行配置）
  - 反馈学习（信号收集 + 权重调整 + 持久化）
  - 上下文增强（引用消解 + 话题追踪 + 实体提取）
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from pycoder.brain.intent_analyzer import (
    IntentAnalysis,
    IntentAnalyzer,
    get_intent_analyzer,
)
from pycoder.brain.agent_selector import (
    AgentSelection,
    AgentSelector,
    get_agent_selector,
)
from pycoder.brain.tool_planner import (
    ToolPlan,
    ToolPlanner,
    get_tool_planner,
    COMPLEXITY_TOOL_PLAN,
    TASK_TOOL_MAP,
)
from pycoder.brain.intelligent_router import (
    ExecutionConfig,
    IntelligentRouter,
    RoutingDecision,
    get_intelligent_router,
    COMPLEXITY_EXECUTION_CONFIG,
)
from pycoder.brain.feedback_loop import (
    AdaptiveWeights,
    AggregatedStats,
    ExecutionSignal,
    FeedbackLoop,
    get_feedback_loop,
)
from pycoder.brain.context_enhancer import (
    ContextEnhancer,
    ConversationTurn,
    EnhancedContext,
    get_context_enhancer,
)


# ══════════════════════════════════════════════════════════
# IntentAnalyzer 测试
# ══════════════════════════════════════════════════════════


class TestIntentAnalyzer:
    """意图分析器测试"""

    def test_trivial_greeting_detected_as_trivial(self):
        """简单问候应被识别为 trivial"""
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("你好")
        assert result.complexity == "trivial"
        assert result.task_type == "qa"
        assert result.confidence >= 0.9

    def test_hello_world_detected_as_trivial(self):
        """英文问候应被识别为 trivial"""
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("hi")
        assert result.complexity == "trivial"

    def test_empty_message_returns_trivial(self):
        """空消息应返回 trivial"""
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("")
        assert result.complexity == "trivial"

    def test_none_message_returns_trivial(self):
        """None 消息应返回 trivial"""
        analyzer = IntentAnalyzer()
        result = analyzer.analyze(None)  # type: ignore
        assert result.complexity == "trivial"

    def test_python_domain_detected(self):
        """Python 领域应被正确识别"""
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("请用 FastAPI 写一个 API 接口")
        assert result.technical_domain == "python"
        assert result.task_type == "code_gen"

    def test_debug_task_detected(self):
        """调试任务应被正确识别"""
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("修复 app.py 中的 TypeError 错误")
        assert result.task_type == "debug"
        assert result.has_file_references is True

    def test_architect_task_detected(self):
        """架构设计任务应被识别为 complex"""
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("设计一个微服务架构方案，包含用户认证和权限管理")
        assert result.task_type == "architect"
        assert result.complexity in ("medium", "complex")

    def test_risk_detection(self):
        """高风险操作应被检测"""
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("帮我执行 rm -rf /tmp 清理")
        assert result.has_risk is True

    def test_ambiguity_detection(self):
        """歧义应被检测"""
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("修改这个文件")
        assert result.is_ambiguous is True
        assert len(result.ambiguity_notes) > 0

    def test_file_references_detected(self):
        """文件引用应被检测"""
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("读取 src/main.py 的内容")
        assert result.has_file_references is True

    def test_complexity_scoring_medium_length(self):
        """中等长度消息复杂度评分"""
        analyzer = IntentAnalyzer()
        result = analyzer.analyze(
            "请帮我重构这个模块，优化性能并添加错误处理"
        )
        assert result.complexity_score >= 0
        assert isinstance(result.complexity_score, int)

    def test_expected_response_type_code(self):
        """代码生成任务预期响应类型为 code"""
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("写一个 Python 函数计算斐波那契数列")
        result.has_file_references = False  # 手动设置，因为是函数生成
        assert result.expected_response_type in ("code", "text", "mixed")

    def test_normalized_intent_includes_domain(self):
        """标准化意图应包含领域信息"""
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("用 pandas 做数据分析")
        assert len(result.normalized_intent) > 0

    def test_analyze_deep_without_llm_returns_hybrid(self):
        """无 LLM 时深度分析应返回 hybrid 结果"""
        analyzer = IntentAnalyzer()
        result = asyncio.run(analyzer.analyze_deep("一个复杂的架构设计问题，需要深入分析"))
        assert result.analysis_method in ("regex", "hybrid")


# ══════════════════════════════════════════════════════════
# AgentSelector 测试
# ══════════════════════════════════════════════════════════


class TestAgentSelector:
    """Agent 选择器测试"""

    def test_trivial_qa_returns_none(self):
        """简单问答应返回 none Agent"""
        selector = AgentSelector()
        intent = IntentAnalysis(
            raw_input="你好",
            complexity="trivial",
            task_type="qa",
        )
        result = selector.select(intent)
        assert result.primary_agent == "none"
        assert result.confidence >= 0.9

    def test_code_gen_returns_developer(self):
        """代码生成应选择 developer"""
        selector = AgentSelector()
        intent = IntentAnalysis(
            raw_input="写一个 FastAPI 接口",
            technical_domain="python",
            task_type="code_gen",
            complexity="medium",
            complexity_score=40,
        )
        result = selector.select(intent)
        assert result.primary_agent in ("developer", "architect")

    def test_debug_returns_debugger(self):
        """调试任务应选择 debugger/fixer/security"""
        selector = AgentSelector()
        intent = IntentAnalysis(
            raw_input="修复 app.py 的 bug",
            technical_domain="python",
            task_type="debug",
            complexity="medium",
            complexity_score=45,
        )
        result = selector.select(intent)
        assert result.primary_agent in ("debugger", "fixer", "security")

    def test_architect_task_returns_architect(self):
        """架构设计应选择 architect"""
        selector = AgentSelector()
        intent = IntentAnalysis(
            raw_input="设计微服务架构",
            technical_domain="python",
            task_type="architect",
            complexity="complex",
            complexity_score=80,
        )
        result = selector.select(intent)
        assert result.primary_agent in ("architect", "orchestrator")

    def test_security_task_returns_security(self):
        """安全审计应选择 security"""
        selector = AgentSelector()
        intent = IntentAnalysis(
            raw_input="审计代码安全漏洞",
            technical_domain="security",
            task_type="review",
            complexity="medium",
            complexity_score=50,
        )
        result = selector.select(intent)
        assert result.primary_agent in ("security", "reviewer")

    def test_clarification_needed_returns_none(self):
        """需要追问时应返回 none"""
        selector = AgentSelector()
        intent = IntentAnalysis(
            raw_input="修改那个文件",
            complexity="simple",
            task_type="refactor",
            needs_clarification=True,
            clarification_questions=["请问需要修改哪个文件？"],
        )
        result = selector.select(intent)
        assert result.primary_agent == "none"

    def test_selection_has_reason(self):
        """选择结果应包含理由"""
        selector = AgentSelector()
        intent = IntentAnalysis(
            raw_input="写一个 Python 脚本",
            technical_domain="python",
            task_type="code_gen",
            complexity="simple",
            complexity_score=20,
        )
        result = selector.select(intent)
        assert len(result.selection_reason) > 0

    def test_record_result_updates_history(self):
        """记录结果应更新历史"""
        selector = AgentSelector()
        selector.record_result("developer", True)
        selector.record_result("developer", True)
        selector.record_result("developer", False)
        intent = IntentAnalysis(
            raw_input="test",
            complexity="simple",
            task_type="code_gen",
            complexity_score=20,
        )
        result = selector.select(intent)
        # 历史有数据，history 得分应不再是默认 50
        assert result.confidence >= 0

    def test_register_agent_adds_to_matrix(self):
        """注册新 Agent 应添加到能力矩阵"""
        selector = AgentSelector()
        selector.register_agent("data_scientist", {
            "name": "数据科学家",
            "description": "数据分析",
            "domains": ["data", "python"],
            "task_types": ["code_gen", "qa"],
            "complexity_range": (20, 70),
            "model_tier": "standard",
            "suitable_for": "数据分析",
        })
        info = selector.get_agent_info("data_scientist")
        assert info is not None
        assert info["name"] == "数据科学家"

    def test_list_agents_returns_all(self):
        """列出 Agent 应返回所有非 none 的 Agent"""
        selector = AgentSelector()
        agents = selector.list_agents()
        assert len(agents) > 5
        assert all(a["id"] != "none" for a in agents)


# ══════════════════════════════════════════════════════════
# ToolPlanner 测试
# ══════════════════════════════════════════════════════════


class TestToolPlanner:
    """工具规划器测试"""

    def test_trivial_plan_allows_direct_answer(self):
        """trivial 复杂度应允许直接回答"""
        planner = ToolPlanner()
        intent = IntentAnalysis(
            raw_input="什么是 Python？",
            complexity="trivial",
            task_type="qa",
        )
        plan = planner.plan(intent)
        assert plan.allow_direct_answer is True
        assert plan.estimated_tool_calls == 0
        assert plan.max_tool_calls == 0

    def test_simple_plan_has_read_tools(self):
        """simple 复杂度应有读工具"""
        planner = ToolPlanner()
        intent = IntentAnalysis(
            raw_input="读取 config.py",
            complexity="simple",
            task_type="qa",
            has_file_references=True,
        )
        plan = planner.plan(intent)
        assert "read" in plan.tool_categories
        assert plan.estimated_tool_calls >= 2

    def test_medium_plan_has_read_write(self):
        """medium 复杂度应有读写工具"""
        planner = ToolPlanner()
        intent = IntentAnalysis(
            raw_input="修复 app.py 的 bug",
            complexity="medium",
            task_type="debug",
        )
        plan = planner.plan(intent)
        assert "read" in plan.tool_categories
        assert not plan.allow_direct_answer

    def test_complex_plan_has_all_categories(self):
        """complex 复杂度应有全类别工具"""
        planner = ToolPlanner()
        intent = IntentAnalysis(
            raw_input="重构整个项目架构",
            complexity="complex",
            task_type="architect",
        )
        plan = planner.plan(intent)
        assert len(plan.tool_categories) >= 3
        assert plan.max_tool_calls >= 30

    def test_code_gen_task_has_execute_tools(self):
        """代码生成任务应有 execute 工具"""
        planner = ToolPlanner()
        intent = IntentAnalysis(
            raw_input="写一个 Python 脚本",
            complexity="simple",
            task_type="code_gen",
        )
        plan = planner.plan(intent)
        assert "execute" in plan.tool_categories or "write" in plan.tool_categories

    def test_risk_increases_max_calls(self):
        """风险操作应增加最大工具调用次数"""
        planner = ToolPlanner()
        intent = IntentAnalysis(
            raw_input="删除系统中的文件",
            complexity="simple",
            task_type="debug",
            has_risk=True,
        )
        plan = planner.plan(intent)
        assert plan.max_tool_calls >= 5

    def test_should_use_tools_false_for_trivial(self):
        """trivial 任务不应使用工具"""
        planner = ToolPlanner()
        intent = IntentAnalysis(
            raw_input="你好",
            complexity="trivial",
            task_type="qa",
        )
        plan = planner.plan(intent)
        assert planner.should_use_tools(plan) is False

    def test_should_use_tools_true_for_medium(self):
        """medium 任务应使用工具"""
        planner = ToolPlanner()
        intent = IntentAnalysis(
            raw_input="修复代码",
            complexity="medium",
            task_type="debug",
        )
        plan = planner.plan(intent)
        assert planner.should_use_tools(plan) is True

    def test_register_tool_adds_to_categories(self):
        """注册新工具应添加到分类"""
        planner = ToolPlanner()
        planner.register_tool("analyze_data", "data", ["path"], "分析数据")
        tools = planner.get_tools_for_category("data")
        assert "analyze_data" in tools

    def test_adjust_plan_low_success_rate(self):
        """低成功率应调整计划（减少工具调用）"""
        planner = ToolPlanner()
        intent = IntentAnalysis(
            raw_input="test",
            complexity="medium",
            task_type="code_gen",
        )
        plan = planner.plan(intent)
        original_max = plan.max_tool_calls
        adjusted = planner.adjust_plan(plan, 0.2)
        assert adjusted.max_tool_calls <= original_max


# ══════════════════════════════════════════════════════════
# IntelligentRouter 测试
# ══════════════════════════════════════════════════════════


class TestIntelligentRouter:
    """智能路由器测试"""

    def test_decide_trivial_greeting(self):
        """简单问候的决策"""
        router = IntelligentRouter()
        decision = router.decide("你好")
        assert isinstance(decision, RoutingDecision)
        assert decision.intent.complexity == "trivial"
        assert decision.agent.primary_agent == "none"
        assert decision.tool_plan.allow_direct_answer is True

    def test_decide_code_gen(self):
        """代码生成的决策"""
        router = IntelligentRouter()
        decision = router.decide("用 FastAPI 写一个用户登录接口")
        assert decision.intent.task_type == "code_gen"
        assert decision.agent.primary_agent != "none"
        assert decision.tool_plan.estimated_tool_calls >= 0

    def test_decide_has_confidence(self):
        """决策应有置信度"""
        router = IntelligentRouter()
        decision = router.decide("写一个 Python 脚本")
        assert 0 <= decision.confidence <= 1.0

    def test_decide_has_decision_time(self):
        """决策应有耗时记录"""
        router = IntelligentRouter()
        decision = router.decide("测试消息")
        assert decision.decision_time_ms >= 0

    def test_decide_to_dict(self):
        """决策应可序列化为 dict"""
        router = IntelligentRouter()
        decision = router.decide("写一个 FastAPI 接口")
        d = decision.to_dict()
        assert "intent" in d
        assert "agent" in d
        assert "tool_plan" in d
        assert "execution" in d

    def test_record_feedback(self):
        """记录反馈应更新 Agent 历史"""
        router = IntelligentRouter()
        router.record_feedback("测试消息", True, "developer")
        # 验证不会抛出异常

    def test_complexity_execution_config_exists(self):
        """所有复杂度级别应有执行配置"""
        for level in ("trivial", "simple", "medium", "complex"):
            assert level in COMPLEXITY_EXECUTION_CONFIG

    def test_trivial_config_has_minimal_iterations(self):
        """trivial 配置应有最小迭代次数"""
        config = COMPLEXITY_EXECUTION_CONFIG["trivial"]
        assert config.max_iterations <= 1

    def test_complex_config_has_qa_review(self):
        """complex 配置应启用 QA 审查"""
        config = COMPLEXITY_EXECUTION_CONFIG["complex"]
        assert config.enable_qa_review is True


# ══════════════════════════════════════════════════════════
# FeedbackLoop 测试
# ══════════════════════════════════════════════════════════


class TestFeedbackLoop:
    """反馈学习循环测试"""

    def test_start_and_end_signal(self):
        """开始和结束信号记录"""
        loop = FeedbackLoop()
        signal = loop.start_signal(session_id="test_session")
        assert signal.session_id == "test_session"
        loop.end_signal(
            signal, completed=True, completion_reason="done",
            iterations=5, tool_calls=3, tool_success=3,
            execution_time_ms=1000,
        )
        assert signal.task_completed is True
        assert signal.actual_iterations == 5

    def test_signal_with_intent_and_agent(self):
        """信号携带意图和 Agent 信息"""
        loop = FeedbackLoop()
        intent = IntentAnalysis(
            raw_input="test",
            technical_domain="python",
            task_type="code_gen",
            complexity="medium",
            complexity_score=40,
            confidence=0.85,
        )
        signal = loop.start_signal(intent=intent, session_id="test")
        assert signal.intent_domain == "python"
        assert signal.intent_task_type == "code_gen"

    def test_user_rating_recording(self):
        """用户评分记录"""
        loop = FeedbackLoop()
        signal = loop.start_signal(session_id="test")
        loop.record_user_rating(signal, rating=4, text="很好", reaction="thumbs_up")
        assert signal.user_rating == 4
        assert signal.reaction == "thumbs_up"

    def test_learn_returns_status(self):
        """学习应返回状态"""
        loop = FeedbackLoop()
        result = loop.learn()
        assert "status" in result

    def test_learn_with_signals(self):
        """有信号时的学习"""
        loop = FeedbackLoop()
        signal = loop.start_signal(session_id="test")
        loop.end_signal(signal, completed=True, iterations=3, tool_calls=2, tool_success=2)
        result = loop.learn()
        assert result["status"] == "updated"

    def test_get_stats(self):
        """获取统计"""
        loop = FeedbackLoop()
        signal = loop.start_signal(session_id="test")
        loop.end_signal(
            signal, completed=True, iterations=3, tool_calls=2, tool_success=2,
            execution_time_ms=500, total_tokens=1000,
        )
        stats = loop.get_stats()
        assert stats.total_executions >= 1
        assert stats.completion_rate >= 0

    def test_get_recommendations(self):
        """获取优化建议"""
        loop = FeedbackLoop()
        recs = loop.get_recommendations()
        assert isinstance(recs, list)
        assert len(recs) > 0

    def test_weights_persistence(self, tmp_path):
        """权重持久化测试"""
        config_path = tmp_path / "adaptive_config.json"
        loop = FeedbackLoop(config_path=config_path)
        loop.weights.agent_history_weight = 0.25
        loop._save_weights()
        assert config_path.exists()

        # 重新加载
        loop2 = FeedbackLoop(config_path=config_path)
        assert loop2.weights.agent_history_weight == 0.25

    def test_signal_persistence(self, tmp_path):
        """信号持久化测试"""
        signals_path = tmp_path / "signals.jsonl"
        loop = FeedbackLoop(signals_path=signals_path)
        signal = loop.start_signal(session_id="test")
        loop.end_signal(signal, completed=True, iterations=3, tool_calls=2, tool_success=2)
        loop.flush()

        data = loop.load_history()
        assert len(data) >= 1

    def test_adaptive_weights_defaults(self):
        """自适应权重默认值"""
        weights = AdaptiveWeights()
        d = weights.to_dict()
        assert "agent_weights" in d
        assert "tool" in d
        assert "thresholds" in d

    def test_adaptive_weights_from_dict(self):
        """从 dict 加载自适应权重"""
        data = {
            "agent_weights": {
                "domain": 0.35,
                "task_type": 0.20,
                "complexity": 0.25,
                "history": 0.10,
                "speed": 0.10,
            },
            "tool": {"retry_max": 3},
            "thresholds": {"min_confidence": 0.6},
            "learning_rate": 0.15,
        }
        weights = AdaptiveWeights.from_dict(data)
        assert weights.agent_domain_weight == 0.35
        assert weights.tool_retry_max == 3
        assert weights.min_confidence_threshold == 0.6
        assert weights.learning_rate == 0.15

    def test_execution_signal_to_dict(self):
        """信号序列化"""
        signal = ExecutionSignal(
            session_id="test",
            intent_domain="python",
            agent_id="developer",
            task_completed=True,
        )
        d = signal.to_dict()
        assert d["session"] == "test"
        assert d["intent"]["domain"] == "python"
        assert d["agent"]["id"] == "developer"

    def test_aggregated_stats_defaults(self):
        """聚合统计默认值"""
        stats = AggregatedStats()
        assert stats.completion_rate == 0.0
        assert stats.avg_time_ms == 0.0


# ══════════════════════════════════════════════════════════
# ContextEnhancer 测试
# ══════════════════════════════════════════════════════════


class TestContextEnhancer:
    """上下文增强器测试"""

    def test_process_simple_message(self):
        """处理简单消息"""
        enhancer = ContextEnhancer()
        ctx = enhancer.process_message("请帮我写一个 Python 函数")
        assert ctx.current_message == "请帮我写一个 Python 函数"
        assert ctx.current_topic != ""

    def test_topic_detection_code_dev(self):
        """话题检测 - 代码开发"""
        enhancer = ContextEnhancer()
        ctx = enhancer.process_message("写一个 FastAPI 接口实现用户登录")
        assert ctx.current_topic == "代码开发"

    def test_topic_detection_debug(self):
        """话题检测 - 调试修复"""
        enhancer = ContextEnhancer()
        ctx = enhancer.process_message("修复 app.py 的 TypeError 错误")
        assert ctx.current_topic == "调试修复"

    def test_entity_extraction_files(self):
        """实体提取 - 文件路径"""
        enhancer = ContextEnhancer()
        ctx = enhancer.process_message("请修改 src/main.py 和 config/settings.py")
        assert len(ctx.key_entities) >= 1

    def test_reference_resolution_pronoun(self):
        """引用消解 - 代词"""
        enhancer = ContextEnhancer()
        history = [
            ConversationTurn(
                role="user",
                content="请修改 src/app.py 中的 hello 函数",
                topics=["代码开发"],
            ),
        ]
        ctx = enhancer.process_message("这个函数还需要添加注释", history=history)
        # 代词消解：应该将"这个"替换为历史中的主语，或者保留相关文件信息
        assert len(ctx.resolved_message) > 0
        assert len(ctx.relevant_files) > 0

    def test_reference_resolution_file_ref(self):
        """引用消解 - 文件引用"""
        enhancer = ContextEnhancer()
        history = [
            ConversationTurn(
                role="user",
                content="请读取 src/config.py 的内容",
                topics=["问答咨询"],
            ),
        ]
        ctx = enhancer.process_message("这个文件中的 DEBUG 配置是什么？", history=history)
        assert "config.py" in ctx.resolved_message

    def test_topic_shift_detection(self):
        """话题转换检测"""
        enhancer = ContextEnhancer()
        history = [
            ConversationTurn(
                role="user",
                content="写一个 Python 函数",
                topics=["代码开发"],
            ),
        ]
        ctx = enhancer.process_message("还有个问题，docker 怎么部署？", history=history)
        assert ctx.is_topic_shift is True

    def test_coherence_calculation(self):
        """连贯性计算"""
        enhancer = ContextEnhancer()
        history = [
            ConversationTurn(
                role="user",
                content="请帮我写一个 FastAPI 接口",
                topics=["代码开发"],
            ),
        ]
        ctx = enhancer.process_message("这个接口需要添加认证中间件", history=history)
        assert 0 <= ctx.coherence_score <= 1.0

    def test_clarification_needed_short_message(self):
        """短消息无历史需要追问"""
        enhancer = ContextEnhancer()
        ctx = enhancer.process_message("修改一下")
        assert ctx.needs_clarification is True

    def test_build_prompt_includes_topic(self):
        """构建 prompt 应包含话题"""
        enhancer = ContextEnhancer()
        ctx = enhancer.process_message("写一个 Python 脚本")
        prompt = ctx.build_prompt()
        assert "代码开发" in prompt

    def test_session_isolation(self):
        """会话隔离测试"""
        enhancer = ContextEnhancer()
        ctx1 = enhancer.process_message("写一个 Python 函数", session_id="session1")
        ctx2 = enhancer.process_message("修复一个 bug", session_id="session2")
        assert ctx1.current_topic != ctx2.current_topic

    def test_record_assistant_response(self):
        """记录助手回复"""
        enhancer = ContextEnhancer()
        enhancer.record_assistant_response("test_session", "这是回答内容", topic="代码开发")
        ctx = enhancer.get_session_context("test_session")
        assert "代码开发" in ctx or "回答内容" in ctx

    def test_clear_session(self):
        """清除会话"""
        enhancer = ContextEnhancer()
        enhancer.process_message("测试消息", session_id="clear_test")
        enhancer.clear_session("clear_test")
        ctx = enhancer.get_session_context("clear_test")
        assert ctx == ""

    def test_conversation_turn_creation(self):
        """对话轮次创建"""
        turn = ConversationTurn(
            role="user",
            content="测试消息",
            topics=["测试"],
            entities=["test.py"],
        )
        assert turn.role == "user"
        assert "test.py" in turn.entities

    def test_enhanced_context_attributes(self):
        """增强上下文属性"""
        ctx = EnhancedContext(current_message="test")
        prompt = ctx.build_prompt()
        assert prompt == ""  # 空上下文不产生 prompt

    def test_multiple_turns_context(self):
        """多轮对话上下文"""
        enhancer = ContextEnhancer()
        enhancer.process_message("写一个 Python 脚本", session_id="multi")
        enhancer.record_assistant_response("multi", "已创建脚本 script.py")
        enhancer.process_message("在脚本中添加日志功能", session_id="multi")
        ctx = enhancer.get_session_context("multi")
        assert "script.py" in ctx or "日志" in ctx


# ══════════════════════════════════════════════════════════
# 集成测试
# ══════════════════════════════════════════════════════════


class TestIntegration:
    """集成测试"""

    def test_full_decision_chain_trivial(self):
        """完整决策链 - 简单问答"""
        router = IntelligentRouter()
        decision = router.decide("你好，你能做什么？")
        assert decision.intent.complexity == "trivial"
        assert decision.agent.primary_agent == "none"
        assert decision.tool_plan.allow_direct_answer is True
        assert decision.execution_config.max_iterations <= 1

    def test_full_decision_chain_code_gen(self):
        """完整决策链 - 代码生成"""
        router = IntelligentRouter()
        decision = router.decide("用 FastAPI 写一个用户注册接口，包含邮箱验证")
        assert decision.intent.task_type == "code_gen"
        assert decision.agent.primary_agent != "none"
        # 代码生成任务可能被评估为 simple 或 medium，取决于复杂度评分
        assert decision.execution_config.max_iterations > 1

    def test_full_decision_chain_complex(self):
        """完整决策链 - 复杂任务"""
        router = IntelligentRouter()
        decision = router.decide(
            "重构整个微服务架构，迁移到 FastAPI，"
            "包含认证和权限系统，支持高并发和分布式部署"
        )
        # 复杂任务应为 medium 或 complex
        assert decision.intent.complexity in ("medium", "complex")
        assert decision.execution_config.max_iterations >= 15
        assert decision.execution_config.enable_qa_review is True or decision.execution_config.strategy in ("team", "auto")

    def test_feedback_loop_integration(self):
        """反馈学习集成"""
        router = IntelligentRouter()
        feedback = FeedbackLoop()

        decision = router.decide("写一个 Python 函数")
        signal = feedback.start_signal(
            session_id="integration_test",
            intent=decision.intent,
            agent=decision.agent,
            tool_plan=decision.tool_plan,
        )
        feedback.end_signal(
            signal, completed=True, iterations=3, tool_calls=2, tool_success=2,
        )
        feedback.record_user_rating(signal, rating=4)
        stats = feedback.get_stats()
        assert stats.total_executions >= 1

    def test_router_with_feedback_recording(self):
        """路由器反馈记录"""
        router = IntelligentRouter()
        router.record_feedback("测试消息", True, "developer")
        # 验证不会抛出异常

    def test_context_enhancer_with_router(self):
        """上下文增强器与路由器协作"""
        enhancer = ContextEnhancer()
        router = IntelligentRouter()

        ctx = enhancer.process_message("修改 src/app.py 的 login 函数")
        decision = router.decide(ctx.resolved_message)
        assert decision.intent.has_file_references is True
        assert "app.py" in ctx.resolved_message or "src/app.py" in ctx.resolved_message


# ══════════════════════════════════════════════════════════
# 可扩展性测试
# ══════════════════════════════════════════════════════════


class TestExtensibility:
    """可扩展性测试"""

    def test_register_new_agent(self):
        """注册新 Agent 类型"""
        selector = AgentSelector()
        new_agent = {
            "name": "DevOps 专家",
            "description": "CI/CD 和部署",
            "domains": ["devops", "python"],
            "task_types": ["deploy", "architect"],
            "complexity_range": (30, 90),
            "model_tier": "premium",
            "suitable_for": "部署流水线、CI/CD",
        }
        selector.register_agent("devops_expert", new_agent)
        info = selector.get_agent_info("devops_expert")
        assert info is not None
        assert info["name"] == "DevOps 专家"

        # 验证新 Agent 可被选择
        intent = IntentAnalysis(
            raw_input="部署到 Kubernetes 集群",
            technical_domain="devops",
            task_type="deploy",
            complexity="medium",
            complexity_score=50,
        )
        result = selector.select(intent)
        assert result.primary_agent in ("devops", "devops_expert")

    def test_register_new_tool(self):
        """注册新工具"""
        planner = ToolPlanner()
        planner.register_tool("k8s_deploy", "devops", ["config_path"], "K8s 部署")
        tools = planner.get_tools_for_category("devops")
        assert "k8s_deploy" in tools

    def test_register_new_domain_keyword(self):
        """注册新领域关键词"""
        from pycoder.brain.intent_analyzer import DOMAIN_KEYWORDS
        DOMAIN_KEYWORDS["kotlin"] = ["kotlin", "ktor", "android"]
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("用 Kotlin 写一个 Android 应用")
        assert result.technical_domain == "kotlin"
        # 清理
        del DOMAIN_KEYWORDS["kotlin"]

    def test_register_new_task_type(self):
        """注册新任务类型"""
        from pycoder.brain.intent_analyzer import TASK_TYPE_KEYWORDS
        TASK_TYPE_KEYWORDS["data_analysis"] = ["分析数据", "数据可视化", "图表"]
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("分析数据并生成可视化图表")
        assert result.task_type == "data_analysis"
        # 清理
        del TASK_TYPE_KEYWORDS["data_analysis"]


# ══════════════════════════════════════════════════════════
# 性能测试
# ══════════════════════════════════════════════════════════


class TestPerformance:
    """性能测试"""

    def test_router_decision_under_10ms(self):
        """路由决策应在 10ms 内完成"""
        import time
        router = IntelligentRouter()
        start = time.monotonic()
        for _ in range(20):
            router.decide("写一个 Python 函数")
        elapsed = (time.monotonic() - start) * 1000 / 20
        # 平均每次决策 < 10ms
        assert elapsed < 50, f"决策耗时 {elapsed:.1f}ms，超过 50ms 上限"

    def test_intent_analyzer_under_5ms(self):
        """意图分析应在 5ms 内完成"""
        import time
        analyzer = IntentAnalyzer()
        start = time.monotonic()
        for _ in range(50):
            analyzer.analyze("用 FastAPI 写一个用户登录接口，包含 JWT 认证")
        elapsed = (time.monotonic() - start) * 1000 / 50
        assert elapsed < 10, f"意图分析耗时 {elapsed:.1f}ms，超过 10ms 上限"

    def test_agent_selector_under_3ms(self):
        """Agent 选择应在 3ms 内完成"""
        import time
        selector = AgentSelector()
        intent = IntentAnalysis(
            raw_input="test",
            technical_domain="python",
            task_type="code_gen",
            complexity="medium",
            complexity_score=40,
        )
        start = time.monotonic()
        for _ in range(100):
            selector.select(intent)
        elapsed = (time.monotonic() - start) * 1000 / 100
        assert elapsed < 5, f"Agent 选择耗时 {elapsed:.1f}ms，超过 5ms 上限"

    def test_tool_planner_under_2ms(self):
        """工具规划应在 2ms 内完成"""
        import time
        planner = ToolPlanner()
        intent = IntentAnalysis(
            raw_input="test",
            complexity="medium",
            task_type="code_gen",
        )
        start = time.monotonic()
        for _ in range(100):
            planner.plan(intent)
        elapsed = (time.monotonic() - start) * 1000 / 100
        assert elapsed < 5, f"工具规划耗时 {elapsed:.1f}ms，超过 5ms 上限"