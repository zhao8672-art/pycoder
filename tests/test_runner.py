#!/usr/bin/env python
"""测试 template_code.py 是否能生成完整项目。

改造说明（2026-07-10 测试卫生修复）：
原文件在模块顶层直接 shutil.rmtree + mkdir，pytest 收集时即触发删除，
被 safe-delete 沙箱拦截。现改为标准 pytest 测试函数 + tmp_path fixture，
既不再触发顶层删除，也不污染项目目录。
"""
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\Administrator\Desktop\pycode")

from pycoder.python.template_code import (
    generate_fastapi_crud,
    generate_fastapi_auth,
    generate_scaffold_project,
)


def test_generate_fastapi_crud(tmp_path):
    """测试1: generate_fastapi_crud 直接调用。"""
    d1 = tmp_path / "test-gen-crud"
    d1.mkdir()
    result = generate_fastapi_crud(d1, "book")
    print(f"TEST 1 - FastAPI CRUD:")
    print(f"  Files: {len(result)}")
    py_files = list(d1.rglob("*.py"))
    total_lines = sum(
        len(f.read_text(encoding="utf-8").splitlines())
        for f in py_files
        if f.is_file()
    )
    print(f"  Python files: {len(py_files)}")
    print(f"  Total lines: {total_lines}")
    print(f"  Files: {[str(f.relative_to(d1)) for f in sorted(py_files)]}")

    # 检查 main.py 是否有实际内容
    main_py = d1 / "src" / "main.py"
    if main_py.exists():
        content = main_py.read_text(encoding="utf-8")
        print(f"  main.py: {len(content)} chars, {len(content.splitlines())} lines")
        print(f"  Contains FastAPI? {'FastAPI' in content}")
    else:
        print("  main.py: MISSING!")

    # 检查 database.py
    db_py = d1 / "src" / "database.py"
    if db_py.exists():
        content = db_py.read_text(encoding="utf-8")
        print(
            f"  database.py: {len(content)} chars, "
            f"contains create_engine? {'create_engine' in content}"
        )
    else:
        print("  database.py: MISSING!")


def test_generate_scaffold_project(tmp_path):
    """测试2: generate_scaffold_project。"""
    d2 = tmp_path / "test-gen-tpl"
    d2.mkdir()
    result2 = generate_scaffold_project(d2, "fastapi-crud", "item")
    print("\nTEST 2 - scaffold_project:")
    print(f"  Files: {len(result2)}")
    py_files2 = list(d2.rglob("*.py"))
    total_lines2 = sum(
        len(f.read_text(encoding="utf-8").splitlines())
        for f in py_files2
        if f.is_file()
    )
    print(f"  Total lines: {total_lines2}")
    print("\nDONE")
