"""
动态工具规划器 — 根据任务复杂度动态决定工具调用次数和类型

替代固定的"每轮必须调用工具"模式，实现:
  - 纯问答: 0 次工具调用
  - 简单查询: 1-2 次读操作
  - 代码修改: 2-5 次读写操作
  - 多文件开发: 5-10 次混合操作
  - 复杂工程: 10-30 次全流程
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pycoder.brain.intent_analyzer import IntentAnalysis

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class ToolPlan:
    """工具调用计划"""

    # 动态规划
    estimated_tool_calls: int = 0  # 预估工具调用次数
    max_tool_calls: int = 0  # 最大工具调用次数
    tool_categories: list[str] = field(default_factory=list)  # read/write/execute/git/search

    # 策略
    allow_parallel_reads: bool = True
    enforce_sequential_writes: bool = True
    allow_direct_answer: bool = False  # 是否允许直接回答（不调用工具）

    # 运行时统计
    actual_tool_calls: int = 0
    successful_tool_calls: int = 0

    # 工具优先级
    preferred_tools: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════
# 工具分类
# ══════════════════════════════════════════════════════════

TOOL_CATEGORIES: dict[str, list[str]] = {
    "read": [
        "read_file", "list_files", "search_code", "git_status",
        "git_log", "git_diff", "git_branch",
    ],
    "write": [
        "write_file", "patch_file", "create_file", "overwrite_file",
    ],
    "execute": [
        "run_command", "run_terminal", "execute_python",
    ],
    "git": [
        "git_add", "git_commit", "git_push", "git_pull",
        "git_stash", "git_branch_create", "git_checkout",
    ],
    "package": [
        "install_package", "search_package", "ensure_tool", "install_deps",
    ],
    "quality": [
        "code_review", "format_code", "security_scan", "dependency_analysis",
    ],
    "system": [
        "docker_status", "python_env", "list_agent_configs",
    ],
}


# 任务类型 → 工具类别映射
TASK_TOOL_MAP: dict[str, list[str]] = {
    "qa": [],  # 纯问答不需要工具
    "code_gen": ["read", "write", "execute"],
    "debug": ["read", "execute", "write"],
    "refactor": ["read", "write", "execute"],
    "architect": ["read", "system"],
    "deploy": ["execute", "git", "system"],
    "review": ["read", "quality"],
    "mixed": ["read", "write", "execute", "git", "quality"],
}


# 复杂度 → 工具调用规划
COMPLEXITY_TOOL_PLAN: dict[str, dict] = {
    "trivial": {
        "estimated_tool_calls": 0,
        "max_tool_calls": 0,
        "allow_direct_answer": True,
        "tool_categories": [],
    },
    "simple": {
        "estimated_tool_calls": 2,
        "max_tool_calls": 5,
        "allow_direct_answer": True,
        "tool_categories": ["read"],
    },
    "medium": {
        "estimated_tool_calls": 5,
        "max_tool_calls": 12,
        "allow_direct_answer": False,
        "tool_categories": ["read", "write", "execute"],
    },
    "complex": {
        "estimated_tool_calls": 15,
        "max_tool_calls": 50,
        "allow_direct_answer": False,
        "tool_categories": ["read", "write", "execute", "git", "quality"],
    },
}


# ══════════════════════════════════════════════════════════
# ToolPlanner
# ══════════════════════════════════════════════════════════


class ToolPlanner:
    """动态工具规划器

    根据意图分析结果，动态规划工具调用的次数、类型和策略。
    """

    def __init__(self) -> None:
        self._available_tools: dict[str, dict] = {}
        self._load_default_tools()

    def _load_default_tools(self) -> None:
        """加载默认工具列表"""
        self._available_tools = {
            "read_file": {"category": "read", "params": ["path"], "desc": "读取文件"},
            "write_file": {"category": "write", "params": ["path", "content"], "desc": "写入文件"},
            "patch_file": {"category": "write", "params": ["path", "search", "replace"], "desc": "精准替换"},
            "create_file": {"category": "write", "params": ["path", "content"], "desc": "创建文件"},
            "search_code": {"category": "read", "params": ["query", "file_type?"], "desc": "搜索代码"},
            "list_files": {"category": "read", "params": ["path?", "depth?"], "desc": "列出目录"},
            "run_command": {"category": "execute", "params": ["command"], "desc": "执行命令"},
            "run_terminal": {"category": "execute", "params": ["command"], "desc": "终端命令"},
            "execute_python": {"category": "execute", "params": ["code"], "desc": "沙箱执行 Python"},
            "git_status": {"category": "read", "params": [], "desc": "Git 状态"},
            "git_diff": {"category": "read", "params": ["file?"], "desc": "Git 变更"},
            "git_log": {"category": "read", "params": [], "desc": "提交历史"},
            "git_branch": {"category": "read", "params": [], "desc": "分支列表"},
            "git_add": {"category": "git", "params": ["path"], "desc": "Git 暂存"},
            "git_commit": {"category": "git", "params": ["message"], "desc": "Git 提交"},
            "git_push": {"category": "git", "params": [], "desc": "Git 推送"},
            "install_package": {"category": "package", "params": ["package"], "desc": "安装包"},
            "code_review": {"category": "quality", "params": ["file"], "desc": "代码审查"},
            "format_code": {"category": "quality", "params": ["code"], "desc": "格式化代码"},
            "security_scan": {"category": "quality", "params": [], "desc": "安全扫描"},
        }

    def plan(self, intent: IntentAnalysis) -> ToolPlan:
        """根据意图分析生成工具调用计划

        Args:
            intent: 意图分析结果

        Returns:
            ToolPlan 工具调用计划
        """
        # 1. 根据复杂度获取基础计划
        base_plan = COMPLEXITY_TOOL_PLAN.get(intent.complexity, COMPLEXITY_TOOL_PLAN["medium"])

        plan = ToolPlan(
            estimated_tool_calls=base_plan["estimated_tool_calls"],
            max_tool_calls=base_plan["max_tool_calls"],
            allow_direct_answer=base_plan["allow_direct_answer"],
            tool_categories=list(base_plan["tool_categories"]),
        )

        # 2. 根据任务类型调整工具类别
        task_categories = TASK_TOOL_MAP.get(intent.task_type, ["read", "write"])
        for cat in task_categories:
            if cat not in plan.tool_categories:
                plan.tool_categories.append(cat)

        # 3. 根据文件引用调整
        if intent.has_file_references:
            if "read" not in plan.tool_categories:
                plan.tool_categories.append("read")
            plan.estimated_tool_calls = max(plan.estimated_tool_calls, 2)

        # 4. 根据风险调整
        if intent.has_risk:
            plan.max_tool_calls = max(plan.max_tool_calls, 5)
            plan.enforce_sequential_writes = True

        # 5. 生成推荐工具列表
        plan.preferred_tools = self._get_preferred_tools(plan.tool_categories, intent)

        return plan

    def _get_preferred_tools(self, categories: list[str], intent: IntentAnalysis) -> list[str]:
        """根据工具类别和意图获取推荐工具"""
        tools: list[str] = []
        for cat in categories:
            cat_tools = [
                name for name, info in self._available_tools.items()
                if info.get("category") == cat
            ]
            tools.extend(cat_tools)

        # 去重，保持顺序
        seen: set[str] = set()
        result: list[str] = []
        for t in tools:
            if t not in seen:
                seen.add(t)
                result.append(t)

        return result

    def should_use_tools(self, plan: ToolPlan) -> bool:
        """判断当前是否应该使用工具"""
        return not plan.allow_direct_answer or plan.estimated_tool_calls > 0

    def can_parallel(self, tool_name: str) -> bool:
        """判断工具是否可以并行执行"""
        tool_info = self._available_tools.get(tool_name, {})
        return tool_info.get("category", "") in ("read", "system")

    def get_tools_for_category(self, category: str) -> list[str]:
        """获取指定类别的工具列表"""
        return [
            name for name, info in self._available_tools.items()
            if info.get("category") == category
        ]

    def register_tool(self, name: str, category: str, params: list[str], desc: str = "") -> None:
        """注册新工具（可扩展性）"""
        self._available_tools[name] = {
            "category": category,
            "params": params,
            "desc": desc,
        }
        # 更新分类映射
        if category not in TOOL_CATEGORIES:
            TOOL_CATEGORIES[category] = []
        if name not in TOOL_CATEGORIES[category]:
            TOOL_CATEGORIES[category].append(name)
        logger.info("tool_registered: %s (category=%s)", name, category)

    def adjust_plan(self, plan: ToolPlan, success_rate: float) -> ToolPlan:
        """根据执行成功率动态调整计划"""
        if success_rate < 0.3:
            # 高失败率，减少工具调用，增加保守策略
            plan.max_tool_calls = max(3, plan.max_tool_calls // 2)
            plan.allow_direct_answer = True
        elif success_rate > 0.8:
            # 高成功率，可以适当增加并行
            plan.allow_parallel_reads = True
        return plan


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_planner_instance: ToolPlanner | None = None


def get_tool_planner() -> ToolPlanner:
    """获取全局工具规划器"""
    global _planner_instance
    if _planner_instance is None:
        _planner_instance = ToolPlanner()
    return _planner_instance