import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useAppStore } from '../stores/appStore';
import { BackendAPI } from '../services/backend';

interface CommandItem {
  id: string;
  type: 'file' | 'symbol' | 'command' | 'tool';
  label: string;
  detail?: string;
  icon: string;
  action: () => void;
}

export const CommandPalette: React.FC = () => {
  const {
    commandPaletteOpen,
    setCommandPaletteOpen,
    openFile,
    setActiveSidebar,
    toggleSidebar,
    setLayout,
    setCurrentModel,
    wsClient,
  } = useAppStore();

  const [query, setQuery] = useState('');
  const [items, setItems] = useState<CommandItem[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const baseCommands: CommandItem[] = [
    { id: 'settings', type: 'command', label: '\u2699 \u8BBE\u7F6E', icon: '\u2699', action: () => { setActiveSidebar('settings'); setLayout({ sidebarOpen: true }); setCommandPaletteOpen(false); } },
    { id: 'skills', type: 'command', label: '\u{1F9E9} Skills \u5E02\u573A', icon: '\u{1F9E9}', action: () => { setActiveSidebar('skills'); setLayout({ sidebarOpen: true }); setCommandPaletteOpen(false); } },
    { id: 'cloud', type: 'command', label: '\u2601\uFE0F PyCoder Cloud', icon: '\u2601\uFE0F', action: () => { setActiveSidebar('cloud'); setLayout({ sidebarOpen: true }); setCommandPaletteOpen(false); } },
    { id: 'team', type: 'command', label: '\u{1F465} Agent \u56E2\u961F', icon: '\u{1F465}', action: () => { setActiveSidebar('team'); setLayout({ sidebarOpen: true }); setCommandPaletteOpen(false); } },
    { id: 'evolution', type: 'command', label: '\u{1F9EC} \u81EA\u6211\u8FDB\u5316\u5F15\u64CE', icon: '\u{1F9EC}', action: () => { useAppStore.getState().toggleEvoPanel?.(); setCommandPaletteOpen(false); } },
    { id: 'snippets', type: 'command', label: '\u{1F4CB} \u4EE3\u7801\u7247\u6BB5', icon: '\u{1F4CB}', action: () => { setActiveSidebar('snippets'); setLayout({ sidebarOpen: true }); setCommandPaletteOpen(false); } },
    { id: 'extensions', type: 'command', label: '\u{1F9F0} \u6269\u5C55\u7BA1\u7406', icon: '\u{1F9F0}', action: () => { setActiveSidebar('extensions'); setLayout({ sidebarOpen: true }); setCommandPaletteOpen(false); } },
    { id: 'browser', type: 'command', label: '\u{1F310} \u5185\u7F6E\u6D4F\u89C8\u5668', icon: '\u{1F310}', action: () => { useAppStore.getState().toggleBrowserPanel?.(); setCommandPaletteOpen(false); } },
    { id: 'mcp', type: 'command', label: '\u{1F527} \u5217\u51FA MCP \u5DE5\u5177', icon: '\u{1F527}', action: () => { if (wsClient) { wsClient.sendJson({ type: 'mcp_list' }); } setCommandPaletteOpen(false); } },
    { id: 'generate', type: 'command', label: '\u{1F680} \u4E00\u952E\u751F\u6210\u9879\u76EE', icon: '\u{1F680}', action: () => { setCommandPaletteOpen(false); } },
    { id: 'terminal', type: 'command', label: '\u25B6 \u6253\u5F00\u7EC8\u7AEF', icon: '\u25B6', action: () => { useAppStore.getState().setBottomPanel('terminal'); useAppStore.getState().toggleBottomPanel(); setCommandPaletteOpen(false); } },
    { id: 'testgen', type: 'command', label: '\u{1F9EA} \u6D4B\u8BD5\u751F\u6210\u5668', icon: '\u{1F9EA}', action: () => { useAppStore.getState().setBottomPanel('testgen'); useAppStore.getState().toggleBottomPanel(); setCommandPaletteOpen(false); } },
    { id: 'runfix', type: 'command', label: '\u{1F504} Run & Fix \u5FAA\u73AF', icon: '\u{1F504}', action: () => { useAppStore.getState().setBottomPanel('runfix'); useAppStore.getState().toggleBottomPanel(); setCommandPaletteOpen(false); } },
    { id: 'debug', type: 'command', label: '\u{1F41B} \u8C03\u8BD5\u5668', icon: '\u{1F41B}', action: () => { useAppStore.getState().setBottomPanel('debug'); useAppStore.getState().toggleBottomPanel(); setCommandPaletteOpen(false); } },
    { id: 'runner', type: 'command', label: '\u{1F40D} Python \u8FD0\u884C\u5668', icon: '\u{1F40D}', action: () => { useAppStore.getState().setBottomPanel('runner'); useAppStore.getState().toggleBottomPanel(); setCommandPaletteOpen(false); } },
    { id: 'new-chat', type: 'command', label: '\u{1F4AC} \u65B0\u5EFA AI \u5BF9\u8BDD', icon: '\u{1F4AC}', action: () => { useAppStore.getState().clearChat(); setCommandPaletteOpen(false); } },
    { id: 'toggle-theme', type: 'command', label: '\u{1F313} \u5207\u6362\u660E\u6697\u4E3B\u9898', icon: '\u{1F313}', action: () => { useAppStore.getState().toggleTheme(); setCommandPaletteOpen(false); } },
  ];

  const searchFiles = useCallback(async (q: string) => {
    try {
      const res = await BackendAPI.files.list('.');
      const files: CommandItem[] = [];
      const flattenTree = (tree: any[], prefix: string) => {
        for (const item of tree) {
          const fullPath = prefix ? `${prefix}/${item.name}` : item.name;
          if (item.type === 'file') {
            if (item.name.toLowerCase().includes(q.toLowerCase())) {
              files.push({
                id: `file-${fullPath}`,
                type: 'file',
                label: `📄 ${item.name}`,
                detail: fullPath,
                icon: '📄',
                action: async () => {
                  const contentRes = await BackendAPI.files.read(fullPath);
                  if (contentRes?.content) {
                    openFile({
                      id: fullPath,
                      filePath: fullPath,
                      fileName: item.name,
                      content: contentRes.content,
                      isDirty: false,
                      language: item.name.endsWith('.py') ? 'python' : 'plaintext',
                    });
                  }
                  setCommandPaletteOpen(false);
                },
              });
            }
          } else if (item.children) {
            flattenTree(item.children, fullPath);
          }
        }
      };
      flattenTree(res?.tree || [], '');
      return files.slice(0, 10);
    } catch {
      return [];
    }
  }, [openFile]);

  useEffect(() => {
    if (!commandPaletteOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (!commandPaletteOpen) return;

      if (e.key === 'Escape') {
        setCommandPaletteOpen(false);
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((prev) => Math.min(prev + 1, items.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex((prev) => Math.max(prev - 1, 0));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (items[selectedIndex]) {
          items[selectedIndex].action();
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [commandPaletteOpen, items, selectedIndex]);

  useEffect(() => {
    if (!commandPaletteOpen) return;
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [commandPaletteOpen]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;

    if (!query) {
      setItems(baseCommands);
      setSelectedIndex(0);
      return;
    }

    timer = setTimeout(async () => {
      const fileResults = await searchFiles(query);
      const filteredCommands = baseCommands.filter((cmd) =>
        cmd.label.toLowerCase().includes(query.toLowerCase())
      );
      setItems([...filteredCommands, ...fileResults]);
      setSelectedIndex(0);
    }, 150);

    return () => clearTimeout(timer);
  }, [query]);

  if (!commandPaletteOpen) return null;

  // 分组：命令和文件
  const commandItems = items.filter((i) => i.type === 'command' || i.type === 'tool');
  const fileItems = items.filter((i) => i.type === 'file');

  const renderItem = (item: CommandItem, globalIndex: number) => (
    <div
      key={item.id}
      className={`command-palette-item ${globalIndex === selectedIndex ? 'selected' : ''}`}
      onClick={() => item.action()}
      onMouseEnter={() => setSelectedIndex(globalIndex)}
    >
      <span className="command-palette-item-icon">{item.icon}</span>
      <span className="command-palette-item-label">{item.label}</span>
      {item.detail && <span className="command-palette-item-detail">{item.detail}</span>}
    </div>
  );

  return (
    <div className="command-palette-overlay" onClick={() => setCommandPaletteOpen(false)}>
      <div className="command-palette" onClick={(e) => e.stopPropagation()}>
        <div className="command-palette-header">
          <span className="command-palette-icon">{'\u{1F50D}'}</span>
          <input
            ref={inputRef}
            type="text"
            className="command-palette-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={'\u641C\u7D22\u547D\u4EE4\u3001\u6587\u4EF6\u3001\u7B26\u53F7...'}
          />
          <kbd className="command-palette-shortcut">ESC</kbd>
        </div>
        <div className="command-palette-list">
          {items.length === 0 ? (
            <div className="command-palette-empty">
              <p>{'\u672A\u627E\u5230\u5339\u914D\u7ED3\u679C'}</p>
              <p className="command-palette-empty-hint">{'\u5C1D\u8BD5\u5176\u4ED6\u5173\u952E\u8BCD'}</p>
            </div>
          ) : (
            <>
              {commandItems.length > 0 && (
                <>
                  <div className="command-palette-group-header">{'\u547D\u4EE4'}</div>
                  {commandItems.map((item) => renderItem(item, items.indexOf(item)))}
                </>
              )}
              {fileItems.length > 0 && (
                <>
                  <div className="command-palette-group-header">{'\u6587\u4EF6'}</div>
                  {fileItems.map((item) => renderItem(item, items.indexOf(item)))}
                </>
              )}
            </>
          )}
        </div>
        <div className="command-palette-footer">
          <span className="command-palette-footer-hint">
            <kbd>{'\u2191\u2193'}</kbd> {'\u5BFC\u822A'} <kbd>Enter</kbd> {'\u9009\u62E9'} <kbd>ESC</kbd> {'\u5173\u95ED'}
          </span>
        </div>
      </div>
    </div>
  );
};
