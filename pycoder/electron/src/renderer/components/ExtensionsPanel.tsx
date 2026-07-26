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
    installed: boolean;
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
    const [total, setTotal] = useState(0);
    const [hasMore, setHasMore] = useState(false);
    const [categories, setCategories] = useState<string[]>([]);
    // 异步安装进度
    const [installProgress, setInstallProgress] = useState<Record<string, InstallProgress>>({});
    const pollRef = useRef<Record<string, ReturnType<typeof setInterval>>>({});
    const PAGE_SIZE = 20;
    const debounceRef = useRef<ReturnType<typeof setTimeout>>();

    // 服务端分页: 搜索/筛选/排序/翻页
    useEffect(() => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => {
            if (tab === 'recommended') {
                fetchExtensions(search, page);
            }
        }, 300);
        return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [search, category, sortBy, tab, page]);

    // 首次加载动态分类列表
    useEffect(() => {
        const cats = new Set<string>();
        BackendAPI.extensions.search('', '', 500, 0).then(res => {
            if (res?.extensions) {
                res.extensions.forEach(e => { if (e.category) cats.add(e.category); });
                setCategories(Array.from(cats).sort());
            }
        });
        fetchInstalled();
    }, []);

    const fetchExtensions = useCallback(async (q: string = '', p: number = 0) => {
        if (tab !== 'recommended') return;
        setLoading(true);
        setError('');
        setNetworkFailed(false);
        try {
            const offset = p * PAGE_SIZE;
            const res = await BackendAPI.extensions.search(q, category, PAGE_SIZE, offset);
            const list = res?.extensions || [];
            // 标记已安装状态
            const filtered = list.filter(e => !isInstalledCheck(e));
            setExtensions(filtered);
            setTotal(res?.total || 0);
            setHasMore(res?.has_more || false);
        } catch (err) {
            setError('无法连接扩展市场');
            setNetworkFailed(true);
            setExtensions([]);
        }
        setLoading(false);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [tab, category]);

    const fetchInstalled = useCallback(async () => {
        try {
            const res = await BackendAPI.extensions.installed();
            setInstalled(res?.extensions || []);
        } catch { }
    }, []);

    // Tab 切换时刷新
    useEffect(() => {
        fetchInstalled();
        if (tab === 'recommended') {
            setPage(0);
            fetchExtensions(search, 0);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [tab]);

    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

    const showMsg = (msg: string) => {
        setStatusMsg(msg);
        // PanelContainer 的 useAutoDismiss 会自动消失
    };

    // ── 异步安装轮询 ──
    const startPollInstall = (taskId: string, extId: string) => {
        if (pollRef.current[taskId]) return;
        pollRef.current[taskId] = setInterval(async () => {
            try {
                const res = await BackendAPI.extensions.installStatus(taskId);
                if (!res) return;
                setInstallProgress(prev => ({ ...prev, [extId]: res as unknown as InstallProgress }));
                if (res.status === 'done' || res.status === 'failed') {
                    clearInterval(pollRef.current[taskId]);
                    delete pollRef.current[taskId];
                    if (res.status === 'done') {
                        showMsg('安装完成');
                        setExtensions(prev => prev.map(e =>
                            e.id === extId ? { ...e, installed: true } : e
                        ));
                        fetchInstalled();
                    } else {
                        showMsg('安装失败: ' + (res.error || '未知错误'));
                    }
                }
            } catch {
                clearInterval(pollRef.current[taskId]);
                delete pollRef.current[taskId];
            }
        }, 1000);
    };

    // 清理轮询
    useEffect(() => {
        return () => {
            Object.values(pollRef.current).forEach(id => clearInterval(id));
            pollRef.current = {};
        };
    }, []);

    const handleInstall = async (ext: Extension) => {
        setActionLoading(ext.id);
        setStatusMsg('正在安装 ' + ext.name + '...');
        try {
            const res = await BackendAPI.extensions.install(ext.id);
            if (res?.task_id) {
                setInstallProgress(prev => ({
                    ...prev,
                    [ext.id]: { taskId: res.task_id!, extId: ext.id, status: 'pending', step: 0, progress: 0, message: '准备安装...' }
                }));
                startPollInstall(res.task_id, ext.id);
            } else if (res?.success) {
                showMsg(ext.name + ' 已安装');
                setExtensions(prev => prev.map(e =>
                    e.id === ext.id ? { ...e, installed: true } : e
                ));
                fetchInstalled();
            } else {
                showMsg('安装失败: ' + (res?.error || '未知'));
            }
        } catch {
            showMsg('安装失败: 网络错误');
        }
        setActionLoading(null);
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

    // 当前页显示列表
    const displayList = tab === 'installed' ? installed : extensions;

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
                        <InstallProgressBar extId={detailExt.id} />
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

    // ── 工具栏 ──
    const toolbar = (
        <>
            <div className="extensions-tabs">
                <button className={'extensions-tab' + (tab === 'recommended' ? ' active' : '')} onClick={() => { setPage(0); setTab('recommended'); }}>推荐</button>
                <button className={'extensions-tab' + (tab === 'installed' ? ' active' : '')} onClick={() => { setPage(0); setTab('installed'); }}>已安装 ({installed.length})</button>
            </div>
            <input className="extensions-search" value={search} onChange={e => { setSearch(e.target.value); setPage(0); }} placeholder="搜索扩展..." />
            <select className="extensions-sort" value={sortBy} onChange={e => { setSortBy(e.target.value as any); setPage(0); }} title="排序">
                <option value="stars">⭐ 最多星</option>
                <option value="name">📝 按名称</option>
                <option value="downloads">📥 按下载</option>
            </select>
            <select className="extensions-category" value={category} onChange={e => { setCategory(e.target.value); setPage(0); }} title="分类">
                <option value="">全部分类</option>
                {categories.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
        </>
    );

    // ── 分页底部 ──
    const footer = tab === 'recommended' && total > 0 ? (
        <div className="extensions-pagination" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button className="extensions-page-btn" onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}>上一页</button>
            <span className="extensions-page-info">
                第 {page + 1}/{totalPages} 页 (共 {total} 个)
            </span>
            <button className="extensions-page-btn" onClick={() => setPage(p => p + 1)} disabled={!hasMore}>下一页</button>
            <input
                type="number"
                min={1}
                max={totalPages}
                style={{ width: 50, padding: '2px 4px', fontSize: 12 }}
                placeholder="..."
                onKeyDown={e => {
                    if (e.key === 'Enter') {
                        const v = parseInt((e.target as HTMLInputElement).value);
                        if (v >= 1 && v <= totalPages) setPage(v - 1);
                    }
                }}
            />
        </div>
    ) : undefined;

    return (
        <PanelContainer
            title="扩展管理"
            icon="🧰"
            loading={loading && displayList.length === 0}
            empty={!loading && displayList.length === 0}
            emptyMessage={tab === 'installed' ? '暂无已安装的扩展' : (search ? '未找到 "' + search + '"' : '暂无可用扩展')}
            error={error || undefined}
            networkFailed={networkFailed}
            onRetry={() => fetchExtensions(search, page)}
            toolbar={toolbar}
            footer={footer}
            statusMsg={statusMsg}
            statusType={statusMsg.includes('失败') || statusMsg.includes('错误') ? 'error' : statusMsg.includes('完成') ? 'success' : 'info'}
        >
            {displayList.map((ext) => {
                const loadingThis = actionLoading === ext.id;
                const inst = isInstalledCheck(ext);
                const enabled = ext.enabled ?? true;
                const prog = installProgress[ext.id];
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
                        <InstallProgressBar extId={ext.id} />
                        <div className="extension-actions" onClick={e => e.stopPropagation()}>
                            {loadingThis ? <span className="extension-loading-spin">⟳</span> : inst ? (
                                <>
                                    <button className="extension-toggle-sm" onClick={() => handleToggleEnable(ext)}>
                                        {enabled ? '⏸ 禁用' : '▶ 启用'}
                                    </button>
                                    <button className="extension-uninstall-btn-sm" onClick={() => handleUninstall(ext.id, ext.name)}>卸载</button>
                                </>
                            ) : prog && prog.status !== 'done' && prog.status !== 'failed' ? (
                                <span className="extension-loading-spin">⟳</span>
                            ) : (
                                <button className="extension-install-btn-sm" onClick={() => handleInstall(ext)}>安装</button>
                            )}
                        </div>
                    </div>
                );
            })}
        </PanelContainer>
    );
};
