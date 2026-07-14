/**
 * TestGenPanel — 测试生成面板
 */
import React, { useState } from 'react';

export const TestGenPanel: React.FC = () => {
    const [filePath, setFilePath] = useState('');
    const [result, setResult] = useState('');
    const [generating, setGenerating] = useState(false);

    const generate = async () => {
        if (!filePath) return;
        setGenerating(true);
        try {
            const base = 'http://127.0.0.1:8423';
            const r = await fetch(`${base}/api/pipeline/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    steps: [{ tool: 'generate_tests', args: { file: filePath }, description: '生成测试' }],
                }),
            });
            const data = await r.json();
            setResult(JSON.stringify(data, null, 2));
        } catch (e: any) {
            setResult(`错误: ${e.message}`);
        } finally {
            setGenerating(false);
        }
    };

    return (
        <div className="terminal-panel">
            <div className="terminal-toolbar">
                <span className="terminal-title">测试生成</span>
                <button className="terminal-btn" onClick={generate} disabled={generating || !filePath}>
                    {generating ? '⏳ 生成中...' : '⚡ 生成测试'}
                </button>
            </div>
            <div style={{ padding: 8, display: 'flex', gap: 8 }}>
                <input
                    type="text"
                    className="runner-input"
                    placeholder="输入 .py 文件路径..."
                    value={filePath}
                    onChange={(e) => setFilePath(e.target.value)}
                    style={{
                        flex: 1, fontFamily: 'var(--font-mono)', fontSize: 12,
                        background: 'var(--bg-primary)', color: 'var(--text-primary)',
                        border: '1px solid var(--border-color)', padding: '6px 8px',
                        borderRadius: 4, outline: 'none',
                    }}
                />
            </div>
            <div className="terminal-content" style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                <pre style={{ margin: 0, padding: 8, whiteSpace: 'pre-wrap' }}>
                    {result || '输入文件路径后点击生成'}
                </pre>
            </div>
        </div>
    );
};
