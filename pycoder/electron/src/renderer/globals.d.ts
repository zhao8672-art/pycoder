interface ElectronAPI {
  minimizeWindow: () => Promise<void>;
  toggleMaximizeWindow: () => Promise<void>;
  closeWindow: () => Promise<void>;
  isMaximized: () => Promise<boolean>;

  openFile: (filePath?: string) => Promise<{
    success: boolean;
    path?: string;
    name?: string;
    content?: string;
    size?: number;
    error?: string;
  }>;
  saveFile: (filePath: string, content: string) => Promise<{
    success: boolean;
    path?: string;
    error?: string;
  }>;
  getFileTree: (rootPath?: string, maxDepth?: number) => Promise<any>;

  openProject: () => Promise<{ success: boolean; path?: string; error?: string }>;

  openExternal: (url: string) => Promise<void>;
  showInFolder: (filePath: string) => Promise<void>;
  openFileInOs: (filePath: string) => Promise<void>;

  getBackendUrl: () => Promise<string>;
  getApiKey: () => Promise<string>;

  onMenuEvent: (channel: string, callback: (...args: any[]) => void) => () => void;

  // ── 内置浏览器 AI 分析 ──
  browserExecJs: (code: string) => Promise<{ success: boolean; result?: any; error?: string }>;
  browserNavigate: (url: string) => Promise<{ success: boolean }>;
  browserReload: () => Promise<{ success: boolean }>;
  browserGetContext: () => Promise<{ success: boolean; context?: { url: string; title: string; isLoading: boolean }; error?: string }>;
  browserAnalyzePage: () => Promise<{ success: boolean; analysis?: any; error?: string }>;
  browserScreenshot: () => Promise<{ success: boolean; dataUrl?: string; error?: string }>;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

export { };
