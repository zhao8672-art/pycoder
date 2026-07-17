"""PyCoder 一键启动脚本 — 自动加载Key + 验证 + 双选启动
使用方法:
  python _launch.py              # 仅启动后端
  python _launch.py --desktop    # 启动后端 + Electron前端
"""
import json, os, sys, subprocess, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG = Path.home() / ".pycoder" / "config.json"

# ┌─────────────────────────────────────────────┐
# 1. 确保 config.json 存在并加载 Key
# └─────────────────────────────────────────────┘
print("⚙  加载模型配置...")
CONFIG.parent.mkdir(parents=True, exist_ok=True)
if not CONFIG.exists():
    print("    未找到 config.json，创建默认配置...")
    CONFIG.write_text(json.dumps({
        "provider": {
            "default": "deepseek",
            "api_keys": {},
            "default_model": "deepseek-chat",
        },
        "selected_model": "",
        "blocked_keys": [],
    }, indent=2, ensure_ascii=False), encoding="utf-8")

cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
keys = cfg.get("provider", {}).get("api_keys", {})
print(f"    已加载 {len(keys)} 个 Key: {list(keys.keys())}")

# ┌─────────────────────────────────────────────┐
# 2. 设置环境变量
# └─────────────────────────────────────────────┘
env = os.environ.copy()
env["PYCODER_CLOUD_JWT_SECRET"] = env.get("PYCODER_CLOUD_JWT_SECRET", "local-dev-jwt-2026")
env["PYCODER_API_KEY"] = env.get("PYCODER_API_KEY", "REDACTED-PYCODER-API-KEY")

# 从 config 同步 Key 到环境变量
KEY_MAP = {
    "deepseek": "DEEPSEEK_API_KEY",
    "agnes": "AGNES_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "glm": "GLM_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
}
for provider, api_key in keys.items():
    if provider in KEY_MAP:
        env[KEY_MAP[provider]] = api_key

# ┌─────────────────────────────────────────────┐
# 3. Kill 旧进程
# └─────────────────────────────────────────────┘
print("⚡ 停止旧进程...")
subprocess.run(["taskkill", "/F", "/IM", "python.exe"], capture_output=True)
subprocess.run(["taskkill", "/F", "/IM", "electron.exe"], capture_output=True)
time.sleep(3)

# ┌─────────────────────────────────────────────┐
# 4. 清除缓存
# └─────────────────────────────────────────────┘
print("🗑  清除缓存...")
import glob, shutil
for d in glob.glob(str(ROOT / "**" / "__pycache__"), recursive=True):
    shutil.rmtree(d, ignore_errors=True)
for f in glob.glob(str(ROOT / "**" / "*.pyc"), recursive=True):
    try: os.remove(f)
    except: pass

# ┌─────────────────────────────────────────────┐
# 5. 启动后端
# └─────────────────────────────────────────────┘
print("🚀 启动后端...")
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "pycoder.server.app:app",
     "--host", "127.0.0.1", "--port", "8423", "--log-level", "error"],
    cwd=str(ROOT), env=env,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
)
print(f"    后端 PID={proc.pid}")

# ┌─────────────────────────────────────────────┐
# 6. 等待就绪并验证
# └─────────────────────────────────────────────┘
print("⏳ 等待后端就绪...")
for i in range(20):
    time.sleep(2)
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8423/api/config/status", timeout=5)
        status = json.loads(r.read().decode())
        print(f"    ✅ 后端就绪 (v0.5.0)")
        print(f"    模型: {status['recommended_model']}")
        print(f"    已配置 Key: {[p['id'] for p in status['providers'] if p['has_key']]}")
        break
    except Exception:
        if i < 19:
            print(f"    等待 {i+1}/20...")

# ┌─────────────────────────────────────────────┐
# 7. 启动前端（可选）
# └─────────────────────────────────────────────┘
if "--desktop" in sys.argv:
    print("🖥  启动前端...")
    subprocess.Popen(
        ["powershell", "-NoExit", "-Command",
         f"cd '{ROOT / 'pycoder' / 'electron'}'; "
         "$env:SKIP_EMBEDDED_BACKEND='1'; npx electron ."],
        cwd=str(ROOT / "pycoder" / "electron"),
    )
    print("    Electron 已启动")

print(f"\n✅ 启动完成")
print(f"   API:  http://127.0.0.1:8423")
print(f"   配置: {CONFIG}")
