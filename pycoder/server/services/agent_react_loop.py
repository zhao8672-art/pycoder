"""P1-5: ReAct (Reasoning + Acting) 循环实现

ReAct 模式让 Agent 在"思考-行动-观察"循环中逐步推进任务：
    1. Thought  — LLM 根据当前观察推理下一步
    2. Action   — 选择并调用一个工具
    3. Observation — 工具执行结果反馈到下一轮推理

相较于旧版 agent_orchestrator 的"一次性多工具调用"模式，ReAct：
    - 每轮只执行一个动作，便于观察与控制
    - 工具结果立即影响下一轮推理（而非批量喂回）
    - 显式 Thought 字段，决策过程可审计
    - 支持 FINISH 动作提前终止

依赖关系:
    - core.ports.LLMProvider  — LLM 调用抽象（P1-4）
    - tool_executor           — 工具执行回调（execute_agent_tool 兼容签名）

用法:
    from pycoder.server.services.agent_react_loop import ReActLoop

    loop = ReActLoop(llm=llm_provider, tool_executor=executor, tools=tools_desc)
    result = await loop.run("重构 app.py 拆分为多模块")
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pycoder.core.ports.llm_provider import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


# 终止动作名 — LLM 输出此动作表示任务完成
FINISH_ACTION = "FINISH"

# ReAct 步骤响应的 JSON Schema
REACT_STEP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "action": {"type": "string", "minLength": 1},
        "action_input": {"type": "object"},
    },
    "required": ["thought", "action", "action_input"],
    "additionalProperties": False,
}


# 工具执行器类型： (name, params) -> 结果字符串
ToolExecutor = Callable[[str, dict], Awaitable[str]]


@dataclass
class ReActStep:
    """单步 ReAct 记录 — 思考 / 行动 / 输入 / 观察"""

    thought: str
    action: str
    action_input: dict
    observation: str = ""
    iteration: int = 0

    def to_dict(self) -> dict:
        return {
            "iteration": self.iteration,
            "thought": self.thought,
            "action": self.action,
            "action_input": self.action_input,
            "observation": self.observation[:500],
        }


@dataclass
class ReActResult:
    """ReAct 循环执行结果"""

    final_answer: str
    steps: list[ReActStep] = field(default_factory=list)
    iterations: int = 0
    terminated_by: str = "max_iterations"  # finish | max_iterations | error
    error: str = ""

    @property
    def success(self) -> bool:
        return self.terminated_by == "finish" and not self.error

    def to_dict(self) -> dict:
        return {
            "final_answer": self.final_answer,
            "iterations": self.iterations,
            "terminated_by": self.terminated_by,
            "success": self.success,
            "error": self.error,
            "steps": [s.to_dict() for s in self.steps],
        }


"""
沉思反思系统提示 — 对标智谱 Agent 的 Rumination 推理机制

注入到 ReAct 循环中，强制 Agent 在执行前/执行中/执行后触发自我反思。
"""
RUMINATION_SYSTEM_PROMPT = """## 沉思反思规则（强制遵守）

你必须使用 **三步反思机制** 驱动决策，而不是线性思考。

### 执行前反思（每轮必须）
在输出当前步骤之前，先自我提问：
1. 我对当前观察的理解是否正确？有无遗漏关键信息？
2. 这一步会不会引入新问题？最可能的失败点是什么？
3. 有没有更简单的替代方案？

### 执行中复盘（每 3 步触发一次）
当历史步骤数为 3 的倍数时，你必须在 thought 中先回答：
1. 当前进展是否仍对原始目标？有没有跑偏？
2. 最近几步是否有冗余？是否可以合并简化？
3. 前面的输出/数据是否准确？需不需要重新验证？

### 执行后总结（FINISH 时）
在 FINISH 步骤的 thought 中必须包含：
1. 原始目标：是否完全达成？
2. 边界覆盖：边缘情况/错误处理是否考虑？
3. 经验沉淀：哪些模式可以记录为经验供后续复用？
"""


REACT_SYSTEM_PROMPT = RUMINATION_SYSTEM_PROMPT + """

你是 ReAct 模式的 AI 编程助手。请严格按以下 JSON 格式输出每一步决策：

```json
{
  "thought": "对当前观察的推理，决定下一步",
  "action": "工具名或 FINISH",
  "action_input": {工具参数}
}
```

规则：
1. 每次只输出一个 JSON 对象（一个动作）
2. 任务完成时 action 必须为 "FINISH"，thought 字段填写最终答案
3. action_input 必须是 JSON 对象（{}），FINISH 时留空 {}
4. 不要输出 JSON 以外的文字（不要 Markdown 解释）
5. 根据工具观察结果决定是否继续或结束
6. **禁止使用 XML 标签**（如 <tool>），仅支持 JSON 格式

## 示例

用户：读取 config.yaml 的内容

```json
{
  "thought": "需要读取配置文件，调用 read_file 工具",
  "action": "read_file",
  "action_input": {"path": "config.yaml"}
}
```

工具返回内容后，若已获取所需信息：

```json
{
  "thought": "已读取 config.yaml，任务完成",
  "action": "FINISH",
  "action_input": {}
}
```
"""


class ReActLoop:
    """ReAct 循环：思考 → 行动 → 观察 → 思考...

    Attributes:
        llm: LLM 调用端口（LLMProvider）
        tool_executor: 工具执行回调，签名 (name: str, params: dict) -> str
        tools: 可用工具描述列表，注入到提示词
        max_iterations: 最大循环次数
    """

    def __init__(
        self,
        llm: LLMProvider,
        tool_executor: ToolExecutor,
        *,
        tools: list[dict] | None = None,
        max_iterations: int = 15,
        system_prompt: str = REACT_SYSTEM_PROMPT,
        session_id: str = "",
    ) -> None:
        self.llm = llm
        self.tool_executor = tool_executor
        self.tools = tools or _DEFAULT_TOOLS
        self.max_iterations = max_iterations
        self._system_prompt = system_prompt
        self._session_id = session_id

    async def run(self, task: str, context: str = "") -> ReActResult:
        """执行 ReAct 循环直到 FINISH 或达到迭代上限

        Args:
            task: 用户任务描述
            context: 初始上下文（如相关文件内容）

        Returns:
            ReActResult — 包含最终答案与所有步骤
        """
        steps: list[ReActStep] = []
        observations = [context] if context else []

        # P1: 注入会话级关键事实（历史决策/文件引用/错误模式）
        fact_context = self._load_fact_context()
        if fact_context:
            observations.append(fact_context)

        # M4: 注入历史失败教训，避免重复犯错（与 agent_orchestrator 一致）
        feedback_context = self._build_feedback_context(task)

        # P0: 注入 RepoMap 仓库地图 + Memory Bank 项目记忆
        augmented_system_prompt = self._system_prompt
        try:
            from pycoder.python.repomap import get_repo_map
            from pycoder.server.memory_bank import get_memory_bank

            repo_map = get_repo_map()
            chat_files = self._chat_files if hasattr(self, "_chat_files") else []
            repo_context = repo_map.get_repo_map(chat_files=chat_files)
            if repo_context:
                augmented_system_prompt += f"\n\n{repo_context}"

            memory_context = get_memory_bank().load_context_for_prompt(max_tokens=1500)
            if memory_context:
                augmented_system_prompt += f"\n\n{memory_context}"
        except (ImportError, LookupError, OSError) as e:
            logger.debug("context_injection_skipped reason=%s", e)

        # 动态反思间隔：错误率高时更频繁反思
        error_count = 0  # 累计错误次数（解析失败 + 工具失败）

        for i in range(1, self.max_iterations + 1):
            # ── 动态沉思反思：根据错误率调整反思频率 ──
            rumination_interval = self._compute_rumination_interval(steps, error_count)
            if len(steps) > 0 and len(steps) % rumination_interval == 0:
                rumination_prompt = (
                    f"\n## 🧠 执行中反思（第 {len(steps)} 步触发，间隔={rumination_interval}）\n"
                    "请在 thought 中回答以下问题后再输出下一步：\n"
                    "1. 当前进展是否仍对齐原始目标？\n"
                    "2. 最近几步是否有冗余操作？\n"
                    "3. 前面的输出是否准确？\n"
                    "然后继续按 ReAct 格式输出。"
                )
                observations.append(rumination_prompt)

            try:
                prompt = self._build_prompt(task, steps, observations, feedback_context)
                response = await self.llm.generate(
                    prompt=prompt,
                    system_prompt=augmented_system_prompt,
                    max_tokens=2048,
                )
            except (ConnectionError, TimeoutError, RuntimeError, OSError) as e:
                logger.warning("react_llm_failed iteration=%d error=%s", i, e)
                return ReActResult(
                    final_answer=f"LLM 调用失败: {e}",
                    steps=steps,
                    iterations=i - 1,
                    terminated_by="error",
                    error=str(e),
                )

            step = self._parse_step(response, iteration=i)
            if step is None:
                # 解析失败：把原始输出作为观察，让下一轮重试
                error_count += 1
                logger.warning(
                    "react_parse_failed iteration=%d preview=%.200s", i, response.content
                )
                observations.append(
                    f"⚠️ 上一轮输出无法解析为 ReAct 步骤，请严格按 JSON 格式输出。原始输出: {response.content[:300]}"
                )
                steps.append(
                    ReActStep(
                        thought="(解析失败)",
                        action="(parse_error)",
                        action_input={},
                        observation="输出格式错误",
                        iteration=i,
                    )
                )
                continue

            steps.append(step)

            if step.action == FINISH_ACTION:
                logger.info("react_finished iterations=%d thought_len=%d", i, len(step.thought))
                self._persist_facts(task, steps)
                return ReActResult(
                    final_answer=step.thought,
                    steps=steps,
                    iterations=i,
                    terminated_by="finish",
                )

            # 执行工具
            try:
                observation = await self.tool_executor(step.action, step.action_input)
            except (TimeoutError, ValueError, KeyError, RuntimeError, OSError) as e:
                error_count += 1
                observation = f"❌ 工具执行失败: {e}"
                logger.warning("react_tool_failed action=%s error=%s", step.action, e)

            step.observation = observation
            observations.append(observation)
            logger.info(
                "react_step iteration=%d action=%s obs_len=%d", i, step.action, len(observation)
            )

        # 达到上限
        logger.warning("react_max_iterations max=%d", self.max_iterations)
        return ReActResult(
            final_answer=f"达到最大迭代次数 {self.max_iterations}，未能完成",
            steps=steps,
            iterations=self.max_iterations,
            terminated_by="max_iterations",
        )

    def _build_prompt(
        self,
        task: str,
        steps: list[ReActStep],
        observations: list[str],
        feedback_context: str = "",
    ) -> str:
        """构建 ReAct 提示词 — 包含任务、可用工具、历史步骤"""
        lines: list[str] = []
        if feedback_context:
            lines.append(feedback_context)
        lines.append("# 任务\n" + task)

        lines.append("\n# 可用工具\n")
        for t in self.tools:
            params = ", ".join(t.get("params", []))
            lines.append(f"- {t['name']}({params}): {t.get('desc', '')}")
        lines.append(f"- {FINISH_ACTION}(): 任务完成，thought 字段填写最终答案")

        if steps:
            lines.append("\n# 历史步骤\n")
            for s in steps:
                lines.append(f"## 第{s.iteration}步")
                lines.append(f"Thought: {s.thought}")
                lines.append(f"Action: {s.action}")
                lines.append(f"Action Input: {json.dumps(s.action_input, ensure_ascii=False)}")
                if s.observation:
                    lines.append(f"Observation: {s.observation[:800]}")
                lines.append("")

        if observations and observations[0]:
            lines.append("\n# 初始上下文\n" + observations[0][:1500])

        lines.append("\n# 请输出下一步（严格 JSON 格式）")
        return "\n".join(lines)

    def _build_feedback_context(self, task: str) -> str:
        """M4: 构建历史失败教训上下文（与 agent_orchestrator 一致）

        延迟导入避免循环依赖；任何失败都降级为空串（不阻塞 ReAct 循环）。
        """
        try:
            from pycoder.capabilities.self_evo.learning.feedback_applier import get_feedback_applier

            return get_feedback_applier().build_context_for_task("react", task)
        except (ImportError, RuntimeError, OSError, ValueError, KeyError, TypeError) as e:
            logger.warning("react_feedback_inject_failed error=%s", e)
            return ""

    def _load_fact_context(self) -> str:
        """P1: 加载会话级关键事实，注入到初始上下文

        失败时降级为空串，不影响 ReAct 主流程。
        """
        if not self._session_id:
            return ""
        try:
            from pycoder.server.services.agent_memory import get_memory_manager

            return get_memory_manager().build_fact_context(self._session_id)
        except (ImportError, RuntimeError, OSError, ValueError) as e:
            logger.debug("react_fact_load_failed error=%s", e)
            return ""

    def _persist_facts(self, task: str, steps: list[ReActStep]) -> None:
        """P1: 从 ReAct 执行历史提取并持久化关键事实

        将 task 描述和各步骤的 thought/observation 转换为消息格式，
        交给 AgentMemoryManager 提取事实并持久化。
        """
        if not self._session_id or not steps:
            return
        try:
            from pycoder.server.services.agent_memory import get_memory_manager

            # 将 ReAct 步骤转为消息格式供事实提取
            messages: list[dict] = [{"role": "user", "content": task}]
            for s in steps:
                if s.thought:
                    messages.append({"role": "assistant", "content": s.thought})
                if s.observation:
                    messages.append(
                        {
                            "role": "tool",
                            "content": str(s.observation)[:500],
                        }
                    )
            manager = get_memory_manager()
            saved = manager.persist_facts(self._session_id, messages)
            if saved:
                logger.info("react_facts_persisted session=%s count=%d", self._session_id, saved)
        except (ImportError, RuntimeError, OSError, ValueError) as e:
            logger.debug("react_fact_persist_failed error=%s", e)

    def _compute_rumination_interval(self, steps: list, error_count: int) -> int:
        """根据错误率动态计算反思间隔

        策略:
        - 零错误：间隔 5 步（低频反思，减少 token 浪费）
        - 低错误率（<20%）：间隔 3 步（默认频率）
        - 高错误率（>=20%）：间隔 2 步（高频反思，及时纠偏）
        - 持续错误（>=3 次）：间隔 1 步（每步反思）

        Args:
            steps: 已执行的步骤列表
            error_count: 累计错误次数

        Returns:
            反思间隔（步数）
        """
        total_steps = len(steps)
        if total_steps == 0:
            return 5  # 默认间隔

        error_rate = error_count / total_steps

        if error_count >= 3:
            return 1  # 持续错误：每步反思
        elif error_rate >= 0.2:
            return 2  # 高错误率
        elif error_rate > 0:
            return 3  # 低错误率
        else:
            return 5  # 零错误

    def _parse_step(self, response: LLMResponse, iteration: int) -> ReActStep | None:
        """解析 LLM 响应为 ReActStep

        支持:
            1. 纯 JSON: {"thought":..., "action":..., "action_input":{...}}
            2. Markdown 代码块包裹的 JSON
            3. 兼容旧 tool_calls 格式（取第一个）

        Returns:
            ReActStep 或 None（解析失败）
        """
        text = (response.content or "").strip()
        if not text:
            return None

        candidates = _extract_json_candidates(text)
        for candidate in candidates:
            step = _try_parse_react_json(candidate, iteration)
            if step:
                return step

        # 兼容旧格式 {"tool_calls": [...]}
        for candidate in candidates:
            step = _try_parse_tool_calls_compat(candidate, iteration)
            if step:
                return step

        return None


# ══════════════════════════════════════════════════════════
# 默认工具描述（与 agent_tools.py 保持一致）
# ══════════════════════════════════════════════════════════

_DEFAULT_TOOLS: list[dict] = [
    {"name": "read_file", "params": ["path"], "desc": "读取工作区内文件"},
    {"name": "write_file", "params": ["path", "content"], "desc": "写入文件"},
    {"name": "patch_file", "params": ["path", "search", "replace"], "desc": "精准替换代码段"},
    {"name": "search_code", "params": ["query", "file_type?"], "desc": "搜索代码"},
    {"name": "run_command", "params": ["command"], "desc": "执行白名单命令"},
    {"name": "run_terminal", "params": ["command"], "desc": "执行终端命令"},
    {"name": "execute_python", "params": ["code"], "desc": "沙箱执行 Python"},
    {"name": "list_files", "params": ["path?", "depth?"], "desc": "列出目录"},
    {"name": "git_diff", "params": ["file?"], "desc": "查看 Git 变更"},
    {"name": "git_status", "params": [], "desc": "查看 Git 状态"},
    {"name": "git_add", "params": ["path"], "desc": "Git 暂存文件"},
    {"name": "git_commit", "params": ["message"], "desc": "Git 提交"},
    {"name": "git_push", "params": [], "desc": "Git 推送"},
    {"name": "git_log", "params": [], "desc": "查看提交历史"},
    {"name": "install_package", "params": ["package"], "desc": "安装 Python 包"},
    {"name": "search_package", "params": ["query"], "desc": "搜索 Python 包"},
    {"name": "ensure_tool", "params": ["tool"], "desc": "确保工具已安装"},
    {"name": "list_agent_configs", "params": [], "desc": "列出系统 Agent 配置"},
]


# ══════════════════════════════════════════════════════════
# JSON 解析辅助
# ══════════════════════════════════════════════════════════


def _extract_json_candidates(text: str) -> list[str]:
    """从文本中提取 JSON 候选字符串（代码块 + 裸 JSON）"""
    import re

    candidates: list[str] = []

    # Markdown ```json ... ``` 或 ``` ... ```
    for m in re.finditer(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL):
        candidates.append(m.group(1).strip())

    # 裸 JSON：第一个 { 到最后一个 }
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first : last + 1])

    return candidates


def _try_parse_react_json(json_str: str, iteration: int) -> ReActStep | None:
    """尝试按 ReAct JSON Schema 解析"""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    if "action" not in data or "thought" not in data:
        return None

    action_input = data.get("action_input", {})
    if not isinstance(action_input, dict):
        action_input = {}

    return ReActStep(
        thought=str(data["thought"]),
        action=str(data["action"]),
        action_input=action_input,
        iteration=iteration,
    )


def _try_parse_tool_calls_compat(json_str: str, iteration: int) -> ReActStep | None:
    """兼容旧格式：{"tool_calls": [{"name":..., "params":...}]}"""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    calls = data.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        return None
    first = calls[0]
    if not isinstance(first, dict) or "name" not in first:
        return None

    return ReActStep(
        thought=str(data.get("thought", "")),
        action=str(first["name"]),
        action_input=first.get("params", {}),
        iteration=iteration,
    )
