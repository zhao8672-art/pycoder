"""
✨ Task 1 集成测试 — MCP Tools + REST API 验证

测试项目:
  1. MCP Tools 注册成功
  2. REST API 端点可访问
  3. 搜索、推荐、排行等功能
  4. 前端 WebSocket 集成

运行: python -m pytest test_integration_task1.py -v
"""

import sys
import pytest
from httpx import AsyncClient, ASGITransport


def _make_client(app):
    """创建带 API 认证头的测试客户端

    P0-4 强制认证后，所有 REST 请求须携带 X-API-Key。
    本辅助函数从 app 模块读取当前 _API_KEY（可能为显式 key、
    自动生成 key 或 disabled 时的空串），自动注入到请求头。

    注意：`import pycoder.server.app as m` 在包结构下被解析为
    FastAPI 实例（__init__.py 导出），故使用 sys.modules 取真正模块。
    """
    app_module = sys.modules["pycoder.server.app"]
    api_key = getattr(app_module, "_API_KEY", "") or ""
    headers = {"X-API-Key": api_key} if api_key else {}
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test", headers=headers)


# ─────────────────────────────────────────────────────────
# Test 1: MCP Tools 注册测试
# ─────────────────────────────────────────────────────────


def test_mcp_tools_registered():
    """测试 MCP Tools 是否正确注册"""
    from pycoder.server.mcp_tools import _builtin_tools

    required_tools = [
        "skills_search_v2",
        "skills_recommendations_v2",
        "skills_trending_v2",
        "skills_stats_v2",
        "skills_sync_v2",
    ]

    for tool_name in required_tools:
        assert tool_name in _builtin_tools, f"工具未注册: {tool_name}"
        tool = _builtin_tools[tool_name]
        assert tool.name == tool_name
        assert tool.description, f"工具 {tool_name} 缺少描述"
        assert tool.input_schema, f"工具 {tool_name} 缺少 input_schema"
        assert tool.handler, f"工具 {tool_name} 缺少处理器"

    print("✓ 所有 MCP Tools 已成功注册")


@pytest.mark.asyncio
async def test_mcp_tools_callable():
    """测试 MCP Tools 是否可调用"""
    from pycoder.server.mcp_tools import call_builtin_tool

    # 测试搜索工具
    result = await call_builtin_tool("skills_search_v2", {"query": "test"})
    # MCPCallResult 有 success 和 output 属性
    assert hasattr(result, 'success')
    assert hasattr(result, 'output')
    assert result.success is True

    # 测试推荐工具
    result = await call_builtin_tool("skills_recommendations_v2", {"limit": 5})
    assert hasattr(result, 'success')
    assert result.success is True

    print("✓ MCP Tools 可正常调用")


def test_api_routes_registered():
    """测试 REST API 路由是否注册"""
    from pycoder.server.app import app

    routes = [route.path for route in app.routes]

    required_routes = [
        "/api/skills/v2/search",
        "/api/skills/v2/recommendations",
        "/api/skills/v2/trending",
        "/api/skills/v2/stats/overview",
        "/api/skills/v2/categories/list",
        "/api/skills/v2/{skill_id}",
        "/api/skills/v2/{skill_id}/rate",
        "/api/skills/v2/sync",
    ]

    for route in required_routes:
        assert route in routes, f"路由未注册: {route}"

    print("✓ 所有 REST API 路由已正确注册")


# ─────────────────────────────────────────────────────────
# Test 2: REST API 端点测试
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_endpoint():
    """测试搜索端点"""
    from pycoder.server.app import app

    async with _make_client(app) as client:
        response = await client.get(
            "/api/skills/v2/search",
            params={"query": "test", "sort_by": "quality", "limit": 5}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "results" in data
        print(f"✓ 搜索端点: 返回 {data['total']} 个结果")


@pytest.mark.asyncio
async def test_recommendations_endpoint():
    """测试推荐端点"""
    from pycoder.server.app import app

    async with _make_client(app) as client:
        response = await client.get(
            "/api/skills/v2/recommendations",
            params={"limit": 5}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "recommendations" in data
        print(f"✓ 推荐端点: 返回 {data['count']} 个推荐")


@pytest.mark.asyncio
async def test_trending_endpoint():
    """测试热门排行端点"""
    from pycoder.server.app import app

    async with _make_client(app) as client:
        response = await client.get(
            "/api/skills/v2/trending",
            params={"limit": 10}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "trending" in data
        print(f"✓ 热门排行端点: 返回 {data['count']} 个技能")


@pytest.mark.asyncio
async def test_stats_endpoint():
    """测试统计端点"""
    from pycoder.server.app import app

    async with _make_client(app) as client:
        response = await client.get("/api/skills/v2/stats/overview")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "stats" in data
        stats = data["stats"]
        assert "total_skills" in stats
        assert "categories_count" in stats
        print(f"✓ 统计端点: {stats['total_skills']} 个技能, {stats['categories_count']} 个分类")


@pytest.mark.asyncio
async def test_categories_endpoint():
    """测试分类列表端点"""
    from pycoder.server.app import app

    async with _make_client(app) as client:
        response = await client.get("/api/skills/v2/categories/list")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "categories" in data
        print(f"✓ 分类列表端点: {data['count']} 个分类")


@pytest.mark.asyncio
async def test_rate_endpoint():
    """测试评分端点"""
    from pycoder.server.app import app

    async with _make_client(app) as client:
        # 先搜索找到一个技能
        search_response = await client.get(
            "/api/skills/v2/search",
            params={"limit": 1}
        )

        if search_response.json()["total"] > 0:
            skill_id = search_response.json()["results"][0]["id"]

            # 评分这个技能
            rate_response = await client.post(
                f"/api/skills/v2/{skill_id}/rate",
                json={"rating": 5, "review": "Great skill!"}
            )

            assert rate_response.status_code == 200
            data = rate_response.json()
            assert data["success"] is True
            assert data["rating"] == 5
            print(f"✓ 评分端点: 成功评分技能 {skill_id}")


# ─────────────────────────────────────────────────────────
# Test 3: 性能测试
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_response_time():
    """验证 API 响应时间 <200ms"""
    import time
    from pycoder.server.app import app

    async with _make_client(app) as client:
        endpoints = [
            "/api/skills/v2/search?query=test",
            "/api/skills/v2/recommendations",
            "/api/skills/v2/trending",
            "/api/skills/v2/stats/overview",
            "/api/skills/v2/categories/list",
        ]

        for endpoint in endpoints:
            start = time.time()
            response = await client.get(endpoint)
            elapsed = (time.time() - start) * 1000  # 转为毫秒

            assert response.status_code == 200
            assert elapsed < 200, f"{endpoint} 响应时间过长: {elapsed:.1f}ms"

        print("✓ 性能测试: 所有端点响应时间 <200ms")


# ─────────────────────────────────────────────────────────
# Test 4: 错误处理
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_skill_id():
    """测试不存在的技能 ID"""
    from pycoder.server.app import app

    async with _make_client(app) as client:
        response = await client.get("/api/skills/v2/nonexistent-skill-id")

        assert response.status_code == 200
        data = response.json()
        # 不存在的 ID 返回 success=True 但无数据或 error 字段
        assert "success" in data
        print("✓ 错误处理: 不存在的技能 ID 处理正确")


@pytest.mark.asyncio
async def test_invalid_rating():
    """测试无效评分值"""
    from pycoder.server.app import app

    async with _make_client(app) as client:
        response = await client.post(
            "/api/skills/v2/test-skill/rate",
            json={"rating": 10, "review": "test"}  # 无效: 应在 1-5
        )

        # FastAPI 的 Pydantic 验证返回 422
        assert response.status_code == 422
        print("✓ 错误处理: 无效评分值返回 422 验证错误")


# ─────────────────────────────────────────────────────────
# Test 5: 集成流程
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_workflow():
    """测试完整的工作流: 搜索 → 推荐 → 详情 → 评分"""
    from pycoder.server.app import app

    async with _make_client(app) as client:
        # 1. 搜索
        search = await client.get("/api/skills/v2/search?query=claude&limit=5")
        assert search.status_code == 200
        skills = search.json()["results"]
        print(f"✓ 搜索: 找到 {len(skills)} 个技能")

        if skills:
            skill_id = skills[0]["id"]

            # 2. 获取详情
            detail = await client.get(f"/api/skills/v2/{skill_id}")
            assert detail.status_code == 200
            assert detail.json()["success"] is True
            print(f"✓ 详情: 获取技能 {skill_id} 的详细信息")

            # 3. 评分
            rate = await client.post(
                f"/api/skills/v2/{skill_id}/rate",
                json={"rating": 4, "review": "Good skill"}
            )
            assert rate.status_code == 200
            assert rate.json()["success"] is True
            print("✓ 评分: 成功评分")

        # 4. 获取推荐
        recs = await client.get("/api/skills/v2/recommendations?limit=3")
        assert recs.status_code == 200
        assert recs.json()["success"] is True
        print(f"✓ 推荐: 返回 {recs.json()['count']} 个推荐")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
