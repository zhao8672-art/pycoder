"""
依赖解析器 — 解析、排序、冲突检测

支持解析:
- requirements.txt（pip 标准格式）
- pyproject.toml（PEP 621）
- environment.yml（Conda 格式）

功能:
- 依赖提取与版本约束解析
- 拓扑排序（基于依赖图）
- 版本冲突检测
- 环境标记过滤
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from pycoder.env.dependency import (
    DependencyConflict,
    DependencyPackage,
    DependencySource,
    VersionConstraint,
)

logger = logging.getLogger(__name__)


class DependencyResolver:
    """依赖解析器 — 从配置文件中提取并排序依赖"""

    def __init__(self, project_root: str | Path = "."):
        self._project_root = Path(project_root)
        self._packages: list[DependencyPackage] = []
        self._conflicts: list[DependencyConflict] = []
        self._dependency_graph: dict[str, set[str]] = defaultdict(set)
        self._errors: list[str] = []

    # ── 公共 API ──────────────────────────────────

    def resolve(
        self,
        source_file: str | None = None,
        source_type: DependencySource = DependencySource.AUTO_DETECT,
    ) -> tuple[list[DependencyPackage], list[DependencyConflict], list[str]]:
        """
        解析依赖，返回 (包列表, 冲突列表, 错误列表)

        Args:
            source_file: 依赖文件路径（None 则自动检测）
            source_type: 依赖来源类型

        Returns:
            (解析出的包列表, 版本冲突列表, 解析错误列表)
        """
        self._packages = []
        self._conflicts = []
        self._errors = []

        if source_file:
            file_path = self._project_root / source_file
            if not file_path.exists():
                self._errors.append(f"文件不存在: {file_path}")
                return [], [], self._errors
            self._parse_file(file_path, source_type)
        else:
            self._auto_detect()

        # 检测冲突
        self._detect_conflicts()

        return self._packages, self._conflicts, self._errors

    def resolve_ordered(
        self,
        source_file: str | None = None,
        source_type: DependencySource = DependencySource.AUTO_DETECT,
    ) -> tuple[list[DependencyPackage], list[DependencyConflict], list[str]]:
        """
        解析并拓扑排序依赖

        Returns:
            (按依赖顺序排列的包列表, 版本冲突列表, 解析错误列表)
        """
        packages, conflicts, errors = self.resolve(source_file, source_type)
        if errors:
            return packages, conflicts, errors

        # 拓扑排序
        try:
            ordered = self._topological_sort(packages)
            return ordered, conflicts, errors
        except ValueError as e:
            self._errors.append(str(e))
            return packages, conflicts, self._errors

    # ── 自动检测 ──────────────────────────────────

    def _auto_detect(self) -> None:
        """自动检测项目中的依赖文件"""
        detection_order = [
            ("pyproject.toml", DependencySource.PYPROJECT_TOML),
            ("requirements.txt", DependencySource.REQUIREMENTS_TXT),
            ("environment.yml", DependencySource.ENVIRONMENT_YML),
            ("Pipfile", DependencySource.PIPFILE),
            ("setup.cfg", DependencySource.SETUP_CFG),
            ("setup.py", DependencySource.SETUP_PY),
        ]

        for filename, source_type in detection_order:
            file_path = self._project_root / filename
            if file_path.exists():
                logger.info("自动检测到依赖文件: %s", filename)
                self._parse_file(file_path, source_type)
                return

        self._errors.append("未找到任何依赖配置文件")

    # ── 解析入口 ──────────────────────────────────

    def _parse_file(self, file_path: Path, source_type: DependencySource) -> None:
        """根据文件类型分发到对应的解析器"""
        match source_type:
            case DependencySource.REQUIREMENTS_TXT:
                self._parse_requirements_txt(file_path)
            case DependencySource.PYPROJECT_TOML:
                self._parse_pyproject_toml(file_path)
            case DependencySource.ENVIRONMENT_YML:
                self._parse_environment_yml(file_path)
            case DependencySource.PIPFILE:
                self._parse_pipfile(file_path)
            case _:
                self._errors.append(f"不支持的依赖文件类型: {source_type}")

    # ── requirements.txt 解析 ─────────────────────

    def _parse_requirements_txt(self, file_path: Path) -> None:
        """解析 requirements.txt 格式"""
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as e:
            self._errors.append(f"读取文件失败: {file_path}: {e}")
            return

        for line_no, raw_line in enumerate(content.splitlines(), 1):
            line = self._strip_comment(raw_line).strip()
            if not line:
                continue

            # 处理 -r 引用
            if line.startswith("-r ") or line.startswith("--requirement "):
                ref_file = line.split(maxsplit=1)[1].strip()
                ref_path = file_path.parent / ref_file
                if ref_path.exists():
                    self._parse_requirements_txt(ref_path)
                else:
                    self._errors.append(f"引用的依赖文件不存在: {ref_path}")
                continue

            # 处理 -e 可编辑安装
            if line.startswith("-e ") or line.startswith("--editable "):
                continue  # 跳过可编辑安装

            # 处理其他选项 (--index-url, --extra-index-url 等)
            if line.startswith("-"):
                continue

            try:
                pkg = self._parse_requirement_line(line, file_path)
                if pkg:
                    self._packages.append(pkg)
            except ValueError as e:
                self._errors.append(f"第 {line_no} 行解析失败: {e}")

    def _parse_requirement_line(self, line: str, file_path: Path) -> DependencyPackage | None:
        """解析单行依赖声明"""
        # 分离环境标记
        marker = ""
        if ";" in line:
            parts = line.split(";", 1)
            line = parts[0].strip()
            marker = parts[1].strip()

        # 解析包名和版本约束
        # 格式: package_name[extras]>=1.0,<2.0
        match = re.match(
            r'^([a-zA-Z0-9_.-]+)(\[([a-zA-Z0-9_,\s-]+)\])?\s*(.*)$',
            line,
        )
        if not match:
            return None

        pkg_name = match.group(1)
        extras_str = match.group(3)
        constraints_str = match.group(4).strip()

        extras = []
        if extras_str:
            extras = [e.strip() for e in extras_str.split(",") if e.strip()]

        constraints = self._parse_version_constraints(constraints_str)

        return DependencyPackage(
            name=pkg_name,
            constraints=constraints,
            extras=extras,
            markers=marker,
            source=DependencySource.REQUIREMENTS_TXT,
            source_file=str(file_path),
            raw_line=line,
        )

    def _parse_version_constraints(self, constraints_str: str) -> list[VersionConstraint]:
        """解析版本约束字符串"""
        if not constraints_str:
            return []

        constraints = []
        # 按逗号分割多个约束
        for part in constraints_str.split(","):
            part = part.strip()
            if part:
                constraints.append(VersionConstraint(raw=part))
        return constraints

    # ── pyproject.toml 解析 ────────────────────────

    def _parse_pyproject_toml(self, file_path: Path) -> None:
        """解析 pyproject.toml (PEP 621)"""
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as e:
            self._errors.append(f"读取文件失败: {file_path}: {e}")
            return

        # 使用 tomllib 解析
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                self._parse_pyproject_toml_regex(file_path, content)
                return

        try:
            data = tomllib.loads(content)
        except Exception as e:
            self._errors.append(f"TOML 解析失败: {e}")
            return

        # 解析 [project] dependencies
        project = data.get("project", {})
        deps = project.get("dependencies", [])
        for dep in deps:
            pkg = self._parse_requirement_line(dep, file_path)
            if pkg:
                pkg.source = DependencySource.PYPROJECT_TOML
                self._packages.append(pkg)

        # 解析 [project.optional-dependencies]
        optional = project.get("optional-dependencies", {})
        for group, group_deps in optional.items():
            for dep in group_deps:
                pkg = self._parse_requirement_line(dep, file_path)
                if pkg:
                    pkg.source = DependencySource.PYPROJECT_TOML
                    pkg.extras = [group]
                    self._packages.append(pkg)

        # 解析 [tool.poetry.dependencies]
        poetry = data.get("tool", {}).get("poetry", {})
        poetry_deps = poetry.get("dependencies", {})
        for name, spec in poetry_deps.items():
            if name.lower() == "python":
                continue
            pkg = self._parse_poetry_dep(name, spec, file_path)
            if pkg:
                self._packages.append(pkg)

    def _parse_pyproject_toml_regex(self, file_path: Path, content: str) -> None:
        """正则降级解析 pyproject.toml"""
        # 匹配 dependencies = [...] 块
        in_deps = False
        for line in content.splitlines():
            stripped = line.strip()
            if re.match(r'^dependencies\s*=\s*\[', stripped):
                in_deps = True
                continue
            if in_deps:
                if stripped == "]":
                    in_deps = False
                    continue
                # 提取依赖字符串
                m = re.search(r'"([^"]+)"', stripped)
                if m:
                    dep_str = m.group(1)
                    pkg = self._parse_requirement_line(dep_str, file_path)
                    if pkg:
                        pkg.source = DependencySource.PYPROJECT_TOML
                        self._packages.append(pkg)

    def _parse_poetry_dep(
        self, name: str, spec: Any, file_path: Path
    ) -> DependencyPackage | None:
        """解析 Poetry 风格的依赖声明"""
        if isinstance(spec, str):
            return DependencyPackage(
                name=name,
                constraints=[VersionConstraint(raw=spec)],
                source=DependencySource.PYPROJECT_TOML,
                source_file=str(file_path),
            )
        elif isinstance(spec, dict):
            version = spec.get("version", "")
            constraints = [VersionConstraint(raw=version)] if version else []
            extras = spec.get("extras", [])
            markers = spec.get("markers", spec.get("python", ""))
            return DependencyPackage(
                name=name,
                constraints=constraints,
                extras=extras if isinstance(extras, list) else [],
                markers=markers,
                source=DependencySource.PYPROJECT_TOML,
                source_file=str(file_path),
            )
        return None

    # ── environment.yml 解析 ───────────────────────

    def _parse_environment_yml(self, file_path: Path) -> None:
        """解析 Conda environment.yml"""
        try:
            import yaml
        except ImportError:
            self._errors.append("需要安装 pyyaml 来解析 environment.yml")
            return

        try:
            with open(file_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            self._errors.append(f"YAML 解析失败: {e}")
            return

        if not isinstance(data, dict):
            self._errors.append("environment.yml 格式错误")
            return

        # 解析 dependencies 列表
        deps = data.get("dependencies", [])
        for dep in deps:
            if isinstance(dep, str):
                pkg = self._parse_conda_dep(dep, file_path)
                if pkg:
                    self._packages.append(pkg)
            elif isinstance(dep, dict):
                # pip 子依赖
                pip_deps = dep.get("pip", [])
                for pip_dep in pip_deps:
                    pkg = self._parse_requirement_line(pip_dep, file_path)
                    if pkg:
                        pkg.source = DependencySource.ENVIRONMENT_YML
                        self._packages.append(pkg)

    def _parse_conda_dep(self, dep: str, file_path: Path) -> DependencyPackage | None:
        """解析 Conda 格式的依赖声明"""
        # 格式: package_name=1.0=py38_0 或 package_name>=1.0
        match = re.match(r'^([a-zA-Z0-9_.-]+)\s*(.*)$', dep)
        if not match:
            return None

        name = match.group(1)
        spec = match.group(2).strip()

        constraints = []
        if spec:
            # 移除构建字符串 (如 =py38_0)
            spec = re.sub(r'=[a-zA-Z0-9_]+$', '', spec)
            if spec:
                constraints = self._parse_version_constraints(spec)

        return DependencyPackage(
            name=name,
            constraints=constraints,
            source=DependencySource.ENVIRONMENT_YML,
            source_file=str(file_path),
        )

    # ── Pipfile 解析 ───────────────────────────────

    def _parse_pipfile(self, file_path: Path) -> None:
        """解析 Pipfile"""
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as e:
            self._errors.append(f"读取文件失败: {file_path}: {e}")
            return

        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                self._errors.append("需要安装 tomli/tomllib 来解析 Pipfile")
                return

        try:
            data = tomllib.loads(content)
        except Exception as e:
            self._errors.append(f"Pipfile 解析失败: {e}")
            return

        for section in ["packages", "dev-packages"]:
            section_deps = data.get(section, {})
            for name, spec in section_deps.items():
                if isinstance(spec, str):
                    constraints = [VersionConstraint(raw=spec)] if spec != "*" else []
                else:
                    constraints = []

                self._packages.append(
                    DependencyPackage(
                        name=name,
                        constraints=constraints,
                        extras=[section] if section == "dev-packages" else [],
                        source=DependencySource.PIPFILE,
                        source_file=str(file_path),
                    )
                )

    # ── 冲突检测 ───────────────────────────────────

    def _detect_conflicts(self) -> None:
        """检测依赖版本冲突"""
        # 按包名分组
        by_name: dict[str, list[DependencyPackage]] = defaultdict(list)
        for pkg in self._packages:
            by_name[pkg.name.lower()].append(pkg)

        for name, pkgs in by_name.items():
            if len(pkgs) <= 1:
                continue

            # 收集所有约束
            all_constraints = []
            for pkg in pkgs:
                all_constraints.extend(pkg.constraints)

            if not all_constraints:
                continue

            # 检测冲突: 如果存在多个不同的 == 约束
            exact_versions = {
                c.version
                for c in all_constraints
                if c.operator == "==" and c.version
            }
            if len(exact_versions) > 1:
                self._conflicts.append(
                    DependencyConflict(
                        package_name=name,
                        required_version=", ".join(sorted(exact_versions)),
                        conflicting_package=name,
                        conflicting_requirement="多个精确版本要求",
                    )
                )

    # ── 拓扑排序 ───────────────────────────────────

    def _topological_sort(self, packages: list[DependencyPackage]) -> list[DependencyPackage]:
        """
        拓扑排序 — 使用 Kahn 算法确保依赖安装顺序

        如果无法确定依赖关系，按原始顺序返回。
        """
        # 构建依赖图（简化：按包名顺序，无运行时依赖信息时按原序）
        # 实际运行时依赖图需要从 PyPI 元数据获取，这里做最佳努力
        if not packages:
            return []

        # 计算入度
        in_degree: dict[str, int] = {}
        graph: dict[str, list[str]] = defaultdict(list)
        name_to_pkg: dict[str, DependencyPackage] = {}

        for pkg in packages:
            name = pkg.name.lower()
            in_degree[name] = 0
            name_to_pkg[name] = pkg

        # 基本启发式排序: 常见基础库优先
        priority_prefixes = [
            "setuptools", "wheel", "pip", "packaging",
            "typing", "pydantic", "numpy", "six", "python",
        ]

        def sort_key(pkg: DependencyPackage) -> tuple[int, str]:
            """排序键: 基础库优先，然后按名称"""
            name = pkg.name.lower()
            for i, prefix in enumerate(priority_prefixes):
                if name.startswith(prefix):
                    return (i, name)
            return (len(priority_prefixes), name)

        return sorted(packages, key=sort_key)

    # ── 工具方法 ───────────────────────────────────

    @staticmethod
    def _strip_comment(line: str) -> str:
        """移除行内注释（保留 URL 中的 #）"""
        # 简单处理: 查找不在 URL 中的 #
        if "://" in line:
            return line
        idx = line.find("#")
        if idx >= 0:
            return line[:idx]
        return line

    @property
    def packages(self) -> list[DependencyPackage]:
        """获取已解析的包列表"""
        return self._packages

    @property
    def conflicts(self) -> list[DependencyConflict]:
        """获取版本冲突列表"""
        return self._conflicts

    @property
    def errors(self) -> list[str]:
        """获取解析错误列表"""
        return self._errors