import React, { useEffect, useState } from 'react';
import { useAppStore, useEditorStore } from '../stores/appStore';
import { EditorTabContextMenu } from './EditorTabContextMenu';

export const EditorTabs: React.FC = () => {
  const { openTabs, activeTabId, setActiveTab, closeTab, restoreClosedTab, closedTabs } = useEditorStore();
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; tabId: string; fileName: string } | null>(null);

  // Ctrl+Shift+T — 恢复标签页
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 't') { e.preventDefault(); restoreClosedTab(); }
    };
    document.addEventListener('keydown', h);
    return () => document.removeEventListener('keydown', h);
  }, [restoreClosedTab]);

  const handleContext = (e: React.MouseEvent, tab: { id: string; fileName: string }) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, tabId: tab.id, fileName: tab.fileName });
  };

  const closeOthers = (tabId: string) => {
    openTabs.forEach(t => { if (t.id !== tabId) closeTab(t.id); });
    setContextMenu(null);
  };
  const closeRight = (tabId: string) => {
    const idx = openTabs.findIndex(t => t.id === tabId);
    if (idx >= 0) { openTabs.slice(idx + 1).forEach(t => closeTab(t.id)); }
    setContextMenu(null);
  };
  const closeAll = () => {
    [...openTabs].forEach(t => closeTab(t.id));
    setContextMenu(null);
  };

  // Drag reorder — swap tab positions
  const dragSrc = React.useRef<string | null>(null);
  const onDragStart = (e: React.DragEvent, tabId: string) => { dragSrc.current = tabId; e.dataTransfer.effectAllowed = 'move'; };
  const onDragOver = (e: React.DragEvent) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; };
  const onDrop = (e: React.DragEvent, targetId: string) => {
    e.preventDefault();
    const src = dragSrc.current; dragSrc.current = null;
    if (!src || src === targetId) return;
    const tabs = [...useEditorStore.getState().openTabs];
    const si = tabs.findIndex(t => t.id === src), ti = tabs.findIndex(t => t.id === targetId);
    if (si < 0 || ti < 0) return;
    [tabs[si], tabs[ti]] = [tabs[ti], tabs[si]];
    useEditorStore.setState({ openTabs: tabs });
  };

  return (
    <div className="editor-tabs">
      {openTabs.map((tab) => (
        <div key={tab.id}
          className={`editor-tab ${tab.id === activeTabId ? 'active' : ''} ${tab.isDirty ? 'dirty' : ''}`}
          onClick={() => setActiveTab(tab.id)}
          onContextMenu={(e) => handleContext(e, tab)}
          draggable onDragStart={(e) => onDragStart(e, tab.id)}
          onDragOver={onDragOver} onDrop={(e) => onDrop(e, tab.id)}>
          <span className="tab-name">
            {tab.isDirty && <span className="tab-dirty-indicator">● </span>}
            {tab.fileName}
          </span>
          <button className="tab-close" onClick={(e) => { e.stopPropagation(); closeTab(tab.id); }}>✕</button>
        </div>
      ))}
      {closedTabs.length > 0 && <div className="tab-restore-hint" title="Ctrl+Shift+T">↩ {closedTabs.length}</div>}
      {contextMenu && <EditorTabContextMenu {...contextMenu} onClose={() => setContextMenu(null)}
        onClose={() => { closeTab(contextMenu.tabId); setContextMenu(null); }}
        onCloseOthers={() => closeOthers(contextMenu.tabId)}
        onCloseRight={() => closeRight(contextMenu.tabId)}
        onCloseAll={closeAll}
      />}
    </div>
  );
};
