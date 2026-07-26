/**
 * WorkspacePanel — 工作区管理面板
 *
 * 功能:
 * - 工作区名称/描述编辑
 * - 多根文件夹管理（添加/删除/排序）
 * - AI 规则编辑
 * - 项目脚手架（从模板创建新项目）
 * - 工作区设置查看
 */
import React, { useState, useEffect, useCallback } from 'react';
import { PanelContainer } from './common/PanelContainer';
import { BackendAPI } from '../services/backend';
import type { WorkspaceConfig, WorkspaceFolderItem } from '../types';

type TabKey = 'overview' | 'folders' | 'rules' | 'scaffold';

export const WorkspacePanel: React.FC = () => {
    const [config, setConfig] = useState<WorkspaceConfig | null>(null);
    const [rules, setRules] = useState('');
    const [rulesDirty, setRulesDirty] = useState(false);
    const [activeTab, setActiveTab] = useState<TabKey>('overview');
    const [loading, setLoading] = useState(true);
    const [statusMsg, setStatusMsg] = useState('');
    const [statusType, setStatusType] = useState<'success' | 'error' | 'info'>('info');

    // 脚手架状态
    const [scaffoldName, setScaffoldName] = useState('');
    const [scaffoldTemplate, setScaffoldTemplate] = useState('basic');
    const [templates, setTemplates] = useState<Array<{ id: string; name: string; description: string }>>([]);
    const [scaffolding, setScaffolding] = useState(false);

    // 添加文件夹对话框
    const [showAddFolder, setShowAddFolder] = useState(false);
    const [folderPath, setFolderPath] = useState('');
    const [folderName, setFolderName] = useState('');

    // 编辑名称
    const [editingName, setEditingName] = useState(false);
    const [editingDesc, setEditingDesc] = useState(false);
    const [nameDraft, setNameDraft] = useState('');
    const [descDraft, setDescDraft] = useState('');

    const showStatus = useCallback((msg: string, type: 'success' | 'error' | 'info' = 'info') => {
        setStatusMsg(msg);
        setStatusType(type);
    }, []);

    const loadConfig = useCallback(async () => {
        setLoading(true);
        try {
            const cfg = await BackendAPI.workspace.manage.getConfig();
            if (cfg) {
                setConfig(cfg);
                setNameDraft(cfg.name || '');
                setDescDraft(cfg.description || '');
            }
            const r = await BackendAPI.workspace.manage.getRules();
            if (r) setRules(r.content || '');
            const t = await BackendAPI.workspace.manage.templates();
            if (t) setTemplates(t.templates || []);
        } catch {
            showStatus('加载工作区配置失败', 'error');
        } finally {
            setLoading(false);
        }
    }, [showStatus]);

    useEffect(() => { loadConfig(); }, [loadConfig]);

    // ── 名称/描述编辑 ──────────────────────────────────
    const handleSaveName = async () => {
        if (!config) return;
        const res = await BackendAPI.workspace.manage.updateName(nameDraft);
        if (res?.success) {
            setConfig({ ...config, name: nameDraft });
            setEditingName(false);
            showStatus('名称已更新', 'success');
        } else {
            showStatus('更新名称失败', 'error');
        }
    };

    const handleSaveDesc = async () => {
        if (!config) return;
        const res = await BackendAPI.workspace.manage.updateDescription(descDraft);
        if (res?.success) {
            setConfig({ ...config, description: descDraft });
            setEditingDesc(false);
            showStatus('描述已更新', 'success');
        } else {
            showStatus('更新描述失败', 'error');
        }
    };

    // ── 文件夹管理 ──────────────────────────────────────
    const handleAddFolder = async () => {
        if (!folderPath) return;
        const res = await BackendAPI.workspace.manage.addFolder(folderPath, folderName || undefined);
        if (res?.success) {
            showStatus('文件夹已添加', 'success');
            setShowAddFolder(false);
            setFolderPath('');
            setFolderName('');
            loadConfig();
        } else {
            showStatus(res?.error || '添加失败', 'error');
        }
    };

    const handleRemoveFolder = async (path: string) => {
        const res = await BackendAPI.workspace.manage.removeFolder(path);
        if (res?.success) {
            showStatus('文件夹已移除', 'success');
            loadConfig();
        } else {
            showStatus(res?.error || '移除失败', 'error');
        }
    };

    // ── AI 规则 ─────────────────────────────────────────
    const handleSaveRules = async () => {
        const res = await BackendAPI.workspace.manage.saveRules(rules);
        if (res?.success) {
            setRulesDirty(false);
            showStatus('AI 规则已保存', 'success');
        } else {
            showStatus('保存规则失败', 'error');
        }
    };

    // ── 脚手架 ──────────────────────────────────────────
    const handleScaffold = async () => {
        if (!scaffoldName) return;
        setScaffolding(true);
        const res = await BackendAPI.workspace.manage.scaffold(scaffoldName, scaffoldTemplate);
        if (res?.success) {
            showStatus(`项目 "${scaffoldName}" 创建成功！${res.files ? ` (${res.files.length} 个文件)` : ''}`, 'success');
            setScaffoldName('');
            loadConfig();
        } else {
            showStatus(res?.error || '创建失败', 'error');
        }
        setScaffolding(false);
    };

    // ── 渲染 ────────────────────────────────────────────
    const tabs: Array<{ key: TabKey; label: string; icon: string }> = [
        { key: 'overview', label: '概览', icon: '📋' },
        { key: 'folders', label: '文件夹', icon: '📁' },
        { key: 'rules', label: 'AI 规则', icon: '🤖' },
        { key: 'scaffold', label: '脚手架', icon: '🏗️' },
    ];

    return (
        <PanelContainer
            title={config?.name || '工作区管理'}
            icon="📂"
            loading={loading}
            empty={!config && !loading}
            emptyMessage="无法加载工作区配置"
            statusMsg={statusMsg}
            statusType={statusType}
            toolbar={
                <button className="ws-refresh-btn" onClick={loadConfig} title="刷新">
                    🔄
                </button>
            }
            footer={
                <div className="ws-footer">
                    <span className="ws-version">v{config?.version || '?'}</span>
                    {config?.folders && <span>{config.folders.length} 个文件夹</span>}
                </div>
            }
        >
            {/* ── Tab 导航 ── */}
            <div className="ws-tabs">
                {tabs.map(t => (
                    <button
                        key={t.key}
                        className={`ws-tab ${activeTab === t.key ? 'active' : ''}`}
                        onClick={() => setActiveTab(t.key)}
                    >
                        {t.icon} {t.label}
                    </button>
                ))}
            </div>

            {/* ── 概览 Tab ── */}
            {activeTab === 'overview' && config && (
                <div className="ws-section">
                    <div className="ws-field">
                        <label>名称</label>
                        {editingName ? (
                            <div className="ws-edit-row">
                                <input value={nameDraft} onChange={e => setNameDraft(e.target.value)} className="ws-input" />
                                <button className="ws-btn" onClick={handleSaveName}>💾</button>
                                <button className="ws-btn ws-btn-cancel" onClick={() => setEditingName(false)}>✕</button>
                            </div>
                        ) : (
                            <div className="ws-value-row">
                                <span>{config.name || '(未命名)'}</span>
                                <button className="ws-btn ws-btn-sm" onClick={() => setEditingName(true)}>✏️</button>
                            </div>
                        )}
                    </div>

                    <div className="ws-field">
                        <label>描述</label>
                        {editingDesc ? (
                            <div className="ws-edit-row">
                                <textarea value={descDraft} onChange={e => setDescDraft(e.target.value)} className="ws-textarea" rows={3} />
                                <button className="ws-btn" onClick={handleSaveDesc}>💾</button>
                                <button className="ws-btn ws-btn-cancel" onClick={() => setEditingDesc(false)}>✕</button>
                            </div>
                        ) : (
                            <div className="ws-value-row">
                                <span className="ws-desc">{config.description || '(无描述)'}</span>
                                <button className="ws-btn ws-btn-sm" onClick={() => setEditingDesc(true)}>✏️</button>
                            </div>
                        )}
                    </div>

                    <div className="ws-field">
                        <label>AI 配置</label>
                        <div className="ws-ai-info">
                            {config.ai?.model ? <div>模型: {config.ai.model as string}</div> : null}
                            {config.ai?.temperature ? <div>Temperature: {config.ai.temperature as number}</div> : null}
                            {!config.ai?.model && <div className="ws-muted">未配置（使用默认值）</div>}
                        </div>
                    </div>

                    <div className="ws-field">
                        <label>任务快捷命令</label>
                        <div className="ws-tasks">
                            {config.tasks && Object.keys(config.tasks).length > 0 ? (
                                Object.entries(config.tasks).map(([k, v]) => (
                                    <div key={k} className="ws-task-item">
                                        <code>{k}</code>: {v as string}
                                    </div>
                                ))
                            ) : (
                                <div className="ws-muted">无自定义任务</div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* ── 文件夹 Tab ── */}
            {activeTab === 'folders' && (
                <div className="ws-section">
                    <div className="ws-section-header">
                        <span>根文件夹（{config?.folders?.length || 0}）</span>
                        <button className="ws-btn" onClick={() => setShowAddFolder(true)}>+ 添加</button>
                    </div>

                    {showAddFolder && (
                        <div className="ws-add-folder-form">
                            <input
                                placeholder="文件夹路径 (绝对或相对)"
                                value={folderPath}
                                onChange={e => setFolderPath(e.target.value)}
                                className="ws-input"
                            />
                            <input
                                placeholder="显示名称 (可选)"
                                value={folderName}
                                onChange={e => setFolderName(e.target.value)}
                                className="ws-input"
                            />
                            <div className="ws-form-actions">
                                <button className="ws-btn" onClick={handleAddFolder}>确认添加</button>
                                <button className="ws-btn ws-btn-cancel" onClick={() => { setShowAddFolder(false); setFolderPath(''); setFolderName(''); }}>取消</button>
                            </div>
                        </div>
                    )}

                    <div className="ws-folder-list">
                        {(config?.folders || []).map((f, i) => (
                            <div key={f.path + i} className="ws-folder-item">
                                <span className="ws-folder-icon">📂</span>
                                <div className="ws-folder-info">
                                    <span className="ws-folder-name">{f.name}</span>
                                    <span className="ws-folder-path">{f.path}</span>
                                </div>
                                <button
                                    className="ws-btn ws-btn-sm ws-btn-danger"
                                    onClick={() => handleRemoveFolder(f.path)}
                                    title="移出工作区"
                                >
                                    ✕
                                </button>
                            </div>
                        ))}
                        {(!config?.folders || config.folders.length === 0) && (
                            <div className="ws-muted">暂无根文件夹</div>
                        )}
                    </div>
                </div>
            )}

            {/* ── AI 规则 Tab ── */}
            {activeTab === 'rules' && (
                <div className="ws-section">
                    <p className="ws-hint">
                        定义项目级 AI 行为规则，类似 Cursor 的 .cursorrules。
                        这些规则将在 AI 对话开始时自动注入。
                    </p>
                    <textarea
                        className="ws-rules-editor"
                        value={rules}
                        onChange={e => { setRules(e.target.value); setRulesDirty(true); }}
                        placeholder={`# 项目 AI 规则\n- 语言: Python 3.14\n- 框架: FastAPI\n- 测试: pytest\n- 代码风格: PEP 8`}
                        rows={18}
                    />
                    <div className="ws-form-actions">
                        <button
                            className="ws-btn"
                            onClick={handleSaveRules}
                            disabled={!rulesDirty}
                        >
                            💾 保存规则
                        </button>
                        {rulesDirty && <span className="ws-dirty-badge">有未保存的更改</span>}
                    </div>
                </div>
            )}

            {/* ── 脚手架 Tab ── */}
            {activeTab === 'scaffold' && (
                <div className="ws-section">
                    <p className="ws-hint">从模板快速创建新项目，自动添加到工作区。</p>

                    <div className="ws-field">
                        <label>项目名称</label>
                        <input
                            className="ws-input"
                            value={scaffoldName}
                            onChange={e => setScaffoldName(e.target.value)}
                            placeholder="my-project"
                        />
                    </div>

                    <div className="ws-field">
                        <label>模板</label>
                        <div className="ws-template-list">
                            {templates.map(t => (
                                <label key={t.id} className={`ws-template-option ${scaffoldTemplate === t.id ? 'selected' : ''}`}>
                                    <input
                                        type="radio"
                                        name="template"
                                        value={t.id}
                                        checked={scaffoldTemplate === t.id}
                                        onChange={() => setScaffoldTemplate(t.id)}
                                    />
                                    <span className="ws-template-name">{t.name}</span>
                                    <span className="ws-template-desc">{t.description}</span>
                                </label>
                            ))}
                        </div>
                    </div>

                    <button
                        className="ws-btn ws-btn-primary"
                        onClick={handleScaffold}
                        disabled={!scaffoldName || scaffolding}
                    >
                        {scaffolding ? '⏳ 创建中...' : `🏗️ 创建 "${scaffoldName || '...'}"`}
                    </button>
                </div>
            )}

            <style>{`
        .ws-tabs {
          display: flex; gap: 4px; padding: 8px 12px;
          border-bottom: 1px solid var(--border-color, #e0e0e0);
          background: var(--bg-secondary, #f5f5f5);
        }
        .ws-tab {
          padding: 6px 12px; border: none; border-radius: 4px;
          cursor: pointer; font-size: 13px;
          background: transparent; color: var(--text-secondary, #666);
          transition: all .15s;
        }
        .ws-tab:hover { background: var(--bg-hover, #e8e8e8); }
        .ws-tab.active {
          background: var(--accent-color, #0078d4);
          color: #fff;
        }
        .ws-section {
          padding: 12px;
          display: flex; flex-direction: column; gap: 12px;
        }
        .ws-field {
          display: flex; flex-direction: column; gap: 4px;
        }
        .ws-field label {
          font-size: 12px; font-weight: 600;
          color: var(--text-secondary, #666);
          text-transform: uppercase; letter-spacing: 0.5px;
        }
        .ws-value-row {
          display: flex; align-items: center; gap: 8px;
        }
        .ws-edit-row {
          display: flex; align-items: flex-start; gap: 6px;
        }
        .ws-desc { color: var(--text-secondary, #666); font-size: 13px; }
        .ws-muted { color: var(--text-muted, #999); font-size: 12px; font-style: italic; }
        .ws-input {
          flex: 1; padding: 6px 8px; border: 1px solid var(--border-color, #ddd);
          border-radius: 4px; font-size: 13px;
          background: var(--bg-primary, #fff);
          color: var(--text-primary, #333);
        }
        .ws-textarea {
          flex: 1; padding: 6px 8px; border: 1px solid var(--border-color, #ddd);
          border-radius: 4px; font-size: 13px; resize: vertical;
          font-family: inherit;
          background: var(--bg-primary, #fff);
          color: var(--text-primary, #333);
        }
        .ws-btn {
          padding: 4px 10px; border: 1px solid var(--border-color, #ddd);
          border-radius: 4px; cursor: pointer; font-size: 13px;
          background: var(--bg-primary, #fff);
          color: var(--text-primary, #333);
          transition: all .15s;
          white-space: nowrap;
        }
        .ws-btn:hover { background: var(--bg-hover, #e8e8e8); }
        .ws-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .ws-btn-sm { padding: 2px 6px; font-size: 12px; }
        .ws-btn-cancel { color: #d32; }
        .ws-btn-danger { color: #d32; }
        .ws-btn-primary {
          background: var(--accent-color, #0078d4);
          color: #fff; border-color: var(--accent-color, #0078d4);
          padding: 8px 16px; font-weight: 600;
        }
        .ws-btn-primary:hover { opacity: 0.9; }
        .ws-section-header {
          display: flex; justify-content: space-between; align-items: center;
        }
        .ws-folder-list { display: flex; flex-direction: column; gap: 4px; }
        .ws-folder-item {
          display: flex; align-items: center; gap: 8px;
          padding: 6px 8px; border-radius: 4px;
          background: var(--bg-secondary, #f5f5f5);
        }
        .ws-folder-icon { font-size: 16px; }
        .ws-folder-info {
          flex: 1; display: flex; flex-direction: column; gap: 2px;
        }
        .ws-folder-name { font-size: 13px; font-weight: 500; }
        .ws-folder-path { font-size: 11px; color: var(--text-muted, #999); }
        .ws-add-folder-form {
          display: flex; flex-direction: column; gap: 6px;
          padding: 8px; border: 1px solid var(--border-color, #ddd);
          border-radius: 4px; background: var(--bg-secondary, #f5f5f5);
        }
        .ws-form-actions {
          display: flex; align-items: center; gap: 8px;
        }
        .ws-hint {
          font-size: 12px; color: var(--text-secondary, #666);
          line-height: 1.5; margin: 0;
        }
        .ws-rules-editor {
          width: 100%; padding: 8px;
          border: 1px solid var(--border-color, #ddd);
          border-radius: 4px; font-family: 'Consolas', 'Monaco', monospace;
          font-size: 12px; line-height: 1.6;
          resize: vertical; tab-size: 2;
          background: var(--editor-bg, #1e1e1e);
          color: var(--editor-fg, #d4d4d4);
        }
        .ws-dirty-badge {
          font-size: 11px; color: #f0ad4e; font-weight: 600;
        }
        .ws-ai-info {
          font-size: 13px; display: flex; flex-direction: column; gap: 2px;
        }
        .ws-tasks { display: flex; flex-direction: column; gap: 2px; }
        .ws-task-item {
          font-size: 13px; padding: 2px 0;
        }
        .ws-task-item code {
          background: var(--bg-tertiary, #eee);
          padding: 1px 4px; border-radius: 3px;
          font-family: 'Consolas', monospace; font-size: 12px;
        }
        .ws-template-list {
          display: flex; flex-direction: column; gap: 4px;
        }
        .ws-template-option {
          display: flex; align-items: center; gap: 8px;
          padding: 8px; border: 1px solid var(--border-color, #ddd);
          border-radius: 4px; cursor: pointer;
          transition: all .15s;
        }
        .ws-template-option:hover { background: var(--bg-hover, #e8e8e8); }
        .ws-template-option.selected {
          border-color: var(--accent-color, #0078d4);
          background: color-mix(in srgb, var(--accent-color, #0078d4) 8%, transparent);
        }
        .ws-template-name { font-size: 13px; font-weight: 500; }
        .ws-template-desc {
          font-size: 11px; color: var(--text-muted, #999);
        }
        .ws-footer {
          display: flex; justify-content: space-between; align-items: center;
          padding: 4px 0; font-size: 11px; color: var(--text-muted, #999);
        }
        .ws-version { font-family: 'Consolas', monospace; }
        .ws-refresh-btn {
          background: none; border: none; cursor: pointer;
          font-size: 16px; padding: 2px 4px;
        }
      `}</style>
        </PanelContainer>
    );
};

export default WorkspacePanel;
