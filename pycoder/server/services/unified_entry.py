"""
PyCoder 统一聊天入口 — 全局主控调度Agent (UnifiedEntryAgent)

架构:
    UnifiedEntryAgent 是系统全局最高调度中枢，所有用户消息必经此处。
    它协调以下子模块完成从输入到输出的完整链路:

    User Input → IntentParser → CommandBeautifier → ModeRouter → [Chat / Hermes / Agent] → ResultMerger → User Output
                                                         ↑
                                                   SystemMonitor（全链路监测）

职责:
    1. 接收所有用户对话请求
    2. 委托 IntentParser 解析意图
    3. 委托 CommandBeautifier 标准化指令
    4. 委托 ModeRouter 并行/串行调度三种工作模式
    5. 委托 ResultMerger 归集整合多模式结果
    6. 通过 SystemMonitor 实时监测故障并自修复

设计原则:
    - 自身不直接调用 LLM（除非进行意图分类）
    - 所有 LLM 调用都委托给三种工作模式的 ChatBridge 完成
    - 结果格式化为用户提示词要求的固定结构
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class TaskCategory(Enum):
    """任务分类"""
    CHAT = "chat"         # A类: 简单问答、概念解释、闲聊 → 普通聊天模式
    HERMES = "hermes"      # B类: 工具操作、文件修改、诊断修复 → Hermes 结构化工作法
    AGENT = "agent"       # C类: 系统工程、多文件开发、架构设计 → 多Agent团队协作


@dataclass
class ParsedIntent:
    """意图解析结果"""
    raw_input: str
    surface_text: str           # 表层文字内容
    core_need: str              # 核心真实需求
    ambiguity: str = ""         # 信息缺失/歧义说明
    task_category: TaskCategory = TaskCategory.CHAT
    beautified_command: str = ""  # 标准化后的任务指令
    sub_intents: list[ParsedIntent] = field(default_factory=list)
    has_risk: bool = False       # 是否包含高风险操作
    risk_description: str = ""   # 风险说明


@dataclass
class ModeResult:
    """单模式执行结果"""
    mode: TaskCategory
    success: bool
    content: str = ""
    error: str = ""
    duration_ms: int = 0
    retries: int = 0


@dataclass
class UnifiedResult:
    """统一入口最终结果"""
    original_input: str
    intent: ParsedIntent
    dispatched_modes: list[str]
    mode_results: list[ModeResult]
    merged_output: str
    system_issues: list[str]
    risk_warnings: list[str]


# ── 轻量意图分类规则（规则优先，省 Token）──

_TASK_PATTERNS: list[tuple[str, TaskCategory, str]] = [
    # ── B类: 工具操作（hermes）──
    ("修改|更改|改成|修复|修复bug|添加|增加|删除|更新|优化|重构|改进", TaskCategory.HERMES,
     "任务涉及代码/文件修改，需要结构化执行"),
    ("安装|卸载|配置|设置|运行|执行|测试|调试|编译", TaskCategory.HERMES,
     "任务涉及工具/环境操作，需要执行步骤"),
    ("写一个|生成一个|创建一个|新建一个", TaskCategory.HERMES,
     "任务涉及代码生成，需要产出文件"),
    ("检查|诊断|分析|查看|排查|审查|review", TaskCategory.HERMES,
     "任务涉及检查/分析操作，需要读取上下文"),
    ("提交|commit|push|pull|merge|branch|stash", TaskCategory.HERMES,
     "任务涉及 Git 操作"),

    # ── C类: 系统工程（agent）──
    ("开发|搭建|构建|实现.*系统|实现.*项目|实现.*平台|实现.*应用|实现.*服务", TaskCategory.AGENT,
     "任务涉及完整系统开发，需要多角色协作"),
    ("设计.*架构|规划.*项目|整体.*重构|全栈|全部重写", TaskCategory.AGENT,
     "任务涉及架构设计/全面重构，需要团队协作"),
    ("多.*步骤|复杂.*任务|完整.*流程|全套|整合", TaskCategory.AGENT,
     "任务涉及多步骤复杂操作，需要多 Agent 协作"),
    ("从零|从头|搭建.*框架|初始化.*项目|scaffold", TaskCategory.AGENT,
     "任务涉及项目初始化搭建，需要完整规划"),

    # ── A类: 简单问答（chat）── 默认兜底
    ("问|什么是|解释|什么意思|为什么|如何理解|介绍|是什么|区别|对比|比较", TaskCategory.CHAT,
     "纯知识问答，无需工具操作"),
    ("能不能|可以吗|怎么办|有没有|是否|推荐|建议|评价|怎么样", TaskCategory.CHAT,
     "咨询/建议类，无需执行操作"),
]


def _classify_intent(message: str) -> tuple[TaskCategory, str]:
    """基于规则分类用户意图。

    返回 (task_category, reason)
    """
    # 检查消息长度——简短问候默认 chat
    if len(message.strip()) < 8:
        return TaskCategory.CHAT, "短消息，判断为简单问答"

    for pattern, category, reason in _TASK_PATTERNS:
        if re.search(pattern, message):
            return category, reason

    # 包含文件路径或代码语法的默认为 B 类
    if re.search(r'\.py|\.ts|\.js|\.json|\.html|\.css|\.md', message):
        return TaskCategory.HERMES, "消息涉及具体文件，判断为工具操作"

    # 长消息默认 hermes（大概率是具体任务）
    if len(message) > 100:
        return TaskCategory.HERMES, "长消息，判断为有具体操作需求"

    return TaskCategory.CHAT, "默认简单问答"


class UnifiedEntryAgent:
    """PyCoder 统一对话入口 — 全局最高调度权限

    使用方式:
        agent = UnifiedEntryAgent(model="deepseek-chat", api_key="sk-xxx")
        result = await agent.process("帮我写一个 FastAPI 用户管理接口")

    流式方式:
        async for event in agent.process_stream("用户消息"):
            # event: {"type": "unified_intent/content/done", ...}
            await ws.send_json(event)
    """

    def __init__(self, model: str = "deepseek-chat", api_key: str = ""):
        self.model = model
        self.api_key = api_key
        self._mode_status: dict[str, bool] = {
            "chat": True,
            "hermes": True,
            "agent": True,
        }
        self._start_time = time.monotonic()

    # ══════════════════════════════════════════════════════════
    # 主入口
    # ══════════════════════════════════════════════════════════

    async def process(self, user_message: str, context: str = "") -> UnifiedResult:
        """完整处理用户消息，返回统一结果（非流式）。"""
        # 步骤1+2: 意图解析 + 指令美化（规则优先，不调 LLM）
        intent = self._parse_intent(user_message)

        # 步骤3: 模式路由
        tasks = self._route_to_modes(intent)

        # 步骤4: 执行模式
        results = await self._execute_modes(tasks, context)

        # 步骤5: 结果归集
        merged = self._merge_results(intent, results)

        # 步骤6: 系统监控
        issues = self._check_system_health(results)

        risk_warnings = []
        if intent.has_risk:
            risk_warnings.append(intent.risk_description)

        return UnifiedResult(
            original_input=user_message,
            intent=intent,
            dispatched_modes=[r.mode.value for r in results],
            mode_results=results,
            merged_output=merged,
            system_issues=issues,
            risk_warnings=risk_warnings,
        )

    def _make_progress_callback(self) -> Callable[[dict], Awaitable[None]]:
        """创建一个异步回调，将 progress 事件注入到 yield 流中。

        由于生成器无法从外部注入事件，这里将通过一个中间队列实现：
        - 外部代码调用 callback(event) 将事件放入队列
        - process_stream 在每次 yield 之间检查队列并消费
        """
        import asyncio
        queue: asyncio.Queue[dict] = asyncio.Queue()

        async def _callback(event: dict) -> None:
            await queue.put(event)

        _callback._queue = queue  # type: ignore[attr-defined]
        return _callback

    async def _drain_progress_queue(
        self,
        queue: asyncio.Queue[dict],
    ) -> list[dict]:
        """排空进度事件队列，返回所有待发送的事件"""
        events: list[dict] = []
        while not queue.empty():
            try:
                ev = queue.get_nowait()
                events.append(ev)
            except asyncio.QueueEmpty:
                break
        return events

    async def process_stream(
        self, user_message: str, context: str = "", session_id: str | None = None
    ):
        """流式处理用户消息，逐事件返回给前端。

        Args:
            user_message: 用户当前消息
            context: 额外上下文（如文件内容）
            session_id: 会话ID，用于加载历史记录保持上下文连续性

        Yields:
            dict: 包含 "type" 字段的事件字典

        P6: 上下文保持与任务追踪 —— 每轮对话检测偏离、更新进度、注入锚点
        """
        from pycoder.server.services.context_orchestrator import (
            get_orchestrator,
        )
        from pycoder.server.services.plugin_executor import PluginExecutor
        from pycoder.server.services.progress_reporter import (
            ProgressReporter,
            StageDef,
        )
        from pycoder.server.session_store import get_session_store

        # ── 加载会话历史（保持上下文连续性）──
        history_context = ""
        if session_id:
            try:
                store = get_session_store()
                if store.get_session(session_id):
                    history_msgs = list(store.get_messages(session_id, limit=100))
                    if history_msgs:
                        lines: list[str] = []
                        for m in history_msgs[-20:]:
                            role_label = "用户" if m.role == "user" else "助手"
                            lines.append(
                                f"{role_label}: {str(m.content)[:500]}"
                            )
                        history_context = "\n".join(lines)
                        logger.debug(
                            "unified_history_loaded",
                            extra={
                                "session_id": session_id,
                                "msg_count": len(history_msgs),
                            },
                        )
            except (OSError, ValueError, RuntimeError) as e:
                logger.warning(
                    "unified_history_load_failed",
                    extra={"session_id": session_id, "error": str(e)},
                )

        # ── 上下文管理：任务追踪 + 偏离检测 ──
        ctx_orch = get_orchestrator()
        if not ctx_orch.tracker.is_active:
            ctx_orch.start_task(user_message)
        else:
            ctx_result = await ctx_orch.process_user_message(user_message)
            # 发射上下文事件（任务状态 + 偏离提醒 + 回顾提示）
            ctx_events = ctx_result.get("events", [])
            for ctx_ev in ctx_events:
                yield ctx_ev
            # 发射 task_status 事件
            yield {
                "type": "task_status",
                "status": ctx_result.get("status", {}),
            }

        # ── 初始化进度报告器和插件执行器 ──
        progress_reporter = ProgressReporter()
        plugin_executor = PluginExecutor()

        # 创建异步回调，将进度事件注入 yield 流
        progress_cb = self._make_progress_callback()
        plugin_cb = self._make_progress_callback()
        progress_reporter.set_callback(progress_cb)
        plugin_executor.set_plugin_callback(plugin_cb)

        # 定义总执行阶段
        stages = [
            StageDef("intent", "🔍 意图解析", "分析用户输入意图"),
            StageDef("route", "🔄 模式路由", "调度最佳工作模式"),
            StageDef("llm", "🧠 AI 生成响应", "调用大模型生成内容"),
            StageDef("plugin", "🔧 后台插件执行", "静默执行匹配插件和技能"),
            StageDef("merge", "📋 结果归集", "整合多模式输出"),
            StageDef("done", "✅ 完成", "任务执行完毕"),
        ]
        progress_reporter.set_stages(stages, total_eta=45)

        # 共享上下文（插件执行结果写入这里，供后续阶段使用）
        shared_context: dict = {}

        # ── 辅助函数：排放队列中的进度/插件事件 ──
        async def flush_progress():
            for ev in await self._drain_progress_queue(progress_cb._queue):
                yield ev
            for ev in await self._drain_progress_queue(plugin_cb._queue):
                yield ev

        # ══════════════════════════════════════════════════════
        # 步骤1: 意图解析
        # ══════════════════════════════════════════════════════
        async for ev in flush_progress():
            yield ev
        intent = self._parse_intent(user_message)
        yield {
            "type": "unified_intent",
            "category": intent.task_category.value,
            "surface_text": intent.surface_text,
            "core_need": intent.core_need,
            "ambiguity": intent.ambiguity or "无",
        }
        await progress_reporter.advance("intent", "正在分析用户意图...")

        # ══════════════════════════════════════════════════════
        # 步骤2: 指令美化
        # ══════════════════════════════════════════════════════
        async for ev in flush_progress():
            yield ev
        beautified = intent.beautified_command or intent.raw_input
        yield {
            "type": "unified_beautify",
            "content": beautified,
        }

        # ══════════════════════════════════════════════════════
        # 步骤3: 模式路由
        # ══════════════════════════════════════════════════════
        async for ev in flush_progress():
            yield ev
        tasks = self._route_to_modes(intent)
        mode_names = [t["mode"].value for t in tasks]
        mode_reason = [t["reason"] for t in tasks]
        yield {
            "type": "unified_route",
            "modes": mode_names,
            "reason": "; ".join(mode_reason),
        }
        await progress_reporter.advance("route", f"已路由至 {', '.join(mode_names)} 模式")

        # 发送 mode 切换状态事件
        for task in tasks:
            mode = task["mode"]
            if mode == TaskCategory.HERMES:
                yield {
                    "type": "agent_status",
                    "message": "🔧 自动切换到 Hermes 结构化工作模式",
                }
            elif mode == TaskCategory.AGENT:
                yield {
                    "type": "agent_status",
                    "message": "👥 自动启用 Agent 团队协作模式",
                }

        # ══════════════════════════════════════════════════════
        # 步骤4: 执行模式（流式）+ 后台插件并行执行
        # ══════════════════════════════════════════════════════
        results: list[ModeResult] = []
        mode_content = ""

        # 启动后台插件/技能执行任务（与 AI 生成并行）
        bg_task = None
        try:
            bg_task = asyncio.create_task(
                plugin_executor.execute_all(user_message, shared_context),
            )
        except (RuntimeError, ValueError) as e:
            logger.debug("create_plugin_executor_task_failed: %s", e)
            pass
        # P7: 启动自动插件/Skills 补全检测（后台静默执行）
        ap_bg_task = None
        try:
            from pycoder.server.services.auto_plugin_manager import (
                get_plugin_manager,
            )
            ap_mgr = get_plugin_manager()
            ap_bg_task = asyncio.create_task(
                ap_mgr.auto_fulfill(user_message),
            )
        except (RuntimeError, ImportError, ValueError) as e:
            logger.debug("create_auto_plugin_task_failed: %s", e)
            pass
        await progress_reporter.advance("llm", "正在调用 AI 模型生成响应...")

        for task in tasks:
            mode = task["mode"]
            start = int(time.monotonic() * 1000)
            max_retries = 2
            retry_count = 0
            success = False

            for _attempt in range(max_retries):
                try:
                    if mode == TaskCategory.CHAT:
                        async for ev in self._execute_chat_stream(
                            intent.beautified_command or intent.raw_input,
                            context,
                            history_context,
                        ):
                            if ev.get("type") == "token":
                                mode_content += ev.get("data") or ev.get("content", "")
                                yield ev
                            elif ev.get("type") == "reasoning":
                                yield ev
                            elif ev.get("type") == "done":
                                mode_content = ev.get("content") or mode_content
                                success = True
                            elif ev.get("type") == "error":
                                yield ev
                    elif mode == TaskCategory.HERMES:
                        async for ev in self._execute_hermes_stream(
                            intent.beautified_command or intent.raw_input,
                            context,
                            history_context,
                        ):
                            if ev.get("type") == "token":
                                mode_content += ev.get("data") or ev.get("content", "")
                                yield ev
                            elif ev.get("type") == "reasoning":
                                yield ev
                            elif ev.get("type") == "done":
                                mode_content = ev.get("content") or mode_content
                                success = True
                            elif ev.get("type") == "error":
                                yield ev
                    elif mode == TaskCategory.AGENT:
                        async for ev in self._execute_agent_stream(
                            intent.beautified_command or intent.raw_input,
                            context,
                            history_context,
                        ):
                            if ev.get("type") in ("token", "agent_chunk"):
                                mode_content += ev.get("data") or ev.get("content", "")
                                yield ev
                            elif ev.get("type") in ("done", "agent_result"):
                                mode_content = (
                                    ev.get("content") or ev.get("summary", "") or mode_content
                                )
                                success = True
                                yield ev
                            elif ev.get("type") == "error":
                                yield ev

                    if success:
                        break
                    retry_count += 1
                    yield {
                        "type": "agent_status",
                        "message": f"⚠️ {mode.value} 模式执行失败，自动重试 ({retry_count}/{max_retries})",
                    }
                except Exception as e:
                    retry_count += 1
                    if retry_count >= max_retries:
                        yield {
                            "type": "error",
                            "message": f"{mode.value} 模式执行失败: {str(e)[:200]}",
                        }
                        break

            # 在 AI 生成间隙排放进度队列中的插件事件
            async for ev in flush_progress():
                yield ev

            elapsed = int(time.monotonic() * 1000) - start
            results.append(ModeResult(
                mode=mode,
                success=success,
                content=mode_content,
                error="" if success else f"执行失败，已重试 {retry_count} 次",
                duration_ms=elapsed,
                retries=retry_count,
            ))

        # ── 等待后台插件/技能执行完成（最多等10s）──
        if bg_task is not None:
            try:
                await asyncio.wait_for(bg_task, timeout=10.0)
            except (TimeoutError, Exception):
                pass
        # P7: 等待自动插件/Skills 补全检测完成
        if ap_bg_task is not None:
            try:
                await asyncio.wait_for(ap_bg_task, timeout=8.0)
            except (TimeoutError, Exception):
                pass
        async for ev in flush_progress():
            yield ev

        # ── 进度: 插件执行完成 ──
        await progress_reporter.advance("plugin", "后台插件执行完毕")

        # ── 进度: 结果归集 ──
        await progress_reporter.advance("merge", "整合多模式执行结果")
        async for ev in flush_progress():
            yield ev

        # ── 步骤5: 结果归集 ──
        merged = self._merge_results(intent, results)
        yield {
            "type": "unified_merge",
            "content": merged[:500],
        }

        # ── 步骤6: 系统监控 ──
        issues = self._check_system_health(results)
        if issues:
            yield {
                "type": "unified_health",
                "issues": issues,
            }
        async for ev in flush_progress():
            yield ev

        # ── 最终 done 事件 ──
        await progress_reporter.advance("done", "全部任务执行完成")
        async for ev in flush_progress():
            yield ev

        yield {
            "type": "done",
            "content": merged,
            "v2_engine": True,
        }

        # P6: 上下文保持 — 记录 AI 回复到上下文窗口 + 标记锚点命中
        try:
            from pycoder.server.services.context_orchestrator import (
                get_orchestrator,
            )
            orch = get_orchestrator()
            if orch and merged:
                orch.add_assistant_response(merged[:2000])
                # 简单启发式: 如果回复中包含代码块 → 锚点被正确使用
                orch.record_anchor_feedback("```" in merged)
            ctx_status = orch.tracker.get_status() if orch else {}
            yield {
                "type": "task_status",
                "status": ctx_status,
            }
        except (ImportError, AttributeError):
            pass

    # ══════════════════════════════════════════════════════════
    # 步骤1: 意图解析
    # ══════════════════════════════════════════════════════════

    def _parse_intent(self, message: str) -> ParsedIntent:
        """解析用户意图（规则优先，零 Token 消耗）"""
        category, reason = _classify_intent(message)

        return ParsedIntent(
            raw_input=message,
            surface_text=message.split("\n")[0][:200],
            core_need=reason,
            ambiguity=self._detect_ambiguity(message),
            task_category=category,
            beautified_command=message,  # 指令美化在后续合并
        )

    def _detect_ambiguity(self, message: str) -> str:
        """检测用户输入中的歧义和信息缺失。"""
        issues: list[str] = []

        # 检测模糊代词
        if re.search(r'这个|那个|它|那个文件|刚才的|上面的', message):
            issues.append("含模糊代词（这个/那个/它），缺少具体对象引用")

        # 检测未指定文件路径
        if re.search(r'修改|修复|改|优化|重构', message) and not re.search(r'\.\w{1,5}\b|\S+/\S+', message):
            issues.append("提到修改/修复但未指定具体文件")

        # 检测未指定技术栈
        if re.search(r'写|生成|开发|创建.*项目|搭建', message) and not re.search(
            r'python|fastapi|flask|django|react|vue|node|spring|go|rust|java|typescript|javascript',
            message, re.IGNORECASE
        ):
            issues.append("涉及开发但未指定技术栈/框架")

        # 检测极短输入
        if len(message.strip()) < 5:
            issues.append("输入过短，缺少必要信息")

        return "；".join(issues) if issues else ""

    # ══════════════════════════════════════════════════════════
    # 步骤3: 模式路由
    # ══════════════════════════════════════════════════════════

    def _route_to_modes(self, intent: ParsedIntent) -> list[dict]:
        """根据意图路由到对应工作模式。"""
        category = intent.task_category

        if category == TaskCategory.CHAT:
            return [{"mode": TaskCategory.CHAT, "reason": "简单问答/知识咨询，直接文字回复"}]

        elif category == TaskCategory.HERMES:
            return [{"mode": TaskCategory.HERMES, "reason": "工具操作/代码修改，使用结构化5步工作法"}]

        elif category == TaskCategory.AGENT:
            return [{"mode": TaskCategory.AGENT, "reason": "系统工程/多步骤开发，启用多Agent团队协作"}]

        return [{"mode": TaskCategory.CHAT, "reason": "默认聊天模式"}]

    # ══════════════════════════════════════════════════════════
    # 步骤4: 模式执行
    # ══════════════════════════════════════════════════════════

    async def _execute_modes(self, tasks: list[dict], context: str) -> list[ModeResult]:
        """串行执行各模式（防止资源抢占）。"""
        results: list[ModeResult] = []
        for task in tasks:
            mode = task["mode"]
            start = int(time.monotonic() * 1000)
            max_retries = 2
            retry_count = 0
            success = False
            content = ""
            error = ""

            for _ in range(max_retries):
                try:
                    if mode == TaskCategory.CHAT:
                        content = await self._execute_chat_sync(context)
                    elif mode == TaskCategory.HERMES:
                        content = await self._execute_hermes_sync(context)
                    elif mode == TaskCategory.AGENT:
                        content = await self._execute_agent_sync(context)
                    success = True
                    break
                except Exception as e:
                    retry_count += 1
                    error = str(e)[:300]
                    if retry_count >= max_retries:
                        break

            results.append(ModeResult(
                mode=mode,
                success=success,
                content=content,
                error=error,
                duration_ms=int(time.monotonic() * 1000) - start,
                retries=retry_count,
            ))

        return results

    async def _execute_chat_sync(
        self, context: str, history_context: str = ""
    ) -> str:
        """同步执行普通聊天模式。"""
        from pycoder.server.chat_bridge import ChatBridge
        bridge = ChatBridge()
        if self.api_key:
            bridge.configure(model=self.model, api_key=self.api_key)
        if history_context:
            bridge.add_message(
                "user",
                f"[对话历史回顾]\n{history_context}\n\n[当前任务] {context}",
            )
        try:
            return await bridge.chat(context)
        finally:
            await bridge.close()

    async def _execute_hermes_sync(
        self, context: str, history_context: str = ""
    ) -> str:
        """同步执行 Hermes 模式。"""
        from pycoder.prompts.loader import get_prompt
        from pycoder.server.chat_bridge import ChatBridge
        bridge = ChatBridge()
        if self.api_key:
            bridge.configure(model=self.model, api_key=self.api_key)
        hermes_prompt = get_prompt("hermes")
        if hermes_prompt:
            bridge.config.system_prompt = hermes_prompt
        if history_context:
            bridge.add_message(
                "user",
                f"[对话历史回顾]\n{history_context}\n\n[当前任务] {context}",
            )
        try:
            return await bridge.chat(context)
        finally:
            await bridge.close()

    async def _execute_agent_sync(
        self, context: str, history_context: str = ""
    ) -> str:
        """同步执行 Agent 模式。"""
        from pycoder.server.chat_bridge import ChatBridge
        from pycoder.server.services.agent_strategies import UNIFIED_SYSTEM_PROMPT
        bridge = ChatBridge()
        if self.api_key:
            bridge.configure(model=self.model, api_key=self.api_key)
        bridge.config.system_prompt = UNIFIED_SYSTEM_PROMPT
        if history_context:
            bridge.add_message(
                "user",
                f"[对话历史回顾]\n{history_context}\n\n[当前任务] {context}",
            )
        try:
            return await bridge.chat(context)
        finally:
            await bridge.close()

    async def _execute_chat_stream(
        self, message: str, context: str, history_context: str = ""
    ):
        """流式执行普通聊天模式。"""
        from pycoder.server.chat_bridge import ChatBridge
        bridge = ChatBridge()
        if self.api_key:
            bridge.configure(model=self.model, api_key=self.api_key)
        # 注入会话历史上下文（仅作为 bridge 消息，不在 chat_stream 中重复包装）
        effective_message = message
        if history_context:
            effective_message = (
                f"[对话历史回顾]\n{history_context}\n\n[当前消息] {message}"
            )
        try:
            full = ""
            async for ev in bridge.chat_stream(effective_message):
                if ev.event_type == "token":
                    full += ev.content
                    yield {"type": "token", "data": ev.content, "content": ev.content}
                elif ev.event_type == "reasoning":
                    yield {"type": "reasoning", "content": ev.content}
                elif ev.event_type == "done":
                    final = ev.content or full
                    yield {"type": "done", "content": final}
                elif ev.event_type == "error":
                    yield {"type": "error", "message": ev.content}
        finally:
            await bridge.close()

    async def _execute_hermes_stream(
        self, message: str, context: str, history_context: str = ""
    ):
        """流式执行 Hermes 结构化工作模式。"""
        from pycoder.prompts.loader import get_prompt
        from pycoder.server.chat_bridge import ChatBridge
        bridge = ChatBridge()
        if self.api_key:
            bridge.configure(model=self.model, api_key=self.api_key)
        hermes_prompt = get_prompt("hermes")
        if hermes_prompt:
            bridge.config.system_prompt = hermes_prompt
        # 注入会话历史上下文（仅作为 chat_stream 参数，不重复 add_message）
        effective_message = message
        if history_context:
            effective_message = (
                f"[对话历史回顾]\n{history_context}\n\n[当前消息] {message}"
            )
        try:
            full = ""
            async for ev in bridge.chat_stream(effective_message):
                if ev.event_type == "token":
                    full += ev.content
                    yield {"type": "token", "data": ev.content, "content": ev.content}
                elif ev.event_type == "reasoning":
                    yield {"type": "reasoning", "content": ev.content}
                elif ev.event_type == "done":
                    final = ev.content or full
                    yield {"type": "done", "content": final}
                elif ev.event_type == "error":
                    yield {"type": "error", "message": ev.content}
        finally:
            await bridge.close()

    async def _execute_agent_stream(
        self, message: str, context: str, history_context: str = ""
    ):
        """流式执行 Agent 团队协作模式。"""
        from pycoder.server.services.agent_orchestrator import agent_chat_stream

        # 合并历史上下文
        merged_context = context or ""
        if history_context:
            merged_context = (
                f"## 对话历史\n{history_context}\n\n## 额外上下文\n{merged_context}"
                if merged_context
                else f"## 对话历史\n{history_context}"
            )

        async for ev in agent_chat_stream(
            message,
            model=self.model,
            system_prompt=None,
            api_key=self.api_key,
            context=merged_context,
        ):
            yield ev

    # ══════════════════════════════════════════════════════════
    # 步骤5: 结果归集
    # ══════════════════════════════════════════════════════════

    def _merge_results(self, intent: ParsedIntent, results: list[ModeResult]) -> str:
        """归集整合所有模式结果，输出面向用户的干净内容。

        修复：不再将内部调度标记（【原始用户输入】等）暴露给用户。
        这些标记仅用于内部日志，用户看到的是干净的 AI 回复内容。
        """
        # ── 提取 AI 实际回复内容（去除内部标记）──
        raw_content = ""
        if results and results[0].success:
            raw_content = results[0].content
        else:
            return "所有模式执行失败，请查看系统故障处理方案。"

        # 去除 LLM 输出中可能残留的【标记】块
        cleaned = self._strip_internal_markers(raw_content)

        # ── 附加执行摘要（客户友好格式）──
        modes_summary = "、".join(
            f"{r.mode.value}({'✅' if r.success else '❌'})" for r in results
        )
        footer = (
            f"\n\n---\n"
            f"🔧 调度模式: {modes_summary}"
        )

        return cleaned + footer

    @staticmethod
    def _strip_internal_markers(text: str) -> str:
        """去除 LLM 输出中的内部调度标记，保留面向用户的干净内容。"""
        import re
        # 已知的内部标记块（含中英文变体）
        marker_patterns = [
            r"【原始用户输入】.*?(?=【|$)",
            r"【分层意图解析】.*?(?=【|$)",
            r"【美化后标准化任务指令】.*?(?=【|$)",
            r"【本次[^】]*调度[^】]*模式[^】]*】.*?(?=【|$)",
            r"【多模式执行整合输出结果】",
            r"【系统故障处理方案】.*?(?=【|$)",
            r"【高危操作风险提示】.*?(?=【|$)",
            r"\[原始用户输入\].*?(?=\[|$)",
            r"\[分层意图解析\].*?(?=\[|$)",
        ]
        result = text
        for pat in marker_patterns:
            result = re.sub(pat, "", result, flags=re.DOTALL)
        # 清理多余空行
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()

    # ══════════════════════════════════════════════════════════
    # 步骤6: 系统监控
    # ══════════════════════════════════════════════════════════

    def _check_system_health(self, results: list[ModeResult]) -> list[str]:
        """检查系统运行状态，识别故障模式。"""
        issues: list[str] = []

        for r in results:
            if not r.success:
                issues.append(
                    f"模式 [{r.mode.value}] 执行失败: {r.error} "
                    f"(已重试 {r.retries} 次，耗时 {r.duration_ms}ms)"
                )

            # 超时检测
            if r.duration_ms > 120000:
                issues.append(
                    f"模式 [{r.mode.value}] 执行超时 ({r.duration_ms}ms)，"
                    f"可能因为网络延迟或 LLM 服务响应慢"
                )

        return issues


# ── 便捷工厂函数 ──


def create_unified_entry(model: str = "deepseek-chat", api_key: str = "") -> UnifiedEntryAgent:
    """创建统一入口 Agent 实例。"""
    return UnifiedEntryAgent(model=model, api_key=api_key)
