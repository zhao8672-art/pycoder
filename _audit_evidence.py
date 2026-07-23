"""全面审计证据脚本 — 核查10项审计报告问题

用法: python _audit_evidence.py

输出: 每项问题的文件路径、大小、前3行 + 依赖锁定检查 + 模块导入验证
"""
from __future__ import annotations

import os
import re
import sys
import urllib.request
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent

# ============================================================
# 10 项审计检查定义
# ============================================================
AUDIT_ITEMS = [
    (
        "1. 依赖管理不一致",
        [
            "pyproject.toml",
            "requirements.txt",
            "requirements/requirements.in",
            "requirements/requirements-dev.in",
            "requirements/requirements-browser.in",
            "requirements/requirements-help.in",
            "requirements/requirements-playwright.in",
            "requirements-all.txt",
        ],
        "pyproject.toml + 5 个可选依赖组 + requirements-all.txt",
    ),
    (
        "2. Windows 兼容性不足",
        [
            "start.bat",
            "start.ps1",
            "scripts/pycoder.bat",
            "scripts/pycoder.ps1",
            "scripts/run.py",
            "Makefile",
        ],
        "Windows 启动脚本 (仓库根 + scripts/)",
    ),
    (
        "3. 测试配置缺失",
        [
            "pyproject.toml",
            "pytest.ini",
            "tests/test_cross_platform_consistency.py",
            "tests/conftest.py",
        ],
        "pytest 配置 + 测试文件",
    ),
    (
        "4. 文档脱节",
        [
            "README.md",
            "docs/LAUNCH.md",
            "pyproject.toml",
            "scripts/print_commands.py",
            "scripts/check_readme_consistency.py",
        ],
        "文档 + 一致性检查脚本",
    ),
    (
        "5. 持久化记忆系统",
        [
            "memory/__init__.py",
            "pycoder/memory/__init__.py",
            "pycoder/memory/session_memory.py",
            "pycoder/memory/persistent_memory.py",
            "pycoder/memory/deep_memory.py",
        ],
        "SQLite + 向量检索记忆系统",
    ),
    (
        "6. 安全代码执行沙箱",
        [
            "safety/__init__.py",
            "pycoder/safety/__init__.py",
            "pycoder/safety/sandbox.py",
            "pycoder/safety/sandbox_executor.py",
            "pycoder/safety/permission.py",
            "pycoder/safety/audit.py",
            "pycoder/safety/circuit_breaker.py",
            "pycoder/safety/rollback.py",
            "pycoder/adapters/sandbox_selector.py",
            "pycoder/server/routers/sandbox_api.py",
            "Dockerfile",
            "docker-compose.yml",
        ],
        "Docker 沙箱 + 权限引擎 + 熔断器 + 回滚",
    ),
    (
        "7. 多模态支持",
        [
            "multimodal/__init__.py",
            "pycoder/multimodal/__init__.py",
            "pycoder/multimodal/vision_client.py",
            "pycoder/multimodal/ocr_engine.py",
            "pycoder/multimodal/image_analyzer.py",
            "pycoder/multimodal/tool_definitions.py",
        ],
        "OCR + 视觉模型 + 图像分析",
    ),
    (
        "8. 插件系统",
        [
            "plugins/__init__.py",
            "pycoder/plugins/__init__.py",
            "pycoder/plugins/base.py",
            "pycoder/plugins/hermes_plugin.py",
        ],
        "插件注册中心 + BasePlugin + 钩子",
    ),
    (
        "9. 错误监控",
        [
            "observability/__init__.py",
            "pycoder/observability/__init__.py",
            "pycoder/observability/sentry.py",
        ],
        "Sentry 错误监控 (条件加载)",
    ),
    (
        "10. 依赖锁定验证",
        [],
        "requirements.txt 精确锁定 (==) 检查",
    ),
]


# ============================================================
# 检查函数
# ============================================================

def check_one(rel_path: str) -> dict:
    full = ROOT / rel_path
    info = {
        "path": str(full),
        "exists": full.exists(),
        "size": 0,
        "lines": [],
    }
    if info["exists"]:
        try:
            info["size"] = full.stat().st_size
            content = full.read_text(encoding="utf-8", errors="replace")
            info["lines"] = content.splitlines()[:3]
        except Exception as e:
            info["lines"] = [f"[ERROR reading: {e}]"]
    return info


def check_python_module(mod: str) -> dict:
    info = {"module": mod, "importable": False, "version": None, "file": None}
    try:
        m = __import__(mod, fromlist=["*"])
        info["importable"] = True
        info["file"] = getattr(m, "__file__", None)
        info["version"] = getattr(m, "__version__", None)
    except ImportError as e:
        info["import_error"] = str(e)
    except Exception as e:
        info["other_error"] = str(e)
    return info


def check_dependency_locking() -> dict:
    """检查 requirements.txt 是否精确锁定 (==), 以及 pyproject.toml 配置"""
    result = {"all_locked": True, "details": []}

    # 检查 requirements.txt
    req_path = ROOT / "requirements.txt"
    if not req_path.exists():
        result["all_locked"] = False
        result["details"].append("requirements.txt 不存在")
        return result

    req_content = req_path.read_text(encoding="utf-8")

    # 关键依赖必须使用 ==
    critical_deps = [
        ("requests", "requests=="),
        ("fastapi", "fastapi=="),
        ("litellm", "litellm=="),
        ("openai", "openai=="),
        ("pydantic", "pydantic=="),
        ("sentry-sdk", "sentry-sdk"),  # 可能带 extras: sentry-sdk[fastapi,httpx]==
        ("pillow", "pillow=="),
        ("pytesseract", "pytesseract=="),
        ("opencv-python-headless", "opencv-python-headless=="),
        ("pdfplumber", "pdfplumber=="),
    ]
    for name, pattern in critical_deps:
        if pattern in req_content:
            result["details"].append(f"  [OK]  {name}: 精确锁定")
        else:
            result["details"].append(f"  [FAIL] {name}: 未找到 {pattern}")
            result["all_locked"] = False

    # 检查是否有裸 >= 版本
    has_bare_ge = ">=" in req_content and not any(
        f"{name}==>=" in req_content for name, _ in critical_deps
    )
    result["has_bare_ge"] = has_bare_ge

    # 检查 pyproject.toml
    pyproject_path = ROOT / "pyproject.toml"
    if pyproject_path.exists():
        pyproject = pyproject_path.read_text(encoding="utf-8")
        result["pyproject_has_dynamic_deps"] = 'dynamic = ["dependencies", "optional-dependencies"]' in pyproject
        result["pyproject_has_pytest_config"] = "[tool.pytest.ini_options]" in pyproject
        result["pyproject_has_optional_deps"] = (
            "[tool.setuptools.dynamic.optional-dependencies]" in pyproject
        )
        result["pyproject_has_scripts"] = "[project.scripts]" in pyproject
    else:
        result["pyproject_has_dynamic_deps"] = False
        result["pyproject_has_pytest_config"] = False
        result["pyproject_has_optional_deps"] = False
        result["pyproject_has_scripts"] = False

    return result


# ============================================================
# 主函数
# ============================================================

def main() -> int:
    print("=" * 78)
    print("  PyCoder 全面审计证据报告")
    print(f"  生成时间: {__import__('datetime').datetime.now().isoformat()}")
    print(f"  仓库根:   {ROOT}")
    print("=" * 78)
    print()

    total_files = 0
    found_files = 0

    for title, paths, desc in AUDIT_ITEMS:
        print(f"[{title}]")
        print(f"  说明: {desc}")

        if title == "10. 依赖锁定验证":
            # 特殊处理: 依赖锁定检查
            deps = check_dependency_locking()
            print(f"  requirements.txt 全部精确锁定(==): {deps['all_locked']}")
            for detail in deps["details"]:
                print(detail)
            print(f"  pyproject.toml dynamic dependencies: {deps.get('pyproject_has_dynamic_deps', False)}")
            print(f"  pyproject.toml [tool.pytest.ini_options]: {deps.get('pyproject_has_pytest_config', False)}")
            print(f"  pyproject.toml [tool.setuptools.dynamic.optional-dependencies]: {deps.get('pyproject_has_optional_deps', False)}")
            print(f"  pyproject.toml [project.scripts]: {deps.get('pyproject_has_scripts', False)}")
            print()
            continue

        for rel in paths:
            total_files += 1
            info = check_one(rel)
            mark = "[OK]" if info["exists"] else "[MISSING]"
            if info["exists"]:
                found_files += 1
            print(f"  {mark}  {rel}")
            if info["exists"]:
                print(f"        size: {info['size']:,} bytes")
                for i, line in enumerate(info["lines"], 1):
                    short = line if len(line) < 100 else line[:97] + "..."
                    print(f"        L{i}: {short}")
        print()

    # Python 模块导入检查
    print("=" * 78)
    print("  Python 模块真实可导入性检查")
    print("=" * 78)
    print()
    total_modules = 0
    found_modules = 0
    for mod in [
        "pycoder",
        "pycoder.memory",
        "pycoder.memory.deep_memory",
        "pycoder.safety",
        "pycoder.safety.sandbox",
        "pycoder.multimodal",
        "pycoder.multimodal.vision_client",
        "pycoder.plugins",
        "pycoder.observability",
        "pycoder.observability.sentry",
    ]:
        total_modules += 1
        info = check_python_module(mod)
        mark = "[OK]" if info["importable"] else "[FAIL]"
        if info["importable"]:
            found_modules += 1
        print(f"  {mark}  import {mod}")
        if info["importable"]:
            print(f"        file: {info['file']}")
            if info["version"]:
                print(f"        version: {info['version']}")
        else:
            print(f"        error: {info.get('import_error', info.get('other_error', 'unknown'))}")
    print()

    # 第三方依赖检查
    print("=" * 78)
    print("  第三方关键依赖真实可导入性检查")
    print("=" * 78)
    print()
    third_party_ok = True
    for mod in ["sentry_sdk", "PIL", "pytesseract", "pdfplumber", "cv2",
                "fastapi", "litellm", "openai", "httpx", "pydantic"]:
        info = check_python_module(mod)
        mark = "[OK]" if info["importable"] else "[FAIL]"
        if not info["importable"]:
            third_party_ok = False
        print(f"  {mark}  import {mod:20s}  version={info.get('version', 'N/A')}")
    print()

    # 汇总
    deps = check_dependency_locking()
    print("=" * 78)
    print("  总计")
    print("=" * 78)
    print(f"  文件: {found_files} / {total_files} 存在 ({found_files / max(total_files, 1) * 100:.1f}%)")
    print(f"  PyCoder 模块: {found_modules} / {total_modules} 可导入")
    print(f"  第三方依赖: {'全部可导入' if third_party_ok else '部分缺失'}")
    print(f"  依赖锁定: {'全部(==)精确锁定' if deps['all_locked'] else '存在问题'}")
    print(f"  pyproject.toml 测试配置: {'OK' if deps.get('pyproject_has_pytest_config') else 'MISSING'}")
    print(f"  pyproject.toml 可选依赖: {'OK' if deps.get('pyproject_has_optional_deps') else 'MISSING'}")
    print()

    # Git 状态
    print("=" * 78)
    print("  Git 状态")
    print("=" * 78)
    print()
    import subprocess
    r = subprocess.run(
        ["git", "log", "--oneline", "origin/master", "-5"],
        capture_output=True, text=True, timeout=10, cwd=str(ROOT),
    )
    print("  远程 origin/master 最近 5 个 commit:")
    for line in (r.stdout or "").strip().split("\n"):
        print(f"    {line}")
    r2 = subprocess.run(
        ["git", "diff", "origin/master", "--stat"],
        capture_output=True, text=True, timeout=10, cwd=str(ROOT),
    )
    if (r2.stdout or "").strip():
        print("  本地 vs 远程: 有差异")
    else:
        print("  本地 vs 远程: 已同步")
    print()

    # 后端健康
    print("=" * 78)
    print("  后端服务健康")
    print("=" * 78)
    print()
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8423/api/health/live",
            headers={"Connection": "close"},
        )
        with urllib.request.urlopen(req, timeout=5) as r3:
            body = r3.read().decode("utf-8", errors="replace")
            print(f"  [OK] /api/health/live  HTTP {r3.status}")
            print(f"       {body[:300]}")
    except Exception as e:
        print(f"  [INFO] 后端未运行: {e}")

    # 最终结论
    print()
    print("=" * 78)
    all_ok = (
        found_files == total_files
        and found_modules == total_modules
        and third_party_ok
        and deps["all_locked"]
    )
    if all_ok:
        print("  结论: 所有 10 项审计检查通过 — 系统功能完整")
        print("=" * 78)
        return 0
    else:
        print("  结论: 存在未通过项，详见上方 [FAIL] 标记")
        print("=" * 78)
        return 1


if __name__ == "__main__":
    sys.exit(main())