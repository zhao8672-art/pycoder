"""
中文 AGENTS.md 模板

为 PyCoder 项目生成标准的 AGENTS.md 文件，
包含 AI Agent 协作规范、项目约定和开发指南。
"""

from dataclasses import dataclass, field


@dataclass
class AgentTemplate:
    """Agent 协作模板"""

    name: str
    role: str
    description: str
    responsibilities: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


# 预定义 Agent 角色模板
AGENT_TEMPLATES = {
    "software_pm": AgentTemplate(
        name="技术PM",
        role="software_pm",
        description="任务拆解、代码审核、交付管控",
        responsibilities=[
            "需求分析与任务拆解",
            "架构方案评审",
            "Code Review 与质量门禁",
            "交付进度跟踪",
        ],
        tools=["git", "code_review", "task_tracker"],
        constraints=[
            "不直接修改生产代码",
            "所有合并需经过 HITL 审批",
        ],
    ),
    "tech_architect": AgentTemplate(
        name="系统架构师",
        role="tech_architect",
        description="架构设计、技术选型、API 契约",
        responsibilities=[
            "系统架构设计（C4 模型）",
            "技术选型与风险评估",
            "API 规范定义（OpenAPI）",
            "数据模型设计（ER 图）",
        ],
        tools=["c4_diagram", "openapi_generator", "erd_generator"],
        constraints=[
            "选型必须提供对比表和决策理由",
            "架构变更需通知 PM",
        ],
    ),
    "frontend_engineer": AgentTemplate(
        name="前端工程师",
        role="frontend_engineer",
        description="UI/UX 实现、组件开发",
        responsibilities=[
            "Vue3/React 组件开发",
            "响应式布局与跨浏览器适配",
            "WCAG 无障碍标准实现",
            "组件测试（Storybook + E2E）",
        ],
        tools=["vue", "react", "storybook", "playwright"],
        constraints=[
            "TypeScript 强类型优先",
            "Lighthouse >85, 首屏 <2s",
        ],
    ),
    "backend_engineer": AgentTemplate(
        name="后端工程师",
        role="backend_engineer",
        description="API 开发、业务逻辑实现",
        responsibilities=[
            "RESTful API 开发",
            "数据库设计与优化",
            "单元测试编写（>80% 覆盖）",
            "性能优化（API <200ms）",
        ],
        tools=["fastapi", "django", "flask", "pytest"],
        constraints=[
            "API 响应 P99 <500ms",
            "接口测试全覆盖",
        ],
    ),
    "qa_engineer": AgentTemplate(
        name="QA 工程师",
        role="qa_engineer",
        description="测试策略、质量门禁",
        responsibilities=[
            "测试用例编写（核心功能 100% 覆盖）",
            "自动化测试脚本维护",
            "安全测试（OWASP Top 10）",
            "性能测试（负载/压力/并发）",
        ],
        tools=["pytest", "playwright", "locust", "owasp_zap"],
        constraints=[
            "严重 Bug = 0 才可上线",
            "中等 Bug <=3",
        ],
    ),
    "devops_engineer": AgentTemplate(
        name="DevOps 工程师",
        role="devops_engineer",
        description="CI/CD、部署、监控",
        responsibilities=[
            "CI/CD 流水线维护",
            "蓝绿部署/滚动更新",
            "数据库备份与恢复",
            "生产环境监控告警",
        ],
        tools=["docker", "k8s", "github_actions", "prometheus"],
        constraints=[
            "部署必须有回滚方案",
            "新部署后 30 分钟重点观察",
        ],
    ),
}


def generate_agents_md(
    project_name: str = "PyCoder",
    project_description: str = "",
    language: str = "Python",
    framework: str = "",
    custom_templates: list[AgentTemplate] | None = None,
) -> str:
    """
    生成中文 AGENTS.md 文件内容

    Args:
        project_name: 项目名称
        project_description: 项目描述
        language: 主要编程语言
        framework: 使用的框架
        custom_templates: 自定义 Agent 模板（覆盖默认）

    Returns:
        完整的 AGENTS.md 内容字符串
    """
    lines = [
        f"# AGENTS.md — {project_name}",
        "",
        "## 项目定位",
        (
            f"{project_description or project_name + ' 项目'}"
            if project_description
            else f"{project_name} — {language} 项目"
        ),
        "",
        f"**主要语言：** {language}",
    ]

    if framework:
        lines.append(f"**框架：** {framework}")

    lines.extend(
        [
            "",
            "## Agent 协作规范",
            "",
            "所有 Agent 遵循 ACP 通信协议（yzk-acp/v1）：",
            "- A→B 只传决策结论+产出物摘要",
            "- 格式：`[TASK:xxx] 状态:xxx | 决策:xxx | 产出:xxx | 下游需知:xxx`",
            "- 接收方验证输入完整性后再执行",
            "",
            "## 团队角色",
            "",
            "| 角色 | ID | 职责 |",
            "|------|-----|------|",
        ]
    )

    templates = custom_templates or list(AGENT_TEMPLATES.values())
    for t in templates:
        lines.append(f"| {t.name} | `{t.role}` | {t.description} |")

    lines.extend(
        [
            "",
            "## 开发流程",
            "",
            "```",
            "需求 → 架构设计 → 方案评审 → 任务拆解 →",
            "前端/后端并行开发 | QA编写测试用例 | DevOps准备CI/CD →",
            "Code Review → QA测试 → HITL审批 → 部署",
            "```",
            "",
            "## HITL 规范",
            "",
            "以下操作需要人工审批：",
            "- `merge_to_main` — 合并到主分支",
            "- `deploy_production` — 部署到生产环境",
            "- `modify_database` — 修改数据库结构",
            "",
            "## 提交规范",
            "",
            "使用 Conventional Commits：",
            "- `feat:` 新功能",
            "- `fix:` 修复 Bug",
            "- `docs:` 文档变更",
            "- `refactor:` 重构",
            "- `test:` 测试相关",
            "- `chore:` 构建/工具变更",
            "",
            "## 代码审查清单",
            "",
            "- [ ] 功能实现符合需求规格",
            "- [ ] 单元测试覆盖率 >=80%",
            "- [ ] API 文档已更新（如适用）",
            "- [ ] 无明显的安全漏洞",
            "- [ ] 性能影响评估通过",
            "- [ ] 代码风格符合项目规范",
            "",
            "---",
            "",
            f"*此文件由 PyCoder 自动生成，基于 {project_name} 项目配置。*",
        ]
    )

    return "\n".join(lines)


def get_template(role: str) -> AgentTemplate | None:
    """获取指定角色的模板"""
    return AGENT_TEMPLATES.get(role)


def list_roles() -> list[str]:
    """列出所有可用角色"""
    return list(AGENT_TEMPLATES.keys())


if __name__ == "__main__":
    print(
        generate_agents_md(
            project_name="PyCoder",
            project_description="Python 开发者原生的 AI 编程 Agent",
            language="Python",
            framework="FastAPI + Textual",
        )
    )
