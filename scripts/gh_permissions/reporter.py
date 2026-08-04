"""gh_permissions 报告格式化器 — 生成 CI 风格的权限检查报告。

支持 3 种输出格式:
  - ci:    CI 风格报告 (含耗时、scope 详情、box drawing 边框)
  - json:  JSON 格式 (CI/CD 解析友好)
  - human: 人类可读摘要 (默认)
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from gh_permissions.models import PermissionResult


class ReportFormatter:
    """权限检查报告格式化器。

    封装 CI 日志格式和耗时统计, 替代 workflow YAML 中的内联 shell 脚本。
    所有方法均为静态方法, 无需实例化。
    """

    # Box drawing 字符
    BOX_TOP = "═" * 55
    BOX_BOTTOM = "═" * 55
    SECTION_SEP = "─" * 50

    # gh CLI 常用 scope 说明
    SCOPE_DESCRIPTIONS: dict[str, str] = {
        "repo": "仓库访问、分支保护 API、读取 workflow 状态",
        "workflow": "触发 workflow (gh workflow run, 需 workflow_dispatch)",
        "read:org": "读取组织信息",
        "admin:org": "组织管理权限",
        "gist": "创建 Gist",
        "delete_repo": "删除仓库",
    }

    @staticmethod
    def format_ci(result: PermissionResult) -> str:
        """生成 CI 风格报告 (含耗时、scope 详情、box drawing 边框)。

        替代 CI workflow YAML 中的 80+ 行内联 shell 脚本。

        Args:
            result: 权限检查结果

        Returns:
            str: 格式化的 CI 报告
        """
        lines: list[str] = []
        lines.append(f"┌{ReportFormatter.BOX_TOP}┐")
        lines.append("│  GITHUB_TOKEN 权限预检查                              │")
        lines.append(f"├{ReportFormatter.BOX_TOP}┤")
        lines.append("│                                                      │")
        lines.append("│  ── 检查结果 ──────────────────────────────────────  │")

        # 检查状态
        ok_str = "✅" if result.ok else "❌"
        auth_str = "✅" if result.authenticated else "❌"
        token_str = "✅" if result.token_valid else "❌"
        lines.append(f"│  通过:           {ok_str:<38}│")
        lines.append(f"│  已认证:         {auth_str:<38}│")
        lines.append(f"│  Token 有效:     {token_str:<38}│")

        if result.username:
            lines.append(f"│  用户名:         {result.username:<38}│")

        # Scope 详情
        current = result.current_scopes
        current_str = ", ".join(current) if current else "(无)"
        lines.append(f"│  当前 scope ({len(current)}): {current_str:<33}│")

        required = result.required_scopes
        required_str = ", ".join(required)
        lines.append(f"│  必需 scope ({len(required)}): {required_str:<33}│")

        missing = result.missing_scopes
        if missing:
            missing_str = ", ".join(missing)
            lines.append(f"│  缺失 scope ({len(missing)}): {missing_str:<34}│")
        else:
            lines.append("│  缺失 scope:     (无)                               │")

        if result.refreshed:
            lines.append(
                f"│  已刷新:         ✅ (尝试 {result.refresh_attempts} 次)                    │"
            )

        if result.error:
            # 截断过长的错误信息
            error_str = result.error[:40] + "..." if len(result.error) > 40 else result.error
            lines.append(f"│  错误信息:       {error_str:<38}│")

        # 耗时
        lines.append("│                                                      │")
        lines.append("│  ── 耗时 ──────────────────────────────────────────  │")
        lines.append(f"│  检查耗时:       {result.elapsed:.2f}s{' ' * 34}│")
        lines.append("│                                                      │")

        # 最终结果
        if result.ok:
            lines.append(f"│  ✅ 权限检查通过 (耗时 {result.elapsed:.2f}s){' ' * max(0, 20 - len(f'{result.elapsed:.2f}'))}│")
        else:
            lines.append("│  ⚠️  GITHUB_TOKEN 权限不足, 但 CI 将继续执行         │")
            lines.append("│     (GITHUB_TOKEN 使用 permissions 块控制, 非 PAT)   │")

        lines.append(f"└{ReportFormatter.BOX_BOTTOM}┘")
        return "\n".join(lines)

    @staticmethod
    def format_json(result: PermissionResult) -> str:
        """JSON 格式输出 (CI/CD 解析友好)。"""
        return result.to_json()

    @staticmethod
    def format_human(result: PermissionResult) -> str:
        """人类可读摘要。"""
        lines: list[str] = []
        lines.append("=" * 55)
        lines.append("  GitHub CLI 权限检查结果")
        lines.append("=" * 55)
        lines.append(f"  通过:           {'✅' if result.ok else '❌'}")
        lines.append(f"  已认证:         {'✅' if result.authenticated else '❌'}")
        lines.append(f"  Token 有效:     {'✅' if result.token_valid else '❌'}")

        if result.username:
            lines.append(f"  用户名:         {result.username}")

        current = result.current_scopes
        lines.append(f"  当前 scope:     {', '.join(current) if current else '(无)'}")
        lines.append(f"  必需 scope:     {', '.join(result.required_scopes)}")

        if result.missing_scopes:
            lines.append(f"  缺失 scope:     {', '.join(result.missing_scopes)}")

        if result.refreshed:
            lines.append(f"  已执行刷新:     ✅ (尝试 {result.refresh_attempts} 次)")

        if result.error:
            lines.append(f"  错误:           {result.error}")

        lines.append(f"  耗时:           {result.elapsed:.2f}s")
        lines.append("=" * 55)
        return "\n".join(lines)

    @staticmethod
    def format(result: PermissionResult, fmt: str = "human") -> str:
        """按指定格式生成报告。

        Args:
            result: 权限检查结果
            fmt: 输出格式 ("ci" / "json" / "human")

        Returns:
            str: 格式化报告

        Raises:
            ValueError: 不支持的格式
        """
        match fmt:
            case "ci":
                return ReportFormatter.format_ci(result)
            case "json":
                return ReportFormatter.format_json(result)
            case "human":
                return ReportFormatter.format_human(result)
            case _:
                raise ValueError(f"不支持的格式: {fmt} (可选: ci / json / human)")

    @staticmethod
    def print_report(result: PermissionResult, fmt: str = "human") -> None:
        """打印报告到 stdout。

        Args:
            result: 权限检查结果
            fmt: 输出格式 ("ci" / "json" / "human")
        """
        print(ReportFormatter.format(result, fmt))
