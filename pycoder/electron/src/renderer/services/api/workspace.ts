/**
 * API — 工作区管理
 */
import { apiRequest, type SuccessResponse } from './client';
import type {
  WorkspaceResponse, WorkspaceConfig, WorkspaceFolderItem,
  RulesContent, AiContextPrompt, ScaffoldResult, ScaffoldTemplate, EnvResponse,
} from '../../types';

export const workspaceApi = {
  switch: (path: string) =>
    apiRequest<WorkspaceResponse>('/api/files/workspace/switch', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }),
  current: () => apiRequest<WorkspaceResponse>('/api/files/workspace/current'),
  recent: () => apiRequest<{ workspaces: string[] }>('/api/files/workspace/recent'),
  restore: () => apiRequest<WorkspaceResponse>('/api/files/workspace/restore'),
  env: () => apiRequest<EnvResponse>('/api/env'),

  manage: {
    getConfig: () => apiRequest<WorkspaceConfig>('/api/workspace/manage/config'),
    init: (path: string) =>
      apiRequest<{ success: boolean; workspace: string; name: string }>('/api/workspace/manage/init', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      }).catch(() => null),
    saveConfig: () => apiRequest<{ success: boolean; path?: string }>('/api/workspace/manage/save', { method: 'POST' }),
    updateName: (name: string) =>
      apiRequest<{ success: boolean; name: string }>('/api/workspace/manage/config/name', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      }),
    updateDescription: (description: string) =>
      apiRequest<{ success: boolean; description: string }>('/api/workspace/manage/config/description', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description }),
      }),
    listFolders: () => apiRequest<{ folders: WorkspaceFolderItem[] }>('/api/workspace/manage/folders'),
    addFolder: (path: string, name?: string) =>
      apiRequest<{ success: boolean; folder?: WorkspaceFolderItem; error?: string }>('/api/workspace/manage/folders/add', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, name }),
      }),
    removeFolder: (path: string) =>
      apiRequest<{ success: boolean; error?: string }>('/api/workspace/manage/folders/remove', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      }),
    reorderFolders: (paths: string[]) =>
      apiRequest<{ success: boolean; folders?: WorkspaceFolderItem[]; error?: string }>('/api/workspace/manage/folders/reorder', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths }),
      }),
    getRules: () => apiRequest<RulesContent>('/api/workspace/manage/rules'),
    saveRules: (content: string) =>
      apiRequest<{ success: boolean; error?: string }>('/api/workspace/manage/rules', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      }),
    getAiContext: () => apiRequest<AiContextPrompt>('/api/workspace/manage/ai-context'),
    getSettings: () => apiRequest<{ settings: Record<string, unknown> }>('/api/workspace/manage/settings'),
    updateSettings: (settings: Record<string, unknown>) =>
      apiRequest<{ success: boolean; settings?: Record<string, unknown> }>('/api/workspace/manage/settings', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings }),
      }),
    scaffold: (name: string, template: string) =>
      apiRequest<ScaffoldResult>('/api/workspace/manage/scaffold', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, template }),
      }),
    templates: () => apiRequest<{ templates: ScaffoldTemplate[] }>('/api/workspace/manage/templates'),
  },
};