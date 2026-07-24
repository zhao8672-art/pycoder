/**
 * Skills V2 搜索 Hook
 *
 * 组合 skillsApi.search + useDebounce(300ms) + 状态管理。
 * 监听查询参数变化，自动触发搜索并维护 loading/error/data/page 状态。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { skillsApi } from '../services/skillsApi';
import type {
    SearchParams,
    SkillItem,
} from '../services/skillsApi';
import { useDebounce } from './useDebounce';

export interface UseSkillsSearchResult {
    /** 当前页技能列表 */
    skills: SkillItem[];
    /** 总匹配数（来自 meta.total） */
    total: number;
    /** 加载中 */
    loading: boolean;
    /** 错误信息 */
    error: string;
    /** 当前页码 */
    page: number;
    /** 每页数量 */
    pageSize: number;
    /** 搜索耗时（ms） */
    tookMs: number;
    /** 总页数 */
    totalPages: number;
    /** 切换页码 */
    setPage: (page: number) => void;
    /** 手动刷新当前查询 */
    refresh: () => void;
}

/** 搜索参数（不含分页 — 分页由 hook 内部维护） */
export interface UseSkillsSearchParams extends Omit<SearchParams, 'page'> {
    /** 防抖延迟（默认 300ms） */
    debounceMs?: number;
    /** 每页数量（默认 20） */
    pageSize?: number;
}

export function useSkillsSearch(params: UseSkillsSearchParams): UseSkillsSearchResult {
    const {
        q = '',
        category = '',
        tags = '',
        min_rating,
        max_rating,
        min_downloads,
        max_downloads,
        updated_within_days,
        author = '',
        verified_only = false,
        has_update_only = false,
        installed_only = null,
        sort_by = 'relevance',
        debounceMs = 300,
        pageSize = 20,
    } = params;

    // 防抖搜索关键词（其他筛选条件即时触发）
    const debouncedQ = useDebounce(q, debounceMs);

    const [skills, setSkills] = useState<SkillItem[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [page, setPage] = useState(1);
    const [tookMs, setTookMs] = useState(0);
    const [refreshKey, setRefreshKey] = useState(0);

    // 任意筛选条件变化时，重置到第 1 页
    const filtersRef = useRef<string>('');
    const currentFilters = JSON.stringify({
        debouncedQ,
        category,
        tags,
        min_rating,
        max_rating,
        min_downloads,
        max_downloads,
        updated_within_days,
        author,
        verified_only,
        has_update_only,
        installed_only,
        sort_by,
        pageSize,
    });
    useEffect(() => {
        if (filtersRef.current && filtersRef.current !== currentFilters) {
            setPage(1);
        }
        filtersRef.current = currentFilters;
    }, [currentFilters]);

    const refresh = useCallback(() => {
        setRefreshKey((k) => k + 1);
    }, []);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError('');

        skillsApi
            .search({
                q: debouncedQ,
                category,
                tags,
                min_rating,
                max_rating,
                min_downloads,
                max_downloads,
                updated_within_days,
                author,
                verified_only,
                has_update_only,
                installed_only,
                sort_by,
                page,
                page_size: pageSize,
            })
            .then((res) => {
                if (cancelled) return;
                if (!res) {
                    setError('无法连接到技能市场');
                    setSkills([]);
                    setTotal(0);
                    return;
                }
                if (!res.success) {
                    setError(res.error || res.detail || '搜索失败');
                    setSkills([]);
                    setTotal(0);
                    return;
                }
                const data = res.data?.skills ?? [];
                const metaTotal = res.meta?.total ?? 0;
                const metaTook = res.meta?.took_ms ?? 0;
                setSkills(data);
                setTotal(metaTotal);
                setTookMs(metaTook);
            })
            .catch((err: unknown) => {
                if (cancelled) return;
                setError((err as Error)?.message || '搜索失败');
                setSkills([]);
                setTotal(0);
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });

        return () => {
            cancelled = true;
        };
        // refreshKey 用于手动刷新
    }, [
        debouncedQ,
        category,
        tags,
        min_rating,
        max_rating,
        min_downloads,
        max_downloads,
        updated_within_days,
        author,
        verified_only,
        has_update_only,
        installed_only,
        sort_by,
        page,
        pageSize,
        refreshKey,
    ]);

    const totalPages = pageSize > 0 ? Math.max(1, Math.ceil(total / pageSize)) : 1;

    return {
        skills,
        total,
        loading,
        error,
        page,
        pageSize,
        tookMs,
        totalPages,
        setPage,
        refresh,
    };
}

export default useSkillsSearch;
