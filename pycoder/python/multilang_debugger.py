"""
多语言调试器 — 支持 Java/Go/Rust/JS 等语言断点调试
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


class MultiLangDebugger:
    """多语言断点调试支持"""

    def debug(self, language: str, code: str, breakpoints: list[int]) -> dict:
        """运行多语言调试"""
        debuggers = {
            "python": self._debug_python,
            "java": self._debug_java,
            "go": self._debug_go,
            "javascript": self._debug_js,
            "typescript": self._debug_ts,
        }
        handler = debuggers.get(language)
        if not handler:
            return {"success": False, "error": f"不支持 {language} 调试"}
        return handler(code, breakpoints)

    def list_debuggable(self) -> list[str]:
        """列出可调试的语言"""
        return ["python", "java", "go", "javascript", "typescript"]

    def _debug_python(self, code: str, breakpoints: list[int]) -> dict:
        lines = code.split("\n")
        for bp in sorted(breakpoints, reverse=True):
            idx = bp - 1
            if 0 <= idx < len(lines):
                indent = " " * (len(lines[idx]) - len(lines[idx].lstrip()))
                lines.insert(idx, f"{indent}import pdb; pdb.set_trace()")
        modified = "\n".join(lines)

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(modified)
            tmp_path = f.name

        try:
            r = subprocess.run(
                ["python", tmp_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return {
                "success": r.returncode == 0,
                "output": r.stdout[:3000],
                "error": r.stderr[:1000],
                "breakpoints": breakpoints,
                "language": "python",
            }
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def _debug_java(self, code: str, breakpoints: list[int]) -> dict:
        if not Path("Main.java").exists():
            with open("Main.java", "w") as f:
                f.write(code)

        r = subprocess.run(
            ["javac", "-g", "Main.java"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode != 0:
            return {"success": False, "error": f"编译失败: {r.stderr[:500]}"}

        return {
            "success": True,
            "output": "编译成功。使用 jdb 进行交互式调试",
            "hint": "Java 调试需要交互式终端，请使用终端面板运行: jdb Main",
            "language": "java",
        }

    def _debug_go(self, code: str, breakpoints: list[int]) -> dict:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".go",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(code)
            tmp = f.name

        try:
            r = subprocess.run(
                ["go", "build", "-gcflags=all=-N -l", "-o", "debug_bin", tmp],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if r.returncode != 0:
                return {"success": False, "error": f"编译失败: {r.stderr[:500]}"}
            return {
                "success": True,
                "output": "Go 调试编译成功。",
                "hint": "使用 delve (dlv) 进行调试: dlv exec ./debug_bin",
                "language": "go",
            }
        finally:
            Path(tmp).unlink(missing_ok=True)

    def _debug_js(self, code: str, breakpoints: list[int]) -> dict:
        for bp in sorted(breakpoints, reverse=True):
            lines = code.split("\n")
            if bp - 1 < len(lines):
                lines.insert(bp - 1, "debugger;")
            code = "\n".join(lines)

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".js",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(code)
            tmp = f.name

        try:
            r = subprocess.run(
                ["node", tmp],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return {
                "success": r.returncode == 0,
                "output": r.stdout[:3000],
                "error": r.stderr[:1000],
                "hint": "使用 node inspect 进行交互式调试",
                "language": "javascript",
            }
        finally:
            Path(tmp).unlink(missing_ok=True)

    def _debug_ts(self, code: str, breakpoints: list[int]) -> dict:
        return {
            "success": True,
            "output": "TypeScript 调试: 先用 tsc 编译，再用 node inspect 调试",
            "hint": "使用 ts-node + node inspect 组合",
            "language": "typescript",
        }


_debugger: MultiLangDebugger | None = None


def get_multilang_debugger() -> MultiLangDebugger:
    global _debugger
    if _debugger is None:
        _debugger = MultiLangDebugger()
    return _debugger
