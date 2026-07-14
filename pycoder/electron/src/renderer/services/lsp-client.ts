/**
 * LSP 客户端 — 通过 IPC 与主进程的 Pyright LSP Server 通信
 *
 * 集成方式:
 *   渲染进程 (Monaco)  ←→  LSP Client (IPC)  ←→  主进程 (Pyright stdio)
 *
 * 功能:
 * - 使用 pyright-langserver 进行实时诊断（错误/警告波浪线）
 * - 代码补全（Ctrl+Space）
 * - 悬停显示类型信息
 * - 跳转到定义（Ctrl+Click）
 */

import { EventEmitter } from 'events';

export interface LSPDiagnostic {
  uri: string;
  line: number;
  column: number;
  endLine: number;
  endColumn: number;
  message: string;
  severity: 'error' | 'warning' | 'info';
}

export interface LSPCompletionItem {
  label: string;
  kind: string;
  detail: string;
  insertText: string;
}

interface ElectronAPI {
  invoke(channel: string, ...args: any[]): Promise<any>;
  on(channel: string, callback: (...args: any[]) => void): void;
  removeListener(channel: string, callback: (...args: any[]) => void): void;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

export class LSPClient extends EventEmitter {
  private initialized = false;
  private documentVersions = new Map<string, number>();

  constructor() {
    super();
  }

  /**
   * 初始化 LSP 连接 — 在主进程中启动 Pyright 进程
   */
  async initialize(rootUri: string): Promise<boolean> {
    try {
      if (!window.electronAPI) {
        if (typeof window !== 'undefined') {
          const logger = (window as any).__lsp_log || console;
          logger.warn('[LSP] LSP 仅在 Electron 环境可用');
        }
        return false;
      }

      const result = await window.electronAPI.invoke('lsp:start', rootUri);
      this.initialized = result === true;

      window.electronAPI.on('lsp:diagnostics', (_event: any, data: { uri: string; diagnostics: LSPDiagnostic[] }) => {
        this.emit('diagnostics', data.uri, data.diagnostics);
      });

      if (this.initialized) {
        this.emit('ready');
      }
      return this.initialized;
    } catch (err) {
      this.initialized = false;
      return false;
    }
  }

  isReady(): boolean {
    return this.initialized && !!window.electronAPI;
  }

  /**
   * 打开文档 — 通知 LSP Server 开始分析文件
   */
  async openDocument(uri: string, text: string): Promise<void> {
    if (!this.isReady()) return;
    this.documentVersions.set(uri, 1);
    await window.electronAPI!.invoke('lsp:open-document', uri, text);
  }

  /**
   * 变更文档 — 增量更新 LSP Server 的文件内容
   */
  async changeDocument(uri: string, text: string): Promise<void> {
    if (!this.isReady()) return;
    const version = (this.documentVersions.get(uri) || 0) + 1;
    this.documentVersions.set(uri, version);
    await window.electronAPI!.invoke('lsp:change-document', uri, text, version);
  }

  /**
   * 获取代码补全建议（Ctrl+Space 触发）
   */
  async getCompletions(uri: string, line: number, column: number): Promise<LSPCompletionItem[]> {
    if (!this.isReady()) return [];
    return await window.electronAPI!.invoke('lsp:completions', uri, line, column) || [];
  }

  /**
   * 获取悬停信息（鼠标悬停时显示类型/文档）
   */
  async getHover(uri: string, line: number, column: number): Promise<string | null> {
    if (!this.isReady()) return null;
    return await window.electronAPI!.invoke('lsp:hover', uri, line, column) || null;
  }

  /**
   * 跳转到定义（Ctrl+Click 或 F12）
   */
  async goToDefinition(uri: string, line: number, column: number): Promise<{ uri: string; line: number; column: number } | null> {
    if (!this.isReady()) return null;
    return await window.electronAPI!.invoke('lsp:definition', uri, line, column) || null;
  }

  /**
   * 关闭文档
   */
  async closeDocument(uri: string): Promise<void> {
    if (!this.isReady()) return;
    this.documentVersions.delete(uri);
    await window.electronAPI!.invoke('lsp:close-document', uri);
  }

  /**
   * 关闭 LSP 连接
   */
  async shutdown(): Promise<void> {
    if (!this.initialized) return;
    this.initialized = false;
    if (window.electronAPI) {
      await window.electronAPI.invoke('lsp:shutdown').catch(() => { });
    }
    // LSP 已关闭
  }
}

// 单例
let instance: LSPClient | null = null;

export function getLSPClient(): LSPClient {
  if (!instance) {
    instance = new LSPClient();
  }
  return instance;
}
