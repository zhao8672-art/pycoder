"""
ChatBridge — AI 聊天桥接层

替代原 pycoder.tui.bridge.TUIBridge，为 Electron 后端提供无 UI 依赖的流式聊天能力。
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

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
# API Base 映射
# ══════════════════════════════════════════════════════════

PROVIDER_API_BASES = {
    "deepseek": "https://api.deepseek.com",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "openai": "https://api.openai.com/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "agnes": "https://apihub.agnes-ai.com/v1",
}


def _detect_provider(model: str) -> str:
    """检测模型所属的提供商 — 支持更多模型前缀"""
    if not model:
        return "deepseek"
    if model.startswith("deepseek"):
        return "deepseek"
    if model.startswith("qwen"):
        return "qwen"
    if model.startswith("glm"):
        return "glm"
    if model.startswith("gpt") or model.startswith("o"):
        return "openai"
    if model.startswith("claude"):
        return "anthropic"
    if model.startswith("gemini"):
        return "google"
    if model.startswith("z-") or model.startswith("nvidia-"):
        return "nvidia"
    if model.startswith("agnes"):
        return "agnes"
    if model.startswith("openrouter"):
        return "openrouter"
    # 包含斜杠的模型 ID（如 google/gemini-2.0-flash）→ openrouter
    if "/" in model:
        return "openrouter"
    return "deepseek"


# ══════════════════════════════════════════════════════════
# ChatBridge
# ══════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════
# P6: 上下文锚点辅助函数
# ══════════════════════════════════════════════════════


def _get_context_anchor() -> str:
    """获取当前会话的上下文锚点（任务目标 + 进度 + 偏离提醒）

    由 ContextOrchestrator 管理，在每次 LLM 调用前注入到 system prompt 前缀。
    获取失败时静默返回空串，不阻塞主流程。
    """
    try:
        from pycoder.server.services.context_orchestrator import (
            get_orchestrator,
        )

        orch = get_orchestrator()
        if orch and orch.tracker.is_active:
            return orch.get_anchor()
    except (ImportError, AttributeError, TypeError, ValueError):
        pass
    return ""


class ChatBridge:
    """AI 聊天桥接 — 无 UI 依赖，仅提供流式 API 调用"""

    # 类级共享 httpx client（连接池复用）
    _shared_client: object | None = None
    _client_lock = None

    def __init__(self):
        self.config = BridgeConfig()
        self._messages: list[dict] = []

    async def chat(self, prompt: str, *, max_tokens: int = 1000) -> str:
        """简单同步聊天 — 供自进化引擎等内部组件使用，内置 Provider 降级"""
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
                logger.warning("chat_sync_exception provider=%s error=%s", try_prov, e)
                continue

        return ""

    @classmethod
    async def _get_client(cls) -> object:
        """获取或创建共享 httpx client（带连接池）。"""
        if cls._shared_client is None:
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

    def add_message(self, role: str, content: str):
        """添加上下文消息"""
        self._messages.append({"role": role, "content": content})

    def _get_effective_messages(self) -> list[dict]:
        """M5: 返回发给 LLM 的历史消息（应用滑窗截断 + 记忆压缩 + 上下文锚点）

        当消息数超过 max_history_messages 时:
        - 旧消息压缩为摘要（agent_memory.AgentMemoryManager）
        - 摘要作为 system 消息插入到开头
        - 最近消息保留完整

        保留 _messages 完整历史供审计/序列化；仅截断本次发给 LLM 的副本。
        max_history_messages=0 表示不截断。

        P6: 上下文锚点 —— 从 ContextOrchestrator 注入任务目标/进度/偏离提醒
        作为 system message 前缀，确保 LLM 始终知道当前任务上下文。
        """
        messages = list(self._messages)
        max_hist = self.config.max_history_messages
        if max_hist > 0 and len(messages) > max_hist:
            dropped_messages = messages[:-max_hist]
            kept_messages = messages[-max_hist:]
            # P1: 压缩旧消息为摘要，避免丢失早期关键信息
            compressed = self._compress_old_messages(dropped_messages)
            messages = kept_messages
            if compressed:
                messages.insert(0, {"role": "system", "content": compressed})
            logger.debug(
                "chat_history_compressed dropped=%d kept=%d summary_len=%d",
                len(dropped_messages),
                max_hist,
                len(compressed),
            )

        # P6: 注入上下文锚点（任务目标 + 进度 + 偏离提醒）
        anchor = _get_context_anchor()
        if anchor and messages:
            # 追加到已存在的 system message 后面，或插入新 system
            if messages[0].get("role") == "system":
                messages[0]["content"] = anchor + "\n\n---\n" + str(messages[0]["content"])
            else:
                messages.insert(0, {"role": "system", "content": anchor})

        return messages

    def _check_token_budget(self, messages: list[dict]) -> int:
        """精确计算消息列表的 token 数，超出阈值时预警"""
        msg_str = json.dumps([{"role": m.get("role", ""), "content": m.get("content", "")} for m in messages])
        estimated = TokenCounter.count(msg_str)
        if estimated > 60000:
            logger.warning(
                "context_near_limit estimated=%d limit=64000",
                estimated,
            )
        return estimated

    def _compress_old_messages(self, old_messages: list[dict]) -> str:
        """压缩旧消息为摘要文本（零延迟规则提取，不调用 LLM）

        失败时降级为空串，不影响主流程。
        """
        if not old_messages:
            return ""
        try:
            from pycoder.server.services.agent_memory import get_memory_manager

            manager = get_memory_manager()
            return manager.compress_history(old_messages)
        except (ImportError, RuntimeError, OSError, ValueError) as e:
            logger.debug("memory_compress_failed error=%s", e)
            return ""


# ══════════════════════════════════════════════════════════
# TokenCounter — 精确 Token 计数器 (tiktoken)
# ══════════════════════════════════════════════════════════


    # ── 智能意图分类 ──
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

        # 5. 长消息 → 默认为 tool 模式（用户可能在描述复杂需求）
        return ("tool", True, 5)

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
            effective_mode, force_tools, max_tool_rounds = self._classify_intent(message)
            if effective_mode == "chat":
                logger.debug(
                    "intent_router chat_mode msg_len=%d preview=%s",
                    len(message), message[:50],
                )

        # ── 构建 Provider 降级链 ──
        # 按优先级获取所有可用 Provider，当主 Provider 返回 401 时自动降级
        fallback_providers: list[tuple[str, str, str]] = []
        try:
            from pycoder.providers.auth import PROVIDER_DEFS, ModelManager

            mm = ModelManager()
            detected = mm.auto_detect()
            # 按 PROVIDER_DEFS 优先级排序
            for pname, pdefs in sorted(PROVIDER_DEFS.items(), key=lambda x: x[1]["priority"]):
                if pname in detected:
                    pkey = detected[pname]
                    model_id = pdefs["recommended_model"]
                    pbase = PROVIDER_API_BASES.get(pname, "https://api.deepseek.com")
                    fallback_providers.append((model_id, pkey, pbase))
            if not fallback_providers:
                # 尝试从环境变量直接读取
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
        # 仅 tool 模式注入 V2 能力块（chat 模式不需要）
        if force_tools:
            caps = self._build_capabilities_block()
            if caps:
                if effective_system:
                    effective_system = effective_system + "\n\n---\n" + caps
                else:
                    effective_system = caps

        # 3) 规范化消息结构（system 在 [0]，差异化在末尾，字段顺序固定）
        from pycoder.prompts.cache_rules import canonicalize_messages

        messages = canonicalize_messages(messages, effective_system)
        # system 已经由 canonicalize 自动插入，不再手动 insert

        messages.append({"role": "user", "content": message})

        # ── 成本熔断预检 ──
        try:
            from pycoder.server.services.cost_control import get_cost_controller

            estimated = estimate_tokens(message) + sum(
                estimate_tokens(m.get("content", "")) for m in messages
            )
            ok, reason = get_cost_controller().check_before_call(estimated)
            if not ok:
                yield ChatEvent(event_type="error", content=f"成本超限: {reason}")
                return
        except (ImportError, RuntimeError, OSError, ValueError, TypeError) as e:
            logger.warning("cost_check_failed error=%s", e)

        # ── 构建 tools payload（仅 tool 模式构建，chat 模式为空）──
        tools_payload: list[dict] = []
        if force_tools:
            try:
                from pycoder.server.mcp_tools import list_builtin_tools

                all_tools = list_builtin_tools()
                skip_tools = {"refresh_extensions", "skills_sync_v2", "system_upgrade"}

                if tool_names is not None:
                    name_set = set(tool_names)
                    all_tools = [t for t in all_tools if t.get("name", "") in name_set]

                # ── V2: 合并 V2 能力到工具列表 ──
                try:
                    from pycoder.server.app import get_v2_engine

                    v2_engine = get_v2_engine()
                    if v2_engine:
                        for cap in v2_engine.registry.list_all():
                            cap_short = cap.id.split(".")[-1]
                            if tool_names is not None and cap_short not in name_set:
                                continue
                            tools_payload.append(
                                {
                                    "type": "function",
                                    "function": {
                                        "name": cap.id.replace(".", "_"),
                                        "description": f"[V2] {cap.description}",
                                        "parameters": cap.schema
                                        or {"type": "object", "properties": {}},
                                    },
                                }
                            )
                except (ImportError, AttributeError, TypeError, ValueError):
                    pass

                for t in all_tools:
                    import re as _re

                    name = t.get("name", "")
                    if name in skip_tools:
                        continue
                    safe_name = _re.sub(r"[^a-zA-Z0-9_-]", "_", name)
                    schema = t.get("input_schema", {"type": "object", "properties": {}})
                    tools_payload.append(
                        {
                            "type": "function",
                            "function": {
                                "name": safe_name,
                                "description": t.get("description", ""),
                                "parameters": schema,
                            },
                        }
                    )
            except (ImportError, RuntimeError) as e:
                logger.warning("tools_injection_failed error=%s", e)

        # ── 缓存命中率优化: 规范化 tools 序列顺序 ──
        from pycoder.prompts.cache_rules import canonicalize_tools

        tools_payload = canonicalize_tools(tools_payload)

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

        # ── ReAct 工具调用循环 ──
        for round_num in range(max(max_tool_rounds, 1)):
            # 仅在非首轮或明确需要工具时显示进度
            if round_num > 0 and force_tools:
                yield ChatEvent(
                    event_type="token",
                    content=f"\n🔄 第 {round_num + 1}/{max_tool_rounds} 轮...\n",
                )
            payload: dict = {
                "model": self.config.model,
                "messages": messages,
                "stream": True,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
            }
            if is_deepseek and self.config.enable_thinking:
                payload["reasoning_effort"] = self.config.reasoning_effort
            if is_deepseek and self.config.enable_cache:
                payload["enable_cache"] = True
            if tools_payload:
                payload["tools"] = tools_payload
                payload["tool_choice"] = "auto"

            round_content = ""
            usage: dict = {}
            tool_calls: list[dict] = []

            try:
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
                        # D2: 诊断日志
                        logger.error(
                            "D2_CHAT_401 model=%s base=%s key_pref=%s status=%d body=%s",
                            current_model,
                            self.config.api_base,
                            self.config.api_key[:12] + "..." if self.config.api_key else "NOKEY",
                            response.status_code,
                            err_text[:100],
                        )
                        tried_providers.add(current_model)

                        # 尝试降级到下一个可用 Provider
                        if fallback_providers:
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
                                # 更新请求头
                                headers["Authorization"] = f"Bearer {nk}"
                                # 更新 payload model
                                payload["model"] = nm
                                # 重建 KV cache 等 DeepSeek 特有选项
                                if is_deepseek and self.config.enable_thinking:
                                    payload["reasoning_effort"] = self.config.reasoning_effort
                                elif "reasoning_effort" in payload:
                                    del payload["reasoning_effort"]
                                if is_deepseek and self.config.enable_cache:
                                    payload["enable_cache"] = True
                                elif "enable_cache" in payload:
                                    del payload["enable_cache"]
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
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            continue
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        if choice := (data.get("choices") or [None])[0]:
                            delta = choice.get("delta") or {}
                            if delta.get("reasoning_content"):
                                yield ChatEvent(
                                    event_type="reasoning", content=delta["reasoning_content"]
                                )
                            if content := delta.get("content"):
                                round_content += content
                                yield ChatEvent(event_type="token", content=content)
                            # 流式累积工具调用
                            if delta.get("tool_calls"):
                                for tc in delta["tool_calls"]:
                                    idx = tc.get("index", 0)
                                    while len(tool_calls) <= idx:
                                        tool_calls.append(
                                            {"id": "", "function": {"name": "", "arguments": ""}}
                                        )
                                    if tc.get("id"):
                                        tool_calls[idx]["id"] += tc["id"]
                                    if tc.get("function"):
                                        if tc["function"].get("name"):
                                            tool_calls[idx]["function"]["name"] += tc["function"][
                                                "name"
                                            ]
                                        if tc["function"].get("arguments"):
                                            tool_calls[idx]["function"]["arguments"] += tc[
                                                "function"
                                            ]["arguments"]
                            if choice.get("finish_reason") == "tool_calls":
                                break

                        if data.get("usage"):
                            usage = data["usage"]

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                yield ChatEvent(event_type="error", content=f"连接失败: {str(e)[:200]}")
                return
            except Exception as e:
                yield ChatEvent(event_type="error", content=f"请求异常: {str(e)[:300]}")
                return

            all_content += round_content
            if usage:
                total_usage = usage

            # 记录 token 用量
            if usage:
                try:
                    from pycoder.server.services.cost_control import get_cost_controller

                    get_cost_controller().record_usage(
                        input_tokens=usage.get("prompt_tokens", 0),
                        output_tokens=usage.get("completion_tokens", 0),
                        model=self.config.model,
                    )
                except (ImportError, RuntimeError, ValueError, TypeError) as e:
                    logger.warning("cost_record_failed error=%s", e)

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

                yield ChatEvent(event_type="token", content=f"\n\n🔧 执行 {tool_name}...\n")
                logger.info(
                    "mcp_tool_call_from_ai round=%d tool=%s args=%s",
                    round_num + 1,
                    tool_name,
                    str(tool_args)[:200],
                )

                try:
                    # ── V2: 优先通过能力总线执行 ──
                    result_str = None
                    try:
                        from pycoder.server.app import get_v2_engine

                        v2_engine = get_v2_engine()
                        if v2_engine:
                            cap_id = tool_name.replace("_", ".")
                            cap_result = await v2_engine.call(
                                cap_id, tool_args, caller="chatbridge"
                            )
                            if cap_result.success:
                                result_str = json.dumps(
                                    cap_result.data if cap_result.data else {"ok": True},
                                    ensure_ascii=False,
                                    indent=2,
                                )
                                # M9: 与 V1 路径保持一致的动态截断逻辑
                                max_result_len = 8000 if tool_name == "list_agent_configs" else 3000
                                result_str = result_str[:max_result_len]
                            elif cap_result.error_code != "NOT_FOUND":
                                result_str = json.dumps(
                                    {"error": cap_result.error}, ensure_ascii=False
                                )
                    except (AttributeError, TypeError, ValueError):
                        pass

                    # ── V1: 回退到 mcp_tools ──
                    if result_str is None:
                        from pycoder.server.mcp_tools import call_builtin_tool

                        result = await call_builtin_tool(tool_name, tool_args)
                        if result.success:
                            result_str = json.dumps(result.output, ensure_ascii=False, indent=2)
                            # M9: list_agent_configs 等工具输出较大（7角色×12字段≈7KB），提高截断上限
                            max_result_len = 8000 if tool_name == "list_agent_configs" else 3000
                            result_str = result_str[:max_result_len]
                        else:
                            result_str = json.dumps({"error": result.error}, ensure_ascii=False)
                except Exception as e:
                    result_str = json.dumps({"error": str(e)[:500]}, ensure_ascii=False)

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

            # 🔴 铁律: 多步任务每轮后注入阶段报告指令
            if max_tool_rounds > 1 and force_tools:
                remaining = max_tool_rounds - round_num - 1
                if remaining > 0:
                    # 还有后续步骤 → 要求阶段报告
                    stage_num = round_num + 1
                    stage_msg = (
                        f"📌 **阶段报告 {stage_num}/{max_tool_rounds} 要求**：\n"
                        f"请先输出当前步骤的**阶段报告**（做了什么、结果、下一步），"
                        f"然后再决定是否继续调用工具。格式：\n"
                        f"`📌 阶段 {stage_num}: [当前步骤名称] — ✅/❌ [状态描述] — 下一步: [计划]`\n"
                        f"**剩余 {remaining} 步**。"
                    )
                else:
                    # 最后一步 → 要求最终完整报告
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
                # 单步任务 → 要求最终报告
                messages.append({"role": "system", "content": (
                    "🔴 **输出任务报告**：请输出完整任务报告（需求、步骤、状态、产出物），不要继续调用工具。"
                )})
            # else: 单步 chat 模式无工具有报告 → LLM 自然会回复

        # P5: 可观测性 — 记录延迟和 token 消耗
        try:
            from pycoder.server.services.observability import get_metrics, track_tokens

            metrics = get_metrics()
            elapsed_ms = (time.perf_counter() - _start_time) * 1000
            metrics.observe("chat_latency_ms", elapsed_ms, labels={"model": self.config.model})
            metrics.increment("chat_requests_total", labels={"model": self.config.model})
            if total_usage:
                track_tokens(
                    self.config.model,
                    total_usage.get("prompt_tokens", 0),
                    total_usage.get("completion_tokens", 0),
                )
        except (ImportError, RuntimeError, ValueError, TypeError):
            pass  # 可观测性失败不影响主流程

        yield ChatEvent(
            event_type="done",
            content=all_content or "（AI 未生成有效回复，请尝试重新发送您的问题。）",
            usage=total_usage,
        )

    async def close(self):
        """清理资源"""
        self._messages.clear()

    @classmethod
    async def close_global(cls):
        """关闭全局共享 client（应用关闭时调用）"""
        if cls._shared_client is not None:
            await cls._shared_client.aclose()
            cls._shared_client = None

    # ── 自身能力注入 ──

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
# 工具函数
# ══════════════════════════════════════════════════════════


def estimate_tokens(text: str) -> int:
    """估算文本的 token 数量 (~每中文字符1token，每英文词1.3token)"""
    if not text:
        return 0


# ══════════════════════════════════════════════════════════
# P4: 多模型路由支持
# ══════════════════════════════════════════════════════════

MODEL_ROUTING: dict[str, dict[str, str]] = {
    "deepseek": {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base": "https://api.deepseek.com",
    },
    "deepseek-reasoner": {
        "provider": "deepseek",
        "model": "deepseek-reasoner",
        "base": "https://api.deepseek.com",
    },
    "qwen": {
        "provider": "qwen",
        "model": "qwen-coder-plus",
        "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    "glm": {
        "provider": "glm",
        "model": "glm-4-flash",
        "base": "https://open.bigmodel.cn/api/paas/v4",
    },
    "gpt-4o-mini": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "base": "https://api.openai.com/v1",
    },
}


def _resolve_model_endpoint(model: str) -> tuple[str, str]:
    """解析模型名称为 API Base URL + 实际模型名

    Args:
        model: 模型名称（deepseek/qwen/glm/gpt-4o-mini 等）

    Returns:
        (api_base_url, resolved_model_name)
    """
    # 检查是否匹配已知模型
    route = MODEL_ROUTING.get(model)
    if route:
        return route["base"], route["model"]

    # 通过前缀匹配
    for prefix, route in [
        ("deepseek-reasoner", MODEL_ROUTING.get("deepseek-reasoner")),
        ("deepseek", MODEL_ROUTING.get("deepseek")),
        ("qwen", MODEL_ROUTING.get("qwen")),
        ("glm", MODEL_ROUTING.get("glm")),
        ("gpt", MODEL_ROUTING.get("gpt-4o-mini")),
    ]:
        if model.startswith(prefix) and route:
            return route["base"], model

    # 默认回退到 DeepSeek
    return (
        PROVIDER_API_BASES.get("deepseek", "https://api.deepseek.com"),
        model,
    )


class TokenCounter:
    """精确 Token 计数器 — 使用 tiktoken (兼容 cl100k_base)

    当 tiktoken 不可用时自动降级为 len//3 估算。
    """

    _encoders: dict[str, object] = {}

    @classmethod
    def count(cls, text: str, model: str = "deepseek-chat") -> int:
        """精确计算 token 数"""
        try:
            encoding = cls._get_encoding(model)
            return len(encoding.encode(text))
        except (ImportError, KeyError, ValueError):
            return len(text) // 3  # 降级估算

    @classmethod
    def truncate(cls, text: str, max_tokens: int, model: str = "deepseek-chat") -> str:
        """精确截断到指定 token 数"""
        try:
            encoding = cls._get_encoding(model)
            tokens = encoding.encode(text)
            return encoding.decode(tokens[:max_tokens])
        except (ImportError, KeyError):
            return text[:max_tokens * 3]  # 降级截断

    @classmethod
    def _get_encoding(cls, model: str):
        """获取编码器（带缓存）"""
        if model not in cls._encoders:
            import tiktoken
            # DeepSeek/Qwen/GLM 兼容 cl100k_base
            cls._encoders[model] = tiktoken.get_encoding("cl100k_base")
        return cls._encoders[model]

def estimate_tokens(text: str) -> int:
    """估算文本的 token 数量 (~每中文字符1token，每英文词1.3token)"""
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other_chars = len(text) - chinese_chars
    return int(chinese_chars * 1.2 + other_chars / 2.5) + 4
