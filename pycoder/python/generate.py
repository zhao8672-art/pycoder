"""One-click project generation (extracted from __main__.py)."""

from __future__ import annotations


def generate_project(description: str, target_dir: str | None = None) -> dict:
    """
    一键生成完整项目（Hermes/Codex 兼容 API）。

    Returns:
        {"success": bool, "project_path": str, "template": str, "error": str}
    """
    try:
        _run_generate_mode(description, target_dir or "")
        return {
            "success": True,
            "project_path": target_dir or ".",
            "template": "auto-detected",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# from pycoder.prompts.agents_generator import generate_agents_md (unused)


def _infer_name(description: str) -> str:
    """从描述中自动推断项目名称。"""
    import re

    # 移除框架前缀 (如 "FastAPI ", "Flask ", "Django ")
    cleaned = re.sub(r"^(FastAPI|Flask|Django|Express|Spring\s*Boot)\s+", "", description)
    # 提取中文实体名映射为英文
    entity_map = {
        "用户": "user", "图书": "book", "商品": "product", "订单": "order",
        "文章": "article", "产品": "product", "项目": "project", "任务": "task",
        "学生": "student", "老师": "teacher", "课程": "course", "日志": "log",
        "分类": "category", "标签": "tag",
    }
    for cn, en in entity_map.items():
        if cn in cleaned:
            return f"{en}-manager"
    # 回退：使用描述的前几个英文字符，或默认名
    eng = re.sub(r"[^\w-]", "", cleaned.lower().replace(" ", "-"))
    return eng[:30] if eng else "my-project"


def _run_generate_mode(description: str, target_dir: str) -> None:
    """一键生成完整可运行的项目"""
    from pathlib import Path

    from pycoder.python.scaffold import find_template_by_description
    from pycoder.python.template_code import generate_scaffold_project

    workspace = Path(target_dir).resolve() if target_dir else Path.cwd()

    # 如果指定了目录，直接使用它；否则自动推断项目名
    if target_dir:
        project_path = workspace
    else:
        project_path = workspace / _infer_name(description)

    template = find_template_by_description(description)

    # 从描述中提取实体名（如"图书" → "book"）
    import re

    entity_match = re.search(
        r"(用户|图书|商品|订单|文章|产品|项目|任务|学生|老师|课程|日志|分类|标签)", description
    )
    entity_name = entity_match.group(1) if entity_match else "item"
    entity_map = {
        "用户": "user",
        "图书": "book",
        "商品": "product",
        "订单": "order",
        "文章": "article",
        "产品": "product",
        "项目": "project",
        "任务": "task",
        "学生": "student",
        "老师": "teacher",
        "课程": "course",
        "日志": "log",
        "分类": "category",
        "标签": "tag",
    }
    entity_en = entity_map.get(entity_name, "item")

    template_name = template.name if template else "fastapi-crud"

    # 确定模板类型
    template_name = template.name if template else "fastapi-crud"
    template_display = template.display_name if template else "FastAPI CRUD"

    print(f"\n{'='*50}")
    print("  🚀 PyCoder 一键项目生成")
    print(f"{'='*50}")
    print(f"  需求: {description}")
    print(f"  模板: {template_display}")
    print(f"  目标: {project_path}")
    print(f"{'='*50}\n")

    # 生成真实的生产级代码
    if project_path.exists():
        import shutil

        shutil.rmtree(project_path)
    project_path.mkdir(parents=True)

    print("📝 生成完整项目代码...\n")

    # 先生成子目录（避免路径问题）
    for sub in ["src", "src/models", "src/routers", "src/schemas", "tests", "pages", "data"]:
        (project_path / sub).mkdir(parents=True, exist_ok=True)

    try:
        created = generate_scaffold_project(project_path, template_name, entity_en)
    except Exception as e:
        print(f"  ❌ 代码生成失败: {e}")
        # 回退到空模板
        from pycoder.python.scaffold import scaffold_project

        created = scaffold_project(template, project_path, project_path.name)

    total = len(created)
    py_files = [f for f in created if f.endswith(".py")]

    print(f"  ✅ 生成 {total} 个文件 ({len(py_files)} 个 Python 文件):")
    for f in sorted(created):
        size = (project_path / f).stat().st_size if (project_path / f).exists() else 0
        size_str = f"({size}B)" if size < 1000 else f"({size/1000:.1f}KB)"
        print(f"     📄 {f} {size_str}")

    # 统计代码行数
    total_lines = 0
    for py_file in project_path.rglob("*.py"):
        try:
            total_lines += len(py_file.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeDecodeError):
            pass

    print(f"\n  📊 总计: {total} 个文件, {total_lines} 行代码")
    print(f"  📐 技术栈: {template_display}")
    print(f"\n{'='*50}")
    print("  启动项目:")
    print(f"    cd {project_path}")
    print("    pip install -r requirements.txt")
    print(
        f"    {'uvicorn src.main:app --reload' if 'fastapi' in template_name else 'streamlit run app.py'}"
    )
    print(f"{'='*50}\n")

    # 尝试自动安装依赖
    try:
        import subprocess

        req_path = project_path / "requirements.txt"
        if req_path.exists():
            print("📦 正在安装依赖...")
            result = subprocess.run(
                ["pip", "install", "-r", str(req_path)],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode == 0:
                print("  ✅ 依赖安装完成")
            else:
                print(f"  ⚠️ 部分依赖安装失败: {result.stderr[-200:]}")
    except Exception as e:
        print(f"  ⚠️ 自动安装跳过: {e}")
        print("     请手动执行: pip install -r requirements.txt")

    # 尝试运行测试
    try:
        print("\n🧪 运行测试...")
        import subprocess

        result = subprocess.run(
            ["pytest", str(project_path / "tests"), "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            print("  ✅ 全部测试通过!")
        else:
            test_out = result.stdout[-300:]
            print(f"  ⚠️ 测试结果:\n{test_out}")
    except Exception as e:
        print(f"  ⚠️ 测试跳过: {e}")
