"""测试 error_handlers 模块"""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from pycoder.server.error_handlers import (
    ErrorCode,
    make_error_response,
    make_success_response,
    register_error_handlers,
)


def test_error_code_constants():
    """测试错误码常量"""
    assert ErrorCode.UNAUTHORIZED == "UNAUTHORIZED"
    assert ErrorCode.NOT_FOUND == "NOT_FOUND"
    assert ErrorCode.VALIDATION_ERROR == "VALIDATION_ERROR"
    assert ErrorCode.INTERNAL_ERROR == "INTERNAL_ERROR"


def test_make_error_response():
    """测试构造错误响应"""
    resp = make_error_response(
        code=ErrorCode.NOT_FOUND,
        message="资源不存在",
        status_code=404,
        details={"resource": "skill"},
    )
    assert resp.status_code == 404
    body = resp.body.decode()
    assert "NOT_FOUND" in body
    assert "资源不存在" in body
    assert "skill" in body
    assert "request_id" in body
    assert "timestamp" in body


def test_make_error_response_default_request_id():
    """测试自动生成 request_id"""
    resp = make_error_response(
        code=ErrorCode.INTERNAL_ERROR,
        message="错误",
    )
    body = resp.body.decode()
    assert "request_id" in body
    # UUID 格式
    import re
    assert re.search(r'"request_id"\s*:\s*"[a-f0-9-]{36}"', body)


def test_make_success_response():
    """测试构造成功响应"""
    result = make_success_response(
        data={"key": "value"},
        message="操作成功",
    )
    assert result["success"] is True
    assert result["data"] == {"key": "value"}
    assert result["message"] == "操作成功"
    assert "request_id" in result
    assert "timestamp" in result


def test_register_error_handlers():
    """测试注册错误处理器"""
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/test-404")
    async def test_404():
        raise HTTPException(status_code=404, detail="not found")

    @app.get("/test-500")
    async def test_500():
        raise RuntimeError("unexpected error")

    class Item(BaseModel):
        name: str = Field(..., min_length=1)

    @app.post("/test-validation")
    async def test_validation(item: Item):
        return {"ok": True}

    # raise_server_exceptions=False 让 500 异常被全局处理器捕获而非直接抛出
    client = TestClient(app, raise_server_exceptions=False)

    # 测试 404
    resp = client.get("/test-404")
    assert resp.status_code == 404
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"

    # 测试 500
    resp = client.get("/test-500")
    assert resp.status_code == 500
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INTERNAL_ERROR"
    # 不应泄露详细堆栈
    assert "Traceback" not in resp.text

    # 测试验证错误
    resp = client.post("/test-validation", json={"name": ""})
    assert resp.status_code == 422
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "errors" in body["error"]["details"]


def test_validation_error_format():
    """测试验证错误格式"""
    app = FastAPI()
    register_error_handlers(app)

    class StrictModel(BaseModel):
        age: int = Field(..., ge=0, le=150)
        email: str

    @app.post("/strict")
    async def strict_endpoint(data: StrictModel):
        return {"ok": True}

    client = TestClient(app)
    resp = client.post("/strict", json={"age": -1, "email": 123})
    assert resp.status_code == 422
    body = resp.json()
    errors = body["error"]["details"]["errors"]
    assert len(errors) >= 1
    for err in errors:
        assert "field" in err
        assert "message" in err
        assert "type" in err


def test_unauthorized_error():
    """测试 401 错误格式"""
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/protected")
    async def protected():
        raise HTTPException(status_code=401, detail="Unauthorized")

    client = TestClient(app)
    resp = client.get("/protected")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "UNAUTHORIZED"
