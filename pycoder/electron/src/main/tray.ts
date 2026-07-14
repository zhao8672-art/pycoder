import { Tray, Menu, nativeImage, BrowserWindow, app } from 'electron';
import path from 'path';
import fs from 'fs';

let appTray: Tray | null = null;

export function createTray(): void {
  try {
    // 优先从 asar 外部 resources/ 目录加载（打包后）
    const iconPath = process.resourcesPath
      ? path.join(process.resourcesPath, 'tray-icon.png')
      : path.join(__dirname, '../../resources/tray-icon.png');

    let trayIcon: Electron.NativeImage;
    if (fs.existsSync(iconPath)) {
      trayIcon = nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 });
    } else {
      // 创建一个 16x16 的透明 PNG 作为占位图标
      const size = 16;
      const buf = Buffer.alloc(size * size * 4, 0);
      // 将第一个像素设为可见颜色（#4f8cff），让占位图标在任务栏可见
      buf[2] = 0xff;  // B
      buf[3] = 0xff;  // A
      trayIcon = nativeImage.createFromBuffer(buf, { width: size, height: size });
    }

    appTray = new Tray(trayIcon);
    appTray.setToolTip('PyCoder IDE - AI 编程助手');

    const contextMenu = Menu.buildFromTemplate([
      {
        label: '显示窗口',
        click: () => {
          const win = BrowserWindow.getAllWindows()[0];
          if (win) {
            win.show();
            win.focus();
          }
        },
      },
      {
        label: '新建对话',
        click: () => {
          const win = BrowserWindow.getAllWindows()[0];
          if (win) {
            win.show();
            win.webContents.send('menu:new-chat');
          }
        },
      },
      { type: 'separator' },
      {
        label: '退出',
        click: () => app.quit(),
      },
    ]);

    appTray.setContextMenu(contextMenu);
    appTray.on('double-click', () => {
      const win = BrowserWindow.getAllWindows()[0];
      if (win) {
        win.show();
        win.focus();
      }
    });
  } catch (err) {
    console.error('[PyCoder] Failed to create tray:', err);
  }
}
