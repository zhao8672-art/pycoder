import { Menu, dialog, shell, BrowserWindow, app } from 'electron';

export function createAppMenu(): void {
  const isMac = process.platform === 'darwin';

  const template: Electron.MenuItemConstructorOptions[] = [
    ...(isMac ? [{
      label: app.name,
      submenu: [
        { label: '关于 PyCoder', role: 'about' as const },
        { type: 'separator' as const },
        {
          label: '偏好设置...',
          accelerator: 'CmdOrCtrl+,',
          click: () => {
            BrowserWindow.getFocusedWindow()?.webContents.send('menu:open-settings');
          },
        },
        { type: 'separator' as const },
        { label: '退出 PyCoder', accelerator: 'CmdOrCtrl+Q', click: () => app.quit() },
      ],
    }] : []),

    {
      label: '文件',
      submenu: [
        {
          label: '打开项目...',
          accelerator: 'CmdOrCtrl+O',
          click: () => BrowserWindow.getFocusedWindow()?.webContents.send('menu:open-project'),
        },
        {
          label: '打开文件...',
          accelerator: 'CmdOrCtrl+Shift+O',
          click: () => BrowserWindow.getFocusedWindow()?.webContents.send('menu:open-file'),
        },
        { type: 'separator' },
        {
          label: '保存',
          accelerator: 'CmdOrCtrl+S',
          click: () => BrowserWindow.getFocusedWindow()?.webContents.send('menu:save-file'),
        },
        { type: 'separator' },
        ...(isMac ? [] : [{
          label: '退出',
          accelerator: 'Alt+F4',
          click: () => app.quit(),
        }]),
      ],
    },

    {
      label: '编辑',
      submenu: [
        { label: '撤销', accelerator: 'CmdOrCtrl+Z', role: 'undo' as const },
        { label: '重做', accelerator: 'CmdOrCtrl+Shift+Z', role: 'redo' as const },
        { type: 'separator' },
        { label: '剪切', accelerator: 'CmdOrCtrl+X', role: 'cut' as const },
        { label: '复制', accelerator: 'CmdOrCtrl+C', role: 'copy' as const },
        { label: '粘贴', accelerator: 'CmdOrCtrl+V', role: 'paste' as const },
      ],
    },

    {
      label: 'AI',
      submenu: [
        {
          label: '新建对话',
          accelerator: 'CmdOrCtrl+Shift+N',
          click: () => BrowserWindow.getFocusedWindow()?.webContents.send('menu:new-chat'),
        },
        { type: 'separator' },
        {
          label: '解释代码',
          accelerator: 'CmdOrCtrl+I',
          click: () => BrowserWindow.getFocusedWindow()?.webContents.send('menu:explain-code'),
        },
        {
          label: '添加测试',
          accelerator: 'CmdOrCtrl+Shift+T',
          click: () => BrowserWindow.getFocusedWindow()?.webContents.send('menu:add-tests'),
        },
        {
          label: '查找 Bug',
          accelerator: 'CmdOrCtrl+B',
          click: () => BrowserWindow.getFocusedWindow()?.webContents.send('menu:find-bug'),
        },
      ],
    },

    {
      label: '视图',
      submenu: [
        { label: '重新加载', accelerator: 'CmdOrCtrl+R', role: 'reload' as const },
        { label: '强制重新加载', accelerator: 'CmdOrCtrl+Shift+R', role: 'forceReload' as const },
        { label: '开发者工具', accelerator: 'F12', role: 'toggleDevTools' as const },
      ],
    },

    {
      label: '帮助',
      submenu: [
        {
          label: '关于 PyCoder',
          click: () => {
            dialog.showMessageBox({
              type: 'info',
              title: '关于 PyCoder',
              message: 'PyCoder IDE',
              detail: '版本: 0.5.0\nPython 开发者原生的 AI 编程 IDE\n\n开源协议: Apache 2.0',
            });
          },
        },
        { type: 'separator' },
        {
          label: 'GitHub',
          click: () => shell.openExternal('https://github.com/PyCoder-ai/pycoder'),
        },
      ],
    },
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}
