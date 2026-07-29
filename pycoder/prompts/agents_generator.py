"""Agent 角色描述生成器 — 生成 agents.md 文件"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 类型映射: project_type → 中文名称
_TYPE_MAP: dict[str, str] = {
    "web": "Web 应用",
    "library": "库/框架",
    "script": "脚本工具",
    "cli": "命令行工具",
    "data": "数据处理",
    "ml": "机器学习",
    "unknown": "通用",
    "custom_type": "custom_type",
}

# 框架特定约定
_FRAMEWORK_SECTIONS: dict[str, str] = {
    "FastAPI": """### FastAPI 约定

- 使用 `async def` 处理路由
- 使用 Pydantic v2 模型定义请求/响应
- API 路径使用 RESTful 风格（复数名词）
- 依赖注入使用 `Depends()`
""",
    "Flask": """### Flask 约定

- 使用 Blueprint 组织路由
- 使用 Flask-SQLAlchemy 管理数据库
- 使用 Flask-Migrate 处理迁移
""",
    "Django": """### Django 约定

- Fat Models, Thin Views
- 使用 Django REST Framework 构建 API
- 使用 Django ORM 管理数据库
""",
    "pandas": """### 数据科学约定

- 使用 Jupyter Notebook 进行探索性分析
- 将可复用逻辑抽取为 .py 模块
- 数据处理管道使用函数式风格
- 结果可视化使用 matplotlib/seaborn
""",
    "NumPy": """### 数据科学约定

- 使用 Jupyter Notebook 进行探索性分析
- 将可复用逻辑抽取为 .py 模块
- 数据处理管道使用函数式风格
- 结果可视化使用 matplotlib/seaborn
""",
    "PyTorch": """### PyTorch 约定

- 使用 torch.nn.Module 定义模型
- 使用 DataLoader 加载数据
- 使用 torch.optim 管理优化器
""",
}


def detect_environment(project_path: str | Path | None = None) -> Any | None:
    """检测项目环境（兼容性别名）"""
    try:
        from pycoder.python.env_detector import detect_environment as _detect

        return _detect(project_path)
    except ImportError:
        return None


def generate_agents_md(
    project_path: str | Path | None = None,
    include_env: bool = True,
) -> str:
    """生成 AGENTS.md 文件内容

    Args:
        project_path: 项目路径（用于环境检测）
        include_env: 是否包含环境检测信息

    Returns:
        AGENTS.md 的完整内容字符串
    """
    sections: list[str] = []

    # 环境检测
    env = None
    if include_env and project_path:
        env = detect_environment(project_path)

    # 标题
    sections.append("# PyCoder AGENTS.md\n")

    if env:
        sections.append(f"> 自动生成于 {_current_date()} | PyCoder AGENTS.md\n")
        sections.append("## 项目概述\n")
        sections.append("- **项目名称**: pycode")
        sections.append(f"- **主要语言**: Python {env.python_version}")
        if env.venv_type and env.venv_type != "none":
            sections.append(f"- **虚拟环境**: {env.venv_type}")
        if env.package_manager:
            sections.append(f"- **包管理器**: {env.package_manager}")
        project_type_cn = _TYPE_MAP.get(env.project_type, env.project_type or "通用")
        sections.append(f"- **项目类型**: {project_type_cn}")
        frameworks = env.frameworks[:8] if env.frameworks else []
        if frameworks:
            sections.append(f"- **框架**: {', '.join(frameworks)}")
        sections.append("")
    else:
        sections.append("# " + "PyCoder AGENTS.md")
        sections.append("")
        sections.append("## 项目概述")
        sections.append("")
        sections.append("- **项目名称**: pycode")
        sections.append("- **主要语言**: Python 3.x")
        sections.append("- **包管理器**: pip")
        sections.append("- **项目类型**: Web 应用")
        sections.append(
            "- **框架**: FastAPI, pandas, NumPy, Matplotlib, Streamlit, pytest, Textual, Rich"
        )
        sections.append("")

    sections.append("## Python 编码规范")
    sections.append("")
    sections.append("### 必须遵守")
    sections.append("")
    sections.append("1. **PEP 8** — 代码风格严格遵循 PEP 8，使用 Black 自动格式化")
    sections.append("2. **Type Hints** — 所有公共函数/方法必须有类型注解")
    sections.append("3. **中文注释** — 注释和文档字符串使用中文")
    sections.append(
        "4. **现代语法** — 优先使用 Python 3.10+ 特性（match/case, `|` 联合类型, walrus `:=`）"
    )
    sections.append("5. **错误处理** — 使用具体异常类型，避免裸 `except:`")
    sections.append("6. **f-string** — 字符串格式化统一使用 f-string")
    sections.append("")
    sections.append("### 推荐做法")
    sections.append("")
    sections.append("- 使用 `pathlib.Path` 替代 `os.path`")
    sections.append("- 使用 `dataclasses` 或 `Pydantic` 定义数据模型")
    sections.append("- 使用 `asyncio` 处理 I/O 密集型任务")
    sections.append("- 配置通过环境变量 + `.env` 文件注入（python-dotenv）")
    sections.append("- 敏感信息（API Key、密码）绝不硬编码")
    sections.append("")
    sections.append("### 禁止做法")
    sections.append("")
    sections.append("- 裸 `except:` 吞掉所有异常")
    sections.append("- 使用 `from module import *`")
    sections.append("- 在函数参数中使用可变默认值 `def f(x=[])`")
    sections.append("- 硬编码文件路径（使用相对路径或配置）")
    sections.append("- 在生产代码中使用 `print()` 调试（用 `logging`）")
    sections.append("")

    sections.append("## 项目结构约定")
    sections.append("")
    sections.append("```")
    sections.append("project/")
    sections.append("├── src/            # 源代码")
    sections.append("├── tests/          # 测试（pytest）")
    sections.append("├── docs/           # 文档")
    sections.append("├── config/         # 配置文件")
    sections.append("├── scripts/        # 工具脚本")
    sections.append("├── pyproject.toml  # 项目元数据")
    sections.append("├── .env.example    # 环境变量模板")
    sections.append("└── AGENTS.md       # 本文件")
    sections.append("```")
    sections.append("")

    sections.append("## 测试规范")
    sections.append("")
    sections.append("- 测试框架: **pytest**")
    sections.append("- 覆盖率目标: >= 80%")
    sections.append("- 测试文件命名: `test_<模块名>.py`")
    sections.append("- CI 中必须通过全部测试才能合并")
    sections.append("")

    sections.append("## Git 工作流")
    sections.append("")
    sections.append("- 分支策略: `master` (稳定) + `feat/xxx` (功能) + `fix/xxx` (修复)")
    sections.append(
        "- 提交格式: `feat: xxx` / `fix: xxx` / `docs: xxx` / `refactor: xxx` / `test: xxx`"
    )
    sections.append("- PR 需要至少 1 人 Code Review 通过")
    sections.append("- 合并前 squash commits 保持历史整洁")
    sections.append("")

    sections.append("## 自动提交与推送")
    sections.append("")
    sections.append("**每次完成任务后，AI 助手必须执行:**")
    sections.append("")
    sections.append("```bash")
    sections.append("cd C:\\Users\\Administrator\\Desktop\\pycode")
    sections.append('python __git_commit_push.py "fix: 修改说明"')
    sections.append("```")
    sections.append("")
    sections.append("或双击 `__git_auto_push.bat` (Windows)")
    sections.append("")
    sections.append("### post-commit 钩子自动推送")
    sections.append("")
    sections.append(
        "- `.git/hooks/post-commit` 已安装，每次 `git commit` 后自动执行 `git push origin master`"
    )
    sections.append('- Git 别名 `git acp "msg"` = add + commit + push 一步到位')
    sections.append("")
    sections.append("### 手动方式")
    sections.append("")
    sections.append("```bash")
    sections.append("git add -A")
    sections.append('git commit -m "fix: 说明"')
    sections.append("git push origin master")
    sections.append("```")
    sections.append("")

    sections.append("## AI Agent 协作规则")
    sections.append("")
    sections.append("当 AI 助手修改代码时，应遵循:")
    sections.append("")
    sections.append("1. **先读后改** — 修改文件前先读取完整内容")
    sections.append("2. **Diff 展示** — 修改后展示 unified diff，用户确认后写入")
    sections.append("3. **保持一致性** — 遵循项目现有的代码风格和模式")
    sections.append("4. **最小化改动** — 只修改必要的部分，不过度重构")
    sections.append("5. **可回滚** — 重大改动前建议创建 git commit 或备份")
    sections.append("6. **解释变更** — 每次修改附带中文说明原因")
    sections.append("")

    # 框架特定约定
    if env and env.frameworks:
        sections.append("## 环境特定约定")
        sections.append("")
        seen_frameworks: set[str] = set()
        for fw in env.frameworks[:8]:
            section = _FRAMEWORK_SECTIONS.get(fw)
            if section and fw not in seen_frameworks:
                sections.append(section)
                seen_frameworks.add(fw)
        sections.append("")

    sections.append("---")
    sections.append("")
    sections.append("*此文件由 PyCoder 自动生成。运行 `python -m pycoder --agents` 重新生成。*")

    return "\n".join(sections)


def _current_date() -> str:
    """获取当前日期字符串"""
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _generate_core_dev_section() -> str:
    """生成核心开发 Agent 描述"""
    return """## 核心开发 Agent

### 架构师 (Architect)
- **职责**: 系统架构设计、技术选型、架构评审
- **能力**: 系统设计、技术选型、架构评审
- **模型**: deepseek-reasoner
- **温度**: 0.3

### 开发者 (Developer)
- **职责**: 功能实现和代码编写
- **能力**: 编码、调试、代码审查
- **模型**: deepseek-chat
- **温度**: 0.5

### 代码审查员 (Reviewer)
- **职责**: 代码质量审查和最佳实践检查
- **能力**: 代码审查、质量检查、重构建议
- **模型**: deepseek-chat
- **温度**: 0.2

"""


def _generate_qa_section() -> str:
    """生成质量保障 Agent 描述"""
    return """## 质量保障 Agent

### 测试工程师 (Tester)
- **职责**: 编写和执行测试用例
- **能力**: 单元测试、集成测试、端到端测试
- **模型**: deepseek-chat
- **温度**: 0.4

### 质量分析师 (QA Analyst)
- **职责**: 质量指标分析和改进建议
- **能力**: 质量分析、性能分析、覆盖率分析
- **模型**: deepseek-chat
- **温度**: 0.3

"""


def _generate_infra_section() -> str:
    """生成基础设施 Agent 描述"""
    return """## 基础设施 Agent

### DevOps 工程师 (DevOps)
- **职责**: CI/CD 和基础设施管理
- **能力**: CI/CD、容器化、监控
- **模型**: deepseek-chat
- **温度**: 0.4

### 数据库管理员 (DBA)
- **职责**: 数据库设计和优化
- **能力**: 数据库设计、查询优化、迁移管理
- **模型**: deepseek-chat
- **温度**: 0.3

"""


def _generate_collab_section() -> str:
    """生成协作与沟通 Agent 描述"""
    return """## 协作与沟通 Agent

### Scrum Master
- **职责**: 任务协调和进度管理
- **能力**: 任务管理、进度跟踪、风险管理
- **模型**: deepseek-chat
- **温度**: 0.5

### 技术文档工程师 (Tech Writer)
- **职责**: 技术文档和 API 文档编写
- **能力**: 文档编写、API 文档、用户指南
- **模型**: deepseek-chat
- **温度**: 0.4

"""


def _generate_security_section() -> str:
    """生成安全与合规 Agent 描述"""
    return """## 安全与合规 Agent

### 安全分析师 (Security Analyst)
- **职责**: 安全漏洞检测和修复建议
- **能力**: 安全扫描、漏洞分析、合规检查
- **模型**: deepseek-reasoner
- **温度**: 0.2

### 合规官 (Compliance Officer)
- **职责**: 代码合规性检查
- **能力**: 合规检查、许可证管理、数据隐私
- **模型**: deepseek-chat
- **温度**: 0.3

"""


def _generate_learning_section() -> str:
    """生成学习与进化 Agent 描述"""
    return """## 学习与进化 Agent

### 学习者 (Learner)
- **职责**: 从历史经验中学习和改进
- **能力**: 模式识别、经验提取、知识管理
- **模型**: deepseek-chat
- **温度**: 0.6

### 优化器 (Optimizer)
- **职责**: 代码和系统性能优化
- **能力**: 性能分析、代码优化、资源优化
- **模型**: deepseek-reasoner
- **温度**: 0.3

### 创新者 (Innovator)
- **职责**: 新技术探索和创新方案设计
- **能力**: 技术调研、原型开发、创新方案
- **模型**: deepseek-reasoner
- **温度**: 0.7

"""


def _generate_usage_guide() -> str:
    """生成使用说明"""
    return """## 使用说明

### 选择 Agent
系统会根据任务类型自动选择合适的 Agent 角色。也可以通过 `/agent <角色名>` 手动指定。

### 多 Agent 协作
复杂任务可以同时调用多个 Agent 协作完成：
- 架构师 + 开发者：设计并实现新功能
- 测试工程师 + 质量分析师：全面质量保障
- 安全分析师 + 合规官：安全合规检查

### 自定义 Agent
可以在 `pycoder/brain/specialized_agents.py` 中自定义 Agent 角色配置。
"""


# ══════════════════════════════════════════════════════════
# 兼容性导出 — 保留旧 API 以防止导入错误
# ══════════════════════════════════════════════════════════


def generate_and_write(output_dir: str | Path | None = None) -> str:
    """生成 AGENTS.md 并写入文件"""
    if output_dir is None:
        output_dir = Path.cwd()
    content = generate_agents_md(project_path=output_dir, include_env=True)
    out_path = Path(output_dir) / "AGENTS.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def get_agents_context(project_dir: str | Path | None = None) -> str:
    """获取 AGENTS.md 上下文内容"""
    if project_dir is None:
        project_dir = Path.cwd()
    agents_path = Path(project_dir) / "AGENTS.md"
    if agents_path.exists():
        content = agents_path.read_text(encoding="utf-8")
        # 截断过长内容
        if len(content) > 2000:
            content = content[:2000] + "\n\n...(已截断)"
        return content
    # 自动生成精简版（不包含项目概述标题）
    full = generate_agents_md(project_path=project_dir, include_env=True)
    # 过滤掉项目概述 section，保留编码规范和环境特定约定
    lines = full.split("\n")
    filtered: list[str] = []
    skip = False
    for line in lines:
        if line.strip().startswith("## 项目概述"):
            skip = True
            continue
        if skip and line.strip().startswith("## "):
            skip = False
        if not skip:
            filtered.append(line)
    return "\n".join(filtered)


def load_agents_md(project_dir: str | Path | None = None) -> str | None:
    """加载 AGENTS.md 文件内容"""
    if project_dir is None:
        project_dir = Path.cwd()
    agents_path = Path(project_dir) / "AGENTS.md"
    try:
        if agents_path.exists():
            return agents_path.read_text(encoding="utf-8")
    except OSError:
        return None
    return None
