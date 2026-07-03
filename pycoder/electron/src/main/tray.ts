import { Tray, Menu, nativeImage, BrowserWindow, app } from 'electron';
import path from 'path';
import fs from 'fs';

let appTray: Tray | null = null;

export function createTray(): void {
  try {
    const iconPath = process.resourcesPath
      ? path.join(process.resourcesPath, 'tray-icon.png')
      : path.join(__dirname, '../../resources/tray-icon.png');

    let trayIcon: Electron.NativeImage;
    if (fs.existsSync(iconPath)) {
      trayIcon = nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 });
    } else {
      const size = 16;
      const buf = Buffer.alloc(size * size * 4, 0);
      buf[2] = 0xff;
      buf[3] = 0xff;
      trayIcon = nativeImage.createFromBuffer(buf, { width: size, height: size });
    }

    appTray = new Tray(trayIcon);
    appTray.setToolTip('PyCoder IDE - AI 编程助手');

    const contextMenu = Menu.buildFromTemplate([
      {
        label: '显示窗口',
        click: () => {
          const win = BrowserWindow.getAllWindows()[0];
          if (win) { win.show(); win.focus(); }
        },
      },
      {
        label: '新建对话',
        click: () => {
          const win = BrowserWindow.getAllWindows()[0];
          if (win) { win.show(); win.webContents.send('menu:new-chat'); }
        },
      },
      { type: 'separator' },
      { label: '退出', click: () => app.quit() },
    ]);

    appTray.setContextMenu(contextMenu);
    appTray.on('double-click', () => {
      const win = BrowserWindow.getAllWindows()[0];
      if (win) { win.show(); win.focus(); }
    });
  } catch (err) {
    console.error('[PyCoder] Failed to create tray:', err);
  }
}
