"""覆盖率测试: pycoder/net/client.py

目标: 行覆盖率 >= 95%

覆盖内容:
  - HTTPClient: __init__ / __aenter__ / __aexit__ / aclose
    request (成功/失败/重试/raise_for_status) / get / post / delete
    stream / get_json
  - create_httpx_client / create_async_httpx_client

测试策略:
  - 使用 httpx.MockTransport 模拟 HTTP 响应
  - 通过 monkeypatch 在 httpx.AsyncClient 创建时注入 transport
  - 测试各 retry 分支: 成功一次/失败重试/全部失败抛异常
"""
from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from pycoder.net import client as client_mod
from pycoder.net.client import (
    HTTPClient,
    create_async_httpx_client,
    create_httpx_client,
)


# ── 辅助: 用 MockTransport 替换 httpx.AsyncClient ─────────

def _patch_async_client_with_transport(monkeypatch, transport):
    """让 httpx.AsyncClient 自动使用给定的 transport"""
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)


def _make_transport(handler):
    """创建 MockTransport"""
    return httpx.MockTransport(handler)


# ══════════════════════════════════════════════════════════
# HTTPClient: 构造 / 上下文管理
# ══════════════════════════════════════════════════════════

class TestHTTPClientInit:
    def test_defaults(self):
        c = HTTPClient()
        assert c._base_url is None
        assert c._timeout == 10.0
        assert c._max_retries == 2
        assert c._headers == {}
        assert c._client is None

    def test_with_params(self):
        c = HTTPClient(
            base_url="http://example.com",
            timeout=30.0,
            max_retries=5,
            headers={"X-Custom": "v"},
        )
        assert c._base_url == "http://example.com"
        assert c._timeout == 30.0
        assert c._max_retries == 5
        assert c._headers == {"X-Custom": "v"}

    async def test_aenter_creates_client(self, monkeypatch):
        transport = _make_transport(lambda req: httpx.Response(200, text="ok"))
        _patch_async_client_with_transport(monkeypatch, transport)

        c = HTTPClient(base_url="http://test")
        result = await c.__aenter__()
        assert result is c
        assert c._client is not None
        await c.aclose()

    async def test_aenter_no_base_url(self, monkeypatch):
        """无 base_url → 不传 base_url 给 AsyncClient"""
        captured_kwargs = {}
        transport = _make_transport(lambda req: httpx.Response(200))
        original = httpx.AsyncClient

        def patched(*args, **kwargs):
            captured_kwargs.update(kwargs)
            kwargs["transport"] = transport
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", patched)

        c = HTTPClient()
        await c.__aenter__()
        assert "base_url" not in captured_kwargs
        assert captured_kwargs["trust_env"] is False
        assert captured_kwargs["timeout"] == 10.0
        await c.aclose()

    async def test_aexit_closes_client(self, monkeypatch):
        transport = _make_transport(lambda req: httpx.Response(200))
        _patch_async_client_with_transport(monkeypatch, transport)

        c = HTTPClient()
        await c.__aenter__()
        assert c._client is not None
        await c.__aexit__(None, None, None)
        assert c._client is None

    async def test_aclose_no_client(self):
        """aclose 时 _client 为 None → 不抛异常"""
        c = HTTPClient()
        # _client 仍为 None
        await c.aclose()
        assert c._client is None


# ══════════════════════════════════════════════════════════
# HTTPClient: request
# ══════════════════════════════════════════════════════════

class TestRequest:
    async def test_success_no_raise(self, monkeypatch):
        """成功响应 + 不 raise_for_status → 直接返回"""
        transport = _make_transport(lambda req: httpx.Response(200, json={"ok": True}))
        _patch_async_client_with_transport(monkeypatch, transport)

        async with HTTPClient() as c:
            resp = await c.request("GET", "http://test/x")
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}

    async def test_success_with_raise_for_status(self, monkeypatch):
        """成功响应 + raise_for_status=True → 不抛异常"""
        transport = _make_transport(lambda req: httpx.Response(200, text="ok"))
        _patch_async_client_with_transport(monkeypatch, transport)

        async with HTTPClient() as c:
            resp = await c.request("GET", "http://test/x", raise_for_status=True)
            assert resp.status_code == 200

    async def test_raise_for_status_4xx_raises(self, monkeypatch):
        """4xx 响应 + raise_for_status=True → 抛 HTTPStatusError"""
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="not found")
        transport = _make_transport(handler)
        _patch_async_client_with_transport(monkeypatch, transport)

        async with HTTPClient(max_retries=0) as c:
            with pytest.raises(httpx.HTTPStatusError):
                await c.request("GET", "http://test/x", raise_for_status=True)

    async def test_request_without_context_assertion(self):
        """未进入上下文就调用 request → 抛 AssertionError"""
        c = HTTPClient()
        with pytest.raises(AssertionError):
            await c.request("GET", "http://test/x")

    async def test_retry_succeeds_after_failure(self, monkeypatch):
        """第一次失败 + 第二次成功 → 返回成功响应"""
        call_count = [0]
        def handler(req: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            if call_count[0] == 1:
                raise httpx.ConnectError("conn failed")
            return httpx.Response(200, text="ok")
        transport = _make_transport(handler)
        _patch_async_client_with_transport(monkeypatch, transport)

        # mock anyio.sleep 避免真实等待
        import anyio
        async def fake_sleep(seconds):
            return
        monkeypatch.setattr(anyio, "sleep", fake_sleep)

        async with HTTPClient(max_retries=2) as c:
            resp = await c.request("GET", "http://test/x")
            assert resp.status_code == 200
            assert call_count[0] == 2

    async def test_retry_exhausted_raises(self, monkeypatch):
        """所有重试都失败 → 抛最后一个异常"""
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("conn failed")
        transport = _make_transport(handler)
        _patch_async_client_with_transport(monkeypatch, transport)

        import anyio
        async def fake_sleep(seconds):
            return
        monkeypatch.setattr(anyio, "sleep", fake_sleep)

        async with HTTPClient(max_retries=2) as c:
            with pytest.raises(httpx.ConnectError):
                await c.request("GET", "http://test/x")

    async def test_transport_error_retried(self, monkeypatch):
        """TransportError 也触发重试"""
        call_count = [0]
        def handler(req: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            if call_count[0] == 1:
                raise httpx.TransportError("network err")
            return httpx.Response(200)
        transport = _make_transport(handler)
        _patch_async_client_with_transport(monkeypatch, transport)

        import anyio
        async def fake_sleep(seconds):
            return
        monkeypatch.setattr(anyio, "sleep", fake_sleep)

        async with HTTPClient(max_retries=1) as c:
            resp = await c.request("GET", "http://test/x")
            assert resp.status_code == 200

    async def test_zero_retries(self, monkeypatch):
        """max_retries=0 → 只调用一次，失败立即抛"""
        call_count = [0]
        def handler(req: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            raise httpx.ConnectError("conn failed")
        transport = _make_transport(handler)
        _patch_async_client_with_transport(monkeypatch, transport)

        async with HTTPClient(max_retries=0) as c:
            with pytest.raises(httpx.ConnectError):
                await c.request("GET", "http://test/x")
            assert call_count[0] == 1

    async def test_kwargs_passed_to_request(self, monkeypatch):
        """额外的 kwargs 应传给 httpx"""
        captured = {}
        def handler(req: httpx.Request) -> httpx.Response:
            captured["url"] = str(req.url)
            captured["method"] = req.method
            captured["headers"] = dict(req.headers)
            return httpx.Response(200)
        transport = _make_transport(handler)
        _patch_async_client_with_transport(monkeypatch, transport)

        async with HTTPClient() as c:
            await c.request(
                "POST", "http://test/x",
                json={"key": "val"},
                headers={"X-Test": "1"},
            )
            assert captured["method"] == "POST"

    async def test_unreachable_fallback_with_negative_retries(self, monkeypatch):
        """max_retries=-1 → for 循环不执行 → 抛 RuntimeError 防御性兜底

        源码末尾 ``raise RuntimeError("HTTP request failed after retries")`` 是
        防御性兜底，正常 max_retries>=0 不会触达（循环内必返回或 raise）。
        仅当 max_retries 为负数使 range(1, max_retries+2) 为空时才会执行。
        """
        transport = _make_transport(lambda req: httpx.Response(200))
        _patch_async_client_with_transport(monkeypatch, transport)

        async with HTTPClient(max_retries=-1) as c:
            with pytest.raises(RuntimeError, match="HTTP request failed after retries"):
                await c.request("GET", "http://test/x")


# ══════════════════════════════════════════════════════════
# HTTPClient: get / post / delete
# ══════════════════════════════════════════════════════════

class TestVerbMethods:
    async def test_get(self, monkeypatch):
        captured = {}
        def handler(req: httpx.Request) -> httpx.Response:
            captured["method"] = req.method
            return httpx.Response(200, json={"data": "ok"})
        transport = _make_transport(handler)
        _patch_async_client_with_transport(monkeypatch, transport)

        async with HTTPClient() as c:
            resp = await c.get("http://test/x")
            assert resp.status_code == 200
            assert captured["method"] == "GET"

    async def test_post(self, monkeypatch):
        captured = {}
        def handler(req: httpx.Request) -> httpx.Response:
            captured["method"] = req.method
            return httpx.Response(201)
        transport = _make_transport(handler)
        _patch_async_client_with_transport(monkeypatch, transport)

        async with HTTPClient() as c:
            resp = await c.post("http://test/x", json={"k": "v"})
            assert resp.status_code == 201
            assert captured["method"] == "POST"

    async def test_delete(self, monkeypatch):
        captured = {}
        def handler(req: httpx.Request) -> httpx.Response:
            captured["method"] = req.method
            return httpx.Response(204)
        transport = _make_transport(handler)
        _patch_async_client_with_transport(monkeypatch, transport)

        async with HTTPClient() as c:
            resp = await c.delete("http://test/x")
            assert resp.status_code == 204
            assert captured["method"] == "DELETE"


# ══════════════════════════════════════════════════════════
# HTTPClient: stream / get_json
# ══════════════════════════════════════════════════════════

class TestStreamAndGetJson:
    async def test_stream_returns_response(self, monkeypatch):
        transport = _make_transport(lambda req: httpx.Response(200, text="streamed"))
        _patch_async_client_with_transport(monkeypatch, transport)

        async with HTTPClient() as c:
            # stream 是同步方法 — 返回 _AsyncGeneratorContextManager
            stream_cm = c.stream("GET", "http://test/x")
            # 进入 stream 上下文
            async with stream_cm as resp:
                assert resp.status_code == 200

    def test_stream_without_context_asserts(self):
        """未进入上下文调用 stream → AssertionError"""
        c = HTTPClient()
        with pytest.raises(AssertionError):
            c.stream("GET", "http://test/x")

    async def test_get_json_success(self, monkeypatch):
        transport = _make_transport(
            lambda req: httpx.Response(200, json={"key": "value"})
        )
        _patch_async_client_with_transport(monkeypatch, transport)

        async with HTTPClient() as c:
            data = await c.get_json("http://test/x")
            assert data == {"key": "value"}

    async def test_get_json_failure_raises(self, monkeypatch):
        """4xx 响应 → raise_for_status 抛异常"""
        transport = _make_transport(lambda req: httpx.Response(500))
        _patch_async_client_with_transport(monkeypatch, transport)

        async with HTTPClient(max_retries=0) as c:
            with pytest.raises(httpx.HTTPStatusError):
                await c.get_json("http://test/x")


# ══════════════════════════════════════════════════════════
# 工厂函数
# ══════════════════════════════════════════════════════════

class TestFactoryFunctions:
    def test_create_httpx_client_defaults(self):
        c = create_httpx_client()
        assert isinstance(c, httpx.Client)
        # trust_env=False 是默认设置
        assert c._transport is not None
        c.close()

    def test_create_httpx_client_with_params(self):
        c = create_httpx_client(
            timeout=20.0,
            headers={"X-A": "1"},
            verify=False,
            follow_redirects=True,
        )
        assert isinstance(c, httpx.Client)
        c.close()

    async def test_create_async_httpx_client_defaults(self):
        c = create_async_httpx_client()
        assert isinstance(c, httpx.AsyncClient)
        await c.aclose()

    async def test_create_async_httpx_client_with_params(self):
        c = create_async_httpx_client(
            timeout=30.0,
            headers={"X-B": "2"},
            verify=False,
            follow_redirects=True,
        )
        assert isinstance(c, httpx.AsyncClient)
        await c.aclose()

    async def test_create_async_httpx_client_can_aclose(self):
        c = create_async_httpx_client()
        await c.aclose()


# ══════════════════════════════════════════════════════════
# 异常别名
# ══════════════════════════════════════════════════════════

class TestExceptionAliases:
    def test_exception_aliases(self):
        """模块导出的异常别名应等于 httpx 对应异常"""
        assert client_mod.ConnectError is httpx.ConnectError
        assert client_mod.TimeoutException is httpx.TimeoutException
        assert client_mod.HTTPError is httpx.HTTPError
        assert client_mod.TransportError is httpx.TransportError
