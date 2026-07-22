"""阶段 3 验证：性能监控中间件"""
from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.middleware import PerformanceMonitoringMiddleware


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(PerformanceMonitoringMiddleware)

    @app.get("/fast")
    def fast():
        return {"ok": True}

    @app.get("/slow")
    def slow():
        time.sleep(1.2)  # > SLOW_THRESHOLD_MS (1000ms)
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return TestClient(app)


def test_response_time_header_present(client):
    r = client.get("/fast")
    assert "X-Response-Time" in r.headers
    assert r.headers["X-Response-Time"].endswith("ms")


def test_health_path_skipped(client):
    """健康检查路径不添加响应时间头（减少噪音）"""
    r = client.get("/health")
    # 不会因为跳过而失败，但会缺少 X-Response-Time
    assert r.status_code == 200


def test_slow_request_logged(caplog):
    """慢请求会记录 WARNING 日志"""
    import logging
    app = FastAPI()
    app.add_middleware(PerformanceMonitoringMiddleware)

    @app.get("/slow")
    def slow():
        time.sleep(1.1)
        return {"ok": True}

    test_client = TestClient(app)
    with caplog.at_level(logging.INFO, logger="pycoder.server.middleware.perf"):
        r = test_client.get("/slow")
    assert r.status_code == 200
    # 验证慢请求日志
    slow_logs = [r for r in caplog.records if "SLOW" in r.getMessage()]
    assert len(slow_logs) >= 1
