/** Image & Screenshot Viewer — inline image preview panel */
import React, { useState } from 'react';

interface Props {
    initialSrc?: string;
}

export const ImageViewer: React.FC<Props> = ({ initialSrc = '' }) => {
    const [src, setSrc] = useState(initialSrc);
    const [zoom, setZoom] = useState(1);
    const [input, setInput] = useState(initialSrc);

    const loadImage = () => {
        setSrc(input);
    };

    return (
        <div className="image-viewer">
            <div className="iv-toolbar">
                <input className="iv-url-input" value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && loadImage()}
                    placeholder="输入图片路径 (支持 file:// 和 http(s)://)" />
                <button className="iv-btn" onClick={loadImage}>加载</button>
                <span className="iv-sep">|</span>
                <button className="iv-btn" onClick={() => setZoom(z => Math.min(z + 0.25, 3))}>🔍+</button>
                <button className="iv-btn" onClick={() => setZoom(z => Math.max(z - 0.25, 0.25))}>🔍-</button>
                <button className="iv-btn" onClick={() => setZoom(1)}>1:1</button>
            </div>
            {src ? (
                <div className="iv-viewport">
                    <img src={src} style={{ transform: `scale(${zoom})`, transformOrigin: 'top left' }}
                        alt="preview" onError={() => { }} />
                </div>
            ) : (
                <div className="iv-empty">拖拽图片到此处或输入路径加载</div>
            )}
        </div>
    );
};
