/**
 * PythonRunnerPanel — 简易 Python 代码运行器
 */
import React, { useState } from 'react';

export const PythonRunnerPanel: React.FC = () => {
    const [code, setCode] = useState('# 输入 Python 代码\nprint("Hello PyCoder!")');
    const [output, setOutput] = useState('');
    const [running, setRunning] = useState(false);

    const runCode = async () => {
        setRunning(true);
        setOutput('');
        try {
            const base = 'http://127.0.0.1:8423';
            const r = await fetch(`${base}/api/code/exec`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code, timeout: 15, long_running: false }),
            });
            const data = await r.json();
            setOutput(data.stdout || data.stderr || data.error_message || '(无输出)');
        } catch (e: any) {
            setOutput(`请求失败: ${e.message}`);
        } finally {
            setRunning(false);
        }
    };

    return (
        <div className="terminal-panel">
            <div className="terminal-toolbar">
                <span className="terminal-title">Python 运行器</span>
                <button className="terminal-btn" onClick={runCode} disabled={running}>
                    {running ? '⏳ 运行中...' : '▶ 运行'}
                </button>
                <button className="terminal-btn" onClick={() => setCode('')}>清空</button>
            </div>
            <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
                <textarea
                    className="runner-input"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    style={{
                        flex: 1, fontFamily: 'var(--font-mono)', fontSize: 12,
                        background: 'var(--bg-primary)', color: 'var(--text-primary)',
                        border: 'none', padding: 8, resize: 'none', outline: 'none',
                    }}
                />
                <div className="terminal-content" style={{ flex: 1, overflow: 'auto' }}>
                    <div style={{ padding: '4px 8px', color: 'var(--text-muted)', fontSize: 11 }}>输出:</div>
                    <pre style={{ margin: 0, padding: 8, whiteSpace: 'pre-wrap', fontSize: 12 }}>
                        {output || '点击 ▶ 运行查看输出'}
                    </pre>
                </div>
            </div>
        </div>
    );
};
