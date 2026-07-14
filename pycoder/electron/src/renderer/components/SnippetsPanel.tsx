/**
 * Snippets 管理 GUI — 可视化代码片段管理面板
 */
import React, { useState, useEffect, useCallback } from 'react';
import { BackendAPI } from '../services/backend';

interface Snippet {
    prefix: string;
    description: string;
    body: string;
    language: string;
    tags?: string[];
}

const LANGUAGES = ['python', 'javascript', 'typescript', 'html', 'css', 'json', 'markdown', 'shell'];

export const SnippetsPanel: React.FC = () => {
    const [snippets, setSnippets] = useState<Snippet[]>([]);
    const [loading, setLoading] = useState(false);
    const [language, setLanguage] = useState('python');
    const [search, setSearch] = useState('');
    const [selected, setSelected] = useState<Snippet | null>(null);
    const [newSnippet, setNewSnippet] = useState<Partial<Snippet>>({});
    const [showCreate, setShowCreate] = useState(false);

    const loadSnippets = useCallback(async () => {
        setLoading(true);
        try {
            const res = await BackendAPI.snippets.list(language);
            if (res?.snippets) {
                setSnippets(typeof res.snippets === 'object' ? Object.entries(res.snippets).map(([prefix, body]: [string, any]) => ({
                    prefix, description: '', body: typeof body === 'string' ? body : JSON.stringify(body),
                    language, tags: [],
                })) : []);
            } else {
                setSnippets(buildMockSnippets(language));
            }
        } catch {
            setSnippets(buildMockSnippets(language));
        }
        setLoading(false);
    }, [language]);

    useEffect(() => { loadSnippets(); }, [loadSnippets]);

    const buildMockSnippets = (lang: string): Snippet[] => {
        const mocks: Record<string, Snippet[]> = {
            python: [
                { prefix: 'def', description: '函数定义', body: 'def ${1:name}(${2:args}):\n    ${3:pass}', language: 'python' },
                { prefix: 'class', description: '类定义', body: 'class ${1:Name}:\n    def __init__(self):\n        ${2:pass}', language: 'python' },
                { prefix: 'ifmain', description: 'if __name__ 入口', body: 'if __name__ == "__main__":\n    ${1:pass}', language: 'python' },
                { prefix: 'try', description: '异常处理', body: 'try:\n    ${1:pass}\nexcept ${2:Exception} as e:\n    ${3:print(e)}', language: 'python' },
                { prefix: 'for', description: 'for 循环', body: 'for ${1:item} in ${2:items}:\n    ${3:pass}', language: 'python' },
                { prefix: 'listcomp', description: '列表推导式', body: '[${1:expr} for ${2:x} in ${3:iterable}]', language: 'python' },
            ],
            javascript: [
                { prefix: 'func', description: '函数定义', body: 'function ${1:name}(${2:args}) {\n    ${3:return;}\n}', language: 'javascript' },
                { prefix: 'clog', description: 'console.log', body: 'console.log(${1:value});', language: 'javascript' },
                { prefix: 'arrf', description: '箭头函数', body: '(${1:args}) => ${2:expr}', language: 'javascript' },
                { prefix: 'imp', description: 'import 语句', body: 'import { ${1:name} } from "${2:module}";', language: 'javascript' },
            ],
        };
        return mocks[lang] || mocks.python;
    };

    const filtered = snippets.filter(s =>
        !search || s.prefix.includes(search.toLowerCase()) || s.description.includes(search)
    );

    const handleCreate = async () => {
        if (!newSnippet.prefix || !newSnippet.body) return;
        try {
            await BackendAPI.files.write(
                `_snippets/${language}/${newSnippet.prefix}.json`,
                JSON.stringify({ prefix: newSnippet.prefix, body: newSnippet.body, description: newSnippet.description }, null, 2)
            );
            setShowCreate(false);
            setNewSnippet({});
            loadSnippets();
        } catch (e) {
            console.error('Snippet save failed:', e);
        }
    };

    const copySnippet = (body: string) => {
        navigator.clipboard.writeText(body).then(() => {
            const el = document.getElementById('snippet-copied');
            if (el) { el.style.opacity = '1'; setTimeout(() => { el.style.opacity = '0'; }, 1500); }
        });
    };

    return (
        <div className="snippets-panel">
            <div className="snippets-toolbar">
                <span className="snippets-title">📋 代码片段</span>
                <button className="btn-xs" onClick={() => setShowCreate(!showCreate)}>+ 新建</button>
            </div>

            {/* 语言标签 */}
            <div className="snippets-lang-tabs">
                {LANGUAGES.map(l => (
                    <button key={l} className={`snippets-lang-tab ${l === language ? 'active' : ''}`} onClick={() => setLanguage(l)}>
                        {l}
                    </button>
                ))}
            </div>

            {/* 搜索 */}
            <div className="snippets-search">
                <input className="input-xs" value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索片段..." style={{ width: '100%' }} />
            </div>

            {/* 新建表单 */}
            {showCreate && (
                <div className="snippets-create">
                    <input className="input-xs" value={newSnippet.prefix || ''} onChange={e => setNewSnippet({ ...newSnippet, prefix: e.target.value })} placeholder="前缀 (如: myfunc)" />
                    <input className="input-xs" value={newSnippet.description || ''} onChange={e => setNewSnippet({ ...newSnippet, description: e.target.value })} placeholder="描述 (可选)" />
                    <textarea className="input-xs" value={newSnippet.body || ''} onChange={e => setNewSnippet({ ...newSnippet, body: e.target.value })} placeholder="代码内容" rows={4} style={{ resize: 'vertical' }} />
                    <div style={{ display: 'flex', gap: 4 }}>
                        <button className="btn-sm" onClick={handleCreate}>💾 保存</button>
                        <button className="btn-sm" onClick={() => setShowCreate(false)}>取消</button>
                    </div>
                </div>
            )}

            <span id="snippet-copied" style={{ opacity: 0, fontSize: 11, color: '#4c6', textAlign: 'center', display: 'block', padding: 4, transition: 'opacity 0.3s' }}>✅ 已复制!</span>

            {/* 列表 */}
            <div className="snippets-list">
                {loading && <div className="dim">⏳ 加载中...</div>}
                {!loading && filtered.length === 0 && <div className="dim">无匹配片段</div>}
                {filtered.map((s, i) => (
                    <div
                        key={i}
                        className={`snippets-item ${selected?.prefix === s.prefix ? 'selected' : ''}`}
                        onClick={() => setSelected(selected?.prefix === s.prefix ? null : s)}
                    >
                        <div className="snippets-item-header">
                            <span className="snippets-prefix">{s.prefix}</span>
                            <span className="snippets-desc">{s.description}</span>
                            <button className="btn-xs" onClick={e => { e.stopPropagation(); copySnippet(s.body); }}>📋</button>
                        </div>
                        {selected?.prefix === s.prefix && (
                            <pre className="snippets-body">{s.body}</pre>
                        )}
                    </div>
                ))}
            </div>

            <style>{`
        .snippets-panel { display:flex; flex-direction:column; height:100%; overflow:hidden; }
        .snippets-toolbar { display:flex; justify-content:space-between; align-items:center; padding:8px 12px; border-bottom:1px solid #333; }
        .snippets-title { font-size:12px; font-weight:600; color:#ccc; }
        .snippets-lang-tabs { display:flex; gap:2px; padding:6px 8px; flex-wrap:wrap; border-bottom:1px solid #333; }
        .snippets-lang-tab { padding:2px 8px; border-radius:3px; border:1px solid transparent; background:none; color:#888; font-size:10px; cursor:pointer; }
        .snippets-lang-tab:hover { color:#ddd; }
        .snippets-lang-tab.active { background:#36c; color:#fff; border-color:#58f; }
        .snippets-search { padding:8px 12px; }
        .snippets-create { display:flex; flex-direction:column; gap:6px; padding:8px 12px; background:rgba(255,255,255,0.02); }
        .snippets-create .input-xs { font-size:11px; padding:4px 8px; border-radius:3px; border:1px solid #555; background:#1a1a2e; color:#ddd; }
        .snippets-create textarea.input-xs { font-family:monospace; }
        .snippets-list { flex:1; overflow-y:auto; padding:4px 0; }
        .snippets-item { padding:6px 12px; cursor:pointer; border-bottom:1px solid rgba(255,255,255,0.03); }
        .snippets-item:hover { background:rgba(255,255,255,0.03); }
        .snippets-item.selected { background:rgba(100,150,255,0.08); }
        .snippets-item-header { display:flex; align-items:center; gap:8px; }
        .snippets-prefix { color:#fc6; font-size:12px; font-weight:600; font-family:monospace; }
        .snippets-desc { color:#888; font-size:11px; flex:1; }
        .snippets-body { margin:8px 0 0; padding:8px; border-radius:4px; background:#1a1a2e; color:#ddd; font-size:11px; overflow-x:auto; white-space:pre-wrap; border:1px solid #333; }
        .dim { padding:20px; text-align:center; color:#666; font-size:12px; }
      `}</style>
        </div>
    );
};
