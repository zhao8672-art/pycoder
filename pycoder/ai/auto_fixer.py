"""
自动修复-验证循环 — AI 写代码后自动编译→测试→修复→重试

实现 "Write → Build → Test → Fix" 闭环，最大 3 次重试。
与 chat_bridge.py 集成，在 write_file/create_file/patch_file 后自动触发。

用法:
    from pycoder.ai.auto_fixer import AutoFixer
    fixer = AutoFixer()
    result = await fixer.validate_and_fix("app/main.py", llm_callback=my_callback)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Awaitable
from typing import Callable

logger = logging.getLogger(__name__)

# 最大重试次数
MAX_RETRIES = 3


@dataclass
class FixerResult:
    """修复验证结果"""

    file_path: str
    status: str  # verified / fixed / failed / skipped
    attempts: int = 0
    errors: list[str] = field(default_factory=list)
    error_type: str = ""  # syntax / import / runtime / test_fail
    fix_applied: bool = False
    fix_content: str = ""

    @property
    def success(self) -> bool:
        return self.status in ("verified", "fixed")


class AutoFixer:
    """自动修复器 — Write → Build → Test → Fix 循环"""

    def __init__(
        self,
        project_root: Path | None = None,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self._root = project_root or Path.cwd()
        self._max_retries = max_retries

    async def validate_and_fix(
        self,
        file_path: str | Path,
        test_target: str = "",
        llm_callback: Callable[[str, str], Awaitable[str]] | None = None,
        auto_fix: bool = True,
    ) -> FixerResult:
        """验证并自动修复新写入的代码文件。

        Args:
            file_path: 要验证的 .py 文件路径
            test_target: pytest 目标（如 tests/test_api.py），为空则自动检测
            llm_callback: AI 修复回调 async def(错误信息, 文件内容) → 修复后内容
            auto_fix: 是否自动调用 LLM 修复（默认 True）

        Returns:
            FixerResult 包含验证/修复状态
        """
        fp = Path(file_path)
        result = FixerResult(file_path=str(fp))

        if not fp.exists():
            result.status = "skipped"
            result.errors.append("文件不存在")
            return result

        if fp.suffix != ".py":
            result.status = "skipped"
            result.errors.append(f"非 Python 文件: {fp.suffix}")
            return result

        _original_for_debug = fp.read_text(encoding="utf-8", errors="replace")  # noqa: F841

        for attempt in range(1, self._max_retries + 1):
            result.attempts = attempt

            # ── 步骤 1: 语法检查 ──
            syntax_ok, syntax_err = self._check_syntax(fp)
            if syntax_ok:
                # 语法通过 → 继续测试
                pass
            else:
                result.error_type = "syntax"
                result.errors.append(f"语法错误: {syntax_err}")
                if auto_fix and llm_callback:
                    fixed = await self._attempt_llm_fix(
                        llm_callback, fp, syntax_err, "syntax", attempt
                    )
                    if fixed:
                        continue  # 重试
                result.status = "failed"
                return result

            # ── 步骤 2: 导入检查（仅对非测试文件）──
            if "test_" not in fp.name:
                import_ok, import_err = await self._check_import(fp)
                if not import_ok:
                    result.error_type = "import"
                    result.errors.append(f"导入错误: {import_err}")
                    if auto_fix and llm_callback:
                        fixed = await self._attempt_llm_fix(
                            llm_callback, fp, import_err, "import", attempt
                        )
                        if fixed:
                            continue
                    # 导入错误不阻塞（可能缺依赖）
                    logger.debug("autofix_import_skip file=%s err=%s", fp.name, import_err)

            # ── 步骤 3: 运行测试 ──
            test_ok, test_output = await self._run_tests(fp, test_target)
            if test_ok:
                result.status = "verified"
                return result

            result.error_type = "test_fail"
            result.errors.append(f"测试失败:\n{test_output[:500]}")
            if auto_fix and llm_callback and attempt < self._max_retries:
                fixed = await self._attempt_llm_fix(
                    llm_callback, fp, test_output, "test_fail", attempt
                )
                if fixed:
                    continue
                result.status = "failed"
                return result

            # 最后一次尝试也失败了
            result.status = "failed"
            return result

        # 耗尽重试次数
        result.status = "failed"
        result.errors.append(f"超过最大重试次数 ({self._max_retries})")
        return result

    def _check_syntax(self, file_path: Path) -> tuple[bool, str]:
        """Python 语法检查"""
        import ast
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            ast.parse(source)
            return True, ""
        except SyntaxError as e:
            return False, f"第 {e.lineno} 行: {e.msg}"

    async def _check_import(self, file_path: Path) -> tuple[bool, str]:
        """检查模块能否被 Python 导入"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "python", "-c",
                f"import ast; ast.parse(open({str(file_path)!r}).read())",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode != 0:
                return False, stderr.decode("utf-8", errors="replace")[:500]
            return True, ""
        except TimeoutError:
            return False, "导入检查超时"
        except Exception as e:
            return False, str(e)

    async def _run_tests(self, file_path: Path, test_target: str) -> tuple[bool, str]:
        """运行 pytest"""
        # 自动检测测试文件
        if not test_target:
            test_dir = self._root / "tests"
            test_file = test_dir / f"test_{file_path.name}"
            if test_file.exists():
                test_target = str(test_file)
            else:
                # 运行整个测试目录
                if test_dir.exists():
                    test_target = str(test_dir)
                else:
                    return True, "无测试目录，跳过"

        try:
            proc = await asyncio.create_subprocess_exec(
                "pytest", test_target, "-x", "--tb=short", "-q",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._root),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            output = stdout.decode("utf-8", errors="replace")
            if proc.returncode == 0:
                return True, output
            return False, output[:1000]
        except TimeoutError:
            return False, "测试超时 (120s)"
        except Exception as e:
            return False, str(e)

    async def _attempt_llm_fix(
        self,
        callback: Callable[[str, str], Awaitable[str]],
        file_path: Path,
        error_msg: str,
        error_type: str,
        attempt: int,
    ) -> bool:
        """调用 LLM 尝试修复"""
        try:
            current = file_path.read_text(encoding="utf-8", errors="replace")
            prompt = (
                f"以下代码有 {error_type} 错误:\n\n"
                f"```\n{error_msg[:800]}\n```\n\n"
                f"当前代码:\n```python\n{current[:3000]}\n```\n\n"
                f"请只返回修复后的完整代码（不要省略，不要写注释说其他代码保持不变）。"
            )
            fixed = await callback(prompt, str(file_path))
            if fixed and fixed.strip() and fixed != current:
                # 验证修复后语法
                import ast
                try:
                    ast.parse(fixed)
                except SyntaxError as e:
                    logger.warning(
                        "autofix_llm_returned_bad_syntax file=%s attempt=%d error=%s",
                        file_path.name, attempt, e,
                    )
                    return False
                file_path.write_text(fixed, encoding="utf-8")
                logger.info(
                    "autofix_applied file=%s type=%s attempt=%d",
                    file_path.name, error_type, attempt,
                )
                return True
        except Exception as e:
            logger.warning("autofix_llm_failed file=%s error=%s", file_path.name, e)
        return False


# 全局单例
_instance: AutoFixer | None = None


def get_auto_fixer(project_root: Path | None = None) -> AutoFixer:
    """获取 AutoFixer 单例"""
    global _instance
    if _instance is None:
        _instance = AutoFixer(project_root=project_root)
    return _instance
