# Pycoder V2 架构重设计：以 AI 为核心的智能编辑器

> 版本: 2.0.0-alpha  
> 日期: 2026-07-11  
> 状态: 架构设计阶段  

---

## 目录

1. [设计哲学](#1-设计哲学)
2. [架构全景图](#2-架构全景图)
3. [AI 大脑核心](#3-ai-大脑核心)
4. [统一能力总线](#4-统一能力总线)
5. [编辑器能力模块](#5-编辑器能力模块)
6. [自我进化引擎](#6-自我进化引擎)
7. [动态模块系统](#7-动态模块系统)
8. [安全与权限体系](#8-安全与权限体系)
9. [数据流与交互协议](#9-数据流与交互协议)
10. [V1 → V2 迁移路径](#10-v1--v2-迁移路径)

---

## 1. 设计哲学

### 1.1 核心理念：编辑器是身体，AI 是大脑

```
传统编辑器:  [编辑器核心] + [AI 插件]     ← AI 是附属功能
Pycoder V2:  [AI 大脑] × [编辑器能力]     ← AI 是控制中枢
```

**V1 的问题**：当前 Pycoder 虽然拥有丰富的 AI 能力（Agent 系统、自主流水线、自我进化），但 AI 仍然是一个"服务层"——它被动响应用户请求，通过工具调用间接操作编辑器。AI 无法：

- 主动感知项目状态变化并自主行动
- 修改 Pycoder 自身的源代码并热重载
- 动态扩展自身的能力边界
- 将自身作为一等公民参与架构决策

**V2 的目标**：让 AI 成为编辑器的操作系统，编辑器的一切功能都是 AI 可以调用的"硬件资源"。

### 1.2 四大设计原则

| 原则 | 说明 |
|------|------|
| **AI 即中枢** (AI as Kernel) | AI 是系统的核心调度者，所有功能通过 AI 协调执行 |
| **能力即服务** (Capability as Service) | 编辑器、系统、自进化能力全部通过统一接口暴露 |
| **自我指涉** (Self-Referential) | AI 能将自己的源代码作为普通项目进行分析和修改 |
| **渐进信任** (Graduated Trust) | 权限逐级开放，AI 用能力证明换取更大自主权 |

---

## 2. 架构全景图

### 2.1 分层架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                      PRESENTATION LAYER                          │
│                                                                  │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐    │
│   │ Electron │   │   Web    │   │   CLI    │   │  VS Code │    │
│   │   IDE    │   │   PWA    │   │  (Rich)  │   │ Extension│    │
│   └────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘    │
│        └───────────────┴──────────────┴──────────────┘           │
│                            │                                      │
│                 Intent Protocol (WebSocket + SSE)                 │
├────────────────────────────┼──────────────────────────────────────┤
│                            ▼                                      │
│   ┌─────────────────────────────────────────────────────────┐    │
│   │                   AI BRAIN KERNEL                        │    │
│   │                                                          │    │
│   │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │    │
│   │  │ Consciousness│  │    Task      │  │    Agent     │   │    │
│   │  │    Engine    │  │   Planner    │  │   Swarm Mgr  │   │    │
│   │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │    │
│   │         └─────────────────┼─────────────────┘            │    │
│   │                           ▼                              │    │
│   │  ┌──────────────────────────────────────────────────┐   │    │
│   │  │            Context & Memory Engine                │   │    │
│   │  │  ┌─────────┐ ┌──────────┐ ┌──────────────────┐   │   │    │
│   │  │  │Working  │ │ Project  │ │  Long-term       │   │   │    │
│   │  │  │Memory   │ │ Knowledge│ │  Knowledge Base  │   │   │    │
│   │  │  └─────────┘ └──────────┘ └──────────────────┘   │   │    │
│   │  └──────────────────────────────────────────────────┘   │    │
│   └─────────────────────────┬───────────────────────────────┘    │
│                              │                                    │
├──────────────────────────────┼────────────────────────────────────┤
│                              ▼                                    │
│   ┌─────────────────────────────────────────────────────────┐    │
│   │              UNIFIED CAPABILITY BUS                      │    │
│   │              (MCP Protocol v2 + gRPC)                    │    │
│   │                                                          │    │
│   │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │    │
│   │  │Registry  │  │ Router   │  │Transform │  │Monitor   │ │    │
│   │  │          │  │          │  │          │  │          │ │    │
│   │  └──────────┘  └──────────┘  └──────────┘  └──────────┘ │    │
│   └─────────────────────────┬───────────────────────────────┘    │
│                              │                                    │
├──────────────────────────────┼────────────────────────────────────┤
│                              ▼                                    │
│   ┌─────────────────────────────────────────────────────────┐    │
│   │                 CAPABILITY DOMAINS                       │    │
│   │                                                          │    │
│   │  ┌────────────┐ ┌────────────┐ ┌────────────────────┐   │    │
│   │  │  Editor    │ │  System    │ │   Self-Evolution   │   │    │
│   │  │  Domain    │ │  Domain    │ │   Domain           │   │    │
│   │  ├────────────┤ ├────────────┤ ├────────────────────┤   │    │
│   │  │• CodeEdit  │ │• FileOps   │ │• CodeAnalyze       │   │    │
│   │  │• LSP       │ │• ShellExec │ │• SelfFix           │   │    │
│   │  │• Refactor  │ │• GitOps    │ │• SelfTest          │   │    │
│   │  │• Debug     │ │• PkgMgmt   │ │• SelfDeploy        │   │    │
│   │  │• Format    │ │• Process   │ │• ArchEvo           │   │    │
│   │  │• Search    │ │• Network   │ │• LearningLoop      │   │    │
│   │  │• Preview   │ │• Database  │ │• HotReload         │   │    │
│   │  │• Diff      │ │• EnvDetect │ │• PerfOptimize      │   │    │
│   │  └────────────┘ └────────────┘ └────────────────────┘   │    │
│   │                                                          │    │
│   │  ┌──────────────────────────────────────────────────┐   │    │
│   │  │           DYNAMIC MODULE SLOTS                    │   │    │
│   │  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐    │   │    │
│   │  │  │Plugin A│ │Plugin B│ │Plugin C│ │  ...   │    │   │    │
│   │  │  └────────┘ └────────┘ └────────┘ └────────┘    │   │    │
│   │  └──────────────────────────────────────────────────┘   │    │
│   └─────────────────────────────────────────────────────────┘    │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌─────────────────────────────────────────────────────────┐    │
│   │              SAFETY & GOVERNANCE LAYER                   │    │
│   │                                                          │    │
│   │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐     │    │
│   │  │ Permission   │ │  Sandbox     │ │  Audit       │     │    │
│   │  │ Engine       │ │  Manager     │ │  Trail       │     │    │
│   │  │ (5 Levels)   │ │  (WASM/Docker│ │  (Immutable) │     │    │
│   │  └──────────────┘ └──────────────┘ └──────────────┘     │    │
│   │                                                          │    │
│   │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐     │    │
│   │  │ Rollback     │ │  Circuit     │ │  Human-in-   │     │    │
│   │  │ Manager      │ │  Breaker     │ │  the-Loop    │     │    │
│   │  └──────────────┘ └──────────────┘ └──────────────┘     │    │
│   └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 与 V1 架构的关键差异

| 维度 | V1 (当前) | V2 (目标) |
|------|----------|----------|
| AI 定位 | 服务层，被动响应 | 核心层，主动控制 |
| 能力暴露 | 各模块独立 API | 统一能力总线 |
| 自我修改 | 有自进化但受限 | 完整自我指涉闭环 |
| 模块系统 | 静态扩展/插件 | AI 可按需动态加载 |
| 权限控制 | 4 级简单分类 | 5 级渐进信任 + 审计 |
| AI 感知 | 请求-响应 | 持续感知项目状态 |
| 编辑器关系 | AI 辅助编辑器 | AI 是编辑器的大脑 |

---

## 3. AI 大脑核心

AI 大脑是整个系统的中枢神经，不再是简单的聊天处理器，而是一个**持续运行的智能代理**。

### 3.1 意识引擎 (Consciousness Engine)

```
┌─────────────────────────────────────────────────┐
│              CONSCIOUSNESS ENGINE                │
│                                                  │
│  ┌────────────┐  ┌──────────┐  ┌────────────┐   │
│  │ Perception │  │Attention │  │  Intention  │   │
│  │   Layer    │→ │  Manager │→ │  Generator  │   │
│  └────────────┘  └──────────┘  └────────────┘   │
│       │               │               │          │
│       ▼               ▼               ▼          │
│  ┌────────────┐  ┌──────────┐  ┌────────────┐   │
│  │File Watcher│  │Priority  │  │Action Queue │   │
│  │Git Monitor │  │Scoring   │  │Scheduler    │   │
│  │Test Runner │  │Model     │  │             │   │
│  │LSP Events  │  │          │  │             │   │
│  └────────────┘  └──────────┘  └────────────┘   │
│                                                  │
│  Operating Modes:                                │
│  • IDLE    — 低功耗监听，仅处理关键事件           │
│  • AWARE   — 主动感知，分析变化，预判需求          │
│  • FOCUSED — 全速运行，执行复杂任务               │
│  • REFLECT — 回顾已完成任务，总结经验              │
└─────────────────────────────────────────────────┘
```

**感知层 (Perception Layer)**：
- **文件监听器**：实时监控工作区所有文件变化（增/删/改）
- **Git 监听器**：追踪提交、分支切换、合并冲突
- **测试监听器**：自动运行相关测试，感知回归
- **LSP 事件流**：语法错误、类型错误、警告实时反馈
- **系统事件**：进程崩溃、端口占用、磁盘空间

**注意力管理器 (Attention Manager)**：
- 优先级评分模型：综合紧迫性、影响范围、用户关注度
- 事件去重与聚合：100 次文件保存 → 1 次分析触发
- 上下文切换成本计算：决定是否打断当前任务
- 焦虑阈值：问题严重度超过阈值时主动"打扰"用户

**意图生成器 (Intention Generator)**：
- 从感知事件推理用户意图
- 生成主动行动建议："检测到 3 个 TODO，要我帮你处理吗？"
- 预加载相关上下文：打开文件 A → 预分析其依赖

### 3.2 任务规划器 (Task Planner)

```
用户意图: "给用户模块添加 JWT 认证"
         │
         ▼
┌──────────────────────────────────────────────┐
│              TASK PLANNER                     │
│                                               │
│  ① 理解与分解 (Understand & Decompose)         │
│     ├─ 语义分析：识别关键实体和动作              │
│     ├─ 上下文注入：当前项目结构、已有代码         │
│     └─ 输出：任务依赖图 (DAG)                   │
│                                               │
│  ② 策略选择 (Strategy Selection)               │
│     ├─ 简单任务 → sequential_single_agent       │
│     ├─ 中等任务 → parallel_specialized_agents   │
│     └─ 复杂任务 → full_sdlc_pipeline            │
│                                               │
│  ③ 资源评估 (Resource Estimation)              │
│     ├─ Token 预算估算                           │
│     ├─ 时间估算                                 │
│     └─ 风险点标记                               │
│                                               │
│  ④ 动态重规划 (Dynamic Replanning)             │
│     ├─ 子任务失败 → 重新规划剩余任务              │
│     ├─ 新信息出现 → 调整策略                     │
│     └─ 用户干预 → 合并用户反馈                   │
└──────────────────────────────────────────────┘
```

### 3.3 Agent 集群编排器 (Agent Swarm Orchestrator)

```
┌──────────────────────────────────────────────────────┐
│                AGENT SWARM ORCHESTRATOR               │
│                                                       │
│  ┌───────────────────────────────────────────────┐   │
│  │              角色工厂 (Role Factory)           │   │
│  │                                                │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐       │   │
│  │  │Architect │ │Developer │ │  Tester  │ ...   │   │
│  │  │   Agent  │ │  Agent   │ │  Agent   │       │   │
│  │  └──────────┘ └──────────┘ └──────────┘       │   │
│  └───────────────────────────────────────────────┘   │
│                         │                             │
│                         ▼                             │
│  ┌───────────────────────────────────────────────┐   │
│  │          并行执行引擎 (Parallel Executor)       │   │
│  │                                                │   │
│  │   Task A ──→ Agent 1 ──┐                       │   │
│  │   Task B ──→ Agent 2 ──┼──→ Merger ──→ Result  │   │
│  │   Task C ──→ Agent 3 ──┘                       │   │
│  │                                                │   │
│  │   依赖感知调度：C 依赖 A → C 等 A 完成后启动      │   │
│  └───────────────────────────────────────────────┘   │
│                         │                             │
│                         ▼                             │
│  ┌───────────────────────────────────────────────┐   │
│  │          结果聚合器 (Result Aggregator)         │   │
│  │                                                │   │
│  │  • 代码合并（冲突解决）                          │   │
│  │  • 质量审查（交叉验证）                          │   │
│  │  • 统一提交（原子性保证）                        │   │
│  └───────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────┘
```

### 3.4 上下文与记忆引擎 (Context & Memory Engine)

```
┌──────────────────────────────────────────────────────┐
│             CONTEXT & MEMORY ENGINE                   │
│                                                       │
│  ┌─────────────────────┐  ┌──────────────────────┐   │
│  │   Working Memory    │  │   Episodic Memory    │   │
│  │   (会话级，实时)      │  │   (会话级，历史)       │   │
│  │                     │  │                      │   │
│  │ • 当前对话上下文      │  │ • 对话历史摘要         │   │
│  │ • 打开的文件状态      │  │ • 已执行的工具调用      │   │
│  │ • 未完成的任务        │  │ • 用户反馈记录         │   │
│  │ • 滑窗截断 + 摘要     │  │ • 成功/失败模式        │   │
│  └─────────────────────┘  └──────────────────────┘   │
│                                                       │
│  ┌─────────────────────┐  ┌──────────────────────┐   │
│  │  Project Knowledge  │  │  Long-term Knowledge │   │
│  │  (项目级，持久)       │  │  (跨项目，积累)        │   │
│  │                     │  │                      │   │
│  │ • 架构决策记录 (ADR) │  │ • 用户编码偏好         │   │
│  │ • 项目约定与规范      │  │ • 常用技术栈模式       │   │
│  │ • 依赖关系图          │  │ • 错误修复知识库       │   │
│  │ • API 文档索引        │  │ • 最佳实践积累         │   │
│  │ • 代码库向量索引      │  │ • 外部文档缓存         │   │
│  └─────────────────────┘  └──────────────────────┘   │
│                                                       │
│  检索策略:                                             │
│  • 关键词匹配 → BM25                                  │
│  • 语义相似 → Embedding + Vector Search               │
│  • 图遍历 → 依赖关系链追踪                             │
│  • 混合检索 → 多路召回 + 重排序                        │
└──────────────────────────────────────────────────────┘
```

---

## 4. 统一能力总线

统一能力总线是所有模块与 AI 大脑之间唯一的通信通道。任何模块想被 AI 调用，必须在此注册。

### 4.1 总线架构

```
┌──────────────────────────────────────────────────────────┐
│                  UNIFIED CAPABILITY BUS                   │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │                 CAPABILITY REGISTRY                  │ │
│  │                                                      │ │
│  │  每个能力的注册信息:                                   │ │
│  │  {                                                   │ │
│  │    "id": "editor.code.apply_edit",                    │ │
│  │    "version": "1.0.0",                                │ │
│  │    "description": "应用代码编辑到文件",                 │ │
│  │    "schema": {  // JSON Schema 参数定义               │ │
│  │      "type": "object",                                │ │
│  │      "properties": {                                  │ │
│  │        "path": {"type": "string"},                    │ │
│  │        "edits": {"type": "array", ... }               │ │
│  │      }                                                │ │
│  │    },                                                 │ │
│  │    "permission": "workspace_write",                    │ │
│  │    "execution": "sync",                               │ │
│  │    "side_effects": ["file_write"],                     │ │
│  │    "rollback_support": true,                           │ │
│  │    "timeout_ms": 5000,                                 │ │
│  │    "retry_policy": {"max_retries": 2, "backoff": 1.5} │ │
│  │  }                                                    │ │
│  └─────────────────────────────────────────────────────┘ │
│                         │                                 │
│  ┌──────────────────────┼──────────────────────────────┐ │
│  │                  INTELLIGENT ROUTER                  │ │
│  │                                                      │ │
│  │  ┌──────────┐   ┌──────────┐   ┌──────────┐        │ │
│  │  │Load      │   │Semantic  │   │Fallback  │        │ │
│  │  │Balancer  │   │Router    │   │Chain     │        │ │
│  │  └──────────┘   └──────────┘   └──────────┘        │ │
│  │                                                      │ │
│  │  功能:                                               │ │
│  │  • 根据能力 ID 或语义描述路由到正确实现                │ │
│  │  • 多个实现提供同一能力时，选择最优（负载/延迟/质量）   │ │
│  │  • 能力不存在时，尝试组合现有能力或建议安装插件         │ │
│  └─────────────────────────────────────────────────────┘ │
│                         │                                 │
│  ┌──────────────────────┼──────────────────────────────┐ │
│  │               PROTOCOL ADAPTERS                      │ │
│  │                                                      │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │ │
│  │  │MCP v2    │  │ gRPC     │  │Internal  │          │ │
│  │  │(外部扩展) │  │(高性能)   │  │(内置模块)  │          │ │
│  │  └──────────┘  └──────────┘  └──────────┘          │ │
│  └─────────────────────────────────────────────────────┘ │
│                         │                                 │
│  ┌──────────────────────┼──────────────────────────────┐ │
│  │                OBSERVABILITY                         │ │
│  │                                                      │ │
│  │  • 每次调用的全链路追踪 (trace_id)                     │ │
│  │  • 延迟、成功率、错误率实时监控                        │ │
│  │  • 能力调用图谱 (谁调用了谁，频率如何)                  │ │
│  │  • 成本归因 (每次调用的 token 消耗)                    │ │
│  └──────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

### 4.2 能力分类体系

```python
class CapabilityCategory(enum.Enum):
    """能力的三大类别"""
    
    EDITOR = "editor"           # 编辑器能力：代码编辑、LSP、重构、格式化
    SYSTEM = "system"           # 系统能力：文件操作、Shell、Git、网络
    SELF_EVO = "self_evo"       # 自进化能力：代码分析、自修复、自部署
    PLUGIN = "plugin"           # 动态插件能力：第三方扩展
```

### 4.3 标准能力清单

下面是 V2 中所有标准能力的完整目录：

#### 4.3.1 编辑器能力域

| 能力 ID | 说明 | 权限级别 |
|---------|------|---------|
| `editor.code.read` | 读取源代码文件 | L0 (只读) |
| `editor.code.write` | 写入/修改源代码 | L1 (工作区写) |
| `editor.code.create` | 创建新文件/目录 | L1 |
| `editor.code.delete` | 删除文件/目录 | L1 |
| `editor.code.search` | 全文搜索 | L0 |
| `editor.code.grep` | 正则搜索 | L0 |
| `editor.code.replace_bulk` | 批量替换 | L1 |
| `editor.lsp.complete` | 代码补全 | L0 |
| `editor.lsp.diagnostics` | 诊断信息 | L0 |
| `editor.lsp.references` | 查找引用 | L0 |
| `editor.lsp.definition` | 跳转定义 | L0 |
| `editor.lsp.rename` | 符号重命名 | L1 |
| `editor.refactor.extract_function` | 提取函数 | L1 |
| `editor.refactor.extract_variable` | 提取变量 | L1 |
| `editor.refactor.inline` | 内联 | L1 |
| `editor.refactor.move_symbol` | 移动符号 | L1 |
| `editor.format.apply` | 应用格式化 | L1 |
| `editor.format.configure` | 配置格式化规则 | L1 |
| `editor.debug.start` | 启动调试 | L2 |
| `editor.debug.set_breakpoint` | 设置断点 | L1 |
| `editor.debug.evaluate` | 求值表达式 | L1 |
| `editor.debug.step` | 单步执行 | L2 |
| `editor.preview.html` | 预览 HTML | L0 |
| `editor.preview.markdown` | 预览 Markdown | L0 |
| `editor.preview.image` | 预览图片 | L0 |
| `editor.diff.compare` | 比较差异 | L0 |
| `editor.diff.apply` | 应用差异 | L1 |
| `editor.symbol.outline` | 符号大纲 | L0 |

#### 4.3.2 系统能力域

| 能力 ID | 说明 | 权限级别 |
|---------|------|---------|
| `system.file.list` | 列出目录 | L0 |
| `system.file.stat` | 文件信息 | L0 |
| `system.file.move` | 移动文件 | L1 |
| `system.file.watch` | 监听文件变化 | L0 |
| `system.shell.execute` | 执行 Shell 命令 | L2 |
| `system.shell.interactive` | 交互式 Shell | L2 |
| `system.git.status` | Git 状态 | L0 |
| `system.git.diff` | Git 差异 | L0 |
| `system.git.commit` | Git 提交 | L1 |
| `system.git.branch` | 分支操作 | L1 |
| `system.git.push` | 推送 | L2 |
| `system.package.install` | 安装包 | L2 |
| `system.package.remove` | 卸载包 | L2 |
| `system.package.list` | 列出已安装包 | L0 |
| `system.package.audit` | 安全审计 | L0 |
| `system.process.list` | 列出进程 | L0 |
| `system.process.kill` | 终止进程 | L2 |
| `system.network.http` | HTTP 请求 | L2 |
| `system.network.websocket` | WebSocket 连接 | L2 |
| `system.database.query` | 数据库查询 | L2 |
| `system.env.detect` | 环境检测 | L0 |
| `system.env.set_var` | 设置环境变量 | L2 |

#### 4.3.3 自进化能力域

| 能力 ID | 说明 | 权限级别 |
|---------|------|---------|
| `self_evo.code.scan` | 扫描代码问题 | L3 |
| `self_evo.code.fix` | 生成修复方案 | L3 |
| `self_evo.code.apply_fix` | 应用修复 | L4 |
| `self_evo.test.run` | 运行自身测试 | L3 |
| `self_evo.test.coverage` | 测试覆盖率 | L3 |
| `self_evo.deploy.hot_reload` | 热重载模块 | L4 |
| `self_evo.deploy.restart` | 重启服务 | L4 |
| `self_evo.deploy.rollback` | 回滚变更 | L4 |
| `self_evo.arch.analyze` | 架构分析 | L3 |
| `self_evo.arch.propose` | 架构改进建议 | L3 |
| `self_evo.arch.implement` | 实施架构改进 | L4 |
| `self_evo.learn.record` | 记录学习经验 | L3 |
| `self_evo.learn.retrieve` | 检索历史经验 | L0 |
| `self_evo.perf.profile` | 性能分析 | L3 |
| `self_evo.perf.optimize` | 性能优化 | L4 |

---

## 5. 编辑器能力模块

### 5.1 代码编辑引擎

```
┌─────────────────────────────────────────────────┐
│            CODE EDITING ENGINE                   │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │  AST     │  │  Text    │  │  Multi-  │       │
│  │  Editor  │  │  Editor  │  │  File    │       │
│  │          │  │          │  │  Editor  │       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
│       └──────────────┼──────────────┘            │
│                      ▼                            │
│  ┌──────────────────────────────────────────┐    │
│  │         Transaction Manager              │    │
│  │  • 原子性：要么全部成功，要么全部回滚       │    │
│  │  • 隔离性：并发编辑不互相干扰              │    │
│  │  • 持久性：变更前自动快照 (git stash)       │    │
│  └──────────────────────────────────────────┘    │
│                      │                            │
│                      ▼                            │
│  ┌──────────────────────────────────────────┐    │
│  │         Undo/Redo Stack                   │    │
│  │  • 无限撤销层级                            │    │
│  │  • 按文件/按操作分组                       │    │
│  │  • 支持 AI 操作的批量回滚                  │    │
│  └──────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

**智能编辑特性**：
- **AST 感知编辑**：不是文本替换，而是语义级别的代码修改
- **意图理解**：AI 说"把认证逻辑提取到中间件"→ 自动定位相关代码、提取、重构
- **影响分析**：修改前自动分析影响范围（哪些文件、哪些测试会受影响）
- **智能冲突解决**：AI 修改与用户手动修改冲突时，语义级合并

### 5.2 LSP 集成

```
┌─────────────────────────────────────────────────┐
│              LSP INTEGRATION                     │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │        LSP Manager (多服务器管理)          │   │
│  │                                           │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐        │   │
│  │  │Pyright │ │Ruff    │ │Tailwind│ ...    │   │
│  │  │Server  │ │Server  │ │Server  │        │   │
│  │  └────────┘ └────────┘ └────────┘        │   │
│  └──────────────────────────────────────────┘   │
│                      │                            │
│  ┌───────────────────┼───────────────────────┐   │
│  │           LSP Event Stream                 │   │
│  │                                            │   │
│  │  诊断事件 → 意识引擎 → AI 主动修复           │   │
│  │  补全事件 → AI 上下文增强 → 更智能补全        │   │
│  │  引用事件 → 依赖分析 → 影响范围评估           │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

### 5.3 重构引擎

AI 驱动的重构不仅仅是文本替换，而是语义级别的代码变换：

- **安全重构**：重构前后运行测试，确保行为不变
- **跨文件重构**：自动追踪所有引用点
- **渐进式重构**：大重构分步骤，每步可验证
- **AI 建议**：主动发现代码异味并建议重构方案

---

## 6. 自我进化引擎

这是 V2 最核心的差异化能力——AI 能够分析、修改、测试、部署 Pycoder 自身的源代码。

### 6.1 自我指涉架构

```
┌──────────────────────────────────────────────────────────┐
│                 SELF-EVOLUTION ENGINE                     │
│                                                           │
│   ┌───────────────────────────────────────────────────┐  │
│   │                  进化生命周期                        │  │
│   │                                                    │  │
│   │  ① SCAN    ② ANALYZE   ③ PROPOSE   ④ IMPLEMENT    │  │
│   │  扫描代码  → 分析问题  →  提出方案  →  实施修改     │  │
│   │     │          │           │           │           │  │
│   │     └──────────┴───────────┴───────────┘           │  │
│   │                      │                              │  │
│   │                      ▼                              │  │
│   │  ⑧ LEARN    ⑦ DEPLOY    ⑥ VERIFY    ⑤ TEST       │  │
│   │  记录经验  ← 部署上线  ←  人工审查  ←  运行测试     │  │
│   └───────────────────────────────────────────────────┘  │
│                                                           │
│   ┌───────────────────────────────────────────────────┐  │
│   │              代码自认知系统                         │  │
│   │                                                    │  │
│   │  SelfModel: Pycoder 对自身代码库的动态模型          │  │
│   │  ┌──────────┐  ┌──────────┐  ┌──────────┐        │  │
│   │  │Module    │  │Interface │  │Dependency│        │  │
│   │  │Graph     │  │Registry  │  │Graph     │        │  │
│   │  └──────────┘  └──────────┘  └──────────┘        │  │
│   │                                                    │  │
│   │  • 知道每个模块的功能和接口                          │  │
│   │  • 了解模块间的依赖关系                              │  │
│   │  • 能评估修改的影响范围                              │  │
│   │  • 能生成自己的 API 文档                             │  │
│   └───────────────────────────────────────────────────┘  │
│                                                           │
│   ┌───────────────────────────────────────────────────┐  │
│   │              安全进化约束                           │  │
│   │                                                    │  │
│   │  • 关键路径保护：config、认证、数据库永不自动修改     │  │
│   │  • 渐进式变更：每次最多修改 3 个文件                  │  │
│   │  • 测试门禁：修改后必须通过全部测试                   │  │
│   │  • 人工审查点：Level 4 操作需要人工确认               │  │
│   │  • 自动回滚：任何一步失败立即回滚                     │  │
│   │  • Git 保护：self_evo 分支，不影响 master            │  │
│   └───────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### 6.2 热重载系统

```python
class HotReloadManager:
    """
    AI 修改自身代码后，安全地热重载模块。
    
    策略:
    1. 可热重载的模块（无状态工具函数）→ 直接 importlib.reload
    2. 有状态但可重建的模块 → 保存状态 → reload → 恢复状态
    3. 核心服务模块 → 优雅重启（等请求处理完再重启）
    4. 不可热重载的模块 → 标记需要完整重启
    """
    
    def can_hot_reload(self, module_path: str) -> ReloadStrategy:
        """判断模块的最佳重载策略"""
        
    def safe_reload(self, module_path: str) -> ReloadResult:
        """安全热重载，失败自动回滚"""
```

### 6.3 学习循环

```
┌────────────────────────────────────────────┐
│              LEARNING LOOP                  │
│                                             │
│  ┌─────────┐     ┌─────────┐               │
│  │ 执行任务 │────→│ 记录结果 │               │
│  └─────────┘     └────┬────┘               │
│       ↑                │                    │
│       │                ▼                    │
│  ┌────┴────┐     ┌─────────┐               │
│  │ 优化策略 │←────│ 分析模式 │               │
│  └─────────┘     └─────────┘               │
│                                             │
│  学习维度:                                   │
│  • 什么类型的修复方案最有效？                 │
│  • 哪些模块最容易出问题？                     │
│  • 哪种代码风格产生最少 bug？                │
│  • 什么情况下应该建议人工介入？               │
│  • 用户的反馈偏好是什么？                     │
└────────────────────────────────────────────┘
```

---

## 7. 动态模块系统

### 7.1 模块生命周期

```
┌──────────────────────────────────────────────────────┐
│              DYNAMIC MODULE LIFECYCLE                 │
│                                                       │
│   DISCOVER ──→ LOAD ──→ ACTIVATE ──→ RUN ──→ IDLE    │
│      │          │         │            │        │      │
│      │          │         │            │        ▼      │
│      │          │         │            └──→ DEACTIVATE │
│      │          │         │                     │      │
│      │          │         └──→ ERROR ──→ RECOVER      │
│      │          │                                    │
│      └──────────┴──────────→ UNLOAD                  │
│                                                       │
│   AI 控制能力:                                         │
│   • 按需发现: "我需要一个数据库迁移工具" → 搜索并安装    │
│   • 条件加载: "当前是 Django 项目" → 加载 Django 模块   │
│   • 动态替换: 发现更好的实现 → 热替换                    │
│   • 资源管理: 长时间不用 → 自动卸载释放内存              │
└──────────────────────────────────────────────────────┘
```

### 7.2 模块规范

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

@dataclass
class ModuleManifest:
    """模块清单 —— 每个动态模块必须提供"""
    id: str              # 唯一标识: "pycoder.module.django"
    name: str            # 显示名称: "Django Support"
    version: str         # 语义化版本: "1.0.0"
    description: str     # 功能描述
    author: str          # 作者
    capabilities: list[str]  # 提供的能力 ID 列表
    dependencies: list[str]  # 依赖的其他模块
    permissions: list[str]   # 需要的权限
    
class DynamicModule(ABC):
    """所有动态模块的基类"""
    
    manifest: ModuleManifest
    
    @abstractmethod
    async def on_load(self) -> None:
        """模块加载时调用 —— 初始化资源"""
    
    @abstractmethod
    async def on_activate(self, context: dict) -> None:
        """模块激活时调用 —— 注册能力"""
    
    @abstractmethod
    async def on_deactivate(self) -> None:
        """模块停用时调用 —— 清理资源"""
    
    @abstractmethod
    async def on_unload(self) -> None:
        """模块卸载时调用 —— 释放所有资源"""
    
    @abstractmethod
    def health_check(self) -> bool:
        """健康检查 —— AI 用来判断模块是否正常工作"""
```

### 7.3 AI 驱动的模块管理

```
场景 1：AI 发现项目需要数据库迁移工具
────────────────────────────────────────
AI: "检测到你的 Django 项目缺少迁移管理工具。
     需要我搜索并安装合适的模块吗？"
     
用户确认 →
AI → capabilities.search("database migration django")
    → 找到 "pycoder.module.django-migrations" (评分 4.8)
    → 检查安全审计报告 ✓
    → 检查依赖兼容性 ✓
    → capabilities.install("pycoder.module.django-migrations")
    → 模块注册到能力总线
    → AI 现在可以: self_evo.capability("database.migrate").call(...)

场景 2：AI 发现更好的模块可用
────────────────────────────────────────
AI: "检测到 'django-migrations' 有了新版本 2.0，
     新增了自动回滚功能。要我升级吗？"
     
用户确认 →
AI → 备份当前模块
    → 安装新版本
    → 验证兼容性
    → 旧版本进入休眠（保留 7 天以便回退）
```

---

## 8. 安全与权限体系

### 8.1 五级权限模型

```
┌──────────────────────────────────────────────────────┐
│              5-LEVEL PERMISSION MODEL                  │
│                                                       │
│  Level 4: FULL AUTONOMY    ████████████  完全自主      │
│  ─────────────────────────────────────────             │
│  • 修改 Pycoder 自身代码                                │
│  • 重启/热重载服务                                      │
│  • 架构级变更                                          │
│  • 需要: 人工显式确认 + 测试通过                        │
│                                                       │
│  Level 3: SYSTEM ACCESS    ██████████    系统访问       │
│  ─────────────────────────────────────────             │
│  • Shell 命令执行                                       │
│  • 包安装/卸载                                         │
│  • 网络请求                                            │
│  • 数据库操作                                          │
│  • 需要: 关键操作确认 OR 白名单                         │
│                                                       │
│  Level 2: PROJECT WRITE   ████████      项目写入        │
│  ─────────────────────────────────────────             │
│  • 修改项目文件                                         │
│  • Git 操作（commit, push）                             │
│  • 运行项目测试                                        │
│  • 需要: 首次确认后可批量操作                           │
│                                                       │
│  Level 1: WORKSPACE WRITE  ██████        工作区写入     │
│  ─────────────────────────────────────────             │
│  • 创建/编辑文件                                        │
│  • 格式化代码                                          │
│  • 重构操作                                            │
│  • 需要: 默认允许                                       │
│                                                       │
│  Level 0: READ ONLY        ████          只读          │
│  ─────────────────────────────────────────             │
│  • 读取文件                                            │
│  • 代码分析                                            │
│  • 搜索/诊断                                           │
│  • 需要: 始终允许                                       │
└──────────────────────────────────────────────────────┘
```

### 8.2 权限引擎

```python
class PermissionEngine:
    """
    每次 AI 发起能力调用时，权限引擎介入检查。
    
    决策流程:
    1. 查找能力要求的权限级别
    2. 检查当前信任级别
    3. 低于则该操作 → 自动允许
    4. 等于或高于 → 进入决策:
       a. 在白名单中 → 自动允许
       b. 类似操作已批准 → 自动允许
       c. 需要确认 → 弹出提示
       d. 在黑名单中 → 自动拒绝
    5. 记录审计日志
    """
    
    def check(self, capability: str, params: dict) -> PermissionDecision:
        """检查是否允许执行此能力调用"""
    
    def escalate(self, reason: str) -> TrustLevel:
        """AI 可以用"良好行为记录"申请提升信任级别"""
    
    def revoke(self, incident: SecurityIncident) -> TrustLevel:
        """安全事件自动降级"""
```

### 8.3 沙箱系统

```
┌──────────────────────────────────────────────┐
│              SANDBOX SYSTEM                   │
│                                               │
│  ┌──────────────────────────────────────┐    │
│  │         Process Sandbox               │    │
│  │  • 独立的用户/组                      │    │
│  │  • 文件系统隔离（只能访问指定路径）     │    │
│  │  • 网络访问控制（白名单域名）          │    │
│  │  • 资源限制（CPU 30%, 内存 512MB）     │    │
│  │  • 超时强制（单次操作最长 60s）         │    │
│  └──────────────────────────────────────┘    │
│                                               │
│  ┌──────────────────────────────────────┐    │
│  │         Code Sandbox (WASM)           │    │
│  │  • AI 生成的代码在 WASM 中试运行       │    │
│  │  • 无文件系统访问                      │    │
│  │  • 无网络访问                          │    │
│  │  • 严格的内存和时间限制                │    │
│  │  • 用于: 用户代码的安全执行            │    │
│  └──────────────────────────────────────┘    │
│                                               │
│  ┌──────────────────────────────────────┐    │
│  │         Plugin Sandbox                │    │
│  │  • 每个插件独立进程                    │    │
│  │  • 进程间通过能力总线通信              │    │
│  │  • 插件崩溃不影响主系统               │    │
│  │  • 资源配额可配置                      │    │
│  └──────────────────────────────────────┘    │
└──────────────────────────────────────────────┘
```

### 8.4 审计追踪

每次 AI 操作都记录完整的审计日志：

```python
@dataclass
class AuditRecord:
    trace_id: str           # 全链路追踪ID
    timestamp: datetime     # 时间戳
    capability: str         # 调用的能力
    params_summary: str     # 参数摘要（不记录敏感信息）
    permission_level: int   # 所需权限级别
    decision: str           # 允许/拒绝/需要确认
    user_confirmed: bool    # 用户是否确认
    result: str             # 成功/失败/超时
    duration_ms: int        # 执行耗时
    rollback_used: bool     # 是否触发了回滚
    diff: Optional[str]     # 如果是写操作，记录 diff
```

审计日志不可篡改（append-only），支持：
- 按时间/能力/用户/结果过滤
- 回溯任意时间点的系统状态
- 生成安全合规报告
- 异常模式自动检测

---

## 9. 数据流与交互协议

### 9.1 AI 发起操作的标准流程

```
用户输入 OR 意识引擎触发
        │
        ▼
┌──────────────────┐
│  意图理解 & 规划   │  ← AI Brain: Task Planner
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  生成执行计划      │  ← AI Brain: Agent Swarm Orchestrator
│  (可能涉及多个能力) │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  逐一调用能力      │  ← Unified Capability Bus
│  capability.call()│
└────────┬─────────┘
         │
    ┌────┼────┐
    ▼    ▼    ▼
  [权限检查] → 通过?
         │
    ┌────┼────┐
    │    │    │
    ▼    ▼    ▼
  [沙箱执行] [审计记录] [实时反馈]
         │
         ▼
┌──────────────────┐
│  结果聚合 & 验证   │  ← 结果聚合器
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  反馈给用户/继续   │  ← 循环或结束
└──────────────────┘
```

### 9.2 AI 与 UI 的交互协议

```typescript
// Intent Protocol — AI 与 UI 之间的双向通信

// AI → UI: 请求 UI 操作
interface AIIntent {
  type: 'edit' | 'navigate' | 'preview' | 'notify' | 'ask';
  payload: EditPayload | NavigatePayload | PreviewPayload | NotifyPayload;
  urgency: 'background' | 'normal' | 'important' | 'critical';
  id: string; // 可追踪的意图 ID
}

// UI → AI: 用户动作
interface UserAction {
  type: 'accept' | 'reject' | 'modify' | 'interrupt' | 'context';
  intent_id: string; // 关联的 AI 意图
  payload: any;
}

// AI → UI: 意识引擎通知
interface AwarenessNotification {
  type: 'file_changed' | 'test_failed' | 'security_issue' | 'performance_regression';
  severity: 'info' | 'warning' | 'error';
  summary: string;
  suggestion?: string;
  auto_fixable: boolean;
}
```

### 9.3 流式执行与实时反馈

```
能力调用支持三种执行模式:

1. SYNC（同步）
   capability.call("editor.code.read", {path: "app.py"})
   → 立即返回结果
   适用: 读操作、快速操作

2. STREAM（流式）
   capability.stream("system.shell.execute", {cmd: "npm run build"})
   → 实时输出每一行
   适用: 长时间运行的任务

3. ASYNC（异步）
   task_id = capability.async_call("self_evo.code.scan", {path: "pycoder/"})
   → 返回 task_id
   → AI 可继续做其他事
   → 完成后通过事件通知
   适用: 极长时间的任务，允许后台运行
```

---

## 10. V1 → V2 迁移路径

### 10.1 迁移策略：渐进式进化

V2 不是重写，而是在 V1 基础上的架构演进。分四个阶段：

```
阶段 1: 总线统一 (2-3 周)
├─ 实现 UnifiedCapabilityBus
├─ 将现有 MCP 工具迁移到总线
├─ 保持 V1 API 兼容（双轨运行）
└─ 里程碑: 所有现有功能通过总线可调用

阶段 2: AI 升级 (2-3 周)
├─ 实现 Consciousness Engine
├─ 升级 Task Planner
├─ Agent Swarm Orchestrator 替代现有 Agent 循环
└─ 里程碑: AI 能主动感知并自主完成中等复杂度任务

阶段 3: 自进化闭环 (3-4 周)
├─ 实现 SelfModel（代码自认知）
├─ 实现安全热重载
├─ 实现进化流水线（扫描→修复→测试→部署）
└─ 里程碑: AI 能修复自身 bug 并热重载

阶段 4: 动态模块 (2-3 周)
├─ 实现动态模块加载器
├─ 插件沙箱隔离
├─ AI 驱动的模块发现与安装
└─ 里程碑: AI 能按需扩展自身能力
```

### 10.2 兼容性保证

| V1 功能 | V2 处理方式 |
|---------|-----------|
| `server/mcp_tools.py` 工具注册 | 迁移到 `UnifiedCapabilityBus`，旧注册方式保留兼容 |
| `server/chat_bridge.py` | 重构为 `AI Brain → LLM Provider` 的一部分 |
| `server/services/agent_loop.py` | 升级为 `Agent Swarm Orchestrator` |
| `server/self_evolution.py` | 升级为 `Self-Evolution Engine` |
| `server/ws_handler.py` | 升级为 `Intent Protocol` 处理器 |
| `pycoder/electron/` | UI 层适配新的 Intent Protocol，但现有 IPC 接口保持 |
| `API 路由 (/api/*)` | 保留现有路由，新增 `/api/v2/*` 端点 |

### 10.3 新文件结构

```
pycoder/
├── __init__.py
├── __main__.py
│
├── brain/                        # [新] AI 大脑核心
│   ├── __init__.py
│   ├── consciousness.py          # 意识引擎
│   ├── task_planner.py           # 任务规划器
│   ├── agent_swarm.py            # Agent 集群编排器
│   ├── memory_engine.py          # 上下文与记忆引擎
│   └── personality.py            # AI 个性与行为策略
│
├── bus/                          # [新] 统一能力总线
│   ├── __init__.py
│   ├── registry.py               # 能力注册表
│   ├── router.py                 # 智能路由器
│   ├── protocol.py               # 协议适配器 (MCP/gRPC/Internal)
│   ├── monitor.py                # 可观测性
│   └── transformer.py            # 输入输出转换
│
├── capabilities/                 # [新] 能力实现
│   ├── editor/                   # 编辑器能力
│   │   ├── code_edit.py
│   │   ├── lsp.py
│   │   ├── refactor.py
│   │   ├── format.py
│   │   ├── debug.py
│   │   └── preview.py
│   ├── system/                   # 系统能力
│   │   ├── file_ops.py
│   │   ├── shell.py
│   │   ├── git_ops.py
│   │   ├── package.py
│   │   ├── network.py
│   │   └── database.py
│   └── self_evo/                 # 自进化能力
│       ├── code_scan.py
│       ├── self_fix.py
│       ├── self_test.py
│       ├── deploy.py
│       ├── arch_evo.py
│       └── learning.py
│
├── safety/                       # [新] 安全与治理
│   ├── __init__.py
│   ├── permission.py             # 权限引擎
│   ├── sandbox.py                # 沙箱管理
│   ├── audit.py                  # 审计追踪
│   ├── rollback.py               # 回滚管理
│   └── circuit_breaker.py        # 熔断器
│
├── modules/                      # [新] 动态模块系统
│   ├── __init__.py
│   ├── loader.py                 # 模块加载器
│   ├── lifecycle.py              # 生命周期管理
│   ├── sandbox.py                # 模块沙箱
│   └── marketplace.py            # 模块市场
│
├── core/                         # [保留] Clean Architecture
├── adapters/                     # [保留] 适配器
├── providers/                    # [保留] AI 提供商
├── server/                       # [升级] HTTP/WS 服务
├── python/                       # [保留] Python 工具
├── extensions/                   # [迁移到 modules/]
├── plugins/                      # [迁移到 modules/]
├── electron/                     # [适配] 新的 Intent Protocol
└── prompts/                      # [保留] 提示词
```

---

## 附录 A: 关键接口定义

### A.1 AI Brain 核心接口

```python
class AIBrain(ABC):
    """AI 大脑 —— 系统唯一的控制入口"""
    
    @abstractmethod
    async def perceive(self, event: SystemEvent) -> None:
        """接收系统事件，触发意识分析"""
    
    @abstractmethod
    async def think(self, context: TaskContext) -> ExecutionPlan:
        """分析任务，生成执行计划"""
    
    @abstractmethod
    async def act(self, plan: ExecutionPlan) -> ExecutionResult:
        """执行计划，通过能力总线调用各模块"""
    
    @abstractmethod
    async def reflect(self, result: ExecutionResult) -> LearningRecord:
        """反思结果，记录经验用于未来改进"""
    
    @abstractmethod
    async def evolve(self, target: EvolutionTarget) -> EvolutionResult:
        """自我进化：分析自身代码，实施改进"""
```

### A.2 能力总线接口

```python
class CapabilityBus(ABC):
    """统一能力总线 —— AI 操作所有模块的唯一通道"""
    
    @abstractmethod
    async def register(self, capability: CapabilityDefinition) -> None:
        """注册一个新能力"""
    
    @abstractmethod
    async def call(
        self, 
        capability_id: str, 
        params: dict,
        context: ExecutionContext
    ) -> CapabilityResult:
        """调用一个已注册的能力"""
    
    @abstractmethod
    async def stream(
        self,
        capability_id: str,
        params: dict,
        context: ExecutionContext
    ) -> AsyncIterator[CapabilityEvent]:
        """流式调用能力"""
    
    @abstractmethod
    async def discover(self, description: str) -> list[CapabilityDefinition]:
        """语义搜索发现能力"""
    
    @abstractmethod
    async def compose(
        self,
        pipeline: list[CapabilityCall]
    ) -> CompositeResult:
        """组合多个能力为流水线"""
```

---

## 附录 B: 安全性设计清单

| 安全措施 | 实现方式 | 默认状态 |
|---------|---------|---------|
| 敏感文件保护 | 路径黑名单（.env, .git/config, key files） | 不允许修改 |
| 网络访问控制 | 域名白名单 + 内网 IP 黑名单 | 需确认 |
| 命令注入防护 | 参数化命令，禁止 Shell 元字符 | 强制执行 |
| 无限循环保护 | 单个任务最大步数限制 | 20 步 |
| Token 消耗预算 | 日/会话/任务三级预算 | ¥5/天 |
| 权限提升审计 | 每次提权记录原因和上下文 | 全量审计 |
| 自动回滚 | 变更前后快照，失败自动恢复 | 强制执行 |
| 代码审查门禁 | Self-evo 修改必须通过测试 | 强制执行 |
| 模块签名验证 | 动态模块安装前验证签名 | 强制执行 |
| 降级开关 | 紧急情况一键限制 AI 权限 | 用户可触发 |

---

> **文档状态**: 设计阶段，欢迎审阅和讨论。  
> **下一步**: 评审通过后，按照 [第 10 节](#10-v1--v2-迁移路径) 的迁移路径逐步实施。
