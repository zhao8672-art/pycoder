"""JavaScript/TypeScript LSP Provider — 封装 TypeScript Language Server 交互

提供 JS/TS 文件的诊断、补全、引用查找等 LSP 能力。
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class JavaScriptProvider:
    """JavaScript/TypeScript LSP 客户端

    封装 typescript-language-server 的命令构建和结果解析。
    """

    LANGUAGE = "typescript"
    EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]

    def __init__(self, workspace: Path):
        self._workspace = workspace

    @staticmethod
    def get_server_command() -> list[str]:
        """获取 LSP 服务器启动命令"""
        return ["typescript-language-server", "--stdio"]

    @staticmethod
    def get_install_guide() -> str:
        """获取安装指南"""
        return "npm install -g typescript typescript-language-server"

    def get_project_config(self) -> dict:
        """获取项目配置（tsconfig.json 路径等）"""
        tsconfig = self._workspace / "tsconfig.json"
        return {
            "has_tsconfig": tsconfig.exists(),
            "tsconfig_path": str(tsconfig) if tsconfig.exists() else None,
        }