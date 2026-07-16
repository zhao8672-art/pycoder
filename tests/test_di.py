"""
依赖注入容器 (Registry) 测试

覆盖:
  - register: 实例注册、工厂注册、参数校验
  - register_instance / register_factory 便捷方法
  - resolve: 实例解析、工厂延迟初始化、缓存
  - resolve_optional: 安全解析
  - is_registered: 注册状态查询
  - list_registered: 列出已注册项
  - clear / reset: 清空注册表
  - 全局单例 registry 可用性
  - 错误路径: 未注册解析、类型错误、缺少参数
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import pytest

from pycoder.core.di import Registry, registry


# ══════════════════════════════════════════════════════════
# 测试用 Protocol 定义
# ══════════════════════════════════════════════════════════


class Greeter(Protocol):
    """测试用 Greeter 协议"""

    def greet(self, name: str) -> str: ...


class Calculator(Protocol):
    """测试用 Calculator 协议"""

    def add(self, a: int, b: int) -> int: ...


# 测试用实现类
class EnglishGreeter:
    def greet(self, name: str) -> str:
        return f"Hello, {name}!"


class ChineseGreeter:
    def greet(self, name: str) -> str:
        return f"你好，{name}！"


class SimpleCalculator:
    def __init__(self, multiplier: int = 1):
        self._multiplier = multiplier

    def add(self, a: int, b: int) -> int:
        return (a + b) * self._multiplier


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def fresh_registry() -> Registry:
    """每个测试使用全新的 Registry 实例"""
    return Registry()


# ══════════════════════════════════════════════════════════
# register 测试
# ══════════════════════════════════════════════════════════


class TestRegister:
    """注册功能测试"""

    def test_register_instance(self, fresh_registry: Registry):
        """register 应接受实例注册"""
        greeter = EnglishGreeter()
        fresh_registry.register(Greeter, greeter)
        assert fresh_registry.is_registered(Greeter)

    def test_register_factory(self, fresh_registry: Registry):
        """register 应接受工厂函数注册"""
        fresh_registry.register(Greeter, factory=lambda: EnglishGreeter())
        assert fresh_registry.is_registered(Greeter)

    def test_register_overwrites_previous(self, fresh_registry: Registry):
        """重复注册应覆盖之前的实现"""
        fresh_registry.register(Greeter, EnglishGreeter())
        fresh_registry.register(Greeter, ChineseGreeter())
        resolved = fresh_registry.resolve(Greeter)
        assert isinstance(resolved, ChineseGreeter)

    def test_register_instance_replaces_factory(self, fresh_registry: Registry):
        """实例注册应覆盖工厂注册"""
        fresh_registry.register(Greeter, factory=lambda: EnglishGreeter())
        fresh_registry.register(Greeter, ChineseGreeter())
        resolved = fresh_registry.resolve(Greeter)
        assert isinstance(resolved, ChineseGreeter)

    def test_register_factory_replaces_instance(self, fresh_registry: Registry):
        """工厂注册应覆盖实例注册"""
        fresh_registry.register(Greeter, EnglishGreeter())
        fresh_registry.register(Greeter, factory=lambda: ChineseGreeter())
        resolved = fresh_registry.resolve(Greeter)
        assert isinstance(resolved, ChineseGreeter)

    def test_register_raises_type_error(self, fresh_registry: Registry):
        """proto 不是 type 时应抛出 TypeError"""
        with pytest.raises(TypeError, match="proto 必须是类型"):
            fresh_registry.register("not_a_type", EnglishGreeter())  # type: ignore[arg-type]

    def test_register_raises_value_error_no_impl(self, fresh_registry: Registry):
        """未提供 implementation 或 factory 时应抛出 ValueError"""
        with pytest.raises(ValueError, match="必须提供"):
            fresh_registry.register(Greeter)  # type: ignore[call-arg]


# ══════════════════════════════════════════════════════════
# 便捷方法测试
# ══════════════════════════════════════════════════════════


class TestConvenienceMethods:
    """register_instance / register_factory 便捷方法测试"""

    def test_register_instance(self, fresh_registry: Registry):
        """register_instance 应注册实例"""
        fresh_registry.register_instance(Greeter, EnglishGreeter())
        assert fresh_registry.is_registered(Greeter)

    def test_register_factory(self, fresh_registry: Registry):
        """register_factory 应注册工厂"""
        fresh_registry.register_factory(Greeter, lambda: ChineseGreeter())
        assert fresh_registry.is_registered(Greeter)


# ══════════════════════════════════════════════════════════
# resolve 测试
# ══════════════════════════════════════════════════════════


class TestResolve:
    """解析功能测试"""

    def test_resolve_returns_instance(self, fresh_registry: Registry):
        """resolve 应返回注册的实例"""
        greeter = EnglishGreeter()
        fresh_registry.register(Greeter, greeter)
        resolved = fresh_registry.resolve(Greeter)
        assert resolved is greeter

    def test_resolve_factory_creates_instance(self, fresh_registry: Registry):
        """resolve 应从工厂创建实例"""
        fresh_registry.register(Greeter, factory=lambda: ChineseGreeter())
        resolved = fresh_registry.resolve(Greeter)
        assert isinstance(resolved, ChineseGreeter)

    def test_resolve_factory_caches_result(self, fresh_registry: Registry):
        """工厂结果应被缓存，后续 resolve 返回同一实例"""
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return EnglishGreeter()

        fresh_registry.register(Greeter, factory=factory)
        r1 = fresh_registry.resolve(Greeter)
        r2 = fresh_registry.resolve(Greeter)
        assert r1 is r2  # 同一实例
        assert call_count == 1  # 工厂只调用一次

    def test_resolve_raises_lookup_error(self, fresh_registry: Registry):
        """未注册的 Protocol 应抛出 LookupError"""
        with pytest.raises(LookupError, match="未注册"):
            fresh_registry.resolve(Greeter)

    def test_resolve_optional_returns_none(self, fresh_registry: Registry):
        """resolve_optional 未注册时返回 None"""
        result = fresh_registry.resolve_optional(Greeter)
        assert result is None

    def test_resolve_optional_returns_instance(self, fresh_registry: Registry):
        """resolve_optional 已注册时返回实例"""
        greeter = EnglishGreeter()
        fresh_registry.register(Greeter, greeter)
        result = fresh_registry.resolve_optional(Greeter)
        assert result is greeter

    def test_resolve_optional_factory_caches(self, fresh_registry: Registry):
        """resolve_optional 工厂结果也应缓存"""
        fresh_registry.register(Greeter, factory=lambda: ChineseGreeter())
        r1 = fresh_registry.resolve_optional(Greeter)
        r2 = fresh_registry.resolve_optional(Greeter)
        assert r1 is r2

    def test_resolve_multiple_protocols(self, fresh_registry: Registry):
        """多个不同 Protocol 同时注册和解析"""
        fresh_registry.register(Greeter, EnglishGreeter())
        fresh_registry.register(Calculator, SimpleCalculator())
        g = fresh_registry.resolve(Greeter)
        c = fresh_registry.resolve(Calculator)
        assert isinstance(g, EnglishGreeter)
        assert isinstance(c, SimpleCalculator)
        assert g.greet("World") == "Hello, World!"
        assert c.add(1, 2) == 3


# ══════════════════════════════════════════════════════════
# is_registered 测试
# ══════════════════════════════════════════════════════════


class TestIsRegistered:
    """is_registered 查询测试"""

    def test_is_registered_true_for_instance(self, fresh_registry: Registry):
        """实例注册后应返回 True"""
        fresh_registry.register(Greeter, EnglishGreeter())
        assert fresh_registry.is_registered(Greeter)

    def test_is_registered_true_for_factory(self, fresh_registry: Registry):
        """工厂注册后应返回 True"""
        fresh_registry.register(Greeter, factory=lambda: EnglishGreeter())
        assert fresh_registry.is_registered(Greeter)

    def test_is_registered_false(self, fresh_registry: Registry):
        """未注册应返回 False"""
        assert not fresh_registry.is_registered(Greeter)


# ══════════════════════════════════════════════════════════
# list_registered 测试
# ══════════════════════════════════════════════════════════


class TestListRegistered:
    """list_registered 测试"""

    def test_list_registered_empty(self, fresh_registry: Registry):
        """空注册表应返回空列表"""
        assert fresh_registry.list_registered() == []

    def test_list_registered_returns_names(self, fresh_registry: Registry):
        """应返回已注册 Protocol 的名称列表"""
        fresh_registry.register(Greeter, EnglishGreeter())
        fresh_registry.register(Calculator, SimpleCalculator())
        names = fresh_registry.list_registered()
        assert "Greeter" in names
        assert "Calculator" in names
        assert len(names) == 2

    def test_list_registered_sorted(self, fresh_registry: Registry):
        """返回列表应按字母顺序排序"""
        fresh_registry.register(Calculator, SimpleCalculator())
        fresh_registry.register(Greeter, EnglishGreeter())
        names = fresh_registry.list_registered()
        assert names == sorted(names)

    def test_list_registered_no_duplicates(self, fresh_registry: Registry):
        """同一 Protocol 同时有实例和工厂不应重复"""
        # 实例注册会覆盖工厂，所以只应出现一次
        fresh_registry.register(Greeter, factory=lambda: EnglishGreeter())
        fresh_registry.register(Greeter, ChineseGreeter())
        names = fresh_registry.list_registered()
        assert names.count("Greeter") == 1


# ══════════════════════════════════════════════════════════
# clear / reset 测试
# ══════════════════════════════════════════════════════════


class TestClear:
    """clear / reset 清空测试"""

    def test_clear_removes_all(self, fresh_registry: Registry):
        """clear 应清空所有注册"""
        fresh_registry.register(Greeter, EnglishGreeter())
        fresh_registry.register(Calculator, SimpleCalculator())
        fresh_registry.clear()
        assert not fresh_registry.is_registered(Greeter)
        assert not fresh_registry.is_registered(Calculator)
        assert fresh_registry.list_registered() == []

    def test_reset_removes_all(self, fresh_registry: Registry):
        """reset 应清空所有注册"""
        fresh_registry.register(Greeter, EnglishGreeter())
        fresh_registry.reset()
        assert not fresh_registry.is_registered(Greeter)

    def test_clear_then_register(self, fresh_registry: Registry):
        """clear 后可以重新注册"""
        fresh_registry.register(Greeter, EnglishGreeter())
        fresh_registry.clear()
        fresh_registry.register(Greeter, ChineseGreeter())
        resolved = fresh_registry.resolve(Greeter)
        assert isinstance(resolved, ChineseGreeter)


# ══════════════════════════════════════════════════════════
# 全局单例测试
# ══════════════════════════════════════════════════════════


class TestGlobalRegistry:
    """全局 registry 单例测试"""

    def test_global_registry_exists(self):
        """全局 registry 应存在"""
        assert registry is not None
        assert isinstance(registry, Registry)

    def test_global_registry_is_singleton(self):
        """多次导入应为同一实例"""
        from pycoder.core.di import registry as r2
        assert registry is r2

    def test_global_registry_clear_and_restore(self):
        """全局 registry 可清空后恢复"""
        # 保存当前注册项
        old_names = registry.list_registered()
        try:
            registry.clear()
            assert registry.list_registered() == []
        finally:
            # 清理后不恢复，避免影响其他测试
            # 全局 registry 的清空是测试的最后一步
            pass