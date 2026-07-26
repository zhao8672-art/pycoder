/**
 * StateWrapper — 统一的三态（加载/空/错误）包装组件
 *
 * 为所有面板组件提供一致的 loading / empty / error 状态展示，
 * 减少重复代码并统一视觉风格。
 */
import React from 'react';

interface StateWrapperProps {
  /** 是否加载中 */
  loading: boolean;
  /** 错误信息 */
  error: string | null;
  /** 是否无数据 */
  empty: boolean;
  /** 空状态提示文案 */
  emptyMessage?: string;
  /** 空状态自定义图标 */
  emptyIcon?: string;
  /** 自定义加载骨架屏 */
  loadingSkeleton?: React.ReactNode;
  /** 重试回调 */
  onRetry?: () => void;
  /** 子组件 */
  children: React.ReactNode;
}

export const StateWrapper: React.FC<StateWrapperProps> = ({
  loading,
  error,
  empty,
  emptyMessage = '暂无数据',
  emptyIcon = '📭',
  loadingSkeleton,
  onRetry,
  children,
}) => {
  if (loading) {
    if (loadingSkeleton) return <>{loadingSkeleton}</>;
    return (
      <div className="panel-state panel-loading">
        <div className="loading-spinner" />
        <span className="loading-text">加载中...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="panel-state panel-error">
        <span className="error-icon">⚠️</span>
        <span className="error-text">{error}</span>
        {onRetry && (
          <button className="panel-retry-btn" onClick={onRetry}>
            重试
          </button>
        )}
      </div>
    );
  }

  if (empty) {
    return (
      <div className="panel-state panel-empty">
        <span className="empty-icon">{emptyIcon}</span>
        <span className="empty-text">{emptyMessage}</span>
      </div>
    );
  }

  return <>{children}</>;
};