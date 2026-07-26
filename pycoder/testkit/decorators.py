"""能力测试装饰器 — 标记和验证能力契约测试"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any


def capability_test(
    capability_id: str,
    *,
    description: str = "",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """标记一个测试为能力契约测试

    Args:
        capability_id: 能力 ID（domain.action 格式，如 "editor.code.read"）
        description: 测试描述（可选）

    使用示例：
        @capability_test("editor.code.read")
        def test_read_returns_content():
            ...

    装饰后可通过 `test._capability_id` 和 `test._capability_description` 访问元数据。
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        # 附加元数据
        wrapper._capability_id = capability_id  # type: ignore[attr-defined]
        wrapper._capability_description = description  # type: ignore[attr-defined]
        wrapper._is_capability_test = True  # type: ignore[attr-defined]

        return wrapper

    return decorator


def is_capability_test(func: Callable[..., Any]) -> bool:
    """检查一个函数是否被 @capability_test 标记"""
    return getattr(func, "_is_capability_test", False)


def get_capability_id(func: Callable[..., Any]) -> str | None:
    """获取测试标记的能力 ID"""
    return getattr(func, "_capability_id", None)
