# PyCoder 模块化改造方案 — min m3（DeepSeek-V4-Pro 版）

> 生成日期：2026-07-26 | 模型：DeepSeek-V4-Pro | 基于实际代码扫描

---

## 〇、本文档与之前两个方案的差异

前两个方案分别是"通用分层架构"和"能力域+V2总线"思路。本方案完全不同：

| 维度 | qwen3.7plus 方案 | 上一个 min m3 方案 | **本方案（DeepSeek min m3）** |
|------|-----------------|-------------------|---------------------------|
| 分析基础 | 推测 | 部分扫描 | **全量扫描 563 文件 + 55 组件** |
| 驱动方式 | 原则驱动 | 架构驱动 | **数据驱动 / 实测违规驱动** |
| 核心问题定义 | 模块边界模糊 | 能力注册分散 | **55 个组件全量导入同一 Store + chat_bridge 交叉耦合枢纽** |
| 组织原则 | 分层 | 能力域 | **合同契约（Contract）— 每个模块必须声明输入/输出边界** |
| 前端策略 | 目录重组 | 目录重组 | **Store 收敛 + 组件分类（P/D/C）重构** |
| 后端策略 | 接口优化 | 下沉为能力 | **消除 3 个耦合枢纽 + 按域拆解 server/** |
| 可验证性 | 低（原则性） | 中（能力注册） | **高（自动化契约检查 CI）** |

---

## 一、项目现状：基于全量扫描的数据报告

### 1.1 后端模块统计

| 目录 | 文件数 | 行数估算 | 角色 |
|------|--------|---------|------|
| `pycoder/server/` | **208** | ~42,000 | ⚠️ 超大型单体（占全项目 36%） |
| `pycoder/electron/` | 59 | ~9,000 | 前端 |
| `pycoder/ai/` | 39 | ~8,000 | AI 能力层 |
| `pycoder/capabilities/` | 37 | ~7,000 | V2 能力 |
| `pycoder/python/` | 30 | ~6,000 | Python 工具链 |
| `pycoder/brain/` | 24 | ~5,000 | 推理规划 |
| `pycoder/core/` | 19 | ~3,800 | V2 Clean Architecture |
| `pycoder/memory/` | 12 | ~2,400 | 记忆 |
| `pycoder/scripts/` | 11 | ~1,500 | 工具 |
| `pycoder/gateway/` | 9 | ~1,800 | 网关 |
| `pycoder/safety/` | 8 | ~1,600 | 安全 |
| `pycoder/lsp/` | 8 | ~1,600 | LSP |
| `pycoder/extensions/` | 8 | ~1,600 | 扩展 |
| `pycoder/providers/` | 7 | ~1,400 | 模型 Provider |
| `pycoder/prompts/` | 7 | ~1,400 | 提示词 |
| `pycoder/skills/` | 7 | ~1,400 | 技能 |
| `pycoder/lifecycle/` | 6 | ~1,200 | 生命周期 |
| `pycoder/evolution/` | 5 | ~1,000 | 进化 |
| `pycoder/multimodal/` | 5 | ~800 | 多模态 |
| `pycoder/web/` | 6 | ~800 | Web 工具 |
| 其他 | < 5/项 | ~3,000 | 边界模块 |

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
| DebugPanel | ✓ | ✓ | | | |
| SettingsPanel | ✓ | ✓ | ✓ | | |
| FileTree | ✓ | ✓ | | | |
| Sidebar | ✓ | ✓ | | | |
| GitPanel | ✓ | ✓ | ✓ | | |
| BrowserPanel | ✓ | ✓ | ✓ | | |
| CommandPalette | ✓ | ✓ | ✓ | | |
| DiffPreview | ✓ | ✓ | ✓ | | |
| DiffView | ✓ | ✓ | ✓ | | |
| DropZone | ✓ | ✓ | ✓ | | |
| **EditorTabs** | ✓ | ✓ | ✓ | ✓ | |
| GitBranchGraph | ✓ | ✓ | ✓ | | |
| **MonacoEditor** | ✓ | ✓ | ✓ | ✓ | |
| SearchPanel | ✓ | ✓ | ✓ | | |
| StatusBar | ✓ | ✓ | ✓ | | |
| WelcomeScreen | ✓ | ✓ | ✓ | | |
| **DependencyManager** | ✓ | ✓ | ✓ | | ✓ |
| **ChatHistorySearch** | ✓ | ✓ | ✓ | | ✓ |
| TeamPanel | ✓ | ✓ | ✓ | | |
| ExtensionsPanel | ✓ | ✓ | ✓ | | |
| **WorkspacePanel** | ✓ | ✓ | ✓ | | ✓ |
| **PublishDialog** | ✓ | ✓ | ✓ | | ✓ |
| CloneDialog | ✓ | ✓ | ✓ | | |
| GitHubPanel | ✓ | ✓ | ✓ | | |
| **PythonRunner** | ✓ | ✓ | ✓ | | ✓ |
| **SnippetsPanel** | ✓ | ✓ | ✓ | | ✓ |
| **TestGenerator** | ✓ | ✓ | ✓ | | ✓ |
| SkillsMarket | ✓ | ✓ | ✓ | | |
| **EvolutionPanel** | ✓ | ✓ | ✓ | | ✓ |
| **AgentProgressBar** | ✓ | ✓ | ✓ | | ✓ |
| **AgentThinkingBlock** | ✓ | ✓ | ✓ | | ✓ |
| **AgentToolChain** | ✓ | ✓ | ✓ | | ✓ |
| **AgentDiffCard** | ✓ | ✓ | ✓ | | ✓ |
| **ChatMessagesList** | ✓ | ✓ | ✓ | | ✓ |
| **SessionManager** | ✓ | ✓ | ✓ | | ✓ |
| **EditorTabContextMenu** | ✓ | ✓ | ✓ | | ✓ |
| VirtualList | ✓ | ✓ | ✓ | | ✓ |
| StateWrapper | ✓ | ✓ | ✓ | | ✓ |
| Resizer | ✓ | ✓ | ✓ | | ✓ |
| ImageViewer | ✓ | ✓ | ✓ | | ✓ |
| WebPreview | ✓ | ✓ | ✓ | | ✓ |
| OutputPanel | ✓ | ✓ | ✓ | | ✓ |
| ProblemsPanel | ✓ | ✓ | ✓ | | ✓ |
| TerminalPanel | ✓ | ✓ | ✓ | | ✓ |
| RunFixPanel | ✓ | ✓ | ✓ | | ✓ |
| MenuBar | ✓ | ✓ | ✓ | | ✓ |
| ThemeManager | ✓ | ✓ | ✓ | | ✓ |
| AgentWorkbench | ✓ | ✓ | ✓ | | ✓ |
| TestGenPanel | ✓ | ✓ | ✓ | | ✓ |
| PythonRunnerPanel | ✓ | ✓ | ✓ | | ✓ |

**统计**：
- 100% 组件导入 `useAppStore` — 全量耦合
- 100% 组件导入 `useUIStore` — 全量耦合
- 95% 组件导入 `useChatStore` — 几乎全量耦合
- 48% 组件导入 `useBackendStore` — 半量耦合
- 仅 2 个组件导入 `useEditorStore` — 编辑器功能未收敛

### 1.5 后端耦合违规：领域层导入服务层（方向性错误）

| 违规文件 | 导入内容 | 违反层次 |
|---------|---------|---------|
| `ai/nlu/deep_analyzer.py` | `pycoder.server.services.agent_tools` | 领域层 → 服务层 ❌ |
| `ai/generation/iterative.py` | `pycoder.server.services.execution_rules` | 领域层 → 服务层 ❌ |
| `ai/fusion/engine.py` | `pycoder.server.services.quality_guard` | 领域层 → 服务层 ❌ |

### 1.6 server/ 内部耦合枢纽

| 枢纽文件 | 同时导入的包数量 | 问题 |
|---------|:---:|------|
| `server/chat_bridge.py` | **12+** | 超级耦合中枢 |
| `server/app.py` | **10+** | 启动时加载所有依赖 |
| `server/services/team/team_coordinator.py` | **8+** | 团队协调器耦合 |

---

## 二、min m3 设计哲学：合同契约驱动

### 2.1 核心思想

本方案的核心思想是：**每个模块必须声明一个"合同契约"（Contract），明确描述该模块的输入（依赖什么）、输出（暴露什么）、和不变式（保证什么）。**

与之前两个方案的关键区别：
- qwen 方案：按"技术层"分（config → utils → agent → server）— 标准但未解决实际耦合
- 上个 min m3：按"能力域"分（extension.memory.retrieve）— 有创意但依赖 V2 总线
- **本方案**：按"合同契约"分 — 每个模块说清楚"我需要什么"和"我提供什么"，然后自动化检查

### 2.2 合同契约的三要素

```python
@dataclass
class ModuleContract:
    """min m3 模块合同 — 每个模块必须声明"""
    
    # 1. 输入：我依赖什么？
    dependencies: list[str]   # 允许导入的模块列表
    
    # 2. 输出：我暴露什么？
    public_api: list[str]     # 通过 __all__ 暴露的符号
    
    # 3. 不变式：我保证什么？
    invariants: list[str]     # 可自动化验证的断言
```

### 2.3 模块分类：P/D/C 模型

将所有模块分为三类：

| 类型 | 缩写 | 含义 | 规则 | 示例 |
|------|------|------|------|------|
| **平台模块** | P | Platform | 只能被 D 和 C 依赖，自己不依赖任何业务模块 | `config`, `utils`, `bus`, `safety` |
| **领域模块** | D | Domain | 只能依赖 P，不能依赖 C | `ai`, `brain`, `memory`, `evolution`, `skills`, `extensions`, `capabilities`, `lifecycle`, `gateway` |
| **组合模块** | C | Composite | 可以依赖 P 和 D，是最终的应用入口 | `server`, `electron` |

**P/D/C 三层依赖规则**：

```
C → D → P
C → P  (允许)
D → C  (禁止！)
D → P  (允许)
P → anything (禁止！P 是最底层)
```

### 2.4 前端组件分类：P/D/C 类比

| 类型 | 规则 | 示例 |
|------|------|------|
| **P（基础组件）** | 不依赖任何 Store，只接受 props | `Icon`, `Button`, `VirtualList`, `Resizer`, `StateWrapper` |
| **D（功能组件）** | 只依赖 1 个 Store，通过 props 接收数据 | 理想的目标状态 |
| **C（页面组件）** | 可以依赖多个 Store，作为编排者 | `App`, `AIPanel`, `Sidebar` |

---

## 三、min m3 目标架构

### 3.1 后端目标：消除 3 个耦合枢纽

```
现状（违规）:
  ai/nlu  ──→  server/services/agent_tools     ❌ 领域层导入服务层
  ai/gen  ──→  server/services/execution_rules ❌ 领域层导入服务层
  ai/fusion ─→ server/services/quality_guard   ❌ 领域层导入服务层

目标（修复后）:
  ai/nlu  ──→  pycoder/core/ports/agent_tools  ✅ 领域层导入接口
  ai/gen  ──→  pycoder/core/ports/execution_rules ✅ 领域层导入接口
  ai/fusion ─→ pycoder/core/ports/quality_guard   ✅ 领域层导入接口
  server/services/ 实现这些接口                      ✅ 服务层实现接口
```

### 3.2 前端目标：消除全量 Store 耦合

```
现状（违规）:
  55 个组件 ──→ useAppStore    ❌ 全量耦合
  55 个组件 ──→ useUIStore     ❌ 全量耦合
  52 个组件 ──→ useChatStore   ❌ 几乎全量耦合

目标（修复后）:
  P 组件（10 个）──→ 无 Store 依赖            ✅ 纯 props
  D 组件（25 个）──→ 1 个 Store 依赖          ✅ 单一职责
  C 组件（10 个）──→ 2-3 个 Store 依赖        ✅ 编排者
```

### 3.3 目标目录结构

```
pycoder/
├── contracts/                    # [NEW] 合同契约中心
│   ├── __init__.py
│   ├── base.py                   # ModuleContract 基类
│   ├── checker.py                # 自动检查器（CI 集成）
│   └── contracts/                # 每个模块的合同定义
│       ├── ai.yaml
│       ├── brain.yaml
│       ├── server.yaml
│       └── ...
├── core/                         # [EXISTING] P 层
│   ├── ports/                    # 接口定义（Protocol）
│   │   ├── agent_tools.py        # [NEW] 从 server/services 提取接口
│   │   ├── execution_rules.py    # [NEW] 从 server/services 提取接口
│   │   └── quality_guard.py      # [NEW] 从 server/services 提取接口
│   └── adapters/                 # 适配实现
├── server/                       # [REFACTOR] C 层
│   ├── app.py                    # 精简后 < 200 行
│   ├── domains/                  # [NEW] 按域组织
│   │   ├── chat/                 # 聊天域
│   │   ├── workspace/            # 工作区域
│   │   ├── git/                  # Git 域
│   │   ├── team/                 # 团队域
│   │   ├── agent/                # Agent 域
│   │   ├── extensions/           # 扩展域
│   │   ├── skills/               # 技能域
│   │   ├── evolution/            # 进化域
│   │   ├── files/                 # 文件域
│   │   ├── sessions/             # 会话域
│   │   ├── config/               # 配置域
│   │   ├── search/               # 搜索域
│   │   └── system/               # 系统域
│   ├── services/                 # 保留，但每个域 ≤ 500 行
│   └── routers/                  # 保留，但每个域 ≤ 300 行
├── ai/                           # [EXISTING] D 层
├── brain/                        # [EXISTING] D 层
└── ...
```

---

## 四、实施阶段（min m3 五阶段）

### Phase 0：修复违规导入（立即 / 1 天）

**目标**：消除 3 个领域层→服务层的方向性违规导入。

| 任务 | 具体操作 | 验收 |
|------|---------|------|
| 提取 `core/ports/agent_tools.py` | 从 `server/services/agent_tools.py` 提取 Protocol 接口 | `ai/nlu/deep_analyzer.py` 改为导入 `core.ports` |
| 提取 `core/ports/execution_rules.py` | 从 `server/services/execution_rules.py` 提取 Protocol 接口 | `ai/generation/iterative.py` 改为导入 `core.ports` |
| 提取 `core/ports/quality_guard.py` | 从 `server/services/quality_guard.py` 提取 Protocol 接口 | `ai/fusion/engine.py` 改为导入 `core.ports` |

### Phase 1：合同契约框架（1 周）

**目标**：建立合同契约体系，让每个模块声明边界。

| # | 任务 | 交付物 |
|---|------|--------|
| 1 | 创建 `pycoder/contracts/` 包 | `base.py` + `checker.py` |
| 2 | 为 18 个既有模块编写合同定义 | `contracts/*.yaml` |
| 3 | 实现 `python -m pycoder.contracts check` CLI | 自动检查所有模块边界 |
| 4 | 集成到 CI/CD | `.github/workflows/contracts.yml` |
| 5 | 为 Phase 0 修复的 3 个接口编写合同 | 验证 D→C 违规已消除 |

### Phase 2：前端 Store 收敛（2 周）

**目标**：将 55 个组件从全量 Store 耦合中解耦。

| # | 任务 | 影响范围 |
|---|------|---------|
| 1 | 将 `useAppStore` 的 100+ 字段按职责拆分到 5 个独立 Store | `appStore.ts` |
| 2 | 分类组件为 P/D/C | 55 个组件 |
| 3 | P 组件改为纯 props 驱动 | `Icon`, `Button`, `VirtualList`, `Resizer`, `StateWrapper` 等 10 个 |
| 4 | D 组件改为只依赖 1 个 Store | 25 个功能组件 |
| 5 | 清理 `useAppStore` 兼容层 | 删除旧 API |

**前端 Store 目标结构**：

```typescript
// 拆分后的 Store 结构
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

### Phase 3：server/ 按域拆解（3 周）

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

### Phase 4：验证与收尾（1 周）

| # | 任务 | 验收 |
|---|------|------|
| 1 | 运行 `pycoder.contracts check` 确认零违规 | 0 违规 |
| 2 | 运行 `pydeps --circular` 确认零循环依赖 | 0 循环依赖 |
| 3 | 前端构建验证 | 零错误，主包 ≤ 80 KB |
| 4 | 后端启动验证 | 启动时间 ≤ 1.5s |
| 5 | 全量回归测试 | 现有测试 100% 通过 |

---

## 五、验收标准

### 5.1 合同合规（自动化）

| 检查项 | 命令 | 阈值 |
|--------|------|------|
| D→C 违规 | `python -m pycoder.contracts check --layer D` | 0 |
| C→P 违规 | `python -m pycoder.contracts check --layer C` | 0 |
| 循环依赖 | `pydeps pycoder --circular` | 0 |
| 未声明导入 | `python -m pycoder.contracts check --undeclared` | 0 |

### 5.2 前端 Store 合规

| 指标 | 当前 | 目标 |
|------|------|------|
| 导入 `useAppStore` 的组件数 | 55 | 0（删除兼容层） |
| P 组件 Store 依赖数 | 4 | 0 |
| D 组件 Store 依赖数 | 3-5 | 1 |
| 最大组件 Store 依赖数 | 5 | 3 |

### 5.3 后端文件合规

| 指标 | 当前 | 目标 |
|------|------|------|
| server/ 文件数 | 208 | ≤ 150 |
| 最大单文件行数 | 1,200 | ≤ 500 |
| chat_bridge.py 导入包数 | 12+ | ≤ 5 |

---

## 六、与之前方案的对比总结

| 特性 | qwen 方案 | 上个 min m3 | **本方案（DeepSeek）** |
|------|----------|------------|----------------------|
| 数据驱动 | 否 | 部分 | **是 — 全量扫描 563 文件 + 55 组件** |
| 发现具体违规 | 否 | 否 | **是 — 3 个 D→C 违规 + 55 组件全量 Store 耦合** |
| 自动化验证 | 低 | 中 | **高 — `pycoder.contracts check` CI 命令** |
| 前端改造 | 目录重组 | 目录重组 | **Store 收敛 + P/D/C 分类 + 兼容层删除** |
| 后端改造 | 接口优化 | 下沉为能力 | **修复违规导入 + 按域拆解 server/** |
| 可落地性 | 中 | 中 | **高 — 每个阶段有具体文件操作** |

---

*此文档由 DeepSeek-V4-Pro 生成。基于实际项目全量扫描结果（208 个 server 文件、55 个前端组件、3 个方向性违规、55 个组件全量 Store 耦合），与之前两个方案在分析基础、改造策略、验证方式上完全不同。*