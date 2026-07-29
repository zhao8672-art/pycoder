"""契约断言工具 — 在测试中验证契约合规性"""

from __future__ import annotations

from pycoder.contracts.base import Layer, get_contract


def assert_contract_compliant(module_name: str, imported_paths: list[str]) -> None:
    """断言模块的导入列表符合契约

    Args:
        module_name: 模块名
        imported_paths: 该模块实际导入的所有 pycoder.* 路径

    Raises:
        AssertionError: 如果存在违规导入
    """
    contract = get_contract(module_name)
    if contract is None:
        # 未声明合同的模块，跳过
        return

    violations: list[str] = []

    for path in imported_paths:
        if not path.startswith("pycoder."):
            continue

        # 允许导入自身
        own_prefix = f"pycoder.{module_name}"
        if path == own_prefix or path.startswith(own_prefix + "."):
            continue

        # 检查是否在声明依赖中
        if contract.allows_import(path):
            continue

        violations.append(path)

    assert (
        not violations
    ), f"模块 '{module_name}' 存在 {len(violations)} 个违规导入：\n" + "\n".join(
        f"  - {v}" for v in violations
    )


def assert_layer_rule(source_layer: Layer, target_layer: Layer) -> None:
    """断言层级依赖规则

    规则：
        C → D ✅
        C → P ✅
        D → P ✅
        D → C ❌
        P → anything ❌
    """
    if source_layer == Layer.PLATFORM and target_layer in (
        Layer.DOMAIN,
        Layer.COMPOSITE,
    ):
        raise AssertionError(
            f"P→D/C 违规：平台层模块不能依赖{'领域' if target_layer == Layer.DOMAIN else '组合'}层模块"
        )

    if source_layer == Layer.DOMAIN and target_layer == Layer.COMPOSITE:
        raise AssertionError("D→C 违规：领域层模块不能依赖组合层模块")
