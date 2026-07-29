"""MockBus — 单元测试用 Mock 能力总线

模拟 pycoder.bus.capability_bus 的行为，用于隔离测试能力实现。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any


class MockBus:
    """Mock 能力总线 — 用于单元测试

    使用示例：
        bus = MockBus()
        bus.register("editor.code.read", lambda args: {"content": "hello"})
        result = bus.call("editor.code.read", {"path": "main.py"})
        assert result["content"] == "hello"

        # 验证调用记录
        bus.assert_called("editor.code.read")
        bus.assert_called_with("editor.code.read", {"path": "main.py"})
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Any] = {}
        self._call_records: list[tuple[str, dict[str, Any]]] = []

    def register(self, capability_id: str, handler: Any) -> None:
        """注册能力处理器"""
        self._handlers[capability_id] = handler

    def unregister(self, capability_id: str) -> None:
        """取消注册"""
        self._handlers.pop(capability_id, None)

    def call(self, capability_id: str, args: dict[str, Any] | None = None) -> Any:
        """调用能力（同步）"""
        args = args or {}
        self._call_records.append((capability_id, args))

        handler = self._handlers.get(capability_id)
        if handler is None:
            raise KeyError(f"能力 '{capability_id}' 未注册")

        if asyncio.iscoroutinefunction(handler):
            # 异步处理器，用事件循环运行
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(handler(args))
            finally:
                loop.close()
        return handler(args)

    async def call_async(self, capability_id: str, args: dict[str, Any] | None = None) -> Any:
        """调用能力（异步）"""
        args = args or {}
        self._call_records.append((capability_id, args))

        handler = self._handlers.get(capability_id)
        if handler is None:
            raise KeyError(f"能力 '{capability_id}' 未注册")

        if asyncio.iscoroutinefunction(handler):
            return await handler(args)
        return handler(args)

    def stream(self, capability_id: str, args: dict[str, Any] | None = None) -> AsyncIterator[Any]:
        """流式调用能力（返回异步迭代器）"""
        args = args or {}
        self._call_records.append((capability_id, args))

        async def _stream() -> AsyncIterator[Any]:
            handler = self._handlers.get(capability_id)
            if handler is None:
                raise KeyError(f"能力 '{capability_id}' 未注册")
            if asyncio.isasyncgenfunction(handler):
                async for item in handler(args):
                    yield item
            else:
                # 非生成器，返回单个结果
                result = (
                    await handler(args) if asyncio.iscoroutinefunction(handler) else handler(args)
                )
                yield result

        return _stream()

    # ── 断言工具 ──

    def assert_called(self, capability_id: str) -> None:
        """断言指定能力被调用过"""
        calls = [r for r in self._call_records if r[0] == capability_id]
        assert calls, f"能力 '{capability_id}' 未被调用"

    def assert_called_with(self, capability_id: str, expected_args: dict[str, Any]) -> None:
        """断言指定能力以特定参数被调用"""
        calls = [r for r in self._call_records if r[0] == capability_id]
        assert calls, f"能力 '{capability_id}' 未被调用"
        assert any(
            r[1] == expected_args for r in calls
        ), f"能力 '{capability_id}' 未以 {expected_args} 被调用，实际调用：{[r[1] for r in calls]}"

    def assert_not_called(self, capability_id: str) -> None:
        """断言指定能力未被调用"""
        calls = [r for r in self._call_records if r[0] == capability_id]
        assert not calls, f"能力 '{capability_id}' 不应被调用，但被调用了 {len(calls)} 次"

    @property
    def call_count(self) -> int:
        """总调用次数"""
        return len(self._call_records)

    def reset(self) -> None:
        """重置所有调用记录"""
        self._call_records.clear()
