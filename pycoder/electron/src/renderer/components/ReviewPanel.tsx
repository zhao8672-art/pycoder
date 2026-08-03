/**
 * F5 代码审查面板 — 展示 ReviewResult、行内跳转、查看修复/一键应用
 *
 * 用法：接入侧边栏或 AIPanel，传入可选 wsClient（保留扩展位）。
 */
import React, { useState, useCallback } from 'react';
import { useAppStore } from '../stores/appStore';
import { getApiBase } from '../services/config';
import * as reviewApi from '../services/reviewApi';
import type { ReviewIssue, ReviewResult } from '../services/reviewApi';

interface Props {
    onClose?: () => void;
}

/** 严重级展示元数据（图标 + 颜色 + 中文名） */
const SEVERITY_META: Record<string, { icon: string; color: string; label: string }> = {
    critical: { icon: '🔴', color: '#f14c4c', label: '严重' },
    error: { icon: '🟠', color: '#e8912d', label: '错误' },
    warning: { icon: '🟡', color: '#cca700', label: '警告' },
    info: { icon: '🔵', color: '#3794ff', label: '提示' },
};

const SEVERITY_ORDER = ['critical', 'error', 'warning', 'info'];

export const ReviewPanel: React.FC<Props> = ({ onClose }) => {
    const openFile = useAppStore((s) => s.openFile);
    const [diffText, setDiffText] = useState('');
    const [running, setRunning] = useState(false);
    const [result, setResult] = useState<ReviewResult | null>(null);
    const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
    const [fixState, setFixState] = useState<Record<number, { loading: boolean; patch: string; applied: boolean }>>({});
    const [message, setMessage] = useState('');

    // ── 运行审查 ──
    const handleRun = useCallback(async () => {
        if (!diffText.trim()) return;
        setRunning(true);
        setResult(null);
        setFixState({});
        try {
            const res = await reviewApi.runReview({ diff: diffText });
            setResult(res);
        } catch (err: any) {
            setMessage(`❌ 审查失败: ${err.message}`);
            setTimeout(() => setMessage(''), 4000);
        } finally {
            setRunning(false);
        }
    }, [diffText]);

    // ── 跳转到对应文件行（打开文件标签，行号由编辑器定位） ──
    const handleJump = useCallback((issue: ReviewIssue) => {
        const fileName = issue.file_path.split(/[\\/]/).pop() || issue.file_path;
        openFile({
            id: issue.file_path,
            filePath: issue.file_path,
            fileName,
            content: '',
            isDirty: false,
            language: fileName.endsWith('.py') ? 'python' : 'plaintext',
        });
    }, [openFile]);

    // ── 查看修复 ──
    const handleViewFix = useCallback(async (idx: number, issue: ReviewIssue) => {
        setFixState((prev) => ({ ...prev, [idx]: { loading: true, patch: '', applied: false } }));
        try {
            const res = await reviewApi.generateFix(issue);
            setFixState((prev) => ({ ...prev, [idx]: { loading: false, patch: res.patch, applied: false } }));
        } catch (err: any) {
            setFixState((prev) => ({ ...prev, [idx]: { loading: false, patch: '', applied: false } }));
            setMessage(`❌ 生成修复失败: ${err.message}`);
            setTimeout(() => setMessage(''), 4000);
        }
    }, []);

    // ── 一键应用（走现有 /api/diff/hunk/apply 能力） ──
    const handleApplyFix = useCallback(async (idx: number, issue: ReviewIssue) => {
        const state = fixState[idx];
        if (!state?.patch) return;
        try {
            const base = await getApiBase();
            const resp = await fetch(`${base}/api/diff/hunk/apply`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    file_path: issue.file_path,
                    hunk_text: state.patch,
                    action: 'accept',
                }),
            });
            const data = await resp.json();
            if (data.success) {
                setFixState((prev) => ({ ...prev, [idx]: { ...prev[idx], applied: true } }));
                setMessage(`✅ 修复已应用到 ${issue.file_path}`);
            } else {
                setMessage(`❌ 应用失败: ${data.error || '未知错误'}`);
            }
        } catch (err: any) {
            setMessage(`❌ 应用出错: ${err.message}`);
        }
        setTimeout(() => setMessage(''), 3000);
    }, [fixState]);

    const toggleGroup = (sev: string) =>
        setCollapsed((prev) => ({ ...prev, [sev]: !prev[sev] }));

    // 按严重级分组
    const grouped: Record<string, Array<{ idx: number; issue: ReviewIssue }>> = {};
    result?.issues.forEach((issue, idx) => {
        (grouped[issue.severity] ||= []).push({ idx, issue });
    });

    const scoreColor = !result ? '#888'
        : result.overall_score >= 80 ? '#4ec9b0'
        : result.overall_score >= 60 ? '#cca700' : '#f14c4c';

    return (
        <div className="review-panel" style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: 12, gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <h3 style={{ margin: 0 }}>🔍 F5 代码审查</h3>
                {onClose && <button onClick={onClose}>✕</button>}
            </div>

            <textarea
                placeholder="粘贴 unified diff 文本，点击「开始审查」…"
                value={diffText}
                onChange={(e) => setDiffText(e.target.value)}
                style={{ width: '100%', minHeight: 100, fontFamily: 'monospace', fontSize: 12 }}
            />
            <button onClick={handleRun} disabled={running || !diffText.trim()}>
                {running ? '审查中…' : '开始审查'}
            </button>
            {message && <div style={{ fontSize: 12 }}>{message}</div>}

            {result && (
                <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {/* 评分卡片 */}
                    <div style={{ padding: 12, border: '1px solid #444', borderRadius: 6 }}>
                        <div style={{ fontSize: 28, fontWeight: 700, color: scoreColor }}>
                            {result.overall_score}
                            <span style={{ fontSize: 14, color: '#888' }}>/100</span>
                        </div>
                        <div style={{ fontSize: 13, marginTop: 4 }}>{result.summary}</div>
                        {result.truncated && (
                            <div style={{ fontSize: 12, color: '#cca700' }}>⚠️ 因成本熔断部分内容被截断</div>
                        )}
                        <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: 12, color: '#aaa' }}>
                            {SEVERITY_ORDER.map((sev) => (
                                <span key={sev}>
                                    {SEVERITY_META[sev].icon} {SEVERITY_META[sev].label} {result.stats.by_severity[sev] ?? 0}
                                </span>
                            ))}
                        </div>
                    </div>

                    {/* 分组 issue 列表 */}
                    {SEVERITY_ORDER.filter((sev) => grouped[sev]?.length).map((sev) => (
                        <div key={sev} style={{ border: '1px solid #333', borderRadius: 6 }}>
                            <div
                                onClick={() => toggleGroup(sev)}
                                style={{ padding: '6px 10px', cursor: 'pointer', userSelect: 'none', fontWeight: 600, color: SEVERITY_META[sev].color }}
                            >
                                {collapsed[sev] ? '▶' : '▼'} {SEVERITY_META[sev].icon} {SEVERITY_META[sev].label}（{grouped[sev].length}）
                            </div>
                            {!collapsed[sev] && grouped[sev].map(({ idx, issue }) => (
                                <div key={idx} style={{ padding: '6px 12px', borderTop: '1px solid #2a2a2a', fontSize: 13 }}>
                                    <div
                                        onClick={() => handleJump(issue)}
                                        title="点击跳转文件"
                                        style={{ cursor: 'pointer', color: '#3794ff' }}
                                    >
                                        {issue.file_path}:{issue.line_start}
                                        {issue.line_end > issue.line_start ? `-${issue.line_end}` : ''}
                                        <span style={{ color: '#888', marginLeft: 6 }}>[{issue.category}]</span>
                                    </div>
                                    <div style={{ marginTop: 2 }}>{issue.message}</div>
                                    {issue.suggestion && (
                                        <div style={{ color: '#9ccc9c', fontSize: 12, marginTop: 2 }}>💡 {issue.suggestion}</div>
                                    )}
                                    <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                                        <button
                                            onClick={() => handleViewFix(idx, issue)}
                                            disabled={fixState[idx]?.loading}
                                            style={{ fontSize: 12 }}
                                        >
                                            {fixState[idx]?.loading ? '生成中…' : '查看修复'}
                                        </button>
                                        {fixState[idx]?.patch && !fixState[idx]?.applied && (
                                            <button onClick={() => handleApplyFix(idx, issue)} style={{ fontSize: 12 }}>
                                                一键应用
                                            </button>
                                        )}
                                        {fixState[idx]?.applied && <span style={{ color: '#4ec9b0', fontSize: 12 }}>✅ 已应用</span>}
                                    </div>
                                    {fixState[idx]?.patch && (
                                        <pre style={{ marginTop: 4, padding: 6, background: '#1a1a1a', fontSize: 11, overflowX: 'auto', maxHeight: 160 }}>
                                            {fixState[idx].patch}
                                        </pre>
                                    )}
                                </div>
                            ))}
                        </div>
                    ))}
                    {result.issues.length === 0 && (
                        <div style={{ color: '#4ec9b0', fontSize: 13 }}>✅ 未发现问题，代码质量良好</div>
                    )}
                </div>
            )}
        </div>
    );
};

export default ReviewPanel;
