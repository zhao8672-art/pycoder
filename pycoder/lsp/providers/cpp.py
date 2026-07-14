"""C/C++ LSP Provider — 封装 clangd 交互

提供 C/C++ 文件的诊断、补全、引用查找等 LSP 能力。
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class CppProvider:
    """C/C++ LSP 客户端 (clangd)

    封装 clangd 的命令构建和结果解析。
    """

    LANGUAGE = "cpp"
    EXTENSIONS = [".cpp", ".cxx", ".cc", ".c", ".h", ".hpp", ".hxx"]

    def __init__(self, workspace: Path):
        self._workspace = workspace

    @staticmethod
    def get_server_command() -> list[str]:
        """获取 LSP 服务器启动命令"""
        return ["clangd"]

    @staticmethod
    def get_install_guide() -> str:
        """获取安装指南"""
        return (
            "LLVM 官方安装: https://clangd.llvm.org/installation.html\n"
            "或使用包管理器:\n"
            "  - Windows: scoop install llvm\n"
            "  - macOS: brew install llvm\n"
            "  - Linux: apt install clangd"
        )

    def get_project_config(self) -> dict:
        """获取项目配置（compile_commands.json 等）"""
        compile_cmds = self._workspace / "compile_commands.json"
        cmake = self._workspace / "CMakeLists.txt"
        return {
            "has_compile_commands": compile_cmds.exists(),
            "has_cmake": cmake.exists(),
            "compile_commands_path": str(compile_cmds) if compile_cmds.exists() else None,
        }
