"""
多语言代码执行支持 — Java, Go, Rust, Node.js, C/C++

通过 MCP 工具 execute_multilang 和 /api/code/exec-multilang 端点暴露，
自动检测已安装的编译器/运行时。
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# 语言 → 默认文件扩展名和编译/运行命令
LANG_CONFIG = {
    "python": {"ext": ".py", "compile": None, "run": ["python", "{file}"]},
    "javascript": {"ext": ".js", "compile": None, "run": ["node", "{file}"]},
    "typescript": {"ext": ".ts", "compile": None, "run": ["npx", "tsx", "{file}"]},
    "java": {
        "ext": ".java",
        "compile": ["javac", "{file}"],
        "run": ["java", "-cp", "{dir}", "{classname}"],
    },
    "go": {
        "ext": ".go",
        "compile": None,
        "run": ["go", "run", "{file}"],
    },
    "rust": {
        "ext": ".rs",
        "compile": ["rustc", "{file}", "-o", "{dir}/output"],
        "run": ["{dir}/output"],
    },
    "c": {
        "ext": ".c",
        "compile": ["gcc", "{file}", "-o", "{dir}/output"],
        "run": ["{dir}/output"],
    },
    "cpp": {
        "ext": ".cpp",
        "compile": ["g++", "{file}", "-o", "{dir}/output"],
        "run": ["{dir}/output"],
    },
    "bash": {"ext": ".sh", "compile": None, "run": ["bash", "{file}"]},
    "csharp": {
        "ext": ".cs",
        "compile": ["mcs", "-out:{dir}/output.exe", "{file}"],
        "run": ["mono", "{dir}/output.exe"],
    },
    "ruby": {"ext": ".rb", "compile": None, "run": ["ruby", "{file}"]},
}


def check_available(language: str) -> bool:
    """检查指定语言的运行时是否可用"""
    cfg = LANG_CONFIG.get(language)
    if not cfg:
        return False

    check_cmd = {
        "python": ["python", "--version"],
        "javascript": ["node", "--version"],
        "typescript": ["node", "--version"],
        "java": ["javac", "-version"],
        "go": ["go", "version"],
        "rust": ["rustc", "--version"],
        "c": ["gcc", "--version"],
        "cpp": ["g++", "--version"],
        "bash": ["bash", "--version"],
        "csharp": ["mcs", "--version"],
        "ruby": ["ruby", "--version"],
    }.get(language, ["echo"])

    try:
        import subprocess as _sp

        _sp.run(check_cmd, capture_output=True, timeout=5, check=True)
        return True
    except (_sp.SubprocessError, OSError) as e:
        logger.debug("check_available_failed lang=%s cmd=%s error=%s", language, check_cmd, e)
        return False


def list_available() -> list[str]:
    """列出所有可用的语言运行时"""
    return [lang for lang in LANG_CONFIG if check_available(lang)]


async def _run_subprocess(
    cmd: list[str], timeout: int, cwd: str | None = None
) -> tuple[int, str, str]:
    """异步执行子进程，返回 (returncode, stdout, stderr)"""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return (
        proc.returncode,
        stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else "",
        stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else "",
    )


async def execute_multilang(language: str, code: str, timeout: int = 30) -> dict:
    """在临时目录中异步编译并运行多语言代码"""
    cfg = LANG_CONFIG.get(language)
    if not cfg:
        return {
            "success": False,
            "error": f"不支持的语言: {language}。支持: {list(LANG_CONFIG.keys())}",
        }

    if not check_available(language):
        return {"success": False, "error": f"{language} 运行时未安装。请先安装对应的编译器或运行时"}

    work_dir = Path(tempfile.mkdtemp(prefix=f"pycoder_{language}_"))
    try:
        source_file = work_dir / f"main{cfg['ext']}"
        source_file.write_text(code, encoding="utf-8")

        classname = "Main"
        if language == "java":
            m = re.search(r"public\s+class\s+(\w+)", code)
            if m:
                classname = m.group(1)

        # 编译阶段
        compile_cmd = cfg.get("compile")
        compile_output = ""
        if compile_cmd:
            cmd = [
                arg.replace("{file}", str(source_file)).replace("{dir}", str(work_dir))
                for arg in compile_cmd
            ]
            try:
                rc, stdout, stderr = await _run_subprocess(cmd, timeout=30, cwd=str(work_dir))
            except TimeoutError:
                return {
                    "success": False,
                    "error": "编译超时 (30s)",
                    "language": language,
                    "phase": "compile",
                }
            if rc != 0:
                return {
                    "success": False,
                    "language": language,
                    "phase": "compile",
                    "stdout": stdout[:2000],
                    "stderr": stderr[:2000],
                    "exit_code": rc,
                }
            compile_output = stdout[:500]

        # 运行阶段
        run_cmd = cfg["run"]
        if run_cmd:
            cmd = [
                arg.replace("{file}", str(source_file))
                .replace("{dir}", str(work_dir))
                .replace("{classname}", classname)
                for arg in run_cmd
            ]
            try:
                rc, stdout, stderr = await _run_subprocess(cmd, timeout=timeout, cwd=str(work_dir))
            except TimeoutError:
                return {
                    "success": False,
                    "error": f"执行超时 ({timeout}s)",
                    "language": language,
                    "phase": "run",
                }
            return {
                "success": rc == 0,
                "language": language,
                "phase": "run",
                "stdout": stdout[:8000],
                "stderr": stderr[:4000],
                "exit_code": rc,
                "compile_output": compile_output,
            }

        return {"success": True, "language": language, "stdout": "", "message": "代码已执行"}

    except (OSError, ValueError, RuntimeError, TypeError) as e:
        return {"success": False, "error": str(e), "language": language}
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
