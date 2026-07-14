import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useAppStore } from '../stores/appStore';
import { BackendAPI } from '../services/backend';
import type { GitStatus } from '../types';
import { CloneDialog } from './CloneDialog';
import { PublishDialog } from './PublishDialog';

const STATUS_ICONS: Record<string, string> = {
  M: '📝', A: '➕', D: '🗑️', R: '🔀', C: '📋', '?': '❓',
};

export const GitPanel: React.FC = () => {
  const { gitStatus, setGitStatus } = useAppStore();
  const [loading, setLoading] = useState(false);
  const [branches, setBranches] = useState<any[]>([]);
  const [activeBranch, setActiveBranch] = useState('');
  const [commitMsg, setCommitMsg] = useState('');
  const [showBranchMenu, setShowBranchMenu] = useState(false);
  const [newBranchName, setNewBranchName] = useState('');
  const [logs, setLogs] = useState<any[]>([]);
  const [statusMsg, setStatusMsg] = useState('');
  const [showLog, setShowLog] = useState(false);
  const [showCloneDialog, setShowCloneDialog] = useState(false);
  const [showPublishDialog, setShowPublishDialog] = useState(false);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileDiff, setFileDiff] = useState('');
  const [stashList, setStashList] = useState<string[]>([]);
  const [showStashMenu, setShowStashMenu] = useState(false);
  const [showFileHistory, setShowFileHistory] = useState<string | null>(null);
  const [fileHistoryData, setFileHistoryData] = useState<any[]>([]);
  const [tags, setTags] = useState<any[]>([]);
  const [showTags, setShowTags] = useState(false);
  const [conflicts, setConflicts] = useState<any[]>([]);
  const [gitignorePattern, setGitignorePattern] = useState('');
  const intervalRef = useRef<ReturnType<typeof setInterval>>();

  // Auto-refresh every 5s (P1)
  useEffect(() => {
    intervalRef.current = setInterval(() => {
      refreshStatus();
    }, 5000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, []);

  const refreshStatus = useCallback(async () => {
    setLoading(true);
    try {
      const res = await BackendAPI.git.status();
      if (res) setGitStatus(res as unknown as GitStatus);
    } catch { }
    setLoading(false);
  }, [setGitStatus]);

  const refreshBranches = useCallback(async () => {
    try {
      const res = await BackendAPI.git.branches();
      if (res?.branches) {
        setBranches(res.branches);
        setActiveBranch(res.active || '');
      }
    } catch { }
  }, []);

  const refreshStashList = useCallback(async () => {
    try {
      const res = await BackendAPI.git.stash('list');
      setStashList(res?.stashes || []);
    } catch { }
  }, []);

  const refreshTags = useCallback(async () => {
    try {
      const res = await BackendAPI.git.tags();
      setTags(res?.tags || []);
    } catch { }
  }, []);

  const refreshConflicts = useCallback(async () => {
    try {
      const res = await BackendAPI.git.conflicts();
      setConflicts(res?.conflicted || []);
    } catch { }
  }, []);

  useEffect(() => {
    if (!gitStatus) refreshStatus();
    refreshBranches();
    refreshConflicts();
  }, []);

  const showMsg = (msg: string) => {
    setStatusMsg(msg);
    setTimeout(() => setStatusMsg(''), 3000);
  };

  // ── Stage / Unstage / Discard (P0) ──
  const handleStage = async (file: string) => {
    const res = await BackendAPI.git.stage([file]);
    if (res?.success) { showMsg('Staged: ' + file); refreshStatus(); }
    else showMsg('Stage fail: ' + (res?.error || ''));
  };

  const handleUnstage = async (file: string) => {
    const res = await BackendAPI.git.unstage([file]);
    if (res?.success) { showMsg('Unstaged: ' + file); refreshStatus(); }
    else showMsg('Unstage fail: ' + (res?.error || ''));
  };

  const handleDiscard = async (file: string) => {
    if (!confirm('Discard changes in ' + file + '?')) return;
    const res = await BackendAPI.git.discard([file]);
    if (res?.success) { showMsg('Discarded: ' + file); refreshStatus(); }
    else showMsg('Discard fail: ' + (res?.error || ''));
  };

  const handleCommit = async () => {
    if (!commitMsg.trim()) return;
    const res = await BackendAPI.git.commit([], commitMsg);
    if (res?.success) {
      showMsg('OK: ' + (res.hash?.slice(0, 8) || ''));
      setCommitMsg('');
      refreshStatus();
    } else showMsg('Fail: ' + (res?.error || ''));
  };

  const handlePush = async () => {
    const res = await BackendAPI.git.push();
    showMsg(res?.success ? 'Pushed OK' : 'Push fail: ' + (res?.error || ''));
  };

  const handlePull = async () => {
    const res = await BackendAPI.git.pull();
    if (res?.success) { showMsg('Pulled OK'); refreshStatus(); }
    else showMsg('Pull fail: ' + (res?.error || ''));
  };

  const handleFetch = async () => {
    const res = await BackendAPI.git.fetch();
    showMsg(res?.success ? 'Fetched OK' : 'Fetch fail: ' + (res?.error || ''));
  };

  const handleSwitchBranch = async (name: string) => {
    const res = await BackendAPI.git.switchBranch(name);
    if (res?.success) {
      showMsg('Switched to ' + name);
      setShowBranchMenu(false);
      refreshStatus(); refreshBranches();
    } else showMsg('Switch fail: ' + (res?.error || ''));
  };

  const handleDeleteBranch = async (name: string) => {
    if (!confirm('Delete branch "' + name + '"?')) return;
    const res = await BackendAPI.git.deleteBranch(name);
    if (res?.success) { showMsg('Deleted ' + name); refreshBranches(); }
    else showMsg('Delete fail: ' + (res?.error || ''));
  };

  const handleCreateBranch = async () => {
    if (!newBranchName.trim()) return;
    const res = await BackendAPI.git.createBranch(newBranchName);
    if (res?.success) {
      showMsg('Created ' + newBranchName);
      setNewBranchName('');
      refreshBranches();
    } else showMsg('Create fail: ' + (res?.error || ''));
  };

  const handleStash = async () => {
    const res = await BackendAPI.git.stash('push');
    showMsg(res?.success ? 'Stashed' : 'Stash fail: ' + (res?.error || ''));
    if (res?.success) { refreshStatus(); refreshStashList(); }
  };

  const handleStashPop = async () => {
    const res = await BackendAPI.git.stash('pop');
    showMsg(res?.success ? 'Popped' : 'Pop fail: ' + (res?.error || ''));
    if (res?.success) { refreshStatus(); refreshStashList(); }
  };

  const handleStashApply = async (idx: number) => {
    const res = await BackendAPI.git.stashApply(idx);
    if (res?.success) { showMsg('Applied stash ' + idx); refreshStatus(); refreshStashList(); }
    else showMsg('Apply fail: ' + (res?.error || ''));
  };

  const handleStashDrop = async (idx: number) => {
    const res = await BackendAPI.git.stash('drop', String(idx));
    if (res?.success) { showMsg('Dropped stash ' + idx); refreshStashList(); }
    else showMsg('Drop fail: ' + (res?.error || ''));
  };

  const handleFileDiff = async (file: string) => {
    setSelectedFile(file === selectedFile ? null : file);
    if (file !== selectedFile) {
      const res = await BackendAPI.git.diff(file);
      setFileDiff(res?.diff || '(no diff)');
    }
  };

  const handleViewLog = async () => {
    if (showLog) { setShowLog(false); return; }
    const res = await BackendAPI.git.log(10);
    setLogs(res?.commits || []);
    setShowLog(true);
  };

  const handleGenerateMessage = async () => {
    const res = await BackendAPI.git.generateMessage();
    if (res?.message) setCommitMsg(res.message);
  };

  const handleFileHistory = async (file: string) => {
    if (showFileHistory === file) { setShowFileHistory(null); return; }
    const res = await BackendAPI.git.fileHistory(file);
    setFileHistoryData(res?.commits || []);
    setShowFileHistory(file);
  };

  // ── Phase 3 (P2) operations ──
  const handleReset = async (mode: string) => {
    if (!confirm('Reset (' + mode + ') will undo changes. Continue?')) return;
    const res = await BackendAPI.git.reset(mode);
    showMsg(res?.success ? 'Reset (' + mode + ') OK' : 'Reset fail: ' + (res?.error || ''));
    if (res?.success) refreshStatus();
  };

  const handleRevert = async () => {
    const hash = prompt('Commit hash to revert (e.g. HEAD):');
    if (!hash) return;
    const res = await BackendAPI.git.revert(hash);
    showMsg(res?.success ? 'Reverted OK' : 'Revert fail: ' + (res?.error || ''));
    if (res?.success) refreshStatus();
  };

  const handleResolveConflict = async (file: string, resolution: string) => {
    const res = await BackendAPI.git.resolveConflict(file, resolution);
    if (res?.success) { showMsg('Resolved ' + file + ' (' + resolution + ')'); refreshConflicts(); refreshStatus(); }
    else showMsg('Resolve fail: ' + (res?.error || ''));
  };

  const handleAddGitignore = async () => {
    if (!gitignorePattern.trim()) return;
    const res = await BackendAPI.git.addToGitignore(gitignorePattern);
    showMsg(res?.success ? 'Added to .gitignore' : 'Fail: ' + (res?.error || ''));
    if (res?.success) setGitignorePattern('');
  };

  const changes = (gitStatus as any)?.files || gitStatus?.changes || [];
  const stagedFiles = changes.filter((c: any) => c.staged);
  const unstagedFiles = changes.filter((c: any) => !c.staged);

  return (
    <div className="git-panel">
      {statusMsg && <div className="git-status-msg">{statusMsg}</div>}

      {/* ── Conflicts Banner (P2) ── */}
      {conflicts.length > 0 && (
        <div className="git-conflicts-banner">
          {'⚠️ ' + conflicts.length + ' conflict(s) — '}
          {conflicts.map((c: any, i: number) => (
            <span key={i} className="git-conflict-item">
              {c.path}
              <button onClick={() => handleResolveConflict(c.path, 'ours')}>Ours</button>
              <button onClick={() => handleResolveConflict(c.path, 'theirs')}>Theirs</button>
            </span>
          ))}
        </div>
      )}

      <div className="git-header">
        <div className="git-branch-section">
          <button className="git-branch-btn" onClick={() => setShowBranchMenu(!showBranchMenu)} title="Switch branch">
            {'⎇ ' + (activeBranch || gitStatus?.branch || '...')}
            <span className="git-branch-arrow">{showBranchMenu ? '▲' : '▼'}</span>
          </button>
          <span className="git-ahead-behind">
            ({gitStatus?.ahead || 0}↑ {gitStatus?.behind || 0}↓)
          </span>
        </div>
        <div className="git-header-actions">
          <button className="git-header-btn" onClick={refreshStatus} disabled={loading}>⟳</button>
          <button className="git-header-btn" onClick={() => setShowCloneDialog(true)} title="Clone repository">📋</button>
          <button className="git-header-btn" onClick={handleViewLog}>Log</button>
          <button className="git-header-btn" onClick={() => { refreshTags(); setShowTags(!showTags); }}>Tags</button>
        </div>
      </div>

      {/* ── P0: Publish提示 ── */}
      {gitStatus && !(gitStatus as any).has_remote && (gitStatus as any).is_git_repo && (
        <div className="git-publish-banner" onClick={() => setShowPublishDialog(true)}>
          ☁️ Publish to GitHub — share your code with the world
        </div>
      )}

      {showBranchMenu && (
        <div className="git-branch-menu">
          <div className="git-branch-menu-search">
            <input value={newBranchName} onChange={e => setNewBranchName(e.target.value)}
              placeholder="New branch name..." onKeyDown={e => e.key === 'Enter' && handleCreateBranch()} />
            <button onClick={handleCreateBranch} disabled={!newBranchName.trim()}>Create</button>
          </div>
          <div className="git-branch-list">
            {branches.map((b: any) => (
              <div key={b.name} className={'git-branch-item' + (b.name === activeBranch ? ' active' : '')}>
                <span className="git-branch-name" onClick={() => b.name !== activeBranch && handleSwitchBranch(b.name)}>
                  {b.name === activeBranch ? '✓ ' : '  '}{b.name}
                </span>
                {b.name !== activeBranch && (
                  <button className="git-branch-del-btn" onClick={() => handleDeleteBranch(b.name)} title="Delete branch">🗑️</button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Tags Panel (P2) ── */}
      {showTags && (
        <div className="git-log-panel">
          <div className="git-log-header">
            <span>Tags</span>
            <button onClick={() => setShowTags(false)}>×</button>
          </div>
          {tags.length === 0 && <div className="git-placeholder">No tags</div>}
          {tags.map((t: any, i: number) => (
            <div key={i} className="git-log-item">
              <span className="git-log-hash">{'🏷️ ' + t.name}</span>
              <span className="git-log-msg">{t.message || t.commit}</span>
              <span className="git-log-date">{t.date?.slice(0, 10)}</span>
            </div>
          ))}
        </div>
      )}

      {showLog && (
        <div className="git-log-panel">
          <div className="git-log-header">
            <span>Commit History</span>
            <button onClick={() => setShowLog(false)}>×</button>
          </div>
          {logs.map((c: any, i: number) => (
            <div key={i} className="git-log-item">
              <span className="git-log-hash">{c.hash?.slice(0, 7)}</span>
              <span className="git-log-msg">{c.message}</span>
              <span className="git-log-date">{c.date?.slice(0, 10)}</span>
            </div>
          ))}
        </div>
      )}

      {/* ── Stash Panel (P1) ── */}
      {showStashMenu && (
        <div className="git-log-panel">
          <div className="git-log-header">
            <span>Stash List</span>
            <button onClick={() => { setShowStashMenu(false); refreshStashList(); }}>↻</button>
            <button onClick={() => setShowStashMenu(false)}>×</button>
          </div>
          {stashList.length === 0 && <div className="git-placeholder">No stashes</div>}
          {stashList.map((s: string, i: number) => {
            const idxMatch = s.match(/^stash@\{(\d+)\}/);
            const idx = idxMatch ? parseInt(idxMatch[1]) : i;
            return (
              <div key={i} className="git-log-item">
                <span className="git-log-msg">{s}</span>
                <button className="git-stash-action" onClick={() => handleStashApply(idx)} title="Apply">📋</button>
                <button className="git-stash-action" onClick={() => handleStashDrop(idx)} title="Drop">🗑️</button>
              </div>
            );
          })}
        </div>
      )}

      {/* ── P0: Staged Changes Section ── */}
      <div className="git-changes">
        {stagedFiles.length > 0 && (
          <>
            <div className="git-section-title">{'Staged (' + stagedFiles.length + ')'}</div>
            {stagedFiles.map((change: any, i: number) => (
              <div key={'s-' + i} className={'git-change-item' + (selectedFile === (change.file || change.path) ? ' selected' : '')}>
                <span className="git-change-status">{STATUS_ICONS[change.status] || change.status}</span>
                <span className="git-change-file" onClick={() => handleFileDiff(change.file || change.path)}>
                  {change.file || change.path}
                </span>
                <button className="git-stage-btn" onClick={() => handleUnstage(change.file || change.path)} title="Unstage">⊖</button>
              </div>
            ))}
          </>
        )}

        {unstagedFiles.length > 0 && (
          <>
            <div className="git-section-title">{'Changes (' + unstagedFiles.length + ')'}</div>
            {unstagedFiles.map((change: any, i: number) => (
              <div key={'u-' + i} className={'git-change-item' + (selectedFile === (change.file || change.path) ? ' selected' : '')}>
                <span className="git-change-status">{STATUS_ICONS[change.status] || change.status}</span>
                <span className="git-change-file" onClick={() => handleFileDiff(change.file || change.path)}>
                  {change.file || change.path}
                </span>
                <button className="git-stage-btn" onClick={() => handleStage(change.file || change.path)} title="Stage">⊕</button>
                <button className="git-stage-btn" onClick={() => handleDiscard(change.file || change.path)} title="Discard">🗑️</button>
                <button className="git-stage-btn" onClick={() => handleFileHistory(change.file || change.path)} title="History">📜</button>
              </div>
            ))}
          </>
        )}

        {changes.length === 0 && gitStatus && (
          <div className="git-placeholder">Clean working tree</div>
        )}
      </div>

      {/* ── File History (P1) ── */}
      {showFileHistory && (
        <div className="git-log-panel" style={{ margin: '4px' }}>
          <div className="git-log-header">
            <span>{'📜 ' + showFileHistory}</span>
            <button onClick={() => setShowFileHistory(null)}>×</button>
          </div>
          {fileHistoryData.map((c: any, i: number) => (
            <div key={i} className="git-log-item">
              <span className="git-log-hash">{c.hash}</span>
              <span className="git-log-msg">{c.message}</span>
              <span className="git-log-date">{c.date?.slice(0, 10)}</span>
            </div>
          ))}
        </div>
      )}

      {/* ── Diff Preview ── */}
      {selectedFile && !showFileHistory && (
        <div className="git-diff-preview">
          <div className="git-diff-header">
            <span>{selectedFile}</span>
            <button onClick={() => setSelectedFile(null)}>×</button>
          </div>
          <pre className="git-diff-content"><code>{fileDiff}</code></pre>
        </div>
      )}

      {/* ── Commit Area ── */}
      <div className="git-commit-area">
        <textarea className="git-commit-input" value={commitMsg}
          onChange={e => setCommitMsg(e.target.value)} placeholder="Commit message..." rows={2} />
        <div className="git-commit-actions">
          <button className="git-commit-btn" onClick={handleCommit} disabled={!commitMsg.trim() || loading}>
            Commit
          </button>
          <button className="git-gen-msg-btn" onClick={handleGenerateMessage} title="AI generate message">AI</button>
        </div>
      </div>

      {/* ── P2: .gitignore Pattern Input ── */}
      <div className="git-ignore-area">
        <input className="git-ignore-input" value={gitignorePattern}
          onChange={e => setGitignorePattern(e.target.value)} placeholder=".gitignore pattern..." />
        <button className="git-ignore-btn" onClick={handleAddGitignore} disabled={!gitignorePattern.trim()}>Add</button>
      </div>

      {/* ── Actions Bar (P0+P1+P2) ── */}
      <div className="git-actions">
        <button className="git-action-btn" onClick={handlePush} title="Push">Push</button>
        <button className="git-action-btn" onClick={handlePull} title="Pull">Pull</button>
        <button className="git-action-btn" onClick={handleFetch} title="Fetch">Fetch</button>
        <button className="git-action-btn" onClick={handleStash} title="Stash push">Stash</button>
        <button className="git-action-btn" onClick={handleStashPop} title="Stash pop">Pop</button>
        <button className="git-action-btn" onClick={() => { setShowStashMenu(true); refreshStashList(); }} title="Stash list">
          📋
        </button>
      </div>

      {/* ── P2: Advanced Actions ── */}
      <div className="git-advanced-actions">
        <button className="git-action-btn" onClick={() => handleReset('soft')} title="Reset soft">Rst‑S</button>
        <button className="git-action-btn" onClick={() => handleReset('mixed')} title="Reset mixed">Rst‑M</button>
        <button className="git-action-btn" onClick={() => handleReset('hard')} title="Reset hard">Rst‑H</button>
        <button className="git-action-btn" onClick={handleRevert} title="Revert commit">Revert</button>
      </div>

      {/* ── Clone/Publish Dialogs ── */}
      {showCloneDialog && <CloneDialog onClose={() => setShowCloneDialog(false)} onCloned={() => refreshStatus()} />}
      {showPublishDialog && <PublishDialog onClose={() => setShowPublishDialog(false)} onPublished={() => refreshStatus()} />}
    </div>
  );
};

