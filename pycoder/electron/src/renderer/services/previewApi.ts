/**
 * F7 实时预览 API — dev-server 探测 / 文件监听 / reload 推送封装
 */
import { apiRequest } from './api/client';
import { getApiBase, getApiKey, getWsUrl } from './config';

/** dev-server / 静态 HTML 探测结果 */
export interface PreviewDetectResult {
    url: string;
    port: number;
    framework: string;
    running: boolean;
    mode: 'dev-server' | 'static-html' | 'none';
    entry: string;
}

/** 预览监听状态 */
export interface PreviewStatus {
    watching: boolean;
    path: string;
    subscribers: number;
    reload_count: number;
    watchdog_available: boolean;
}

export const previewApi = {
    /** 探测工作区 dev-server（Vite/Next 等）或静态 HTML 入口 */
    detect: () => apiRequest<PreviewDetectResult>('/api/preview/detect'),

    /** 启动文件变更监听（path 省略时监听整个工作区） */
    start: (path?: string) =>
        apiRequest<PreviewStatus & { success: boolean }>('/api/preview/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(path ? { path } : {}),
        }),

    /** 停止文件变更监听 */
    stop: () =>
        apiRequest<PreviewStatus & { success: boolean }>('/api/preview/stop', { method: 'POST' }),

    /** 查询监听状态 */
    status: () => apiRequest<PreviewStatus>('/api/preview/status'),

    /** 静态 HTML 模式：读取工作区文件原文（供 iframe srcDoc 使用） */
    fetchStatic: async (path: string): Promise<string | null> => {
        try {
            const base = await getApiBase();
            const apiKey = await getApiKey();
            const res = await fetch(
                `${base}/api/preview/static?path=${encodeURIComponent(path)}`,
                { headers: apiKey ? { 'X-API-Key': apiKey } : {} },
            );
            return res.ok ? await res.text() : null;
        } catch (err) {
            console.error('[previewApi] fetchStatic failed:', err);
            return null;
        }
    },

    /** 构建带鉴权的 reload 推送 WebSocket URL */
    buildWsUrl: async (): Promise<string> => {
        const base = await getWsUrl('/ws/preview');
        const apiKey = await getApiKey();
        return apiKey ? `${base}?api_key=${encodeURIComponent(apiKey)}` : base;
    },
};
