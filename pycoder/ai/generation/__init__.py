"""多策略代码生成器 — 弥补与 Codex -6.0 的代码生成差距

五种生成策略:
  SINGLE_PASS  → 一次生成 (简单代码, <10行)
  ITERATIVE    → 生成→验证→优化循环 (复杂算法)
  TEST_DRIVEN  → 测试→生成→验证 (有测试用例)
  SPEC_DRIVEN  → 规约→生成→验证 (有接口定义)
  TEMPLATE_BASED → 模板匹配 (常见模式)
"""

from __future__ import annotations

from pycoder.ai.generation.single_pass import SinglePassGenerator
from pycoder.ai.generation.iterative import IterativeGenerator
from pycoder.ai.generation.test_driven import TestDrivenGenerator
from pycoder.ai.generation.multi_strategy import MultiStrategyGenerator, get_generator

__all__ = [
    "SinglePassGenerator",
    "IterativeGenerator",
    "TestDrivenGenerator",
    "MultiStrategyGenerator",
    "get_generator",
]
