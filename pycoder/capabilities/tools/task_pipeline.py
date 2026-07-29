"""任务管道 — 多步骤命令序列执行

功能:
  1. 按顺序执行多个命令步骤
  2. 支持失败重试 (可配置重试次数和延迟)
  3. 支持失败回滚 (已执行步骤的撤销)
  4. 每步骤独立超时

使用场景:
    pipeline = TaskPipeline()
    steps = [
        PipelineStep(command="python -m venv venv", description="创建虚拟环境"),
        PipelineStep(command="venv\\Scripts\\activate", description="激活虚拟环境"),
        PipelineStep(command="pip install -r requirements.txt", description="安装依赖", timeout=300),
    ]
    result = await pipeline.execute(steps)
"""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pycoder.core.shell_translator import translate_to_current_platform

logger = logging.getLogger(__name__)


@dataclass
class PipelineStep:
    """管道步骤"""

    command: str
    description: str = ""
    timeout: int = 60
    retries: int = 0
    retry_delay: float = 1.0
    continue_on_failure: bool = False
    working_dir: str = ""
    rollback_command: str = ""  # 回滚命令

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "description": self.description,
            "timeout": self.timeout,
            "retries": self.retries,
            "continue_on_failure": self.continue_on_failure,
            "working_dir": self.working_dir,
        }


@dataclass
class StepResult:
    """步骤执行结果"""

    step_index: int = 0
    command: str = ""
    description: str = ""
    success: bool = False
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    attempts: int = 0
    rollback_executed: bool = False

    def to_dict(self) -> dict:
        return {
            "step_index": self.step_index,
            "command": self.command,
            "description": self.description,
            "success": self.success,
            "exit_code": self.exit_code,
            "stdout": self.stdout[:4000],
            "stderr": self.stderr[:2000],
            "duration": round(self.duration, 2),
            "attempts": self.attempts,
        }


@dataclass
class PipelineResult:
    """管道执行结果"""

    success: bool = False
    executed: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[StepResult] = field(default_factory=list)
    total_duration: float = 0.0
    error_message: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "executed": self.executed,
            "failed": self.failed,
            "skipped": self.skipped,
            "results": [r.to_dict() for r in self.results],
            "total_duration": round(self.total_duration, 2),
            "error_message": self.error_message,
        }


class TaskPipeline:
    """任务管道 — 多步骤命令序列执行"""

    MAX_STEPS = 20  # 最大步骤数
    MAX_TIMEOUT = 600  # 单步骤最大超时 (秒)

    # 危险命令模式 (禁止执行)
    _DANGEROUS_PATTERNS = [
        "rm -rf /",
        "rm -rf ~",
        "rm -rf C:\\",
        "format ",
        "del /f /s /q C:\\",
        "shutdown",
        "mkfs",
    ]

    async def execute(
        self,
        steps: list[PipelineStep],
        *,
        cwd: str = "",
        stop_on_failure: bool = True,
    ) -> PipelineResult:
        """执行管道

        Args:
            steps: 步骤列表
            cwd: 默认工作目录
            stop_on_failure: 失败时是否停止后续步骤

        Returns:
            PipelineResult: 执行结果
        """
        if not steps:
            return PipelineResult(success=True, error_message="无步骤")

        if len(steps) > self.MAX_STEPS:
            return PipelineResult(
                success=False,
                error_message=f"步骤数超过上限 ({self.MAX_STEPS})",
            )

        result = PipelineResult()
        start_time = asyncio.get_event_loop().time()
        executed_steps: list[tuple[PipelineStep, StepResult]] = []

        for i, step in enumerate(steps):
            # 安全检查
            if self._is_dangerous(step.command):
                step_result = StepResult(
                    step_index=i,
                    command=step.command,
                    description=step.description,
                    success=False,
                    stderr="危险命令被拒绝执行",
                )
                result.results.append(step_result)
                result.failed += 1
                if stop_on_failure and not step.continue_on_failure:
                    result.error_message = f"步骤 {i}: 危险命令被拒绝"
                    break
                continue

            # 执行步骤
            step_result = await self._execute_step(step, i, cwd)
            result.results.append(step_result)
            executed_steps.append((step, step_result))

            if step_result.success:
                result.executed += 1
            else:
                result.failed += 1
                if not step.continue_on_failure and stop_on_failure:
                    result.error_message = f"步骤 {i} 失败: {step_result.stderr[:200]}"
                    # 执行回滚
                    if step.rollback_command:
                        await self._execute_rollback(step, i, cwd)
                        step_result.rollback_executed = True
                    break

        result.total_duration = asyncio.get_event_loop().time() - start_time
        result.success = result.failed == 0
        return result

    async def _execute_step(self, step: PipelineStep, index: int, default_cwd: str) -> StepResult:
        """执行单个步骤 (含重试)"""
        max_attempts = step.retries + 1
        cwd = step.working_dir or default_cwd or str(Path.cwd())

        # 跨平台命令翻译
        command = step.command
        try:
            translation = translate_to_current_platform(command)
            if translation.changed:
                command = translation.translated
        except Exception:
            pass  # 翻译失败不影响执行

        timeout = min(step.timeout, self.MAX_TIMEOUT)
        last_result = StepResult(
            step_index=index,
            command=command,
            description=step.description,
        )

        for attempt in range(1, max_attempts + 1):
            last_result.attempts = attempt
            start = asyncio.get_event_loop().time()

            try:
                if sys.platform == "win32":
                    proc = await asyncio.create_subprocess_exec(
                        "powershell.exe",
                        "-Command",
                        command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=cwd or None,
                    )
                else:
                    proc = await asyncio.create_subprocess_exec(
                        "bash",
                        "-c",
                        command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=cwd or None,
                    )

                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )

                last_result.stdout = stdout_bytes.decode("utf-8", errors="replace")
                last_result.stderr = stderr_bytes.decode("utf-8", errors="replace")
                last_result.exit_code = proc.returncode or 0
                last_result.success = proc.returncode == 0
                last_result.duration = asyncio.get_event_loop().time() - start

                if last_result.success:
                    return last_result

                # 失败但还有重试机会
                if attempt < max_attempts:
                    logger.info(
                        "pipeline_step_retry index=%d attempt=%d/%d exit_code=%d",
                        index,
                        attempt,
                        max_attempts,
                        last_result.exit_code,
                    )
                    await asyncio.sleep(step.retry_delay)

            except TimeoutError:
                last_result.success = False
                last_result.stderr = f"步骤超时 ({timeout}s)"
                last_result.duration = float(timeout)
                if attempt < max_attempts:
                    await asyncio.sleep(step.retry_delay)
            except FileNotFoundError as e:
                last_result.success = False
                last_result.stderr = f"命令未找到: {e}"
                last_result.duration = 0.0
                break  # 命令不存在，重试无意义
            except Exception as e:
                last_result.success = False
                last_result.stderr = str(e)
                last_result.duration = asyncio.get_event_loop().time() - start
                if attempt < max_attempts:
                    await asyncio.sleep(step.retry_delay)

        return last_result

    async def _execute_rollback(self, step: PipelineStep, index: int, cwd: str) -> None:
        """执行回滚命令"""
        if not step.rollback_command:
            return

        try:
            command = step.rollback_command
            translation = translate_to_current_platform(command)
            if translation.changed:
                command = translation.translated

            if sys.platform == "win32":
                proc = await asyncio.create_subprocess_exec(
                    "powershell.exe",
                    "-Command",
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd or None,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    "bash",
                    "-c",
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd or None,
                )

            await asyncio.wait_for(proc.communicate(), timeout=30)
            logger.info("pipeline_rollback_executed index=%d", index)
        except Exception as e:
            logger.warning("pipeline_rollback_failed index=%d error=%s", index, e)

    def _is_dangerous(self, command: str) -> bool:
        """检查命令是否危险"""
        cmd_lower = command.lower().strip()
        for pattern in self._DANGEROUS_PATTERNS:
            if pattern.lower() in cmd_lower:
                return True
        return False
