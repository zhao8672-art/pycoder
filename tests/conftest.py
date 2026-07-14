"""Test configuration and shared fixtures."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Generator

# ── Windows GBK 编码兼容 ──────────────────────────────────
# pytest 收集含中文的测试时，subprocess 管道默认用 GBK 解码导致
# UnicodeDecodeError / KeyboardInterrupt。强制 UTF-8 模式。
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import pytest
from fastapi.testclient import TestClient

# 网络测试：进行真实 HTTP 请求，CI 中默认跳过，设置 RUN_NETWORK_TESTS=1 启用
_NETWORK_TESTS = {
    "tests/test_skills_market_deep.py::test_fetcher",
    "tests/test_skills_market_deep.py::test_install",
    "tests/test_skills_market_v2.py::test_enhanced_sync",
}


def pytest_collection_modifyitems(config, items):
    """跳过网络测试（除非 RUN_NETWORK_TESTS=1）"""
    if os.environ.get("RUN_NETWORK_TESTS"):
        return
    skip = pytest.mark.skip(reason="requires network - set RUN_NETWORK_TESTS=1 to run")
    for item in items:
        if item.nodeid in _NETWORK_TESTS:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def app():
    """Get the FastAPI application instance."""
    from pycoder.server.app import app
    return app


@pytest.fixture(scope="function")
def client() -> Generator[TestClient, None, None]:
    """Get a TestClient for the FastAPI application.

    P0-4 强制 API 认证后，请求须携带 X-API-Key。本 fixture 从
    app 模块读取当前 _API_KEY 并注入默认请求头，使各路由测试
    无需逐个添加认证头。function 作用域确保 P0-4 认证测试重载
    模块后仍能读取到最新 key。

    注意：不依赖 session 级 app fixture，因 P0-4 测试可能已重载
    模块（旧 app 实例与当前 _API_KEY 不匹配）。每次重新导入确保
    app 与 _API_KEY 来自同一模块实例。
    """
    import sys
    from pycoder.server.app import app
    app_module = sys.modules.get("pycoder.server.app")
    api_key = getattr(app_module, "_API_KEY", "") or "" if app_module else ""
    headers = {"X-API-Key": api_key} if api_key else {}
    with TestClient(app, headers=headers) as c:
        yield c


@pytest.fixture(scope="function")
def fresh_store():
    """Get a fresh in-memory session store for each test."""
    from pycoder.server.session_store import get_session_store, SessionStore
    store = get_session_store()
    # Use in-memory store for tests
    store_path = Path(__file__).parent / "test_data"
    store_path.mkdir(exist_ok=True)
    yield store
    # Cleanup
    for f in store_path.glob("*.db"):
        f.unlink()
    store_path.rmdir()


@pytest.fixture(scope="session")
def test_data_dir():
    """Get the test data directory."""
    return Path(__file__).parent / "test_data"
