# PyCoder 🤖

> Python 开发者原生的 AI 编程 Agent

[![PyPI version](https://img.shields.io/badge/pypi-v0.5.0-blue)](https://pypi.org/project/pycoder/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-5191+-brightgreen)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-≥80%25-brightgreen)](.coveragerc)

**PyCoder** 是一个受 Aider 启发、独立实现的开源 AI 编程助手，专为中国 Python 开发者优化。它提供 Web API 和 Electron 桌面 IDE 两种使用方式，原生支持 DeepSeek、通义千问 (Qwen)、智谱 GLM 等国产大模型。

## ✨ 核心特性一览

- 🤖 **多模型支持** — DeepSeek / 通义千问 / 智谱 GLM / Ollama 本地模型
- 🐍 **Python 生态自动感知** — venv / conda / poetry / pipenv / Django / Flask / FastAPI / PyTorch
- 🔧 **多语言代码执行** — Python / JavaScript / TypeScript / Java / Go / Rust / C / C++ / Bash
- 🧩 **扩展市场** — 多数据源聚合（GitHub / npm / PyPI / Open VSX），支持一键安装
- 🎯 **Skills 市场** — 12 个开源数据源聚合，智能推荐与搜索
- 🔒 **权限策略引擎** — Shell / 文件 / 网络操作分级控制（allow / ask / deny）
- 🧠 **Self-Evolution** — AI 自我进化与能力升级
- 📡 **MCP 协议** — 模型上下文协议支持
- 🔑 **BYOK 模式** — 自带 Key，数据不经过第三方服务器
- 📖 **开源可审计** — Apache 2.0 许可证，代码完全透明

---

## 🚀 快速开始

### pip 安装

```bash
pip install pycoder
```

### 源码安装

```bash
git clone https://github.com/PyCoder-ai/pycoder.git
cd pycoder
pip install -e ".[dev]"
```

### 配置 API Key

支持 **DeepSeek**、**通义千问 (Qwen)**、**智谱 GLM** 等多种国产模型：

```bash
# 方式一：环境变量
export DEEPSEEK_API_KEY=sk-xxxxxxxxxxxx
# 或
export QWEN_API_KEY=sk-xxxxxxxxxxxx
# 或
export GLM_API_KEY=xxxxxxxxxxxx

# 方式二：运行配置向导
python -m pycoder --setup
```

### 启动

```bash
# App Server（FastAPI + WebSocket）
python -m pycoder --server

# 指定模型
python -m pycoder -m deepseek-chat
python -m pycoder -m qwen-coder-plus
python -m pycoder -m glm-4

# Electron 桌面 IDE
cd pycoder/electron
npm install
npm run dev
```

---

## 📊 功能矩阵

### 多模型支持

| 提供方 | 模型 | 输入/输出 ($/M tokens) |
|--------|------|----------------------|
| **DeepSeek** | deepseek-chat, deepseek-coder | .14 / .28 |
| **通义千问** | qwen-coder-plus, qwen-coder-turbo, qwen-max | .15-0.80 / .60-2.00 |
| **智谱 GLM** | glm-4, glm-4-flash, glm-4v-flash | .10 / .10 |
| **Ollama** | 本地模型（支持自定义） | 免费 |

自动 API 地址路由、智能降级、响应缓存。

### 多语言代码执行

| 语言 | 执行 | 编译 | 调试 | 分析 | 测试 |
|------|------|------|------|------|------|
| **Python** | ✅ | — | ✅ pdb | ✅ AST | ✅ pytest |
| **JavaScript** | ✅ | — | 🔜 | 🔜 | 🔜 |
| **TypeScript** | ✅ | — | 🔜 | 🔜 | 🔜 |
| **Java** | ✅ | ✅ javac | 🔜 | 🔜 | 🔜 |
| **Go** | ✅ | — | 🔜 | 🔜 | 🔜 |
| **Rust** | ✅ | ✅ rustc | 🔜 | 🔜 | 🔜 |
| **C** | ✅ | ✅ gcc | 🔜 | 🔜 | 🔜 |
| **C++** | ✅ | ✅ g++ | 🔜 | 🔜 | 🔜 |
| **Bash** | ✅ | — | — | — | — |
| **C#** | ✅ | ✅ mcs | 🔜 | 🔜 | 🔜 |
| **Ruby** | ✅ | — | 🔜 | 🔜 | 🔜 |

> ✅ 已支持 | 🔜 后续迭代

### Python 生态自动感知

- **虚拟环境：** venv / conda / poetry / uv
- **包管理器：** pip / poetry / pdm / pipenv
- **框架检测：** Django / Flask / FastAPI / PyTorch / pandas
- **项目类型：** web / data_science / library
- **Git 仓库信息：** 分支、变更文件

---

## 🏗️ 架构概览

```
┌─────────────────────────────────────────────────┐
│                 Electron 桌面 IDE                 │
│         (React + Monaco Editor + WebSocket)       │
└──────────────────────┬──────────────────────────┘
                       │ HTTP / WebSocket
┌──────────────────────▼──────────────────────────┐
│              FastAPI Server (port 8423)           │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ Chat API │ │ File API │ │ Extension Market │ │
│  └────┬─────┘ └────┬─────┘ └────────┬─────────┘ │
│       │            │                │           │
│  ┌────▼────────────▼────────────────▼─────────┐ │
│  │          AI Agent (Capabilities)           │ │
│  │   Function Calling + MCP Tools + Skills    │ │
│  └────────────────┬───────────────────────────┘ │
│                   │                             │
│  ┌────────────────▼───────────────────────────┐ │
│  │         Code Executor (Sandbox)            │ │
│  │   Python (subprocess) + Multilang (async)  │ │
│  └────────────────────────────────────────────┘ │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│           AI 模型提供方 (BYOK)                   │
│  DeepSeek / Qwen / GLM / Ollama / OpenAI        │
└─────────────────────────────────────────────────┘
```

---

## 📦 安装方式

### PyPI 安装（推荐）

```bash
pip install pycoder
```

### 源码安装（开发）

```bash
git clone https://github.com/PyCoder-ai/pycoder.git
cd pycoder
pip install -e ".[dev]"
```

### Electron 桌面 IDE

```bash
cd pycoder/electron
npm install
npm run dev          # 开发模式
# 或
npm run dev:hot     # 热重载模式
```

---

## ⚙️ 配置

### 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| DEEPSEEK_API_KEY | DeepSeek API Key | sk-xxx |
| QWEN_API_KEY | 通义千问 API Key | sk-xxx |
| GLM_API_KEY | 智谱 GLM API Key | xxx |
| PYCODER_MODEL | 默认模型 | deepseek-chat |
| PYCODER_SERVER_PORT | Server 端口 | 8423 |
| PYCODER_API_KEY | API 认证密钥（设为 `disabled` 关闭认证） | disabled |
| PYCODER_WORKSPACE | 工作区根目录 | /path/to/project |

### 配置文件

位置：`~/.pycoder/config.json`

```json
{
  "api_keys": {
    "deepseek": "sk-xxxxxxxxxxxx",
    "qwen": "sk-xxxxxxxxxxxx",
    "glm": "xxxxxxxxxxxx"
  },
  "default_model": "deepseek-chat",
  "theme": "tokyo_night",
  "budget": {
    "max_tokens_per_session": 100000,
    "daily_budget_usd": 5.0
  }
}
```

---

## 🔧 命令行命令

| 参数 | 功能 |
|------|------|
| `--server` | 启动 App Server |
| `--server-port PORT` | Server 端口（默认 8423） |
| `--model, -m` | 指定 AI 模型 |
| `--setup` | 运行配置向导 |
| `--env` | 显示环境信息 |
| `--cost` | 显示费用报告 |
| `--version, -V` | 显示版本号 |

---

## 🏗️ 项目结构

```
pycoder/
├── pycoder/                  # 主源代码
│   ├── __init__.py           # 版本号
│   ├── __main__.py           # CLI 入口
│   ├── server/               # FastAPI + WebSocket
│   │   ├── app.py            # 服务主入口
│   │   ├── routers/          # API 路由 (40+ 模块)
│   │   ├── capabilities.py   # AI 工具调用 (Function Calling)
│   │   ├── chat_bridge.py    # OpenAI Function Calling 桥接
│   │   └── mcp_tools.py      # MCP 工具注册
│   ├── providers/            # AI 模型提供方
│   │   ├── deepseek.py       # DeepSeek 适配
│   │   ├── qwen.py           # 通义千问适配
│   │   ├── glm.py            # 智谱 GLM 适配
│   │   └── ollama_client.py  # Ollama 适配
│   ├── python/               # 代码执行与分析
│   │   ├── code_executor.py  # Python 沙箱执行
│   │   ├── multilang_executor.py  # 多语言执行
│   │   └── env_detector.py   # 环境检测
│   ├── extensions/           # 扩展市场
│   │   ├── marketplace.py    # 多源聚合引擎
│   │   └── manager.py        # 安装/管理
│   ├── electron/             # Electron 桌面 IDE
│   │   └── src/              # React + Monaco
│   └── prompts/              # Agent 提示词
├── tests/                    # 测试套件 (5191+ tests)
├── docs/                     # 文档
├── scripts/                  # 工具脚本
└── pyproject.toml            # 项目元数据
```

---

## 📡 API 文档

启动 Server 后访问交互式文档（默认需在请求头携带 `X-API-Key`，或设置 `PYCODER_API_KEY=disabled` 关闭认证）：

- **Swagger UI**: <http://127.0.0.1:8423/docs>
- **ReDoc**: <http://127.0.0.1:8423/redoc>
- **OpenAPI JSON**: <http://127.0.0.1:8423/openapi.json>

核心 API 端点（565+ routes）：

| 类别 | 端点 | 说明 |
| ---- | ---- | ---- |
| 健康检查 | `GET /api/health` | 服务状态 + 版本 |
| 聊天 | `WS /ws/chat` | AI 对话 WebSocket |
| 终端 | `WS /ws/terminal` | 终端交互 WebSocket |
| 文件操作 | `GET/POST /api/files/*` | 文件读写 |
| 代码执行 | `POST /api/code/exec` | Python 沙箱执行 |
| 多语言执行 | `POST /api/code/exec-multilang` | Java/Go/Rust/C++ 执行 |
| 扩展市场 | `GET /api/extensions/search` | 扩展搜索 |
| Skills 市场 | `GET /api/skills/v2/search` | Skills 搜索 |
| 权限策略 | `GET/POST /api/permissions` | 权限控制 |
| Git | `GET /api/git/*` | Git 状态/分支/差异 |
| 进化 | `WS /ws/evolution` | 自我进化监控 |

---

## 🧩 高级功能

### 扩展市场

多数据源智能聚合引擎，从 GitHub / npm / PyPI / Open VSX 等 9 个源并行拉取，stale-while-revalidate 缓存策略保证响应速度。

```bash
# 搜索扩展
curl http://localhost:8423/api/extensions/search?q=git

# 安装扩展（支持 GitHub / npm / PyPI / Open VSX）
curl -X POST http://localhost:8423/api/extensions/install \
  -H "Content-Type: application/json" \
  -d '{"id": "pycoder.gitlens"}'
```

### Skills 市场

12 个开源数据源聚合（GitHub Awesome Lists / Hugging Face / MCP Servers 等），质量评分排序，种子数据兜底。

### Self-Evolution

AI 自我进化系统，支持能力升级、配置自适应、完整回滚链。

### MCP 协议

完整实现 Model Context Protocol，支持工具注册、调用、健康追踪。

---

## 🤝 贡献指南

欢迎贡献！请查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解详情。

**开发环境搭建：**

```bash
git clone https://github.com/PyCoder-ai/pycoder.git
cd pycoder
pip install -e ".[dev]"

# 运行测试（含覆盖率）
scripts/test.bat          # Windows
# 或
scripts/test.sh           # Linux/macOS

# 代码格式化
python -m black pycoder/ && python -m isort pycoder/

# 类型检查
python -m mypy pycoder/ --ignore-missing-imports
```

**提交规范：** `feat:` / `fix:` / `docs:` / `test:` / `refactor:` / `chore:`

**分支策略：** `master`（稳定） + `feat/xxx`（功能） + `fix/xxx`（修复）

**测试要求：** 覆盖率 ≥ 80%，新功能必须附带测试

---

## 📄 许可证

Apache 2.0 License © 2026 PyCoder Team — 受 [Aider](https://github.com/Aider-AI/aider) 启发、独立实现。

## 🙏 致谢

- [Aider](https://aider.chat/) — AI Pair Programming in Your Terminal
- [FastAPI](https://fastapi.tiangolo.com/) — Modern Web Framework
- [Monaco Editor](https://microsoft.github.io/monaco-editor/) — VS Code Editor
- DeepSeek / 通义千问 / 智谱 GLM — 中国 AI 模型提供方
