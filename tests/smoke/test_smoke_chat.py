"""冒烟测试 — 聊天认证关键路径

冒烟只验证路由注册 + 认证中间件生效，不触发真实 LLM 调用（避免网络/慢）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.smoke
def test_chat_requires_auth():
    """不带 API Key 请求 /api/chat 应被认证中间件拦截 (401/403)"""
    from pycoder.server.app import app

    with TestClient(app) as c:
        resp = c.post("/api/chat", json={"message": "hi", "model": "auto"})
        assert resp.status_code in (401, 403)


@pytest.mark.smoke
def test_chat_route_registered(client):
    """带认证请求 /api/chat 应返回非 500 的合法业务响应（路由存在且可处理）"""
    resp = client.post("/api/chat", json={"message": "ping", "model": "auto"})
    # 认证通过后，快速路径应返回 200；若上游异常则带 route 字段分类，而非裸 500
    assert resp.status_code != 500