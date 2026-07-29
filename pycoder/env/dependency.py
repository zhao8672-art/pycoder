"""
依赖与环境数据模型

定义自动化依赖安装所需的全部数据类型，包括：
- 依赖来源类型枚举
- 依赖包描述
- 版本约束与冲突
- 安装结果与报告
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class DependencySource(enum.StrEnum):
    """依赖来源类型"""
    REQUIREMENTS_TXT = "requirements.txt"
    PYPROJECT_TOML = "pyproject.toml"
    ENVIRONMENT_YML = "environment.yml"
    PIPFILE = "Pipfile"
    SETUP_CFG = "setup.cfg"
    SETUP_PY = "setup.py"
    AUTO_DETECT = "auto"  # 自动检测


class DependencyStatus(enum.StrEnum):
    """依赖安装状态"""
    PENDING = "pending"
    INSTALLING = "installing"
    INSTALLED = "installed"
    FAILED = "failed"
    SKIPPED = "skipped"  # 已安装且版本满足
    CONFLICT = "conflict"


class PackageManager(enum.StrEnum):
    """包管理器类型"""
    PIP = "pip"
    CONDA = "conda"
    POETRY = "poetry"
    UV = "uv"
    AUTO = "auto"


@dataclass
class VersionConstraint:
    """版本约束 — 描述一个依赖的版本要求"""
    raw: str  # 原始约束字符串，如 ">=1.0,<2.0"
    operator: str = ""  # 操作符: >=, ==, ~=, !=, >, <, <=
    version: str = ""  # 目标版本

    def __post_init__(self):
        if not self.operator and self.raw:
            self._parse()

    def _parse(self) -> None:
        """解析原始约束字符串"""
        import re

        s = self.raw.strip()
        if not s:
            return

        # 匹配: >=1.0, <2.0 或 ~=1.0.0 或 ==1.0 等
        m = re.match(r'^\s*(>=|<=|~=|!=|==|>|<)\s*([\d.*]+[a-zA-Z0-9.]*)\s*$', s)
        if m:
            self.operator = m.group(1)
            self.version = m.group(2)
        else:
            # 可能是简单版本号
            m2 = re.match(r'^([\d.*]+[a-zA-Z0-9.]*)\s*$', s)
            if m2:
                self.operator = "=="
                self.version = m2.group(1)

    def is_satisfied_by(self, installed_version: str) -> bool:
        """检查已安装版本是否满足此约束"""
        if not self.operator or not self.version:
            return True  # 无约束时总是满足

        from packaging.version import Version, parse as parse_version

        try:
            installed = parse_version(installed_version)
            target = parse_version(self.version)
        except Exception:
            return True  # 无法解析版本时宽松处理

        match self.operator:
            case "==":
                return installed == target
            case ">=":
                return installed >= target
            case "<=":
                return installed <= target
            case ">":
                return installed > target
            case "<":
                return installed < target
            case "!=":
                return installed != target
            case "~=":
                # ~= 兼容版本: ~=1.4.2 等价于 >=1.4.2, <1.5
                return installed >= target and installed < self._next_major(target)
            case _:
                return True

    @staticmethod
    def _next_major(version: Version) -> Version:
        """计算下一个主版本号"""
        from packaging.version import Version as _V

        release = list(version.release)
        if len(release) < 2:
            # 只有主版本号 (如 "1")，下一个是 "2"
            release[-1] += 1
            return _V(".".join(str(x) for x in release))
        release[-2] += 1
        for i in range(-1, -len(release) + 1, -1):
            release[i] = 0
        return _V(".".join(str(x) for x in release))

    def to_pip_string(self) -> str:
        """转为 pip 格式字符串"""
        if self.operator and self.version:
            return f"{self.operator}{self.version}"
        return self.raw or ""


@dataclass
class DependencyPackage:
    """单个依赖包描述"""
    name: str  # 包名
    constraints: list[VersionConstraint] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)  # 可选 extras, 如 ["dev", "test"]
    markers: str = ""  # 环境标记, 如 "sys_platform == 'win32'"
    source: DependencySource = DependencySource.AUTO_DETECT
    source_file: str = ""  # 来源文件路径
    raw_line: str = ""  # 原始配置行

    @property
    def pip_specifier(self) -> str:
        """生成 pip 安装说明符"""
        parts = [self.name]
        if self.extras:
            parts[0] = f"{self.name}[{','.join(self.extras)}]"
        if self.constraints:
            constraints_str = ",".join(c.to_pip_string() for c in self.constraints)
            parts.append(constraints_str)
        return "".join(parts)

    def is_satisfied_by(self, installed_version: str) -> bool:
        """检查已安装版本是否满足所有约束"""
        if not self.constraints:
            return True
        return all(c.is_satisfied_by(installed_version) for c in self.constraints)


@dataclass
class DependencyConflict:
    """版本冲突描述"""
    package_name: str
    required_version: str  # 要求的版本
    conflicting_package: str  # 冲突的包名
    conflicting_requirement: str  # 冲突包的版本要求
    message: str = ""

    def __post_init__(self):
        if not self.message:
            self.message = (
                f"版本冲突: {self.package_name} 要求 {self.required_version}，"
                f"但与 {self.conflicting_package} 的 {self.conflicting_requirement} 冲突"
            )


@dataclass
class InstallResult:
    """单个包的安装结果"""
    package_name: str
    status: DependencyStatus = DependencyStatus.PENDING
    version: str = ""  # 安装的版本
    duration_ms: float = 0.0
    error: str = ""
    stdout: str = ""
    stderr: str = ""


@dataclass
class InstallReport:
    """安装报告 — 汇总所有依赖的安装结果"""
    source: DependencySource = DependencySource.AUTO_DETECT
    source_file: str = ""
    total_packages: int = 0
    installed: int = 0
    skipped: int = 0  # 已满足
    failed: int = 0
    conflicts: list[DependencyConflict] = field(default_factory=list)
    results: list[InstallResult] = field(default_factory=list)
    total_duration_ms: float = 0.0
    package_manager: PackageManager = PackageManager.AUTO
    timestamp: str = ""

    @property
    def success_rate(self) -> float:
        """安装成功率 (0.0-1.0)"""
        attempted = self.total_packages - self.skipped
        if attempted == 0:
            return 1.0
        return self.installed / attempted

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "source": str(self.source),
            "source_file": self.source_file,
            "total_packages": self.total_packages,
            "installed": self.installed,
            "skipped": self.skipped,
            "failed": self.failed,
            "success_rate": round(self.success_rate * 100, 1),
            "conflicts": [
                {"package": c.package_name, "message": c.message}
                for c in self.conflicts
            ],
            "results": [
                {
                    "package": r.package_name,
                    "status": str(r.status),
                    "version": r.version,
                    "duration_ms": r.duration_ms,
                    "error": r.error,
                }
                for r in self.results
            ],
            "total_duration_ms": self.total_duration_ms,
            "package_manager": str(self.package_manager),
            "timestamp": self.timestamp,
        }

    def to_markdown(self) -> str:
        """生成 Markdown 格式的安装报告"""
        lines = [
            f"# 依赖安装报告",
            f"",
            f"| 项目 | 值 |",
            f"|------|-----|",
            f"| 来源文件 | {self.source_file or '自动检测'} |",
            f"| 包管理器 | {self.package_manager} |",
            f"| 总包数 | {self.total_packages} |",
            f"| 已安装 | {self.installed} |",
            f"| 已跳过 | {self.skipped} |",
            f"| 失败 | {self.failed} |",
            f"| 成功率 | {self.success_rate * 100:.1f}% |",
            f"| 总耗时 | {self.total_duration_ms / 1000:.1f}s |",
            f"| 时间戳 | {self.timestamp} |",
            f"",
        ]

        if self.conflicts:
            lines.append("## 版本冲突")
            lines.append("")
            for c in self.conflicts:
                lines.append(f"- **{c.package_name}**: {c.message}")

        if self.results:
            lines.append("## 安装详情")
            lines.append("")
            lines.append("| 包名 | 状态 | 版本 | 耗时 | 错误 |")
            lines.append("|------|------|------|------|------|")
            for r in self.results:
                error = r.error[:50] + "..." if len(r.error) > 50 else r.error
                lines.append(
                    f"| {r.package_name} | {r.status} | {r.version or '-'} | "
                    f"{r.duration_ms:.0f}ms | {error or '-'} |"
                )

        return "\n".join(lines)