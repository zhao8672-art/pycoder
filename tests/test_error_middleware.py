"""阶段 2 验证：统一错误处理中间件工作正常"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.core.errors import (
    NotFoundError,
    PermissionDeniedError,
    PyCoderError,
    RateLimitError,
    ValidationError,
)
from pycoder.server.middleware import ErrorHandlingMiddleware


@pytest.fixture
def client():
    """构造一个带 ErrorMiddleware 的测试应用"""
    app = FastAPI()
    app.add_middleware(ErrorHandlingMiddleware)

    @app.get("/raise-typed")
    def raise_typed():
        raise NotFoundError("Test not found", details={"resource": "user_42"})

    @app.get("/raise-validation")
    def raise_validation():
        raise ValidationError("Invalid email", details={"field": "email"})

    @app.get("/raise-permission")
    def raise_permission():
        raise PermissionDeniedError("No admin rights")

    @app.get("/raise-rate")
    def raise_rate():
        raise RateLimitError("Too fast", details={"retry_after": 60})

    @app.get("/raise-generic")
    def raise_generic():
        raise RuntimeError("Boom! Unexpected")

    @app.get("/ok")
    def ok():
        return {"ok": True}

    return TestClient(app)


def test_not_found_returns_404(client):
    r = client.get("/raise-typed")
    assert r.status_code == 404
    data = r.json()
    assert data["error"] == "NOT_FOUND"
    assert data["message"] == "Test not found"
    assert data["details"] == {"resource": "user_42"}


def test_validation_returns_400(client):
    r = client.get("/raise-validation")
    assert r.status_code == 400
    data = r.json()
    assert data["error"] == "VALIDATION_ERROR"
    assert data["details"]["field"] == "email"


def test_permission_returns_403(client):
    r = client.get("/raise-permission")
    assert r.status_code == 403
    assert r.json()["error"] == "PERMISSION_DENIED"


def test_rate_limit_returns_429(client):
    r = client.get("/raise-rate")
    assert r.status_code == 429
    assert r.json()["details"]["retry_after"] == 60


def test_generic_exception_returns_500(client):
    r = client.get("/raise-generic")
    assert r.status_code == 500
    data = r.json()
    assert data["error"] == "INTERNAL_ERROR"
    assert "request_id" in data


def test_ok_request_passes_through(client):
    r = client.get("/ok")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_request_id_header_present(client):
    r = client.get("/ok")
    assert "X-Request-ID" in r.headers


def test_request_id_preserved_from_request(client):
    r = client.get("/ok", headers={"X-Request-ID": "test1234"})
    assert r.headers["X-Request-ID"] == "test1234"


def test_pycoder_error_inheritance():
    """PyCoderError 及其子类继承关系正确"""
    assert issubclass(NotFoundError, PyCoderError)
    assert issubclass(ValidationError, PyCoderError)
    assert issubclass(PermissionDeniedError, PyCoderError)
    assert issubclass(RateLimitError, PyCoderError)


def test_error_to_dict():
    e = ValidationError("bad", details={"x": 1})
    d = e.to_dict()
    assert d["error"] == "VALIDATION_ERROR"
    assert d["message"] == "bad"
    assert d["details"] == {"x": 1}
