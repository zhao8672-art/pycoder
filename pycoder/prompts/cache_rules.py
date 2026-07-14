"""
Prompt Cache 命中率优化规则 — pycoder 全 Agent 强制遵守

背景：
    DeepSeek / Claude / GPT 等主流 LLM 均支持自动前缀缓存（Prefix / KV Cache）。
    当连续请求的 prompt 前缀（包括 system prompt、历史消息结构、tools 列表）一致时，
    服务端自动命中缓存，省去重复 Token 计算，最高可降低 90% 输入成本。

适用范围：
    本规则适用于 pycoder 所有现有及未来新增的 Agent（hermes / pm / architect /
    developer / qa / fixer / documenter / devops / unified_entry / 自定义Agent）。
    在 `chat_bridge.py`、`agent_loop.py`、`agent_orchestrator.py` 等组装 prompt
    的位置强制生效。

使用方式：
    from pycoder.prompts.cache_rules import CACHE_RULES_PROMPT, apply_cache_rules
"""

from __future__ import annotations

import hashlib

# ══════════════════════════════════════════════════════════
# 一、注入到 system prompt 的规则文本（中文 / 英文）
# ══════════════════════════════════════════════════════════

CACHE_RULES_PROMPT_ZH = """
## ⛓️ Prompt 缓存优化规则（强制遵守 — 降低 Token 成本）

LLM 服务端会根据 prompt 前缀自动缓存计算中间结果（KV Cache）。
遵守以下规则，可大幅提高缓存命中率，降低每次调用的输入成本。

### 1. 前缀稳定性 — 最高优先级
- **system prompt 高稳定在前**：你的 system prompt 内容不变时，其位置和顺序不能变。
  不要在 system prompt 之前插入任何差异化内容（时间戳、用户名、UUID）。
- **工具/函数定义固定序列化**：当 tools 列表不变时，必须保持完全相同的 JSON 顺序。
  不要在运行时动态插入/删除工具定义。
- **每条指令块的格式和分隔符固定**：使用与上一轮相同的 markdown 标题层级和分隔线。

### 2. 消息结构一致性
- **多轮对话格式严格对齐**：role/name/content 字段顺序不变。
- **历史消息稳定保留**：已被 LLM 处理的多轮历史不要重新排序或重写。
- **系统消息放在 messages[0]**：始终作为对话的第一条，不要在中间插入新的 system 消息。

### 3. 差异化内容放到末尾
- 本次请求特有的用户输入、文件内容、上下文摘要放在消息列表的**最后一条**。
- 不要把差异化内容插入到历史消息中间。
- 不要在 system prompt 中嵌入时间戳或动态 ID。

### 4. 批量操作透传缓存
- 同一 session 内连续调用时，保持 messages 列表是**追加**模式（append-only）。
- 不要删除中间轮次的 assistant/tool 消息（除非滑窗截断超出 context window）。
- 工具调用返回结果保持与 tool_call_id 的精确对应关系。

### 5. 失败重试复用缓存
- 同级重试（retry）时，只修改最后一个 user message 的内容，不要重建整个 messages 数组。
- 如需切换模型，标注为新 session 以避免缓存污染。

### 自检清单
- [ ] system prompt 在 messages[0]，且本轮与上轮完全一致
- [ ] tools 列表 JSON 序列化顺序不变
- [ ] 差异化内容仅在最后一条 user message 中
- [ ] 历史消息保持原始顺序，未重新排序
"""

CACHE_RULES_PROMPT_EN = """
## ⛓️ Prompt Cache Optimization Rules (MANDATORY — Reduce Token Cost)

LLM servers automatically cache intermediate computations (KV Cache) based on
prompt prefixes. Following these rules dramatically improves cache hit rates,
reducing per-call input costs by up to 90%.

### 1. Prefix Stability — Highest Priority
- **System prompt stays first and unchanged**: Do not insert timestamps, user
  names, or UUIDs before the system prompt.
- **Tools / functions list in fixed order**: When the tools list doesn't change,
  keep the exact same JSON serialization order. Never dynamically insert/remove
  tool definitions at runtime.
- **Consistent formatting and separators**: Use the same markdown heading levels
  and section separators as the previous round.

### 2. Message Structure Consistency
- **Multi-turn format strictly aligned**: role/name/content field order unchanged.
- **Historical messages preserved as-is**: Do not reorder or rewrite multi-turn
  history that the LLM has already processed.
- **System message always at messages[0]**: Never insert a new system message
  in the middle of the conversation.

### 3. Differentiated Content at the End
- User input, file contents, and context summaries that are unique to this
  request should be in the **last** user message only.
- Do not insert differentiated content into the middle of the history.
- Never embed timestamps or dynamic IDs in the system prompt.

### 4. Append-Only for Cache Transparency
- Within the same session, keep the messages list in **append-only** mode.
- Do not delete assistant/tool messages from intermediate rounds (unless a
  sliding window truncation is required due to context window limits).
- Tool call responses must maintain exact correspondence with tool_call_id.

### 5. Retry Reuses Cache
- On same-tier retries, modify only the last user message — do not rebuild
  the entire messages array.
- If switching models, mark as a new session to avoid cache pollution.

### Self-Check Checklist
- [ ] System prompt at messages[0], identical to previous round
- [ ] Tools list JSON serialization order unchanged
- [ ] Differentiated content only in the last user message
- [ ] History messages preserved in original order
"""

# ══════════════════════════════════════════════════════════
# 二、运行时验证工具
# ══════════════════════════════════════════════════════════


def _hash_prefix(messages: list[dict], prefix_len: int = 2) -> str:
    """计算 messages 前缀哈希（用于判断是否可命中缓存）"""
    try:
        prefix = messages[:prefix_len]
        raw = _json_stable_dumps(prefix)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]
    except Exception:
        return "invalid"


def _json_stable_dumps(obj, sort_keys: bool = True) -> str:
    """稳定的 JSON 序列化，确保相同结构相同序列"""
    import json
    return json.dumps(obj, ensure_ascii=False, sort_keys=sort_keys)


def compute_cache_fingerprint(
    messages: list[dict],
    tools: list[dict] | None = None,
    system_fingerprint: str = "",
) -> str:
    """计算当前请求的缓存指纹

    Args:
        messages: 对话历史
        tools: 工具列表
        system_fingerprint: system prompt 内容哈希（外部计算）

    Returns:
        12 位 hex 指纹
    """
    parts = [system_fingerprint]
    if tools:
        parts.append(_json_stable_dumps(tools))
    parts.append(_hash_prefix(messages, min(3, len(messages))))
    combined = "|".join(parts)
    return hashlib.sha256(combined.encode()).hexdigest()[:12]


class CacheHitTracker:
    """缓存命中追踪器

    在 `chat_bridge.chat_stream()` 中每次调用后记录指纹，
    下次调用前对比判断是否命中缓存。
    """

    def __init__(self):
        self._last_fingerprint: str = ""
        self._request_count: int = 0
        self._estimated_hits: int = 0
        self._last_system_hash: str = ""

    def set_system_hash(self, system_prompt: str) -> None:
        """记录 system prompt 哈希（用于前缀稳定性检测）"""
        self._last_system_hash = hashlib.sha256(
            system_prompt.encode(),
        ).hexdigest()[:12]

    def check_hit(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> tuple[bool, str]:
        """检查是否可能命中缓存

        Returns:
            (是否可能命中, 当前指纹)
        """
        self._request_count += 1
        fp = compute_cache_fingerprint(messages, tools, self._last_system_hash)
        hit = fp == self._last_fingerprint and self._request_count > 1
        self._last_fingerprint = fp
        if hit:
            self._estimated_hits += 1
        return hit, fp

    @property
    def hit_rate(self) -> float:
        """估算缓存命中率"""
        if self._request_count < 2:
            return 0.0
        return self._estimated_hits / max(self._request_count - 1, 1)


# ══════════════════════════════════════════════════════════
# 三、消息列表规范化（运行时自动修正）
# ══════════════════════════════════════════════════════════


def canonicalize_messages(
    messages: list[dict],
    system_prompt: str = "",
) -> list[dict]:
    """规范化消息列表，最大化缓存命中概率

    规则：
    1. system message 必须在 messages[0]，且必须完整保留。
    2. 去除重复的 system message。
    3. 确保 role/name/content 字段顺序固定。
    4. 历史消息保持 append-only 顺序。

    Args:
        messages: 原始消息列表
        system_prompt: system 消息内容（如果 messages 中没有则插入）

    Returns:
        规范化后的消息列表
    """
    result: list[dict] = []

    # 插入 system prompt 作为第一条
    if system_prompt:
        result.append({"role": "system", "content": system_prompt})

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # 去除重复的 system 消息
        if role == "system":
            if not system_prompt or not result:
                result.append({"role": "system", "content": content})
            continue

        # 重建为稳定字段顺序
        clean: dict = {"role": role, "content": content}
        if msg.get("name"):
            clean["name"] = msg["name"]
        if msg.get("tool_calls"):
            clean["tool_calls"] = msg["tool_calls"]
        if msg.get("tool_call_id"):
            clean["tool_call_id"] = msg["tool_call_id"]
            clean["role"] = "tool"

        result.append(clean)

    return result


def canonicalize_tools(tools: list[dict]) -> list[dict]:
    """规范化 tools 列表，确保稳定的 JSON 序列化顺序

    按 function.name 排序，确保每次请求的 tools 序列相同。
    """
    if not tools:
        return tools
    return sorted(
        tools,
        key=lambda t: (
            t.get("type", "function"),
            t.get("function", {}).get("name", ""),
        ),
    )


# ══════════════════════════════════════════════════════════
# 四、便捷工厂 — 返回适用于 system prompt 注入的规则片段
# ══════════════════════════════════════════════════════════


def get_cache_rules(lang: str = "zh") -> str:
    """获取缓存规则文本（用于追加到 system prompt 末尾）

    Args:
        lang: "zh" 或 "en"

    Returns:
        缓存规则 markdown 文本
    """
    return CACHE_RULES_PROMPT_ZH if lang == "zh" else CACHE_RULES_PROMPT_EN


def inject_cache_rules(system_prompt: str, lang: str = "zh") -> str:
    """将缓存规则追加到 system prompt 末尾

    已包含缓存规则则跳过，避免重复注入。
    """
    marker = "缓存优化规则（强制遵守" if lang == "zh" else "Cache Optimization Rules (MANDATORY"
    if marker in system_prompt:
        return system_prompt
    return system_prompt.rstrip() + "\n\n" + get_cache_rules(lang)
