# PyCoder AI 智能化重新设计方案

> 版本: 1.0 | 日期: 2026-07-16 | 目标: 解决 AI 智能化不足问题，实现动态自适应 AI 引擎

---

## 1. 问题诊断

### 1.1 当前核心问题

| 问题 | 现状 | 影响 |
|------|------|------|
| **固定工具调用模式** | `UNIFIED_SYSTEM_PROMPT` 强制要求"每次回复第一条必须是 JSON 工具调用" | 简单问答也强制走工具调用，浪费 token 和延迟 |
| **关键词匹配选 Agent** | `specialized_agents.py` 和 `agent_swarm.py` 使用关键词匹配分配角色 | 误判率高，无法理解语义意图 |
| **正则意图分类** | `intent_parser.py` 纯正则匹配，无 LLM 辅助 | 复杂意图无法准确识别，歧义处理弱 |
| **无反馈学习** | 学习系统存在但与核心循环脱节 | 无法从错误中学习，重复犯错 |
| **上下文感知弱** | 会话记忆仅简单注入，无结构化上下文管理 | 长对话跑偏，回答不连贯 |

### 1.2 根因分析

```
用户输入 → [正则意图分类] → [固定模式路由] → [关键词匹配Agent] → [强制工具调用]
                ↑ 弱              ↑ 僵化            ↑ 误判           ↑ 浪费
```

核心问题：**AI 决策链路缺乏真正的智能分析环节**，所有判断基于静态规则而非动态理解。

---

## 2. 设计方案

### 2.1 新架构总览

```
                         ┌──────────────────────────┐
                         │    Intelligent Router     │
                         │  (智能路由决策中心)        │
                         └──────────┬───────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          │                         │                         │
          ▼                         ▼                         ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Intent Analyzer │    │  Agent Selector  │    │  Tool Planner    │
│  (深度意图分析)   │    │  (智能Agent选择)  │    │  (动态工具规划)   │
└────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │    Adaptive Executor     │
                    │  (自适应执行引擎)          │
                    └──────────┬───────────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
                    ▼                     ▼
          ┌──────────────┐     ┌──────────────────┐
          │  Tool Loop   │     │  Feedback Loop   │
          │  (动态工具循环)│◄───▶│  (反馈学习循环)   │
          └──────────────┘     └──────────────────┘
```

### 2.2 核心模块设计

#### 2.2.1 智能路由决策中心 (IntelligentRouter)

**职责**: 接收用户输入，协调意图分析、Agent 选择、工具规划三大模块，输出统一执行计划。

```python
@dataclass
class RoutingDecision:
    """路由决策结果"""
    intent: IntentAnalysis      # 意图分析结果
    agent: AgentSelection       # Agent 选择结果
    tool_plan: ToolPlan         # 工具调用计划
    execution_config: ExecutionConfig  # 执行配置
    confidence: float           # 决策置信度
```

**决策流程**:
1. 意图分析 → 理解用户真正想做什么
2. Agent 选择 → 根据意图选择合适的 Agent/模式
3. 工具规划 → 分析需要哪些工具、调用多少次
4. 执行配置 → 确定迭代预算、温度、模型等参数

#### 2.2.2 深度意图分析器 (IntentAnalyzer)

**设计原则**: 正则快速过滤 + LLM 深度理解，分两层执行。

**Layer 1 — 快速通道** (正则匹配，零 Token 消耗):
- 明确的简单问候、元问题 → 直接走 chat 模式
- 明确的文件路径引用 → 标记为工具操作
- 高风险操作 → 提前标记

**Layer 2 — 深度理解** (LLM 分析，歧义/复杂请求):
- 技术领域识别: Python/JS/Go/Rust/DevOps/Data/AI
- 任务类型识别: 问答/代码生成/调试/重构/架构设计/部署
- 复杂度评估: 简单/中等/复杂，影响后续 Agent 选择和工具规划
- 歧义检测: 识别模糊引用、缺失信息、矛盾需求

```python
@dataclass
class IntentAnalysis:
    """意图分析结果"""
    # 基础信息
    raw_input: str
    normalized_intent: str       # 标准化后的意图描述
    
    # 领域分类
    technical_domain: str        # python/js/go/rust/devops/data/ai/general
    task_type: str               # qa/code_gen/debug/refactor/architect/deploy
    
    # 复杂度
    complexity: str              # trivial/simple/medium/complex
    complexity_score: int        # 0-100
    
    # 特殊性
    has_file_references: bool    # 是否涉及具体文件
    has_risk: bool               # 是否有高风险操作
    is_ambiguous: bool           # 是否有歧义
    ambiguity_notes: list[str]   # 歧义点说明
    
    # 交互需求
    needs_clarification: bool    # 是否需要追问用户
    clarification_questions: list[str]  # 追问问题
    expected_response_type: str  # 预期回答类型: text/code/diff/report/mixed
```

#### 2.2.3 智能 Agent 选择器 (AgentSelector)

**设计原则**: 基于语义理解的 Agent 匹配，而非关键词匹配。

**决策维度**:
| 维度 | 权重 | 说明 |
|------|------|------|
| 技术领域匹配 | 30% | Agent 擅长的技术栈是否匹配 |
| 任务类型匹配 | 25% | Agent 角色是否适合当前任务类型 |
| 复杂度匹配 | 20% | Agent 能力是否能处理该复杂度 |
| 历史成功率 | 15% | 同类任务中该 Agent 的历史表现 |
| 响应速度要求 | 10% | 用户是否期望快速响应 |

**Agent 池** (基于现有 10 角色 + 扩展):
- 简单问答: 无需 Agent，直接 LLM 回答
- 代码生成: developer
- 调试修复: debugger + fixer
- 架构设计: architect
- 代码审查: reviewer + qa
- 安全审计: security
- 部署运维: devops
- 文档编写: documenter
- 性能优化: optimizer
- 复杂工程: orchestrator → 协调多 Agent 团队

```python
@dataclass
class AgentSelection:
    """Agent 选择结果"""
    primary_agent: str           # 主 Agent ID
    secondary_agents: list[str]  # 辅助 Agent
    selection_reason: str        # 选择理由
    confidence: float            # 匹配置信度
    model_tier: str              # 模型分层: premium/standard/economy
    estimated_tokens: int        # 预估 Token 消耗
```

#### 2.2.4 动态工具规划器 (ToolPlanner)

**设计原则**: 根据任务复杂度动态决定工具调用次数和类型，而非强制固定轮次。

**规划策略**:
| 任务类型 | 工具调用策略 | 示例 |
|---------|-------------|------|
| 纯问答 | 0 次工具调用，直接回答 | "什么是 FastAPI？" |
| 简单查询 | 1-2 次读操作 | "读取 config.py 内容" |
| 代码修改 | 2-5 次读写操作 | "修复 app.py 的 bug" |
| 多文件开发 | 5-10 次混合操作 | "实现用户认证模块" |
| 复杂工程 | 10-30 次全流程 | "重构整个项目架构" |

**工具选择策略**:
- 基于意图分析的技术领域和任务类型预筛选工具
- 读操作可并行，写操作串行
- 根据工具执行结果动态调整后续工具选择

```python
@dataclass
class ToolPlan:
    """工具调用计划"""
    # 动态规划
    estimated_tool_calls: int    # 预估工具调用次数
    max_tool_calls: int          # 最大工具调用次数
    tool_categories: list[str]   # 需要的工具类别: read/write/execute/git/search
    
    # 策略
    allow_parallel_reads: bool   # 是否允许并行读
    enforce_sequential_writes: bool  # 是否强制串行写
    
    # 运行时
    actual_tool_calls: int = 0   # 实际调用次数
    successful_tool_calls: int = 0  # 成功调用次数
```

#### 2.2.5 自适应执行引擎 (AdaptiveExecutor)

**设计原则**: 替代现有的固定循环，实现动态自适应执行。

**核心改进**:
1. **动态迭代预算**: 根据任务复杂度动态分配，而非固定 15/50 轮
2. **提前终止**: 任务完成时自动终止，不浪费轮次
3. **自适应重试**: 工具失败时根据错误类型决定是否重试、如何重试
4. **上下文感知**: 每轮执行前注入最新的相关上下文

```python
class AdaptiveExecutor:
    """自适应执行引擎"""
    
    async def execute(self, decision: RoutingDecision) -> AsyncIterator[dict]:
        """执行路由决策
        
        1. 根据 Agent 选择加载对应的系统提示词和工具集
        2. 根据 ToolPlan 设置执行参数
        3. 进入自适应循环:
           - 每轮前: 注入最新上下文、反思检查
           - 执行中: 监控工具调用、检测跑偏
           - 每轮后: 评估进展、决定是否继续
        4. 完成后: 收集反馈、更新学习信号
        """
```

#### 2.2.6 反馈学习循环 (FeedbackLoop)

**设计原则**: 实时收集执行信号，持续优化决策模型。

**学习信号**:
| 信号类型 | 来源 | 用途 |
|---------|------|------|
| 工具调用成功率 | 执行统计 | 优化工具选择 |
| Agent 匹配准确率 | 用户反馈 | 优化 Agent 选择 |
| 任务完成率 | 执行结果 | 优化策略选择 |
| 用户满意度 | 显式/隐式反馈 | 全局优化 |
| 响应延迟 | 性能监控 | 优化模型选择 |

**学习机制**:
1. **即时学习**: 每次执行后更新统计
2. **批量学习**: 定期汇总分析趋势
3. **强化学习**: 根据反馈调整决策权重

---

## 3. 实现计划

### 3.1 新增模块

| 模块 | 路径 | 状态 | 说明 |
|------|------|------|------|
| IntelligentRouter | `pycoder/brain/intelligent_router.py` | ✅ 已完成 | 智能路由决策中心 |
| IntentAnalyzer | `pycoder/brain/intent_analyzer.py` | ✅ 已完成 | 深度意图分析器（双层架构） |
| AgentSelector | `pycoder/brain/agent_selector.py` | ✅ 已完成 | 智能 Agent 选择器（多维评分） |
| ToolPlanner | `pycoder/brain/tool_planner.py` | ✅ 已完成 | 动态工具规划器 |
| AdaptiveExecutor | `pycoder/brain/adaptive_executor.py` | ✅ 已完成 | 自适应执行引擎 |
| FeedbackLoop | `pycoder/brain/feedback_loop.py` | ✅ 已完成 | 反馈学习循环 |
| ContextEnhancer | `pycoder/brain/context_enhancer.py` | ✅ 已完成 | 对话交互增强器（NLU/上下文） |

### 3.2 修改模块

| 模块 | 路径 | 状态 | 变更说明 |
|------|------|------|---------|
| brain/__init__.py | `pycoder/brain/__init__.py` | ✅ 已完成 | 导出所有新模块 |
| agent_loop.py | `pycoder/server/services/agent_loop.py` | ✅ 已完成 | 集成智能路由、上下文增强、反馈学习 |

### 3.3 执行顺序

```
Phase 1: 核心决策层 ✅
  ├── 1.1 IntentAnalyzer (深度意图分析)
  ├── 1.2 AgentSelector (智能 Agent 选择)
  └── 1.3 ToolPlanner (动态工具规划)

Phase 2: 执行层 ✅
  ├── 2.1 IntelligentRouter (路由决策中心)
  └── 2.2 AdaptiveExecutor (自适应执行引擎)

Phase 3: 学习层 ✅
  ├── 3.1 FeedbackLoop (反馈学习循环)
  └── 3.2 ContextEnhancer (对话交互增强)

Phase 4: 集成 ✅
  ├── 4.1 修改 brain/__init__.py (导出新模块)
  └── 4.2 修改 agent_loop.py (集成智能路由 + 反馈学习)
```

### 3.4 新增模块详细说明

#### 3.4.1 ContextEnhancer — 对话交互增强器

**路径**: `pycoder/brain/context_enhancer.py`

**核心功能**:
- **结构化上下文管理**: 替代简单的上下文注入，实现分层上下文（当前话题、关键实体、相关文件、相关历史）
- **模糊引用消解**: 处理"它"、"这个"、"那个"、"刚才的文件"等模糊代词/引用
- **话题追踪**: 检测话题切换，保持上下文连贯性，支持 continuation/correction/confirmation 类型的延续
- **实体提取**: 从消息和历史中提取文件路径、代码符号、错误信息等关键实体
- **连贯性计算**: 评估当前消息与历史对话的连贯性得分
- **追问检测**: 检测是否需要追问用户以澄清意图

#### 3.4.2 AdaptiveExecutor — 自适应执行引擎

**路径**: `pycoder/brain/adaptive_executor.py`

**核心功能**:
- **路由决策驱动**: 接收 IntelligentRouter 的决策结果，动态调整执行参数
- **直接回答路径**: 简单问答直接走 LLM 回答，跳过工具调用
- **追问路径**: 歧义请求自动追问用户
- **自适应循环**: 动态迭代预算、提前终止、反思注入
- **智能重试**: 根据错误类型（timeout/connection/rate_limit/permission 等）决定是否重试及重试策略
- **反馈集成**: 与 FeedbackLoop 协作，实时收集执行信号

#### 3.4.3 FeedbackLoop — 反馈学习循环

**路径**: `pycoder/brain/feedback_loop.py`

**核心功能**:
- **执行信号收集**: 记录每次执行的意图、Agent、工具、结果等全维度数据
- **自适应权重调整**: 根据 Agent 准确率、工具成功率动态调整决策权重
- **用户反馈收集**: 支持评分（1-5）和快捷反应（👍/👎）
- **批量持久化**: 信号写入 `data/signals.jsonl`，跨会话保持
- **聚合统计**: 按 domain/agent/strategy 维度聚合分析
- **优化建议**: 基于学习数据自动生成改进建议

### 3.5 agent_loop.py 集成详情

**修改点**:
1. `__init__`: 新增 `router`、`feedback`、`context_enhancer`、`enable_intelligent_routing` 参数
2. `chat_stream` 开头: 调用 `ContextEnhancer.process_message()` 增强上下文，调用 `IntelligentRouter.decide()` 做出路由决策
3. 直接回答路径: 简单问答（trivial + qa）直接走 LLM 回答，免工具调用
4. 追问路径: 歧义请求输出追问问题
5. 动态参数: 根据决策动态调整 `max_iterations`、`timeout` 等
6. 完成路径: 所有完成分支均调用 `_record_feedback()` 记录执行信号
7. 新增方法: `_record_feedback()`、`record_user_rating()`、`get_feedback_stats()`、`get_feedback_recommendations()`

---

## 4. 性能指标

### 4.1 目标指标

| 指标 | 当前值 | 目标值 | 提升幅度 |
|------|--------|--------|---------|
| 用户问题一次性解决率 | ~60% | ~90% | +30% |
| 工具调用准确率 | ~55% | ~95% | +40% |
| 简单问答响应时间 | ~3s | ~1s | -67% |
| Agent 选择准确率 | ~70% | ~95% | +25% |
| 上下文连贯性 | 中等 | 优秀 | — |
| 不必要工具调用 | ~40% | <5% | -87% |

### 4.2 兼容性保证

- 所有现有 API 端点保持不变
- 现有 Agent 角色定义向后兼容
- 现有工具调用格式兼容
- 通过 `use_intelligent_router` 参数控制启用/禁用

---

## 5. 可扩展性设计

### 5.1 插件化 Agent 注册

```python
# 新增 Agent 只需注册，无需修改核心代码
@register_agent(
    role="data_scientist",
    domains=["data", "ml", "ai"],
    task_types=["analysis", "modeling"],
    complexity_range=(30, 80),
)
class DataScientistAgent(AgentProfile):
    ...
```

### 5.2 工具动态发现

```python
# 工具通过装饰器注册，自动纳入 ToolPlanner 的候选池
@register_tool(
    category="data",
    required_domain=["data", "ml"],
    complexity_min=20,
)
async def analyze_dataframe(df_path: str, query: str) -> dict:
    ...
```

### 5.3 策略热更新

反馈学习循环实时更新决策权重，无需重启服务即可优化 Agent 选择和工具规划策略。