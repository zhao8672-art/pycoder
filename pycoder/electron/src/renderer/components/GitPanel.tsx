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

  // 每 5 秒自动刷新 (P1)
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

  // ── 暂存 / 取消暂存 / 丢弃 (P0) ──
  const handleStage = async (file: string) => {
    const res = await BackendAPI.git.stage([file]);
    if (res?.success) { showMsg('已暂存: ' + file); refreshStatus(); }
    else showMsg('暂存失败: ' + (res?.error || ''));
  };

  const handleUnstage = async (file: string) => {
    const res = await BackendAPI.git.unstage([file]);
    if (res?.success) { showMsg('已取消暂存: ' + file); refreshStatus(); }
    else showMsg('取消暂存失败: ' + (res?.error || ''));
  };

  const handleDiscard = async (file: string) => {
    if (!confirm('丢弃 ' + file + ' 的更改？')) return;
    const res = await BackendAPI.git.discard([file]);
    if (res?.success) { showMsg('已丢弃: ' + file); refreshStatus(); }
    else showMsg('丢弃失败: ' + (res?.error || ''));
  };

  const handleCommit = async () => {
    if (!commitMsg.trim()) return;
    const res = await BackendAPI.git.commit([], commitMsg);
    if (res?.success) {
      showMsg('提交成功: ' + (res.hash?.slice(0, 8) || ''));
      setCommitMsg('');
      refreshStatus();
    } else showMsg('提交失败: ' + (res?.error || ''));
  };

  const handlePush = async () => {
    const res = await BackendAPI.git.push();
    showMsg(res?.success ? '推送成功' : '推送失败: ' + (res?.error || ''));
  };

  const handlePull = async () => {
    const res = await BackendAPI.git.pull();
    if (res?.success) { showMsg('拉取成功'); refreshStatus(); }
    else showMsg('拉取失败: ' + (res?.error || ''));
  };

  const handleFetch = async () => {
    const res = await BackendAPI.git.fetch();
    showMsg(res?.success ? '获取成功' : '获取失败: ' + (res?.error || ''));
  };

  const handleSwitchBranch = async (name: string) => {
    const res = await BackendAPI.git.switchBranch(name);
    if (res?.success) {
      showMsg('已切换到 ' + name);
      setShowBranchMenu(false);
      refreshStatus(); refreshBranches();
    } else showMsg('切换失败: ' + (res?.error || ''));
  };

  const handleDeleteBranch = async (name: string) => {
    if (!confirm('删除分支 "' + name + '"？')) return;
    const res = await BackendAPI.git.deleteBranch(name);
    if (res?.success) { showMsg('已删除 ' + name); refreshBranches(); }
    else showMsg('删除失败: ' + (res?.error || ''));
  };

  const handleCreateBranch = async () => {
    if (!newBranchName.trim()) return;
    const res = await BackendAPI.git.createBranch(newBranchName);
    if (res?.success) {
      showMsg('已创建 ' + newBranchName);
      setNewBranchName('');
      refreshBranches();
    } else showMsg('创建失败: ' + (res?.error || ''));
  };

  const handleStash = async () => {
    const res = await BackendAPI.git.stash('push');
    showMsg(res?.success ? '已储藏' : '储藏失败: ' + (res?.error || ''));
    if (res?.success) { refreshStatus(); refreshStashList(); }
  };

  const handleStashPop = async () => {
    const res = await BackendAPI.git.stash('pop');
    showMsg(res?.success ? '已恢复' : '恢复失败: ' + (res?.error || ''));
    if (res?.success) { refreshStatus(); refreshStashList(); }
  };

  const handleStashApply = async (idx: number) => {
    const res = await BackendAPI.git.stashApply(idx);
    if (res?.success) { showMsg('已应用储藏 ' + idx); refreshStatus(); refreshStashList(); }
    else showMsg('应用失败: ' + (res?.error || ''));
  };

  const handleStashDrop = async (idx: number) => {
    const res = await BackendAPI.git.stash('drop', String(idx));
    if (res?.success) { showMsg('已删除储藏 ' + idx); refreshStashList(); }
    else showMsg('删除失败: ' + (res?.error || ''));
  };

  const handleFileDiff = async (file: string) => {
    setSelectedFile(file === selectedFile ? null : file);
    if (file !== selectedFile) {
      const res = await BackendAPI.git.diff(file);
      setFileDiff(res?.diff || '(无差异)');
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

  // ── Phase 3 (P2) 操作 ──
  const handleReset = async (mode: string) => {
    if (!confirm('重置 (' + mode + ') 将撤销更改。继续？')) return;
    const res = await BackendAPI.git.reset(mode);
    showMsg(res?.success ? '重置 (' + mode + ') 成功' : '重置失败: ' + (res?.error || ''));
    if (res?.success) refreshStatus();
  };

  const handleRevert = async () => {
    const hash = prompt('要撤销的提交哈希 (如 HEAD)：');
    if (!hash) return;
    const res = await BackendAPI.git.revert(hash);
    showMsg(res?.success ? '撤销成功' : '撤销失败: ' + (res?.error || ''));
    if (res?.success) refreshStatus();
  };

  const handleResolveConflict = async (file: string, resolution: string) => {
    const res = await BackendAPI.git.resolveConflict(file, resolution);
    if (res?.success) { showMsg('已解决 ' + file + ' (' + resolution + ')'); refreshConflicts(); refreshStatus(); }
    else showMsg('解决失败: ' + (res?.error || ''));
  };

  const handleAddGitignore = async () => {
    if (!gitignorePattern.trim()) return;
    const res = await BackendAPI.git.addToGitignore(gitignorePattern);
    showMsg(res?.success ? '已添加到 .gitignore' : '失败: ' + (res?.error || ''));
    if (res?.success) setGitignorePattern('');
  };

  const changes = (gitStatus as any)?.files || gitStatus?.changes || [];
  const stagedFiles = changes.filter((c: any) => c.staged);
  const unstagedFiles = changes.filter((c: any) => !c.staged);

  return (
    <div className="git-panel">
      {statusMsg && <div className="git-status-msg">{statusMsg}</div>}

      {/* ── 冲突提示 (P2) ── */}
      {conflicts.length > 0 && (
        <div className="git-conflicts-banner">
          {'⚠️ ' + conflicts.length + ' 个冲突 — '}
          {conflicts.map((c: any, i: number) => (
            <span key={i} className="git-conflict-item">
              {c.path}
              <button onClick={() => handleResolveConflict(c.path, 'ours')}>保留我方</button>
              <button onClick={() => handleResolveConflict(c.path, 'theirs')}>保留他方</button>
            </span>
          ))}
        </div>
      )}

      <div className="git-header">
        <div className="git-branch-section">
          <button className="git-branch-btn" onClick={() => setShowBranchMenu(!showBranchMenu)} title="切换分支">
            {'⎇ ' + (activeBranch || gitStatus?.branch || '...')}
            <span className="git-branch-arrow">{showBranchMenu ? '▲' : '▼'}</span>
          </button>
          <span className="git-ahead-behind">
            ({gitStatus?.ahead || 0}↑ {gitStatus?.behind || 0}↓)
          </span>
        </div>
        <div className="git-header-actions">
          <button className="git-header-btn" onClick={refreshStatus} disabled={loading}>⟳</button>
          <button className="git-header-btn" onClick={() => setShowCloneDialog(true)} title="克隆仓库">📋</button>
          <button className="git-header-btn" onClick={handleViewLog}>日志</button>
          <button className="git-header-btn" onClick={() => { refreshTags(); setShowTags(!showTags); }}>标签</button>
        </div>
      </div>

      {/* ── P0: 发布提示 ── */}
      {gitStatus && !(gitStatus as any).has_remote && (gitStatus as any).is_git_repo && (
        <div className="git-publish-banner" onClick={() => setShowPublishDialog(true)}>
          ☁️ 发布到 GitHub — 分享你的代码
        </div>
      )}

      {showBranchMenu && (
        <div className="git-branch-menu">
          <div className="git-branch-menu-search">
            <input value={newBranchName} onChange={e => setNewBranchName(e.target.value)}
              placeholder="新分支名称..." onKeyDown={e => e.key === 'Enter' && handleCreateBranch()} />
            <button onClick={handleCreateBranch} disabled={!newBranchName.trim()}>创建</button>
          </div>
          <div className="git-branch-list">
            {branches.map((b: any) => (
              <div key={b.name} className={'git-branch-item' + (b.name === activeBranch ? ' active' : '')}>
                <span className="git-branch-name" onClick={() => b.name !== activeBranch && handleSwitchBranch(b.name)}>
                  {b.name === activeBranch ? '✓ ' : '  '}{b.name}
                </span>
                {b.name !== activeBranch && (
                  <button className="git-branch-del-btn" onClick={() => handleDeleteBranch(b.name)} title="删除分支">🗑️</button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 标签面板 (P2) ── */}
      {showTags && (
        <div className="git-log-panel">
          <div className="git-log-header">
            <span>标签</span>
            <button onClick={() => setShowTags(false)}>×</button>
          </div>
          {tags.length === 0 && <div className="git-placeholder">暂无标签</div>}
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
            <span>提交历史</span>
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

      {/* ── 储藏面板 (P1) ── */}
      {showStashMenu && (
        <div className="git-log-panel">
          <div className="git-log-header">
            <span>储藏列表</span>
            <button onClick={() => { setShowStashMenu(false); refreshStashList(); }}>↻</button>
            <button onClick={() => setShowStashMenu(false)}>×</button>
          </div>
          {stashList.length === 0 && <div className="git-placeholder">暂无储藏</div>}
          {stashList.map((s: string, i: number) => {
            const idxMatch = s.match(/^stash@\{(\d+)\}/);
            const idx = idxMatch ? parseInt(idxMatch[1]) : i;
            return (
              <div key={i} className="git-log-item">
                <span className="git-log-msg">{s}</span>
                <button className="git-stash-action" onClick={() => handleStashApply(idx)} title="应用">📋</button>
                <button className="git-stash-action" onClick={() => handleStashDrop(idx)} title="删除">🗑️</button>
              </div>
            );
          })}
        </div>
      )}

      {/* ── P0: 已暂存更改区域 ── */}
      <div className="git-changes">
        {stagedFiles.length > 0 && (
          <>
            <div className="git-section-title">{'已暂存 (' + stagedFiles.length + ')'}</div>
            {stagedFiles.map((change: any, i: number) => (
              <div key={'s-' + i} className={'git-change-item' + (selectedFile === (change.file || change.path) ? ' selected' : '')}>
                <span className="git-change-status">{STATUS_ICONS[change.status] || change.status}</span>
                <span className="git-change-file" onClick={() => handleFileDiff(change.file || change.path)}>
                  {change.file || change.path}
                </span>
                <button className="git-stage-btn" onClick={() => handleUnstage(change.file || change.path)} title="取消暂存">⊖</button>
              </div>
            ))}
          </>
        )}

        {unstagedFiles.length > 0 && (
          <>
            <div className="git-section-title">{'更改 (' + unstagedFiles.length + ')'}</div>
            {unstagedFiles.map((change: any, i: number) => (
              <div key={'u-' + i} className={'git-change-item' + (selectedFile === (change.file || change.path) ? ' selected' : '')}>
                <span className="git-change-status">{STATUS_ICONS[change.status] || change.status}</span>
                <span className="git-change-file" onClick={() => handleFileDiff(change.file || change.path)}>
                  {change.file || change.path}
                </span>
                <button className="git-stage-btn" onClick={() => handleStage(change.file || change.path)} title="暂存">⊕</button>
                <button className="git-stage-btn" onClick={() => handleDiscard(change.file || change.path)} title="丢弃">🗑️</button>
                <button className="git-stage-btn" onClick={() => handleFileHistory(change.file || change.path)} title="历史">📜</button>
              </div>
            ))}
          </>
        )}

        {changes.length === 0 && gitStatus && (
          <div className="git-placeholder">工作区干净</div>
        )}
      </div>

      {/* ── 文件历史 (P1) ── */}
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

      {/* ── 差异预览 ── */}
      {selectedFile && !showFileHistory && (
        <div className="git-diff-preview">
          <div className="git-diff-header">
            <span>{selectedFile}</span>
            <button onClick={() => setSelectedFile(null)}>×</button>
          </div>
          <pre className="git-diff-content"><code>{fileDiff}</code></pre>
        </div>
      )}

      {/* ── 提交区域 ── */}
      <div className="git-commit-area">
        <textarea className="git-commit-input" value={commitMsg}
          onChange={e => setCommitMsg(e.target.value)} placeholder="提交信息..." rows={2} />
        <div className="git-commit-actions">
          <button className="git-commit-btn" onClick={handleCommit} disabled={!commitMsg.trim() || loading}>
            提交
          </button>
          <button className="git-gen-msg-btn" onClick={handleGenerateMessage} title="AI 生成提交信息">AI</button>
        </div>
      </div>

      {/* ── P2: .gitignore 规则输入 ── */}
      <div className="git-ignore-area">
        <input className="git-ignore-input" value={gitignorePattern}
          onChange={e => setGitignorePattern(e.target.value)} placeholder=".gitignore 规则..." />
        <button className="git-ignore-btn" onClick={handleAddGitignore} disabled={!gitignorePattern.trim()}>添加</button>
      </div>

      {/* ── 操作栏 (P0+P1+P2) ── */}
      <div className="git-actions">
        <button className="git-action-btn" onClick={handlePush} title="推送">推送</button>
        <button className="git-action-btn" onClick={handlePull} title="拉取">拉取</button>
        <button className="git-action-btn" onClick={handleFetch} title="获取">获取</button>
        <button className="git-action-btn" onClick={handleStash} title="储藏">储藏</button>
        <button className="git-action-btn" onClick={handleStashPop} title="恢复储藏">恢复</button>
        <button className="git-action-btn" onClick={() => { setShowStashMenu(true); refreshStashList(); }} title="储藏列表">
          📋
        </button>
      </div>

      {/* ── P2: 高级操作 ── */}
      <div className="git-advanced-actions">
        <button className="git-action-btn" onClick={() => handleReset('soft')} title="软重置">软重置</button>
        <button className="git-action-btn" onClick={() => handleReset('mixed')} title="混合重置">混合重置</button>
        <button className="git-action-btn" onClick={() => handleReset('hard')} title="硬重置">硬重置</button>
        <button className="git-action-btn" onClick={handleRevert} title="撤销提交">撤销</button>
      </div>

      {/* ── 克隆/发布对话框 ── */}
      {showCloneDialog && <CloneDialog onClose={() => setShowCloneDialog(false)} onCloned={() => refreshStatus()} />}
      {showPublishDialog && <PublishDialog onClose={() => setShowPublishDialog(false)} onPublished={() => refreshStatus()} />}
    </div>
  );
};
