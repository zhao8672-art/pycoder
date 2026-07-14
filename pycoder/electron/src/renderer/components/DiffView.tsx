/**
 * 图形化 Diff 对比视图 — 并排显示原始/修改代码差异
 */
import React, { useState, useEffect, useCallback } from 'react';
import { BackendAPI } from '../services/backend';
import { useAppStore } from '../stores/appStore';

interface DiffLine {
    type: 'add' | 'remove' | 'context' | 'header';
    oldLine?: number;
    newLine?: number;
    content: string;
}

export const DiffView: React.FC = () => {
    const { gitStatus } = useAppStore();
    const [selectedFile, setSelectedFile] = useState('');
    const [diffLines, setDiffLines] = useState<DiffLine[]>([]);
    const [loading, setLoading] = useState(false);
    const [files, setFiles] = useState<string[]>([]);
    const [viewMode, setViewMode] = useState<'unified' | 'split'>('split');

    useEffect(() => {
        if (gitStatus) {
            const allFiles = [
                ...(gitStatus.staged || []).map((f: any) => ({ ...f, staged: true })),
                ...(gitStatus.unstaged || []).map((f: any) => ({ ...f, staged: false })),
            ];
            setFiles(allFiles.map((f: any) => f.path || f.file || ''));
        }
    }, [gitStatus]);

    const loadDiff = useCallback(async (filePath: string) => {
        setLoading(true);
        try {
            const res = await BackendAPI.git.diff(filePath, false);
            const diffText = res?.diff || '';
            setDiffLines(parseDiffText(diffText));
            setSelectedFile(filePath);
        } catch (e) {
            setDiffLines([]);
        }
        setLoading(false);
    }, []);

    const parseDiffText = (text: string): DiffLine[] => {
        const lines: DiffLine[] = [];
        let oldLine = 0;
        let newLine = 0;

        for (const line of text.split('\n')) {
            if (line.startsWith('@@')) {
                lines.push({ type: 'header', content: line });
                const m = line.match(/@@ -(\d+).*\+(\d+)/);
                if (m) { oldLine = parseInt(m[1]) - 1; newLine = parseInt(m[2]) - 1; }
            } else if (line.startsWith('+')) {
                newLine++;
                lines.push({ type: 'add', newLine, content: line.substring(1) });
            } else if (line.startsWith('-')) {
                oldLine++;
                lines.push({ type: 'remove', oldLine, content: line.substring(1) });
            } else if (line.startsWith('diff') || line.startsWith('index') || line.startsWith('---') || line.startsWith('+++')) {
                lines.push({ type: 'header', content: line });
            } else {
                oldLine++; newLine++;
                lines.push({ type: 'context', oldLine, newLine, content: line.startsWith(' ') ? line.substring(1) : line });
            }
        }
        return lines;
    };

    const lineColor = (type: string) => {
        switch (type) {
            case 'add': return { bg: 'rgba(0,255,0,0.08)', border: '#2a2' };
            case 'remove': return { bg: 'rgba(255,0,0,0.08)', border: '#c44' };
            case 'header': return { bg: 'rgba(100,100,255,0.1)', border: '#68f' };
            default: return { bg: 'transparent', border: 'transparent' };
        }
    };

    return (
        <div className="diff-view">
            <div className="diff-toolbar">
                <span className="diff-title">📊 差异对比</span>
                <div className="diff-toolbar-actions">
                    <button className={`btn-sm ${viewMode === 'unified' ? 'active' : ''}`} onClick={() => setViewMode('unified')}>统一</button>
                    <button className={`btn-sm ${viewMode === 'split' ? 'active' : ''}`} onClick={() => setViewMode('split')}>并排</button>
                </div>
            </div>

            <div className="diff-file-list">
                {files.length === 0 && <div className="dim">无变更文件</div>}
                {files.slice(0, 30).map((f, i) => (
                    <div
                        key={i}
                        className={`diff-file-item ${selectedFile === f ? 'selected' : ''}`}
                        onClick={() => loadDiff(f)}
                    >
                        <span className="diff-file-icon">📄</span>
                        <span className="diff-file-name">{f}</span>
                    </div>
                ))}
            </div>

            {loading && <div className="diff-loading">⏳ 加载差异...</div>}

            {!loading && diffLines.length > 0 && (
                <div className="diff-content">
                    {viewMode === 'unified' ? (
                        <div className="diff-unified">
                            {diffLines.map((l, i) => (
                                <div key={i} className="diff-line" style={{ background: lineColor(l.type).bg, borderLeft: `3px solid ${lineColor(l.type).border}` }}>
                                    <span className="diff-line-num">
                                        {l.type === 'remove' ? l.oldLine?.toString().padStart(4) : ''}
                                        {l.type === 'add' ? l.newLine?.toString().padStart(4) : ''}
                                        {l.type === 'context' ? `${l.oldLine}`.padStart(4) : ''}
                                        {l.type === 'header' ? '    ' : ''}
                                    </span>
                                    <span className="diff-line-sign">
                                        {l.type === 'add' ? '+' : l.type === 'remove' ? '-' : ' '}
                                    </span>
                                    <span className="diff-line-code">{l.content}</span>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="diff-split">
                            <div className="diff-split-left">
                                {diffLines.filter(l => l.type !== 'add').map((l, i) => (
                                    <div key={i} className="diff-line" style={{ background: l.type === 'remove' ? 'rgba(255,0,0,0.1)' : 'transparent' }}>
                                        <span className="diff-line-num">{l.oldLine?.toString().padStart(4) || '    '}</span>
                                        <span className="diff-line-code">{l.content}</span>
                                    </div>
                                ))}
                            </div>
                            <div className="diff-split-right">
                                {diffLines.filter(l => l.type !== 'remove').map((l, i) => (
                                    <div key={i} className="diff-line" style={{ background: l.type === 'add' ? 'rgba(0,255,0,0.1)' : 'transparent' }}>
                                        <span className="diff-line-num">{l.newLine?.toString().padStart(4) || '    '}</span>
                                        <span className="diff-line-code">{l.content}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}

            <style>{`
        .diff-view { display:flex; flex-direction:column; height:100%; overflow:hidden; }
        .diff-toolbar { display:flex; justify-content:space-between; align-items:center; padding:8px 12px; border-bottom:1px solid #333; }
        .diff-title { font-size:12px; font-weight:600; color:#ccc; }
        .diff-toolbar-actions { display:flex; gap:4px; }
        .btn-sm { padding:2px 8px; border-radius:4px; border:1px solid #555; background:#1a1a2e; color:#ddd; font-size:11px; cursor:pointer; }
        .btn-sm.active { background:#36c; border-color:#58f; }
        .diff-file-list { padding:6px; max-height:150px; overflow-y:auto; border-bottom:1px solid #333; }
        .diff-file-item { display:flex; align-items:center; gap:6px; padding:4px 8px; cursor:pointer; border-radius:4px; font-size:12px; color:#bbb; }
        .diff-file-item:hover { background:rgba(255,255,255,0.05); }
        .diff-file-item.selected { background:rgba(100,150,255,0.15); color:#fff; }
        .diff-file-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .diff-content { flex:1; overflow:auto; font-family:'Cascadia Code',Consolas,monospace; font-size:12px; line-height:1.5; }
        .diff-line { display:flex; padding:0 8px; white-space:pre; }
        .diff-line-num { min-width:44px; color:#666; text-align:right; padding-right:8px; user-select:none; }
        .diff-line-sign { width:16px; color:#888; user-select:none; }
        .diff-line-code { flex:1; overflow:hidden; }
        .diff-split { display:flex; }
        .diff-split-left, .diff-split-right { flex:1; overflow-x:auto; border-right:1px solid #333; }
        .diff-split-right { border-right:none; }
        .diff-loading { padding:20px; text-align:center; color:#888; }
        .dim { padding:12px; color:#666; text-align:center; font-size:12px; }
      `}</style>
        </div>
    );
};
