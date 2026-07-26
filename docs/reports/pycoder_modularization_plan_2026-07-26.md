# PyCoder 模块化改造方案

> 生成日期：2026-07-26 | 基于项目深度分析

---

## 一、项目现状分析

### 1.1 项目规模

| 维度 | 数据 |
|------|------|
| Python 文件数 | 563 |
| 代码总行数 | ~160,000 |
| React 组件数 | 55 |
| CSS 总行数 | 7,500+ |
| 后端包数 | 11 个主要包 |
| 前端 Store 数 | 5 个 Zustand Store |

### 1.2 当前架构问题

| 问题类别 | 具体问题 | 严重度 |
|---------|---------|--------|
| **单体 Store** | `appStore.ts` 100+ 字段兼容层，违反单一职责 | 高 |
| **God Component** | `App.tsx` 360 行、33 个直接导入 | 高 |
| **CSS 巨石** | `layout.css` 单文件 7,500+ 行 | 中 |
| **API 耦合** | `backend.ts` 原 500+ 行单一对象（已拆分） | 已修复 |
| **模块边界模糊** | 领域逻辑与服务层混合 | 高 |
| **循环依赖风险** | 模块间导入关系不清晰 | 中 |
| **测试覆盖不足** | 核心模块缺乏独立单元测试 | 高 |

### 1.3 后端模块现状

```
pycoder/
├── __init__.py
├── __main__.py              # 入口
├── agent/                   # AI Agent 核心（~20 文件）
├── config/                  # 配置管理（~5 文件）
├── evolution/               # 自进化引擎（~15 文件）
├── extensions/              # 扩展系统（~10 文件）
├── memory/                  # 记忆系统（~12 文件）
├── safety/                  # 安全策略（~3 文件）
├── server/                  # 服务层（~40 文件）
│   ├── app.py               # FastAPI 应用
│   ├── routers/             # 路由定义
│   ├── services/            # 业务服务
│   └── ws_handler*.py       # WebSocket
├── skills/                  # 技能系统（~8 文件）
├── tools/                   # 工具集（~25 文件）
└── utils/                   # 通用工具（~10 文件）
```

### 1.4 前端模块现状

```
src/renderer/
├── components/              # 55 个组件（扁平结构）
│   ├── AIPanel.tsx          # 212 KB（最大）
│   ├── ActivityBar.tsx
│   ├── Sidebar.tsx
│   ├── TerminalPanel.tsx
│   └── ...（50+ 组件）
├── stores/                  # 5 个 Zustand Store
│   ├── appStore.ts          # 100+ 字段兼容层
│   ├── uiStore.ts
│   ├── editorStore.ts
│   ├── chatStore.ts
│   └── backendStore.ts
├── services/                # API + WS + 缓存
│   ├── api/                 # 10 个 API 模块（已拆分）
│   ├── wsConnectionRegistry.ts
│   └── cache.ts
├── hooks/                   # 自定义 Hooks
├── types/                   # 类型定义
└── styles/                  # CSS 样式
```

---

## 二、模块化设计原则

### 2.1 核心原则

| 原则 | 说明 |
|------|------|
| **高内聚** | 每个模块只负责一个明确的职责，内部元素紧密相关 |
| **低耦合** | 模块间通过最小化接口交互，减少直接依赖 |
| **单一职责** | 每个模块只有一个变更理由 |
| **依赖倒置** | 上层模块不依赖下层实现细节，依赖抽象接口 |
| **开闭原则** | 对扩展开放，对修改关闭 |

### 2.2 模块划分标准

1. **职责边界清晰** — 每个模块有且只有一个变更理由
2. **接口最小化** — 公共 API 尽量少，隐藏内部实现
3. **可独立测试** — 每个模块可在隔离环境中运行单元测试
4. **可独立部署** — 未来可拆分为独立微服务（可选）
5. **依赖方向明确** — 上层 → 下层，禁止反向依赖

### 2.3 分层架构

```
┌─────────────────────────────────────────────────┐
│  应用层 (Application Layer)                      │
│  pycoder/app.py, pycoder/__main__.py            │
├─────────────────────────────────────────────────┤
│  服务层 (Service Layer)                          │
│  pycoder/server/  — REST API + WebSocket         │
├─────────────────────────────────────────────────┤
│  领域层 (Domain Layer)                           │
│  pycoder/agent/      — AI Agent 核心             │
│  pycoder/evolution/  — 自进化引擎                │
│  pycoder/memory/     — 记忆系统                  │
│  pycoder/skills/     — 技能系统                  │
│  pycoder/extensions/ — 扩展系统                  │
├─────────────────────────────────────────────────┤
│  基础设施层 (Infrastructure Layer)               │
│  pycoder/tools/    — 工具集                      │
│  pycoder/config/   — 配置管理                    │
│  pycoder/utils/    — 通用工具                    │
│  pycoder/safety/   — 安全策略                    │
│  pycoder/storage/  — 持久化存储                  │
└─────────────────────────────────────────────────┘
```

### 2.4 模块间通信机制

| 通信方式 | 适用场景 | 示例 |
|---------|---------|------|
| **直接导入** | 同层/跨层模块调用 | `from pycoder.config import get_config` |
| **依赖注入** | 跨层调用，避免硬依赖 | Agent 接收 Config 实例而非直接导入 |
| **事件总线** | 松耦合通知 | Agent 完成 → 通知 Memory 存储 |
| **WebSocket** | 前后端实时通信 | 聊天消息、任务进度推送 |
| **REST API** | 前后端数据交互 | 会话管理、文件操作、Git 操作 |

### 2.5 依赖管理策略

```python
# 依赖方向：上层 → 下层（禁止反向依赖）
# 同层模块间：通过接口导入，禁止直接访问内部

# ✅ 正确
from pycoder.config import Config          # 领域层 → 基础设施层
from pycoder.agent import Agent            # 服务层 → 领域层

# ❌ 错误
from pycoder.server import app             # 领域层 → 服务层（反向）
from pycoder.agent.internal import _cache  # 跨模块访问内部实现
```

---

## 三、后端模块化改造方案

### 3.1 模块划分

#### 模块 1: `pycoder/config/` — 配置管理

| 项目 | 说明 |
|------|------|
| **职责** | 环境变量、配置文件、模型参数管理 |
| **公共接口** | `get_config()`, `get_env()`, `ModelConfig` |
| **依赖** | 无（最底层模块） |
| **当前状态** | 已有，需整理接口 |

#### 模块 2: `pycoder/utils/` — 通用工具

| 项目 | 说明 |
|------|------|
| **职责** | 日志、文件操作、字符串处理、类型定义 |
| **公共接口** | `log`, `Path`, `safe_read()`, `safe_write()` |
| **依赖** | `config` |
| **当前状态** | 已有，需清理 |

#### 模块 3: `pycoder/safety/` — 安全策略

| 项目 | 说明 |
|------|------|
| **职责** | 权限控制、命令白名单、文件路径校验 |
| **公共接口** | `PermissionPolicy`, `check_path()`, `validate_command()` |
| **依赖** | `config`, `utils` |
| **当前状态** | 已有 `permission_policy.py`，需迁移整合 |

#### 模块 4: `pycoder/storage/` — 持久化存储

| 项目 | 说明 |
|------|------|
| **职责** | 会话存储、消息存储、文件索引 |
| **公共接口** | `SessionStore`, `MessageStore`, `FileIndex` |
| **依赖** | `config`, `utils` |
| **当前状态** | 分散在 `server/services/`，需抽取 |

#### 模块 5: `pycoder/agent/` — AI Agent 核心

| 项目 | 说明 |
|------|------|
| **职责** | Agent 循环、工具调用、LLM 交互 |
| **公共接口** | `Agent`, `AgentLoop`, `ToolRegistry` |
| **依赖** | `config`, `utils`, `safety`, `storage` |
| **当前状态** | 已有，需整理接口 |

#### 模块 6: `pycoder/evolution/` — 自进化引擎

| 项目 | 说明 |
|------|------|
| **职责** | 代码分析、自动修复、进化策略 |
| **公共接口** | `EvolutionEngine`, `CodeAnalyzer`, `FixStrategy` |
| **依赖** | `config`, `utils`, `agent`, `storage` |
| **当前状态** | 已有，需整理 |

#### 模块 7: `pycoder/memory/` — 记忆系统

| 项目 | 说明 |
|------|------|
| **职责** | 长期记忆、上下文管理、知识检索 |
| **公共接口** | `MemoryStore`, `ContextManager`, `KnowledgeRetriever` |
| **依赖** | `config`, `utils`, `storage` |
| **当前状态** | 已有，需整理 |

#### 模块 8: `pycoder/skills/` — 技能系统

| 项目 | 说明 |
|------|------|
| **职责** | 技能注册、技能执行、技能市场 |
| **公共接口** | `SkillRegistry`, `SkillExecutor`, `SkillMarket` |
| **依赖** | `config`, `utils`, `agent` |
| **当前状态** | 已有，需整理 |

#### 模块 9: `pycoder/extensions/` — 扩展系统

| 项目 | 说明 |
|------|------|
| **职责** | 扩展加载、扩展生命周期、扩展 API |
| **公共接口** | `ExtensionManager`, `ExtensionLoader`, `ExtensionAPI` |
| **依赖** | `config`, `utils`, `agent` |
| **当前状态** | 已有，需整理 |

#### 模块 10: `pycoder/tools/` — 工具集

| 项目 | 说明 |
|------|------|
| **职责** | 文件操作、Git 操作、代码执行、搜索 |
| **公共接口** | `FileTools`, `GitTools`, `CodeExecTools`, `SearchTools` |
| **依赖** | `config`, `utils`, `safety` |
| **当前状态** | 已有，需整理 |

#### 模块 11: `pycoder/server/` — 服务层

| 项目 | 说明 |
|------|------|
| **职责** | REST API、WebSocket、中间件、路由 |
| **公共接口** | `create_app()`, `register_routes()`, `WebSocketHandler` |
| **依赖** | 所有领域模块 |
| **当前状态** | 已有，需重构路由组织 |

### 3.2 后端模块依赖图

```
config (无依赖)
  ↑
utils (→ config)
  ↑
safety (→ config, utils)
  ↑
storage (→ config, utils)
  ↑
agent (→ config, utils, safety, storage)
  ↑
├── evolution (→ config, utils, agent, storage)
├── memory (→ config, utils, storage)
├── skills (→ config, utils, agent)
├── extensions (→ config, utils, agent)
└── tools (→ config, utils, safety)
  ↑
server (→ 所有模块)
```

### 3.3 后端改造实施步骤

| 阶段 | 任务 | 验收标准 |
|------|------|---------|
| **Phase 1** | 整理 `config` 和 `utils` 模块接口 | 所有公共函数有类型注解和文档字符串 |
| **Phase 2** | 迁移 `permission_policy.py` → `safety/` | 现有测试全部通过 |
| **Phase 3** | 抽取 `storage/` 模块 | 会话/消息存储接口独立可测试 |
| **Phase 4** | 整理 `agent/` 模块接口 | Agent 可独立实例化，不依赖 server |
| **Phase 5** | 整理 `evolution/`, `memory/`, `skills/`, `extensions/` | 每个模块可独立导入 |
| **Phase 6** | 重构 `server/` 路由组织 | 路由按领域模块分组，每组独立注册 |
| **Phase 7** | 补充单元测试 | 每个模块 ≥80% 覆盖率 |

---

## 四、前端模块化改造方案

### 4.1 模块划分

#### 模块 A: `components/common/` — 通用 UI 组件

| 项目 | 说明 |
|------|------|
| **职责** | 按钮、输入框、弹窗、图标、状态包装器 |
| **公共接口** | `Button`, `Input`, `Modal`, `Icon`, `StateWrapper`, `VirtualList`, `Resizer` |
| **依赖** | 无（纯 UI 组件） |

#### 模块 B: `components/layout/` — 布局组件

| 项目 | 说明 |
|------|------|
| **职责** | 应用外壳、侧边栏、活动栏、底部面板 |
| **公共接口** | `AppShell`, `Sidebar`, `ActivityBar`, `BottomPanel`, `StatusBar` |
| **依赖** | `common`, `stores/ui` |

#### 模块 C: `components/editor/` — 编辑器组件

| 项目 | 说明 |
|------|------|
| **职责** | 代码编辑器、标签页、差异预览 |
| **公共接口** | `MonacoEditor`, `EditorTabs`, `DiffPreview` |
| **依赖** | `common`, `stores/editor` |

#### 模块 D: `components/ai/` — AI 交互组件

| 项目 | 说明 |
|------|------|
| **职责** | AI 面板、消息列表、Agent 事件渲染 |
| **公共接口** | `AIPanel`, `MessageList`, `AgentEventsRenderer` |
| **依赖** | `common`, `stores/chat`, `services/api` |

#### 模块 E: `components/features/` — 功能面板

| 项目 | 说明 |
|------|------|
| **职责** | Git、扩展、技能、团队、设置等功能面板 |
| **公共接口** | `GitPanel`, `ExtensionsPanel`, `SkillsMarket`, `TeamPanel`, `SettingsPanel` |
| **依赖** | `common`, `stores/*`, `services/api` |

#### 模块 F: `stores/` — 状态管理

| 项目 | 说明 |
|------|------|
| **职责** | 应用状态、UI 状态、编辑器状态、聊天状态 |
| **公共接口** | `useUIStore`, `useEditorStore`, `useChatStore`, `useBackendStore` |
| **依赖** | `services/api` |

#### 模块 G: `services/` — 服务层

| 项目 | 说明 |
|------|------|
| **职责** | API 调用、WebSocket、缓存、配置 |
| **公共接口** | `BackendAPI`, `WSConnectionRegistry`, `apiCache` |
| **依赖** | 无 |

#### 模块 H: `hooks/` — 自定义 Hooks

| 项目 | 说明 |
|------|------|
| **职责** | 键盘快捷键、Web Vitals、无障碍、通用逻辑 |
| **公共接口** | `useKeyboardShortcuts`, `useWebVitals`, `useA11y`, `useFocusTrap` |
| **依赖** | 无 |

### 4.2 前端目标目录结构

```
src/renderer/
├── components/
│   ├── common/              # 通用 UI 组件
│   │   ├── Button.tsx
│   │   ├── Icon.tsx
│   │   ├── StateWrapper.tsx
│   │   ├── VirtualList.tsx
│   │   └── Resizer.tsx
│   ├── layout/              # 布局组件
│   │   ├── AppShell.tsx
│   │   ├── Sidebar.tsx
│   │   ├── ActivityBar.tsx
│   │   ├── BottomPanel.tsx
│   │   └── StatusBar.tsx
│   ├── editor/              # 编辑器组件
│   │   ├── MonacoEditor.tsx
│   │   ├── EditorTabs.tsx
│   │   └── DiffPreview.tsx
│   ├── ai/                  # AI 交互组件
│   │   ├── AIPanel.tsx
│   │   ├── MessageList.tsx
│   │   └── AgentEventsRenderer.tsx
│   └── features/            # 功能面板
│       ├── git/
│       │   └── GitPanel.tsx
│       ├── extensions/
│       │   └── ExtensionsPanel.tsx
│       ├── skills/
│       │   └── SkillsMarket.tsx
│       ├── team/
│       │   └── TeamPanel.tsx
│       └── settings/
│           └── SettingsPanel.tsx
├── stores/                  # 状态管理
│   ├── uiStore.ts
│   ├── editorStore.ts
│   ├── chatStore.ts
│   └── backendStore.ts
├── services/                # 服务层
│   ├── api/                 # 10 个 API 模块
│   │   ├── client.ts
│   │   ├── health.ts
│   │   ├── models.ts
│   │   ├── sessions.ts
│   │   ├── workspace.ts
│   │   ├── extensions.ts
│   │   ├── files.ts
│   │   ├── git.ts
│   │   ├── misc.ts
│   │   └── index.ts
│   ├── ws/
│   │   └── wsConnectionRegistry.ts
│   ├── cache.ts
│   └── config.ts
├── hooks/                   # 自定义 Hooks
│   ├── useKeyboardShortcuts.ts
│   ├── useWebVitals.ts
│   └── useA11y.ts
├── types/                   # 类型定义
├── utils/                   # 工具函数
└── styles/                  # 样式
    ├── theme.css
    ├── layout.css
    └── components/          # 按组件拆分 CSS
```

### 4.3 前端改造实施步骤

| 阶段 | 任务 | 验收标准 |
|------|------|---------|
| **Phase 1** | 创建 `components/layout/` 目录，迁移布局组件 | `App.tsx` 行数 < 100 |
| **Phase 2** | 创建 `components/editor/` 目录，迁移编辑器组件 | 编辑器相关组件独立可测试 |
| **Phase 3** | 创建 `components/ai/` 目录，迁移 AI 组件 | AI 面板可独立渲染 |
| **Phase 4** | 创建 `components/features/` 子目录，按功能分组 | 每个功能面板独立目录 |
| **Phase 5** | 清理 `appStore.ts` 兼容层 | 所有组件使用独立 Store |
| **Phase 6** | 补充前端单元测试 | 核心组件 ≥70% 覆盖率 |

---

## 五、模块间通信机制详解

### 5.1 后端通信

```python
# 1. 直接导入（同层/下层模块）
from pycoder.config import get_config
from pycoder.utils import log

# 2. 依赖注入（跨层调用）
class Agent:
    def __init__(self, config: Config, storage: SessionStore):
        self.config = config
        self.storage = storage

# 3. 事件总线（松耦合通知）
from pycoder.utils.events import EventBus

event_bus = EventBus()
event_bus.emit("agent.completed", {"session_id": "xxx"})
```

### 5.2 前端通信

```typescript
// 1. Zustand Store（状态共享）
import { useUIStore } from '../stores/uiStore';
const sidebarOpen = useUIStore(s => s.sidebarOpen);

// 2. API 服务（数据获取）
import { sessionApi } from '../services/api/sessions';
const sessions = await sessionApi.list();

// 3. WebSocket（实时通信）
import { WSConnectionRegistry } from '../services/wsConnectionRegistry';
const ws = WSConnectionRegistry.getInstance().getConnection();

// 4. 事件回调（组件间通信）
<ActivityBar onItemClick={handleItemClick} />
```

---

## 六、验收标准

### 6.1 模块独立性

- [ ] 每个模块可独立导入，不触发循环依赖
- [ ] 每个模块有明确的 `__init__.py` 公共接口
- [ ] 模块间无直接访问内部实现（`_private` 前缀保护）

### 6.2 代码质量

- [ ] 所有公共函数有类型注解
- [ ] 所有公共函数有中文文档字符串
- [ ] 无裸 `except:` 异常处理
- [ ] 无 `print()` 调试语句

### 6.3 测试覆盖

- [ ] 后端核心模块 ≥80% 测试覆盖率
- [ ] 前端核心组件 ≥70% 测试覆盖率
- [ ] 每个模块有独立的单元测试文件

### 6.4 架构合规

- [ ] 依赖方向：上层 → 下层，无反向依赖
- [ ] 同层模块间通过接口导入
- [ ] 无循环依赖（通过 `import-linter` 验证）

---

## 七、实施路线图

### 总体时间线

```
Week 1-2:  后端 Phase 1-3（config/utils/safety/storage 整理）
Week 3-4:  后端 Phase 4-5（agent/evolution/memory 整理）
Week 5-6:  后端 Phase 6-7（server 重构 + 测试补充）
Week 7-8:  前端 Phase 1-3（布局/编辑器/AI 组件迁移）
Week 9-10: 前端 Phase 4-6（功能面板/Store 清理/测试）
Week 11-12: 集成测试 + 回归测试 + 文档完善
```

### 里程碑

| 里程碑 | 目标 | 验收方式 |
|--------|------|---------|
| **M1** | 后端基础设施层整理完成 | `config`/`utils`/`safety`/`storage` 可独立导入 |
| **M2** | 后端领域层整理完成 | `agent`/`evolution`/`memory`/`skills`/`extensions` 可独立导入 |
| **M3** | 后端服务层重构完成 | 路由按领域分组，无循环依赖 |
| **M4** | 前端组件目录重组完成 | 5 个组件子目录，App.tsx < 100 行 |
| **M5** | 测试覆盖达标 | 后端 ≥80%，前端 ≥70% |
| **M6** | 全量回归通过 | 所有功能正常，无性能退化 |

---

## 八、风险评估与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| 改造期间功能回归 | 高 | 中 | 每阶段完成后全量回归测试 |
| 循环依赖引入 | 中 | 中 | 使用 `import-linter` CI 检查 |
| 接口变更影响调用方 | 中 | 高 | 保持向后兼容，废弃接口标记 `@deprecated` |
| 测试覆盖不足 | 中 | 高 | 每阶段强制补充测试 |
| 前端构建体积膨胀 | 低 | 低 | 持续监控 Vite chunk 分析 |
| 团队成员学习成本 | 中 | 中 | 编写模块接口文档 + 示例代码 |

---

## 九、工具链支持

| 工具 | 用途 | 安装 |
|------|------|------|
| `import-linter` | 检测循环依赖和依赖方向 | `pip install import-linter` |
| `pydeps` | 可视化模块依赖图 | `pip install pydeps` |
| `pytest-cov` | 后端测试覆盖率 | `pip install pytest-cov` |
| `vitest` | 前端单元测试 | `npm install -D vitest` |
| `@vitest/coverage-v8` | 前端覆盖率 | `npm install -D @vitest/coverage-v8` |
| `madge` | 前端依赖图可视化 | `npm install -D madge` |

---

*此文档由 PyCoder 模块化分析自动生成。*
