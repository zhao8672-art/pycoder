#!/usr/bin/env python3
"""GitHub CLI 权限检查模块 — 可复用的 token scope 验证与自动刷新工具。

功能:
  - 检查 gh CLI 是否安装并已认证
  - 解析 token scope, 验证必需权限 (repo, workflow 等)
  - 验证 token 有效性 (gh api user)
  - 自动刷新缺失 scope (gh auth refresh -s <missing>)
  - 带重试的权限检查流程 (可配置最大重试次数)
  - 支持交互式 / 非交互式模式 (CI/CD)
  - 结构化结果 (PermissionResult dataclass)
  - 详细日志输出 (logging 模块)

用法 (作为模块导入):
  ```python
  from gh_permissions import GitHubPermissionChecker

  checker = GitHubPermissionChecker(
      required_scopes=["repo", "workflow"],
      max_retries=2,
      interactive=True,
  )
  result = checker.check_with_retry()
  if not result.ok:
      print(f"权限不足: {result.missing_scopes}")
      sys.exit(1)
  ```

用法 (命令行直接运行):
  ```bash
  # 检查默认 scope (repo + workflow)
  python scripts/gh_permissions.py

  # 指定 scope + 非交互模式 + verbose
  python scripts/gh_permissions.py --scopes repo workflow read:org --no-interactive --verbose

  # 仅检查不刷新
  python scripts/gh_permissions.py --check-only

  # 输出 JSON 结果 (适合 CI/CD 解析)
  python scripts/gh_permissions.py --json
  ```

退出码:
  0  权限检查通过
  1  通用错误 (gh CLI 未安装、参数错误)
  2  认证错误 (未登录、token 无效)
  3  权限不足 (缺失 scope 且刷新失败/跳过)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ── 日志配置 ──────────────────────────────────────────────
logger = logging.getLogger("gh_permissions")


def setup_logging(verbose: bool = False) -> None:
    """配置日志格式和级别。"""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)5s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, stream=sys.stderr)


# ── 数据模型 ──────────────────────────────────────────────


@dataclass
class PermissionResult:
    """权限检查结果。

    Attributes:
        ok: 是否全部检查通过
        authenticated: gh CLI 是否已认证
        token_valid: token 是否有效 (API 调用成功)
        username: 当前认证的用户名 (token 无效时为 None)
        current_scopes: 当前 token 拥有的 scope 列表
        required_scopes: 本次检查要求的 scope 列表
        missing_scopes: 缺失的 scope 列表
        error: 错误信息 (检查失败时填充)
        refreshed: 是否执行过 scope 刷新
        refresh_attempts: 刷新尝试次数
    """

    ok: bool = False
    authenticated: bool = False
    token_valid: bool = False
    username: str | None = None
    current_scopes: list[str] = field(default_factory=list)
    required_scopes: list[str] = field(default_factory=list)
    missing_scopes: list[str] = field(default_factory=list)
    error: str | None = None
    refreshed: bool = False
    refresh_attempts: int = 0

    def to_dict(self) -> dict:
        """转为字典 (用于 JSON 输出)。"""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """转为 JSON 字符串。"""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ── 异常定义 ──────────────────────────────────────────────


class GitHubPermissionError(Exception):
    """GitHub 权限检查基础异常。"""


class GitHubCLINotFoundError(GitHubPermissionError):
    """gh CLI 未安装。"""


class GitHubAuthError(GitHubPermissionError):
    """gh CLI 未认证或 token 无效。"""


class GitHubScopeMissingError(GitHubPermissionError):
    """token 缺失必需 scope。"""

    def __init__(self, missing_scopes: list[str], current_scopes: list[str]) -> None:
        self.missing_scopes = missing_scopes
        self.current_scopes = current_scopes
        super().__init__(
            f"缺失 scope: {missing_scopes} (当前: {current_scopes})"
        )


# ── 核心检查器 ────────────────────────────────────────────


class GitHubPermissionChecker:
    """GitHub CLI 权限检查器。

    封装 gh CLI 的认证状态检查、token scope 验证和自动刷新逻辑,
    可在其他 CI 脚本中复用。

    Args:
        required_scopes: 必需的 token scope 列表 (默认 ["repo", "workflow"])
        max_retries: 刷新失败后的最大重试次数 (默认 2)
        interactive: 是否允许交互式操作 (gh auth refresh 需要浏览器)
        retry_delay: 重试之间的延迟秒数 (默认 2.0)
        repo: 目标仓库 (owner/repo 格式, 用于权限验证, 可选)
    """

    # gh CLI 常用 scope 说明 (用于日志输出)
    SCOPE_DESCRIPTIONS: dict[str, str] = {
        "repo": "仓库访问、分支保护 API、读取 workflow 状态",
        "workflow": "触发 workflow (gh workflow run, 需 workflow_dispatch)",
        "read:org": "读取组织信息",
        "admin:org": "组织管理权限",
        "gist": "创建 Gist",
        "delete_repo": "删除仓库",
    }

    def __init__(
        self,
        required_scopes: list[str] | None = None,
        max_retries: int = 2,
        interactive: bool = True,
        retry_delay: float = 2.0,
        repo: str | None = None,
    ) -> None:
        self.required_scopes = required_scopes or ["repo", "workflow"]
        self.max_retries = max_retries
        self.interactive = interactive
        self.retry_delay = retry_delay
        self.repo = repo

    # ── 公共方法 ──────────────────────────────────────────

    def check(self) -> PermissionResult:
        """执行一次性权限检查 (不刷新)。

        Returns:
            PermissionResult: 检查结果
        """
        result = PermissionResult(required_scopes=list(self.required_scopes))

        # 1. 检查 gh CLI 是否安装
        if not self._is_gh_installed():
            result.error = "gh CLI 未安装"
            logger.error("gh CLI 未安装, 请先安装: https://cli.github.com/")
            return result

        # 2. 检查认证状态
        auth_status = self._get_auth_status()
        if not auth_status:
            result.error = "gh CLI 未认证"
            logger.error("gh CLI 未认证, 请运行: gh auth login")
            return result

        result.authenticated = True
        logger.debug("gh CLI 已认证")

        # 3. 解析 token scope
        result.current_scopes = self._parse_scopes(auth_status)
        logger.debug(f"当前 token scope: {result.current_scopes}")

        # 4. 验证 token 有效性
        username = self._validate_token()
        if username is None:
            result.error = "token 无效或已过期"
            logger.error("token 无效或已过期, 请重新认证: gh auth login")
            return result

        result.token_valid = True
        result.username = username
        logger.debug(f"token 有效, 用户: {username}")

        # 5. 检查必需 scope
        result.missing_scopes = [
            s for s in self.required_scopes if s not in result.current_scopes
        ]

        if result.missing_scopes:
            result.error = f"缺失 scope: {result.missing_scopes}"
            logger.warning(f"缺失 token scope: {result.missing_scopes}")
            self._log_scope_details(result.missing_scopes, result.current_scopes)
        else:
            result.ok = True
            logger.info(
                f"权限检查通过 (scope: {', '.join(result.current_scopes)})"
            )

        return result

    def refresh(self, missing_scopes: list[str]) -> bool:
        """尝试通过 gh auth refresh 补充缺失的 token scope。

        Args:
            missing_scopes: 缺失的 scope 列表

        Returns:
            bool: 刷新是否成功
        """
        if not missing_scopes:
            return True

        logger.warning(f"检测到缺失 scope: {missing_scopes}")
        self._log_scope_descriptions(missing_scopes)

        if not self.interactive:
            logger.error("--no-interactive 模式下无法交互式刷新权限")
            logger.info(f"请手动执行: gh auth refresh -s {' '.join(missing_scopes)}")
            return False

        # 交互式确认
        logger.info(f"即将执行: gh auth refresh -s {' '.join(missing_scopes)}")
        print("  这会打开浏览器请求你重新授权 GitHub CLI, 补充缺失的 scope。")
        try:
            confirm = input("确认刷新权限? (y/N): ").strip().lower()
        except EOFError:
            logger.warning("无法读取用户输入 (非交互式环境)")
            logger.info(f"请手动执行: gh auth refresh -s {' '.join(missing_scopes)}")
            return False

        if confirm != "y":
            logger.warning("用户取消权限刷新")
            logger.info(
                f"请手动执行: gh auth refresh -s {' '.join(missing_scopes)}"
            )
            return False

        # 执行刷新
        logger.info(f"正在刷新 token scope (添加: {' '.join(missing_scopes)})...")
        try:
            proc = subprocess.run(
                ["gh", "auth", "refresh", "-s", *missing_scopes],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                logger.debug(f"refresh 返回码: {proc.returncode}")
                logger.debug(f"refresh stderr: {proc.stderr[:300]}")
        except subprocess.TimeoutExpired:
            logger.error("权限刷新超时 (120s)")
            return False
        except FileNotFoundError:
            logger.error("gh CLI 不可用")
            return False

        # 重新检查 scope (不信任返回码, 以实际状态为准)
        auth_status = self._get_auth_status()
        if not auth_status:
            logger.error("刷新后无法获取认证状态")
            return False

        new_scopes = self._parse_scopes(auth_status)
        logger.debug(f"刷新后 scope: {new_scopes}")

        all_present = all(s in new_scopes for s in missing_scopes)
        if all_present:
            logger.info(f"✅ 权限刷新成功, 已补充 scope: {missing_scopes}")
            return True

        logger.error("权限刷新后仍缺失部分 scope")
        still_missing = [s for s in missing_scopes if s not in new_scopes]
        logger.warning(f"仍缺失: {still_missing}")
        logger.warning(f"当前 scope: {new_scopes}")
        logger.info(
            f"请手动执行: gh auth refresh -s {' '.join(still_missing)}"
        )
        return False

    def check_with_retry(self) -> PermissionResult:
        """带重试的权限检查 (检查 → 刷新 → 重新检查)。

        Returns:
            PermissionResult: 最终检查结果
        """
        result = PermissionResult(required_scopes=list(self.required_scopes))
        total_attempts = self.max_retries + 1  # 初始检查 + 重试次数
        was_refreshed = False  # 跨迭代追踪刷新状态

        for attempt in range(1, total_attempts + 1):
            logger.debug(f"权限检查 [尝试 {attempt}/{total_attempts}]...")

            result = self.check()
            result.refresh_attempts = attempt - 1
            result.refreshed = was_refreshed  # 继承前序刷新状态

            if result.ok:
                return result

            # 未认证 — 无法通过 refresh 解决
            if not result.authenticated:
                logger.error("gh CLI 未认证或 token 无效, 需要重新登录")
                logger.info(
                    f"请执行: gh auth login -s {' '.join(self.required_scopes)}"
                )
                return result

            # 缺失 scope — 尝试刷新
            if result.missing_scopes and attempt < total_attempts:
                logger.info(
                    f"尝试刷新缺失 scope (第 {attempt}/{self.max_retries} 次)..."
                )
                if self.refresh(result.missing_scopes):
                    was_refreshed = True
                    # 刷新成功, 循环回去重新检查
                    continue
                # 刷新失败
                if attempt < self.max_retries:
                    logger.warning(
                        f"刷新失败, {self.retry_delay}s 后重试..."
                    )
                    time.sleep(self.retry_delay)
            elif result.missing_scopes and attempt == total_attempts:
                # 最后一次尝试
                logger.error(
                    f"权限检查失败, 已达最大重试次数 ({self.max_retries})"
                )
                logger.info(
                    f"请手动执行: gh auth refresh -s {' '.join(self.required_scopes)}"
                )
                logger.info(
                    f"或重新登录: gh auth login -s {' '.join(self.required_scopes)}"
                )

        return result

    # ── 内部方法 ──────────────────────────────────────────

    def _is_gh_installed(self) -> bool:
        """检查 gh CLI 是否安装。"""
        gh_path = shutil.which("gh")
        if gh_path:
            logger.debug(f"gh CLI 路径: {gh_path}")
            return True
        return False

    def _get_auth_status(self) -> str:
        """获取 gh auth status 输出。

        Returns:
            str: auth status 输出 (未认证时返回空字符串)
        """
        try:
            proc = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            # gh auth status 在已认证时返回 0, 未认证时返回非 0
            # 但 stderr 也包含有用信息
            output = proc.stdout + proc.stderr
            if "Logged in" in output:
                return output
            return ""
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""

    def _parse_scopes(self, auth_status: str) -> list[str]:
        """从 gh auth status 输出中解析 token scope。

        gh auth status 输出格式:
            Token scopes: 'repo', 'read:org', 'workflow'

        Args:
            auth_status: gh auth status 的完整输出

        Returns:
            list[str]: scope 列表
        """
        # 匹配 "Token scopes: 'repo', 'workflow'" 格式
        match = re.search(r"Token scopes:\s*(.+)", auth_status, re.IGNORECASE)
        if not match:
            logger.debug("未找到 Token scopes 行")
            return []

        raw_scopes = match.group(1)
        # 移除引号和空格, 按逗号分割
        scopes = [s.strip().strip("'\"") for s in raw_scopes.split(",")]
        return [s for s in scopes if s]

    def _validate_token(self) -> str | None:
        """通过 gh api user 验证 token 有效性。

        Returns:
            str | None: 用户名 (token 无效时返回 None)
        """
        try:
            proc = subprocess.run(
                ["gh", "api", "user", "--jq", ".login"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                username = proc.stdout.strip()
                # 排除错误响应
                if "Bad credentials" not in username and "401" not in username:
                    return username
            logger.debug(f"token 验证失败: rc={proc.returncode}, stderr={proc.stderr[:200]}")
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def _log_scope_details(
        self, missing: list[str], current: list[str]
    ) -> None:
        """打印 scope 缺失详情。"""
        logger.warning(f"当前 scope: {current if current else '(无)'}")
        for scope in missing:
            desc = self.SCOPE_DESCRIPTIONS.get(scope, "未知用途")
            logger.warning(f"  缺失: {scope} — {desc}")

    def _log_scope_descriptions(self, scopes: list[str]) -> None:
        """打印 scope 用途说明。"""
        print("  这些权限是脚本运行的必需条件:")
        for scope in scopes:
            desc = self.SCOPE_DESCRIPTIONS.get(scope, "未知用途")
            print(f"    {scope:<12} — {desc}")


# ── 便捷函数 ──────────────────────────────────────────────


def check_permissions(
    required_scopes: list[str] | None = None,
    max_retries: int = 2,
    interactive: bool = True,
    verbose: bool = False,
) -> PermissionResult:
    """一次性权限检查便捷函数。

    Args:
        required_scopes: 必需的 scope 列表 (默认 ["repo", "workflow"])
        max_retries: 最大重试次数
        interactive: 是否允许交互式操作
        verbose: 是否输出详细日志

    Returns:
        PermissionResult: 检查结果
    """
    setup_logging(verbose)
    checker = GitHubPermissionChecker(
        required_scopes=required_scopes,
        max_retries=max_retries,
        interactive=interactive,
    )
    return checker.check_with_retry()


# ── CLI 入口 ──────────────────────────────────────────────


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description="GitHub CLI 权限检查工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 检查默认 scope (repo + workflow)
  python scripts/gh_permissions.py

  # 指定 scope + 非交互模式
  python scripts/gh_permissions.py --scopes repo workflow read:org --no-interactive

  # 仅检查不刷新
  python scripts/gh_permissions.py --check-only

  # 输出 JSON 结果 (适合 CI/CD)
  python scripts/gh_permissions.py --json

  # 在其他 Python 脚本中复用:
  from gh_permissions import check_permissions
  result = check_permissions(["repo", "workflow"], interactive=False)
  if not result.ok:
      sys.exit(1)
        """,
    )
    parser.add_argument(
        "--scopes",
        nargs="+",
        default=["repo", "workflow"],
        help="必需的 token scope (默认: repo workflow)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="刷新失败后的最大重试次数 (默认: 2)",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="非交互模式 (不执行 gh auth refresh, 仅检查)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="仅检查不刷新 (等同于 --no-interactive --max-retries 0)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="输出 DEBUG 级别日志",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出 JSON 格式结果 (适合 CI/CD 解析)",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="目标仓库 (owner/repo, 可选, 用于额外权限验证)",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    # --check-only 覆盖
    interactive = not args.no_interactive and not args.check_only
    max_retries = 0 if args.check_only else args.max_retries

    checker = GitHubPermissionChecker(
        required_scopes=args.scopes,
        max_retries=max_retries,
        interactive=interactive,
        repo=args.repo,
    )

    result = checker.check_with_retry()

    # JSON 输出模式
    if args.json:
        print(result.to_json())
    else:
        # 人类可读摘要
        print()
        print("=" * 55)
        print("  GitHub CLI 权限检查结果")
        print("=" * 55)
        print(f"  通过:           {'✅' if result.ok else '❌'}")
        print(f"  已认证:         {'✅' if result.authenticated else '❌'}")
        print(f"  Token 有效:     {'✅' if result.token_valid else '❌'}")
        if result.username:
            print(f"  用户名:         {result.username}")
        print(f"  当前 scope:     {', '.join(result.current_scopes) or '(无)'}")
        print(f"  必需 scope:     {', '.join(result.required_scopes)}")
        if result.missing_scopes:
            print(f"  缺失 scope:     {', '.join(result.missing_scopes)}")
        if result.refreshed:
            print(f"  已执行刷新:     ✅ (尝试 {result.refresh_attempts} 次)")
        if result.error:
            print(f"  错误:           {result.error}")
        print("=" * 55)

    # 退出码
    if result.ok:
        return 0
    if not result.authenticated:
        return 2
    if result.missing_scopes:
        return 3
    return 1


if __name__ == "__main__":
    sys.exit(main())
