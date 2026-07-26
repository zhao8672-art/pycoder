"""
🚀 Skills Market API v2 路由 — 全新升级版

路由前缀: /api/v2/skills
支持: FTS5 搜索、12 维筛选、分页、异步安装、版本更新、评论、收藏

特性:
- 字段对齐前端 SkillItem（含 stars/downloads/has_update/verified/publisher）
- FTS5 全文检索 + BM25 相关性排序（自动降级 LIKE）
- 12 维筛选：分类/标签/评分范围/下载量范围/更新时间/作者/已验证/有更新/已安装
- 分页（page + page_size）
- 异步安装任务（task_id + 进度查询）
- 评论提交（含 review_text）+ 一人一评
- 版本检查 + 单技能/全部更新
- 收藏管理
- 统一响应格式 { success, data, meta { page, page_size, total, took_ms } }
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from pycoder.core.services.log import log
from pycoder.skills import SkillMarketplace

# ═══════════════════════════════════════════════════════════
# Pydantic 请求/响应模型
# ═══════════════════════════════════════════════════════════


class SkillInstallRequest(BaseModel):
    """安装请求（V2）"""

    skill_id: str = Field(..., description="技能 ID")
    install_dependencies: bool = Field(default=True, description="递归安装依赖")
    async_mode: bool = Field(default=False, description="异步模式，返回 task_id")


class SkillReviewRequest(BaseModel):
    """评论提交请求"""

    rating: int = Field(ge=1, le=5, description="评分 1-5")
    review_text: str = Field(default="", max_length=2000, description="评论正文")
    user_id: str = Field(default="anonymous", description="用户 ID")
    user_name: str = Field(default="anonymous", description="用户显示名")


class SkillFavoriteRequest(BaseModel):
    """收藏请求"""

    skill_id: str = Field(..., description="技能 ID")
    user_id: str = Field(default="anonymous", description="用户 ID")


class SkillPublishRequest(BaseModel):
    """技能发布请求（V2 — 完整字段）"""

    id: str = Field(..., description="技能 ID")
    name: str = Field(..., description="技能名称")
    description: str = Field(default="", description="描述")
    author: str = Field(default="PyCoder", description="作者")
    publisher: str = Field(default="", description="发布者")
    category: str = Field(default="general", description="分类")
    tags: list[str] = Field(default_factory=list, description="标签")
    dependencies: list[str] = Field(default_factory=list, description="依赖")
    version: str = Field(default="1.0.0", description="版本")
    markdown_content: str = Field(default="", description="Markdown 内容")
    source_url: str = Field(default="", description="源码 URL")
    homepage_url: str = Field(default="", description="主页 URL")
    license: str = Field(default="", description="许可证")
    icon_url: str = Field(default="", description="图标 URL")
    verified: bool = Field(default=False, description="是否已验证")


class SkillScreenshotRequest(BaseModel):
    """添加截图请求"""

    url: str = Field(..., description="截图 URL")
    caption: str = Field(default="", description="说明文字")
    sort_order: int = Field(default=0, description="排序序号")


class SkillVersionRequest(BaseModel):
    """添加版本请求"""

    version: str = Field(..., description="版本号")
    changelog: str = Field(default="", description="更新日志")
    download_url: str = Field(default="", description="下载 URL")
    released_at: str = Field(default="", description="发布时间（ISO）")


# ═══════════════════════════════════════════════════════════
# 创建路由器
# ═══════════════════════════════════════════════════════════

router = APIRouter(prefix="/api/v2/skills", tags=["skills-v2"])


def _get_marketplace() -> SkillMarketplace:
    """获取技能市场单例"""
    return SkillMarketplace()


def _ok(data: dict, meta: dict | None = None) -> dict:
    """统一成功响应"""
    return {"success": True, "data": data, "meta": meta or {}}


def _fail(message: str, code: int = 400) -> HTTPException:
    """统一失败响应"""
    return HTTPException(status_code=code, detail=message)


# ═══════════════════════════════════════════════════════════
# 1. 统一搜索（FTS5 + 12 维筛选 + 分页）
# ═══════════════════════════════════════════════════════════


@router.get(
    "",
    summary="🔍 统一搜索（V2）",
    description="FTS5 全文检索 + 12 维筛选 + 分页",
)
async def search_skills_v2(
    q: str = Query(default="", description="搜索关键词"),
    category: str = Query(default="", description="分类"),
    tags: str = Query(default="", description="标签（逗号分隔）"),
    min_rating: float = Query(default=0.0, ge=0, le=5, description="最低评分"),
    max_rating: float = Query(default=5.0, ge=0, le=5, description="最高评分"),
    min_downloads: int = Query(default=0, ge=0, description="最低下载量"),
    max_downloads: int = Query(default=0, ge=0, description="最高下载量（0=不限）"),
    updated_within_days: int = Query(default=0, ge=0, description="N 天内更新（0=不限）"),
    author: str = Query(default="", description="作者"),
    verified_only: bool = Query(default=False, description="仅已验证"),
    has_update_only: bool = Query(default=False, description="仅有更新"),
    installed_only: bool | None = Query(default=None, description="True=仅已安装/False=仅未安装"),
    sort_by: str = Query(
        default="relevance",
        pattern="^(relevance|rating|downloads|updated|name|stars)$",
        description="排序",
    ),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=500, description="每页数量"),
) -> dict:
    """V2 统一搜索端点"""
    marketplace = _get_marketplace()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None

    try:
        result = await marketplace.search_skills_v2(
            query=q,
            category=category,
            tags=tag_list,
            min_rating=min_rating,
            max_rating=max_rating,
            min_downloads=min_downloads,
            max_downloads=max_downloads,
            updated_within_days=updated_within_days,
            author=author,
            verified_only=verified_only,
            has_update_only=has_update_only,
            installed_only=installed_only,
            sort_by=sort_by,
            page=page,
            page_size=page_size,
        )
        return _ok(
            {"skills": result["skills"], "query": q},
            meta={
                "page": result["page"],
                "page_size": result["page_size"],
                "total": result["total"],
                "took_ms": result["took_ms"],
                "sort_by": result["sort_by"],
            },
        )
    except Exception as e:
        log.error("skills_v2_search_error", error=str(e))
        raise _fail(f"搜索失败: {e}", 500) from e


# ═══════════════════════════════════════════════════════════
# 2. 分类列表
# ═══════════════════════════════════════════════════════════


@router.get(
    "/categories",
    summary="📂 分类列表",
    description="获取所有分类（含计数）",
)
async def list_categories() -> dict:
    """分类列表"""
    marketplace = _get_marketplace()
    try:
        result = await marketplace.list_categories()
        return _ok(result)
    except Exception as e:
        log.error("skills_v2_categories_error", error=str(e))
        raise _fail(f"获取分类失败: {e}", 500) from e


# ═══════════════════════════════════════════════════════════
# 3. 技能详情（V2 — 含截图/版本/评分分布/评论）
# ═══════════════════════════════════════════════════════════


@router.get(
    "/{skill_id}",
    summary="📖 技能详情（V2）",
    description="含截图、版本历史、评分分布、评论列表",
)
async def get_skill_detail(skill_id: str) -> dict:
    """技能详情"""
    marketplace = _get_marketplace()
    try:
        result = await marketplace.get_skill(skill_id)
        if "error" in result:
            return {"success": False, "error": result["error"]}
        return _ok({"skill": result["skill"]})
    except Exception as e:
        log.error("skills_v2_detail_error", skill_id=skill_id, error=str(e))
        raise _fail(f"获取详情失败: {e}", 500) from e


# ═══════════════════════════════════════════════════════════
# 4. 安装（同步/异步）
# ═══════════════════════════════════════════════════════════


@router.post(
    "/install",
    summary="📥 安装技能（V2）",
    description="支持同步/异步安装，递归装依赖，含进度反馈",
)
async def install_skill(payload: SkillInstallRequest = Body(...)) -> dict:
    """安装技能"""
    marketplace = _get_marketplace()
    try:
        if payload.async_mode:
            result = await marketplace.create_install_task(
                payload.skill_id,
                install_dependencies=payload.install_dependencies,
            )
            return _ok(result)
        result = await marketplace.install_skill(
            payload.skill_id,
            install_dependencies=payload.install_dependencies,
        )
        return _ok(result)
    except Exception as e:
        log.error("skills_v2_install_error", skill_id=payload.skill_id, error=str(e))
        raise _fail(f"安装失败: {e}", 500) from e


@router.get(
    "/install/{task_id}/status",
    summary="📊 查询安装任务进度",
    description="按 task_id 查询异步安装任务状态",
)
async def get_install_status(task_id: str) -> dict:
    """查询安装任务进度"""
    marketplace = _get_marketplace()
    try:
        result = await marketplace.get_install_task(task_id)
        if "error" in result:
            return {"success": False, "error": result["error"]}
        return _ok(result)
    except Exception as e:
        log.error("skills_v2_install_status_error", task_id=task_id, error=str(e))
        raise _fail(f"查询任务失败: {e}", 500) from e


# ═══════════════════════════════════════════════════════════
# 5. 卸载
# ═══════════════════════════════════════════════════════════


@router.post(
    "/uninstall",
    summary="📤 卸载技能",
    description="卸载指定技能",
)
async def uninstall_skill(payload: SkillInstallRequest = Body(...)) -> dict:
    """卸载技能"""
    marketplace = _get_marketplace()
    try:
        result = await marketplace.uninstall_skill(payload.skill_id)
        return _ok(result)
    except Exception as e:
        log.error("skills_v2_uninstall_error", skill_id=payload.skill_id, error=str(e))
        raise _fail(f"卸载失败: {e}", 500) from e


# ═══════════════════════════════════════════════════════════
# 6. 评论提交 + 列表（V2 — 含 review_text）
# ═══════════════════════════════════════════════════════════


@router.post(
    "/{skill_id}/reviews",
    summary="💬 提交评价（V2）",
    description="评分 + 评论正文，一人一评（重复提交为更新）",
)
async def submit_review(skill_id: str, payload: SkillReviewRequest = Body(...)) -> dict:
    """提交评价"""
    marketplace = _get_marketplace()
    try:
        result = await marketplace.rate_skill(
            skill_id,
            payload.rating,
            user_id=payload.user_id,
            user_name=payload.user_name,
            review_text=payload.review_text,
        )
        return _ok(result)
    except Exception as e:
        log.error("skills_v2_review_error", skill_id=skill_id, error=str(e))
        raise _fail(f"提交评价失败: {e}", 500) from e


@router.get(
    "/{skill_id}/reviews",
    summary="💬 评论列表",
    description="分页获取评论列表",
)
async def list_reviews(
    skill_id: str,
    sort_by: str = Query(default="recent", pattern="^(recent|helpful|rating_desc|rating_asc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
) -> dict:
    """评论列表"""
    marketplace = _get_marketplace()
    try:
        result = await marketplace.get_reviews(
            skill_id,
            sort_by=sort_by,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return _ok(
            {"reviews": result["reviews"]},
            meta={
                "page": page,
                "page_size": page_size,
                "total": result["total"],
                "sort_by": result["sort_by"],
            },
        )
    except Exception as e:
        log.error("skills_v2_reviews_list_error", skill_id=skill_id, error=str(e))
        raise _fail(f"获取评论失败: {e}", 500) from e


# ═══════════════════════════════════════════════════════════
# 7. 更新检查 + 单技能更新 + 批量更新
# ═══════════════════════════════════════════════════════════


@router.get(
    "/updates/check",
    summary="🔄 检查更新",
    description="检查所有已安装技能的可用更新",
)
async def check_updates() -> dict:
    """检查更新"""
    marketplace = _get_marketplace()
    try:
        result = await marketplace.check_updates()
        return _ok(result)
    except Exception as e:
        log.error("skills_v2_check_updates_error", error=str(e))
        raise _fail(f"检查更新失败: {e}", 500) from e


@router.post(
    "/{skill_id}/update",
    summary="🔄 更新单技能",
    description="更新指定技能到最新版本",
)
async def update_skill(skill_id: str) -> dict:
    """更新单技能"""
    marketplace = _get_marketplace()
    try:
        result = await marketplace.update_skill_version(skill_id)
        return _ok(result)
    except Exception as e:
        log.error("skills_v2_update_error", skill_id=skill_id, error=str(e))
        raise _fail(f"更新失败: {e}", 500) from e


@router.post(
    "/update-all",
    summary="🔄 批量更新",
    description="批量更新所有有可用更新的技能",
)
async def update_all() -> dict:
    """批量更新"""
    marketplace = _get_marketplace()
    try:
        result = await marketplace.update_all()
        return _ok(result)
    except Exception as e:
        log.error("skills_v2_update_all_error", error=str(e))
        raise _fail(f"批量更新失败: {e}", 500) from e


# ═══════════════════════════════════════════════════════════
# 8. 收藏管理
# ═══════════════════════════════════════════════════════════


@router.post(
    "/favorite",
    summary="⭐ 收藏/取消收藏",
    description="切换技能收藏状态",
)
async def toggle_favorite(payload: SkillFavoriteRequest = Body(...)) -> dict:
    """收藏切换"""
    marketplace = _get_marketplace()
    try:
        result = await marketplace.toggle_favorite(payload.skill_id, payload.user_id)
        return _ok(result)
    except Exception as e:
        log.error("skills_v2_favorite_error", skill_id=payload.skill_id, error=str(e))
        raise _fail(f"收藏操作失败: {e}", 500) from e


@router.get(
    "/favorites/{user_id}",
    summary="⭐ 收藏列表",
    description="获取用户收藏的技能列表",
)
async def get_favorites(user_id: str) -> dict:
    """收藏列表"""
    marketplace = _get_marketplace()
    try:
        result = await marketplace.get_favorites(user_id)
        return _ok(result)
    except Exception as e:
        log.error("skills_v2_favorites_error", user_id=user_id, error=str(e))
        raise _fail(f"获取收藏失败: {e}", 500) from e


# ═══════════════════════════════════════════════════════════
# 9. 截图与版本管理（管理员/作者）
# ═══════════════════════════════════════════════════════════


@router.post(
    "/{skill_id}/screenshots",
    summary="📸 添加截图",
    description="为技能添加截图",
)
async def add_screenshot(skill_id: str, payload: SkillScreenshotRequest = Body(...)) -> dict:
    """添加截图"""
    marketplace = _get_marketplace()
    try:
        result = await marketplace.add_screenshot(
            skill_id, payload.url, payload.caption, payload.sort_order
        )
        return _ok(result)
    except Exception as e:
        log.error("skills_v2_screenshot_error", skill_id=skill_id, error=str(e))
        raise _fail(f"添加截图失败: {e}", 500) from e


@router.post(
    "/{skill_id}/versions",
    summary="🔖 添加版本",
    description="添加版本历史记录",
)
async def add_version(skill_id: str, payload: SkillVersionRequest = Body(...)) -> dict:
    """添加版本"""
    marketplace = _get_marketplace()
    try:
        result = await marketplace.add_version(
            skill_id,
            payload.version,
            changelog=payload.changelog,
            download_url=payload.download_url,
            released_at=payload.released_at,
        )
        return _ok(result)
    except Exception as e:
        log.error("skills_v2_version_error", skill_id=skill_id, error=str(e))
        raise _fail(f"添加版本失败: {e}", 500) from e


# ═══════════════════════════════════════════════════════════
# 10. 技能发布（V2 — 完整字段）
# ═══════════════════════════════════════════════════════════


@router.post(
    "/publish",
    summary="📦 发布技能（V2）",
    description="发布新技能，支持完整字段（含 markdown_content、dependencies）",
)
async def publish_skill(payload: SkillPublishRequest = Body(...)) -> dict:
    """发布技能"""
    from pycoder.skills import SkillDefinition

    marketplace = _get_marketplace()
    try:
        skill_def = SkillDefinition(
            id=payload.id,
            name=payload.name,
            description=payload.description,
            author=payload.author,
            publisher=payload.publisher or payload.author,
            category=payload.category,
            tags=payload.tags,
            dependencies=payload.dependencies,
            version=payload.version,
            markdown_content=payload.markdown_content or f"# {payload.name}\n\n{payload.description}",
            source_url=payload.source_url,
            homepage_url=payload.homepage_url,
            license=payload.license,
            icon_url=payload.icon_url,
            verified=payload.verified,
        )
        result = await marketplace.register_skill(skill_def, skill_def.markdown_content)
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "发布失败")}
        # 注册首版本
        if payload.version:
            await marketplace.add_version(
                payload.id, payload.version,
                changelog="初始发布",
            )
        return _ok(result)
    except Exception as e:
        log.error("skills_v2_publish_error", skill_id=payload.id, error=str(e))
        raise _fail(f"发布失败: {e}", 500) from e


# ═══════════════════════════════════════════════════════════
# 11. 市场统计
# ═══════════════════════════════════════════════════════════


@router.get(
    "/stats/overview",
    summary="📊 市场统计",
    description="技能总数、安装数、评分、分类分布",
)
async def get_stats() -> dict:
    """市场统计"""
    marketplace = _get_marketplace()
    try:
        stats = marketplace.get_stats()
        return _ok(stats)
    except Exception as e:
        log.error("skills_v2_stats_error", error=str(e))
        raise _fail(f"获取统计失败: {e}", 500) from e


# ═══════════════════════════════════════════════════════════
# 12. 远程 Registry 同步（V2 P4-1）
# ═══════════════════════════════════════════════════════════


class RegistrySyncRequest(BaseModel):
    """Registry 同步请求"""

    registry_url: str = Field(
        default="",
        description="Registry URL（空=使用默认 https://registry.pycoder.io）",
    )
    timeout: float = Field(default=30.0, ge=1.0, le=300.0, description="HTTP 超时（秒）")
    max_retries: int = Field(default=2, ge=0, le=5, description="失败重试次数")


@router.post(
    "/registry/sync",
    summary="🔄 从远程 Registry 同步技能",
    description="拉取远程技能索引和详情，同步到本地数据库（保留本地安装/评分数据）",
)
async def sync_registry(payload: RegistrySyncRequest = Body(...)) -> dict:
    """从远程 Registry 同步技能

    策略：
    - 新技能：INSERT
    - 已存在：UPDATE 远程字段（version/description/...），保留本地字段
      （install_count/rating/installed_at/local_version）
    - 同步后 remote_version 更新为远程最新版本（用于 has_update 检测）
    """
    from pycoder.skills.registry_client import (
        DEFAULT_REGISTRY_URL,
        RegistryClient,
    )

    marketplace = _get_marketplace()
    url = payload.registry_url or DEFAULT_REGISTRY_URL
    client = RegistryClient(
        registry_url=url,
        timeout=payload.timeout,
        max_retries=payload.max_retries,
    )
    try:
        result = await marketplace.sync_from_registry(client)
        return _ok(
            result,
            meta={"registry_url": url},
        )
    except Exception as e:
        log.error("skills_v2_registry_sync_error", url=url, error=str(e))
        raise _fail(f"Registry 同步失败: {e}", 500) from e


# ═══════════════════════════════════════════════════════════
# 外部数据源同步 (Tech Leads Club 84 + OpenClaw 5147)
# ═══════════════════════════════════════════════════════════


@router.post(
    "/external-sync",
    summary="🔄 同步外部高质技能（Tech Leads + OpenClaw）",
    description=(
        "从 Tech Leads Club (84 验证技能) 和 OpenClaw Awesome (5147 技能) "
        "采集并导入本地数据库，使前端可搜索。"
        "首次同步约需 25-40 秒（下载 30 个分类文件）。"
    ),
)
async def sync_external() -> dict:
    """同步外部技能到本地数据库"""
    marketplace = _get_marketplace()
    try:
        result = marketplace.import_external_skills()
        return _ok(
            {
                "added": result.get("added", 0),
                "skipped": result.get("skipped", 0),
                "errors": result.get("errors", 0),
                "total_in_db": result.get("total_in_db", 0),
                "sources": result.get("sources", []),
            },
            meta={
                "message": (
                    f"新增 {result.get('added', 0)} 个技能, "
                    f"数据库总计 {result.get('total_in_db', 0)} 个"
                ),
            },
        )
    except Exception as e:
        log.error("skills_external_sync_error", error=str(e))
        raise _fail(f"外部技能同步失败: {e}", 500) from e


__all__ = ["router"]
