"""
skills_market_mcp_v2.py 模块单元测试 — 覆盖率目标 ≥80%

覆盖内容:
  - 8 个 handle_* 异步处理器（搜索/推荐/趋势/详情/评分/统计/同步/分类）
  - SKILLS_MARKET_TOOLS_V2 字典完整性
  - get_skills_market_tools_v2 函数
  - call_skills_tool_v2 调度函数（含未知工具/无处理器/异常分支）

测试策略: 用 monkeypatch 替换 get_enhanced_market 工厂, 返回 Mock 市场对象。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from pycoder.server import skills_market_mcp_v2 as mcp_v2
from pycoder.server.skills_market_mcp_v2 import (
    SKILLS_MARKET_TOOLS_V2,
    call_skills_tool_v2,
    get_skills_market_tools_v2,
    handle_skills_categories_v2,
    handle_skills_detail_v2,
    handle_skills_rate_v2,
    handle_skills_recommendations_v2,
    handle_skills_search_v2,
    handle_skills_stats_v2,
    handle_skills_sync_v2,
    handle_skills_trending_v2,
)


# ── Mock 市场对象 ──

class FakeMarket:
    """模拟 EnhancedSkillsMarketManager 的可控行为"""

    def __init__(self):
        self.search_result: dict = {"total": 2, "skills": [{"id": "s1"}, {"id": "s2"}]}
        self.recommendations: list = [{"skill_id": "r1"}]
        self.trending: list = [{"name": "T1"}]
        self.skill_detail: dict | None = {"id": "s1", "name": "skill-1"}
        self.stats: dict = {"total_skills": 10}
        self.categories: dict = {"code": 5}
        self.sync_result: dict = {"total_skills": 10, "sources": {"github": 5}}
        self.search_kwargs: dict | None = None
        self.rate_calls: list = []
        self.raise_on_search: Exception | None = None

    def search(self, **kwargs):
        self.search_kwargs = kwargs
        if self.raise_on_search:
            raise self.raise_on_search
        return self.search_result

    def get_recommendations(self, category="", limit=10):
        return self.recommendations

    def get_trending(self, limit=20):
        return self.trending

    def get_skill_detail(self, skill_id):
        return self.skill_detail

    def rate_skill(self, skill_id, rating, review):
        self.rate_calls.append((skill_id, rating, review))

    def get_stats(self):
        return self.stats

    def get_categories(self):
        return self.categories

    async def sync_from_all_sources(self):
        return self.sync_result


@pytest.fixture
def fake_market(monkeypatch):
    """注入 FakeMarket 替换 get_enhanced_market"""
    market = FakeMarket()
    # 模块内 handler 通过局部 import 获取 get_enhanced_market
    import pycoder.server.skills_market_mcp_v2 as mod
    monkeypatch.setattr(
        "pycoder.server.skills_market_v2.get_enhanced_market",
        lambda: market,
        raising=False,
    )
    return market


# ── handle_skills_search_v2 ──

async def test_handle_search_default_args(fake_market):
    """handle_skills_search_v2 默认参数"""
    result = await handle_skills_search_v2({})
    assert result["success"] is True
    assert result["total"] == 2
    assert result["results"] == [{"id": "s1"}, {"id": "s2"}]
    assert result["sort_by"] == "quality"
    assert result["offset"] == 0
    assert result["limit"] == 20
    # 验证调用参数
    assert fake_market.search_kwargs == {
        "query": "", "category": "", "tags": [],
        "sort_by": "quality", "limit": 20, "offset": 0,
    }


async def test_handle_search_with_args(fake_market):
    """handle_skills_search_v2 接收参数透传"""
    args = {
        "query": "pytest", "category": "code", "tags": ["t1"],
        "sort_by": "stars", "limit": 5, "offset": 10,
    }
    result = await handle_skills_search_v2(args)
    assert result["success"] is True
    assert result["query"] == "pytest"
    assert result["sort_by"] == "stars"
    assert fake_market.search_kwargs["tags"] == ["t1"]
    assert fake_market.search_kwargs["limit"] == 5


async def test_handle_search_handles_exception(fake_market):
    """handle_skills_search_v2 异常时返回 success=False"""
    fake_market.raise_on_search = RuntimeError("boom")
    result = await handle_skills_search_v2({"query": "x"})
    assert result["success"] is False
    assert "boom" in result["error"]


async def test_handle_search_missing_keys(fake_market):
    """handle_skills_search_v2 缺失 keys 时使用 .get 默认值"""
    result = await handle_skills_search_v2({"query": "abc"})
    assert result["success"] is True
    assert result["total"] == 2


# ── handle_skills_recommendations_v2 ──

async def test_handle_recommendations_default(fake_market):
    result = await handle_skills_recommendations_v2({})
    assert result["success"] is True
    assert result["recommendations"] == [{"skill_id": "r1"}]
    assert result["category"] == "(all)"
    assert result["count"] == 1


async def test_handle_recommendations_with_category(fake_market):
    result = await handle_skills_recommendations_v2({"category": "code", "limit": 3})
    assert result["success"] is True
    assert result["category"] == "code"


async def test_handle_recommendations_exception(fake_market, monkeypatch):
    """get_recommendations 抛异常时返回 success=False"""
    def boom(category="", limit=10):
        raise ValueError("no recs")
    monkeypatch.setattr(fake_market, "get_recommendations", boom)
    result = await handle_skills_recommendations_v2({})
    assert result["success"] is False
    assert "no recs" in result["error"]


# ── handle_skills_trending_v2 ──

async def test_handle_trending_default(fake_market):
    result = await handle_skills_trending_v2({})
    assert result["success"] is True
    assert result["trending"] == [{"name": "T1"}]
    assert result["count"] == 1


async def test_handle_trending_with_limit(fake_market):
    result = await handle_skills_trending_v2({"limit": 5})
    assert result["success"] is True


async def test_handle_trending_exception(fake_market, monkeypatch):
    monkeypatch.setattr(fake_market, "get_trending", lambda limit=20: (_ for _ in ()).throw(RuntimeError("err")))
    result = await handle_skills_trending_v2({})
    assert result["success"] is False
    assert "err" in result["error"]


# ── handle_skills_detail_v2 ──

async def test_handle_detail_missing_skill_id(fake_market):
    """handle_skills_detail_v2 缺少 skill_id 返回错误"""
    result = await handle_skills_detail_v2({})
    assert result["success"] is False
    assert "skill_id" in result["error"]


async def test_handle_detail_found(fake_market):
    result = await handle_skills_detail_v2({"skill_id": "s1"})
    assert result["success"] is True
    assert result["skill"] == {"id": "s1", "name": "skill-1"}


async def test_handle_detail_not_found(fake_market):
    fake_market.skill_detail = None
    result = await handle_skills_detail_v2({"skill_id": "no-exist"})
    assert result["success"] is False
    assert "no-exist" in result["error"]


async def test_handle_detail_exception(fake_market, monkeypatch):
    monkeypatch.setattr(fake_market, "get_skill_detail", lambda sid: (_ for _ in ()).throw(ValueError("db")))
    result = await handle_skills_detail_v2({"skill_id": "s1"})
    assert result["success"] is False
    assert "db" in result["error"]


# ── handle_skills_rate_v2 ──

async def test_handle_rate_missing_skill_id(fake_market):
    result = await handle_skills_rate_v2({})
    assert result["success"] is False
    assert "skill_id" in result["error"]


async def test_handle_rate_invalid_rating(fake_market):
    """rating 越界返回错误"""
    result = await handle_skills_rate_v2({"skill_id": "s1", "rating": 0})
    assert result["success"] is False
    assert "rating" in result["error"]
    result_high = await handle_skills_rate_v2({"skill_id": "s1", "rating": 6})
    assert result_high["success"] is False


async def test_handle_rate_success(fake_market):
    result = await handle_skills_rate_v2({
        "skill_id": "s1", "rating": 4, "review": "good",
    })
    assert result["success"] is True
    assert result["skill_id"] == "s1"
    assert result["rating"] == 4
    assert "评分成功" in result["message"]
    assert fake_market.rate_calls == [("s1", 4, "good")]


async def test_handle_rate_default_rating(fake_market):
    """rating 缺失默认 5"""
    result = await handle_skills_rate_v2({"skill_id": "s1"})
    assert result["success"] is True
    assert result["rating"] == 5


async def test_handle_rate_exception(fake_market, monkeypatch):
    def boom(sid, r, rv):
        raise RuntimeError("db error")
    monkeypatch.setattr(fake_market, "rate_skill", boom)
    result = await handle_skills_rate_v2({"skill_id": "s1", "rating": 3})
    assert result["success"] is False
    assert "db error" in result["error"]


# ── handle_skills_stats_v2 ──

async def test_handle_stats_success(fake_market):
    result = await handle_skills_stats_v2({})
    assert result["success"] is True
    assert result["stats"] == {"total_skills": 10}


async def test_handle_stats_exception(fake_market, monkeypatch):
    monkeypatch.setattr(fake_market, "get_stats", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    result = await handle_skills_stats_v2({})
    assert result["success"] is False


# ── handle_skills_sync_v2 ──

async def test_handle_sync_success(fake_market):
    result = await handle_skills_sync_v2({})
    assert result["success"] is True
    assert result["total_skills"] == 10
    assert result["sources"] == {"github": 5}
    assert "同步成功" in result["message"]


async def test_handle_sync_exception(fake_market, monkeypatch):
    async def boom():
        raise RuntimeError("network")
    monkeypatch.setattr(fake_market, "sync_from_all_sources", boom)
    result = await handle_skills_sync_v2({})
    assert result["success"] is False
    assert "network" in result["error"]


# ── handle_skills_categories_v2 ──

async def test_handle_categories_success(fake_market):
    result = await handle_skills_categories_v2({})
    assert result["success"] is True
    assert result["categories"] == {"code": 5}
    assert result["count"] == 1


async def test_handle_categories_exception(fake_market, monkeypatch):
    monkeypatch.setattr(fake_market, "get_categories", lambda: (_ for _ in ()).throw(RuntimeError("err")))
    result = await handle_skills_categories_v2({})
    assert result["success"] is False


# ── SKILLS_MARKET_TOOLS_V2 ──

def test_tools_dict_contains_all_handlers():
    """SKILLS_MARKET_TOOLS_V2 包含 8 个工具定义"""
    expected = {
        "skills_search_v2", "skills_recommendations_v2", "skills_trending_v2",
        "skills_detail_v2", "skills_rate_v2", "skills_stats_v2",
        "skills_sync_v2", "skills_categories_v2",
    }
    assert expected.issubset(SKILLS_MARKET_TOOLS_V2.keys())


def test_get_skills_market_tools_v2_returns_same_dict():
    """get_skills_market_tools_v2 返回 SKILLS_MARKET_TOOLS_V2 字典"""
    assert get_skills_market_tools_v2() is SKILLS_MARKET_TOOLS_V2


def test_each_tool_has_required_fields():
    """每个工具有 name/description/input_schema/handler"""
    for name, tool in SKILLS_MARKET_TOOLS_V2.items():
        assert tool["name"] == name
        assert "description" in tool
        assert "input_schema" in tool
        assert callable(tool["handler"])


# ── call_skills_tool_v2 ──

async def test_call_tool_unknown(fake_market):
    """调用未知工具返回错误"""
    result = await call_skills_tool_v2("does-not-exist", {})
    assert result["success"] is False
    assert "未知工具" in result["error"]


async def test_call_tool_dispatch_search(fake_market):
    """call_skills_tool_v2 调度到 handle_skills_search_v2"""
    result = await call_skills_tool_v2("skills_search_v2", {"query": "test"})
    assert result["success"] is True


async def test_call_tool_dispatch_categories(fake_market):
    """call_skills_tool_v2 调度到 handle_skills_categories_v2"""
    result = await call_skills_tool_v2("skills_categories_v2", {})
    assert result["success"] is True
    assert result["count"] == 1


async def test_call_tool_handler_exception_returns_error(fake_market, monkeypatch):
    """handler 自身抛出未捕获异常时, call_skills_tool_v2 返回 success=False"""
    async def boom(args):
        raise RuntimeError("handler boom")
    monkeypatch.setitem(
        SKILLS_MARKET_TOOLS_V2["skills_categories_v2"], "handler", boom
    )
    result = await call_skills_tool_v2("skills_categories_v2", {})
    assert result["success"] is False
    assert "工具执行失败" in result["error"]


async def test_call_tool_no_handler(monkeypatch):
    """工具缺少 handler 字段时返回错误"""
    # 暂时移除 handler
    saved = SKILLS_MARKET_TOOLS_V2["skills_stats_v2"]["handler"]
    SKILLS_MARKET_TOOLS_V2["skills_stats_v2"]["handler"] = None
    try:
        result = await call_skills_tool_v2("skills_stats_v2", {})
        assert result["success"] is False
        assert "无处理器" in result["error"]
    finally:
        SKILLS_MARKET_TOOLS_V2["skills_stats_v2"]["handler"] = saved
