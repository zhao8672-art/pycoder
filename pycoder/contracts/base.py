"""合同契约基类 — ModuleContract 与 Layer 定义"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class Layer(enum.StrEnum):
    """模块所属层级 — P/D/C 三层模型"""

    PLATFORM = "P"  # 平台层：不依赖任何业务模块（config/utils/bus/core/observability）
    DOMAIN = "D"  # 领域层：只能依赖 P（ai/brain/memory/evolution/skills/extensions/capabilities）
    COMPOSITE = "C"  # 组合层：可依赖 P 和 D（server/electron）


@dataclass(frozen=True)
class ModuleContract:
    """模块合同 — 每个模块必须声明的边界契约

    三要素：
        1. dependencies: 允许导入的模块列表（输入）
        2. public_api: 通过 __all__ 暴露的符号（输出）
        3. invariants: 可验证的不变式断言（保证）

    可选：
        capabilities: 暴露的能力 ID 列表（domain.action 格式）
        storage_keys: 持久化键声明
        external_io: 外部 IO 声明
    """

    name: str  # 模块名（如 "ai"）
    layer: Layer  # P/D/C 层级
    dependencies: list[str] = field(default_factory=list)  # 允许导入的模块前缀
    public_api: list[str] = field(default_factory=list)  # 暴露的公共符号
    capabilities: list[str] = field(default_factory=list)  # 能力 ID（domain.action）
    invariants: list[str] = field(default_factory=list)  # 不变式描述
    storage_keys: list[str] = field(default_factory=list)  # 持久化键
    external_io: list[str] = field(default_factory=list)  # 外部 IO 声明

    def __post_init__(self) -> None:
        """校验合同基本合法性"""
        if not self.name:
            raise ValueError("模块名不能为空")
        if not isinstance(self.layer, Layer):
            raise TypeError(f"layer 必须是 Layer 枚举，得到 {type(self.layer)}")

    def allows_import(self, module_path: str) -> bool:
        """检查是否允许导入指定模块路径

        Args:
            module_path: 模块路径（如 "pycoder.server.services"）

        Returns:
            True 如果允许导入
        """
        # 允许导入标准库和第三方库
        if not module_path.startswith("pycoder."):
            return True

        # 允许导入自身
        own_prefix = f"pycoder.{self.name}"
        if module_path == own_prefix or module_path.startswith(own_prefix + "."):
            return True

        # 检查是否在声明的依赖中
        for dep in self.dependencies:
            if module_path == dep or module_path.startswith(dep + "."):
                return True

        return False

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于序列化）"""
        return {
            "name": self.name,
            "layer": str(self.layer),
            "dependencies": list(self.dependencies),
            "public_api": list(self.public_api),
            "capabilities": list(self.capabilities),
            "invariants": list(self.invariants),
            "storage_keys": list(self.storage_keys),
            "external_io": list(self.external_io),
        }


# ──────────────────────────────────────────────
# 18 个模块的合同定义（基于全量扫描）
# ──────────────────────────────────────────────

CONTRACTS: list[ModuleContract] = [
    # ── P 层：平台模块（不依赖业务模块）──
    ModuleContract(
        name="config",
        layer=Layer.PLATFORM,
        dependencies=[],
        public_api=["get_config", "get_env", "ModelConfig"],
        invariants=["不依赖任何 pycoder.* 业务模块"],
    ),
    ModuleContract(
        name="utils",
        layer=Layer.PLATFORM,
        dependencies=["pycoder.config"],
        public_api=["log", "safe_read", "safe_write"],
        invariants=["仅依赖 config"],
    ),
    ModuleContract(
        name="bus",
        layer=Layer.PLATFORM,
        dependencies=["pycoder.config", "pycoder.utils"],
        public_api=["capability_bus", "CapabilityRegistry"],
        capabilities=["bus.call", "bus.stream", "bus.emit"],
        invariants=["不依赖任何领域层或组合层模块"],
    ),
    ModuleContract(
        name="core",
        layer=Layer.PLATFORM,
        dependencies=["pycoder.config", "pycoder.utils"],
        public_api=["ports", "adapters", "di"],
        invariants=["ports/ 仅定义 Protocol，不依赖具体实现"],
    ),
    ModuleContract(
        name="safety",
        layer=Layer.PLATFORM,
        dependencies=["pycoder.config", "pycoder.utils"],
        public_api=["PermissionPolicy", "check_path", "validate_command"],
        invariants=["不依赖任何业务模块"],
    ),
    ModuleContract(
        name="observability",
        layer=Layer.PLATFORM,
        dependencies=["pycoder.config", "pycoder.utils"],
        public_api=["traced", "init_sentry"],
        capabilities=["observability.trace.query", "observability.metrics.snapshot"],
        invariants=["可选依赖（Sentry/OTel），缺失时静默降级"],
    ),
    ModuleContract(
        name="providers",
        layer=Layer.PLATFORM,
        dependencies=["pycoder.config", "pycoder.core"],
        public_api=["ModelManager", "LLMProvider"],
        invariants=["不依赖 server/ai/brain"],
    ),
    ModuleContract(
        name="prompts",
        layer=Layer.PLATFORM,
        dependencies=["pycoder.config", "pycoder.utils"],
        public_api=["cache_rules", "canonicalize_messages"],
        invariants=["不依赖任何业务模块"],
    ),
    # ── D 层：领域模块（只能依赖 P）──
    ModuleContract(
        name="ai",
        layer=Layer.DOMAIN,
        dependencies=["pycoder.core", "pycoder.config", "pycoder.utils", "pycoder.prompts"],
        public_api=["DeepAnalyzer", "IterativeGenerator", "FusionEngine"],
        capabilities=["ai.nlu.analyze", "ai.generation.iterate", "ai.fusion.fuse"],
        invariants=["不依赖 pycoder.server", "不依赖 pycoder.brain"],
    ),
    ModuleContract(
        name="brain",
        layer=Layer.DOMAIN,
        dependencies=["pycoder.core", "pycoder.config", "pycoder.utils", "pycoder.ai"],
        public_api=["TaskPlanner", "AgentSwarm"],
        invariants=["不依赖 pycoder.server"],
    ),
    ModuleContract(
        name="memory",
        layer=Layer.DOMAIN,
        dependencies=["pycoder.core", "pycoder.config", "pycoder.utils"],
        public_api=["MemoryStore", "ContextManager"],
        capabilities=["memory.context.retrieve", "memory.facts.store"],
        invariants=["不依赖 pycoder.server"],
    ),
    ModuleContract(
        name="evolution",
        layer=Layer.DOMAIN,
        dependencies=["pycoder.core", "pycoder.config", "pycoder.utils", "pycoder.ai"],
        public_api=["EvolutionEngine"],
        invariants=["不依赖 pycoder.server"],
    ),
    ModuleContract(
        name="skills",
        layer=Layer.DOMAIN,
        dependencies=["pycoder.core", "pycoder.config", "pycoder.utils"],
        public_api=["SkillRegistry", "SkillExecutor"],
        invariants=["不依赖 pycoder.server"],
    ),
    ModuleContract(
        name="extensions",
        layer=Layer.DOMAIN,
        dependencies=["pycoder.core", "pycoder.config", "pycoder.utils"],
        public_api=["ExtensionManager"],
        invariants=["不依赖 pycoder.server"],
    ),
    # core.services.net 和 core.services.external_skills 是 P 层工具，已纳入 core 依赖
    ModuleContract(
        name="capabilities",
        layer=Layer.DOMAIN,
        dependencies=["pycoder.core", "pycoder.bus", "pycoder.config", "pycoder.utils"],
        public_api=["register_editor_capabilities", "register_system_capabilities"],
        capabilities=[
            "editor.code.read",
            "editor.code.write",
            "system.shell.execute",
        ],
        invariants=["不依赖 pycoder.server"],
    ),
    ModuleContract(
        name="lifecycle",
        layer=Layer.DOMAIN,
        dependencies=["pycoder.core", "pycoder.config", "pycoder.utils"],
        public_api=["get_orchestrator"],
        capabilities=["lifecycle.project.create", "lifecycle.project.run"],
        invariants=["不依赖 pycoder.server"],
    ),
    ModuleContract(
        name="gateway",
        layer=Layer.DOMAIN,
        dependencies=["pycoder.core", "pycoder.config", "pycoder.utils"],
        public_api=["get_gateway"],
        capabilities=["gateway.message.send"],
        invariants=["不依赖 pycoder.server"],
    ),
    # ── C 层：组合模块（可依赖 P 和 D）──
    ModuleContract(
        name="server",
        layer=Layer.COMPOSITE,
        dependencies=[
            "pycoder.core",
            "pycoder.bus",
            "pycoder.config",
            "pycoder.utils",
            "pycoder.ai",
            "pycoder.brain",
            "pycoder.memory",
            "pycoder.evolution",
            "pycoder.skills",
            "pycoder.extensions",
            "pycoder.capabilities",
            "pycoder.lifecycle",
            "pycoder.gateway",
            "pycoder.providers",
            "pycoder.prompts",
            "pycoder.safety",
            "pycoder.observability",
        ],
        public_api=["app", "create_app"],
        invariants=["作为应用入口，可依赖所有 P 和 D 层模块"],
    ),
    ModuleContract(
        name="electron",
        layer=Layer.COMPOSITE,
        dependencies=["pycoder.config", "pycoder.utils"],
        public_api=["create_window"],
        invariants=["仅依赖平台层"],
    ),
]


def get_contract(module_name: str) -> ModuleContract | None:
    """获取指定模块的合同"""
    for contract in CONTRACTS:
        if contract.name == module_name:
            return contract
    return None


def all_contracts() -> list[ModuleContract]:
    """获取所有合同"""
    return list(CONTRACTS)
