/**
 * 拖拽文件上传组件 — 支持从本地拖拽文件到工作区
 */
import React, { useState, useRef, useCallback } from 'react';
import { BackendAPI } from '../services/backend';
import { useAppStore } from '../stores/appStore';

interface UploadedFile {
    name: string;
    size: number;
    progress: number;
    status: 'uploading' | 'done' | 'error';
    error?: string;
}

export const DropZone: React.FC = () => {
    const [isDragging, setIsDragging] = useState(false);
    const [uploads, setUploads] = useState<UploadedFile[]>([]);
    const [targetDir, setTargetDir] = useState('');
    const fileInputRef = useRef<HTMLInputElement>(null);
    const { projectRoot } = useAppStore();

    const handleDragOver = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(true);
    }, []);

    const handleDragLeave = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(false);
    }, []);

    const uploadFiles = async (files: FileList) => {
        const newUploads: UploadedFile[] = Array.from(files).map(f => ({
            name: f.name,
            size: f.size,
            progress: 0,
            status: 'uploading' as const,
        }));
        setUploads(prev => [...prev, ...newUploads]);

        for (const file of Array.from(files)) {
            try {
                const result = await BackendAPI.upload.upload(file, targetDir);
                setUploads(prev =>
                    prev.map(u => u.name === file.name
                        ? { ...u, status: result?.success ? 'done' : 'error', progress: 100, error: result?.error }
                        : u
                    )
                );
            } catch (e) {
                setUploads(prev =>
                    prev.map(u => u.name === file.name
                        ? { ...u, status: 'error' as const, progress: 0, error: String(e) }
                        : u
                    )
                );
            }
        }
    };

    const handleDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(false);
        if (e.dataTransfer.files.length > 0) {
            uploadFiles(e.dataTransfer.files);
        }
    }, [targetDir]);

    const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files?.length) {
            uploadFiles(e.target.files);
        }
    };

    const formatSize = (bytes: number) => {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    };

    const clearUploads = () => setUploads([]);

    return (
        <div className="dropzone-container">
            <div
                className={`dropzone-area ${isDragging ? 'dragging' : ''}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
            >
                <div className="dropzone-icon">📤</div>
                <div className="dropzone-text">
                    {isDragging ? '松开以添加文件' : '拖拽文件到此处或点击选择文件'}
                </div>
                <div className="dropzone-hint">文件将上传到: {targetDir || projectRoot || '工作区根目录'}</div>

                <div className="dropzone-target">
                    <input
                        className="input-sm"
                        value={targetDir}
                        onChange={e => setTargetDir(e.target.value)}
                        placeholder="目标子目录 (可选)"
                        onClick={e => e.stopPropagation()}
                    />
                </div>

                <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    style={{ display: 'none' }}
                    onChange={handleFileSelect}
                />
            </div>

            {uploads.length > 0 && (
                <div className="dropzone-uploads">
                    <div className="dropzone-uploads-header">
                        <span>上传列表 ({uploads.length})</span>
                        <button className="btn-link" onClick={clearUploads}>清除</button>
                    </div>
                    {uploads.map((f, i) => (
                        <div key={i} className={`dropzone-file ${f.status}`}>
                            <span className="dropzone-file-name">{f.name}</span>
                            <span className="dropzone-file-size">{formatSize(f.size)}</span>
                            {f.status === 'uploading' && <span className="dropzone-progress">⏳</span>}
                            {f.status === 'done' && <span className="dropzone-check">✅</span>}
                            {f.status === 'error' && <span className="dropzone-error" title={f.error}>❌</span>}
                        </div>
                    ))}
                </div>
            )}

            <style>{`
        .dropzone-container { padding: 12px; }
        .dropzone-area {
          border: 2px dashed #567;
          border-radius: 12px;
          padding: 32px 16px;
          text-align: center;
          cursor: pointer;
          transition: all 0.2s;
          background: var(--bg-secondary, #1e1e2e);
        }
        .dropzone-area.dragging {
          border-color: #6cf;
          background: rgba(102, 204, 255, 0.08);
          transform: scale(1.02);
        }
        .dropzone-area:hover { border-color: #9bf; }
        .dropzone-icon { font-size: 36px; margin-bottom: 8px; }
        .dropzone-text { font-size: 14px; color: #ccc; margin-bottom: 4px; }
        .dropzone-hint { font-size: 11px; color: #888; margin-bottom: 12px; }
        .dropzone-target { margin-top: 8px; }
        .dropzone-target .input-sm {
          width: 200px; padding: 4px 8px; border-radius: 4px;
          border: 1px solid #444; background: #1a1a2e; color: #ddd; font-size: 12px;
        }
        .dropzone-uploads { margin-top: 12px; }
        .dropzone-uploads-header {
          display: flex; justify-content: space-between; align-items: center;
          font-size: 12px; color: #999; margin-bottom: 6px;
        }
        .btn-link { background: none; border: none; color: #6cf; cursor: pointer; font-size: 12px; }
        .btn-link:hover { color: #9bf; }
        .dropzone-file {
          display: flex; align-items: center; gap: 8px;
          padding: 6px 8px; border-radius: 4px; font-size: 12px;
          background: var(--bg-primary, #16162a);
          margin-bottom: 4px;
        }
        .dropzone-file.done { border-left: 3px solid #4c6; }
        .dropzone-file.error { border-left: 3px solid #f66; }
        .dropzone-file-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #ddd; }
        .dropzone-file-size { color: #888; min-width: 60px; text-align: right; }
        .dropzone-progress { color: #fc6; }
        .dropzone-check { color: #4c6; }
        .dropzone-error { color: #f66; cursor: help; }
      `}</style>
        </div>
    );
};
