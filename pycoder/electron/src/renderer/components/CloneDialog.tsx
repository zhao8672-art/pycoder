import React, { useState } from 'react';
import { BackendAPI } from '../services/backend';

interface Props {
    onClose: () => void;
    onCloned: (path: string) => void;
}

export const CloneDialog: React.FC<Props> = ({ onClose, onCloned }) => {
    const [url, setUrl] = useState('');
    const [targetDir, setTargetDir] = useState('');
    const [cloning, setCloning] = useState(false);
    const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

    const handleClone = async () => {
        if (!url.trim()) return;
        setCloning(true);
        setResult(null);
        const res = await BackendAPI.github.clone(url.trim(), targetDir || undefined);
        setCloning(false);
        if (res?.success) {
            setResult({ ok: true, msg: '已克隆到 ' + res.path });
            setTimeout(() => { onCloned(res.path); onClose(); }, 1000);
        } else {
            setResult({ ok: false, msg: res?.error || '克隆失败' });
        }
    };

    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="modal-dialog" onClick={e => e.stopPropagation()}>
                <div className="modal-header">
                    <span>📋 克隆仓库</span>
                    <button className="modal-close" onClick={onClose}>×</button>
                </div>
                <div className="modal-body">
                    <label className="modal-label">仓库地址</label>
                    <input className="settings-input" value={url}
                        onChange={e => setUrl(e.target.value)}
                        placeholder="https://github.com/user/repo.git" />
                    <div className="modal-hint">支持 HTTPS、SSH 及简写格式如 "user/repo"</div>

                    <label className="modal-label">目标目录（可选）</label>
                    <input className="settings-input" value={targetDir}
                        onChange={e => setTargetDir(e.target.value)}
                        placeholder="留空则使用仓库名" />

                    {result && (
                        <div className={result.ok ? 'git-status-msg' : 'modal-error'}>
                            {result.msg}
                        </div>
                    )}

                    <div className="modal-actions">
                        <button className="settings-btn" onClick={onClose}>取消</button>
                        <button className="settings-btn settings-btn-primary"
                            onClick={handleClone} disabled={cloning || !url.trim()}>
                            {cloning ? '克隆中...' : '克隆'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};
