"""
OpenAPI/Swagger 集成 — 自动生成 API 调用代码 + 模拟服务
"""

from __future__ import annotations

from pathlib import Path


def generate_from_openapi(
    spec_url: str = "",
    spec_json: dict | None = None,
    language: str = "python",
    output_dir: str = "",
) -> dict:
    """从 OpenAPI 规范生成客户端代码"""
    spec = spec_json or {}
    if spec_url and not spec:
        try:
            import requests

            r = requests.get(spec_url, timeout=30)
            spec = r.json()
        except Exception as e:
            return {"success": False, "error": f"获取 OpenAPI 失败: {e}"}

    if not spec:
        return {"success": False, "error": "需要 spec_url 或 spec_json"}

    paths = spec.get("paths", {})
    code_lines = (
        _gen_python_client(spec, paths) if language == "python" else _gen_js_client(spec, paths)
    )
    code = "\n".join(code_lines)

    out = Path(output_dir or Path.cwd())
    out.mkdir(parents=True, exist_ok=True)
    filename = f"api_client.{'py' if language == 'python' else 'js'}"
    (out / filename).write_text(code, encoding="utf-8")

    return {
        "success": True,
        "file": str(out / filename),
        "endpoints": len(paths),
        "code": code[:3000],
    }


def generate_mock_server(spec_json: dict) -> dict:
    """从 OpenAPI 生成模拟服务器"""
    paths = spec_json.get("paths", {})
    endpoints = []
    for path, methods in paths.items():
        for method, detail in methods.items():
            resp = detail.get("responses", {}).get("200", {})
            schema = resp.get("content", {}).get("application/json", {}).get("schema", {})
            endpoints.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "summary": detail.get("summary", ""),
                    "example_response": _generate_example(schema),
                }
            )

    return {
        "success": True,
        "title": spec_json.get("info", {}).get("title", "Mock API"),
        "endpoints": endpoints,
        "total": len(endpoints),
    }


def _generate_example(schema: dict) -> dict:
    """根据 JSON Schema 生成示例值"""
    stype = schema.get("type", "object")
    example = {}
    if stype == "object":
        for prop, ps in schema.get("properties", {}).items():
            ptype = ps.get("type", "string")
            example[prop] = {
                "string": "example",
                "integer": 0,
                "number": 0.0,
                "boolean": True,
                "array": [],
            }.get(ptype, "example")
    return example


def _gen_python_client(spec: dict, paths: dict) -> list[str]:
    """生成 Python 客户端"""
    title = spec.get("info", {}).get("title", "API")
    # 修复: servers 为空列表时回退到默认 url, 避免 IndexError
    servers = spec.get("servers") or [{}]
    base_url = servers[0].get("url", "http://localhost")
    lines = [
        f'"""Auto-generated client for {title}"""',
        "import requests",
        "",
        "class APIClient:",
        f'    def __init__(self, base_url="{base_url}"):',
        "        self.base_url = base_url.rstrip('/')",
        "        self.session = requests.Session()",
        "",
    ]
    for path, methods in paths.items():
        for method, detail in methods.items():
            func_name = _path_to_func(method, path)
            summary = detail.get("summary", "")
            params = _extract_params(detail)
            lines.append(f"    def {func_name}(self{', ' + ', '.join(params) if params else ''}):")
            lines.append(f'        """{summary}"""')
            if method == "get":
                lines.append(f"        return self.session.get(f'{{self.base_url}}{path}')")
            elif method == "post":
                lines.append(
                    f"        return self.session.post(f'{{self.base_url}}{path}', json=data)"
                )
            elif method == "put":
                lines.append(
                    f"        return self.session.put(f'{{self.base_url}}{path}', json=data)"
                )
            elif method == "delete":
                lines.append(f"        return self.session.delete(f'{{self.base_url}}{path}')")
            lines.append("")
    return lines


def _gen_js_client(spec: dict, paths: dict) -> list[str]:
    """生成 JS 客户端"""
    title = spec.get("info", {}).get("title", "API")
    # 修复: servers 为空列表时回退到默认 url, 避免 IndexError
    servers = spec.get("servers") or [{}]
    base_url = servers[0].get("url", "http://localhost")
    lines = [
        f"// Auto-generated client for {title}",
        f'const BASE = "{base_url}";',
        "",
    ]
    for path, methods in paths.items():
        for method, _detail in methods.items():
            func_name = _path_to_func(method, path)
            lines.append(f"async function {func_name}() {{")
            lines.append(
                f"  const r = await fetch(BASE + '{path}', {{ method: '{method.upper()}' }});"
            )
            lines.append("  return r.json();")
            lines.append("}")
            lines.append("")
    return lines


def _path_to_func(method: str, path: str) -> str:
    safe = path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
    return f"{method}_{safe or 'root'}".replace("-", "_")


def _extract_params(detail: dict) -> list[str]:
    params = []
    for p in detail.get("parameters", []):
        params.append(f"{p['name']}=None")
    # 修复: 只要存在 requestBody 键就应生成 data 参数 (空 dict {} 也是合法 body)
    if detail.get("requestBody") is not None:
        params.append("data=None")
    return params
