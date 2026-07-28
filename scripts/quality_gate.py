"""PyCoder 本地质量门禁脚本 — commit 前一键预检查

用途:
    在 git commit 前本地运行，提前发现 CI 会拦截的问题，节省推送往返时间。
    覆盖 CI 的核心检查项，但使用更快的子集（跳过 slow 测试）。

用法:
    python scripts/quality_gate.py            # 全量检查
    python scripts/quality_gate.py --quick    # 仅 lint + 快速测试
    python scripts/quality_gate.py --skip-typecheck  # 跳过 mypy (慢)
    python scripts/quality_gate.py --skip-security   # 跳过 bandit

退出码:
    0 = 全部通过
    1 = 有检查项失败

设计原则:
    - 纯标准库，无第三方依赖
    - 每个检查项独立，失败不中断后续检查（汇总报告）
    - 彩色输出，清晰标识 PASS/FAIL/SKIP
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# Windows 终端颜色支持
if sys.platform == "win32":
    os.system("")  # 启用 ANSI 转义码处理


# ── 颜色 ─────────────────────────────────────────────────
def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def green(text: str) -> str:
    return _color(text, "32")


def red(text: str) -> str:
    return _color(text, "31")


def yellow(text: str) -> str:
    return _color(text, "33")


def cyan(text: str) -> str:
    return _color(text, "36")


def gray(text: str) -> str:
    return _color(text, "90")


# ── 检查项定义 ────────────────────────────────────────────


@dataclass
class CheckResult:
    """单项检查结果"""

    name: str
    success: bool
    skipped: bool = False
    duration_s: float = 0.0
    output: str = ""
    error_hint: str = ""


@dataclass
class QualityGate:
    """质量门禁执行器"""

    quick: bool = False
    skip_typecheck: bool = False
    skip_security: bool = False
    skip_tests: bool = False
    results: list[CheckResult] = field(default_factory=list)

    def run(self) -> int:
        """执行所有检查项，返回退出码"""
        print(cyan("=" * 70))
        print(cyan("  PyCoder 本地质量门禁 — commit 前预检查"))
        print(cyan("=" * 70))
        print()

        checks = self._build_checks()
        for name, fn in checks:
            print(f"{gray('▶')} 运行 {name}...")
            result = fn()
            self.results.append(result)
            self._print_result(result)

        return self._print_summary()

    def _build_checks(self) -> list[tuple[str, callable]]:
        checks: list[tuple[str, callable]] = []

        # 1. Lint (ruff) — 必跑
        checks.append(("ruff lint", self._check_ruff))

        # 2. Format check (black --check) — 必跑
        checks.append(("black format check", self._check_black))

        # 3. Import check (核心模块可导入) — 必跑
        checks.append(("core imports", self._check_imports))

        if not self.skip_security:
            checks.append(("bandit security", self._check_bandit))

        if not self.skip_typecheck and not self.quick:
            checks.append(("mypy typecheck", self._check_mypy))

        if not self.skip_tests:
            checks.append(("pytest (fast)", self._check_pytest))

        return checks

    # ── 各检查项实现 ──

    def _run_subprocess(self, cmd: list[str], timeout: int = 180) -> tuple[int, str]:
        """运行子进程，返回 (returncode, output)"""
        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = (proc.stdout + proc.stderr)[-3000:]
            return proc.returncode, output
        except subprocess.TimeoutExpired:
            return 1, f"超时 ({timeout}s)"
        except FileNotFoundError as e:
            return 1, f"工具未安装: {e}"

    def _check_ruff(self) -> CheckResult:
        start = time.time()
        rc, out = self._run_subprocess([PY, "-m", "ruff", "check", "pycoder/", "tests/"])
        return CheckResult(
            name="ruff lint",
            success=rc == 0,
            duration_s=time.time() - start,
            output=out,
            error_hint="运行 `python -m ruff check --fix pycoder/ tests/` 自动修复",
        )

    def _check_black(self) -> CheckResult:
        start = time.time()
        rc, out = self._run_subprocess(
            [PY, "-m", "black", "--check", "--line-length", "100", "pycoder/", "tests/"]
        )
        return CheckResult(
            name="black format check",
            success=rc == 0,
            duration_s=time.time() - start,
            output=out,
            error_hint="运行 `python -m black pycoder/ tests/` 自动格式化",
        )

    def _check_imports(self) -> CheckResult:
        """验证核心模块可正常导入（捕获 import 错误）"""
        start = time.time()
        core_modules = [
            "pycoder",
            "pycoder.server.app",
            "pycoder.bus.protocol",
            "pycoder.capabilities.permissions",
            "pycoder.capabilities.degradation",
            "pycoder.ai.analysis.perf_advisor",
            "pycoder.ai.security.code_sanitizer",
            "pycoder.ai.dialog.decision_snapshot",
            "pycoder.capabilities.tools.task_pipeline",
            "pycoder.capabilities.tools.test_runner",
            "pycoder.capabilities.self_evo.learning.error_patterns",
            "pycoder.capabilities.self_evo.learning.error_classifier",
            "pycoder.io.project_index",
            "pycoder.core.shell_translator",
        ]
        failed: list[str] = []
        for mod in core_modules:
            rc, out = self._run_subprocess([PY, "-c", f"import {mod}"], timeout=30)
            if rc != 0:
                failed.append(f"{mod}: {out.strip().splitlines()[-1] if out.strip() else ''}")
        return CheckResult(
            name="core imports",
            success=len(failed) == 0,
            duration_s=time.time() - start,
            output="\n".join(failed) if failed else "所有核心模块导入成功",
            error_hint="检查模块路径或修复 import 错误",
        )

    def _check_bandit(self) -> CheckResult:
        start = time.time()
        rc, out = self._run_subprocess(
            [PY, "-m", "bandit", "-r", "pycoder/", "-q", "-ii"]
        )
        return CheckResult(
            name="bandit security",
            success=rc == 0,
            duration_s=time.time() - start,
            output=out,
            error_hint="检查 HIGH 严重度安全问题，或运行 `bandit -r pycoder/ -ii` 查看详情",
        )

    def _check_mypy(self) -> CheckResult:
        start = time.time()
        rc, out = self._run_subprocess(
            [PY, "-m", "mypy", "pycoder/", "--ignore-missing-imports", "--no-error-summary"],
            timeout=300,
        )
        return CheckResult(
            name="mypy typecheck",
            success=rc == 0,
            duration_s=time.time() - start,
            output=out,
            error_hint="添加类型注解或使用 # type: ignore 临时跳过",
        )

    def _check_pytest(self) -> CheckResult:
        start = time.time()
        cmd = [PY, "-m", "pytest", "tests/", "-x", "--tb=short", "-q"]
        if self.quick:
            cmd.extend(["-m", "not slow", "--no-header"])
        else:
            cmd.extend(["-m", "not slow", "--no-header"])
        rc, out = self._run_subprocess(cmd, timeout=600)
        return CheckResult(
            name="pytest (fast)",
            success=rc == 0,
            duration_s=time.time() - start,
            output=out[-2000:] if out else "",
            error_hint="修复失败的测试，或使用 -k 过滤特定测试",
        )

    # ── 输出 ──

    def _print_result(self, result: CheckResult) -> None:
        if result.skipped:
            tag = yellow("SKIP")
        elif result.success:
            tag = green("PASS")
        else:
            tag = red("FAIL")

        duration_str = f"{result.duration_s:.1f}s" if result.duration_s > 0 else ""
        print(f"  [{tag}] {result.name} {gray(duration_str)}")

        if not result.success and result.output:
            # 仅打印最后 5 行输出
            lines = result.output.strip().splitlines()
            for line in lines[-5:]:
                print(f"        {gray(line)}")
            if result.error_hint:
                print(f"        {yellow('提示')}: {result.error_hint}")
        print()

    def _print_summary(self) -> int:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.success)
        failed = sum(1 for r in self.results if not r.success and not r.skipped)
        skipped = sum(1 for r in self.results if r.skipped)
        total_duration = sum(r.duration_s for r in self.results)

        print(cyan("=" * 70))
        if failed == 0:
            print(green(f"  ✅ 全部通过 — {passed}/{total} 项检查 ({total_duration:.1f}s)"))
            print(cyan("=" * 70))
            return 0
        else:
            print(red(f"  ❌ {failed} 项失败 — {passed} 通过, {failed} 失败, {skipped} 跳过 ({total_duration:.1f}s)"))
            print(cyan("=" * 70))
            return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PyCoder 本地质量门禁 — commit 前预检查",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="快速模式: 仅 lint + 快速测试 (跳过 mypy/security)",
    )
    parser.add_argument(
        "--skip-typecheck", action="store_true",
        help="跳过 mypy 类型检查 (较慢)",
    )
    parser.add_argument(
        "--skip-security", action="store_true",
        help="跳过 bandit 安全扫描",
    )
    parser.add_argument(
        "--skip-tests", action="store_true",
        help="跳过 pytest 测试",
    )
    args = parser.parse_args()

    gate = QualityGate(
        quick=args.quick,
        skip_typecheck=args.skip_typecheck,
        skip_security=args.skip_security,
        skip_tests=args.skip_tests,
    )
    return gate.run()


if __name__ == "__main__":
    sys.exit(main())
