/**
 * Editor Store — 文件树、编辑器标签页
 */
import { create } from 'zustand';
import type { EditorTab, FileEntry } from '../types';

interface EditorState {
    fileTree: FileEntry | null;
    projectRoot: string;
    openTabs: EditorTab[];
    activeTabId: string | null;
    closedTabs: EditorTab[];  // Ctrl+Shift+T 恢复
    autoSaveDelay: number;  // ms，0=禁用

    setFileTree: (tree: FileEntry | null) => void;
    setProjectRoot: (root: string) => void;
    openFile: (tab: EditorTab) => void;
    closeTab: (tabId: string) => void;
    restoreClosedTab: () => void;
    setActiveTab: (tabId: string) => void;
    updateTabContent: (tabId: string, content: string) => void;
    setAutoSaveDelay: (delay: number) => void;
}

export const useEditorStore = create<EditorState>((set) => ({
    fileTree: null,
    projectRoot: '',
    openTabs: [],
    activeTabId: null,
    closedTabs: [],
    autoSaveDelay: 0,

    setFileTree: (tree) => set({ fileTree: tree }),
    setProjectRoot: (root) => set({ projectRoot: root }),
    openFile: (tab) => set((s) => {
        const exists = s.openTabs.find((t) => t.id === tab.id);
        if (exists) return { activeTabId: tab.id };
        return { openTabs: [...s.openTabs, tab], activeTabId: tab.id };
    }),
    closeTab: (tabId) => set((s) => {
        const closed = s.openTabs.find((t) => t.id === tabId);
        const newTabs = s.openTabs.filter((t) => t.id !== tabId);
        const activeId = s.activeTabId === tabId
            ? (newTabs[newTabs.length - 1]?.id ?? null)
            : s.activeTabId;
        const newClosed = closed
            ? [...s.closedTabs.slice(-19), closed]
            : s.closedTabs;
        return { openTabs: newTabs, activeTabId: activeId, closedTabs: newClosed };
    }),
    restoreClosedTab: () => set((s) => {
        if (s.closedTabs.length === 0) return {};
        const restored = s.closedTabs[s.closedTabs.length - 1];
        const tabs = [...s.closedTabs.slice(0, -1)];
        const exists = s.openTabs.find((t) => t.id === restored.id);
        if (exists) return { closedTabs: tabs };
        return {
            openTabs: [...s.openTabs, restored],
            activeTabId: restored.id,
            closedTabs: tabs,
        };
    }),
    setActiveTab: (tabId) => set({ activeTabId: tabId }),
    updateTabContent: (tabId, content) => set((s) => ({
        openTabs: s.openTabs.map((t) =>
            t.id === tabId ? { ...t, content, isDirty: true } : t,
        ),
    })),
    setAutoSaveDelay: (delay) => set({ autoSaveDelay: delay }),
}));
