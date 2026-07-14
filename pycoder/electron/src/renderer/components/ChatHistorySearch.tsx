/** Chat History Search — FTS5 full-text search over sessions & messages */
import React, { useState, useEffect, useCallback } from 'react';
import { BackendAPI } from '../services/backend';
import type { WSConnectionManager, WSMessage } from '../services/websocket';

interface Props {
    wsClient: WSConnectionManager | null;
}

interface HistoryResult {
    sessionId: string;
    sessionTitle: string;
    matchedContent: string;
    timestamp: number;
    role: string;
}

export const ChatHistorySearch: React.FC<Props> = ({ wsClient }) => {
    const [query, setQuery] = useState('');
    const [results, setResults] = useState<HistoryResult[]>([]);
    const [loading, setLoading] = useState(false);
    const [timeFilter, setTimeFilter] = useState<'all' | 'today' | 'week' | 'month'>('all');

    const search = useCallback(async () => {
        if (!query.trim() || query.length < 2) return;
        setLoading(true);
        try {
            const res = await BackendAPI.sessions.search?.(query) || {} as any;
            const items = res.results || res.messages || [];
            setResults(items.slice(0, 50));
        } catch (e) {
            // Fallback: use rest API
            try {
                const req = `search=${encodeURIComponent(query)}&time=${timeFilter}&limit=50`;
                const rsp = await fetch(`/api/sessions/search?${req}`);
                const data = await rsp.json();
                setResults(data.results || data.messages || []);
            } catch {
                setResults([]);
            }
        }
        setLoading(false);
    }, [query, timeFilter]);

    // Search as user types (debounced)
    useEffect(() => {
        const t = setTimeout(search, 400);
        return () => clearTimeout(t);
    }, [query, search]);

    // Keyboard shortcut: Ctrl+F in chat panel
    useEffect(() => {
        const h = (e: KeyboardEvent) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'f' &&
                document.activeElement?.closest('.ai-panel-messages')) {
                e.preventDefault();
                (document.querySelector('.ch-search-input') as HTMLInputElement)?.focus();
            }
        };
        document.addEventListener('keydown', h);
        return () => document.removeEventListener('keydown', h);
    }, []);

    return (
        <div className="chat-history-search">
            <div className="chs-header">
                <input className="ch-search-input" value={query}
                    onChange={e => setQuery(e.target.value)}
                    placeholder="🔍 搜索对话历史 (Ctrl+F) — 输入关键词..." />
                <select className="chs-time-filter" value={timeFilter}
                    onChange={e => setTimeFilter(e.target.value as any)}>
                    <option value="all">全部时间</option>
                    <option value="today">今天</option>
                    <option value="week">本周</option>
                    <option value="month">本月</option>
                </select>
            </div>
            {loading && <div className="chs-loading">搜索中...</div>}
            {results.length > 0 && (
                <div className="chs-results">
                    {results.map((r, i) => (
                        <div key={i} className="chs-result-item"
                            onClick={() => wsClient?.sendJson({ type: 'switch_session', session_id: r.sessionId })}>
                            <div className="chs-result-header">
                                <span className="chs-role">{r.role === 'user' ? '🧑' : '🤖'}</span>
                                <span className="chs-session">{r.sessionTitle || r.sessionId?.slice(0, 8)}</span>
                                <span className="chs-time">{new Date(r.timestamp * 1000).toLocaleDateString()}</span>
                            </div>
                            <div className="chs-content">{r.matchedContent?.slice(0, 200)}</div>
                        </div>
                    ))}
                </div>
            )}
            {!loading && results.length === 0 && query.length >= 2 && (
                <div className="chs-empty">未找到匹配的对话记录</div>
            )}
        </div>
    );
};
