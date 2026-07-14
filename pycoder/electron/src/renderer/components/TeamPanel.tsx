import React, { useState, useEffect, useCallback, useRef } from 'react';
import { BackendAPI } from '../services/backend';
import type { WSConnectionManager, WSMessage } from '../services/websocket';

interface Workspace {
    id: string; name: string; created_by: string; created_at: number;
    member_count: number; members?: Member[];
}
interface Member { id: string; display_name: string; role: string; last_active_at: number; }
interface Review { id: string; title: string; file_path: string; status: string; requested_by: string; assigned_to: string[]; comments: Array<{ user: string; comment: string; timestamp: string }>; created_at: number; }
interface Activity { id: string; user_name: string; action: string; detail: string; timestamp: number; }

interface Props { wsClient: WSConnectionManager | null; }

type AIAgentStatus = 'idle' | 'running' | 'done' | 'failed';

export const TeamPanel: React.FC<Props> = ({ wsClient }) => {
    // ── AI Agent Team State ──
    const [aiTab, setAiTab] = useState<'agent' | 'collab'>('agent');
    const [taskInput, setTaskInput] = useState('');
    const [agentStatus, setAgentStatus] = useState<AIAgentStatus>('idle');
    const [agentLog, setAgentLog] = useState<string[]>([]);
    const [agentProgress, setAgentProgress] = useState(0);
    const [currentAgent, setCurrentAgent] = useState('');
    const [runId, setRunId] = useState('');
    const [taskList, setTaskList] = useState<any[]>([]);
    const [reviewIssues, setReviewIssues] = useState<any[]>([]);
    const [reviewRounds, setReviewRounds] = useState(0);
    const logEndRef = useRef<HTMLDivElement>(null);

    // ── Collaboration State (existing) ──
    const [collabTab, setCollabTab] = useState<'workspaces' | 'members' | 'reviews' | 'activity'>('workspaces');
    const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
    const [activeWs, setActiveWs] = useState<Workspace | null>(null);
    const [members, setMembers] = useState<Member[]>([]);
    const [reviews, setReviews] = useState<Review[]>([]);
    const [activities, setActivities] = useState<Activity[]>([]);
    const [statusMsg, setStatusMsg] = useState('');
    const [working, setWorking] = useState(false);
    const [wsName, setWsName] = useState('');
    const [showCreate, setShowCreate] = useState(false);
    const [newWsName, setNewWsName] = useState('');
    const [newWsUser, setNewWsUser] = useState('local');
    const [showJoin, setShowJoin] = useState(false);
    const [joinId, setJoinId] = useState('');
    const [joinName, setJoinName] = useState('guest');
    const [showReviewForm, setShowReviewForm] = useState(false);
    const [reviewTitle, setReviewTitle] = useState('');
    const [reviewDesc, setReviewDesc] = useState('');
    const [reviewFile, setReviewFile] = useState('');
    const [reviewCode, setReviewCode] = useState('');

    // Auto scroll log
    useEffect(() => { logEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [agentLog]);

    // ── AI Agent 任务启动 ──
    const handleStartTask = async () => {
        if (!taskInput.trim()) return;
        setAgentStatus('running');
        setAgentLog(['🚀 启动 AI Agent 团队...']);
        setAgentProgress(0);
        setCurrentAgent('');
        setTaskList([]);
        setReviewIssues([]);
        setReviewRounds(0);

        try {
            // 使用 REST API 启动（避免 WebSocket 长时间连接）
            const res = await BackendAPI.team.start(taskInput);
            if (!res?.success) {
                setAgentLog(prev => [...prev, `❌ 启动失败: ${res?.message || 'unknown'}`]);
                setAgentStatus('failed');
                return;
            }
            const id = res.run_id;
            setRunId(id);
            setAgentLog(prev => [...prev, `✅ 团队已启动 (ID: ${id})`]);

            // 轮询状态
            let done = false;
            while (!done) {
                await new Promise(r => setTimeout(r, 3000));
                try {
                    const statusRes = await BackendAPI.team.status(id);
                    if (!statusRes) { done = true; break; }
                    setAgentProgress(statusRes.progress || 0);
                    setCurrentAgent(statusRes.current_agent || '');
                    if (statusRes.tasks) setTaskList(statusRes.tasks);
                    if (statusRes.review_rounds) setReviewRounds(statusRes.review_rounds);

                    setAgentLog(prev => {
                        const newLog = [...prev];
                        if (statusRes.status === 'decomposing' && !prev.some(l => l.includes('📋')))
                            newLog.push('📋 任务分解中...');
                        if (statusRes.current_agent && !prev.some(l => l.includes(statusRes.current_agent)))
                            newLog.push(`🤖 ${statusRes.current_agent} 执行中...`);
                        if (statusRes.status === 'reviewing' && !prev.some(l => l.includes('🔍')))
                            newLog.push('🔍 QA 审查中...');
                        if (statusRes.status === 'delivering' && !prev.some(l => l.includes('🚀')))
                            newLog.push('🚀 生成交付成果...');
                        return newLog;
                    });

                    if (statusRes.status === 'done' || statusRes.status === 'failed') {
                        done = true;
                        const finalStatus = statusRes.status === 'done' ? 'done' : 'failed';
                        setAgentStatus(finalStatus);
                        const successCount = statusRes.success_count || 0;
                        const totalCount = statusRes.total_tasks || 0;
                        setAgentLog(prev => [...prev,
                        finalStatus === 'done'
                            ? `✅ 团队执行完成！${successCount}/${totalCount} 任务成功，${reviewRounds} 轮审查`
                            : `❌ 执行失败`
                        ]);
                    }
                } catch {
                    setAgentLog(prev => [...prev, '⚠️ 状态查询超时，继续等待...']);
                }
            }
        } catch (e: any) {
            setAgentLog(prev => [...prev, `❌ 错误: ${e.message || e}`]);
            setAgentStatus('failed');
        }
    };

    // ── AI Agent View ──
    const renderAgentView = () => (
        <div className="team-panel">
            <div className="team-panel-header" style={{ padding: '8px 10px' }}>
                <span style={{ fontSize: 14, fontWeight: 600 }}>🤖 AI Agent 团队</span>
            </div>

            <div style={{ padding: '8px 10px' }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
                    输入任务描述，AI Agent 团队自动完成开发、测试、部署
                </div>
                <textarea className="team-input team-textarea"
                    value={taskInput} onChange={e => setTaskInput(e.target.value)}
                    placeholder="例如: 帮我开发一个股票行情查询Web应用"
                    rows={3} disabled={agentStatus === 'running'} />
                <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
                    <button className="team-btn team-btn-primary"
                        onClick={handleStartTask}
                        disabled={agentStatus === 'running' || !taskInput.trim()}>
                        {agentStatus === 'running' ? '⏳ 执行中...' : '🚀 启动 Agent 团队'}
                    </button>
                    {agentStatus === 'done' || agentStatus === 'failed' ? (
                        <button className="team-btn" onClick={() => { setAgentStatus('idle'); setAgentLog([]); setAgentProgress(0); }}>
                            🔄 重置
                        </button>
                    ) : null}
                </div>
            </div>

            {/* Progress bar */}
            {agentStatus === 'running' && (
                <div style={{ padding: '0 10px', marginBottom: 4 }}>
                    <div style={{ height: 4, background: 'var(--bg-tertiary)', borderRadius: 2, overflow: 'hidden' }}>
                        <div style={{
                            height: '100%', width: agentProgress + '%',
                            background: 'var(--accent-blue)', borderRadius: 2,
                            transition: 'width 0.5s ease'
                        }} />
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                        {agentProgress}% {currentAgent ? `- ${currentAgent}` : ''}
                    </div>
                </div>
            )}

            {/* Task list */}
            {taskList.length > 0 && (
                <div style={{ padding: '0 10px', marginBottom: 4 }}>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 2 }}>任务列表:</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
                        {taskList.map((t: any, i: number) => (
                            <span key={i} style={{
                                fontSize: 10, padding: '1px 6px', borderRadius: 3,
                                background: t.status === 'done' ? 'rgba(46,160,67,0.15)' :
                                    t.status === 'failed' ? 'rgba(220,53,69,0.15)' : 'var(--bg-tertiary)',
                                color: t.status === 'done' ? '#3fb950' :
                                    t.status === 'failed' ? '#e06c75' : 'var(--text-muted)',
                            }}>
                                {t.status === 'done' ? '✅' : t.status === 'failed' ? '❌' : '⏳'} {t.title}
                            </span>
                        ))}
                    </div>
                </div>
            )}

            {/* Log output */}
            <div className="git-changes" style={{ maxHeight: 300, overflow: 'auto' }}>
                {agentLog.length === 0 && <div className="git-placeholder">输入任务并启动 Agent 团队</div>}
                {agentLog.map((line, i) => (
                    <div key={i} style={{ fontSize: 11, padding: '2px 10px', color: 'var(--text-secondary)' }}>
                        {line}
                    </div>
                ))}
                <div ref={logEndRef} />
            </div>
        </div>
    );

    // ── Collaboration functions (existing) ──
    const send = useCallback((subcommand: string, extra: any = {}) => {
        if (!wsClient) return;
        wsClient.sendJson({ type: 'team_ws', subcommand, ...extra });
    }, [wsClient]);

    useEffect(() => {
        if (!wsClient) return;
        const unsub = wsClient.onMessage((msg: WSMessage) => {
            if (msg.type === 'team_ws_result') {
                setWorking(false);
                const sc = msg.subcommand;
                if (sc === 'list') { setWorkspaces(msg.workspaces || []); }
                else if (sc === 'get') { setActiveWs(msg.workspace || null); setCollabTab('members'); }
                else if (sc === 'create' && msg.success) { setStatusMsg(`✅ Created: ${msg.name}`); send('list'); setShowCreate(false); }
                else if (sc === 'join' && msg.success) { setStatusMsg(`✅ Joined`); send('get', { workspace_id: msg.workspace_id }); setShowJoin(false); }
                else if (sc === 'delete' && msg.success) { setStatusMsg('🗑 Deleted'); setActiveWs(null); send('list'); }
                else if (sc === 'members') { setMembers(msg.members || []); }
                else if (sc === 'review_list') { setReviews(msg.reviews || []); }
                else if (sc === 'review_create' && msg.success) { setStatusMsg('✅ Review created'); setShowReviewForm(false); send('review_list', { workspace_id: activeWs?.id }); }
                else if (sc === 'activity') { setActivities(msg.activities || []); }
                else if (!msg.success) { setStatusMsg(`❌ ${msg.error || 'Error'}`); }
                setTimeout(() => setStatusMsg(''), 3000);
            }
        });
        return () => unsub();
    }, [wsClient]);

    useEffect(() => { send('list'); }, []);

    const loadWs = useCallback((ws: Workspace) => {
        setActiveWs(ws);
        send('members', { workspace_id: ws.id });
        send('review_list', { workspace_id: ws.id });
        send('activity', { workspace_id: ws.id });
    }, [send]);

    const handleCreate = useCallback(() => {
        setWorking(true); send('create', { name: newWsName, created_by: newWsUser });
    }, [newWsName, newWsUser, send]);

    const handleJoin = useCallback(() => {
        setWorking(true); send('join', { workspace_id: joinId, display_name: joinName });
    }, [joinId, joinName, send]);

    const handleCreateReview = useCallback(() => {
        if (!activeWs) return;
        setWorking(true);
        send('review_create', {
            workspace_id: activeWs.id, title: reviewTitle,
            description: reviewDesc, file_path: reviewFile,
            code_snippet: reviewCode, requested_by: newWsUser,
        });
    }, [activeWs, reviewTitle, reviewDesc, reviewFile, reviewCode, newWsUser, send]);

    // ── Tab switcher ──
    if (aiTab === 'agent') {
        return (
            <div>
                <div className="git-tabs" style={{ display: 'flex', borderBottom: '1px solid var(--border-color)' }}>
                    <button className="git-tab"
                        style={{
                            flex: 1, padding: '6px 0', fontSize: 10, textTransform: 'uppercase',
                            background: 'transparent', border: 'none',
                            borderBottom: aiTab === 'agent' ? '2px solid var(--accent)' : '2px solid transparent',
                            color: aiTab === 'agent' ? 'var(--text-primary)' : 'var(--text-muted)', cursor: 'pointer'
                        }}
                        onClick={() => setAiTab('agent')}>🤖 AI 团队</button>
                    <button className="git-tab"
                        style={{
                            flex: 1, padding: '6px 0', fontSize: 10, textTransform: 'uppercase',
                            background: 'transparent', border: 'none',
                            borderBottom: aiTab === 'collab' ? '2px solid var(--accent)' : '2px solid transparent',
                            color: aiTab === 'collab' ? 'var(--text-primary)' : 'var(--text-muted)', cursor: 'pointer'
                        }}
                        onClick={() => setAiTab('collab')}>👥 协作</button>
                </div>
                {renderAgentView()}
            </div>
        );
    }

    // ── Collaboration View (existing) ──
    // (unchanged from original)
    if (!activeWs) {
        return (
            <div>
                <div className="git-tabs" style={{ display: 'flex', borderBottom: '1px solid var(--border-color)' }}>
                    <button className="git-tab"
                        style={{
                            flex: 1, padding: '6px 0', fontSize: 10, textTransform: 'uppercase',
                            background: 'transparent', border: 'none',
                            borderBottom: aiTab === 'agent' ? '2px solid var(--accent)' : '2px solid transparent',
                            color: aiTab === 'agent' ? 'var(--text-primary)' : 'var(--text-muted)', cursor: 'pointer'
                        }}
                        onClick={() => setAiTab('agent')}>🤖 AI 团队</button>
                    <button className="git-tab"
                        style={{
                            flex: 1, padding: '6px 0', fontSize: 10, textTransform: 'uppercase',
                            background: 'transparent', border: 'none',
                            borderBottom: aiTab === 'collab' ? '2px solid var(--accent)' : '2px solid transparent',
                            color: aiTab === 'collab' ? 'var(--text-primary)' : 'var(--text-muted)', cursor: 'pointer'
                        }}
                        onClick={() => setAiTab('collab')}>👥 协作</button>
                </div>
                <div className="team-panel">
                    <div className="team-panel-header"><h3>👥 团队工作区</h3></div>
                    <div className="team-panel-actions">
                        <button className="team-btn team-btn-primary" onClick={() => setShowCreate(true)}>➕ 新建</button>
                        <button className="team-btn" onClick={() => setShowJoin(true)}>🔗 加入</button>
                    </div>
                    {showCreate && (
                        <div className="team-form">
                            <input className="team-input" placeholder="工作区名称" value={newWsName} onChange={e => setNewWsName(e.target.value)} autoFocus />
                            <input className="team-input" placeholder="你的名字" value={newWsUser} onChange={e => setNewWsUser(e.target.value)} />
                            <div className="team-form-actions">
                                <button className="team-btn" onClick={() => setShowCreate(false)}>取消</button>
                                <button className="team-btn team-btn-primary" onClick={handleCreate} disabled={working || !newWsName}>创建</button>
                            </div>
                        </div>
                    )}
                    {showJoin && (
                        <div className="team-form">
                            <input className="team-input" placeholder="工作区 ID" value={joinId} onChange={e => setJoinId(e.target.value)} autoFocus />
                            <input className="team-input" placeholder="你的显示名称" value={joinName} onChange={e => setJoinName(e.target.value)} />
                            <div className="team-form-actions">
                                <button className="team-btn" onClick={() => setShowJoin(false)}>取消</button>
                                <button className="team-btn team-btn-primary" onClick={handleJoin} disabled={working || !joinId}>加入</button>
                            </div>
                        </div>
                    )}
                    {statusMsg && <div className="team-status">{statusMsg}</div>}
                    <div className="team-list">
                        {workspaces.map(ws => (
                            <div key={ws.id} className="team-card" onClick={() => loadWs(ws)}>
                                <div className="team-card-name">📁 {ws.name}</div>
                                <div className="team-card-meta">
                                    <span>ID: {ws.id}</span>
                                    <span>👤 {ws.member_count}</span>
                                </div>
                            </div>
                        ))}
                        {workspaces.length === 0 && <div className="team-empty">还没有工作区，新建一个开始协作</div>}
                    </div>
                </div>
            </div>
        );
    }

    // Workspace detail (unchanged)
    const actionIcons: Record<string, string> = {
        create_workspace: '📁', member_join: '👋', review: '🔍',
        session_share: '🔗', chat: '💬', file_edit: '✏️',
    };
    const statusBadges: Record<string, string> = {
        open: '🟡', approved: '🟢', changes_requested: '🔴', closed: '⚪',
    };

    return (
        <div>
            <div className="git-tabs" style={{ display: 'flex', borderBottom: '1px solid var(--border-color)' }}>
                <button className="git-tab"
                    style={{
                        flex: 1, padding: '6px 0', fontSize: 10, textTransform: 'uppercase',
                        background: 'transparent', border: 'none',
                        borderBottom: aiTab === 'agent' ? '2px solid var(--accent)' : '2px solid transparent',
                        color: aiTab === 'agent' ? 'var(--text-primary)' : 'var(--text-muted)', cursor: 'pointer'
                    }}
                    onClick={() => setAiTab('agent')}>🤖 AI 团队</button>
                <button className="git-tab"
                    style={{
                        flex: 1, padding: '6px 0', fontSize: 10, textTransform: 'uppercase',
                        background: 'transparent', border: 'none',
                        borderBottom: aiTab === 'collab' ? '2px solid var(--accent)' : '2px solid transparent',
                        color: aiTab === 'collab' ? 'var(--text-primary)' : 'var(--text-muted)', cursor: 'pointer'
                    }}
                    onClick={() => setAiTab('collab')}>👥 协作</button>
            </div>
            <div className="team-panel">
                <div className="team-panel-header">
                    <h3>👥 {activeWs.name}</h3>
                    <div className="team-panel-header-actions">
                        <button className="team-btn-team" onClick={() => { setActiveWs(null); send('list'); }}>← 返回</button>
                        <button className="team-btn-team" onClick={() => send('delete', { workspace_id: activeWs.id })} disabled={working}>🗑</button>
                    </div>
                </div>
                <div className="team-tabs">
                    {(['members', 'reviews', 'activity'] as const).map(t => (
                        <button key={t} className={`team-tab ${collabTab === t ? 'active' : ''}`} onClick={() => setCollabTab(t)}>
                            {t === 'members' ? '👤 成员' : t === 'reviews' ? '🔍 审查' : '📋 动态'}
                        </button>
                    ))}
                </div>
                {statusMsg && <div className="team-status">{statusMsg}</div>}
                {collabTab === 'members' && (
                    <div className="team-tab-content">
                        <button className="team-btn team-btn-primary team-btn-sm" onClick={() => {
                            send('share_session', { workspace_id: activeWs.id, session_id: 'active', user_name: newWsUser });
                            setStatusMsg('✅ 会话已共享');
                        }} disabled={working}>🔗 共享当前会话</button>
                        <div className="team-member-list">
                            {members.map(m => (
                                <div key={m.id} className="team-member">
                                    <span className="team-member-name">
                                        {m.role === 'owner' ? '👑' : m.role === 'admin' ? '⭐' : '👤'} {m.display_name}
                                    </span>
                                    <span className="team-member-role">{m.role}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
                {collabTab === 'reviews' && (
                    <div className="team-tab-content">
                        <button className="team-btn team-btn-primary team-btn-sm" onClick={() => setShowReviewForm(true)}>➕ 请求审查</button>
                        {showReviewForm && (
                            <div className="team-form">
                                <input className="team-input" placeholder="审查标题" value={reviewTitle} onChange={e => setReviewTitle(e.target.value)} autoFocus />
                                <input className="team-input" placeholder="文件路径" value={reviewFile} onChange={e => setReviewFile(e.target.value)} />
                                <textarea className="team-input team-textarea" placeholder="描述" value={reviewDesc} onChange={e => setReviewDesc(e.target.value)} rows={2} />
                                <textarea className="team-input team-textarea" placeholder="代码片段" value={reviewCode} onChange={e => setReviewCode(e.target.value)} rows={3} />
                                <div className="team-form-actions">
                                    <button className="team-btn" onClick={() => setShowReviewForm(false)}>取消</button>
                                    <button className="team-btn team-btn-primary" onClick={handleCreateReview} disabled={working || !reviewTitle}>提交审查</button>
                                </div>
                            </div>
                        )}
                        {reviews.length === 0 && <div className="team-empty">还没有审查请求</div>}
                        {reviews.map(r => (
                            <div key={r.id} className="team-review-card">
                                <div className="team-review-header">
                                    <span className="team-review-title">{statusBadges[r.status] || '🟡'} {r.title}</span>
                                    <span className="team-review-status">{r.status}</span>
                                </div>
                                {r.file_path && <div className="team-review-file">📄 {r.file_path}</div>}
                                {r.description && <div className="team-review-desc">{r.description}</div>}
                                {r.comments.length > 0 && (
                                    <details className="team-review-comments">
                                        <summary>💬 {r.comments.length} 条评论</summary>
                                        {r.comments.map((c, i) => (
                                            <div key={i} className="team-review-comment">
                                                <strong>{c.user}</strong>: {c.comment}
                                            </div>
                                        ))}
                                    </details>
                                )}
                            </div>
                        ))}
                    </div>
                )}
                {collabTab === 'activity' && (
                    <div className="team-tab-content">
                        {activities.map(a => (
                            <div key={a.id} className="team-activity">
                                <span className="team-activity-icon">{actionIcons[a.action] || '📌'}</span>
                                <span className="team-activity-text">
                                    <strong>{a.user_name}</strong> {a.detail}
                                </span>
                            </div>
                        ))}
                        {activities.length === 0 && <div className="team-empty">暂无动态</div>}
                    </div>
                )}
            </div>
        </div>
    );
};
