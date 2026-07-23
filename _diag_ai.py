"""诊断 AI 功能卡顿的根因."""
import http.client
import json
import time
import os
import sys

API_KEY = "REDACTED-PYCODER-API-KEY"
HOST, PORT = "127.0.0.1", 8423

def get(path, timeout=10):
    conn = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    try:
        conn.request("GET", path, headers={"X-API-Key": API_KEY, "Connection": "close"})
        r = conn.getresponse()
        data = r.read().decode("utf-8", errors="replace")
        return r.status, data
    finally:
        conn.close()

def post(path, body, timeout=30):
    conn = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    try:
        payload = json.dumps(body)
        conn.request("POST", path, body=payload,
                     headers={"X-API-Key": API_KEY, "Content-Type": "application/json",
                              "Connection": "close"})
        r = conn.getresponse()
        data = r.read().decode("utf-8", errors="replace")
        return r.status, data
    finally:
        conn.close()

print("=" * 70)
print("  PyCoder AI 功能诊断")
print("=" * 70)

# 1. 健康检查
s, d = get("/api/health/live")
print(f"\n1. 健康检查: HTTP {s}")
if s != 200:
    print(f"   失败: {d[:200]}")
    sys.exit(1)

# 2. 模型列表
s, d = get("/api/models")
print(f"\n2. 模型列表: HTTP {s}")
try:
    models = json.loads(d)
    print(f"   数量: {len(models) if isinstance(models, list) else 'N/A'}")
    if isinstance(models, list):
        for m in models[:5]:
            print(f"   - {m.get('id', m)} ({m.get('provider', '?')})")
except Exception as e:
    print(f"   解析失败: {e}")
    print(f"   原始: {d[:300]}")

# 3. LLM provider 状态
s, d = get("/api/llm/status")
print(f"\n3. LLM 状态: HTTP {s}")
print(f"   {d[:500]}")

# 4. 环境变量诊断
print(f"\n4. 环境变量 (诊断):")
for k in ["DEEPSEEK_API_KEY", "AGNES_API_KEY", "QWEN_API_KEY",
          "DASHSCOPE_API_KEY", "GLM_API_KEY", "OPENAI_API_KEY",
          "PYCODER_DEFAULT_MODEL"]:
    v = os.environ.get(k, "")
    if v:
        masked = v[:4] + "***" + v[-2:] if len(v) > 8 else "***"
        print(f"   {k} = {masked}")
    else:
        print(f"   {k} = (未设置)")

# 5. 尝试 AI 调用 (短超时看是否卡住)
print(f"\n5. AI 调用测试 (短超时 15s):")
start = time.time()
try:
    s, d = post("/api/chat", {
        "messages": [{"role": "user", "content": "说'OK'"}],
        "model": "deepseek-chat",
        "max_tokens": 50,
    }, timeout=15)
    elapsed = time.time() - start
    print(f"   HTTP {s} ({elapsed:.1f}s)")
    print(f"   响应: {d[:300]}")
except Exception as e:
    elapsed = time.time() - start
    print(f"   异常 ({elapsed:.1f}s): {e}")

# 6. 备用端点
print(f"\n6. 备用端点 /api/llm/chat:")
start = time.time()
try:
    s, d = post("/api/llm/chat", {
        "messages": [{"role": "user", "content": "说'OK'"}],
        "model": "deepseek-chat",
    }, timeout=15)
    elapsed = time.time() - start
    print(f"   HTTP {s} ({elapsed:.1f}s)")
    print(f"   响应: {d[:300]}")
except Exception as e:
    elapsed = time.time() - start
    print(f"   异常 ({elapsed:.1f}s): {e}")

# 7. 找出正确的 chat 端点
print(f"\n7. 路由探测:")
for path in ["/api/chat", "/api/llm/chat", "/api/v1/chat", "/api/ai/chat",
             "/api/completions", "/api/generate", "/api/chat/completions"]:
    try:
        s, d = get(path, timeout=5)
        print(f"   {path:30s} -> {s}")
    except Exception as e:
        print(f"   {path:30s} -> ERR ({e})")

print()
print("=" * 70)
