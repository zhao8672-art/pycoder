/**
 * API — 杂项（搜索、配置、执行、云同步、进化、团队等）
 */
import { apiRequest, type SuccessResponse } from './client';
import type {
  SearchResponse, SkillsResponse, CodeExecResponse,
  CloudSyncResponse, TeamResponse, EvolutionStatsResponse,
} from '../../types';

export const searchApi = {
  query: (q: string, opts?: Record<string, unknown>) =>
    apiRequest<SearchResponse>('/api/search/query', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: q, ...(opts || {}) }),
    }),
  files: (pattern: string) =>
    apiRequest<{ files: string[] }>(`/api/search/files?pattern=${encodeURIComponent(pattern)}`),
};

export const configApi = {
  keys: () =>
    apiRequest<{ providers: Record<string, { name: string; configured: boolean; key_preview: string; env_var: string }> }>('/api/config/keys'),
  skills: () => apiRequest<SkillsResponse>('/api/skills'),
  permissions: () => apiRequest<{ policy: Record<string, string> }>('/api/permissions'),
  updatePermissions: (policy: Record<string, string>) =>
    apiRequest<{ success: boolean; policy: Record<string, string> }>('/api/permissions', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(policy),
    }),
  setup: (provider: string, apiKey: string, model?: string) =>
    apiRequest<{ success: boolean }>('/api/config/setup', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, api_key: apiKey, model }),
    }),
  /** 一键配置：自动验证 + 保存 + 设默认模型 */
  quickSetup: (provider: string, apiKey: string) =>
    apiRequest<{
      success: boolean;
      error?: string;
      register_url?: string;
      tried?: string[];
      supported?: string[];
      provider?: string;
      provider_name?: string;
      model_id?: string;
      model_name?: string;
      message?: string;
      saved?: boolean;
    }>('/api/config/quick-setup', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, api_key: apiKey }),
    }),
  /** 验证 API Key（不保存） */
  validateKey: (provider: string, apiKey: string) =>
    apiRequest<{ success: boolean; provider: string }>('/api/config/validate-key', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, api_key: apiKey }),
    }),
};

export const contextApi = {
  file: (path: string) =>
    apiRequest<{ symbols: Array<{ name: string; kind: string; line: number }> }>(`/api/context/file?path=${encodeURIComponent(path)}`),
  symbols: (q: string) =>
    apiRequest<{ symbols: Array<{ name: string; kind: string; file: string; line: number }> }>(`/api/context/symbols?q=${encodeURIComponent(q)}`),
};

export const codeExecApi = {
  run: (code: string, timeout = 30, longRunning = false) =>
    apiRequest<CodeExecResponse>('/api/code/exec', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, timeout, long_running: longRunning }),
    }),
  config: () => apiRequest<{ config: Record<string, unknown> }>('/api/code/exec/config'),
  runMultilang: (language: string, code: string, timeout = 30) =>
    apiRequest<{ success: boolean; language: string; stdout: string; stderr: string; error?: string }>('/api/code/exec-multilang', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language, code, timeout }),
    }),
  languages: () =>
    apiRequest<{ languages: Array<{ language: string; ext: string; available: boolean; needs_compile: boolean }>; total: number }>('/api/code/languages'),
};

export const cloudApi = {
  status: () => apiRequest<CloudSyncResponse>('/api/cloud/status'),
  sync: () => apiRequest<CloudSyncResponse>('/api/cloud/sync', { method: 'POST' }),
};

export const evolutionApi = {
  stats: () => apiRequest<EvolutionStatsResponse>('/api/v2/evolution/stats'),
  tasks: (limit = 20) =>
    apiRequest<{ tasks: Array<{ id: string; type: string; status: string }> }>(`/api/v2/evolution/tasks?limit=${limit}`),
  run: (type = 'fix', target = '') =>
    apiRequest<{ result: Record<string, unknown> }>('/api/v2/evolution/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, target }),
    }),
  watch: {
    start: (interval = 300) =>
      apiRequest<{ status: string }>('/api/v2/evolution/watch/start', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ interval }),
      }),
    stop: () => apiRequest<{ status: string }>('/api/v2/evolution/watch/stop', { method: 'POST' }),
    status: () => apiRequest<{ active: boolean; interval: number }>('/api/v2/evolution/watch/status'),
  },
};

export const pipelineApi = {
  run: (name: string) =>
    apiRequest<{ results: Array<{ step: number; success: boolean }> }>('/api/pipeline/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),
};

export const scaffoldApi = {
  templates: () => apiRequest<{ templates: Array<{ name: string; description: string }> }>('/api/scaffold/templates'),
  generate: (framework: string, name = 'my-project') =>
    apiRequest<{ project_dir: string; files_created: number }>('/api/scaffold/generate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ framework, name }),
    }),
};

export const teamApi = {
  runs: (limit = 10) => apiRequest<TeamResponse>(`/api/team/runs?limit=${limit}`),
  start: (task: string) =>
    apiRequest<{ success: boolean; run_id?: string; message?: string }>('/api/team/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task }),
    }),
  status: (runId: string) =>
    apiRequest<{ id: string; status: string; progress: number; current_agent?: string }>(`/api/team/status/${runId}`),
};

export const undoApi = {
  preview: (file: string, content: string) =>
    apiRequest<{ diff: string }>('/api/undo/preview', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file, content }),
    }),
  snapshot: (file: string) =>
    apiRequest<SuccessResponse>('/api/undo/snapshot', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file }),
    }),
  undo: (file: string, steps = 1) =>
    apiRequest<{ restored_to: string }>('/api/undo/undo', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file, steps }),
    }),
};

export const envApi = {
  capabilities: () =>
    apiRequest<{ capabilities: Record<string, { available: boolean; version: string }> }>('/api/env/capabilities'),
};