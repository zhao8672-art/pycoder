/**
 * Backend Store — 后端连接状态、WebSocket 客户端管理
 *
 * 从 appStore.ts 兼容层中独立，职责单一。
 */
import { create } from 'zustand';
import type { WSConnectionManager } from '../services/websocket';
import type { BackendStatus } from '../types';

export interface BackendState {
  backendStatus: BackendStatus;
  backendUrl: string;
  wsClient: WSConnectionManager | null;

  setBackendStatus: (status: BackendStatus) => void;
  setBackendUrl: (url: string) => void;
  setWsClient: (client: WSConnectionManager | null) => void;
}

export const useBackendStore = create<BackendState>((set) => ({
  backendStatus: 'stopped' as BackendStatus,
  backendUrl: 'http://127.0.0.1:8423',
  wsClient: null,

  setBackendStatus: (status) => set({ backendStatus: status }),
  setBackendUrl: (url) => set({ backendUrl: url }),
  setWsClient: (client) => set({ wsClient: client }),
}));