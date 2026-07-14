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
}


def _detect_provider(model: str) -> str:
    if model.startswith("deepseek"):
        return "deepseek"
    if model.startswith("qwen"):
        return "qwen"
    if model.startswith("glm"):
        return "glm"
    if model.startswith("gpt") or model.startswith("o"):
        return "openai"
    if model.startswith("z-") or model.startswith("nvidia-"):
        return "nvidia"
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
        """简单同步聊天 — 供自进化引擎等内部组件使用"""
        client = await ChatBridge._get_client()
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.model or "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
        try:
            resp = await client.post(
                f"{self.config.api_base}/chat/completions",
                headers=headers, json=payload, timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except (OSError, ValueError, KeyError, AttributeError):
            pass
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
        """配置模型、API Key、系统提示词和最大 Token 数"""
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
                messages[0]["content"] = (
                    anchor + "\n\n---\n" + str(messages[0]["content"])
                )
            else:
                messages.insert(0, {"role": "system", "content": anchor})

        return messages

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

    async def chat_stream(self, message: str) -> AsyncIterator[ChatEvent]:
        """流式聊天 — 支持多轮工具调用循环

        当 AI 发起 function call 时，自动执行工具、将结果反馈给 AI，
        AI 基于结果继续生成回复，直到不再需要工具调用（最多 5 轮）。

        Args:
            message: 用户消息

        Yields:
            ChatEvent: event_type ∈ {"token", "reasoning", "done", "error"}
        """
        import httpx

        # P5: 可观测性 — 记录开始时间
        _start_time = time.perf_counter()

        api_key = self.config.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            yield ChatEvent(event_type="error", content="未配置 API Key，请运行 --setup 配置")
            return

        # ── 构建消息上下文 ──
        messages = self._get_effective_messages()

        # ── 注入缓存命中率优化规则 + V2 能力 ──
        caps = self._build_capabilities_block()
        effective_system = self.config.system_prompt
        # 1) 将缓存优化规则追加到 system prompt
        if effective_system:
            from pycoder.prompts.cache_rules import inject_cache_rules
            effective_system = inject_cache_rules(effective_system, lang="zh")
        # 2) 追加 V2 能力块
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

        # ── 构建 tools payload（仅首轮需要） ──
        tools_payload: list[dict] = []
        try:
            from pycoder.server.mcp_tools import list_builtin_tools

            all_tools = list_builtin_tools()
            skip_tools = {"refresh_extensions", "skills_sync_v2", "system_upgrade"}

            # ── V2: 合并 V2 能力到工具列表 ──
            try:
                from pycoder.server.app import get_v2_engine
                v2_engine = get_v2_engine()
                if v2_engine:
                    for cap in v2_engine.registry.list_all():
                        tools_payload.append({
                            "type": "function",
                            "function": {
                                "name": cap.id.replace(".", "_"),
                                "description": f"[V2] {cap.description}",
                                "parameters": cap.schema or {"type": "object", "properties": {}},
                            },
                        })
            except (ImportError, AttributeError, TypeError, ValueError):
                pass

            for t in all_tools:
                name = t.get("name", "")
                if name in skip_tools:
                    continue
                schema = t.get("input_schema", {"type": "object", "properties": {}})
                tools_payload.append(
                    {
                        "type": "function",
                        "function": {
                            "name": name,
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
        max_rounds = 5

        # ── 工具调用循环 ──
        for round_num in range(max_rounds):
            # P2+: 每轮发送进度心跳，保持 WebSocket 活跃
            yield ChatEvent(
                event_type="token",
                content=f"\n🔄 第 {round_num + 1}/{max_rounds} 轮工具调用...\n",
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
                            cap_result = await v2_engine.call(cap_id, tool_args, caller="chatbridge")
                            if cap_result.success:
                                result_str = json.dumps(
                                    cap_result.data if cap_result.data else {"ok": True},
                                    ensure_ascii=False, indent=2,
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
    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other_chars = len(text) - chinese_chars
    return int(chinese_chars * 1.2 + other_chars / 2.5) + 4
