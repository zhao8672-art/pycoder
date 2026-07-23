"""PyCoder 跨平台任务运行器 — Windows 原生 PowerShell / CMD 友好

当系统没有 make 时, 用 Python 替代:
    python scripts/run.py install-all
    python scripts/run.py test
    python scripts/run.py lint

设计: 纯标准库, 无第三方依赖, 所有平台 (Win/Linux/macOS) 通用.
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IS_WINDOWS = platform.system() == "Windows"
PY = sys.executable


def _run(cmd: list[str], **kwargs) -> int:
    """执行子命令, 透传 PYTHONIOENCODING 等环境变量."""
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.call(cmd, cwd=str(ROOT), env=env, **kwargs)


# ── 任务定义 ─────────────────────────────────────────────
TASKS: dict[str, str] = {
    # 安装
    "install": "安装主依赖 (等价 pip install -e .)",
    "install-all": "安装所有依赖 (main + dev + help + browser + playwright)",
    "install-dev": "安装开发依赖 (main + dev)",
    "install-browser": "安装浏览器自动化依赖",
    "install-help": "安装交互式帮助依赖",
    "install-playwright": "安装 Playwright + 浏览器二进制",
    # 开发
    "dev": "启动 App Server (开发模式)",
    "server": "dev 别名",
    "setup": "运行 API Key 配置向导",
    "status": "显示 API Key 和模型配置状态",
    "scan": "扫描代码库 (默认 pycoder/)",
    "evolve": "启动自我进化",
    # 测试
    "test": "运行全部测试",
    "test-fast": "仅运行快速测试",
    # 质量
    "lint": "运行 ruff + bandit",
    "format": "格式化代码 (black + isort)",
    "type-check": "mypy 类型检查",
    "security": "安全扫描 (bandit + safety)",
    # 文档
    "docs": "检查 README 文档一致性",
    # 前端
    "electron": "启动 Electron 桌面 IDE",
    # 清理
    "clean": "清理所有临时文件",
    "clean-pyc": "清理 .pyc / __pycache__",
    "clean-cache": "清理 Electron / pytest 缓存",
    # 一键
    "all": "全量: 安装所有 + lint + 测试",
}


def cmd_install(_args: argparse.Namespace) -> int:
    return _run([PY, "-m", "pip", "install", "-e", "."])


def cmd_install_all(_args: argparse.Namespace) -> int:
    rc = _run([PY, "-m", "pip", "install", "-r", "requirements-all.txt"])
    if rc != 0:
        return rc
    return _run([PY, "-m", "pip", "install", "-e", "."])


def cmd_install_dev(_args: argparse.Namespace) -> int:
    return _run([PY, "-m", "pip", "install", "-e", ".[dev]"])


def cmd_install_browser(_args: argparse.Namespace) -> int:
    return _run([PY, "-m", "pip", "install", "-e", ".[browser]"])


def cmd_install_help(_args: argparse.Namespace) -> int:
    return _run([PY, "-m", "pip", "install", "-e", ".[help]"])


def cmd_install_playwright(_args: argparse.Namespace) -> int:
    rc = _run([PY, "-m", "pip", "install", "-e", ".[playwright]"])
    if rc != 0:
        return rc
    return _run([PY, "-m", "playwright", "install"])


def cmd_dev(_args: argparse.Namespace) -> int:
    return _run([PY, "-m", "pycoder", "--server"])


cmd_server = cmd_dev


def cmd_setup(_args: argparse.Namespace) -> int:
    return _run([PY, "-m", "pycoder", "--setup"])


def cmd_status(_args: argparse.Namespace) -> int:
    return _run([PY, "-m", "pycoder", "--status"])


def cmd_scan(_args: argparse.Namespace) -> int:
    return _run([PY, "-m", "pycoder", "--scan", "pycoder/"])


def cmd_evolve(_args: argparse.Namespace) -> int:
    return _run([PY, "-m", "pycoder", "--evolve"])


def cmd_test(_args: argparse.Namespace) -> int:
    return _run([PY, "-m", "pytest"])


def cmd_test_fast(_args: argparse.Namespace) -> int:
    return _run([PY, "-m", "pytest", "-m", "not slow", "-x"])


def cmd_lint(_args: argparse.Namespace) -> int:
    rc = _run([PY, "-m", "ruff", "check", "pycoder/"])
    if rc != 0:
        return rc
    return _run([PY, "-m", "bandit", "-r", "pycoder/", "-q"])


def cmd_format(_args: argparse.Namespace) -> int:
    rc = _run([PY, "-m", "black", "pycoder/", "tests/"])
    if rc != 0:
        return rc
    return _run([PY, "-m", "isort", "pycoder/", "tests/"])


def cmd_type_check(_args: argparse.Namespace) -> int:
    return _run([PY, "-m", "mypy", "pycoder/"])


def cmd_security(_args: argparse.Namespace) -> int:
    rc = _run([PY, "-m", "bandit", "-r", "pycoder/"])
    if rc != 0:
        return rc
    return _run([PY, "-m", "safety", "check"])


def cmd_docs(_args: argparse.Namespace) -> int:
    return _run([PY, "scripts/check_readme_consistency.py"])


def cmd_electron(_args: argparse.Namespace) -> int:
    electron_dir = ROOT / "pycoder" / "electron"
    if not (electron_dir / "node_modules").exists():
        rc = _run(["npm", "install"], cwd=str(electron_dir))
        if rc != 0:
            return rc
    return _run(["npx", "electron", "."], cwd=str(electron_dir))


def cmd_clean(_args: argparse.Namespace) -> int:
    cmd_clean_pyc(_args)
    cmd_clean_cache(_args)
    return 0


def cmd_clean_pyc(_args: argparse.Namespace) -> int:
    """清理 __pycache__ / .pyc."""
    import glob

    for p in glob.glob(str(ROOT / "**" / "__pycache__"), recursive=True):
        if ".venv" in p or "node_modules" in p:
            continue
        shutil.rmtree(p, ignore_errors=True)
    for p in glob.glob(str(ROOT / "**" / "*.pyc"), recursive=True):
        if ".venv" in p or "node_modules" in p:
            continue
        try:
            os.remove(p)
        except OSError:
            pass
    return 0


def cmd_clean_cache(_args: argparse.Namespace) -> int:
    """清理 .pytest_cache / .mypy_cache / .ruff_cache / Electron cache."""
    for d in (".pytest_cache", ".mypy_cache", ".ruff_cache"):
        shutil.rmtree(ROOT / d, ignore_errors=True)
    # Electron cache
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        cache_dir = Path(appdata) / "pycoder"
        if cache_dir.exists():
            for sub in ("Cache", "GPUCache", "Code Cache", "ShaderCache",
                        "DawnGraphiteCache", "DawnWebGPUCache"):
                shutil.rmtree(cache_dir / sub, ignore_errors=True)
    return 0


def cmd_all(_args: argparse.Namespace) -> int:
    """全量: install-all + lint + test."""
    for name in ("install-all", "lint", "test"):
        fn = HANDLERS.get(name)
        if fn is None:
            print(f"[WARN] task {name} not implemented")
            continue
        print(f"\n>>> {name}")
        rc = fn(_args)
        if rc != 0:
            return rc
    return 0


HANDLERS: dict[str, callable] = {
    "install": cmd_install,
    "install-all": cmd_install_all,
    "install-dev": cmd_install_dev,
    "install-browser": cmd_install_browser,
    "install-help": cmd_install_help,
    "install-playwright": cmd_install_playwright,
    "dev": cmd_dev,
    "server": cmd_server,
    "setup": cmd_setup,
    "status": cmd_status,
    "scan": cmd_scan,
    "evolve": cmd_evolve,
    "test": cmd_test,
    "test-fast": cmd_test_fast,
    "lint": cmd_lint,
    "format": cmd_format,
    "type-check": cmd_type_check,
    "security": cmd_security,
    "docs": cmd_docs,
    "electron": cmd_electron,
    "clean": cmd_clean,
    "clean-pyc": cmd_clean_pyc,
    "clean-cache": cmd_clean_cache,
    "all": cmd_all,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PyCoder 跨平台任务运行器 (替代 make, Windows 友好)",
    )
    parser.add_argument(
        "task",
        nargs="?",
        default="help",
        help=f"任务名, 可选: {', '.join(sorted(TASKS))}",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出所有可用任务",
    )
    args, unknown = parser.parse_known_args()

    if args.list or args.task == "help":
        print("=" * 70)
        print(f"  PyCoder 任务运行器 — 平台: {platform.system()} {platform.release()}")
        print("=" * 70)
        print()
        max_name = max(len(n) for n in TASKS) + 2
        for name, desc in sorted(TASKS.items()):
            print(f"  {name:<{max_name}}  {desc}")
        print()
        print("  用法: python scripts/run.py <task>")
        print("=" * 70)
        return 0

    if args.task not in HANDLERS:
        print(f"[ERROR] 未知任务: {args.task}")
        print(f"可用任务: {', '.join(sorted(HANDLERS))}")
        return 1

    print(f">>> {args.task}")
    return HANDLERS[args.task](args)


if __name__ == "__main__":
    sys.exit(main())
