/**
 * ProblemsPanel — 代码问题列表面板
 * 从 LSP 诊断 / 自定义规则引擎 / linter 输出聚合显示
 * v0.7.0: 集成 LSP 实时诊断 (通过 IPC)
 */
import React, { useEffect, useState, useCallback } from 'react';

interface Problem {
    file: string;
    line: number;
    severity: 'error' | 'warning' | 'info';
    message: string;
    source: string;
}

interface LSPDiag {
    uri: string;
    line: number;
    column: number;
    endLine: number;
    endColumn: number;
    message: string;
    severity: 'error' | 'warning' | 'info';
}

export const ProblemsPanel: React.FC = () => {
    const [problems, setProblems] = useState<Problem[]>([]);
    const [lspProblems, setLspProblems] = useState<Problem[]>([]);
    const [filter, setFilter] = useState<string>('all');
    const [showLsp, setShowLsp] = useState(true);

    // ── 从后端 API 获取规则检查结果 ──
    useEffect(() => {
        const fetchProblems = async () => {
            try {
                const base = 'http://127.0.0.1:8423';
                const r = await fetch(`${base}/api/rules/check`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ project: '.' }),
                });
                const data = await r.json();
                if (data?.violations) {
                    setProblems(
                        data.violations.map((v: any) => ({
                            file: v.file || '',
                            line: v.line || 0,
                            severity: v.severity === 'critical' ? 'error' : (v.severity as any),
                            message: v.message || v.text || '',
                            source: v.rule_name || 'custom-rules',
                        })),
                    );
                }
            } catch { /* 静默 */ }
        };
        fetchProblems();
        const timer = setInterval(fetchProblems, 30000);
        return () => clearInterval(timer);
    }, []);

    // ── LSP 诊断监听 (v0.7.0) ──
    useEffect(() => {
        const handleLspDiagnostics = (_event: any, data: { uri: string; diagnostics: LSPDiag[] }) => {
            if (!data?.diagnostics) return;
            // 提取文件名 (从 URI 中)
            const fileName = data.uri.replace(/^file:\/\/\//, '').replace(/\\/g, '/').split('/').pop() || data.uri;
            const mapped: Problem[] = data.diagnostics.map((d: LSPDiag) => ({
                file: fileName,
                line: d.line + 1,  // LSP 0-based → 1-based
                severity: d.severity,
                message: d.message,
                source: 'pyright-lsp',
            }));
            setLspProblems(mapped);
        };

        if (window.electronAPI) {
            window.electronAPI.on('lsp:diagnostics', handleLspDiagnostics);
            return () => {
                window.electronAPI?.removeListener('lsp:diagnostics', handleLspDiagnostics);
            };
        }
    }, []);

    // ── 合并所有问题 ──
    const allProblems = showLsp
        ? [...problems, ...lspProblems]
        : problems;

    const filtered = filter === 'all' ? allProblems : allProblems.filter((p) => p.severity === filter);
    const counts = {
        error: allProblems.filter((p) => p.severity === 'error').length,
        warning: allProblems.filter((p) => p.severity === 'warning').length,
        info: allProblems.filter((p) => p.severity === 'info').length,
    };
    const lspCount = lspProblems.length;

    return (
        <div className="terminal-panel">
            <div className="terminal-toolbar">
                <span className="terminal-title">问题</span>
                <div className="problems-filters">
                    <button className={`problems-filter-btn ${filter === 'all' ? 'active' : ''}`}
                        onClick={() => setFilter('all')}>全部 ({allProblems.length})</button>
                    <button className={`problems-filter-btn error ${filter === 'error' ? 'active' : ''}`}
                        onClick={() => setFilter('error')}>错误 ({counts.error})</button>
                    <button className={`problems-filter-btn warning ${filter === 'warning' ? 'active' : ''}`}
                        onClick={() => setFilter('warning')}>警告 ({counts.warning})</button>
                    <button
                        className={`problems-filter-btn ${showLsp ? 'active' : ''}`}
                        onClick={() => setShowLsp(!showLsp)}
                        title="切换 LSP 诊断显示"
                        style={{ fontSize: 11 }}
                    >
                        LSP ({lspCount})
                    </button>
                </div>
            </div>
            <div className="problems-list" style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                {filtered.length === 0 && (
                    <div className="terminal-line" style={{ color: 'var(--accent-green)', padding: 8 }}>
                        ✅ 未发现问题
                    </div>
                )}
                {filtered.map((p, i) => (
                    <div key={i} className="terminal-line" style={{ display: 'flex', gap: 8, padding: '2px 8px' }}>
                        <span style={{
                            color: p.severity === 'error' ? 'var(--accent-red)' :
                                p.severity === 'warning' ? 'var(--accent-yellow)' : 'var(--text-muted)',
                            flexShrink: 0,
                        }}>
                            {p.severity === 'error' ? '✖' : p.severity === 'warning' ? '⚠' : 'ℹ'}
                        </span>
                        <span style={{ color: 'var(--text-muted)', flexShrink: 0 }}>
                            {p.file}:{p.line}
                        </span>
                        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {p.message}
                        </span>
                        <span style={{
                            color: p.source === 'pyright-lsp' ? 'var(--accent-blue)' : 'var(--text-muted)',
                            fontSize: 10,
                            fontWeight: p.source === 'pyright-lsp' ? 500 : 400,
                        }}>{p.source}</span>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default ProblemsPanel;
