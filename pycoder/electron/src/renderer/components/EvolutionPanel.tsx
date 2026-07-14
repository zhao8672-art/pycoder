import React, { useState, useEffect, useRef, useCallback } from 'react';
import { WSConnectionManager, WSMessage } from '../services/websocket';
import { getWsUrl, getApiKey } from '../services/config';

interface EvoStatData {
    total_tasks: number;
    successful: number;
    failed: number;
    rolled_back: number;
    lines_changed: number;
    bugs_fixed: number;
}

export const EvolutionPanel: React.FC = () => {
    const [status, setStatus] = useState<'idle' | 'running' | 'done' | 'failed'>('idle');
    const [logs, setLogs] = useState<string[]>([]);
    const [stats, setStats] = useState<EvoStatData | null>(null);
    const [taskType, setTaskType] = useState('fix');
    const [target, setTarget] = useState('');
    const wsRef = useRef<WSConnectionManager | null>(null);
    const logEndRef = useRef<HTMLDivElement>(null);

    const addLog = useCallback((msg: string) => {
        setLogs(prev => [...prev.slice(-200), `[${new Date().toLocaleTimeString()}] ${msg}`]);
    }, []);

    useEffect(() => {
        logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [logs]);

    useEffect(() => {
        let cancelled = false;
        const connect = async () => {
            try {
                const [url, apiKey] = await Promise.all([getWsUrl('/api/v2/ws/evolution'), getApiKey()]);
                const wsUrl = apiKey ? `${url}?api_key=${encodeURIComponent(apiKey)}` : url;
                const mgr = new WSConnectionManager(wsUrl);
                wsRef.current = mgr;

                mgr.onMessage((msg: WSMessage) => {
                    if (cancelled) return;
                    switch (msg.type) {
                        case 'phase':
                            addLog('📌 [' + msg.phase + '] ' + msg.message);
                            setStatus('running');
                            break;
                        case 'analysis':
                            addLog('📊 分析完成 (' + (msg as any).full_length + ' 字符)');
                            break;
                        case 'fixes':
                            addLog('🔧 解析出 ' + msg.count + ' 个修复，涉及: ' + ((msg.files || []).join(', ')));
                            break;
                        case 'file_patch':
                            addLog((msg.success ? '✅' : '❌') + ' [' + msg.index + '/' + msg.total + '] ' + msg.file);
                            break;
                        case 'test_result':
                            addLog(msg.passed ? '✅ 测试通过' : '❌ 测试失败');
                            break;
                        case 'done':
                            addLog('🎉 ' + msg.message);
                            setStatus('done');
                            break;
                        case 'rolled_back':
                            addLog('🔄 ' + msg.message);
                            setStatus('failed');
                            break;
                        case 'error':
                            addLog('❌ ' + msg.message);
                            setStatus('failed');
                            break;
                        case 'stats':
                            setStats(msg.stats as any);
                            break;
                    }
                });

                mgr.onStatusChange((s) => {
                    if (cancelled) return;
                    if (s.connected) {
                        addLog('🔗 进化引擎已连接');
                        mgr.sendJson({ type: 'stats' });
                    }
                });

                mgr.connect();
            } catch (e) {
                if (!cancelled) addLog('⚠️ 进化引擎连接失败');
            }
        };
        connect();
        return () => {
            cancelled = true;
            wsRef.current?.disconnect();
        };
    }, []);

    const triggerEvolve = () => {
        const mgr = wsRef.current;
        if (mgr) {
            setLogs([]);
            setStatus('running');
            addLog('🚀 开始进化扫描...');
            mgr.sendJson({ type: 'evolve', task_type: taskType, target: target });
        }
    };

    return (
        <div className="evolution-panel">
            <div className="evolution-header">
                <h3>🧬 自我进化引擎</h3>
                <div className="evolution-stats-row">
                    {stats ? (
                        <>
                            <span title="总任务">📋 {stats.total_tasks}</span>
                            <span title="成功">✅ {stats.successful}</span>
                            <span title="失败">❌ {stats.failed}</span>
                            <span title="回滚">🔄 {stats.rolled_back}</span>
                            <span title="修复 Bug">🐛 {stats.bugs_fixed}</span>
                        </>
                    ) : (
                        <span className="text-muted">连接中...</span>
                    )}
                </div>
            </div>

            <div className="evolution-controls">
                <select value={taskType} onChange={e => setTaskType(e.target.value)} className="evo-select" title="选择进化任务类型">
                    <option value="fix">🔍 Bug 扫描修复</option>
                    <option value="optimize">⚡ 性能优化</option>
                    <option value="security">🔒 安全审查</option>
                    <option value="quality">🧹 代码质量</option>
                </select>
                <input
                    type="text"
                    value={target}
                    onChange={e => setTarget(e.target.value)}
                    placeholder="目标目录 (为空则全局)"
                    className="evo-target-input"
                />
                <button
                    className="evo-btn"
                    onClick={triggerEvolve}
                    disabled={status === 'running'}
                >
                    {status === 'running' ? '⏳ 进化中...' : '🚀 开始进化'}
                </button>
            </div>

            <div className="evolution-logs">
                {logs.map((l, i) => <div key={i} className="evo-log-line">{l}</div>)}
                <div ref={logEndRef} />
            </div>
        </div>
    );
};
