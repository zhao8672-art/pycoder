import React, { useState, useEffect, useCallback } from 'react';
import type { WSConnectionManager, WSMessage } from '../services/websocket';

interface CloudUser { id: string; username: string; email: string; plan: string; tokens_used_today: number; tokens_total: number; }
interface Quota { plan: string; daily_limit: number; used_today: number; remaining: number; usage_pct: number; near_limit: boolean; }
interface Plan { name: string; label: string; price: string; daily_tokens: number; max_sessions: number; features: string[]; }

interface Props { wsClient: WSConnectionManager | null; }

export const CloudPanel: React.FC<Props> = ({ wsClient }) => {
    const [tab, setTab] = useState<'login' | 'dashboard'>('login');
    const [token, setToken] = useState(() => localStorage.getItem('pycoder_cloud_token') || '');
    const [user, setUser] = useState<CloudUser | null>(null);
    const [quota, setQuota] = useState<Quota | null>(null);
    const [plans, setPlans] = useState<Plan[]>([]);
    const [usageHistory, setUsageHistory] = useState<any>(null);
    const [statusMsg, setStatusMsg] = useState('');

    // Login form
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [email, setEmail] = useState('');
    const [isRegister, setIsRegister] = useState(false);

    const send = useCallback((subcommand: string, extra: any = {}) => {
        if (!wsClient) return;
        wsClient.sendJson({ type: 'cloud', subcommand, ...extra });
    }, [wsClient]);

    useEffect(() => {
        if (!wsClient) return;
        const unsub = wsClient.onMessage((msg: WSMessage) => {
            if (msg.type === 'cloud_result') {
                const sc = msg.subcommand;
                if ((sc === 'login' || sc === 'register') && msg.success) {
                    setToken(msg.token);
                    localStorage.setItem('pycoder_cloud_token', msg.token);
                    setUser({ id: msg.user_id, username: msg.username, email: msg.email || '', plan: msg.plan || 'free', tokens_used_today: msg.tokens_used_today || 0, tokens_total: msg.tokens_total || 0 });
                    setStatusMsg(`✅ 欢迎, ${msg.username}!`);
                    setTab('dashboard');
                } else if (sc === 'user_info' && msg.success) {
                    setUser(msg.user);
                } else if (sc === 'check_quota' && msg.success) {
                    setQuota(msg);
                } else if (sc === 'usage_history' && msg.success) {
                    setUsageHistory(msg);
                } else if (sc === 'plans') {
                    setPlans(msg.plans || []);
                } else if (sc === 'upgrade' && msg.success) {
                    setStatusMsg(`✅ 已升级到 ${msg.plan}`);
                    send('user_info', { token });
                } else if (!msg.success) {
                    setStatusMsg(`❌ ${msg.error || '错误'}`);
                }
                setTimeout(() => setStatusMsg(''), 4000);
            }
        });
        return () => unsub();
    }, [wsClient, token]);

    // Auto-load if token exists
    useEffect(() => {
        if (token && wsClient) {
            send('user_info', { token });
            send('check_quota', { token });
            send('usage_history', { token });
        }
    }, [token, wsClient]);

    // Load plans
    useEffect(() => {
        if (wsClient) send('plans');
    }, [wsClient]);

    const handleAuth = useCallback(() => {
        if (!wsClient) return;
        if (isRegister) {
            send('register', { username, password, email });
        } else {
            send('login', { username, password });
        }
    }, [wsClient, username, password, email, isRegister, send]);

    const handleLogout = useCallback(() => {
        setToken('');
        setUser(null);
        setQuota(null);
        setUsageHistory(null);
        localStorage.removeItem('pycoder_cloud_token');
        setTab('login');
        setStatusMsg('已退出登录');
    }, []);

    const handleUpgrade = useCallback((plan: string) => {
        send('upgrade', { token, plan });
    }, [token, send]);

    // Login / Register view
    if (tab === 'login' || !token) {
        return (
            <div className="cloud-panel">
                <div className="cloud-header"><h3>☁️ PyCoder Cloud</h3></div>
                <p className="cloud-desc">无需自备 API Key，注册即用</p>

                <div className="cloud-form">
                    <input className="cloud-input" placeholder="用户名" value={username} onChange={e => setUsername(e.target.value)} autoFocus />
                    <input className="cloud-input" type="password" placeholder="密码" value={password} onChange={e => setPassword(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && handleAuth()} />
                    {isRegister && <input className="cloud-input" placeholder="邮箱 (可选)" value={email} onChange={e => setEmail(e.target.value)} />}
                    <button className="cloud-btn cloud-btn-primary" onClick={handleAuth} disabled={!username || !password}>
                        {isRegister ? '📝 注册' : '🔑 登录'}
                    </button>
                    <button className="cloud-btn cloud-btn-link" onClick={() => setIsRegister(!isRegister)}>
                        {isRegister ? '已有账号？登录' : '没有账号？注册'}
                    </button>
                </div>

                {statusMsg && <div className="cloud-status">{statusMsg}</div>}
            </div>
        );
    }

    // Dashboard
    const pct = quota?.usage_pct || 0;
    const nearLimit = quota?.near_limit || false;

    return (
        <div className="cloud-panel">
            <div className="cloud-header">
                <h3>☁️ PyCoder Cloud</h3>
                <button className="cloud-btn cloud-btn-sm" onClick={handleLogout}>退出</button>
            </div>

            {user && (
                <div className="cloud-user-card">
                    <div className="cloud-user-name">👤 {user.username}</div>
                    <div className="cloud-user-plan">
                        {user.plan === 'free' ? '🆓 免费版' : user.plan === 'pro' ? '⭐ 专业版' : '👥 团队版'}
                    </div>
                </div>
            )}

            {quota && (
                <div className="cloud-quota">
                    <div className="cloud-quota-header">
                        <span>📊 今日用量</span>
                        <span>{quota.used_today.toLocaleString()} / {quota.daily_limit.toLocaleString()} tokens</span>
                    </div>
                    <div className="cloud-quota-bar">
                        <div className={`cloud-quota-fill ${nearLimit ? 'cloud-quota-warn' : ''}`}
                            style={{ width: `${Math.min(pct, 100)}%` }} />
                    </div>
                    <div className="cloud-quota-footer">
                        <span>剩余: {quota.remaining.toLocaleString()} tokens</span>
                        <span className={nearLimit ? 'cloud-warning' : ''}>
                            {pct.toFixed(0)}%
                        </span>
                    </div>
                    {nearLimit && <div className="cloud-warning-banner">⚠️ 今日额度即将用尽</div>}
                </div>
            )}

            {statusMsg && <div className="cloud-status">{statusMsg}</div>}

            {/* Usage History */}
            <details className="cloud-details">
                <summary>📈 用量历史 ({usageHistory?.request_count || 0} 次请求)</summary>
                {usageHistory?.by_model && (
                    <div className="cloud-model-breakdown">
                        {Object.entries(usageHistory.by_model).map(([model, tokens]) => (
                            <div key={model} className="cloud-model-row">
                                <span>{model}</span>
                                <span>{(tokens as number).toLocaleString()} tokens</span>
                            </div>
                        ))}
                    </div>
                )}
            </details>

            {/* Plan Upgrade */}
            <details className="cloud-details">
                <summary>💎 升级套餐</summary>
                <div className="cloud-plans">
                    {plans.map(p => (
                        <div key={p.name} className={`cloud-plan-card ${p.name === user?.plan ? 'cloud-plan-active' : ''}`}>
                            <div className="cloud-plan-name">{p.label}</div>
                            <div className="cloud-plan-price">{p.price}</div>
                            <div className="cloud-plan-tokens">每日 {p.daily_tokens.toLocaleString()} tokens</div>
                            <ul className="cloud-plan-features">
                                {p.features.map((f, i) => <li key={i}>{f}</li>)}
                            </ul>
                            {p.name !== user?.plan && (
                                <button className="cloud-btn cloud-btn-primary cloud-btn-sm" onClick={() => handleUpgrade(p.name)}>
                                    升级
                                </button>
                            )}
                            {p.name === user?.plan && <span className="cloud-plan-current">当前套餐</span>}
                        </div>
                    ))}
                </div>
            </details>
        </div>
    );
};
