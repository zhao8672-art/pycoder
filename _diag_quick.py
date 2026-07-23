"""紧凑版 AI 调用诊断."""
import http.client, json, time, sys

sys.stdout.reconfigure(encoding="utf-8")
API_KEY = "REDACTED-PYCODER-API-KEY"

def call(model, timeout=12):
    conn = http.client.HTTPConnection("127.0.0.1", 8423, timeout=timeout)
    body = json.dumps({"message": "OK", "model": model, "stream": False})
    conn.request("POST", "/api/chat", body=body,
                 headers={"X-API-Key": API_KEY, "Content-Type": "application/json"})
    r = conn.getresponse()
    data = r.read().decode("utf-8", errors="replace")
    conn.close()
    return r.status, data

for m in ["auto", "deepseek-chat", "agnes-2.0-flash"]:
    print(f"\n=== model={m} ===", flush=True)
    t0 = time.time()
    try:
        s, d = call(m, timeout=12)
        print(f"HTTP {s} ({time.time()-t0:.2f}s): {d[:400]}", flush=True)
    except Exception as e:
        print(f"EXC ({time.time()-t0:.2f}s): {e}", flush=True)
