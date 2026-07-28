"""ChatBridge — AI 聊天桥接层（主入口）

替代原 pycoder.tui.bridge.TUIBridge，为 Electron 后端提供无 UI 依赖的流式聊天能力。

═══════════════════════════════════════════════════════════════
模块拆分说明（P2-B）：
本文件为门面（Facade），保留 ChatBridge 主类。
辅助功能已拆分到 6 个子模块：
- chat_bridge_router.py    — Provider 路由 & 模型端点解析
- chat_bridge_tokens.py    — Token 计数 & 估算
- chat_bridge_context.py   — 上下文构建 & 历史压缩
- chat_bridge_history.py   — 对话历史管理（HistoryManager）
- chat_bridge_stream.py    — 流式响应解析（SSE/delta/payload）
- chat_bridge_tools.py     — 工具调用分发（V1+V2 沙箱）
- chat_bridge_plugins.py   — 钩子与中间件（反思/幻觉/自愈等）

为保证向后兼容，所有原导出符号均通过 re-export 暴露。
═══════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

# P2-C: 链路追踪集成（默认 NoOp，零开销；OTEL_ENABLED=1 时启用）
from pycoder.observability.tracing import traced

# ── 子模块 re-export（保持向后兼容）──────────────────────
from .chat_bridge_context import (  # noqa: F401
    _apply_context_anchor,
    _apply_history_sliding_window,
    _check_token_budget,
    _compress_old_messages,
    _get_context_anchor,
)
from .chat_bridge_history import HistoryManager  # noqa: F401
from .chat_bridge_plugins import (  # noqa: F401
    GuardResult,
    RuminationResult,
    TaskGrade,
    analyze_after_write,
    check_cost_budget,
    format_hallucination_warning,
    grade_task_difficulty,
    hallucination_validate,
    live_learner_observe,
    mark_provider_key_invalid,
    maybe_annotate_tool_result,
    record_cost_usage,
    record_observability,
    record_project_error,
    record_project_file_modified,
    record_project_fix_attempt,
    rumination_mid_execute,
    rumination_post_execute,
    rumination_pre_execute,
    self_heal_after_write,
)
from .chat_bridge_router import (  # noqa: F401
    MODEL_ROUTING,
    PROVIDER_API_BASES,
    _detect_provider,
    _resolve_model_endpoint,
)
from .chat_bridge_stream import (  # noqa: F401
    build_request_payload,
    extract_stream_delta,
    parse_sse_line,
    rebuild_payload_for_fallback,
)
from .chat_bridge_tokens import TokenCounter, estimate_tokens  # noqa: F401
from .chat_bridge_tools import (  # noqa: F401
    CATEGORY_TOOL_MAP,
    SKIP_TOOLS,
    build_tools_payload,
    cache_file_read,
    execute_tool_call,
    execute_tool_via_v1,
    execute_tool_via_v2,
    execute_tool_with_sandbox,
    get_cached_file_read,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 事件类型
# ══════════════════════════════════════════════════════════


@dataclass
class ChatEvent:
    """流式聊天事件"""

    event_type: str  # "token" | "reasoning" | "done" | "error"
    content: str = ""
    usage: dict = field(default_factory=dict)


# ══════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════


@dataclass
class BridgeConfig:
    """桥接配置"""

    model: str = "deepseek-chat"
    api_key: str = ""
    api_base: str = "https://api.deepseek.com"
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 8192
    reasoning_effort: str = "medium"  # "max"|"medium"|"low" — DeepSeek V4 推理强度
    enable_thinking: bool = True  # 是否启用深度思考链
    enable_cache: bool = True  # 是否启用 KV Cache 降本
    # M5: 发给 LLM 的历史消息滑窗上限（0 表示不截断）
    # agent_orchestrator 每轮 add_message 累积工具结果，15 轮后 ~15K token；
    # 截断为最近 N 条避免 prompt 膨胀。_messages 仍保留完整历史供审计。
    max_history_messages: int = 20


# ══════════════════════════════════════════════════════════
# ChatBridge — 主类（Facade）
# ══════════════════════════════════════════════════════════


class ChatBridge:
    """AI 聊天桥接 — 无 UI 依赖，仅提供流式 API 调用

    内部组合 HistoryManager 管理对话历史，工具调用、流式解析、
    钩子中间件等能力委托给子模块。
    """

    # 类级共享 httpx client（连接池复用）
    _shared_client: object | None = None
    _client_lock: asyncio.Lock | None = None
    # P1-4: NLU 引擎单例缓存（避免每次请求新建）
    _nlu_engine: object | None = None

    def __init__(self):
        self.config = BridgeConfig()
        # 委托给 HistoryManager 管理消息（保持 _messages 属性向后兼容）
        self._history = HistoryManager(
            max_history_messages=self.config.max_history_messages,
        )
        self._rumination_count = 0  # P1-1: 反思轮次计数
        self._nlu_cache: dict[str, object] | None = None  # P0-1: NLU 结果缓存
        self._nlu_result_cache: dict[int, tuple[float, tuple]] = {}
        self._read_file_cache: dict[str, str] = {}  # 文件读取缓存（避免重复读取）
        self._guard_cache: dict[str, float] = {}  # 幻觉验证缓存
        self._repeating_round_count: int = 0  # 连续重复轮次计数

    # ── _messages 属性代理到 HistoryManager（向后兼容）──

    @property
    def _messages(self) -> list[dict]:
        return self._history.messages

    @_messages.setter
    def _messages(self, value: list[dict]) -> None:
        self._history.messages = value

    # ════════════════════════════════════════════════════
    # 同步聊天（供自进化引擎等内部组件使用）
    # ════════════════════════════════════════════════════

    @traced("chat_bridge.chat")
    async def chat(self, prompt: str, *, max_tokens: int = 1000) -> str:
        """简单同步聊天 — 内置 Provider 降级"""
        client = await ChatBridge._get_client()

        # 构建 Provider 降级链
        fallback_providers: list[tuple[str, str, str, str]] = []
        try:
            from pycoder.providers.auth import PROVIDER_DEFS, ModelManager

            mm = ModelManager()
            detected = mm.auto_detect()
            for pname, pdefs in sorted(PROVIDER_DEFS.items(), key=lambda x: x[1]["priority"]):
                if pname in detected:
                    pkey = detected[pname]
                    model_id = pdefs["recommended_model"]
                    pbase = PROVIDER_API_BASES.get(pname, "https://api.deepseek.com")
                    fallback_providers.append((model_id, pkey, pbase, pname))
        except (ImportError, RuntimeError, OSError):
            pass

        # 确保 Key 已设置
        if not self.config.api_key:
            try:
                mm = ModelManager()
                detected = mm.auto_detect()
                provider = _detect_provider(self.config.model)
                if provider in detected:
                    self.config.api_key = detected[provider]
                elif detected:
                    self.config.api_key = next(iter(detected.values()))
            except (ImportError, RuntimeError, OSError):
                pass

        api_key = self.config.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            return ""

        tried: set[str] = set()
        for try_model, try_key, try_base, try_prov in (
            [(self.config.model, api_key, self.config.api_base, _detect_provider(self.config.model))]
            + fallback_providers
        ):
            model_key = f"{try_prov}:{try_model}"
            if model_key in tried:
                continue
            tried.add(model_key)

            headers = {
                "Authorization": f"Bearer {try_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": try_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            }
            try:
                resp = await client.post(
                    f"{try_base.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
                elif resp.status_code == 401:
                    logger.warning("chat_sync_401 provider=%s key_invalid, trying next", try_prov)
                    continue
                else:
                    logger.warning("chat_sync_error provider=%s status=%d", try_prov, resp.status_code)
                    continue
            except (OSError, ValueError, KeyError, AttributeError) as e:
                # OSError 不覆盖 httpx 的 TransportError（TimeoutException/ConnectError 等）
                logger.warning("chat_sync_exception provider=%s error=%s", try_prov, e)
                continue
            except Exception as e:
                # 兜底：捕获 httpx.TimeoutException / ConnectError / NetworkError 等
                # 这些异常在 P3-C 混沌测试中被识别为未处理的崩溃场景
                logger.warning("chat_sync_network_error provider=%s error=%s", try_prov, e)
                continue

        return ""

    @classmethod
    async def _get_client(cls) -> object:
        """获取或创建共享 httpx client（带连接池，锁保护）。"""
        if cls._shared_client is None:
            if cls._client_lock is None:
                cls._client_lock = asyncio.Lock()
            async with cls._client_lock:
                if cls._shared_client is None:  # double-check
                    import httpx
                    cls._shared_client = httpx.AsyncClient(
                        timeout=httpx.Timeout(120.0),
                        trust_env=False,
                        limits=httpx.Limits(
                            max_keepalive_connections=5,
                            max_connections=10,
                            keepalive_expiry=60,
                        ),
                    )
        return cls._shared_client

    # ════════════════════════════════════════════════════
    # 配置
    # ════════════════════════════════════════════════════

    def configure(
        self,
        model: str | None = None,
        api_key: str | None = None,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
    ):
        """配置模型、API Key、系统提示词和最大 Token 数

        自动检测 provider 并设置 api_base，
        同时检查用户是否自定义了该模型的 API 端点。
        """
        if model:
            self.config.model = model
        if api_key:
            self.config.api_key = api_key
        if system_prompt is not None:
            self.config.system_prompt = system_prompt
        if max_tokens is not None:
            self.config.max_tokens = max_tokens

        # 自动检测 provider 并设置 api_base
        provider = _detect_provider(self.config.model)
        if provider in PROVIDER_API_BASES:
            self.config.api_base = PROVIDER_API_BASES[provider]

        # 检查用户自定义 API Base（最高优先级）
        try:
            from pycoder.providers.auth import ModelManager
            custom_base = ModelManager().get_custom_api_base(self.config.model)
            if custom_base:
                self.config.api_base = custom_base
        except (ImportError, AttributeError, RuntimeError):
            pass

        # 同步 max_history_messages 到 HistoryManager
        self._history.max_history = self.config.max_history_messages

    def add_message(self, role: str, content: str):
        """添加上下文消息"""
        self._history.add_message(role, content)

    def _get_effective_messages(self) -> list[dict]:
        """返回发给 LLM 的历史消息（应用滑窗截断 + 记忆压缩 + 上下文锚点）"""
        # 每次调用都同步 config.max_history_messages 到 HistoryManager，
        # 保证外部直接修改 config 后立即生效
        self._history.max_history = self.config.max_history_messages
        return self._history.get_effective_messages()

    def _check_token_budget(self, messages: list[dict]) -> int:
        """精确计算消息列表的 token 数，超出阈值时预警"""
        return _check_token_budget(messages)

    def _compress_old_messages(self, old_messages: list[dict]) -> str:
        """压缩旧消息为摘要文本（零延迟规则提取，不调用 LLM）"""
        return _compress_old_messages(old_messages)

    # ════════════════════════════════════════════════════
    # 智能意图分类
    # ════════════════════════════════════════════════════

    _SIMPLE_CHAT_PATTERNS: list[str] = [
        "你好", "hello", "嗨", "hi", "谢谢", "thanks", "再见", "bye",
        "你是谁", "介绍", "能做什么", "帮助", "help", "功能",
        "什么是", "什么是pycoder", "版本", "version",
        "天气", "今天", "日期", "时间", "joke", "笑话",
    ]
    _TOOL_NEEDED_KEYWORDS: list[str] = [
        "写", "创建", "修改", "删除", "运行", "执行", "测试", "安装",
        "生成", "构建", "分析", "审查", "重构", "修复", "查找", "搜索",
        "create", "write", "modify", "delete", "run", "execute", "test",
        "install", "generate", "build", "analyze", "review", "refactor",
        "fix", "search", "find", "commit", "git", "deploy", "部署",
        "file", "code", "代码", "文件", "项目", "project",
    ]

    def _classify_intent(self, message: str) -> tuple[str, bool, int]:
        """快速分类用户意图（零 token 成本）

        Returns:
            (mode: "chat"|"tool", needs_tools: bool, max_rounds: int)
        """
        msg_lower = message.lower().strip()
        msg_len = len(msg_lower)

        # 1. 简单问候/闲聊 → chat 模式
        for pattern in self._SIMPLE_CHAT_PATTERNS:
            if msg_lower == pattern or msg_lower.startswith(pattern):
                return ("chat", False, 0)

        # 2. 超短消息（<10 字符）→ chat 模式
        if msg_len < 10 and not any(
            kw in msg_lower for kw in self._TOOL_NEEDED_KEYWORDS
        ):
            return ("chat", False, 0)

        # 3. 包含工具操作关键词 → tool 模式
        tool_keyword_count = sum(1 for kw in self._TOOL_NEEDED_KEYWORDS if kw in msg_lower)
        if tool_keyword_count >= 2:
            return ("tool", True, 8)  # 复杂任务允许 8 轮
        if tool_keyword_count >= 1:
            return ("tool", True, 5)  # 标准工具任务 5 轮

        # 4. 中等长度（10-50 字符）无明确工具关键词 → chat 模式
        if msg_len < 50:
            return ("chat", False, 0)

        # 5. 长消息 → 默认为 tool 模式
        return ("tool", True, 5)

    async def _route_with_nlu(self, message: str) -> tuple[str, bool, int]:
        """P0-1: 三层 NLU 路由 — 关键词快速预检 + NLU 深度分析

        P1-4 优化: 短消息跳过 NLU + 缓存 + 超时降级

        Returns:
            (mode: "chat"|"tool", needs_tools: bool, max_rounds: int)
        """
        # Layer 1: 快速关键词预检
        mode, needs_tools, rounds = self._classify_intent(message)

        # P1-4: 短消息/明确 chat → 直接返回
        if mode == "chat" and len(message) < 50:
            return (mode, needs_tools, rounds)

        # P1-4: NLU 结果缓存（5 分钟内相同消息不重复分析）
        cache_key = hash(message)
        cached = self._nlu_result_cache.get(cache_key)
        if cached and (time.time() - cached[0]) < 300:  # 5 分钟 TTL
            return cached[1]

        # Layer 2 & 3: 中等/复杂消息 → CompositeNLUEngine（类级缓存）
        try:
            from pycoder.ai.nlu.composite_nlu import CompositeNLUEngine
            if ChatBridge._nlu_engine is None:
                ChatBridge._nlu_engine = CompositeNLUEngine()
            _nlu = ChatBridge._nlu_engine
            _result = await asyncio.wait_for(
                _nlu.understand(message), timeout=2.0
            )
            self._nlu_cache = dict(intent=_result, category=_result.task_category)

            if _result.task_category in (
                "code_generation", "refactoring", "debugging",
            ):
                _complexity = getattr(_result, "complexity", 0.5)
                result = ("tool", True, 8 if _complexity > 0.6 else 5)
            elif _result.ambiguity > 0.5:
                result = ("tool", True, 5)
            else:
                result = ("chat", False, 0)

            self._nlu_result_cache[cache_key] = (time.time(), result)
            return result
        except asyncio.TimeoutError:
            logger.debug("nlu_route_timeout, falling back to keyword match")
            return (mode, needs_tools, rounds)
        except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.debug("nlu_route_fallback error=%s", e)
            return (mode, needs_tools, rounds)

    # ════════════════════════════════════════════════════
    # 流式聊天主流程
    # ════════════════════════════════════════════════════

    @traced("chat_bridge.chat_stream")
    async def chat_stream(
        self,
        message: str,
        *,
        tool_names: list[str] | None = None,
        mode: str = "auto",  # "auto"|"chat"|"tool" — 模式覆盖
    ) -> AsyncIterator[ChatEvent]:
        """流式聊天 — ReAct 模式工具调用循环

        智能路由: auto 模式下自动检测意图 → chat(无工具) 或 tool(工具调用) 模式。
        chat 模式直接回复，tool 模式执行 思考→行动→观察 的 ReAct 循环。

        Args:
            message: 用户消息
            tool_names: 可选，限制注入的工具名称列表。None=全部
            mode: "auto" 自动检测 / "chat" 纯对话 / "tool" 强制工具模式

        Yields:
            ChatEvent: event_type ∈ {"token", "reasoning", "done", "error"}
        """
        import httpx

        _start_time = time.perf_counter()

        # ── 智能意图分类 ──
        effective_mode = mode
        max_tool_rounds = 5
        force_tools = True
        if mode == "auto":
            effective_mode, force_tools, max_tool_rounds = (
                await self._route_with_nlu(message)
            )
            if effective_mode == "chat":
                logger.debug(
                    "intent_router chat_mode msg_len=%d preview=%s",
                    len(message), message[:50],
                )

        # ── P0-3: 任务难度分级（注入项目真实上下文）──
        _task_grade = None
        if force_tools:
            _ctx: dict = {"mode": effective_mode}
            try:
                # P2-7: 在线程池中执行同步 glob + open，避免阻塞事件循环
                def _build_context():
                    _cwd = os.getcwd()
                    import glob as _glob
                    _py_files = _glob.glob(
                        f"{_cwd}/**/*.py", recursive=True,
                    ) if _cwd else []
                    _ctx_local = {"files": len(_py_files)}
                    _ctx_local["domain"] = (
                        self._nlu_cache.get("category", "")
                        if self._nlu_cache else ""
                    )
                    _req = os.path.join(_cwd, "requirements.txt")
                    if os.path.exists(_req):
                        with open(_req, encoding="utf-8") as _f:
                            _ctx_local["dependencies"] = len(
                                [l for l in _f if l.strip()],
                            )
                    return _ctx_local
                _ctx = await asyncio.to_thread(_build_context)
            except (OSError, ValueError, RuntimeError):
                pass
            _task_grade = grade_task_difficulty(message, context=_ctx)
            if _task_grade:
                max_tool_rounds = _task_grade.max_iterations
                self.config.temperature = _task_grade.temperature
                logger.debug(
                    "task_grader level=%s score=%.0f rounds=%d temp=%.2f",
                    _task_grade.level.name, _task_grade.score,
                    max_tool_rounds, _task_grade.temperature,
                )

        # ── 构建 Provider 降级链 ──
        fallback_providers: list[tuple[str, str, str]] = []
        try:
            from pycoder.providers.auth import PROVIDER_DEFS, ModelManager

            mm = ModelManager()
            detected = mm.auto_detect()
            for pname, pdefs in sorted(PROVIDER_DEFS.items(), key=lambda x: x[1]["priority"]):
                if pname in detected:
                    pkey = detected[pname]
                    model_id = pdefs["recommended_model"]
                    pbase = PROVIDER_API_BASES.get(pname, "https://api.deepseek.com")
                    fallback_providers.append((model_id, pkey, pbase))
            if not fallback_providers:
                for env_key, model_id, base in [
                    ("DEEPSEEK_API_KEY", "deepseek-chat", "https://api.deepseek.com"),
                    ("OPENAI_API_KEY", "gpt-4o-mini", "https://api.openai.com/v1"),
                ]:
                    k = os.environ.get(env_key, "")
                    if k:
                        fallback_providers.append((model_id, k, base))
                        break
        except (ImportError, RuntimeError, OSError) as e:
            logger.debug("fallback_providers_setup_failed error=%s", e)

        # ── 重置：从 ModelManager 获取当前 Provider 的 Key ──
        if not self.config.api_key:
            try:
                from pycoder.providers.auth import ModelManager

                mm = ModelManager()
                detected = mm.auto_detect()
                provider = _detect_provider(self.config.model)
                if provider in detected:
                    self.config.api_key = detected[provider]
                elif detected:
                    self.config.api_key = next(iter(detected.values()))
            except (ImportError, RuntimeError, OSError) as e:
                logger.debug("modelmanager_fallback_failed error=%s", e)

        api_key = self.config.api_key
        if not api_key:
            yield ChatEvent(
                event_type="error",
                content=(
                    "⚠️ **未配置 AI 模型 API Key**\n\n"
                    "请通过以下任一方式配置:\n"
                    "1. **环境变量**: 设置 `DEEPSEEK_API_KEY=sk-xxx`\n"
                    "2. **Settings 面板**: 打开左侧 ⚙ 设置 → API Key 管理 → 输入 Key\n"
                    "3. **快速配置**: 发送 `/setup deepseek YOUR_API_KEY`\n\n"
                    "💡 免费获取 Key: https://platform.deepseek.com/api_keys"
                ),
            )
            return

        # ── 构建消息上下文 ──
        messages = self._get_effective_messages()

        # ── 注入缓存规则 + 能力块（仅 tool 模式注入能力清单）──
        effective_system = self.config.system_prompt
        if effective_system:
            from pycoder.prompts.cache_rules import inject_cache_rules

            effective_system = inject_cache_rules(effective_system, lang="zh")
        if force_tools:
            caps = self._build_capabilities_block()
            if caps:
                if effective_system:
                    effective_system = effective_system + "\n\n---\n" + caps
                else:
                    effective_system = caps

        # 规范化消息结构（system 在 [0]，差异化在末尾）
        from pycoder.prompts.cache_rules import canonicalize_messages

        messages = canonicalize_messages(messages, effective_system)
        messages.append({"role": "user", "content": message})

        # ── 成本熔断预检 ──
        estimated = estimate_tokens(message) + sum(
            estimate_tokens(m.get("content", "")) for m in messages
        )
        ok, reason = check_cost_budget(estimated_tokens=estimated)
        if not ok:
            yield ChatEvent(event_type="error", content=f"成本超限: {reason}")
            return

        # ── 构建 tools payload（仅 tool 模式）──
        tools_payload: list[dict] = []
        if force_tools:
            task_grade_reasoning = _task_grade.reasoning if _task_grade else None
            tools_payload = build_tools_payload(
                tool_names=tool_names,
                nlu_cache=self._nlu_cache,
                task_grade_reasoning=task_grade_reasoning,
                effective_mode=effective_mode,
            )

        is_deepseek = self.config.model.startswith("deepseek")
        client = await ChatBridge._get_client()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        all_content = ""
        total_usage: dict = {}
        tried_providers: set[str] = set()

        # ── P1-3: 多模型融合择优（chat模式 + ≥2 provider）──
        if not force_tools and len(fallback_providers) >= 2:
            try:
                from pycoder.ai.fusion.engine import FusionEngine, FusionMode
                _fusion = FusionEngine()
                _f_result = await _fusion.fuse(
                    prompt=message,
                    mode=FusionMode.BEST_OF_N,
                    providers=fallback_providers[:2],
                )
                if _f_result and getattr(_f_result, "confidence", 0) > 0.7:
                    content = getattr(_f_result, "content", "")
                    if content:
                        yield ChatEvent(event_type="token", content=content)
                        yield ChatEvent(
                            event_type="done", content=content,
                            usage={"fusion": True, "provider": "multi"},
                        )
                        return
            except (ImportError, RuntimeError, ValueError, TypeError, AttributeError):
                pass

        # ── ReAct 工具调用循环 ──
        round_num = 0
        for round_num in range(max(max_tool_rounds, 1)):
            if round_num > 0 and force_tools:
                yield ChatEvent(
                    event_type="token",
                    content=f"\n🔄 第 {round_num + 1}/{max_tool_rounds} 轮...\n",
                )

            payload = build_request_payload(
                model=self.config.model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                tools_payload=tools_payload,
                is_deepseek=is_deepseek,
                reasoning_effort=self.config.reasoning_effort,
                enable_thinking=self.config.enable_thinking,
                enable_cache=self.config.enable_cache,
            )

            round_content = ""
            usage: dict = {}
            tool_calls: list[dict] = []

            try:
                async with asyncio.timeout(120):  # 单轮LLM调用最多120秒
                    async with client.stream(
                        "POST",
                        f"{self.config.api_base.rstrip('/')}/chat/completions",
                        json=payload,
                        headers=headers,
                    ) as response:
                        if response.status_code == 401:
                            error_body = await response.aread()
                            err_text = error_body.decode()[:300]
                            current_model = self.config.model
                            current_provider = _detect_provider(current_model)
                            logger.error(
                                "D2_CHAT_401 model=%s base=%s status=%d body=%s",
                                current_model, self.config.api_base,
                                response.status_code, err_text[:100],
                            )
                            tried_providers.add(current_model)
                            mark_provider_key_invalid(current_provider)

                            # 尝试降级到下一个可用 Provider
                            next_prov = None
                            for nm, nk, nb in fallback_providers:
                                if nm not in tried_providers:
                                    next_prov = (nm, nk, nb)
                                    break
                            if next_prov:
                                nm, nk, nb = next_prov
                                logger.warning(
                                    "provider_401_fallback from=%s to=%s reason=%s",
                                    current_model, nm, err_text[:100],
                                )
                                self.config.model = nm
                                self.config.api_key = nk
                                self.config.api_base = nb
                                api_key = nk
                                is_deepseek = nm.startswith("deepseek")
                                headers["Authorization"] = f"Bearer {nk}"
                                yield ChatEvent(
                                    event_type="token",
                                    content=f"\n⚠️ {current_model} Key 无效，自动降级到 {nm}...\n",
                                )
                                continue  # 重试当前轮次
                            # 所有 Provider 均失败
                            yield ChatEvent(
                                event_type="error",
                                content=(
                                    f"❌ **所有 API Key 均无效**\n"
                                    f"已尝试 {len(tried_providers)} 个提供商，均返回认证失败。\n\n"
                                    f"请在 Settings 面板更新 API Key，或发送:\n"
                                    f"  `/setup deepseek YOUR_NEW_KEY`"
                                ),
                            )
                            return

                        if response.status_code != 200:
                            error_body = await response.aread()
                            yield ChatEvent(
                                event_type="error",
                                content=f"API 请求失败 (HTTP {response.status_code}): {error_body.decode()[:500]}",
                            )
                            return

                        async for line in response.aiter_lines():
                            data = parse_sse_line(line)
                            if data is None:
                                continue

                            content_delta, reasoning_delta, tool_calls, finish_is_tool = (
                                extract_stream_delta(
                                    data, existing_tool_calls=tool_calls,
                                )
                            )
                            if reasoning_delta:
                                yield ChatEvent(
                                    event_type="reasoning", content=reasoning_delta
                                )
                                if content_delta:
                                    round_content += content_delta
                                    yield ChatEvent(event_type="token", content=content_delta)
                            elif content_delta:
                                round_content += content_delta
                                yield ChatEvent(event_type="token", content=content_delta)
                            if finish_is_tool:
                                break

                            if data.get("usage"):
                                usage = data["usage"]

            except TimeoutError:
                logger.warning(
                    "chat_stream_timeout round=%s model=%s",
                    round_num + 1, self.config.model,
                )
                yield ChatEvent(
                    event_type="token",
                    content="\n⏱ **LLM 调用超时 (120s)**，已返回当前进度。\n",
                )
                if round_content:
                    all_content += round_content
                break  # 有部分内容就退出循环，无内容下面异常处理会 return
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                yield ChatEvent(event_type="error", content=f"连接失败: {str(e)[:200]}")
                return
            except asyncio.CancelledError:
                logger.info("chat_stream_cancelled round=%s", round_num + 1)
                if round_content:
                    all_content += round_content
                break
            except (httpx.HTTPError, OSError, ValueError, json.JSONDecodeError) as e:
                yield ChatEvent(event_type="error", content=f"请求异常: {str(e)[:300]}")
                return

            all_content += round_content
            if usage:
                total_usage = usage

            # 记录 token 用量
            record_cost_usage(usage=usage, model=self.config.model)

            # 无工具调用 → 结束
            if not tool_calls:
                break

            # ── 执行工具调用并反馈给 AI ──
            messages.append(
                {
                    "role": "assistant",
                    "content": round_content,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": tc["function"]["arguments"],
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )

            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    tool_args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    tool_args = {}

                # ── 文件读取缓存 ──
                cached = get_cached_file_read(self._read_file_cache, tool_name, tool_args)
                if cached is not None:
                    yield ChatEvent(
                        event_type="token",
                        content=(
                            f"📋 {tool_name} (缓存): 📁 "
                            f"{tool_args.get('path', '')} 已缓存\n"
                        ),
                    )
                    self._repeating_round_count += 1
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": cached,
                    })
                    continue

                yield ChatEvent(
                    event_type="token",
                    content=f"\n\n🔧 执行 {tool_name}...\n",
                )
                logger.info(
                    "mcp_tool_call_from_ai round=%d tool=%s args=%s",
                    round_num + 1, tool_name, str(tool_args)[:200],
                )

                # 执行工具调用
                result_str = await execute_tool_call(tool_name, tool_args)

                # 文件读取缓存
                cache_file_read(
                    self._read_file_cache, tool_name, tool_args, result_str,
                )

                yield ChatEvent(
                    event_type="token",
                    content=f"📋 {tool_name} 结果:\n```json\n{result_str}\n```\n\n",
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_str,
                    }
                )

            logger.info("tool_round_complete round=%d tools=%d", round_num + 1, len(tool_calls))

            # ── 检测重复循环 ──
            if self._repeating_round_count >= 3 and round_num > 2:
                logger.warning(
                    "early_termination repeating=%d round=%d",
                    self._repeating_round_count, round_num + 1,
                )
                messages.append({
                    "role": "system",
                    "content": "⚠️ 检测到重复操作，请直接输出当前结果报告，不要再调用工具。",
                })
                self._repeating_round_count = 0

            # ── P0-2: 幻觉抑制（工具结果验证）──
            # 注意：result_str 来自上面 for tc in tool_calls 循环；
            # 若 tool_calls 为空，外层 `if not tool_calls: break` 已退出本轮
            if force_tools and result_str and len(result_str) > 100:
                guard_result = await hallucination_validate(
                    result_str,
                    context={"tool": tool_name, "round": round_num + 1},
                )
                if guard_result and guard_result.overall_score < 50:
                    try:
                        parsed = json.loads(result_str) if result_str.startswith("{") else result_str
                    except json.JSONDecodeError:
                        parsed = result_str
                    result_str = json.dumps(
                        {
                            "data": parsed,
                            "⚠️ 幻觉风险": f"可信度 {guard_result.overall_score}/100",
                            "建议": guard_result.recommendations[:2],
                        },
                        ensure_ascii=False, indent=2,
                    )

            # ── P1-1: RuminationEngine（事前+事中）──
            if force_tools and round_num > 0:
                await rumination_pre_execute(tool_name, tool_args)
                rumination_result = await rumination_mid_execute(
                    tool_name, result_str or "", round_num,
                )
                if rumination_result.deviation_score > 0.4:
                    messages.append({
                        "role": "system",
                        "content": rumination_result.correction_msg,
                    })
                self._rumination_count += 1

            # ── P2-3: 代码自愈回滚 ──
            if force_tools and tool_name in ("write_file", "create_file", "patch_file"):
                _path = tool_args.get("path", "")
                if _path and _path.endswith(".py"):
                    async for event in self_heal_after_write_async(_path):
                        yield event

                # 五层代码分析
                if _path and _path.endswith((".py", ".js", ".ts")):
                    async for event in analyze_after_write_async(_path):
                        yield event

            # 🔴 铁律: 多步任务每轮后注入阶段报告指令
            stage_num = round_num + 1
            if max_tool_rounds > 1 and force_tools:
                remaining = max_tool_rounds - round_num - 1
                if remaining > 0:
                    stage_msg = (
                        f"📌 **阶段报告 {stage_num}/{max_tool_rounds} 要求**：\n"
                        f"请先输出当前步骤的**阶段报告**（做了什么、结果、下一步），"
                        f"然后再决定是否继续调用工具。格式：\n"
                        f"`📌 阶段 {stage_num}: [当前步骤名称] — ✅/❌ [状态描述] — 下一步: [计划]`\n"
                        f"**剩余 {remaining} 步**。"
                    )
                else:
                    stage_msg = (
                        "🔴 **最终报告要求**：这是最后一步。请输出完整的**任务总结报告**：\n"
                        "📋 任务报告\n"
                        "├─ 用户需求: （概括）\n"
                        "├─ 完整执行步骤: （列出所有步骤）\n"
                        "├─ 完成状态: ✅已完成\n"
                        "├─ 产出物: （文件列表）\n"
                        "└─ 后续建议: （如有）\n"
                        "**不要再调用工具，直接输出上述报告。**"
                    )
                messages.append({"role": "system", "content": stage_msg})
                yield ChatEvent(
                    event_type="token",
                    content=f"\n📋 📌 阶段报告 {stage_num}/{max_tool_rounds} 已请求...\n",
                )
            elif round_num == max_tool_rounds - 1 and max_tool_rounds <= 1:
                messages.append({
                    "role": "system",
                    "content": "🔴 **输出任务报告**：请输出完整任务报告（需求、步骤、状态、产出物），不要继续调用工具。",
                })

        # P5: 可观测性
        elapsed_ms = (time.perf_counter() - _start_time) * 1000
        record_observability(
            elapsed_ms=elapsed_ms,
            model=self.config.model,
            usage=total_usage,
        )

        # ── P0-2: 最终幻觉抑制验证 ──
        _hallucination_warning = ""
        if force_tools and all_content and len(all_content) > 50:
            guard_result = await hallucination_validate(
                all_content,
                context={"mode": "final", "rounds": round_num + 1},
            )
            if guard_result and guard_result.overall_score < 60:
                _hallucination_warning = format_hallucination_warning(
                    guard_result.overall_score, guard_result.recommendations,
                )

        # ── P1-1: Rumination 最终反思评分 ──
        _rumination_summary, _ = await rumination_post_execute(
            all_content, is_tool_mode=force_tools,
        )

        # ── P2-2: 在线自进化 — 每次 chat 结束记录经验 ──
        await live_learner_observe(
            message,
            success=bool(all_content),
            rounds=round_num + 1,
            mode=effective_mode,
        )

        # ── 报告完整性二次确认 ──
        if force_tools and all_content:
            _has_report = ("报告" in all_content or "📋" in all_content or "📌" in all_content)
            if not _has_report:
                all_content += (
                    "\n\n---\n📋 **任务摘要**\n"
                    f"├─ 执行模式: {effective_mode}\n"
                    f"├─ 工具轮次: {round_num + 1}\n"
                    f"├─ 反思评分: {_rumination_summary}\n"
                    f"├─ 幻觉验证: {'⚠️ 低于阈值' if _hallucination_warning else '✅ 通过'}\n"
                    f"└─ {_rumination_summary if not _has_report else ''}"
                )

        yield ChatEvent(
            event_type="done",
            content=(all_content or "（AI 未生成有效回复，请尝试重新发送您的问题。）")
                     + _hallucination_warning,
            usage=total_usage,
        )

    # ════════════════════════════════════════════════════
    # 资源管理
    # ════════════════════════════════════════════════════

    async def close(self):
        """清理资源"""
        self._history.clear()

    @classmethod
    async def close_global(cls):
        """关闭全局共享 client（应用关闭时调用）"""
        if cls._shared_client is not None:
            await cls._shared_client.aclose()
            cls._shared_client = None

    # ════════════════════════════════════════════════════
    # 自身能力注入
    # ════════════════════════════════════════════════════

    def _build_capabilities_block(self) -> str:
        """生成能力清单块，让 AI 知道自身的功能"""
        try:
            from pycoder.server.capabilities import generate_capabilities

            return generate_capabilities()
        except ImportError:
            return ""
        except Exception:
            import traceback

            traceback.print_exc()
            return ""

    # ── Agent 模式 (兼容 quality_pipeline) ──

    def enable_agent_mode(self, registry=None):
        """启用 Agent 模式 (占位)"""
        pass

    def disable_agent_mode(self):
        """禁用 Agent 模式 (占位)"""
        pass


# ══════════════════════════════════════════════════════════
# 异步生成器适配器（用于将子模块的 yield_event 转换为 ChatEvent 流）
# ══════════════════════════════════════════════════════════


async def self_heal_after_write_async(file_path: str) -> AsyncIterator[ChatEvent]:
    """异步生成器：自愈检查并 yield ChatEvent"""
    async def yield_event(content: str):
        yield ChatEvent(event_type="token", content=content)

    # 用队列桥接子模块的 yield_event 回调
    queue: asyncio.Queue = asyncio.Queue()

    async def event_yield(content: str):
        await queue.put(ChatEvent(event_type="token", content=content))

    async def run_check():
        try:
            await self_heal_after_write(file_path, yield_event=event_yield)
        finally:
            await queue.put(None)  # sentinel

    task = asyncio.create_task(run_check())
    while True:
        ev = await queue.get()
        if ev is None:
            break
        yield ev
    await task


async def analyze_after_write_async(file_path: str) -> AsyncIterator[ChatEvent]:
    """异步生成器：五层代码分析并 yield ChatEvent"""
    async def event_yield(content: str):
        yield ChatEvent(event_type="token", content=content)

    queue: asyncio.Queue = asyncio.Queue()

    async def event_yield_v2(content: str):
        await queue.put(ChatEvent(event_type="token", content=content))

    async def run_analysis():
        try:
            await analyze_after_write(file_path, yield_event=event_yield_v2)
        finally:
            await queue.put(None)

    task = asyncio.create_task(run_analysis())
    while True:
        ev = await queue.get()
        if ev is None:
            break
        yield ev
    await task


__all__ = [
    # 主类
    "ChatBridge",
    "ChatEvent",
    "BridgeConfig",
    "HistoryManager",
    # 路由
    "PROVIDER_API_BASES",
    "MODEL_ROUTING",
    "_detect_provider",
    "_resolve_model_endpoint",
    # Token
    "TokenCounter",
    "estimate_tokens",
    # 上下文
    "_get_context_anchor",
    "_compress_old_messages",
    "_check_token_budget",
    "_apply_context_anchor",
    "_apply_history_sliding_window",
    # 流式
    "parse_sse_line",
    "extract_stream_delta",
    "build_request_payload",
    "rebuild_payload_for_fallback",
    # 工具
    "build_tools_payload",
    "execute_tool_call",
    "execute_tool_with_sandbox",
    "execute_tool_via_v2",
    "execute_tool_via_v1",
    "cache_file_read",
    "get_cached_file_read",
    "SKIP_TOOLS",
    "CATEGORY_TOOL_MAP",
    # 钩子
    "RuminationResult",
    "GuardResult",
    "TaskGrade",
    "grade_task_difficulty",
    "rumination_pre_execute",
    "rumination_mid_execute",
    "rumination_post_execute",
    "hallucination_validate",
    "format_hallucination_warning",
    "maybe_annotate_tool_result",
    "live_learner_observe",
    "record_project_error",
    "record_project_fix_attempt",
    "record_project_file_modified",
    "self_heal_after_write",
    "analyze_after_write",
    "record_observability",
    "record_cost_usage",
    "check_cost_budget",
    "mark_provider_key_invalid",
]
