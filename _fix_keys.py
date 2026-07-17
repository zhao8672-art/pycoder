"""更新 Agnes Key：保存新Key + 移除旧黑名单 + 验证"""
import json, urllib.request, os, sys, subprocess, time
from pathlib import Path

HOST = "http://127.0.0.1:8423"
NEW = "sk-REDACTED-AGNES"
OLD = "REDACTED-PYCODER-OLD-KEY"

def post(url, data):
    req = urllib.request.Request(url, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

print("1. 从黑名单移除旧Key + 保存新Key")
cfg = Path.home() / ".pycoder" / "config.json"
c = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else {}
if "blocked_keys" in c and OLD in c["blocked_keys"]:
    c["blocked_keys"].remove(OLD)
    print("  ✅ 移除旧黑名单")
c.setdefault("provider", {}).setdefault("api_keys", {})["agnes"] = NEW
cfg.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
print("  ✅ 保存新Key")

print("\n2. 重启后端")
subprocess.run(["taskkill", "/F", "/PID", "62576"], capture_output=True)
time.sleep(2)
env = {**os.environ, "PYCODER_CLOUD_JWT_SECRET": "test-123",
       "PYCODER_API_KEY": "REDACTED-PYCODER-API-KEY",
       "DEEPSEEK_API_KEY": "sk-REDACTED-DEEPSEEK",
       "AGNES_API_KEY": NEW}
proc = subprocess.Popen([sys.executable, "-m", "uvicorn",
    "pycoder.server.app:app", "--host", "127.0.0.1", "--port", "8423"],
    cwd=r"C:\Users\Administrator\Desktop\pycode", env=env,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
print(f"  PID={proc.pid}")
for i in range(15):
    time.sleep(2)
    try:
        urllib.request.urlopen(f"{HOST}/api/health", timeout=3)
        print("  ✅ 后端已启动")
        break
    except:
        print(f"  等待 {i+1}/15...")

print("\n3. 验证")
r = urllib.request.urlopen(f"{HOST}/api/models", timeout=5)
d = json.loads(r.read().decode())
print(f"  推荐: {d['recommended_model']}")
avail = [m["id"] for m in d["models"] if m["available"]]
print(f"  可用: {avail}")

print("\n  DeepSeek:", end=" ")
r = post(f"{HOST}/api/chat", {"message": "回复'你好'", "model": "deepseek-chat"})
print("✅" if r.get("reply") else "❌")

print("  Agnes:", end=" ")
r = post(f"{HOST}/api/chat", {"message": "回复'你好'", "model": "agnes-2.0-flash"})
reply = r.get("reply", "")
if "401" not in reply and "降级" not in reply:
    print(f"✅ 新Key有效 - {reply[:100]}")
else:
    print(f"❌ {reply[:120]}")
print("\n完成")
