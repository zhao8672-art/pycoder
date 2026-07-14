"""
本地模型支持 — 通过 Ollama 接入本地开源模型

P2-4 功能:
- Ollama 客户端集成
- CodeGeeX4 / Qwen-Coder 本地推理
- 自动检测本地可用模型
- 网络状态自动切换（在线→离线）

离线工作流:
1. 检测是否有本地 Ollama 服务
2. 列出可用模型
3. 如果在线模型不可用，自动切换到本地模型
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


# ── Ollama 模型列表 ──────────────────────────────────────

RECOMMENDED_LOCAL_MODELS = [
    {
        "name": "qwen3-coder:14b",
        "display_name": "Qwen3-Coder 14B",
        "size": "~8.5GB",
        "context": 32768,
        "description": "阿里通义千问 Coder 版，强大的代码生成能力",
        "tags": ["coding", "chinese"],
    },
    {
        "name": "qwen3-coder:7b",
        "display_name": "Qwen3-Coder 7B",
        "size": "~4.5GB",
        "context": 32768,
        "description": "轻量版 Coder，适合低配机器",
        "tags": ["coding", "chinese", "lightweight"],
    },
    {
        "name": "codegeex4:9b",
        "display_name": "CodeGeeX4 9B",
        "size": "~5.5GB",
        "context": 128000,
        "description": "智谱 CodeGeeX4，长上下文支持",
        "tags": ["coding", "long-context"],
    },
    {
        "name": "deepseek-coder-v2:16b",
        "display_name": "DeepSeek Coder V2 16B",
        "size": "~9.5GB",
        "context": 128000,
        "description": "DeepSeek 开源 Coder 模型",
        "tags": ["coding", "fim", "long-context"],
    },
    {
        "name": "codellama:13b",
        "display_name": "CodeLlama 13B",
        "size": "~7.5GB",
        "context": 16384,
        "description": "Meta CodeLlama，经典代码模型",
        "tags": ["coding"],
    },
    {
        "name": "llama3.1:8b",
        "display_name": "Llama 3.1 8B",
        "size": "~4.5GB",
        "context": 131072,
        "description": "Meta 最新通用模型",
        "tags": ["general", "lightweight"],
    },
]


@dataclass
class LocalModel:
    """本地模型信息"""

    name: str
    display_name: str
    size: str = ""
    context_window: int = 4096
    installed: bool = False
    running: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "size": self.size,
            "context_window": self.context_window,
            "installed": self.installed,
            "running": self.running,
        }


class OllamaClient:
    """
    Ollama 客户端 — 与本地 Ollama 服务通信。

    API 兼容 OpenAI 格式: POST /api/generate 或 /api/chat

    用法:
        client = OllamaClient()

        # 检查可用模型
        models = await client.list_models()

        # 聊天
        async for event in client.chat_stream("qwen3-coder:14b", "写一个快排"):
            print(event)

        # 安装推荐模型
        await client.pull_model("qwen3-coder:14b")
    """

    DEFAULT_OLLAMA_URL = "http://localhost:11434"

    def __init__(self, base_url: str = None):
        self.base_url = (base_url or self.DEFAULT_OLLAMA_URL).rstrip("/")
        self._client: httpx.AsyncClient | None = None
        self._available: bool | None = None
        self._models_cache: list[LocalModel] = []

    # ── 服务检测 ──────────────────────────────────────────

    async def check_availability(self) -> bool:
        """检查 Ollama 服务是否可用"""
        if self._available is not None:
            return self._available

        try:
            client = await self._get_client()
            response = await client.get("/api/tags", timeout=httpx.Timeout(5.0))
            self._available = response.status_code == 200
            return self._available
        except (httpx.HTTPError, OSError, ConnectionError) as e:
            logger.debug("ollama_check_availability_failed error=%s", e)
            self._available = False
            return False

    def check_availability_sync(self) -> bool:
        """同步检查可用性"""
        try:
            import urllib.request

            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except (OSError, ConnectionError, TimeoutError) as e:
            logger.debug("ollama_check_availability_sync_failed error=%s", e)
            return False

    # ── 模型管理 ──────────────────────────────────────────

    async def list_models(self) -> list[LocalModel]:
        """列出本地已安装的模型"""
        if not await self.check_availability():
            return []

        try:
            client = await self._get_client()
            response = await client.get("/api/tags", timeout=httpx.Timeout(10.0))
            data = response.json()

            models = []
            for model_data in data.get("models", []):
                name = model_data.get("name", "")
                models.append(
                    LocalModel(
                        name=name,
                        display_name=name.split(":")[0],
                        size=model_data.get("size", ""),
                        installed=True,
                        running=True,
                    )
                )

            self._models_cache = models
            return models
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, OSError) as e:
            logger.debug("ollama_list_models_failed error=%s", e)
            return self._models_cache

    def list_recommended(self) -> list[dict]:
        """列出推荐安装的模型"""
        return RECOMMENDED_LOCAL_MODELS

    async def pull_model(self, model_name: str) -> AsyncIterator[dict]:
        """
        拉取（安装）模型。

        Yields:
            {"status": "downloading", "progress": "...", "completed": 5000000000, "total": 8000000000}
            {"status": "done", "model": "qwen3-coder:14b"}
        """
        if not await self.check_availability():
            yield {"status": "error", "error": "Ollama 服务不可用"}
            return

        try:
            client = await self._get_client()
            async with client.stream(
                "POST",
                "/api/pull",
                json={"name": model_name},
                timeout=httpx.Timeout(600.0),  # 10 分钟超时
            ) as response:
                async for line in response.aiter_lines():
                    if line.strip():
                        try:
                            data = json.loads(line)
                            yield data
                            if data.get("status") == "success":
                                break
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            yield {"status": "error", "error": str(e)}

    async def delete_model(self, model_name: str) -> bool:
        """删除本地模型"""
        if not await self.check_availability():
            return False

        try:
            client = await self._get_client()
            response = await client.delete(
                "/api/delete",
                json={"name": model_name},
                timeout=httpx.Timeout(30.0),
            )
            return response.status_code == 200
        except (httpx.HTTPError, OSError, ConnectionError) as e:
            logger.warning("ollama_delete_model_failed model=%s error=%s", model_name, e)
            return False

    # ── 聊天推理 ──────────────────────────────────────────

    async def chat_stream(
        self,
        model: str,
        message: str,
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> AsyncIterator[dict]:
        """
        流式聊天（Ollama API）。

        Yields:
            {"type": "token", "content": "..."}
            {"type": "done", "content": "..."}
            {"type": "error", "content": "..."}
        """
        if not await self.check_availability():
            yield {"type": "error", "content": "Ollama 服务不可用"}
            return

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
            },
        }

        try:
            client = await self._get_client()
            full_response = []

            async with client.stream(
                "POST",
                "/api/chat",
                json=payload,
                timeout=httpx.Timeout(120.0),
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    yield {"type": "error", "content": f"HTTP {response.status_code}: {error_text}"}
                    return

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        msg = data.get("message", {})
                        content = msg.get("content", "")

                        if content:
                            full_response.append(content)
                            yield {"type": "token", "content": content}

                        if data.get("done"):
                            yield {
                                "type": "done",
                                "content": "".join(full_response),
                                "usage": {
                                    "prompt_tokens": data.get("prompt_eval_count", 0),
                                    "completion_tokens": data.get("eval_count", 0),
                                },
                            }
                            break

                    except json.JSONDecodeError:
                        continue

        except httpx.ConnectError:
            yield {"type": "error", "content": f"无法连接到 Ollama ({self.base_url})"}
        except httpx.TimeoutException:
            yield {"type": "error", "content": "Ollama 请求超时"}
        except Exception as e:
            yield {"type": "error", "content": str(e)}

    async def chat(self, model: str, message: str, system_prompt: str = "") -> dict:
        """非流式聊天"""
        full = []
        async for event in self.chat_stream(model, message, system_prompt):
            if event["type"] == "token":
                full.append(event["content"])
            elif event["type"] == "error":
                return {"content": f"错误: {event['content']}", "usage": {}}

        return {
            "content": "".join(full),
            "usage": {"total_tokens": len("".join(full)) // 4},
        }

    # ── FIM 补全 (Fill-in-the-Middle) ─────────────────────

    async def fim_complete(
        self, model: str, prefix: str, suffix: str, language: str = "python"
    ) -> dict:
        """
        FIM (Fill-in-the-Middle) 代码补全。

        仅支持支持 FIM 的模型（如 deepseek-coder-v2, qwen3-coder）。
        """
        if not await self.check_availability():
            return {"text": "", "error": "Ollama 服务不可用"}

        payload = {
            "model": model,
            "prompt": prefix,
            "suffix": suffix,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "stop": ["\n\n", "```"],
            },
        }

        try:
            client = await self._get_client()
            response = await client.post(
                "/api/generate",
                json=payload,
                timeout=httpx.Timeout(30.0),
            )
            data = response.json()
            return {
                "text": data.get("response", ""),
                "usage": {
                    "prompt_tokens": data.get("prompt_eval_count", 0),
                    "completion_tokens": data.get("eval_count", 0),
                },
            }
        except Exception as e:
            return {"text": "", "error": str(e)}

    # ── 帮助方法 ──────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(120.0, connect=5.0),
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    def get_install_instructions(self) -> str:
        """获取安装说明"""
        return """📦 Ollama 安装指南

1. 下载安装 Ollama:
   https://ollama.com/download

2. 安装推荐模型:
   ollama pull qwen3-coder:14b     # 阿里通义千问 Coder (推荐)
   ollama pull codegeex4:9b        # 智谱 CodeGeeX4
   ollama pull deepseek-coder-v2:16b  # DeepSeek Coder V2

3. 在 PyCoder 中切换:
   /model local:qwen3-coder:14b
"""


# ── 网络状态检测与自动切换 ────────────────────────────────


class NetworkSwitch:
    """
    网络状态自动切换 — 在线/离线模式。

    策略:
    1. 检测在线 API 可用性
    2. 如果不可用，自动切换到 Ollama 本地模型
    3. 恢复在线后切换回在线模型
    """

    def __init__(self, bridge=None, ollama_client: OllamaClient = None):
        self.bridge = bridge
        self.ollama = ollama_client or OllamaClient()
        self.mode: str = "online"  # online | offline
        self.original_model: str = ""
        self.fallback_local_model: str = ""

    async def check_and_switch(self) -> dict:
        """
        检查网络状态并自动切换。

        Returns:
            {"mode": "online"|"offline", "model": "...", "message": "..."}
        """
        # 检查在线 API
        online_available = await self._check_online_api()
        local_available = await self.ollama.check_availability()

        if online_available:
            if self.mode == "offline" and self.original_model:
                # 恢复在线模式
                self.mode = "online"
                return {
                    "mode": "online",
                    "model": self.original_model,
                    "message": f"🟢 在线模式已恢复 → {self.original_model}",
                }
            self.mode = "online"
            return {"mode": "online", "model": self.original_model, "message": ""}

        # 在线不可用，尝试切换到本地
        if local_available:
            local_models = await self.ollama.list_models()
            if local_models:
                local_model = self._pick_best_local_model(local_models)
                if self.mode != "offline":
                    self.mode = "offline"
                    if self.bridge:
                        self.original_model = self.bridge.config.model
                return {
                    "mode": "offline",
                    "model": local_model.name,
                    "message": f"🔵 已切换到离线模式 → {local_model.display_name}",
                }

        return {"mode": "offline", "model": "", "message": "❌ 无可用模型"}

    def _pick_best_local_model(self, models: list[LocalModel]) -> LocalModel | None:
        """从本地模型中选择最佳编码模型"""
        priority = [
            "qwen3-coder:14b",
            "qwen3-coder:7b",
            "codegeex4:9b",
            "deepseek-coder-v2:16b",
            "codellama:13b",
            "llama3.1:8b",
        ]

        for preferred in priority:
            for model in models:
                if model.name.startswith(preferred.split(":")[0]):
                    return model

        return models[0] if models else None

    async def _check_online_api(self) -> bool:
        """检查在线 API 是否可用"""
        try:
            import httpx

            client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
            await client.get("https://api.deepseek.com/v1/models")
            await client.aclose()
            # 即使返回 401 也说明服务可达
            return True
        except (httpx.HTTPError, OSError, ConnectionError, ImportError) as e:
            logger.debug("online_api_check_failed error=%s", e)
            return False


# ── 全局单例 ─────────────────────────────────────────────

_ollama_client: OllamaClient | None = None
_network_switch: NetworkSwitch | None = None


def get_ollama_client() -> OllamaClient:
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient()
    return _ollama_client


def get_network_switch(bridge=None) -> NetworkSwitch:
    global _network_switch
    if _network_switch is None:
        _network_switch = NetworkSwitch(bridge=bridge)
    return _network_switch
