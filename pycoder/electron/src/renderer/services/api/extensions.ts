/**
 * API — 扩展管理
 */
import { apiRequest, type SuccessResponse } from './client';
import type { ExtensionsResponse } from '../../types';

export const extensionApi = {
  search: (q: string, category?: string, sort?: string, limit?: number, offset?: number) => {
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (category) params.set('category', category);
    if (sort) params.set('sort', sort);
    if (limit) params.set('limit', String(limit));
    if (offset) params.set('offset', String(offset));
    return apiRequest<ExtensionsResponse>(`/api/extensions/search?${params.toString()}`);
  },
  categories: () => apiRequest<{ categories: string[] }>('/api/extensions/categories'),
  installed: () => apiRequest<ExtensionsResponse>('/api/extensions/installed'),
  recommended: () => apiRequest<ExtensionsResponse>('/api/extensions/recommended'),
  install: (id: string) =>
    apiRequest<SuccessResponse>('/api/extensions/install', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    }),
  installStatus: (taskId: string) =>
    apiRequest<{ task_id: string; ext_id: string; status: string; step: number; progress: number; message: string; error?: string }>(`/api/extensions/install/${taskId}/status`),
  uninstall: (id: string) =>
    apiRequest<SuccessResponse>('/api/extensions/uninstall', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    }),
  enable: (id: string) =>
    apiRequest<SuccessResponse>('/api/extensions/enable', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    }),
  disable: (id: string) =>
    apiRequest<SuccessResponse>('/api/extensions/disable', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    }),
  update: (id: string) =>
    apiRequest<SuccessResponse>('/api/extensions/update', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    }),
  details: (id: string) => apiRequest<Record<string, unknown>>(`/api/extensions/details/${id}`),
  stats: () => apiRequest<Record<string, unknown>>('/api/extensions/stats'),
  activate: (id: string) =>
    apiRequest<SuccessResponse>('/api/extensions/activate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    }),
  deactivate: (id: string) =>
    apiRequest<SuccessResponse>('/api/extensions/deactivate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    }),
  activateAll: () => apiRequest<Record<string, unknown>>('/api/extensions/activate-all', { method: 'POST' }),
  commands: (q = '') => apiRequest<Record<string, unknown>>(`/api/extensions/commands?q=${encodeURIComponent(q)}`),
  executeCommand: (id: string, args: unknown[] = [], kwargs: Record<string, unknown> = {}) =>
    apiRequest<Record<string, unknown>>('/api/extensions/commands/execute', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, args, kwargs }),
    }),
  scaffold: (id: string, name = '', description = '', author = '') =>
    apiRequest<{ success: boolean; id: string; path: string }>('/api/extensions/scaffold', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, name, description, author }),
    }),
  pack: (id: string) =>
    apiRequest<{ success: boolean; path: string; size: number }>(`/api/extensions/pack/${id}`, { method: 'POST' }),
  settings: {
    list: (extId?: string) => {
      const params = extId ? `?ext_id=${encodeURIComponent(extId)}` : '';
      return apiRequest<{ settings: Array<Record<string, unknown>>; total: number }>(`/api/extensions/settings${params}`);
    },
    set: (key: string, value: unknown) =>
      apiRequest<SuccessResponse>('/api/extensions/settings', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, value }),
      }),
  },
  run: (id: string, func = 'name', args: Record<string, unknown> = {}) =>
    apiRequest<Record<string, unknown>>('/api/extensions/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, function: func, args }),
    }),
  verify: (id: string) => apiRequest<Record<string, unknown>>(`/api/extensions/verify/${id}`),
};