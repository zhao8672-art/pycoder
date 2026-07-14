import React, { useState, useRef, useCallback } from 'react';
import type { WSConnectionManager, WSMessage } from '../services/websocket';
import { useAppStore } from '../stores/appStore';

interface DebugVariable {
    name: string;
    value: string;
    type: string;
}

interface Breakpoint {
    id: string;
    file: string;
    line: number;
    enabled: boolean;
}

interface CallStackFrame {
    file: string;
    line: number;
    function: string;
    code?: string;
}

interface Props {
    wsClient: WSConnectionManager | null;
}

export const DebugPanel: React.FC<Props> = ({ wsClient }) => {
    const [code, setCode] = useState('');
    const [output, setOutput] = useState('');
    const [error, setError] = useState('');
    const [running, setRunning] = useState(false);
    const [variables, setVariables] = useState<DebugVariable[]>([]);
    const [breakpoints, setBreakpoints] = useState<Breakpoint[]>([]);
    const [callStack, setCallStack] = useState<CallStackFrame[]>([]);
    const [newBpLine, setNewBpLine] = useState('');
    const tapeRef = useRef<HTMLDivElement>(null);

    const addBreakpoint = useCallback(() => {
        const line = parseInt(newBpLine, 10);
        if (!line || line < 1) return;
        setBreakpoints((prev) => [
            ...prev,
            { id: `bp-${Date.now()}`, file: 'current', line, enabled: true },
        ]);
        setNewBpLine('');
    }, [newBpLine]);

    const toggleBreakpoint = useCallback((id: string) => {
        setBreakpoints((prev) => prev.map((b) => (b.id === id ? { ...b, enabled: !b.enabled } : b)));
    }, []);

    const removeBreakpoint = useCallback((id: string) => {
        setBreakpoints((prev) => prev.filter((b) => b.id !== id));
    }, []);

    const runDebug = useCallback(async () => {
        if (!code.trim() || running) return;
        setRunning(true);
        setOutput('🔍 调试运行中...');
        setError('');
        setVariables([]);
        setCallStack([]);

        if (!wsClient) {
            setError('WebSocket 未连接');
            setRunning(false);
            return;
        }

        const bpLines = breakpoints.filter((b) => b.enabled).map((b) => b.line);
        wsClient.sendJson({
            type: 'mcp_call',
            tool: 'debug_python',
            args: { code, breakpoints: bpLines },
        });

        // Simple response handler through AIPanel's message bus
        // The result will appear in the AI chat since mcp_call goes through WS
        setOutput('✅ 调试请求已发送，查看 AI 对话框中的结果');
        setRunning(false);
    }, [code, running, breakpoints, wsClient]);

    // Quick test: call mcp directly via fetch
    const quickDebug = useCallback(async () => {
        if (!code.trim() || running) return;
        setRunning(true);
        setOutput('⏳ 执行中...');
        try {
            const resp = await fetch('http://127.0.0.1:8423/api/code/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code, timeout: 15 }),
            });
            const data = await resp.json();
            setOutput(data.output || data.error || '(无输出)');
            if (data.error) setError(data.error);
            // Parse variables from output
            if (data.output) {
                const varRegex = /^(\w+)\s*=\s*(.+)$/gm;
                const vars: DebugVariable[] = [];
                let m;
                while ((m = varRegex.exec(data.output)) !== null) {
                    vars.push({ name: m[1], value: m[2], type: typeof JSON.parse(JSON.stringify(m[2])) });
                }
                if (vars.length > 0) setVariables(vars);
            }
        } catch (e: any) {
            setError(`连接失败: ${e.message}`);
        } finally {
            setRunning(false);
        }
    }, [code, running]);

    return (
        <div className="debug-panel">
            <div className="debug-header">
                <span>🐛 Debug Panel</span>
                <div className="debug-actions">
                    <button onClick={quickDebug} disabled={running} className="debug-btn debug-btn-run">
                        {running ? '⏳' : '▶'} 执行
                    </button>
                    <button onClick={runDebug} disabled={running} className="debug-btn debug-btn-debug">
                        🔍 MCP 调试
                    </button>
                </div>
            </div>

            {/* Code input */}
            <div className="debug-section">
                <div className="debug-section-title">代码</div>
                <textarea
                    className="debug-code-input"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    placeholder={`# 输入 Python 代码...\n# 示例:\ndef factorial(n):\n    return 1 if n <= 1 else n * factorial(n-1)\nprint(factorial(5))`}
                    rows={8}
                    spellCheck={false}
                />
            </div>

            {/* Breakpoints */}
            <div className="debug-section">
                <div className="debug-section-title">断点 (Breakpoints)</div>
                <div className="debug-bp-row">
                    <input
                        type="number"
                        className="debug-bp-input"
                        min="1"
                        value={newBpLine}
                        onChange={(e) => setNewBpLine(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && addBreakpoint()}
                        placeholder="行号..."
                    />
                    <button onClick={addBreakpoint} className="debug-btn debug-btn-sm">＋ 添加</button>
                </div>
                <div className="debug-bp-list">
                    {breakpoints.length === 0 ? (
                        <span className="debug-hint">无断点 — 在代码行号输入后点添加</span>
                    ) : (
                        breakpoints.map((bp) => (
                            <div key={bp.id} className={`debug-bp-item${bp.enabled ? '' : ' bp-disabled'}`}>
                                <span className="debug-bp-line" onClick={() => toggleBreakpoint(bp.id)}>
                                    ● L{bp.line} {bp.enabled ? 'active' : 'disabled'}
                                </span>
                                <button className="debug-btn-rm" onClick={() => removeBreakpoint(bp.id)}>✕</button>
                            </div>
                        ))
                    )}
                </div>
            </div>

            {/* Variables */}
            <div className="debug-section">
                <div className="debug-section-title">变量 (Variables)</div>
                <div className="debug-var-list">
                    {variables.length === 0 ? (
                        <span className="debug-hint">运行后显示变量状态</span>
                    ) : (
                        variables.map((v, i) => (
                            <div key={i} className="debug-var-item">
                                <span className="debug-var-name">{v.name}</span>
                                <span className="debug-var-type">[{v.type}]</span>
                                <span className="debug-var-val">{v.value}</span>
                            </div>
                        ))
                    )}
                </div>
            </div>

            {/* Call Stack */}
            <div className="debug-section">
                <div className="debug-section-title">调用栈 (Call Stack)</div>
                <div className="debug-stack-list">
                    {callStack.length === 0 ? (
                        <span className="debug-hint">异常时显示调用栈</span>
                    ) : (
                        callStack.map((f, i) => (
                            <div key={i} className="debug-stack-frame">
                                <span className="debug-stack-func">{f.function}</span>
                                <span className="debug-stack-loc">{f.file}:{f.line}</span>
                            </div>
                        ))
                    )}
                </div>
            </div>

            {/* Output / Error */}
            <div className="debug-section">
                <div className="debug-section-title">输出</div>
                <div ref={tapeRef} className="debug-output">
                    <pre className="debug-output-text">{output || '等待运行...'}</pre>
                </div>
                {error && (
                    <div className="debug-error">
                        <pre className="debug-error-text">{error}</pre>
                    </div>
                )}
            </div>
        </div>
    );
};
