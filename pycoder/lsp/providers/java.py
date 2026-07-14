"""Java LSP Provider — 封装 Eclipse JDTLS 交互

提供 Java 文件的诊断、补全、引用查找等 LSP 能力。
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class JavaProvider:
    """Java LSP 客户端 (Eclipse JDTLS)

    封装 jdtls 的命令构建和结果解析。
    """

    LANGUAGE = "java"
    EXTENSIONS = [".java"]

    def __init__(self, workspace: Path):
        self._workspace = workspace

    @staticmethod
    def get_server_command() -> list[str]:
        """获取 LSP 服务器启动命令"""
        return ["jdtls"]

    @staticmethod
    def get_install_guide() -> str:
        """获取安装指南"""
        return (
            "从 https://www.eclipse.org/downloads/ 下载 Eclipse JDTLS\n"
            "或使用包管理器: brew install jdtls (macOS) / "
            "scoop install jdtls (Windows)"
        )

    def get_project_config(self) -> dict:
        """获取项目配置（pom.xml / build.gradle 等）"""
        pom = self._workspace / "pom.xml"
        gradle = self._workspace / "build.gradle"
        gradle_kts = self._workspace / "build.gradle.kts"
        return {
            "has_pom": pom.exists(),
            "has_gradle": gradle.exists() or gradle_kts.exists(),
            "build_system": "maven" if pom.exists() else "gradle" if gradle.exists() else "unknown",
        }