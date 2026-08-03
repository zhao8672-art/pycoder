/** Web Live Preview — F7 实时预览
 *
 * 能力:
 *   - dev-server 探测（/api/preview/detect，Vite/Next/静态 HTML）
 *   - 设备切换（桌面/平板/手机宽度）
 *   - 手动刷新 + 自动刷新（watchdog 监听工作区 → /ws/preview 推送 reload）
 *   - 纯 HTML 项目静态预览（srcDoc 渲染，无需 dev-server）
 */
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { previewApi, type PreviewDetectResult } from '../services/previewApi';
import { WSConnectionManager } from '../services/websocket';

interface Props {
    defaultUrl?: string;
}

type Device = 'desktop' | 'tablet' | 'phone';

/** 设备预设宽度 */
const DEVICE_WIDTHS: Record<Device, string> = {
    desktop: '100%',
    tablet: '768px',
    phone: '375px',
};

const DEVICE_LABELS: Record<Device, string> = {
    desktop: '🖥 桌面',
    tablet: '📱 平板',
    phone: '📱 手机',
};

export const WebPreview: React.FC<Props> = ({ defaultUrl = '' }) => {
    const [url, setUrl] = useState(defaultUrl || 'http://localhost:5173');
    const [loading, setLoading] = useState(false);
    const [device, setDevice] = useState<Device>('desktop');
    const [autoRefresh, setAutoRefresh] = useState(false);
    const [detectInfo, setDetectInfo] = useState<PreviewDetectResult | null>(null);
    const [staticDoc, setStaticDoc] = useState<string | null>(null);
    const [reloadKey, setReloadKey] = useState(0);
    const iframeRef = useRef<HTMLIFrameElement>(null);
    const wsRef = useRef<WSConnectionManager | null>(null);
    // 记录自动刷新是否由本组件开启（卸载时负责停止 watcher）
    const watcherOwnedRef = useRef(false);

    /** 重新加载预览：静态模式重新拉取 HTML，dev-server 模式重载 iframe */
    const doReload = useCallback(() => {
        if (detectInfo?.mode === 'static-html' && detectInfo.entry) {
            previewApi.fetchStatic(detectInfo.entry).then(doc => {
                if (doc !== null) setStaticDoc(doc);
            });
        } else {
            // 通过 key 强制 iframe 重挂载（跨域时 location.reload 不可用）
            setReloadKey(k => k + 1);
            setLoading(true);
        }
    }, [detectInfo]);

    /** 探测 dev-server / 静态 HTML 入口 */
    const runDetect = useCallback(async () => {
        const info = await previewApi.detect();
        if (!info) return;
        setDetectInfo(info);
        if (info.mode === 'dev-server' && info.running && info.url) {
            setUrl(info.url);
            setStaticDoc(null);
            setReloadKey(k => k + 1);
        } else if (info.mode === 'static-html' && info.entry) {
            const doc = await previewApi.fetchStatic(info.entry);
            if (doc !== null) setStaticDoc(doc);
        }
    }, []);

    // 挂载时自动探测一次
    useEffect(() => { runDetect(); }, [runDetect]);

    /** 自动刷新开关：启动/停止后端 watcher + WS 订阅 */
    const toggleAutoRefresh = useCallback(async () => {
        if (autoRefresh) {
            setAutoRefresh(false);
            wsRef.current?.disconnect();
            wsRef.current = null;
            if (watcherOwnedRef.current) {
                watcherOwnedRef.current = false;
                await previewApi.stop();
            }
            return;
        }
        const started = await previewApi.start();
        if (!started?.success) return;
        watcherOwnedRef.current = true;

        const wsUrl = await previewApi.buildWsUrl();
        const ws = new WSConnectionManager(wsUrl);
        ws.onMessage(msg => {
            if (msg.type === 'reload') doReload();
        });
        ws.connect();
        wsRef.current = ws;
        setAutoRefresh(true);
    }, [autoRefresh, doReload]);

    // 卸载时清理 WS 与 watcher
    useEffect(() => () => {
        wsRef.current?.disconnect();
        if (watcherOwnedRef.current) {
            watcherOwnedRef.current = false;
            previewApi.stop();
        }
    }, []);

    const handleNavigate = (newUrl: string) => {
        setStaticDoc(null);
        setUrl(newUrl);
        setReloadKey(k => k + 1);
        setLoading(true);
    };

    const presets = [
        { label: ':5173', url: 'http://localhost:5173' },
        { label: ':3000', url: 'http://localhost:3000' },
        { label: ':8080', url: 'http://localhost:8080' },
    ];

    return (
        <div className="web-preview-container">
            <div className="web-preview-toolbar">
                <input className="wp-url-input" value={url}
                    onChange={e => setUrl(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleNavigate(url)}
                    placeholder="输入 URL 或本地端口..." />
                <button className="wp-btn" title="打开" onClick={() => handleNavigate(url)}>🔍</button>
                <button className="wp-btn" title="刷新" onClick={doReload}>↻</button>
                <button
                    className={`wp-btn wp-toggle ${autoRefresh ? 'wp-toggle-on' : ''}`}
                    title="文件变更时自动刷新"
                    onClick={toggleAutoRefresh}>
                    {autoRefresh ? '⚡自动' : '⚡手动'}
                </button>
                <span className="wp-sep">|</span>
                {(Object.keys(DEVICE_WIDTHS) as Device[]).map(d => (
                    <button key={d}
                        className={`wp-preset wp-device ${device === d ? 'wp-device-on' : ''}`}
                        onClick={() => setDevice(d)}>
                        {DEVICE_LABELS[d]}
                    </button>
                ))}
                <span className="wp-sep">|</span>
                {presets.map(p => (
                    <button key={p.url} className="wp-preset" onClick={() => handleNavigate(p.url)}>{p.label}</button>
                ))}
                <button className="wp-btn" title="探测 dev-server" onClick={runDetect}>🛰</button>
                {detectInfo && (
                    <span className="wp-detect-info" title={detectInfo.url || detectInfo.entry}>
                        {detectInfo.mode === 'dev-server'
                            ? `${detectInfo.framework}${detectInfo.running ? ' ●运行中' : ' ○未运行'}`
                            : detectInfo.mode === 'static-html'
                                ? `静态: ${detectInfo.entry}`
                                : '未检测到项目'}
                    </span>
                )}
                {loading && <span className="wp-loading">加载中...</span>}
            </div>
            <div className="wp-viewport">
                {staticDoc !== null ? (
                    <iframe ref={iframeRef} key={`static-${reloadKey}`}
                        className="wp-iframe" style={{ width: DEVICE_WIDTHS[device] }}
                        srcDoc={staticDoc}
                        onLoad={() => setLoading(false)}
                        sandbox="allow-scripts allow-same-origin allow-forms allow-popups" />
                ) : (
                    <iframe ref={iframeRef} key={reloadKey}
                        className="wp-iframe" style={{ width: DEVICE_WIDTHS[device] }}
                        src={url}
                        onLoad={() => setLoading(false)}
                        sandbox="allow-scripts allow-same-origin allow-forms allow-popups" />
                )}
            </div>
        </div>
    );
};

export default WebPreview;
