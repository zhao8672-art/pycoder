import React, { useState, useEffect, useCallback } from 'react';
import type { WSConnectionManager, WSMessage } from '../services/websocket';

interface RunFixStepData {
    step: number;
    action: string;
    status: string;
    message?: string;
    error?: string;
    fix_description?: string;
}

interface RunFixDoneData {
    success: boolean;
    total_retries: number;
    final_code: string;
    exec_output: string;
    duration_ms: number;
    steps: RunFixStepData[];
}

interface Props {
    wsClient: WSConnectionManager | null;
    onClose?: () => void;
}

export const RunFixPanel: React.FC<Props> = ({ wsClient, onClose }) => {
    const [task, setTask] = useState('');
    const [running, setRunning] = useState(false);
    const [steps, setSteps] = useState<RunFixStepData[]>([]);
    const [result, setResult] = useState<RunFixDoneData | null>(null);
    const [finalOutput, setFinalOutput] = useState('');

    // 监听 WebSocket 消息
    useEffect(() => {
        if (!wsClient) return;
        const unsub = wsClient.onMessage((msg: WSMessage) => {
            if (msg.type === 'run_fix_step') {
                setSteps((prev) => {
                    // 替换已有的同步骤，或追加
                    const exists = prev.findIndex((s) => s.step === msg.step && s.action === msg.action);
                    if (exists >= 0) {
                        const updated = [...prev];
                        updated[exists] = msg as RunFixStepData;
                        return updated;
                    }
                    return [...prev, msg as RunFixStepData];
                });
            }
            if (msg.type === 'run_fix_done') {
                setRunning(false);
                const data = msg as unknown as RunFixDoneData;
                setResult(data);
                if (data.exec_output) {
                    setFinalOutput(data.exec_output);
                }
            }
        });
        return () => unsub();
    }, [wsClient]);

    // 开始 Run & Fix
    const handleStart = useCallback(() => {
        if (!wsClient || !task.trim()) return;
        setRunning(true);
        setSteps([]);
        setResult(null);
        setFinalOutput('');
        wsClient.sendJson({ type: 'run_fix', task, target_file: 'runfix_solution.py' });
    }, [wsClient, task]);

    const isDone = result !== null;
    const successCount = steps.filter((s) => s.status === 'success').length;
    const failCount = steps.filter((s) => s.status === 'failed').length;

    return (
        <div className="run-fix-panel">
            <div className="run-fix-header">
                <h3>🔁 Run & Fix</h3>
                {onClose && <button className="run-fix-close" onClick={onClose}>✕</button>}
            </div>
            <p className="run-fix-desc">
                描述你要实现的功能，AI 自动写代码 → 运行 → 修复直到通过
            </p>

            {/* 输入区 */}
            <div className="run-fix-input-area">
                <textarea
                    className="run-fix-textarea"
                    value={task}
                    onChange={(e) => setTask(e.target.value)}
                    placeholder="例如: 写一个 FastAPI 用户注册接口，包含邮箱验证"
                    rows={3}
                    disabled={running}
                />
                <button
                    className="run-fix-btn run-fix-btn-start"
                    onClick={handleStart}
                    disabled={running || !task.trim()}
                >
                    {running ? '⏳ 运行中...' : '▶ 开始 Run & Fix'}
                </button>
            </div>

            {/* 进度步骤 */}
            {steps.length > 0 && (
                <div className="run-fix-steps">
                    <div className="run-fix-stats">
                        <span>步骤: {steps.length}</span>
                        <span className="run-fix-count-ok">✅ {successCount}</span>
                        {failCount > 0 && <span className="run-fix-count-fail">❌ {failCount}</span>}
                    </div>
                    {steps.map((s, i) => (
                        <div key={i} className={`run-fix-step run-fix-step-${s.status}`}>
                            <div className="run-fix-step-icon">
                                {s.status === 'running' ? '⏳' : s.status === 'success' ? '✅' : '❌'}
                            </div>
                            <div className="run-fix-step-body">
                                <div className="run-fix-step-action">
                                    {s.action === 'generate' ? '📝 生成代码' :
                                        s.action === 'run' ? `🏃 运行测试 #${Math.floor(s.step / 2) + 1}` :
                                            s.action === 'fix' ? `🔧 AI 修复 #${Math.floor(s.step / 2)}` : s.action}
                                    {s.message && <span className="run-fix-step-msg"> — {s.message}</span>}
                                </div>
                                {s.error && (
                                    <pre className="run-fix-step-error">{s.error.slice(0, 300)}</pre>
                                )}
                                {s.fix_description && (
                                    <div className="run-fix-step-fix">{s.fix_description}</div>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* 结果 */}
            {isDone && (
                <div className={`run-fix-result ${result?.success ? 'run-fix-result-ok' : 'run-fix-result-fail'}`}>
                    <div className="run-fix-result-title">
                        {result?.success ? '🎉 全部通过!' : '❌ 达到最大重试次数'}
                    </div>
                    <div className="run-fix-result-meta">
                        重试 {result?.total_retries} 次 | 耗时 {((result?.duration_ms || 0) / 1000).toFixed(1)}s
                    </div>
                    {finalOutput && (
                        <details className="run-fix-result-output" open={!result?.success}>
                            <summary>📄 运行输出</summary>
                            <pre>{finalOutput}</pre>
                        </details>
                    )}
                </div>
            )}
        </div>
    );
};
