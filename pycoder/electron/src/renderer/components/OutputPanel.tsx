/**
 * OutputPanel — 后端日志和运行输出面板
 */
import React, { useEffect, useState, useRef } from 'react';

export const OutputPanel: React.FC = () => {
    const [logs, setLogs] = useState<string[]>([]);
    const endRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        // 定期拉取后端日志
        const fetchLogs = async () => {
            try {
                const base = 'http://127.0.0.1:8423';
                const r = await fetch(`${base}/api/health`);
                const data = await r.json();
                setLogs((prev) => {
                    const line = `[${new Date().toLocaleTimeString()}] health: ${data.status} v${data.version}`;
                    return [...prev.slice(-99), line];
                });
            } catch {
                setLogs((prev) => [...prev.slice(-99), `[${new Date().toLocaleTimeString()}] ⚠️ 后端未响应`]);
            }
        };
        fetchLogs();
        const timer = setInterval(fetchLogs, 10000);
        return () => clearInterval(timer);
    }, []);

    useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [logs]);

    return (
        <div className="terminal-panel">
            <div className="terminal-toolbar">
                <span className="terminal-title">输出日志</span>
                <button className="terminal-btn" onClick={() => setLogs([])}>清空</button>
            </div>
            <div className="terminal-content" style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                {logs.map((line, i) => (
                    <div key={i} className="terminal-line">{line}</div>
                ))}
                <div ref={endRef} />
            </div>
        </div>
    );
};
