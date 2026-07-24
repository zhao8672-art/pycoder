import { app, BrowserWindow, shell, session } from 'electron';
import path from 'path';
import { createAppMenu } from './menu';
import { createTray } from './tray';
import { PythonBackendManager } from './backend';
import { registerIpcHandlers } from './ipc-handlers';

// Step6: 设置自定义 app name → 自动改变 userData/cache 路径，避免缓存权限问题
app.name = 'pycoder-electron';

const SERVER_PORT = parseInt(process.env.PYCODER_BACKEND_PORT || '8423', 10);
const isDev = process.env.NODE_ENV === 'development';

let mainWindow: BrowserWindow | null = null;
let backendManager: PythonBackendManager;

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 960,
    minHeight: 640,
    title: 'PyCoder IDE - Python AI 编程助手',
    backgroundColor: '#1a1b2e',
    show: true,
    frame: false,
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      webviewTag: true,
    },
  });

  if (isDev) {
    mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));
  }

  mainWindow.once('ready-to-show', () => {
    // Window already shown
    if (backendManager) {
      mainWindow?.webContents.send('backend:status', backendManager.getStatus());
    }
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http')) {
      shell.openExternal(url);
    }
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// 生产模式下通过 session 设置 CSP（兼容 file:// 协议加载模块脚本）
function setupCSP(): void {
  if (isDev) return;
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    // ★ 只对主窗口应用 CSP，不干扰 webview 内的请求
    if (details.webContents?.id !== mainWindow?.webContents.id) {
      callback({ responseHeaders: details.responseHeaders });
      return;
    }
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [
          "default-src 'self'; " +
          "script-src 'self' 'unsafe-eval' 'unsafe-inline'; " +
          "style-src 'self' 'unsafe-inline'; " +
          "font-src 'self' data:; " +
          "img-src 'self' data: https: http:; " +
          "frame-src https: http:; " +
          "media-src https: http:; " +
          "worker-src 'self' blob:; " +
          "connect-src 'self' http://127.0.0.1:* ws://127.0.0.1:*;",
        ],
      },
    });
  });
}

app.whenReady().then(async () => {
  // Step6: 设置自定义 Electron 缓存路径，避免权限不足导致的 GPU 缓存创建失败
  const fs = require('fs');
  const customDataDir = path.join(app.getPath('appData'), 'pycoder-electron');
  fs.mkdirSync(customDataDir, { recursive: true });
  app.setPath('userData', customDataDir);
  app.setPath('cache', path.join(customDataDir, 'Cache'));

  // P2-5: 启动前清理可能锁定的 Electron 缓存目录
  const fs = require('fs');
  const userDataPath = app.getPath('userData');
  const cacheDirs = ['Cache', 'Code Cache', 'GPUCache', 'DawnGraphiteCache', 'DawnWebGPUCache', 'VideoDecodeStats'];
  for (const dir of cacheDirs) {
    const cachePath = path.join(userDataPath, dir);
    if (fs.existsSync(cachePath)) {
      try {
        fs.rmSync(cachePath, { recursive: true, force: true });
      } catch {
        // 缓存清理失败不阻止启动
      }
    }
  }

  registerIpcHandlers();
  createAppMenu();
  createTray();

  // 生产模式 CSP（仅作用于主窗口，不干扰 webview）
  setupCSP();

  backendManager = new PythonBackendManager(SERVER_PORT);
  // 异步启动后端，不阻塞窗口创建
  backendManager.start().catch((err) => {
    console.error('Backend start failed:', err);
  });

  createWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  backendManager?.stop();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
