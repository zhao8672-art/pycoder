"""
项目脚手架系统 — 内置项目模板，一键生成标准项目结构

提供:
- 8 个内置模板 (FastAPI-CRUD, Streamlit, CLI, Flask 等)
- 模板注册与发现
- 从模板+AI定制生成项目
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TemplateFile:
    """模板文件定义"""

    path: str  # 相对路径 (如 "src/models/user.py")
    content: str = ""  # 文件内容 (可为空，由AI填充)
    description: str = ""  # 文件用途说明


@dataclass
class ProjectTemplate:
    """项目模板"""

    name: str  # "fastapi-crud"
    display_name: str  # "FastAPI CRUD 项目"
    description: str  # 详细描述
    category: str  # "web" | "cli" | "data" | "library"
    python_version: str = ">=3.10"
    files: list[TemplateFile] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    dev_dependencies: list[str] = field(default_factory=list)
    entry_point: str = ""  # "src/main.py" 或 "app.py"
    run_command: str = ""  # "uvicorn src.main:app --reload"


# ══════════════════════════════════════════════════════════
# 内置模板库 (8个)
# ══════════════════════════════════════════════════════════

BUILTIN_TEMPLATES: dict[str, ProjectTemplate] = {
    # ── FastAPI CRUD ──
    "fastapi-crud": ProjectTemplate(
        name="fastapi-crud",
        display_name="FastAPI CRUD REST API",
        description="完整的 FastAPI RESTful API 项目，含模型、路由、Schema、数据库连接",
        category="web",
        dependencies=["fastapi", "uvicorn[standard]", "sqlalchemy", "pydantic"],
        dev_dependencies=["pytest", "httpx"],
        entry_point="src/main.py",
        run_command="uvicorn src.main:app --reload",
        files=[
            TemplateFile("src/__init__.py", "", "包初始化"),
            TemplateFile("src/models/__init__.py", "", "模型包"),
            TemplateFile("src/routers/__init__.py", "", "路由包"),
            TemplateFile("src/schemas/__init__.py", "", "Schema包"),
            TemplateFile("src/database.py", "", "数据库连接与Session"),
            TemplateFile("src/main.py", "", "FastAPI 应用入口"),
            TemplateFile("tests/__init__.py", "", "测试包"),
            TemplateFile("requirements.txt", "", "依赖清单"),
            TemplateFile("README.md", "", "项目说明"),
        ],
    ),
    # ── FastAPI + JWT Auth ──
    "fastapi-auth": ProjectTemplate(
        name="fastapi-auth",
        display_name="FastAPI + JWT 认证系统",
        description="FastAPI 项目，含用户注册/登录、JWT Token 认证、角色权限",
        category="web",
        dependencies=[
            "fastapi",
            "uvicorn[standard]",
            "sqlalchemy",
            "pydantic",
            "python-jose[cryptography]",
            "passlib[bcrypt]",
            "python-multipart",
        ],
        dev_dependencies=["pytest", "httpx"],
        entry_point="src/main.py",
        run_command="uvicorn src.main:app --reload",
        files=[
            TemplateFile("src/__init__.py", "", "包初始化"),
            TemplateFile("src/models/__init__.py", "", "模型包"),
            TemplateFile("src/models/user.py", "", "User 模型 (SQLAlchemy)"),
            TemplateFile("src/routers/__init__.py", "", "路由包"),
            TemplateFile("src/routers/auth.py", "", "认证路由 (注册/登录/Token)"),
            TemplateFile("src/routers/users.py", "", "用户路由 (CRUD)"),
            TemplateFile("src/schemas/__init__.py", "", "Schema包"),
            TemplateFile("src/schemas/user.py", "", "User Pydantic 模型"),
            TemplateFile("src/auth.py", "", "JWT 工具函数"),
            TemplateFile("src/database.py", "", "数据库连接"),
            TemplateFile("src/main.py", "", "FastAPI 入口 (含CORS)"),
            TemplateFile("tests/__init__.py", "", "测试包"),
            TemplateFile("tests/test_auth.py", "", "认证测试"),
            TemplateFile("requirements.txt", "", "依赖清单"),
            TemplateFile("README.md", "", "项目说明"),
        ],
    ),
    # ── Streamlit 数据看板 ──
    "streamlit-dashboard": ProjectTemplate(
        name="streamlit-dashboard",
        display_name="Streamlit 数据看板",
        description="Streamlit 数据可视化看板，适合快速搭建数据展示和监控页面",
        category="data",
        dependencies=["streamlit", "pandas", "plotly", "numpy"],
        dev_dependencies=[],
        entry_point="app.py",
        run_command="streamlit run app.py",
        files=[
            TemplateFile("app.py", "", "Streamlit 主应用"),
            TemplateFile("pages/__init__.py", "", "多页面包"),
            TemplateFile("data/__init__.py", "", "数据模块"),
            TemplateFile("utils/__init__.py", "", "工具函数"),
            TemplateFile("requirements.txt", "", "依赖清单"),
            TemplateFile("README.md", "", "项目说明"),
        ],
    ),
    # ── CLI 命令行工具 (Click) ──
    "cli-tool": ProjectTemplate(
        name="cli-tool",
        display_name="CLI 命令行工具 (Click)",
        description="基于 Click 的 Python 命令行工具，支持子命令、参数解析、彩色输出",
        category="cli",
        dependencies=["click", "rich"],
        dev_dependencies=["pytest"],
        entry_point="src/cli.py",
        run_command="python -m src.cli --help",
        files=[
            TemplateFile("src/__init__.py", "", "包初始化"),
            TemplateFile("src/cli.py", "", "Click CLI 入口 (含子命令)"),
            TemplateFile("src/commands/__init__.py", "", "命令包"),
            TemplateFile("tests/__init__.py", "", "测试包"),
            TemplateFile("requirements.txt", "", "依赖清单"),
            TemplateFile("README.md", "", "项目说明"),
        ],
    ),
    # ── 数据处理管道 ──
    "data-pipeline": ProjectTemplate(
        name="data-pipeline",
        display_name="数据处理管道 (pandas)",
        description="基于 pandas 的数据 ETL 管道，含数据加载、清洗、转换、输出",
        category="data",
        dependencies=["pandas", "numpy", "openpyxl"],
        dev_dependencies=["pytest"],
        entry_point="src/pipeline.py",
        run_command="python src/pipeline.py",
        files=[
            TemplateFile("src/__init__.py", "", "包初始化"),
            TemplateFile("src/pipeline.py", "", "ETL 管道主逻辑"),
            TemplateFile("src/extract.py", "", "数据提取模块"),
            TemplateFile("src/transform.py", "", "数据转换模块"),
            TemplateFile("src/load.py", "", "数据加载模块"),
            TemplateFile("data/__init__.py", "", "数据目录"),
            TemplateFile("output/__init__.py", "", "输出目录"),
            TemplateFile("tests/__init__.py", "", "测试包"),
            TemplateFile("requirements.txt", "", "依赖清单"),
            TemplateFile("README.md", "", "项目说明"),
        ],
    ),
    # ── Flask REST API ──
    "flask-rest": ProjectTemplate(
        name="flask-rest",
        display_name="Flask REST API",
        description="基于 Flask 的 RESTful API 项目，含蓝图、数据库、错误处理",
        category="web",
        dependencies=["flask", "flask-sqlalchemy", "flask-cors"],
        dev_dependencies=["pytest"],
        entry_point="app.py",
        run_command="flask run --debug",
        files=[
            TemplateFile("app.py", "", "Flask 应用入口"),
            TemplateFile("config.py", "", "配置文件"),
            TemplateFile("models.py", "", "SQLAlchemy 模型"),
            TemplateFile("routes.py", "", "API 路由"),
            TemplateFile("tests/__init__.py", "", "测试包"),
            TemplateFile("tests/test_routes.py", "", "路由测试"),
            TemplateFile("requirements.txt", "", "依赖清单"),
            TemplateFile("README.md", "", "项目说明"),
        ],
    ),
    # ── Python 库基础结构 ──
    "python-library": ProjectTemplate(
        name="python-library",
        display_name="Python 库基础结构",
        description="标准的 Python 包/库项目，含 setup、测试、文档结构",
        category="library",
        dependencies=[],
        dev_dependencies=["pytest", "black", "ruff"],
        entry_point="",
        run_command="pytest tests/",
        files=[
            TemplateFile("src/__init__.py", "", "公共API导出"),
            TemplateFile("src/core.py", "", "核心逻辑"),
            TemplateFile("src/utils.py", "", "工具函数"),
            TemplateFile("tests/__init__.py", "", "测试包"),
            TemplateFile("tests/test_core.py", "", "核心测试"),
            TemplateFile("pyproject.toml", "", "项目元数据"),
            TemplateFile("README.md", "", "项目说明"),
        ],
    ),
    # ── Jupyter 分析项目 ──
    "jupyter-analysis": ProjectTemplate(
        name="jupyter-analysis",
        display_name="Jupyter 数据分析项目",
        description="适合数据探索、可视化和分析的 Jupyter Notebook 项目",
        category="data",
        dependencies=["jupyter", "pandas", "numpy", "matplotlib", "seaborn"],
        dev_dependencies=[],
        entry_point="notebooks/01_explore.ipynb",
        run_command="jupyter notebook",
        files=[
            TemplateFile("notebooks/01_explore.py", "", "数据探索脚本"),
            TemplateFile("notebooks/02_visualize.py", "", "可视化脚本"),
            TemplateFile("src/__init__.py", "", "可复用工具包"),
            TemplateFile("src/data_loader.py", "", "数据加载工具"),
            TemplateFile("src/plots.py", "", "绘图工具"),
            TemplateFile("data/__init__.py", "", "数据目录"),
            TemplateFile("requirements.txt", "", "依赖清单"),
            TemplateFile("README.md", "", "项目说明"),
        ],
    ),
}


# ══════════════════════════════════════════════════════════
# 脚手架 API
# ══════════════════════════════════════════════════════════


def list_templates(category: str = None) -> list[ProjectTemplate]:
    """列出所有可用模板"""
    templates = list(BUILTIN_TEMPLATES.values())
    if category:
        templates = [t for t in templates if t.category == category]
    return templates


def get_template(name: str) -> ProjectTemplate | None:
    """按名称获取模板"""
    for key, tmpl in BUILTIN_TEMPLATES.items():
        if key == name or tmpl.display_name == name:
            return tmpl
    return None


def find_template_by_description(description: str) -> ProjectTemplate | None:
    """根据描述文字智能匹配模板 (关键词匹配)"""
    desc_lower = description.lower()

    # 关键词→模板名 映射
    keywords = {
        "streamlit": "streamlit-dashboard",
        "看板": "streamlit-dashboard",
        "仪表盘": "streamlit-dashboard",
        "可视化": "streamlit-dashboard",
        "命令行": "cli-tool",
        "cli": "cli-tool",
        "click": "cli-tool",
        "工具": "cli-tool",
        "数据处理": "data-pipeline",
        "etl": "data-pipeline",
        "pipeline": "data-pipeline",
        "清洗": "data-pipeline",
        "转换": "data-pipeline",
        "flask": "flask-rest",
        "认证": "fastapi-auth",
        "登录": "fastapi-auth",
        "jwt": "fastapi-auth",
        "token": "fastapi-auth",
        "库": "python-library",
        "包": "python-library",
        "sdk": "python-library",
        "jupyter": "jupyter-analysis",
        "notebook": "jupyter-analysis",
        "分析": "jupyter-analysis",
        "统计": "jupyter-analysis",
    }

    for kw, tmpl_name in keywords.items():
        if kw in desc_lower:
            return get_template(tmpl_name)

    # 默认: fastapi-crud (最常见的需求)
    return get_template("fastapi-crud")


def scaffold_project(
    template: ProjectTemplate,
    target_dir: Path,
    project_name: str,
) -> list[str]:
    """根据模板创建项目基础结构 (只创建目录和空文件)"""
    created = []

    for tfile in template.files:
        file_path = target_dir / tfile.path
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if not file_path.exists():
            file_path.write_text("# " + file_path.name + "\n", encoding="utf-8")
            created.append(tfile.path)

    # 写 requirements.txt
    req_path = target_dir / "requirements.txt"
    req_lines = list(template.dependencies)
    if req_lines:
        req_path.write_text("\n".join(req_lines) + "\n", encoding="utf-8")
        if "requirements.txt" not in created:
            created.append("requirements.txt")

    return created
