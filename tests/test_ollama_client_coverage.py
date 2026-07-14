"""ollama_client.py 模块单元测试 — 覆盖率目标 ≥80%

覆盖内容:
  - LocalModel dataclass / to_dict
  - OllamaClient: 检测/模型列表/拉取/删除/聊天/FIM/帮助
  - NetworkSwitch: 在线/离线切换 / 最佳模型选择 / 在线检测
  - 全局单例: get_ollama_client / get_network_switch

测试策略:
  - 自定义 MockAsyncClient 替换 httpx.AsyncClient (含 stream 上下文管理器)
  - monkeypatch urllib.request.urlopen (同步检测)
  - monkeypatch httpx.AsyncClient (在线 API 检测)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from pycoder.providers import ollama_client as oc


# ══════════════════════════════════════════════════════════
# Mock 辅助
# ══════════════════════════════════════════════════════════

class MockResponse:
    """模拟 httpx 响应"""

    def __init__(self, status_code=200, json_data=None, text="", lines=None, content=b""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text
        self._lines = lines or []
        self._content = content

    def json(self):
        return self._json

    async def aread(self):
        return self._content

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class MockStreamCM:
    """模拟 client.stream(...) 异步上下文管理器"""

    def __init__(self, response=None, raise_on_enter=None):
        self._response = response
        self._raise = raise_on_enter

    async def __aenter__(self):
        if self._raise is not None:
            raise self._raise
        return self._response

    async def __aexit__(self, *args):
        return False


class MockAsyncClient:
    """模拟 httpx.AsyncClient"""

    def __init__(self, get_resp=None, post_resp=None, delete_resp=None,
                 stream_resp=None, stream_exc=None):
        self._get = get_resp
        self._post = post_resp
        self._delete = delete_resp
        self._stream = stream_resp
        self._stream_exc = stream_exc
        self.closed = False

    async def get(self, url, **kwargs):
        if isinstance(self._get, Exception):
            raise self._get
        if callable(self._get):
            return self._get(url, **kwargs)
        return self._get

    async def post(self, url, **kwargs):
        if isinstance(self._post, Exception):
            raise self._post
        return self._post

    async def delete(self, url, **kwargs):
        if isinstance(self._delete, Exception):
            raise self._delete
        return self._delete

    def stream(self, method, url, **kwargs):
        return MockStreamCM(self._stream, self._stream_exc)

    async def aclose(self):
        self.closed = True


def make_client_with_mock(tracker_mock=None, **kwargs):
    """创建 OllamaClient 并注入 mock httpx client"""
    client = oc.OllamaClient()
    client._client = MockAsyncClient(**kwargs)
    return client


# ══════════════════════════════════════════════════════════
# LocalModel
# ══════════════════════════════════════════════════════════

def test_local_model_defaults():
    m = oc.LocalModel(name="test", display_name="Test")
    assert m.size == ""
    assert m.context_window == 4096
    assert m.installed is False
    assert m.running is False


def test_local_model_to_dict():
    m = oc.LocalModel(name="qwen:7b", display_name="Qwen", size="4GB",
                      context_window=32768, installed=True, running=True)
    d = m.to_dict()
    assert d["name"] == "qwen:7b"
    assert d["display_name"] == "Qwen"
    assert d["size"] == "4GB"
    assert d["context_window"] == 32768
    assert d["installed"] is True
    assert d["running"] is True


def test_recommended_models_list():
    """RECOMMENDED_LOCAL_MODELS 非空且结构正确"""
    assert len(oc.RECOMMENDED_LOCAL_MODELS) >= 5
    for m in oc.RECOMMENDED_LOCAL_MODELS:
        assert "name" in m and "display_name" in m


# ══════════════════════════════════════════════════════════
# OllamaClient.__init__
# ══════════════════════════════════════════════════════════

def test_ollama_client_default_url():
    c = oc.OllamaClient()
    assert c.base_url == "http://localhost:11434"
    assert c._available is None


def test_ollama_client_custom_url_strips_trailing_slash():
    c = oc.OllamaClient("http://localhost:11434/")
    assert c.base_url == "http://localhost:11434"


def test_ollama_client_custom_url_no_slash():
    c = oc.OllamaClient("http://host:8080")
    assert c.base_url == "http://host:8080"


# ══════════════════════════════════════════════════════════
# check_availability
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_check_availability_cached():
    c = oc.OllamaClient()
    c._available = True
    # 不应调用 _get_client
    c._client = None
    assert await c.check_availability() is True


@pytest.mark.asyncio
async def test_check_availability_success():
    resp = MockResponse(status_code=200, json_data={"models": []})
    c = oc.OllamaClient()
    c._client = MockAsyncClient(get_resp=resp)
    assert await c.check_availability() is True
    assert c._available is True


@pytest.mark.asyncio
async def test_check_availability_non_200():
    resp = MockResponse(status_code=500)
    c = oc.OllamaClient()
    c._client = MockAsyncClient(get_resp=resp)
    assert await c.check_availability() is False


@pytest.mark.asyncio
async def test_check_availability_http_error():
    c = oc.OllamaClient()
    c._client = MockAsyncClient(get_resp=httpx.HTTPError("conn refused"))
    assert await c.check_availability() is False
    assert c._available is False


@pytest.mark.asyncio
async def test_check_availability_os_error():
    c = oc.OllamaClient()
    c._client = MockAsyncClient(get_resp=OSError("nope"))
    assert await c.check_availability() is False


# ══════════════════════════════════════════════════════════
# check_availability_sync
# ══════════════════════════════════════════════════════════

def test_check_availability_sync_success(monkeypatch):
    c = oc.OllamaClient()
    fake_resp = MagicMock()
    fake_resp.status = 200
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)

    def fake_urlopen(req, timeout):
        return fake_resp

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert c.check_availability_sync() is True


def test_check_availability_sync_failure(monkeypatch):
    c = oc.OllamaClient()

    def fake_urlopen(req, timeout):
        raise OSError("refused")

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert c.check_availability_sync() is False


def test_check_availability_sync_timeout(monkeypatch):
    c = oc.OllamaClient()

    def fake_urlopen(req, timeout):
        raise TimeoutError("slow")

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert c.check_availability_sync() is False


# ══════════════════════════════════════════════════════════
# list_models
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_list_models_unavailable():
    c = oc.OllamaClient()
    c._available = False
    models = await c.list_models()
    assert models == []


@pytest.mark.asyncio
async def test_list_models_success():
    data = {
        "models": [
            {"name": "qwen3-coder:14b", "size": 8500000000},
            {"name": "llama3.1:8b", "size": 4500000000},
        ],
    }
    resp = MockResponse(status_code=200, json_data=data)
    c = oc.OllamaClient()
    c._available = True  # 跳过 check_availability
    c._client = MockAsyncClient(get_resp=resp)
    models = await c.list_models()
    assert len(models) == 2
    assert models[0].name == "qwen3-coder:14b"
    assert models[0].display_name == "qwen3-coder"
    assert models[0].installed is True
    assert models[0].running is True
    assert c._models_cache == models


@pytest.mark.asyncio
async def test_list_models_returns_cache_on_error():
    c = oc.OllamaClient()
    c._available = True
    cached = [oc.LocalModel(name="cached", display_name="Cached")]
    c._models_cache = cached
    c._client = MockAsyncClient(get_resp=httpx.HTTPError("boom"))
    models = await c.list_models()
    assert models == cached


@pytest.mark.asyncio
async def test_list_models_json_decode_error():
    resp = MockResponse(status_code=200)
    resp.json = lambda: (_ for _ in ()).throw(json.JSONDecodeError("bad", "doc", 0))
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(get_resp=resp)
    models = await c.list_models()
    assert models == []


@pytest.mark.asyncio
async def test_list_models_empty_response():
    resp = MockResponse(status_code=200, json_data={})
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(get_resp=resp)
    models = await c.list_models()
    assert models == []


def test_list_recommended():
    c = oc.OllamaClient()
    recs = c.list_recommended()
    assert recs is oc.RECOMMENDED_LOCAL_MODELS


# ══════════════════════════════════════════════════════════
# pull_model
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_pull_model_unavailable():
    c = oc.OllamaClient()
    c._available = False
    results = []
    async for r in c.pull_model("qwen:7b"):
        results.append(r)
    assert len(results) == 1
    assert results[0]["status"] == "error"


@pytest.mark.asyncio
async def test_pull_model_success():
    lines = [
        json.dumps({"status": "downloading", "completed": 100, "total": 200}),
        json.dumps({"status": "success"}),
    ]
    resp = MockResponse(lines=lines)
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(stream_resp=resp)
    results = []
    async for r in c.pull_model("qwen:7b"):
        results.append(r)
        if r.get("status") == "success":
            break
    assert any(r.get("status") == "downloading" for r in results)


@pytest.mark.asyncio
async def test_pull_model_invalid_line_skipped():
    lines = ["not json", json.dumps({"status": "success"})]
    resp = MockResponse(lines=lines)
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(stream_resp=resp)
    results = []
    async for r in c.pull_model("qwen:7b"):
        results.append(r)
        if r.get("status") == "success":
            break
    # 只 yield 有效 JSON 行
    assert all(r.get("status") for r in results)


@pytest.mark.asyncio
async def test_pull_model_blank_lines_skipped():
    lines = ["", "  ", json.dumps({"status": "success"})]
    resp = MockResponse(lines=lines)
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(stream_resp=resp)
    results = []
    async for r in c.pull_model("qwen:7b"):
        results.append(r)
        if r.get("status") == "success":
            break
    assert len(results) == 1


@pytest.mark.asyncio
async def test_pull_model_stream_error():
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(stream_exc=RuntimeError("stream broke"))
    results = []
    async for r in c.pull_model("qwen:7b"):
        results.append(r)
    assert len(results) == 1
    assert results[0]["status"] == "error"


# ══════════════════════════════════════════════════════════
# delete_model
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_delete_model_unavailable():
    c = oc.OllamaClient()
    c._available = False
    assert await c.delete_model("qwen:7b") is False


@pytest.mark.asyncio
async def test_delete_model_success():
    resp = MockResponse(status_code=200)
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(delete_resp=resp)
    assert await c.delete_model("qwen:7b") is True


@pytest.mark.asyncio
async def test_delete_model_non_200():
    resp = MockResponse(status_code=404)
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(delete_resp=resp)
    assert await c.delete_model("qwen:7b") is False


@pytest.mark.asyncio
async def test_delete_model_http_error():
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(delete_resp=httpx.HTTPError("boom"))
    assert await c.delete_model("qwen:7b") is False


# ══════════════════════════════════════════════════════════
# chat_stream
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_chat_stream_unavailable():
    c = oc.OllamaClient()
    c._available = False
    results = []
    async for r in c.chat_stream("qwen:7b", "hi"):
        results.append(r)
    assert results[0]["type"] == "error"


@pytest.mark.asyncio
async def test_chat_stream_success():
    lines = [
        json.dumps({"message": {"content": "Hello"}, "done": False}),
        json.dumps({"message": {"content": " world"}, "done": True,
                    "prompt_eval_count": 10, "eval_count": 5}),
    ]
    resp = MockResponse(status_code=200, lines=lines)
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(stream_resp=resp)
    results = []
    async for r in c.chat_stream("qwen:7b", "hi", system_prompt="you are helpful"):
        results.append(r)
    types = [r["type"] for r in results]
    assert "token" in types
    assert "done" in types
    done = [r for r in results if r["type"] == "done"][0]
    assert done["content"] == "Hello world"
    assert done["usage"]["prompt_tokens"] == 10
    assert done["usage"]["completion_tokens"] == 5


@pytest.mark.asyncio
async def test_chat_stream_no_system_prompt():
    lines = [json.dumps({"message": {"content": "ok"}, "done": True})]
    resp = MockResponse(status_code=200, lines=lines)
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(stream_resp=resp)
    results = []
    async for r in c.chat_stream("qwen:7b", "hi"):
        results.append(r)
    assert any(r["type"] == "done" for r in results)


@pytest.mark.asyncio
async def test_chat_stream_http_error_status():
    resp = MockResponse(status_code=500, content=b"server error")
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(stream_resp=resp)
    results = []
    async for r in c.chat_stream("qwen:7b", "hi"):
        results.append(r)
    assert results[0]["type"] == "error"
    assert "HTTP 500" in results[0]["content"]


@pytest.mark.asyncio
async def test_chat_stream_connect_error():
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(stream_exc=httpx.ConnectError("no conn"))
    results = []
    async for r in c.chat_stream("qwen:7b", "hi"):
        results.append(r)
    assert results[0]["type"] == "error"
    assert "无法连接" in results[0]["content"]


@pytest.mark.asyncio
async def test_chat_stream_timeout():
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(stream_exc=httpx.TimeoutException("slow"))
    results = []
    async for r in c.chat_stream("qwen:7b", "hi"):
        results.append(r)
    assert results[0]["type"] == "error"
    assert "超时" in results[0]["content"]


@pytest.mark.asyncio
async def test_chat_stream_generic_exception():
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(stream_exc=RuntimeError("boom"))
    results = []
    async for r in c.chat_stream("qwen:7b", "hi"):
        results.append(r)
    assert results[0]["type"] == "error"
    assert "boom" in results[0]["content"]


@pytest.mark.asyncio
async def test_chat_stream_invalid_json_line_skipped():
    lines = ["not json", json.dumps({"message": {"content": "ok"}, "done": True})]
    resp = MockResponse(status_code=200, lines=lines)
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(stream_resp=resp)
    results = []
    async for r in c.chat_stream("qwen:7b", "hi"):
        results.append(r)
    assert any(r["type"] == "done" for r in results)


@pytest.mark.asyncio
async def test_chat_stream_blank_line_skipped():
    lines = ["", "  ", json.dumps({"message": {"content": "ok"}, "done": True})]
    resp = MockResponse(status_code=200, lines=lines)
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(stream_resp=resp)
    results = []
    async for r in c.chat_stream("qwen:7b", "hi"):
        results.append(r)
    assert any(r["type"] == "token" for r in results)


@pytest.mark.asyncio
async def test_chat_stream_empty_content_not_yielded():
    """message.content 为空时不 yield token"""
    lines = [
        json.dumps({"message": {"content": ""}, "done": False}),
        json.dumps({"message": {"content": "real"}, "done": True}),
    ]
    resp = MockResponse(status_code=200, lines=lines)
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(stream_resp=resp)
    results = []
    async for r in c.chat_stream("qwen:7b", "hi"):
        results.append(r)
    tokens = [r for r in results if r["type"] == "token"]
    assert len(tokens) == 1
    assert tokens[0]["content"] == "real"


# ══════════════════════════════════════════════════════════
# chat (非流式)
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_chat_success():
    lines = [
        json.dumps({"message": {"content": "Hello"}, "done": False}),
        json.dumps({"message": {"content": "!"}, "done": True}),
    ]
    resp = MockResponse(status_code=200, lines=lines)
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(stream_resp=resp)
    result = await c.chat("qwen:7b", "hi")
    assert result["content"] == "Hello!"
    assert "total_tokens" in result["usage"]


@pytest.mark.asyncio
async def test_chat_error_event():
    resp = MockResponse(status_code=500, content=b"err")
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(stream_resp=resp)
    result = await c.chat("qwen:7b", "hi")
    assert "错误" in result["content"]
    assert result["usage"] == {}


# ══════════════════════════════════════════════════════════
# fim_complete
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_fim_complete_unavailable():
    c = oc.OllamaClient()
    c._available = False
    result = await c.fim_complete("qwen:7b", "pre", "suf")
    assert result["text"] == ""
    assert "error" in result


@pytest.mark.asyncio
async def test_fim_complete_success():
    resp = MockResponse(status_code=200, json_data={
        "response": "completed_code",
        "prompt_eval_count": 5,
        "eval_count": 3,
    })
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(post_resp=resp)
    result = await c.fim_complete("qwen:7b", "pre", "suf", language="python")
    assert result["text"] == "completed_code"
    assert result["usage"]["prompt_tokens"] == 5
    assert result["usage"]["completion_tokens"] == 3


@pytest.mark.asyncio
async def test_fim_complete_no_response_field():
    resp = MockResponse(status_code=200, json_data={})
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(post_resp=resp)
    result = await c.fim_complete("qwen:7b", "pre", "suf")
    assert result["text"] == ""


@pytest.mark.asyncio
async def test_fim_complete_exception():
    c = oc.OllamaClient()
    c._available = True
    c._client = MockAsyncClient(post_resp=httpx.HTTPError("boom"))
    result = await c.fim_complete("qwen:7b", "pre", "suf")
    assert result["text"] == ""
    assert "boom" in result["error"]


# ══════════════════════════════════════════════════════════
# _get_client / close / install_instructions
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_client_creates_new():
    c = oc.OllamaClient()
    assert c._client is None
    client = await c._get_client()
    assert client is not None
    # 复用
    client2 = await c._get_client()
    assert client is client2
    await c.close()


@pytest.mark.asyncio
async def test_close_with_client():
    c = oc.OllamaClient()
    await c._get_client()
    assert c._client is not None
    await c.close()
    assert c._client is None


@pytest.mark.asyncio
async def test_close_without_client():
    c = oc.OllamaClient()
    await c.close()  # 不应抛异常
    assert c._client is None


def test_get_install_instructions():
    c = oc.OllamaClient()
    text = c.get_install_instructions()
    assert "Ollama" in text
    assert "ollama.com" in text


# ══════════════════════════════════════════════════════════
# NetworkSwitch
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_network_switch_stays_online(monkeypatch):
    """在线可用且当前已在线"""
    ns = oc.NetworkSwitch()
    monkeypatch.setattr(ns, "_check_online_api", _async_true)
    ns.ollama._available = True
    result = await ns.check_and_switch()
    assert result["mode"] == "online"


@pytest.mark.asyncio
async def test_network_switch_restore_online(monkeypatch):
    """离线后恢复在线"""
    ns = oc.NetworkSwitch()
    ns.mode = "offline"
    ns.original_model = "deepseek-chat"
    monkeypatch.setattr(ns, "_check_online_api", _async_true)
    ns.ollama._available = False
    result = await ns.check_and_switch()
    assert result["mode"] == "online"
    assert "已恢复" in result["message"]


@pytest.mark.asyncio
async def test_network_switch_to_offline(monkeypatch):
    """在线不可用，切换到本地"""
    ns = oc.NetworkSwitch()
    ns.mode = "online"
    ns.original_model = "deepseek-chat"

    async def fake_check_online():
        return False

    monkeypatch.setattr(ns, "_check_online_api", fake_check_online)
    ns.ollama._available = True

    fake_models = [oc.LocalModel(name="qwen3-coder:14b", display_name="Qwen")]
    monkeypatch.setattr(ns.ollama, "list_models", _async_return(fake_models))

    bridge = MagicMock()
    bridge.config.model = "deepseek-chat"
    ns.bridge = bridge

    result = await ns.check_and_switch()
    assert result["mode"] == "offline"
    assert "qwen3-coder" in result["model"]
    assert ns.mode == "offline"
    assert ns.original_model == "deepseek-chat"


@pytest.mark.asyncio
async def test_network_switch_no_local_models(monkeypatch):
    """在线不可用，本地无模型"""
    ns = oc.NetworkSwitch()
    monkeypatch.setattr(ns, "_check_online_api", _async_false)
    ns.ollama._available = True
    monkeypatch.setattr(ns.ollama, "list_models", _async_return([]))
    result = await ns.check_and_switch()
    assert result["mode"] == "offline"
    assert result["model"] == ""
    assert "无可用模型" in result["message"]


@pytest.mark.asyncio
async def test_network_switch_local_unavailable(monkeypatch):
    """在线不可用且本地服务不可用"""
    ns = oc.NetworkSwitch()
    monkeypatch.setattr(ns, "_check_online_api", _async_false)
    ns.ollama._available = False
    result = await ns.check_and_switch()
    assert result["mode"] == "offline"
    assert "无可用模型" in result["message"]


def test_pick_best_local_model_priority():
    ns = oc.NetworkSwitch()
    models = [
        oc.LocalModel(name="llama3.1:8b", display_name="Llama"),
        oc.LocalModel(name="qwen3-coder:14b", display_name="Qwen"),
    ]
    best = ns._pick_best_local_model(models)
    assert best.name == "qwen3-coder:14b"


def test_pick_best_local_model_fallback_first():
    ns = oc.NetworkSwitch()
    models = [oc.LocalModel(name="unknown-model", display_name="Unknown")]
    best = ns._pick_best_local_model(models)
    assert best.name == "unknown-model"


def test_pick_best_local_model_empty():
    ns = oc.NetworkSwitch()
    assert ns._pick_best_local_model([]) is None


@pytest.mark.asyncio
async def test_check_online_api_success(monkeypatch):
    ns = oc.NetworkSwitch()
    fake_client = MockAsyncClient(get_resp=MockResponse(status_code=200))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: fake_client)
    assert await ns._check_online_api() is True


@pytest.mark.asyncio
async def test_check_online_api_http_error(monkeypatch):
    ns = oc.NetworkSwitch()

    class FailingClient:
        async def get(self, url, **kwargs):
            raise httpx.HTTPError("nope")

        async def aclose(self):
            pass

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FailingClient())
    assert await ns._check_online_api() is False


@pytest.mark.asyncio
async def test_check_online_api_os_error(monkeypatch):
    ns = oc.NetworkSwitch()

    class FailingClient:
        async def get(self, url, **kwargs):
            raise OSError("nope")

        async def aclose(self):
            pass

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FailingClient())
    assert await ns._check_online_api() is False


# ══════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════

def test_get_ollama_client_singleton():
    oc._ollama_client = None
    c1 = oc.get_ollama_client()
    c2 = oc.get_ollama_client()
    assert c1 is c2


def test_get_network_switch_singleton():
    oc._network_switch = None
    ns1 = oc.get_network_switch()
    ns2 = oc.get_network_switch()
    assert ns1 is ns2


def test_get_network_switch_with_bridge():
    oc._network_switch = None
    bridge = MagicMock()
    ns = oc.get_network_switch(bridge=bridge)
    assert ns.bridge is bridge


# ── 异步辅助函数 ──

async def _async_true() -> bool:
    return True


async def _async_false() -> bool:
    return False


def _async_return(value: Any):
    async def _fn():
        return value
    return _fn
