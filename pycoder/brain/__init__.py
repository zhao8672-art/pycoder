"""
AI 大脑核心 — Pycoder V2 的中央控制层

包含:
- 智能路由: 统一的意图分析 + Agent 选择 + 工具规划决策中心
- 自适应执行引擎: 动态迭代预算、提前终止、自适应重试
- 反馈学习循环: 实时信号收集、自适应权重调整
- 对话增强器: 结构化上下文管理、话题追踪、引用消解
- 意识引擎: 持续感知项目状态
- 任务规划器: 动态分解和重规划
- Agent 编排器: 多角色并行协作
- 记忆引擎: 四级记忆体系
- 八阶段流水线引擎: 完整开发闭环
- 四级质量门禁: 自动化质量把关
- 模型路由器: 动态模型选择
- 成本控制器: Token 预算管理
- 共享状态系统: Agent 间通信
- 标准化执行报告: 统一输出格式
- Hermes 调度中枢: 任务解析与调度
- 14 角色 Agent 团队: 专业化分工协作
"""

from pycoder.brain.adaptive_executor import (
    AdaptiveExecutor,
    ExecutionContext,
    get_adaptive_executor,
)
from pycoder.brain.agent_selector import (
    AgentSelection,
    AgentSelector,
    get_agent_selector,
)
from pycoder.brain.agent_swarm import AgentRole, AgentSwarmOrchestrator, AgentTask
from pycoder.brain.consciousness import ConsciousnessEngine, OperatingMode, SystemEvent
from pycoder.brain.context_enhancer import (
    ContextEnhancer,
    ConversationTurn,
    EnhancedContext,
    get_context_enhancer,
)
from pycoder.brain.feedback_loop import (
    AdaptiveWeights,
    AggregatedStats,
    ExecutionSignal,
    FeedbackLoop,
    get_feedback_loop,
)
from pycoder.brain.intelligent_router import (
    ExecutionConfig,
    IntelligentRouter,
    RoutingDecision,
    get_intelligent_router,
)
from pycoder.brain.intent_analyzer import (
    IntentAnalysis,
    IntentAnalyzer,
    get_intent_analyzer,
)
from pycoder.brain.memory_engine import MemoryEngine, ProjectKnowledge, WorkingMemory
from pycoder.brain.task_planner import ExecutionPlan, Task, TaskPlanner
from pycoder.brain.tool_planner import (
    ToolPlan,
    ToolPlanner,
    get_tool_planner,
)

# 八阶段流水线引擎
from pycoder.brain.pipeline_engine import (
    PipelineEngine,
    PipelinePhase,
    PipelinePhaseResult,
    PipelinePhaseStatus,
    PipelineResult,
    get_pipeline_engine,
)

# 四级质量门禁
from pycoder.brain.quality_gate import (
    GateLevel,
    GateResult,
    QualityGate,
    get_quality_gate,
)

# 模型路由器
from pycoder.brain.model_router import (
    ModelRouter,
    ModelRoute,
    ModelTier,
    get_model_router,
)

# 成本控制器
from pycoder.brain.cost_controller import (
    BudgetStatus,
    CostBudget,
    CostController,
    CostEntry,
    get_cost_controller,
)

# 共享状态系统
from pycoder.brain.shared_state import (
    SharedState,
    SharedTaskState,
    TaskPhase,
    TaskStatus,
    ValidationContract,
    get_shared_state,
)

# 标准化执行报告
from pycoder.brain.execution_report import (
    ExecutionReport,
    FileChange,
    OperationSummary,
    ReportBuilder,
    ReportStatus,
    get_report_builder,
)

# Hermes 调度中枢
from pycoder.brain.hermes_agent import (
    DispatchResult,
    HermesAgent,
    TaskAnalysis,
    TaskComplexity,
    get_hermes_agent,
)

# 14 角色 Agent 团队
from pycoder.brain.specialized_agents import (
    AgentProfile,
    AgentRole as SpecializedAgentRole,
    SpecializedAgentTeam,
    Team,
    TeamTask,
    get_agent_team,
)

__all__ = [
    # 智能路由
    "IntelligentRouter",
    "RoutingDecision",
    "ExecutionConfig",
    "get_intelligent_router",
    # 意图分析
    "IntentAnalyzer",
    "IntentAnalysis",
    "get_intent_analyzer",
    # Agent 选择
    "AgentSelector",
    "AgentSelection",
    "get_agent_selector",
    # 工具规划
    "ToolPlanner",
    "ToolPlan",
    "get_tool_planner",
    # 自适应执行
    "AdaptiveExecutor",
    "ExecutionContext",
    "get_adaptive_executor",
    # 反馈学习
    "FeedbackLoop",
    "ExecutionSignal",
    "AdaptiveWeights",
    "AggregatedStats",
    "get_feedback_loop",
    # 对话增强
    "ContextEnhancer",
    "ConversationTurn",
    "EnhancedContext",
    "get_context_enhancer",
    # 已有模块
    "ConsciousnessEngine",
    "SystemEvent",
    "OperatingMode",
    "TaskPlanner",
    "Task",
    "ExecutionPlan",
    "AgentSwarmOrchestrator",
    "AgentRole",
    "AgentTask",
    "MemoryEngine",
    "WorkingMemory",
    "ProjectKnowledge",
    # 流水线引擎
    "PipelineEngine",
    "PipelinePhase",
    "PipelinePhaseResult",
    "PipelinePhaseStatus",
    "PipelineResult",
    "get_pipeline_engine",
    # 质量门禁
    "QualityGate",
    "GateLevel",
    "GateResult",
    "get_quality_gate",
    # 模型路由
    "ModelRouter",
    "ModelRoute",
    "ModelTier",
    "get_model_router",
    # 成本控制
    "CostController",
    "CostBudget",
    "CostEntry",
    "BudgetStatus",
    "get_cost_controller",
    # 共享状态
    "SharedState",
    "SharedTaskState",
    "TaskPhase",
    "TaskStatus",
    "ValidationContract",
    "get_shared_state",
    # 执行报告
    "ExecutionReport",
    "FileChange",
    "OperationSummary",
    "ReportBuilder",
    "ReportStatus",
    "get_report_builder",
    # Hermes 调度
    "HermesAgent",
    "DispatchResult",
    "TaskAnalysis",
    "TaskComplexity",
    "get_hermes_agent",
    # Agent 团队
    "SpecializedAgentTeam",
    "SpecializedAgentRole",
    "AgentProfile",
    "Team",
    "TeamTask",
    "get_agent_team",
]
