/** Web Live Preview — embedded iframe + LiveReload for HTML/CSS/JS */
import React, { useState, useRef, useEffect } from 'react';

interface Props {
    defaultUrl?: string;
}

export const WebPreview: React.FC<Props> = ({ defaultUrl = '' }) => {
    const [url, setUrl] = useState(defaultUrl || 'http://localhost:8080');
    const [loading, setLoading] = useState(false);
    const iframeRef = useRef<HTMLIFrameElement>(null);

    const handleNavigate = (newUrl: string) => {
        setUrl(newUrl); setLoading(true);
    };

    const presets = [
        { label: 'localhost:8080', url: 'http://localhost:8080' },
        { label: 'localhost:3000', url: 'http://localhost:3000' },
        { label: 'localhost:5000', url: 'http://localhost:5000' },
    ];

    return (
        <div className="web-preview-container">
            <div className="web-preview-toolbar">
                <input className="wp-url-input" value={url}
                    onChange={e => setUrl(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleNavigate(url)}
                    placeholder="输入 URL 或本地端口..." />
                <button className="wp-btn" onClick={() => handleNavigate(url)}>🔍</button>
                <button className="wp-btn" onClick={() => iframeRef.current?.contentWindow?.location.reload()}>↻</button>
                <span className="wp-sep">|</span>
                {presets.map(p => (
                    <button key={p.url} className="wp-preset" onClick={() => handleNavigate(p.url)}>{p.label}</button>
                ))}
                {loading && <span className="wp-loading">加载中...</span>}
            </div>
            <iframe ref={iframeRef} className="wp-iframe"
                src={url} onLoad={() => setLoading(false)}
                sandbox="allow-scripts allow-same-origin allow-forms allow-popups" />
        </div>
    );
};
