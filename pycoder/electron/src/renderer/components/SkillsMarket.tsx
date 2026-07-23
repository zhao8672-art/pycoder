import React, { useState, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import type { WSConnectionManager } from '../services/websocket';

interface SkillItem {
    id: string;
    name: string;
    description: string;
    author: string;
    stars: number;
    downloads: number;
    category: string;
    tags: string[];
    version: string;
    installed: boolean;
    has_update: boolean;
    rating?: number;
    ratings_count?: number;
    publisher?: string;
    verified?: boolean;
}

interface SkillDetail extends SkillItem {
    reviews?: Array<{ user: string; rating: number; review: string; created_at: string }>;
    created_at?: string;
    updated_at?: string;
    installs?: number;
}

interface Props {
    wsClient: WSConnectionManager | null;
}

const CATEGORY_LABELS: Record<string, string> = {
    'code-quality': '代码质量', 'database': '数据库',
    'devops': 'DevOps', 'getting-started': '入门指南',
    'architecture': '架构', 'security': '安全',
    'other': '其他',
};

export const SkillsMarket: React.FC<Props> = ({ wsClient }) => {
    const [skills, setSkills] = useState<SkillItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [sortBy, setSortBy] = useState('stars');
    const [search, setSearch] = useState('');
    const [statusMsg, setStatusMsg] = useState('');
    const [syncing, setSyncing] = useState(false);
    const [tab, setTab] = useState<'recommended' | 'installed'>('recommended');
    const [detailSkill, setDetailSkill] = useState<SkillDetail | null>(null);
    const [skillReadme, setSkillReadme] = useState<string | null>(null);
    const [readmeLoading, setReadmeLoading] = useState(false);
    const [showPublish, setShowPublish] = useState(false);
    const [updatingAll, setUpdatingAll] = useState(false);

    // Publish form
    const [publishForm, setPublishForm] = useState({
        id: '', name: '', description: '', author: '',
        category: 'other', tags: '', version: '1.0.0', url: '',
    });

    const sendMCP = useCallback((subcommand: string, extra: any = {}) => {
        if (!wsClient) return;
        wsClient.sendJson({
            type: 'mcp_call', tool: 'skills_market',
            args: { subcommand, ...extra },
        });
    }, [wsClient]);

    useEffect(() => {
        if (!wsClient) return;
        const unsub = wsClient.onMessage((msg: any) => {
            if (msg.type === 'mcp_result' && msg.tool === 'skills_market') {
                setLoading(false);
                setUpdatingAll(false);
                const o = msg.output || {};
                if (msg.success && o.skills) {
                    setSkills(o.skills);
                    setStatusMsg(`已加载 ${o.total} 个技能`);
                } else if (msg.success && o.skill_id) {
                    setStatusMsg(`✅ ${o.action === 'uninstalled' ? '已卸载' : o.name || o.skill_id}`);
                    setTimeout(() => fetchSkills(), 500);
                } else if (msg.success && o.updated) {
                    setStatusMsg(`✅ 已更新 ${o.updated.length} 个技能`);
                    setTimeout(() => fetchSkills(), 500);
                } else if (msg.success && o.new_rating) {
                    setStatusMsg(`⭐ 评分: ${o.new_rating}`);
                    setDetailSkill(null);
                } else if (msg.success && o.skill) {
                    setDetailSkill(o.skill);
                    // 异步 fetch README from GitHub
                    const url = o.skill.url || '';
                    if (url && url.includes('github.com')) {
                        setReadmeLoading(true);
                        setSkillReadme(null);
                        const rawUrl = url.replace('github.com', 'raw.githubusercontent.com') + '/main/README.md';
                        fetch(rawUrl)
                            .then(r => r.ok ? r.text() : fetch(url.replace('github.com', 'raw.githubusercontent.com') + '/master/README.md').then(r2 => r2.ok ? r2.text() : ''))
                            .then(text => { setSkillReadme(text || null); setReadmeLoading(false); })
                            .catch(() => { setReadmeLoading(false); });
                    }
                } else if (!msg.success) {
                    setStatusMsg(`❌ ${o.error || msg.error || '错误'}`);
                    setTimeout(() => setStatusMsg(''), 5000);
                }
            }
            if (msg.type === 'mcp_connect_result' || (msg.type === 'mcp_result' && msg.tool === 'skills_update')) {
                setSyncing(false);
                if (msg.success) {
                    setStatusMsg(`✅ 同步成功！`);
                    setTimeout(() => fetchSkills(), 500);
                } else {
                    setStatusMsg(`❌ 同步失败`);
                }
            }
        });
        return () => unsub();
    }, [wsClient]);

    const fetchSkills = useCallback(() => {
        if (!wsClient) return;
        setLoading(true);
        sendMCP('list', { sort_by: sortBy, search, category: '' });
    }, [wsClient, sortBy, search, sendMCP]);

    const handleInstall = useCallback((id: string) => {
        setStatusMsg(`⏳ 安装中...`);
        sendMCP('install', { skill_id: id });
    }, [sendMCP]);

    const handleUninstall = useCallback((id: string) => {
        setStatusMsg(`⏳ 卸载中...`);
        sendMCP('uninstall', { skill_id: id });
    }, [sendMCP]);

    const handleUpdateAll = useCallback(() => {
        setUpdatingAll(true);
        setStatusMsg('⏳ 全部更新中...');
        sendMCP('update_all');
    }, [sendMCP]);

    const handleRate = useCallback((id: string, rating: number, review?: string) => {
        sendMCP('rate', { skill_id: id, rating, review: review || '' });
    }, [sendMCP]);

    const handleDetail = useCallback((id: string) => {
        sendMCP('detail', { skill_id: id });
    }, [sendMCP]);

    const handlePublish = useCallback(() => {
        const tags = publishForm.tags.split(',').map((t: string) => t.trim()).filter(Boolean);
        sendMCP('publish', {
            skill_data: { ...publishForm, tags, downloads: 0, stars: 0 },
        });
        setShowPublish(false);
        setStatusMsg('📦 发布中...');
        setTimeout(() => fetchSkills(), 1000);
    }, [publishForm, sendMCP, fetchSkills]);

    const handleSync = useCallback(() => {
        if (!wsClient) return;
        setSyncing(true);
        setStatusMsg('同步中...');
        wsClient.sendJson({ type: 'mcp_call', tool: 'skills_update', args: {} });
        setTimeout(() => { setSyncing(false); setStatusMsg('同步超时'); fetchSkills(); }, 25000);
    }, [wsClient, fetchSkills]);

    useEffect(() => { fetchSkills(); }, [fetchSkills]);

    const displaySkills = tab === 'installed'
        ? skills.filter((s) => s.installed)
        : skills.filter((s) => !s.installed);

    const installedCount = skills.filter(s => s.installed).length;
    const hasUpdates = skills.some(s => s.installed && s.has_update);

    // Detail View
    if (detailSkill) {
        return (
            <div className="skills-market">
                <div className="skills-market-header"><h3>📖 {detailSkill.name}</h3></div>
                <div className="skills-detail">
                    <p className="skills-card-desc">{detailSkill.description}</p>
                    {/* README */}
                    {readmeLoading && <div className="skills-readme-loading">📖 加载 README...</div>}
                    {skillReadme && (
                        <details className="skills-readme" open>
                            <summary>📖 README</summary>
                            <div className="skills-readme-content">
                                {skillReadme.split('\n').slice(0, 200).map((line, i) => (
                                    <ReactMarkdown key={i}>{line}</ReactMarkdown>
                                ))}
                            </div>
                        </details>
                    )}
                    <div className="skills-detail-meta">
                        <span>👤 {detailSkill.author || detailSkill.publisher || '未知'}</span>
                        <span>⭐ {detailSkill.rating || detailSkill.stars} ({detailSkill.ratings_count || 0})</span>
                        <span>⬇ {detailSkill.downloads}</span>
                        <span>v{detailSkill.version}</span>
                        {detailSkill.verified && <span className="skills-verified">✓ 已验证</span>}
                    </div>
                    {(detailSkill.tags || []).length > 0 && (
                        <div className="skills-detail-tags">
                            {detailSkill.tags.map((t: string) => <span key={t} className="skills-tag">{t}</span>)}
                        </div>
                    )}
                    {/* Reviews */}
                    {detailSkill.reviews && detailSkill.reviews.length > 0 && (
                        <details className="skills-detail-reviews">
                            <summary>💬 评论 ({detailSkill.reviews.length})</summary>
                            {detailSkill.reviews.slice(-5).map((r, i) => (
                                <div key={i} className="skills-review">
                                    <div className="skills-review-header">
                                        <span>{'⭐'.repeat(r.rating)}</span>
                                        <span className="skills-review-user">{r.user}</span>
                                    </div>
                                    {r.review && <p className="skills-review-text">{r.review}</p>}
                                </div>
                            ))}
                        </details>
                    )}
                    {/* Rating */}
                    <div className="skills-detail-rate">
                        <span>评分: </span>
                        {[1, 2, 3, 4, 5].map((n) => (
                            <button key={n} className="skills-star-btn" onClick={() => handleRate(detailSkill.id, n)}>
                                ⭐
                            </button>
                        ))}
                    </div>
                    <button className="skills-btn" onClick={() => setDetailSkill(null)}>← 返回列表</button>
                </div>
            </div>
        );
    }

    // Publish Form
    if (showPublish) {
        return (
            <div className="skills-market">
                <div className="skills-market-header"><h3>📦 发布新 Skill</h3></div>
                <div className="skills-publish-form">
                    {['id', 'name', 'description', 'author', 'url'].map((field) => (
                        <input key={field} className="skills-publish-input" placeholder={field}
                            value={(publishForm as any)[field]}
                            onChange={(e) => setPublishForm({ ...publishForm, [field]: e.target.value })}
                        />
                    ))}
                    <select className="skills-publish-input" value={publishForm.category} aria-label="Skill category"
                        onChange={(e) => setPublishForm({ ...publishForm, category: e.target.value })}>
                        <option value="other">其他</option>
                        <option value="code-quality">代码质量</option>
                        <option value="database">数据库</option>
                        <option value="devops">DevOps</option>
                        <option value="security">安全</option>
                        <option value="architecture">架构</option>
                    </select>
                    <input className="skills-publish-input" placeholder="标签（逗号分隔）" value={publishForm.tags}
                        onChange={(e) => setPublishForm({ ...publishForm, tags: e.target.value })} />
                    <input className="skills-publish-input" placeholder="版本（默认 1.0.0）" value={publishForm.version}
                        onChange={(e) => setPublishForm({ ...publishForm, version: e.target.value })} />
                    <div className="skills-publish-actions">
                        <button className="skills-btn" onClick={() => setShowPublish(false)}>取消</button>
                        <button className="skills-btn skills-btn-install" onClick={handlePublish}
                            disabled={!publishForm.id || !publishForm.name}>发布</button>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="skills-market">
            <div className="skills-market-header">
                <h3>🧩 技能市场</h3>
                <div className="skills-market-actions">
                    <button className="skills-btn skills-btn-publish" onClick={() => setShowPublish(true)} title="发布新技能">📦 发布</button>
                    <button className="skills-btn skills-btn-sync" onClick={handleSync} disabled={syncing}>
                        {syncing ? '⏳...' : '🔄 同步'}
                    </button>
                </div>
            </div>

            <div className="skills-tabs">
                <button className={`skills-tab ${tab === 'recommended' ? 'active' : ''}`} onClick={() => setTab('recommended')}>
                    ⭐ 推荐 ({skills.length - installedCount})
                </button>
                <button className={`skills-tab ${tab === 'installed' ? 'active' : ''}`} onClick={() => setTab('installed')}>
                    ✅ 已安装 ({installedCount})
                </button>
            </div>

            <div className="skills-market-toolbar">
                <input className="skills-search" placeholder="搜索..." value={search}
                    onChange={(e) => setSearch(e.target.value)} />
                <select className="skills-sort" value={sortBy} onChange={(e) => setSortBy(e.target.value)} aria-label="排序">
                    <option value="stars">最多星</option>
                    <option value="downloads">最多下载</option>
                    <option value="name">按名称</option>
                </select>
                {tab === 'installed' && hasUpdates && (
                    <button className="skills-btn skills-btn-update-all" onClick={handleUpdateAll} disabled={updatingAll}>
                        {updatingAll ? '⏳...' : '🔄 全部更新'}
                    </button>
                )}
            </div>

            {statusMsg && <div className="skills-status">{statusMsg}</div>}

            {tab === 'installed' && displaySkills.length === 0 && !loading && (
                <div className="skills-empty">
                    <p>还没有安装任何技能</p>
                    <p className="skills-empty-hint">切换到「推荐」标签页浏览并安装</p>
                </div>
            )}

            <div className="skills-list">
                {displaySkills.map((skill) => (
                    <div key={skill.id} className="skills-card">
                        <div className="skills-card-header skills-card-clickable" onClick={() => handleDetail(skill.id)}>
                            <span className="skills-card-name">
                                {skill.installed ? '✅ ' : ''}{skill.name}
                                {skill.has_update && <span className="skills-update-badge">更新</span>}
                                {skill.verified && <span className="skills-verified-badge">✓</span>}
                            </span>
                            <div className="skills-card-meta">
                                <span className="skills-star">⭐ {skill.rating || skill.stars}</span>
                                <span className="skills-dl">⬇ {skill.downloads}</span>
                                <span className="skills-version">v{skill.version}</span>
                            </div>
                        </div>
                        <div className="skills-card-desc">{skill.description}</div>
                        <div className="skills-card-footer">
                            <span className="skills-tags">
                                {(skill.tags || []).map((t) => <span key={t} className="skills-tag">{t}</span>)}
                            </span>
                            <span className="skills-category">{CATEGORY_LABELS[skill.category] || skill.category}</span>
                            {skill.installed ? (
                                <button className="skills-btn skills-btn-uninstall" onClick={() => handleUninstall(skill.id)}>
                                    🗑 卸载
                                </button>
                            ) : (
                                <button className="skills-btn skills-btn-install" onClick={() => handleInstall(skill.id)}>
                                    + 安装
                                </button>
                            )}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};
