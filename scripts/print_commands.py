"""PyCoder 命令索引 — 跨平台单一入口

用法:
    python scripts/print_commands.py            # 人类可读
    python scripts/print_commands.py --json     # JSON 输出
    python scripts/print_commands.py --markdown # Markdown 格式 (用于 README)

不依赖任何第三方包, 纯标准库实现, 保证所有平台可用.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

# 添加项目根到 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ============================================================================
# 命令清单 — 单一来源真相 (Single Source of Truth)
# ============================================================================
COMMANDS: list[dict[str, Any]] = [
    {
        "category": "启动",
        "name": "python -m pycoder --server",
        "short": "python -m pycoder",
        "description": "启动 App Server (FastAPI + WebSocket), 默认端口 8423",
        "platform": "all",
    },
    {
        "category": "启动",
        "name": "python -m pycoder --server --server-port 9000",
        "short": "--server-port",
        "description": "指定端口启动",
        "platform": "all",
    },
    {
        "category": "启动",
        "name": "python -m pycoder --model deepseek-chat",
        "short": "-m MODEL",
        "description": "指定 AI 模型",
        "platform": "all",
    },
    {
        "category": "启动",
        "name": "python _launch.py --desktop",
        "short": "_launch.py",
        "description": "一键启动后端 + Electron 桌面 IDE (推荐)",
        "platform": "all",
    },
    {
        "category": "启动",
        "name": "cd pycoder/electron && npx electron .",
        "short": "npx electron",
        "description": "仅启动 Electron 桌面 IDE (后端需独立启动)",
        "platform": "all",
    },
    {
        "category": "配置",
        "name": "python -m pycoder --setup",
        "short": "--setup",
        "description": "运行 API Key 配置向导",
        "platform": "all",
    },
    {
        "category": "配置",
        "name": "python -m pycoder --status",
        "short": "--status",
        "description": "显示 API Key 和模型配置状态",
        "platform": "all",
    },
    {
        "category": "配置",
        "name": "python -m pycoder --env",
        "short": "--env",
        "description": "显示当前 Python 环境信息",
        "platform": "all",
    },
    {
        "category": "诊断",
        "name": "python -m pycoder --cost",
        "short": "--cost",
        "description": "显示 LLM 费用报告",
        "platform": "all",
    },
    {
        "category": "诊断",
        "name": "python -m pycoder --scan pycoder/",
        "short": "--scan PATH",
        "description": "扫描代码库并生成问题报告",
        "platform": "all",
    },
    {
        "category": "诊断",
        "name": "python -m pycoder --evolve",
        "short": "--evolve",
        "description": "启动自我进化模式 (扫描 → 分析 → 修复 → 测试)",
        "platform": "all",
    },
    {
        "category": "生成",
        "name": "python -m pycoder --generate 'FastAPI 用户管理系统'",
        "short": "-g DESC",
        "description": "一键生成完整项目",
        "platform": "all",
    },
    {
        "category": "生成",
        "name": "python -m pycoder --list-templates",
        "short": "--list-templates",
        "description": "列出所有可用项目模板",
        "platform": "all",
    },
    {
        "category": "自主",
        "name": "python -m pycoder --autonomous --task '做博客API'",
        "short": "-a -t DESC",
        "description": "全自主开发模式 (配合 --task 使用)",
        "platform": "all",
    },
    {
        "category": "版本",
        "name": "python -m pycoder --version",
        "short": "-V",
        "description": "显示版本号",
        "platform": "all",
    },
    {
        "category": "Git",
        "name": "python __git_commit_push.py 'fix: 说明'",
        "short": "__git_commit_push.py",
        "description": "一键提交 + 推送 (AI 助手标准操作)",
        "platform": "all",
    },
    {
        "category": "Windows 专属",
        "name": "start_backend.bat",
        "short": "start_backend.bat",
        "description": "Windows 批处理启动后端 (双击运行)",
        "platform": "windows",
    },
    {
        "category": "Windows 专属",
        "name": "python _cleanup_electron_cache.py",
        "short": "_cleanup_electron_cache.py",
        "description": "清理 Electron 缓存 (启动失败时使用)",
        "platform": "all",
    },
    {
        "category": "macOS/Linux 专属",
        "name": "./.git-hooks/install-post-commit.sh",
        "short": "install-post-commit.sh",
        "description": "安装 post-commit 自动推送钩子",
        "platform": "unix",
    },
    {
        "category": "Windows 专属",
        "name": "powershell .git-hooks/install-post-commit.ps1",
        "short": "install-post-commit.ps1",
        "description": "安装 post-commit 自动推送钩子",
        "platform": "windows",
    },
]


def filter_by_platform(commands: list[dict], current_platform: str) -> list[dict]:
    """过滤掉不适用当前平台的命令."""
    plat_map = {"Windows": "windows", "Darwin": "macos", "Linux": "unix"}
    current = plat_map.get(current_platform, "all")
    result = []
    for c in commands:
        if c["platform"] == "all" or c["platform"] == current:
            result.append(c)
    return result


def print_human(commands: list[dict]) -> None:
    """人类可读输出."""
    print("=" * 70)
    print(f"  PyCoder 命令索引 — 平台: {platform.system()} {platform.release()}")
    print("=" * 70)
    print()

    # 按 category 分组
    by_cat: dict[str, list[dict]] = {}
    for c in commands:
        by_cat.setdefault(c["category"], []).append(c)

    for cat in ["启动", "配置", "生成", "自主", "诊断", "Git", "Windows 专属", "macOS/Linux 专属"]:
        if cat not in by_cat:
            continue
        print(f"## {cat}")
        print("-" * 70)
        for c in by_cat[cat]:
            print(f"  $ {c['name']}")
            print(f"    [{c['short']}]  {c['description']}")
            print()
    print("=" * 70)
    print(f"  共 {len(commands)} 条命令")
    print("  完整文档: docs/LAUNCH.md")
    print("=" * 70)


def print_markdown(commands: list[dict]) -> None:
    """Markdown 表格输出 (用于 README)."""
    print("| 命令 | 短选项 | 平台 | 说明 |")
    print("|------|--------|------|------|")
    for c in commands:
        plat_short = {"all": "全平台", "windows": "Windows", "unix": "macOS/Linux", "macos": "macOS"}.get(c["platform"], c["platform"])
        cmd = c["name"].replace("|", "\\|")
        desc = c["description"].replace("|", "\\|")
        print(f"| `{cmd}` | `{c['short']}` | {plat_short} | {desc} |")


def print_json(commands: list[dict]) -> None:
    """JSON 输出."""
    print(json.dumps(commands, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="PyCoder 命令索引")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    parser.add_argument("--markdown", action="store_true", help="Markdown 表格输出")
    parser.add_argument("--all-platforms", action="store_true", help="包含所有平台命令 (默认过滤)")
    args = parser.parse_args()

    if args.all_platforms:
        cmds = COMMANDS
    else:
        cmds = filter_by_platform(COMMANDS, platform.system())

    if args.json:
        print_json(cmds)
    elif args.markdown:
        print_markdown(cmds)
    else:
        print_human(cmds)

    return 0


if __name__ == "__main__":
    sys.exit(main())
