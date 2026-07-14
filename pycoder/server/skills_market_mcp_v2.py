"""
✨ Skills Market MCP Tools v2 — 将升级版 Skills Market 接口暴露为 MCP Tool

新增功能:
  - 高级搜索 (sort_by: quality/stars/downloads/rating/name)
  - 智能推荐系统 (基于质量评分)
  - 热门排行榜 (实时更新)
  - 统计仪表板 (分类、评分、趋势)
  - 云端评分同步 (待实现)

每个工具对应一个 MCP Tool 定义，可从 /mcp 路由查询。
"""

from __future__ import annotations

from pycoder.server.log import log

# ══════════════════════════════════════════════════════════
# MCP Tool 定义和工具处理器
# ══════════════════════════════════════════════════════════


async def handle_skills_search_v2(args: dict) -> dict:
    """高级搜索：关键词 + 分类 + 标签 + 排序 + 分页"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    market = get_enhanced_market()
    query = args.get("query", "")
    category = args.get("category", "")
    tags = args.get("tags", [])
    sort_by = args.get("sort_by", "quality")  # quality/stars/downloads/rating/name
    limit = args.get("limit", 20)
    offset = args.get("offset", 0)

    try:
        results = market.search(
            query=query,
            category=category,
            tags=tags,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
        )
        return {
            "success": True,
            "query": query,
            "total": results.get("total", 0),
            "results": results.get("skills", []),
            "sort_by": sort_by,
            "offset": offset,
            "limit": limit,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def handle_skills_recommendations_v2(args: dict) -> dict:
    """获取推荐列表"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    market = get_enhanced_market()
    category = args.get("category", "")
    limit = args.get("limit", 10)

    try:
        recommendations = market.get_recommendations(category=category, limit=limit)
        return {
            "success": True,
            "recommendations": recommendations,
            "category": category or "(all)",
            "count": len(recommendations),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def handle_skills_trending_v2(args: dict) -> dict:
    """获取热门排行"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    market = get_enhanced_market()
    limit = args.get("limit", 20)

    try:
        trending = market.get_trending(limit=limit)
        return {
            "success": True,
            "trending": trending,
            "count": len(trending),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def handle_skills_detail_v2(args: dict) -> dict:
    """获取技能详情"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    market = get_enhanced_market()
    skill_id = args.get("skill_id", "")

    if not skill_id:
        return {
            "success": False,
            "error": "skill_id 是必需的参数",
        }

    try:
        detail = market.get_skill_detail(skill_id)
        if detail:
            return {
                "success": True,
                "skill": detail,
            }
        else:
            return {
                "success": False,
                "error": f"技能不存在: {skill_id}",
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def handle_skills_rate_v2(args: dict) -> dict:
    """评分技能"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    market = get_enhanced_market()
    skill_id = args.get("skill_id", "")
    rating = args.get("rating", 5)
    review = args.get("review", "")

    if not skill_id:
        return {
            "success": False,
            "error": "skill_id 是必需的参数",
        }

    if not 1 <= rating <= 5:
        return {
            "success": False,
            "error": "rating 必须在 1-5 之间",
        }

    try:
        market.rate_skill(skill_id, rating, review)
        return {
            "success": True,
            "skill_id": skill_id,
            "rating": rating,
            "review": review,
            "message": f"✓ 评分成功: {skill_id} = {rating}⭐",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def handle_skills_stats_v2(args: dict) -> dict:
    """获取统计信息"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    market = get_enhanced_market()

    try:
        stats = market.get_stats()
        return {
            "success": True,
            "stats": stats,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def handle_skills_sync_v2(args: dict) -> dict:
    """同步所有数据源（异步）"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    market = get_enhanced_market()

    try:
        result = await market.sync_from_all_sources()
        return {
            "success": True,
            "total_skills": result.get("total_skills", 0),
            "sources": result.get("sources", {}),
            "message": f"✓ 同步成功: {result.get('total_skills', 0)} 个技能",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def handle_skills_categories_v2(args: dict) -> dict:
    """列出所有分类"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    market = get_enhanced_market()

    try:
        categories = market.get_categories()
        return {
            "success": True,
            "categories": categories,
            "count": len(categories),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


# ══════════════════════════════════════════════════════════
# MCP Tool 定义
# ══════════════════════════════════════════════════════════

SKILLS_MARKET_TOOLS_V2 = {
    "skills_search_v2": {
        "name": "skills_search_v2",
        "description": "🔍 高级搜索技能：支持关键词、分类、标签、排序、分页",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词 (支持中英文)",
                },
                "category": {
                    "type": "string",
                    "description": "按分类筛选 (如: code, data, ai)",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "按标签筛选",
                },
                "sort_by": {
                    "type": "string",
                    "enum": ["quality", "stars", "downloads", "rating", "name"],
                    "description": "排序方式",
                    "default": "quality",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回数量",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                },
                "offset": {
                    "type": "integer",
                    "description": "分页偏移",
                    "default": 0,
                },
            },
        },
        "handler": handle_skills_search_v2,
    },
    "skills_recommendations_v2": {
        "name": "skills_recommendations_v2",
        "description": "⭐ 获取智能推荐：基于质量评分的个性化推荐",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "限定分类 (留空则不限制)",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回数量",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
        },
        "handler": handle_skills_recommendations_v2,
    },
    "skills_trending_v2": {
        "name": "skills_trending_v2",
        "description": "🔥 获取热门排行：实时热门技能榜单",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "返回数量",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                },
            },
        },
        "handler": handle_skills_trending_v2,
    },
    "skills_detail_v2": {
        "name": "skills_detail_v2",
        "description": "📖 获取技能详情：完整的技能信息和评分",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_id": {
                    "type": "string",
                    "description": "技能 ID",
                },
            },
            "required": ["skill_id"],
        },
        "handler": handle_skills_detail_v2,
    },
    "skills_rate_v2": {
        "name": "skills_rate_v2",
        "description": "⭐ 评分技能：提交技能评分和评论",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_id": {
                    "type": "string",
                    "description": "技能 ID",
                },
                "rating": {
                    "type": "integer",
                    "description": "评分 (1-5)",
                    "minimum": 1,
                    "maximum": 5,
                    "default": 5,
                },
                "review": {
                    "type": "string",
                    "description": "评论文本",
                },
            },
            "required": ["skill_id"],
        },
        "handler": handle_skills_rate_v2,
    },
    "skills_stats_v2": {
        "name": "skills_stats_v2",
        "description": "📊 统计仪表板：获取市场统计数据",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
        "handler": handle_skills_stats_v2,
    },
    "skills_sync_v2": {
        "name": "skills_sync_v2",
        "description": "🔄 数据同步：从所有源同步最新技能数据 (异步)",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
        "handler": handle_skills_sync_v2,
    },
    "skills_categories_v2": {
        "name": "skills_categories_v2",
        "description": "🏷️ 获取分类列表：所有可用的技能分类",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
        "handler": handle_skills_categories_v2,
    },
}


def get_skills_market_tools_v2() -> dict:
    """获取所有 v2 工具定义"""
    return SKILLS_MARKET_TOOLS_V2


async def call_skills_tool_v2(tool_name: str, args: dict) -> dict:
    """
    调用 Skills Market v2 工具

    Args:
        tool_name: 工具名称 (如 'skills_search_v2')
        args: 工具参数

    Returns:
        {success, ...} 结果字典
    """
    tool_def = SKILLS_MARKET_TOOLS_V2.get(tool_name)
    if not tool_def:
        return {
            "success": False,
            "error": f"未知工具: {tool_name}",
        }

    try:
        handler = tool_def.get("handler")
        if not handler:
            return {
                "success": False,
                "error": f"工具 {tool_name} 无处理器",
            }

        result = await handler(args)
        return result
    except Exception as e:
        log.error("skills_tool_error", tool=tool_name, error=str(e))
        return {
            "success": False,
            "error": f"工具执行失败: {str(e)}",
        }
