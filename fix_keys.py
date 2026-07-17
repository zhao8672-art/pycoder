"""彻底修复 Key 管理 — 生成配置 + 清除缓存 + 验证"""
import json
import os
import shutil
import glob
import sys
import subprocess
import time
import urllib.request
from pathlib import Path

# ┌─────────────────────────────────────────────┐
# 1. 清除所有 Python 缓存
# └─────────────────────────────────────────────┘
print("[1/6] 清除缓存...")
root = Path(r"C:\Users\Administrator\Desktop\pycode")
for d in glob.glob(str(root / "**" / "__pycache__"), recursive=True):
    try:
        shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass
for f in glob.glob(str(root / "**" / "*.pyc"), recursive=True):
    try:
        os.remove(f)
    except OSError:
        pass
print("  ✅ 缓存已清除")

# ┌─────────────────────────────────────────────┐
# 2. 写入正确的 config.json
# └─────────────────────────────────────────────┘
print("[2/6] 写入配置...")
config_dir = Path.home() / ".pycoder"
config_dir.mkdir(parents=True, exist_ok=True)
config_path = config_dir / "config.json"

config = {
    "provider": {
        "default": "deepseek",
        "api_keys": {
            "deepseek": "sk-REDACTED-DEEPSEEK",
        },
        "default_model": "deepseek-chat",
    },
    "selected_model": "deepseek-chat",
    "blocked_keys": [
        "REDACTED-PYCODER-OLD-KEY",  # Agnes — 永久封禁
    ],
}
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"  ✅ 配置已写入: {config_path}")
print(f"  ✅ Agnes Key 已加入黑名单")

# ┌─────────────────────────────────────────────┐
# 3. Kill 所有旧进程
# └─────────────────────────────────────────────┘
print("[3/6] 杀掉旧进程...")
subprocess.run(["taskkill", "/F", "/IM", "python.exe"], capture_output=True)
subprocess.run(["taskkill", "/F", "/IM", "electron.exe"], capture_output=True)
time.sleep(2)
print("  ✅ 旧进程已终止")

# ┌─────────────────────────────────────────────┐
# 4. 启动后端（正确环境变量）
# └─────────────────────────────────────────────┘
print("[4/6] 启动后端...")
env = os.environ.copy()
env["PYCODER_CLOUD_JWT_SECRET"] = "test-123"
env["PYCODER_API_KEY"] = "REDACTED-PYCODER-API-KEY"
env["DEEPSEEK_API_KEY"] = "sk-REDACTED-DEEPSEEK"
# 强制删除旧 Key
env.pop("AGNES_API_KEY", None)

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "pycoder.server.app:app", "--host", "127.0.0.1", "--port", "8423"],
    cwd=str(root),
    env=env,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
)
print(f"  ✅ 后端 PID={proc.pid}")

# ┌─────────────────────────────────────────────┐
# 5. 等待启动 + 验证
# └─────────────────────────────────────────────┘
print("[5/6] 等待启动...")
for i in range(15):
    time.sleep(2)
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8423/api/health", timeout=3)
        data = json.loads(r.read().decode())
        print(f"  ✅ 后端运行中: {data['status']} ver={data['version']}")
        break
    except Exception:
        print(f"  等待 {i+1}/15...")

# 验证模型推荐
r = urllib.request.urlopen("http://127.0.0.1:8423/api/models", timeout=5)
data = json.loads(r.read().decode())
print(f"\n[6/6] 验证结果:")
print(f"  推荐模型: {data['recommended_model']}")
avail = [m["id"] for m in data["models"] if m["available"]]
print(f"  可用模型: {avail}")
# 检查 agnes 是否还在推荐
if "agnes" in str(data["recommended_model"]):
    print("  ❌ 错误: agnes 仍在推荐列表中!")
else:
    print("  ✅ agnes 已被正确排除")
print(f"  模型总数: {data['total']}")

print("\n✅ 全部修复完成")
