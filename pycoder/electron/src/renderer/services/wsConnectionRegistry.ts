/**
 * WSConnectionRegistry — WebSocket 连接生命周期管理单例
 *
 * 替代 App.tsx 中的模块顶层 IIFE 初始化方式，
 * 提供可靠的异步初始化、连接状态可观测性和 React 生命周期对齐。
 */
import { WSConnectionManager } from './websocket';
import { getWsUrl, getApiKey } from './config';
import { useBackendStore } from '../stores/backendStore';

export class WSConnectionRegistry {
  private static instance: WSConnectionManager | null = null;
  private static initPromise: Promise<WSConnectionManager> | null = null;
  private static initialized = false;

  /** 获取或初始化 WebSocket 连接管理器 */
  static async getInstance(): Promise<WSConnectionManager> {
    if (this.instance) return this.instance;

    if (!this.initPromise) {
      this.initPromise = this.initialize();
    }
    return this.initPromise;
  }

  /** 同步获取当前实例（可能为 null） */
  static getInstanceSync(): WSConnectionManager | null {
    return this.instance;
  }

  private static async initialize(): Promise<WSConnectionManager> {
    const [url, apiKey] = await Promise.all([getWsUrl('/ws/chat/v2'), getApiKey()]);
    const wsUrl = apiKey ? `${url}?api_key=${encodeURIComponent(apiKey)}` : url;

    const client = new WSConnectionManager(wsUrl);

    // 认证失败时重新获取 api_key 并重建连接
    client.onAuthFail = async () => {
      console.warn('[WS] 认证失败，尝试重新获取 API Key...');
      const freshKey = await getApiKey();
      if (freshKey) {
        const newUrl = `${url}?api_key=${encodeURIComponent(freshKey)}`;
        const newClient = new WSConnectionManager(newUrl);
        newClient.onAuthFail = client.onAuthFail;
        newClient.connect();
        WSConnectionRegistry.instance = newClient;
        useBackendStore.getState().setWsClient(newClient);
      } else {
        client.connect();
      }
    };

    client.connect();
    WSConnectionRegistry.instance = client;
    WSConnectionRegistry.initialized = true;
    return client;
  }

  /** 断开连接并清理 */
  static disconnect(): void {
    if (this.instance) {
      this.instance.disconnect();
      this.instance = null;
      this.initPromise = null;
      this.initialized = false;
      useBackendStore.getState().setWsClient(null);
    }
  }

  /** 是否已初始化 */
  static get isInitialized(): boolean {
    return this.initialized;
  }
}