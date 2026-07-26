/**
 * API — Git 操作
 */
import { apiRequest, type SuccessResponse } from './client';
import type { GitStatusResponse } from '../../types';

export const gitApi = {
  status: () => apiRequest<GitStatusResponse>('/api/git/status'),
  log: (limit = 10) => apiRequest<{ commits: string[] }>(`/api/git/log?limit=${limit}`),
  branches: () => apiRequest<{ branches: string[]; current: string }>('/api/git/branches'),
  createBranch: (name: string) =>
    apiRequest<SuccessResponse>('/api/git/branch/create', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),
  switchBranch: (name: string) =>
    apiRequest<SuccessResponse>('/api/git/branch/switch', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),
  deleteBranch: (name: string, force?: boolean) =>
    apiRequest<SuccessResponse>('/api/git/branch/delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, force }),
    }),
  commit: (files?: string[], message?: string) =>
    apiRequest<SuccessResponse>('/api/git/commit', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files, message }),
    }),
  generateMessage: () => apiRequest<{ message: string }>('/api/git/commit/generate-message', { method: 'POST' }),
  push: (remote?: string, branch?: string) =>
    apiRequest<SuccessResponse>('/api/git/push', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ remote, branch }),
    }),
  pull: (remote?: string) =>
    apiRequest<SuccessResponse>('/api/git/pull', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ remote }),
    }),
  stash: (action: string) =>
    apiRequest<SuccessResponse>('/api/git/stash', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    }),
  diff: (file?: string, staged?: boolean) =>
    apiRequest<{ diff: string }>(`/api/git/diff?file=${encodeURIComponent(file || '')}&staged=${staged || false}`),
  blame: (file: string) =>
    apiRequest<{ lines: Array<{ line: number; author: string; date: string }> }>(`/api/git/blame?file=${encodeURIComponent(file)}`),
  stage: (files: string[]) =>
    apiRequest<SuccessResponse>('/api/git/stage', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files }),
    }),
  unstage: (files: string[]) =>
    apiRequest<SuccessResponse>('/api/git/unstage', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files }),
    }),
  discard: (files: string[]) =>
    apiRequest<SuccessResponse>('/api/git/discard', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files }),
    }),
  fileHistory: (file: string, limit = 20) =>
    apiRequest<{ history: Array<{ commit: string; message: string; date: string }> }>(`/api/git/file-history?file=${encodeURIComponent(file)}&limit=${limit}`),
  tags: () => apiRequest<{ tags: string[] }>('/api/git/tags'),
  conflicts: () => apiRequest<{ conflicts: Array<{ file: string; lines: number }> }>('/api/git/conflicts'),
  ignore: (pattern: string) =>
    apiRequest<SuccessResponse>('/api/git/ignore', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pattern }),
    }),
  init: () => apiRequest<SuccessResponse>('/api/git/init', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) }),

  github: {
    authStatus: () => apiRequest<{ authenticated: boolean; username?: string }>('/api/github/auth/status'),
    authClear: () => apiRequest<SuccessResponse>('/api/github/auth', { method: 'DELETE' }),
    repos: () => apiRequest<{ repos: Array<{ name: string; full_name: string }> }>('/api/github/repos'),
  },

  diffApi: {
    generate: (original: string, modified: string) =>
      apiRequest<{ diff: string }>('/api/diff', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ original, modified }),
      }),
  },
};