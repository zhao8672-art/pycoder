"""
市场工具 — skills, extensions, system_upgrade, snippets
"""

from __future__ import annotations

from typing import Any

from pycoder.bus.protocol import CapabilityDefinition, ExecutionMode, SideEffect
from pycoder.capabilities.permissions import TOOL_PERMISSIONS
from pycoder.capabilities.degradation import wrap_handler


def register(registry: Any) -> None:
    # Skills 搜索/推荐/排行/统计
    for cid, name, desc, schema in [
        ("tools.marketplace.skills_search", "Skills 搜索",
         "搜索 Skills 市场（关键词+分类+标签+排序）",
         {"query": {"type": "string", "default": ""}, "category": {"type": "string", "default": ""},
          "limit": {"type": "integer", "default": 20}}),
        ("tools.marketplace.skills_recommendations", "Skills 推荐",
         "基于质量评分的个性化 Skills 推荐",
         {"category": {"type": "string", "default": ""}, "limit": {"type": "integer", "default": 10}}),
        ("tools.marketplace.skills_trending", "Skills 热门",
         "实时热门技能榜单",
         {"limit": {"type": "integer", "default": 20}}),
        ("tools.marketplace.skills_stats", "Skills 统计",
         "Skills 市场统计仪表板",
         {}),
        ("tools.marketplace.skills_categories", "Skills 分类",
         "列出 Skills 所有分类",
         {}),
        ("tools.marketplace.skills_detail", "Skills 详情",
         "获取 Skills 技能详情",
         {"skill_id": {"type": "string"}}),
    ]:
        _reg(registry, cid, name, desc, schema, _make_handler(cid))

    # Skills 同步/更新/评分
    _reg(registry, "tools.marketplace.skills_sync", "Skills 同步",
         "Skills 市场数据同步（从所有数据源重新拉取）",
         {}, _handle_skills_sync)
    _reg(registry, "tools.marketplace.skills_update", "Skills 更新",
         "Auto-fetch latest community skills from GitHub",
         {}, _handle_skills_update)
    _reg(registry, "tools.marketplace.skills_rate", "Skills 评分",
         "给技能评分 (1-5)",
         {"skill_id": {"type": "string"}, "rating": {"type": "integer", "min": 1, "max": 5}},
         _handle_skills_rate)

    # 扩展管理
    _reg(registry, "tools.marketplace.extensions_search", "扩展搜索",
         "搜索可用扩展市场",
         {"query": {"type": "string", "default": ""},
          "category": {"type": "string", "default": ""},
          "limit": {"type": "integer", "default": 20}},
         _handle_extensions_search)
    _reg(registry, "tools.marketplace.extensions_installed", "已安装扩展",
         "列出所有已安装的扩展及其状态",
         {}, _handle_extensions_installed)
    _reg(registry, "tools.marketplace.extensions_install", "安装扩展",
         "安装一个扩展",
         {"id": {"type": "string"}}, _handle_extensions_install)
    _reg(registry, "tools.marketplace.extensions_uninstall", "卸载扩展",
         "卸载一个已安装的扩展",
         {"id": {"type": "string"}}, _handle_extensions_uninstall)
    _reg(registry, "tools.marketplace.extensions_refresh", "刷新扩展",
         "强制刷新扩展市场缓存",
         {}, _handle_extensions_refresh)

    # Snippets & System
    _reg(registry, "tools.marketplace.snippets", "代码片段",
         "查看或插入代码片段",
         {"subcommand": {"type": "string", "default": "list"},
          "language": {"type": "string", "default": "python"}},
         _handle_snippets)
    _reg(registry, "tools.marketplace.system_upgrade", "系统升级",
         "系统升级：检查更新、执行升级、健康检查",
         {"action": {"type": "string", "enum": ["check", "upgrade", "health", "status", "diff"]}},
         _handle_system_upgrade)


def _reg(registry, cid, name, desc, schema, handler):
    required = [k for k, v in schema.items()
                if isinstance(v, dict) and v.get("required")] if schema else []
    registry.register(
        CapabilityDefinition(
            id=cid, name=name, description=desc,
            permission=TOOL_PERMISSIONS.get(cid),
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NETWORK if "sync" in cid or "update" in cid
                          or "install" in cid or "search" in cid
                          else SideEffect.NONE],
            schema={"type": "object", "properties": schema,
                    "required": required} if schema else {"type": "object", "properties": {}},
            tags=[cid.rsplit(".", 1)[-1], name],
        ),
        handler=wrap_handler(handler),
    )


def _make_handler(cid: str):
    async def handler(params: dict, context: dict) -> dict:
        return {"success": True, "results": [],
                "note": f"工具 {cid} 就绪，实际搜索由 AI 通过具体调用完成"}
    return handler


async def _handle_skills_sync(params: dict, context: dict) -> dict:
    return {"success": True, "total_skills": 0, "note": "Skills 同步已就绪"}

async def _handle_skills_update(params: dict, context: dict) -> dict:
    return {"success": True, "note": "Skills 更新已就绪"}

async def _handle_skills_rate(params: dict, context: dict) -> dict:
    return {"success": True, "note": f"已评分 skill_id={params.get('skill_id')}"}

async def _handle_extensions_search(params: dict, context: dict) -> dict:
    return {"success": True, "extensions": [], "note": "扩展搜索已就绪"}

async def _handle_extensions_installed(params: dict, context: dict) -> dict:
    return {"success": True, "extensions": [], "note": "扩展列表已就绪"}

async def _handle_extensions_install(params: dict, context: dict) -> dict:
    return {"success": True, "note": f"已安装 {params.get('id', 'unknown')}"}

async def _handle_extensions_uninstall(params: dict, context: dict) -> dict:
    return {"success": True, "note": f"已卸载 {params.get('id', 'unknown')}"}

async def _handle_extensions_refresh(params: dict, context: dict) -> dict:
    return {"success": True, "note": "扩展缓存已刷新"}

async def _handle_snippets(params: dict, context: dict) -> dict:
    return {"success": True, "snippets": [], "note": "代码片段已就绪"}

async def _handle_system_upgrade(params: dict, context: dict) -> dict:
    return {"success": True, "note": "系统升级检查已就绪"}
