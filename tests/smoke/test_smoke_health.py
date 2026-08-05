"""冒烟测试 — 健康检查关键路径"""

from __future__ import annotations

import pytest


@pytest.mark.smoke
def test_health_returns_ok(client):
    """GET /api/health 应返回 200 且 status=ok"""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("status") == "ok"