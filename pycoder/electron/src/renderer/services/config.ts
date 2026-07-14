/**
 * 后端地址配置 — 统一获取后端 URL 和 WebSocket URL
 *
 * 所有组件/服务从此处获取地址，而非硬编码。
 * 端口可通过环境变量 PYCODER_BACKEND_PORT 覆盖（默认 8423）。
 */

const DEFAULT_PORT = '8423';
let _cachedBase: string | null = null;

async function getBackendBase(): Promise<string> {
    if (_cachedBase) return _cachedBase;
    try {
        _cachedBase = await window.electronAPI.getBackendUrl();
    } catch {
        _cachedBase = `http://127.0.0.1:${DEFAULT_PORT}`;
    }
    return _cachedBase!;
}

/** 获取后端 HTTP API 基础 URL（如 http://127.0.0.1:8423） */
export async function getApiBase(): Promise<string> {
    return getBackendBase();
}

/** 获取后端 WebSocket URL（如 ws://127.0.0.1:8423/ws/chat） */
export async function getWsUrl(path: string): Promise<string> {
    const base = await getBackendBase();
    return base.replace(/^http/, 'ws') + path;
}

/** 同步获取后端基础 URL（仅当已缓存时可用） */
export function getApiBaseSync(): string {
    return _cachedBase || `http://127.0.0.1:${DEFAULT_PORT}`;
}

/** 获取 API Key（跨页面刷新缓存） */
let _cachedApiKey: string | null = null;
let _apiKeyFetchTime = 0;
const API_KEY_CACHE_TTL = 60000; // 60秒后重新读取

export async function getApiKey(): Promise<string> {
    const now = Date.now();
    // 注意: 空字符串('') 不应被缓存, 否则首次获取失败后会永久返回空 Key
    if (_cachedApiKey !== null && _cachedApiKey !== '' && (now - _apiKeyFetchTime) < API_KEY_CACHE_TTL) {
        return _cachedApiKey;
    }
    try {
        const key = await window.electronAPI.getApiKey();
        _cachedApiKey = key || '';
        _apiKeyFetchTime = now;
    } catch {
        _cachedApiKey = '';
    }
    return _cachedApiKey;
}
