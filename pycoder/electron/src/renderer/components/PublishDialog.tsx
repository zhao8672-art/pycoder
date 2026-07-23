import React, { useState } from 'react';
import { BackendAPI } from '../services/backend';

interface Props {
    onClose: () => void;
    onPublished: (url: string) => void;
}

export const PublishDialog: React.FC<Props> = ({ onClose, onPublished }) => {
    const [repoName, setRepoName] = useState('');
    const [description, setDescription] = useState('');
    const [isPrivate, setIsPrivate] = useState(true);
    const [publishing, setPublishing] = useState(false);
    const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

    const handlePublish = async () => {
        if (!repoName.trim()) return;
        setPublishing(true);
        setResult(null);
        const res = await BackendAPI.github.publish(repoName.trim(), description, isPrivate);
        setPublishing(false);
        if (res?.success) {
            setResult({ ok: true, msg: '发布成功！在 GitHub 中打开: ' + res.repo_url });
            setTimeout(() => { onPublished(res.repo_url); onClose(); }, 1500);
        } else {
            setResult({ ok: false, msg: res?.error || '发布失败' });
        }
    };

    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="modal-dialog" onClick={e => e.stopPropagation()}>
                <div className="modal-header">
                    <span>☁️ 发布到 GitHub</span>
                    <button className="modal-close" onClick={onClose}>×</button>
                </div>
                <div className="modal-body">
                    <label className="modal-label">仓库名称</label>
                    <input className="settings-input" value={repoName}
                        onChange={e => setRepoName(e.target.value)}
                        placeholder="my-awesome-project" />

                    <label className="modal-label">描述（可选）</label>
                    <input className="settings-input" value={description}
                        onChange={e => setDescription(e.target.value)}
                        placeholder="简要描述" />

                    <div className="modal-checkbox">
                        <label>
                            <input type="checkbox" checked={isPrivate}
                                onChange={e => setIsPrivate(e.target.checked)} />
                            {' '}私有仓库
                        </label>
                    </div>

                    <div className="modal-hint">
                        将创建一个新仓库并将代码推送到 GitHub。
                    </div>

                    {result && (
                        <div className={result.ok ? 'git-status-msg' : 'modal-error'}>
                            {result.msg}
                        </div>
                    )}

                    <div className="modal-actions">
                        <button className="settings-btn" onClick={onClose}>取消</button>
                        <button className="settings-btn settings-btn-primary"
                            onClick={handlePublish} disabled={publishing || !repoName.trim()}>
                            {publishing ? '发布中...' : '发布'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};
