"""
统一执行管线 — 所有 AI 任务的唯一执行路径

设计原则:
1. CHAT/HERMES/AGENT 三模式共享同一套 5 阶段流水线
2. 优先使用 DeepSeek Native Function Calling，FC 失败时自动降级到文本 JSON 解析
3. 每阶段自动发射进度事件
4. 完成后生成结构化执行报告
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from pycoder.bus.protocol import TrustLevel

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# 执行配置
# ══════════════════════════════════════════════════════════


@dataclass
class ExecutionConfig:
    """三合一的执行配置"""
    name: str
    max_iterations: int
    tool_timeout: int
    max_concurrent_tools: int
    enable_rumination: bool
    system_prompt: str
    max_empty_retries: int = 2

    # 进度阶段定义
    stages: list[dict] = field(default_factory=list)


# ══════════════════════════════════════════════════════════
# 三种策略定义
# ══════════════════════════════════════════════════════════

CHAT_CONFIG = ExecutionConfig(
    name="chat",
    max_iterations=1,
    tool_timeout=15,
    max_concurrent_tools=3,
    enable_rumination=False,
    max_empty_retries=0,
    system_prompt=(
        "你是 PyCoder 编程助手。"
        "你可以用 JSON 工具调用来执行实际操作。"
        "格式: {\"tool_calls\": [{\"name\": \"read_file\", \"params\": {\"path\": \"xxx\"}}]}\n"
        "对于纯知识问答直接文字回复。"
        "对于需要操作文件/命令/代码的任务，必须调用工具执行。"
    ),
    stages=[
        {"id": "intent", "label": "🔍 意图解析", "desc": "分析用户意图"},
        {"id": "llm", "label": "🧠 AI 生成", "desc": "调用大模型生成回复"},
        {"id": "done", "label": "✅ 完成", "desc": "回复生成完毕"},
    ],
)

HERMES_CONFIG = ExecutionConfig(
    name="hermes",
    max_iterations=10,
    tool_timeout=30,
    max_concurrent_tools=5,
    enable_rumination=False,
    max_empty_retries=3,
    system_prompt=(
        "你是 PyCoder Hermes 执行器。你必须通过调用函数工具来实际执行任务。\n\n"
        "## 可用工具（必须使用）\n"
        "- read_file / write_file / list_files — 文件操作\n"
        "- run_terminal — 执行命令\n"
        "- search — 搜索文本\n"
        "- git_status / git_log — Git 操作\n"
        "- execute_python — 执行 Python 代码\n"
        "- python_env — 环境信息\n"
        "- code_review — 代码审查\n"
        "- security_scan — 安全扫描\n"
        "- dependency_analysis — 依赖分析\n\n"
        "## 🚨 强制规则\n"
        "1. 每次回复必须以 JSON 格式输出工具调用\n"
        '2. 格式: {"tool_calls": [{"name": "工具名", "params": {}}]}\n'
        "3. 禁止输出纯文字描述而不调用工具\n"
        "4. 工具执行完毕后，输出分析总结报告\n"
    ),
    stages=[
        {"id": "intent", "label": "🔍 意图解析", "desc": "分析用户意图"},
        {"id": "route", "label": "🔄 模式路由", "desc": "调度 Hermes 模式"},
        {"id": "llm", "label": "🧠 AI 执行", "desc": "Hermes 5步工作法"},
        {"id": "plugin", "label": "🔧 后台插件", "desc": "执行匹配插件"},
        {"id": "merge", "label": "📋 结果归集", "desc": "整合输出"},
        {"id": "done", "label": "✅ 完成", "desc": "任务执行完毕"},
    ],
)

AGENT_CONFIG = ExecutionConfig(
    name="agent",
    max_iterations=50,
    tool_timeout=60,
    max_concurrent_tools=8,
    enable_rumination=True,
    max_empty_retries=2,
    system_prompt=(
        "你是 PyCoder 全自主 Agent。面对任务必须调用工具一步步完成。\n\n"
        '## 🔴 必须遵守\n'
        '1. 每次回复必须以 JSON 格式输出工具调用\n'
        '2. 格式: {"tool_calls": [{"name": "工具名", "params": {}}]}\n'
        "3. 不可输出纯文字描述而不调用工具\n"
        '4. 任务完成后输出总结报告\n'
    ),
    stages=[
        {"id": "intent", "label": "🔍 意图解析", "desc": "分析用户意图"},
        {"id": "route", "label": "🔄 模式路由", "desc": "调度 Agent 模式"},
        {"id": "llm", "label": "🧠 AI 执行", "desc": "Agent 多轮迭代"},
        {"id": "plugin", "label": "🔧 后台插件", "desc": "执行匹配插件"},
        {"id": "merge", "label": "📋 结果归集", "desc": "整合输出"},
        {"id": "done", "label": "✅ 完成", "desc": "任务执行完毕"},
    ],
)

CONFIG_MAP: dict[str, ExecutionConfig] = {
    "chat": CHAT_CONFIG,
    "hermes": HERMES_CONFIG,
    "agent": AGENT_CONFIG,
}


def get_execution_config(mode: str) -> ExecutionConfig:
    """按模式获取执行配置"""
    return CONFIG_MAP.get(mode, CHAT_CONFIG)


# ══════════════════════════════════════════════════════════
# P0: 按模式动态选择工具集
# ══════════════════════════════════════════════════════════

TOOL_TIERS: dict[str, list[str] | None] = {
    "chat": [
        "read_file", "write_file", "list_files", "search",
        "run_terminal", "git_status", "execute_python", "python_env",
    ],
    "hermes": [
        "read_file", "write_file", "list_files", "search",
        "run_terminal", "git_status", "git_log",
        "execute_python", "python_env",
        "code_review", "format_code", "docker_status",
        "security_scan", "dependency_analysis",
    ],
    "agent": None,  # 全部 48 个工具
}


def get_tool_names_for_mode(mode: str) -> list[str] | None:
    """获取指定模式的工具名称列表（None = 全部）"""
    return TOOL_TIERS.get(mode)


# ══════════════════════════════════════════════════════════
# 执行管线
# ══════════════════════════════════════════════════════════


class ExecutionPipeline:
    """五阶段统一执行管线 — 所有模式共用"""

    def __init__(self, config: ExecutionConfig):
        self.config = config
        self.tool_calls: list[dict] = []
        self.written_files: list[str] = []
        self._start_time = time.monotonic()
        self._last_had_tools = False
        self._empty_retries = 0
        self._last_yield_time = 0.0  # 上次 yield 时间戳（用于 keepalive）

    async def _maybe_keepalive(self, phase: str = "llm"):
        """检查并发送 keepalive 心跳（如果超过 12 秒未 yield）"""
        now = time.monotonic()
        if now - self._last_yield_time > 12:
            self._last_yield_time = now
            return {
                "type": "progress",
                "phase": phase,
                "stage": "⏳ AI 推理中...",
                "current_step": 2,
                "total_steps": len(self.config.stages),
                "percent": 55,
                "elapsed_seconds": int(now - self._start_time),
                "eta_seconds": 0,
                "milestones": [],
            }
        return None

    async def execute(
        self,
        message: str,
        bridge,  # ChatBridge
        history_context: str = "",
    ) -> AsyncIterator[dict]:
        """主执行循环

        Yields:
            → agent_status / progress / token / tool_result / done
        """
        strategy = self.config

        # ── Stage 1: Context Assembly ──
        from pycoder.prompts.cache_rules import inject_cache_rules
        bridge.config.system_prompt = inject_cache_rules(
            strategy.system_prompt, lang="zh"
        )
        effective_message = message
        if history_context:
            effective_message = (
                f"[对话历史回顾]\n{history_context}\n\n[当前消息] {message}"
            )

        yield {
            "type": "agent_status",
            "status": "started",
            "message": (
                f"🔍 意图解析: {strategy.name.upper()} 模式"
            ),
        }
        yield {
            "type": "progress",
            "phase": "intent",
            "stage": strategy.stages[0]["label"],
            "current_step": 0,
            "total_steps": len(strategy.stages),
            "percent": 15,
            "elapsed_seconds": 0,
            "eta_seconds": 0,
            "milestones": [],
        }
        await asyncio.sleep(0)

        # P0: 根据模式选择工具集
        tool_names = get_tool_names_for_mode(strategy.name)
        if tool_names:
            logger.info(
                "pipeline_tool_tier mode=%s tool_count=%d",
                strategy.name,
                len(tool_names),
            )

        # ── Stage 2-4: LLM Invoke → Parse → Execute ──
        full_content = ""
        total_tokens = 0
        iter_count = 0

        for iter_count in range(1, strategy.max_iterations + 1):
            pct = int(iter_count / strategy.max_iterations * 100)

            # 进度: 思考中
            yield {
                "type": "progress",
                "phase": "llm",
                "stage": f"🤖 {strategy.name.upper()} 执行中 ({iter_count}/{strategy.max_iterations})",
                "current_step": 2,
                "total_steps": len(strategy.stages),
                "percent": min(50 + pct // 3, 70),
                "elapsed_seconds": 0,
                "eta_seconds": 0,
                "milestones": [],
            }

            # 构建 prompt
            if iter_count == 1:
                if strategy.name != "chat":
                    prompt = (
                        f"请直接输出 JSON 工具调用来完成任务:\n\n"
                        f"{effective_message}\n\n"
                    )
                else:
                    prompt = effective_message
                if strategy.enable_rumination:
                    prompt += "\n\n请先分析需求，再逐步执行。每3步进行一次反思复盘。"
            elif self._last_had_tools:
                prompt = (
                    "以上是工具执行结果。如需继续请输出 JSON 工具调用。"
                    "已完成请直接输出总结。"
                )
            else:
                prompt = (
                    "【紧急】你上一轮没有调用任何工具！"
                    '你必须以 JSON 格式输出工具调用: '
                    '{"tool_calls": [{"name": "工具名", "params": {}}]}'
                )

            # 反思复盘
            if strategy.enable_rumination and iter_count > 1 and iter_count % 3 == 0:
                prompt += (
                    f"\n\n---\n### 反思复盘（第{iter_count // 3}次）\n"
                    "1. 当前进展是否对齐原始目标？\n"
                    "2. 最近几步是否有冗余或错误？\n"
                    "3. 有没有更简单的替代方案？\n"
                )

            # 调用 LLM (Native FC + 文本兜底)
            response_text = ""
            has_tool_calls = False
            tool_call_names: list[str] = []

            # 重置 keepalive 计时器
            self._last_yield_time = time.monotonic()

            try:
                async for ev in bridge.chat_stream(
                    prompt, tool_names=tool_names
                ):
                    if ev.event_type == "token":
                        self._last_yield_time = time.monotonic()
                        response_text += ev.content
                        total_tokens += len(ev.content)
                        yield {"type": "token", "data": ev.content,
                               "content": ev.content}
                        if "🔧" in ev.content:
                            tn = ev.content.replace(
                                "🔧 执行 ", ""
                            ).strip()[:40]
                            tool_call_names.append(tn)
                            has_tool_calls = True
                    elif ev.event_type == "reasoning":
                        # reasoning 期间也可能长时间无 yield
                        yield {"type": "reasoning", "content": ev.content}
                    elif ev.event_type == "done":
                        response_text = ev.content or response_text
                    elif ev.event_type == "error":
                        yield {"type": "error", "message": ev.content}
                        return
            except Exception as e:
                yield {"type": "error",
                       "message": f"LLM 调用失败: {str(e)[:200]}"}
                return

            self._last_had_tools = has_tool_calls
            full_content += response_text

            if not response_text:
                logger.warning(
                    "pipeline_empty_response iteration=%d",
                    iter_count,
                )
                if self._empty_retries < strategy.max_empty_retries:
                    self._empty_retries += 1
                    continue
                break

            # 完成检测（无工具调用时）
            if not has_tool_calls:
                # CHAT 模式：有实质内容就直接接受
                if strategy.name == "chat":
                    break
                # AGENT/HERMES：有实质内容但无工具调用 → 根据迭代次数和重试判断
                has_substance = len(response_text) > 100
                has_retries_left = self._empty_retries < strategy.max_empty_retries
                if has_substance and not has_retries_left:
                    break
                if has_retries_left:
                    self._empty_retries += 1
                    yield {
                        "type": "agent_status",
                        "status": "working",
                        "message": f"⚠️ AI 未调用工具，第 {self._empty_retries} 次强化重试...",
                    }
                    continue
                break

        # ── Stage 5: Result Assembly ──
        elapsed = time.monotonic() - self._start_time
        tool_count = full_content.count("🔧 执行")
        summary_line = (
            f"⚡ 工具调用 {tool_count} 次"
            if tool_count > 0
            else ""
        )
        time_line = f"⏱ 耗时 {elapsed:.1f}s"
        summary = ""
        if summary_line or time_line:
            parts = [p for p in [summary_line, time_line] if p]
            summary = " | ".join(parts)

        yield {
            "type": "progress",
            "phase": "done",
            "stage": f"✅ {strategy.name.upper()} 执行完成",
            "current_step": len(strategy.stages),
            "total_steps": len(strategy.stages),
            "percent": 100,
            "elapsed_seconds": int(elapsed),
            "eta_seconds": 0,
            "milestones": [],
        }

        final_content = full_content.rstrip()
        if summary:
            final_content += (
                f"\n\n---\n📊 执行摘要\n{summary}"
            )

        yield {
            "type": "done",
            "content": final_content,
            "v2_engine": True,
            "tool_calls_count": tool_count,
            "duration_ms": int(elapsed * 1000),
        }

        yield {
            "type": "agent_status",
            "status": "completed",
            "message": (
                f"✅ {strategy.name.upper()} 完成"
                f" ({len(full_content)} 字符)"
                + (f", {tool_count} 次工具调用" if tool_count else "")
            ),
        }
