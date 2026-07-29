import React from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface Props {
    children: ReactNode;
}

interface State {
    hasError: boolean;
    errorMessage: string;
    errorStack: string;
}

/**
 * 渲染进程错误边界 — 捕获 React 渲染树异常，避免整个页面白屏
 */
export class ErrorBoundary extends React.Component<Props, State> {
    constructor(props: Props) {
        super(props);
        this.state = { hasError: false, errorMessage: '', errorStack: '' };
    }

    static getDerivedStateFromError(error: Error): Partial<State> {
        return { hasError: true, errorMessage: error.message || String(error), errorStack: error.stack || '' };
    }

    componentDidCatch(error: Error, info: ErrorInfo): void {
        console.error('[ErrorBoundary] React 渲染错误:', error, info.componentStack);
    }

    handleRetry = (): void => {
        this.setState({ hasError: false, errorMessage: '', errorStack: '' });
    };

    handleReload = (): void => {
        window.location.reload();
    };

    render(): ReactNode {
        if (this.state.hasError) {
            return (
                <div className="error-boundary-container">
                    <div className="error-boundary-card">
                        <div className="error-boundary-icon">⚠️</div>
                        <h1 className="error-boundary-title">应用发生错误</h1>
                        <p className="error-boundary-desc">
                            很抱歉，页面遇到了意外错误。您可以尝试恢复或重新加载。
                        </p>
                        <div className="error-boundary-message">
                            <code>{this.state.errorMessage}</code>
                        </div>
                        {this.state.errorStack && (
                            <details className="error-boundary-details">
                                <summary>查看详细堆栈</summary>
                                <pre className="error-boundary-stack">{this.state.errorStack}</pre>
                            </details>
                        )}
                        <div className="error-boundary-actions">
                            <button
                                className="error-boundary-btn error-boundary-btn-retry"
                                onClick={this.handleRetry}
                            >
                                重试恢复
                            </button>
                            <button
                                className="error-boundary-btn error-boundary-btn-reload"
                                onClick={this.handleReload}
                            >
                                重新加载
                            </button>
                        </div>
                    </div>
                </div>
            );
        }
        return this.props.children;
    }
}