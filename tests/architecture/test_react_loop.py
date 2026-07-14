"""P1-5: ReAct 循环测试

覆盖：
- 正常 FINISH 终止
- 工具观察反馈到下一轮
- 达到最大迭代次数
- LLM 调用失败处理
- 工具执行失败处理
- JSON 解析失败重试
- 旧 tool_calls 格式兼容
- 提示词构建
- 步骤序列化
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

import pytest

from pycoder.core.ports.llm_provider import LLMEvent, LLMProvider, LLMResponse
from pycoder.server.services.agent_react_loop import (
    FINISH_ACTION,
    REACT_SYSTEM_PROMPT,
    ReActLoop,
    ReActResult,
    ReActStep,
    _extract_json_candidates,
    _try_parse_react_json,
    _try_parse_tool_calls_compat,
)


# ══════════════════════════════════════════════════════════
# 测试桩
# ══════════════════════════════════════════════════════════

class MockLLMProvider:
    """模拟 LLM — 按预设序列返回响应"""
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._calls: list[str] = []
        self._system_prompts: list[str] = []

    async def generate(self, prompt, system_prompt="", max_tokens=4096) -> LLMResponse:
        self._calls.append(prompt)
        self._system_prompts.append(system_prompt)
        if not self._responses:
            return LLMResponse(content="", finish_reason="stop")
        content = self._responses.pop(0)
        return LLMResponse(content=content, finish_reason="stop")

    def stream(self, prompt, system_prompt="", max_tokens=4096) -> AsyncIterator[LLMEvent]:
        raise NotImplementedError

    def configure(self, **kwargs) -> None:
        pass

    @property
    def call_count(self) -> int:
        return len(self._calls)


class FailingLLMProvider:
    """LLM 调用总是失败"""
    async def generate(self, prompt, system_prompt="", max_tokens=4096) -> LLMResponse:
        raise ConnectionError("LLM 服务不可用")

    def stream(self, prompt, system_prompt="", max_tokens=4096) -> AsyncIterator[LLMEvent]:
        raise NotImplementedError

    def configure(self, **kwargs) -> None:
        pass


async def _executor_success(name: str, params: dict) -> str:
    """始终成功的工具执行器"""
    return f"✅ {name} 执行成功: {json.dumps(params, ensure_ascii=False)}"


async def _executor_failing(name: str, params: dict) -> str:
    """对 read_file 抛异常的工具执行器"""
    if name == "read_file":
        raise FileNotFoundError(f"文件不存在: {params.get('path')}")
    return f"✅ {name}: ok"


def _make_react_json(thought: str, action: str, action_input: dict | None = None) -> str:
    """生成 ReAct 格式 JSON 字符串"""
    return json.dumps({
        "thought": thought,
        "action": action,
        "action_input": action_input or {},
    }, ensure_ascii=False)


# ══════════════════════════════════════════════════════════
# 测试用例
# ══════════════════════════════════════════════════════════

class TestReActLoopTermination:
    """ReAct 循环终止条件"""

    @pytest.mark.asyncio
    async def test_finish_terminates_immediately(self):
        """FINISH 动作立即终止，返回 thought 作为答案"""
        llm = MockLLMProvider([
            _make_react_json("任务已完成", FINISH_ACTION),
        ])
        loop = ReActLoop(llm=llm, tool_executor=_executor_success, max_iterations=5)
        result = await loop.run("测试任务")
        assert result.success is True
        assert result.terminated_by == "finish"
        assert result.final_answer == "任务已完成"
        assert result.iterations == 1
        assert llm.call_count == 1

    @pytest.mark.asyncio
    async def test_max_iterations_termination(self):
        """达到最大迭代次数时终止"""
        # 每轮都返回 read_file，从不 FINISH
        llm = MockLLMProvider([
            _make_react_json("读取文件", "read_file", {"path": f"f{i}.py"})
            for i in range(5)
        ])
        loop = ReActLoop(llm=llm, tool_executor=_executor_success, max_iterations=3)
        result = await loop.run("无限读取")
        assert result.terminated_by == "max_iterations"
        assert result.iterations == 3
        assert "最大迭代次数" in result.final_answer
        assert len(result.steps) == 3
        assert result.success is False

    @pytest.mark.asyncio
    async def test_finish_after_tool_observation(self):
        """工具执行后立即 FINISH"""
        llm = MockLLMProvider([
            _make_react_json("先读取文件", "read_file", {"path": "app.py"}),
            _make_react_json("已获取文件内容，任务完成", FINISH_ACTION),
        ])
        loop = ReActLoop(llm=llm, tool_executor=_executor_success, max_iterations=5)
        result = await loop.run("读取并总结")
        assert result.success is True
        assert result.iterations == 2
        assert len(result.steps) == 2
        # 第一步应有观察
        assert result.steps[0].observation
        assert "read_file" in result.steps[0].observation


class TestReActLoopObservation:
    """工具观察反馈机制"""

    @pytest.mark.asyncio
    async def test_observation_feeds_back_to_next_prompt(self):
        """工具结果必须出现在下一轮提示词中"""
        captured_prompts: list[str] = []

        class CapturingLLM(MockLLMProvider):
            async def generate(self, prompt, system_prompt="", max_tokens=4096):
                captured_prompts.append(prompt)
                return await super().generate(prompt, system_prompt, max_tokens)

        llm = CapturingLLM([
            _make_react_json("查找文件", "list_files", {"path": "."}),
            _make_react_json("完成", FINISH_ACTION),
        ])
        loop = ReActLoop(llm=llm, tool_executor=_executor_success, max_iterations=5)
        await loop.run("测试观察反馈")
        # 第二轮提示词应包含第一轮的观察
        assert len(captured_prompts) == 2
        assert "✅ list_files" in captured_prompts[1]

    @pytest.mark.asyncio
    async def test_observation_recorded_in_step(self):
        """步骤对象必须记录观察结果"""
        llm = MockLLMProvider([
            _make_react_json("读文件", "read_file", {"path": "x.py"}),
            _make_react_json("完成", FINISH_ACTION),
        ])
        loop = ReActLoop(llm=llm, tool_executor=_executor_success, max_iterations=5)
        result = await loop.run("测试步骤记录")
        assert result.steps[0].observation
        assert "read_file" in result.steps[0].observation

    @pytest.mark.asyncio
    async def test_initial_context_appears_in_prompt(self):
        """初始上下文应注入到提示词"""
        captured: list[str] = []

        class CaptureLLM(MockLLMProvider):
            async def generate(self, prompt, system_prompt="", max_tokens=4096):
                captured.append(prompt)
                return await super().generate(prompt, system_prompt, max_tokens)

        llm = CaptureLLM([_make_react_json("完成", FINISH_ACTION)])
        loop = ReActLoop(llm=llm, tool_executor=_executor_success, max_iterations=3)
        await loop.run("任务", context="重要背景信息 xyz123")
        assert "xyz123" in captured[0]


class TestReActLoopErrorHandling:
    """错误处理"""

    @pytest.mark.asyncio
    async def test_llm_failure_terminates_with_error(self):
        """LLM 调用失败应立即终止并标记 error"""
        loop = ReActLoop(
            llm=FailingLLMProvider(),
            tool_executor=_executor_success,
            max_iterations=5,
        )
        result = await loop.run("失败任务")
        assert result.terminated_by == "error"
        assert result.success is False
        assert "LLM 调用失败" in result.final_answer
        assert result.error

    @pytest.mark.asyncio
    async def test_tool_failure_records_observation_and_continues(self):
        """工具执行失败不应终止循环，而应记录观察后继续"""
        llm = MockLLMProvider([
            _make_react_json("读取不存在的文件", "read_file", {"path": "missing.py"}),
            _make_react_json("文件不存在，任务完成", FINISH_ACTION),
        ])
        loop = ReActLoop(llm=llm, tool_executor=_executor_failing, max_iterations=5)
        result = await loop.run("测试容错")
        assert result.success is True
        assert result.iterations == 2
        # 第一步观察应包含失败信息
        assert "失败" in result.steps[0].observation or "❌" in result.steps[0].observation

    @pytest.mark.asyncio
    async def test_parse_failure_does_not_terminate(self):
        """LLM 输出无法解析时，不终止，下一轮重试"""
        llm = MockLLMProvider([
            "这不是 JSON 格式，无法解析",
            _make_react_json("修正后完成", FINISH_ACTION),
        ])
        loop = ReActLoop(llm=llm, tool_executor=_executor_success, max_iterations=5)
        result = await loop.run("解析失败重试")
        assert result.success is True
        assert result.iterations == 2
        # 第一步是 parse_error
        assert result.steps[0].action == "(parse_error)"

    @pytest.mark.asyncio
    async def test_parse_failure_max_iterations(self):
        """连续解析失败达到上限后终止"""
        llm = MockLLMProvider(["无效输出"] * 5)
        loop = ReActLoop(llm=llm, tool_executor=_executor_success, max_iterations=3)
        result = await loop.run("全失败")
        assert result.terminated_by == "max_iterations"
        assert all(s.action == "(parse_error)" for s in result.steps)


class TestReActLoopParsing:
    """JSON 解析逻辑"""

    def test_extract_json_from_markdown_block(self):
        text = '文字 ```json\n{"thought":"x","action":"y","action_input":{}}\n```'
        candidates = _extract_json_candidates(text)
        assert len(candidates) >= 1
        assert '"action"' in candidates[0]

    def test_extract_bare_json(self):
        text = '{"thought":"x","action":"y","action_input":{}}'
        candidates = _extract_json_candidates(text)
        assert len(candidates) >= 1

    def test_parse_react_json_success(self):
        json_str = '{"thought":"读取","action":"read_file","action_input":{"path":"x.py"}}'
        step = _try_parse_react_json(json_str, iteration=1)
        assert step is not None
        assert step.thought == "读取"
        assert step.action == "read_file"
        assert step.action_input == {"path": "x.py"}
        assert step.iteration == 1

    def test_parse_react_json_missing_action_returns_none(self):
        json_str = '{"thought":"无动作"}'
        assert _try_parse_react_json(json_str, 1) is None

    def test_parse_react_json_invalid_returns_none(self):
        assert _try_parse_react_json("not json", 1) is None
        assert _try_parse_react_json("", 1) is None

    def test_parse_react_json_action_input_defaults_to_empty(self):
        json_str = '{"thought":"x","action":"FINISH"}'
        step = _try_parse_react_json(json_str, 1)
        assert step is not None
        assert step.action_input == {}

    def test_tool_calls_compat_parsing(self):
        """兼容旧格式 {"tool_calls":[{"name":..., "params":...}]}"""
        json_str = '{"thought":"用旧格式","tool_calls":[{"name":"read_file","params":{"path":"a.py"}}]}'
        step = _try_parse_tool_calls_compat(json_str, iteration=2)
        assert step is not None
        assert step.action == "read_file"
        assert step.action_input == {"path": "a.py"}
        assert step.iteration == 2
        assert step.thought == "用旧格式"

    def test_tool_calls_compat_empty_returns_none(self):
        assert _try_parse_tool_calls_compat('{"tool_calls":[]}', 1) is None
        assert _try_parse_tool_calls_compat("{}", 1) is None
        assert _try_parse_tool_calls_compat("not json", 1) is None

    @pytest.mark.asyncio
    async def test_loop_accepts_tool_calls_format(self):
        """ReActLoop 能处理旧 tool_calls 格式"""
        llm = MockLLMProvider([
            '```json\n{"thought":"旧格式","tool_calls":[{"name":"list_files","params":{}}]}\n```',
            _make_react_json("完成", FINISH_ACTION),
        ])
        loop = ReActLoop(llm=llm, tool_executor=_executor_success, max_iterations=5)
        result = await loop.run("兼容旧格式")
        assert result.success is True
        assert result.steps[0].action == "list_files"


class TestReActLoopPrompt:
    """提示词构建"""

    def test_prompt_includes_task(self):
        loop = ReActLoop(
            llm=MockLLMProvider([_make_react_json("完成", FINISH_ACTION)]),
            tool_executor=_executor_success,
        )
        import asyncio as _a
        prompt = loop._build_prompt("特殊任务 xyz", [], [])
        assert "特殊任务 xyz" in prompt

    def test_prompt_includes_tools(self):
        custom_tools = [{"name": "custom_tool", "params": ["a"], "desc": "自定义工具"}]
        loop = ReActLoop(
            llm=MockLLMProvider([]),
            tool_executor=_executor_success,
            tools=custom_tools,
        )
        prompt = loop._build_prompt("任务", [], [])
        assert "custom_tool" in prompt
        assert "FINISH" in prompt

    def test_prompt_includes_history_steps(self):
        loop = ReActLoop(
            llm=MockLLMProvider([]),
            tool_executor=_executor_success,
        )
        steps = [ReActStep(
            thought="历史思考",
            action="read_file",
            action_input={"path": "h.py"},
            observation="历史观察 abc",
            iteration=1,
        )]
        prompt = loop._build_prompt("任务", steps, [])
        assert "历史思考" in prompt
        assert "read_file" in prompt
        assert "历史观察 abc" in prompt

    @pytest.mark.asyncio
    async def test_system_prompt_used(self):
        """验证系统提示词传给 LLM"""
        llm = MockLLMProvider([_make_react_json("完成", FINISH_ACTION)])
        loop = ReActLoop(llm=llm, tool_executor=_executor_success, max_iterations=3)
        await loop.run("任务")
        # V2 引擎会将仓库地图和记忆库注入系统提示词，因此用包含检查
        assert REACT_SYSTEM_PROMPT in llm._system_prompts[0]


class TestReActResultSerialization:
    """结果序列化"""

    def test_step_to_dict(self):
        step = ReActStep(
            thought="思考",
            action="read_file",
            action_input={"path": "x.py"},
            observation="观察" * 300,  # 600 字符 > 500
            iteration=1,
        )
        d = step.to_dict()
        assert d["iteration"] == 1
        assert d["action"] == "read_file"
        # observation 应截断到 500 字符
        assert len(d["observation"]) == 500

    def test_result_to_dict_success(self):
        result = ReActResult(
            final_answer="答案",
            iterations=2,
            terminated_by="finish",
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["final_answer"] == "答案"
        assert d["iterations"] == 2

    def test_result_to_dict_failure(self):
        result = ReActResult(
            final_answer="失败",
            iterations=0,
            terminated_by="error",
            error="连接错误",
        )
        d = result.to_dict()
        assert d["success"] is False
        assert d["error"] == "连接错误"

    def test_result_success_property(self):
        assert ReActResult("ok", terminated_by="finish").success is True
        assert ReActResult("ok", terminated_by="max_iterations").success is False
        assert ReActResult("ok", terminated_by="error").success is False


class TestReActLoopProtocolConformance:
    """ReActLoop 接受任意 LLMProvider 实现（鸭子类型）"""

    @pytest.mark.asyncio
    async def test_accepts_duck_typed_llm(self):
        """无需继承，只要实现 generate 方法即可"""
        class DuckLLM:
            async def generate(self, prompt, system_prompt="", max_tokens=4096):
                return LLMResponse(content=_make_react_json("done", FINISH_ACTION))
            def stream(self, *a, **kw): ...
            def configure(self, **kw): ...

        loop = ReActLoop(llm=DuckLLM(), tool_executor=_executor_success, max_iterations=3)
        result = await loop.run("鸭子测试")
        assert result.success is True


class TestReActLoopFeedbackIntegration:
    """M4: ReAct 循环集成 FeedbackApplier"""

    def test_build_feedback_context_method_exists(self):
        """_build_feedback_context 方法应存在并返回字符串"""
        loop = ReActLoop(
            llm=MockLLMProvider([]),
            tool_executor=_executor_success,
        )
        ctx = loop._build_feedback_context("测试任务")
        assert isinstance(ctx, str)

    def test_build_prompt_with_feedback_context(self):
        """feedback_context 非空时应注入到 prompt 顶部"""
        loop = ReActLoop(
            llm=MockLLMProvider([]),
            tool_executor=_executor_success,
        )
        feedback = "## 历史失败教训（避免重复犯错）\n- 失败原因: 导入错误 xyz789"
        prompt = loop._build_prompt("任务", [], [], feedback_context=feedback)
        assert "历史失败教训" in prompt
        assert "xyz789" in prompt
        # feedback 应在任务之前
        assert prompt.index("历史失败教训") < prompt.index("# 任务")

    def test_build_prompt_without_feedback_context_default_empty(self):
        """不传 feedback_context 时保持原有行为（向后兼容）"""
        loop = ReActLoop(
            llm=MockLLMProvider([]),
            tool_executor=_executor_success,
        )
        prompt = loop._build_prompt("任务 abc", [], [])
        assert "任务 abc" in prompt
        assert "历史失败教训" not in prompt

    @pytest.mark.asyncio
    async def test_feedback_injected_into_actual_prompt(self, monkeypatch):
        """run() 应将 feedback context 注入实际发给 LLM 的 prompt"""
        captured: list[str] = []

        class CaptureLLM(MockLLMProvider):
            async def generate(self, prompt, system_prompt="", max_tokens=4096):
                captured.append(prompt)
                return await super().generate(prompt, system_prompt, max_tokens)

        llm = CaptureLLM([_make_react_json("完成", FINISH_ACTION)])
        loop = ReActLoop(llm=llm, tool_executor=_executor_success, max_iterations=3)

        # 注入一个伪 feedback context，避免依赖真实 ExperienceBuffer
        monkeypatch.setattr(
            loop, "_build_feedback_context",
            lambda task: "## 历史失败教训（避免重复犯错）\n- 失败原因: 注入标记 marker_456"
        )
        await loop.run("任意任务")
        assert any("marker_456" in p for p in captured)

    def test_build_feedback_context_returns_empty_on_import_error(self, monkeypatch):
        """get_feedback_applier 导入失败时应返回空串（不阻塞 ReAct 循环）"""
        loop = ReActLoop(
            llm=MockLLMProvider([]),
            tool_executor=_executor_success,
        )

        # 模拟导入失败：让 import 语句抛 ImportError
        import builtins
        original_import = builtins.__import__

        def failing_import(name, *args, **kwargs):
            if "feedback_applier" in name:
                raise ImportError("模拟导入失败")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", failing_import)
        ctx = loop._build_feedback_context("任务")
        assert ctx == ""
