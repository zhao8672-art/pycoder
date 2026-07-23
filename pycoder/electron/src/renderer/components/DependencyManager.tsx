/** Visual Dependency Manager — graphical package management panel */
import React, { useState, useEffect } from 'react';
import { BackendAPI } from '../services/backend';

interface Dependency {
    name: string;
    version: string;
    latest: string;
    type: 'runtime' | 'dev';
    description: string;
}

export const DependencyManager: React.FC = () => {
    const [deps, setDeps] = useState<Dependency[]>([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState('');
    const [typeFilter, setTypeFilter] = useState<'all' | 'runtime' | 'dev'>('all');
    const [error, setError] = useState('');

    const loadDeps = async () => {
        setLoading(true);
        try {
            const res = await fetch('/api/dependencies');
            const data = await res.json();
            setDeps(data.dependencies || data.deps || []);
        } catch {
            setDeps([
                { name: 'fastapi', version: '0.115.0', latest: '0.115.6', type: 'runtime', description: 'Web 框架' },
                { name: 'uvicorn', version: '0.30.0', latest: '0.34.0', type: 'runtime', description: 'ASGI 服务器' },
                { name: 'pydantic', version: '2.9.0', latest: '2.10.4', type: 'runtime', description: '数据验证' },
                { name: 'pytest', version: '8.3.0', latest: '8.3.4', type: 'dev', description: '测试框架' },
                { name: 'black', version: '24.8.0', latest: '24.10.0', type: 'dev', description: '代码格式化' },
            ]);
        }
        setLoading(false);
    };

    useEffect(() => { loadDeps(); }, []);

    const filtered = deps.filter(d => {
        const matchName = !filter || d.name.toLowerCase().includes(filter.toLowerCase());
        const matchType = typeFilter === 'all' || d.type === typeFilter;
        return matchName && matchType;
    });

    const needsUpdate = (d: Dependency) => d.version !== d.latest && d.latest > d.version;

    return (
        <div className="dep-manager">
            <div className="dep-header">
                <input className="dep-search" value={filter} onChange={e => setFilter(e.target.value)}
                    placeholder="搜索依赖包..." />
                <select value={typeFilter} onChange={e => setTypeFilter(e.target.value as any)}>
                    <option value="all">全部</option>
                    <option value="runtime">运行时</option>
                    <option value="dev">开发</option>
                </select>
                <button className="dep-btn" onClick={loadDeps}>↻ 刷新</button>
                <span className="dep-count">{filtered.length} 个包</span>
            </div>
            {loading ? <div className="dep-loading">加载中...</div> : (
                <div className="dep-list">
                    {filtered.map(d => (
                        <div key={d.name} className={`dep-item ${needsUpdate(d) ? 'dep-outdated' : ''}`}>
                            <div className="dep-info">
                                <span className="dep-name">{d.name}</span>
                                <span className="dep-type">{d.type}</span>
                                <span className="dep-desc">{d.description}</span>
                            </div>
                            <div className="dep-versions">
                                <span className="dep-current">v{d.version}</span>
                                {needsUpdate(d) && <span className="dep-latest">→ v{d.latest}</span>}
                                {needsUpdate(d) && <button className="dep-upgrade">↑ 升级</button>}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};
