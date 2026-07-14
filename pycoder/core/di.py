"""P0: Dependency Injection Container — 轻量级注册表

所有核心依赖通过此容器注册和解析，消除硬 import。
消费方依赖 Registry 而非具体实现。

用法:
    # 注册（启动时）
    from pycoder.core.di import registry
    registry.register(LLMProvider, BridgeLLMProvider(bridge))

    # 解析（运行时）
    llm = registry.resolve(LLMProvider)
    response = await llm.generate("Hello")

设计原则:
    - 零外部依赖（纯标准库）
    - 按 Protocol 类型索引（而非字符串 key）
    - 支持实例注册和工厂延迟初始化
    - 线程安全（asyncio 单事件循环场景下自然安全）
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


class Registry:
    """依赖注入注册表 — 按 Protocol 类型注册/解析

    所有核心依赖（LLMProvider、CodeSandbox、FileSystem）
    通过此容器注册和解析。启动时在 app.py lifespan 中注册，
    运行时通过 registry.resolve() 获取。

    线程安全说明:
        当前设计针对 asyncio 单事件循环场景。
        多线程场景下可加 threading.Lock 保护 _instances/_factories。
    """

    def __init__(self) -> None:
        self._instances: dict[type, Any] = {}
        self._factories: dict[type, Callable[[], Any]] = {}

    # ── 注册 ──

    def register(
        self,
        proto: type[T],
        implementation: T | None = None,
        *,
        factory: Callable[[], T] | None = None,
    ) -> None:
        """注册一个 Protocol 的实现。

        三种用法:
            registry.register(LLMProvider, my_llm)          # 实例（立即初始化）
            registry.register(LLMProvider, factory=create)  # 工厂（延迟初始化，首次 resolve 时调用）

        Raises:
            ValueError: 未提供 implementation 或 factory
            TypeError: proto 不是 type
        """
        if not isinstance(proto, type):
            raise TypeError(f"proto 必须是类型，收到 {type(proto).__name__}")

        if implementation is not None:
            self._instances[proto] = implementation
            self._factories.pop(proto, None)  # 覆盖工厂
        elif factory is not None:
            self._factories[proto] = factory
            self._instances.pop(proto, None)  # 覆盖实例
        else:
            raise ValueError(f"注册 {proto.__name__} 时必须提供 implementation= 或 factory= 参数")

    def register_instance(self, proto: type[T], implementation: T) -> None:
        """便捷方法: 注册已创建的实例"""
        self.register(proto, implementation=implementation)

    def register_factory(self, proto: type[T], factory: Callable[[], T]) -> None:
        """便捷方法: 注册工厂函数"""
        self.register(proto, factory=factory)

    # ── 解析 ──

    def resolve(self, proto: type[T]) -> T:
        """解析依赖。先查实例，再查工厂（工厂结果会被缓存）。

        Raises:
            LookupError: proto 未注册
        """
        # 1. 直接实例
        if proto in self._instances:
            return self._instances[proto]

        # 2. 工厂（延迟初始化 + 缓存）
        if proto in self._factories:
            instance = self._factories[proto]()
            self._instances[proto] = instance
            return instance

        raise LookupError(
            f"未注册: {getattr(proto, '__name__', str(proto))}。"
            f"请在启动时调用 registry.register({getattr(proto, '__name__', '?')}, ...)"
        )

    def resolve_optional(self, proto: type[T]) -> T | None:
        """安全解析 — 未注册时返回 None 而非抛异常"""
        if proto in self._instances:
            return self._instances[proto]
        if proto in self._factories:
            instance = self._factories[proto]()
            self._instances[proto] = instance
            return instance
        return None

    # ── 查询 ──

    def is_registered(self, proto: type) -> bool:
        """检查 Protocol 是否已注册"""
        return proto in self._instances or proto in self._factories

    def list_registered(self) -> list[str]:
        """列出所有已注册的 Protocol 名称"""
        names: set[str] = set()
        for p in self._instances:
            names.add(getattr(p, "__name__", str(p)))
        for p in self._factories:
            names.add(getattr(p, "__name__", str(p)))
        return sorted(names)

    # ── 生命周期 ──

    def clear(self) -> None:
        """清空所有注册（测试/重启用）"""
        self._instances.clear()
        self._factories.clear()

    def reset(self) -> None:
        """同 clear() — 语义别名"""
        self.clear()


# ── 全局单例 ──

registry = Registry()
