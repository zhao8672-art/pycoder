/**
 * Git 分支树形面板 — 可视化分支图 + 分支操作
 */
import React, { useState, useEffect, useCallback } from 'react';
import { BackendAPI } from '../services/backend';
import { useAppStore } from '../stores/appStore';

interface BranchItem {
    name: string;
    isActive: boolean;
    isRemote: boolean;
    lastCommit: string;
    lastCommitMsg: string;
    ahead?: number;
    behind?: number;
}

export const GitBranchGraph: React.FC = () => {
    const { gitStatus, setGitStatus } = useAppStore();
    const [branches, setBranches] = useState<BranchItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [newBranch, setNewBranch] = useState('');
    const [msg, setMsg] = useState('');

    const loadBranches = useCallback(async () => {
        setLoading(true);
        try {
            const res = await BackendAPI.git.branches();
            if (res?.branches) {
                setBranches(res.branches.map((b: any) => ({
                    name: b.name || b,
                    isActive: b.name === res.active,
                    isRemote: (b.name || b).startsWith('remotes/'),
                    lastCommit: b.last_commit || b.commit || '',
                    lastCommitMsg: b.last_commit_msg || b.message || '',
                    ahead: b.ahead,
                    behind: b.behind,
                })));
            }
            const st = await BackendAPI.git.status();
            if (st) setGitStatus(st);
        } catch (e) {
            setMsg('加载分支失败');
        }
        setLoading(false);
    }, [setGitStatus]);

    useEffect(() => { loadBranches(); }, [loadBranches]);

    const handleCreateBranch = async () => {
        if (!newBranch.trim()) return;
        const res = await BackendAPI.git.createBranch(newBranch.trim());
        if (res?.success) { setNewBranch(''); setMsg(`分支 ${newBranch} 已创建`); loadBranches(); }
        else setMsg(res?.error || '创建失败');
    };

    const handleSwitchBranch = async (name: string) => {
        const res = await BackendAPI.git.switchBranch(name);
        if (res?.success) { setMsg(`已切换到 ${name}`); loadBranches(); }
        else setMsg(res?.error || '切换失败');
    };

    const handleDeleteBranch = async (name: string) => {
        if (!confirm(`确定删除分支 ${name}?`)) return;
        const res = await BackendAPI.git.deleteBranch(name, false);
        if (res?.success) { setMsg(`分支 ${name} 已删除`); loadBranches(); }
        else setMsg(res?.error || '删除失败');
    };

    const handlePush = async () => {
        const res = await BackendAPI.git.push();
        if (res?.success) { setMsg('推送成功'); loadBranches(); }
        else setMsg(res?.error || '推送失败');
    };

    const handlePull = async () => {
        const res = await BackendAPI.git.pull();
        if (res?.success) { setMsg('拉取成功'); loadBranches(); }
        else setMsg(res?.error || '拉取失败');
    };

    const localBranches = branches.filter(b => !b.isRemote);
    const remoteBranches = branches.filter(b => b.isRemote);

    return (
        <div className="branch-graph">
            <div className="branch-toolbar">
                <span className="branch-title">🌿 分支管理 ({branches.length})</span>
                <div className="branch-actions">
                    <button className="btn-xs" onClick={handlePull} title="拉取">⬇</button>
                    <button className="btn-xs" onClick={handlePush} title="推送">⬆</button>
                    <button className="btn-xs" onClick={loadBranches} title="刷新">🔄</button>
                </div>
            </div>

            {msg && <div className="branch-msg">{msg}</div>}

            <div className="branch-create">
                <input
                    className="input-xs"
                    value={newBranch}
                    onChange={e => setNewBranch(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleCreateBranch()}
                    placeholder="新分支名称..."
                />
                <button className="btn-xs" onClick={handleCreateBranch}>+ 创建</button>
            </div>

            <div className="branch-list">
                <div className="branch-section-title">📌 本地分支</div>
                {localBranches.map((b, i) => (
                    <div key={i} className={`branch-item ${b.isActive ? 'active' : ''}`}>
                        <span className="branch-icon">{b.isActive ? '⭐' : '🔹'}</span>
                        <span className="branch-name" onClick={() => handleSwitchBranch(b.name)}>{b.name}</span>
                        {b.lastCommitMsg && <span className="branch-commit" title={b.lastCommitMsg}>{b.lastCommitMsg.slice(0, 40)}</span>}
                        {b.ahead ? <span className="branch-ahead">↑{b.ahead}</span> : null}
                        {b.behind ? <span className="branch-behind">↓{b.behind}</span> : null}
                        {!b.isActive && (
                            <button className="btn-del" onClick={() => handleDeleteBranch(b.name)}>🗑</button>
                        )}
                    </div>
                ))}

                {remoteBranches.length > 0 && (
                    <>
                        <div className="branch-section-title">🌐 远程分支</div>
                        {remoteBranches.map((b, i) => (
                            <div key={i} className="branch-item remote">
                                <span className="branch-icon">☁️</span>
                                <span className="branch-name">{b.name.replace('remotes/origin/', '')}</span>
                                <span className="branch-commit">{b.lastCommitMsg?.slice(0, 40)}</span>
                            </div>
                        ))}
                    </>
                )}
            </div>

            {loading && <div className="branch-loading">⏳ 加载中...</div>}

            <style>{`
        .branch-graph { display:flex; flex-direction:column; height:100%; overflow:hidden; }
        .branch-toolbar { display:flex; justify-content:space-between; align-items:center; padding:8px 12px; border-bottom:1px solid #333; }
        .branch-title { font-size:12px; font-weight:600; color:#ccc; }
        .branch-actions { display:flex; gap:4px; }
        .btn-xs { padding:2px 6px; border-radius:3px; border:1px solid #555; background:#1a1a2e; color:#ddd; font-size:10px; cursor:pointer; }
        .btn-xs:hover { background:#333; }
        .btn-del { background:none; border:none; cursor:pointer; font-size:12px; opacity:0.5; }
        .btn-del:hover { opacity:1; }
        .branch-msg { padding:4px 12px; font-size:11px; color:#4c6; }
        .branch-create { display:flex; gap:4px; padding:8px 12px; }
        .input-xs { flex:1; padding:3px 6px; border-radius:3px; border:1px solid #555; background:#1a1a2e; color:#ddd; font-size:11px; }
        .input-xs:focus { outline:none; border-color:#68f; }
        .branch-list { flex:1; overflow-y:auto; padding:4px 0; }
        .branch-section-title { padding:6px 12px 2px; font-size:10px; color:#888; text-transform:uppercase; letter-spacing:0.5px; }
        .branch-item { display:flex; align-items:center; gap:6px; padding:5px 12px; font-size:12px; cursor:pointer; }
        .branch-item:hover { background:rgba(255,255,255,0.03); }
        .branch-item.active { background:rgba(100,150,255,0.1); }
        .branch-item.active .branch-name { color:#68f; font-weight:600; }
        .branch-icon { font-size:10px; }
        .branch-name { color:#ddd; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:180px; }
        .branch-commit { color:#888; font-size:10px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; }
        .branch-ahead { color:#6c6; font-size:10px; }
        .branch-behind { color:#f96; font-size:10px; margin-left:2px; }
        .branch-item.remote { opacity:0.7; }
        .branch-item.remote .branch-icon { font-size:10px; }
        .branch-loading { padding:20px; text-align:center; color:#888; }
      `}</style>
        </div>
    );
};
