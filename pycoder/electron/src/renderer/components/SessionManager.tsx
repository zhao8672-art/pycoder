/**
 * SessionManager — 会话管理弹出层子组件
 */
import React from 'react';

interface SessionItem {
    id: string;
    model?: string;
    title?: string;
    updated_at?: number;
}

interface Props {
    visible: boolean;
    sessions: SessionItem[];
    activeSessionId: string | null;
    selectedSessions: Set<string>;
    showDeleteConfirm: boolean;
    deleteMode: 'selected' | 'all';
    onClose: () => void;
    onSelect: (id: string) => void;
    onNewSession: () => void;
    onToggleSelect: (id: string) => void;
    onBatchDelete: () => void;
    onDeleteModeChange: (mode: 'selected' | 'all') => void;
    onDeleteConfirm: () => void;
    onDeleteCancel: () => void;
}

export const SessionManager: React.FC<Props> = ({
    visible, sessions, activeSessionId, selectedSessions,
    showDeleteConfirm, deleteMode,
    onClose, onSelect, onNewSession, onToggleSelect,
    onBatchDelete, onDeleteModeChange, onDeleteConfirm, onDeleteCancel,
}) => {
    if (!visible) return null;

    return (
        <div className="session-manager-overlay" onClick={onClose}>
            <div className="session-manager" onClick={(e) => e.stopPropagation()}>
                <div className="session-manager-header">
                    <h3>{'会话管理'}</h3>
                    <button className="session-close-btn" onClick={onClose}>{'\u2715'}</button>
                </div>

                <div className="session-manager-actions">
                    <button className="session-action-btn primary" onClick={onNewSession}>
                        {'\u2795 新建会话'}
                    </button>
                    {selectedSessions.size > 0 && (
                        <button className="session-action-btn danger" onClick={onBatchDelete}>
                            {'\u{1F5D1} 删除选中 ('}{selectedSessions.size}{')'}
                        </button>
                    )}
                </div>

                <div className="session-list">
                    {sessions.length === 0 && (
                        <p className="session-empty">{'暂无会话记录'}</p>
                    )}
                    {sessions.map((s) => (
                        <div
                            key={s.id}
                            className={`session-item ${s.id === activeSessionId ? 'active' : ''}`}
                            onClick={() => onSelect(s.id)}
                        >
                            <input
                                type="checkbox"
                                className="session-checkbox"
                                checked={selectedSessions.has(s.id)}
                                onClick={(e) => e.stopPropagation()}
                                onChange={() => onToggleSelect(s.id)}
                            />
                            <div className="session-info">
                                <span className="session-title">
                                    {s.title || `会话 ${s.id.slice(0, 8)}`}
                                </span>
                                <span className="session-meta">
                                    {s.model || 'auto'}
                                    {s.updated_at ? ` \u00B7 ${new Date(s.updated_at * 1000).toLocaleDateString()}` : ''}
                                </span>
                            </div>
                        </div>
                    ))}
                </div>

                {showDeleteConfirm && (
                    <div className="delete-confirm">
                        <p>{'确定要删除选中的会话吗？此操作不可撤销。'}</p>
                        <div className="delete-options">
                            <label>
                                <input
                                    type="radio"
                                    checked={deleteMode === 'selected'}
                                    onChange={() => onDeleteModeChange('selected')}
                                />
                                {'删除选中 ('}{selectedSessions.size}{')'}
                            </label>
                            <label>
                                <input
                                    type="radio"
                                    checked={deleteMode === 'all'}
                                    onChange={() => onDeleteModeChange('all')}
                                />
                                {'删除全部'}
                            </label>
                        </div>
                        <div className="delete-actions">
                            <button className="btn-cancel" onClick={onDeleteCancel}>{'取消'}</button>
                            <button className="btn-danger" onClick={onDeleteConfirm}>{'确认删除'}</button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
