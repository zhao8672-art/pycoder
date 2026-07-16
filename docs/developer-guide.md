# PyCoder 开发者指南

> 版本: 1.0 | 更新时间: 2026-07-16 | 目标读者: PyCoder 贡献者与扩展开发者

---

## 1. 项目概述

PyCoder 是一个基于 Clean Architecture 的全栈自主软件工程 Agent 平台，集成了 AI 大脑、能力总线、安全沙箱、记忆系统和多平台消息网关。

### 1.1 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 运行时 | Python 3.12+ | 推荐 3.14 |
| Web 框架 | FastAPI 0.135+ | 异步 REST API |
| 实时通信 | WebSocket (websockets 16.0) | 双向流式通信 |
| AI 推理 | LiteLLM 1.82+ | 多模型统一调用 |
| 数据存储 | SQLAlchemy 2.0 + SQLite | ORM + 持久化 |
| 向量记忆 | ChromaDB | 深度记忆系统 |
| 容器隔离 | Docker SDK | 沙箱执行 |
| 前端 | Electron + React + TypeScript | 桌面应用 |
| 包管理 | pip + setuptools | 依赖管理 |

### 1.2 项目结构

```
pycode/
├── pycoder/                     # 核心 Python 包
│   ├── brain/                   # AI 大脑核心
│   │   ├── consciousness.py     # 意识引擎 (ReAct 循环)
│   │   ├── task_planner.py      # 任务规划器
│   │   ├── agent_swarm.py       # Agent 集群编排
│   │   ├── dag_scheduler.py     # DAG 并行调度
│   │   ├── memory_engine.py     # 记忆引擎
│   │   └── specialized_agents.py # 专业 Agent 角色
│   ├── bus/                     # V2 能力总线
│   │   ├── registry.py          # 能力注册中心
│   │   ├── router.py            # 能力路由器
│   │   ├── protocol.py          # MCP 协议适配
│   │   ├── mcp_adapter.py       # MCP 标准兼容
│   │   ├── transformer.py       # 数据转换
│   │   └── monitor.py           # 总线监控
│   ├── server/                  # 服务层
│   │   ├── app.py               # FastAPI 应用入口
│   │   ├── routers/             # 路由层 (50+ 路由模块)
│   │   │   ├── chat_routes.py   # 聊天路由
│   │   │   ├── code_exec.py     # 代码执行路由
│   │   │   ├── files.py         # 文件管理路由
│   │   │   ├── git.py           # Git 操作路由
│   │   │   └── v2/              # V2 引擎路由
│   │   ├── services/            # 业务服务层
│   │   │   ├── unified_agent.py # 统一 Agent 入口
│   │   │   ├── agent_react_loop.py # ReAct 循环
│   │   │   ├── autonomous_pipeline.py # 全自主流水线
│   │   │   ├── hallucination_guard.py # 幻觉抑制
│   │   │   ├── docker_sandbox.py # Docker 沙箱
│   │   │   └── team/            # 团队协作服务
│   │   ├── ws_handler.py        # WebSocket 处理器
│   │   └── self_evolution.py    # 自进化引擎
│   ├── gateway/                 # 多平台消息网关
│   │   ├── adapters/            # 平台适配器
│   │   │   ├── telegram.py
│   │   │   ├── discord.py
│   │   │   ├── slack.py
│   │   │   └── cli.py
│   │   ├── message_router.py    # 消息路由器
│   │   └── session_manager.py   # 会话管理
│   ├── safety/                  # 安全模块
│   │   ├── permission.py        # 5 级权限模型
│   │   ├── sandbox.py           # 子进程沙箱
│   │   ├── sandbox_executor.py  # Docker 沙箱执行器
│   │   ├── audit.py             # 审计追踪
│   │   ├── rollback.py          # 回滚管理
│   │   └── circuit_breaker.py   # 熔断器
│   ├── memory/                  # 记忆系统
│   │   ├── session_memory.py    # 会话记忆 (短时)
│   │   └── deep_memory.py       # 深度记忆 (ChromaDB)
│   ├── providers/               # LLM 提供商
│   │   ├── auth.py              # 认证与密钥管理
│   │   ├── registry.py          # 模型注册表
│   │   └── cost.py              # 成本追踪
│   ├── capabilities/            # 能力定义
│   │   ├── editor/              # 编辑器能力
│   │   ├── system/              # 系统能力
│   │   ├── self_evo/            # 自进化能力
│   │   │   └── learning/        # 学习子系统
│   │   └── tools/               # 工具能力
│   ├── extensions/              # 扩展系统
│   ├── skills/                  # 内置技能
│   ├── knowledge/               # 知识库
│   ├── workspace/               # 工作区管理
│   ├── browser/                 # 浏览器自动化
│   ├── lsp/                     # LSP 语言支持
│   ├── config/                  # 配置管理
│   └── core/                    # 核心接口
│       ├── ports/               # 端口接口定义
│       ├── di.py                # 依赖注入容器
│       └── dal.py               # 数据访问层
├── tests/                       # 测试目录
├── docs/                        # 文档
├── config/                      # 配置文件
├── scripts/                     # 工具脚本
├── requirements/                # 依赖声明
├── pyproject.toml               # 项目元数据
└── Dockerfile*                  # Docker 配置
```

---

## 2. 开发环境搭建

### 2.1 前置要求

- Python 3.12+ (推荐 3.14)
- Git
- Docker (可选，用于沙箱执行)
- Node.js 18+ (仅前端开发需要)

### 2.2 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/PyCoder-ai/pycoder.git
cd pycoder

# 2. 创建虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

# 3. 安装依赖
pip install -e .
pip install -r requirements-dev.txt

# 4. 验证安装
python -m pycoder --version

# 5. 启动开发服务器
python -m pycoder
# 服务默认运行在 http://localhost:8420
# API 文档: http://localhost:8420/docs
```

### 2.3 环境变量配置

创建 `.env` 文件：

```bash
# API 认证 (开发环境可设为 disabled)
PYCODER_API_KEY=disabled

# LLM 提供商 API Key
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
AGNES_API_KEY=sk-xxx

# 模型配置
PYCODER_DEFAULT_MODEL=gpt-4o

# 日志级别
PYCODER_LOG_LEVEL=DEBUG

# 数据目录 (默认 ~/.pycoder/)
PYCODER_HOME=/path/to/pycoder-data
```

### 2.4 前端开发 (Electron)

```bash
cd pycoder/electron
npm install
npm run start        # 启动 Electron 应用
npm run dev          # 开发模式 (热重载)
npm run test         # 运行前端测试
```

---

## 3. 架构设计

### 3.1 Clean Architecture 分层

```
┌──────────────────────────────────────────────────┐
│              PRESENTATION LAYER                   │
│  FastAPI Routes + WebSocket + Electron UI        │
├──────────────────────────────────────────────────┤
│              APPLICATION LAYER                    │
│  Services + Use Cases + Agent Orchestrator       │
├──────────────────────────────────────────────────┤
│              DOMAIN LAYER                         │
│  AI Brain (Consciousness, Planner, Swarm)        │
│  V2 Capability Bus (Registry, Router, Protocol)  │
├──────────────────────────────────────────────────┤
│              INFRASTRUCTURE LAYER                 │
│  Safety (Permission, Sandbox, Audit)             │
│  Memory (Session, Deep, Vector)                  │
│  Providers (LLM Auth, Registry, Cost)            │
│  Gateway (Telegram, Discord, Slack, CLI)         │
└──────────────────────────────────────────────────┘
```

### 3.2 核心设计模式

#### 3.2.1 端口-适配器模式

所有外部依赖通过端口接口抽象，具体实现通过适配器注入：

```python
# core/ports/code_sandbox.py — 端口接口
class CodeSandboxPort(ABC):
    @abstractmethod
    async def execute(self, code: str, language: str) -> SandboxResult: ...

# adapters/subprocess_sandbox.py — 子进程适配器
class SubprocessSandbox(CodeSandboxPort):
    async def execute(self, code: str, language: str) -> SandboxResult: ...

# adapters/docker_sandbox.py — Docker 适配器
class DockerSandbox(CodeSandboxPort):
    async def execute(self, code: str, language: str) -> SandboxResult: ...
```

#### 3.2.2 V2 能力总线

所有 AI 能力通过统一的能力总线注册和调用：

```python
from pycoder.bus.registry import capability

@capability(
    id="editor.format_code",
    category="CODE_GENERATION",
    trust_level=TrustLevel.MEDIUM_TRUST,
    timeout=30,
    retries=2,
)
async def format_code(code: str, style: str = "black") -> str:
    """格式化代码"""
    ...
```

#### 3.2.3 ReAct 循环 (Agent 核心)

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  THINK   │ ──▶ │  ACT     │ ──▶ │ OBSERVE  │ ──▶ │ REFLECT  │
│ (推理)   │     │ (执行)   │     │ (观察)   │     │ (反思)   │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
      ▲                                                   │
      └───────────────────────────────────────────────────┘
                        循环直到目标达成
```

### 3.3 数据流

```
用户输入 → Gateway/Router → AI Brain → V2 Capability Bus
    │                              │
    ▼                              ▼
 安全审计 ←────────────────── 沙箱执行
    │                              │
    ▼                              ▼
 记忆持久化 ←────────────── 结果返回
```

---

## 4. 开发指南

### 4.1 添加新的 API 端点

1. 在 `pycoder/server/routers/` 下创建路由模块：

```python
# pycoder/server/routers/my_feature.py
from fastapi import APIRouter

router = APIRouter(prefix="/api/my-feature", tags=["my-feature"])

@router.get("/status")
async def get_status():
    return {"success": True, "status": "ok"}
```

2. 在 `pycoder/server/app.py` 中注册路由：

```python
from pycoder.server.routers.my_feature import router as my_feature_router
app.include_router(my_feature_router)
```

3. 添加认证中间件豁免（如需要）：

```python
# 在 app.py 的认证中间件中添加路径
if request.url.path.startswith("/api/my-feature"):
    # 免认证逻辑
    pass
```

### 4.2 添加新的 V2 能力

```python
# pycoder/capabilities/my_capability.py
from pycoder.bus.registry import capability, TrustLevel, CapabilityCategory

@capability(
    id="my_domain.my_action",
    name="我的能力",
    description="能力描述",
    category=CapabilityCategory.CODE_GENERATION,
    trust_level=TrustLevel.MEDIUM_TRUST,
    timeout=30,
    retries=2,
    schema={
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "参数1"}
        },
        "required": ["param1"]
    }
)
async def my_action(param1: str) -> dict:
    """能力实现"""
    return {"result": param1}
```

### 4.3 添加新的消息平台适配器

```python
# pycoder/gateway/adapters/my_platform.py
from pycoder.gateway import PlatformAdapter

class MyPlatformAdapter(PlatformAdapter):
    platform = "my_platform"

    async def connect(self, config: dict) -> bool:
        """连接平台"""
        ...

    async def disconnect(self) -> None:
        """断开连接"""
        ...

    async def send_message(self, target: str, message: str) -> str:
        """发送消息"""
        ...

    async def listen(self, callback) -> None:
        """监听消息"""
        ...
```

### 4.4 添加新的 Agent 角色

```python
# pycoder/brain/specialized_agents.py 或新建文件
from pycoder.brain.specialized_agents import AgentRole

class MySpecialistAgent(AgentRole):
    name = "my_specialist"
    description = "我的专业 Agent"
    system_prompt = """你是一个专业的..."""

    @property
    def tools(self) -> list[str]:
        return ["editor.format_code", "system.execute_shell"]
```

### 4.5 添加新的记忆层

```python
# pycoder/memory/my_memory.py
from pycoder.memory import MemoryLayer

class MyMemoryLayer(MemoryLayer):
    async def store(self, key: str, value: dict) -> None:
        ...

    async def recall(self, query: str, limit: int = 10) -> list[dict]:
        ...

    async def forget(self, key: str) -> None:
        ...
```

---

## 5. 编码规范

### 5.1 Python 代码风格

- 遵循 **PEP 8**，使用 Black 自动格式化 (line-length=100)
- 所有公共函数/方法必须有**类型注解**
- 注释和文档字符串使用**中文**
- 优先使用 Python 3.10+ 特性 (match/case, `|` 联合类型, walrus `:=`)
- 字符串格式化统一使用 **f-string**
- 使用 `pathlib.Path` 替代 `os.path`
- 使用 `logging` 模块，禁止在生产代码中使用 `print()`

### 5.2 代码格式化

```bash
# 格式化代码
black pycoder/ tests/
# 排序导入
isort pycoder/ tests/
# Lint 检查
ruff check pycoder/ tests/
# 自动修复
ruff check --fix pycoder/ tests/
```

### 5.3 禁止事项

- ❌ 裸 `except:` 吞掉所有异常
- ❌ `from module import *`
- ❌ 函数参数中使用可变默认值 `def f(x=[])`
- ❌ 硬编码文件路径 (使用相对路径或配置)
- ❌ 硬编码敏感信息 (API Key、密码)
- ❌ 同步阻塞调用在 async 路由中

### 5.4 Git 提交规范

```
feat: 新功能
fix: 修复 Bug
docs: 文档更新
refactor: 代码重构
test: 测试相关
chore: 构建/工具变更
```

---

## 6. 测试

### 6.1 运行测试

```bash
# 运行全部测试
pytest

# 运行特定模块测试
pytest tests/test_server_core_modules.py

# 运行并显示覆盖率
pytest --cov=pycoder --cov-report=html

# 仅运行特定标记的测试
pytest -m "not slow"
```

### 6.2 编写测试

```python
# tests/test_my_module.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

class TestMyFeature:
    @pytest.fixture
    def my_service(self, tmp_path):
        """创建测试服务实例"""
        from pycoder.server.services.my_service import MyService
        return MyService(workspace=tmp_path)

    def test_basic_operation(self, my_service):
        """基本操作测试"""
        result = my_service.do_something("input")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_async_operation(self, my_service):
        """异步操作测试"""
        result = await my_service.do_async("input")
        assert result is not None

    def test_error_handling(self, my_service):
        """错误处理测试"""
        with pytest.raises(ValueError, match="Invalid input"):
            my_service.do_something("")
```

### 6.3 测试覆盖率目标

- 整体覆盖率 >= 80%
- 核心模块 (brain, safety, bus) >= 90%
- 关键路径 (chat, code_exec, git) >= 85%

---

## 7. 调试

### 7.1 日志配置

```python
import logging
logger = logging.getLogger(__name__)
logger.debug("调试信息")
logger.info("一般信息")
logger.warning("警告信息")
logger.error("错误信息")
```

### 7.2 VS Code 调试配置

`.vscode/launch.json`:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "PyCoder Server",
            "type": "debugpy",
            "request": "launch",
            "module": "pycoder",
            "args": [],
            "env": {
                "PYCODER_API_KEY": "disabled",
                "PYCODER_LOG_LEVEL": "DEBUG"
            }
        },
        {
            "name": "Pytest Current File",
            "type": "debugpy",
            "request": "launch",
            "module": "pytest",
            "args": ["${file}", "-v", "-s"]
        }
    ]
}
```

---

## 8. 常见问题

### 8.1 启动失败

```bash
# 检查 Python 版本
python --version  # 需要 >= 3.12

# 检查依赖安装
pip list | grep pycoder

# 查看详细日志
python -m pycoder --log-level DEBUG
```

### 8.2 API 认证失败

```bash
# 开发环境关闭认证
set PYCODER_API_KEY=disabled   # Windows
export PYCODER_API_KEY=disabled  # Linux/macOS

# 查看自动生成的 API Key
cat ~/.pycoder/.api_key
```

### 8.3 测试失败

```bash
# 清理缓存
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type d -name ".pytest_cache" -exec rm -rf {} +

# 重新安装依赖
pip install -e . --force-reinstall
pip install -r requirements-dev.txt --force-reinstall

# 重新运行测试
pytest -v --tb=short
```

---

## 9. 贡献流程

1. Fork 仓库并创建功能分支: `git checkout -b feat/my-feature`
2. 编写代码和测试
3. 运行测试和 Lint: `pytest && ruff check pycoder/`
4. 提交代码: `git commit -m "feat: 添加新功能"`
5. 推送并创建 Pull Request: `git push origin feat/my-feature`
6. 等待 Code Review

### 9.1 PR 检查清单

- [ ] 代码通过 Black + isort + ruff 格式化
- [ ] 所有测试通过
- [ ] 新功能有对应的测试覆盖
- [ ] 公共 API 有类型注解和文档字符串
- [ ] 敏感信息不硬编码
- [ ] 安全相关代码经过 Bandit 扫描
- [ ] 异步路由使用 `async def`