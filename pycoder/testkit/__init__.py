"""测试工具包 — 能力契约测试基础设施

提供：
    1. @capability_test 装饰器 — 标记能力测试
    2. MockBus — 单元测试用 Mock 能力总线
    3. contract_assert — 契约断言工具

使用示例：
    from pycoder.testkit import capability_test, MockBus

    @capability_test("editor.code.read")
    def test_read_capability():
        bus = MockBus()
        bus.register("editor.code.read", handler)
        result = bus.call("editor.code.read", {"path": "main.py"})
        assert result is not None
"""

from __future__ import annotations

from pycoder.testkit.decorators import capability_test
from pycoder.testkit.mock_bus import MockBus

__all__ = ["capability_test", "MockBus"]
