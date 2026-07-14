import React, { useRef, useEffect, useState, useCallback } from 'react';
import { useUIStore } from '../stores/uiStore';
import { useChatStore } from '../stores/chatStore';
import '../styles/browser.css';

/**
 * BrowserPanel — 编辑器内嵌浏览器 + AI 分析集成
 * AI 可通过 IPC 读取页面信息、执行 JS、截图，并自动分析问题
 */
export const BrowserPanel: React.FC = () => {
    const containerRef = useRef<HTMLDivElement>(null);
    const [url, setUrl] = useState('https://www.baidu.com');
    const [loading, setLoading] = useState(false);
    const [canGoBack, setCanGoBack] = useState(false);
    const [canGoForward, setCanGoForward] = useState(false);
    const [inspecting, setInspecting] = useState(false);
    const toggleBrowserPanel = useUIStore((s) => s.toggleBrowserPanel);
    const addMessage = useChatStore((s) => s.addMessage);

    useEffect(() => {
        const container = containerRef.current;
        if (!container || container.querySelector('webview')) return;

        const wv = document.createElement('webview');
        wv.setAttribute('src', url);
        wv.setAttribute('allowpopups', '');
        wv.setAttribute('nodeintegration', '');
        container.appendChild(wv);

        const onStop = () => {
            setLoading(false);
            try { setUrl(wv.getURL()); } catch { }
            try { setCanGoBack(wv.canGoBack()); } catch { }
            try { setCanGoForward(wv.canGoForward()); } catch { }
        };
        wv.addEventListener('did-start-loading', () => setLoading(true));
        wv.addEventListener('did-stop-loading', onStop);

        // 注入错误采集脚本
        wv.addEventListener('dom-ready', () => {
            wv.executeJavaScript(`
                window.__pycoderErrors = [];
                window.addEventListener('error', function(e) {
                    window.__pycoderErrors.push({
                        type: 'error', message: e.message,
                        source: e.filename, line: e.lineno, col: e.colno,
                        time: new Date().toISOString()
                    });
                });
                window.addEventListener('unhandledrejection', function(e) {
                    window.__pycoderErrors.push({
                        type: 'unhandledRejection', message: String(e.reason),
                        time: new Date().toISOString()
                    });
                });
                console.log('[PyCoder] 错误采集已就绪');
            `).catch(() => { });
        });

        return () => {
            wv.removeEventListener('did-stop-loading', onStop);
            try { container.removeChild(wv); } catch { }
        };
    }, []);

    const getWv = () => containerRef.current?.querySelector('webview') as any;

    const go = useCallback((t: string) => {
        const wv = getWv();
        if (!wv) return;
        let u = t.trim();
        if (u && !/^https?:\/\//i.test(u)) u = 'https://' + u;
        if (u) { wv.loadURL(u); setUrl(u); }
    }, []);

    const nav = (action: string) => {
        const wv = getWv();
        if (wv) wv[action]?.();
    };

    // ── AI 分析当前页面 ──
    const sendToAI = useCallback(async () => {
        setInspecting(true);
        try {
            const wv = getWv();
            if (!wv) return;

            // 1. 获取页面基本信息
            const pageUrl = wv.getURL();
            const pageTitle = wv.getTitle();

            // 2. 注入检测脚本获取页面详情
            const diagCode = `
                (function() {
                    try {
                        const d = document;
                        const errors = window.__pycoderErrors || [];
                        return JSON.stringify({
                            url: location.href,
                            title: d.title,
                            bodySize: (d.body?.innerHTML||'').length,
                            scripts: Array.from(d.querySelectorAll('script[src]')).map(s=>s.src).filter(Boolean),
                            inlineScripts: d.querySelectorAll('script:not([src])').length,
                            consoleErrors: errors,
                            headings: Array.from(d.querySelectorAll('h1,h2,h3')).slice(0,10).map(h=>({tag:h.tagName,text:h.textContent?.slice(0,60)})),
                            forms: Array.from(d.querySelectorAll('form')).length,
                            images: d.querySelectorAll('img').length,
                            links: Array.from(d.querySelectorAll('a[href]')).length,
                            viewport: d.querySelector('meta[name=viewport]')?.getAttribute('content')||'none',
                            bodyText: (d.body?.innerText||'').slice(0,3000),
                        });
                    } catch(e) { return JSON.stringify({error:e.message}); }
                })()
            `;
            const pageInfo = await wv.executeJavaScript(diagCode);

            // 3. 构建 AI 上下文消息
            const info = JSON.parse(pageInfo);
            const errorSummary = info.consoleErrors?.length
                ? `\n\n⚠️ 检测到 ${info.consoleErrors.length} 个错误:\n` +
                info.consoleErrors.slice(0, 10).map((e: any) =>
                    `  - [${e.type}] ${e.message} (行${e.line})`
                ).join('\n')
                : '\n\n✅ 未检测到 JS 错误';

            // 4. 发送给 AI
            addMessage({
                id: `browser-ctx-${Date.now()}`,
                role: 'user',
                content: `我正在查看网页: **${info.title || '无标题'}**\nURL: ${info.url}\n\n页面分析:\n- 脚本文件: ${info.scripts?.length || 0} 个\n- 内联脚本: ${info.inlineScripts || 0} 个\n- 表单: ${info.forms || 0} 个\n- 图片: ${info.images || 0} 个\n- 链接: ${info.links || 0} 个\n- 页面大小: ${Math.round((info.bodySize || 0) / 1024)}KB\n\n${info.bodyText ? '页面文本摘要:\n' + info.bodyText.slice(0, 2000) + '\n\n...\n\n' : ''}${errorSummary}\n\n请分析这个页面，帮我:\n1. 检查是否有错误或问题\n2. 如果发现错误，给出修复方案\n3. 如果有优化建议，也请提出来`,
                timestamp: Date.now() / 1000,
            });

            setInspecting(false);
        } catch (e: any) {
            setInspecting(false);
            addMessage({
                id: `browser-err-${Date.now()}`,
                role: 'system',
                content: `⚠️ 浏览器分析失败: ${e.message}`,
                timestamp: Date.now() / 1000,
            });
        }
    }, [addMessage]);

    // ── 截图发给 AI ──
    const screenshotToAI = useCallback(async () => {
        setInspecting(true);
        try {
            const api = (window as any).electronAPI;
            if (!api?.browserScreenshot) {
                // 降级：直接传页面信息
                sendToAI();
                return;
            }
            const shot = await api.browserScreenshot();
            if (shot?.success && shot.dataUrl) {
                addMessage({
                    id: `browser-shot-${Date.now()}`,
                    role: 'user',
                    content: `[浏览器截图] 当前页面: ${url}\n请分析截图中的页面布局、样式和可能的问题。`,
                    timestamp: Date.now() / 1000,
                });
                // 同时发送页面分析
                sendToAI();
            }
        } catch {
            sendToAI();
        } finally {
            setInspecting(false);
        }
    }, [url, sendToAI]);

    return (
        <div className="browser-panel-editor">
            <div className="browser-toolbar-inline">
                <button className="browser-btn" onClick={() => nav('goBack')} disabled={!canGoBack}>◀</button>
                <button className="browser-btn" onClick={() => nav('goForward')} disabled={!canGoForward}>▶</button>
                <button className="browser-btn" onClick={() => nav('reload')}>🔄</button>
                <div className="browser-url-bar">
                    {loading && <span className="browser-spinner" />}
                    <input className="browser-url-input" value={url}
                        onChange={e => setUrl(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && go(url)}
                        placeholder="输入网址或搜索..." />
                </div>
                <button className="browser-btn" onClick={() => nav('goHome')}>🏠</button>
                <button className="browser-btn" onClick={sendToAI} disabled={inspecting}
                    title="发送页面信息给AI分析">🤖</button>
                <button className="browser-btn" onClick={screenshotToAI} disabled={inspecting}
                    title="截图+分析发送AI">📸</button>
                <button className="browser-btn browser-close-btn" onClick={toggleBrowserPanel}>✕</button>
            </div>
            <div ref={containerRef} className="browser-webview-host" />
        </div>
    );
};
