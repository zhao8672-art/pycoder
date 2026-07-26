/**
 * API — 会话管理
 */
import { apiRequest, type SuccessResponse } from './client';
import type { SessionsListResponse, SessionMessagesResponse, SessionItem } from '../../types';

export const sessionApi = {
  list: () => apiRequest<SessionsListResponse>('/api/sessions'),
  create: (model?: string) =>
    apiRequest<SessionItem>('/api/sessions', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model }),
    }),
  delete: (id: string) => apiRequest<SuccessResponse>(`/api/sessions/${id}`, { method: 'DELETE' }),
  messages: (id: string, limit = 200) =>
    apiRequest<SessionMessagesResponse>(`/api/sessions/${id}/messages?limit=${limit}`),
  batchDelete: (ids: string[]) =>
    apiRequest<SuccessResponse>('/api/sessions/batch-delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_ids: ids }),
    }),
  deleteAll: () => apiRequest<SuccessResponse>('/api/sessions/all', { method: 'DELETE' }),
};