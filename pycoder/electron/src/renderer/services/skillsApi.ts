/**
 * Skills Market API v2 客户端
 *
 * 通过 fetch 调用后端 `/api/v2/skills/*` 系列端点。
 * 所有方法返回完整响应体（{success, data, meta}）或 null（请求失败时）。
 *
 * 后端路由源: pycoder/server/routers/skills_v2_market_api.py
 */

import { getApiBase, getApiKey } from './config';

// ═══════════════════════════════════════════════════════════
// 类型定义
// ═══════════════════════════════════════════════════════════

/** 技能列表项（搜索结果中单条记录） */
export interface SkillItem {
    id: string;
    name: string;
    description: string;
    author: string;
    category: string;
    tags: string[];
    dependencies: string[];
    install_count: number;
    rating: number;
    rating_count: number;
    created_at: string;
    updated_at: string;
    is_builtin: boolean;
    installed: boolean;
    publisher: string;
    verified: boolean;
    source_url: string;
    homepage_url: string;
    license: string;
    icon_url: string;
    local_version: string;
    remote_version: string;
    stars: number;
    downloads: number;
    has_update: boolean;
    version: string;
}

/** 截图 */
export interface Screenshot {
    url: string;
    caption: string;
}

/** 版本记录 */
export interface SkillVersion {
    version: string;
    released_at: string;
    changelog: string;
    download_url: string;
    download_count: number;
}

/** 评论 */
export interface Review {
    id?: number;
    user: string;
    user_id: string;
    rating: number;
    review: string;
    review_text?: string;
    created_at: string;
    updated_at?: string;
    helpful_count: number;
}

/** 技能详情（含扩展数据） */
export interface SkillDetail extends SkillItem {
    markdown_content: string;
    screenshots: Screenshot[];
    versions: SkillVersion[];
    /** 评分分布：{ "5": 12, "4": 8, ... } */
    rating_distribution: Record<string, number>;
    reviews: Review[];
    recent_ratings?: Array<Record<string, unknown>>;
}

/** 异步安装任务 */
export interface InstallTask {
    task_id: string;
    skill_id: string;
    status: 'pending' | 'running' | 'success' | 'failed' | 'completed';
    progress: number;
    current_step: string;
    error: string;
    started_at: string;
    completed_at: string;
}

/** 搜索结果（data 部分） */
export interface SearchResult {
    skills: SkillItem[];
    query: string;
}

/** 搜索结果元信息 */
export interface SearchMeta {
    page: number;
    page_size: number;
    total: number;
    took_ms: number;
    sort_by: string;
}

/** 分类项 */
export interface Category {
    name: string;
    count: number;
    total_installs: number;
    avg_rating: number;
}

/** 单个可用更新 */
export interface UpdateInfo {
    skill_id: string;
    name: string;
    local_version: string;
    remote_version: string;
    source_url: string;
}

/** 市场统计 */
export interface MarketStats {
    total_skills: number;
    installed_skills: number;
    builtin_skills: number;
    average_rating: number;
    total_installs: number;
    total_ratings: number;
    categories: Record<string, number>;
    data_dir?: string;
}

// ═══════════════════════════════════════════════════════════
// 通用响应类型
// ═══════════════════════════════════════════════════════════

/** 统一响应格式 { success, data, meta } */
export interface ApiResponse<T = unknown, M = unknown> {
    success: boolean;
    data?: T;
    meta?: M;
    error?: string;
    detail?: string;
}

/** 搜索参数 */
export interface SearchParams {
    q?: string;
    category?: string;
    tags?: string;
    min_rating?: number;
    max_rating?: number;
    min_downloads?: number;
    max_downloads?: number;
    updated_within_days?: number;
    author?: string;
    verified_only?: boolean;
    has_update_only?: boolean;
    installed_only?: boolean | null;
    sort_by?: 'relevance' | 'rating' | 'downloads' | 'updated' | 'name' | 'stars';
    page?: number;
    page_size?: number;
}

/** 发布技能参数 */
export interface PublishParams {
    id: string;
    name: string;
    description: string;
    author?: string;
    publisher?: string;
    category?: string;
    tags?: string[];
    dependencies?: string[];
    version?: string;
    markdown_content?: string;
    source_url?: string;
    homepage_url?: string;
    license?: string;
    icon_url?: string;
    verified?: boolean;
}

/** 安装请求 */
export interface InstallParams {
    skill_id: string;
    install_dependencies?: boolean;
    async_mode?: boolean;
}

/** 评价提交 */
export interface ReviewParams {
    rating: number;
    review_text: string;
    user_id?: string;
    user_name?: string;
}

/** 收藏切换 */
export interface FavoriteParams {
    skill_id: string;
    user_id?: string;
}

/** 添加截图 */
export interface ScreenshotParams {
    url: string;
    caption?: string;
    sort_order?: number;
}

/** 添加版本 */
export interface VersionParams {
    version: string;
    changelog?: string;
    download_url?: string;
    released_at?: string;
}

// ═══════════════════════════════════════════════════════════
// 内部 fetch 封装
// ═══════════════════════════════════════════════════════════

/** 统一 fetch 调用，含超时与 API Key 注入 */
async function request<T = unknown, M = unknown>(
    path: string,
    options: RequestInit = {},
): Promise<ApiResponse<T, M> | null> {
    try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 30000);
        const base = await getApiBase();
        const apiKey = await getApiKey();
        const headers: Record<string, string> = {
            ...(options.headers as Record<string, string> || {}),
        };
        if (options.body && !headers['Content-Type']) {
            headers['Content-Type'] = 'application/json';
        }
        if (apiKey) {
            headers['X-API-Key'] = apiKey;
        }
        const res = await fetch(`${base}${path}`, {
            ...options,
            headers,
            signal: controller.signal,
        });
        clearTimeout(timeout);
        return (await res.json()) as ApiResponse<T, M>;
    } catch (err) {
        if ((err as Error).name !== 'AbortError') {
            console.error(`[skillsApi] ${path} failed:`, err);
        }
        return null;
    }
}

/** 序列化查询参数（跳过 undefined/null/空字符串） */
function buildQuery(params: Record<string, unknown>): string {
    const sp = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
        if (value === undefined || value === null || value === '') continue;
        if (typeof value === 'boolean') {
            sp.set(key, value ? 'true' : 'false');
        } else {
            sp.set(key, String(value));
        }
    }
    return sp.toString();
}

// ═══════════════════════════════════════════════════════════
// API 单例
// ═══════════════════════════════════════════════════════════

export const skillsApi = {
    /** 🔍 统一搜索（FTS5 + 12 维筛选 + 分页） */
    search(params: SearchParams): Promise<ApiResponse<SearchResult, SearchMeta> | null> {
        const query = buildQuery({
            q: params.q,
            category: params.category,
            tags: params.tags,
            min_rating: params.min_rating,
            max_rating: params.max_rating,
            min_downloads: params.min_downloads,
            max_downloads: params.max_downloads,
            updated_within_days: params.updated_within_days,
            author: params.author,
            verified_only: params.verified_only,
            has_update_only: params.has_update_only,
            installed_only: params.installed_only,
            sort_by: params.sort_by,
            page: params.page,
            page_size: params.page_size,
        });
        return request<SearchResult, SearchMeta>(`/api/v2/skills?${query}`);
    },

    /** 📂 分类列表（含计数） */
    categories(): Promise<ApiResponse<{ categories: Category[] }> | null> {
        return request<{ categories: Category[] }>('/api/v2/skills/categories');
    },

    /** 📖 技能详情（含截图/版本/评分分布/评论） */
    detail(skillId: string): Promise<ApiResponse<{ skill: SkillDetail }> | null> {
        return request<{ skill: SkillDetail }>(
            `/api/v2/skills/${encodeURIComponent(skillId)}`,
        );
    },

    /** 📥 安装技能（同步/异步） */
    install(params: InstallParams): Promise<ApiResponse<InstallTask | Record<string, unknown>> | null> {
        return request<InstallTask | Record<string, unknown>>(
            '/api/v2/skills/install',
            {
                method: 'POST',
                body: JSON.stringify({
                    skill_id: params.skill_id,
                    install_dependencies: params.install_dependencies ?? true,
                    async_mode: params.async_mode ?? false,
                }),
            },
        );
    },

    /** 📊 查询安装任务进度 */
    installStatus(taskId: string): Promise<ApiResponse<InstallTask> | null> {
        return request<InstallTask>(
            `/api/v2/skills/install/${encodeURIComponent(taskId)}/status`,
        );
    },

    /** 📤 卸载技能 */
    uninstall(skillId: string): Promise<ApiResponse<Record<string, unknown>> | null> {
        return request<Record<string, unknown>>('/api/v2/skills/uninstall', {
            method: 'POST',
            body: JSON.stringify({ skill_id: skillId, install_dependencies: true }),
        });
    },

    /** 💬 提交评价（一人一评，重复提交为更新） */
    submitReview(
        skillId: string,
        params: ReviewParams,
    ): Promise<ApiResponse<Record<string, unknown>> | null> {
        return request<Record<string, unknown>>(
            `/api/v2/skills/${encodeURIComponent(skillId)}/reviews`,
            {
                method: 'POST',
                body: JSON.stringify({
                    rating: params.rating,
                    review_text: params.review_text,
                    user_id: params.user_id ?? 'anonymous',
                    user_name: params.user_name ?? 'anonymous',
                }),
            },
        );
    },

    /** 💬 评论列表（分页 + 排序） */
    reviews(
        skillId: string,
        sortBy: 'recent' | 'helpful' | 'rating_desc' | 'rating_asc' = 'recent',
        page = 1,
        pageSize = 20,
    ): Promise<
        ApiResponse<{ reviews: Review[] }, {
            page: number;
            page_size: number;
            total: number;
            sort_by: string;
        }> | null
    > {
        const query = buildQuery({ sort_by: sortBy, page, page_size: pageSize });
        return request<{ reviews: Review[] }, {
            page: number;
            page_size: number;
            total: number;
            sort_by: string;
        }>(`/api/v2/skills/${encodeURIComponent(skillId)}/reviews?${query}`);
    },

    /** 🔄 检查更新 */
    checkUpdates(): Promise<ApiResponse<{ updates: UpdateInfo[]; count: number }> | null> {
        return request<{ updates: UpdateInfo[]; count: number }>(
            '/api/v2/skills/updates/check',
        );
    },

    /** 🔄 更新单技能 */
    updateSkill(skillId: string): Promise<ApiResponse<Record<string, unknown>> | null> {
        return request<Record<string, unknown>>(
            `/api/v2/skills/${encodeURIComponent(skillId)}/update`,
            { method: 'POST' },
        );
    },

    /** 🔄 批量更新所有有可用更新的技能 */
    updateAll(): Promise<ApiResponse<Record<string, unknown>> | null> {
        return request<Record<string, unknown>>('/api/v2/skills/update-all', {
            method: 'POST',
        });
    },

    /** ⭐ 收藏/取消收藏（切换） */
    toggleFavorite(params: FavoriteParams): Promise<ApiResponse<Record<string, unknown>> | null> {
        return request<Record<string, unknown>>('/api/v2/skills/favorite', {
            method: 'POST',
            body: JSON.stringify({
                skill_id: params.skill_id,
                user_id: params.user_id ?? 'anonymous',
            }),
        });
    },

    /** ⭐ 收藏列表 */
    favorites(userId: string): Promise<ApiResponse<{ favorites: SkillItem[] } | SkillItem[]> | null> {
        return request<{ favorites: SkillItem[] } | SkillItem[]>(
            `/api/v2/skills/favorites/${encodeURIComponent(userId)}`,
        );
    },

    /** 📸 添加截图 */
    addScreenshot(
        skillId: string,
        params: ScreenshotParams,
    ): Promise<ApiResponse<Record<string, unknown>> | null> {
        return request<Record<string, unknown>>(
            `/api/v2/skills/${encodeURIComponent(skillId)}/screenshots`,
            {
                method: 'POST',
                body: JSON.stringify({
                    url: params.url,
                    caption: params.caption ?? '',
                    sort_order: params.sort_order ?? 0,
                }),
            },
        );
    },

    /** 🔖 添加版本 */
    addVersion(
        skillId: string,
        params: VersionParams,
    ): Promise<ApiResponse<Record<string, unknown>> | null> {
        return request<Record<string, unknown>>(
            `/api/v2/skills/${encodeURIComponent(skillId)}/versions`,
            {
                method: 'POST',
                body: JSON.stringify({
                    version: params.version,
                    changelog: params.changelog ?? '',
                    download_url: params.download_url ?? '',
                    released_at: params.released_at ?? '',
                }),
            },
        );
    },

    /** 📦 发布技能（完整字段） */
    publish(params: PublishParams): Promise<ApiResponse<Record<string, unknown>> | null> {
        return request<Record<string, unknown>>('/api/v2/skills/publish', {
            method: 'POST',
            body: JSON.stringify({
                id: params.id,
                name: params.name,
                description: params.description,
                author: params.author ?? 'PyCoder',
                publisher: params.publisher ?? '',
                category: params.category ?? 'general',
                tags: params.tags ?? [],
                dependencies: params.dependencies ?? [],
                version: params.version ?? '1.0.0',
                markdown_content: params.markdown_content ?? '',
                source_url: params.source_url ?? '',
                homepage_url: params.homepage_url ?? '',
                license: params.license ?? '',
                icon_url: params.icon_url ?? '',
                verified: params.verified ?? false,
            }),
        });
    },

    /** 📊 市场统计 */
    stats(): Promise<ApiResponse<MarketStats> | null> {
        return request<MarketStats>('/api/v2/skills/stats/overview');
    },
};

export default skillsApi;
