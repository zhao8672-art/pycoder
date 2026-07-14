"""
Run & Fix 自动循环引擎 — AI 写代码 → 运行 → 失败 → 修复 → 重新运行

核心流程:
    user_task → AI 生成代码 → 写入文件 → 运行
        ├── 成功 → 返回结果 ✅
        └── 失败 → 错误信息 → AI 修复代码 → 重新写入 → 再运行
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from pycoder.server.log import log


@dataclass
class RunFixStep:
    """Run & Fix 循环的每一步状态"""

    step: int
    action: str  # "generate" | "run" | "fix" | "check"
    status: str  # "running" | "success" | "failed"
    code: str = ""
    output: str = ""
    error: str = ""
    fix_description: str = ""


@dataclass
class RunFixResult:
    """Run & Fix 循环最终结果"""

    success: bool
    steps: list[RunFixStep]
    final_code: str = ""
    exec_output: str = ""
    total_retries: int = 0
    duration_ms: float = 0.0


class RunFixLoop:
    """Run & Fix 自动循环引擎"""

    MAX_RETRIES = 5
    EXEC_TIMEOUT_SEC = 30

    def __init__(self, chat_stream_fn, ws_send_fn, model: str = "deepseek-chat"):
        self._chat = chat_stream_fn
        self._ws_send = ws_send_fn
        self._model = model
        self._target_dir = Path(os.getcwd()) / ".runfix"
        self._target_dir.mkdir(parents=True, exist_ok=True)
        self.on_step = None  # 外部设置的回调

    async def execute(self, task: str, target_file: str = "solution.py") -> RunFixResult:
        """执行完整的 Run & Fix 循环"""
        steps: list[RunFixStep] = []
        start_time = time.time()
        full_path = self._target_dir / target_file

        # Step 1: 生成初始代码
        await self._send_step(
            {
                "step": 0,
                "action": "generate",
                "status": "running",
                "message": "AI 生成代码中...",
            }
        )
        code = await self._generate_code(task, target_file)
        if not code:
            step1 = RunFixStep(step=0, action="generate", status="failed", error="AI 未能生成代码")
            steps.append(step1)
            return RunFixResult(success=False, steps=steps)
        step1 = RunFixStep(step=0, action="generate", status="success", code=code)
        steps.append(step1)

        # Step 2-R: Run → Fix 循环
        for retry in range(self.MAX_RETRIES):
            await self._send_step(
                {
                    "step": retry * 2 + 1,
                    "action": "run",
                    "status": "running",
                    "message": f"运行测试 (第 {retry + 1} 次)...",
                }
            )

            # 运行代码
            run_result = await self._run_code(full_path)
            step_run = RunFixStep(
                step=retry * 2 + 1,
                action="run",
                status="success" if run_result["success"] else "failed",
                output=run_result.get("stdout", ""),
                error=run_result.get("stderr", ""),
            )
            steps.append(step_run)

            if run_result["success"]:
                duration = (time.time() - start_time) * 1000
                return RunFixResult(
                    success=True,
                    steps=steps,
                    final_code=full_path.read_text(encoding="utf-8"),
                    exec_output=run_result.get("stdout", ""),
                    total_retries=retry,
                    duration_ms=duration,
                )

            # 失败 → 修复
            error_text = run_result.get("stderr", "") or run_result.get("error", "未知错误")
            await self._send_step(
                {
                    "step": retry * 2 + 2,
                    "action": "fix",
                    "status": "running",
                    "message": f"AI 修复中 (第 {retry + 1} 次)...",
                }
            )

            fixed = await self._fix_code(task, full_path, error_text, retry)
            if fixed:
                step_fix = RunFixStep(
                    step=retry * 2 + 2,
                    action="fix",
                    status="success",
                    code=fixed,
                    fix_description=f"Retry {retry + 1}: {error_text[:200]}",
                )
            else:
                step_fix = RunFixStep(
                    step=retry * 2 + 2,
                    action="fix",
                    status="failed",
                    error="AI 修复失败",
                )
                steps.append(step_fix)
                break
            steps.append(step_fix)

        duration = (time.time() - start_time) * 1000
        return RunFixResult(
            success=False,
            steps=steps,
            total_retries=self.MAX_RETRIES,
            duration_ms=duration,
        )

    async def _generate_code(self, task: str, target_file: str) -> str:
        """AI 生成初始代码"""
        prompt = f"""请为以下任务生成 Python 代码。

任务: {task}

要求:
1. 代码必须包含 if __name__ == "__main__" 入口，可以直接 python 运行
2. 包含所有必要的 import 语句
3. 处理所有可能出现的错误情况（try/except）
4. 代码文件将保存为: {target_file}

只返回可运行的 Python 代码，不要添加任何解释或 markdown 代码块标记。"""
        return await self._call_ai_and_write(prompt, target_file)

    async def _run_code(self, file_path: Path) -> dict:
        """运行 Python 文件并返回结果"""
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(file_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._target_dir),
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.EXEC_TIMEOUT_SEC,
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return {
                    "success": False,
                    "stderr": f"⏱ 执行超时 ({self.EXEC_TIMEOUT_SEC}s)",
                    "error": "timeout",
                }
            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode == 0:
                return {"success": True, "stdout": stdout_str}
            else:
                return {"success": False, "stderr": stderr_str, "stdout": stdout_str}
        except Exception as e:
            return {"success": False, "stderr": str(e), "error": "exec_error"}

    async def _fix_code(self, task: str, file_path: Path, error: str, retry: int) -> str:
        """AI 修复代码"""
        current = file_path.read_text(encoding="utf-8") if file_path.exists() else ""

        prompt = f"""以下 Python 代码运行时出现错误，请修复它。

## 原始任务
{task}

## 当前代码
```python
{current}
```

## 错误信息
{error}

## 修复要求
1. 分析错误原因，从根本上解决问题
2. 添加适当的错误处理（如果缺失）
3. 如果缺少依赖包，在代码开头添加安装提示注释
4. 只返回修复后的完整 Python 代码，不要任何额外解释"""
        return await self._call_ai_and_write(prompt, file_path.name)

    async def _call_ai_and_write(self, prompt: str, filename: str) -> str:
        """调用 AI 并将返回内容写入文件"""
        full = ""
        async for event in self._chat("run_fix", prompt, self._model, hermes=False):
            if event.get("type") == "done":
                full = event.get("content", "")

        if not full:
            return ""

        # 剥离 markdown 代码块
        cleaned = self._strip_code_fence(full)
        file_path = self._target_dir / filename
        file_path.write_text(cleaned, encoding="utf-8")

        # 自动安装缺失依赖
        try:
            await self._auto_install_deps(cleaned)
        except (TimeoutError, OSError, ValueError) as e:
            log.debug("auto_install_deps_failed", error=str(e))

        return cleaned

    async def _auto_install_deps(self, code: str) -> list[str]:
        """从代码中提取 import 并自动安装缺失包"""
        imports = re.findall(r"^import (\S+)|^from (\S+)", code, re.MULTILINE)
        # 扁平化
        modules = set()
        for imp in imports:
            mod = imp[0] or imp[1]
            base = mod.split(".")[0]
            if base not in self._STDLIB_MODULES:
                modules.add(base)

        installed = []
        for mod in modules:
            try:
                proc = await asyncio.wait_for(
                    asyncio.create_subprocess_exec(
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        mod,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    ),
                    timeout=60,
                )
                await proc.wait()
                if proc.returncode == 0:
                    installed.append(mod)
            except (TimeoutError, OSError, ValueError) as e:
                log.debug("pip_install_failed", module=mod, error=str(e))
        return installed

    _STDLIB_MODULES = {
        "os",
        "sys",
        "re",
        "json",
        "math",
        "time",
        "datetime",
        "collections",
        "itertools",
        "functools",
        "pathlib",
        "typing",
        "abc",
        "enum",
        "dataclasses",
        "uuid",
        "hashlib",
        "base64",
        "io",
        "textwrap",
        "random",
        "statistics",
        "decimal",
        "fractions",
        "string",
        "logging",
        "argparse",
        "configparser",
        "asyncio",
        "threading",
        "multiprocessing",
        "subprocess",
        "socket",
        "http",
        "urllib",
        "xml",
        "html",
        "csv",
        "sqlite3",
        "copy",
        "pprint",
        "tempfile",
        "shutil",
        "glob",
        "fnmatch",
        "unittest",
        "doctest",
        "pdb",
        "traceback",
        "warnings",
        "contextlib",
        "weakref",
        "numbers",
        "operator",
        "bisect",
        "array",
        "struct",
        "pickle",
        "shelve",
        "dbm",
        "zipfile",
        "tarfile",
        "gzip",
        "bz2",
        "lzma",
        "secrets",
        "ssl",
        "email",
        "mimetypes",
    }

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            first_nl = text.find("\n")
            if first_nl > 0:
                text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()

    async def _send_step(self, step_data: dict):
        """发送步骤状态到 WebSocket（通过回调或 ws_send）"""
        if self.on_step:
            await self.on_step(step_data)
        try:
            await self._ws_send(
                json.dumps(
                    {
                        "type": "run_fix_step",
                        **step_data,
                    }
                )
            )
        except (ConnectionError, OSError, RuntimeError) as e:
            log.debug("ws_send_step_failed", error=str(e))
