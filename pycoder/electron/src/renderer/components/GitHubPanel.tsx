import React, { useEffect, useState, useCallback } from 'react';
import { BackendAPI } from '../services/backend';

type TabType = 'repos' | 'pulls' | 'issues';
type ViewType = 'list' | 'auth';

interface Repo {
    name: string; full_name: string; description: string;
    private: boolean; html_url: string; clone_url: string;
    language: string; stargazers_count: number; forks_count: number;
    open_issues_count: number; updated_at: string;
}

interface PullRequest {
    number: number; title: string; state: string;
    user: string; created_at: string; html_url: string;
    head: string; base: string;
}

interface Issue {
    number: number; title: string; state: string;
    user: string; labels: { name: string; color: string }[];
    created_at: string; html_url: string;
}

export const GitHubPanel: React.FC = () => {
    const [view, setView] = useState<ViewType>('auth');
    const [tab, setTab] = useState<TabType>('repos');
    const [user, setUser] = useState<any>(null);
    const [token, setToken] = useState('');
    const [repos, setRepos] = useState<Repo[]>([]);
    const [pulls, setPulls] = useState<PullRequest[]>([]);
    const [issues, setIssues] = useState<Issue[]>([]);
    const [loading, setLoading] = useState(false);
    const [statusMsg, setStatusMsg] = useState('');
    const [activeRepo, setActiveRepo] = useState<string>('');
    const [search, setSearch] = useState('');
    const [showCloneDialog, setShowCloneDialog] = useState(false);

    const showMsg = (msg: string) => {
        setStatusMsg(msg);
        setTimeout(() => setStatusMsg(''), 3000);
    };

    const checkAuth = useCallback(async () => {
        const res = await BackendAPI.github.authStatus();
        if (res?.authenticated) {
            setUser(res.user);
            setView('list');
            fetchRepos();
        }
    }, []);

    const handleAuth = async () => {
        if (!token.trim()) return;
        setLoading(true);
        const res = await BackendAPI.github.auth(token.trim());
        setLoading(false);
        if (res?.success) {
            setUser(res.user);
            setView('list');
            showMsg('已连接为 ' + res.user);
            fetchRepos();
        } else {
            showMsg('认证失败: ' + (res?.error || '错误'));
        }
    };

    const handleLogout = async () => {
        await BackendAPI.github.authClear();
        setUser(null);
        setView('auth');
        setRepos([]);
        showMsg('已断开连接');
    };

    const fetchRepos = useCallback(async () => {
        setLoading(true);
        const res = await BackendAPI.github.repos();
        setRepos(res?.repos || []);
        setLoading(false);
    }, []);

    const fetchPulls = useCallback(async (repoFullName: string) => {
        const [owner, repo] = repoFullName.split('/');
        const res = await BackendAPI.github.pulls(owner, repo);
        setPulls(res?.pulls || []);
    }, []);

    const fetchIssues = useCallback(async (repoFullName: string) => {
        const [owner, repo] = repoFullName.split('/');
        const res = await BackendAPI.github.issues(owner, repo);
        setIssues(res?.issues || []);
    }, []);

    const handleSelectRepo = (fullName: string) => {
        if (activeRepo === fullName) {
            setActiveRepo('');
            setPulls([]);
            setIssues([]);
            return;
        }
        setActiveRepo(fullName);
        if (tab === 'pulls') fetchPulls(fullName);
        if (tab === 'issues') fetchIssues(fullName);
    };

    const handleOpenGitHub = (url: string) => {
        window.open(url, '_blank');
    };

    useEffect(() => { checkAuth(); }, []);

    // ── Auth View ──
    if (view === 'auth') {
        return (
            <div className="git-panel">
                {statusMsg && <div className="git-status-msg">{statusMsg}</div>}
                <div className="git-header" style={{ justifyContent: 'center', padding: '20px 10px' }}>
                    <span style={{ fontSize: 24 }}>🐙</span>
                </div>
                <div style={{ padding: '0 10px' }}>
                    <label className="modal-label">GitHub 个人访问令牌</label>
                    <input className="settings-input" type="password" value={token}
                        onChange={e => setToken(e.target.value)}
                        placeholder="ghp_xxxxxxxxxxxxxxxxxxxx" />
                    <div className="modal-hint">
                        在以下地址创建令牌：{' '}
                        <a href="#" onClick={() => window.open('https://github.com/settings/tokens', '_blank')}>
                            github.com/settings/tokens
                        </a>
                        {' '}，需勾选 repo 权限。
                    </div>
                    <div className="modal-actions" style={{ marginTop: 12 }}>
                        <button className="settings-btn settings-btn-primary"
                            onClick={handleAuth} disabled={loading || !token.trim()}>
                            {loading ? '连接中...' : '连接 GitHub'}
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    // ── GitHub Connected View ──
    const filteredRepos = search
        ? repos.filter(r => r.name.toLowerCase().includes(search.toLowerCase()) || r.full_name.toLowerCase().includes(search.toLowerCase()))
        : repos;

    return (
        <div className="git-panel">
            {statusMsg && <div className="git-status-msg">{statusMsg}</div>}

            <div className="git-header">
                <div className="git-branch-section">
                    <span style={{ fontSize: 14 }}>🐙 {user?.login || 'GitHub'}</span>
                </div>
                <div className="git-header-actions">
                    <button className="git-header-btn" onClick={fetchRepos} disabled={loading}>⟳</button>
                    <button className="git-header-btn" onClick={handleLogout} title="断开连接">⏻</button>
                </div>
            </div>

            <div className="git-tabs" style={{ display: 'flex', borderBottom: '1px solid var(--border-color)' }}>
                {(['repos', 'pulls', 'issues'] as TabType[]).map(t => (
                    <button key={t}
                        className={'git-tab ' + (tab === t ? 'active' : '')}
                        style={{
                            flex: 1, padding: '6px 0', fontSize: 10, textTransform: 'uppercase',
                            background: 'transparent', border: 'none', borderBottom: tab === t ? '2px solid var(--accent)' : '2px solid transparent',
                            color: tab === t ? 'var(--text-primary)' : 'var(--text-muted)', cursor: 'pointer'
                        }}
                        onClick={() => { setTab(t); if (activeRepo) { t === 'pulls' ? fetchPulls(activeRepo) : fetchIssues(activeRepo); } }}>
                        {t === 'repos' ? '📦 仓库' : t === 'pulls' ? '🔀 PR' : '🐛 议题'}
                    </button>
                ))}
            </div>

            {tab === 'repos' && (
                <>
                    <div style={{ padding: '4px 8px' }}>
                        <input className="extensions-search" value={search}
                            onChange={e => setSearch(e.target.value)} placeholder="搜索仓库..." />
                    </div>
                    <div className="git-changes">
                        {filteredRepos.length === 0 && <div className="git-placeholder">暂无仓库</div>}
                        {filteredRepos.map(r => (
                            <div key={r.full_name}
                                className={'git-change-item' + (activeRepo === r.full_name ? ' selected' : '')}
                                onClick={() => handleSelectRepo(r.full_name)}>
                                <span className="git-change-status">{r.private ? '🔒' : '🌍'}</span>
                                <span className="git-change-file">
                                    <div style={{ fontSize: 12, fontWeight: 500 }}>{r.name}</div>
                                    <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                                        {(r.language || '') && <span>{r.language} · </span>}
                                        ⭐{r.stargazers_count} · 🍴{r.forks_count}
                                    </div>
                                </span>
                                <button className="git-stage-btn" onClick={e => { e.stopPropagation(); handleOpenGitHub(r.html_url); }} title="在 GitHub 中打开">🌐</button>
                                <button className="git-stage-btn" onClick={e => { e.stopPropagation(); navigator.clipboard.writeText(r.clone_url); showMsg('地址已复制'); }} title="复制克隆地址">📋</button>
                            </div>
                        ))}
                    </div>
                </>
            )}

            {tab === 'pulls' && (
                <div className="git-changes">
                    {!activeRepo && <div className="git-placeholder">请先选择仓库</div>}
                    {activeRepo && pulls.length === 0 && <div className="git-placeholder">暂无打开的 PR</div>}
                    {pulls.map(pr => (
                        <div key={pr.number} className="git-change-item" onClick={() => handleOpenGitHub(pr.html_url)}>
                            <span className="git-change-status">{pr.draft ? '📝' : '🔀'}</span>
                            <span className="git-change-file">
                                <div style={{ fontSize: 12 }}>#{pr.number} {pr.title}</div>
                                <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{pr.user} · {pr.head}→{pr.base}</div>
                            </span>
                        </div>
                    ))}
                </div>
            )}

            {tab === 'issues' && (
                <div className="git-changes">
                    {!activeRepo && <div className="git-placeholder">请先选择仓库</div>}
                    {activeRepo && issues.length === 0 && <div className="git-placeholder">暂无打开的议题</div>}
                    {issues.map(iss => (
                        <div key={iss.number} className="git-change-item" onClick={() => handleOpenGitHub(iss.html_url)}>
                            <span className="git-change-status">🐛</span>
                            <span className="git-change-file">
                                <div style={{ fontSize: 12 }}>#{iss.number} {iss.title}</div>
                                <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                                    {iss.labels.map((l, i) => (
                                        <span key={i} style={{ background: '#' + l.color, color: '#fff', padding: '1px 4px', borderRadius: 3, marginRight: 3, fontSize: 9 }}>
                                            {l.name}
                                        </span>
                                    ))}
                                    {iss.user}
                                </div>
                            </span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};
