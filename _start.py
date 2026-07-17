"""重启后端"""
import subprocess, sys, time, urllib.request, json, os

print("Killing old processes...")
subprocess.run(["taskkill", "/F", "/FI", "PID ge 1", "/FI", "IMAGENAME eq python.exe"],
               capture_output=True)
time.sleep(3)

print("Starting backend...")
env = {**os.environ,
    "PYCODER_CLOUD_JWT_SECRET": "test-123",
    "PYCODER_API_KEY": "REDACTED-PYCODER-API-KEY",
    "DEEPSEEK_API_KEY": "sk-REDACTED-DEEPSEEK",
    "AGNES_API_KEY": "sk-REDACTED-AGNES",
}
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "pycoder.server.app:app",
     "--host", "127.0.0.1", "--port", "8423"],
    cwd=r"C:\Users\Administrator\Desktop\pycode", env=env,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
)
print(f"Backend PID={proc.pid}")

for i in range(15):
    time.sleep(2)
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8423/api/health", timeout=3)
        d = json.loads(r.read().decode())
        print(f"UP: {d['status']} v{d['version']}")
        break
    except Exception:
        print(f"w{i+1}/15...")

print(f"Done. PID={proc.pid}")
