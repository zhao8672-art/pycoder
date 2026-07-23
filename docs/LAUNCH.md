# PyCoder 启动指南

> 跨平台启动 PyCoder 后端 + Electron 桌面前端

## 一键启动（推荐）

### Python 跨平台启动器（所有平台通用）

```bash
# 仅启动后端
python _launch.py

# 启动后端 + Electron 桌面 IDE
python _launch.py --desktop
```

`_launch.py` 特性：
- ✅ 自动加载 `~/.pycoder/config.json` 中的 API Key
- ✅ 自动设置 `PYCODER_API_KEY` 等环境变量
- ✅ 杀死旧 python.exe/electron.exe 进程
- ✅ 清理 `__pycache__` 与临时文件
- ✅ 等待后端就绪（最多 40 秒）
- ✅ 跨平台（Windows / macOS / Linux）

### Windows 原生批处理（start_backend.bat）

```bat
:: 双击或在 cmd 中运行
start_backend.bat
```

适用场景：双击启动后端、不需要前端时。

### macOS / Linux 启动（start_backend.sh）

```bash
chmod +x start_backend.sh
./start_backend.sh
```

## 手动启动（高级用户）

### 后端

```bash
# 1. 设置环境变量
export PYCODER_CLOUD_JWT_SECRET="local-dev-jwt-2026"
export PYCODER_API_KEY="your-key"
# Windows PowerShell:
# $env:PYCODER_CLOUD_JWT_SECRET="local-dev-jwt-2026"
# $env:PYCODER_API_KEY="your-key"

# 2. 启动
python -m uvicorn pycoder.server.app:app --host 127.0.0.1 --port 8423
```

### 前端 (Electron 桌面 IDE)

```bash
cd pycoder/electron
npm install   # 首次启动
npm run dev   # 开发模式
# 或
npx electron .   # 生产模式
```

## 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `PYCODER_API_KEY` | ✅ | API 认证密钥（默认模式） |
| `PYCODER_CLOUD_JWT_SECRET` | ⚠️ 推荐 | JWT 签名密钥（生产环境） |
| `DEEPSEEK_API_KEY` | ⚠️ 视模型 | DeepSeek 模型 Key |
| `QWEN_API_KEY` / `DASHSCOPE_API_KEY` | ⚠️ 视模型 | 通义千问 Key |
| `GLM_API_KEY` | ⚠️ 视模型 | 智谱 GLM Key |
| `SKIP_EMBEDDED_BACKEND` | 桌面端 | 设为 `1` 跳过 Electron 内嵌后端 |
| `PYCODER_GIT_REMOTE` | 可选 | post-commit 钩子推送的远程名（默认 `origin`） |

## Git 钩子安装

项目根 `.git-hooks/` 目录提供 post-commit 自动推送钩子。

### Linux / macOS

```bash
./.git-hooks/install-post-commit.sh
```

### Windows PowerShell

```powershell
.\.git-hooks\install-post-commit.ps1
```

### 手动安装

```bash
cp .git-hooks/post-commit .git/hooks/post-commit
chmod +x .git/hooks/post-commit
```

## 端口

| 端口 | 服务 |
|------|------|
| 8423 | PyCoder App Server (FastAPI + WebSocket) |
| 5173 | Electron 开发模式 (Vite dev server) |

## 故障排除

### 端口被占用

```bash
# Windows
netstat -ano | findstr :8423
taskkill /F /PID <pid>

# macOS / Linux
lsof -i :8423
kill -9 <pid>
```

### Electron 启动失败（缓存锁定）

```bash
python _cleanup_electron_cache.py
```

### 后端启动慢 / 卡住

检查 `~/.pycoder/` 目录权限，确保可写。删除 `backend.log` 后重试。

### 测试 0 全部失败

- 确认 Python ≥ 3.12 (`python --version`)
- 重新安装依赖: `pip install -e ".[dev]"`
- 清理缓存: `find . -type d -name __pycache__ -exec rm -rf {} +`
