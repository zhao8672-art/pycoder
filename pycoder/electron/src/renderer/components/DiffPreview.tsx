import React, { useState, useCallback } from 'react';
import { useAppStore } from '../stores/appStore';
import { BackendAPI } from '../services/backend';
import type { DiffFile, DiffHunk } from '../types';
import type { WSConnectionManager } from '../services/websocket';

interface DiffEntry {
  id: string;
  filePath: string;
  original: string;
  modified: string;
  status: 'pending' | 'accepted' | 'rejected';
  hunks: DiffHunk[];
  hunkStatus: ('pending' | 'accepted' | 'rejected')[];
}

interface Props {
  wsClient?: WSConnectionManager | null;
}

export const DiffPreview: React.FC<Props> = ({ wsClient }) => {
  const { pendingDiffs, setPendingDiffs, autoCommitEnabled, setAutoCommitEnabled } = useAppStore();
  const [entries, setEntries] = useState<DiffEntry[]>([]);
  const [applying, setApplying] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [feedbackHunk, setFeedbackHunk] = useState<{ entryId: string; hunkIdx: number } | null>(null);
  const [feedbackText, setFeedbackText] = useState('');

  // 将 incoming diffs 转为 entries
  React.useEffect(() => {
    if (pendingDiffs.length > 0) {
      const newEntries: DiffEntry[] = pendingDiffs.map((d, i) => {
        const hunks = d.hunks || [];
        return {
          id: `diff-${i}-${Date.now()}`,
          filePath: d.path,
          original: '',
          modified: formatDiffLines(hunks),
          status: 'pending' as const,
          hunks,
          hunkStatus: hunks.map(() => 'pending' as const),
        };
      });
      setEntries((prev) => [...prev, ...newEntries]);
    }
  }, [pendingDiffs]);

  // ── Hunk 级操作 ──
  const handleAcceptHunk = useCallback(async (entry: DiffEntry, hunkIdx: number) => {
    const hunk = entry.hunks[hunkIdx];
    if (!hunk) return;

    setApplying(`${entry.id}-h${hunkIdx}`);
    try {
      const res = await BackendAPI.diff.applyHunk(entry.filePath, hunk.lines.join('\n'), 'accept');
      if (res?.success) {
        setEntries((prev) =>
          prev.map((e) => {
            if (e.id !== entry.id) return e;
            const newStatus = [...e.hunkStatus];
            newStatus[hunkIdx] = 'accepted';
            const allDone = newStatus.every((s) => s !== 'pending');
            return { ...e, hunkStatus: newStatus, status: allDone ? 'accepted' : 'pending' };
          })
        );
        setMessage(`✅ Hunk #${hunkIdx + 1} 已应用`);
      } else {
        setMessage(`❌ 应用失败: ${res?.error || '未知错误'}`);
      }
    } catch (err: any) {
      setMessage(`❌ 出错: ${err.message}`);
    } finally {
      setApplying(null);
      setTimeout(() => setMessage(''), 3000);
    }
  }, []);

  const handleRejectHunk = useCallback((entry: DiffEntry, hunkIdx: number) => {
    setEntries((prev) =>
      prev.map((e) => {
        if (e.id !== entry.id) return e;
        const newStatus = [...e.hunkStatus];
        newStatus[hunkIdx] = 'rejected';
        const allDone = newStatus.every((s) => s !== 'pending');
        return { ...e, hunkStatus: newStatus, status: allDone ? 'rejected' : 'pending' };
      })
    );
    setMessage(`已拒绝 Hunk #${hunkIdx + 1}`);
    setTimeout(() => setMessage(''), 2000);
  }, []);

  const handleRejectWithFeedback = useCallback(async (entry: DiffEntry, hunkIdx: number, feedback: string) => {
    const hunk = entry.hunks[hunkIdx];
    if (!hunk || !wsClient) return;

    // 从 hunk 中提取原始代码
    const originalLines = hunk.lines
      .filter((l: string) => l.startsWith('-') && !l.startsWith('---'))
      .map((l: string) => l.slice(1));

    setMessage(`🔄 重新生成 Hunk #${hunkIdx + 1}...`);

    wsClient.sendJson({
      type: 'inline_edit',
      code: originalLines.join('\n'),
      instruction: feedback,
      file_path: entry.filePath,
    });

    setFeedbackHunk(null);
    setFeedbackText('');
  }, [wsClient]);

  // ── 文件级操作 ──
  const handleAccept = useCallback(async (entry: DiffEntry) => {
    setApplying(entry.id);
    setMessage(`正在写入 ${entry.filePath}...`);

    try {
      const res = await BackendAPI.files.write(entry.filePath, entry.modified);
      if (res?.success) {
        setEntries((prev) =>
          prev.map((e) => (e.id === entry.id ? { ...e, status: 'accepted' as const, hunkStatus: e.hunkStatus.map(() => 'accepted' as const) } : e))
        );
        setMessage(`✅ ${entry.filePath} 已保存`);
      } else {
        setMessage(`❌ 写入失败: ${res?.error || '未知错误'}`);
      }
    } catch (err: any) {
      setMessage(`❌ 写入出错: ${err.message}`);
    } finally {
      setApplying(null);
    }
  }, []);

  const handleReject = useCallback((entry: DiffEntry) => {
    setEntries((prev) =>
      prev.map((e) => (e.id === entry.id ? { ...e, status: 'rejected' as const, hunkStatus: e.hunkStatus.map(() => 'rejected' as const) } : e))
    );
    setMessage(`已拒绝 ${entry.filePath}`);
    setTimeout(() => setMessage(''), 2000);
  }, []);

  const handleAcceptAll = useCallback(async () => {
    const pending = entries.filter((e) => e.status === 'pending');
    const acceptedFiles: string[] = [];

    for (const entry of pending) {
      await handleAccept(entry);
      acceptedFiles.push(entry.filePath);
    }

    // 自动 Git commit
    if (autoCommitEnabled && acceptedFiles.length > 0) {
      try {
        const res = await BackendAPI.git.commit(acceptedFiles);
        if (res?.success) {
          setMessage(`✅ Committed: ${res.message?.split('\n')[0] || ''} (${res.hash?.slice(0, 7) || ''})`);
        } else {
          setMessage('⚠️ Git commit 失败 (文件已保存，请手动提交)');
        }
      } catch {
        setMessage('⚠️ Git commit 异常 (文件已保存，请手动提交)');
      }
    }
  }, [entries, handleAccept, autoCommitEnabled]);

  const handleRejectAll = useCallback(() => {
    setEntries((prev) =>
      prev.map((e) => (e.status === 'pending' ? { ...e, status: 'rejected' as const, hunkStatus: e.hunkStatus.map(() => 'rejected' as const) } : e))
    );
    setMessage('已拒绝全部变更');
    setTimeout(() => setMessage(''), 2000);
  }, []);

  const pendingCount = entries.filter((e) => e.status === 'pending').length;
  const acceptedCount = entries.filter((e) => e.status === 'accepted').length;
  const rejectedCount = entries.filter((e) => e.status === 'rejected').length;

  if (entries.length === 0) return null;

  return (
    <div className="diff-preview">
      <div className="diff-header">
        <span className="diff-title">📋 变更预览</span>
        <div className="diff-stats">
          <span className="diff-stat pending">{pendingCount} 待处理</span>
          <span className="diff-stat accepted">{acceptedCount} 已接受</span>
          <span className="diff-stat rejected">{rejectedCount} 已拒绝</span>
        </div>
        <div className="diff-auto-commit">
          <label className="diff-checkbox">
            <input
              type="checkbox"
              checked={autoCommitEnabled}
              onChange={(e) => setAutoCommitEnabled(e.target.checked)}
            />
            <span>自动 Git 提交</span>
          </label>
        </div>
        {pendingCount > 0 && (
          <div className="diff-actions">
            <button className="diff-btn diff-btn-accept-all" onClick={handleAcceptAll}>
              ✅ 接受全部
            </button>
            <button className="diff-btn diff-btn-reject-all" onClick={handleRejectAll}>
              ❌ 拒绝全部
            </button>
          </div>
        )}
      </div>

      {message && <div className="diff-message">{message}</div>}

      <div className="diff-list">
        {entries.map((entry) => (
          <div key={entry.id} className={`diff-entry diff-${entry.status}`}>
            <div className="diff-entry-header">
              <span className="diff-entry-file">
                {entry.status === 'accepted' ? '✅' : entry.status === 'rejected' ? '⛔' : '📝'}
                {' '}{entry.filePath}
              </span>
              <div className="diff-entry-actions">
                {entry.status === 'pending' && (
                  <>
                    <button className="diff-entry-btn accept" onClick={() => handleAccept(entry)} disabled={applying === entry.id}>
                      {applying === entry.id ? '⏳' : '✓'} 接受全部
                    </button>
                    <button className="diff-entry-btn reject" onClick={() => handleReject(entry)}>✕ 拒绝全部</button>
                  </>
                )}
                {entry.status === 'accepted' && <span className="diff-badge accepted">已保存</span>}
                {entry.status === 'rejected' && <span className="diff-badge rejected">已拒绝</span>}
              </div>
            </div>

            {/* Hunk 级操作 */}
            {entry.hunks.length > 0 ? (
              <div className="diff-hunks">
                {entry.hunks.map((hunk, hIdx) => (
                  <div key={`${entry.id}-h${hIdx}`} className={`diff-hunk ${entry.hunkStatus[hIdx] || 'pending'}`}>
                    <div className="diff-hunk-header">
                      <span className="diff-hunk-title">Hunk #{hIdx + 1}</span>
                      <span className="diff-hunk-stats">
                        +{hunk.lines.filter((l: string) => l.startsWith('+') && !l.startsWith('+++')).length}
                        /-{hunk.lines.filter((l: string) => l.startsWith('-') && !l.startsWith('---')).length}
                      </span>
                      <div className="diff-hunk-actions">
                        {entry.hunkStatus[hIdx] === 'pending' && (
                          <>
                            <button
                              className="diff-hunk-btn accept"
                              onClick={() => handleAcceptHunk(entry, hIdx)}
                              disabled={applying === `${entry.id}-h${hIdx}`}
                            >
                              {applying === `${entry.id}-h${hIdx}` ? '⏳' : '✓'} 接受
                            </button>
                            <button className="diff-hunk-btn reject" onClick={() => handleRejectHunk(entry, hIdx)}>✕ 拒绝</button>
                            <button className="diff-hunk-btn feedback" onClick={() => setFeedbackHunk({ entryId: entry.id, hunkIdx: hIdx })}>
                              💬 修改意见
                            </button>
                          </>
                        )}
                        {entry.hunkStatus[hIdx] === 'accepted' && <span className="diff-hunk-badge accepted">✓ 已应用</span>}
                        {entry.hunkStatus[hIdx] === 'rejected' && <span className="diff-hunk-badge rejected">✕ 已拒绝</span>}
                      </div>
                    </div>
                    <pre className="diff-hunk-content">
                      <code>{(hunk.lines || []).join('\n')}</code>
                    </pre>

                    {/* 反馈输入框 */}
                    {feedbackHunk?.entryId === entry.id && feedbackHunk?.hunkIdx === hIdx && (
                      <div className="diff-feedback">
                        <textarea
                          className="diff-feedback-input"
                          placeholder="输入修改意见，如「改用 asyncio 实现」..."
                          value={feedbackText}
                          onChange={(e) => setFeedbackText(e.target.value)}
                          rows={2}
                        />
                        <div className="diff-feedback-actions">
                          <button onClick={() => { setFeedbackHunk(null); setFeedbackText(''); }}>取消</button>
                          <button
                            onClick={() => handleRejectWithFeedback(entry, hIdx, feedbackText)}
                            disabled={!feedbackText.trim()}
                          >
                            发送并重新生成
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <pre className="diff-entry-content">{entry.modified || '(新文件)'}</pre>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

function formatDiffLines(hunks: DiffHunk[]): string {
  if (!hunks || hunks.length === 0) return '';
  return hunks.map((hunk) => hunk.lines.join('\n')).join('\n');
}
