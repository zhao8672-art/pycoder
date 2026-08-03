/**
 * MobileLayout — F4 移动端布局壳
 *
 * 聚合移动端三大核心视图：AI 聊天 / 终端 / 文件浏览（只读）。
 * 由 App.tsx 在 isMobile() 为真时渲染，替代桌面三栏布局。
 *
 * 设计要点：
 *   - 底部 tab 导航切换视图，已访问视图保持挂载（display:none）以保留状态
 *   - 文件浏览走 /api/mobile/files 精简接口，代码以只读 <pre> 查看（不加载 Monaco）
 *   - 首屏数据走 /api/mobile/summary 单次聚合请求，适应移动弱网
 */
import React, { useEffect, useState } from 'react';
import { AIPanel } from './AIPanel';
import TerminalPanel from './TerminalPanel';
import { Icon } from './common/Icon';
import type { IconName } from './common/Icon';
import { apiRequest } from '../services/api/client';
import { BackendAPI } from '../services/backend';
import { WSConnectionRegistry } from '../services/wsConnectionRegistry';
import { useBackendStore } from '../stores/backendStore';
import { useChatStore } from '../stores/chatStore';
import { useUIStore } from '../stores/uiStore';

/** 移动端 tab 标识 */
type MobileTab = 'chat' | 'terminal' | 'files';

/** /api/mobile/summary 响应（F4 后端首屏聚合数据） */
interface MobileSummary {
    workspace: string;
    workspace_name: string;
    session_count: number;
    running_tasks: number;
    version: string;
    mobile: boolean;
}

/** /api/mobile/files 单项（精简字段） */
interface MobileFileItem {
    name: string;
    is_dir: boolean;
    path: string;
    size: number;
}

/** /api/mobile/files 响应 */
interface MobileFilesResponse {
    path: string;
    workspace: string;
    count: number;
    truncated: boolean;
    items: MobileFileItem[];
}

/** 底部 tab 配置 */
const TABS: { key: MobileTab; label: string; icon: IconName }[] = [
    { key: 'chat', label: '聊天', icon: 'chat' },
    { key: 'terminal', label: '终端', icon: 'terminal' },
    { key: 'files', label: '文件', icon: 'folder' },
];

/** 文件大小人性化显示 */
function formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** 计算上级目录路径（相对工作区，'.' 表示根） */
function parentPath(p: string): string {
    if (p === '.' || !p.includes('/')) return '.';
    return p.slice(0, p.lastIndexOf('/'));
}

/**
 * 移动端文件浏览视图（只读）
 *
 * 目录导航基于 /api/mobile/files；文件内容通过 /api/files/read 只读展示，
 * 不加载 Monaco 编辑器（移动端仅浏览，不支持编辑）。
 */
const MobileFilesView: React.FC = () => {
    const [path, setPath] = useState('.');
    const [data, setData] = useState<MobileFilesResponse | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [viewer, setViewer] = useState<{ name: string; content: string } | null>(null);

    // 目录内容加载（路径变化时重新请求）
    useEffect(() => {
        let cancelled = false;
        const load = async () => {
            setLoading(true);
            setError(null);
            const res = await apiRequest<MobileFilesResponse>(
                `/api/mobile/files?path=${encodeURIComponent(path)}&limit=200`,
            );
            if (cancelled) return;
            setLoading(false);
            if (res) {
                setData(res);
            } else {
                setError('目录加载失败，请检查后端连接与 API Key');
            }
        };
        load();
        return () => {
            cancelled = true;
        };
    }, [path]);

    /** 点击条目：目录下钻 / 文件只读查看 */
    const openItem = async (item: MobileFileItem) => {
        if (item.is_dir) {
            setPath(item.path);
            return;
        }
        const res = await apiRequest<{ content?: string }>(
            `/api/files/read?path=${encodeURIComponent(item.path)}`,
        );
        if (res?.content !== undefined) {
            setViewer({ name: item.name, content: res.content });
        } else {
            setError('文件读取失败（可能为二进制或超过 1MB 限制）');
        }
    };

    return (
        <>
            <div className="mobile-files-toolbar">
                {path !== '.' && (
                    <button className="mobile-btn" onClick={() => setPath(parentPath(path))}>
                        返回
                    </button>
                )}
                <span className="mobile-files-path">{path === '.' ? '工作区根目录' : path}</span>
                <button className="mobile-btn" onClick={() => setPath('.')}>
                    根目录
                </button>
            </div>
            <div className="mobile-files-list">
                {loading && <div className="mobile-files-state">加载中…</div>}
                {error && <div className="mobile-files-state">{error}</div>}
                {!loading && !error && data && data.items.length === 0 && (
                    <div className="mobile-files-state">空目录</div>
                )}
                {!loading &&
                    data?.items.map((item) => (
                        <button
                            key={item.path}
                            className="mobile-file-item"
                            onClick={() => openItem(item)}
                        >
                            <Icon name={item.is_dir ? 'folder' : 'file-code'} size={18} />
                            <span className="mobile-file-item-name">{item.name}</span>
                            {!item.is_dir && (
                                <span className="mobile-file-item-size">{formatSize(item.size)}</span>
                            )}
                        </button>
                    ))}
                {!loading && data?.truncated && (
                    <div className="mobile-files-state">条目过多，已仅显示前 200 条</div>
                )}
            </div>
            {viewer && (
                <div className="mobile-file-viewer">
                    <div className="mobile-files-toolbar">
                        <button className="mobile-btn" onClick={() => setViewer(null)}>
                            关闭
                        </button>
                        <span className="mobile-files-path">{viewer.name}（只读）</span>
                    </div>
                    <pre>{viewer.content}</pre>
                </div>
            )}
        </>
    );
};

/** 移动端布局壳 — 底部 tab 导航 + 单视图切换 */
export const MobileLayout: React.FC = () => {
    const [activeTab, setActiveTab] = useState<MobileTab>('chat');
    // 已访问的 tab 保持挂载，避免终端/聊天状态丢失
    const [visited, setVisited] = useState<ReadonlySet<MobileTab>>(() => new Set(['chat']));
    const [ready, setReady] = useState(false);
    const [connectError, setConnectError] = useState(false);
    const [retryTick, setRetryTick] = useState(0);
    const [summary, setSummary] = useState<MobileSummary | null>(null);

    const theme = useUIStore((s) => s.theme);
    const backendStatus = useBackendStore((s) => s.backendStatus);
    const setBackendStatus = useBackendStore((s) => s.setBackendStatus);
    const wsClient = useBackendStore((s) => s.wsClient);

    // 应用主题（与桌面端一致）
    useEffect(() => {
        document.documentElement.setAttribute('data-theme', theme);
    }, [theme]);

    // WS 连接初始化（聊天面板依赖）
    useEffect(() => {
        WSConnectionRegistry.getInstance().then((client) => {
            useBackendStore.getState().setWsClient(client);
        });
        return () => {
            WSConnectionRegistry.disconnect();
        };
    }, []);

    // 后端健康检查 + 移动端首屏聚合数据（指数退避重试）
    useEffect(() => {
        let cancelled = false;
        let retries = 0;
        let timer: number | undefined;

        const check = async () => {
            if (cancelled) return;
            const health = await BackendAPI.health();
            if (health?.status === 'ok') {
                setBackendStatus('running');
                setConnectError(false);
                setReady(true);

                const [modelsRes, sessionsRes, summaryRes] = await Promise.all([
                    BackendAPI.models(),
                    BackendAPI.sessions.list(),
                    apiRequest<MobileSummary>('/api/mobile/summary'),
                ]);
                if (cancelled) return;

                if (modelsRes?.models) {
                    useChatStore.getState().setModels(modelsRes.models);
                    const recommended =
                        modelsRes.recommended_model || modelsRes.models[0]?.id || 'deepseek-chat';
                    useChatStore.getState().setCurrentModel(recommended);
                }
                if (sessionsRes?.sessions) {
                    useChatStore.getState().setSessions(sessionsRes.sessions);
                    useChatStore.getState().setActiveSession(sessionsRes.sessions[0]?.id || null);
                }
                if (summaryRes) setSummary(summaryRes);

                useBackendStore.getState().wsClient?.connect();
            } else {
                retries += 1;
                setConnectError(true);
                timer = window.setTimeout(check, Math.min(2000 * 2 ** (retries - 1), 15000));
            }
        };
        check();
        return () => {
            cancelled = true;
            window.clearTimeout(timer);
        };
    }, [setBackendStatus, retryTick]);

    /** 切换 tab（首次访问时加入保持挂载集合） */
    const switchTab = (tab: MobileTab) => {
        setActiveTab(tab);
        setVisited((prev) => (prev.has(tab) ? prev : new Set(prev).add(tab)));
    };

    // 后端未就绪：全屏连接占位
    if (!ready) {
        return (
            <div className="mobile-layout">
                <div className="mobile-loading">
                    <div className="loading-spinner" />
                    <div>{connectError ? '后端连接失败，正在自动重试…' : '正在连接后端服务…'}</div>
                    {connectError && (
                        <button
                            className="mobile-btn"
                            onClick={() => {
                                setConnectError(false);
                                setRetryTick((t) => t + 1);
                            }}
                        >
                            立即重试
                        </button>
                    )}
                </div>
            </div>
        );
    }

    return (
        <div className="mobile-layout">
            <header className="mobile-header">
                <span
                    className={`mobile-header-status${backendStatus === 'running' ? ' online' : ''}`}
                />
                <span className="mobile-header-title">PyCoder</span>
                <span className="mobile-header-summary">
                    {summary
                        ? `${summary.workspace_name} · 会话 ${summary.session_count} · 任务 ${summary.running_tasks}`
                        : ''}
                </span>
            </header>
            <div className="mobile-content">
                {visited.has('chat') && (
                    <div
                        className="mobile-view"
                        style={{ display: activeTab === 'chat' ? 'flex' : 'none' }}
                    >
                        <AIPanel wsClient={wsClient} />
                    </div>
                )}
                {visited.has('terminal') && (
                    <div
                        className="mobile-view"
                        style={{ display: activeTab === 'terminal' ? 'flex' : 'none' }}
                    >
                        <TerminalPanel />
                    </div>
                )}
                {activeTab === 'files' && (
                    <div className="mobile-view">
                        <MobileFilesView />
                    </div>
                )}
            </div>
            <nav className="mobile-tabbar">
                {TABS.map((t) => (
                    <button
                        key={t.key}
                        className={`mobile-tab${activeTab === t.key ? ' active' : ''}`}
                        onClick={() => switchTab(t.key)}
                    >
                        <Icon name={t.icon} size={20} />
                        <span>{t.label}</span>
                    </button>
                ))}
            </nav>
        </div>
    );
};

export default MobileLayout;
