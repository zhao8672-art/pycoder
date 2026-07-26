"""合同契约中心 — 模块边界声明与自动化检查

每个模块必须声明一个 ModuleContract，明确描述：
1. 输入：依赖什么（dependencies）
2. 输出：暴露什么（public_api）
3. 不变式：保证什么（invariants）
4. 能力清单：暴露的能力 ID（capabilities，domain.action 格式）

使用方式：
    from pycoder.contracts import ModuleContract, Layer

    CONTRACT = ModuleContract(
        name="ai",
        layer=Layer.DOMAIN,
        dependencies=["pycoder.core", "pycoder.config", "pycoder.utils"],
        public_api=["DeepAnalyzer", "IterativeGenerator", "FusionEngine"],
        capabilities=["ai.nlu.analyze", "ai.generation.iterate", "ai.fusion.fuse"],
        invariants=["不依赖 pycoder.server"],
    )

CLI 检查：
    python -m pycoder.contracts check
    python -m pycoder.contracts check --layer D  # 仅检查领域层
"""

from __future__ import annotations

from pycoder.contracts.base import Layer, ModuleContract
from pycoder.contracts.checker import ContractChecker, ContractViolation

__all__ = [
    "Layer",
    "ModuleContract",
    "ContractChecker",
    "ContractViolation",
]
