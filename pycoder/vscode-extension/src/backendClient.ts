/**
 * PyCoder Backend Client — REST + WebSocket connection manager
 */

import * as vscode from 'vscode';

export class BackendClient {
    private _baseUrl: string;
    private _ws: WebSocket | null = null;
    private _wsHandlers: Set<(msg: any) => void> = new Set();
    private _status: 'disconnected' | 'connecting' | 'connected' = 'disconnected';
    private _onStatusChange: ((status: string) => void) | null = null;
    private _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private _disposed = false;

    constructor(baseUrl: string) {
        this._baseUrl = baseUrl;
    }

    get baseUrl(): string { return this._baseUrl; }
    get status(): string { return this._status; }

    set onStatusChange(fn: ((status: string) => void) | null) { this._onStatusChange = fn; }

    // ── REST API ──

    async request<T>(path: string, options?: RequestInit): Promise<T | null> {
        try {
            const res = await fetch(`${this._baseUrl}${path}`, {
                ...options,
                signal: AbortSignal.timeout(15000),
            });
            if (!res.ok) return null;
            return await res.json() as T;
        } catch { return null; }
    }

    async healthCheck(): Promise<boolean> {
        const res = await this.request<{ status: string }>('/api/health');
        return res?.status === 'ok';
    }

    async getModels(): Promise<any[]> {
        const res = await this.request<{ models: any[] }>('/api/models');
        return res?.models || [];
    }

    async getEnv(): Promise<any> {
        return await this.request('/api/env');
    }

    // ── WebSocket — Chat ──

    connectWs() {
        if (this._disposed || this._status === 'connected') return;
        this._setStatus('connecting');

        try {
            const url = this._baseUrl.replace(/^http/, 'ws') + '/ws/chat';
            this._ws = new WebSocket(url);

            this._ws.onopen = () => {
                this._setStatus('connected');
                if (this._reconnectTimer) {
                    clearTimeout(this._reconnectTimer);
                    this._reconnectTimer = null;
                }
            };

            this._ws.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    this._wsHandlers.forEach((h) => h(msg));
                } catch { /* ignore non-JSON */ }
            };

            this._ws.onclose = () => {
                this._setStatus('disconnected');
                this._ws = null;
                if (!this._disposed) {
                    this._reconnectTimer = setTimeout(() => this.connectWs(), 5000);
                }
            };

            this._ws.onerror = () => { /* onclose will fire after */ };
        } catch {
            this._setStatus('disconnected');
            if (!this._disposed) {
                this._reconnectTimer = setTimeout(() => this.connectWs(), 5000);
            }
        }
    }

    sendWsMessage(msg: object) {
        if (this._ws?.readyState === WebSocket.OPEN) {
            this._ws.send(JSON.stringify(msg));
        }
    }

    onWsMessage(handler: (msg: any) => void): () => void {
        this._wsHandlers.add(handler);
        return () => this._wsHandlers.delete(handler);
    }

    async sendChatMessage(message: string, model?: string): Promise<void> {
        return new Promise((resolve) => {
            const unsub = this.onWsMessage((msg) => {
                if (msg.type === 'done') {
                    unsub();
                    resolve();
                }
            });
            this.sendWsMessage({ type: 'message', message, model: model || 'auto' });
        });
    }

    // ── Lifecycle ──

    disconnect() {
        this._disposed = true;
        if (this._reconnectTimer) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }
        if (this._ws) {
            this._ws.close();
            this._ws = null;
        }
        this._setStatus('disconnected');
    }

    private _setStatus(status: 'disconnected' | 'connecting' | 'connected') {
        if (this._status !== status) {
            this._status = status;
            this._onStatusChange?.(status);
        }
    }
}
