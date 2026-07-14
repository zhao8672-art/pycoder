"""
运行时自动安装器 — 检测并安装缺失的语言环境
"""

from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)


class RuntimeInstaller:
    """自动检测并安装缺失的编程语言运行时"""

    _INSTALLERS = {
        "java": {
            "check": ["java", "-version"],
            "install": {
                "linux": "apt install -y default-jdk",
                "macos": "brew install openjdk",
                "windows": "winget install EclipseAdoptium.Temurin.21.JDK",
            },
        },
        "go": {
            "check": ["go", "version"],
            "install": {
                "linux": "apt install -y golang-go",
                "macos": "brew install go",
                "windows": "winget install GoLang.Go",
            },
        },
        "rust": {
            "check": ["rustc", "--version"],
            "install": {
                "linux": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y",
                "macos": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y",
                "windows": "winget install Rustlang.Rustup",
            },
        },
        "node": {
            "check": ["node", "--version"],
            "install": {
                "linux": "apt install -y nodejs npm",
                "macos": "brew install node",
                "windows": "winget install OpenJS.NodeJS.LTS",
            },
        },
        "gcc": {
            "check": ["gcc", "--version"],
            "install": {
                "linux": "apt install -y build-essential",
                "macos": "brew install gcc",
                "windows": "winget install Microsoft.VisualStudio.2022.BuildTools",
            },
        },
        "docker": {
            "check": ["docker", "--version"],
            "install": {
                "linux": "apt install -y docker.io",
                "macos": "brew install docker",
                "windows": "winget install Docker.DockerDesktop",
            },
        },
    }

    def check(self, language: str) -> dict:
        """检查运行时是否已安装"""
        info = self._INSTALLERS.get(language)
        if not info:
            return {"available": False, "error": f"未知运行时: {language}"}

        cmd = info["check"]
        if shutil.which(cmd[0]) is None:
            return {
                "available": False,
                "missing": cmd[0],
                "install_hint": info["install"].get("windows", "请手动安装"),
            }

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            version = (r.stdout or r.stderr).strip().split("\n")[0][:50]
            return {"available": True, "version": version}
        except (subprocess.SubprocessError, OSError) as e:
            logger.debug("check_runtime_version_failed cmd=%s error=%s", cmd, e)
            return {"available": True, "version": "已安装（版本未知）"}

    def check_all(self) -> dict:
        """检查所有运行时"""
        results = {}
        for lang in self._INSTALLERS:
            results[lang] = self.check(lang)
        return results

    def install(self, language: str) -> dict:
        """尝试安装运行时"""
        info = self._INSTALLERS.get(language)
        if not info:
            return {"success": False, "error": "未知运行时"}

        import platform

        system = platform.system().lower()
        key = "windows" if system == "windows" else "macos" if system == "darwin" else "linux"
        cmd = info["install"].get(key)

        if not cmd:
            return {
                "success": False,
                "error": f"不支持自动安装 {language} 在 {system}",
                "manual": "请手动安装",
            }

        return {
            "success": False,
            "hint": f"自动安装当前为预览模式。请手动运行: {cmd}",
            "command": cmd,
            "needs_admin": system == "windows",
        }

    def scan_workspace_needs(self, project_dir: str = ".") -> list[dict]:
        """扫描项目需要的运行时"""
        from pathlib import Path

        needs = []
        root = Path(project_dir)
        patterns = {
            "java": ["*.java", "*.gradle", "pom.xml"],
            "go": ["*.go", "go.mod"],
            "rust": ["*.rs", "Cargo.toml"],
            "node": ["*.js", "*.ts", "package.json"],
            "docker": ["Dockerfile", "docker-compose.yml"],
        }
        for lang, pats in patterns.items():
            found = any(list(root.rglob(p)) for p in pats)
            if found:
                check = self.check(lang)
                needs.append(
                    {
                        "language": lang,
                        "files_found": True,
                        "installed": check["available"],
                        "hint": check.get("install_hint", ""),
                    }
                )
        return needs


_installer: RuntimeInstaller | None = None


def get_runtime_installer() -> RuntimeInstaller:
    global _installer
    if _installer is None:
        _installer = RuntimeInstaller()
    return _installer
