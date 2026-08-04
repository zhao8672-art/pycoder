#!/usr/bin/env python3
"""gh_permissions 模块的 Mock 测试 — 验证权限缺失时的重试逻辑。

使用 unittest.mock.patch 模拟 gh CLI 响应, 无需真实 GitHub 连接。

测试场景:
  1. 全部 scope 具备 → 直接通过 (无重试)
  2. 缺失 scope, 刷新成功 → 1 次重试后通过
  3. 缺失 scope, 第 1 次刷新失败, 第 2 次成功 → 2 次重试后通过
  4. 缺失 scope, 全部刷新失败 → 达到最大重试次数后失败
  5. 未认证 → 立即失败 (不尝试刷新)
  6. token 无效 → 立即失败 (不尝试刷新)
  7. 非交互模式 + 缺失 scope → 不刷新, 直接失败
  8. 刷新后 scope 部分补充 → 仍判定为失败

运行方式:
  # 直接运行 (verbose 输出)
  python tests/test_gh_permissions.py

  # pytest 运行
  python -m pytest tests/test_gh_permissions.py -v
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 将 scripts/ 加入路径以导入 gh_permissions 模块
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from gh_permissions import (  # noqa: E402
    GitHubPermissionChecker,
    PermissionResult,
    check_permissions,
)


# ── Mock 辅助工具 ─────────────────────────────────────────


class MockSubprocessResponse:
    """模拟 subprocess.run 的返回值。"""

    def __init__(
        self,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def make_auth_status_output(
    authenticated: bool = True,
    scopes: list[str] | None = None,
    username: str = "testuser",
) -> str:
    """构造 gh auth status 的模拟输出。

    Args:
        authenticated: 是否已认证
        scopes: token scope 列表
        username: 用户名

    Returns:
        str: 模拟的 gh auth status 输出
    """
    if not authenticated:
        return (
            "You are not logged into any GitHub hosts."
            " To log in, run: gh auth login"
        )

    scopes_str = ", ".join(f"'{s}'" for s in (scopes or []))
    return (
        f"github.com\n"
        f"  Logged in to github.com account {username}\n"
        f"  - Active account: true\n"
        f"  - Git operations protocol: https\n"
        f"  - Token: gho_****\n"
        f"  - Token scopes: {scopes_str}\n"
    )


class MockGHResponder:
    """Mock subprocess.run 的智能响应器。

    根据命令参数和内部状态返回不同的模拟响应,
    支持 scope 刷新后的状态变化。

    Attributes:
        authenticated: 是否已认证
        scopes: 当前 scope 列表 (刷新后可变化)
        username: 用户名
        token_valid: token 是否有效
        refresh_results: 每次 refresh 的返回码列表 (按顺序消耗)
        refresh_call_count: refresh 已被调用次数
    """

    def __init__(
        self,
        authenticated: bool = True,
        scopes: list[str] | None = None,
        username: str = "testuser",
        token_valid: bool = True,
        refresh_results: list[int] | None = None,
        refresh_adds_scopes: bool = True,
    ) -> None:
        self.authenticated = authenticated
        self.scopes = scopes or []
        self.username = username
        self.token_valid = token_valid
        self.refresh_results = refresh_results or []
        self.refresh_adds_scopes = refresh_adds_scopes
        self.refresh_call_count = 0
        self.call_log: list[list[str]] = []  # 记录所有调用

    def __call__(self, cmd: list[str], **kwargs) -> MockSubprocessResponse:
        """模拟 subprocess.run 调用。"""
        self.call_log.append(cmd)

        # gh auth status
        if cmd[:3] == ["gh", "auth", "status"]:
            output = make_auth_status_output(
                authenticated=self.authenticated,
                scopes=self.scopes,
                username=self.username,
            )
            # gh auth status 在未认证时返回非 0
            rc = 0 if self.authenticated else 1
            return MockSubprocessResponse(
                returncode=rc,
                stdout=output if self.authenticated else "",
                stderr=output if not self.authenticated else "",
            )

        # gh api user --jq .login
        if cmd[:4] == ["gh", "api", "user", "--jq"]:
            if self.token_valid:
                return MockSubprocessResponse(
                    returncode=0,
                    stdout=self.username,
                    stderr="",
                )
            return MockSubprocessResponse(
                returncode=1,
                stdout="",
                stderr='{"message": "Bad credentials", "status": "401"}',
            )

        # gh auth refresh -s <scopes...>
        if cmd[:3] == ["gh", "auth", "refresh"]:
            self.refresh_call_count += 1

            # 获取本次 refresh 的返回码
            idx = self.refresh_call_count - 1
            if idx < len(self.refresh_results):
                rc = self.refresh_results[idx]
            else:
                rc = 0  # 默认成功

            # 如果成功且配置为补充 scope, 则将缺失 scope 加入
            if rc == 0 and self.refresh_adds_scopes:
                refreshed_scopes = cmd[3:]  # -s 后面的 scope 列表
                # 过滤掉 "-s" 参数
                scopes_to_add = [s for s in refreshed_scopes if s != "-s"]
                for s in scopes_to_add:
                    if s not in self.scopes:
                        self.scopes.append(s)

            return MockSubprocessResponse(
                returncode=rc,
                stdout="",
                stderr="" if rc == 0 else "Error refreshing token",
            )

        # 未知命令
        return MockSubprocessResponse(
            returncode=1,
            stdout="",
            stderr=f"Unknown mock command: {cmd}",
        )


# ── 测试用例 ──────────────────────────────────────────────


class TestGitHubPermissionChecker(unittest.TestCase):
    """GitHubPermissionChecker 的 Mock 测试。"""

    def setUp(self) -> None:
        """每个测试前重置 logging。"""
        import logging

        logging.disable(logging.CRITICAL)  # 测试时禁用日志输出

    def tearDown(self) -> None:
        """测试后恢复 logging。"""
        import logging

        logging.disable(logging.NOTSET)

    # ── 场景 1: 全部 scope 具备, 直接通过 ──────────────────

    def test_01_all_scopes_present(self) -> None:
        """全部 scope 具备时, 无需刷新, 直接通过。"""
        responder = MockGHResponder(
            authenticated=True,
            scopes=["repo", "workflow", "read:org"],
            username="testuser",
            token_valid=True,
        )

        with patch("subprocess.run", side_effect=responder):
            checker = GitHubPermissionChecker(
                required_scopes=["repo", "workflow"],
                max_retries=2,
                interactive=True,
            )
            result = checker.check_with_retry()

        self.assertTrue(result.ok)
        self.assertTrue(result.authenticated)
        self.assertTrue(result.token_valid)
        self.assertEqual(result.username, "testuser")
        self.assertEqual(result.missing_scopes, [])
        self.assertEqual(result.refresh_attempts, 0)
        self.assertFalse(result.refreshed)

    # ── 场景 2: 缺失 scope, 刷新成功 ──────────────────────

    def test_02_missing_scope_refresh_succeeds(self) -> None:
        """缺失 workflow scope, 第 1 次刷新成功。"""
        responder = MockGHResponder(
            authenticated=True,
            scopes=["repo"],  # 缺失 workflow
            username="testuser",
            token_valid=True,
            refresh_results=[0],  # 第 1 次刷新成功
            refresh_adds_scopes=True,
        )

        with patch("subprocess.run", side_effect=responder):
            with patch("builtins.input", return_value="y"):
                checker = GitHubPermissionChecker(
                    required_scopes=["repo", "workflow"],
                    max_retries=2,
                    interactive=True,
                )
                result = checker.check_with_retry()

        self.assertTrue(result.ok)
        self.assertTrue(result.refreshed)
        self.assertEqual(result.refresh_attempts, 1)
        self.assertEqual(responder.refresh_call_count, 1)
        # 刷新后 scope 应包含 workflow
        self.assertIn("workflow", responder.scopes)

    # ── 场景 3: 第 1 次刷新失败, 第 2 次成功 ───────────────

    def test_03_refresh_fails_then_succeeds(self) -> None:
        """第 1 次刷新失败, 第 2 次刷新成功。"""
        responder = MockGHResponder(
            authenticated=True,
            scopes=["repo"],  # 缺失 workflow
            username="testuser",
            token_valid=True,
            refresh_results=[1, 0],  # 第 1 次失败, 第 2 次成功
            refresh_adds_scopes=True,
        )

        with patch("subprocess.run", side_effect=responder):
            with patch("builtins.input", return_value="y"):
                checker = GitHubPermissionChecker(
                    required_scopes=["repo", "workflow"],
                    max_retries=2,
                    interactive=True,
                    retry_delay=0,  # 测试时不等待
                )
                result = checker.check_with_retry()

        self.assertTrue(result.ok)
        self.assertTrue(result.refreshed)
        self.assertEqual(result.refresh_attempts, 2)
        self.assertEqual(responder.refresh_call_count, 2)

    # ── 场景 4: 全部刷新失败 ──────────────────────────────

    def test_04_all_refreshes_fail(self) -> None:
        """全部 2 次刷新均失败, 最终结果为权限不足。"""
        responder = MockGHResponder(
            authenticated=True,
            scopes=["repo"],  # 缺失 workflow
            username="testuser",
            token_valid=True,
            refresh_results=[1, 1],  # 2 次都失败
            refresh_adds_scopes=False,  # 刷新不补充 scope
        )

        with patch("subprocess.run", side_effect=responder):
            with patch("builtins.input", return_value="y"):
                checker = GitHubPermissionChecker(
                    required_scopes=["repo", "workflow"],
                    max_retries=2,
                    interactive=True,
                    retry_delay=0,
                )
                result = checker.check_with_retry()

        self.assertFalse(result.ok)
        self.assertFalse(result.refreshed)
        self.assertIn("workflow", result.missing_scopes)
        self.assertEqual(responder.refresh_call_count, 2)

    # ── 场景 5: 未认证, 立即失败 ──────────────────────────

    def test_05_not_authenticated_no_retry(self) -> None:
        """未认证时不尝试刷新, 直接失败。"""
        responder = MockGHResponder(
            authenticated=False,
            scopes=[],
            username="",
            token_valid=False,
        )

        with patch("subprocess.run", side_effect=responder):
            checker = GitHubPermissionChecker(
                required_scopes=["repo", "workflow"],
                max_retries=2,
                interactive=True,
            )
            result = checker.check_with_retry()

        self.assertFalse(result.ok)
        self.assertFalse(result.authenticated)
        self.assertEqual(responder.refresh_call_count, 0)  # 不应尝试刷新

    # ── 场景 6: token 无效, 立即失败 ──────────────────────

    def test_06_token_invalid_no_retry(self) -> None:
        """token 无效时不尝试刷新, 直接失败。"""
        responder = MockGHResponder(
            authenticated=True,
            scopes=["repo", "workflow"],
            username="testuser",
            token_valid=False,  # token 无效
        )

        with patch("subprocess.run", side_effect=responder):
            checker = GitHubPermissionChecker(
                required_scopes=["repo", "workflow"],
                max_retries=2,
                interactive=True,
            )
            result = checker.check_with_retry()

        self.assertFalse(result.ok)
        self.assertTrue(result.authenticated)  # 已认证但 token 无效
        self.assertFalse(result.token_valid)
        self.assertEqual(responder.refresh_call_count, 0)  # 不应尝试刷新

    # ── 场景 7: 非交互模式 + 缺失 scope → 不刷新 ───────────

    def test_07_non_interactive_no_refresh(self) -> None:
        """非交互模式下缺失 scope, 不执行刷新。"""
        responder = MockGHResponder(
            authenticated=True,
            scopes=["repo"],  # 缺失 workflow
            username="testuser",
            token_valid=True,
            refresh_results=[0],
        )

        with patch("subprocess.run", side_effect=responder):
            checker = GitHubPermissionChecker(
                required_scopes=["repo", "workflow"],
                max_retries=2,
                interactive=False,  # 非交互
            )
            result = checker.check_with_retry()

        self.assertFalse(result.ok)
        self.assertIn("workflow", result.missing_scopes)
        self.assertEqual(responder.refresh_call_count, 0)  # 不应尝试刷新

    # ── 场景 8: 刷新后部分 scope 补充 ─────────────────────

    def test_08_partial_scope_refresh(self) -> None:
        """刷新只补充部分 scope, 仍判定为失败。"""

        # 自定义 responder: refresh 成功时只补充 workflow, 不补充 read:org
        class PartialRefreshResponder(MockGHResponder):
            def __call__(
                self, cmd: list[str], **kwargs
            ) -> MockSubprocessResponse:
                response = super().__call__(cmd, **kwargs)
                # refresh 成功后只补充 workflow
                if (
                    cmd[:3] == ["gh", "auth", "refresh"]
                    and response.returncode == 0
                ):
                    if "workflow" not in self.scopes:
                        self.scopes.append("workflow")
                    # read:org 故意不补充
                return response

        responder = PartialRefreshResponder(
            authenticated=True,
            scopes=["repo"],  # 缺失 workflow 和 read:org
            username="testuser",
            token_valid=True,
            refresh_results=[0],  # 刷新成功
            refresh_adds_scopes=False,  # 父类不自动补充, 由子类控制
        )

        with patch("subprocess.run", side_effect=responder):
            with patch("builtins.input", return_value="y"):
                checker = GitHubPermissionChecker(
                    required_scopes=["repo", "workflow", "read:org"],
                    max_retries=2,
                    interactive=True,
                    retry_delay=0,
                )
                result = checker.check_with_retry()

        self.assertFalse(result.ok)
        self.assertIn("read:org", result.missing_scopes)
        self.assertNotIn("workflow", result.missing_scopes)

    # ── 场景 9: check_permissions 便捷函数 ────────────────

    def test_09_check_permissions_helper(self) -> None:
        """测试 check_permissions 便捷函数。"""
        responder = MockGHResponder(
            authenticated=True,
            scopes=["repo", "workflow"],
            username="helperuser",
            token_valid=True,
        )

        with patch("subprocess.run", side_effect=responder):
            result = check_permissions(
                required_scopes=["repo", "workflow"],
                max_retries=1,
                interactive=False,
                verbose=False,
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.username, "helperuser")

    # ── 场景 10: PermissionResult 序列化 ──────────────────

    def test_10_permission_result_serialization(self) -> None:
        """测试 PermissionResult 的 to_dict / to_json。"""
        result = PermissionResult(
            ok=True,
            authenticated=True,
            token_valid=True,
            username="serialize_user",
            current_scopes=["repo", "workflow"],
            required_scopes=["repo", "workflow"],
            missing_scopes=[],
            error=None,
            refreshed=False,
            refresh_attempts=0,
        )

        d = result.to_dict()
        self.assertEqual(d["username"], "serialize_user")
        self.assertTrue(d["ok"])

        import json

        j = json.loads(result.to_json())
        self.assertEqual(j["username"], "serialize_user")
        self.assertEqual(j["current_scopes"], ["repo", "workflow"])

    # ── 场景 11: 多次重试消耗 refresh_results ─────────────

    def test_11_refresh_results_exhaustion(self) -> None:
        """refresh_results 列表耗尽后, 默认返回成功。"""
        responder = MockGHResponder(
            authenticated=True,
            scopes=["repo"],
            username="testuser",
            token_valid=True,
            refresh_results=[1],  # 只有 1 个结果 (失败)
            refresh_adds_scopes=True,
        )

        with patch("subprocess.run", side_effect=responder):
            with patch("builtins.input", return_value="y"):
                checker = GitHubPermissionChecker(
                    required_scopes=["repo", "workflow"],
                    max_retries=3,  # 允许 3 次重试
                    interactive=True,
                    retry_delay=0,
                )
                result = checker.check_with_retry()

        # 第 1 次刷新失败 (rc=1), 第 2 次默认成功 (rc=0, scope 补充)
        self.assertTrue(result.ok)
        self.assertTrue(result.refreshed)
        self.assertEqual(responder.refresh_call_count, 2)

    # ── 场景 12: 交互式取消刷新 ───────────────────────────

    def test_12_interactive_cancel_refresh(self) -> None:
        """交互模式下用户输入 N 取消刷新。"""
        responder = MockGHResponder(
            authenticated=True,
            scopes=["repo"],
            username="testuser",
            token_valid=True,
            refresh_results=[0],
        )

        with patch("subprocess.run", side_effect=responder):
            with patch("builtins.input", return_value="n"):
                checker = GitHubPermissionChecker(
                    required_scopes=["repo", "workflow"],
                    max_retries=2,
                    interactive=True,
                    retry_delay=0,
                )
                result = checker.check_with_retry()

        self.assertFalse(result.ok)
        self.assertIn("workflow", result.missing_scopes)
        # 用户取消, 不应执行 refresh 命令
        self.assertEqual(responder.refresh_call_count, 0)

    # ── 场景 13: 交互式 EOF (非交互环境) ──────────────────

    def test_13_interactive_eof(self) -> None:
        """交互模式下 input() 抛出 EOFError (CI 环境)。"""
        responder = MockGHResponder(
            authenticated=True,
            scopes=["repo"],
            username="testuser",
            token_valid=True,
            refresh_results=[0],
        )

        with patch("subprocess.run", side_effect=responder):
            with patch("builtins.input", side_effect=EOFError):
                checker = GitHubPermissionChecker(
                    required_scopes=["repo", "workflow"],
                    max_retries=2,
                    interactive=True,
                    retry_delay=0,
                )
                result = checker.check_with_retry()

        self.assertFalse(result.ok)
        self.assertEqual(responder.refresh_call_count, 0)


# ── 可视化测试运行器 ───────────────────────────────────────


def run_visual_tests() -> int:
    """以可视化方式运行所有测试, 打印详细结果。"""
    import logging
    import time

    # 启用 INFO 级别日志以查看重试过程
    logging.disable(logging.NOTSET)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)5s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    # 测试场景描述
    scenarios = [
        ("场景 1: 全部 scope 具备", "test_01_all_scopes_present"),
        ("场景 2: 缺失 scope, 刷新成功", "test_02_missing_scope_refresh_succeeds"),
        ("场景 3: 第 1 次刷新失败, 第 2 次成功", "test_03_refresh_fails_then_succeeds"),
        ("场景 4: 全部刷新失败", "test_04_all_refreshes_fail"),
        ("场景 5: 未认证, 立即失败", "test_05_not_authenticated_no_retry"),
        ("场景 6: token 无效, 立即失败", "test_06_token_invalid_no_retry"),
        ("场景 7: 非交互模式不刷新", "test_07_non_interactive_no_refresh"),
        ("场景 8: 刷新后部分补充", "test_08_partial_scope_refresh"),
        ("场景 9: 便捷函数", "test_09_check_permissions_helper"),
        ("场景 10: 结果序列化", "test_10_permission_result_serialization"),
        ("场景 11: refresh 列表耗尽", "test_11_refresh_results_exhaustion"),
        ("场景 12: 用户取消刷新", "test_12_interactive_cancel_refresh"),
        ("场景 13: EOF 环境", "test_13_interactive_eof"),
    ]

    suite = unittest.TestSuite()
    for desc, test_name in scenarios:
        suite.addTest(TestGitHubPermissionChecker(test_name))

    print()
    print("=" * 60)
    print("  gh_permissions 模块 Mock 测试")
    print("=" * 60)
    print(f"  共 {len(scenarios)} 个测试场景")
    print("=" * 60)
    print()

    start_time = time.time()
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    elapsed = time.time() - start_time

    print()
    print("=" * 60)
    print(f"  结果: {result.testsRun - len(result.failures) - len(result.errors)}/{result.testsRun} 通过"
          f" | {len(result.failures)} 失败 | {len(result.errors)} 错误"
          f" | 耗时 {elapsed:.2f}s")
    print("=" * 60)

    if result.failures:
        print("\n失败详情:")
        for test, traceback in result.failures:
            print(f"  ✗ {test}")
            for line in traceback.split("\n"):
                print(f"    {line}")

    if result.errors:
        print("\n错误详情:")
        for test, traceback in result.errors:
            print(f"  ✗ {test}")
            for line in traceback.split("\n"):
                print(f"    {line}")

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_visual_tests())
