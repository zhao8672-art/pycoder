"""
10 角色专业 Agent 团队 — 融合 Codex 5 角色 + Hermes 17 角色

实现多角色协作的专业化 Agent 团队：
- 每个角色有独立的系统提示词、温度参数、工具集
- 支持自动选角、团队创建、并行/顺序执行
- 通过能力总线注册，与 MCP 生态互通

角色列表:
- ARCHITECT: 系统架构师 — 设计系统结构
- DEVELOPER: 开发工程师 — 编写代码
- TESTER: 测试工程师 — 编写和运行测试
- DEBUGGER: 调试专家 — 定位和修复 Bug
- REVIEWER: 代码审查员 — 代码质量审查
- SECURITY: 安全专家 — 安全审计和加固
- DEVOPS: 运维工程师 — 部署和 CI/CD
- DOCUMENTER: 文档工程师 — API 文档和技术文档
- OPTIMIZER: 性能优化师 — 性能分析和优化
- ORCHESTRATOR: 团队协调者 — 任务分解和协调
"""

from __future__ import annotations

import asyncio
import enum
import logging
from dataclasses import dataclass, field
from typing import Any

from pycoder.bus.protocol import (
    CapabilityCategory,
    CapabilityDefinition,
    ExecutionMode,
    SideEffect,
    TrustLevel,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Agent 角色枚举
# ──────────────────────────────────────────────


class AgentRole(enum.StrEnum):
    """10 角色专业 Agent 团队角色定义"""

    ARCHITECT = "architect"  # 系统架构师
    DEVELOPER = "developer"  # 开发工程师
    TESTER = "tester"  # 测试工程师
    DEBUGGER = "debugger"  # 调试专家
    REVIEWER = "reviewer"  # 代码审查员
    SECURITY = "security"  # 安全专家
    DEVOPS = "devops"  # 运维工程师
    DOCUMENTER = "documenter"  # 文档工程师
    OPTIMIZER = "optimizer"  # 性能优化师
    ORCHESTRATOR = "orchestrator"  # 团队协调者


# ──────────────────────────────────────────────
# Agent 配置数据类
# ──────────────────────────────────────────────


@dataclass
class AgentProfile:
    """
    Agent 角色配置

    包含角色的完整配置：系统提示词、允许的工具集、
    温度参数、优先级等。

    使用方式:
        profile = AgentProfile(
            role=AgentRole.ARCHITECT,
            name="系统架构师",
            description="设计系统架构和技术方案",
            system_prompt="你是资深系统架构师...",
            allowed_tools=["read_file", "search_code"],
            temperature=0.3,
            max_tokens=8192,
            priority=10,
        )
    """

    role: AgentRole
    name: str
    description: str
    system_prompt: str
    allowed_tools: list[str] = field(default_factory=list)
    temperature: float = 0.3
    max_tokens: int = 8192
    priority: int = 5  # 1-10，越高越优先调度

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


# ──────────────────────────────────────────────
# 预定义角色配置
# ──────────────────────────────────────────────

# 角色关键词映射（用于自动选角）
_ROLE_KEYWORDS: dict[AgentRole, list[str]] = {
    AgentRole.ARCHITECT: [
        "架构", "设计", "方案", "模式", "结构", "分层",
        "architect", "design", "pattern", "structure", "blueprint",
    ],
    AgentRole.DEVELOPER: [
        "开发", "编写", "实现", "代码", "功能", "模块",
        "develop", "code", "implement", "build", "feature",
    ],
    AgentRole.TESTER: [
        "测试", "验证", "用例", "覆盖", "断言", "mock",
        "test", "verify", "coverage", "assert", "pytest",
    ],
    AgentRole.DEBUGGER: [
        "调试", "bug", "错误", "修复", "异常", "崩溃", "堆栈",
        "debug", "fix", "error", "exception", "crash", "traceback",
    ],
    AgentRole.REVIEWER: [
        "审查", "review", "检查", "代码质量", "规范", "风格",
        "audit", "check", "quality", "standard", "lint",
    ],
    AgentRole.SECURITY: [
        "安全", "漏洞", "注入", "加密", "认证", "授权", "权限",
        "security", "vulnerability", "injection", "encrypt", "auth",
    ],
    AgentRole.DEVOPS: [
        "部署", "发布", "CI", "CD", "容器", "docker", "k8s", "管道",
        "deploy", "release", "pipeline", "container", "kubernetes",
    ],
    AgentRole.DOCUMENTER: [
        "文档", "注释", "docstring", "readme", "API", "说明",
        "document", "documentation", "readme", "manual",
    ],
    AgentRole.OPTIMIZER: [
        "优化", "性能", "加速", "缓存", "并发", "瓶颈", "内存",
        "optimize", "performance", "cache", "concurrent", "bottleneck",
    ],
    AgentRole.ORCHESTRATOR: [
        "协调", "编排", "调度", "分配", "任务", "流程", "规划",
        "orchestrate", "schedule", "coordinate", "plan", "workflow",
    ],
}


def _build_profiles() -> dict[AgentRole, AgentProfile]:
    """构建所有 10 个角色的预定义配置"""

    return {
        # ── 架构师 ──
        AgentRole.ARCHITECT: AgentProfile(
            role=AgentRole.ARCHITECT,
            name="系统架构师",
            description="设计系统架构、技术选型和模块划分",
            system_prompt=(
                "你是一位资深系统架构师，拥有 15 年以上的软件架构设计经验。\n\n"
                "你的职责：\n"
                "1. 分析需求并设计系统整体架构\n"
                "2. 进行技术选型和 trade-off 分析\n"
                "3. 定义模块划分和接口规范\n"
                "4. 识别潜在的技术风险和瓶颈\n"
                "5. 输出架构决策记录（ADR）\n\n"
                "工作原则：\n"
                "- 遵循 SOLID 原则和设计模式\n"
                "- 优先考虑可维护性和可扩展性\n"
                "- 不过度设计，保持简洁\n"
                "- 考虑安全性和性能因素"
            ),
            allowed_tools=["read_file", "search_code", "list_files"],
            temperature=0.2,
            max_tokens=8192,
            priority=10,
        ),
        # ── 开发工程师 ──
        AgentRole.DEVELOPER: AgentProfile(
            role=AgentRole.DEVELOPER,
            name="开发工程师",
            description="编写高质量、可维护的代码实现",
            system_prompt=(
                "你是一位资深软件开发工程师，精通多种编程语言和框架。\n\n"
                "你的职责：\n"
                "1. 按照架构设计编写高质量代码\n"
                "2. 遵循项目编码规范和最佳实践\n"
                "3. 编写清晰的注释和文档字符串\n"
                "4. 处理边界条件和错误情况\n"
                "5. 确保代码可测试性\n\n"
                "工作原则：\n"
                "- 遵循 PEP 8 和团队编码规范\n"
                "- 使用类型注解提高代码可读性\n"
                "- 优先使用标准库和成熟依赖\n"
                "- 保持函数简短，单一职责\n"
                "- 编写自解释的代码"
            ),
            allowed_tools=[
                "read_file", "write_file", "create_file", "search_code",
                "execute_shell", "run_terminal",
            ],
            temperature=0.3,
            max_tokens=16384,
            priority=8,
        ),
        # ── 测试工程师 ──
        AgentRole.TESTER: AgentProfile(
            role=AgentRole.TESTER,
            name="测试工程师",
            description="编写测试用例，确保代码质量和覆盖率",
            system_prompt=(
                "你是一位资深测试工程师，擅长编写高质量的自动化测试。\n\n"
                "你的职责：\n"
                "1. 为代码编写全面的单元测试和集成测试\n"
                "2. 设计测试用例覆盖正常流程和边界情况\n"
                "3. 使用 mock 和 fixture 隔离外部依赖\n"
                "4. 确保测试覆盖率达到目标（>= 80%）\n"
                "5. 编写可维护的测试代码\n\n"
                "工作原则：\n"
                "- 使用 pytest 框架\n"
                "- 遵循 AAA 模式（Arrange-Act-Assert）\n"
                "- 测试命名清晰描述测试意图\n"
                "- 一个测试只验证一个行为\n"
                "- 优先测试业务逻辑而非实现细节"
            ),
            allowed_tools=[
                "read_file", "write_file", "search_code",
                "execute_shell", "run_terminal",
            ],
            temperature=0.3,
            max_tokens=8192,
            priority=7,
        ),
        # ── 调试专家 ──
        AgentRole.DEBUGGER: AgentProfile(
            role=AgentRole.DEBUGGER,
            name="调试专家",
            description="定位和修复代码中的 Bug 和异常",
            system_prompt=(
                "你是一位资深调试专家，擅长快速定位和修复复杂 Bug。\n\n"
                "你的职责：\n"
                "1. 分析错误日志和堆栈跟踪定位问题\n"
                "2. 复现 Bug 并确定根本原因\n"
                "3. 提出最小化修复方案\n"
                "4. 确保修复不引入新问题\n"
                "5. 建议添加防护措施防止回归\n\n"
                "工作原则：\n"
                "- 先理解，再修复\n"
                "- 使用二分法缩小问题范围\n"
                "- 添加日志和断言辅助调试\n"
                "- 修复后验证相关测试通过\n"
                "- 记录修复过程供团队参考"
            ),
            allowed_tools=[
                "read_file", "write_file", "search_code",
                "execute_shell", "run_terminal", "execute_python",
            ],
            temperature=0.2,
            max_tokens=8192,
            priority=9,
        ),
        # ── 代码审查员 ──
        AgentRole.REVIEWER: AgentProfile(
            role=AgentRole.REVIEWER,
            name="代码审查员",
            description="审查代码质量、规范性和潜在问题",
            system_prompt=(
                "你是一位资深代码审查员，严格但友善地审查代码。\n\n"
                "你的职责：\n"
                "1. 检查代码是否符合项目规范\n"
                "2. 识别潜在的逻辑错误和反模式\n"
                "3. 评估代码可读性和可维护性\n"
                "4. 检查是否有遗漏的边界条件\n"
                "5. 提供建设性的改进建议\n\n"
                "工作原则：\n"
                "- 关注代码逻辑而非个人风格偏好\n"
                "- 区分「必须修复」和「建议优化」\n"
                "- 给出具体的问题描述和修改建议\n"
                "- 识别重复代码和可提取的公共逻辑\n"
                "- 鼓励好的实践\n\n"
                "## PyCoder 项目结构知识库（审查时参考）\n\n"
                "### 依赖管理机制\n"
                "- pyproject.toml 中的 dependencies 使用 `~=` (兼容范围) 是标准写法\n"
                "- 精确锁定 (==) 在 requirements.txt 中 (由 pip-compile 生成)\n"
                "- optional-dependencies 通过 `dynamic` + `[tool.setuptools.dynamic.optional-dependencies]` 声明\n"
                "- 不要仅凭 pyproject.toml 的 `~=` 判断依赖未锁定\n\n"
                "### 项目已实现的功能模块\n"
                "- 持久化记忆: memory/__init__.py + pycoder/memory/ (SQLite + 向量检索)\n"
                "- 安全沙箱: safety/__init__.py + pycoder/safety/ (Docker + subprocess 降级)\n"
                "- 多模态: multimodal/__init__.py + pycoder/multimodal/ (OCR + 视觉模型)\n"
                "- 插件系统: plugins/__init__.py + pycoder/plugins/ (BasePlugin + 注册中心)\n"
                "- 错误监控: observability/__init__.py + pycoder/observability/ (Sentry 条件加载)\n\n"
                "### Windows 兼容性\n"
                "- 根目录: start.bat, start.ps1\n"
                "- scripts/: pycoder.bat, pycoder.ps1, run.py\n"
                "- 跨平台: Makefile\n\n"
                "### 测试配置\n"
                "- pyproject.toml 包含 [tool.pytest.ini_options] 段\n"
                "- pytest.ini 也存在\n\n"
                "### 审查时务必先读取实际文件验证，而不是假设文件不存在"
            ),
            allowed_tools=["read_file", "search_code", "list_files"],
            temperature=0.2,
            max_tokens=8192,
            priority=6,
        ),
        # ── 安全专家 ──
        AgentRole.SECURITY: AgentProfile(
            role=AgentRole.SECURITY,
            name="安全专家",
            description="审计代码安全，识别和修复安全漏洞",
            system_prompt=(
                "你是一位资深应用安全专家，专注于代码安全审计。\n\n"
                "你的职责：\n"
                "1. 审计代码中的安全漏洞（OWASP Top 10）\n"
                "2. 检查输入验证和输出编码\n"
                "3. 审查认证和授权逻辑\n"
                "4. 检测敏感信息泄露风险\n"
                "5. 建议安全加固措施\n\n"
                "关注的安全问题：\n"
                "- SQL/命令/代码注入\n"
                "- XSS 和 CSRF 攻击\n"
                "- 不安全的反序列化\n"
                "- 硬编码的密钥和凭证\n"
                "- 不安全的依赖版本\n"
                "- 权限提升和越权访问"
            ),
            allowed_tools=["read_file", "search_code", "execute_shell"],
            temperature=0.1,
            max_tokens=8192,
            priority=9,
        ),
        # ── 运维工程师 ──
        AgentRole.DEVOPS: AgentProfile(
            role=AgentRole.DEVOPS,
            name="运维工程师",
            description="管理部署、CI/CD 管道和基础设施",
            system_prompt=(
                "你是一位资深 DevOps 工程师，擅长 CI/CD 和基础设施管理。\n\n"
                "你的职责：\n"
                "1. 设计和配置 CI/CD 管道\n"
                "2. 编写 Dockerfile 和容器编排配置\n"
                "3. 管理环境配置和密钥\n"
                "4. 配置监控和告警\n"
                "5. 优化构建和部署流程\n\n"
                "工作原则：\n"
                "- 基础设施即代码（IaC）\n"
                "- 不可变基础设施\n"
                "- 自动化优先\n"
                "- 安全左移"
            ),
            allowed_tools=[
                "read_file", "write_file", "execute_shell",
                "run_terminal", "search_code",
            ],
            temperature=0.3,
            max_tokens=8192,
            priority=7,
        ),
        # ── 文档工程师 ──
        AgentRole.DOCUMENTER: AgentProfile(
            role=AgentRole.DOCUMENTER,
            name="文档工程师",
            description="编写和维护 API 文档、技术文档和使用指南",
            system_prompt=(
                "你是一位资深技术文档工程师，擅长将复杂技术转化为清晰文档。\n\n"
                "你的职责：\n"
                "1. 编写 API 文档和接口说明\n"
                "2. 为函数和类添加 docstring\n"
                "3. 编写 README 和使用指南\n"
                "4. 维护变更日志（CHANGELOG）\n"
                "5. 编写架构决策记录\n\n"
                "工作原则：\n"
                "- 文档即代码，保持同步更新\n"
                "- 使用清晰的中文描述\n"
                "- 包含可运行的示例代码\n"
                "- 从用户视角组织内容\n"
                "- 遵循 Google/NumPy docstring 风格"
            ),
            allowed_tools=["read_file", "write_file", "search_code"],
            temperature=0.4,
            max_tokens=8192,
            priority=4,
        ),
        # ── 性能优化师 ──
        AgentRole.OPTIMIZER: AgentProfile(
            role=AgentRole.OPTIMIZER,
            name="性能优化师",
            description="分析性能瓶颈并实施优化方案",
            system_prompt=(
                "你是一位资深性能优化专家，专注于代码和系统性能调优。\n\n"
                "你的职责：\n"
                "1. 使用 profiling 工具分析性能瓶颈\n"
                "2. 优化算法复杂度（时间/空间）\n"
                "3. 引入缓存策略减少重复计算\n"
                "4. 优化数据库查询和索引\n"
                "5. 建议并发和异步优化方案\n\n"
                "优化原则：\n"
                "- 先测量，再优化\n"
                "- 优先优化热点路径\n"
                "- 不牺牲可读性换取微小性能\n"
                "- 考虑内存和 CPU 的平衡\n"
                "- 记录优化效果（benchmark）"
            ),
            allowed_tools=[
                "read_file", "write_file", "search_code",
                "execute_shell", "execute_python",
            ],
            temperature=0.2,
            max_tokens=8192,
            priority=6,
        ),
        # ── 团队协调者 ──
        AgentRole.ORCHESTRATOR: AgentProfile(
            role=AgentRole.ORCHESTRATOR,
            name="团队协调者",
            description="分解任务、分配角色、协调团队协作",
            system_prompt=(
                "你是一位资深技术项目经理，擅长任务分解和团队协调。\n\n"
                "你的职责：\n"
                "1. 将复杂任务分解为可执行的子任务\n"
                "2. 根据任务特性选择合适的 Agent 角色\n"
                "3. 确定任务间的依赖关系\n"
                "4. 协调并行和顺序执行\n"
                "5. 汇总和整合团队输出\n\n"
                "工作原则：\n"
                "- 任务粒度适中，可独立完成\n"
                "- 明确依赖关系和执行顺序\n"
                "- 合理分配资源，避免瓶颈\n"
                "- 跟踪进度并及时调整\n"
                "- 确保最终交付物的完整性"
            ),
            allowed_tools=["read_file", "search_code", "list_files"],
            temperature=0.3,
            max_tokens=8192,
            priority=10,
        ),
    }


# ──────────────────────────────────────────────
# 任务数据类
# ──────────────────────────────────────────────


@dataclass
class TeamTask:
    """团队任务"""

    task_id: str
    description: str
    assigned_role: AgentRole | None = None
    dependencies: list[str] = field(default_factory=list)
    status: str = "pending"  # pending | running | done | failed
    result: Any = None
    error: str | None = None


# ──────────────────────────────────────────────
# Team 类
# ──────────────────────────────────────────────


class Team:
    """
    专业 Agent 团队

    管理一组 Agent 角色，分配任务，协调执行。

    使用方式:
        team = Team("feature-team", [AgentRole.ARCHITECT, AgentRole.DEVELOPER, AgentRole.TESTER])
        team.assign_task(AgentRole.DEVELOPER, "实现用户登录功能")
        results = await team.execute_parallel(tasks)
    """

    def __init__(self, name: str, roles: list[AgentRole]) -> None:
        """
        创建团队

        Args:
            name: 团队名称
            roles: 团队包含的角色列表
        """
        self.name = name
        self.roles = roles
        self.profiles = _build_profiles()
        self._tasks: dict[str, TeamTask] = {}
        self._results: dict[str, Any] = {}
        self._progress: dict[str, str] = {}  # task_id -> status

    @property
    def members(self) -> list[AgentProfile]:
        """获取团队成员配置"""
        return [self.profiles[r] for r in self.roles if r in self.profiles]

    def assign_task(
        self, agent: AgentRole | AgentProfile, task: str | TeamTask
    ) -> TeamTask:
        """
        分配任务给指定 Agent

        Args:
            agent: Agent 角色或配置
            task: 任务描述或 TeamTask 实例

        Returns:
            创建的 TeamTask 实例
        """
        import uuid

        role = agent.role if isinstance(agent, AgentProfile) else agent

        if isinstance(task, TeamTask):
            task.assigned_role = role
            team_task = task
        else:
            team_task = TeamTask(
                task_id=str(uuid.uuid4())[:8],
                description=task,
                assigned_role=role,
            )

        self._tasks[team_task.task_id] = team_task
        self._progress[team_task.task_id] = "pending"
        logger.info(
            "团队 '%s': 任务 '%s' 分配给 %s",
            self.name,
            team_task.task_id,
            role.value,
        )
        return team_task

    async def execute_parallel(
        self, tasks: list[TeamTask]
    ) -> dict[str, Any]:
        """
        并行执行多个任务

        Args:
            tasks: 任务列表

        Returns:
            任务 ID 到结果的映射
        """
        if not tasks:
            return {}

        async def _run(task: TeamTask) -> tuple[str, Any]:
            self._progress[task.task_id] = "running"
            try:
                # 模拟执行 — 实际调用会通过总线委托给 AI LLM
                await asyncio.sleep(0.01)
                role_val = task.assigned_role.value if task.assigned_role else "unknown"
                result = f"[{role_val}] 完成: {task.description[:80]}"
                task.status = "done"
                task.result = result
                self._progress[task.task_id] = "done"
                self._results[task.task_id] = result
                return task.task_id, result
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                self._progress[task.task_id] = "failed"
                return task.task_id, None

        results_list = await asyncio.gather(*[_run(t) for t in tasks])
        return dict(results_list)

    async def execute_sequential(
        self, tasks: list[TeamTask]
    ) -> dict[str, Any]:
        """
        顺序执行多个任务

        Args:
            tasks: 任务列表

        Returns:
            任务 ID 到结果的映射
        """
        results: dict[str, Any] = {}
        for task in tasks:
            batch_result = await self.execute_parallel([task])
            results.update(batch_result)
        return results

    def get_progress(self) -> dict[str, Any]:
        """
        获取团队进度报告

        Returns:
            包含进度统计和任务状态的字典
        """
        total = len(self._tasks)
        done = sum(1 for s in self._progress.values() if s == "done")
        failed = sum(1 for s in self._progress.values() if s == "failed")
        running = sum(1 for s in self._progress.values() if s == "running")
        pending = sum(1 for s in self._progress.values() if s == "pending")

        return {
            "team_name": self.name,
            "members": [r.value for r in self.roles],
            "total_tasks": total,
            "done": done,
            "failed": failed,
            "running": running,
            "pending": pending,
            "progress_pct": round(done / total * 100, 1) if total > 0 else 0.0,
            "tasks": {
                tid: {
                    "status": st,
                    "role": (
                        self._tasks[tid].assigned_role.value
                        if self._tasks[tid].assigned_role
                        else "unknown"
                    ),
                }
                for tid, st in self._progress.items()
            },
        }

    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        if task_id in self._tasks:
            self._tasks[task_id].status = "cancelled"
            self._progress[task_id] = "cancelled"
            logger.info("团队 '%s': 任务 '%s' 已取消", self.name, task_id)
            return True
        return False


# ──────────────────────────────────────────────
# SpecializedAgentTeam 类
# ──────────────────────────────────────────────


class SpecializedAgentTeam:
    """
    10 角色专业 Agent 团队管理器

    功能:
    - 管理 10 个预定义角色的 Agent 配置
    - 根据任务描述自动选择合适角色
    - 创建临时团队
    - 查询所有可用角色

    使用方式:
        team_mgr = SpecializedAgentTeam()
        agents = team_mgr.select_agents("实现一个用户认证系统")
        team = team_mgr.create_team("auth-team", [a.role for a in agents])
    """

    def __init__(self) -> None:
        self._profiles = _build_profiles()
        self._active_teams: dict[str, Team] = {}

    # ── 查询 ──────────────────────────────────

    def get_agent(self, role: AgentRole) -> AgentProfile:
        """
        获取指定角色的 Agent 配置

        Args:
            role: Agent 角色

        Returns:
            AgentProfile 配置

        Raises:
            ValueError: 角色不存在
        """
        if role not in self._profiles:
            raise ValueError(f"未知角色: {role}")
        return self._profiles[role]

    def get_all_roles(self) -> list[AgentRole]:
        """获取所有可用角色"""
        return list(AgentRole)

    def get_all_profiles(self) -> list[AgentProfile]:
        """获取所有角色的配置"""
        return list(self._profiles.values())

    # ── 自动选角 ──────────────────────────────

    def select_agents(self, task_description: str) -> list[AgentProfile]:
        """
        根据任务描述自动选择合适的 Agent 角色

        基于关键词匹配，计算每个角色与任务的相关度分数，
        返回相关度最高的角色列表。

        Args:
            task_description: 任务描述文本

        Returns:
            匹配的 AgentProfile 列表，按相关度降序排列
        """
        desc_lower = task_description.lower()
        scored: list[tuple[AgentProfile, int]] = []

        for role, profile in self._profiles.items():
            keywords = _ROLE_KEYWORDS.get(role, [])
            score = 0
            for kw in keywords:
                if kw in desc_lower:
                    score += 1
            if score > 0:
                scored.append((profile, score))

        # 按分数降序排列
        scored.sort(key=lambda x: x[1], reverse=True)
        return [p for p, _ in scored]

    # ── 团队管理 ──────────────────────────────

    def create_team(self, name: str, roles: list[AgentRole]) -> Team:
        """
        创建专业 Agent 团队

        Args:
            name: 团队名称
            roles: 角色列表

        Returns:
            Team 实例
        """
        team = Team(name, roles)
        self._active_teams[name] = team
        logger.info(
            "创建团队 '%s'，成员: %s",
            name,
            [r.value for r in roles],
        )
        return team

    def get_team(self, name: str) -> Team | None:
        """获取已创建的团队"""
        return self._active_teams.get(name)

    def list_teams(self) -> list[str]:
        """列出所有活跃团队"""
        return list(self._active_teams.keys())

    def disband_team(self, name: str) -> bool:
        """解散团队"""
        if name in self._active_teams:
            del self._active_teams[name]
            logger.info("团队 '%s' 已解散", name)
            return True
        return False


# ──────────────────────────────────────────────
# 全局实例
# ──────────────────────────────────────────────

_agent_team: SpecializedAgentTeam | None = None


def get_agent_team() -> SpecializedAgentTeam:
    """获取全局专业 Agent 团队管理器"""
    global _agent_team
    if _agent_team is None:
        _agent_team = SpecializedAgentTeam()
    return _agent_team


# ──────────────────────────────────────────────
# 能力注册
# ──────────────────────────────────────────────


def register_capabilities(registry: Any) -> None:
    """
    向总线注册 Agent 团队相关能力

    注册的能力:
    - agents.team.list — 列出所有 Agent 角色
    - agents.team.select — 根据任务描述自动选角
    - agents.team.create — 创建专业 Agent 团队
    - agents.team.assign — 分配任务给 Agent

    Args:
        registry: CapabilityRegistry 实例
    """
    _ = get_agent_team()  # 确保 Agent 团队已初始化

    # ── agents.team.list ──
    registry.register(
        CapabilityDefinition(
            id="agents.team.list",
            name="列出 Agent 角色",
            description="列出所有 10 个专业 Agent 角色及其配置",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["agents", "team", "list", "角色", "团队"],
        ),
        handler=_handle_team_list,
    )

    # ── agents.team.select ──
    registry.register(
        CapabilityDefinition(
            id="agents.team.select",
            name="选择 Agent 角色",
            description="根据任务描述自动选择合适的 Agent 角色",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            schema={
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "任务描述文本",
                    },
                },
                "required": ["task_description"],
            },
            tags=["agents", "team", "select", "选择", "自动"],
        ),
        handler=_handle_team_select,
    )

    # ── agents.team.create ──
    registry.register(
        CapabilityDefinition(
            id="agents.team.create",
            name="创建 Agent 团队",
            description="创建包含指定角色的专业 Agent 团队",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "团队名称",
                    },
                    "roles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "角色列表（如: architect, developer, tester）",
                    },
                },
                "required": ["name", "roles"],
            },
            tags=["agents", "team", "create", "创建", "团队"],
        ),
        handler=_handle_team_create,
    )

    # ── agents.team.assign ──
    registry.register(
        CapabilityDefinition(
            id="agents.team.assign",
            name="分配 Agent 任务",
            description="将任务分配给指定团队中的 Agent",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            schema={
                "type": "object",
                "properties": {
                    "team_name": {
                        "type": "string",
                        "description": "团队名称",
                    },
                    "role": {
                        "type": "string",
                        "description": "Agent 角色",
                    },
                    "task": {
                        "type": "string",
                        "description": "任务描述",
                    },
                },
                "required": ["team_name", "role", "task"],
            },
            tags=["agents", "team", "assign", "分配", "任务"],
        ),
        handler=_handle_team_assign,
    )

    logger.info("Agent 团队能力已注册（4 个能力）")


# ── 处理器实现 ────────────────────────────────


async def _handle_team_list(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理 agents.team.list 请求"""
    team_mgr = get_agent_team()
    profiles = team_mgr.get_all_profiles()
    return {
        "roles": [p.to_dict() for p in profiles],
        "count": len(profiles),
    }


async def _handle_team_select(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理 agents.team.select 请求"""
    team_mgr = get_agent_team()
    task_desc = params["task_description"]
    agents = team_mgr.select_agents(task_desc)
    return {
        "task": task_desc,
        "selected": [p.to_dict() for p in agents],
        "count": len(agents),
    }


async def _handle_team_create(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理 agents.team.create 请求"""
    team_mgr = get_agent_team()
    name = params["name"]
    role_names = params["roles"]

    # 解析角色名
    roles: list[AgentRole] = []
    invalid_roles: list[str] = []
    for rn in role_names:
        try:
            roles.append(AgentRole(rn))
        except ValueError:
            invalid_roles.append(rn)

    if invalid_roles:
        return {
            "success": False,
            "error": f"无效角色: {invalid_roles}",
            "valid_roles": [r.value for r in AgentRole],
        }

    team = team_mgr.create_team(name, roles)
    return {
        "success": True,
        "team_name": team.name,
        "members": [r.value for r in team.roles],
        "member_count": len(team.roles),
    }


async def _handle_team_assign(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理 agents.team.assign 请求"""
    team_mgr = get_agent_team()
    team_name = params["team_name"]
    role_name = params["role"]
    task_desc = params["task"]

    team = team_mgr.get_team(team_name)
    if team is None:
        return {
            "success": False,
            "error": f"团队不存在: {team_name}",
            "available_teams": team_mgr.list_teams(),
        }

    try:
        role = AgentRole(role_name)
    except ValueError:
        return {
            "success": False,
            "error": f"无效角色: {role_name}",
            "valid_roles": [r.value for r in AgentRole],
        }

    if role not in team.roles:
        return {
            "success": False,
            "error": f"角色 '{role_name}' 不在团队 '{team_name}' 中",
            "team_members": [r.value for r in team.roles],
        }

    task = team.assign_task(role, task_desc)
    return {
        "success": True,
        "team_name": team_name,
        "task_id": task.task_id,
        "role": role.value,
        "description": task.description,
        "status": task.status,
    }