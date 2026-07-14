import React from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface Props {
    children: ReactNode;
}

interface State {
    hasError: boolean;
    errorMessage: string;
}

/**
 * 渲染进程错误边界 — 捕获 React 渲染树异常，避免整个页面白屏
 */
export class ErrorBoundary extends React.Component<Props, State> {
    constructor(props: Props) {
        super(props);
        this.state = { hasError: false, errorMessage: '' };
    }

    static getDerivedStateFromError(error: Error): State {
        return { hasError: true, errorMessage: error.message || String(error) };
    }

    componentDidCatch(error: Error, info: ErrorInfo): void {
        console.error('[ErrorBoundary] React 渲染错误:', error, info.componentStack);
    }

    render(): ReactNode {
        if (this.state.hasError) {
            return (
                <div style={{
                    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                    height: '100vh', width: '100vw', background: '#1a1b2e', color: '#c0caf5',
                    fontFamily: "'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
                    padding: '2rem',
                }}>
                    <h1 style={{ fontSize: '2rem', marginBottom: '1rem' }}>⚠️ 应用发生错误</h1>
                    <pre style={{
                        background: '#24253a', padding: '1rem 1.5rem', borderRadius: '8px',
                        maxWidth: '80vw', overflow: 'auto', whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word', marginBottom: '1.5rem',
                    }}>
                        {this.state.errorMessage}
                    </pre>
                    <button
                        onClick={() => { this.setState({ hasError: false, errorMessage: '' }); window.location.reload(); }}
                        style={{
                            background: '#7aa2f7', color: '#1a1b2e', border: 'none',
                            padding: '0.6rem 1.5rem', borderRadius: '6px', cursor: 'pointer',
                            fontSize: '0.95rem', fontWeight: 600,
                        }}
                    >
                        重新加载
                    </button>
                </div>
            );
        }
        return this.props.children;
    }
}
