/**
 * ProblemsPanel — 代码问题列表面板
 * 从 LSP 诊断 / 自定义规则引擎 / linter 输出聚合显示
 */
import React, { useEffect, useState } from 'react';

interface Problem {
    file: string;
    line: number;
    severity: 'error' | 'warning' | 'info';
    message: string;
    source: string;
}

export const ProblemsPanel: React.FC = () => {
    const [problems, setProblems] = useState<Problem[]>([]);
    const [filter, setFilter] = useState<string>('all');

    useEffect(() => {
        // 从后端获取规则检查结果
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

    const filtered = filter === 'all' ? problems : problems.filter((p) => p.severity === filter);
    const counts = {
        error: problems.filter((p) => p.severity === 'error').length,
        warning: problems.filter((p) => p.severity === 'warning').length,
        info: problems.filter((p) => p.severity === 'info').length,
    };

    return (
        <div className="terminal-panel">
            <div className="terminal-toolbar">
                <span className="terminal-title">问题</span>
                <div className="problems-filters">
                    <button className={`problems-filter-btn ${filter === 'all' ? 'active' : ''}`}
                        onClick={() => setFilter('all')}>全部 ({problems.length})</button>
                    <button className={`problems-filter-btn error ${filter === 'error' ? 'active' : ''}`}
                        onClick={() => setFilter('error')}>错误 ({counts.error})</button>
                    <button className={`problems-filter-btn warning ${filter === 'warning' ? 'active' : ''}`}
                        onClick={() => setFilter('warning')}>警告 ({counts.warning})</button>
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
                        <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>{p.source}</span>
                    </div>
                ))}
            </div>
        </div>
    );
};
