"""
AGENTS.md 自动生成器

为当前Python项目自动生成AGENTS.md标准文件，
包含项目约定、编码规范、Agent协作规则。

用途：
- python -m pycoder --agents — 生成AGENTS.md到项目根目录
- TUI中 /agents — 预览AGENTS.md内容
- Bridge自动注入AGENTS.md到系统提示
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

from pycoder.python.env_detector import detect_environment

logger = logging.getLogger(__name__)


def generate_agents_md(
    project_path: str | None = None,
    include_env: bool = True,
) -> str:
    """
    为当前项目生成 AGENTS.md 内容。

    Args:
        project_path: 项目路径（None=当前目录）
        include_env: 是否包含环境检测信息

    Returns:
        AGENTS.md 格式的 Markdown 字符串
    """
    path = Path(project_path) if project_path else Path.cwd()
    project_name = path.resolve().name

    env = detect_environment(str(path)) if include_env else None

    lines = [
        f"# {project_name}",
        "",
        f"> 自动生成于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} | PyCoder AGENTS.md",
        "",
        "## 项目概述",
        "",
        f"- **项目名称**: {project_name}",
        f"- **主要语言**: Python {env.python_version if env else '3.x'}",
    ]

    if env:
        if env.venv_type and env.venv_type != "none":
            lines.append(f"- **虚拟环境**: {env.venv_type}")
        if env.package_manager:
            lines.append(f"- **包管理器**: {env.package_manager}")
        if env.project_type:
            type_map = {
                "web": "Web 应用",
                "data_science": "数据科学",
                "library": "库/框架",
                "script": "脚本工具",
                "unknown": "通用",
            }
            lines.append(f"- **项目类型**: {type_map.get(env.project_type, env.project_type)}")
        if env.frameworks:
            lines.append(f"- **框架**: {', '.join(env.frameworks[:8])}")

    lines.extend(
        [
            "",
            "## Python 编码规范",
            "",
            "### 必须遵守",
            "",
            "1. **PEP 8** — 代码风格严格遵循 PEP 8，使用 Black 自动格式化",
            "2. **Type Hints** — 所有公共函数/方法必须有类型注解",
            "3. **中文注释** — 注释和文档字符串使用中文",
            "4. **现代语法** — 优先使用 Python 3.10+ 特性（match/case, `|` 联合类型, walrus `:=`）",
            "5. **错误处理** — 使用具体异常类型，避免裸 `except:`",
            "6. **f-string** — 字符串格式化统一使用 f-string",
            "",
            "### 推荐做法",
            "",
            "- 使用 `pathlib.Path` 替代 `os.path`",
            "- 使用 `dataclasses` 或 `Pydantic` 定义数据模型",
            "- 使用 `asyncio` 处理 I/O 密集型任务",
            "- 配置通过环境变量 + `.env` 文件注入（python-dotenv）",
            "- 敏感信息（API Key、密码）绝不硬编码",
            "",
            "### 禁止做法",
            "",
            "- ❌ 裸 `except:` 吞掉所有异常",
            "- ❌ 使用 `from module import *`",
            "- ❌ 在函数参数中使用可变默认值 `def f(x=[])`",
            "- ❌ 硬编码文件路径（使用相对路径或配置）",
            "- ❌ 在生产代码中使用 `print()` 调试（用 `logging`）",
            "",
            "## 项目结构约定",
            "",
            "```",
            "project/",
            "├── src/            # 源代码",
            "├── tests/          # 测试（pytest）",
            "├── docs/           # 文档",
            "├── config/         # 配置文件",
            "├── scripts/        # 工具脚本",
            "├── pyproject.toml  # 项目元数据",
            "├── .env.example    # 环境变量模板",
            "└── AGENTS.md       # 本文件",
            "```",
            "",
            "## 测试规范",
            "",
            "- 测试框架: **pytest**",
            "- 覆盖率目标: >= 80%",
            "- 测试文件命名: `test_<模块名>.py`",
            "- CI 中必须通过全部测试才能合并",
            "",
            "## Git 工作流",
            "",
            "- 分支策略: `main` (稳定) + `feat/xxx` (功能) + `fix/xxx` (修复)",
            "- 提交格式: `feat: xxx` / `fix: xxx` / `docs: xxx` / `refactor: xxx` / `test: xxx`",
            "- PR 需要至少 1 人 Code Review 通过",
            "- 合并前 squash commits 保持历史整洁",
            "",
            "## AI Agent 协作规则",
            "",
            "当 AI 助手修改代码时，应遵循:",
            "",
            "1. **先读后改** — 修改文件前先读取完整内容",
            "2. **Diff 展示** — 修改后展示 unified diff，用户确认后写入",
            "3. **保持一致性** — 遵循项目现有的代码风格和模式",
            "4. **最小化改动** — 只修改必要的部分，不过度重构",
            "5. **可回滚** — 重大改动前建议创建 git commit 或备份",
            "6. **解释变更** — 每次修改附带中文说明原因",
            "",
        ]
    )

    # 环境特定建议
    if env and env.frameworks:
        lines.append("## 环境特定约定\n")
        for fw in env.frameworks:
            if fw == "FastAPI":
                lines.extend(
                    [
                        "### FastAPI 约定",
                        "",
                        "- 使用 `async def` 处理路由",
                        "- 使用 Pydantic v2 模型定义请求/响应",
                        "- API 路径使用 RESTful 风格（复数名词）",
                        "- 依赖注入使用 `Depends()`",
                        "",
                    ]
                )
            elif fw == "Django":
                lines.extend(
                    [
                        "### Django 约定",
                        "",
                        "- 遵循 Django 最佳实践（Fat Models, Thin Views）",
                        "- 使用 Django ORM 而非原始 SQL",
                        "- 配置按环境分离（settings/base.py, dev.py, prod.py）",
                        "",
                    ]
                )
            elif fw == "Flask":
                lines.extend(
                    [
                        "### Flask 约定",
                        "",
                        "- 使用 Blueprint 组织路由",
                        "- 使用 Flask-SQLAlchemy 管理数据库",
                        "- 工厂模式创建 app 实例",
                        "",
                    ]
                )
            elif fw in ("pandas", "NumPy"):
                lines.extend(
                    [
                        "### 数据科学约定",
                        "",
                        "- 使用 Jupyter Notebook 进行探索性分析",
                        "- 将可复用逻辑抽取为 .py 模块",
                        "- 数据处理管道使用函数式风格",
                        "- 结果可视化使用 matplotlib/seaborn",
                        "",
                    ]
                )
            elif fw == "PyTorch":
                lines.extend(
                    [
                        "### PyTorch 约定",
                        "",
                        "- 模型定义继承 `torch.nn.Module`",
                        "- 使用 `torch.utils.data.DataLoader` 加载数据",
                        "- 训练循环使用 tqdm 进度条",
                        "- 模型保存使用 `state_dict()`",
                        "",
                    ]
                )

    lines.extend(
        [
            "---",
            "",
            "## Prompt 缓存优化规则（运行时自动生效）",
            "",
            "> 以下规则由 `pycoder.prompts.cache_rules` 模块在每次 LLM 调用时自动注入。",
            "> 所有 Agent（含未来新增）的 system prompt 末尾都会自动追加此规则，",
            "> 无需在每个 Agent 角色的 `agent_definitions.AGENT_ROLES` 中手动维护。",
            "",
            "1. **system prompt 固定在 messages[0]** — 不插入时间戳/动态 ID",
            "2. **tools 按 `function.name` 字典序稳定序列化**",
            "3. **历史消息 append-only** — 不重排、不删除中间轮次",
            "4. **差异化内容在末尾** — 用户输入/文件内容放最后一条 message",
            "5. **重试时仅修改最后一条 user message** — 不重建整个 messages 数组",
            "",
            "---",
            "",
            "*此文件由 PyCoder 自动生成。运行 `python -m pycoder --agents` 重新生成。*",
        ]
    )

    return "\n".join(lines)


def generate_and_write(project_path: str | None = None) -> Path:
    """生成并写入 AGENTS.md 到项目根目录"""
    path = Path(project_path) if project_path else Path.cwd()
    content = generate_agents_md(str(path))
    agents_path = path / "AGENTS.md"

    with open(agents_path, "w", encoding="utf-8") as f:
        f.write(content)

    return agents_path


def load_agents_md(project_path: str | None = None) -> str | None:
    """加载项目中的 AGENTS.md 文件"""
    path = Path(project_path) if project_path else Path.cwd()
    agents_path = path / "AGENTS.md"

    if agents_path.exists():
        try:
            with open(agents_path, encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.debug("Failed to read AGENTS.md: %s", e)

    return None


def get_agents_context(project_path: str | None = None) -> str:
    """
    获取 AGENTS.md 上下文（用于注入系统提示）。

    如果项目有 AGENTS.md，加载；否则生成。
    截断到 2000 字符，适配系统提示。
    """
    content = load_agents_md(project_path)

    if content is None:
        # 自动生成（精简版，只包含关键约定）
        content = generate_agents_md(project_path, include_env=True)
        # 只取编码规范和 Agent 规则部分
        lines = content.split("\n")
        key_sections = []
        in_key_section = False
        for line in lines:
            if (
                line.startswith("## Python 编码规范")
                or line.startswith("## AI Agent 协作规则")
                or line.startswith("## 环境特定约定")
            ):
                in_key_section = True
            elif line.startswith("## ") and in_key_section:
                in_key_section = False
            elif in_key_section:
                key_sections.append(line)

        if key_sections:
            content = "\n".join(key_sections)

    # 截断
    if len(content) > 2000:
        content = content[:2000] + "\n\n# ... (AGENTS.md 过长，已截断)"

    return content


# ══════════════════════════════════════════════════════════
# 角色提示词自动生成 — 单一事实源同步
# ════════════════════════════════════════════════════════


def generate_role_prompts_md(output_dir: str | None = None) -> list[Path]:
    """从 AGENT_ROLES 单一事实源自动生成 prompts/agents/*.md

    消除三处提示词冗余：md 文件改为 AGENT_ROLES 的只读产物。
    改角色定义只需改 ``pycoder/server/services/agent_definitions.py``，
    再运行本函数即可全量同步（含 documenter / fixer 等代码侧角色）。

    Args:
        output_dir: 输出目录（默认 ``pycoder/prompts/agents``）

    Returns:
        生成的 .md 文件路径列表
    """
    from pycoder.server.services.agent_definitions import AGENT_ROLES

    base = Path(output_dir) if output_dir else (Path(__file__).resolve().parent / "agents")
    base.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for role_id, role in AGENT_ROLES.items():
        md = _render_role_md(role)
        p = base / f"{role_id}.md"
        p.write_text(md, encoding="utf-8")
        written.append(p)
    return written


def _render_role_md(role) -> str:
    """将单个 AgentRole 渲染为 Markdown 文档"""
    lines = [
        f"# {role.name} (`{role.id}`)",
        "",
        "> 自动生成自 `agent_definitions.AGENT_ROLES`，请勿手改；",
        "> 改角色定义请编辑 `pycoder/server/services/agent_definitions.py` "
        "后运行 `python -m pycoder.prompts.agents_generator --roles`。",
        "",
        role.description,
        "",
        "## 配置",
        "",
        f"- 模型: `{role.model}`",
        f"- 模型分层: `{role.model_tier}`",
        f"- 可并行: {'是' if role.parallel else '否'}" f"（最大并发 {role.max_concurrent}）",
        f"- 禁止操作: {', '.join(role.forbid_actions) or '无'}",
        f"- 绑定 Skills: {', '.join(role.skills) or '无'}",
        "",
        "## 工具",
        "",
        ", ".join(f"`{t}`" for t in role.tools),
        "",
        "## 系统提示词",
        "",
        "~~~",
        role.system_prompt.strip(),
        "~~~",
        "",
        "## ⛓️ Prompt 缓存优化规则（运行时自动注入）",
        "",
        "> 本规则由 `pycoder.prompts.cache_rules` 模块在每次 LLM 调用时自动注入",
        "> system prompt 末尾，无需在 `agent_definitions.AGENT_ROLES` 中手动维护。",
        "> 生成时机：`chat_bridge.chat_stream()` / `agent_loop.execute()`",
        "",
        "- system prompt 固定在 `messages[0]`，前缀不插入动态内容",
        "- tools 列表按 `function.name` 排序保证序列稳定",
        "- 历史消息 append-only，不重新排序",
        "- 差异化内容（用户输入/文件内容）放在最后一条 user message",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    if "--roles" in sys.argv:
        paths = generate_role_prompts_md()
        for p in paths:
            print(f"✅ 生成角色提示词: {p}")
