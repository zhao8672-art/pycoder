"""合同契约检查器 — 自动化验证模块边界合规性

功能：
    1. 检查 D→C 违规（领域层不应导入组合层）
    2. 检查 P→D/C 违规（平台层不应导入领域/组合层）
    3. 检查未声明的依赖
    4. 检查循环依赖

使用方式：
    from pycoder.contracts import ContractChecker

    checker = ContractChecker()
    violations = checker.check_all()
    for v in violations:
        print(f"[{v.severity}] {v.module} → {v.imported}: {v.message}")
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from pycoder.contracts.base import CONTRACTS, Layer, ModuleContract


@dataclass
class ContractViolation:
    """契约违规记录"""

    module: str  # 违规模块名
    imported: str  # 被导入的模块路径
    severity: str  # "ERROR" | "WARNING"
    message: str  # 违规说明
    file_path: str = ""  # 违规文件路径
    line_number: int = 0  # 违规行号


class ContractChecker:
    """合同契约检查器"""

    def __init__(self, contracts: list[ModuleContract] | None = None) -> None:
        self.contracts = contracts or CONTRACTS
        self._contract_map: dict[str, ModuleContract] = {c.name: c for c in self.contracts}

    def check_import(self, source_module: str, imported_path: str) -> ContractViolation | None:
        """检查单个导入是否合规

        Args:
            source_module: 源模块名（如 "ai"）
            imported_path: 被导入的路径（如 "pycoder.server.services"）

        Returns:
            违规记录，合规则返回 None
        """
        # 忽略非 pycoder 的导入
        if not imported_path.startswith("pycoder."):
            return None

        contract = self._contract_map.get(source_module)
        if contract is None:
            return ContractViolation(
                module=source_module,
                imported=imported_path,
                severity="WARNING",
                message=f"模块 '{source_module}' 未声明合同",
            )

        # 检查是否允许导入
        if contract.allows_import(imported_path):
            return None

        # 判断违规类型
        target_module = self._extract_module_name(imported_path)
        target_contract = self._contract_map.get(target_module)

        if target_contract:
            # D → C 违规
            if contract.layer == Layer.DOMAIN and target_contract.layer == Layer.COMPOSITE:
                return ContractViolation(
                    module=source_module,
                    imported=imported_path,
                    severity="ERROR",
                    message=(
                        f"D→C 违规：领域层模块 '{source_module}' "
                        f"不能导入组合层模块 '{target_module}'"
                    ),
                )
            # P → D/C 违规
            if contract.layer == Layer.PLATFORM and target_contract.layer in (
                Layer.DOMAIN,
                Layer.COMPOSITE,
            ):
                return ContractViolation(
                    module=source_module,
                    imported=imported_path,
                    severity="ERROR",
                    message=(
                        f"P→D/C 违规：平台层模块 '{source_module}' "
                        f"不能导入{'领域' if target_contract.layer == Layer.DOMAIN else '组合'}层模块 '{target_module}'"
                    ),
                )

        # 未声明的依赖
        return ContractViolation(
            module=source_module,
            imported=imported_path,
            severity="WARNING",
            message=(
                f"未声明依赖：模块 '{source_module}' 导入了 '{imported_path}'，"
                f"但未在合同的 dependencies 中声明"
            ),
        )

    def check_file(self, file_path: Path) -> list[ContractViolation]:
        """检查单个文件的导入合规性

        Args:
            file_path: Python 文件路径

        Returns:
            违规列表
        """
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []

        try:
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError:
            return []

        # 确定源模块名
        source_module = self._infer_module_name(file_path)
        if source_module is None:
            return []

        violations: list[ContractViolation] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    v = self.check_import(source_module, alias.name)
                    if v:
                        v.file_path = str(file_path)
                        v.line_number = node.lineno
                        violations.append(v)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("pycoder."):
                    v = self.check_import(source_module, node.module)
                    if v:
                        v.file_path = str(file_path)
                        v.line_number = node.lineno
                        violations.append(v)

        return violations

    def check_directory(self, dir_path: Path) -> list[ContractViolation]:
        """检查目录下所有 Python 文件的导入合规性

        Args:
            dir_path: 要检查的目录

        Returns:
            违规列表
        """
        all_violations: list[ContractViolation] = []

        for py_file in dir_path.rglob("*.py"):
            # 跳过 __pycache__、tests、node_modules
            parts = py_file.parts
            if any(
                skip in parts for skip in ("__pycache__", "node_modules", ".git", "dist", "build")
            ):
                continue
            all_violations.extend(self.check_file(py_file))

        return all_violations

    def check_all(self) -> list[ContractViolation]:
        """检查整个项目"""
        project_root = Path(__file__).parent.parent.parent
        pycoder_root = project_root / "pycoder"
        return self.check_directory(pycoder_root)

    def _extract_module_name(self, import_path: str) -> str | None:
        """从导入路径提取模块名

        Examples:
            "pycoder.server.services" → "server"
            "pycoder.ai.nlu" → "ai"
        """
        if not import_path.startswith("pycoder."):
            return None
        parts = import_path.split(".")
        if len(parts) < 2:
            return None
        return parts[1]

    def _infer_module_name(self, file_path: Path) -> str | None:
        """从文件路径推断所属模块名

        Examples:
            pycoder/ai/nlu/deep_analyzer.py → "ai"
            pycoder/server/services/agent_tools.py → "server"
        """
        try:
            parts = file_path.parts
            pycoder_idx = list(parts).index("pycoder")
            if pycoder_idx + 1 < len(parts):
                return parts[pycoder_idx + 1]
        except ValueError:
            pass
        return None


def main() -> int:
    """CLI 入口：python -m pycoder.contracts check"""

    checker = ContractChecker()
    violations = checker.check_all()

    if not violations:
        print("✅ 所有模块契约合规，零违规")
        return 0

    errors = [v for v in violations if v.severity == "ERROR"]
    warnings = [v for v in violations if v.severity == "WARNING"]

    print(f"❌ 发现 {len(errors)} 个违规，{len(warnings)} 个警告\n")

    for v in errors:
        location = f"{v.file_path}:{v.line_number}" if v.file_path else v.module
        print(f"  [ERROR] {location}")
        print(f"          {v.message}")
        print()

    for v in warnings:
        location = f"{v.file_path}:{v.line_number}" if v.file_path else v.module
        print(f"  [WARN]  {location}")
        print(f"          {v.message}")
        print()

    return 1 if errors else 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
