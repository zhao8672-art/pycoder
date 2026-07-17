"""重启后端脚本 - 修复 AI 优先级后重启服务"""
import os
import subprocess
import sys
import time

# 只杀掉端口 8423 上的进程（不杀 Python 自身）
os.system("netstat -ano | findstr :8423 > %temp%\\port8423.txt 2>nul")
time.sleep(0.5)
try:
    with open(os.environ["TEMP"] + "\\port8423.txt") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 5 and parts[4] != "0":
                pid = parts[4]
                os.system(f"taskkill /F /PID {pid} 2>nul")
except:
    pass
time.sleep(2)

# 启动新的后端
env = os.environ.copy()
env["PYCODER_CLOUD_JWT_SECRET"] = "test-secret-12345"
env["PYCODER_API_KEY"] = "REDACTED-PYCODER-API-KEY"
env["DEEPSEEK_API_KEY"] = "sk-REDACTED-DEEPSEEK"
env["AGNES_API_KEY"] = "REDACTED-PYCODER-OLD-KEY"

cmd = [
    sys.executable, "-m", "uvicorn",
    "pycoder.server.app:app",
    "--host", "127.0.0.1",
    "--port", "8423",
]

proc = subprocess.Popen(
    cmd,
    cwd=r"C:\Users\Administrator\Desktop\pycode",
    env=env,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
)

print(f"Backend started: PID={proc.pid}")
print("Waiting 10s for startup...")
time.sleep(10)

# 验证
import urllib.request
try:
    r = urllib.request.urlopen("http://127.0.0.1:8423/api/health", timeout=5)
    data = r.read().decode()
    print(f"HEALTH: {data}")
except Exception as e:
    print(f"FAILED: {e}")
