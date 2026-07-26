"""
技能生命周期与市场分析 API — Phase 3

路由前缀: /api/skills/lifecycle
标签: skills-lifecycle

功能:
1. 生命周期趋势查询 (emerging/growing/mature/declining)
2. Stack Overflow 趋势数据
3. 按需报告触发
4. 中国技能市场数据
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query

from pycoder.core.services.log import log

router = APIRouter(prefix="/api/skills/lifecycle", tags=["skills-lifecycle"])


# ═══════════════════════════════════════════════════════════
# 生命周期趋势
# ═══════════════════════════════════════════════════════════


@router.get("/trends")
async def get_trends(
    category: str = Query("", description="按分类筛选"),
    stage: str = Query("", description="按阶段筛选 (emerging/growing/mature/declining/stable)"),
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
):
    """获取技能生命周期趋势数据"""
    try:
        from pycoder.server.skills_lifecycle import get_lifecycle_engine

        engine = get_lifecycle_engine()
        db_path = engine._db_path

        import sqlite3

        conn = sqlite3.connect(str(db_path), timeout=5)
        where_clauses = []
        params = []
        if category:
            where_clauses.append("category = ?")
            params.append(category)
        if stage:
            where_clauses.append("stage = ?")
            params.append(stage)

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        cursor = conn.execute(
            f"SELECT skill_id, skill_name, category, stage, growth_rate_28d, "
            f"       growth_rate_prev, momentum, weeks_on_rise, current_rank, "
            f"       last_updated, source "
            f"FROM lifecycle_labels "
            f"WHERE {where_sql} "
            f"ORDER BY ABS(momentum) DESC, growth_rate_28d DESC "
            f"LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        rows = cursor.fetchall()

        cursor2 = conn.execute(
            f"SELECT COUNT(*) FROM lifecycle_labels WHERE {where_sql}",
            params,
        )
        total = cursor2.fetchone()[0]
        conn.close()

        items = []
        for r in rows:
            items.append({
                "skill_id": r[0],
                "skill_name": r[1],
                "category": r[2],
                "stage": r[3],
                "growth_rate_28d": round(r[4], 4) if r[4] else 0,
                "growth_rate_prev": round(r[5], 4) if r[5] else 0,
                "momentum": round(r[6], 4) if r[6] else 0,
                "weeks_on_rise": r[7] or 0,
                "current_rank": r[8] or 0,
                "last_updated": r[9],
                "source": r[10] or "",
            })

        return {
            "success": True,
            "data": items,
            "meta": {"total": total, "limit": limit, "offset": offset},
        }
    except Exception as e:
        log.warning("lifecycle_trends_api_error", error=str(e)[:80])
        raise HTTPException(status_code=500, detail=str(e)[:200]) from e


@router.get("/emerging")
async def get_emerging(
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    min_growth: float = Query(0.2, ge=0, description="最低增长率"),
):
    """获取新兴技能列表 (增长率 > threshold)"""
    try:
        from pycoder.server.skills_lifecycle import get_lifecycle_engine

        engine = get_lifecycle_engine()
        db_path = engine._db_path

        import sqlite3

        conn = sqlite3.connect(str(db_path), timeout=5)
        cursor = conn.execute(
            "SELECT skill_id, skill_name, category, stage, "
            "       growth_rate_28d, stars_28d, stars_total, momentum "
            "FROM lifecycle_labels "
            "WHERE growth_rate_28d >= ? AND stage IN ('emerging', 'growing') "
            "ORDER BY growth_rate_28d DESC LIMIT ?",
            (min_growth, limit),
        )
        rows = cursor.fetchall()
        conn.close()

        items = []
        for r in rows:
            items.append({
                "skill_id": r[0],
                "skill_name": r[1],
                "category": r[2],
                "stage": r[3],
                "growth_rate_28d": round(r[4], 4),
                "stars_28d": r[5] or 0,
                "stars_total": r[6] or 0,
                "momentum": round(r[7], 4) if r[7] else 0,
            })

        return {"success": True, "data": items, "meta": {"total": len(items), "limit": limit}}
    except Exception as e:
        log.warning("lifecycle_emerging_api_error", error=str(e)[:80])
        raise HTTPException(status_code=500, detail=str(e)[:200]) from e


# ═══════════════════════════════════════════════════════════
# Stack Overflow 趋势
# ═══════════════════════════════════════════════════════════


@router.get("/so-trends")
async def get_so_trends(
    category: str = Query("", description="按分类筛选"),
    sort_by: str = Query("growth_rate", description="排序方式: growth_rate/adoption/name"),
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
):
    """获取 Stack Overflow 调查趋势数据"""
    try:
        from pycoder.server.skills_lifecycle import get_lifecycle_engine

        engine = get_lifecycle_engine()
        trends = engine.get_so_trends(category)

        if sort_by == "adoption":
            trends.sort(key=lambda t: t["adoption_2025"], reverse=True)
        elif sort_by == "name":
            trends.sort(key=lambda t: t["technology"])
        else:
            trends.sort(key=lambda t: t["growth_rate"], reverse=True)

        return {
            "success": True,
            "data": trends[:limit],
            "meta": {"total": len(trends), "limit": limit},
        }
    except Exception as e:
        log.warning("so_trends_api_error", error=str(e)[:80])
        raise HTTPException(status_code=500, detail=str(e)[:200]) from e


# ═══════════════════════════════════════════════════════════
# 生命周期统计
# ═══════════════════════════════════════════════════════════


@router.get("/stats")
async def get_lifecycle_stats():
    """获取技能生命周期统计信息"""
    try:
        from pycoder.server.skills_lifecycle import get_lifecycle_engine

        engine = get_lifecycle_engine()
        stats = engine.get_stats()
        by_category = engine.get_lifecycle_by_category()

        return {
            "success": True,
            "data": {
                "overall": stats,
                "by_category": by_category,
            },
        }
    except Exception as e:
        log.warning("lifecycle_stats_api_error", error=str(e)[:80])
        raise HTTPException(status_code=500, detail=str(e)[:200]) from e


# ═══════════════════════════════════════════════════════════
# 按需报告触发
# ═══════════════════════════════════════════════════════════


@router.post("/report")
async def trigger_report_manual():
    """手动触发技能市场月报生成"""
    try:
        from pycoder.server.skills_report import generate_skills_report

        result = generate_skills_report()

        return {
            "success": True,
            "data": result,
            "meta": {"timestamp": time.time()},
        }
    except Exception as e:
        log.warning("manual_report_error", error=str(e)[:80])
        raise HTTPException(status_code=500, detail=str(e)[:200]) from e


# ═══════════════════════════════════════════════════════════
# 中国技能市场
# ═══════════════════════════════════════════════════════════


@router.get("/china-market")
async def get_china_market(
    limit: int = Query(30, ge=1, le=100, description="返回数量"),
):
    """获取中国技能市场数据

    聚合中国相关数据源 (chinese-ai-tools, chinese-dev-tools, china-llm) 的排名数据。
    """
    try:
        from pathlib import Path
        import json

        from pycoder.server.skills_data_sources import get_ossinsight_client

        # 1. 尝试从注册表中获取中国相关技能
        registry_path = Path.cwd() / ".skills-registry-enhanced.json"
        cn_skills = []
        if registry_path.exists():
            data = json.loads(registry_path.read_text(encoding="utf-8"))
            for skill in data.get("skills", []):
                # 匹配中国相关的数据源
                source = skill.get("source", "")
                if any(kw in source for kw in [
                    "china", "chinese", "awesome_chinese",
                ]):
                    cn_skills.append(skill)

        # 2. 获取 OSSInsight 中国编程语言排名
        client = get_ossinsight_client()
        china_ranking = client.get_trending_by_category(
            "programming-language-of-china", min_stars_28d=0
        )
        ossinsight_items = [
            {
                "rank": item.rank,
                "repo_name": item.repo_name,
                "stars_28d": item.stars_28d,
                "stars_total": item.stars_total,
                "change_pct": round(item.change_pct, 2),
            }
            for item in china_ranking[:20]
        ]

        # 3. SO 趋势中的中国相关技术
        engine = __import__(
            "pycoder.server.skills_lifecycle",
            fromlist=["get_lifecycle_engine"],
        ).get_lifecycle_engine()
        engine.import_so_survey()
        so_trends = engine.get_so_trends()

        return {
            "success": True,
            "data": {
                "china_source_skills": cn_skills[:limit],
                "ossinsight_china_ranking": ossinsight_items,
                "so_china_related": [
                    t for t in so_trends
                    if any(kw in t["technology"].lower() for kw in [
                        "chinese", "python", "deepseek", "chatgpt", "claude",
                        "pytorch", "react",
                    ])
                ][:15],
            },
            "meta": {
                "cn_source_count": len(cn_skills),
                "ossinsight_count": len(ossinsight_items),
            },
        }
    except Exception as e:
        log.warning("china_market_api_error", error=str(e)[:80])
        return {
            "success": False,
            "error": str(e)[:200],
            "data": {
                "cn_source_skills": [],
                "ossinsight_china_ranking": [],
                "so_china_related": [],
            },
        }


# ═══════════════════════════════════════════════════════════
# 数据源状态
# ═══════════════════════════════════════════════════════════


@router.get("/sources")
async def get_data_sources_status():
    """获取所有数据源状态和统计"""
    try:
        from pycoder.server.skills_updater_v2 import get_enhanced_fetcher

        fetcher = get_enhanced_fetcher()
        stats = fetcher.get_stats()
        sync_status = fetcher.sync_status()

        # 数据源概览
        sources_list = []
        for sid, config in fetcher.SOURCES.items():
            is_china = any(kw in sid for kw in ["china", "chinese", "ossinsight_china"])
            sources_list.append({
                "id": sid,
                "name": config.get("name", ""),
                "type": config.get("type", ""),
                "is_chinese_market": is_china,
            })

        return {
            "success": True,
            "data": {
                "sources": sources_list,
                "total_sources": len(sources_list),
                "chinese_sources": sum(1 for s in sources_list if s["is_chinese_market"]),
                "stats": stats,
                "sync_status": sync_status,
            },
        }
    except Exception as e:
        log.warning("sources_status_api_error", error=str(e)[:80])
        raise HTTPException(status_code=500, detail=str(e)[:200]) from e


__all__ = ["router"]
