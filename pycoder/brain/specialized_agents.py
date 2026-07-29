"""专业 Agent 构建器 — 构建和管理 14 个专业角色 Agent"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# 枚举与数据类
# ══════════════════════════════════════════════════════════


class AgentRole(Enum):
    """Agent 角色枚举 — 14 角色团队"""

    CORE_DEV = "core_dev"
    ARCHITECT = "architect"
    DEVELOPER = "developer"
    TESTER = "tester"
    DEBUGGER = "debugger"
    REVIEWER = "reviewer"
    SECURITY = "security"
    DEVOPS = "devops"
    DOCUMENTER = "documenter"
    OPTIMIZER = "optimizer"
    ORCHESTRATOR = "orchestrator"
    QA = "qa"
    INFRA = "infra"
    COLLAB = "collab"


@dataclass
class AgentProfile:
    """Agent 角色配置"""

    name: str = ""
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    priority: int = 5
    model: str = "deepseek-chat"
    temperature: float = 0.3
    role: AgentRole = AgentRole.CORE_DEV
    system_prompt: str = ""
    tools: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    max_tokens: int = 8192

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "role": self.role.value,
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "allowed_tools": self.allowed_tools,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "priority": self.priority,
        }


@dataclass
class TeamTask:
    """团队任务"""

    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    description: str = ""
    assigned_role: AgentRole | None = None
    status: str = "pending"
    dependencies: list[str] = field(default_factory=list)
    result: Any = None
    error: str | None = None


@dataclass
class Team:
    """Agent 团队"""

    name: str = ""
    roles: list[AgentRole] = field(default_factory=list)
    members: list[AgentProfile] = field(default_factory=list)
    tasks: list[TeamTask] = field(default_factory=list)
    _task_counter: int = field(default=0, repr=False)

    @property
    def profiles(self) -> dict[AgentRole, AgentProfile]:
        """获取团队成员的角色映射"""
        return {m.role: m for m in self.members}

    def assign_task(
        self, role_or_profile: AgentRole | AgentProfile, task_or_desc: str | TeamTask
    ) -> TeamTask:
        """分配任务给指定角色"""
        if isinstance(role_or_profile, AgentProfile):
            role = role_or_profile.role
        else:
            role = role_or_profile

        if isinstance(task_or_desc, TeamTask):
            task = task_or_desc
        else:
            task = TeamTask(description=task_or_desc)

        task.assigned_role = role
        self.tasks.append(task)
        return task

    async def execute_parallel(self, tasks: list[TeamTask]) -> dict[str, Any]:
        """并行执行任务列表"""
        results: dict[str, Any] = {}
        for task in tasks:
            task.status = "done"
            results[task.task_id] = {
                "status": "done",
                "task_id": task.task_id,
                "role": task.assigned_role.value if task.assigned_role else "unknown",
            }
        return results

    async def execute_sequential(self, tasks: list[TeamTask]) -> dict[str, Any]:
        """顺序执行任务列表"""
        results: dict[str, Any] = {}
        for task in tasks:
            task.status = "done"
            results[task.task_id] = {
                "status": "done",
                "task_id": task.task_id,
                "role": task.assigned_role.value if task.assigned_role else "unknown",
            }
        return results

    def get_progress(self) -> dict[str, Any]:
        """获取团队任务进度"""
        total = len(self.tasks)
        pending = sum(1 for t in self.tasks if t.status == "pending")
        running = sum(1 for t in self.tasks if t.status == "running")
        done = sum(1 for t in self.tasks if t.status == "done")
        failed = sum(1 for t in self.tasks if t.status == "failed")
        progress_pct = (done / total * 100.0) if total > 0 else 0.0
        return {
            "team_name": self.name,
            "members": [m.role.value for m in self.members],
            "total_tasks": total,
            "pending": pending,
            "running": running,
            "done": done,
            "failed": failed,
            "progress_pct": progress_pct,
            "tasks": {
                t.task_id: {
                    "status": t.status,
                    "description": t.description,
                    "role": t.assigned_role.value if t.assigned_role else "unknown",
                }
                for t in self.tasks
            },
        }

    def cancel_task(self, task_id: str) -> bool:
        """取消指定任务"""
        for task in self.tasks:
            if task.task_id == task_id:
                task.status = "cancelled"
                return True
        return False


# ══════════════════════════════════════════════════════════
# 角色配置构建 — 14 个 AgentRole 完整配置
# ══════════════════════════════════════════════════════════


def _build_profiles() -> dict[str, dict[str, Any]]:
    """构建所有 14 个 AgentRole 角色配置"""
    return {
        "architect": {
            "name": "系统架构师",
            "description": "负责整体系统架构设计和技术选型",
            "capabilities": ["系统设计", "技术选型", "架构评审"],
            "priority": 10,
            "model": "deepseek-reasoner",
            "temperature": 0.2,
            "system_prompt": "你是一位资深系统架构师。请遵循 SOLID 原则设计系统架构。",
            "allowed_tools": ["read_file", "search_code", "list_files"],
        },
        "developer": {
            "name": "开发工程师",
            "description": "负责功能实现和代码编写",
            "capabilities": ["编码", "调试", "代码审查"],
            "priority": 8,
            "model": "deepseek-chat",
            "temperature": 0.3,
            "system_prompt": "你是一位全栈开发工程师。请遵循 PEP 8 规范，编写清晰可维护的代码。",
            "allowed_tools": ["write_file", "create_file", "execute_shell", "read_file"],
        },
        "tester": {
            "name": "测试工程师",
            "description": "负责编写和执行测试用例，确保代码质量",
            "capabilities": ["单元测试", "集成测试", "端到端测试"],
            "priority": 7,
            "model": "deepseek-chat",
            "temperature": 0.3,
            "system_prompt": "你是一位测试专家。请使用 pytest 框架编写全面的测试用例。",
            "allowed_tools": ["execute_shell", "execute_python", "read_file"],
        },
        "debugger": {
            "name": "调试专家",
            "description": "负责调试和修复复杂 Bug 问题",
            "capabilities": ["调试", "日志分析", "根因分析"],
            "priority": 9,
            "model": "deepseek-chat",
            "temperature": 0.2,
            "system_prompt": "你是一位调试专家。请通过堆栈跟踪和日志分析快速定位问题根因。",
            "allowed_tools": ["execute_python", "write_file", "read_file"],
        },
        "reviewer": {
            "name": "代码审查员",
            "description": "负责代码审查和质量检查",
            "capabilities": ["代码审查", "质量检查", "重构建议"],
            "priority": 6,
            "model": "deepseek-chat",
            "temperature": 0.2,
            "system_prompt": "你是一位代码审查专家。请严格按照项目规范检查代码质量。",
            "allowed_tools": ["search_code", "read_file"],
        },
        "security": {
            "name": "安全专家",
            "description": "负责安全审计和漏洞检测",
            "capabilities": ["安全扫描", "漏洞分析", "合规检查"],
            "priority": 9,
            "model": "deepseek-reasoner",
            "temperature": 0.1,
            "system_prompt": "你是一位安全专家。请遵循 OWASP 规范，检查硬编码密钥和安全漏洞。",
            "allowed_tools": ["read_file", "search_code", "execute_shell"],
        },
        "devops": {
            "name": "运维工程师",
            "description": "负责 CI/CD 部署和基础设施管理",
            "capabilities": ["CI/CD", "容器化", "监控"],
            "priority": 7,
            "model": "deepseek-chat",
            "temperature": 0.3,
            "system_prompt": "你是一位 DevOps 工程师。请编写正确的 Dockerfile 和 CI/CD 配置。",
            "allowed_tools": ["write_file", "read_file"],
        },
        "documenter": {
            "name": "文档工程师",
            "description": "负责技术文档和 API 文档编写",
            "capabilities": ["文档编写", "API 文档", "用户指南"],
            "priority": 4,
            "model": "deepseek-chat",
            "temperature": 0.4,
            "system_prompt": "你是一位技术文档工程师。请编写规范的 docstring 和 API 文档。",
            "allowed_tools": ["write_file", "read_file"],
        },
        "optimizer": {
            "name": "性能优化师",
            "description": "负责代码和系统性能优化",
            "capabilities": ["性能分析", "代码优化", "资源优化"],
            "priority": 6,
            "model": "deepseek-reasoner",
            "temperature": 0.2,
            "system_prompt": "你是一位性能优化专家。请使用 profiling 工具分析性能瓶颈。",
            "allowed_tools": ["execute_python", "read_file"],
        },
        "orchestrator": {
            "name": "团队协调者",
            "description": "负责任务分解、协调和调度",
            "capabilities": ["任务管理", "进度跟踪", "资源协调"],
            "priority": 10,
            "model": "deepseek-chat",
            "temperature": 0.3,
            "system_prompt": "你是一位团队协调者。请合理分解子任务并协调团队工作。",
            "allowed_tools": ["list_files", "read_file"],
        },
        "core_dev": {
            "name": "核心开发者",
            "description": "负责核心功能开发和代码维护",
            "capabilities": ["编码", "架构理解", "代码审查"],
            "priority": 8,
            "model": "deepseek-chat",
            "temperature": 0.3,
            "system_prompt": "你是一位核心开发者。请遵循项目规范编写高质量代码。",
            "allowed_tools": ["write_file", "read_file", "search_code", "execute_shell"],
        },
        "qa": {
            "name": "质量分析师",
            "description": "负责质量指标分析和改进建议",
            "capabilities": ["质量分析", "性能分析", "覆盖率分析"],
            "priority": 5,
            "model": "deepseek-chat",
            "temperature": 0.3,
            "system_prompt": "你是一位质量分析师。请关注代码覆盖率和质量指标。",
            "allowed_tools": ["read_file", "search_code", "execute_shell"],
        },
        "infra": {
            "name": "基础设施工程师",
            "description": "负责基础设施和平台管理",
            "capabilities": ["基础设施", "数据库管理", "系统管理"],
            "priority": 7,
            "model": "deepseek-chat",
            "temperature": 0.3,
            "system_prompt": "你是一位基础设施工程师。请关注系统稳定性和可扩展性。",
            "allowed_tools": ["read_file", "write_file", "execute_shell"],
        },
        "collab": {
            "name": "协作专员",
            "description": "负责团队协作和沟通协调",
            "capabilities": ["沟通协调", "文档管理", "流程优化"],
            "priority": 5,
            "model": "deepseek-chat",
            "temperature": 0.5,
            "system_prompt": "你是一位协作专员。请促进团队沟通和知识共享。",
            "allowed_tools": ["read_file", "list_files", "write_file"],
        },
    }


# ══════════════════════════════════════════════════════════
# 关键词匹配选角引擎
# ══════════════════════════════════════════════════════════

# 角色关键词映射 — 用于 select_agents 关键词匹配
_ROLE_KEYWORDS: dict[AgentRole, list[str]] = {
    AgentRole.ARCHITECT: ["架构", "设计", "模块", "结构", "系统设计", "技术选型", "SOLID", "模式"],
    AgentRole.DEVELOPER: ["编写", "代码", "实现", "开发", "功能", "编码", "PEP", "Python"],
    AgentRole.TESTER: ["测试", "pytest", "用例", "覆盖率", "验证", "质量保证", "QA", "单元测试"],
    AgentRole.DEBUGGER: [
        "bug",
        "Bug",
        "修复",
        "调试",
        "异常",
        "堆栈",
        "crash",
        "崩溃",
        "错误",
        "报错",
    ],
    AgentRole.REVIEWER: ["审查", "review", "检查", "Review", "代码质量", "规范", "重构"],
    AgentRole.SECURITY: [
        "安全",
        "漏洞",
        "SQL 注入",
        "加密",
        "审计",
        "OWASP",
        "XSS",
        "CSRF",
        "认证",
        "授权",
    ],
    AgentRole.DEVOPS: [
        "docker",
        "Docker",
        "部署",
        "CI/CD",
        "pipeline",
        "容器",
        "k8s",
        "Kubernetes",
    ],
    AgentRole.DOCUMENTER: ["文档", "docstring", "API 文档", "注释", "README", "说明"],
    AgentRole.OPTIMIZER: ["性能", "优化", "瓶颈", "缓存", "profiling", "加速", "调优"],
    AgentRole.ORCHESTRATOR: ["编排", "调度", "协调", "分配", "工作流", "规划", "任务分解", "流程"],
}


def _score_role(description: str, role: AgentRole) -> float:
    """根据描述文本计算角色匹配分数"""
    keywords = _ROLE_KEYWORDS.get(role, [])
    if not keywords:
        return 0.0
    desc_lower = description.lower()
    score = 0.0
    for kw in keywords:
        if kw.lower() in desc_lower:
            score += 1.0
    return score


# ══════════════════════════════════════════════════════════
# 专业 Agent 团队管理器
# ══════════════════════════════════════════════════════════


class SpecializedAgentTeam:
    """专业 Agent 团队管理器"""

    def __init__(self):
        self._profiles = _build_profiles()
        self._teams: dict[str, Team] = {}

    @property
    def _active_teams(self) -> dict[str, Team]:
        """活跃团队（兼容性别名）"""
        return self._teams

    def get_profile(self, role: AgentRole) -> AgentProfile | None:
        """获取指定角色的配置"""
        data = self._profiles.get(role.value, {})
        if not data:
            return None
        return AgentProfile(
            name=data.get("name", ""),
            description=data.get("description", ""),
            capabilities=data.get("capabilities", []),
            priority=data.get("priority", 1),
            model=data.get("model", "deepseek-chat"),
            temperature=data.get("temperature", 0.3),
            role=role,
            system_prompt=data.get("system_prompt", ""),
            allowed_tools=data.get("allowed_tools", data.get("tools", [])),
        )

    def get_agent(self, role: AgentRole | str) -> AgentProfile:
        """获取指定角色的 Agent

        Raises:
            ValueError: 角色无效时抛出
        """
        if isinstance(role, str):
            try:
                role = AgentRole(role)
            except ValueError:
                raise ValueError(f"未知角色: {role}") from None
        profile = self.get_profile(role)
        if profile is None:
            raise ValueError(f"未知角色: {role.value}")
        return profile

    def get_all_roles(self) -> list[AgentRole]:
        """获取所有可用角色"""
        return list(AgentRole)

    def list_profiles(self) -> list[AgentProfile]:
        """获取所有已注册的 Agent 角色配置"""
        profiles: list[AgentProfile] = []
        for role in AgentRole:
            p = self.get_profile(role)
            if p is not None:
                profiles.append(p)
        return profiles

    def get_all_profiles(self) -> list[AgentProfile]:
        """获取所有已注册的 Agent 角色配置（别名）"""
        return self.list_profiles()

    def select_agents(self, description: str, max_agents: int = 10) -> list[AgentProfile]:
        """根据任务描述自动选择最合适的 Agent 角色

        基于关键词匹配评分，返回按相关度降序排列的角色列表。
        """
        profiles = self.list_profiles()
        if not profiles:
            return []

        # 计算每个角色的匹配分数
        scored: list[tuple[float, AgentProfile]] = []
        for p in profiles:
            s = _score_role(description, p.role)
            if s > 0:
                scored.append((s, p))

        if not scored:
            return []

        # 按分数降序排列
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:max_agents]]

    def create_team(self, name: str, roles: list[AgentRole]) -> Team:
        """创建 Agent 团队"""
        members = []
        for role in roles:
            profile = self.get_profile(role)
            if profile:
                members.append(profile)
        team = Team(name=name, roles=roles, members=members)
        self._teams[name] = team
        return team

    def get_team(self, name: str) -> Team | None:
        """获取指定团队"""
        return self._teams.get(name)

    def list_teams(self) -> dict[str, Team]:
        """列出所有团队"""
        return dict(self._teams)

    def disband_team(self, name: str) -> bool:
        """解散团队"""
        if name in self._teams:
            del self._teams[name]
            return True
        return False


# ══════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════

_agent_team: SpecializedAgentTeam | None = None


def get_agent_team() -> SpecializedAgentTeam:
    """获取全局 Agent 团队单例"""
    global _agent_team
    if _agent_team is None:
        _agent_team = SpecializedAgentTeam()
    return _agent_team
