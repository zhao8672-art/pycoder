"""
Agent 策略定义 — 统一引擎的三种执行策略

策略:
  - simple:  单 Agent 交互（对应原 AgentOrchestrator）
  - team:    多 Agent 团队协作（对应原 TeamCoordinator）
  - auto:    全自主流水线（对应原 AutonomousPipeline + 自动策略选择）
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ══════════════════════════════════════════════════════════
# 统一系统提示词（合并三种模式的核心指令）
# ══════════════════════════════════════════════════════════

UNIFIED_SYSTEM_PROMPT = """你是 PyCoder 统一 AI 编程助手，运行在用户的本地开发环境中。

## 🔴 必须遵守的规则（违反将导致任务重新执行）

### 规则 1：每次回复必须包含 JSON 工具调用
你的每次回复的**第一条有效内容**必须是以下格式之一的 JSON 工具调用：

**多工具并行**（强烈推荐）：
```json
{"tool_calls": [{"name": "list_files", "params": {"path": "."}}, {"name": "git_status", "params": {}}]}
```

**单工具调用**：
```json
{"name": "write_file", "params": {"path": "test.py", "content": "print('hello')"}}
```

### 规则 2：不允许纯文字描述
**禁止**输出"我会先做XX再做YY"、"让我来分析"、"以下是执行结果"等无工具调用的纯文字内容。
你**必须**以 JSON tool_calls 开始你的回复。

### 规则 3：任务完成后输出总结
在所有工具执行完毕后，输出纯文字总结报告。

## ⚡ 你能做什么（重要）
- **读取本地文件**: 使用 `read_file` 工具直接读取工作区内的任何文件
- **写入文件**: 使用 `write_file`/`patch_file`/`create_file` 工具修改或创建文件
- **执行命令**: 使用 `run_command`/`run_terminal` 在终端运行 Python/pip/git/pytest 等命令
- **执行代码**: 使用 `execute_python` 在沙箱中直接运行 Python 代码
- **搜索代码**: 使用 `search_code` 在整个项目中搜索
- **列出目录**: 使用 `list_files` 查看项目结构
- **Git 操作**: 使用 `git_diff`/`git_status`/`git_add`/`git_commit`/`git_push`/`git_log` 完整 Git 工作流
- **安装包**: 使用 `install_package`/`ensure_tool` 安装工具和依赖
- **查询系统**: 使用 `list_agent_configs` 查询系统 Agent 配置

**请注意：你有完整的工作区文件系统访问权限，可以直接读写文件，不需要用户手动执行命令或提供文件内容。** 用户提问时直接使用工具读取所需文件即可。

## 工作流程
1. **输出 JSON 工具调用** — 以 `{"tool_calls": [...]}` 开始你的回复，调用需要的工具
2. **等待工具结果** — 系统会自动执行工具并返回结果
3. **继续下一轮** — 基于结果继续输出 JSON 工具调用或输出总结
4. **输出总结** — 所有任务完成后输出总结报告

## 可用工具列表
| 工具 | 描述 |
|---|---|
| read_file | 读取文件 |
| write_file | 写入文件（覆盖或新建） |
| patch_file | 补丁替换（最小改动） |
| create_file | 创建文件 |
| search_code | 搜索代码 |
| run_command | 执行命令 |
| run_terminal | 执行终端命令 |
| execute_python | 沙箱执行 Python 代码 |
| list_files | 列出目录 |
| git_status | 查看 Git 状态 |
| git_log | 查看提交历史 |
| git_branch | 查看分支 |
| git_diff | 查看 Git 变更 |
| git_add | Git 暂存 |
| git_commit | Git 提交 |
| list_agent_configs | 列出系统 Agent 配置 |
| install_package | 安装包 |
| search_package | 搜索包 |
| ensure_tool | 确保工具已安装 |
| install_deps | 批量安装依赖 |
| docker_status | Docker 状态检查 |
| python_env | 虚拟环境管理 |
| code_review | 代码质量审查 |
| format_code | 代码格式化 |
| security_scan | 依赖安全扫描 |
| dependency_analysis | 依赖分析 |

## 输出约束
- 读操作可以并行调用多个（多个 tool_calls 一次发出）
- 写操作严格串行，一次只写一个文件
- 禁止输出纯文字描述而不调用工具
"""


@dataclass
class AgentStrategy:
    """策略配置"""

    name: str
    description: str
    max_iterations: int
    tool_timeout: int
    max_concurrent_tools: int
    enable_rumination: bool  # 是否启用反思机制
    enable_snapshots: bool  # 是否启用快照回滚
    enable_qa_review: bool  # 是否启用 QA 审查
    system_prompt: str = UNIFIED_SYSTEM_PROMPT
    roles: list[dict] = field(default_factory=list)  # team 策略时使用的角色


# ── 三种策略配置 ──

SIMPLE_STRATEGY = AgentStrategy(
    name="simple",
    description="单 Agent 交互 — 适合简单任务、问答、单文件修改",
    max_iterations=15,
    tool_timeout=30,
    max_concurrent_tools=5,
    enable_rumination=True,
    enable_snapshots=False,
    enable_qa_review=False,
)

TEAM_STRATEGY = AgentStrategy(
    name="team",
    description="多 Agent 团队协作 — 适合复杂多文件、多步骤开发任务",
    max_iterations=10,
    tool_timeout=60,
    max_concurrent_tools=3,
    enable_rumination=True,
    enable_snapshots=True,
    enable_qa_review=True,
    roles=[
        {
            "id": "pm",
            "name": "项目经理",
            "model": "deepseek-chat",
            "description": "分解任务、制定计划",
        },
        {
            "id": "architect",
            "name": "架构师",
            "model": "deepseek-reasoner",
            "description": "设计架构、选择技术栈",
        },
        {
            "id": "developer",
            "name": "全栈开发者",
            "model": "deepseek-chat",
            "description": "编码实现",
        },
        {"id": "qa", "name": "质量保证", "model": "deepseek-chat", "description": "审查代码质量"},
    ],
)

AUTO_STRATEGY = AgentStrategy(
    name="auto",
    description="全自主流水线 — 适合完整功能开发、项目脚手架、复杂重构",
    # 与 TaskGrader 高难档对齐：高复杂任务需要足够步数自主跑到交付。
    # 实际运行时会按任务难度动态覆盖（见 resolve_iterations_for_grade）。
    max_iterations=50,
    tool_timeout=60,
    max_concurrent_tools=5,
    enable_rumination=True,
    enable_snapshots=True,
    enable_qa_review=True,
)

STRATEGY_MAP: dict[str, AgentStrategy] = {
    "simple": SIMPLE_STRATEGY,
    "team": TEAM_STRATEGY,
    "auto": AUTO_STRATEGY,
}


# ══════════════════════════════════════════════════════════
# 难度档 → 迭代预算（对齐 TaskGrader）
# ══════════════════════════════════════════════════════════
# 让高复杂任务有足够步数自主跑到交付，而不被写死的迭代上限截断。
GRADE_ITERATION_BUDGET: dict[str, int] = {
    "low": 5,  # 轻量任务
    "medium": 15,  # 中等任务
    "high": 50,  # 复杂长程任务
}


def resolve_iterations_for_grade(grade_level: str, base: int = 50) -> int:
    """根据任务难度档位解析迭代预算

    Args:
        grade_level: TaskGrader 输出的难度档 (low|medium|high)
        base: 未知档位时的兜底预算

    Returns:
        该档位对应的最大执行步数
    """
    return GRADE_ITERATION_BUDGET.get(grade_level, base)


def get_strategy(name: str) -> AgentStrategy:
    """按名称获取策略配置"""
    return STRATEGY_MAP.get(name, SIMPLE_STRATEGY)


async def auto_select_strategy(
    task: str,
    llm_call: callable,
) -> str:
    """自动分析任务，选择合适的策略"""
    prompt = f"""分析以下用户任务，判断最适合的执行策略。

任务: {task}

可选策略:
- simple: 简单任务，单 Agent 即可完成（读文件、回答、单文件修改）
- team: 多 Agent 团队协作（多文件、多步骤、需要架构设计）
- auto: 全自主流水线（完整功能开发、重构、项目脚手架）

请只返回策略名称: simple / team / auto
"""
    try:
        result = ""
        async for event in llm_call(prompt):
            if event.event_type in ("token", "done"):
                result += event.content
        result = result.strip().lower()
        for name in ("auto", "team", "simple"):
            if name in result:
                return name
    except Exception as e:
        logger = __import__("logging").getLogger(__name__)
        logger.debug("auto_select_strategy_failed error=%s", e)

    return "auto"  # 默认使用 auto
