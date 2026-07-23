"""快速 AI 调用诊断 — 用正确格式."""
import http.client
import json
import time

API_KEY = "REDACTED-PYCODER-API-KEY"

# 探测 /api/chat 的 OpenAPI schema
conn = http.client.HTTPConnection("127.0.0.1", 8423, timeout=10)
conn.request("GET", "/openapi.json", headers={"X-API-Key": API_KEY, "Connection": "close"})
r = conn.getresponse()
data = json.loads(r.read().decode("utf-8", errors="replace"))

# 找到 /api/chat 端点
schemas = data.get("components", {}).get("schemas", {})
print("=== /api/chat 相关 schema ===")
for name, sch in schemas.items():
    if "chat" in name.lower() or "request" in name.lower() and "chat" in str(sch).lower():
        print(f"\n--- {name} ---")
        print(json.dumps(sch, ensure_ascii=False, indent=2)[:800])

# 找 /api/chat 路径
print("\n=== /api/chat 路径定义 ===")
for path, methods in data.get("paths", {}).items():
    if "chat" in path:
        print(f"\n{path}:")
        for method, info in methods.items():
            print(f"  {method.upper()}: {info.get('summary', '')}")
            req = info.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
            if req:
                ref = req.get("$ref", "")
                if ref:
                    print(f"    body: {ref}")
                else:
                    print(f"    body: {json.dumps(req, ensure_ascii=False)[:300]}")
            responses = info.get("responses", {})
            for code, resp in list(responses.items())[:2]:
                ref = resp.get("content", {}).get("application/json", {}).get("schema", {})
                if ref:
                    print(f"    {code}: {ref.get('$ref', ref)}")
