from __future__ import annotations

from typing import Any

import anyio
import httpx

DEFAULT_TIMEOUT = 10.0

ConnectError = httpx.ConnectError
TimeoutException = httpx.TimeoutException
HTTPError = httpx.HTTPError
TransportError = httpx.TransportError


class HTTPClient:
    """A small wrapper around httpx.AsyncClient with sensible defaults.

    - default timeout
    - retries with backoff
    - trust_env=False to avoid unexpected proxying
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | httpx.Timeout = DEFAULT_TIMEOUT,
        max_retries: int = 2,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._max_retries = max_retries
        self._headers = headers or {}
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> HTTPClient:
        client_kwargs: dict[str, Any] = {
            "timeout": self._timeout,
            "trust_env": False,
            "headers": self._headers,
        }
        if self._base_url is not None:
            client_kwargs["base_url"] = self._base_url

        self._client = httpx.AsyncClient(**client_kwargs)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def request(
        self,
        method: str,
        url: str,
        *,
        raise_for_status: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        assert self._client is not None, "HTTPClient must be used as async context manager"

        for attempt in range(1, self._max_retries + 2):
            try:
                resp = await self._client.request(method, url, **kwargs)
                if raise_for_status:
                    resp.raise_for_status()
                return resp
            except (httpx.HTTPError, httpx.TransportError):
                if attempt > self._max_retries:
                    raise
                await anyio.sleep(0.5 * attempt)

        raise RuntimeError("HTTP request failed after retries")

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("DELETE", url, **kwargs)

    def stream(self, method: str, url: str, **kwargs: Any):
        """返回流式响应上下文管理器。

        用法::

            async with client.stream("GET", url) as response:
                async for chunk in response.aiter_bytes():
                    ...

        注意: ``httpx.AsyncClient.stream`` 返回的是 ``_AsyncGeneratorContextManager``，
        不可被 ``await``；旧实现 ``return await self._client.stream(...)`` 会抛
        ``TypeError: '_AsyncGeneratorContextManager' object can't be awaited``。
        此处直接返回上下文管理器，与 httpx 原生用法保持一致。
        """
        assert self._client is not None, "HTTPClient must be used as async context manager"
        return self._client.stream(method, url, **kwargs)

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        resp = await self.request("GET", url, raise_for_status=True, **kwargs)
        return resp.json()


def create_httpx_client(
    *,
    timeout: float | httpx.Timeout = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
    verify: bool = True,
    follow_redirects: bool = False,
) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        trust_env=False,
        headers=headers,
        verify=verify,
        follow_redirects=follow_redirects,
    )


def create_async_httpx_client(
    *,
    timeout: float | httpx.Timeout = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
    verify: bool = True,
    follow_redirects: bool = False,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout,
        trust_env=False,
        headers=headers,
        verify=verify,
        follow_redirects=follow_redirects,
    )
