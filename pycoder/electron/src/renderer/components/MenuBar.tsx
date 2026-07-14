import React, { useState, useRef, useEffect } from 'react';

interface MenuItem {
  label: string;
  submenu?: Array<{
    label: string;
    accelerator?: string;
    click?: () => void;
    separator?: boolean;
  }>;
  role?: string;
}

const menuItems: MenuItem[] = [
  {
    label: '文件',
    submenu: [
      { label: '打开项目...', accelerator: 'Ctrl+O', click: () => window.electronAPI?.sendMenuEvent('menu:open-project') },
      { label: '打开文件...', accelerator: 'Ctrl+Shift+O', click: () => window.electronAPI?.sendMenuEvent('menu:open-file') },
      { separator: true },
      { label: '保存', accelerator: 'Ctrl+S', click: () => window.electronAPI?.sendMenuEvent('menu:save-file') },
      { separator: true },
      { label: '退出', accelerator: 'Alt+F4', click: () => window.electronAPI?.quit() },
    ],
  },
  {
    label: '编辑',
    submenu: [
      { label: '撤销', accelerator: 'Ctrl+Z', role: 'undo' },
      { label: '重做', accelerator: 'Ctrl+Shift+Z', role: 'redo' },
      { separator: true },
      { label: '剪切', accelerator: 'Ctrl+X', role: 'cut' },
      { label: '复制', accelerator: 'Ctrl+C', role: 'copy' },
      { label: '粘贴', accelerator: 'Ctrl+V', role: 'paste' },
    ],
  },
  {
    label: 'AI',
    submenu: [
      { label: '新建对话', accelerator: 'Ctrl+Shift+N', click: () => window.electronAPI?.sendMenuEvent('menu:new-chat') },
      { separator: true },
      { label: '解释代码', accelerator: 'Ctrl+I', click: () => window.electronAPI?.sendMenuEvent('menu:explain-code') },
      { label: '添加测试', accelerator: 'Ctrl+Shift+T', click: () => window.electronAPI?.sendMenuEvent('menu:add-tests') },
      { label: '查找 Bug', accelerator: 'Ctrl+B', click: () => window.electronAPI?.sendMenuEvent('menu:find-bug') },
    ],
  },
  {
    label: '视图',
    submenu: [
      { label: '重新加载', accelerator: 'Ctrl+R', role: 'reload' },
      { label: '强制重新加载', accelerator: 'Ctrl+Shift+R', role: 'forceReload' },
      { label: '开发者工具', accelerator: 'F12', role: 'toggleDevTools' },
    ],
  },
  {
    label: '帮助',
    submenu: [
      { label: '关于 PyCoder', click: () => window.electronAPI?.showAbout() },
      { separator: true },
      { label: 'GitHub', click: () => window.electronAPI?.openExternal('https://github.com/PyCoder-ai/pycoder') },
    ],
  },
];

export const MenuBar: React.FC = () => {
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenMenu(null);
      }
    };

    if (openMenu) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [openMenu]);

  const handleRoleClick = (role: string) => {
    window.electronAPI?.sendMenuEvent(`menu:role-${role}`);
    setOpenMenu(null);
  };

  const handleMenuClick = (menuItem: { click?: () => void; role?: string }) => {
    if (menuItem.role) {
      handleRoleClick(menuItem.role);
    } else if (menuItem.click) {
      menuItem.click();
    }
    setOpenMenu(null);
  };

  const toggleMenu = (label: string) => {
    setOpenMenu(openMenu === label ? null : label);
  };

  return (
    <div className="menubar-container" ref={menuRef}>
      <div className="menubar-drag">
        <span className="menubar-title">🐍 PyCoder IDE</span>
      </div>
      <div className="menubar-menu">
        {menuItems.map((item) => (
          <div key={item.label} className="menubar-item">
            <button
              className={`menubar-btn ${openMenu === item.label ? 'active' : ''}`}
              onClick={() => toggleMenu(item.label)}
            >
              {item.label}
            </button>
            {openMenu === item.label && item.submenu && (
              <div className="menubar-dropdown">
                {item.submenu.map((subItem, index) => (
                  subItem.separator ? (
                    <div key={`sep-${index}`} className="menubar-separator" />
                  ) : (
                    <button
                      key={`${item.label}-${index}`}
                      className="menubar-dropdown-item"
                      onClick={() => handleMenuClick(subItem)}
                    >
                      <span className="menubar-item-label">{subItem.label}</span>
                      {subItem.accelerator && (
                        <span className="menubar-item-accelerator">{subItem.accelerator}</span>
                      )}
                    </button>
                  )
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="menubar-controls">
        <button className="menubar-control-btn" onClick={() => window.electronAPI?.minimizeWindow()} title="最小化">
          −
        </button>
        <button className="menubar-control-btn" onClick={() => window.electronAPI?.toggleMaximizeWindow()} title="最大化">
          □
        </button>
        <button className="menubar-control-btn menubar-close-btn" onClick={() => window.electronAPI?.closeWindow()} title="关闭">
          ✕
        </button>
      </div>
    </div>
  );
};