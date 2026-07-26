/**
 * PanelContainer — 功能面板统一外壳容器
 *
 * 所有侧边栏面板统一使用此容器，确保布局一致性：
 *
 * ┌─────────────────────────────────────────────┐
 * │ PanelHeader                                 │
 * │  ← 返回按钮 | 图标 + 标题 | 操作按钮组     │
 * ├─────────────────────────────────────────────┤
 * │ PanelToolbar (可选)                         │
 * │  搜索栏 | 排序 | 分类过滤 | 视图切换       │
 * ├─────────────────────────────────────────────┤
 * │ PanelContent                                │
 * │  (children)                                 │
 * ├─────────────────────────────────────────────┤
 * │ PanelFooter (可选)                          │
 * │  状态信息 | 分页控件 | 计数               │
 * ├─────────────────────────────────────────────┤
 * │ PanelStatusBar                              │
 * │  操作状态 | 错误提示 | 进度指示           │
 * └─────────────────────────────────────────────┘
 */
import React, { useEffect, useRef, useState } from 'react';

/* ── Props ──────────────────────────────────── */

export interface PanelContainerProps {
    /** 面板标题 */
    title: string;
    /** 面板图标（emoji） */
    icon?: string;
    /** 是否显示加载中 */
    loading?: boolean;
    /** 是否为空 */
    empty?: boolean;
    /** 空状态提示文案 */
    emptyMessage?: string;
    /** 错误信息 */
    error?: string;
    /** 网络失败提示（含重试按钮） */
    networkFailed?: boolean;
    /** 重试回调 */
    onRetry?: () => void;
    /** 返回按钮回调（有值则显示返回按钮） */
    onBack?: () => void;
    /** 顶部操作按钮组 */
    headerActions?: React.ReactNode;
    /** 工具栏（搜索/排序/筛选等） */
    toolbar?: React.ReactNode;
    /** 底部栏（分页/计数等） */
    footer?: React.ReactNode;
    /** 状态消息（自动消失） */
    statusMsg?: string;
    /** 状态消息类型 */
    statusType?: 'info' | 'success' | 'error' | 'warning';
    /** 子内容 */
    children: React.ReactNode;
    /** 额外 CSS 类名 */
    className?: string;
}

/* ── 状态消息自动消失 Hook ──────────────────── */

const STATUS_DURATION: Record<string, number> = {
    success: 3000,
    info: 4000,
    warning: 8000,
    error: 10000,
};

function useAutoDismiss(msg: string | undefined, type: string) {
    const [visible, setVisible] = useState(false);
    const timerRef = useRef<ReturnType<typeof setTimeout>>();

    useEffect(() => {
        if (!msg) { setVisible(false); return; }
        setVisible(true);
        const ms = STATUS_DURATION[type] || 4000;
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => setVisible(false), ms);
        return () => { if (timerRef.current) clearTimeout(timerRef.current); };
    }, [msg, type]);

    return visible;
}

/* ── 骨架屏占位 ────────────────────────────── */

export const PanelSkeleton: React.FC<{ type?: 'card' | 'list' | 'detail'; rows?: number }> = ({
    type = 'card',
    rows = 6,
}) => {
    const shimmer = 'linear-gradient(90deg, var(--bg-secondary) 25%, var(--bg-tertiary) 50%, var(--bg-secondary) 75%)';
    const bg = { background: shimmer, backgroundSize: '200% 100%', animation: 'shimmer 1.5s infinite' };
    return (
        <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
            {Array.from({ length: rows }).map((_, i) => (
                <div key={i} style={{
                    ...bg,
                    height: type === 'card' ? 80 : type === 'detail' ? 200 : 40,
                    borderRadius: 6,
                }} />
            ))}
            <style>{`@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }`}</style>
        </div>
    );
};

/* ── 主组件 ────────────────────────────────── */

export const PanelContainer: React.FC<PanelContainerProps> = ({
    title,
    icon,
    loading,
    empty,
    emptyMessage,
    error,
    networkFailed,
    onRetry,
    onBack,
    headerActions,
    toolbar,
    footer,
    statusMsg,
    statusType = 'info',
    children,
    className,
}) => {
    const showStatus = useAutoDismiss(statusMsg, statusType);

    const statusColors: Record<string, string> = {
        success: '#27ae60',
        info: '#3498db',
        warning: '#f39c12',
        error: '#e74c3c',
    };

    return (
        <div className={'panel-container' + (className ? ' ' + className : '')}>
            {/* 头部 */}
            <div className="panel-header">
                <div className="panel-header-left">
                    {onBack && (
                        <button className="panel-back-btn" onClick={onBack} title="返回">
                            ←
                        </button>
                    )}
                    <span className="panel-title">
                        {icon && <span className="panel-icon">{icon}</span>}
                        {title}
                    </span>
                </div>
                {headerActions && <div className="panel-header-actions">{headerActions}</div>}
            </div>

            {/* 工具栏 */}
            {toolbar && <div className="panel-toolbar">{toolbar}</div>}

            {/* 内容区 */}
            <div className="panel-content">
                {loading && (children ? null : <PanelSkeleton />)}

                {!loading && error && (
                    <div className="panel-error">
                        <span>⚠️ {error}</span>
                        {onRetry && <button className="panel-retry-btn" onClick={onRetry}>重试</button>}
                    </div>
                )}

                {!loading && networkFailed && (
                    <div className="panel-network-warning">
                        ⚠️ 网络连接异常
                        {onRetry && <button className="panel-retry-btn" onClick={onRetry}>重试</button>}
                    </div>
                )}

                {!loading && !error && !networkFailed && empty && (
                    <div className="panel-empty">{emptyMessage || '暂无数据'}</div>
                )}

                {(!loading || !empty) && children}
            </div>

            {/* 底部 */}
            {footer && <div className="panel-footer">{footer}</div>}

            {/* 状态栏 */}
            {showStatus && statusMsg && (
                <div className="panel-statusbar" style={{ '--status-color': statusColors[statusType] || statusColors.info } as React.CSSProperties}>
                    {statusMsg}
                </div>
            )}
        </div>
    );
};
