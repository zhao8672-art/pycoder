/**
 * API — 文件操作
 */
import { apiRequest, type SuccessResponse } from './client';
import type { FileEntry } from '../../types';

export const fileApi = {
  list: (dirPath = '.') =>
    apiRequest<{ tree: FileEntry | null }>(`/api/files/list?path=${encodeURIComponent(dirPath)}`),
  read: (filePath: string) =>
    apiRequest<{ content: string; total_length: number }>(`/api/files/read?path=${encodeURIComponent(filePath)}`),
  write: (filePath: string, content: string) =>
    apiRequest<SuccessResponse>('/api/files/write', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: filePath, content }),
    }),
};