import React, { useState, useEffect, useCallback, useRef } from 'react';
import { BackendAPI } from '../services/backend';
import { PanelContainer } from './common/PanelContainer';

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
    installed?: boolean;
    enabled?: boolean;
    url?: string;
    installs?: number;
    is_seed?: boolean;
    updated_at?: number;
}

interface InstallProgress {
    taskId: string;
    extId: string;
    status: string;
    step: number;
    progress: number;
    message: string;
    error?: string;
}

const PAGE_SIZE = 20;

export const ExtensionsPanel: React.FC = () => {
    const [extensions, setExtensions] = useState<Extension[]>([]);
    const [installed, setInstalled] = useState<Extension[]>([]);
    const [loading, setLoading] = useState(false);
    const [search, setSearch] = useState('');
    const [category, setCategory] = useState('');
    const [sortBy, setSortBy] = useState<'stars' | 'name' | 'downloads'>('stars');
    const [tab, setTab] = useState<'recommended' | 'installed'>('recommended');
    const [statusMsg, setStatusMsg] = useState('');
    const [statusType, setStatusType] = useState<'info' | 'success' | 'error'>('info');
    const [actionLoading, setActionLoading] = useState<string | null>(null);
    const [error, setError] = useState('');
    const [networkFailed, setNetworkFailed] = useState(false);
    const [detailExt, setDetailExt] = useState<Extension | null>(null);
    const [page, setPage] = useState(0);
    const [total, setTotal] = useState(0);
    const [hasMore, setHasMore] = useState(false);
    const [categories, setCategories] = useState<string[]>([]);
    const [installProgress, setInstallProgress] = useState<Record<string, InstallProgress>>({});
    const pollRef = useRef<Record<string, ReturnType<typeof setInterval>>>({});
    const debounceRef = useRef<ReturnType<typeof setTimeout>>();
    const installedRef = useRef<Extension[]>([]);
    // 保持 installedRef 同步
    installedRef.current = installed;

    const showMsg = (msg: string, type: 'info' | 'success' | 'error' = 'info') => {
        setStatusMsg(msg);
        setStatusType(type);
        setTimeout(() => setStatusMsg(''), type === 'error' ? 5000 : 3000);
    };

    // ── 加载分类列表 ──
    useEffect(() => {
        BackendAPI.extensions.categories().then(res => {
            if (res?.categories) setCategories(res.categories);
        }).catch(() => { });
        fetchInstalled();
    }, []);

    // ── 搜索/筛选/排序/翻页 ──
    useEffect(() => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => {
            if (tab === 'recommended') fetchExtensions(search, page);
        }, 300);
        return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [search, category, sortBy, tab, page]);

    // Tab 切换时刷新
    useEffect(() => {
        fetchInstalled();
        if (tab === 'recommended') setPage(0);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [tab]);

    // 当已安装列表更新时，从当前市场列表中过滤掉已安装的扩展
    useEffect(() => {
        if (tab !== 'recommended' || extensions.length === 0) return;
        setExtensions(prev => prev.filter(e => !e.installed && !installed.some(i => i.id === e.id)));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [installed]);

    const fetchExtensions = useCallback(async (q: string = '', p: number = 0) => {
        if (tab !== 'recommended') return;
        setLoading(true);
        setError('');
        setNetworkFailed(false);
        try {
            let currentPage = p;
            let data: Extension[] = [];
            let totalCount = 0;
            let hasMoreData = false;
            const installedIds = new Set(installedRef.current.map(i => i.id));

            // 循环翻页直到找到有未安装扩展的页
            while (data.length === 0) {
                const offset = currentPage * PAGE_SIZE;
                const res = await BackendAPI.extensions.search(q, category, sortBy, PAGE_SIZE, offset);
                const list = res?.extensions || [];
                totalCount = res?.total || 0;
                hasMoreData = res?.has_more || false;
                data = list.filter(e => !e.installed && !installedIds.has(e.id));
                // 如果当前页全部是已安装的，尝试下一页
                if (data.length === 0 && list.length > 0 && hasMoreData) {
                    currentPage++;
                } else {
                    break;
                }
            }
            // 如果内部跳了页才更新 page state（不触发 debounce 重查）
            if (currentPage !== p) {
                // 直接修改 DOM state，跳过 effect 响应
                setPage(currentPage);
            }
            setExtensions(data);
            setTotal(totalCount);
            setHasMore(hasMoreData);
        } catch (err) {
            setError('无法连接扩展市场，请检查网络后重试');
            setNetworkFailed(true);
            setExtensions([]);
        }
        setLoading(false);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [tab, category, sortBy]);

    const fetchInstalled = useCallback(async () => {
        try {
            const res = await BackendAPI.extensions.installed();
            setInstalled(res?.extensions || []);
        } catch {
            if (tab === 'installed') {
                setError('加载已安装扩展失败');
                setNetworkFailed(true);
            }
        }
    }, [tab]);

    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

    // ── 异步安装轮询 ──
    const stopPoll = (taskId: string) => {
        if (pollRef.current[taskId]) {
            clearInterval(pollRef.current[taskId]);
            delete pollRef.current[taskId];
        }
    };

    const startPollInstall = (taskId: string, extId: string) => {
        if (pollRef.current[taskId]) return;
        pollRef.current[taskId] = setInterval(async () => {
            try {
                const res = await BackendAPI.extensions.installStatus(taskId);
                if (!res) return;
                setInstallProgress(prev => ({ ...prev, [extId]: res as unknown as InstallProgress }));
                if (res.status === 'done' || res.status === 'failed') {
                    stopPoll(taskId);
                    if (res.status === 'done') {
                        showMsg('✅ 安装完成', 'success');
                        setInstallProgress(prev => { const n = { ...prev }; delete n[extId]; return n; });
                        fetchInstalled();
                        setExtensions(prev => prev.map(e =>
                            e.id === extId ? { ...e, installed: true, enabled: true } : e
                        ));
                    } else {
                        showMsg('❌ 安装失败: ' + (res.error || '未知错误'), 'error');
                    }
                }
            } catch {
                stopPoll(taskId);
            }
        }, 1000);
    };

    useEffect(() => {
        return () => {
            Object.values(pollRef.current).forEach(id => clearInterval(id));
            pollRef.current = {};
        };
    }, []);

    const handleInstall = async (ext: Extension) => {
        setActionLoading(ext.id);
        showMsg('正在安装 ' + ext.name + '...', 'info');
        try {
            const res = await BackendAPI.extensions.install(ext.id);
            if (res?.task_id) {
                setInstallProgress(prev => ({
                    ...prev,
                    [ext.id]: { taskId: res.task_id!, extId: ext.id, status: 'pending', step: 0, progress: 0, message: '准备安装...' }
                }));
                startPollInstall(res.task_id, ext.id);
            } else if (res?.success) {
                showMsg('✅ ' + ext.name + ' 已安装', 'success');
                setExtensions(prev => prev.map(e =>
                    e.id === ext.id ? { ...e, installed: true, enabled: true } : e
                ));
                fetchInstalled();
            } else {
                showMsg('❌ 安装失败: ' + (res?.error || '未知'), 'error');
            }
        } catch {
            showMsg('❌ 安装失败: 网络错误', 'error');
        }
        setActionLoading(null);
    };

    const handleUninstall = async (id: string, name: string) => {
        setActionLoading(id);
        showMsg('正在卸载 ' + name + '...', 'info');
        try {
            const res = await BackendAPI.extensions.uninstall(id);
            if (res?.success) {
                showMsg('✅ ' + name + ' 已卸载', 'success');
                setExtensions(prev => prev.map(e =>
                    e.id === id ? { ...e, installed: false, enabled: false } : e
                ));
            } else {
                showMsg('❌ 卸载失败: ' + (res?.error || '未知'), 'error');
            }
        } catch {
            showMsg('❌ 卸载失败: 网络错误', 'error');
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
                showMsg('✅ ' + ext.name + (enable ? ' 已启用' : ' 已禁用'), 'success');
                setExtensions(prev => prev.map(e =>
                    e.id === ext.id ? { ...e, enabled: enable } : e
                ));
                fetchInstalled();
            } else {
                showMsg('❌ 操作失败', 'error');
            }
        } catch {
            showMsg('❌ 操作失败: 网络错误', 'error');
        }
        setActionLoading(null);
    };

    const handleUpdate = async (ext: Extension) => {
        setActionLoading(ext.id);
        showMsg('正在更新 ' + ext.name + '...', 'info');
        try {
            const res = await BackendAPI.extensions.update(ext.id);
            if (res?.success) {
                showMsg('✅ ' + ext.name + ' 已更新', 'success');
                fetchInstalled();
            } else {
                showMsg('❌ 更新失败: ' + (res?.error || '未知'), 'error');
            }
        } catch {
            showMsg('❌ 更新失败: 网络错误', 'error');
        }
        setActionLoading(null);
    };

    const handleRetry = () => {
        if (tab === 'recommended') fetchExtensions(search, page);
        else fetchInstalled();
    };

    // ── 安装进度条组件 ──
    const InstallProgressBar = ({ extId }: { extId: string }) => {
        const prog = installProgress[extId];
        if (!prog) return null;
        const stepLabels = ['', '下载中', '验证中', '安装中', '激活中', '已完成'];
        const barColor = prog.status === 'failed' ? '#e74c3c' : prog.status === 'done' ? '#27ae60' : '#3498db';
        return (
            <div style={{ marginTop: 6, padding: '4px 0' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>
                    <span>{prog.message || stepLabels[prog.step] || '...'}</span>
                    <span>{Math.round(prog.progress)}%</span>
                </div>
                <div style={{ height: 4, background: 'var(--border-color)', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ width: `${prog.progress}%`, height: '100%', background: barColor, borderRadius: 2, transition: 'width 0.5s ease' }}></div>
                </div>
                {prog.error && <div style={{ fontSize: 11, color: '#e74c3c', marginTop: 2 }}>{prog.error}</div>}
            </div>
        );
    };

    // ── 详情视图 ──
    if (detailExt) {
        const inst = detailExt.installed ?? false;
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
                            <a className="extensions-detail-link" href={detailExt.url} target="_blank" rel="noreferrer">查看源码 ↗</a>
                        )}
                        {inst && (
                            <div className="extensions-detail-status">
                                <span className={'extension-status-dot ' + (enabled ? 'enabled' : 'disabled')}></span>
                                {enabled ? '已启用' : '已禁用'}
                            </div>
                        )}
                        <InstallProgressBar extId={detailExt.id} />
                    </div>
                    <div className="extensions-detail-actions">
                        {inst ? (
                            <>
                                <button className={'extension-toggle-btn ' + (enabled ? 'toggle-disable' : 'toggle-enable')}
                                    disabled={actionLoading === detailExt.id}
                                    onClick={() => { handleToggleEnable(detailExt); }}>
                                    {actionLoading === detailExt.id ? '...' : (enabled ? '⏸ 禁用' : '▶ 启用')}
                                </button>
                                <button className="extension-update-btn"
                                    disabled={actionLoading === detailExt.id}
                                    onClick={() => { handleUpdate(detailExt); }}>
                                    {actionLoading === detailExt.id ? '...' : '🔄 更新'}
                                </button>
                                <button className="extension-uninstall-btn"
                                    disabled={actionLoading === detailExt.id}
                                    onClick={() => { handleUninstall(detailExt.id, detailExt.name); setDetailExt(null); }}>
                                    卸载
                                </button>
                            </>
                        ) : (
                            <button className="extension-install-btn"
                                disabled={actionLoading === detailExt.id}
                                onClick={() => { handleInstall(detailExt); }}>
                                {actionLoading === detailExt.id ? '安装中...' : '📥 安装'}
                            </button>
                        )}
                        <button className="extensions-detail-back" onClick={() => setDetailExt(null)}>返回</button>
                    </div>
                </div>
            </div>
        );
    }

    // ── 工具栏 ──
    const toolbar = (
        <>
            <div className="extensions-tabs">
                <button className={'extensions-tab' + (tab === 'recommended' ? ' active' : '')}
                    onClick={() => { setPage(0); setTab('recommended'); setError(''); setNetworkFailed(false); }}>
                    🏪 市场
                </button>
                <button className={'extensions-tab' + (tab === 'installed' ? ' active' : '')}
                    onClick={() => { setPage(0); setTab('installed'); setError(''); setNetworkFailed(false); }}>
                    📦 已安装 ({installed.length})
                </button>
            </div>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
                <input className="extensions-search" value={search}
                    onChange={e => { setSearch(e.target.value); setPage(0); }}
                    onKeyDown={e => { if (e.key === 'Enter') { setPage(0); fetchExtensions(search, 0); } }}
                    placeholder={tab === 'recommended' ? "搜索扩展名称..." : "筛选已安装扩展..."}
                    style={{ flex: 1, minWidth: 120 }} />
                {tab === 'recommended' && (
                    <>
                        <select className="extensions-sort" value={sortBy}
                            onChange={e => { setSortBy(e.target.value as any); setPage(0); }}
                            title="排序方式">
                            <option value="stars">⭐ 最多星</option>
                            <option value="downloads">📥 按下载</option>
                            <option value="name">📝 按名称</option>
                        </select>
                        <select className="extensions-category" value={category}
                            onChange={e => { setCategory(e.target.value); setPage(0); }}
                            title="筛选分类">
                            <option value="">🏷 全部分类</option>
                            {categories.map(c => <option key={c} value={c}>{c}</option>)}
                        </select>
                    </>
                )}
            </div>
        </>
    );

    // ── 分页底部 ──
    const footer = tab === 'recommended' && total > 0 ? (
        <div className="extensions-pagination" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <button className="extensions-page-btn" onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0 || loading}>◀ 上一页</button>
            <span className="extensions-page-info" style={{ fontSize: 12, opacity: 0.7 }}>
                第 {page + 1}/{totalPages} 页 · 共 {total} 个
            </span>
            <button className="extensions-page-btn" onClick={() => setPage(p => p + 1)} disabled={!hasMore || loading}>下一页 ▶</button>
            <input type="number" min={1} max={totalPages}
                style={{ width: 40, padding: '1px 3px', fontSize: 11 }}
                placeholder="页" title="跳转到页码（按 Enter）"
                onKeyDown={e => {
                    if (e.key === 'Enter') {
                        const v = parseInt((e.target as HTMLInputElement).value);
                        if (v >= 1 && v <= totalPages) setPage(v - 1);
                    }
                }} />
            <button className="extensions-page-btn" onClick={handleRetry} disabled={loading} title="刷新">🔄</button>
        </div>
    ) : tab === 'installed' && installed.length > 0 ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 4 }}>
            <button className="extensions-page-btn" onClick={handleRetry} disabled={loading} title="刷新已安装列表">🔄 刷新</button>
        </div>
    ) : undefined;

    // ── 当前显示列表 ──
    const displayList = tab === 'installed'
        ? (search ? installed.filter(e => e.name.toLowerCase().includes(search.toLowerCase())) : installed)
        : extensions;

    return (
        <PanelContainer
            title="扩展管理"
            icon="🧰"
            loading={loading && displayList.length === 0}
            empty={!loading && displayList.length === 0}
            emptyMessage={
                tab === 'installed'
                    ? (search ? '未找到匹配 "' + search + '" 的已安装扩展' : '暂无已安装的扩展\n点击"市场"标签浏览推荐扩展')
                    : (search ? '未找到 "' + search + '"' : (networkFailed ? '无法连接扩展市场' : '暂无可用扩展'))
            }
            error={error || undefined}
            networkFailed={networkFailed}
            onRetry={handleRetry}
            toolbar={toolbar}
            footer={footer}
            statusMsg={statusMsg}
            statusType={statusType}
        >
            {displayList.map((ext) => {
                const loadingThis = actionLoading === ext.id;
                const inst = ext.installed ?? installed.some(i => i.id === ext.id);
                const enabled = ext.enabled ?? true;
                const prog = installProgress[ext.id];
                return (
                    <div key={ext.id} className="extension-card"
                        onClick={() => setDetailExt(ext)}
                        style={{ cursor: 'pointer' }}>
                        <div className="extension-card-header">
                            <span className="extension-name">{ext.name}</span>
                            <span className="extension-stars">⭐ {ext.stars || 0}</span>
                        </div>
                        <div className="extension-desc" style={{ fontSize: 12, opacity: 0.8, lineHeight: 1.4 }}>
                            {ext.description?.substring(0, 120)}{ext.description?.length > 120 ? '...' : ''}
                        </div>
                        <div className="extension-meta" style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', fontSize: 11 }}>
                            <span>👤 {ext.author}</span>
                            <span>v{ext.version}</span>
                            {ext.tags?.slice(0, 3).map(t => (
                                <span key={t} className="extension-tag" style={{ fontSize: 10 }}>{t}</span>
                            ))}
                            {inst && <>
                                <span className={'extension-status-dot ' + (enabled ? 'enabled' : 'disabled')}></span>
                                <span className="extension-installed-badge" style={{ color: '#27ae60' }}>✓ 已安装</span>
                            </>}
                        </div>
                        <InstallProgressBar extId={ext.id} />
                        <div className="extension-actions" onClick={e => e.stopPropagation()}
                            style={{ display: 'flex', gap: 4, marginTop: 4 }}>
                            {loadingThis ? (
                                <span className="extension-loading-spin" style={{ fontSize: 14 }}>⏳</span>
                            ) : inst ? (
                                <>
                                    <button className="extension-toggle-sm" style={{ fontSize: 11, padding: '2px 6px' }}
                                        onClick={() => handleToggleEnable(ext)}>
                                        {enabled ? '⏸ 禁用' : '▶ 启用'}
                                    </button>
                                    <button className="extension-uninstall-btn-sm" style={{ fontSize: 11, padding: '2px 6px' }}
                                        onClick={() => handleUninstall(ext.id, ext.name)}>
                                        卸载
                                    </button>
                                </>
                            ) : prog && prog.status !== 'done' && prog.status !== 'failed' ? (
                                <span className="extension-loading-spin" style={{ fontSize: 14 }}>⏳</span>
                            ) : (
                                <button className="extension-install-btn-sm" onClick={() => handleInstall(ext)}
                                    style={{ fontSize: 11, padding: '2px 6px' }}>
                                    📥 安装
                                </button>
                            )}
                        </div>
                    </div>
                );
            })}
        </PanelContainer>
    );
};

export default ExtensionsPanel;
