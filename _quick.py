"""简单验证"""
import json, urllib.request
r = urllib.request.urlopen("http://127.0.0.1:8423/api/health", timeout=5)
d = json.loads(r.read().decode())
print(f"BACKEND={d['status']}")

r2 = urllib.request.urlopen("http://127.0.0.1:8423/api/models", timeout=5)
d2 = json.loads(r2.read().decode())
print(f"MODEL={d2['recommended_model']}")

req = urllib.request.Request(
    "http://127.0.0.1:8423/api/chat",
    data=json.dumps({"message": "你好", "model": "auto"}).encode(),
    headers={"Content-Type": "application/json"}, method="POST",
)
r3 = urllib.request.urlopen(req, timeout=60)
resp = json.loads(r3.read().decode())
reply = resp.get("reply", "")
print(f"ROUNDS={'OK-no5' if '第 1/5 轮' not in reply else 'OLD5'}")
print(f"REPORT={'OK' if '报告' in reply or '📋' in reply else 'MISSING'}")
print(f"PREVIEW: {reply[:200]}")
print("DONE")
