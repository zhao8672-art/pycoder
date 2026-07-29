"""环境管理模块 — 自动化工具检测与依赖安装"""
from __future__ import annotations

from typing import Any

from pycoder.env.auto_installer import AutoInstaller
from pycoder.env.env_installer import EnvInstaller
from pycoder.env.tool_detector import ToolDetector, ToolRequirement, ToolStatus

__all__ = [
    "ToolDetector", "ToolRequirement", "ToolStatus", "AutoInstaller",
    "EnvInstaller", "register_capabilities",
]


def register_capabilities(registry: Any) -> None:
    """向能力总线注册环境工具检测与安装能力"""
    from pycoder.bus.protocol import (
        CapabilityCategory,
        CapabilityDefinition,
        ExecutionMode,
        SideEffect,
        TrustLevel,
    )

    detector = ToolDetector()
    installer = AutoInstaller(detector)

    def _detect_tools(params: dict, ctx: dict) -> dict:
        results = detector.detect_all()
        return {
            "tools": [
                {
                    "name": r.name, "installed": r.installed,
                    "version": r.version, "meets_minimum": r.meets_minimum,
                    "error": r.error,
                }
                for r in results
            ],
        }

    def _check_tool(params: dict, ctx: dict) -> dict:
        req = detector.get_tool_by_name(params["tool_name"])
        if not req:
            return {"error": f"工具 {params['tool_name']} 未定义"}
        status = detector._detect_one(req)
        return {
            "name": status.name, "installed": status.installed,
            "version": status.version, "meets_minimum": status.meets_minimum,
            "error": status.error,
        }

    def _install_tool(params: dict, ctx: dict) -> dict:
        success = installer.auto_install(params["tool_name"])
        return {"success": success, "tool_name": params["tool_name"]}

    def _get_install_guide(params: dict, ctx: dict) -> dict:
        tool = detector.get_tool_by_name(params["tool_name"])
        if not tool:
            return {"error": f"工具 {params['tool_name']} 未定义"}
        return {
            "name": tool.name, "display_name": tool.display_name,
            "install_guide": tool.install_guide,
            "platform_install": tool.platform_install,
        }

    registry.register(
        CapabilityDefinition(
            id="env.detect_tools",
            name="检测所有工具",
            description="检测系统环境中所有预定义工具的可用性和版本",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={"type": "object", "properties": {}},
            tags=["env", "detect", "tools", "检测", "工具"],
        ),
        handler=_detect_tools,
    )

    registry.register(
        CapabilityDefinition(
            id="env.check_tool",
            name="检测指定工具",
            description="检测指定工具的可用性和版本",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string", "description": "工具名称 (git/docker/node/bandit/semgrep)"},
                },
                "required": ["tool_name"],
            },
            tags=["env", "check", "tool", "检测"],
        ),
        handler=_check_tool,
    )

    registry.register(
        CapabilityDefinition(
            id="env.install_tool",
            name="安装工具",
            description="自动安装指定的系统工具",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.SYSTEM_ACCESS,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.PROCESS],
            schema={
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string", "description": "工具名称"},
                },
                "required": ["tool_name"],
            },
            tags=["env", "install", "tool", "安装"],
        ),
        handler=_install_tool,
    )

    registry.register(
        CapabilityDefinition(
            id="env.get_install_guide",
            name="获取安装指南",
            description="获取指定工具的安装指南和平台特定命令",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string", "description": "工具名称"},
                },
                "required": ["tool_name"],
            },
            tags=["env", "guide", "install", "安装指南"],
        ),
        handler=_get_install_guide,
    )

    # ── 依赖安装能力 ──────────────────────────────

    env_installer = EnvInstaller()

    def _auto_install_deps(params: dict, ctx: dict) -> dict:
        """自动检测并安装项目依赖"""
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            report = loop.run_until_complete(env_installer.auto_install())
            return report.to_dict()
        finally:
            loop.close()

    def _install_from_file(params: dict, ctx: dict) -> dict:
        """从指定文件安装依赖"""
        import asyncio

        from pycoder.env.dependency import DependencySource

        source_file = params["source_file"]
        source_type_str = params.get("source_type", "auto")
        try:
            source_type = DependencySource(source_type_str)
        except ValueError:
            source_type = DependencySource.AUTO_DETECT

        loop = asyncio.new_event_loop()
        try:
            report = loop.run_until_complete(
                env_installer.install_from_file(source_file, source_type)
            )
            return report.to_dict()
        finally:
            loop.close()

    def _check_environment(params: dict, ctx: dict) -> dict:
        """检查环境状态（不安装）"""
        import asyncio

        from pycoder.env.dependency import DependencySource

        source_file = params.get("source_file")
        source_type_str = params.get("source_type", "auto")
        try:
            source_type = DependencySource(source_type_str)
        except ValueError:
            source_type = DependencySource.AUTO_DETECT

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                env_installer.check_environment(source_file, source_type)
            )
        finally:
            loop.close()

    def _install_packages(params: dict, ctx: dict) -> dict:
        """安装指定的包列表"""
        import asyncio

        package_specs = params.get("packages", [])

        loop = asyncio.new_event_loop()
        try:
            report = loop.run_until_complete(
                env_installer.install_packages(package_specs)
            )
            return report.to_dict()
        finally:
            loop.close()

    def _get_last_report(params: dict, ctx: dict) -> dict:
        """获取最后一次安装报告"""
        report = env_installer.last_report
        if report:
            return report.to_dict()
        return {"error": "暂无安装报告"}

    registry.register(
        CapabilityDefinition(
            id="env.auto_install_deps",
            name="自动安装依赖",
            description="自动检测项目中的依赖配置文件（requirements.txt/pyproject.toml/environment.yml），解析、安装并验证所有依赖",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.SYSTEM_ACCESS,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.PROCESS, SideEffect.NETWORK],
            schema={"type": "object", "properties": {}},
            tags=["env", "install", "deps", "依赖", "自动安装"],
        ),
        handler=_auto_install_deps,
    )

    registry.register(
        CapabilityDefinition(
            id="env.install_from_file",
            name="从文件安装依赖",
            description="从指定的依赖配置文件安装依赖",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.SYSTEM_ACCESS,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.PROCESS, SideEffect.NETWORK],
            schema={
                "type": "object",
                "properties": {
                    "source_file": {"type": "string", "description": "依赖文件路径"},
                    "source_type": {
                        "type": "string",
                        "description": "文件类型: requirements.txt / pyproject.toml / environment.yml / auto",
                        "default": "auto",
                    },
                },
                "required": ["source_file"],
            },
            tags=["env", "install", "file", "依赖", "从文件安装"],
        ),
        handler=_install_from_file,
    )

    registry.register(
        CapabilityDefinition(
            id="env.check_environment",
            name="检查环境状态",
            description="检查项目的依赖安装状态，列出缺失、版本不满足和已满足的包",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "source_file": {"type": "string", "description": "依赖文件路径（可选，不指定则自动检测）"},
                    "source_type": {"type": "string", "description": "文件类型", "default": "auto"},
                },
            },
            tags=["env", "check", "environment", "检查", "环境"],
        ),
        handler=_check_environment,
    )

    registry.register(
        CapabilityDefinition(
            id="env.install_packages",
            name="安装指定包",
            description="安装指定的 Python 包列表",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.SYSTEM_ACCESS,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.PROCESS, SideEffect.NETWORK],
            schema={
                "type": "object",
                "properties": {
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "包说明符列表，如 ['numpy>=1.21', 'pandas==1.3.0']",
                    },
                },
                "required": ["packages"],
            },
            tags=["env", "install", "packages", "包安装"],
        ),
        handler=_install_packages,
    )

    registry.register(
        CapabilityDefinition(
            id="env.get_install_report",
            name="获取安装报告",
            description="获取最后一次依赖安装的详细报告",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={"type": "object", "properties": {}},
            tags=["env", "report", "install", "报告"],
        ),
        handler=_get_last_report,
    )
