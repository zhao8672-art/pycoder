"""
Item API 测试
运行: pytest tests/ -v
"""
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def test_health():
    """健康检查"""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_create_item():
    """创建测试"""
    resp = client.post("/items", json={"title": "测试Item"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "测试Item"
    assert data["id"] is not None
    return data


def test_list_items():
    """列表测试"""
    resp = client.get("/items")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data


def test_get_item():
    """详情测试"""
    created = test_create_item()
    resp = client.get(f"/items/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_update_item():
    """更新测试"""
    created = test_create_item()
    resp = client.put(f"/items/{created['id']}", json={"title": "更新标题"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "更新标题"


def test_delete_item():
    """删除测试"""
    created = test_create_item()
    resp = client.delete(f"/items/{created['id']}")
    assert resp.status_code == 200
