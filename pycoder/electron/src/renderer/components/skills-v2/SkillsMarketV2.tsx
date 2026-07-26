/**
 * Skills Market V2 主入口组件
 *
 * 替代原 SkillsMarket.tsx，对接后端 `/api/v2/skills` 端点。
 *
 * 特性:
 * - 防抖搜索 + 输入建议下拉
 * - 可折叠左侧筛选侧栏（分类/评分/下载量/更新时间/已验证/仅有更新）
 * - 顶部 Tab：推荐 / 已安装 / 收藏
 * - 工具栏：排序下拉 + 全部更新 + 发布
 * - 卡片虚拟滚动（每页 20，滚动到底部自动加载下一页）
 * - 安装 4 步进度条（轮询 task status）
 * - 状态栏：total + took_ms + 当前页/总页数
 */

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { skillsApi } from '../../services/skillsApi';
import type {
    Category,
    InstallTask,
    SkillItem,
    SkillDetail as SkillDetailType,
} from '../../services/skillsApi';
import { useDebounce } from '../../hooks/useDebounce';
import { SkillDetailV2 } from './SkillDetailV2';
import { SkillPublishFormV2 } from './SkillPublishFormV2';

type TabKey = 'recommended' | 'installed' | 'favorites';
type SortKey = 'relevance' | 'rating' | 'downloads' | 'updated' | 'name' | 'stars';
type RatingFilter = 'all' | 'ge4' | 'ge3';
type DownloadsFilter = 'all' | 'gt1000' | '100to1000' | 'lt100';
type UpdatedFilter = 0 | 7 | 30 | 90;

/** 当前生效的筛选条件（传给搜索 API） */
interface ActiveFilters {
    category: string;
    minRating: number;
    minDownloads: number;
    maxDownloads: number;
    updatedWithinDays: number;
    verifiedOnly: boolean;
    hasUpdateOnly: boolean;
}

interface InstallProgress {
    taskId: string;
    skillId: string;
    status: InstallTask['status'];
    progress: number;
    step: string;
    error: string;
}

/** 安装进度字典：skill_id → InstallProgress */
type InstallProgressMap = Record<string, InstallProgress>;

/** 安装的 4 个阶段（用于进度条展示） */
const INSTALL_STEPS = ['检查依赖', '解析依赖图', '下载技能', '完成'];

export const SkillsMarketV2: React.FC = () => {
    // ── 顶部 Tab ──
    const [tab, setTab] = useState<TabKey>('recommended');

    // ── 搜索 ──
    const [searchInput, setSearchInput] = useState('');
    const debouncedSearch = useDebounce(searchInput, 300);
    const [showSuggestions, setShowSuggestions] = useState(false);

    // ── 筛选条件 ──
    const [selectedCategory, setSelectedCategory] = useState<string>('');
    const [ratingFilter, setRatingFilter] = useState<RatingFilter>('all');
    const [downloadsFilter, setDownloadsFilter] = useState<DownloadsFilter>('all');
    const [updatedFilter, setUpdatedFilter] = useState<UpdatedFilter>(0);
    const [verifiedOnly, setVerifiedOnly] = useState(false);
    const [hasUpdateOnly, setHasUpdateOnly] = useState(false);

    // ── 排序 ──
    const [sortBy, setSortBy] = useState<SortKey>('relevance');

    // ── 侧栏折叠 ──
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

    // ── 数据 ──
    const [skills, setSkills] = useState<SkillItem[]>([]);
    const [total, setTotal] = useState(0);
    const [tookMs, setTookMs] = useState(0);
    const [page, setPage] = useState(1);
    const [pageSize] = useState(100);
    const [loading, setLoading] = useState(false);
    const [loadingMore, setLoadingMore] = useState(false);
    const [error, setError] = useState('');
    const [hasMore, setHasMore] = useState(true);

    // ── 分页输入 ──
    const [jumpPageInput, setJumpPageInput] = useState('');

    // ── 分类 ──
    const [categories, setCategories] = useState<Category[]>([]);

    // ── 收藏列表 ──
    const [favorites, setFavorites] = useState<SkillItem[]>([]);

    // ── 详情/发布 ──
    const [detailSkill, setDetailSkill] = useState<SkillDetailType | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [showPublish, setShowPublish] = useState(false);

    // ── 安装进度 ──
    const [installProgress, setInstallProgress] = useState<InstallProgressMap>({});
    const pollingTimers = useRef<Record<string, ReturnType<typeof setInterval>>>({});

    // ── 全部更新 ──
    const [updatingAll, setUpdatingAll] = useState(false);
    const [statusMsg, setStatusMsg] = useState('');

    // ── 输入建议：从当前 skills 中按名称匹配前 5 ──
    const suggestions = useMemo(() => {
        if (!searchInput.trim()) return [];
        const q = searchInput.toLowerCase();
        return skills
            .filter((s) => s.name.toLowerCase().includes(q) || s.id.toLowerCase().includes(q))
            .slice(0, 5);
    }, [searchInput, skills]);

    // ── 计算当前生效的筛选条件 ──
    const activeFilters: ActiveFilters = useMemo(() => {
        const minRating = ratingFilter === 'ge4' ? 4 : ratingFilter === 'ge3' ? 3 : 0;
        let minDownloads = 0;
        let maxDownloads = 0;
        if (downloadsFilter === 'gt1000') {
            minDownloads = 1000;
        } else if (downloadsFilter === '100to1000') {
            minDownloads = 100;
            maxDownloads = 1000;
        } else if (downloadsFilter === 'lt100') {
            maxDownloads = 100;
        }
        return {
            category: selectedCategory,
            minRating,
            minDownloads,
            maxDownloads,
            updatedWithinDays: updatedFilter,
            verifiedOnly,
            hasUpdateOnly,
        };
    }, [selectedCategory, ratingFilter, downloadsFilter, updatedFilter, verifiedOnly, hasUpdateOnly]);

    // ── 拉取分类列表（仅一次 + tab/搜索变化时刷新总数） ──
    useEffect(() => {
        skillsApi
            .categories()
            .then((res) => {
                if (res?.success && res.data?.categories) {
                    setCategories(res.data.categories);
                }
            })
            .catch(() => { });
    }, []);

    // ── 拉取收藏列表（切到收藏 Tab 时） ──
    useEffect(() => {
        if (tab !== 'favorites') return;
        skillsApi
            .favorites('anonymous')
            .then((res) => {
                if (!res?.success) {
                    setFavorites([]);
                    return;
                }
                const data = res.data;
                if (Array.isArray(data)) {
                    setFavorites(data as SkillItem[]);
                } else if (data && Array.isArray((data as { favorites?: SkillItem[] }).favorites)) {
                    setFavorites((data as { favorites: SkillItem[] }).favorites);
                } else {
                    setFavorites([]);
                }
            })
            .catch(() => setFavorites([]));
    }, [tab]);

    // ── 搜索（重置到第 1 页） ──
    const fetchSkills = useCallback(
        async (targetPage: number, append: boolean) => {
            if (append) {
                setLoadingMore(true);
            } else {
                setLoading(true);
            }
            setError('');

            // Tab 转换为 installed_only 参数
            let installedOnly: boolean | null = null;
            if (tab === 'installed') installedOnly = true;
            else if (tab === 'recommended') installedOnly = false;

            try {
                const res = await skillsApi.search({
                    q: debouncedSearch,
                    category: activeFilters.category,
                    min_rating: activeFilters.minRating,
                    min_downloads: activeFilters.minDownloads,
                    max_downloads: activeFilters.maxDownloads,
                    updated_within_days: activeFilters.updatedWithinDays,
                    verified_only: activeFilters.verifiedOnly,
                    has_update_only: activeFilters.hasUpdateOnly,
                    installed_only: installedOnly,
                    sort_by: sortBy,
                    page: targetPage,
                    page_size: pageSize,
                });

                if (!res) {
                    setError('无法连接到技能市场');
                    setSkills([]);
                    setTotal(0);
                    setHasMore(false);
                    return;
                }
                if (!res.success) {
                    setError(res.error || res.detail || '搜索失败');
                    setSkills([]);
                    setTotal(0);
                    setHasMore(false);
                    return;
                }
                const list = res.data?.skills ?? [];
                const metaTotal = res.meta?.total ?? 0;
                const metaTook = res.meta?.took_ms ?? 0;

                setSkills((prev) => (append ? [...prev, ...list] : list));
                setTotal(metaTotal);
                setTookMs(metaTook);
                setHasMore(list.length === pageSize && targetPage * pageSize < metaTotal);
            } catch (err) {
                setError((err as Error)?.message || '搜索失败');
                if (!append) {
                    setSkills([]);
                    setTotal(0);
                }
                setHasMore(false);
            } finally {
                if (append) setLoadingMore(false);
                else setLoading(false);
            }
        },
        [debouncedSearch, activeFilters, sortBy, pageSize, tab],
    );

    // ── 主搜索：依赖变化触发（重置第 1 页） ──
    useEffect(() => {
        if (tab === 'favorites') return; // 收藏 Tab 不走搜索
        setPage(1);
        fetchSkills(1, false);
    }, [tab, fetchSkills]);

    // ── 滚动到底部自动加载下一页 ──
    const sentinelRef = useRef<HTMLDivElement | null>(null);
    useEffect(() => {
        if (tab === 'favorites') return;
        const el = sentinelRef.current;
        if (!el) return;
        const observer = new IntersectionObserver(
            (entries) => {
                const entry = entries[0];
                if (entry.isIntersecting && hasMore && !loadingMore && !loading) {
                    const nextPage = page + 1;
                    setPage(nextPage);
                    fetchSkills(nextPage, true);
                }
            },
            { rootMargin: '400px' },
        );
        observer.observe(el);
        return () => observer.disconnect();
    }, [hasMore, loadingMore, loading, page, fetchSkills, tab]);

    // ── 加载更多（按钮） ──
    const handleLoadMore = useCallback(() => {
        if (!hasMore || loadingMore || loading) return;
        const nextPage = page + 1;
        setPage(nextPage);
        fetchSkills(nextPage, true);
    }, [hasMore, loadingMore, loading, page, fetchSkills]);

    const totalPages = pageSize > 0 ? Math.max(1, Math.ceil(total / pageSize)) : 1;

    // ── 跳转到指定页 ──
    const handleJumpPage = useCallback(() => {
        const p = parseInt(jumpPageInput, 10);
        if (isNaN(p) || p < 1 || p > totalPages) return;
        setJumpPageInput('');
        setPage(p);
        fetchSkills(p, false);
    }, [jumpPageInput, totalPages, fetchSkills]);

    // ── 详情 ──
    const openDetail = useCallback(async (skillId: string) => {
        setDetailLoading(true);
        setDetailSkill(null);
        try {
            const res = await skillsApi.detail(skillId);
            if (res?.success && res.data?.skill) {
                setDetailSkill(res.data.skill);
            } else {
                setError(res?.error || '获取详情失败');
            }
        } catch (err) {
            setError((err as Error)?.message || '获取详情失败');
        } finally {
            setDetailLoading(false);
        }
    }, []);

    // ── 安装（异步 + 进度轮询） ──
    const startInstall = useCallback(
        async (skillId: string) => {
            try {
                const res = await skillsApi.install({
                    skill_id: skillId,
                    install_dependencies: true,
                    async_mode: true,
                });
                if (!res?.success) {
                    setError(res?.error || '启动安装任务失败');
                    return;
                }
                const taskId =
                    (res.data as InstallTask)?.task_id ||
                    (res.data as { task_id?: string })?.task_id ||
                    '';
                if (!taskId) {
                    // 同步安装完成，直接刷新
                    setStatusMsg(`✅ 已安装 ${skillId}`);
                    fetchSkills(1, false);
                    return;
                }
                // 初始化进度
                setInstallProgress((prev) => ({
                    ...prev,
                    [skillId]: {
                        taskId,
                        skillId,
                        status: 'pending',
                        progress: 0,
                        step: '检查依赖',
                        error: '',
                    },
                }));

                // 轮询任务状态
                const timer = setInterval(async () => {
                    const statusRes = await skillsApi.installStatus(taskId);
                    if (!statusRes?.success || !statusRes.data) return;
                    const task = statusRes.data;
                    setInstallProgress((prev) => ({
                        ...prev,
                        [skillId]: {
                            taskId,
                            skillId,
                            status: task.status,
                            progress: task.progress,
                            step: task.current_step || '',
                            error: task.error || '',
                        },
                    }));

                    if (task.status === 'success' || task.status === 'completed') {
                        const t = pollingTimers.current[skillId];
                        if (t) {
                            clearInterval(t);
                            delete pollingTimers.current[skillId];
                        }
                        setStatusMsg(`✅ ${skillId} 安装完成`);
                        setTimeout(() => {
                            setInstallProgress((prev) => {
                                const next = { ...prev };
                                delete next[skillId];
                                return next;
                            });
                        }, 2000);
                        fetchSkills(1, false);
                    } else if (task.status === 'failed') {
                        const t = pollingTimers.current[skillId];
                        if (t) {
                            clearInterval(t);
                            delete pollingTimers.current[skillId];
                        }
                        setError(`安装失败: ${task.error || '未知错误'}`);
                    }
                }, 800);
                pollingTimers.current[skillId] = timer;
            } catch (err) {
                setError((err as Error)?.message || '安装失败');
            }
        },
        [fetchSkills],
    );

    // ── 卸载 ──
    const handleUninstall = useCallback(
        async (skillId: string) => {
            setStatusMsg(`⏳ 卸载中 ${skillId}...`);
            try {
                const res = await skillsApi.uninstall(skillId);
                if (res?.success) {
                    setStatusMsg(`✅ 已卸载 ${skillId}`);
                    fetchSkills(1, false);
                } else {
                    setError(res?.error || '卸载失败');
                }
            } catch (err) {
                setError((err as Error)?.message || '卸载失败');
            }
        },
        [fetchSkills],
    );

    // ── 全部更新 ──
    const handleUpdateAll = useCallback(async () => {
        setUpdatingAll(true);
        setStatusMsg('⏳ 全部更新中...');
        try {
            const res = await skillsApi.updateAll();
            if (res?.success) {
                const data = res.data as { updated?: string[]; failed?: unknown[] };
                setStatusMsg(`✅ 已更新 ${data?.updated?.length ?? 0} 个技能`);
                fetchSkills(1, false);
            } else {
                setError(res?.error || '批量更新失败');
            }
        } catch (err) {
            setError((err as Error)?.message || '批量更新失败');
        } finally {
            setUpdatingAll(false);
        }
    }, [fetchSkills]);

    // ── 收藏切换 ──
    const handleToggleFavorite = useCallback(
        async (skillId: string) => {
            try {
                await skillsApi.toggleFavorite({ skill_id: skillId, user_id: 'anonymous' });
                if (tab === 'favorites') {
                    setFavorites((prev) => prev.filter((s) => s.id !== skillId));
                }
                setStatusMsg(`⭐ 已切换收藏 ${skillId}`);
            } catch (err) {
                setError((err as Error)?.message || '收藏操作失败');
            }
        },
        [tab],
    );

    // ── 清理轮询定时器 ──
    useEffect(() => {
        const timers = pollingTimers.current;
        return () => {
            Object.values(timers).forEach((t) => clearInterval(t));
        };
    }, []);

    // ── 自动隐藏状态消息 ──
    useEffect(() => {
        if (!statusMsg) return;
        const t = setTimeout(() => setStatusMsg(''), 4000);
        return () => clearTimeout(t);
    }, [statusMsg]);

    const hasUpdatesAvailable = skills.some((s) => s.has_update);

    // ═══════════════════════════════════════════════════════════
    // 渲染：发布表单
    // ═══════════════════════════════════════════════════════════
    if (showPublish) {
        return (
            <div className="skills-v2-container">
                <SkillPublishFormV2
                    onCancel={() => setShowPublish(false)}
                    onPublished={() => {
                        setShowPublish(false);
                        setStatusMsg('✅ 发布成功');
                        fetchSkills(1, false);
                    }}
                    categories={categories}
                />
            </div>
        );
    }

    // ═══════════════════════════════════════════════════════════
    // 渲染：详情页
    // ═══════════════════════════════════════════════════════════
    if (detailSkill || detailLoading) {
        return (
            <div className="skills-v2-container">
                {detailLoading ? (
                    <div className="skills-v2-loading">加载中...</div>
                ) : (
                    detailSkill && (
                        <SkillDetailV2
                            skill={detailSkill}
                            onBack={() => setDetailSkill(null)}
                            onInstall={(id) => {
                                startInstall(id);
                            }}
                            onUninstall={handleUninstall}
                            onToggleFavorite={handleToggleFavorite}
                            onUpdate={async (id) => {
                                const r = await skillsApi.updateSkill(id);
                                if (r?.success) {
                                    setStatusMsg(`✅ 已更新 ${id}`);
                                    openDetail(id);
                                } else {
                                    setError(r?.error || '更新失败');
                                }
                            }}
                        />
                    )
                )}
            </div>
        );
    }

    // ═══════════════════════════════════════════════════════════
    // 渲染：主列表
    // ═══════════════════════════════════════════════════════════
    const displaySkills = tab === 'favorites' ? favorites : skills;

    return (
        <div className="skills-v2-container">
            {/* 顶部标题栏 */}
            <div className="skills-v2-header">
                <h3 className="skills-v2-title">🧩 技能市场 V2</h3>
                <div className="skills-v2-header-actions">
                    {hasUpdatesAvailable && (
                        <button
                            className="skills-v2-btn skills-v2-btn-update-all"
                            onClick={handleUpdateAll}
                            disabled={updatingAll}
                        >
                            {updatingAll ? '⏳ 更新中...' : '🔄 全部更新'}
                        </button>
                    )}
                    <button
                        className="skills-v2-btn skills-v2-btn-publish"
                        onClick={() => setShowPublish(true)}
                    >
                        📦 发布
                    </button>
                </div>
            </div>

            {/* 顶部 Tab */}
            <div className="skills-v2-tabs">
                <button
                    className={`skills-v2-tab ${tab === 'recommended' ? 'active' : ''}`}
                    onClick={() => setTab('recommended')}
                >
                    🔥 推荐
                </button>
                <button
                    className={`skills-v2-tab ${tab === 'installed' ? 'active' : ''}`}
                    onClick={() => setTab('installed')}
                >
                    ✅ 已安装
                </button>
                <button
                    className={`skills-v2-tab ${tab === 'favorites' ? 'active' : ''}`}
                    onClick={() => setTab('favorites')}
                >
                    ⭐ 收藏 ({favorites.length})
                </button>
            </div>

            {/* 搜索栏 + 工具栏 */}
            <div className="skills-v2-toolbar">
                <div className="skills-v2-search-wrapper">
                    <input
                        className="skills-v2-search-input"
                        placeholder="搜索技能..."
                        value={searchInput}
                        onChange={(e) => {
                            setSearchInput(e.target.value);
                            setShowSuggestions(true);
                        }}
                        onFocus={() => setShowSuggestions(true)}
                        onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
                    />
                    {showSuggestions && suggestions.length > 0 && (
                        <ul className="skills-v2-suggestions">
                            {suggestions.map((s) => (
                                <li
                                    key={s.id}
                                    className="skills-v2-suggestion-item"
                                    onClick={() => {
                                        setSearchInput(s.name);
                                        setShowSuggestions(false);
                                        openDetail(s.id);
                                    }}
                                >
                                    <span className="skills-v2-suggestion-icon">
                                        {s.icon_url ? (
                                            <img src={s.icon_url} alt="" width={20} height={20} />
                                        ) : (
                                            '🧩'
                                        )}
                                    </span>
                                    <span className="skills-v2-suggestion-name">{s.name}</span>
                                    <span className="skills-v2-suggestion-meta">
                                        ⭐ {s.rating.toFixed(1)} · ⬇ {s.downloads}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>

                <select
                    className="skills-v2-sort-select"
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value as SortKey)}
                    aria-label="排序"
                >
                    <option value="relevance">相关性</option>
                    <option value="rating">评分最高</option>
                    <option value="downloads">下载最多</option>
                    <option value="updated">最近更新</option>
                    <option value="name">按名称</option>
                    <option value="stars">最多星</option>
                </select>

                <button
                    className="skills-v2-btn skills-v2-btn-sidebar-toggle"
                    onClick={() => setSidebarCollapsed((c) => !c)}
                >
                    {sidebarCollapsed ? '☰' : '✕'}
                </button>
            </div>

            {/* 主体：侧栏 + 卡片列表 */}
            <div className="skills-v2-body">
                {/* 左侧筛选栏 */}
                {!sidebarCollapsed && (
                    <aside className="skills-v2-sidebar">
                        <div className="skills-v2-sidebar-section">
                            <h4 className="skills-v2-sidebar-title">📂 分类</h4>
                            <div className="skills-v2-checkbox-list">
                                <label className="skills-v2-checkbox-item">
                                    <input
                                        type="radio"
                                        name="category"
                                        checked={selectedCategory === ''}
                                        onChange={() => setSelectedCategory('')}
                                    />
                                    <span>全部</span>
                                </label>
                                {categories.map((c) => (
                                    <label key={c.name} className="skills-v2-checkbox-item">
                                        <input
                                            type="radio"
                                            name="category"
                                            checked={selectedCategory === c.name}
                                            onChange={() => setSelectedCategory(c.name)}
                                        />
                                        <span>{c.name}</span>
                                        <span className="skills-v2-count-badge">{c.count}</span>
                                    </label>
                                ))}
                            </div>
                        </div>

                        <div className="skills-v2-sidebar-section">
                            <h4 className="skills-v2-sidebar-title">⭐ 评分</h4>
                            <select
                                className="skills-v2-select"
                                value={ratingFilter}
                                onChange={(e) => setRatingFilter(e.target.value as RatingFilter)}
                            >
                                <option value="all">全部</option>
                                <option value="ge4">≥ 4 星</option>
                                <option value="ge3">≥ 3 星</option>
                            </select>
                        </div>

                        <div className="skills-v2-sidebar-section">
                            <h4 className="skills-v2-sidebar-title">⬇ 下载量</h4>
                            <select
                                className="skills-v2-select"
                                value={downloadsFilter}
                                onChange={(e) => setDownloadsFilter(e.target.value as DownloadsFilter)}
                            >
                                <option value="all">全部</option>
                                <option value="gt1000">&gt; 1000</option>
                                <option value="100to1000">100 - 1000</option>
                                <option value="lt100">&lt; 100</option>
                            </select>
                        </div>

                        <div className="skills-v2-sidebar-section">
                            <h4 className="skills-v2-sidebar-title">📅 更新时间</h4>
                            <select
                                className="skills-v2-select"
                                value={String(updatedFilter)}
                                onChange={(e) =>
                                    setUpdatedFilter(Number(e.target.value) as UpdatedFilter)
                                }
                            >
                                <option value="0">全部</option>
                                <option value="7">最近 7 天</option>
                                <option value="30">最近 30 天</option>
                                <option value="90">最近 90 天</option>
                            </select>
                        </div>

                        <div className="skills-v2-sidebar-section">
                            <h4 className="skills-v2-sidebar-title">其他</h4>
                            <label className="skills-v2-checkbox-item">
                                <input
                                    type="checkbox"
                                    checked={verifiedOnly}
                                    onChange={(e) => setVerifiedOnly(e.target.checked)}
                                />
                                <span>仅已验证</span>
                            </label>
                            <label className="skills-v2-checkbox-item">
                                <input
                                    type="checkbox"
                                    checked={hasUpdateOnly}
                                    onChange={(e) => setHasUpdateOnly(e.target.checked)}
                                />
                                <span>仅有更新</span>
                            </label>
                        </div>
                    </aside>
                )}

                {/* 主区域 */}
                <main className="skills-v2-main">
                    {loading && <div className="skills-v2-loading">加载中...</div>}
                    {error && <div className="skills-v2-error">❌ {error}</div>}
                    {!loading && !error && displaySkills.length === 0 && (
                        <div className="skills-v2-empty">暂无数据</div>
                    )}

                    {!error && displaySkills.length > 0 && (
                        <div className="skills-v2-card-list">
                            {displaySkills.map((skill) => {
                                const prog = installProgress[skill.id];
                                return (
                                    <div
                                        key={skill.id}
                                        className="skills-v2-card"
                                        onClick={() => openDetail(skill.id)}
                                    >
                                        <div className="skills-v2-card-header">
                                            <span className="skills-v2-card-icon">
                                                {skill.icon_url ? (
                                                    <img
                                                        src={skill.icon_url}
                                                        alt=""
                                                        width={32}
                                                        height={32}
                                                    />
                                                ) : (
                                                    '🧩'
                                                )}
                                            </span>
                                            <div className="skills-v2-card-title">
                                                <span className="skills-v2-card-name">
                                                    {skill.name}
                                                </span>
                                                {skill.verified && (
                                                    <span
                                                        className="skills-v2-badge skills-v2-badge-verified"
                                                        title="已验证"
                                                    >
                                                        ✓
                                                    </span>
                                                )}
                                                {skill.has_update && (
                                                    <span
                                                        className="skills-v2-badge skills-v2-badge-update"
                                                        title="有可用更新"
                                                    >
                                                        🔄 更新
                                                    </span>
                                                )}
                                            </div>
                                            <div className="skills-v2-card-stats">
                                                <span title="评分">⭐ {skill.rating.toFixed(1)}</span>
                                                <span title="下载量">⬇ {skill.downloads}</span>
                                                <span title="版本">🏷 v{skill.version || '-'}</span>
                                            </div>
                                        </div>

                                        <p className="skills-v2-card-desc">
                                            {skill.description || '暂无描述'}
                                        </p>

                                        {skill.tags && skill.tags.length > 0 && (
                                            <div className="skills-v2-card-tags">
                                                {skill.tags.slice(0, 5).map((t) => (
                                                    <span key={t} className="skills-v2-tag">
                                                        {t}
                                                    </span>
                                                ))}
                                            </div>
                                        )}

                                        {/* 安装进度条 */}
                                        {prog && (
                                            <div className="skills-v2-install-progress">
                                                <div className="skills-v2-progress-steps">
                                                    {INSTALL_STEPS.map((step, idx) => {
                                                        const stepProgress = ((idx + 1) / INSTALL_STEPS.length) * 100;
                                                        const active = prog.progress >= stepProgress - 25;
                                                        return (
                                                            <span
                                                                key={step}
                                                                className={`skills-v2-progress-step ${active ? 'active' : ''
                                                                    }`}
                                                            >
                                                                {active ? '✓' : idx + 1}. {step}
                                                            </span>
                                                        );
                                                    })}
                                                </div>
                                                <div className="skills-v2-progress-bar">
                                                    <div
                                                        className="skills-v2-progress-fill"
                                                        style={{ width: `${prog.progress}%` }}
                                                    />
                                                </div>
                                                <div className="skills-v2-progress-info">
                                                    {prog.step} ({prog.progress}%)
                                                    {prog.error && (
                                                        <span className="skills-v2-progress-error">
                                                            {' '}— {prog.error}
                                                        </span>
                                                    )}
                                                </div>
                                            </div>
                                        )}

                                        <div
                                            className="skills-v2-card-actions"
                                            onClick={(e) => e.stopPropagation()}
                                        >
                                            {!skill.installed ? (
                                                <button
                                                    className="skills-v2-btn skills-v2-btn-install"
                                                    onClick={() => startInstall(skill.id)}
                                                    disabled={!!prog}
                                                >
                                                    📥 安装
                                                </button>
                                            ) : (
                                                <>
                                                    <button
                                                        className="skills-v2-btn skills-v2-btn-uninstall"
                                                        onClick={() => handleUninstall(skill.id)}
                                                    >
                                                        📤 卸载
                                                    </button>
                                                    {skill.has_update && (
                                                        <button
                                                            className="skills-v2-btn skills-v2-btn-update"
                                                            onClick={async () => {
                                                                const r = await skillsApi.updateSkill(skill.id);
                                                                if (r?.success) {
                                                                    setStatusMsg(`✅ 已更新 ${skill.name}`);
                                                                    fetchSkills(1, false);
                                                                } else {
                                                                    setError(r?.error || '更新失败');
                                                                }
                                                            }}
                                                        >
                                                            🔄 更新
                                                        </button>
                                                    )}
                                                </>
                                            )}
                                            <button
                                                className="skills-v2-btn skills-v2-btn-favorite"
                                                onClick={() => handleToggleFavorite(skill.id)}
                                            >
                                                ⭐
                                            </button>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}

                    {/* 无限滚动哨兵 + 加载更多按钮 */}
                    {tab !== 'favorites' && (
                        <div className="skills-v2-pagination-bar">
                            {/* 空哨兵（用于 IntersectionObserver 触发下一页） */}
                            {hasMore && (
                                <div ref={sentinelRef} className="skills-v2-sentinel" style={{ height: 1 }} />
                            )}

                            {/* 加载更多按钮 */}
                            {hasMore && (
                                <button
                                    className="skills-v2-btn skills-v2-btn-load-more"
                                    onClick={handleLoadMore}
                                    disabled={loadingMore || loading}
                                >
                                    {loadingMore
                                        ? '⏳ 加载中...'
                                        : `📥 加载更多（当前 ${displaySkills.length} / ${total}）`}
                                </button>
                            )}

                            {!hasMore && total > 0 && (
                                <div className="skills-v2-all-loaded">
                                    ✅ 全部加载完毕（共 {total} 个技能）
                                </div>
                            )}

                            {/* 分页跳转 */}
                            {totalPages > 1 && (
                                <div className="skills-v2-page-jump">
                                    <span>
                                        第 {page} / {totalPages} 页
                                    </span>
                                    <input
                                        className="skills-v2-page-input"
                                        type="number"
                                        min={1}
                                        max={totalPages}
                                        placeholder="跳转页"
                                        value={jumpPageInput}
                                        onChange={(e) => setJumpPageInput(e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter') handleJumpPage();
                                        }}
                                    />
                                    <button
                                        className="skills-v2-btn skills-v2-btn-jump"
                                        onClick={handleJumpPage}
                                    >
                                        跳转
                                    </button>
                                </div>
                            )}

                            {/* 状态信息 */}
                            <div className="skills-v2-status-bar">
                                <span>共 {total} 个技能</span>
                                <span>耗时 {tookMs} ms</span>
                                {statusMsg && (
                                    <span className="skills-v2-status-msg">{statusMsg}</span>
                                )}
                            </div>
                        </div>
                    )}
                </main>
            </div>
        </div>
    );
};

export default SkillsMarketV2;
