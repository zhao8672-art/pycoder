import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('electronAPI', {
  // ── 窗口控制 ──
  minimizeWindow: () => ipcRenderer.invoke('window:minimize'),
  toggleMaximizeWindow: () => ipcRenderer.invoke('window:maximize'),
  closeWindow: () => ipcRenderer.invoke('window:close'),
  isMaximized: () => ipcRenderer.invoke('window:is-maximized'),

  // ── 文件操作 ──
  openFile: (filePath?: string) => ipcRenderer.invoke('file:open', filePath),
  saveFile: (filePath: string, content: string) => ipcRenderer.invoke('file:save', filePath, content),
  getFileTree: (rootPath?: string, maxDepth?: number) => ipcRenderer.invoke('file:tree', rootPath, maxDepth),

  // ── 项目操作 ──
  openProject: () => ipcRenderer.invoke('project:open'),
  openFolderDialog: () => ipcRenderer.invoke('dialog:open-folder'),

  // ── Shell 操作 ──
  openExternal: (url: string) => ipcRenderer.invoke('shell:open-external', url),
  showInFolder: (filePath: string) => ipcRenderer.invoke('shell:show-in-folder', filePath),
  openFileInOs: (filePath: string) => ipcRenderer.invoke('shell:open-file', filePath),

  // ── 后端 ──
  getBackendUrl: () => ipcRenderer.invoke('app:get-backend-url'),
  getApiKey: () => ipcRenderer.invoke('app:get-api-key'),

  // ── 菜单操作 ──
  sendMenuEvent: (channel: string) => ipcRenderer.send(channel),
  quit: () => ipcRenderer.invoke('app:quit'),
  showAbout: () => ipcRenderer.invoke('app:show-about'),

  // ── 事件监听（菜单 → 渲染进程） ──
  onMenuEvent: (channel: string, callback: (...args: any[]) => void) => {
    const validChannels = [
      'menu:open-project', 'menu:open-file', 'menu:save-file',
      'menu:new-chat', 'menu:explain-code', 'menu:add-tests',
      'menu:find-bug', 'menu:open-settings',
      'backend:status',
    ];
    if (validChannels.includes(channel)) {
      const listener = (_event: any, ...args: any[]) => callback(...args);
      ipcRenderer.on(channel, listener);
      return () => ipcRenderer.removeListener(channel, listener);
    }
    return () => { };
  },

  // ── 内置浏览器操作（AI 分析用） ──
  browserExecJs: (code: string) => ipcRenderer.invoke('browser:exec-js', code),
  browserNavigate: (url: string) => ipcRenderer.invoke('browser:navigate', url),
  browserReload: () => ipcRenderer.invoke('browser:reload'),
  browserGetContext: () => ipcRenderer.invoke('browser:get-context'),
  browserAnalyzePage: () => ipcRenderer.invoke('browser:analyze-page'),
  browserScreenshot: () => ipcRenderer.invoke('browser:screenshot'),
});
