import { app, BrowserWindow, shell, session } from 'electron';
import path from 'path';
import { createAppMenu } from './menu';
import { createTray } from './tray';
import { PythonBackendManager } from './backend';
import { registerIpcHandlers } from './ipc-handlers';

// 全局错误捕获，确保任何未处理异常都可见
process.on('uncaughtException', (err) => {
  console.error('[FATAL] uncaughtException:', err);
});
process.on('unhandledRejection', (reason) => {
  console.error('[FATAL] unhandledRejection:', reason);
});

// P4: 极早期启动日志（在 app.whenReady 之前）
try {
  const fs0 = require('fs');
  const os0 = require('os');
  const logDir0 = process.env.APPDATA
    ? require('path').join(process.env.APPDATA, 'pycoder-electron')
    : require('path').join(os0.tmpdir(), 'pycoder-electron');
  fs0.mkdirSync(logDir0, { recursive: true });
  const early = `[${new Date().toISOString()}] early pid=${process.pid} exec=${process.execPath} argv=${process.argv.join(' ')}\n`;
  fs0.appendFileSync(require('path').join(logDir0, 'early.log'), early);
} catch (e) {
  // ignore
}

// Step6: 设置自定义 app name → 自动改变 userData/cache 路径，避免缓存权限问题
app.name = 'pycoder-electron';

// P0-Fix: GPU 加速开关策略
// FIX(窗口响应慢): 旧代码同时禁用了 disable-gpu + disable-software-rasterizer
// + disable-gpu-compositing + no-sandbox，导致所有渲染退化到纯 CPU 软件渲染，
// 窗口操作（滚动/拖拽/重绘）明显卡顿。
//
// 现在只保留 disable-gpu（解决已知的 GPU 缓存锁 "Unable to move the cache: 拒绝访问"），
// 允许 Chromium 使用 software rasterizer + GPU compositing 进行加速渲染。
// no-sandbox 也移除（仅对打包的本地应用必要，且会降低渲染性能）。
app.commandLine.appendSwitch('disable-gpu');
app.disableHardwareAcceleration();

const SERVER_PORT = parseInt(process.env.PYCODER_BACKEND_PORT || '8423', 10);
const isDev = process.env.NODE_ENV === 'development';

let mainWindow: BrowserWindow | null = null;
let backendManager: PythonBackendManager;

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
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

  // 渲染进程崩溃监控 — 记录崩溃原因，防止"自动关闭"无法排查
  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    const fs = require('fs');
    const logDir = path.join(app.getPath('appData'), 'pycoder-electron');
    const msg = `[${new Date().toISOString()}] render-process-gone: reason=${details.reason} exitCode=${details.exitCode}\n`;
    try {
      fs.appendFileSync(path.join(logDir, 'crash.log'), msg);
    } catch { /* ignore */ }
    console.error('[CRASH]', msg);
    // 崩溃后重新创建窗口
    setTimeout(() => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
      }
    }, 1000);
  });

  mainWindow.webContents.on('unresponsive', () => {
    const fs = require('fs');
    const logDir = path.join(app.getPath('appData'), 'pycoder-electron');
    const msg = `[${new Date().toISOString()}] renderer unresponsive\n`;
    try {
      fs.appendFileSync(path.join(logDir, 'crash.log'), msg);
    } catch { /* ignore */ }
    console.error('[UNRESPONSIVE]', msg);
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

// F3: 语音输入 — 权限请求白名单 (麦克风等)
// 未设置处理器时 Electron 默认放行所有权限, 这里显式收敛,
// 确保 getUserMedia / SpeechRecognition 的 media 权限被允许
const ALLOWED_PERMISSIONS = new Set([
  'media', // 麦克风/摄像头 (F3 语音输入)
  'clipboard-read',
  'clipboard-sanitized-write',
  'notifications',
  'fullscreen',
  'pointerLock',
]);

function setupPermissions(): void {
  session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => {
    callback(ALLOWED_PERMISSIONS.has(permission));
  });
}

app.whenReady().then(async () => {
  // P2-5: 启动前清理可能锁定的 Electron 缓存目录
  const fs = require('fs');
  const customDataDir = path.join(app.getPath('appData'), 'pycoder-electron');
  fs.mkdirSync(customDataDir, { recursive: true });
  app.setPath('userData', customDataDir);
  app.setPath('cache', path.join(customDataDir, 'Cache'));

  // P4: 启动诊断日志 — 帮助排查打包版问题
  try {
    const diag = [
      `execPath=${process.execPath}`,
      `resourcesPath=${process.resourcesPath}`,
      `appPath=${app.getAppPath()}`,
      `isPackaged=${app.isPackaged}`,
      `port=${process.env.PYCODER_BACKEND_PORT || 8423}`,
    ].join('\n');
    const logPath = path.join(customDataDir, 'startup.log');
    fs.writeFileSync(logPath, `[${new Date().toISOString()}] ${diag}\n`, { flag: 'a' });
  } catch { /* ignore */ }
  const userDataPath = app.getPath('userData');
  // FIX(窗口响应慢): 旧代码每次启动都清理所有缓存目录（包括 Code Cache / Cache），
  // 导致 V8 字节码缓存、Chromium 资源缓存全部失效，每次启动都要重新编译 JS、
  // 重新解析资源，首屏加载明显变慢。
  //
  // 现在只清理 GPU 相关缓存（已知的"Unable to move the cache: 拒绝访问"锁问题源），
  // 保留通用缓存以加速启动。
  const cacheDirs = ['GPUCache', 'DawnGraphiteCache', 'DawnWebGPUCache'];
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

  // F3: 麦克风等权限白名单 (语音输入)
  setupPermissions();

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
