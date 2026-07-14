"""
AI 大脑核心 — Pycoder V2 的中央控制层

包含:
- 意识引擎: 持续感知项目状态
- 任务规划器: 动态分解和重规划
- Agent 编排器: 多角色并行协作
- 记忆引擎: 四级记忆体系
"""

from pycoder.brain.consciousness import ConsciousnessEngine, SystemEvent, OperatingMode
from pycoder.brain.task_planner import TaskPlanner, Task, ExecutionPlan
from pycoder.brain.agent_swarm import AgentSwarmOrchestrator, AgentRole, AgentTask
from pycoder.brain.memory_engine import MemoryEngine, WorkingMemory, ProjectKnowledge

__all__ = [
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
]
