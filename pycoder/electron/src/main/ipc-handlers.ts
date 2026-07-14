import { ipcMain, dialog, shell, BrowserWindow, app } from 'electron';
import fs from 'fs';
import path from 'path';

export function registerIpcHandlers(): void {
  // ── 窗口控制 ──

  ipcMain.handle('window:minimize', () => {
    BrowserWindow.getFocusedWindow()?.minimize();
  });

  ipcMain.handle('window:maximize', () => {
    const win = BrowserWindow.getFocusedWindow();
    if (win) {
      win.isMaximized() ? win.unmaximize() : win.maximize();
    }
  });

  ipcMain.handle('window:close', () => {
    BrowserWindow.getFocusedWindow()?.close();
  });

  ipcMain.handle('window:is-maximized', () => {
    return BrowserWindow.getFocusedWindow()?.isMaximized() ?? false;
  });

  // ── 文件操作 ──

  ipcMain.handle('file:open', async (_event, filePath?: string) => {
    try {
      if (!filePath) {
        const result = await dialog.showOpenDialog({
          title: '选择文件',
          properties: ['openFile'],
          filters: [
            { name: 'Python 文件', extensions: ['py'] },
            { name: '代码文件', extensions: ['py', 'js', 'ts', 'jsx', 'tsx', 'html', 'css', 'json', 'md', 'yaml', 'yml', 'toml'] },
            { name: '所有文件', extensions: ['*'] },
          ],
        });
        if (result.canceled || result.filePaths.length === 0) {
          return { success: false, error: '用户取消' };
        }
        filePath = result.filePaths[0];
      }

      const resolved = path.resolve(filePath);
      const stat = fs.statSync(resolved);
      if (!stat.isFile()) {
        return { success: false, error: '不是文件' };
      }
      const content = fs.readFileSync(resolved, 'utf-8');
      return {
        success: true,
        path: resolved,
        name: path.basename(resolved),
        content,
        size: stat.size,
        modifiedAt: stat.mtimeMs / 1000,
      };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  });

  ipcMain.handle('file:save', async (_event, filePath: string, content: string) => {
    try {
      const resolved = path.resolve(filePath);
      fs.mkdirSync(path.dirname(resolved), { recursive: true });
      fs.writeFileSync(resolved, content, 'utf-8');
      return { success: true, path: resolved };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  });

  ipcMain.handle('file:tree', async (_event, rootPath?: string, maxDepth = 3) => {
    const cwd = rootPath ? path.resolve(rootPath) : process.cwd();
    return scanDirectory(cwd, cwd, maxDepth);
  });

  // ── 项目操作 ──

  ipcMain.handle('project:open', async () => {
    const result = await dialog.showOpenDialog({
      title: '打开项目',
      properties: ['openDirectory'],
    });
    if (result.canceled || result.filePaths.length === 0) {
      return { success: false, error: '用户取消' };
    }
    return { success: true, path: result.filePaths[0] };
  });

  ipcMain.handle('dialog:open-folder', async () => {
    const result = await dialog.showOpenDialog({
      title: '选择工作区文件夹',
      properties: ['openDirectory'],
    });
    if (result.canceled || result.filePaths.length === 0) {
      return null;
    }
    return result.filePaths[0];
  });

  // ── Shell 操作 ──

  ipcMain.handle('shell:open-external', async (_event, url: string) => {
    await shell.openExternal(url);
    return { success: true };
  });

  ipcMain.handle('shell:show-in-folder', async (_event, filePath: string) => {
    shell.showItemInFolder(path.resolve(filePath));
    return { success: true };
  });

  ipcMain.handle('shell:open-file', async (_event, filePath: string) => {
    shell.openPath(path.resolve(filePath));
    return { success: true };
  });

  // ── 获取后端 URL ──

  ipcMain.handle('app:get-backend-url', () => {
    const port = process.env.PYCODER_BACKEND_PORT || '8423';
    return `http://127.0.0.1:${port}`;
  });

  // ── 获取 API Key（优先 ~/.pycoder/.api_key，回退到 .env） ──

  ipcMain.handle('app:get-api-key', () => {
    try {
      const homedir = require('os').homedir();
      const apiKeyPath = path.join(homedir, '.pycoder', '.api_key');
      if (fs.existsSync(apiKeyPath)) {
        return fs.readFileSync(apiKeyPath, 'utf-8').trim();
      }
      // 回退: 从 .env 文件读取 PYCODER_API_KEY
      const envPath = path.join(homedir, '.pycoder', '.env');
      if (fs.existsSync(envPath)) {
        const envContent = fs.readFileSync(envPath, 'utf-8');
        for (const line of envContent.split('\n')) {
          const trimmed = line.trim();
          if (trimmed.startsWith('PYCODER_API_KEY=')) {
            const key = trimmed.substring('PYCODER_API_KEY='.length).trim();
            if (key) {
              // 同步到 .api_key 供下次使用
              try { fs.writeFileSync(apiKeyPath, key, 'utf-8'); } catch { }
              return key;
            }
          }
        }
      }
    } catch {
      // 忽略错误
    }
    return '';
  });

  // ── 应用操作 ──

  ipcMain.handle('app:quit', () => {
    app.quit();
  });

  ipcMain.handle('app:show-about', async () => {
    await dialog.showMessageBox({
      type: 'info',
      title: '关于 PyCoder',
      message: 'PyCoder IDE',
      detail: '版本: 0.5.0\nPython 开发者原生的 AI 编程 IDE\n\n开源协议: Apache 2.0',
    });
  });

  // ── LSP (Language Server Protocol) ──

  ipcMain.handle('lsp:start', async (_event, rootUri: string) => {
    const { getLSPProcessManager } = require('./lsp-server');
    const mgr = getLSPProcessManager();
    const ok = await mgr.start(rootUri);
    // 转发诊断结果到渲染进程
    mgr.on('diagnostics', (uri: string, diagnostics: any[]) => {
      BrowserWindow.getAllWindows().forEach((win) => {
        win.webContents.send('lsp:diagnostics', { uri, diagnostics });
      });
    });
    return ok;
  });

  ipcMain.handle('lsp:open-document', async (_event, uri: string, text: string) => {
    const { getLSPProcessManager } = require('./lsp-server');
    await getLSPProcessManager().openDocument(uri, text);
    return true;
  });

  ipcMain.handle('lsp:change-document', async (_event, uri: string, text: string, version: number) => {
    const { getLSPProcessManager } = require('./lsp-server');
    await getLSPProcessManager().changeDocument(uri, text, version);
    return true;
  });

  ipcMain.handle('lsp:close-document', async (_event, uri: string) => {
    const { getLSPProcessManager } = require('./lsp-server');
    await getLSPProcessManager().closeDocument(uri);
    return true;
  });

  ipcMain.handle('lsp:completions', async (_event, uri: string, line: number, column: number) => {
    const { getLSPProcessManager } = require('./lsp-server');
    return await getLSPProcessManager().getCompletions(uri, line, column);
  });

  ipcMain.handle('lsp:hover', async (_event, uri: string, line: number, column: number) => {
    const { getLSPProcessManager } = require('./lsp-server');
    return await getLSPProcessManager().getHover(uri, line, column);
  });

  ipcMain.handle('lsp:definition', async (_event, uri: string, line: number, column: number) => {
    const { getLSPProcessManager } = require('./lsp-server');
    return await getLSPProcessManager().goToDefinition(uri, line, column);
  });

  ipcMain.handle('lsp:shutdown', async () => {
    const { getLSPProcessManager } = require('./lsp-server');
    await getLSPProcessManager().shutdown();
    return true;
  });

  // ══════════════════════════════════════════════
  // 浏览器操作 — AI 可读取/操作内置浏览器
  // ══════════════════════════════════════════════

  ipcMain.handle('browser:exec-js', async (_event, code: string) => {
    const win = BrowserWindow.getFocusedWindow();
    if (!win) return { success: false, error: '无窗口' };
    try {
      const result = await win.webContents.executeJavaScript(`
        (function() {
          const wv = document.querySelector('webview');
          if (!wv) return JSON.stringify({error:'no webview'});
          try { return JSON.stringify(eval(${JSON.stringify(code)})); }
          catch(e) { return JSON.stringify({error: e.message}); }
        })()
      `);
      return { success: true, result: JSON.parse(result) };
    } catch (e: any) {
      return { success: false, error: e.message };
    }
  });

  ipcMain.handle('browser:navigate', async (_event, url: string) => {
    const win = BrowserWindow.getFocusedWindow();
    if (!win) return { success: false };
    await win.webContents.executeJavaScript(`
      (function() {
        const wv = document.querySelector('webview');
        if (wv) wv.loadURL(${JSON.stringify(url)});
      })()
    `);
    return { success: true };
  });

  ipcMain.handle('browser:reload', async () => {
    const win = BrowserWindow.getFocusedWindow();
    if (!win) return { success: false };
    await win.webContents.executeJavaScript(`
      (function() {
        const wv = document.querySelector('webview');
        if (wv) wv.reload();
      })()
    `);
    return { success: true };
  });

  ipcMain.handle('browser:get-context', async () => {
    const win = BrowserWindow.getFocusedWindow();
    if (!win) return { success: false, error: '无窗口' };
    const result = await win.webContents.executeJavaScript(`
      (function() {
        const wv = document.querySelector('webview');
        if (!wv) return JSON.stringify({error:'no webview'});
        try {
          return JSON.stringify({
            url: wv.getURL(),
            title: wv.getTitle(),
            userAgent: wv.getUserAgent(),
            isLoading: wv.isLoading(),
          });
        } catch(e) { return JSON.stringify({error:e.message}); }
      })()
    `);
    return { success: true, context: JSON.parse(result) };
  });

  ipcMain.handle('browser:analyze-page', async () => {
    const win = BrowserWindow.getFocusedWindow();
    if (!win) return { success: false, error: '无窗口' };
    const result = await win.webContents.executeJavaScript(`
      (function() {
        const wv = document.querySelector('webview');
        if (!wv) return JSON.stringify({error:'no webview'});
        try {
          const code = [
            'try {',
            '  const d = document;',
            '  return JSON.stringify({',
            '    url: location.href,',
            '    title: d.title,',
            '    headings: Array.from(d.querySelectorAll("h1,h2,h3")).slice(0,20).map(h=>({tag:h.tagName,text:h.textContent.slice(0,80)})),',
            '    scripts: Array.from(d.querySelectorAll("script[src]")).map(s=>s.getAttribute("src")).filter(Boolean).slice(0,10),',
            '    forms: Array.from(d.querySelectorAll("form")).map(f=>({action:f.action,method:f.method,inputs:f.querySelectorAll("input,select,textarea").length})),',
            '    links: Array.from(d.querySelectorAll("a[href]")).slice(0,30).map(a=>({href:a.href,text:a.textContent.slice(0,40)})),',
            '    errors: (window.__pycoderErrors||[]).slice(0,20),',
            '    bodyText: (d.body?.innerText||"").slice(0,2000),',
            '    metaViewport: d.querySelector("meta[name=viewport]")?.getAttribute("content")||"none"',
            '  });',
            '} catch(e) { return JSON.stringify({error:e.message}); }',
          ].join('\\n');
          wv.executeJavaScript(code).then(r => {
            try { window.__pycoderAnalysisResult = JSON.parse(r); }
            catch { window.__pycoderAnalysisResult = {raw: String(r)}; }
          }).catch(e => { window.__pycoderAnalysisResult = {error: e.message}; });
          return JSON.stringify({pending: true, note: 'analysis running'});
        } catch(e) { return JSON.stringify({error:e.message}); }
      })()
    `);
    // 等分析结果
    await new Promise(r => setTimeout(r, 1500));
    const final = await win.webContents.executeJavaScript(
      `JSON.stringify(window.__pycoderAnalysisResult || {error:'timeout'})`
    );
    return { success: true, analysis: JSON.parse(final) };
  });
}

// ── 目录扫描辅助函数 ──

function scanDirectory(rootPath: string, dirPath: string, maxDepth: number, currentDepth = 0): any {
  const ignoreDirs = new Set([
    '.git', '__pycache__', 'node_modules', '.venv', 'venv',
    '.env', '.idea', '.vscode', '.DS_Store', 'dist', 'build',
    '.egg-info', '.mypy_cache', '.pytest_cache',
  ]);
  const ignoreExts = new Set(['.pyc', '.pyo', '.so', '.dll', '.dylib']);

  if (currentDepth > maxDepth) {
    return { name: path.basename(dirPath), type: 'dir', truncated: true };
  }

  try {
    const entries = fs.readdirSync(dirPath, { withFileTypes: true });
    const children: any[] = [];

    const sorted = entries.sort((a, b) => {
      if (a.isDirectory() !== b.isDirectory()) return a.isDirectory() ? -1 : 1;
      return a.name.localeCompare(b.name);
    });

    for (const entry of sorted) {
      if (ignoreDirs.has(entry.name)) continue;
      if (ignoreExts.has(path.extname(entry.name))) continue;

      const fullPath = path.join(dirPath, entry.name);

      if (entry.isDirectory()) {
        if (entry.name.startsWith('.') && currentDepth > 0) continue;
        children.push(scanDirectory(rootPath, fullPath, maxDepth, currentDepth + 1));
      } else if (entry.isFile()) {
        try {
          const stat = fs.statSync(fullPath);
          children.push({
            name: entry.name,
            type: 'file',
            path: path.relative(rootPath, fullPath),
            size: stat.size,
            modifiedAt: stat.mtimeMs / 1000,
          });
        } catch {
          // skip unreadable files
        }
      }
    }

    return {
      name: path.basename(dirPath),
      type: 'dir',
      children,
    };
  } catch (err: any) {
    return { name: path.basename(dirPath), type: 'dir', error: err.message };
  }
}
