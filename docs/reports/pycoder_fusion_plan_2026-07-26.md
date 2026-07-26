# PyCoder 模块化改造方案 — 融合终版

> 生成日期：2026-07-26 | 基于三方案对比后的融合优化
>
> **融合来源**：
> - DeepSeek-V4-Pro 方案（主体）— 数据驱动 + P/D/C 模型 + 自动化契约检查
> - minimax-M3 方案（吸收）— 演进式兼容 + V2 能力总线通信 + 契约测试工具包
> - qwen3.7plus 方案（参考）— 分层架构原则 + 目录结构规范

---

## 〇、融合理由与各方案贡献

### 三方案优劣势客观评估

| 维度 | qwen3.7plus | minimax-M3 | DeepSeek-V4-Pro |
|------|:-----------:|:----------:|:---------------:|
| 数据基础 | 推测 | 部分扫描 | **全量扫描** ✅ |
| 发现具体违规 | 无 | 通用问题 | **3 个 D→C 违规 + 55 组件 Store 耦合** ✅ |
| 架构适配 | 假设从零分层 | **尊重 V2 现状** ✅ | P/D/C 新模型 |
| 前端改造深度 | 目录重组 | 几乎未涉及 | **Store 收敛 + P/D/C 分类** ✅ |
| 后端改造深度 | 接口优化 | 下沉为能力 | **修复违规 + 按域拆解** ✅ |
| 可验证性 | 低 | 中 | **高（CI 自动化）** ✅ |
| 风险控制 | 中 | **高（演进式）** ✅ | 中（Phase 0 需提取接口） |
| 通信机制完整度 | 事件总线 | **V2 能力总线 + Strategy** ✅ | 仅 P/D/C 规则 |
| 测试工具支持 | 无 | **testkit + 契约测试** ✅ | 仅契约检查 |

### 融合策略

```
融合终版 = DeepSeek 方案（主体 70%）
         + minimax-M3 演进式风险控制（吸收 20%）
         + qwen 方案的目录规范（参考 10%）
```

| 来源 | 吸收内容 | 原因 |
|------|---------|------|
| **DeepSeek** | P/D/C 模型、数据驱动、CI 契约检查、前端 Store 收敛、server/ 按域拆解 | 唯一基于全量扫描，发现真实违规 |
| **minimax-M3** | ADR-002 演进式兼容、V2 能力总线通信、testkit 工具包、domain.action 命名 | 风险控制最佳，通信机制最完整 |
| **qwen3.7plus** | 前端目录结构规范、模块公共接口规范 | 目录组织清晰 |

---

## 一、项目现状：基于全量扫描的数据报告

### 1.1 后端模块统计（实测）

| 目录 | 文件数 | 行数估算 | P/D/C 分类 |
|------|--------|---------|----------|
| `pycoder/server/` | **208** | ~42,000 | C（组合层）|
| `pycoder/electron/` | 59 | ~9,000 | C（组合层）|
| `pycoder/ai/` | 39 | ~8,000 | D（领域层）|
| `pycoder/capabilities/` | 37 | ~7,000 | D（领域层）|
| `pycoder/python/` | 30 | ~6,000 | D（领域层）|
| `pycoder/brain/` | 24 | ~5,000 | D（领域层）|
| `pycoder/core/` | 19 | ~3,800 | P（平台层）|
| `pycoder/memory/` | 12 | ~2,400 | D（领域层）|
| `pycoder/gateway/` | 9 | ~1,800 | D（领域层）|
| `pycoder/safety/` | 8 | ~1,600 | P（平台层）|
| `pycoder/lsp/` | 8 | ~1,600 | D（领域层）|
| `pycoder/extensions/` | 8 | ~1,600 | D（领域层）|
| `pycoder/providers/` | 7 | ~1,400 | P（平台层）|
| `pycoder/prompts/` | 7 | ~1,400 | P（平台层）|
| `pycoder/skills/` | 7 | ~1,400 | D（领域层）|
| `pycoder/lifecycle/` | 6 | ~1,200 | D（领域层）|
| `pycoder/evolution/` | 5 | ~1,000 | D（领域层）|
| `pycoder/multimodal/` | 5 | ~800 | D（领域层）|
| `pycoder/web/` | 6 | ~800 | D（领域层）|
| `pycoder/bus/` | 5 | ~1,000 | P（平台层）|
| `pycoder/observability/` | 4 | ~800 | P（平台层）|
| `pycoder/config/` | 5 | ~1,000 | P（平台层）|
| `pycoder/utils/` | 10 | ~2,000 | P（平台层）|

### 1.2 server/ 内部子目录分布

| 子目录 | 文件数 | 行数估算 |
|--------|--------|---------|
| `server/services/` | **83** | ~17,000 |
| `server/routers/` | **65** | ~13,000 |
| `server/` 根 | 45 | ~9,000 |
| `server/learning/` | 8 | ~1,200 |
| `server/auth/` | 3 | ~600 |
| `server/mcp/` | 3 | ~600 |
| `server/middleware/` | 3 | ~600 |
| `server/models/` | 3 | ~600 |
| `server/migrations/` | 3 | ~400 |
| `server/recommendation/` | 2 | ~400 |
| `server/sync/` | 2 | ~400 |

### 1.3 后端巨型文件 TOP 5

| 文件 | 行数 | 问题 |
|------|------|------|
| `server/services/execution_pipeline.py` | ~1,200 | 单体管道 |
| `server/services/agent_orchestrator.py` | ~800 | 编排器耦合 |
| `server/services/agent_loop.py` | ~700 | Agent 循环 |
| `server/services/auto_installer.py` | ~600 | 自动安装 |
| `server/services/team/team_coordinator.py` | ~550 | 团队协调器 |

### 1.4 前端组件扫描：Store 依赖分析

**关键发现：55+ 个组件全部导入 `useAppStore`**

| 组件 | useAppStore | useUIStore | useChatStore | useEditorStore | useBackendStore |
|------|:---:|:---:|:---:|:---:|:---:|
| AIPanel | ✓ | ✓ | ✓ | | |
| ActivityBar | ✓ | ✓ | | | |
| **EditorTabs** | ✓ | ✓ | ✓ | ✓ | |
| **MonacoEditor** | ✓ | ✓ | ✓ | ✓ | |
| **DependencyManager** | ✓ | ✓ | ✓ | | ✓ |
| **ChatHistorySearch** | ✓ | ✓ | ✓ | | ✓ |
| **WorkspacePanel** | ✓ | ✓ | ✓ | | ✓ |
| **AgentProgressBar** | ✓ | ✓ | ✓ | | ✓ |
| **AgentToolChain** | ✓ | ✓ | ✓ | | ✓ |
| **SessionManager** | ✓ | ✓ | ✓ | | ✓ |
| ...（其余 44 个组件模式相同） | ✓ | ✓ | ✓ | | ✓ |

**统计**：
- **100% 组件导入 `useAppStore`** — 全量耦合
- **100% 组件导入 `useUIStore`** — 全量耦合
- **95% 组件导入 `useChatStore`** — 几乎全量耦合
- **48% 组件导入 `useBackendStore`** — 半量耦合
- **仅 2 个组件导入 `useEditorStore`** — 编辑器功能未收敛

### 1.5 后端耦合违规：领域层导入服务层（方向性错误）

| 违规文件 | 导入内容 | 违反层次 |
|---------|---------|---------|
| `ai/nlu/deep_analyzer.py` | `pycoder.server.services.agent_tools` | D → C ❌ |
| `ai/generation/iterative.py` | `pycoder.server.services.execution_rules` | D → C ❌ |
| `ai/fusion/engine.py` | `pycoder.server.services.quality_guard` | D → C ❌ |

### 1.6 server/ 内部耦合枢纽

| 枢纽文件 | 同时导入的包数量 | 问题 |
|---------|:---:|------|
| `server/chat_bridge.py` | **12+** | 超级耦合中枢 |
| `server/app.py` | **10+** | 启动时加载所有依赖 |
| `server/services/team/team_coordinator.py` | **8+** | 团队协调器耦合 |

---

## 二、融合方案设计哲学

### 2.1 三大核心原则

#### 原则 1：合同契约驱动（来自 DeepSeek）

每个模块必须声明一个"合同契约"（Contract），明确描述输入、输出和不变式。

```python
@dataclass
class ModuleContract:
    """融合方案的模块合同 — 每个模块必须声明"""
    
    # 1. 输入：我依赖什么？
    dependencies: list[str]   # 允许导入的模块列表
    
    # 2. 输出：我暴露什么？
    public_api: list[str]     # 通过 __all__ 暴露的符号
    
    # 3. 不变式：我保证什么？
    invariants: list[str]     # 可自动化验证的断言
    
    # 4. 能力清单（来自 minimax-M3）
    capabilities: list[str]   # 暴露的能力 ID（domain.action 格式）
```

#### 原则 2：演进式兼容（来自 minimax-M3）

- **不重写** V2 基础（`core/`、`bus/`、`modules/`、`capabilities/`）
- **扩展** V2 `CapabilityDefinition` 为 `CapabilityContract`（向后兼容）
- **保留**旧导入路径 + `DeprecationWarning`（6 个月过渡期）
- **逐步**迁移调用方，最后删除旧 API

#### 原则 3：P/D/C 分层（来自 DeepSeek）

| 类型 | 缩写 | 含义 | 规则 |
|------|------|------|------|
| **平台模块** | P | Platform | 不依赖任何业务模块 |
| **领域模块** | D | Domain | 只能依赖 P |
| **组合模块** | C | Composite | 可依赖 P 和 D |

```
C → D → P    (允许)
C → P         (允许)
D → C         (禁止！)
P → anything  (禁止！)
```

### 2.2 通信机制（融合 minimax-M3 + DeepSeek）

#### 主通道：V2 能力总线（来自 minimax-M3）

```python
# 调用方（任何层）
from pycoder.bus import capability_bus

result = await capability_bus.call(
    "editor.code.read",
    {"path": "main.py"},
    context={"session_id": "xxx", "trace_id": "yyy"}
)

# 流式调用
async for event in capability_bus.stream(
    "system.shell.execute",
    {"command": "npm test"}
):
    print(event.data)
```

#### 辅助通道 1：Strategy 模式（来自 minimax-M3）

```python
class PhaseStrategy(Protocol):
    async def execute(self, ctx: ProjectContext) -> PhaseResult: ...

orchestrator.register_phase(
    LifecyclePhase.TESTING,
    PytestPhaseStrategy()
)
```

#### 辅助通道 2：直接导入（来自 DeepSeek，受 P/D/C 规则约束）

```python
# ✅ 正确：D → P
from pycoder.config import Config
from pycoder.core.ports import AgentTools

# ✅ 正确：C → D
from pycoder.agent import Agent

# ❌ 错误：D → C
from pycoder.server import app  # 违反 P/D/C
```

### 2.3 命名规范（来自 minimax-M3）

```
domain.action[.sub]
```

| 示例 | 含义 |
|------|------|
| `editor.code.read` | 编辑器域 - 代码 - 读取 |
| `system.shell.execute` | 系统域 - Shell - 执行 |
| `self_evo.code.analyze` | 自进化域 - 代码 - 分析 |
| `lifecycle.project.create` | 生命周期域 - 项目 - 创建 |
| `gateway.telegram.send` | 网关域 - Telegram - 发送 |

---

## 三、融合方案目标架构

### 3.1 分层架构（融合三方案）

```
┌────────────────────────────────────────────────────────────┐
│  L7  接口层 (Interface Layer)                              │
│      server/ (FastAPI + WebSocket)  [C 层]                  │
│      electron/ (Electron Main + Renderer)  [C 层]          │
├────────────────────────────────────────────────────────────┤
│  L6  编排层 (Orchestration Layer)  [D 层]                  │
│      lifecycle/  (项目生命周期)                            │
│      ai/agents/  (Agent 编排)                              │
│      gateway/    (消息路由)                                │
├────────────────────────────────────────────────────────────┤
│  L5  能力层 (Capability Layer)  [D 层]                     │
│      capabilities/editor/  capabilities/system/            │
│      capabilities/self_evo/  capabilities/lifecycle/  ← 新│
│      capabilities/gateway/  capabilities/memory/      ← 新│
│      capabilities/extension/  capabilities/observability/←新│
├────────────────────────────────────────────────────────────┤
│  L4  业务核心层 (Business Core Layer)  [D 层]              │
│      brain/  (推理/规划)  memory/  (记忆)                  │
│      evolution/  (进化)   skills/  (技能)                 │
│      extensions/  extensions/                              │
├────────────────────────────────────────────────────────────┤
│  L3  抽象接口层 (Ports Layer)  [P 层]                      │
│      core/ports/  (Protocol 抽象)                          │
│      + agent_tools / execution_rules / quality_guard  ← 新 │
├────────────────────────────────────────────────────────────┤
│  L2  适配实现层 (Adapters Layer)  [P 层]                   │
│      core/adapters/  providers/  lsp/                      │
│      python/  fs/  io/  net/                              │
├────────────────────────────────────────────────────────────┤
│  L1  基础设施层 (Infrastructure Layer)  [P 层]             │
│      bus/  observability/  safety/  env/  config/           │
│      utils/  prompts/  knowledge/                         │
└────────────────────────────────────────────────────────────┘

横切关注点：
  contracts/   ← 所有 capabilities 引用（来自 DeepSeek + minimax-M3）
  testkit/     ← 仅测试时引用（来自 minimax-M3）
  registry/    ← 启动时引用（来自 minimax-M3）
```

### 3.2 目标目录结构（融合三方案）

```
pycoder/
├── contracts/                    # [NEW] 合同契约中心
│   ├── __init__.py
│   ├── base.py                   # ModuleContract 基类
│   ├── checker.py                # 自动检查器（CI 集成）
│   ├── validator.py              # JSON Schema 验证
│   └── contracts/                # 每个模块的合同定义
│       ├── ai.yaml
│       ├── brain.yaml
│       ├── server.yaml
│       └── ...
├── core/                         # [EXISTING] P 层
│   ├── ports/                    # 接口定义
│   │   ├── agent_tools.py        # [NEW] 从 server/services 提取
│   │   ├── execution_rules.py    # [NEW] 从 server/services 提取
│   │   └── quality_guard.py      # [NEW] 从 server/services 提取
│   └── adapters/
├── bus/                          # [EXISTING] P 层 — 能力总线
├── testkit/                      # [NEW] 测试工具包
│   ├── __init__.py
│   ├── decorators.py             # @capability_test
│   ├── mock_bus.py               # MockBus for unit tests
│   └── contract_assert.py        # 契约断言
├── registry/                     # [NEW] 域注册表
│   ├── __init__.py
│   ├── domain_registry.py        # DomainRegistry
│   └── discovery.py              # 自动发现
├── server/                       # [REFACTOR] C 层
│   ├── app.py                    # 精简后 < 200 行
│   ├── domains/                  # [NEW] 按域组织
│   │   ├── chat/                 # 聊天域
│   │   ├── workspace/            # 工作区域
│   │   ├── git/                  # Git 域
│   │   ├── agent/                # Agent 域
│   │   ├── team/                 # 团队域
│   │   ├── extensions/           # 扩展域
│   │   ├── skills/               # 技能域
│   │   ├── evolution/            # 进化域
│   │   ├── files/                # 文件域
│   │   ├── sessions/             # 会话域
│   │   ├── config/               # 配置域
│   │   ├── search/               # 搜索域
│   │   └── system/               # 系统域
│   ├── services/                 # 保留，但每个域 ≤ 500 行
│   └── routers/                  # 保留，但每个域 ≤ 300 行
├── capabilities/                 # [EXTEND] D 层
│   ├── editor/                   # [EXISTING]
│   ├── system/                   # [EXISTING]
│   ├── self_evo/                 # [EXISTING]
│   ├── lifecycle/                # [NEW] 包装 lifecycle/
│   ├── gateway/                  # [NEW] 包装 gateway/
│   ├── memory/                   # [NEW] 包装 memory/
│   ├── extension/                # [NEW] 包装 extensions/
│   └── observability/            # [NEW] 包装 observability/
├── ai/                           # [EXISTING] D 层
├── brain/                        # [EXISTING] D 层
└── ...
```

### 3.3 前端目标架构

#### Store 收敛（来自 DeepSeek）

```typescript
// 从 1 个巨型 appStore 拆分为 8 个独立 Store
stores/
├── uiStore.ts           // 仅 UI 状态（sidebar, theme, layout）
├── editorStore.ts       // 仅编辑器状态（tabs, cursor, dirty）
├── chatStore.ts         // 仅聊天状态（messages, sessions, streaming）
├── backendStore.ts      // 仅后端状态（health, model, env）
├── gitStore.ts          // [NEW] Git 状态
├── workspaceStore.ts    // [NEW] 工作区状态
├── extensionsStore.ts   // [NEW] 扩展状态
└── settingsStore.ts     // [NEW] 设置状态
```

#### 组件 P/D/C 分类（来自 DeepSeek）

| 类型 | 规则 | 目标组件数 | 示例 |
|------|------|----------|------|
| **P（基础组件）** | 不依赖任何 Store，只接受 props | 10 | `Icon`, `Button`, `VirtualList`, `Resizer`, `StateWrapper` |
| **D（功能组件）** | 只依赖 1 个 Store | 25 | `FileTree`, `EditorTabs`, `GitPanel` |
| **C（页面组件）** | 可依赖 2-3 个 Store | 10 | `App`, `AIPanel`, `Sidebar` |

#### 前端目录结构（来自 qwen3.7plus）

```
src/renderer/
├── components/
│   ├── common/              # P 组件
│   ├── layout/              # C 组件
│   ├── editor/              # D 组件
│   ├── ai/                  # C 组件
│   └── features/            # D 组件（按功能分组）
│       ├── git/
│       ├── extensions/
│       ├── skills/
│       ├── team/
│       └── settings/
├── stores/                  # 8 个独立 Store
├── services/                # API + WS + 缓存
├── hooks/                   # 自定义 Hooks
├── types/                   # 类型定义
└── styles/                  # 样式
```

---

## 四、实施阶段（融合路线图）

### 4.1 总览：6 个 Phase，8 周

```
Phase 0 ─ 修复违规导入（1 天）          [来自 DeepSeek]
Phase 1 ─ 契约框架 + testkit（1.5 周）  [融合 DeepSeek + minimax-M3]
Phase 2 ─ 前端 Store 收敛（2 周）       [来自 DeepSeek]
Phase 3 ─ 能力下沉（1.5 周）            [来自 minimax-M3]
Phase 4 ─ server/ 按域拆解（2 周）      [来自 DeepSeek]
Phase 5 ─ 验证与收尾（1 周）            [融合]
```

### 4.2 Phase 0：修复违规导入（立即 / 1 天）

**目标**：消除 3 个领域层→服务层的方向性违规导入。

**演进式兼容策略**（来自 minimax-M3）：
- 保留旧导入路径 + `DeprecationWarning`
- 新接口先并行存在，6 个月后删除旧路径

| 任务 | 具体操作 | 验收 |
|------|---------|------|
| 提取 `core/ports/agent_tools.py` | 从 `server/services/agent_tools.py` 提取 Protocol 接口 | `ai/nlu/deep_analyzer.py` 改为导入 `core.ports` |
| 提取 `core/ports/execution_rules.py` | 从 `server/services/execution_rules.py` 提取 Protocol 接口 | `ai/generation/iterative.py` 改为导入 `core.ports` |
| 提取 `core/ports/quality_guard.py` | 从 `server/services/quality_guard.py` 提取 Protocol 接口 | `ai/fusion/engine.py` 改为导入 `core.ports` |
| 旧路径保留 | `server/services/agent_tools.py` 保留但标记 `@deprecated` | 6 个月后删除 |

### 4.3 Phase 1：契约框架 + testkit（1.5 周）

**目标**：建立合同契约体系 + 测试工具包。

| # | 任务 | 来源 | 交付物 |
|---|------|------|--------|
| 1 | 创建 `pycoder/contracts/` 包 | DeepSeek | `base.py` + `checker.py` |
| 2 | 实现 `ModuleContract` 数据类 | DeepSeek + minimax-M3 | 含 `capabilities` 字段 |
| 3 | 实现 `python -m pycoder.contracts check` CLI | DeepSeek | 自动检查所有模块边界 |
| 4 | 创建 `pycoder/testkit/` 包 | minimax-M3 | `@capability_test` 装饰器 |
| 5 | 实现 `MockBus` 测试工具 | minimax-M3 | 单元测试隔离 |
| 6 | 创建 `pycoder/registry/` 包 | minimax-M3 | `DomainRegistry` 自动发现 |
| 7 | 为 18 个既有模块编写合同 | DeepSeek | `contracts/*.yaml` |
| 8 | 集成到 CI/CD | DeepSeek | `.github/workflows/contracts.yml` |

### 4.4 Phase 2：前端 Store 收敛（2 周）

**目标**：将 55 个组件从全量 Store 耦合中解耦。

| # | 任务 | 影响范围 |
|---|------|---------|
| 1 | 将 `useAppStore` 的 100+ 字段按职责拆分到 8 个独立 Store | `appStore.ts` |
| 2 | 分类组件为 P/D/C | 55 个组件 |
| 3 | P 组件改为纯 props 驱动 | 10 个基础组件 |
| 4 | D 组件改为只依赖 1 个 Store | 25 个功能组件 |
| 5 | C 组件限制为 2-3 个 Store 依赖 | 10 个页面组件 |
| 6 | 清理 `useAppStore` 兼容层（保留 6 个月过渡期） | 标记 `@deprecated` |

### 4.5 Phase 3：能力下沉（1.5 周）

**目标**：将 `lifecycle/`、`gateway/`、`memory/`、`evolution/`、`extensions/` 包装为 V2 能力。

| # | 任务 | 验收 |
|---|------|------|
| 1 | 创建 `capabilities/lifecycle/`，包装 `lifecycle/` 编排器 | 5 个能力注册 |
| 2 | 创建 `capabilities/gateway/`，包装 `gateway/` 网关 | 4 个能力注册 |
| 3 | 创建 `capabilities/memory/`，包装 `memory/` 系统 | 3 个能力注册 |
| 4 | 创建 `capabilities/extension/`，包装 `extensions/` 系统 | 4 个能力注册 |
| 5 | 创建 `capabilities/observability/`，包装 `observability/` | 2 个能力注册 |
| 6 | 拆分 `capabilities/editor/` 为 `editor/`、`refactor/`、`debug/` | 文件数 ↓ 30% |

**新增能力 ID**（domain.action 命名）：

```
lifecycle.project.create / run / progress / cancel / list
gateway.platforms.list / message.send / session.info / session.switch
memory.context.retrieve / facts.store / facts.search
extension.list.installed / list.search / lifecycle.activate / lifecycle.deactivate
observability.trace.query / metrics.snapshot
```

### 4.6 Phase 4：server/ 按域拆解（2 周）

**目标**：将 208 个文件的 server/ 拆分为 13 个域目录。

| 域 | 预期文件数 | 包含的现有模块 |
|----|-----------|--------------|
| `domains/chat/` | 12 | `chat_bridge.py`, `chat_handler.py`, `chat_routes.py` |
| `domains/workspace/` | 10 | 工作区相关 services + routers |
| `domains/git/` | 8 | Git 相关 services + routers |
| `domains/agent/` | 15 | Agent 编排器、循环、工具 |
| `domains/team/` | 10 | 团队协作相关 |
| `domains/extensions/` | 8 | 扩展管理 |
| `domains/skills/` | 6 | 技能市场 |
| `domains/evolution/` | 6 | 进化引擎 |
| `domains/files/` | 8 | 文件操作 |
| `domains/sessions/` | 6 | 会话管理 |
| `domains/config/` | 5 | 配置管理 |
| `domains/search/` | 5 | 搜索 |
| `domains/system/` | 5 | 系统（健康检查、环境） |

### 4.7 Phase 5：验证与收尾（1 周）

| # | 任务 | 验收 |
|---|------|------|
| 1 | 运行 `pycoder.contracts check` 确认零违规 | 0 违规 |
| 2 | 运行 `pydeps --circular` 确认零循环依赖 | 0 循环依赖 |
| 3 | 编写能力契约测试套件 | 每个能力 ≥ 3 测试 |
| 4 | 性能基线对比 | 启动时间 ↓ 30%，主包 ≤ 80 KB |
| 5 | 文档生成（从 Schema 自动生成） | docs/capabilities.md |
| 6 | 全量回归测试 | 现有测试 100% 通过 |
| 7 | 安全扫描 | 零 critical 漏洞 |

---

## 五、验收标准

### 5.1 合同合规（自动化）

| 检查项 | 命令 | 阈值 |
|--------|------|------|
| D→C 违规 | `python -m pycoder.contracts check --layer D` | 0 |
| C→P 违规 | `python -m pycoder.contracts check --layer C` | 0 |
| 循环依赖 | `pydeps pycoder --circular` | 0 |
| 未声明导入 | `python -m pycoder.contracts check --undeclared` | 0 |
| 能力契约覆盖 | `python -m pycoder.testkit.audit` | 100% |

### 5.2 前端 Store 合规

| 指标 | 当前 | 目标 |
|------|------|------|
| 导入 `useAppStore` 的组件数 | 55 | 0（6 个月后删除兼容层） |
| P 组件 Store 依赖数 | 4 | 0 |
| D 组件 Store 依赖数 | 3-5 | 1 |
| 最大组件 Store 依赖数 | 5 | 3 |

### 5.3 后端文件合规

| 指标 | 当前 | 目标 |
|------|------|------|
| server/ 文件数 | 208 | ≤ 150 |
| 最大单文件行数 | 1,200 | ≤ 500 |
| chat_bridge.py 导入包数 | 12+ | ≤ 5 |
| 能力域文件数 | N/A | ≤ 15/域 |

### 5.4 测试覆盖

| 维度 | 阈值 | 验证方式 |
|------|------|---------|
| 后端测试覆盖 | ≥ 80% | `pytest --cov=pycoder` |
| 前端测试覆盖 | ≥ 70% | `vitest --coverage` |
| 能力契约测试 | 每能力 ≥ 3 测试 | `@capability_test` 装饰器 |
| 类型注解覆盖 | ≥ 95% | `mypy --strict` |

### 5.5 性能基线

| 指标 | 当前 | 目标 | 验证 |
|------|------|------|------|
| 后端启动时间 | ~2.3s | ≤ 1.5s | 计时 |
| 首屏 JS 体积 | 104 KB | ≤ 80 KB | vite build |
| API 响应 P99 | TBD | ↓ 20% | locust 压测 |
| 内存占用 | TBD | ↓ 15% | psutil |

---

## 六、关键设计决策记录（ADR）

### ADR-001：以 DeepSeek 方案为主体

- **决策**：采用 DeepSeek 的 P/D/C 模型 + 数据驱动 + CI 契约检查
- **原因**：唯一基于全量扫描，发现真实违规，可验证性最高
- **影响**：需适应 P/D/C 新模型

### ADR-002：演进式兼容（来自 minimax-M3）

- **决策**：保留旧导入路径 + `DeprecationWarning`，6 个月过渡期
- **原因**：避免破坏现有 192+ 个能力注册，降低改造风险
- **影响**：新旧 API 共存，需定期清理

### ADR-003：契约优先（融合）

- **决策**：能力实现前必须有 JSON Schema + `ModuleContract` 声明
- **原因**：强制设计先于实现、稳定 API 文档来源
- **影响**：开发流程增加"先写 Schema"步骤

### ADR-004：V2 能力总线为主通信通道（来自 minimax-M3）

- **决策**：模块间通信优先使用 V2 能力总线
- **原因**：V2 总线已有完整实现（registry/router/transformer/monitor）
- **影响**：减少直接导入，降低耦合

### ADR-005：测试即文档（来自 minimax-M3）

- **决策**：能力测试必须展示典型用法，`@capability_test` 装饰器强制
- **原因**：测试即活文档，减少额外文档维护
- **影响**：测试质量标准提升

### ADR-006：前端 Store 强制拆分（来自 DeepSeek）

- **决策**：删除 `useAppStore` 兼容层，强制 8 个独立 Store
- **原因**：55 个组件全量耦合是项目最大风险
- **影响**：所有组件需迁移到新 Store

---

## 七、风险评估与缓解

| 风险 | 概率 | 影响 | 缓解 | 来源 |
|------|------|------|------|------|
| 改造期间功能回归 | 中 | 高 | 每阶段完成后全量回归测试 | 通用 |
| V2 架构理解偏差 | 中 | 高 | 早期 PoC 验证 `DomainRegistry` | minimax-M3 |
| 能力契约过严 | 中 | 中 | 提供 `lenient=True` 模式 + 演进期兼容 | minimax-M3 |
| 旧 API 删除影响 | 中 | 中 | 6 个月过渡期 + `DeprecationWarning` | minimax-M3 |
| 前端 Store 迁移工作量大 | 高 | 中 | 分批迁移，先 P 组件，再 D，最后 C | DeepSeek |
| 团队适应成本 | 中 | 中 | 编写模块接口文档 + 示例代码 | 通用 |

---

## 八、工具链支持

| 工具 | 用途 | 安装 |
|------|------|------|
| `import-linter` | 检测循环依赖和依赖方向 | `pip install import-linter` |
| `pydeps` | 可视化模块依赖图 | `pip install pydeps` |
| `pytest-cov` | 后端测试覆盖率 | `pip install pytest-cov` |
| `radon` | 圈复杂度 | `pip install radon` |
| `mypy` | 类型检查 | `pip install mypy` |
| `pydocstyle` | 文档字符串检查 | `pip install pydocstyle` |
| `pytest-xdist` | 并行测试 | `pip install pytest-xdist` |
| `locust` | 压测 | `pip install locust` |
| `madge` | 前端依赖图 | `npm install -D madge` |
| `vitest` | 前端单元测试 | `npm install -D vitest` |

---

## 九、CI/CD 集成

```yaml
# .github/workflows/architecture.yml
name: Architecture Compliance

on: [push, pull_request]

jobs:
  contract-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.14'
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: 模块边界检查
        run: python -m pycoder.contracts check
      - name: 循环依赖检查
        run: pydeps pycoder --circular --show-error
      - name: 能力契约覆盖
        run: python -m pycoder.testkit.audit
      - name: 测试覆盖率
        run: pytest --cov=pycoder --cov-fail-under=80
      - name: 类型检查
        run: mypy --strict pycoder
```

---

## 十、融合方案交付物清单

### 10.1 新增代码包

```
pycoder/
├── contracts/              # 合同契约中心
│   ├── __init__.py
│   ├── base.py            # ModuleContract 基类
│   ├── checker.py         # 自动检查器
│   ├── validator.py       # JSON Schema 验证
│   └── contracts/         # 每个模块的合同定义
├── testkit/                # 测试工具包
│   ├── __init__.py
│   ├── decorators.py      # @capability_test
│   ├── mock_bus.py        # MockBus
│   └── contract_assert.py # 契约断言
├── registry/               # 域注册表
│   ├── __init__.py
│   ├── domain_registry.py
│   └── discovery.py
└── capabilities/           # V2 扩展（新增域）
    ├── lifecycle/
    ├── gateway/
    ├── memory/
    ├── extension/
    └── observability/
```

### 10.2 新增测试

```
tests/
├── test_contracts/          # 契约测试
│   ├── test_base.py
│   ├── test_validator.py
│   └── test_loader.py
├── test_testkit/            # 工具测试
│   ├── test_decorators.py
│   └── test_mock_bus.py
├── test_capabilities/       # 能力测试
│   ├── test_lifecycle.py
│   ├── test_gateway.py
│   ├── test_memory.py
│   └── test_extension.py
└── test_architecture/       # 架构合规
    ├── test_dependencies.py
    └── test_boundaries.py
```

### 10.3 文档

```
docs/
├── reports/
│   └── pycoder_fusion_plan_2026-07-26.md  # 本方案
├── architecture/
│   ├── module-boundary-rules.md           # 边界规则
│   ├── capability-naming-guide.md        # 命名规范
│   └── contract-authoring-guide.md         # 契约编写指南
└── capabilities/
    └── capabilities.md                    # 自动生成的能力清单
```

---

## 十一、立即可执行的下一步

按 Phase 0 优先，建议立即开始：

1. **提取 3 个接口到 `core/ports/`**（修复 D→C 违规）
2. **创建 `pycoder/contracts/`**（合同契约框架）
3. **创建 `pycoder/testkit/`**（测试工具包）
4. **创建 `pycoder/registry/`**（域自动发现）
5. **为 5 个现有能力编写契约测试作为 PoC**

---

*此文档为三方案融合终版。以 DeepSeek-V4-Pro 方案为主体（70%），吸收 minimax-M3 的演进式兼容和 V2 能力总线（20%），参考 qwen3.7plus 的目录规范（10%）。基于实际项目全量扫描结果（208 个 server 文件、55 个前端组件、3 个方向性违规、55 个组件全量 Store 耦合），融合三方案优势，提供最完整、最可落地、风险最低的模块化改造路径。*