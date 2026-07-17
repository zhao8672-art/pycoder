import { getApiBase, getApiKey } from './config';
import type {
  HealthResponse,
  ModelsResponse,
  EnvResponse,
  SessionsListResponse,
  SessionMessagesResponse,
  SessionItem,
  WorkspaceResponse,
  GitStatusResponse,
  SearchResponse,
  DiffListResponse,
  ExtensionsResponse,
  SkillsResponse,
  CodeExecResponse,
  CloudSyncResponse,
  TeamResponse,
  EvolutionStatsResponse,
  FileEntry,
} from '../types';

async function request<T>(path: string, options?: RequestInit): Promise<T | null> {
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

// 通用成功响应
type SuccessResponse = { success: boolean; error?: string };

export const BackendAPI = {
  health: () => request<HealthResponse>('/api/health'),
  models: () => request<ModelsResponse>('/api/models'),
  model: {
    select: (modelId: string) =>
      request<SuccessResponse>('/api/model/select', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelId }),
      }),
    current: () => request<{ success: boolean; model: ModelInfo & { user_selected: boolean }; available_models: ModelInfo[] }>('/api/model/current'),
    setCustomApiBase: (modelId: string, apiBase: string) =>
      request<SuccessResponse>('/api/model/custom-api-base', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelId, api_base: apiBase }),
      }),
    getCustomApiBases: () => request<{ success: boolean; custom_api_bases: Record<string, string> }>('/api/model/custom-api-bases'),
  },
  env: () => request<EnvResponse>('/api/env'),

  sessions: {
    list: () => request<SessionsListResponse>('/api/sessions'),
    create: (model?: string) => request<SessionItem>('/api/sessions', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model }),
    }),
    delete: (id: string) => request<SuccessResponse>(`/api/sessions/${id}`, { method: 'DELETE' }),
    messages: (id: string, limit = 200) =>
      request<SessionMessagesResponse>(`/api/sessions/${id}/messages?limit=${limit}`),
    batchDelete: (ids: string[]) =>
      request<SuccessResponse>('/api/sessions/batch-delete', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_ids: ids }),
      }),
    deleteAll: () => request<SuccessResponse>('/api/sessions/all', { method: 'DELETE' }),
  },

  workspace: {
    switch: (path: string) =>
      request<WorkspaceResponse>('/api/files/workspace/switch', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      }),
    current: () => request<WorkspaceResponse>('/api/files/workspace/current'),
    recent: () => request<{ workspaces: string[] }>('/api/files/workspace/recent'),
    restore: () => request<WorkspaceResponse>('/api/files/workspace/restore'),
  },

  extensions: {
    search: (q: string, category?: string, limit?: number, offset?: number) => {
      const params = new URLSearchParams();
      if (q) params.set('q', q);
      if (category) params.set('category', category);
      if (limit) params.set('limit', String(limit));
      if (offset) params.set('offset', String(offset));
      return request<ExtensionsResponse>(`/api/extensions/search?${params.toString()}`);
    },
    installed: () => request<ExtensionsResponse>('/api/extensions/installed'),
    recommended: () => request<ExtensionsResponse>('/api/extensions/recommended'),
    install: (id: string) =>
      request<SuccessResponse>('/api/extensions/install', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      }),
    uninstall: (id: string) =>
      request<SuccessResponse>('/api/extensions/uninstall', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      }),
    enable: (id: string) =>
      request<SuccessResponse>('/api/extensions/enable', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      }),
    disable: (id: string) =>
      request<SuccessResponse>('/api/extensions/disable', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      }),
    update: (id: string) =>
      request<SuccessResponse>('/api/extensions/update', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      }),
    details: (id: string) => request<Record<string, unknown>>(`/api/extensions/details/${id}`),
    stats: () => request<Record<string, unknown>>('/api/extensions/stats'),
    activate: (id: string) =>
      request<SuccessResponse>('/api/extensions/activate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      }),
    deactivate: (id: string) =>
      request<SuccessResponse>('/api/extensions/deactivate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      }),
    activateAll: () => request<Record<string, unknown>>('/api/extensions/activate-all', { method: 'POST' }),
    commands: (q = '') => request<Record<string, unknown>>(`/api/extensions/commands?q=${encodeURIComponent(q)}`),
    executeCommand: (id: string, args: unknown[] = [], kwargs: Record<string, unknown> = {}) =>
      request<Record<string, unknown>>('/api/extensions/commands/execute', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, args, kwargs }),
      }),
    scaffold: (id: string, name = '', description = '', author = '') =>
      request<{ success: boolean; id: string; path: string }>('/api/extensions/scaffold', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, name, description, author }),
      }),
    pack: (id: string) =>
      request<{ success: boolean; path: string; size: number }>(`/api/extensions/pack/${id}`, { method: 'POST' }),
    settings: {
      list: (extId?: string) => {
        const params = extId ? `?ext_id=${encodeURIComponent(extId)}` : '';
        return request<{ settings: Array<Record<string, unknown>>; total: number }>(`/api/extensions/settings${params}`);
      },
      set: (key: string, value: unknown) =>
        request<SuccessResponse>('/api/extensions/settings', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key, value }),
        }),
    },
    run: (id: string, func = 'name', args: Record<string, unknown> = {}) =>
      request<Record<string, unknown>>('/api/extensions/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, function: func, args }),
      }),
    verify: (id: string) => request<Record<string, unknown>>(`/api/extensions/verify/${id}`),
  },

  files: {
    list: (dirPath = '.') =>
      request<{ tree: FileEntry | null }>(`/api/files/list?path=${encodeURIComponent(dirPath)}`),
    read: (filePath: string) =>
      request<{ content: string; total_length: number }>(
        `/api/files/read?path=${encodeURIComponent(filePath)}`,
      ),
    write: (filePath: string, content: string) =>
      request<SuccessResponse>('/api/files/write', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: filePath, content }),
      }),
  },

  git: {
    status: () => request<GitStatusResponse>('/api/git/status'),
    log: (limit = 10) => request<{ commits: string[] }>(`/api/git/log?limit=${limit}`),
    branches: () => request<{ branches: string[]; current: string }>('/api/git/branches'),
    createBranch: (name: string) =>
      request<SuccessResponse>('/api/git/branch/create', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      }),
    switchBranch: (name: string) =>
      request<SuccessResponse>('/api/git/branch/switch', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      }),
    deleteBranch: (name: string, force?: boolean) =>
      request<SuccessResponse>('/api/git/branch/delete', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, force }),
      }),
    commit: (files?: string[], message?: string) =>
      request<SuccessResponse>('/api/git/commit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ files, message }),
      }),
    generateMessage: () =>
      request<{ message: string }>('/api/git/commit/generate-message', { method: 'POST' }),
    push: (remote?: string, branch?: string) =>
      request<SuccessResponse>('/api/git/push', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ remote, branch }),
      }),
    pull: (remote?: string) =>
      request<SuccessResponse>('/api/git/pull', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ remote }),
      }),
    stash: (action: string) =>
      request<SuccessResponse>('/api/git/stash', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      }),
    diff: (file?: string, staged?: boolean) =>
      request<{ diff: string }>(
        `/api/git/diff?file=${encodeURIComponent(file || '')}&staged=${staged || false}`,
      ),
    blame: (file: string) =>
      request<{ lines: Array<{ line: number; author: string; date: string }> }>(
        `/api/git/blame?file=${encodeURIComponent(file)}`,
      ),
    stage: (files: string[]) =>
      request<SuccessResponse>('/api/git/stage', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ files }),
      }),
    unstage: (files: string[]) =>
      request<SuccessResponse>('/api/git/unstage', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ files }),
      }),
    discard: (files: string[]) =>
      request<SuccessResponse>('/api/git/discard', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ files }),
      }),
    fileHistory: (file: string, limit = 20) =>
      request<{ history: Array<{ commit: string; message: string; date: string }> }>(
        `/api/git/file-history?file=${encodeURIComponent(file)}&limit=${limit}`,
      ),
    tags: () => request<{ tags: string[] }>('/api/git/tags'),
    conflicts: () =>
      request<{ conflicts: Array<{ file: string; lines: number }> }>('/api/git/conflicts'),
    ignore: (pattern: string) =>
      request<SuccessResponse>('/api/git/ignore', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pattern }),
      }),
    init: () =>
      request<SuccessResponse>('/api/git/init', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      }),
  },

  github: {
    authStatus: () => request<{ authenticated: boolean; username?: string }>('/api/github/auth/status'),
    authClear: () => request<SuccessResponse>('/api/github/auth', { method: 'DELETE' }),
    repos: () => request<{ repos: Array<{ name: string; full_name: string }> }>('/api/github/repos'),
  },

  team: {
    runs: (limit = 10) => request<TeamResponse>(`/api/team/runs?limit=${limit}`),
  },

  diff: {
    generate: (original: string, modified: string) =>
      request<{ diff: string }>('/api/diff', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ original, modified }),
      }),
  },

  search: {
    query: (q: string, opts?: Record<string, unknown>) =>
      request<SearchResponse>('/api/search/query', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q, ...(opts || {}) }),
      }),
    files: (pattern: string) =>
      request<{ files: string[] }>(`/api/search/files?pattern=${encodeURIComponent(pattern)}`),
  },

  config: {
    keys: () =>
      request<{ providers: Record<string, { name: string; configured: boolean; key_preview: string; env_var: string }> }>(
        '/api/config/keys',
      ),
    skills: () => request<SkillsResponse>('/api/skills'),
    permissions: () => request<{ policy: Record<string, string> }>('/api/permissions'),
    updatePermissions: (policy: Record<string, string>) =>
      request<{ success: boolean; policy: Record<string, string> }>('/api/permissions', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(policy),
      }),
    setup: (provider: string, apiKey: string, model?: string) =>
      request<{ success: boolean }>('/api/config/setup', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, api_key: apiKey, model }),
      }),
  },

  context: {
    file: (path: string) =>
      request<{ symbols: Array<{ name: string; kind: string; line: number }> }>(
        `/api/context/file?path=${encodeURIComponent(path)}`,
      ),
    symbols: (q: string) =>
      request<{ symbols: Array<{ name: string; kind: string; file: string; line: number }> }>(
        `/api/context/symbols?q=${encodeURIComponent(q)}`,
      ),
  },

  // ── 新功能 API ──
  codeExec: {
    run: (code: string, timeout = 30, longRunning = false) =>
      request<CodeExecResponse>('/api/code/exec', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, timeout, long_running: longRunning }),
      }),
    config: () => request<{ config: Record<string, unknown> }>('/api/code/exec/config'),
    runMultilang: (language: string, code: string, timeout = 30) =>
      request<{ success: boolean; language: string; stdout: string; stderr: string; error?: string }>(
        '/api/code/exec-multilang',
        {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ language, code, timeout }),
        },
      ),
    languages: () =>
      request<{ languages: Array<{ language: string; ext: string; available: boolean; needs_compile: boolean }>; total: number }>(
        '/api/code/languages',
      ),
  },

  cloud: {
    status: () => request<CloudSyncResponse>('/api/cloud/status'),
    sync: () => request<CloudSyncResponse>('/api/cloud/sync', { method: 'POST' }),
  },

  evolution: {
    stats: () => request<EvolutionStatsResponse>('/api/v2/evolution/stats'),
    tasks: (limit = 20) =>
      request<{ tasks: Array<{ id: string; type: string; status: string }> }>(
        `/api/v2/evolution/tasks?limit=${limit}`,
      ),
    run: (type = 'fix', target = '') =>
      request<{ result: Record<string, unknown> }>('/api/v2/evolution/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type, target }),
      }),
    watch: {
      start: (interval = 300) =>
        request<{ status: string }>('/api/v2/evolution/watch/start', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ interval }),
        }),
      stop: () =>
        request<{ status: string }>('/api/v2/evolution/watch/stop', { method: 'POST' }),
      status: () =>
        request<{ active: boolean; interval: number }>('/api/v2/evolution/watch/status'),
    },
  },

  pipeline: {
    run: (name: string) =>
      request<{ results: Array<{ step: number; success: boolean }> }>('/api/pipeline/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      }),
  },

  scaffold: {
    templates: () => request<{ templates: Array<{ name: string; description: string }> }>(
      '/api/scaffold/templates',
    ),
    generate: (framework: string, name = 'my-project') =>
      request<{ project_dir: string; files_created: number }>('/api/scaffold/generate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ framework, name }),
      }),
  },

  envCapabilities: () =>
    request<{
      capabilities: Record<string, { available: boolean; version: string }>;
    }>('/api/env/capabilities'),

  undo: {
    preview: (file: string, content: string) =>
      request<{ diff: string }>('/api/undo/preview', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file, content }),
      }),
    snapshot: (file: string) =>
      request<SuccessResponse>('/api/undo/snapshot', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file }),
      }),
    undo: (file: string, steps = 1) =>
      request<{ restored_to: string }>('/api/undo/undo', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file, steps }),
      }),
  },
};
