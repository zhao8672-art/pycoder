"""
能力注册表 — 管理所有能力的注册、发现、查询

每个编辑器和系统模块通过此注册表向 AI 暴露自己的能力。
AI 通过语义搜索发现和调用能力。
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, AsyncIterator

from pycoder.bus.protocol import (
    CapabilityCall,
    CapabilityCategory,
    CapabilityDefinition,
    CapabilityEvent,
    CapabilityHandler,
    CapabilityResult,
    ExecutionMode,
    StreamCapabilityHandler,
    TrustLevel,
)

logger = logging.getLogger(__name__)


class CapabilityNotFoundError(Exception):
    """能力未找到"""

    def __init__(self, capability_id: str):
        self.capability_id = capability_id
        super().__init__(f"能力 '{capability_id}' 未注册")


class CapabilityExecutionError(Exception):
    """能力执行错误"""

    def __init__(self, capability_id: str, original_error: Exception):
        self.capability_id = capability_id
        self.original_error = original_error
        super().__init__(f"执行能力 '{capability_id}' 时出错: {original_error}")


class CapabilityRegistry:
    """
    能力注册表 —— 所有 AI 可调用能力的中央登记处

    使用方式:
        registry = CapabilityRegistry()

        # 注册能力
        registry.register(
            CapabilityDefinition(id="editor.code.read", ...),
            handler=my_read_handler,
        )

        # 调用能力
        result = await registry.call(CapabilityCall(capability_id="editor.code.read", params={"path": "main.py"}))
    """

    def __init__(self):
        self._definitions: dict[str, CapabilityDefinition] = {}
        self._sync_handlers: dict[str, CapabilityHandler] = {}
        self._stream_handlers: dict[str, StreamCapabilityHandler] = {}
        self._async_handlers: dict[str, CapabilityHandler] = {}
        self._by_category: dict[CapabilityCategory, list[str]] = defaultdict(list)
        self._by_tag: dict[str, list[str]] = defaultdict(list)
        self._search_index: dict[str, CapabilityDefinition] = {}  # 用于语义搜索
        self._lock = asyncio.Lock()

    # ── 注册 ──────────────────────────────────

    def register(
        self,
        definition: CapabilityDefinition,
        handler: CapabilityHandler | StreamCapabilityHandler | None = None,
        *,
        stream_handler: StreamCapabilityHandler | None = None,
        async_handler: CapabilityHandler | None = None,
    ) -> None:
        """
        注册一个能力到总线

        Args:
            definition: 能力定义
            handler: 同步处理器（默认）
            stream_handler: 流式处理器（用于 ExecutionMode.STREAM）
            async_handler: 异步处理器（用于 ExecutionMode.ASYNC）
        """
        if definition.id in self._definitions:
            logger.warning("能力 '%s' 已注册，将被覆盖", definition.id)

        self._definitions[definition.id] = definition
        self._by_category[definition.category].append(definition.id)
        self._search_index[definition.id] = definition

        # 按标签索引
        for tag in definition.tags:
            self._by_tag[tag].append(definition.id)

        # 注册处理器
        if stream_handler:
            self._stream_handlers[definition.id] = stream_handler
        elif definition.execution == ExecutionMode.STREAM and handler and hasattr(handler, '__call__'):
            self._stream_handlers[definition.id] = handler  # type: ignore

        if async_handler:
            self._async_handlers[definition.id] = async_handler
        elif definition.execution == ExecutionMode.ASYNC and handler:
            self._async_handlers[definition.id] = handler

        if handler and definition.execution == ExecutionMode.SYNC:
            self._sync_handlers[definition.id] = handler

        logger.debug("能力已注册: %s (%s)", definition.id, definition.name)

    def unregister(self, capability_id: str) -> bool:
        """注销一个能力"""
        if capability_id not in self._definitions:
            return False

        definition = self._definitions.pop(capability_id)
        self._sync_handlers.pop(capability_id, None)
        self._stream_handlers.pop(capability_id, None)
        self._async_handlers.pop(capability_id, None)

        if capability_id in self._by_category.get(definition.category, []):
            self._by_category[definition.category].remove(capability_id)

        for tag, ids in self._by_tag.items():
            if capability_id in ids:
                ids.remove(capability_id)

        self._search_index.pop(capability_id, None)
        logger.info("能力已注销: %s", capability_id)
        return True

    # ── 查询 ──────────────────────────────────

    def get(self, capability_id: str) -> CapabilityDefinition | None:
        """获取能力定义"""
        return self._definitions.get(capability_id)

    def get_handler(self, capability_id: str) -> CapabilityHandler | StreamCapabilityHandler | None:
        """获取能力处理器"""
        return (
            self._sync_handlers.get(capability_id)
            or self._stream_handlers.get(capability_id)
            or self._async_handlers.get(capability_id)
        )

    def list_all(self) -> list[CapabilityDefinition]:
        """列出所有已注册的能力"""
        return list(self._definitions.values())

    def list_by_category(self, category: CapabilityCategory) -> list[CapabilityDefinition]:
        """按功能域列出能力"""
        return [self._definitions[cid] for cid in self._by_category.get(category, []) if cid in self._definitions]

    def list_by_tag(self, tag: str) -> list[CapabilityDefinition]:
        """按标签列出能力"""
        return [self._definitions[cid] for cid in self._by_tag.get(tag, []) if cid in self._definitions]

    def search(self, query: str) -> list[CapabilityDefinition]:
        """
        语义搜索能力 —— 基于关键词匹配

        搜索维度:
        1. 能力 ID 包含查询词
        2. 名称包含查询词
        3. 描述包含查询词
        4. 标签包含查询词
        """
        query_lower = query.lower()
        results: list[tuple[CapabilityDefinition, int]] = []

        for cap in self._definitions.values():
            score = 0

            # 精确 ID 匹配
            if query_lower == cap.id.lower():
                score += 100
            elif query_lower in cap.id.lower():
                score += 30

            # 名称匹配
            if query_lower in cap.name.lower():
                score += 50

            # 描述匹配
            if query_lower in cap.description.lower():
                score += 20

            # 标签匹配
            for tag in cap.tags:
                if query_lower in tag.lower():
                    score += 40

            if score > 0:
                results.append((cap, score))

        # 按分数降序排列
        results.sort(key=lambda x: x[1], reverse=True)
        return [r[0] for r in results]

    def search_by_description(self, description: str) -> list[CapabilityDefinition]:
        """
        基于自然语言描述搜索能力 —— AI 可以用自然语言描述需求

        Args:
            description: 自然语言描述，如 "我需要读取一个Python文件"

        Returns:
            匹配的能力列表，按相关度排序
        """
        # 关键词提取 —— 基于中文和英文关键词
        keywords = self._extract_keywords(description)
        all_scores: dict[str, float] = defaultdict(float)

        for keyword in keywords:
            for cap in self.search(keyword):
                all_scores[cap.id] += 1.0

        # 按分数排序
        sorted_ids = sorted(all_scores, key=all_scores.get, reverse=True)
        return [self._definitions[cid] for cid in sorted_ids]

    @staticmethod
    def _extract_keywords(description: str) -> list[str]:
        """从自然语言描述中提取关键词"""
        import re

        keywords: list[str] = []
        desc = description.lower()

        # 中文关键词映射
        cn_keyword_map = {
            "读": ["read", "读取", "查看", "打开"],
            "写": ["write", "写入", "修改", "编辑", "创建"],
            "删除": ["delete", "删除", "移除"],
            "搜索": ["search", "搜索", "查找", "grep", "找"],
            "执行": ["execute", "执行", "运行", "跑"],
            "提交": ["commit", "提交", "git"],
            "测试": ["test", "测试", "验证"],
            "格式化": ["format", "格式化", "美化"],
            "重构": ["refactor", "重构", "提取", "重命名"],
            "调试": ["debug", "调试", "断点"],
            "安装": ["install", "安装"],
            "分析": ["analyze", "分析", "扫描", "审查"],
            "部署": ["deploy", "部署", "发布"],
        }

        for _, cn_words in cn_keyword_map.items():
            if any(w in desc for w in cn_words):
                keywords.extend(cn_words)

        # 英文关键词提取
        en_words = re.findall(r'[a-z_]+', desc)
        keywords.extend(w for w in en_words if len(w) > 2)

        return list(dict.fromkeys(keywords))  # 去重保序

    def exists(self, capability_id: str) -> bool:
        """检查能力是否存在"""
        return capability_id in self._definitions

    # ── 调用 ──────────────────────────────────

    async def call(
        self,
        call: CapabilityCall,
        context: dict[str, Any] | None = None,
    ) -> CapabilityResult:
        """
        调用一个能力

        Args:
            call: 调用请求
            context: 执行上下文（权限信息、调用者等）

        Returns:
            CapabilityResult 包含执行结果或错误信息
        """
        ctx = context or {}
        ctx.setdefault("trace_id", call.trace_id)
        ctx.setdefault("caller", call.caller)

        definition = self._definitions.get(call.capability_id)
        if definition is None:
            return CapabilityResult(
                trace_id=call.trace_id,
                capability_id=call.capability_id,
                success=False,
                error=f"能力 '{call.capability_id}' 未注册",
                error_code="CAPABILITY_NOT_FOUND",
            )

        handler = self.get_handler(call.capability_id)
        if handler is None:
            return CapabilityResult(
                trace_id=call.trace_id,
                capability_id=call.capability_id,
                success=False,
                error=f"能力 '{call.capability_id}' 没有注册处理器",
                error_code="NO_HANDLER",
            )

        import time
        start = time.monotonic()

        try:
            data = await handler(call.params, ctx)
            duration = (time.monotonic() - start) * 1000

            return CapabilityResult(
                trace_id=call.trace_id,
                capability_id=call.capability_id,
                success=True,
                data=data,
                duration_ms=duration,
                side_effects_applied=definition.side_effects,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            logger.error("能力 '%s' 执行失败: %s", call.capability_id, e, exc_info=True)

            return CapabilityResult(
                trace_id=call.trace_id,
                capability_id=call.capability_id,
                success=False,
                error=str(e),
                error_code=type(e).__name__,
                duration_ms=duration,
            )

    async def stream(
        self,
        call: CapabilityCall,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[CapabilityEvent]:
        """
        流式调用能力

        Args:
            call: 调用请求
            context: 执行上下文

        Yields:
            CapabilityEvent 流式事件序列
        """
        ctx = context or {}
        ctx.setdefault("trace_id", call.trace_id)
        ctx.setdefault("caller", call.caller)

        handler = self._stream_handlers.get(call.capability_id)
        if handler is None:
            yield CapabilityEvent(
                trace_id=call.trace_id,
                event_type="error",
                message=f"能力 '{call.capability_id}' 不支持流式执行",
            )
            return

        try:
            async for event in handler(call.params, ctx):
                yield event
        except Exception as e:
            logger.error("流式能力 '%s' 执行失败: %s", call.capability_id, e)
            yield CapabilityEvent(
                trace_id=call.trace_id,
                event_type="error",
                message=str(e),
            )

    async def async_call(
        self,
        call: CapabilityCall,
        context: dict[str, Any] | None = None,
    ) -> str:
        """
        异步调用能力，返回 task_id 用于后续查询

        Args:
            call: 调用请求
            context: 执行上下文

        Returns:
            task_id 用于后续查询结果
        """
        ctx = context or {}
        ctx.setdefault("trace_id", call.trace_id)
        ctx.setdefault("caller", call.caller)

        handler = self._async_handlers.get(call.capability_id)
        if handler is None:
            raise CapabilityNotFoundError(call.capability_id)

        task_id = call.trace_id

        async def _run():
            try:
                result = await handler(call.params, ctx)
                self._async_results[task_id] = CapabilityResult(
                    trace_id=call.trace_id,
                    capability_id=call.capability_id,
                    success=True,
                    data=result,
                )
            except Exception as e:
                self._async_results[task_id] = CapabilityResult(
                    trace_id=call.trace_id,
                    capability_id=call.capability_id,
                    success=False,
                    error=str(e),
                )

        asyncio.create_task(_run())
        return task_id

    _async_results: dict[str, CapabilityResult] = {}

    def get_async_result(self, task_id: str) -> CapabilityResult | None:
        """获取异步调用的结果"""
        return self._async_results.get(task_id)

    # ── 批量操作 ─────────────────────────────

    async def call_batch(
        self,
        calls: list[CapabilityCall],
        context: dict[str, Any] | None = None,
        *,
        parallel: bool = True,
    ) -> list[CapabilityResult]:
        """
        批量调用多个能力

        Args:
            calls: 调用请求列表
            context: 执行上下文
            parallel: 是否并行执行

        Returns:
            结果列表，顺序与调用顺序一致
        """
        if parallel:
            tasks = [self.call(c, context) for c in calls]
            return list(await asyncio.gather(*tasks))
        else:
            results: list[CapabilityResult] = []
            for c in calls:
                results.append(await self.call(c, context))
            return results

    # ── 统计 ──────────────────────────────────

    @property
    def count(self) -> int:
        """已注册的能力总数"""
        return len(self._definitions)

    def count_by_category(self) -> dict[str, int]:
        """按功能域统计能力数量"""
        return {k.value: len(v) for k, v in self._by_category.items()}

    @property
    def categories(self) -> list[CapabilityCategory]:
        """已注册的所有功能域"""
        return list(self._by_category.keys())

    def stats(self) -> dict[str, Any]:
        """获取注册表统计信息"""
        return {
            "total_capabilities": self.count,
            "categories": {
                cat.value: len(ids) for cat, ids in self._by_category.items()
            },
            "execution_modes": {
                "sync": len(self._sync_handlers),
                "stream": len(self._stream_handlers),
                "async": len(self._async_handlers),
            },
        }
