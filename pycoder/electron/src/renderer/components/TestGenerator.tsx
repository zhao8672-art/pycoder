import React, { useState, useEffect, useCallback } from 'react';
import type { WSConnectionManager, WSMessage } from '../services/websocket';
import { BackendAPI } from '../services/backend';

interface TestResult {
    success: boolean;
    test_file: string;
    test_count: number;
    passed: number;
    failed: number;
    coverage_percent: number;
    output: string;
    error: string;
    duration_ms: number;
}

interface Props {
    wsClient: WSConnectionManager | null;
}

export const TestGenerator: React.FC<Props> = ({ wsClient }) => {
    const [filePath, setFilePath] = useState('');
    const [running, setRunning] = useState(false);
    const [result, setResult] = useState<TestResult | null>(null);
    const [fileSuggestions, setFileSuggestions] = useState<string[]>([]);
    const [showSuggestions, setShowSuggestions] = useState(false);

    // 查找项目中的 Python 文件
    useEffect(() => {
        const loadFiles = async () => {
            const res = await BackendAPI.files.list('.');
            if (res?.tree) {
                const pyFiles = flattenFiles(res.tree, '');
                setFileSuggestions(pyFiles);
            }
        };
        loadFiles();
    }, []);

    function flattenFiles(items: any[], prefix: string): string[] {
        const result: string[] = [];
        for (const item of items) {
            const full = prefix ? `${prefix}/${item.name}` : item.name;
            if (item.type === 'file' && item.name.endsWith('.py')) {
                result.push(full);
            } else if (item.children) {
                result.push(...flattenFiles(item.children, full));
            }
        }
        return result;
    }

    // 过滤文件建议
    const filteredSuggestions = fileSuggestions.filter((f) =>
        f.toLowerCase().includes(filePath.toLowerCase())
    ).slice(0, 15);

    // 监听 WebSocket
    useEffect(() => {
        if (!wsClient) return;
        const unsub = wsClient.onMessage((msg: WSMessage) => {
            if (msg.type === 'test_generator_done') {
                setRunning(false);
                setResult(msg as unknown as TestResult);
            }
        });
        return () => unsub();
    }, [wsClient]);

    // 生成测试
    const handleGenerate = useCallback(() => {
        if (!wsClient || !filePath.trim()) return;
        setRunning(true);
        setResult(null);
        wsClient.sendJson({ type: 'test_generator', file_path: filePath.trim() });
    }, [wsClient, filePath]);

    return (
        <div className="test-generator">
            <div className="test-gen-header">
                <h3>🧪 智能测试生成</h3>
            </div>
            <p className="test-gen-desc">
                选择 Python 文件 → 自动分析函数/方法 → 生成 pytest 测试 → 运行并报告覆盖率
            </p>

            {/* 文件选择 */}
            <div className="test-gen-file-area">
                <input
                    className="test-gen-input"
                    placeholder="输入文件路径，如: pycoder/server/app.py"
                    value={filePath}
                    onChange={(e) => {
                        setFilePath(e.target.value);
                        setShowSuggestions(true);
                    }}
                    onFocus={() => setShowSuggestions(true)}
                    onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
                    disabled={running}
                />
                {showSuggestions && filteredSuggestions.length > 0 && (
                    <div className="test-gen-suggestions">
                        {filteredSuggestions.map((f) => (
                            <div
                                key={f}
                                className="test-gen-suggestion"
                                onMouseDown={() => {
                                    setFilePath(f);
                                    setShowSuggestions(false);
                                }}
                            >
                                📄 {f}
                            </div>
                        ))}
                    </div>
                )}
            </div>

            <button
                className="test-gen-btn"
                onClick={handleGenerate}
                disabled={running || !filePath.trim()}
            >
                {running ? '⏳ 生成中...' : '▶ 生成测试'}
            </button>

            {/* 结果 */}
            {result && (
                <div className={`test-gen-result ${result.success ? 'test-gen-ok' : 'test-gen-fail'}`}>
                    <div className="test-gen-result-header">
                        <span className="test-gen-result-title">
                            {result.success ? '✅' : '❌'} {result.success ? '测试生成完成' : '生成失败'}
                        </span>
                        <span className="test-gen-duration">
                            耗时 {(result.duration_ms / 1000).toFixed(1)}s
                        </span>
                    </div>

                    <div className="test-gen-stats">
                        <div className="test-gen-stat">
                            <span className="test-gen-stat-value">{result.test_count}</span>
                            <span className="test-gen-stat-label">测试用例</span>
                        </div>
                        <div className="test-gen-stat">
                            <span className="test-gen-stat-value test-gen-passed">{result.passed}</span>
                            <span className="test-gen-stat-label">通过</span>
                        </div>
                        {result.failed > 0 && (
                            <div className="test-gen-stat">
                                <span className="test-gen-stat-value test-gen-failed">{result.failed}</span>
                                <span className="test-gen-stat-label">失败</span>
                            </div>
                        )}
                        <div className="test-gen-stat">
                            <span className="test-gen-stat-value test-gen-cov">{result.coverage_percent}%</span>
                            <span className="test-gen-stat-label">覆盖率</span>
                        </div>
                    </div>

                    {result.test_file && (
                        <div className="test-gen-file-info">
                            📁 测试文件: <code>{result.test_file}</code>
                        </div>
                    )}

                    {result.output && (
                        <details className="test-gen-details" open={!result.success}>
                            <summary>📄 运行输出</summary>
                            <pre className="test-gen-output">{result.output}</pre>
                        </details>
                    )}

                    {result.error && (
                        <div className="test-gen-error">❌ {result.error}</div>
                    )}
                </div>
            )}
        </div>
    );
};
