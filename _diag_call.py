"""用正确格式调用 /api/chat, 验证根因."""
import http.client
import json
import time

API_KEY = "REDACTED-PYCODER-API-KEY"

def call_chat(message, model="auto", timeout=30):
    conn = http.client.HTTPConnection("127.0.0.1", 8423, timeout=timeout)
    try:
        body = json.dumps({"message": message, "model": model, "stream": False})
        conn.request("POST", "/api/chat", body=body,
                     headers={"X-API-Key": API_KEY, "Content-Type": "application/json",
                              "Connection": "close"})
        r = conn.getresponse()
        data = r.read().decode("utf-8", errors="replace")
        return r.status, data
    finally:
        conn.close()

print("=" * 70)
print("  AI 调用根因诊断 (使用正确 schema)")
print("=" * 70)

# 1. 默认模型 (auto)
print("\n1. model=auto, 15s 超时:")
start = time.time()
try:
    s, d = call_chat("说'OK'两个字", model="auto", timeout=15)
    print(f"   HTTP {s} ({time.time()-start:.2f}s)")
    print(f"   {d[:500]}")
except Exception as e:
    print(f"   异常 ({time.time()-start:.2f}s): {e}")

# 2. 显式 deepseek
print("\n2. model=deepseek-chat, 15s 超时:")
start = time.time()
try:
    s, d = call_chat("说'OK'两个字", model="deepseek-chat", timeout=15)
    print(f"   HTTP {s} ({time.time()-start:.2f}s)")
    print(f"   {d[:500]}")
except Exception as e:
    print(f"   异常 ({time.time()-start:.2f}s): {e}")

# 3. agnes 模型
print("\n3. model=agnes-2.0-flash, 15s 超时:")
start = time.time()
try:
    s, d = call_chat("说'OK'两个字", model="agnes-2.0-flash", timeout=15)
    print(f"   HTTP {s} ({time.time()-start:.2f}s)")
    print(f"   {d[:500]}")
except Exception as e:
    print(f"   异常 ({time.time()-start:.2f}s): {e}")

print()
print("=" * 70)
