#!/usr/bin/env python3
"""gh_permissions CLI 入口点 — 命令行权限检查工具。

使用方式:
    # CI 风格报告 (替代 workflow YAML 中的内联 shell 脚本)
    python -m gh_permissions --check-only --format ci --scopes repo workflow

    # JSON 输出 (CI/CD 解析)
    python -m gh_permissions --check-only --format json --scopes repo workflow

    # 带自动刷新的完整检查
    python -m gh_permissions --scopes repo workflow --max-retries 2

    # 非交互模式 (CI 环境)
    python -m gh_permissions --check-only --no-interactive --format ci
"""

from __future__ import annotations

import argparse
import sys
from gh_permissions.checker import GitHubPermissionChecker, setup_logging
from gh_permissions.models import PermissionResult
from gh_permissions.reporter import ReportFormatter


def create_parser() -> argparse.ArgumentParser:
    """创建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="gh_permissions",
        description="GitHub CLI 权限检查工具 — 验证 token scope、自动刷新、生成 CI 报告",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
输出格式:
  ci     CI 风格报告 (含耗时、scope 详情、box drawing 边框)
  json   JSON 格式 (CI/CD 解析友好)
  human  人类可读摘要 (默认)

退出码:
  0  权限检查通过
  1  通用错误 (参数错误、gh CLI 未安装)
  2  认证错误 (未认证 / token 无效)
  3  权限不足 (缺失 scope, 刷新后仍未补充)
""",
    )

    parser.add_argument(
        "--scopes",
        nargs="+",
        default=["repo", "workflow"],
        metavar="SCOPE",
        help="必需的 token scope (默认: repo workflow)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        metavar="N",
        help="刷新失败后的最大重试次数 (默认: 2)",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=2.0,
        metavar="SECONDS",
        help="重试之间的延迟秒数 (默认: 2.0)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="仅检查不刷新 (CI 环境推荐)",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="非交互模式 (禁止 input 提示, CI 环境)",
    )
    parser.add_argument(
        "--format",
        choices=["ci", "json", "human"],
        default="human",
        help="输出格式 (默认: human)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="详细日志输出 (DEBUG 级别)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="gh_permissions 1.0.0",
    )

    return parser


def run(args: argparse.Namespace) -> int:
    """执行权限检查。

    Args:
        args: 已解析的命令行参数

    Returns:
        int: 退出码 (0=通过, 1=通用错误, 2=认证错误, 3=权限不足)
    """
    setup_logging(args.verbose)

    checker = GitHubPermissionChecker(
        required_scopes=args.scopes,
        max_retries=0 if args.check_only else args.max_retries,
        interactive=not args.no_interactive,
        retry_delay=args.retry_delay,
    )

    # 执行检查
    if args.check_only:
        result = checker.check()
    else:
        result = checker.check_with_retry()

    # 输出报告
    ReportFormatter.print_report(result, args.format)

    # 返回退出码
    if result.ok:
        return 0
    if not result.authenticated:
        return 2
    if result.missing_scopes:
        return 3
    return 1


def main() -> None:
    """CLI 主入口。"""
    parser = create_parser()
    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
