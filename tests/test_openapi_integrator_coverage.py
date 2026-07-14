"""
openapi_integrator.py 模块单元测试 — 覆盖率目标 >=95%

测试策略:
- generate_from_openapi: 各种参数组合 (spec_url / spec_json / 都空 / 语言分支 / 输出目录)
- generate_mock_server: 解析 paths 各种方法
- _generate_example: 各种 JSON Schema 类型
- _gen_python_client: 各 HTTP 方法分支
- _gen_js_client: 生成 JS 客户端
- _path_to_func: 各种路径转换
- _extract_params: parameters + requestBody
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pycoder.python import openapi_integrator as oa_mod
from pycoder.python.openapi_integrator import (
    generate_from_openapi,
    generate_mock_server,
    _generate_example,
    _gen_python_client,
    _gen_js_client,
    _path_to_func,
    _extract_params,
)


# ── generate_from_openapi ───────────────────────────────────


class TestGenerateFromOpenapi:
    def test_no_spec_returns_error(self, tmp_path):
        # 既无 spec_url 也无 spec_json
        result = generate_from_openapi(output_dir=str(tmp_path))
        assert result["success"] is False
        assert "spec_url" in result["error"]

    def test_with_spec_json_python(self, tmp_path):
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API"},
            "servers": [{"url": "http://localhost:8080"}],
            "paths": {
                "/users": {
                    "get": {
                        "summary": "Get users",
                        "parameters": [{"name": "page"}],
                    },
                    "post": {
                        "summary": "Create user",
                        "requestBody": {"content": {}},
                    },
                },
                "/users/{id}": {
                    "get": {"summary": "Get user"},
                    "put": {"summary": "Update user", "requestBody": {}},
                    "delete": {"summary": "Delete user"},
                },
            },
        }
        result = generate_from_openapi(spec_json=spec, language="python", output_dir=str(tmp_path))
        assert result["success"] is True
        assert result["endpoints"] == 2  # 两个 path
        assert "code" in result
        # 文件应已写入
        out_file = tmp_path / "api_client.py"
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "APIClient" in content
        assert "def get_users" in content
        assert "def post_users" in content
        assert "def get_users_id" in content

    def test_with_spec_json_javascript(self, tmp_path):
        spec = {
            "info": {"title": "JS API"},
            "paths": {
                "/items": {
                    "get": {"summary": "List items"},
                    "delete": {"summary": "Delete item"},
                },
            },
        }
        result = generate_from_openapi(spec_json=spec, language="javascript", output_dir=str(tmp_path))
        assert result["success"] is True
        out_file = tmp_path / "api_client.js"
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "BASE" in content
        assert "async function get_items" in content
        assert "fetch" in content

    def test_spec_url_fetch_failure(self, tmp_path, monkeypatch):
        # mock requests.get 抛异常
        def raise_error(*args, **kwargs):
            raise RuntimeError("network error")

        # 模拟 requests 模块存在但 get 抛异常
        fake_requests = MagicMock()
        fake_requests.get = raise_error
        monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)
        result = generate_from_openapi(spec_url="http://example.com/openapi.json", output_dir=str(tmp_path))
        assert result["success"] is False
        assert "OpenAPI 失败" in result["error"]

    def test_spec_url_fetch_success(self, tmp_path, monkeypatch):
        # mock requests.get 返回 json
        spec = {
            "info": {"title": "URL API"},
            "paths": {"/x": {"get": {}}},
        }
        mock_response = MagicMock()
        mock_response.json = lambda: spec
        fake_requests = MagicMock()
        fake_requests.get = lambda *a, **k: mock_response
        monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)
        result = generate_from_openapi(spec_url="http://example.com/openapi.json", output_dir=str(tmp_path))
        assert result["success"] is True

    def test_default_output_dir_uses_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        spec = {"info": {"title": "X"}, "paths": {}}
        result = generate_from_openapi(spec_json=spec, language="python")
        assert result["success"] is True
        assert (tmp_path / "api_client.py").exists()

    def test_creates_output_dir(self, tmp_path):
        # output_dir 不存在, 应自动创建
        out_dir = tmp_path / "new_dir" / "sub"
        spec = {"info": {"title": "X"}, "paths": {}}
        result = generate_from_openapi(spec_json=spec, output_dir=str(out_dir))
        assert result["success"] is True
        assert (out_dir / "api_client.py").exists()

    def test_no_servers(self, tmp_path):
        # spec 没有 servers 字段 -> 默认 http://localhost
        spec = {"info": {"title": "X"}, "paths": {}}
        result = generate_from_openapi(spec_json=spec, output_dir=str(tmp_path))
        assert result["success"] is True
        content = (tmp_path / "api_client.py").read_text(encoding="utf-8")
        assert "http://localhost" in content

    def test_empty_servers_list(self, tmp_path):
        # servers 为空列表 -> 默认 url
        spec = {"info": {"title": "X"}, "servers": [], "paths": {}}
        result = generate_from_openapi(spec_json=spec, output_dir=str(tmp_path))
        assert result["success"] is True


# ── generate_mock_server ───────────────────────────────────


class TestGenerateMockServer:
    def test_empty_paths(self):
        result = generate_mock_server({"paths": {}})
        assert result["success"] is True
        assert result["total"] == 0
        assert result["endpoints"] == []

    def test_with_endpoints(self):
        spec = {
            "info": {"title": "Mock API"},
            "paths": {
                "/users": {
                    "get": {
                        "summary": "List users",
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "integer"},
                                                "name": {"type": "string"},
                                            },
                                        }
                                    }
                                }
                            }
                        },
                    },
                    "post": {
                        "summary": "Create user",
                        "responses": {"200": {}},
                    },
                },
            },
        }
        result = generate_mock_server(spec)
        assert result["success"] is True
        assert result["title"] == "Mock API"
        assert result["total"] == 2
        methods = [e["method"] for e in result["endpoints"]]
        assert "GET" in methods
        assert "POST" in methods
        # 验证 example_response
        get_ep = next(e for e in result["endpoints"] if e["method"] == "GET")
        assert get_ep["example_response"] == {"id": 0, "name": "example"}

    def test_no_info_title(self):
        spec = {"paths": {}}
        result = generate_mock_server(spec)
        assert result["title"] == "Mock API"

    def test_response_no_200(self):
        spec = {
            "paths": {
                "/x": {
                    "delete": {
                        "summary": "Delete",
                        "responses": {"404": {}},
                    },
                },
            },
        }
        result = generate_mock_server(spec)
        assert result["total"] == 1
        # response 没 200 -> example_response 为空 {}
        assert result["endpoints"][0]["example_response"] == {}

    def test_response_no_content(self):
        spec = {
            "paths": {
                "/x": {
                    "get": {
                        "responses": {"200": {}},
                    },
                },
            },
        }
        result = generate_mock_server(spec)
        assert result["endpoints"][0]["example_response"] == {}


# ── _generate_example ──────────────────────────────────────


class TestGenerateExample:
    def test_object_with_properties(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "score": {"type": "number"},
                "active": {"type": "boolean"},
                "tags": {"type": "array"},
            },
        }
        result = _generate_example(schema)
        assert result["name"] == "example"
        assert result["age"] == 0
        assert result["score"] == 0.0
        assert result["active"] is True
        assert result["tags"] == []

    def test_object_no_properties(self):
        schema = {"type": "object"}
        result = _generate_example(schema)
        assert result == {}

    def test_default_type(self):
        # type 默认 "object"
        schema = {}
        result = _generate_example(schema)
        assert result == {}

    def test_unknown_property_type(self):
        schema = {
            "type": "object",
            "properties": {
                "custom": {"type": "customtype"},
            },
        }
        result = _generate_example(schema)
        # 未知类型 -> 默认 "example"
        assert result["custom"] == "example"

    def test_non_object_type(self):
        # 非 object 类型 -> 返回空 dict (实现只处理 object)
        schema = {"type": "array"}
        result = _generate_example(schema)
        assert result == {}


# ── _gen_python_client ──────────────────────────────────────


class TestGenPythonClient:
    def test_full_endpoints(self):
        spec = {
            "info": {"title": "API"},
            "servers": [{"url": "http://api.example.com"}],
            "paths": {
                "/items": {
                    "get": {"summary": "List"},
                    "post": {"summary": "Create", "requestBody": {}},
                    "put": {"summary": "Update", "requestBody": {}},
                    "delete": {"summary": "Delete"},
                },
                "/items/{item_id}": {
                    "get": {
                        "summary": "Get",
                        "parameters": [{"name": "item_id"}],
                    },
                },
            },
        }
        lines = _gen_python_client(spec, spec["paths"])
        code = "\n".join(lines)
        assert '"""Auto-generated client for API"""' in code
        assert "import requests" in code
        assert "class APIClient:" in code
        assert "self.base_url" in code
        assert "def get_items" in code
        assert "def post_items" in code
        assert "def put_items" in code
        assert "def delete_items" in code
        assert "def get_items_item_id" in code
        # POST 应包含 json=data
        assert "json=data" in code
        # GET parameters 应包含 item_id=None
        assert "item_id=None" in code

    def test_no_servers(self):
        spec = {"info": {"title": "X"}, "paths": {}}
        lines = _gen_python_client(spec, {})
        code = "\n".join(lines)
        assert "http://localhost" in code

    def test_empty_servers(self):
        spec = {"info": {"title": "X"}, "servers": [], "paths": {}}
        lines = _gen_python_client(spec, {})
        code = "\n".join(lines)
        assert "http://localhost" in code

    def test_default_title(self):
        spec = {"info": {}, "paths": {}}
        lines = _gen_python_client(spec, {})
        code = "\n".join(lines)
        assert 'API' in code  # 默认 title

    def test_patch_method_not_handled(self):
        # PATCH 方法没有专门的分支
        spec = {
            "info": {"title": "X"},
            "paths": {"/x": {"patch": {"summary": "Patch"}}},
        }
        lines = _gen_python_client(spec, spec["paths"])
        code = "\n".join(lines)
        # 应生成函数但无方法体分支
        assert "def patch_x" in code

    def test_endpoint_with_no_summary(self):
        spec = {
            "info": {"title": "X"},
            "paths": {"/x": {"get": {}}},
        }
        lines = _gen_python_client(spec, spec["paths"])
        code = "\n".join(lines)
        assert "def get_x" in code


# ── _gen_js_client ─────────────────────────────────────────


class TestGenJsClient:
    def test_full_endpoints(self):
        spec = {
            "info": {"title": "JS API"},
            "servers": [{"url": "http://js.example.com"}],
            "paths": {
                "/items": {
                    "get": {"summary": "List"},
                    "post": {"summary": "Create"},
                },
            },
        }
        lines = _gen_js_client(spec, spec["paths"])
        code = "\n".join(lines)
        assert "// Auto-generated client for JS API" in code
        assert 'const BASE = "http://js.example.com"' in code
        assert "async function get_items" in code
        assert "async function post_items" in code
        assert "fetch" in code
        assert "r.json()" in code

    def test_no_servers(self):
        spec = {"info": {"title": "X"}, "paths": {}}
        lines = _gen_js_client(spec, {})
        code = "\n".join(lines)
        assert 'http://localhost' in code


# ── _path_to_func ──────────────────────────────────────────


class TestPathToFunc:
    def test_simple_path(self):
        assert _path_to_func("get", "/users") == "get_users"

    def test_root_path(self):
        assert _path_to_func("get", "/") == "get_root"

    def test_empty_path(self):
        assert _path_to_func("get", "") == "get_root"

    def test_path_with_param(self):
        # /users/{id} -> get_users_id
        assert _path_to_func("get", "/users/{id}") == "get_users_id"

    def test_path_with_dash(self):
        # /user-profiles -> get_user_profiles
        assert _path_to_func("get", "/user-profiles") == "get_user_profiles"

    def test_nested_path(self):
        assert _path_to_func("post", "/users/{id}/posts") == "post_users_id_posts"


# ── _extract_params ─────────────────────────────────────────


class TestExtractParams:
    def test_no_params_no_body(self):
        detail = {}
        assert _extract_params(detail) == []

    def test_with_parameters(self):
        detail = {
            "parameters": [
                {"name": "page"},
                {"name": "limit"},
            ]
        }
        result = _extract_params(detail)
        assert "page=None" in result
        assert "limit=None" in result

    def test_with_request_body(self):
        detail = {"requestBody": {"content": {}}}
        result = _extract_params(detail)
        assert "data=None" in result

    def test_with_params_and_body(self):
        detail = {
            "parameters": [{"name": "id"}],
            "requestBody": {},
        }
        result = _extract_params(detail)
        assert "id=None" in result
        assert "data=None" in result
