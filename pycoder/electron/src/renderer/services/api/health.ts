/**
 * API — 健康检查
 */
import { apiRequest } from './client';
import type { HealthResponse } from '../../types';

export const healthApi = {
  check: () => apiRequest<HealthResponse>('/api/health'),
};