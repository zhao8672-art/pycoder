"""冒烟测试 — 代码执行关键路径（本地沙箱，无需网络）"""

from __future__ import annotations

import pytest


@pytest.mark.smoke
def test_code_exec_python(client):
    """POST /api/code-exec/execute 执行简单 Python 应成功"""
    resp = client.post(
        "/api/code-exec/execute",
        json={"code": "print(1 + 1)", "language": "python"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    assert "2" in payload.get("stdout", "")