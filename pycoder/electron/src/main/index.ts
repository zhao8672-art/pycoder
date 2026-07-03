import { app, BrowserWindow, shell, session } from 'electron';
import path from 'path';
import { createAppMenu } from './menu';
import { createTray } from './tray';
import { PythonBackendManager } from './backend';
import { registerIpcHandlers } from './ipc-handlers';

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
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  if (isDev) {
    mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));
  }

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show();
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

function setupCSP(): void {
  if (isDev) return;
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [
          "default-src 'self'; " +
          "script-src 'self' 'unsafe-eval'; " +
          "style-src 'self' 'unsafe-inline'; " +
          "font-src 'self' data:; " +
          "img-src 'self' data:; " +
          "worker-src 'self' blob:; " +
          "connect-src 'self' http://127.0.0.1:* ws://127.0.0.1:*;",
        ],
      },
    });
  });
}

app.whenReady().then(async () => {
  registerIpcHandlers();
  createAppMenu();
  createTray();
  setupCSP();

  backendManager = new PythonBackendManager(SERVER_PORT);
  backendManager.start().catch((err) => {
    console.error('Backend start failed:', err);
  });

  createWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') { app.quit(); }
});

app.on('before-quit', () => { backendManager?.stop(); });

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) { createWindow(); }
});
