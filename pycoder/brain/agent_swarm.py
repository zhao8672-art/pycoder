"""
Agent 集群编排器 — 多角色并行协作引擎

支持:
- 角色工厂: 动态创建不同角色的 Agent
- 并行执行: 独立任务并行分发给多个 Agent
- 依赖感知: 上游任务完成后再启动下游
- 结果聚合: 合并多个 Agent 的输出
- AI 驱动执行: 通过 ChatBridge 调用 LLM 执行任务（P0-3 增强）
- 智能选角: 整合 IntelligentRouter 进行意图感知的角色分配（P0-3 增强）
"""

from __future__ import annotations

import asyncio
import enum
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── 角色 → 系统提示词映射（P0-3: 为每个角色定制专用提示词）──

ROLE_SYSTEM_PROMPTS: dict[str, str] = {
    "architect": (
        "你是 PyCoder 架构师 Agent。专注系统设计、架构规划和模块划分。"
        "输出结构化设计方案，包含组件关系、数据流和接口定义。"
    ),
    "developer": (
        "你是 PyCoder 开发 Agent。专注编写高质量、可维护的 Python 代码。"
        "遵循 PEP 8 规范，使用类型注解，优先编辑现有文件而非创建新文件。"
    ),
    "reviewer": (
        "你是 PyCoder 代码审查 Agent。检查代码质量、安全漏洞和最佳实践。"
        "输出结构化的审查报告，指出具体问题和改进建议。"
    ),
    "tester": (
        "你是 PyCoder 测试 Agent。编写 pytest 测试用例，确保覆盖率 >= 80%。"
        "使用 fixture 隔离测试，覆盖边界条件和异常路径。"
    ),
    "devops": (
        "你是 PyCoder 运维 Agent。处理部署、配置、CI/CD 和环境管理。"
        "确保配置安全（不硬编码密钥），自动化部署流程。"
    ),
    "analyst": (
        "你是 PyCoder 分析 Agent。分析需求、文档和代码库。"
        "输出结构化的分析报告，包含关键发现和可行建议。"
    ),
}


class AgentRole(enum.StrEnum):
    """预定义的 Agent 角色"""

    ARCHITECT = "architect"  # 架构师：设计系统结构
    DEVELOPER = "developer"  # 开发：编写代码
    REVIEWER = "reviewer"  # 审查：代码审查
    TESTER = "tester"  # 测试：编写和运行测试
    DEVOPS = "devops"  # 运维：部署和配置
    ANALYST = "analyst"  # 分析：需求分析和文档


@dataclass
class AgentTask:
    """分配给 Agent 的任务"""

    task_id: str
    role: AgentRole
    prompt: str
    dependencies: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Agent 执行结果"""

    task_id: str
    role: AgentRole
    success: bool
    output: str = ""
    error: str | None = None
    files_modified: list[str] = field(default_factory=list)
    tokens_used: int = 0
    duration_seconds: float = 0.0


class AgentSwarmOrchestrator:
    """
    Agent 集群编排器

    功能:
    - 将任务列表分配给不同角色的 Agent
    - 管理并行执行与依赖关系
    - 聚合结果并处理冲突
    - AI 驱动执行: 通过 ChatBridge 调用 LLM（P0-3）
    - 智能选角: 整合 IntelligentRouter（P0-3）
    """

    # P0-3: 角色 → 关键词权重映射（用于智能选角）
    _ROLE_KEYWORDS: dict[AgentRole, list[tuple[str, float]]] = {
        AgentRole.ARCHITECT: [
            ("设计", 0.9),
            ("架构", 0.9),
            ("design", 0.8),
            ("architect", 0.8),
            ("规划", 0.7),
            ("结构", 0.7),
            ("模块划分", 0.8),
            ("接口", 0.6),
            ("plan", 0.7),
            ("structure", 0.7),
        ],
        AgentRole.DEVELOPER: [
            ("实现", 0.8),
            ("编写", 0.8),
            ("开发", 0.8),
            ("代码", 0.7),
            ("implement", 0.8),
            ("code", 0.7),
            ("develop", 0.8),
            ("功能", 0.6),
            ("修复", 0.7),
            ("fix", 0.7),
            ("bug", 0.6),
            ("修改", 0.6),
        ],
        AgentRole.REVIEWER: [
            ("审查", 0.9),
            ("review", 0.9),
            ("检查", 0.7),
            ("check", 0.7),
            ("质量", 0.7),
            ("quality", 0.7),
            ("审计", 0.8),
            ("audit", 0.8),
            ("安全", 0.6),
            ("security", 0.6),
        ],
        AgentRole.TESTER: [
            ("测试", 0.9),
            ("test", 0.9),
            ("验证", 0.7),
            ("verify", 0.7),
            ("用例", 0.8),
            ("覆盖率", 0.8),
            ("coverage", 0.8),
            ("pytest", 0.8),
        ],
        AgentRole.DEVOPS: [
            ("部署", 0.9),
            ("deploy", 0.9),
            ("发布", 0.8),
            ("release", 0.8),
            ("配置", 0.7),
            ("config", 0.7),
            ("CI/CD", 0.9),
            ("环境", 0.7),
            ("docker", 0.8),
            ("容器", 0.7),
        ],
        AgentRole.ANALYST: [
            ("分析", 0.9),
            ("analyze", 0.9),
            ("需求", 0.8),
            ("requirement", 0.8),
            ("文档", 0.7),
            ("document", 0.7),
            ("调研", 0.7),
            ("research", 0.7),
            ("报告", 0.7),
            ("report", 0.7),
        ],
    }

    def __init__(self):
        self._active_agents: dict[str, AgentTask] = {}
        self._results: dict[str, AgentResult] = {}
        self._chat_bridge: Any = None  # P0-3: ChatBridge 引用

    async def execute(
        self,
        tasks: list[AgentTask],
        *,
        parallel: bool = True,
        on_progress: Any = None,
    ) -> list[AgentResult]:
        """
        执行一组 Agent 任务

        Args:
            tasks: 任务列表
            parallel: 是否并行执行
            on_progress: 进度回调

        Returns:
            执行结果列表
        """
        if not tasks:
            return []

        # 构建依赖图
        {t.task_id: t for t in tasks}
        completed: set[str] = set()
        results: list[AgentResult] = []

        while len(completed) < len(tasks):
            # 找到所有可执行的任务（依赖已满足）
            ready = [
                t
                for t in tasks
                if t.task_id not in completed and all(d in completed for d in t.dependencies)
            ]

            if not ready:
                # 死锁检测
                logger.error("死锁检测: 等待的依赖无法满足")
                break

            if parallel and len(ready) > 1:
                # 并行执行
                batch_results = await asyncio.gather(*[self._execute_single(t) for t in ready])
                for r in batch_results:
                    results.append(r)
                    completed.add(r.task_id)
                    self._results[r.task_id] = r
            else:
                # 顺序执行
                for t in ready:
                    r = await self._execute_single(t)
                    results.append(r)
                    completed.add(r.task_id)
                    self._results[r.task_id] = r

                    if callable(on_progress):
                        on_progress(t.task_id, r)

        return results

    # ── P0-3: ChatBridge 注入 ──

    def set_chat_bridge(self, bridge: Any) -> None:
        """注入 ChatBridge 实例，启用 AI 驱动的 Agent 执行

        Args:
            bridge: ChatBridge 实例（提供 chat() 方法）
        """
        self._chat_bridge = bridge

    # ── 任务执行 ──

    async def _execute_single(self, task: AgentTask) -> AgentResult:
        """
        执行单个 Agent 任务（P0-3 增强: AI 驱动）

        优先使用 ChatBridge 调用 LLM，未配置时降级为本地模拟。
        """
        import time

        start = time.monotonic()

        try:
            # 获取角色专用系统提示词
            role_prompt = ROLE_SYSTEM_PROMPTS.get(task.role.value, "")
            full_prompt = f"{role_prompt}\n\n" f"## 任务\n{task.prompt}\n\n" f"请用中文输出结果。"

            if self._chat_bridge:
                # P0-3: AI 驱动执行
                try:
                    self._chat_bridge.configure(
                        system_prompt=role_prompt,
                        max_tokens=4096,
                    )
                    output = await self._chat_bridge.chat(full_prompt, max_tokens=4096)
                    if not output:
                        output = await self._chat_bridge.chat(
                            f"请完成以下任务: {task.prompt}",
                            max_tokens=2048,
                        )
                except Exception as e:
                    logger.warning("agent_chatbridge_failed role=%s error=%s", task.role.value, e)
                    output = (
                        f"[{task.role.value}] AI 调用失败: {e}\n\n请手动处理: {task.prompt[:200]}"
                    )
            else:
                # 降级: 本地模拟（无 ChatBridge 时）
                logger.info("agent_no_chatbridge role=%s, using mock execution", task.role.value)
                output = f"[{task.role.value}] 任务描述: {task.prompt[:200]}\n\n（未配置 ChatBridge，请手动执行）"

            duration = time.monotonic() - start

            return AgentResult(
                task_id=task.task_id,
                role=task.role,
                success=True,
                output=output,
                tokens_used=len(full_prompt) // 4 + len(output) // 4,
                duration_seconds=duration,
            )
        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                role=task.role,
                success=False,
                error=str(e),
            )

    def get_result(self, task_id: str) -> AgentResult | None:
        """获取任务结果"""
        return self._results.get(task_id)

    def get_all_results(self) -> dict[str, AgentResult]:
        """获取所有结果"""
        return dict(self._results)

    def cancel_task(self, task_id: str) -> None:
        """取消任务"""
        task = self._active_agents.pop(task_id, None)
        if task:
            logger.info("任务已取消: %s", task_id)

    # ── P0-3: 智能选角 ──

    @classmethod
    def auto_assign(cls, task_description: str) -> tuple[AgentRole, float]:
        """根据任务描述自动选择最佳 Agent 角色（P0-3 增强: 加权关键词匹配）

        使用加权关键词匹配计算每个角色的匹配分数，
        选择得分最高的角色。

        Args:
            task_description: 任务描述文本

        Returns:
            (最佳角色, 匹配置信度)
        """
        desc_lower = task_description.lower()
        scores: dict[AgentRole, float] = {}

        for role, keywords in cls._ROLE_KEYWORDS.items():
            score = 0.0
            for keyword, weight in keywords:
                if keyword.lower() in desc_lower:
                    score += weight
            scores[role] = score  # 不归一化，直接使用加权和

        if not scores:
            return AgentRole.DEVELOPER, 0.3

        best_role = max(scores, key=scores.get)
        best_score = scores[best_role]
        # 如果最高分太低，默认 DEVELOPER
        if best_score < 0.5:
            return AgentRole.DEVELOPER, 0.3

        return best_role, min(best_score / 2.0, 1.0)  # 置信度归一化

    @staticmethod
    def assign_roles(tasks: list[Any]) -> list[AgentTask]:
        """
        根据任务描述自动分配 Agent 角色（P0-3 增强: 加权关键词匹配）

        Args:
            tasks: TaskPlanner.Task 列表

        Returns:
            AgentTask 列表
        """
        agent_tasks: list[AgentTask] = []

        for task in tasks:
            task.description.lower()

            # P0-3: 使用加权关键词匹配（替代简单关键词检测）
            role, _ = AgentSwarmOrchestrator.auto_assign(task.description)

            agent_tasks.append(
                AgentTask(
                    task_id=task.task_id,
                    role=role,
                    prompt=task.description,
                    dependencies=task.dependencies,
                )
            )

        return agent_tasks
