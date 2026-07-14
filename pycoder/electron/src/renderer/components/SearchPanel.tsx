import React, { useState, useCallback, useEffect, useRef } from 'react';
import { BackendAPI } from '../services/backend';
import { useAppStore } from '../stores/appStore';

interface SearchResult {
    file: string;
    line: number;
    match: string;
}

export const SearchPanel: React.FC = () => {
    const [query, setQuery] = useState('');
    const [results, setResults] = useState<SearchResult[]>([]);
    const [loading, setLoading] = useState(false);
    const [fileType, setFileType] = useState('');
    const [regex, setRegex] = useState(false);
    const [caseSensitive, setCaseSensitive] = useState(false);
    const [wholeWord, setWholeWord] = useState(false);
    const [engine, setEngine] = useState('');
    const debounceRef = useRef<ReturnType<typeof setTimeout>>();
    const { openFile } = useAppStore();

    const doSearch = useCallback(async (q: string) => {
        if (!q.trim()) { setResults([]); return; }
        setLoading(true);
        try {
            const res = await BackendAPI.search.query(q, {
                fileType: fileType || undefined,
                regex,
                caseSensitive,
                wholeWord,
            });
            setResults(res?.results || []);
            setEngine(res?.engine || '');
        } catch {
            setResults([]);
        } finally {
            setLoading(false);
        }
    }, [fileType, regex, caseSensitive, wholeWord]);

    useEffect(() => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => doSearch(query), 300);
        return () => {
            if (debounceRef.current) clearTimeout(debounceRef.current);
        };
    }, [query, doSearch]);

    const handleResultClick = (r: SearchResult) => {
        openFile({ path: r.file, name: r.file.split('/').pop() || r.file });
    };

    return (
        <div className="search-panel">
            <div className="search-input-row">
                <input
                    className="search-input"
                    value={query}
                    onChange={e => setQuery(e.target.value)}
                    placeholder="搜索代码..."
                    autoFocus
                />
            </div>
            <div className="search-filters">
                <select value={fileType} onChange={e => setFileType(e.target.value)} title="文件类型过滤">
                    <option value="">所有文件</option>
                    <option value=".py">Python (.py)</option>
                    <option value=".ts">TypeScript (.ts)</option>
                    <option value=".tsx">TSX (.tsx)</option>
                    <option value=".js">JavaScript (.js)</option>
                    <option value=".json">JSON (.json)</option>
                    <option value=".md">Markdown (.md)</option>
                </select>
                <label className="filter-check">
                    <input type="checkbox" checked={regex} onChange={e => setRegex(e.target.checked)} />
                    <span>正则</span>
                </label>
                <label className="filter-check">
                    <input type="checkbox" checked={caseSensitive} onChange={e => setCaseSensitive(e.target.checked)} />
                    <span>大小写</span>
                </label>
                <label className="filter-check">
                    <input type="checkbox" checked={wholeWord} onChange={e => setWholeWord(e.target.checked)} />
                    <span>全词</span>
                </label>
            </div>
            <div className="search-results">
                {loading && <div className="search-status">搜索中...</div>}
                {!loading && results.length === 0 && query && (
                    <div className="search-status">
                        无匹配结果
                        {engine && <span className="search-engine">（引擎: {engine}）</span>}
                    </div>
                )}
                {results.map((r, i) => (
                    <div
                        key={i}
                        className="search-result-item"
                        onClick={() => handleResultClick(r)}
                    >
                        <div className="search-result-header">
                            <span className="search-file">📄 {r.file}</span>
                            <span className="search-line">L{r.line}</span>
                        </div>
                        <span className="search-match">{r.match}</span>
                    </div>
                ))}
            </div>
        </div>
    );
};
