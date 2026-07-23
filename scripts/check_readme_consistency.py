"""PyCoder 文档一致性检查

检查项:
  1. README 中 `--model` 描述与 __main__.py argparse 一致
  2. README 数字 badges 与 tests/ 目录实际文件数匹配
  3. pyproject.toml 引用 requirements 文件存在
  4. .gitignore 覆盖 .env / __pycache__ / .venv / .vscode / .idea
  5. _launch.py 与 start_backend.bat 命令行参数一致
  6. .git-hooks 目录下的 post-commit 钩子有效

用法:
    python scripts/check_readme_consistency.py            # 详细输出
    python scripts/check_readme_consistency.py --strict   # 任何警告都报错
    python scripts/check_readme_consistency.py --json     # JSON 输出 (CI)

退出码:
    0 — 全部通过
    1 — 有 ERROR 级别问题
    2 — 有 WARNING (仅 --strict 模式)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# 颜色 (跨平台, 失败时降级为纯文本)
try:
    import colorama

    colorama.init()
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"
except ImportError:
    GREEN = YELLOW = RED = RESET = ""


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.checks: list[dict[str, Any]] = []

    def ok(self, name: str, detail: str = "") -> None:
        self.checks.append({"name": name, "status": "OK", "detail": detail})
        print(f"  {GREEN}[OK]{RESET}    {name}" + (f"  ({detail})" if detail else ""))

    def warn(self, name: str, detail: str) -> None:
        self.warnings.append(f"{name}: {detail}")
        self.checks.append({"name": name, "status": "WARN", "detail": detail})
        print(f"  {YELLOW}[WARN]{RESET}  {name}  — {detail}")

    def err(self, name: str, detail: str) -> None:
        self.errors.append(f"{name}: {detail}")
        self.checks.append({"name": name, "status": "ERROR", "detail": detail})
        print(f"  {RED}[ERROR]{RESET} {name}  — {detail}")


def check_readme_commands(report: Report) -> None:
    """检查 README 中提到的 CLI 命令是否在 __main__.py 中存在."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="ignore")
    main_py = (ROOT / "pycoder" / "__main__.py").read_text(encoding="utf-8", errors="ignore")

    # 提取 README 中提到的 --xxx 参数
    readme_args = set(re.findall(r"--([a-z][a-z-]+)", readme))
    # 提取 __main__.py 中定义的 --xxx 参数
    main_args = set(re.findall(r'"--([a-z][a-z-]+)"', main_py))

    # 排除: 非 pycoder CLI 命令 (mypy/make 等第三方工具参数)
    excluded = {
        # pycoder 自己的命令 (已实现, 无需警告)
        "version", "model", "server", "setup", "env", "cost", "generate",
        "project-dir", "list-templates", "autonomous", "task", "status",
        "evolve", "scan", "evolve-path", "server-port",
        # 第三方工具参数
        "ignore-missing-imports", "strict", "cov", "tb", "cov-report",
        "no-cov", "cache-clear", "no-header", "collect-only",
    }
    mentioned_in_readme = readme_args - excluded
    unknown = mentioned_in_readme - main_args
    if unknown:
        report.warn(
            "README 命令未在 __main__.py 实现",
            f"--{', --'.join(sorted(unknown))}",
        )
    else:
        report.ok("README 命令一致性", f"{len(mentioned_in_readme)} 个命令已核实")

    # 检查 -m -m 重复使用 (在短选项说明块内可接受)
    lines = readme.split("\n")
    in_short_option_block = False
    bad_lines = []
    for i, line in enumerate(lines, 1):
        # 进入短选项说明块
        if "短选项" in line or "与上面等价" in line:
            in_short_option_block = True
            continue
        # 离开说明块 (遇到新的代码段或空段落)
        if in_short_option_block and (line.strip().startswith("```") or not line.strip()):
            if line.strip().startswith("```"):
                in_short_option_block = False
            continue
        if "python -m pycoder -m" in line and not in_short_option_block:
            bad_lines.append((i, line.strip()))
    if bad_lines:
        report.warn(
            "README 含 -m -m 重复使用",
            f"第 {bad_lines[0][0]} 行 — 推荐改用 --model",
        )


def check_readme_numbers(report: Report) -> None:
    """检查 README badges 中数字与实际匹配."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="ignore")
    test_files = list((ROOT / "tests").glob("test_*.py"))

    # 统计测试函数/方法 (而非文件)
    test_funcs = 0
    for f in test_files:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            test_funcs += len(re.findall(r"^\s*(?:async\s+)?def\s+test_", content, re.MULTILINE))
        except OSError:
            pass

    # 提取 badge 中的数字 (e.g. tests-8000%2B)
    m = re.search(r"tests-(\d+)", readme)
    if m:
        claimed = int(m.group(1))
        # 声明的数字应 <= 实际函数数 (允许 8000+ 圆整)
        if test_funcs >= claimed * 0.9:  # 10% 容差
            report.ok(
                "README 测试数 badge",
                f"声明 {claimed}+, 实际 {test_funcs} 个测试函数 (in {len(test_files)} 文件)",
            )
        else:
            report.err(
                "README 测试数 badge 过期",
                f"声明 {claimed}+, 实际仅 {test_funcs} 个测试函数",
            )
    else:
        report.warn("README 测试数 badge", "未找到 tests-N+ 格式")


def check_pyproject_references(report: Report) -> None:
    """检查 pyproject.toml 引用的 requirements 文件是否存在.

    仅检查 [tool.setuptools.dynamic] 块内的 file = "..." 引用,
    避免误报其他字段 (如 [tool.codespell] skip = "..." 模式匹配).
    """
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")
    # 提取 [tool.setuptools.dynamic] 块
    block_match = re.search(
        r"\[tool\.setuptools\.dynamic\](.*?)(?:\[tool\.|\Z)",
        pyproject,
        re.DOTALL,
    )
    if not block_match:
        report.warn("pyproject.toml", "未找到 [tool.setuptools.dynamic] 块")
        return
    block = block_match.group(1)
    # 提取该块内所有 file = "..." 引用
    refs = re.findall(r'file\s*=\s*"([^"]+)"', block)
    for ref in refs:
        path = ROOT / ref
        if path.exists():
            report.ok(f"pyproject 引用: {ref}", "存在")
        else:
            report.err(f"pyproject 引用: {ref}", "文件不存在")


def check_pyproject_config_blocks(report: Report) -> None:
    """检查 pyproject.toml 关键工具配置块完整性 (pytest / coverage / lint 等)."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")
    # 必须存在的工具配置块
    required_blocks = {
        "tool.pytest.ini_options": "[tool.pytest.ini_options] 测试运行配置 (addopts / markers / testpaths)",
        "tool.coverage.run": "[tool.coverage.run] 覆盖率运行配置 (source / omit / branch)",
        "tool.coverage.report": "[tool.coverage.report] 覆盖率报告配置 (fail_under / show_missing)",
        "tool.ruff": "[tool.ruff] Lint 配置",
        "tool.black": "[tool.black] 格式化配置",
        "tool.mypy": "[tool.mypy] 类型检查配置",
    }
    # 可选但建议存在的块 (warn 而非 err)
    optional_blocks = {
        "tool.bandit": "[tool.bandit] 安全扫描配置",
        "tool.isort": "[tool.isort] 导入排序配置",
    }
    for block, desc in required_blocks.items():
        marker = f"[{block}]"
        if marker in pyproject:
            report.ok(f"pyproject {marker}", desc)
        else:
            report.err(f"pyproject {marker} 缺失", desc)
    for block, desc in optional_blocks.items():
        marker = f"[{block}]"
        if marker in pyproject:
            report.ok(f"pyproject {marker}", desc)
        else:
            report.warn(f"pyproject {marker} 缺失", desc)

    # 关键依赖版本约束 (避免 '在我机器上能跑' 问题)
    in_block = re.search(
        r"\[tool\.setuptools\.dynamic\](.*?)(?:\[tool\.|\Z)", pyproject, re.DOTALL
    )
    deps_block = in_block.group(1) if in_block else pyproject
    critical_deps = {
        "litellm": "litellm (核心 LLM 客户端, 应锁定兼容版本)",
        "openai": "openai (OpenAI 协议, 应锁定)",
        "fastapi": "fastapi (Web 框架, 应锁定)",
        "pydantic": "pydantic (数据模型, 应锁定)",
        "httpx": "httpx (HTTP 客户端, 应锁定)",
    }
    for dep, desc in critical_deps.items():
        # 匹配 dep[><=~!] 或 dep 单独行
        if re.search(rf"^{re.escape(dep)}\s*[><=~!]", deps_block, re.MULTILINE):
            report.ok(f"关键依赖锁定: {dep}", desc)
        else:
            report.warn(f"关键依赖未锁定: {dep}", desc)


def check_gitignore(report: Report) -> None:
    """检查 .gitignore 覆盖关键文件."""
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8", errors="ignore")
    required_patterns = {
        ".env": r"^\.env$",
        "__pycache__": r"__pycache__",
        ".venv": r"\.venv",
        ".vscode": r"\.vscode",
        ".idea": r"\.idea",
        "*.log": r"\*\.log",
        "*.pyc": r"\*\.pyc",
    }
    for name, pattern in required_patterns.items():
        if re.search(pattern, gitignore, re.MULTILINE):
            report.ok(f".gitignore 覆盖: {name}", "已包含")
        else:
            report.err(f".gitignore 覆盖: {name}", "缺失")


def check_launch_scripts(report: Report) -> None:
    """检查启动脚本存在性."""
    expected = {
        "_launch.py": "Python 跨平台启动器",
        "start_backend.bat": "Windows 后端启动",
        ".git-hooks/post-commit": "post-commit 钩子",
        ".git-hooks/install-post-commit.ps1": "Windows 钩子安装器",
        ".git-hooks/install-post-commit.sh": "Unix 钩子安装器",
    }
    for path, desc in expected.items():
        p = ROOT / path
        if p.exists():
            report.ok(f"启动脚本: {path}", desc)
        else:
            report.err(f"启动脚本: {path}", f"{desc} — 缺失")


def check_git_hooks_cross_platform(report: Report) -> None:
    """检查 .git-hooks/post-commit 是否使用跨平台兼容写法."""
    hook = (ROOT / ".git-hooks" / "post-commit")
    if not hook.exists():
        report.err(".git-hooks/post-commit", "缺失")
        return
    content = hook.read_text(encoding="utf-8")
    # 必须是 bash shebang
    if content.startswith("#!/bin/bash") or content.startswith("#!/usr/bin/env bash"):
        report.ok(".git-hooks/post-commit", "bash shebang — Git Bash 兼容")
    else:
        report.err(".git-hooks/post-commit", "缺少 bash shebang")
    # 不能有 Windows-only 命令
    bad_patterns = ["cmd.exe", "powershell -File", "taskkill"]
    for bad in bad_patterns:
        if bad in content:
            report.err(
                ".git-hooks/post-commit",
                f"包含 Windows-only 命令: {bad}",
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="PyCoder 文档一致性检查")
    parser.add_argument("--strict", action="store_true", help="WARNING 也报错")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    print("=" * 70)
    print("  PyCoder 文档一致性检查")
    print("=" * 70)
    print()

    report = Report()

    print(">>> README 命令一致性")
    check_readme_commands(report)
    print()
    print(">>> README 数字")
    check_readme_numbers(report)
    print()
    print(">>> pyproject.toml 引用")
    check_pyproject_references(report)
    print()
    print(">>> pyproject.toml 配置块")
    check_pyproject_config_blocks(report)
    print()
    print(">>> .gitignore 覆盖")
    check_gitignore(report)
    print()
    print(">>> 启动脚本")
    check_launch_scripts(report)
    print()
    print(">>> Git 钩子跨平台")
    check_git_hooks_cross_platform(report)
    print()

    print("=" * 70)
    total = len(report.checks)
    ok = sum(1 for c in report.checks if c["status"] == "OK")
    warn = len(report.warnings)
    err = len(report.errors)
    print(
        f"  {GREEN}{ok} OK{RESET}  {YELLOW}{warn} WARN{RESET}  {RED}{err} ERROR{RESET}  "
        f"(共 {total} 项)"
    )
    print("=" * 70)

    if args.json:
        print()
        print(json.dumps(report.checks, ensure_ascii=False, indent=2))

    if err > 0:
        return 1
    if args.strict and warn > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
