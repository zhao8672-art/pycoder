/**
 * API Client — 通用 fetch 封装
 */
import { getApiBase, getApiKey } from '../config';

/** 通用成功响应类型 */
export type SuccessResponse = { success: boolean; error?: string };

/** 通用请求方法 */
export async function apiRequest<T>(path: string, options?: RequestInit): Promise<T | null> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    const base = await getApiBase();
    const apiKey = await getApiKey();
    const headers: Record<string, string> = { ...(options?.headers as Record<string, string> || {}) };
    if (apiKey) {
      headers['X-API-Key'] = apiKey;
    }
    const res = await fetch(`${base}${path}`, {
      ...options,
      headers,
      signal: controller.signal,
    });
    clearTimeout(timeout);
    return await res.json();
  } catch (err) {
    if ((err as Error).name !== 'AbortError') {
      console.error(`[API] ${path} failed:`, err);
    }
    return null;
  }
}