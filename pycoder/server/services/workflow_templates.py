"""
标准工作流模板 — 借鉴好运助手工作流系统，定义可复用的标准化流水线。

每个模板定义了:
  - 阶段序列（串行/并行）
  - 每个阶段绑定的 Agent 角色
  - Token 预算
  - 超时配置
  - 分片策略
  - 必要交付物

用法:
  from pycoder.server.services.workflow_templates import (
      WORKFLOW_TEMPLATES, get_workflow, estimate_budget
  )
  tmpl = get_workflow("fullstack-dev")
  print(tmpl["stages"])  # [(stage_name, agent_role, parallel_allowed)]
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WorkflowStage:
    """工作流阶段定义"""

    name: str  # 阶段名称
    agent_role: str  # 执行的 Agent 角色 ID
    description: str  # 阶段描述
    deliverables: list[str] = field(default_factory=list)  # 必要交付物
    parallel_with: list[str] = field(default_factory=list)  # 可并行的其他阶段名
    timeout_seconds: int = 300  # 超时时间
    max_retries: int = 2  # 最大重试次数


@dataclass
class WorkflowTemplate:
    """工作流模板"""

    id: str
    name: str
    description: str
    stages: list[WorkflowStage]
    token_budget: int  # 总 Token 预算
    cost_budget_usd: float  # 成本预算
    total_timeout: int  # 总超时 (秒)
    max_concurrent_agents: int  # 最大并发 Agent 数
    required_deliverables: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════
# 预定义工作流模板
# ══════════════════════════════════════════════════════════

WORKFLOW_TEMPLATES: dict[str, WorkflowTemplate] = {
    # ─── 全栈开发工作流（9 阶段） ───
    "fullstack-dev": WorkflowTemplate(
        id="fullstack-dev",
        name="全栈应用开发",
        description="完整前端+后端+数据库应用，最全面的开发工作流",
        token_budget=150000,
        cost_budget_usd=5.0,
        total_timeout=1200,
        max_concurrent_agents=6,
        stages=[
            WorkflowStage(
                name="需求分析",
                agent_role="pm",
                description="理解需求，拆解任务，确定优先级",
                deliverables=["任务分解JSON"],
                timeout_seconds=300,
            ),
            WorkflowStage(
                name="架构设计",
                agent_role="architect",
                description="技术选型，模块设计，API定义，数据建模",
                deliverables=["架构文档.md", "API定义"],
                timeout_seconds=600,
            ),
            WorkflowStage(
                name="方案校验(L1)",
                agent_role="qa",
                description="校验架构方案是否符合规范、需求匹配度、风险识别",
                deliverables=["校验报告"],
                timeout_seconds=300,
                max_retries=2,
            ),
            WorkflowStage(
                name="代码实现(并行)",
                agent_role="developer",
                description="按模块并行编码，每个模块一个文件",
                deliverables=["源代码文件"],
                parallel_with=["测试编写"],
                timeout_seconds=900,
                max_retries=2,
            ),
            WorkflowStage(
                name="测试编写",
                agent_role="qa",
                description="编写单元测试和集成测试",
                deliverables=["测试文件", "TEST_REPORT.md"],
                parallel_with=["代码实现(并行)"],
                timeout_seconds=600,
            ),
            WorkflowStage(
                name="代码审查(L2)",
                agent_role="qa",
                description="审查代码质量、安全、性能",
                deliverables=["审查报告"],
                timeout_seconds=300,
            ),
            WorkflowStage(
                name="综合质检(L3+L4)",
                agent_role="qa",
                description="终审验收: 全链路汇总，安全审计，量化打分",
                deliverables=["终审报告", "质量评分"],
                timeout_seconds=300,
            ),
            WorkflowStage(
                name="容器化部署",
                agent_role="devops",
                description="Docker化，编排，环境配置",
                deliverables=["Dockerfile", "docker-compose.yml", "部署脚本"],
                timeout_seconds=600,
            ),
            WorkflowStage(
                name="交付文档",
                agent_role="devops",
                description="编写README、API文档、部署说明",
                deliverables=["README.md", "API文档"],
                timeout_seconds=300,
            ),
        ],
        required_deliverables=[
            "源代码",
            "测试文件",
            "TEST_REPORT.md",
            "README.md",
            "Dockerfile",
            "docker-compose.yml",
        ],
    ),
    # ─── API 服务开发工作流（6 阶段） ───
    "api-service": WorkflowTemplate(
        id="api-service",
        name="后端 API 服务",
        description="纯后端 RESTful API / FastAPI / 数据处理服务",
        token_budget=80000,
        cost_budget_usd=3.0,
        total_timeout=900,
        max_concurrent_agents=4,
        stages=[
            WorkflowStage(
                name="需求分析",
                agent_role="pm",
                description="分析 API 需求，定义端点",
                deliverables=["API需求文档"],
                timeout_seconds=180,
            ),
            WorkflowStage(
                name="架构设计",
                agent_role="architect",
                description="路由设计，数据模型，认证方案",
                deliverables=["API设计文档", "数据模型"],
                timeout_seconds=300,
            ),
            WorkflowStage(
                name="代码实现",
                agent_role="developer",
                description="实现 API 端点、中间件、数据库操作",
                deliverables=["API源代码"],
                timeout_seconds=600,
                max_retries=2,
            ),
            WorkflowStage(
                name="测试编写",
                agent_role="qa",
                description="编写 API 测试和集成测试",
                deliverables=["测试文件"],
                timeout_seconds=300,
            ),
            WorkflowStage(
                name="代码审查+质检",
                agent_role="qa",
                description="质量审查，安全扫描",
                deliverables=["审查报告"],
                timeout_seconds=240,
            ),
            WorkflowStage(
                name="部署文档",
                agent_role="devops",
                description="Docker配置，部署说明",
                deliverables=["Dockerfile", "README.md"],
                timeout_seconds=240,
            ),
        ],
        required_deliverables=[
            "API源代码",
            "测试文件",
            "Dockerfile",
            "README.md",
        ],
    ),
    # ─── 紧急修复工作流（5 阶段） ───
    "hotfix": WorkflowTemplate(
        id="hotfix",
        name="紧急热修复",
        description="生产环境紧急 Bug 修复，快速诊断→修复→部署",
        token_budget=50000,
        cost_budget_usd=2.0,
        total_timeout=600,
        max_concurrent_agents=2,
        stages=[
            WorkflowStage(
                name="问题诊断",
                agent_role="developer",
                description="快速定位Bug根因，复现问题",
                deliverables=["诊断报告"],
                timeout_seconds=180,
            ),
            WorkflowStage(
                name="修复实现",
                agent_role="developer",
                description="最小化修改，修复Bug",
                deliverables=["修复代码"],
                timeout_seconds=300,
                max_retries=2,
            ),
            WorkflowStage(
                name="回归测试",
                agent_role="qa",
                description="验证修复，确保无回归",
                deliverables=["测试验证"],
                timeout_seconds=180,
            ),
            WorkflowStage(
                name="安全审查",
                agent_role="qa",
                description="快速安全检查修复代码",
                deliverables=["安全审查"],
                timeout_seconds=120,
            ),
            WorkflowStage(
                name="紧急部署",
                agent_role="devops",
                description="快速部署修复版本",
                deliverables=["部署确认"],
                timeout_seconds=180,
            ),
        ],
        required_deliverables=["修复代码", "测试验证", "部署确认"],
    ),
    # ─── 代码审查工作流（5 阶段） ───
    "code-review": WorkflowTemplate(
        id="code-review",
        name="代码审查",
        description="标准代码审查流程：规范、安全、复杂度、测试覆盖",
        token_budget=30000,
        cost_budget_usd=1.0,
        total_timeout=300,
        max_concurrent_agents=1,
        stages=[
            WorkflowStage(
                name="代码规范检查",
                agent_role="qa",
                description="PEP8/Ruff 规范检查",
                deliverables=["规范报告"],
                timeout_seconds=60,
            ),
            WorkflowStage(
                name="安全漏洞扫描",
                agent_role="qa",
                description="SQL注入/XSS/路径穿越/硬编码密钥",
                deliverables=["安全报告"],
                timeout_seconds=90,
            ),
            WorkflowStage(
                name="复杂度分析",
                agent_role="qa",
                description="圈复杂度、函数长度、嵌套深度",
                deliverables=["复杂度报告"],
                timeout_seconds=60,
            ),
            WorkflowStage(
                name="测试覆盖分析",
                agent_role="qa",
                description="检查测试覆盖率和质量",
                deliverables=["测试分析"],
                timeout_seconds=60,
            ),
            WorkflowStage(
                name="综合评分",
                agent_role="qa",
                description="汇总各维度，给出综合评分和修复建议",
                deliverables=["综合审查报告"],
                timeout_seconds=30,
            ),
        ],
        required_deliverables=["综合审查报告"],
    ),
}


# ══════════════════════════════════════════════════════════
# 便捷访问函数
# ══════════════════════════════════════════════════════════


def get_workflow(workflow_id: str) -> WorkflowTemplate | None:
    """获取工作流模板"""
    return WORKFLOW_TEMPLATES.get(workflow_id)


def list_workflows() -> list[dict]:
    """列出所有可用工作流"""
    return [
        {
            "id": w.id,
            "name": w.name,
            "description": w.description,
            "stages": len(w.stages),
            "token_budget": w.token_budget,
            "cost_usd": w.cost_budget_usd,
        }
        for w in WORKFLOW_TEMPLATES.values()
    ]


def estimate_budget(workflow_id: str, scale: float = 1.0) -> dict:
    """估算工作流预算"""
    wf = WORKFLOW_TEMPLATES.get(workflow_id)
    if not wf:
        return {"error": f"未知工作流: {workflow_id}"}
    return {
        "workflow": wf.name,
        "token_budget": int(wf.token_budget * scale),
        "cost_estimate_usd": round(wf.cost_budget_usd * scale, 2),
        "total_timeout_seconds": wf.total_timeout,
        "max_concurrent_agents": wf.max_concurrent_agents,
    }


def get_workflow_stages_parallel_map(workflow_id: str) -> list[list[str]]:
    """获取工作流的并行阶段映射（用于并发调度）"""
    wf = WORKFLOW_TEMPLATES.get(workflow_id)
    if not wf:
        return []

    # 按是否有 parallel_with 分组
    parallel_groups: dict[str, set[str]] = {}
    for stage in wf.stages:
        if stage.parallel_with:
            key = stage.name
            group = {stage.name} | set(stage.parallel_with)
            # 合并已有组
            merged = False
            for ek in list(parallel_groups.keys()):
                if group & parallel_groups[ek]:
                    parallel_groups[ek] |= group
                    merged = True
                    break
            if not merged:
                parallel_groups[key] = group
        else:
            parallel_groups[stage.name] = {stage.name}

    # 去重并转排序
    seen: set[str] = set()
    result: list[list[str]] = []
    for stage in wf.stages:
        if stage.name in seen:
            continue
        for group in parallel_groups.values():
            if stage.name in group:
                result.append(sorted(group))
                seen.update(group)
                break
    return result


__all__ = [
    "WorkflowStage",
    "WorkflowTemplate",
    "WORKFLOW_TEMPLATES",
    "get_workflow",
    "list_workflows",
    "estimate_budget",
    "get_workflow_stages_parallel_map",
]
