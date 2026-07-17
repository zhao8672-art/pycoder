"""重启并验证升级"""
import subprocess, sys, time, urllib.request, json, os

subprocess.run(["taskkill", "/F", "/IM", "python.exe"], capture_output=True)
time.sleep(2)

env = {**os.environ}
env["PYCODER_CLOUD_JWT_SECRET"] = "test-123"
env["PYCODER_API_KEY"] = "REDACTED-PYCODER-API-KEY"
env["DEEPSEEK_API_KEY"] = "sk-REDACTED-DEEPSEEK"

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "pycoder.server.app:app", "--host", "127.0.0.1", "--port", "8423"],
    cwd=r"C:\Users\Administrator\Desktop\pycode",
    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
)
print(f"PID={proc.pid}")
for i in range(15):
    time.sleep(2)
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8423/api/health", timeout=3)
        print(f"UP: {json.loads(r.read().decode())['status']}")
        break
    except Exception:
        print(f"w{i+1}...")

# Test
req = urllib.request.Request(
    "http://127.0.0.1:8423/api/chat",
    data=json.dumps({"message": "创建一个hello.txt文件", "model": "auto"}).encode(),
    headers={"Content-Type": "application/json"}, method="POST",
)
try:
    r = urllib.request.urlopen(req, timeout=120)
    resp = json.loads(r.read().decode())
    reply = resp.get("reply", "")
    print(f"Report={'OK' if ('报告' in reply or '📋' in reply or '📌' in reply) else 'MISSING'}")
    print(f"Tools={'OK' if ('file_write' in reply.lower() or 'write_file' in reply.lower()) else 'MISSING'}")
    print(f"Preview: {reply[:300]}")
except Exception as e:
    print(f"Err: {e}")
print("DONE")
