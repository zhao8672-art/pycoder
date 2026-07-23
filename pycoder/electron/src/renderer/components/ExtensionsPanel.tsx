import React, { useState, useEffect, useCallback, useRef } from 'react';
import { BackendAPI } from '../services/backend';

interface Extension {
    id: string;
    name: string;
    description: string;
    author: string;
    stars: number;
    downloads?: number;
    category: string;
    tags: string[];
    version: string;
    installed: boolean;
    enabled?: boolean;
    url?: string;
    installs?: number;
    is_seed?: boolean;
    updated_at?: number;
}

export const ExtensionsPanel: React.FC = () => {
    const [extensions, setExtensions] = useState<Extension[]>([]);
    const [installed, setInstalled] = useState<Extension[]>([]);
    const [loading, setLoading] = useState(false);
    const [search, setSearch] = useState('');
    const [category, setCategory] = useState('');
    const [sortBy, setSortBy] = useState<'stars' | 'name' | 'downloads'>('stars');
    const [tab, setTab] = useState<'recommended' | 'installed'>('recommended');
    const [statusMsg, setStatusMsg] = useState('');
    const [actionLoading, setActionLoading] = useState<string | null>(null);
    const [error, setError] = useState('');
    const [networkFailed, setNetworkFailed] = useState(false);
    const [detailExt, setDetailExt] = useState<Extension | null>(null);
    const [page, setPage] = useState(0);
    const [hasMore, setHasMore] = useState(false);
    const PAGE_SIZE = 20;
    const debounceRef = useRef<ReturnType<typeof setTimeout>>();

    // Search/Filter/Page 变化时重新拉取
    useEffect(() => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => {
            if (tab === 'recommended') fetchExtensions(search);
        }, 400);
        return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
    }, [search, category, sortBy, page, tab]);

    const fetchExtensions = useCallback(async (q: string = '') => {
        setLoading(true);
        setError('');
        setNetworkFailed(false);
        try {
            const res = await BackendAPI.extensions.search(q, category, PAGE_SIZE, page * PAGE_SIZE);
            const list = res?.extensions || [];
            setExtensions(list);
            setHasMore(res?.has_more || false);
            if (list.length <= 6) {
                // Only seed data returned - GitHub API likely rate limited
            }
        } catch (err) {
            setError('无法连接扩展市场');
            setNetworkFailed(true);
            setExtensions([]);
        }
        setLoading(false);
    }, [page, category]);

    const fetchInstalled = useCallback(async () => {
        try {
            const res = await BackendAPI.extensions.installed();
            setInstalled(res?.extensions || []);
        } catch { }
    }, []);

    // Tab 切换时刷新已安装列表
    useEffect(() => {
        fetchInstalled();
    }, [tab]);

    const showMsg = (msg: string) => {
        setStatusMsg(msg);
        setTimeout(() => setStatusMsg(''), 3000);
    };

    const handleInstall = async (ext: Extension) => {
        setActionLoading(ext.id);
        setStatusMsg('正在安装 ' + ext.name + '...');
        try {
            const res = await BackendAPI.extensions.install(ext.id);
            if (res?.success) {
                showMsg(ext.name + ' 已安装');
                setExtensions(prev => prev.map(e =>
                    e.id === ext.id ? { ...e, installed: true } : e
                ));
            } else {
                showMsg('安装失败: ' + (res?.error || '未知'));
            }
        } catch {
            showMsg('安装失败: 网络错误');
        }
        setActionLoading(null);
        fetchInstalled();
    };

    const handleUninstall = async (id: string, name: string) => {
        setActionLoading(id);
        setStatusMsg('正在卸载 ' + name + '...');
        try {
            const res = await BackendAPI.extensions.uninstall(id);
            if (res?.success) {
                showMsg(name + ' 已卸载');
                setExtensions(prev => prev.map(e =>
                    e.id === id ? { ...e, installed: false } : e
                ));
            } else {
                showMsg('卸载失败: ' + (res?.error || '未知'));
            }
        } catch {
            showMsg('卸载失败: 网络错误');
        }
        setActionLoading(null);
        fetchInstalled();
    };

    const handleToggleEnable = async (ext: Extension) => {
        const enable = !(ext.enabled ?? true);
        setActionLoading(ext.id);
        try {
            const res = enable ? await BackendAPI.extensions.enable(ext.id) : await BackendAPI.extensions.disable(ext.id);
            if (res?.success) {
                showMsg(ext.name + (enable ? ' 已启用' : ' 已禁用'));
                setExtensions(prev => prev.map(e =>
                    e.id === ext.id ? { ...e, enabled: enable } : e
                ));
            }
        } catch {
            showMsg('切换失败: 网络错误');
        }
        setActionLoading(null);
        fetchInstalled();
    };

    const handleUpdate = async (ext: Extension) => {
        setActionLoading(ext.id);
        setStatusMsg('正在更新 ' + ext.name + '...');
        try {
            const res = await BackendAPI.extensions.update(ext.id);
            if (res?.success) {
                showMsg(ext.name + ' 已更新');
            } else {
                showMsg('更新失败: ' + (res?.error || '未知'));
            }
        } catch {
            showMsg('更新失败: 网络错误');
        }
        setActionLoading(null);
        fetchInstalled();
    };

    const isInstalledCheck = (ext: Extension) => ext.installed || installed.some(i => i.id === ext.id);

    const displayList = tab === 'installed' ? installed : extensions.filter(e => !isInstalledCheck(e))
        .sort((a, b) => {
            if (sortBy === 'stars') return b.stars - a.stars;
            if (sortBy === 'name') return a.name.localeCompare(b.name);
            return (b.downloads || b.stars) - (a.downloads || a.stars);
        });

    // Detail view
    if (detailExt) {
        const inst = isInstalledCheck(detailExt);
        const enabled = detailExt.enabled ?? true;
        return (
            <div className="extensions-panel">
                <div className="extensions-detail">
                    <div className="extensions-detail-header">
                        <span className="extensions-detail-name">{detailExt.name}</span>
                        <button className="extensions-detail-close" onClick={() => setDetailExt(null)}>✕</button>
                    </div>
                    <div className="extensions-detail-body">
                        <div className="extensions-detail-stars">⭐ {detailExt.stars}</div>
                        {detailExt.downloads !== undefined && (
                            <div className="extensions-detail-downloads">📥 {detailExt.downloads.toLocaleString()}</div>
                        )}
                        <p className="extensions-detail-desc">{detailExt.description}</p>
                        <div className="extensions-detail-meta">
                            <span>👤 {detailExt.author}</span>
                            <span>v{detailExt.version}</span>
                            <span>{detailExt.category || '未分类'}</span>
                            {detailExt.is_seed && <span className="extension-tag extension-tag-seed">内置</span>}
                        </div>
                        {detailExt.tags?.length > 0 && (
                            <div className="extensions-detail-tags">
                                {detailExt.tags.map(t => <span key={t} className="extension-tag">{t}</span>)}
                            </div>
                        )}
                        {detailExt.url && (
                            <a className="extensions-detail-link" href={detailExt.url} target="_blank" rel="noreferrer">查看源码</a>
                        )}
                        {inst && (
                            <div className="extensions-detail-status">
                                <span className={'extension-status-dot ' + (enabled ? 'enabled' : 'disabled')}></span>
                                {enabled ? '已启用' : '已禁用'}
                            </div>
                        )}
                    </div>
                    <div className="extensions-detail-actions">
                        {inst ? (
                            <>
                                <button
                                    className={'extension-toggle-btn ' + (enabled ? 'toggle-disable' : 'toggle-enable')}
                                    onClick={() => { handleToggleEnable(detailExt); setDetailExt(null); }}
                                >
                                    {enabled ? '禁用' : '启用'}
                                </button>
                                <button className="extension-update-btn" onClick={() => { handleUpdate(detailExt); }}>
                                    更新
                                </button>
                                <button className="extension-uninstall-btn" onClick={() => { handleUninstall(detailExt.id, detailExt.name); setDetailExt(null); }}>
                                    卸载
                                </button>
                            </>
                        ) : (
                            <button className="extension-install-btn" onClick={() => { handleInstall(detailExt); setDetailExt(null); }}>安装</button>
                        )}
                        <button className="extensions-detail-back" onClick={() => setDetailExt(null)}>返回</button>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="extensions-panel">
            <div className="extensions-header">
                <div className="extensions-tabs">
                    <button className={'extensions-tab' + (tab === 'recommended' ? ' active' : '')} onClick={() => setTab('recommended')}>推荐</button>
                    <button className={'extensions-tab' + (tab === 'installed' ? ' active' : '')} onClick={() => setTab('installed')}>已安装 ({installed.length})</button>
                </div>
                <input className="extensions-search" value={search} onChange={e => { setSearch(e.target.value); setPage(0); }} placeholder="搜索扩展..." />
                <div className="extensions-toolbar">
                    <select className="extensions-sort" value={sortBy} onChange={e => { setSortBy(e.target.value as any); setPage(0); }} title="排序">
                        <option value="stars">⭐ 最多星</option>
                        <option value="name">📝 按名称</option>
                        <option value="downloads">📥 按下载</option>
                    </select>
                    <select className="extensions-category" value={category} onChange={e => { setCategory(e.target.value); setPage(0); }} title="分类">
                        <option value="">全部分类</option>
                        <option value="git">Git</option>
                        <option value="devops">DevOps</option>
                        <option value="tools">工具</option>
                        <option value="code-quality">代码质量</option>
                        <option value="navigation">导航</option>
                    </select>
                </div>
            </div>

            {statusMsg && <div className="extensions-status">{statusMsg}</div>}
            {networkFailed && <div className="extensions-network-warning">⚠️ GitHub API 不可用，已加载内置扩展 <button onClick={() => fetchExtensions(search)}>重试</button></div>}

            <div className="extensions-list">
                {loading && <div className="extensions-loading">加载中...</div>}
                {!loading && displayList.length === 0 && (
                    <div className="extensions-empty">
                        {tab === 'installed' ? '暂无已安装的扩展' : (search ? '未找到 "' + search + '"' : '暂无可用扩展')}
                    </div>
                )}
                {displayList.map((ext) => {
                    const loadingThis = actionLoading === ext.id;
                    const inst = isInstalledCheck(ext);
                    const enabled = ext.enabled ?? true;
                    return (
                        <div key={ext.id} className="extension-card" onClick={() => setDetailExt(ext)}>
                            <div className="extension-card-header">
                                <span className="extension-name">{ext.name}</span>
                                <span className="extension-stars">⭐ {ext.stars}</span>
                            </div>
                            <div className="extension-desc">{ext.description}</div>
                            <div className="extension-meta">
                                <span>👤 {ext.author}</span>
                                <span>v{ext.version}</span>
                                {ext.tags?.slice(0, 3).map(t => <span key={t} className="extension-tag">{t}</span>)}
                                {inst && <>
                                    <span className={'extension-status-dot ' + (enabled ? 'enabled' : 'disabled')}></span>
                                    <span className="extension-installed-badge">✓ 已安装</span>
                                </>}
                            </div>
                            <div className="extension-actions" onClick={e => e.stopPropagation()}>
                                {loadingThis ? <span className="extension-loading-spin">⟳</span> : inst ? (
                                    <>
                                        <button className="extension-toggle-sm" onClick={() => handleToggleEnable(ext)}>
                                            {enabled ? '⏸ 禁用' : '▶ 启用'}
                                        </button>
                                        <button className="extension-uninstall-btn-sm" onClick={() => handleUninstall(ext.id, ext.name)}>卸载</button>
                                    </>
                                ) : (
                                    <button className="extension-install-btn-sm" onClick={() => handleInstall(ext)}>安装</button>
                                )}
                            </div>
                        </div>
                    );
                })}
                {tab === 'recommended' && hasMore && (
                    <div className="extensions-pagination">
                        <button className="extensions-page-btn" onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}>上一页</button>
                        <span className="extensions-page-info">第 {page + 1} 页</span>
                        <button className="extensions-page-btn" onClick={() => setPage(p => p + 1)} disabled={!hasMore}>下一页</button>
                    </div>
                )}
            </div>
        </div>
    );
};
