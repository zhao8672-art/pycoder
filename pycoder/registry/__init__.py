"""域注册表 — 自动发现和注册能力域

功能：
    1. 扫描 capabilities/ 目录，自动发现所有能力域
    2. 提供域元数据查询
    3. 启动时自动注册所有域

使用方式：
    from pycoder.registry import DomainRegistry

    registry = DomainRegistry()
    registry.discover()
    for domain in registry.domains:
        print(f"{domain.name}: {len(domain.capabilities)} 个能力")
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DomainInfo:
    """能力域信息"""

    name: str  # 域名（如 "editor"）
    path: Path  # 模块路径
    capabilities: list[str] = field(default_factory=list)  # 能力 ID 列表
    register_function: str = ""  # 注册函数名（如 "register_editor_capabilities"）
    loaded: bool = False  # 是否已加载


class DomainRegistry:
    """域注册表 — 自动发现和注册能力域"""

    def __init__(self, capabilities_root: Path | None = None) -> None:
        if capabilities_root is None:
            # 默认：pycoder/capabilities/
            self._root = Path(__file__).parent.parent / "capabilities"
        else:
            self._root = capabilities_root
        self._domains: dict[str, DomainInfo] = {}

    def discover(self) -> list[DomainInfo]:
        """扫描 capabilities/ 目录，发现所有能力域

        Returns:
            发现的域列表
        """
        self._domains.clear()

        if not self._root.exists():
            return []

        for entry in self._root.iterdir():
            if not entry.is_dir():
                continue
            if entry.name.startswith("_") or entry.name.startswith("."):
                continue

            # 检查是否有 __init__.py
            init_file = entry / "__init__.py"
            if not init_file.exists():
                continue

            # 查找注册函数
            register_func = self._find_register_function(entry)
            capabilities = self._extract_capabilities(entry)

            domain = DomainInfo(
                name=entry.name,
                path=entry,
                capabilities=capabilities,
                register_function=register_func,
                loaded=False,
            )
            self._domains[entry.name] = domain

        return list(self._domains.values())

    def register_all(self) -> dict[str, bool]:
        """注册所有已发现的域

        Returns:
            域名到注册结果的映射
        """
        results: dict[str, bool] = {}

        for name, domain in self._domains.items():
            try:
                if domain.register_function:
                    module_path = f"pycoder.capabilities.{name}"
                    module = importlib.import_module(module_path)
                    register_fn = getattr(module, domain.register_function, None)
                    if register_fn and callable(register_fn):
                        register_fn()
                        domain.loaded = True
                        results[name] = True
                    else:
                        results[name] = False
                else:
                    results[name] = False
            except Exception:
                results[name] = False

        return results

    @property
    def domains(self) -> list[DomainInfo]:
        """所有已发现的域"""
        return list(self._domains.values())

    def get_domain(self, name: str) -> DomainInfo | None:
        """获取指定域信息"""
        return self._domains.get(name)

    @property
    def total_capabilities(self) -> int:
        """总能力数"""
        return sum(len(d.capabilities) for d in self._domains.values())

    def _find_register_function(self, domain_path: Path) -> str:
        """查找域的注册函数名"""
        init_file = domain_path / "__init__.py"
        if not init_file.exists():
            return ""

        try:
            content = init_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

        # 查找 register_*_capabilities 函数
        import re

        match = re.search(r"def\s+(register_\w+_capabilities)\s*\(", content)
        if match:
            return match.group(1)
        return ""

    def _extract_capabilities(self, domain_path: Path) -> list[str]:
        """从域目录提取能力 ID 列表"""
        capabilities: list[str] = []
        domain_name = domain_path.name

        # 扫描域目录下的 .py 文件
        for py_file in domain_path.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            # 查找 capability_id = "xxx" 或 "editor.code.read" 等模式
            import re

            matches = re.findall(r'capability_id\s*=\s*["\']([^"\']+)["\']', content)
            if not matches:
                # 查找 CapabilityDefinition 调用中的 id 字段
                matches = re.findall(r'id\s*=\s*["\']([^"\']+)["\']', content)

            for m in matches:
                if m not in capabilities:
                    capabilities.append(m)

        # 如果没找到具体能力，至少返回域名作为前缀
        if not capabilities:
            capabilities.append(f"{domain_name}.*")

        return capabilities
