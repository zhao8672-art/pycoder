"""
TaskDecomposer — LLM 驱动的需求→任务分解
"""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass, field

from pycoder.server.services.agent_definitions import AgentTask, create_task

logger = logging.getLogger(__name__)


DECOMPOSE_SYSTEM_PROMPT = """你是 PyCoder 项目任务分解专家。
分析用户需求，将其拆解为可执行的子任务。

输出格式: 纯 JSON，不要使用 markdown 代码块

{
    "project_name": "项目名",
    "description": "项目简要描述",
    "tech_stack_required": ["需要的技术"],
    "tasks": [
        {
            "title": "任务标题",
            "description": "任务详细描述",
            "assigned_role": "pm|architect|developer|qa|devops",
            "depends_on": ["前置任务标题"],
            "deliverables": ["交付物路径"]
        }
    ]
}

原则:
- 每个任务应该是一个独立的功能点
- 明确任务间的依赖关系
- 优先拆解可以并行执行的任务
- 架构师任务必须先于开发者任务
- QA 任务必须在开发者任务之后
- DevOps 任务在最后
- **禁止使用 XML 标签**，仅输出纯 JSON

## 示例

用户需求：创建一个 FastAPI Hello World API

{"project_name":"hello-api","description":"FastAPI Hello World 示例","tech_stack_required":["fastapi","uvicorn"],"tasks":[{"title":"设计 API 架构","description":"定义路由和响应模型","assigned_role":"architect","depends_on":[],"deliverables":["docs/api-design.md"]},{"title":"实现 Hello World 端点","description":"创建 GET /api/hello 返回问候语","assigned_role":"developer","depends_on":["设计 API 架构"],"deliverables":["app.py"]},{"title":"验证 API 响应","description":"测试端点返回正确结果","assigned_role":"qa","depends_on":["实现 Hello World 端点"],"deliverables":["test_app.py"]}]}
"""


async def decompose_task(user_request: str, chat_bridge=None) -> list[AgentTask]:
    """
    使用 LLM 将用户需求分解为子任务列表

    参数:
        user_request: 用户需求描述
        chat_bridge: ChatBridge 实例 (可选，不传则返回保底分解)

    返回:
        AgentTask 列表
    """
    tasks: list[AgentTask] = []

    if chat_bridge:
        # P0: 优先尝试 LLMProvider 端口 (DI注入), 回退 ChatBridge
        from pycoder.core.ports.llm_provider import LLMProvider as _LLMP

        if isinstance(chat_bridge, _LLMP):
            tasks = await _decompose_via_llm_provider(user_request, chat_bridge)
        else:
            tasks = await _decompose_via_chatbridge(user_request, chat_bridge)

    # 保底分解：如果 LLM 失败或没有返回有效任务
    if not tasks:
        tasks = _fallback_decomposition(user_request)

    return tasks


async def _decompose_via_llm_provider(user_request: str, llm) -> list[AgentTask]:
    """P0: 通过 LLMProvider 端口进行任务分解"""
    from pycoder.server.chat_handler import _get_api_key_for_model

    api_key = _get_api_key_for_model("deepseek-chat")
    llm.configure(model="deepseek-chat", api_key=api_key)

    result = ""
    async for event in llm.stream(
        user_request,
        system_prompt=DECOMPOSE_SYSTEM_PROMPT,
        max_tokens=4096,
    ):
        if event.event_type == "token":
            result += event.content

    return _parse_decomposition_json(result)


async def _decompose_via_chatbridge(user_request: str, chat_bridge) -> list[AgentTask]:
    """P0: 通过 ChatBridge 进行任务分解 (向后兼容路径)"""
    from pycoder.server.chat_handler import _get_api_key_for_model

    api_key = _get_api_key_for_model("deepseek-chat")
    chat_bridge.configure(model="deepseek-chat", api_key=api_key)
    chat_bridge.config.system_prompt = DECOMPOSE_SYSTEM_PROMPT
    chat_bridge.config.max_tokens = 4096

    result = ""
    async for event in chat_bridge.chat_stream(user_request):
        if event.event_type == "token":
            result += event.content

    await chat_bridge.close()
    return _parse_decomposition_json(result)


def _parse_decomposition_json(result: str) -> list[AgentTask]:
    """P0: 解析 LLM 返回的 JSON 任务分解"""
    tasks: list[AgentTask] = []
    cleaned = result.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.rsplit("```", 1)[0]
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError, KeyError, ValueError) as e:
        logger.warning("task_decompose_parse_failed error=%s", e)
        return tasks

    for t in data.get("tasks", []):
        tasks.append(
            create_task(
                title=t.get("title", "Untitled task"),
                description=t.get("description", ""),
                assigned_role=t.get("assigned_role", "developer"),
                depends_on=t.get("depends_on", []),
                deliverables=t.get("deliverables", []),
            )
        )
    return tasks


def _fallback_decomposition(user_request: str) -> list[AgentTask]:
    """保底任务分解（不依赖 LLM）"""
    request_lower = user_request.lower()
    tasks: list[AgentTask] = []

    # 检测项目类型
    is_web = any(
        w in request_lower for w in ["web", "网站", "页面", "api", "接口", "前端", "后端", "html"]
    )
    is_python = any(w in request_lower for w in ["python", "脚本", "工具", "cli", "命令行"])
    has_db = any(w in request_lower for w in ["数据库", "db", "sql", "存储", "数据"])

    # FIX #2: 先创建所有任务以便用 ID 做依赖，而非标题
    arch_task = create_task(
        title="系统架构设计",
        description=f"分析需求，设计系统架构，确定技术栈。{user_request[:200]}",
        assigned_role="architect",
        deliverables=["docs/architecture.md"],
    )
    tasks.append(arch_task)

    dev_tasks: list[AgentTask] = []

    if is_web:
        backend = create_task(
            title="后端开发",
            description=f"开发后端 API 和业务逻辑。{user_request[:200]}",
            assigned_role="developer",
            depends_on=[arch_task.id],
            deliverables=["app.py", "requirements.txt"],
        )
        frontend = create_task(
            title="前端开发",
            description=f"开发前端界面。{user_request[:200]}",
            assigned_role="developer",
            depends_on=[arch_task.id],
            deliverables=["index.html", "static/"],
        )
        tasks.append(backend)
        tasks.append(frontend)
        dev_tasks.extend([backend, frontend])
    elif is_python:
        py_dev = create_task(
            title="Python 模块开发",
            description=f"开发 Python 模块。{user_request[:200]}",
            assigned_role="developer",
            depends_on=[arch_task.id],
            deliverables=["main.py"],
        )
        tasks.append(py_dev)
        dev_tasks.append(py_dev)

    if has_db:
        db_task = create_task(
            title="数据库设计与实现",
            description="设计数据库模型和初始化脚本",
            assigned_role="developer",
            depends_on=[arch_task.id],
            deliverables=["models.py", "schema.sql"],
        )
        tasks.append(db_task)
        dev_tasks.append(db_task)

    # 如果没有特定类型，给一个通用开发任务
    if not dev_tasks:
        gen_dev = create_task(
            title="代码开发",
            description=f"根据架构设计完成编码。{user_request[:200]}",
            assigned_role="developer",
            depends_on=[arch_task.id],
            deliverables=["output/"],
        )
        tasks.append(gen_dev)
        dev_tasks.append(gen_dev)

    # 测试任务 — FIX #2: 用 ID 而非标题
    qa_task = create_task(
        title="编写测试用例",
        description="为项目编写测试用例",
        assigned_role="qa",
        depends_on=[t.id for t in dev_tasks],
        deliverables=["tests/"],
    )
    tasks.append(qa_task)

    # DevOps 任务
    final_deps = [t.id for t in dev_tasks] + [qa_task.id]
    devops_task = create_task(
        title="Docker 化与部署配置",
        description="编写 Dockerfile, docker-compose, README",
        assigned_role="devops",
        depends_on=final_deps,
        deliverables=["Dockerfile", "docker-compose.yml", "README.md"],
    )
    tasks.append(devops_task)

    return tasks


# ══════════════════════════════════════════════════════════
# DAG（有向无环图）支持 — 对标 Codex DAG 任务分解
# ══════════════════════════════════════════════════════════


@dataclass
class TaskNode:
    """DAG 任务节点"""

    task: AgentTask
    level: int = 0  # 拓扑层级（用于并行分组）
    children: list[str] = field(default_factory=list)  # 下游任务 ID

    def to_dict(self) -> dict:
        return {
            "task_id": self.task.id,
            "title": self.task.title,
            "assigned_role": self.task.assigned_role,
            "level": self.level,
            "depends_on": self.task.depends_on,
            "children": self.children,
            "status": self.task.status,
        }


@dataclass
class TaskDAG:
    """任务依赖有向无环图

    - nodes: ID → TaskNode 映射
    - edges: (from_id, to_id) 依赖边
    - parallel_groups: 每层可并行执行的任务组
    """

    nodes: dict[str, TaskNode] = field(default_factory=dict)
    edges: list[tuple[str, str]] = field(default_factory=list)
    parallel_groups: list[list[str]] = field(default_factory=list)
    total_levels: int = 0

    def to_dict(self) -> dict:
        return {
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "edges": self.edges,
            "parallel_groups": self.parallel_groups,
            "total_levels": self.total_levels,
        }

    def max_parallel_count(self) -> int:
        """返回最大并行任务数"""
        return max(len(g) for g in self.parallel_groups) if self.parallel_groups else 1


def build_task_dag(tasks: list[AgentTask]) -> TaskDAG:
    """从任务列表构建 DAG，通过拓扑排序发现可并行组

    流程:
        1. 建立 ID → Node 映射
        2. 拓扑排序 (Kahn 算法)
        3. 按拓扑层级分组 → 同层可并行

    Returns:
        TaskDAG — 包含节点、边、并行分组
    """
    dag = TaskDAG()

    # 1. 创建节点
    for t in tasks:
        dag.nodes[t.id] = TaskNode(task=t)

    # 2. 建立边（depends_on → children）
    for t in tasks:
        for dep_id in t.depends_on:
            if dep_id in dag.nodes:
                dag.edges.append((dep_id, t.id))
                dag.nodes[dep_id].children.append(t.id)

    # 3. 拓扑排序 + 层级分配（Kahn 算法）
    in_degree: dict[str, int] = dict.fromkeys(dag.nodes, 0)
    for _, to_id in dag.edges:
        in_degree[to_id] = in_degree.get(to_id, 0) + 1

    # 用 deque 做 BFS 层级遍历
    queue: deque[str] = deque()
    for tid, deg in in_degree.items():
        if deg == 0:
            queue.append(tid)

    level = 0
    while queue:
        # 当前层所有节点（可并行）
        current_level: list[str] = []
        for _ in range(len(queue)):
            tid = queue.popleft()
            dag.nodes[tid].level = level
            current_level.append(tid)

            for child_id in dag.nodes[tid].children:
                in_degree[child_id] -= 1
                if in_degree[child_id] == 0:
                    queue.append(child_id)

        if current_level:
            dag.parallel_groups.append(current_level)
        level += 1

    dag.total_levels = len(dag.parallel_groups)
    return dag


async def decompose_task_dag(
    user_request: str,
    chat_bridge=None,
) -> tuple[list[AgentTask], TaskDAG]:
    """分解任务并同时生成 DAG（包含并行分组）

    兼容 ``decompose_task`` 的返回值，额外返回 TaskDAG。

    Returns:
        (tasks, dag) — DAG 可直接用于并行调度
    """
    tasks = await decompose_task(user_request, chat_bridge)
    dag = build_task_dag(tasks)
    return tasks, dag
