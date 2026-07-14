"""Go LSP Provider — 封装 gopls 交互

提供 Go 文件的诊断、补全、引用查找等 LSP 能力。
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class GoProvider:
    """Go LSP 客户端 (gopls)

    封装 gopls 的命令构建和结果解析。
    """

    LANGUAGE = "go"
    EXTENSIONS = [".go"]

    def __init__(self, workspace: Path):
        self._workspace = workspace

    @staticmethod
    def get_server_command() -> list[str]:
        """获取 LSP 服务器启动命令"""
        return ["gopls"]

    @staticmethod
    def get_install_guide() -> str:
        """获取安装指南"""
        return "go install golang.org/x/tools/gopls@latest\n" "确保 $GOPATH/bin 在 PATH 中"

    def get_project_config(self) -> dict:
        """获取项目配置（go.mod 等）"""
        go_mod = self._workspace / "go.mod"
        go_sum = self._workspace / "go.sum"
        return {
            "has_go_mod": go_mod.exists(),
            "has_go_sum": go_sum.exists(),
            "go_mod_path": str(go_mod) if go_mod.exists() else None,
        }
