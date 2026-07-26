/**
 * API — 模型管理
 */
import { apiRequest, type SuccessResponse } from './client';
import type { ModelsResponse, ModelInfo } from '../../types';

export const modelApi = {
  list: () => apiRequest<ModelsResponse>('/api/models'),
  select: (modelId: string) =>
    apiRequest<SuccessResponse>('/api/model/select', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: modelId }),
    }),
  current: () =>
    apiRequest<{ success: boolean; model: ModelInfo & { user_selected: boolean }; available_models: ModelInfo[] }>('/api/model/current'),
  setCustomApiBase: (modelId: string, apiBase: string) =>
    apiRequest<SuccessResponse>('/api/model/custom-api-base', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: modelId, api_base: apiBase }),
    }),
  getCustomApiBases: () =>
    apiRequest<{ success: boolean; custom_api_bases: Record<string, string> }>('/api/model/custom-api-bases'),
};