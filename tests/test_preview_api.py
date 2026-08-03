"""F7 实时预览 API 测试

覆盖:
    - dev-server 端口探测（mock socket / is_port_open）
    - package.json scripts 框架与端口推断
    - 静态 HTML 入口检测
    - watcher 启动/停止/防抖合并（fake observer，不泄漏线程；另含真实 watchdog 集成）
    - proxy 反向代理转发（mock httpx）
    - 鉴权（主应用 APIKeyMiddleware：无 Key 401 / 有 Key 200）
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers import files as files_router
from pycoder.server.routers import preview_api
from pycoder.server.services import preview_manager as pm


# ── 通用工具 ──────────────────────────────────────────────
@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """将 files 路由的工作区根指向临时目录"""
    monkeypatch.setattr(files_router, "_WORKSPACE_ROOT", tmp_path)
    return tmp_path


@pytest.fixture()
def preview_app(workspace: Path) -> FastAPI:
    """仅挂载预览路由的轻量应用（避免全量 app 启动开销）"""
    app = FastAPI()
    app.include_router(preview_api.router)
    app.include_router(preview_api.ws_router)
    return app


@pytest.fixture()
def preview_client(preview_app: FastAPI) -> TestClient:
    return TestClient(preview_app)


@pytest.fixture()
def fresh_manager(monkeypatch: pytest.MonkeyPatch) -> Any:
    """独立的 PreviewManager 实例（替换单例，避免测试间串扰）"""
    manager = pm.PreviewManager(debounce_sec=0.05)
    monkeypatch.setattr(preview_api, "get_preview_manager", lambda: manager)
    yield manager
    manager.stop_watcher()


# ══════════════════════════════════════════════════════════
# 1. 端口探测（mock socket）
# ══════════════════════════════════════════════════════════
class _FakeSocket:
    """模拟 socket：按端口集合决定 connect_ex 结果"""

    open_ports: set[int] = set()

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self._timeout = 0.0

    def settimeout(self, value: float) -> None:
        self._timeout = value

    def connect_ex(self, address: tuple[str, int]) -> int:
        return 0 if address[1] in self.open_ports else 111

    def __enter__(self) -> _FakeSocket:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


def test_is_port_open_mock_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """socket 层 mock：5173 监听中，3000 未监听"""
    _FakeSocket.open_ports = {5173}
    monkeypatch.setattr(pm.socket, "socket", _FakeSocket)

    assert pm.is_port_open(5173) is True
    assert pm.is_port_open(3000) is False


def test_is_port_open_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    """socket 构造抛 OSError 时应返回 False 而非冒泡"""

    class _BoomSocket:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise OSError("network unreachable")

    monkeypatch.setattr(pm.socket, "socket", _BoomSocket)
    assert pm.is_port_open(1) is False


# ══════════════════════════════════════════════════════════
# 2. dev-server 检测（package.json + 端口）
# ══════════════════════════════════════════════════════════
def _write_pkg(ws: Path, scripts: dict[str, str]) -> None:
    import json

    (ws / "package.json").write_text(
        json.dumps({"name": "demo", "scripts": scripts}), encoding="utf-8"
    )


def test_detect_vite_running(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """package.json 含 vite dev 脚本且 5173 监听 → running vite"""
    _write_pkg(workspace, {"dev": "vite"})
    monkeypatch.setattr(pm, "is_port_open", lambda port, **_: port == 5173)

    info = pm.detect_dev_server(workspace)
    assert info.running is True
    assert info.framework == "vite"
    assert info.port == 5173
    assert info.url == "http://127.0.0.1:5173"
    assert info.mode == "dev-server"


def test_detect_explicit_port_in_script(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """scripts 中显式 --port 覆盖框架默认端口"""
    _write_pkg(workspace, {"dev": "vite --port 3001"})
    monkeypatch.setattr(pm, "is_port_open", lambda port, **_: port == 3001)

    info = pm.detect_dev_server(workspace)
    assert info.running is True
    assert info.port == 3001
    assert info.url.endswith(":3001")


def test_detect_common_port_fallback(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """期望端口未监听时扫描常见端口（如 8080）"""
    _write_pkg(workspace, {"dev": "vite"})
    monkeypatch.setattr(pm, "is_port_open", lambda port, **_: port == 8080)

    info = pm.detect_dev_server(workspace)
    assert info.running is True
    assert info.port == 8080


def test_detect_declared_but_not_running(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """有 package.json 但无端口监听 → running=False 且给出期望地址"""
    _write_pkg(workspace, {"dev": "next dev"})
    monkeypatch.setattr(pm, "is_port_open", lambda *_a, **_k: False)

    info = pm.detect_dev_server(workspace)
    assert info.running is False
    assert info.framework == "next"
    assert info.port == 3000
    assert info.mode == "dev-server"


# ══════════════════════════════════════════════════════════
# 3. 静态 HTML 检测
# ══════════════════════════════════════════════════════════
def test_detect_static_html_index(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """纯 HTML 项目：无 package.json、无端口监听 → static-html 模式"""
    (workspace / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    monkeypatch.setattr(pm, "is_port_open", lambda *_a, **_k: False)

    info = pm.detect_dev_server(workspace)
    assert info.mode == "static-html"
    assert info.framework == "static-html"
    assert info.entry == "index.html"
    assert info.running is False


def test_detect_static_html_other_name(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无 index.html 时回退到根目录任意 .html"""
    (workspace / "page.html").write_text("<p>x</p>", encoding="utf-8")
    monkeypatch.setattr(pm, "is_port_open", lambda *_a, **_k: False)

    assert pm.detect_static_html(workspace) == "page.html"


def test_detect_nothing(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """空工作区 → mode=none"""
    monkeypatch.setattr(pm, "is_port_open", lambda *_a, **_k: False)
    info = pm.detect_dev_server(workspace)
    assert info.mode == "none"
    assert info.running is False


def test_detect_endpoint(preview_client: TestClient, workspace: Path, monkeypatch) -> None:
    """GET /api/preview/detect 返回探测字段"""
    (workspace / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    monkeypatch.setattr(pm, "is_port_open", lambda *_a, **_k: False)

    resp = preview_client.get("/api/preview/detect")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "static-html"
    assert data["entry"] == "index.html"
    assert {"url", "port", "framework", "running"} <= data.keys()


# ══════════════════════════════════════════════════════════
# 4. 静态文件预览端点
# ══════════════════════════════════════════════════════════
def test_static_endpoint_serves_html(preview_client: TestClient, workspace: Path) -> None:
    """GET /api/preview/static 返回工作区文件内容与 text/html"""
    (workspace / "index.html").write_text("<h1>你好</h1>", encoding="utf-8")

    resp = preview_client.get("/api/preview/static", params={"path": "index.html"})
    assert resp.status_code == 200
    assert "你好" in resp.text
    assert "text/html" in resp.headers["content-type"]


def test_static_endpoint_traversal_blocked(preview_client: TestClient, workspace: Path) -> None:
    """路径穿越被拦截（复用 files._safe_path）"""
    resp = preview_client.get("/api/preview/static", params={"path": "../../etc/passwd"})
    assert resp.status_code == 400


def test_static_endpoint_not_found(preview_client: TestClient, workspace: Path) -> None:
    resp = preview_client.get("/api/preview/static", params={"path": "nope.html"})
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════
# 5. watcher 启动/停止/防抖
# ══════════════════════════════════════════════════════════
class _FakeObserver:
    """替代 watchdog Observer，记录生命周期，不产生真实线程"""

    instances: list[_FakeObserver] = []

    def __init__(self) -> None:
        self.scheduled: list[tuple[Any, str, bool]] = []
        self.started = False
        self.stopped = False
        self.joined = False
        self.daemon = False
        _FakeObserver.instances.append(self)

    def schedule(self, handler: Any, path: str, recursive: bool) -> None:
        self.scheduled.append((handler, path, recursive))

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def join(self, timeout: float | None = None) -> None:
        self.joined = True


def test_watcher_start_and_stop(
    preview_client: TestClient,
    workspace: Path,
    fresh_manager: pm.PreviewManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """start → observer 启动；stop → stop+join 清理，状态归零"""
    _FakeObserver.instances = []
    monkeypatch.setattr(pm, "Observer", _FakeObserver)
    monkeypatch.setattr(pm, "_WATCHDOG_AVAILABLE", True)

    resp = preview_client.post("/api/preview/start", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["watching"] is True

    observer = _FakeObserver.instances[0]
    assert observer.started is True
    assert observer.scheduled[0][1] == str(workspace.resolve())
    assert observer.scheduled[0][2] is True  # recursive

    resp = preview_client.post("/api/preview/stop")
    assert resp.status_code == 200
    data = resp.json()
    assert data["stopped"] is True
    assert data["watching"] is False
    assert observer.stopped is True
    assert observer.joined is True  # 线程已清理


def test_watcher_stop_idempotent(
    preview_client: TestClient, fresh_manager: pm.PreviewManager
) -> None:
    """未启动时 stop 幂等成功"""
    resp = preview_client.post("/api/preview/stop")
    assert resp.status_code == 200
    assert resp.json()["stopped"] is False


def test_watcher_start_invalid_path(
    preview_client: TestClient,
    fresh_manager: pm.PreviewManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """监听不存在目录 → 400"""
    monkeypatch.setattr(pm, "_WATCHDOG_AVAILABLE", True)
    resp = preview_client.post("/api/preview/start", json={"path": "no/such/dir"})
    assert resp.status_code == 400


async def test_watcher_debounce_merges_events() -> None:
    """防抖窗口内多次文件事件合并为一次 reload 广播"""
    manager = pm.PreviewManager(debounce_sec=0.05)
    try:
        queue = manager.subscribe()
        manager._on_fs_event("a.py")
        manager._on_fs_event("b.py")
        manager._on_fs_event("c.py")

        msg = await asyncio.wait_for(queue.get(), timeout=2)
        assert msg["type"] == "reload"
        assert msg["count"] == 1
        assert set(msg["changed"]) == {"a.py", "b.py", "c.py"}

        # 第二次事件 → 新的 reload（count 递增）
        manager._on_fs_event("d.py")
        msg2 = await asyncio.wait_for(queue.get(), timeout=2)
        assert msg2["count"] == 2
        assert queue.empty()
    finally:
        manager.stop_watcher()
        assert manager.reload_count == 2


async def test_watcher_real_watchdog_integration(tmp_path: Path) -> None:
    """真实 watchdog：写入 tmp 文件触发 reload（线程在 stop 后清理）"""
    if not pm._WATCHDOG_AVAILABLE:
        pytest.skip("watchdog 未安装")

    threads_before = threading.active_count()
    manager = pm.PreviewManager(debounce_sec=0.1)
    queue = manager.subscribe()
    try:
        result = manager.start_watcher(tmp_path)
        assert result["success"] is True

        await asyncio.sleep(0.2)  # 等待 observer 就绪
        (tmp_path / "hello.html").write_text("<h1>x</h1>", encoding="utf-8")

        msg = await asyncio.wait_for(queue.get(), timeout=5)
        assert msg["type"] == "reload"
        assert any("hello.html" in p for p in msg["changed"])
    finally:
        manager.stop_watcher()

    assert manager.watching is False
    # 允许 watchdog 内部短暂延迟退出，但不能残留运行中的 observer 线程
    await asyncio.sleep(0.2)
    assert threading.active_count() <= threads_before + 1


# ══════════════════════════════════════════════════════════
# 6. WebSocket reload 推送
# ══════════════════════════════════════════════════════════
def test_ws_receives_reload(preview_app: FastAPI, fresh_manager: pm.PreviewManager) -> None:
    """WS 客户端收到 reload 广播；ping 得到 pong"""
    client = TestClient(preview_app)
    with client.websocket_connect("/ws/preview") as ws:
        ws.send_text("ping")
        pong = ws.receive_json()
        assert pong["type"] == "pong"

        fresh_manager._notify_reload(["src/App.tsx"])
        msg = ws.receive_json()
        assert msg["type"] == "reload"
        assert "src/App.tsx" in msg["changed"]
    assert fresh_manager.subscriber_count == 0  # 断开后订阅已清理


# ══════════════════════════════════════════════════════════
# 7. proxy 反向代理（mock httpx）
# ══════════════════════════════════════════════════════════
class _FakeResponse:
    def __init__(
        self,
        content: bytes = b"<html>proxied</html>",
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.content = content
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {"content-type": "text/html"})


class _FakeAsyncClient:
    """记录请求并按预设响应/异常回复的 httpx.AsyncClient 替身"""

    next_response: _FakeResponse | None = None
    next_error: Exception | None = None
    requested: list[str] = []

    def __init__(self, **_kwargs: Any) -> None:
        self.closed = False

    async def get(self, url: str) -> _FakeResponse:
        _FakeAsyncClient.requested.append(url)
        if _FakeAsyncClient.next_error is not None:
            raise _FakeAsyncClient.next_error
        assert _FakeAsyncClient.next_response is not None
        return _FakeAsyncClient.next_response

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_client() -> None:
    _FakeAsyncClient.next_response = None
    _FakeAsyncClient.next_error = None
    _FakeAsyncClient.requested = []


def test_proxy_forwards_response(
    preview_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """代理转发 dev-server 响应，并剔除 hop-by-hop 头"""
    monkeypatch.setattr(preview_api, "_create_async_client", lambda **_: _FakeAsyncClient())
    _FakeAsyncClient.next_response = _FakeResponse(
        content=b"body-bytes",
        status_code=201,
        headers={
            "content-type": "text/html; charset=utf-8",
            "content-encoding": "gzip",  # 应被剔除
            "x-custom": "keep",
        },
    )

    resp = preview_client.get("/api/preview/proxy", params={"port": 5173, "path": "/index.html"})
    assert resp.status_code == 201
    assert resp.content == b"body-bytes"
    assert resp.headers["x-custom"] == "keep"
    assert "content-encoding" not in resp.headers
    assert _FakeAsyncClient.requested == ["http://127.0.0.1:5173/index.html"]


def test_proxy_bad_port(preview_client: TestClient) -> None:
    """端口超出合法区间 → 400（SSRF 防护）"""
    resp = preview_client.get("/api/preview/proxy", params={"port": 80, "path": "/"})
    assert resp.status_code == 400
    resp = preview_client.get("/api/preview/proxy", params={"port": 70000, "path": "/"})
    assert resp.status_code == 400


def test_proxy_upstream_down(
    preview_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dev-server 不可达 → 502"""
    monkeypatch.setattr(preview_api, "_create_async_client", lambda **_: _FakeAsyncClient())
    _FakeAsyncClient.next_error = httpx.ConnectError("connection refused")

    resp = preview_client.get("/api/preview/proxy", params={"port": 59999, "path": "/"})
    assert resp.status_code == 502
    assert "不可达" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════
# 8. 鉴权（主应用 APIKeyMiddleware）
# ══════════════════════════════════════════════════════════
def test_preview_auth_enforced(client: TestClient) -> None:
    """无/错 API Key → 401；正确 Key → 200（复用主应用 client fixture）"""
    ok = client.get("/api/preview/status")
    assert ok.status_code == 200

    no_key = client.get("/api/preview/status", headers={"X-API-Key": ""})
    assert no_key.status_code == 401

    wrong_key = client.get("/api/preview/status", headers={"X-API-Key": "wrong-key"})
    assert wrong_key.status_code == 401
