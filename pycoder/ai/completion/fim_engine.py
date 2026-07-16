"""
Fill-in-the-Middle 代码补全引擎

利用 DeepSeek FIM API 实现光标位置感知的代码补全:
  - FIM 补全: 根据前缀和后缀生成中间代码
  - 多候选返回: 支持 n 个候选方案
  - 上下文感知: 自动提取光标周围的代码上下文

API 接口:
  POST https://api.deepseek.com/beta/completions
  {
    "model": "deepseek-chat",
    "prompt": "<|fim_prefix|>prefix<|fim_suffix|>suffix<|fim_middle|>",
    "suffix": "...",
    "max_tokens": 256,
    "temperature": 0.2,
    "top_p": 0.95
  }
"""

from __future__ import annotations

import hashlib
import logging
import re
import time

logger = logging.getLogger(__name__)


# ── 语言模板 ──

LANGUAGE_FIM_TEMPLATES: dict[str, str] = {
    "python": "{prefix}█{suffix}",
    "javascript": "{prefix}█{suffix}",
    "typescript": "{prefix}█{suffix}",
    "java": "{prefix}█{suffix}",
    "go": "{prefix}█{suffix}",
    "rust": "{prefix}█{suffix}",
    "cpp": "{prefix}█{suffix}",
    "c": "{prefix}█{suffix}",
    "sql": "{prefix}█{suffix}",
}

# 补全提示模板
FIM_CHAT_PROMPT = """\
补全以下 {language} 代码中标记为 █ 的位置:

```{language}
{prefix}█{suffix}
```

只输出 █ 位置的补全代码，不要包含多余的解释。
"""


class FIMCodeCompleter:
    """FIM 代码补全器 — 光标位置感知的智能补全"""

    def __init__(self) -> None:
        self._bridge: object = None
        self._cache: dict[str, list[str]] = {}

    async def complete(
        self,
        prefix: str,
        suffix: str = "",
        language: str = "python",
        n: int = 3,
        max_tokens: int = 256,
        temperature: float = 0.2,
    ) -> list[str]:
        """执行 FIM 补全，返回 n 个候选

        Args:
            prefix: 光标前/上文的代码
            suffix: 光标后/下文的代码
            language: 编程语言
            n: 返回候选数 (1-5)
            max_tokens: 补全最大 token 数
            temperature: 采样温度 (0-1)
        Returns:
            按分数降序的补全候选列表
        """
        # 生成缓存 key
        cache_key = self._make_cache_key(prefix, suffix, language, n)

        # 检查缓存
        if cache_key in self._cache:
            logger.debug("FIM 缓存命中")
            return self._cache[cache_key]

        start = time.time()

        # 先尝试 DeepSeek FIM 专用 API
        candidates = await self._try_fim_api(prefix, suffix, language, n, max_tokens, temperature)

        # 回退到 Chat-based FIM
        if not candidates:
            try_fim = self._try_chat_fim(
                prefix, suffix, language, n, max_tokens, temperature,
            )
            candidates = await try_fim

        # 后处理: 去重 + 修剪
        candidates = self._deduplicate(candidates)
        candidates = [self._trim_completion(c, prefix, suffix) for c in candidates]
        candidates = [c for c in candidates if c.strip()]

        # 更新缓存
        if candidates:
            self._cache[cache_key] = candidates[:n]

        logger.info(
            "FIM 补全完成: lang=%s, candidates=%d, time=%.0fms",
            language, len(candidates), (time.time() - start) * 1000,
        )

        return candidates[:n]

    async def complete_single(
        self,
        prefix: str,
        suffix: str = "",
        language: str = "python",
    ) -> str:
        """单候选 FIM 补全 (快速)"""
        results = await self.complete(
            prefix, suffix, language,
            n=1, max_tokens=128, temperature=0.1,
        )
        return results[0] if results else ""

    async def _try_fim_api(
        self, prefix: str, suffix: str, language: str,
        n: int, max_tokens: int, temperature: float,
    ) -> list[str]:
        """尝试 DeepSeek FIM 专用 API"""
        try:
            from pycoder.server.chat_bridge import PROVIDER_API_BASES

            api_base = PROVIDER_API_BASES.get("deepseek", "https://api.deepseek.com")
            url = f"{api_base}/beta/completions"  # DeepSeek FIM 端点

            # 获取 API Key
            from pycoder.providers.auth import get_model_manager
            mm = get_model_manager()
            api_key = mm.get_saved_key("deepseek")
            if not api_key:
                return []

            # 构造 FIM prompt
            fim_prompt = f"<|fim_prefix|>{prefix}<|fim_suffix|>{suffix}<|fim_middle|>"

            import httpx
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "deepseek-chat",
                        "prompt": fim_prompt,
                        "suffix": suffix,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "top_p": 0.95,
                    },
                )

                if resp.status_code != 200:
                    logger.warning("FIM API 返回 %s: %s", resp.status_code, resp.text[:200])
                    return []

                data = resp.json()
                candidates = []
                if "choices" in data:
                    for choice in data["choices"]:
                        text = choice.get("text", "").strip()
                        if text:
                            candidates.append(text)
                return candidates

        except ImportError:
            logger.debug("httpx 未安装，跳过 FIM API")
            return []
        except Exception as exc:
            logger.warning("FIM API 调用失败: %s", exc)
            return []

    async def _try_chat_fim(
        self, prefix: str, suffix: str, language: str,
        n: int, max_tokens: int, temperature: float,
    ) -> list[str]:
        """通过聊天接口实现 FIM 补全 (通用回退)"""
        try:
            from pycoder.server.chat_bridge import ChatBridge

            prompt = FIM_CHAT_PROMPT.format(
                language=language,
                prefix=prefix,
                suffix=suffix,
            )

            bridge = ChatBridge()
            bridge.configure(
                model="deepseek-chat",
                temperature=temperature,
                max_tokens=max_tokens,
            )

            response = await bridge.chat(prompt, max_tokens=max_tokens)
            extracted = self._extract_code(response)
            return [extracted] if extracted else []

        except Exception as exc:
            logger.warning("Chat FIM 回退失败: %s", exc)
            return []

    def _extract_code(self, response: str) -> str:
        """从 LLM 回复中提取代码"""
        match = re.search(r"```(?:\w+)?\s*\n(.*?)```", response, re.DOTALL)
        if match:
            return match.group(1).strip()
        return response.strip()

    def _trim_completion(self, completion: str, prefix: str, suffix: str) -> str:
        """修剪补全结果"""
        # 去掉开头空格
        cleaned = completion.lstrip()

        # 如果补全结果包含 suffix 的开头，截断
        if suffix.strip():
            suffix_start = suffix.strip()[:20]
            pos = cleaned.find(suffix_start)
            if pos > 0:
                cleaned = cleaned[:pos]

        return cleaned.strip()

    def _deduplicate(self, candidates: list[str]) -> list[str]:
        """去重"""
        seen: set[str] = set()
        result = []
        for c in candidates:
            sig = hashlib.md5(c.encode()).hexdigest()[:16]
            if sig not in seen:
                seen.add(sig)
                result.append(c)
        return result

    def _make_cache_key(self, prefix: str, suffix: str, language: str, n: int) -> str:
        """生成缓存 key"""
        raw = f"{prefix}|{suffix}|{language}|{n}"
        return hashlib.md5(raw.encode()).hexdigest()

    async def inline_complete(self, code: str, cursor_line: int, cursor_col: int) -> str:
        """基于光标位置的弹内补全

        自动分割光标前的代码(prefix)和光标后的代码(suffix)。
        """
        lines = code.splitlines()

        if cursor_line <= 0 or cursor_line > len(lines):
            return ""

        if cursor_line == 1:
            prefix = code[:cursor_col]
            suffix = code[cursor_col:]
        else:
            before_lines = lines[:cursor_line - 1]
            current_line = lines[cursor_line - 1]
            prefix = "\n".join(before_lines + [current_line[:cursor_col]])
            after_lines = lines[cursor_line:]
            suffix = (
                current_line[cursor_col:]
                + ("\n" if after_lines else "")
                + "\n".join(after_lines)
            )

        return await self.complete_single(prefix=prefix, suffix=suffix)


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_completer: FIMCodeCompleter | None = None


def get_completer() -> FIMCodeCompleter:
    """获取补全器单例"""
    global _completer
    if _completer is None:
        _completer = FIMCodeCompleter()
    return _completer
