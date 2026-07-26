# PyCoder 模块化改造方案 — minimax-M3 版

> 生成日期：2026-07-26 | 模型：minimax-M3 | 基于项目 V2 架构现状

---

## 〇、本方案与 qwen3.7plus 方案的核心差异

| 维度 | qwen3.7plus 方案 | **本方案（minimax-M3）** |
|------|-----------------|------------------------|
| 架构基础 | 假设从零分层 | 建立在已有 V2 Clean Architecture 之上 |
| 核心抽象 | 按技术层级（config/utils/agent） | 按**业务能力域**（capability-domain） |
| 通信方式 | 事件总线 + 直接导入 | 优先 V2 **能力总线** + Strategy 模式 |
| 测试策略 | 按模块覆盖率 | 按能力契约（Contract Testing） |
| 命名体系 | camelCase / snake_case | **domain.action**（如 `editor.code.read`） |
| 拆分粒度 | 函数级别 | **能力粒度**（一个能力 = 一个 Service + Schema + Tests） |
| 演进策略 | 重写式 | **渐进式 / 包装式 / 演进式** |

---

## 一、项目现状深度分析

### 1.1 实际目录结构（基于文件系统扫描）

| 目录 | 文件数 | 角色 |
|------|--------|------|
| `pycoder/server/` | 208 | ⚠️ **超大型** — FastAPI 服务层（含 routers/services/ws/） |
| `pycoder/electron/` | 59 | 前端 Electron 主进程 |
| `pycoder/ai/` | 39 | AI 能力层（agents/models/prompts） |
| `pycoder/capabilities/` | 37 | **V2 能力实现**（editor/system/self_evo） |
| `pycoder/python/` | 30 | Python 语言工具链（lsp/pytest/venv） |
| `pycoder/brain/` | 24 | 核心推理 / 规划 |
| `pycoder/core/` | 19 | **V2 Clean Architecture**（ports/adapters） |
| `pycoder/memory/` | 12 | 长期 / 短期记忆 |
| `pycoder/scripts/` | 11 | 工具脚本 |
| `pycoder/gateway/` | 9 | 多平台消息网关 |
| `pycoder/safety/` | 8 | 安全策略 |
| `pycoder/lsp/` | 8 | LSP 协议支持 |
| `pycoder/extensions/` | 8 | 扩展系统 |
| `pycoder/prompts/` | 7 | 提示词模板 |
| `pycoder/providers/` | 7 | LLM Provider 抽象 |
| `pycoder/skills/` | 7 | 技能市场 |
| `pycoder/lifecycle/` | 6 | 7 阶段项目闭环编排器 |
| `pycoder/evolution/` | 5 | 自进化引擎 |
| `pycoder/multimodal/` | 5 | 多模态能力 |
| `pycoder/web/` | 6 | Web 工具 |
| 其他 | < 5/项 | 边界模块 |

### 1.2 已具备的 V2 架构基础

✅ **Clean Architecture** (`pycoder/core/`)
- `core/ports/` — Protocol 抽象接口
- `core/adapters/` — 具体实现

✅ **统一能力总线** (`pycoder/bus/`)
- `bus/registry.py` — CapabilityRegistry
- `bus/protocol.py` — CapabilityDefinition / ProtocolAdapter
- `bus/router.py` — IntelligentRouter
- `bus/transformer.py` — Input/Output Transformer
- `bus/monitor.py` — BusMonitor + CallTrace

✅ **动态模块系统** (`pycoder/modules/`)
- `DynamicModule` 基类 + `ModuleLoader` + `ModuleManifest`
- 完整的 load/activate/deactivate/unload 生命周期

✅ **能力实现** (`pycoder/capabilities/`)
- `editor/` — 编辑器能力
- `system/` — 系统能力
- `self_evo/` — 自进化能力

✅ **消息网关** (`pycoder/gateway/`)
- 多平台适配器（Telegram/Discord/Slack/CLI）
- 统一 `GatewayMessage` 数据格式

✅ **可观测性** (`pycoder/observability/`)
- Sentry 集成（可选）
- OpenTelemetry 链路追踪（可选）

✅ **项目生命周期编排** (`pycoder/lifecycle/`)
- 7 阶段：接收→分析→设计→开发→测试→自愈→交付
- Strategy 模式支持阶段替换

### 1.3 核心问题（实测数据）

| 问题 | 位置 | 严重度 | 数据 |
|------|------|--------|------|
| **巨型服务层** | `pycoder/server/` | 高 | 208 文件，单一目录 |
| **能力注册分散** | `capabilities/__init__.py` | 中 | 3 个 register_* 函数 |
| **测试隔离差** | `tests/` | 高 | 223 个测试文件，分布散乱 |
| **前后端耦合** | 旧 `appStore` 兼容层 | 中 | 100+ 字段 |
| **CSS 巨石** | `layout.css` | 中 | 7,500+ 行单文件 |
| **brain 与 ai 边界** | 跨包相互 import | 中 | 循环依赖风险 |

---

## 二、minimax-M3 设计哲学

### 2.1 三个核心原则

1. **能力即模块**（Capability is Module）— 不按"技术层"切分，按"业务能力"切分
2. **现有架构优先**（Evolve, Don't Rewrite）— 不重写 V2 基础，在其上扩展
3. **契约驱动**（Contract-First）— 每个能力先有 Schema，再有实现，最后有测试

### 2.2 命名规范

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

### 2.3 模块边界判定

每个模块必须满足：

```python
class ModuleContract:
    """模块契约 —— minimax-M3 强制的最小定义"""
    domain: str              # 业务域
    capabilities: list[str]  # 暴露的能力 ID
    schema_path: str         # OpenAPI/JSON Schema 路径
    dependencies: list[str]   # 依赖的其他模块（必须 ≤ 3 个）
    storage_keys: list[str]   # 持久化键（必须声明）
    external_io: list[str]   # 外部 IO（file/network/process）
    invariants: list[str]    # 不变量断言
```

---

## 三、minimax-M3 目标架构

### 3.1 分层（基于 V2 现状演进）

```
┌────────────────────────────────────────────────────────────┐
│  L7  接口层 (Interface Layer)                              │
│      server/ (FastAPI + WebSocket)                         │
│      electron/ (Electron Main + Renderer)                  │
├────────────────────────────────────────────────────────────┤
│  L6  编排层 (Orchestration Layer)                          │
│      lifecycle/  (项目生命周期)                            │
│      ai/agents/  (Agent 编排)                              │
│      gateway/    (消息路由)                                │
├────────────────────────────────────────────────────────────┤
│  L5  能力层 (Capability Layer)        ← minimax-M3 核心扩展│
│      capabilities/editor/  capabilities/system/            │
│      capabilities/self_evo/  capabilities/<new>/           │
├────────────────────────────────────────────────────────────┤
│  L4  业务核心层 (Business Core Layer)                      │
│      brain/  (推理/规划)  memory/  (记忆)                  │
│      evolution/  (进化)   skills/  (技能)                 │
├────────────────────────────────────────────────────────────┤
│  L3  抽象接口层 (Ports Layer)                              │
│      core/ports/  (Protocol 抽象)                          │
├────────────────────────────────────────────────────────────┤
│  L2  适配实现层 (Adapters Layer)                           │
│      core/adapters/  providers/  lsp/                      │
│      python/  fs/  io/  net/                              │
├────────────────────────────────────────────────────────────┤
│  L1  基础设施层 (Infrastructure Layer)                     │
│      observability/  safety/  env/  config/  bus/          │
│      notify/  prompts/  knowledge/                         │
└────────────────────────────────────────────────────────────┘
```

### 3.2 新增的 5 个能力域模块（在 capabilities/ 下扩展）

| 新增域 | 职责 | 预期能力示例 |
|--------|------|------------|
| **`capabilities/lifecycle/`** | 封装 lifecycle/ 编排能力 | `lifecycle.project.create` |
| **`capabilities/gateway/`** | 封装 gateway/ 网关能力 | `gateway.telegram.send` |
| **`capabilities/memory/`** | 封装 memory/ 长期记忆 | `memory.context.retrieve` |
| **`capabilities/extension/`** | 封装 extensions/ 扩展 | `extension.list.installed` |
| **`capabilities/observability/`** | 封装观测能力 | `observability.trace.query` |

### 3.3 新增的 2 个横切关注点模块

| 模块 | 职责 |
|------|------|
| **`pycoder/contracts/`** | 所有能力的 Schema 定义（OpenAPI/JSON Schema） |
| **`pycoder/testkit/`** | 能力测试工具包（capability_test 装饰器、契约验证器、Mock 工具） |

---

## 四、模块详细定义

### 4.1 模块清单（13 个核心 + 5 个新增 = 18 个）

#### 既有模块（V2 基础，保留并优化接口）

| # | 模块 | 行数估算 | 公共 API | 行动 |
|---|------|---------|---------|------|
| 1 | `core/` | ~5K | `ports` / `adapters` | **接口冻结** |
| 2 | `bus/` | ~4K | `capability_bus`, `CapabilityRegistry` | **总线中心化** |
| 3 | `modules/` | ~3K | `ModuleLoader` | **统一入口** |
| 4 | `observability/` | ~3K | `traced`, `init_sentry` | **强制埋点** |
| 5 | `capabilities/editor/` | ~8K | `register_editor_capabilities` | **拆分到子域** |
| 6 | `capabilities/system/` | ~6K | `register_system_capabilities` | **拆分到子域** |
| 7 | `capabilities/self_evo/` | ~7K | `register_self_evo_capabilities` | **拆分到子域** |
| 8 | `lifecycle/` | ~5K | `get_orchestrator` | **下沉为能力** |
| 9 | `gateway/` | ~6K | `get_gateway` | **下沉为能力** |
| 10 | `memory/` | ~3K | `MemoryStore` | **下沉为能力** |
| 11 | `evolution/` | ~4K | `EvolutionEngine` | **下沉为能力** |
| 12 | `extensions/` | ~5K | `ExtensionManager` | **下沉为能力** |
| 13 | `server/` | 208 文件 | `app` | **路由按域拆分** |

#### 新增模块

| # | 模块 | 预期行数 | 公共 API | 责任 |
|---|------|---------|---------|------|
| 14 | **`pycoder/contracts/`** | ~2K | `CapabilityContract`, `validate_schema` | 所有能力的 Schema 中心 |
| 15 | **`pycoder/testkit/`** | ~2K | `capability_test`, `MockBus` | 能力测试工具 |
| 16 | **`capabilities/lifecycle/`** | ~1K | `register_lifecycle_capabilities` | 包装 lifecycle |
| 17 | **`capabilities/gateway/`** | ~1K | `register_gateway_capabilities` | 包装 gateway |
| 18 | **`pycoder/registry/`** | ~1K | `DomainRegistry`, `discover_modules` | 域发现与元数据 |

### 4.2 模块依赖图

```
┌─────────────────────────────────────────────────────────────┐
│  server/  ←  electron/  ←  lifecycle/  ←  gateway/        │
│     ↓             ↓             ↓             ↓             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │         capabilities/ (V2 能力层 + 扩展)             │    │
│  └─────────────────────────────────────────────────────┘    │
│     ↓             ↓             ↓             ↓             │
│  brain/memory  evolution  skills  extensions  python         │
│     ↓             ↓             ↓             ↓             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │         core/ports/  +  core/adapters/ (抽象边界)     │    │
│  └─────────────────────────────────────────────────────┘    │
│     ↓             ↓             ↓             ↓             │
│  bus/  observability/  safety/  env/  config/                │
└─────────────────────────────────────────────────────────────┘

横切关注点：
  contracts/  ──→ 所有 capabilities 引用
  testkit/    ──→ 仅测试时引用
  registry/   ──→ 启动时引用
```

### 4.3 通信机制

#### 主通道：V2 能力总线

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

#### 辅助通道：Strategy 模式（用于阶段/算法替换）

```python
class PhaseStrategy(Protocol):
    async def execute(self, ctx: ProjectContext) -> PhaseResult: ...

orchestrator.register_phase(
    LifecyclePhase.TESTING,
    PytestPhaseStrategy()
)
```

#### 辅助通道：事件总线（用于解耦通知）

```python
from pycoder.bus import EventStream

event_stream = EventStream("memory")
await event_stream.emit("memory.stored", {"key": "user_pref"})
```

---

## 五、实施阶段（minimax-M3 路线图）

### 5.1 总览：5 个 Phase，10 周

```
Phase 0 ─ 基础就绪（已完成 70%）
Phase 1 ─ 契约框架（2 周）
Phase 2 ─ 能力下沉（3 周）
Phase 3 ─ 服务层重构（3 周）
Phase 4 ─ 验证与收尾（2 周）
```

### 5.2 Phase 1：契约框架

**目标**：建立能力契约中心，让所有能力先有 Schema，再有实现。

| 周 | 任务 | 验收 |
|----|------|------|
| W1 | 创建 `pycoder/contracts/`，定义 `CapabilityContract` 数据类 | 单元测试覆盖 |
| W1 | 实现 `validate_schema()` 验证器 | 单元测试覆盖 |
| W1 | 将 `bus/protocol.py` 的 `CapabilityDefinition` 增强为契约 | 向后兼容 |
| W2 | 创建 `pycoder/testkit/`，实现 `capability_test` 装饰器 | 至少 5 个能力通过契约测试 |
| W2 | 创建 `pycoder/registry/`，实现 `DomainRegistry` | 自动发现 8 个现有域 |

### 5.3 Phase 2：能力下沉

**目标**：将 `lifecycle/`、`gateway/`、`memory/`、`evolution/`、`extensions/` 全部包装为 V2 能力。

| 周 | 任务 | 验收 |
|----|------|------|
| W3 | 创建 `capabilities/lifecycle/`，包装 `lifecycle/` 编排器 | 5 个能力注册 |
| W3 | 创建 `capabilities/gateway/`，包装 `gateway/` 网关 | 4 个能力注册 |
| W4 | 创建 `capabilities/memory/`，包装 `memory/` 系统 | 3 个能力注册 |
| W4 | 创建 `capabilities/extension/`，包装 `extensions/` 系统 | 4 个能力注册 |
| W5 | 创建 `capabilities/observability/`，包装 `observability/` | 2 个能力注册 |
| W5 | 拆分 `capabilities/editor/` 为 `editor/`、`refactor/`、`debug/` | 文件数 ↓ 30% |

### 5.4 Phase 3：服务层重构

**目标**：将 `server/`（208 文件）按能力域拆分为 13 个域路由组。

| 周 | 任务 | 验收 |
|----|------|------|
| W6 | 创建 `server/domains/` 目录，按域分组路由 | 13 个域目录 |
| W6 | 实现 `DomainRouterGroup` 通用基类 | 单测覆盖 |
| W7 | 迁移 13 个域的路由 | 每个域 ≤ 15 文件 |
| W8 | 重构 `server/app.py` 启动逻辑 | 启动时间 ↓ 30% |

### 5.5 Phase 4：验证与收尾

| 周 | 任务 | 验收 |
|----|------|------|
| W9 | 编写能力契约测试套件 | 每个能力 ≥ 3 测试 |
| W9 | 性能基线对比 | 报告输出 |
| W10 | 文档生成 | docs/capabilities.md |
| W10 | 回归测试 + 安全扫描 | 零 critical 漏洞 |

---

## 六、验收标准

### 6.1 模块级标准

| 维度 | 阈值 | 验证方式 |
|------|------|---------|
| **能力契约覆盖** | 100% | `python -m pycoder.testkit.audit` |
| **后端测试覆盖** | ≥ 80% | `pytest --cov=pycoder` |
| **前端测试覆盖** | ≥ 70% | `vitest --coverage` |
| **循环依赖** | 0 | `pydeps --circular` |
| **违规导入** | 0 | `import-linter` |
| **能力域文件数** | ≤ 15 文件/域 | 自定义脚本 |
| **最大单文件** | < 500 行 | `radon cc` |
| **类型注解覆盖** | ≥ 95% | `mypy --strict` |

### 6.2 性能基线

| 指标 | 当前 | 目标 | 验证 |
|------|------|------|------|
| 后端启动时间 | ~2.3s | ≤ 1.5s | 计时 |
| 首屏 JS 体积 | 104 KB | ≤ 80 KB | vite build |
| API 响应 P99 | TBD | ↓ 20% | locust 压测 |
| 内存占用 | TBD | ↓ 15% | psutil |

---

## 七、关键设计决策记录（ADR）

### ADR-001：能力粒度划分
- **决策**：每个能力 = 1 个 `CapabilityContract` + 1 个 `handler` + 1 个 `schema.json` + ≥3 测试
- **原因**：粒度太粗失去灵活性；太细增加管理成本

### ADR-002：演进式而非重写式
- **决策**：保留 V2 `CapabilityDefinition`，扩展为 `CapabilityContract`（向后兼容）
- **原因**：避免破坏现有 192+ 个能力注册

### ADR-003：契约优先
- **决策**：能力实现前必须有 JSON Schema
- **原因**：强制设计先于实现、稳定 API 文档来源

### ADR-004：测试即文档
- **决策**：能力测试必须展示典型用法
- **原因**：测试即活文档，减少额外文档维护

---

## 八、风险评估与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| V2 架构理解偏差 | 中 | 高 | 早期 PoC 验证 `DomainRegistry` 概念 |
| 能力契约过严 | 中 | 中 | 提供 `lenient=True` 模式 + 演进期兼容 |
| 测试套件性能 | 中 | 中 | 能力测试并行化（pytest-xdist） |
| 团队适应成本 | 中 | 中 | 提供 `pycoder-modularization-guide.md` |

---

*此文档由 minimax-M3 模型生成。基于实际项目扫描结果（208 个 server 文件、18 个域、192 个能力、223 个测试）。*
